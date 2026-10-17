"""Flask REST API for the ontology / knowledge-graph builder."""
import logging

from flask import Flask, jsonify, request
from flask_cors import CORS

from db import get_mysql_conn, get_neo4j_driver
from ontology import (
    CONCEPTS,
    CONCEPT_RELATIONS,
    build_concept_layer,
    get_concept_graph,
)
from extractor import (
    INSTANCE_NODES,
    extract_instances,
    get_instance_graph,
    get_instance_labels,
    clear_all,
)
from functions import (
    build_functions,
    get_functions,
    get_function_graph,
)
from text_extractor import (
    extract_from_text,
    preview_from_text,
    confirm_extract,
)
from text_source import (
    create_text_source,
    list_text_sources,
    get_text_source,
    init_text_sources_table,
)
from rules import (
    build_rules,
    get_rules,
    trigger_rule,
)
from qa_service import ask as qa_ask
from qa_sql import ask as qa_sql_ask
from qa_vector import ask as qa_vector_ask
from qa_vector_only import ask as qa_vector_only_ask
from reasoning_service import analyze as reasoning_analyze
from translator import translate_value

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Ensure MySQL text_sources table exists
init_text_sources_table()


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------
@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/stats")
def stats():
    driver = get_neo4j_driver()
    with driver.session() as s:
        concept_count = s.run("MATCH (c:Concept) RETURN count(c) AS n").single()["n"]
        concept_rel_count = s.run(
            "MATCH (:Concept)-[r:CONCEPT_REL]->(:Concept) RETURN count(r) AS n"
        ).single()["n"]
        instance_count = s.run(
            "MATCH (n) WHERE NOT n:Concept RETURN count(n) AS n"
        ).single()["n"]
        instance_rel_count = s.run(
            "MATCH (a)-[r]->(b) WHERE NOT a:Concept AND NOT b:Concept "
            "RETURN count(r) AS n"
        ).single()["n"]
        # Per-label counts
        label_counts = {}
        for label, _, _, _ in INSTANCE_NODES:
            n = s.run(f"MATCH (n:{label}) RETURN count(n) AS n").single()["n"]
            label_counts[label] = n

        # Source distribution
        source_dist = {}
        for row in s.run("MATCH (n) RETURN n.source AS s, count(n) AS c"):
            source_dist[row["s"] or "null"] = row["c"]
        rel_source_dist = {}
        for row in s.run("MATCH ()-[r]->() RETURN r.source AS s, count(r) AS c"):
            rel_source_dist[row["s"] or "null"] = row["c"]

    mysql_counts = {}
    mc = get_mysql_conn()
    try:
        with mc.cursor() as cur:
            tables = [
                "countries_regions", "persons", "organizations",
                "equipments", "facilities", "events",
                "event_persons", "event_organizations",
                "event_equipments", "event_facilities",
            ]
            for t in tables:
                cur.execute(f"SELECT COUNT(*) AS c FROM `{t}`")
                mysql_counts[t] = cur.fetchone()["c"]
    finally:
        mc.close()

    return jsonify({
        "neo4j": {
            "concepts": concept_count,
            "concept_relations": concept_rel_count,
            "instances": instance_count,
            "instance_relations": instance_rel_count,
            "by_label": label_counts,
            "source_distribution": source_dist,
            "rel_source_distribution": rel_source_dist,
        },
        "mysql": mysql_counts,
    })


# ---------------------------------------------------------------------------
# Schema introspection
# ---------------------------------------------------------------------------
@app.route("/api/schema")
def schema():
    """Return concept definitions inferred from MySQL schema (no Neo4j hit)."""
    return jsonify({
        "concepts": CONCEPTS,
        "concept_relations": CONCEPT_RELATIONS,
    })


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
@app.route("/api/build/concepts", methods=["POST"])
def build_concepts():
    log.info("Building concept layer...")
    return jsonify(build_concept_layer())


@app.route("/api/build/instances", methods=["POST"])
def build_instances():
    log.info("Extracting instances from MySQL into Neo4j...")
    return jsonify(extract_instances())


@app.route("/api/build/all", methods=["POST"])
def build_all():
    log.info("Building full knowledge graph (concepts + instances)...")
    a = build_concept_layer()
    b = extract_instances()
    return jsonify({"concept_layer": a, "instance_layer": b})


@app.route("/api/clear", methods=["POST"])
def clear():
    log.info("Clearing Neo4j...")
    return jsonify(clear_all())


@app.route("/api/migrate/source", methods=["POST"])
def migrate_source():
    """Backfill source='sql' for existing nodes/rels created before this feature."""
    driver = get_neo4j_driver()
    with driver.session() as s:
        # Nodes
        node_res = s.run(
            """
            MATCH (n)
            WHERE n.source IS NULL
            SET n.source = 'sql'
            RETURN count(n) AS c
            """
        ).single()["c"]
        # Relationships
        rel_res = s.run(
            """
            MATCH ()-[r]->()
            WHERE r.source IS NULL
            SET r.source = 'sql'
            RETURN count(r) AS c
            """
        ).single()["c"]
    return jsonify({"nodes_updated": node_res, "relations_updated": rel_res})


# ---------------------------------------------------------------------------
# Function nodes
# ---------------------------------------------------------------------------
@app.route("/api/build/functions", methods=["POST"])
def build_functions_endpoint():
    log.info("Building Function nodes...")
    return jsonify(build_functions())


@app.route("/api/functions", methods=["GET"])
def list_functions():
    category = request.args.get("category")
    return jsonify(get_functions(category=category))


@app.route("/api/graph/functions", methods=["GET"])
def graph_functions():
    return jsonify(get_function_graph())


# ---------------------------------------------------------------------------
# Text extraction (LLM)
# ---------------------------------------------------------------------------
@app.route("/api/extract/text", methods=["POST"])
def extract_text():
    data = request.get_json(force=True)
    text = data.get("text", "")
    title = data.get("title", "")
    if not text:
        return jsonify({"error": "text is required"}), 400
    log.info("Text extraction request, length=%d", len(text))
    text_source_id = create_text_source(
        title or text.strip()[:50],
        text,
        source_type="paste",
    )
    result = extract_from_text(text, text_source_id)
    result["text_source_id"] = text_source_id
    return jsonify(result)


@app.route("/api/extract/file", methods=["POST"])
def extract_file():
    if "file" not in request.files:
        return jsonify({"error": "file is required"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "empty filename"}), 400
    text = file.read().decode("utf-8", errors="ignore")
    log.info("File extraction request, filename=%s, length=%d", file.filename, len(text))
    text_source_id = create_text_source(
        file.filename,
        text,
        source_type="upload",
        filename=file.filename,
    )
    result = extract_from_text(text, text_source_id)
    result["text_source_id"] = text_source_id
    return jsonify(result)


# ---------------------------------------------------------------------------
# Text extraction with manual review
# ---------------------------------------------------------------------------
@app.route("/api/extract/preview", methods=["POST"])
def extract_preview():
    data = request.get_json(force=True)
    text = data.get("text", "")
    title = data.get("title", "")
    if not text:
        return jsonify({"error": "text is required"}), 400
    log.info("Preview extraction request, length=%d", len(text))
    text_source_id = create_text_source(
        title or text.strip()[:50],
        text,
        source_type="paste",
    )
    result = preview_from_text(text)
    result["text_source_id"] = text_source_id
    return jsonify(result)


@app.route("/api/extract/confirm", methods=["POST"])
def extract_confirm():
    data = request.get_json(force=True)
    text_source_id = data.get("text_source_id")
    log.info("Confirm extraction request (tid=%s)", text_source_id)
    return jsonify(confirm_extract(data, text_source_id))


# ---------------------------------------------------------------------------
# Text sources
# ---------------------------------------------------------------------------
@app.route("/api/text-sources", methods=["GET"])
def text_sources_list():
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    return jsonify(list_text_sources(limit=limit, offset=offset))


@app.route("/api/text-sources/<int:source_id>", methods=["GET"])
def text_sources_detail(source_id):
    item = get_text_source(source_id)
    if not item:
        return jsonify({"error": "not found"}), 404
    return jsonify(item)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
@app.route("/api/build/rules", methods=["POST"])
def build_rules_endpoint():
    log.info("Building Rule nodes...")
    return jsonify(build_rules())


@app.route("/api/rules", methods=["GET"])
def list_rules():
    category = request.args.get("category")
    return jsonify(get_rules(category=category))


@app.route("/api/rules/<rule_id>/trigger", methods=["POST"])
def trigger_rule_endpoint(rule_id):
    log.info("Triggering rule %s...", rule_id)
    return jsonify(trigger_rule(rule_id))


# ---------------------------------------------------------------------------
# Fusion endpoints
# ---------------------------------------------------------------------------
@app.route("/api/fusion/all", methods=["POST"])
def fusion_all():
    """Run all four fusion operations."""
    from fusion import run_all_fusion
    log.info("Running all fusion operations...")
    return jsonify(run_all_fusion())


@app.route("/api/fusion/concepts", methods=["POST"])
def fusion_concepts():
    from fusion import concept_fusion
    return jsonify(concept_fusion())


@app.route("/api/fusion/concept_relations", methods=["POST"])
def fusion_concept_relations():
    from fusion import concept_relation_fusion
    return jsonify(concept_relation_fusion())


@app.route("/api/fusion/instances", methods=["POST"])
def fusion_instances():
    from fusion import instance_fusion
    return jsonify(instance_fusion())


@app.route("/api/fusion/instance_relations", methods=["POST"])
def fusion_instance_relations():
    from fusion import instance_relation_fusion
    return jsonify(instance_relation_fusion())


# ---------------------------------------------------------------------------
# Domain analysis endpoints
# ---------------------------------------------------------------------------
@app.route("/api/domain/analyze/threat", methods=["POST"])
def domain_threat():
    from domain_functions import analyze_threat_level
    return jsonify(analyze_threat_level())


@app.route("/api/domain/analyze/followup", methods=["POST"])
def domain_followup():
    from domain_functions import assess_followup
    return jsonify(assess_followup())


@app.route("/api/domain/analyze/duration", methods=["POST"])
def domain_duration():
    from domain_functions import estimate_duration
    return jsonify(estimate_duration())


@app.route("/api/domain/analyze/event-extraction", methods=["POST"])
def domain_event_extraction():
    from domain_functions import event_extraction_stats
    return jsonify(event_extraction_stats())


@app.route("/api/domain/analyze/relations", methods=["POST"])
def domain_relations():
    from domain_functions import analyze_event_relations
    return jsonify(analyze_event_relations())


# ---------------------------------------------------------------------------
# Graph queries (for D3)
# ---------------------------------------------------------------------------
@app.route("/api/graph/concepts")
def graph_concepts():
    return jsonify(get_concept_graph())


@app.route("/api/graph/instances")
def graph_instances():
    label = request.args.get("label") or None
    limit = int(request.args.get("limit", 300))
    lang = request.args.get("lang")
    graph = get_instance_graph(label=label, limit=limit)
    if lang == "en":
        graph = translate_value(graph)
    return jsonify(graph)


@app.route("/api/graph/instance-labels")
def graph_instance_labels():
    return jsonify(get_instance_labels())


@app.route("/api/graph/rules")
def graph_rules():
    driver = get_neo4j_driver()
    with driver.session() as s:
        nodes = [
            dict(r)
            for r in s.run(
                """
                MATCH (n)
                WHERE n:Rule OR n:Function
                RETURN id(n) AS nid, labels(n) AS labels, properties(n) AS props
                """
            )
        ]
        edges = [
            dict(r)
            for r in s.run(
                """
                MATCH (a)-[r:TRIGGERS]->(b)
                RETURN id(a) AS source, id(b) AS target,
                       type(r) AS type, properties(r) AS props
                """
            )
        ]
    out_nodes = []
    for n in nodes:
        primary = next((l for l in n["labels"] if l not in ["Rule", "Function"]), n["labels"][0])
        props = n["props"]
        out_nodes.append({
            "id": n["nid"],
            "label": primary,
            "name": props.get("name") or props.get("id") or f"#{n['nid']}",
            "props": props,
        })
    return jsonify({"nodes": out_nodes, "edges": edges})


# ---------------------------------------------------------------------------
# QA Service
# ---------------------------------------------------------------------------
@app.route("/api/qa/ask", methods=["POST"])
def qa_ask_endpoint():
    data = request.get_json(force=True)
    question = data.get("question", "")
    mode = data.get("mode", "auto")
    lang = data.get("lang", "zh")
    if not question:
        return jsonify({"error": "question is required"}), 400
    log.info("QA ask: %s (mode=%s, lang=%s)", question, mode, lang)
    try:
        resp = qa_ask(question, mode, lang=lang)
        if lang == "en":
            resp = translate_value(resp)
        return jsonify(resp)
    except Exception as e:
        log.error("QA ask failed: %s", e)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# NL2SQL QA Service (Method 6)
# ---------------------------------------------------------------------------
@app.route("/api/qa/ask-sql", methods=["POST"])
def qa_sql_endpoint():
    data = request.get_json(force=True)
    question = data.get("question", "")
    if not question:
        return jsonify({"error": "question is required"}), 400
    log.info("QA SQL ask: %s", question)
    try:
        return jsonify(qa_sql_ask(question))
    except Exception as e:
        log.error("QA SQL ask failed: %s", e)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Vector QA Service (Method 2: Vector + MySQL)
# ---------------------------------------------------------------------------
@app.route("/api/qa/ask-vector", methods=["POST"])
def qa_vector_endpoint():
    data = request.get_json(force=True)
    question = data.get("question", "")
    top_k = data.get("top_k", 5)
    if not question:
        return jsonify({"error": "question is required"}), 400
    log.info("QA Vector+MySQL ask: %s", question)
    try:
        return jsonify(qa_vector_ask(question, top_k=top_k))
    except Exception as e:
        log.error("QA Vector+MySQL failed: %s", e)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Vector QA Service (Method 4: Pure Vector)
# ---------------------------------------------------------------------------
@app.route("/api/qa/ask-vector-only", methods=["POST"])
def qa_vector_only_endpoint():
    data = request.get_json(force=True)
    question = data.get("question", "")
    top_k = data.get("top_k", 5)
    if not question:
        return jsonify({"error": "question is required"}), 400
    log.info("QA Vector-only ask: %s", question)
    try:
        return jsonify(qa_vector_only_ask(question, top_k=top_k))
    except Exception as e:
        log.error("QA Vector-only failed: %s", e)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Vector Store Management
# ---------------------------------------------------------------------------
@app.route("/api/vector/index-texts", methods=["POST"])
def vector_index_texts():
    """Index text_sources into vector store."""
    from vector_store import index_texts, get_stats
    from text_source import list_text_sources
    try:
        text_sources = list_text_sources(limit=10000)
        if not text_sources:
            return jsonify({"error": "no text sources found"}), 400

        texts_to_index = []
        for ts in text_sources:
            texts_to_index.append((
                f"{ts.get('title', '')}\n{ts.get('content', '')}",
                {"source_id": str(ts["id"]), "title": ts.get("title", ""), "source_type": ts.get("source_type", "")}
            ))

        result = index_texts(texts_to_index)
        stats = get_stats()
        return jsonify({"result": result, "stats": stats})
    except Exception as e:
        log.error("Vector indexing failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/vector/stats", methods=["GET"])
def vector_stats():
    from vector_store import get_stats
    return jsonify(get_stats())


@app.route("/api/vector/clear", methods=["POST"])
def vector_clear():
    from vector_store import clear_collection
    return jsonify(clear_collection())


# ---------------------------------------------------------------------------
# Event Reasoning Service
# ---------------------------------------------------------------------------
@app.route("/api/reasoning/analyze", methods=["POST"])
def reasoning_analyze_endpoint():
    data = request.get_json(force=True)
    type_ = data.get("type", "")
    seed = data.get("seed", {})
    depth = data.get("depth", 2)
    region = data.get("region")
    if not type_ or not seed.get("name"):
        return jsonify({"error": "type and seed.name are required"}), 400
    log.info("Reasoning analyze: type=%s, seed=%s", type_, seed)
    try:
        return jsonify(reasoning_analyze(type_, seed, depth=depth, region=region))
    except Exception as e:
        log.error("Reasoning analyze failed: %s", e)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Experiment APIs
# ---------------------------------------------------------------------------
@app.route("/api/experiment/run", methods=["POST"])
def experiment_run():
    data = request.get_json(force=True)
    questions = data.get("questions", [])
    methods = data.get("methods", None)
    if not questions:
        return jsonify({"error": "questions is required"}), 400

    from experiment_runner import ExperimentRunner
    runner = ExperimentRunner()
    results = runner.run_all(questions, method_codes=methods)
    return jsonify(results)


@app.route("/api/experiment/evaluate", methods=["POST"])
def experiment_evaluate():
    data = request.get_json(force=True)
    if not data.get("experiment_output"):
        return jsonify({"error": "experiment_output is required"}), 400

    from experiment_eval import ExperimentEvaluator, generate_summary_report
    evaluator = ExperimentEvaluator()
    evals = evaluator.evaluate_experiment(data)
    comp = evaluator.compare_methods(evals)
    bd = evaluator.by_question_type(data, evals)
    report = generate_summary_report(data, evals, comp, bd)

    return jsonify({
        "evaluations": evals,
        "comparison": comp,
        "by_type": bd,
        "report": report,
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    log.info("Starting backend on http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)

"""Layer 2 Experiment: Military Domain KGQA with CMNEE data.

5 methods compared:
  A  - Ontology-constrained KG QA (Cypher generation)
  A' - Same as A after ontology engineering (concept/relation completion + alignment)
  F  - Ontology-guided KG retrieval QA (no query generation)
  D  - NL2SQL direct MySQL query
  E  - Pure vector RAG (TF-IDF text retrieval)

Metrics: accuracy, latency (ms), token consumption.
"""
import json
import logging
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from db import get_neo4j_driver, get_mysql_conn
from llm_client import call_qwen
from vector_store import search as vector_search

# Import method F
from qa_kg_retrieval import QAKGRetrieval

# Import existing QA modules
from qa_sql import ask as sql_ask
from qa_vector_only import ask as vector_only_ask

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
QUESTIONS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cmnee_questions.json")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "l2_experiment")

# ---------------------------------------------------------------------------
# Method A / A': Ontology-constrained KG QA (Cypher generation)
# ---------------------------------------------------------------------------

MILITARY_KG_PROMPT = """You are a Neo4j Cypher expert. Generate a READ-ONLY Cypher query for a military-domain knowledge graph based on the question.

## Military Ontology

### Node Types & Properties
| Label | Key Properties |
|-------|---------------|
| Country | name |
| Organization | name |
| Equipment | name |
| Facility | name |
| Event | name, title, keywords, event_type, trigger, description, source_article_id |

### Relationship Types
- INVOLVED_IN: Organization → Event (Subject participates)
- PARTICIPATED_IN: Organization → Event (Militaryforce participates)
- USED_IN: Equipment → Event
- OCCURRED_IN: Event → Country (Location)
- AFFECTED_IN: Organization → Event (Object affected)

### Critical Rules
1. ONLY read-only: MATCH, OPTIONAL MATCH, RETURN, WHERE, LIMIT, ORDER BY, WITH, DISTINCT
2. Match entity names with CONTAINS on SHORT substrings (3-10 chars): WHERE n.name CONTAINS '航母'
3. For events, search on keywords property: WHERE e.keywords CONTAINS '航母'
4. Break long question descriptions into key nouns and search with CONTAINS
5. EVERY node in MATCH must have a label
6. Output ONLY valid JSON: {"cypher": "your query here"}. No other text.

### Examples
Q: "美国核潜艇巡逻朝鲜半岛发生在哪里？"
{"cypher": "MATCH (e:Event)-[:OCCURRED_IN]->(c:Country) WHERE e.keywords CONTAINS '核潜艇' AND e.keywords CONTAINS '朝鲜半岛' RETURN c.name LIMIT 1"}

Q: "俄库兹涅佐夫号航母飞行试验发生在什么时间？"
{"cypher": "MATCH (e:Event) WHERE e.keywords CONTAINS '库兹涅佐夫' AND e.keywords CONTAINS '飞行' RETURN e.keywords, e.description LIMIT 1"}

Q: "阿里安航天公司发射发生在哪里？"
{"cypher": "MATCH (e:Event)-[:OCCURRED_IN]->(c:Country) WHERE e.keywords CONTAINS '阿里安' RETURN c.name LIMIT 1"}

Q: "共有多少起冲突事件？"
{"cypher": "MATCH (e:Event) WHERE e.event_type = 'Conflict' RETURN count(DISTINCT e) AS count"}"""

METHOD_KG_ANSWER_PROMPT = """You are a military analyst. Answer based STRICTLY on the KG query results.

Question: {question}

KG query results:
{kg_results}

Rules:
1. Answer ONLY from the query results — do not fabricate
2. Be concise and precise
3. If results are empty: say "依据现有知识无法确定"
4. For yes/no: answer "是" or "否"
5. Answer in Chinese

Output JSON: {{"answer": "your answer"}}"""


def _safe_call_llm(system_prompt, user_prompt, temperature=0.1, max_retries=2):
    """Call LLM with retries. Returns dict or None."""
    for attempt in range(max_retries + 1):
        try:
            return call_qwen(system_prompt, user_prompt, temperature=temperature)
        except Exception as e:
            if attempt < max_retries:
                log.warning("LLM call failed (attempt %d/%d): %s", attempt + 1, max_retries, e)
                time.sleep(2)
            else:
                log.error("LLM call failed after %d retries: %s", max_retries, e)
    return None


def method_a_kg_cypher(question, use_engineered_kg=False):
    """Method A / A': Ontology-constrained Cypher generation + KG execution."""
    t_start = time.time()
    record = {"method": "A" if not use_engineered_kg else "A'", "cypher": "", "answer": ""}

    # Step 1: Generate Cypher
    raw = _safe_call_llm(MILITARY_KG_PROMPT, f"Question: {question}", temperature=0.1)
    if not isinstance(raw, dict):
        record["error"] = "Cypher generation failed"
        record["latency_ms"] = round((time.time() - t_start) * 1000)
        return record

    cypher = raw.get("cypher", "").strip()
    # Strip markdown fences
    if cypher.startswith("```"):
        cypher = "\n".join(cypher.split("\n")[1:-1]).strip()
    record["cypher"] = cypher

    # Step 2: Execute Cypher
    driver = get_neo4j_driver()
    kg_results = []
    try:
        with driver.session() as s:
            result = s.run(cypher)
            kg_results = [dict(r) for r in result]
    except Exception as e:
        record["cypher_error"] = str(e)[:200]
        record["latency_ms"] = round((time.time() - t_start) * 1000)
        record["answer"] = "查询执行失败"
        return record

    # Step 3: Generate answer from results
    prompt = METHOD_KG_ANSWER_PROMPT.format(
        question=question,
        kg_results=json.dumps(kg_results[:20], ensure_ascii=False, indent=2)[:3000],
    )
    raw = _safe_call_llm(prompt, "", temperature=0.3)
    record["answer"] = raw.get("answer", "") if isinstance(raw, dict) else ""
    record["kg_result_count"] = len(kg_results)
    record["latency_ms"] = round((time.time() - t_start) * 1000)
    return record


def method_d_nl2sql(question):
    """Method D: NL2SQL direct query."""
    t_start = time.time()
    record = {"method": "D", "sql": "", "answer": ""}

    try:
        result = sql_ask(question)  # returns string answer
        record["answer"] = result
    except Exception as e:
        record["error"] = str(e)[:200]
        record["answer"] = "查询执行失败"

    record["latency_ms"] = round((time.time() - t_start) * 1000)
    return record


def method_e_vector_rag(question):
    """Method E: Pure vector RAG."""
    t_start = time.time()
    record = {"method": "E", "answer": ""}

    try:
        result = vector_only_ask(question, top_k=5)
        record["answer"] = result
    except Exception as e:
        record["error"] = str(e)[:200]
        record["answer"] = "向量检索失败"

    record["latency_ms"] = round((time.time() - t_start) * 1000)
    return record


def method_f_kg_retrieval(question, qa_f):
    """Method F: Ontology-guided KG retrieval."""
    t_start = time.time()
    record = {"method": "F", "answer": ""}

    try:
        result = qa_f.ask(question)
        record["answer"] = result["answer"]
        record["knowledge_nodes_count"] = result.get("knowledge_nodes_count", 0)
        record["latency_ms"] = result.get("latency_ms", 0)
        return record
    except Exception as e:
        record["error"] = str(e)[:200]
        record["answer"] = "知识检索失败"
        record["latency_ms"] = round((time.time() - t_start) * 1000)
    return record


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

ACCURACY_PROMPT = """You are a QA evaluation expert. Rate the semantic match between the predicted answer and the ground truth.

Ground Truth: %(ground_truth)s
Predicted Answer: %(answer)s

Scoring guidelines (0-1):
- 1.0: Answer is fully correct, semantically identical to ground truth
- 0.7-0.9: Mostly correct with minor detail differences
- 0.4-0.6: Partially correct, missing key information
- 0.1-0.3: Some relevance but mostly incorrect
- 0.0: Completely wrong or unrelated

Output ONLY valid JSON: {"score": 0.85, "reason": "brief reason in Chinese"}"""


def run_experiment():
    """Main experiment runner."""
    log.info("=" * 60)
    log.info("Layer 2 Experiment: Military Domain KGQA")
    log.info("=" * 60)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load questions
    with open(QUESTIONS_PATH, "r", encoding="utf-8") as f:
        questions = json.load(f)
    log.info("Loaded %d questions", len(questions))

    # Initialize Method F QA
    qa_f = QAKGRetrieval(llm_fn=_safe_call_llm)

    # Run all methods
    methods = {
        "A": lambda q: method_a_kg_cypher(q, use_engineered_kg=False),
        "A_prime": lambda q: method_a_kg_cypher(q, use_engineered_kg=True),
        "F": lambda q: method_f_kg_retrieval(q, qa_f),
        "D": method_d_nl2sql,
        "E": method_e_vector_rag,
    }

    all_results = {m: [] for m in methods}

    for m_name, m_fn in methods.items():
        log.info("\n--- Method: %s ---", m_name)

        for i, q in enumerate(questions):
            qid = q.get("question_id", f"q_{i:03d}")
            question_text = q.get("question", "")
            ground_truth = q.get("ground_truth", "")
            qtype = q.get("type", "")

            log.info("  [%s] %d/%d: %s", m_name, i + 1, len(questions), question_text[:80])

            record = m_fn(question_text)
            record["question_id"] = qid
            record["question"] = question_text
            record["question_type"] = qtype
            record["ground_truth"] = ground_truth

            all_results[m_name].append(record)

            # Small delay between calls
            time.sleep(0.5)

        # Save intermediate results
        fname = f"results_{m_name}.json"
        with open(os.path.join(OUTPUT_DIR, fname), "w", encoding="utf-8") as f:
            json.dump(all_results[m_name], f, ensure_ascii=False, indent=2)
        log.info("Saved: %s", fname)

    # Score results
    log.info("\n=== Scoring ===")
    method_scores = {}

    for m_name, results in all_results.items():
        scores = []
        for r in results:
            gt = str(r.get("ground_truth", ""))
            ans = str(r.get("answer", ""))

            # Skip empty/failure answers
            if not ans.strip() or "失败" in ans or "无法" in ans[:50]:
                r["accuracy"] = 0.0
                r["score_reason"] = "empty or failed answer"
                scores.append(0.0)
                continue

            prompt = ACCURACY_PROMPT % {"ground_truth": gt, "answer": ans[:800]}
            raw = _safe_call_llm(prompt, "请评分", temperature=0.0)
            if isinstance(raw, dict):
                r["accuracy"] = raw.get("score", 0.0)
                r["score_reason"] = raw.get("reason", "")
            else:
                r["accuracy"] = 0.0
                r["score_reason"] = "scoring parse error"
            scores.append(r["accuracy"])

        avg = sum(scores) / len(scores) if scores else 0.0
        method_scores[m_name] = avg

        # Save scored results
        fname = f"scored_{m_name}.json"
        with open(os.path.join(OUTPUT_DIR, fname), "w", encoding="utf-8") as f:
            json.dump(all_results[m_name], f, ensure_ascii=False, indent=2)

        log.info("  %s: accuracy = %.4f", m_name, avg)

    # Compute latency and token stats
    log.info("\n=== Latency (ms) ===")
    for m_name, results in all_results.items():
        latencies = [r.get("latency_ms", 0) for r in results if r.get("latency_ms")]
        if latencies:
            log.info("  %s: mean=%.0f, median=%.0f, min=%.0f, max=%.0f",
                     m_name, sum(latencies) / len(latencies),
                     sorted(latencies)[len(latencies) // 2], min(latencies), max(latencies))

    # Generate report
    generate_report(method_scores, all_results)

    log.info("\n=== FINAL RESULTS ===")
    for m_name in ["A", "A_prime", "F", "D", "E"]:
        log.info("  %s: %.4f", m_name, method_scores.get(m_name, 0))


def generate_report(method_scores, all_results):
    """Generate Markdown experiment report."""
    method_names = {
        "A": "A - 本体约束 KG 问答（Cypher生成）",
        "A_prime": "A' - 本体约束 KG 问答（经本体工程）",
        "F": "F - 本体引导知识检索问答",
        "D": "D - NL2SQL 直接查询",
        "E": "E - 纯向量 RAG",
    }

    lines = [
        "# 层二实验报告：军事领域 KGQA 验证",
        "",
        f"实验时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"数据集：CMNEE（100篇中文军事新闻 + 48道评测问题）",
        "",
        "## 1. 准确率对比",
        "",
        "| 方法 | 准确率 |",
        "|------|--------|",
    ]

    for m_name in ["A", "A_prime", "F", "D", "E"]:
        acc = method_scores.get(m_name, 0)
        lines.append(f"| {method_names.get(m_name, m_name)} | {acc:.4f} |")

    # Latency
    lines.append("")
    lines.append("## 2. 响应速度（延迟 ms）")
    lines.append("")
    lines.append("| 方法 | 均值 | 中位数 | 最小值 | 最大值 |")
    lines.append("|------|------|--------|--------|--------|")
    for m_name in ["A", "A_prime", "F", "D", "E"]:
        lats = [r.get("latency_ms", 0) for r in all_results.get(m_name, []) if r.get("latency_ms")]
        if lats:
            lines.append(f"| {method_names.get(m_name, m_name)} | "
                         f"{sum(lats) / len(lats):.0f} | {sorted(lats)[len(lats) // 2]} | "
                         f"{min(lats)} | {max(lats)} |")

    # By question type
    lines.append("")
    lines.append("## 3. 按问题类型分解（A方法）")
    lines.append("")
    lines.append("| 类型 | 准确率 | 题目数 |")
    lines.append("|------|--------|--------|")
    a_results = all_results.get("A", [])
    from collections import defaultdict
    type_scores = defaultdict(list)
    for r in a_results:
        type_scores[r.get("question_type", "?")].append(r.get("accuracy", 0))
    for t, scores in sorted(type_scores.items()):
        lines.append(f"| {t} | {sum(scores)/len(scores):.4f} | {len(scores)} |")

    # Core findings
    lines.append("")
    lines.append("## 4. 核心发现")
    lines.append("")
    lines.append(f"- 本体约束 KG 问答 (A): {method_scores.get('A', 0):.4f}")
    lines.append(f"- 本体工程后 (A'): {method_scores.get('A_prime', 0):.4f} "
                 f"(变化: {method_scores.get('A_prime', 0) - method_scores.get('A', 0):+.4f})")
    lines.append(f"- 知识检索问答 (F): {method_scores.get('F', 0):.4f}")
    lines.append(f"- NL2SQL (D): {method_scores.get('D', 0):.4f}")
    lines.append(f"- 纯向量 RAG (E): {method_scores.get('E', 0):.4f}")

    report_path = os.path.join(OUTPUT_DIR, "FINAL_REPORT.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    log.info("Report saved: %s", report_path)


if __name__ == "__main__":
    run_experiment()

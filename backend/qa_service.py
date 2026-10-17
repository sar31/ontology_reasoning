"""QA Service over Knowledge Graph: NL2Cypher + Subgraph-enhanced RAG."""
import json
import logging
import re

from db import get_neo4j_driver
from llm_client import call_qwen
from ontology import CONCEPTS, CONCEPT_RELATIONS
from extractor import INSTANCE_NODES

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema introspection helpers
# ---------------------------------------------------------------------------

def _build_schema_text():
    """Build a text description of the graph schema for LLM prompts."""
    lines = ["=== Concept Layer (Schema) ==="]
    for c in CONCEPTS:
        lines.append(f"- Concept: {c['name']} ({c['label']}) from table {c['table']}")
    lines.append("\n=== Concept Relations ===")
    for r in CONCEPT_RELATIONS:
        lines.append(f"- ({r['source']})-[:{r['name']} {{label:'{r['label']}'}}]->({r['target']}) via {r['via']}")
    lines.append("\n=== Instance Node Labels ===")
    for label, table, pk, name_field in INSTANCE_NODES:
        lines.append(f"- :{label} (from MySQL table `{table}`, pk={pk}, display_field={name_field})")
    return "\n".join(lines)


_SCHEMA_TEXT = _build_schema_text()

# ---------------------------------------------------------------------------
# Question classification
# ---------------------------------------------------------------------------

CLASSIFY_PROMPT = """你是知识图谱问答系统的路由专家。请判断用户问题适合用哪种方式回答。

可选类型：
- "cypher"：问题明确，可以通过Cypher查询直接回答（如"某某参与了哪些事件？"、"有多少个国家？"）
- "open"：问题较开放，需要综合分析（如"分析一下南海局势"、"这些事件有什么关联"）

请严格按JSON输出：{"type": "cypher" 或 "open"}
不要输出任何其他内容。"""


def classify_question(question: str) -> str:
    """Return 'cypher' or 'open'."""
    try:
        raw = call_qwen(CLASSIFY_PROMPT, f"问题：{question}", temperature=0.0)
        if isinstance(raw, dict):
            return raw.get("type", "open")
    except Exception as e:
        log.warning("Question classification failed: %s", e)
    return "open"


# ---------------------------------------------------------------------------
# NL2Cypher
# ---------------------------------------------------------------------------

NL2CYPHER_PROMPT = f"""你是Neo4j Cypher查询专家。根据用户问题生成只读的Cypher查询。

图谱Schema：
{_SCHEMA_TEXT}

每个实例节点都包含以下属性（用于实体定位）：
- display_name：显示名称（中文名，主要匹配属性）
- name：名称（中文名，与display_name通常相同）
- name_en：英文名称（如"F-35 Lightning II"、 "Russian Armed Forces"等）

重要规则：
1. 只生成MATCH / OPTIONAL MATCH / RETURN / WHERE / LIMIT / ORDER BY / WITH / COUNT / COLLECT / DISTINCT语句
2. **绝对禁止** CREATE / DELETE / SET / REMOVE / MERGE / DROP / LOAD
3. 实体定位：优先匹配 display_name 属性；如果用户输入包含英文关键词，匹配 name_en 属性
4. 使用 CONTAINS 进行子串匹配，不要使用 =~ 正则匹配（正则可能因编码问题失败）
   - 正确：WHERE n.display_name CONTAINS '关键词'
   - 正确：WHERE n.name_en CONTAINS 'keyword'
   - 错误：WHERE n.name =~ '(?i).*关键词.*'
5. 限制返回数量，默认 LIMIT 20
6. 请严格按JSON输出：{{"cypher": "..."}}
7. 不要输出任何解释，只输出JSON"""


def _enhance_cypher(cypher: str) -> str:
    """Post-process LLM-generated Cypher to fix common issues.

    1. Convert regex =~ '(?i).*keyword.*' to CONTAINS 'keyword'
    2. Expand single-property searches to multi-property (name + name_en + display_name)
    """
    if not cypher:
        return cypher

    # 1. Replace regex fuzzy match with CONTAINS
    # Pattern: <alias>.<prop> =~ '(?i).*<keyword>.*'
    # Convert to: <alias>.<prop> CONTAINS '<keyword>'
    def _regex_to_contains(m):
        alias_prop = m.group(1)
        keyword = m.group(2)
        return f"{alias_prop} CONTAINS '{keyword}'"

    cypher = re.sub(
        r"(\w+\.\w+)\s*=\~\s*'\(\?i\)\.\*(.*?)\.\*'",
        _regex_to_contains,
        cypher,
    )

    # 2. Expand single-property name search to multi-property
    def _expand_search(m):
        alias = m.group(1)
        keyword = m.group(2)
        if re.search(r'[a-zA-Z]', keyword):
            return (
                f"({alias}.name CONTAINS '{keyword}' "
                f"OR {alias}.display_name CONTAINS '{keyword}' "
                f"OR {alias}.name_en CONTAINS '{keyword}')"
            )
        else:
            return f"({alias}.display_name CONTAINS '{keyword}' OR {alias}.name CONTAINS '{keyword}')"

    cypher = re.sub(
        r"(\w+)\.(?:name|display_name)\s+CONTAINS\s+'([^']+)'",
        _expand_search,
        cypher,
    )

    return cypher


def nl2cypher(question: str) -> str:
    """Convert natural language question to Cypher query via LLM."""
    raw = call_qwen(NL2CYPHER_PROMPT, f"问题：{question}", temperature=0.1)
    if isinstance(raw, dict):
        cypher = raw.get("cypher", "")
        cypher = _sanitize_cypher(cypher)
        if cypher:
            cypher = _enhance_cypher(cypher)
            log.info("Enhanced cypher: %s", cypher)
        return cypher
    return ""


def _sanitize_cypher(cypher: str) -> str:
    """Strip markdown fences, block dangerous keywords, and fix common LLM mistakes."""
    cypher = cypher.strip()
    if cypher.startswith("```"):
        cypher = re.sub(r"^```\w*", "", cypher)
        cypher = re.sub(r"```$", "", cypher)
        cypher = cypher.strip()
    upper = cypher.upper()
    dangerous = ["CREATE", "DELETE", "SET", "REMOVE", "MERGE", "DROP", "LOAD", "CALL"]
    for d in dangerous:
        if re.search(rf"\b{d}\b", upper):
            log.error("Dangerous keyword '%s' detected in generated cypher. Blocking.", d)
            return ""
    return cypher


# ---------------------------------------------------------------------------
# Safe execution
# ---------------------------------------------------------------------------

def safe_execute(cypher: str) -> list:
    """Execute a read-only Cypher query safely."""
    if not cypher:
        return []
    # Double-check no dangerous keywords
    upper = cypher.upper()
    for d in ["CREATE", "DELETE", "SET", "REMOVE", "MERGE", "DROP", "LOAD"]:
        if re.search(rf"\b{d}\b", upper):
            raise ValueError(f"Blocked dangerous cypher keyword: {d}")
    driver = get_neo4j_driver()
    with driver.session() as s:
        result = s.run(cypher)
        return [dict(r) for r in result]


# ---------------------------------------------------------------------------
# Subgraph retrieval
# ---------------------------------------------------------------------------

KEYWORD_PROMPT = """从用户问题中提取用于在知识图谱中搜索实体的关键词列表。
请严格按JSON输出：{"keywords": ["keyword1", "keyword2"]}
只提取可能在图谱中作为实体名称出现的名词或专有名词，不要输出其他内容。"""


def _extract_keywords(question: str) -> list:
    """Extract search keywords from question via LLM."""
    try:
        raw = call_qwen(KEYWORD_PROMPT, f"问题：{question}", temperature=0.0)
        if isinstance(raw, dict):
            return raw.get("keywords", [])
    except Exception as e:
        log.warning("Keyword extraction failed: %s", e)
    # Fallback: simple split
    return [w for w in re.split(r"[\s，。？！；：""''（）【】]", question) if len(w) >= 2]


def retrieve_subgraph(question: str, max_nodes: int = 50) -> dict:
    """Retrieve a relevant subgraph based on keywords in the question."""
    keywords = _extract_keywords(question)
    log.info("Subgraph retrieval keywords: %s", keywords)

    driver = get_neo4j_driver()
    matched_node_ids = set()
    with driver.session() as s:
        # Phase 1: fuzzy match entities by display_name
        for kw in keywords:
            if not kw or len(kw) < 2:
                continue
            pattern = f"(?i).*{re.escape(kw)}.*"
            for rec in s.run(
                "MATCH (n) WHERE n.display_name =~ $pattern RETURN id(n) AS nid LIMIT 10",
                pattern=pattern,
            ):
                matched_node_ids.add(rec["nid"])

        if not matched_node_ids:
            # Fallback: return most recent/popular Event nodes
            for rec in s.run(
                "MATCH (n:Event) RETURN id(n) AS nid LIMIT $limit", limit=max_nodes
            ):
                matched_node_ids.add(rec["nid"])

        # Phase 2: 2-hop neighborhood expansion
        seed_ids = list(matched_node_ids)[:20]
        neighbor_ids = set(seed_ids)
        for rec in s.run(
            """
            MATCH (n)-[r]-(m)
            WHERE id(n) IN $ids
            RETURN id(n) AS nid, id(m) AS mid, id(r) AS rid, type(r) AS rtype,
                   properties(r) AS rprops, labels(m) AS mlabels, properties(m) AS mprops
            LIMIT $limit
            """,
            ids=seed_ids,
            limit=max_nodes * 3,
        ):
            neighbor_ids.add(rec["mid"])

        # Phase 3: fetch full node/edge data for the subgraph
        node_ids = list(neighbor_ids)[:max_nodes]
        nodes_raw = [
            dict(r)
            for r in s.run(
                """
                MATCH (n)
                WHERE id(n) IN $ids
                RETURN id(n) AS nid, labels(n) AS labels, properties(n) AS props
                """,
                ids=node_ids,
            )
        ]
        edges_raw = [
            dict(r)
            for r in s.run(
                """
                MATCH (a)-[r]->(b)
                WHERE id(a) IN $ids AND id(b) IN $ids
                RETURN id(a) AS source, id(b) AS target,
                       type(r) AS type, properties(r) AS props
                """,
                ids=node_ids,
            )
        ]

    nodes = []
    for n in nodes_raw:
        primary = next((l for l in n["labels"] if l != "Concept"), n["labels"][0])
        props = n["props"]
        nodes.append({
            "id": n["nid"],
            "label": primary,
            "name": (
                props.get("display_name")
                or props.get("name")
                or props.get("title")
                or props.get("full_name")
                or f"#{n['nid']}"
            ),
            "props": props,
        })

    edges = []
    for e in edges_raw:
        edges.append({
            "source": e["source"],
            "target": e["target"],
            "type": e["type"],
            "label": e["props"].get("label", e["type"]) if e["props"] else e["type"],
        })

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# Answer generation
# ---------------------------------------------------------------------------

ANSWER_PROMPT = """你是知识图谱问答助手。请基于提供的图谱数据，用中文回答用户问题。

要求：
1. 答案必须严格基于提供的查询结果或子图数据，不要编造信息
2. 如果数据不足，明确说明"根据现有图谱数据无法回答"
3. 回答应简洁、准确，必要时使用列表或表格
4. 在回答末尾列出数据来源（引用的实体名称）

请按JSON输出：{"answer": "...", "sources": ["实体A", "实体B"]}
不要输出任何其他内容。"""

ANSWER_PROMPT_EN = """You are a knowledge-graph QA assistant. Answer the user's question in English,
based on the provided graph data.

Requirements:
1. The answer must be strictly based on the provided query results or subgraph data; do not fabricate
2. If data is insufficient, clearly say "cannot be answered based on the current knowledge graph"
3. Be concise and accurate; use lists or tables where helpful
4. List data sources (the referenced entity names) at the end of the answer

Output JSON: {"answer": "...", "sources": ["EntityA", "EntityB"]}
Do not output any other text."""


def generate_answer(question: str, context: dict, mode: str, lang: str = "zh") -> dict:
    """Generate natural language answer from query results or subgraph."""
    if mode == "cypher":
        context_text = json.dumps(context.get("results", []), ensure_ascii=False, indent=2)
    else:
        context_text = json.dumps(context.get("subgraph", {}), ensure_ascii=False, indent=2)

    prompt = ANSWER_PROMPT_EN if lang == "en" else ANSWER_PROMPT
    user_prompt = f"问题：{question}\n\n图谱数据（{mode}模式）：\n{context_text[:4000]}"
    try:
        raw = call_qwen(prompt, user_prompt, temperature=0.3)
        if isinstance(raw, dict):
            return {
                "answer": raw.get("answer", ""),
                "sources": raw.get("sources", []),
            }
    except Exception as e:
        log.error("Answer generation failed: %s", e)

    # Fallback: return raw context summary
    return {
        "answer": "答案生成失败，以下为原始查询结果：\n" + context_text[:1000],
        "sources": [],
    }


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def ask(question: str, mode: str = "auto", lang: str = "zh") -> dict:
    """Main entry: classify -> route -> execute -> generate answer."""
    log.info("QA ask: question=%s, mode=%s", question, mode)
    if not question or len(question.strip()) < 2:
        return {"answer": "问题太短", "mode": "error", "sources": []}

    if mode == "auto":
        mode = classify_question(question)
        log.info("Auto-classified as: %s", mode)

    if mode == "cypher":
        cypher = nl2cypher(question)
        log.info("Generated cypher: %s", cypher)
        if not cypher:
            return {"answer": "无法生成有效查询", "mode": "cypher", "sources": []}
        try:
            results = safe_execute(cypher)
        except Exception as e:
            log.error("Cypher execution failed: %s", e)
            return {"answer": f"查询执行失败: {e}", "mode": "cypher", "cypher": cypher, "sources": []}

        answer_data = generate_answer(question, {"results": results}, "cypher", lang=lang)
        return {
            "answer": answer_data["answer"],
            "mode": "cypher",
            "cypher": cypher,
            "results": results[:20],
            "sources": answer_data.get("sources", []),
        }

    # RAG / open mode
    subgraph = retrieve_subgraph(question)
    answer_data = generate_answer(question, {"subgraph": subgraph}, "rag", lang=lang)
    return {
        "answer": answer_data["answer"],
        "mode": "rag",
        "subgraph": subgraph,
        "sources": answer_data.get("sources", []),
    }

"""Method F: Ontology-guided Knowledge Retrieval QA.

No Cypher/SQL generation. Instead:
  1. LLM parses question → entity mentions + concept types + relation hints
  2. Ontology matching determines retrieval scope (labels, relations, hops)
  3. Fuzzy name matching locates entities in Neo4j
  4. N-hop neighborhood expansion retrieves relevant knowledge
  5. Structured knowledge context + question → LLM generates answer

Key advantage: avoids Cypher syntax errors, interpretable retrieval path.
"""
import json
import logging
import re
import time

from db import get_neo4j_driver

log = logging.getLogger(__name__)

# Military ontology (from ontology.py)
MILITARY_CONCEPTS = {
    "Country": {"label": "国家/地区", "props": ["name", "name_en", "continent"]},
    "Person": {"label": "人员", "props": ["full_name", "name_en", "role", "rank_title"]},
    "Organization": {"label": "组织", "props": ["name", "name_en"]},
    "Equipment": {"label": "装备", "props": ["name", "name_en"]},
    "Facility": {"label": "设施", "props": ["name", "name_en"]},
    "Event": {"label": "事件", "props": ["title", "event_type", "start_time", "location"]},
}

MILITARY_RELATIONS = [
    "NATIONAL_OF", "BELONGS_TO", "ORIGIN_FROM", "OPERATED_BY_COUNTRY",
    "LOCATED_IN", "OCCURRED_IN", "INVOLVED_IN", "PARTICIPATED_IN",
    "USED_IN", "AFFECTED_IN",
]

QUESTION_PARSER_PROMPT = """Parse the military-domain question into structured components. Output JSON only.

Ontology:
  Concepts: Country (国家/地区), Person (人员), Organization (组织), Equipment (装备), Facility (设施), Event (事件)
  Relations: NATIONAL_OF (Person→Country), BELONGS_TO (Org→Country), ORIGIN_FROM (Equipment→Country),
             OPERATED_BY_COUNTRY (Equipment→Country), LOCATED_IN (Facility→Country), OCCURRED_IN (Event→Country),
             INVOLVED_IN (Person→Event), PARTICIPATED_IN (Org→Event), USED_IN (Equipment→Event), AFFECTED_IN (Facility→Event)

Return JSON:
{
  "entities": ["entity name 1", "entity name 2"],
  "concept_types": ["Country", "Event", ...],
  "relation_hints": ["ORIGIN_FROM", "OCCURRED_IN", ...],
  "intent": "property_lookup | relation_query | entity_list | yes_no | count | trend_analysis",
  "max_hops": 1 or 2 or 3
}

Rules:
- entities: extract exact entity names/mentions from the question
- concept_types: infer which concept types are relevant (from the 6 above)
- relation_hints: infer which relations might be relevant (from the 10 above), or empty list
- intent: classify the question type
- max_hops: 1 for direct property/relation queries, 2-3 for multi-hop"""  # noqa: E501

ANSWER_PROMPT = """You are a military intelligence analyst. Answer the question based STRICTLY on the provided knowledge.

## Ontology Context
{ontology_context}

## Retrieved Knowledge (from Knowledge Graph)
{knowledge_context}

## Question
{question}

Rules:
1. Answer ONLY from the retrieved knowledge — do NOT fabricate
2. Be concise and precise
3. If the knowledge is insufficient, say "依据现有知识无法确定"
4. For yes/no questions: answer "是" or "否"
5. For counts: return the number
6. Answer in Chinese

Output JSON: {{"answer": "your answer"}}"""


class QAKGRetrieval:
    """Ontology-guided KG retrieval QA (Method F)."""

    def __init__(self, llm_fn, driver=None):
        self.llm_fn = llm_fn
        self.driver = driver or get_neo4j_driver()
        self._build_ontology_context()

    def _build_ontology_context(self):
        """Build ontology schema text."""
        lines = ["## 军事本体概念"]
        for cname, cinfo in MILITARY_CONCEPTS.items():
            lines.append(f"- {cname} ({cinfo['label']}): {', '.join(cinfo['props'])}")
        lines.append("\n## 军事本体关系")
        for rel in MILITARY_RELATIONS:
            lines.append(f"- {rel}")
        self.ontology_text = "\n".join(lines)

    def _parse_question(self, question):
        """Step 1: LLM parses question → structured components."""
        raw = self.llm_fn(QUESTION_PARSER_PROMPT, question, temperature=0.0)
        if isinstance(raw, dict):
            return raw
        return {
            "entities": [], "concept_types": [], "relation_hints": [],
            "intent": "property_lookup", "max_hops": 1,
        }

    def _fuzzy_match_entities(self, entities, concept_types, max_hops):
        """Step 2+3: Find entities in Neo4j and retrieve neighborhood."""
        all_nodes = []
        found_ids = set()

        with self.driver.session() as s:
            for entity_name in entities:
                if not entity_name or len(entity_name) < 2:
                    continue
                # Try exact match first
                result = s.run(
                    """MATCH (n) WHERE (n.name = $name OR n.full_name = $name
                       OR n.title = $name OR n.name CONTAINS $name OR n.full_name CONTAINS $name
                       OR n.title CONTAINS $name) AND NOT n:KQA_Thing
                       RETURN n, labels(n) AS labels LIMIT 5""",
                    name=entity_name.strip(),
                )
                for record in result:
                    node = dict(record["n"])
                    node_labels = [l for l in record["labels"] if l != "Concept"]
                    nid = node.get("qid") or node.get("id") or node.get("name")
                    if nid not in found_ids:
                        node["_labels"] = node_labels
                        all_nodes.append(node)
                        found_ids.add(str(nid))

            # 1-2 hop neighborhood expansion
            if found_ids and max_hops >= 1:
                # Get relations between found nodes
                result = s.run(
                    """MATCH (a)-[r]->(b) WHERE (a.name IN $names OR a.full_name IN $names
                       OR a.title IN $names) AND NOT a:KQA_Thing AND NOT b:KQA_Thing
                       RETURN a.name AS source, type(r) AS relation, labels(b) AS target_labels,
                       b.name AS target_name, properties(b) AS target_props LIMIT 30""",
                    names=list({n.get("name", n.get("full_name", n.get("title", "")))
                                for n in all_nodes if n.get("name") or n.get("full_name")
                                or n.get("title")}),
                )
                for record in result:
                    all_nodes.append({
                        "_source": record["source"],
                        "_relation": record["relation"],
                        "_target_name": record["target_name"],
                        "_target_labels": record["target_labels"],
                        **record.get("target_props", {}),
                    })

        return all_nodes

    def _format_knowledge(self, nodes):
        """Format retrieved nodes as structured knowledge context."""
        if not nodes:
            return "（未检索到相关知识）"

        lines = []
        for i, node in enumerate(nodes[:30]):
            # Strip internal fields
            display = {k: v for k, v in node.items()
                       if not k.startswith("_") and v is not None and k != "concept_types"}
            if display:
                name = display.pop("name", display.pop("full_name", display.pop("title", f"node-{i}")))
                props_str = ", ".join(f"{k}={v}" for k, v in list(display.items())[:5])
                labels = node.get("_labels", [])
                label_str = f" ({', '.join(labels)})" if labels else ""
                lines.append(f"{name}{label_str}: {props_str}")
            elif node.get("_source"):
                # Relation edge
                lines.append(f"[{node.get('_source')}]-({node.get('_relation')})->"
                             f"[{node.get('_target_name')}]")

        if not lines:
            return "（检索到的知识节点无有效属性）"

        return "\n".join(lines)

    def ask(self, question):
        """Main entry point for Method F."""
        t_start = time.time()

        # 1. Parse question
        parsed = self._parse_question(question)
        entities = parsed.get("entities", [])
        concept_types = parsed.get("concept_types", [])
        max_hops = min(parsed.get("max_hops", 1), 3)

        # 2+3. Match + retrieve knowledge
        knowledge_nodes = self._fuzzy_match_entities(entities, concept_types, max_hops)
        knowledge_text = self._format_knowledge(knowledge_nodes)

        # 4. Generate answer
        prompt = ANSWER_PROMPT.format(
            ontology_context=self.ontology_text,
            knowledge_context=knowledge_text,
            question=question,
        )
        raw = self.llm_fn(prompt, "", temperature=0.3)
        answer = raw.get("answer", "") if isinstance(raw, dict) else str(raw)

        latency_ms = round((time.time() - t_start) * 1000)

        return {
            "answer": answer,
            "latency_ms": latency_ms,
            "parsed_entities": entities,
            "knowledge_nodes_count": len(knowledge_nodes),
        }

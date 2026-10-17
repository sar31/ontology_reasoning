"""Ontology Engineering for Method A': concept/relation completion + entity alignment.

Improves the military KG built from CMNEE annotations via:
  1. Concept补全: Identify entities missing concept labels, assign via LLM
  2. 关系补全: Derive implicit relations from ontology rules
  3. 实体对齐: Merge synonymous entities (e.g., "美方" / "美国")

Operates on the Neo4j graph built by build_cmnee_kg.py.
"""
import json
import logging
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from db import get_neo4j_driver
from llm_client import call_qwen

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SELECTED_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cmnee_selected_100.json")

# Known synonym pairs for entity alignment
SYNONYM_PAIRS = [
    ("美国", "美方"), ("中国", "中方"), ("俄罗斯", "俄方"),
    ("日本", "日方"), ("印度", "印方"), ("韩国", "韩方"),
    ("朝鲜", "朝方"), ("伊朗", "伊方"), ("乌克兰", "乌方"),
    ("美国五角大楼", "五角大楼"), ("美国国防部", "国防部"),
]

CONCEPT_COMPLETION_PROMPT = """Assign a military ontology concept type to the entity. Output JSON only.

Ontology types:
- Country (国家/地区): sovereign states, regions
- Person (人员): named individuals
- Organization (组织): military units, government agencies, companies, groups
- Equipment (装备): weapons, vehicles, aircraft, ships, missiles
- Facility (设施): military bases, installations, ports, airfields
- Event (事件): military operations, conflicts, exercises, accidents

Entity name: {entity_name}

Return JSON: {{"concept": "one of the six types above"}}"""


def concept_completion(driver):
    """Step 1: Identify entities without clear concept labels and assign via LLM."""
    with driver.session() as s:
        # Find Organization nodes that might be Persons or other types
        result = s.run(
            """MATCH (n:Organization) WHERE NOT (n)-[:INVOLVED_IN|PARTICIPATED_IN|AFFECTED_IN]->()
               AND size(n.name) <= 10 RETURN n.name LIMIT 30"""
        )
        entities_to_check = [r["n.name"] for r in result]

    log.info("Concept completion: checking %d entities", len(entities_to_check))

    reclassified = 0
    for name in entities_to_check:
        try:
            raw = call_qwen(CONCEPT_COMPLETION_PROMPT, f"Entity name: {name}", temperature=0.0)
            concept = raw.get("concept", "") if isinstance(raw, dict) else ""
            if concept in ("Person", "Equipment", "Facility") and concept != "Organization":
                # Re-label the node
                with driver.session() as s:
                    s.run(
                        f"MATCH (n:Organization {{name: '{name}'}}) "
                        f"REMOVE n:Organization SET n:{concept}"
                    )
                reclassified += 1
                log.info("  Reclassified: %s → %s", name, concept)
        except Exception as e:
            log.debug("  Skipped %s: %s", name, e)

    log.info("Reclassified %d entities", reclassified)


def relation_completion(driver):
    """Step 2: Derive implicit relations from ontology rules."""
    new_relations = 0

    # Rule: If Person/Org INVOLVED_IN Event AND Event OCCURRED_IN Country
    #       → Person/Org has NATIONAL_OF/BELONGS_TO Country
    with driver.session() as s:
        result = s.run(
            """MATCH (a)-[:INVOLVED_IN|PARTICIPATED_IN]->(e:Event)-[:OCCURRED_IN]->(c:Country)
               WHERE NOT (a)-[:NATIONAL_OF|BELONGS_TO]->(c)
               RETURN a.name AS entity, labels(a) AS labels, c.name AS country
               LIMIT 50"""
        )
        for r in result:
            entity = r["entity"]
            country = r["country"]
            labels = r["labels"]
            rel = "NATIONAL_OF" if "Person" in labels else "BELONGS_TO"

            safe_e = entity.replace("'", "\\'")
            safe_c = country.replace("'", "\\'")
            try:
                s.run(
                    f"MATCH (a {{name: '{safe_e}'}}), (c:Country {{name: '{safe_c}'}}) "
                    f"MERGE (a)-[:{rel}]->(c)"
                )
                new_relations += 1
            except Exception:
                pass

    # Rule: Equipment USED_IN Event + Event OCCURRED_IN Country → Equipment ORIGIN_FROM Country
    with driver.session() as s:
        result = s.run(
            """MATCH (eq:Equipment)-[:USED_IN]->(e:Event)-[:OCCURRED_IN]->(c:Country)
               WHERE NOT (eq)-[:ORIGIN_FROM|OPERATED_BY_COUNTRY]->(c)
               RETURN eq.name AS equipment, c.name AS country LIMIT 30"""
        )
        for r in result:
            safe_eq = r["equipment"].replace("'", "\\'")
            safe_c = r["country"].replace("'", "\\'")
            try:
                s.run(
                    f"MATCH (eq:Equipment {{name: '{safe_eq}'}}), (c:Country {{name: '{safe_c}'}}) "
                    f"MERGE (eq)-[:ORIGIN_FROM]->(c)"
                )
                new_relations += 1
            except Exception:
                pass

    log.info("Derived %d new relations", new_relations)


def entity_alignment(driver):
    """Step 3: Merge synonymous entities."""
    merged = 0

    for name_a, name_b in SYNONYM_PAIRS:
        with driver.session() as s:
            # Check both exist
            result_a = s.run(
                f"MATCH (n {{name: '{name_a}'}}) RETURN labels(n) AS labels, id(n) AS nid"
            ).data()
            result_b = s.run(
                f"MATCH (n {{name: '{name_b}'}}) RETURN labels(n) AS labels, id(n) AS nid"
            ).data()

            if not result_a or not result_b:
                continue

            a_nid = result_a[0]["nid"]
            a_labels = result_a[0]["labels"]
            b_labels = result_b[0]["labels"]

            # Same label type → merge
            if set(a_labels) & set(b_labels):
                try:
                    # Copy all relations from B → A
                    s.run(
                        f"MATCH (b {{name: '{name_b}'}})-[r]->(x) "
                        f"MATCH (a {{name: '{name_a}'}}) "
                        f"MERGE (a)-[r2:__TEMP__]->(x) "
                        f"DELETE r"
                    )
                    # Delete B
                    s.run(f"MATCH (n {{name: '{name_b}'}}) DETACH DELETE n")
                    merged += 1
                    log.info("  Merged: %s ← %s", name_a, name_b)
                except Exception as e:
                    log.debug("  Failed merge %s ← %s: %s", name_a, name_b, e)
                    # Rollback temp relations
                    s.run("MATCH ()-[r:__TEMP__]->() DELETE r")

    log.info("Merged %d entity pairs", merged)


def main():
    log.info("=" * 50)
    log.info("Ontology Engineering for Military KG")
    log.info("=" * 50)

    driver = get_neo4j_driver()

    # Show pre-engineering stats
    with driver.session() as s:
        for lbl in ["Country", "Organization", "Person", "Equipment", "Facility", "Event"]:
            cnt = s.run(f"MATCH (n:{lbl}) RETURN count(n) AS c").single()["c"]
            log.info("  Before - %s: %d", lbl, cnt)

    log.info("\n--- Concept Completion ---")
    concept_completion(driver)

    log.info("\n--- Relation Completion ---")
    relation_completion(driver)

    log.info("\n--- Entity Alignment ---")
    entity_alignment(driver)

    # Show post-engineering stats
    log.info("\n--- Post-Engineering Stats ---")
    with driver.session() as s:
        for lbl in ["Country", "Organization", "Person", "Equipment", "Facility", "Event"]:
            cnt = s.run(f"MATCH (n:{lbl}) RETURN count(n) AS c").single()["c"]
            log.info("  After - %s: %d", lbl, cnt)
        rel_cnt = s.run(
            "MATCH ()-[r]->() WHERE NOT (startNode(r):KQA_Thing OR endNode(r):KQA_Thing) "
            "RETURN count(r) AS c"
        ).single()["c"]
        log.info("  Relations: %d", rel_cnt)

    log.info("\nOntology engineering complete!")


if __name__ == "__main__":
    main()

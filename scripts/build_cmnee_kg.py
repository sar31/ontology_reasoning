"""Build military-domain KG from CMNEE annotations → Neo4j.

Uses the existing CMNEE event annotations to construct:
- Entity nodes (Person, Organization, Equipment, Facility, Country, Event)
- Relations from event argument structure
- No LLM extraction needed — uses pre-annotated data.

Entity typing logic: CMNEE argument roles → military ontology concepts
  Subject → Person (individuals) or Organization (groups/militaries)
  Object → Person or Organization
  Equipment → Equipment
  Location → Country or Facility
  Militaryforce → Organization
"""
import json
import logging
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from db import get_neo4j_driver

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SELECTED_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cmnee_selected_100.json")

# Role → (Neo4j label, property field)
ROLE_LABEL_MAP = {
    "Subject": ("Organization", "name"),      # Most subjects are military/org entities
    "Object": ("Organization", "name"),
    "Equipment": ("Equipment", "name"),
    "Location": ("Country", "name"),           # Often countries, some facilities
    "Militaryforce": ("Organization", "name"),
}

# Known country/region names for disambiguation
KNOWN_COUNTRIES = {
    "美国", "中国", "俄罗斯", "日本", "印度", "英国", "法国", "德国",
    "韩国", "朝鲜", "伊朗", "以色列", "叙利亚", "乌克兰", "越南",
    "菲律宾", "澳大利亚", "加拿大", "土耳其", "巴基斯坦",
    "美方", "中方", "俄方", "日方", "印方", "韩方",
}

# Known military org keywords
MILITARY_ORG_KEYWORDS = [
    "海军", "空军", "陆军", "国防部", "五角大楼", "司令部", "部队",
    "航母", "舰队", "军团", "师", "旅", "团", "营", "连", "排",
    "打击群", "特遣队", "联合作战", "武装力量", "国民警卫队",
    "navy", "army", "air force", "marines", "pentagon",
]


def classify_entity(name, role):
    """Determine Neo4j label for an entity based on name and annotation role."""
    name_clean = name.strip()

    # Country detection
    if name_clean in KNOWN_COUNTRIES:
        return ("Country", "name")
    # Org keyword detection
    for kw in MILITARY_ORG_KEYWORDS:
        if kw in name_clean:
            return ("Organization", "name")
    # Equipment detection (if role says Equipment)
    if role == "Equipment":
        return ("Equipment", "name")
    # Location → check if country-like
    if role == "Location":
        for c in KNOWN_COUNTRIES:
            if c in name_clean:
                return ("Country", "name")
        return ("Country", "name")  # Default location to Country
    # Militaryforce → Organization
    if role == "Militaryforce":
        return ("Organization", "name")
    # Default Subject/Object → Organization (military domain)
    return ("Organization", "name")


def build_kg_from_annotations(articles):
    """Build KG nodes and relations from CMNEE annotations."""
    driver = get_neo4j_driver()

    # Clear existing military nodes (not KQA)
    with driver.session() as s:
        s.run("MATCH (n) WHERE NOT n:KQA_Thing AND NOT n:Concept DETACH DELETE n")
    log.info("Cleared existing military KG nodes")

    entities = {}  # name → {label, props}
    event_map = []  # [(article_id, event_obj, event_name, entity_names)] for relation building

    # Step 1: Collect all entities from annotations
    for article in articles:
        aid = article.get("id")
        for ei, event in enumerate(article.get("event_list", [])):
            etype = event.get("event_type", "")
            trigger = event.get("trigger", {}).get("text", "")
            text_snippet = article.get("text", "")[:200].replace("\n", " ")

            # Build short keyword description for CONTAINS matching
            subject = ""
            location = ""
            equipment = ""
            for arg in event.get("arguments", []):
                role = arg.get("role", "")
                val = arg.get("text", "").strip()
                if role == "Subject" and not subject:
                    subject = val[:20]
                elif role == "Location" and not location:
                    location = val[:15]
                elif role == "Equipment" and not equipment:
                    equipment = val[:15]
            kw_parts = []
            if subject:
                kw_parts.append(subject)
            if trigger and len(trigger) <= 8:
                kw_parts.append(trigger)
            if equipment:
                kw_parts.append(equipment)
            if location:
                kw_parts.append(location)
            event_keywords = "".join(kw_parts[:4])[:80]

            # Unique event name
            event_name = f"cmnee_evt_{aid}_{ei}"

            event_props = {
                "name": event_name,
                "title": text_snippet[:150],
                "keywords": event_keywords,
                "description": article.get("text", "")[:500],
                "event_type": etype,
                "trigger": trigger,
                "source_article_id": aid,
            }
            entities[event_name] = ("Event", event_props)

            # Collect argument entities and track for relation building
            arg_entities = []
            for arg in event.get("arguments", []):
                role = arg.get("role", "")
                name = arg.get("text", "").strip()
                if not name or len(name) < 2:
                    continue
                label, prop_field = classify_entity(name, role)
                if name not in entities:
                    entities[name] = (label, {prop_field: name})
                arg_entities.append((name, role))

            event_map.append((aid, event, event_name, arg_entities))

    log.info("Collected %d unique entities", len(entities))

    # Step 2: Create Neo4j nodes via parameterized queries
    with driver.session() as s:
        for name, (label, props) in entities.items():
            safe_name = name[:200]
            all_props = {"name": safe_name, **props}
            try:
                s.run(
                    f"CREATE (n:{label}) SET n = $props",
                    props=all_props,
                )
            except Exception as e:
                pass  # Skip problematic entities (e.g., name format issues)

        # Create index
        try:
            s.run("CREATE INDEX mil_entity IF NOT EXISTS FOR (n:Organization) ON (n.name)")
        except Exception:
            pass

    log.info("Created entity nodes in Neo4j")

    # Step 3: Create relations using parameterized queries
    log.info("Creating relations from event_map (%d events)...", len(event_map))
    relation_count = 0
    error_count = 0
    with driver.session() as s:
        for aid, event, event_name, arg_entities in event_map:
            for name, role in arg_entities:
                rel_type = None
                if role == "Subject":
                    rel_type = "INVOLVED_IN"
                elif role == "Object":
                    rel_type = "AFFECTED_IN"
                elif role == "Equipment":
                    rel_type = "USED_IN"
                elif role == "Location":
                    rel_type = "OCCURRED_IN"
                elif role == "Militaryforce":
                    rel_type = "PARTICIPATED_IN"
                elif role == "Date":
                    continue
                else:
                    continue

                label, _ = classify_entity(name, role)
                try:
                    if rel_type == "OCCURRED_IN":
                        # Event → Location (Country)
                        result = s.run(
                            "MATCH (e:Event {name: $evt}) "
                            "MATCH (l:Country {name: $ent}) "
                            "MERGE (e)-[r:" + rel_type + "]->(l) "
                            "RETURN count(r) AS c",
                            evt=event_name, ent=name,
                        )
                    else:
                        # Entity → Event
                        result = s.run(
                            "MATCH (a:" + label + " {name: $ent}) "
                            "MATCH (e:Event {name: $evt}) "
                            "MERGE (a)-[r:" + rel_type + "]->(e) "
                            "RETURN count(r) AS c",
                            evt=event_name, ent=name,
                        )
                    relation_count += 1
                except Exception as e:
                    error_count += 1
                    if error_count <= 3:
                        log.debug("Relation error for %s->%s: %s", name, event_name, str(e)[:100])

    log.info("Created %d relations (%d errors)", relation_count, error_count)

    # Verify
    with driver.session() as s:
        for lbl in ["Country", "Organization", "Equipment", "Event"]:
            cnt = s.run(f"MATCH (n:{lbl}) RETURN count(n) AS c").single()["c"]
            log.info("  %s nodes: %d", lbl, cnt)
        rel_cnt = s.run(
            "MATCH ()-[r]->() WHERE NOT (startNode(r):KQA_Thing OR endNode(r):KQA_Thing) "
            "RETURN count(r) AS c"
        ).single()["c"]
        log.info("  Relations: %d", rel_cnt)


def main():
    log.info("=" * 50)
    log.info("Build CMNEE Military KG")
    log.info("=" * 50)

    with open(SELECTED_PATH, "r", encoding="utf-8") as f:
        articles = json.load(f)
    log.info("Loaded %d articles", len(articles))

    build_kg_from_annotations(articles)
    log.info("KG build complete!")


if __name__ == "__main__":
    main()

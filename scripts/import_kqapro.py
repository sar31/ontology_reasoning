"""Import KQA Pro kb.json into Neo4j with independent KQA_* ontology labels.

Usage: python scripts/import_kqapro.py

The script:
1. Downloads kb.json from Hugging Face (or reads from local cache)
2. Maps 794 Freebase/Wikidata concepts → 8 KQA_* top-level types
3. Creates 16,960 entity nodes in Neo4j
4. Creates relations between nodes
5. Idempotent: clears KQA_* nodes before import
"""
import json
import logging
import os
import sys
from collections import defaultdict

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from db import get_neo4j_driver

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

KB_URL = "https://huggingface.co/datasets/drt/kqa_pro/resolve/main/kb.json"
LOCAL_KB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "kqapro_kb.json")

# ---------------------------------------------------------------------------
# Concept → KQA_* label mapping
# ---------------------------------------------------------------------------

# Each entry: (top_level_label, [list of concept names that belong to this type])
# Concepts not listed here are classified by walking the instanceOf chain.
CONCEPT_TYPE_MAP = {
    "KQA_Person": [
        "human", "actor", "film director", "screenwriter", "musician",
        "singer", "composer", "guitarist", "drummer", "pianist",
        "basketball player", "American football player", "baseball player",
        "athlete", "sportsman", "politician", "diplomat", "writer",
        "journalist", "photographer", "painter", "artist", "author",
        "poet", "novelist", "philosopher", "scientist", "mathematician",
        "physicist", "chemist", "biologist", "engineer", "architect",
        "physician", "surgeon", "lawyer", "judge", "priest", "model",
        "adult", "child",
    ],
    "KQA_CreativeWork": [
        "film", "feature film", "short film", "silent film",
        "television series", "television film", "animated feature film",
        "video game", "written work", "book", "novel", "comic book",
        "album", "single", "song", "musical work", "opera",
        "play", "musical", "ballet",
    ],
    "KQA_Place": [
        "sovereign state", "country", "city", "big city",
        "city of the United States", "town", "village",
        "administrative territorial entity", "state", "province",
        "county", "region", "continent", "island", "mountain",
        "river", "lake", "ocean", "sea", "desert", "forest",
        "neighborhood", "borough", "census-designated place",
    ],
    "KQA_Organization": [
        "business", "company", "organization", "record label",
        "film production company", "political party", "government agency",
        "nonprofit organization", "trade union", "news agency",
        "newspaper", "magazine", "publisher", "broadcaster",
        "television network", "radio station", "airline", "railway company",
        "hotel chain", "restaurant chain", "retail chain", "bank",
        "insurance company", "technology company", "software company",
    ],
    "KQA_EducationalInstitution": [
        "university", "public university", "private university",
        "college", "higher education institution", "school",
        "high school", "secondary school", "primary school",
        "research institute", "academic institution", "business school",
        "medical school", "law school", "conservatory",
    ],
    "KQA_SportsTeam": [
        "association football club", "national association football team",
        "basketball team", "baseball team", "ice hockey team",
        "American football team", "rugby club", "sports club",
        "sports team",
    ],
    "KQA_MusicGroup": [
        "band", "rock band", "musical group", "orchestra",
        "choir", "string quartet", "jazz ensemble",
        "heavy metal band", "punk rock band", "pop group",
        "hip hop group", "musical duo",
    ],
    "KQA_Award": [
        "award", "Academy Awards ceremony", "film award",
        "music award", "literary award", "sports award",
        "science award", "television award", "theatre award",
        "prize",
    ],
    "KQA_Event": [
        "award ceremony", "sports event", "music festival",
        "film festival", "election", "Olympic Games", "World Cup",
        "war", "battle", "conference", "summit", "exhibition",
        "tournament", "competition", "sports season",
        "recurring event",
    ],
}

# Build reverse lookup: concept_name → KQA_label
CONCEPT_TO_LABEL = {}
for label, names in CONCEPT_TYPE_MAP.items():
    for name in names:
        CONCEPT_TO_LABEL[name] = label

# Default fallback for unmapped concepts
FALLBACK_LABEL = "KQA_Thing"


def classify_concept(concept_name, concepts_dict):
    """Given a concept name, return the KQA_* label by walking up the hierarchy."""
    if concept_name in CONCEPT_TO_LABEL:
        return CONCEPT_TO_LABEL[concept_name]

    # Walk up instanceOf chain
    visited = set()
    current_name = concept_name
    while current_name not in visited:
        visited.add(current_name)
        # Find the concept entry
        concept_entry = None
        for cid, cdata in concepts_dict.items():
            if cdata["name"] == current_name:
                concept_entry = cdata
                break
        if not concept_entry:
            break
        parents = concept_entry.get("instanceOf", [])
        if not parents:
            break
        # Try each parent
        for pid in parents:
            if pid in concepts_dict:
                parent_name = concepts_dict[pid]["name"]
                if parent_name in CONCEPT_TO_LABEL:
                    return CONCEPT_TO_LABEL[parent_name]
                current_name = parent_name
                break
        else:
            break

    return FALLBACK_LABEL


# ---------------------------------------------------------------------------
# Main import logic
# ---------------------------------------------------------------------------

def download_kb():
    """Download kb.json from Hugging Face or read from local cache."""
    if os.path.exists(LOCAL_KB_PATH):
        log.info("Loading kb.json from local cache: %s", LOCAL_KB_PATH)
        with open(LOCAL_KB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    log.info("Downloading kb.json from %s ...", KB_URL)
    resp = requests.get(KB_URL, timeout=300)
    resp.raise_for_status()
    kb = resp.json()

    os.makedirs(os.path.dirname(LOCAL_KB_PATH), exist_ok=True)
    with open(LOCAL_KB_PATH, "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False)
    log.info("Saved kb.json to %s", LOCAL_KB_PATH)
    return kb


def clear_kqa_nodes(driver):
    """Remove all KQA_* nodes and their relations before re-import."""
    with driver.session() as s:
        result = s.run(
            "MATCH (n) WHERE ANY(label IN labels(n) WHERE label STARTS WITH 'KQA_') "
            "DETACH DELETE n"
        )
        counters = result.consume().counters
        log.info("Cleared: %d nodes deleted", counters.nodes_deleted)


def sanitize_relation_name(predicate):
    """Convert a predicate string to a Neo4j-safe relationship type.

    Examples: 'shares border with' → 'SHARES_BORDER_WITH'
              'director' → 'DIRECTOR'
    """
    name = predicate.upper().replace(" ", "_").replace("-", "_")
    # Remove non-alphanumeric/underscore characters
    name = "".join(c for c in name if c.isalnum() or c == "_")
    # Must start with letter
    if name and name[0].isdigit():
        name = "REL_" + name
    return name[:50] or "RELATED_TO"


def safe_attr_value(value_obj):
    """Convert attribute value dict to a simple Python value for Neo4j."""
    if not isinstance(value_obj, dict):
        return str(value_obj) if value_obj is not None else ""
    vtype = value_obj.get("type", "string")
    vval = value_obj.get("value", "")
    if vtype in ("quantity", "number"):
        try:
            return float(vval)
        except (ValueError, TypeError):
            return str(vval)
    elif vtype in ("year",):
        try:
            return int(vval)
        except (ValueError, TypeError):
            return str(vval)
    else:
        return str(vval)


def import_to_neo4j(driver, concepts, entities):
    """Import entities and relations into Neo4j."""
    # Step 1: classify all concepts
    concept_label_map = {}
    unmapped = []
    for cid, cdata in concepts.items():
        cname = cdata["name"]
        label = classify_concept(cname, concepts)
        concept_label_map[cid] = (label, cname)
        if label == FALLBACK_LABEL:
            unmapped.append(cname)

    if unmapped:
        log.warning("Unmapped concepts (%d): %s ...",
                    len(unmapped), ", ".join(unmapped[:20]))

    # Step 2: create entity nodes
    # Group entities by label for progress tracking
    label_counts = defaultdict(int)
    entity_labels = {}  # entity Q-ID → list of Neo4j labels

    for eid, edata in entities.items():
        ename = edata.get("name", eid)
        instance_of = edata.get("instanceOf", [])
        labels_for_entity = ["KQA_Thing"]

        for cid in instance_of:
            if cid in concept_label_map:
                kqa_label, _ = concept_label_map[cid]
                if kqa_label != FALLBACK_LABEL and kqa_label not in labels_for_entity:
                    labels_for_entity.append(kqa_label)

        if len(labels_for_entity) == 1:  # only KQA_Thing
            labels_for_entity.append(FALLBACK_LABEL)

        entity_labels[eid] = labels_for_entity
        for lbl in labels_for_entity:
            label_counts[lbl] += 1

    log.info("Label distribution:")
    for lbl, cnt in sorted(label_counts.items(), key=lambda x: -x[1]):
        log.info("  %s: %d entities", lbl, cnt)

    # Step 3: create nodes in Neo4j
    with driver.session() as s:
        # Create indexes for faster lookup
        s.run("CREATE INDEX kqa_entity_id IF NOT EXISTS FOR (n:KQA_Thing) ON (n.qid)")

        batch_size = 500
        eid_list = list(entities.keys())
        for batch_start in range(0, len(eid_list), batch_size):
            batch = eid_list[batch_start:batch_start + batch_size]
            for eid in batch:
                edata = entities[eid]
                ename = edata.get("name", eid)
                labels = entity_labels.get(eid, ["KQA_Thing"])
                attrs = edata.get("attributes", [])

                # Build properties
                props = {"qid": eid, "name": ename}
                for attr in attrs:
                    key = attr.get("key", "")
                    if key:
                        safe_key = (key.lower()
                                    .replace(" ", "_")
                                    .replace("-", "_")
                                    .replace("/", "_")
                                    .replace(",", "")
                                    .replace("(", "")
                                    .replace(")", "")
                                    [:50])
                        props[safe_key] = safe_attr_value(attr.get("value", ""))

                # Store concept names as a property for Cypher filtering
                instance_of_names = []
                for cid in edata.get("instanceOf", []):
                    if cid in concept_label_map:
                        instance_of_names.append(concept_label_map[cid][1])
                props["concept_types"] = instance_of_names[:10]

                label_str = ":".join(labels)
                # Using MERGE to avoid duplicates
                query = (
                    f"MERGE (n:{label_str} {{qid: $qid}}) "
                    "SET n = $props"
                )
                s.run(query, qid=eid, props=props)

            log.info("  Created nodes: %d/%d", batch_start + len(batch), len(eid_list))

    # Step 4: create relations with qualifier properties
    log.info("Creating relations...")
    relation_count = 0
    with driver.session() as s:
        for batch_start in range(0, len(eid_list), batch_size):
            batch = eid_list[batch_start:batch_start + batch_size]
            for eid in batch:
                edata = entities[eid]
                relations = edata.get("relations", [])
                for rel in relations:
                    target_id = rel.get("object", "")
                    predicate = rel.get("predicate", "")
                    if not target_id or not predicate:
                        continue

                    rel_type = sanitize_relation_name(predicate)
                    direction = rel.get("direction", "forward")

                    # Build qualifier properties for the relation
                    qualifiers = rel.get("qualifiers", {})
                    rel_props = {}
                    for qkey, qvals in qualifiers.items():
                        if qvals and len(qvals) > 0:
                            safe_key = (qkey.lower()
                                        .replace(" ", "_")
                                        .replace("-", "_")
                                        .replace("/", "_")
                                        .replace(",", "")
                                        .replace("(", "")
                                        .replace(")", "")
                                        [:50])
                            rel_props[safe_key] = safe_attr_value(qvals[0])

                    # Use MERGE + SET for idempotent relation creation with properties
                    if rel_props:
                        if direction == "forward":
                            query = (
                                f"MATCH (a:KQA_Thing {{qid: $source}}) "
                                f"MATCH (b:KQA_Thing {{qid: $target}}) "
                                f"MERGE (a)-[r:{rel_type}]->(b) "
                                f"SET r += $rel_props"
                            )
                        else:
                            query = (
                                f"MATCH (a:KQA_Thing {{qid: $source}}) "
                                f"MATCH (b:KQA_Thing {{qid: $target}}) "
                                f"MERGE (b)-[r:{rel_type}]->(a) "
                                f"SET r += $rel_props"
                            )
                    else:
                        if direction == "forward":
                            query = (
                                f"MATCH (a:KQA_Thing {{qid: $source}}) "
                                f"MATCH (b:KQA_Thing {{qid: $target}}) "
                                f"MERGE (a)-[:{rel_type}]->(b)"
                            )
                        else:
                            query = (
                                f"MATCH (a:KQA_Thing {{qid: $source}}) "
                                f"MATCH (b:KQA_Thing {{qid: $target}}) "
                                f"MERGE (b)-[:{rel_type}]->(a)"
                            )
                    try:
                        s.run(query, source=eid, target=target_id, rel_props=rel_props)
                        relation_count += 1
                    except Exception:
                        pass  # Skip broken relations

            if (batch_start // batch_size) % 10 == 0:
                log.info("  Relations: %d created so far...", relation_count)

    log.info("Total relations created: %d", relation_count)
    return label_counts, relation_count


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def main():
    log.info("=" * 50)
    log.info("KQA Pro → Neo4j Importer (Independent KQA_* Ontology)")
    log.info("=" * 50)

    # 1. Download data
    kb = download_kb()
    concepts = kb["concepts"]
    entities = kb["entities"]
    log.info("KB loaded: %d concepts, %d entities", len(concepts), len(entities))

    # 2. Get Neo4j driver
    driver = get_neo4j_driver()

    # 3. Clear existing KQA nodes
    clear_kqa_nodes(driver)

    # 4. Import
    label_counts, rel_count = import_to_neo4j(driver, concepts, entities)

    # 5. Verify
    with driver.session() as s:
        node_count = s.run(
            "MATCH (n:KQA_Thing) RETURN count(n) AS c"
        ).single()["c"]
        rel_cypher = s.run(
            "MATCH (a:KQA_Thing)-[r]->(b:KQA_Thing) RETURN count(r) AS c"
        ).single()["c"]

    log.info("=" * 50)
    log.info("Import complete!")
    log.info("  Nodes: %d (expected ~%d)", node_count, len(entities))
    log.info("  Relations: %d", rel_cypher)
    log.info("  Label distribution:")
    for lbl, cnt in sorted(label_counts.items(), key=lambda x: -x[1]):
        log.info("    %s: %d", lbl, cnt)


if __name__ == "__main__":
    main()

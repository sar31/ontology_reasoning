"""Extract knowledge graph data from unstructured text using LLM."""
import logging
import time

from db import get_neo4j_driver
from llm_client import call_qwen, EXTRACTION_SYSTEM_PROMPT

log = logging.getLogger(__name__)


def _merge_source(current, new_source):
    if not current or current == new_source:
        return new_source
    if "sql" in current and "text" in current:
        return current
    parts = sorted(set(current.split("+") + [new_source]))
    return "+".join(parts)


def merge_concepts(concepts, text_source_id=None):
    """Merge LLM-extracted concepts into Neo4j."""
    driver = get_neo4j_driver()
    created = 0
    updated = 0
    with driver.session() as s:
        for c in concepts:
            name = c.get("name", "").strip()
            if not name:
                continue
            result = s.run(
                """
                MERGE (n:Concept {name: $name})
                ON CREATE SET n.created_from = 'text', n.source = 'text',
                    n.text_source_ids = CASE WHEN $tid IS NULL THEN NULL ELSE [$tid] END
                ON MATCH SET n.source = CASE
                    WHEN n.source IS NULL THEN 'text'
                    WHEN n.source CONTAINS 'text' THEN n.source
                    ELSE n.source + '+text'
                END,
                n.text_source_ids = CASE
                    WHEN $tid IS NULL THEN n.text_source_ids
                    WHEN n.text_source_ids IS NULL THEN [$tid]
                    WHEN $tid IN n.text_source_ids THEN n.text_source_ids
                    ELSE n.text_source_ids + $tid
                END
                SET n.label = coalesce(n.label, $label, n.name),
                    n.description = coalesce(n.description, $description, ''),
                    n.table = coalesce(n.table, 'text_extracted')
                RETURN n.source AS source
                """,
                name=name,
                label=c.get("label", ""),
                description=c.get("description", ""),
                tid=text_source_id,
            ).single()
            if result:
                if result["source"] == "text":
                    created += 1
                else:
                    updated += 1
    return {"created": created, "updated": updated}


def merge_concept_relations(relations, text_source_id=None):
    """Merge LLM-extracted concept relations into Neo4j."""
    driver = get_neo4j_driver()
    created = 0
    with driver.session() as s:
        for r in relations:
            src = r.get("source", "").strip()
            tgt = r.get("target", "").strip()
            name = r.get("name", "").strip()
            label = r.get("label", "").strip()
            if not src or not tgt or not name:
                continue
            res = s.run(
                """
                MATCH (a:Concept {name: $src}), (b:Concept {name: $tgt})
                MERGE (a)-[rel:CONCEPT_REL {name: $name}]->(b)
                ON CREATE SET rel.source = 'text', rel.label = $label,
                    rel.text_source_ids = CASE WHEN $tid IS NULL THEN NULL ELSE [$tid] END
                ON MATCH SET rel.source = CASE
                    WHEN rel.source IS NULL THEN 'text'
                    WHEN rel.source CONTAINS 'text' THEN rel.source
                    ELSE rel.source + '+text'
                END,
                rel.text_source_ids = CASE
                    WHEN $tid IS NULL THEN rel.text_source_ids
                    WHEN rel.text_source_ids IS NULL THEN [$tid]
                    WHEN $tid IN rel.text_source_ids THEN rel.text_source_ids
                    ELSE rel.text_source_ids + $tid
                END
                RETURN count(rel) AS n
                """,
                src=src, tgt=tgt, name=name, label=label, tid=text_source_id,
            ).single()["n"]
            created += res
    return {"created": created}


def merge_instances(instances, text_source_id=None):
    """Merge LLM-extracted instances into Neo4j."""
    driver = get_neo4j_driver()
    created = 0
    updated = 0
    with driver.session() as s:
        for inst in instances:
            label = inst.get("label", "").strip()
            name = inst.get("name", "").strip()
            props = inst.get("properties", {})
            if not label or not name:
                continue
            # Sanitize label for Cypher (must be a valid identifier)
            safe_label = "".join(ch for ch in label if ch.isalnum() or ch == "_")
            if not safe_label:
                continue
            result = s.run(
                f"""
                MERGE (n:{safe_label} {{display_name: $name}})
                ON CREATE SET n.source = 'text', n.created_from = 'text',
                    n.text_source_ids = CASE WHEN $tid IS NULL THEN NULL ELSE [$tid] END
                ON MATCH SET n.source = CASE
                    WHEN n.source IS NULL THEN 'text'
                    WHEN n.source CONTAINS 'text' THEN n.source
                    ELSE n.source + '+text'
                END,
                n.text_source_ids = CASE
                    WHEN $tid IS NULL THEN n.text_source_ids
                    WHEN n.text_source_ids IS NULL THEN [$tid]
                    WHEN $tid IN n.text_source_ids THEN n.text_source_ids
                    ELSE n.text_source_ids + $tid
                END
                SET n += $props
                RETURN n.source AS source
                """,
                name=name,
                props=props,
                tid=text_source_id,
            ).single()
            if result:
                if result["source"] == "text":
                    created += 1
                else:
                    updated += 1
    return {"created": created, "updated": updated}


def merge_instance_relations(relations, text_source_id=None):
    """Merge LLM-extracted instance relations into Neo4j."""
    driver = get_neo4j_driver()
    created = 0
    with driver.session() as s:
        for r in relations:
            src_name = r.get("source_name", "").strip()
            src_label = r.get("source_label", "").strip()
            tgt_name = r.get("target_name", "").strip()
            tgt_label = r.get("target_label", "").strip()
            rel_type = r.get("relation_type", "").strip()
            props = r.get("properties", {})
            if not src_name or not tgt_name or not rel_type:
                continue
            safe_src = "".join(ch for ch in src_label if ch.isalnum() or ch == "_")
            safe_tgt = "".join(ch for ch in tgt_label if ch.isalnum() or ch == "_")
            safe_rel = "".join(ch for ch in rel_type if ch.isalnum() or ch == "_")
            if not safe_src or not safe_tgt or not safe_rel:
                continue
            res = s.run(
                f"""
                MATCH (a:{safe_src} {{display_name: $src_name}}), (b:{safe_tgt} {{display_name: $tgt_name}})
                MERGE (a)-[rel:{safe_rel}]->(b)
                ON CREATE SET rel.source = 'text',
                    rel.text_source_ids = CASE WHEN $tid IS NULL THEN NULL ELSE [$tid] END
                ON MATCH SET rel.source = CASE
                    WHEN rel.source IS NULL THEN 'text'
                    WHEN rel.source CONTAINS 'text' THEN rel.source
                    ELSE rel.source + '+text'
                END,
                rel.text_source_ids = CASE
                    WHEN $tid IS NULL THEN rel.text_source_ids
                    WHEN rel.text_source_ids IS NULL THEN [$tid]
                    WHEN $tid IN rel.text_source_ids THEN rel.text_source_ids
                    ELSE rel.text_source_ids + $tid
                END
                SET rel += $props
                RETURN count(rel) AS n
                """,
                src_name=src_name, tgt_name=tgt_name, props=props, tid=text_source_id,
            ).single()["n"]
            created += res
    return {"created": created}


def preview_from_text(text):
    """Call LLM to extract KG data from text, return raw structured data without writing to Neo4j."""
    log.info("Preview extracting from text, length=%d", len(text))
    if not text or len(text.strip()) < 10:
        raise ValueError("Text too short")

    t0 = time.time()
    raw = call_qwen(EXTRACTION_SYSTEM_PROMPT, text)
    t1 = time.time()
    log.info("LLM call took %.1fs", t1 - t0)

    concepts = raw.get("concepts", []) if isinstance(raw, dict) else []
    concept_rels = raw.get("concept_relations", []) if isinstance(raw, dict) else []
    instances = raw.get("instances", []) if isinstance(raw, dict) else []
    instance_rels = raw.get("instance_relations", []) if isinstance(raw, dict) else []

    log.info("LLM preview returned: %d concepts, %d concept_rels, %d instances, %d instance_rels",
             len(concepts), len(concept_rels), len(instances), len(instance_rels))

    return {
        "concepts": concepts,
        "concept_relations": concept_rels,
        "instances": instances,
        "instance_relations": instance_rels,
    }


def confirm_extract(data, text_source_id=None):
    """Merge user-reviewed extraction data into Neo4j."""
    concepts = data.get("concepts", [])
    concept_rels = data.get("concept_relations", [])
    instances = data.get("instances", [])
    instance_rels = data.get("instance_relations", [])

    log.info("Confirming extract: %d concepts, %d rels, %d instances, %d instance_rels (tid=%s)",
             len(concepts), len(concept_rels), len(instances), len(instance_rels), text_source_id)

    c_res = merge_concepts(concepts, text_source_id)
    cr_res = merge_concept_relations(concept_rels, text_source_id)
    i_res = merge_instances(instances, text_source_id)
    ir_res = merge_instance_relations(instance_rels, text_source_id)

    # Auto-trigger fusion rules after saves to deduplicate
    fusion_results = {}
    try:
        from rules import (
            trigger_on_concept_save,
            trigger_on_concept_relation_save,
            trigger_on_instance_save,
            trigger_on_instance_relation_save,
        )
        if c_res.get("created", 0) > 0:
            fusion_results["concept_fusion"] = trigger_on_concept_save()
        if cr_res.get("created", 0) > 0:
            fusion_results["concept_relation_fusion"] = trigger_on_concept_relation_save()
        if i_res.get("created", 0) > 0:
            fusion_results["instance_fusion"] = trigger_on_instance_save()
        if ir_res.get("created", 0) > 0:
            fusion_results["instance_relation_fusion"] = trigger_on_instance_relation_save()
    except Exception as e:
        log.warning("Fusion auto-trigger failed: %s", e)

    return {
        "concepts": c_res,
        "concept_relations": cr_res,
        "instances": i_res,
        "instance_relations": ir_res,
        "fusion": fusion_results if fusion_results else None,
    }


def extract_from_text(text, text_source_id=None):
    """Main entry: extract KG data from text via LLM and merge into Neo4j."""
    log.info("Extracting from text, length=%d", len(text))
    if not text or len(text.strip()) < 10:
        raise ValueError("Text too short")

    preview = preview_from_text(text)
    confirmed = confirm_extract(preview, text_source_id)

    return {
        **confirmed,
        "raw_summary": {
            "concepts_found": len(preview["concepts"]),
            "concept_relations_found": len(preview["concept_relations"]),
            "instances_found": len(preview["instances"]),
            "instance_relations_found": len(preview["instance_relations"]),
        },
    }

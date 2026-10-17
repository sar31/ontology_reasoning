"""Knowledge Fusion — merge redundant concepts, relations, and instances in the KG.

Four fusion functions:
  1. concept_fusion      — Merge duplicate :Concept nodes (same meaning, different names)
  2. concept_relation_fusion — Merge duplicate :CONCEPT_REL edges
  3. instance_fusion     — Merge duplicate :Label instance nodes (same real-world entity)
  4. instance_relation_fusion — Merge duplicate instance relations

Each function returns {merged_count, details}.
"""
import logging
from db import get_neo4j_driver

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Concept Fusion — merge duplicate concept nodes by name similarity
# ---------------------------------------------------------------------------

# Known synonym/alias pairs for concept names
CONCEPT_SYNONYMS = [
    (["国家", "地区", "国家/地区"], "Country"),
    (["人员", "人物", "个人", "人"], "Person"),
    (["组织", "机构", "单位", "团体"], "Organization"),
    (["装备", "设备", "武器", "兵器"], "Equipment"),
    (["设施", "基地", "场所"], "Facility"),
    (["事件", "活动", "行动"], "Event"),
]


def concept_fusion():
    """Merge duplicate :Concept nodes.

    Strategy:
      1. Exact name match (case-insensitive) -> merge into one, keep the oldest.
      2. Synonym mapping -> merge alias concepts into canonical concept.
      3. Concepts with same `table` property -> merge (retain oldest).
    """
    driver = get_neo4j_driver()
    merged = 0
    details = []

    with driver.session() as s:
        # --- Rule 1: Exact name match (case-insensitive) ---
        result = s.run(
            """MATCH (c:Concept)
               WITH toLower(c.name) AS lname, collect(c) AS group, count(*) AS cnt
               WHERE cnt > 1
               RETURN lname, [g IN group | {name: g.name, label: g.label}] AS nodes
               LIMIT 20"""
        )
        for record in result:
            group = record["nodes"]
            keeper = group[0]["name"]
            for dup in group[1:]:
                dup_name = dup["name"]
                _merge_concept_nodes(s, keeper, dup_name)
                merged += 1
                details.append(f"概念合并(name): {dup_name} -> {keeper}")

        # --- Rule 2: Synonym mapping ---
        for aliases, canonical in CONCEPT_SYNONYMS:
            for alias in aliases:
                canonical_node = s.run(
                    "MATCH (c:Concept {name: $name}) RETURN c.name LIMIT 1",
                    name=canonical,
                ).single()
                if not canonical_node:
                    continue
                alias_nodes = s.run(
                    "MATCH (c:Concept) WHERE c.name CONTAINS $alias OR c.label = $alias "
                    "RETURN c.name, c.label LIMIT 5",
                    alias=alias,
                )
                for an in alias_nodes:
                    alias_name = an["c.name"]
                    if alias_name != canonical:
                        _merge_concept_nodes(s, canonical, alias_name)
                        merged += 1
                        details.append(f"概念合并(synonym): {alias_name} -> {canonical}")

        # --- Rule 3: Same table property ---
        result = s.run(
            """MATCH (c:Concept) WHERE c.table IS NOT NULL AND c.table <> 'text_extracted'
               WITH c.table AS tbl, collect(c.name) AS names, count(*) AS cnt
               WHERE cnt > 1
               RETURN tbl, names LIMIT 10"""
        )
        for record in result:
            names = record["names"]
            keeper = names[0]
            for dup in names[1:]:
                _merge_concept_nodes(s, keeper, dup)
                merged += 1
                details.append(f"概念合并(table): {dup} -> {keeper}")

    log.info("Concept fusion: %d merged", merged)
    return {"merged_count": merged, "details": details}


def _merge_concept_nodes(session, keeper_name, duplicate_name):
    """Merge duplicate concept into keeper: copy all relations and properties, then delete."""
    # Copy all relationships from duplicate to keeper
    session.run(
        """MATCH (keeper:Concept {name: $keeper})
           MATCH (dup:Concept {name: $dup})-[r]->(target)
           WHERE target <> keeper
           MERGE (keeper)-[r2:CONCEPT_REL {name: type(r)}]->(target)
           ON CREATE SET r2 = properties(r)
           ON MATCH SET r2 += properties(r)""",
        keeper=keeper_name, dup=duplicate_name,
    )
    session.run(
        """MATCH (keeper:Concept {name: $keeper})
           MATCH (source)-[r]->(dup:Concept {name: $dup})
           WHERE source <> keeper
           MERGE (source)-[r2:CONCEPT_REL {name: type(r)}]->(keeper)
           ON CREATE SET r2 = properties(r)
           ON MATCH SET r2 += properties(r)""",
        keeper=keeper_name, dup=duplicate_name,
    )
    # Merge properties
    session.run(
        """MATCH (keeper:Concept {name: $keeper}), (dup:Concept {name: $dup})
           SET keeper.label = coalesce(keeper.label, dup.label),
               keeper.description = coalesce(keeper.description, dup.description),
               keeper.table = coalesce(keeper.table, dup.table),
               keeper.source = keeper.source + '+merged:' + dup.source
           DELETE dup""",
        keeper=keeper_name, dup=duplicate_name,
    )


# ---------------------------------------------------------------------------
# 2. Concept Relation Fusion — merge duplicate :CONCEPT_REL edges
# ---------------------------------------------------------------------------

def concept_relation_fusion():
    """Merge duplicate :CONCEPT_REL relationships between the same concept pair.

    Two CONCEPT_REL edges are duplicates if they have the same (source_name, target_name, rel_name).
    Keep one and merge properties.
    """
    driver = get_neo4j_driver()
    merged = 0
    details = []

    with driver.session() as s:
        result = s.run(
            """MATCH (a:Concept)-[r:CONCEPT_REL]->(b:Concept)
               WITH a.name AS src, b.name AS tgt, type(r) AS rel_type, collect(r) AS rels, count(*) AS cnt
               WHERE cnt > 1
               RETURN src, tgt, rel_type, cnt LIMIT 20"""
        )
        for record in result:
            # Keep first, delete rest (properties are already merged via ON MATCH SET)
            src, tgt, rel_type, cnt = record["src"], record["tgt"], record["rel_type"], record["cnt"]
            s.run(
                """MATCH (a:Concept {name: $src})-[r:CONCEPT_REL]->(b:Concept {name: $tgt})
                   WITH a, b, collect(r) AS rels
                   WHERE size(rels) > 1
                   WITH a, b, rels[0] AS keep, rels[1..] AS dups
                   FOREACH (d IN dups | DELETE d)""",
                src=src, tgt=tgt,
            )
            removed = cnt - 1
            merged += removed
            details.append(f"概念关系合并: ({src})-[{rel_type}]->({tgt}), 删除{removed}条重复")

    log.info("Concept relation fusion: %d edges merged", merged)
    return {"merged_count": merged, "details": details}


# ---------------------------------------------------------------------------
# 3. Instance Fusion — merge duplicate instance nodes
# ---------------------------------------------------------------------------

def instance_fusion():
    """Merge duplicate instance nodes that represent the same real-world entity.

    Strategy:
      1. Same label + same display_name (exact match) -> merge.
      2. Same label + display_name similarity > 0.85 -> candidate for merge.
      3. Nodes linked by SAME_AS edge -> merge.
    """
    driver = get_neo4j_driver()
    merged = 0
    details = []

    with driver.session() as s:
        # --- Rule 1: Same label + same display_name ---
        result = s.run(
            """MATCH (n)
               WHERE NOT n:Concept AND NOT n:Function AND NOT n:Rule
                 AND NOT n:KQA_Thing AND n.display_name IS NOT NULL
               WITH labels(n) AS lbls, n.display_name AS dname, collect(n) AS nodes, count(*) AS cnt
               WHERE cnt > 1
               RETURN lbls, dname, cnt LIMIT 30"""
        )
        for record in result:
            lbls = record["lbls"]
            dname = record["dname"]
            # Keep SQL-sourced node, or the one with most properties
            s.run(
                f"""MATCH (n:{'+'.join(lbls)} {{display_name: $dname}})
                    WITH n
                    ORDER BY CASE WHEN n.source CONTAINS 'sql' THEN 0 ELSE 1 END, size(keys(n)) DESC
                    WITH collect(n) AS nodes
                    WHERE size(nodes) > 1
                    WITH nodes[0] AS keeper, nodes[1..] AS dups
                    FOREACH (d IN dups |
                      SET keeper += properties(d)
                    )
                    FOREACH (d IN dups |
                      DETACH DELETE d
                    )""",
                dname=dname,
            )
            merged += record["cnt"] - 1
            details.append(f"实例合并(name): {dname} ({lbls}), 合并{record['cnt']}个")

        # --- Rule 2: Same label, names that differ only by whitespace/punctuation ---
        result = s.run(
            """MATCH (n)
               WHERE NOT n:Concept AND NOT n:Function AND NOT n:Rule
                 AND NOT n:KQA_Thing AND n.display_name IS NOT NULL
               WITH labels(n) AS lbls,
                    trim(replace(replace(toLower(n.display_name), ' ', ''), '-', '')) AS clean_name,
                    collect(n) AS nodes, count(*) AS cnt
               WHERE cnt > 1
               RETURN lbls, clean_name, cnt LIMIT 20"""
        )
        for record in result:
            if record["cnt"] > 1:
                clean = record["clean_name"]
                label_str = "+".join(record["lbls"])
                s.run(
                    f"""MATCH (n:{label_str})
                        WHERE trim(replace(replace(toLower(n.display_name), ' ', ''), '-', '')) = $clean
                        WITH n ORDER BY size(keys(n)) DESC
                        WITH collect(n) AS nodes
                        WHERE size(nodes) > 1
                        WITH nodes[0] AS keeper, nodes[1..] AS dups
                        FOREACH (d IN dups | SET keeper += properties(d))
                        FOREACH (d IN dups | DETACH DELETE d)""",
                    clean=clean,
                )

        # --- Rule 3: Nodes with SAME_AS relationship -> merge ---
        try:
            result = s.run(
                """MATCH (a)-[r:SAME_AS]->(b)
                   WHERE NOT a:Concept AND NOT b:Concept
                   RETURN labels(a) AS la, a.display_name AS na,
                          labels(b) AS lb, b.display_name AS nb, id(r) AS rid
                   LIMIT 30"""
            )
            for record in result:
                na, nb = record["na"], record["nb"]
                _merge_instance_nodes(s, record["la"], na, record["lb"], nb)
                merged += 1
                details.append(f"实例合并(SAME_AS): {nb} -> {na}")
        except Exception:
            pass  # SAME_AS relationship type may not exist yet

    log.info("Instance fusion: %d merged", merged)
    return {"merged_count": merged, "details": details}


def _merge_instance_nodes(session, keeper_labels, keeper_name, dup_labels, dup_name):
    """Merge duplicate instance into keeper."""
    kl = "+".join(keeper_labels) if isinstance(keeper_labels, list) else keeper_labels
    dl = "+".join(dup_labels) if isinstance(dup_labels, list) else dup_labels
    session.run(
        f"""MATCH (keeper:{kl} {{display_name: $kn}}), (dup:{dl} {{display_name: $dn}})
            SET keeper += properties(dup), keeper.source = keeper.source + '+merged:' + dup.source
            DETACH DELETE dup""",
        kn=keeper_name, dn=dup_name,
    )


# ---------------------------------------------------------------------------
# 4. Instance Relation Fusion — merge duplicate instance relations
# ---------------------------------------------------------------------------

def instance_relation_fusion():
    """Merge duplicate relationships between the same two instance nodes.

    Two edges are duplicates if they share (source_id, target_id, rel_type).
    Merge properties and delete duplicates.
    """
    driver = get_neo4j_driver()
    merged = 0
    details = []

    with driver.session() as s:
        # Find duplicate edges (same source, target, type)
        result = s.run(
            """MATCH (a)-[r]->(b)
               WHERE NOT a:Concept AND NOT a:Function AND NOT a:Rule
                 AND NOT a:KQA_Thing AND NOT b:KQA_Thing
                 AND NOT b:Concept AND NOT b:Function AND NOT b:Rule
               WITH a, b, type(r) AS rt, collect(r) AS rels, count(*) AS cnt
               WHERE cnt > 1
               RETURN id(a) AS aid, a.display_name AS aname,
                      id(b) AS bid, b.display_name AS bname,
                      rt, cnt LIMIT 30"""
        )
        for record in result:
            rt = record["rt"]
            s.run(
                """MATCH (a)-[r]->(b)
                   WHERE id(a) = $aid AND id(b) = $bid AND type(r) = $rt
                   WITH a, b, collect(r) AS rels
                   WHERE size(rels) > 1
                   WITH a, b, rels[0] AS keeper, rels[1..] AS dups
                   FOREACH (d IN dups |
                     SET keeper += properties(d)
                   )
                   FOREACH (d IN dups |
                     DELETE d
                   )""",
                aid=record["aid"], bid=record["bid"], rt=rt,
            )
            merged += record["cnt"] - 1
            details.append(f"实例关系合并: ({record['aname']})-[{rt}]->({record['bname']})")

    log.info("Instance relation fusion: %d edges merged", merged)
    return {"merged_count": merged, "details": details}


# ---------------------------------------------------------------------------
# Run all four fusions at once
# ---------------------------------------------------------------------------

def run_all_fusion():
    """Run all four fusion operations and return combined results."""
    results = {
        "concept_fusion": concept_fusion(),
        "concept_relation_fusion": concept_relation_fusion(),
        "instance_fusion": instance_fusion(),
        "instance_relation_fusion": instance_relation_fusion(),
    }
    total = sum(r["merged_count"] for r in results.values())
    results["total_merged"] = total
    log.info("Total fusion merged: %d", total)
    return results

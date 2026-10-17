"""Extract instance data from MySQL into Neo4j as a knowledge graph."""
import datetime
import decimal

from db import get_mysql_conn, get_neo4j_driver


# ----------------------------------------------------------------------------
# Schema mapping
# ----------------------------------------------------------------------------
# (label, table, primary_key, display_name_field)
INSTANCE_NODES = [
    ("Country",      "countries_regions", "id", "name"),
    ("Person",       "persons",           "id", "full_name"),
    ("Organization", "organizations",     "id", "name"),
    ("Equipment",    "equipments",        "id", "name"),
    ("Facility",     "facilities",        "id", "name"),
    ("Event",        "events",            "id", "title"),
]

# (source_label, source_table, source_fk_column, target_label, rel_type)
FK_RELATIONS = [
    ("Country",      "countries_regions", "parent_id",            "Country",      "PART_OF"),
    ("Person",       "persons",           "nationality_id",       "Country",      "NATIONAL_OF"),
    ("Organization", "organizations",     "country_id",           "Country",      "BELONGS_TO"),
    ("Organization", "organizations",     "parent_org_id",        "Organization", "PARENT_OF"),
    ("Equipment",    "equipments",        "origin_country_id",    "Country",      "ORIGIN_FROM"),
    ("Equipment",    "equipments",        "operator_country_id",  "Country",      "OPERATED_BY_COUNTRY"),
    ("Equipment",    "equipments",        "operator_org_id",      "Organization", "OPERATED_BY_ORG"),
    ("Facility",     "facilities",        "country_id",           "Country",      "LOCATED_IN"),
    ("Facility",     "facilities",        "operator_org_id",      "Organization", "OPERATED_BY"),
    ("Event",        "events",            "country_id",           "Country",      "OCCURRED_IN"),
]

# (rel_table, source_label, source_fk, target_label, target_fk, rel_type, extra_prop_fields)
RELATION_TABLES = [
    ("event_persons",       "Person",       "person_id",       "Event", "event_id", "INVOLVED_IN",
     ["role", "involvement_description"]),
    ("event_organizations", "Organization", "organization_id", "Event", "event_id", "PARTICIPATED_IN",
     ["role", "involvement_description"]),
    ("event_equipments",    "Equipment",    "equipment_id",    "Event", "event_id", "USED_IN",
     ["usage_type", "quantity", "notes"]),
    ("event_facilities",    "Facility",     "facility_id",     "Event", "event_id", "AFFECTED_IN",
     ["impact_type", "damage_assessment"]),
]


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def _safe(val):
    """Convert MySQL values to Neo4j/JSON-friendly types."""
    if isinstance(val, (datetime.datetime, datetime.date)):
        return val.isoformat()
    if isinstance(val, decimal.Decimal):
        return float(val)
    if isinstance(val, bytes):
        return None  # skip binary blobs (e.g. POINT)
    if isinstance(val, dict) or isinstance(val, list):
        # Neo4j only accepts primitives in property values; serialize as JSON string
        import json
        return json.dumps(val, ensure_ascii=False)
    return val


def _clean_row(row):
    cleaned = {}
    for k, v in row.items():
        sv = _safe(v)
        if sv is not None:
            cleaned[k] = sv
    return cleaned


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------
def extract_instances():
    """Drop & re-extract all instance data from MySQL into Neo4j."""
    driver = get_neo4j_driver()

    # Wipe instance data only, preserving Concept layer
    with driver.session() as s:
        s.run("MATCH (n) WHERE NOT n:Concept DETACH DELETE n")

    summary = {"nodes": {}, "fk_edges": {}, "rel_edges": {}}

    mc = get_mysql_conn()
    try:
        # 1) Insert nodes
        with mc.cursor() as cur, driver.session() as s:
            for label, table, pk, name_field in INSTANCE_NODES:
                cur.execute(f"SELECT * FROM `{table}`")
                rows = cur.fetchall()
                for row in rows:
                    props = _clean_row(row)
                    props["display_name"] = (
                        props.get(name_field) or f"{label}#{props.get(pk)}"
                    )
                    s.run(
                        f"""
                        CREATE (n:{label} {{ id:$id, display_name:$display_name, source:'sql' }})
                        SET n += $props
                        """,
                        id=props[pk],
                        display_name=props["display_name"],
                        props=props,
                    )
                summary["nodes"][label] = len(rows)

        # 2) FK relations
        with mc.cursor() as cur, driver.session() as s:
            for src_label, src_table, src_fk, tgt_label, rel_type in FK_RELATIONS:
                cur.execute(
                    f"SELECT id, `{src_fk}` AS fk FROM `{src_table}` "
                    f"WHERE `{src_fk}` IS NOT NULL"
                )
                rows = cur.fetchall()
                cnt = 0
                for row in rows:
                    res = s.run(
                        f"""
                        MATCH (a:{src_label} {{id:$sid}}), (b:{tgt_label} {{id:$tid}})
                        MERGE (a)-[r:{rel_type}]->(b)
                        ON CREATE SET r.source = 'sql'
                        RETURN count(r) AS n
                        """,
                        sid=row["id"], tid=row["fk"],
                    )
                    cnt += res.single()["n"]
                summary["fk_edges"][rel_type] = cnt

        # 3) Relation table edges
        with mc.cursor() as cur, driver.session() as s:
            for table, src_label, src_fk, tgt_label, tgt_fk, rel_type, prop_fields in RELATION_TABLES:
                fields = ", ".join([src_fk, tgt_fk] + prop_fields)
                cur.execute(f"SELECT {fields} FROM `{table}`")
                rows = cur.fetchall()
                cnt = 0
                for row in rows:
                    props = {f: _safe(row[f]) for f in prop_fields if row.get(f) is not None}
                    res = s.run(
                        f"""
                        MATCH (a:{src_label} {{id:$sid}}), (b:{tgt_label} {{id:$tid}})
                        MERGE (a)-[r:{rel_type}]->(b)
                        ON CREATE SET r.source = 'sql'
                        SET r += $props
                        RETURN count(r) AS n
                        """,
                        sid=row[src_fk], tid=row[tgt_fk], props=props,
                    )
                    cnt += res.single()["n"]
                summary["rel_edges"][rel_type] = cnt
    finally:
        mc.close()

    return summary


def get_instance_graph(label=None, limit=300):
    """Return instances + their relations as nodes/edges.

    Without a label filter, sample nodes evenly across labels (each label gets a
    quota of ``ceil(limit / num_labels)``) so the result is representative of the
    whole graph. A plain ``LIMIT $limit`` without ordering would otherwise return
    only the first nodes in store order, which typically belong to a couple of
    labels.
    """
    driver = get_neo4j_driver()
    with driver.session() as s:
        if label:
            nodes_q = s.run(
                f"MATCH (n:{label}) RETURN id(n) AS nid, labels(n) AS labels, "
                "properties(n) AS props LIMIT $limit",
                limit=limit,
            )
        else:
            nodes_q = s.run(
                """
                MATCH (n) WHERE NOT n:Concept
                WITH n, head([l IN labels(n) WHERE l <> 'Concept']) AS lbl
                WITH count(DISTINCT lbl) AS total, collect({n: n, lbl: lbl}) AS all
                UNWIND all AS x
                WITH x.lbl AS lbl, x.n AS n, total
                WITH lbl, total, collect(n) AS ns
                WITH lbl, ns, toInteger(ceil(1.0 * $limit / total)) AS quota
                UNWIND ns[0 .. quota] AS n
                RETURN id(n) AS nid, labels(n) AS labels, properties(n) AS props
                LIMIT $limit
                """,
                limit=limit,
            )
        nodes_raw = [dict(r) for r in nodes_q]
        node_ids = [n["nid"] for n in nodes_raw]

        edges_q = s.run(
            """
            MATCH (a)-[r]->(b)
            WHERE id(a) IN $ids AND id(b) IN $ids
              AND NOT a:Concept AND NOT b:Concept
            RETURN id(a) AS source, id(b) AS target,
                   type(r) AS type, properties(r) AS props
            """,
            ids=node_ids,
        )
        edges = [dict(r) for r in edges_q]

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
    return {"nodes": nodes, "edges": edges}


def get_instance_labels():
    """Return distinct instance (non-Concept) labels with node counts.

    Sorted by count descending so the frontend can group the core SQL-derived
    labels separately from the many fine-grained labels produced by text
    extraction / fusion.
    """
    driver = get_neo4j_driver()
    with driver.session() as s:
        res = s.run(
            "MATCH (n) WHERE NOT n:Concept "
            "WITH n, head([l IN labels(n) WHERE l <> 'Concept']) AS lbl "
            "RETURN lbl AS label, count(n) AS cnt ORDER BY cnt DESC"
        )
        return [{"label": r["label"], "count": r["cnt"]} for r in res]


def clear_all():
    """Wipe all nodes (concept + instance) from Neo4j."""
    driver = get_neo4j_driver()
    with driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    return {"status": "cleared"}

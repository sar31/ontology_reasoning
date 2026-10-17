"""Build the concept layer (ontology) in Neo4j based on MySQL schema.

The concept layer is derived from the database schema:
- Each entity table  ->  one Concept node
- Each FK column or relation table  ->  one Concept relation
"""
from db import get_neo4j_driver

# ----------------------------------------------------------------------------
# Concept definitions: each row corresponds to one entity table in MySQL
# ----------------------------------------------------------------------------
CONCEPTS = [
    {"name": "Country",      "label": "国家/地区", "table": "countries_regions", "color": "#4F8FF7"},
    {"name": "Person",       "label": "人员",     "table": "persons",            "color": "#F7A04F"},
    {"name": "Organization", "label": "组织",     "table": "organizations",      "color": "#9C4FF7"},
    {"name": "Equipment",    "label": "装备",     "table": "equipments",         "color": "#F74F6B"},
    {"name": "Facility",     "label": "设施",     "table": "facilities",         "color": "#4FF7B5"},
    {"name": "Event",        "label": "事件",     "table": "events",             "color": "#F7E84F"},
]

# ----------------------------------------------------------------------------
# Concept relations
#   "via" describes how the relation is derived:
#       fk:<table>.<column>     -- foreign-key column inside an entity table
#       table:<relation_table>  -- dedicated many-to-many relation table
# ----------------------------------------------------------------------------
CONCEPT_RELATIONS = [
    # FK-based relations (within entity tables)
    {"source": "Country",      "target": "Country",      "name": "PART_OF",              "label": "上级所属", "via": "fk:countries_regions.parent_id"},
    {"source": "Person",       "target": "Country",      "name": "NATIONAL_OF",          "label": "国籍",     "via": "fk:persons.nationality_id"},
    {"source": "Organization", "target": "Country",      "name": "BELONGS_TO",           "label": "所属国家", "via": "fk:organizations.country_id"},
    {"source": "Organization", "target": "Organization", "name": "PARENT_OF",            "label": "上级组织", "via": "fk:organizations.parent_org_id"},
    {"source": "Equipment",    "target": "Country",      "name": "ORIGIN_FROM",          "label": "原产国",   "via": "fk:equipments.origin_country_id"},
    {"source": "Equipment",    "target": "Country",      "name": "OPERATED_BY_COUNTRY",  "label": "使用国",   "via": "fk:equipments.operator_country_id"},
    {"source": "Equipment",    "target": "Organization", "name": "OPERATED_BY_ORG",      "label": "使用组织", "via": "fk:equipments.operator_org_id"},
    {"source": "Facility",     "target": "Country",      "name": "LOCATED_IN",           "label": "所在国家", "via": "fk:facilities.country_id"},
    {"source": "Facility",     "target": "Organization", "name": "OPERATED_BY",          "label": "运营组织", "via": "fk:facilities.operator_org_id"},
    {"source": "Event",        "target": "Country",      "name": "OCCURRED_IN",          "label": "发生国家", "via": "fk:events.country_id"},
    # Relation-table based
    {"source": "Person",       "target": "Event", "name": "INVOLVED_IN",     "label": "参与事件", "via": "table:event_persons"},
    {"source": "Organization", "target": "Event", "name": "PARTICIPATED_IN", "label": "参与事件", "via": "table:event_organizations"},
    {"source": "Equipment",    "target": "Event", "name": "USED_IN",         "label": "用于事件", "via": "table:event_equipments"},
    {"source": "Facility",     "target": "Event", "name": "AFFECTED_IN",     "label": "涉及事件", "via": "table:event_facilities"},
]


def build_concept_layer():
    """(Re)build the concept layer in Neo4j."""
    driver = get_neo4j_driver()
    with driver.session() as s:
        # Wipe existing concept layer (keeping instance data intact)
        s.run("MATCH (c:Concept) DETACH DELETE c")
        for c in CONCEPTS:
            s.run(
                "CREATE (n:Concept {name:$name, label:$label, table:$table, color:$color, source:'sql'})",
                **c,
            )
        for r in CONCEPT_RELATIONS:
            s.run(
                """
                MATCH (a:Concept {name:$source}), (b:Concept {name:$target})
                CREATE (a)-[:CONCEPT_REL {name:$name, label:$label, via:$via, source:'sql'}]->(b)
                """,
                **r,
            )
    return {
        "concepts_created": len(CONCEPTS),
        "concept_relations_created": len(CONCEPT_RELATIONS),
    }


def get_concept_graph():
    """Return concept layer as nodes/edges for D3."""
    driver = get_neo4j_driver()
    with driver.session() as s:
        nodes = [
            dict(r) for r in s.run(
                "MATCH (c:Concept) RETURN c.name AS id, c.name AS name, "
                "c.label AS label, c.table AS table, c.color AS color, c.source AS source, "
                "c.text_source_ids AS text_source_ids"
            )
        ]
        edges = [
            dict(r) for r in s.run(
                """
                MATCH (a:Concept)-[r:CONCEPT_REL]->(b:Concept)
                RETURN a.name AS source, b.name AS target,
                       r.name AS name, r.label AS label, r.via AS via, r.source AS source_rel,
                       r.text_source_ids AS text_source_ids
                """
            )
        ]
    return {"nodes": nodes, "edges": edges}

"""Domain-specific military analysis functions (Phase 1: simulation).

func_13: Event threat level analysis
func_14: Event follow-up assessment
func_15: Event duration estimation
func_16: NL event extraction statistics
func_17: Event relationship analysis

All functions operate on Neo4j military-domain data and use rule-based
simulation (no LLM calls). Results are marked "simulated": true.
"""
import logging
from collections import Counter, defaultdict

from db import get_neo4j_driver

log = logging.getLogger(__name__)

# Event type → threat level mapping
THREAT_LEVELS = {
    "Conflict": "high",
    "Injure": "high",
    "Deploy": "medium",
    "Manoeuvre": "medium",
    "Experiment": "low",
    "Exhibit": "low",
    "Support": "low",
    "Accident": "low",  # elevated if casualties present
}

# Event type → typical follow-up events
FOLLOWUP_MAP = {
    "Deploy": ["Manoeuvre", "Conflict", "diplomatic_protest"],
    "Manoeuvre": ["Deploy", "diplomatic_attention"],
    "Conflict": ["Injure", "ceasefire_negotiation", "international_intervention"],
    "Experiment": ["Exhibit", "Deploy"],
    "Support": ["Deploy", "Exhibit"],
    "Exhibit": ["Deploy"],
    "Accident": ["investigation", "safety_review"],
    "Injure": ["medical_response", "investigation"],
}

# Event type → typical duration range (days)
DURATION_RANGES = {
    "Experiment": (1, 30),
    "Manoeuvre": (7, 90),
    "Deploy": (30, 365),
    "Support": (7, 180),
    "Accident": (1, 7),
    "Exhibit": (1, 14),
    "Conflict": (1, 60),
    "Injure": (1, 1),
}


# ---------------------------------------------------------------------------
# func_13: Event threat level analysis
# ---------------------------------------------------------------------------

def analyze_threat_level():
    """Analyze threat levels for entities based on associated event types.

    Returns entity-level threat profiles: {entity, high/medium/low counts, overall_level}.
    """
    driver = get_neo4j_driver()
    results = []

    with driver.session() as s:
        # Get all entities linked to events with event_type info
        rows = s.run(
            """MATCH (e:Event)
               OPTIONAL MATCH (actor)-[:INVOLVED_IN|PARTICIPATED_IN]->(e)
               WHERE NOT actor:Event AND NOT actor:Country
               RETURN actor.name AS entity, labels(actor) AS labels,
                      e.event_type AS event_type, count(*) AS cnt
               ORDER BY cnt DESC"""
        ).data()

        # Aggregate by entity
        entity_events = defaultdict(lambda: Counter())
        for r in rows:
            if r["entity"] and r["event_type"]:
                entity_events[r["entity"]][r["event_type"]] += r["cnt"]

        for entity, etypes in entity_events.items():
            profile = {"high": 0, "medium": 0, "low": 0}
            for etype, cnt in etypes.items():
                level = THREAT_LEVELS.get(etype, "low")
                profile[level] += cnt

            total = sum(profile.values())
            if profile["high"] >= 3 or profile["high"] > total * 0.5:
                overall = "high"
            elif profile["medium"] >= 3 or profile["high"] >= 1:
                overall = "medium"
            else:
                overall = "low"

            results.append({
                "entity": entity,
                "high": profile["high"],
                "medium": profile["medium"],
                "low": profile["low"],
                "total_events": total,
                "overall_level": overall,
            })

    # Sort by threat: high first
    results.sort(key=lambda x: ({"high": 3, "medium": 2, "low": 1}[x["overall_level"]],
                                 x["high"] + x["medium"]), reverse=True)

    return {
        "simulated": True,
        "function": "func_13",
        "description": "事件威胁等级分析",
        "total_entities_analyzed": len(results),
        "threat_distribution": {
            "high": sum(1 for r in results if r["overall_level"] == "high"),
            "medium": sum(1 for r in results if r["overall_level"] == "medium"),
            "low": sum(1 for r in results if r["overall_level"] == "low"),
        },
        "top_threats": results[:10],
    }


# ---------------------------------------------------------------------------
# func_14: Event follow-up assessment
# ---------------------------------------------------------------------------

def assess_followup():
    """Predict possible follow-up events for each event type in the KG.

    Based on military-domain knowledge about event progression patterns.
    """
    driver = get_neo4j_driver()

    with driver.session() as s:
        rows = s.run(
            """MATCH (e:Event) WHERE e.event_type IS NOT NULL
               RETURN e.event_type AS event_type, count(*) AS cnt
               ORDER BY cnt DESC"""
        ).data()

    event_type_counts = {r["event_type"]: r["cnt"] for r in rows}

    results = []
    for etype, cnt in sorted(event_type_counts.items(), key=lambda x: -x[1]):
        followups = FOLLOWUP_MAP.get(etype, ["unknown"])
        results.append({
            "event_type": etype,
            "count": cnt,
            "possible_followups": followups,
            "assessment": f"{etype}类事件已发生{cnt}起，后续可能出现：{'、'.join(followups)}",
        })

    # Cross-check: are any followup types already occurring?
    existing_types = set(event_type_counts.keys())
    for r in results:
        already_occurred = [f for f in r["possible_followups"]
                            if f in existing_types or any(f in et for et in existing_types)]
        if already_occurred:
            r["already_occurred"] = already_occurred

    return {
        "simulated": True,
        "function": "func_14",
        "description": "事件后续进展研判",
        "event_types_analyzed": len(results),
        "results": results,
    }


# ---------------------------------------------------------------------------
# func_15: Event duration estimation
# ---------------------------------------------------------------------------

def estimate_duration():
    """Estimate typical duration for each event based on its type.

    Uses empirically-calibrated ranges from military domain knowledge.
    """
    driver = get_neo4j_driver()

    with driver.session() as s:
        rows = s.run(
            """MATCH (e:Event) WHERE e.event_type IS NOT NULL
               RETURN e.event_type AS event_type, e.title AS title,
                      e.description AS description
               LIMIT 100"""
        ).data()

    # Group by type
    type_examples = defaultdict(list)
    for r in rows:
        type_examples[r["event_type"]].append(r)

    results = []
    for etype, examples in sorted(type_examples.items()):
        min_d, max_d = DURATION_RANGES.get(etype, (1, 30))
        # Micro-adjustment based on text length
        avg_text_len = sum(len(ex.get("description", "")) for ex in examples) / max(len(examples), 1)
        if avg_text_len > 300:
            adjust = 1.2
        elif avg_text_len > 150:
            adjust = 1.0
        else:
            adjust = 0.8

        est_min = round(min_d * adjust)
        est_max = round(max_d * adjust)

        results.append({
            "event_type": etype,
            "sample_count": len(examples),
            "estimated_min_days": est_min,
            "estimated_max_days": est_max,
            "typical_range": f"{est_min}-{est_max}天",
            "note": f"基于{len(examples)}个样本估算，调整系数{adjust:.1f}",
        })

    return {
        "simulated": True,
        "function": "func_15",
        "description": "事件持续时间计算",
        "results": results,
    }


# ---------------------------------------------------------------------------
# func_16: NL event extraction statistics
# ---------------------------------------------------------------------------

def event_extraction_stats():
    """Statistics on event extraction coverage from CMNEE texts.

    Phase 1: reads from Neo4j CMNEE-sourced events, analyzes coverage patterns.
    """
    driver = get_neo4j_driver()

    with driver.session() as s:
        # Event type distribution
        type_rows = s.run(
            """MATCH (e:Event) WHERE e.event_type IS NOT NULL
               RETURN e.event_type AS event_type, count(*) AS cnt
               ORDER BY cnt DESC"""
        ).data()

        # Argument coverage: how many events have specific argument types
        # (Arguments are stored as relationships to entities)
        arg_rows = s.run(
            """MATCH (e:Event)
               OPTIONAL MATCH (e)<-[r:INVOLVED_IN|PARTICIPATED_IN|USED_IN|AFFECTED_IN]-(actor)
               RETURN e.event_type AS event_type,
                      count(DISTINCT actor) AS linked_actors,
                      count(DISTINCT e) AS event_count
               ORDER BY event_count DESC"""
        ).data()

        # Co-occurrence: which argument types appear together
        cooc_rows = s.run(
            """MATCH (e:Event)
               OPTIONAL MATCH (e)<-[:OCCURRED_IN]-(c:Country)
               OPTIONAL MATCH (e)<-[:INVOLVED_IN|PARTICIPATED_IN]-(o:Organization)
               RETURN e.event_type AS event_type,
                      count(e) AS total,
                      count(c) AS with_location,
                      count(o) AS with_actor
               ORDER BY total DESC"""
        ).data()

    # Build co-occurrence matrix
    cooc_matrix = []
    for r in cooc_rows:
        if r["total"] > 0:
            cooc_matrix.append({
                "event_type": r["event_type"],
                "total": r["total"],
                "has_location_pct": round(r["with_location"] / r["total"] * 100, 1),
                "has_actor_pct": round(r["with_actor"] / r["total"] * 100, 1),
            })

    return {
        "simulated": True,
        "function": "func_16",
        "description": "自然语言事件抽取统计",
        "event_type_distribution": {r["event_type"]: r["cnt"] for r in type_rows},
        "argument_actor_linkage": [
            {"event_type": r["event_type"], "linked_actors": r["linked_actors"]}
            for r in arg_rows
        ],
        "argument_cooccurrence": cooc_matrix,
    }


# ---------------------------------------------------------------------------
# func_17: Event relationship analysis
# ---------------------------------------------------------------------------

def analyze_event_relations():
    """Discover relationships between events via shared entities.

    Finds event pairs linked through shared Subjects, Locations, or Equipment.
    """
    driver = get_neo4j_driver()
    event_pairs = []
    seen_pairs = set()

    with driver.session() as s:
        # Shared Subject: two events involving the same actor
        rows = s.run(
            """MATCH (actor)-[:INVOLVED_IN|PARTICIPATED_IN]->(e1:Event),
                     (actor)-[:INVOLVED_IN|PARTICIPATED_IN]->(e2:Event)
               WHERE id(e1) < id(e2) AND NOT actor:Country
               RETURN actor.name AS shared_entity, 'shared_actor' AS rel_type,
                      e1.event_type AS type1, e1.title AS title1,
                      e2.event_type AS type2, e2.title AS title2
               LIMIT 30"""
        ).data()
        for r in rows:
            key = (r["title1"], r["title2"], "shared_actor")
            if key not in seen_pairs:
                seen_pairs.add(key)
                event_pairs.append(dict(r))

        # Shared Location: two events at the same location
        rows = s.run(
            """MATCH (e1:Event)-[:OCCURRED_IN]->(loc:Country),
                     (e2:Event)-[:OCCURRED_IN]->(loc)
               WHERE id(e1) < id(e2)
               RETURN loc.name AS shared_entity, 'shared_location' AS rel_type,
                      e1.event_type AS type1, e1.title AS title1,
                      e2.event_type AS type2, e2.title AS title2
               LIMIT 30"""
        ).data()
        for r in rows:
            key = (r["title1"], r["title2"], "shared_location")
            if key not in seen_pairs:
                seen_pairs.add(key)
                event_pairs.append(dict(r))

        # Shared Equipment
        rows = s.run(
            """MATCH (eq:Equipment)-[:USED_IN]->(e1:Event),
                     (eq)-[:USED_IN]->(e2:Event)
               WHERE id(e1) < id(e2)
               RETURN eq.name AS shared_entity, 'shared_equipment' AS rel_type,
                      e1.event_type AS type1, e1.title AS title1,
                      e2.event_type AS type2, e2.title AS title2
               LIMIT 20"""
        ).data()
        for r in rows:
            key = (r["title1"], r["title2"], "shared_equipment")
            if key not in seen_pairs:
                seen_pairs.add(key)
                event_pairs.append(dict(r))

    # Aggregate by relation type
    rel_counts = Counter(p["rel_type"] for p in event_pairs)

    return {
        "simulated": True,
        "function": "func_17",
        "description": "事件关系分析",
        "total_relations_found": len(event_pairs),
        "relation_distribution": dict(rel_counts),
        "event_pairs": event_pairs[:20],
    }


# ---------------------------------------------------------------------------
# Dispatch table for trigger_rule()
# ---------------------------------------------------------------------------

DOMAIN_DISPATCH = {
    "func_13": analyze_threat_level,
    "func_14": assess_followup,
    "func_15": estimate_duration,
    "func_16": event_extraction_stats,
    "func_17": analyze_event_relations,
}


def run_domain_function(func_id):
    """Run a domain function by its ID. Returns result dict or raises ValueError."""
    fn = DOMAIN_DISPATCH.get(func_id)
    if not fn:
        raise ValueError(f"Unknown domain function: {func_id}")
    log.info("Running domain function: %s", func_id)
    return fn()

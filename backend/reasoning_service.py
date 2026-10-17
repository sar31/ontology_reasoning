"""Event Reasoning Service: graph traversal + LLM explanation."""
import json
import logging

from db import get_neo4j_driver
from llm_client import call_qwen

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graph algorithms
# ---------------------------------------------------------------------------

def event_correlation(seed_name: str, depth: int = 2) -> dict:
    """Find events that share participants with the seed event.

    If seed_name is not an Event, automatically tries to find it as a
    Person/Organization/etc and uses the first connected Event as the
    actual seed.

    Returns related events grouped by shared participant.
    """
    driver = get_neo4j_driver()
    with driver.session() as s:
        # Try to find seed as Event first
        seed = s.run(
            "MATCH (e:Event) WHERE e.display_name = $name RETURN id(e) AS eid, e.display_name AS name LIMIT 1",
            name=seed_name,
        ).single()

        original_seed_name = seed_name
        seed_redirect = None

        if not seed:
            # Try to find seed as any other node type
            non_event = s.run(
                """
                MATCH (n)
                WHERE n.display_name = $name
                  AND NOT n:Concept AND NOT n:Event
                  AND (n:Person OR n:Organization OR n:Equipment OR n:Facility OR n:Country)
                RETURN id(n) AS nid, labels(n)[0] AS label, n.display_name AS name
                LIMIT 1
                """,
                name=seed_name,
            ).single()

            if not non_event:
                return {"error": f"未找到实体 '{seed_name}'，请检查名称是否正确"}

            # Find events connected to this entity
            connected_events = [
                dict(r)
                for r in s.run(
                    """
                    MATCH (n)-[r]-(e:Event)
                    WHERE id(n) = $nid
                    RETURN id(e) AS eid, e.display_name AS name
                    ORDER BY e.time DESC
                    LIMIT 5
                    """,
                    nid=non_event["nid"],
                )
            ]

            if not connected_events:
                return {"error": f"实体 '{seed_name}' ({non_event['label']}) 未关联任何事件"}

            # Use the first connected event as the actual seed
            seed = connected_events[0]
            seed_redirect = {
                "original_seed": original_seed_name,
                "original_type": non_event["label"],
                "actual_seed": seed["name"],
                "actual_seed_id": seed["eid"],
                "connected_events": [e["name"] for e in connected_events],
            }

        seed_id = seed["eid"]
        seed_name = seed.get("name", original_seed_name)

        # Shared participants via INVOLVED_IN / PARTICIPATED_IN / USED_IN / AFFECTED_IN
        # NOTE: parentheses around OR conditions are critical for correct precedence
        rows = s.run(
            """
            MATCH (e:Event)-[r1]-(p)
            WHERE id(e) = $seed_id AND (p:Person OR p:Organization OR p:Equipment OR p:Facility)
            MATCH (p)-[r2]-(other:Event)
            WHERE id(other) <> $seed_id
            RETURN e.display_name AS source_event,
                   p.display_name AS shared_participant,
                   labels(p)[0] AS participant_type,
                   other.display_name AS related_event,
                   other.time AS related_time,
                   other.location AS related_location,
                   type(r1) AS rel_to_seed,
                   type(r2) AS rel_to_other
            ORDER BY shared_participant, related_event
            LIMIT 50
            """,
            seed_id=seed_id,
        )
        paths = []
        for r in rows:
            paths.append(dict(r))

        # Build subgraph of seed + related events + shared participants
        nodes_raw = [
            dict(r)
            for r in s.run(
                """
                MATCH (e:Event)-[r1]-(p)-[r2]-(other:Event)
                WHERE id(e) = $seed_id AND id(other) <> $seed_id
                  AND (p:Person OR p:Organization OR p:Equipment OR p:Facility)
                WITH DISTINCT p, other
                RETURN id(p) AS nid, labels(p) AS labels, properties(p) AS props
                UNION
                MATCH (e:Event)
                WHERE id(e) = $seed_id
                RETURN id(e) AS nid, labels(e) AS labels, properties(e) AS props
                UNION
                MATCH (e:Event)-[r1]-(p)-[r2]-(other:Event)
                WHERE id(e) = $seed_id AND id(other) <> $seed_id
                WITH DISTINCT other
                RETURN id(other) AS nid, labels(other) AS labels, properties(other) AS props
                LIMIT $limit
                """,
                seed_id=seed_id,
                limit=80,
            )
        ]
        edges_raw = [
            dict(r)
            for r in s.run(
                """
                MATCH (e:Event)-[r]-(p)-[r2]-(other:Event)
                WHERE id(e) = $seed_id AND id(other) <> $seed_id
                  AND (p:Person OR p:Organization OR p:Equipment OR p:Facility)
                RETURN id(startNode(r)) AS s1, id(endNode(r)) AS t1, type(r) AS t1type, properties(r) AS p1,
                       id(startNode(r2)) AS s2, id(endNode(r2)) AS t2, type(r2) AS t2type, properties(r2) AS p2
                LIMIT $limit
                """,
                seed_id=seed_id,
                limit=120,
            )
        ]

    nodes = _format_nodes(nodes_raw)
    edges = _format_edges(edges_raw)

    # Deduplicate edges
    seen = set()
    unique_edges = []
    for e in edges:
        key = (e["source"], e["target"], e["type"])
        if key not in seen:
            seen.add(key)
            unique_edges.append(e)

    # Metrics
    related_events = len({p["related_event"] for p in paths})
    shared_participants = len({p["shared_participant"] for p in paths})

    result = {
        "paths": paths,
        "subgraph": {"nodes": nodes, "edges": unique_edges},
        "metrics": {
            "related_events": related_events,
            "shared_participants": shared_participants,
            "path_count": len(paths),
        },
    }
    if seed_redirect:
        result["seed_redirect"] = seed_redirect
    return result


def participant_network(seed_name: str, seed_label: str = "Organization", depth: int = 2) -> dict:
    """Ego network: events and co-participants of a given organization."""
    driver = get_neo4j_driver()
    with driver.session() as s:
        # Verify seed exists
        seed = s.run(
            f"MATCH (n:{seed_label}) WHERE n.display_name = $name RETURN id(n) AS nid LIMIT 1",
            name=seed_name,
        ).single()
        if not seed:
            return {"error": f"{seed_label} '{seed_name}' not found"}

        seed_id = seed["nid"]

        # Events this org participates in, and co-participants
        rows = s.run(
            """
            MATCH (org)-[r:PARTICIPATED_IN|INVOLVED_IN|USED_IN|AFFECTED_IN]->(e:Event)
            WHERE id(org) = $seed_id
            OPTIONAL MATCH (e)<-[r2:PARTICIPATED_IN|INVOLVED_IN|USED_IN|AFFECTED_IN]-(other)
            WHERE id(other) <> $seed_id
            RETURN e.display_name AS event_name,
                   e.time AS event_time,
                   e.location AS event_location,
                   type(r) AS our_rel_type,
                   r.role AS our_role,
                   collect(DISTINCT {name: other.display_name, label: labels(other)[0], role: r2.role}) AS co_participants
            ORDER BY e.time DESC
            LIMIT 30
            """,
            seed_id=seed_id,
        )
        events = [dict(r) for r in rows]

        # Subgraph: org -> events -> co-participants
        nodes_raw = [
            dict(r)
            for r in s.run(
                """
                MATCH (org)-[r]-(e:Event)
                WHERE id(org) = $seed_id
                WITH DISTINCT org, e
                MATCH (e)-[r2]-(other)
                WHERE id(other) <> $seed_id
                WITH DISTINCT other, e, org
                RETURN id(other) AS nid, labels(other) AS labels, properties(other) AS props
                UNION
                MATCH (org) WHERE id(org) = $seed_id
                RETURN id(org) AS nid, labels(org) AS labels, properties(org) AS props
                UNION
                MATCH (org)-[r]-(e:Event) WHERE id(org) = $seed_id
                RETURN id(e) AS nid, labels(e) AS labels, properties(e) AS props
                LIMIT $limit
                """,
                seed_id=seed_id,
                limit=80,
            )
        ]
        edges_raw = [
            dict(r)
            for r in s.run(
                """
                MATCH (org)-[r]-(e:Event)
                WHERE id(org) = $seed_id
                WITH DISTINCT e
                MATCH (e)-[r2]-(other)
                WHERE id(other) <> $seed_id
                RETURN id(startNode(r2)) AS s, id(endNode(r2)) AS t,
                       type(r2) AS type, properties(r2) AS props
                UNION
                MATCH (org)-[r]-(e:Event)
                WHERE id(org) = $seed_id
                RETURN id(startNode(r)) AS s, id(endNode(r)) AS t,
                       type(r) AS type, properties(r) AS props
                LIMIT $limit
                """,
                seed_id=seed_id,
                limit=120,
            )
        ]

    nodes = _format_nodes(nodes_raw)
    edges = _format_edges(edges_raw)

    # Deduplicate
    nodes = _dedup_nodes(nodes)
    edges = _dedup_edges(edges)

    event_count = len(events)
    co_participant_count = len(
        set()
        .union(*[
            {c["name"] for c in ev.get("co_participants", []) if c.get("name")}
            for ev in events
        ])
    )

    return {
        "events": events,
        "subgraph": {"nodes": nodes, "edges": edges},
        "metrics": {
            "event_count": event_count,
            "co_participant_count": co_participant_count,
        },
    }


def temporal_chain(seed_name: str, region: str = None, days: int = 365) -> dict:
    """Time-ordered chain of events in the same region as the seed event."""
    driver = get_neo4j_driver()
    with driver.session() as s:
        # Get seed event info
        seed = s.run(
            "MATCH (e:Event) WHERE e.display_name = $name RETURN e LIMIT 1",
            name=seed_name,
        ).single()
        if not seed:
            return {"error": f"Event '{seed_name}' not found"}

        seed_props = dict(seed["e"])
        seed_region = region or seed_props.get("location") or seed_props.get("region") or ""

        # Find events in same region, ordered by time
        # Time may be stored as string ISO or datetime; handle both
        if seed_region:
            rows = s.run(
                """
                MATCH (e:Event)
                WHERE e.location = $region OR e.region = $region
                  AND e.display_name <> $seed_name
                RETURN e.display_name AS event_name,
                       e.time AS event_time,
                       e.location AS location,
                       e.description AS description
                ORDER BY e.time ASC
                LIMIT 30
                """,
                region=seed_region,
                seed_name=seed_name,
            )
        else:
            # Fallback: all events ordered by time
            rows = s.run(
                """
                MATCH (e:Event)
                WHERE e.display_name <> $seed_name
                RETURN e.display_name AS event_name,
                       e.time AS event_time,
                       e.location AS location,
                       e.description AS description
                ORDER BY e.time ASC
                LIMIT 30
                """,
                seed_name=seed_name,
            )

        chain = [dict(r) for r in rows]

        # Build simple subgraph of the chain events
        event_names = [seed_name] + [c["event_name"] for c in chain]
        nodes_raw = [
            dict(r)
            for r in s.run(
                """
                MATCH (e:Event)
                WHERE e.display_name IN $names
                RETURN id(e) AS nid, labels(e) AS labels, properties(e) AS props
                """,
                names=event_names,
            )
        ]
        # Try to link consecutive events if they share participants
        edges_raw = [
            dict(r)
            for r in s.run(
                """
                MATCH (e1:Event)-[r]-(p)-[r2]-(e2:Event)
                WHERE e1.display_name IN $names AND e2.display_name IN $names
                  AND id(e1) < id(e2)
                  AND (p:Person OR p:Organization)
                RETURN id(e1) AS s, id(e2) AS t,
                       type(r) AS type, properties(r) AS props
                LIMIT 50
                """,
                names=event_names,
            )
        ]

    nodes = _format_nodes(nodes_raw)
    edges = _format_edges(edges_raw)

    return {
        "seed_event": seed_name,
        "region": seed_region,
        "chain": chain,
        "subgraph": {"nodes": nodes, "edges": _dedup_edges(edges)},
        "metrics": {
            "chain_length": len(chain),
            "region": seed_region or "全部",
        },
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_nodes(nodes_raw: list) -> list:
    out = []
    for n in nodes_raw:
        if not n:
            continue
        primary = next((l for l in n.get("labels", []) if l != "Concept"), n.get("labels", ["Node"])[0])
        props = n.get("props", {})
        out.append({
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
    return out


def _format_edges(edges_raw: list) -> list:
    out = []
    for e in edges_raw:
        if not e:
            continue
        # Handle union query results where fields may be s1/t1 or s/t
        sources = [e.get("s"), e.get("s1"), e.get("s2")]
        targets = [e.get("t"), e.get("t1"), e.get("t2")]
        types = [e.get("type"), e.get("t1type"), e.get("t2type")]
        props = e.get("props") or e.get("p1") or e.get("p2") or {}
        for si, ti, tyi in zip(sources, targets, types):
            if si is not None and ti is not None and tyi is not None:
                out.append({
                    "source": si,
                    "target": ti,
                    "type": tyi,
                    "label": props.get("label", tyi) if isinstance(props, dict) else tyi,
                })
    return out


def _dedup_nodes(nodes: list) -> list:
    seen = set()
    out = []
    for n in nodes:
        if n["id"] not in seen:
            seen.add(n["id"])
            out.append(n)
    return out


def _dedup_edges(edges: list) -> list:
    seen = set()
    out = []
    for e in edges:
        key = (e["source"], e["target"], e["type"])
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


# ---------------------------------------------------------------------------
# LLM Report Generation
# ---------------------------------------------------------------------------

REPORT_PROMPT = """你是军事/地缘政治事件分析专家。请基于以下从知识图谱中提取的结构化数据，撰写一份中文推理分析报告。

要求：
1. 报告应包括：背景概述、关键发现、关联分析、结论与建议
2. 分析必须严格基于提供的数据，不要引入外部知识
3. 使用清晰的小标题组织报告
4. 如果数据不足以支撑某方面分析，明确说明"数据不足"
5. 报告控制在500字以内

请直接输出纯文本报告（不需要JSON格式）。"""


def generate_report(type_: str, structure_data: dict) -> str:
    """Generate a Chinese reasoning report from structural data."""
    if "error" in structure_data:
        return f"推理失败：{structure_data['error']}"

    context = json.dumps(structure_data, ensure_ascii=False, indent=2)
    user_prompt = f"推理类型：{type_}\n\n结构化数据：\n{context[:5000]}"
    try:
        raw = call_qwen(REPORT_PROMPT, user_prompt, temperature=0.4)
        if isinstance(raw, dict):
            # Some models may still return JSON despite prompt
            return raw.get("report", raw.get("answer", str(raw)))
        if isinstance(raw, str):
            return raw
    except Exception as e:
        log.error("Report generation failed: %s", e)

    # Fallback: generate a simple summary
    return _fallback_report(type_, structure_data)


def _fallback_report(type_: str, data: dict) -> str:
    lines = [f"## {type_} 推理报告（自动生成）", ""]
    if type_ == "event_correlation":
        lines.append(f"与目标事件关联的事件数量：{data.get('metrics', {}).get('related_events', 0)}")
        lines.append(f"共享参与者数量：{data.get('metrics', {}).get('shared_participants', 0)}")
        lines.append("关联路径：")
        for p in data.get("paths", [])[:10]:
            lines.append(f"- {p.get('shared_participant')} ({p.get('participant_type')}) 同时参与了 {p.get('source_event')} 和 {p.get('related_event')}")
    elif type_ == "participant_network":
        lines.append(f"该组织参与的事件数量：{data.get('metrics', {}).get('event_count', 0)}")
        lines.append(f"合作方/共同参与者数量：{data.get('metrics', {}).get('co_participant_count', 0)}")
    elif type_ == "temporal_chain":
        lines.append(f"地区：{data.get('region', '未知')}")
        lines.append(f"时序链包含事件数量：{data.get('metrics', {}).get('chain_length', 0)}")
        lines.append("事件时间线：")
        for c in data.get("chain", [])[:15]:
            lines.append(f"- {c.get('event_time', '?')} | {c.get('event_name')} | {c.get('location', '')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def analyze(type_: str, seed: dict, **kwargs) -> dict:
    """Main entry: route to algorithm, then generate LLM report."""
    log.info("Reasoning analyze: type=%s, seed=%s", type_, seed)
    seed_name = seed.get("name", "")
    seed_label = seed.get("label", "Event")
    depth = kwargs.get("depth", 2)

    if type_ == "event_correlation":
        structure = event_correlation(seed_name, depth=depth)
    elif type_ == "participant_network":
        structure = participant_network(seed_name, seed_label=seed_label, depth=depth)
    elif type_ == "temporal_chain":
        region = kwargs.get("region")
        structure = temporal_chain(seed_name, region=region)
    else:
        return {"error": f"Unknown reasoning type: {type_}"}

    report = generate_report(type_, structure)
    return {
        "report": report,
        "type": type_,
        "seed": seed,
        **structure,
    }

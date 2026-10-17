"""Rule nodes and rule trigger engine for the knowledge graph."""
import logging

from db import get_neo4j_driver
from text_extractor import extract_from_text
from fusion import (
    concept_fusion,
    concept_relation_fusion,
    instance_fusion,
    instance_relation_fusion,
    run_all_fusion,
)

log = logging.getLogger(__name__)

SAMPLE_TEXT = (
    "2024年3月，某国海军在南海举行大规模演习。"
    "该国国防部长张三出席了演习开幕式。"
    "演习使用了新型驱逐舰和潜艇。"
    "某国际组织对该演习表示关注。"
)

RULES = [
    # =========================================================================
    # 构建类规则 (construction) — rule_1 ~ rule_7
    # =========================================================================
    {
        "id": "rule_1", "name": "文本概念补充规则", "category": "construction",
        "description": "当文本中发现新概念时，触发概念抽取功能",
        "trigger_condition": "new_concepts_detected",
        "action_function": "func_5", "is_active": True,
    },
    {
        "id": "rule_2", "name": "实例自动发现规则", "category": "construction",
        "description": "从示例文本中自动发现实例，补充到知识图谱中",
        "trigger_condition": "sample_text_provided",
        "action_function": "func_7", "is_active": True,
    },
    {
        "id": "rule_3", "name": "关系完整性检查规则", "category": "construction",
        "description": "为孤立节点补充关系",
        "trigger_condition": "isolated_nodes_detected",
        "action_function": "func_8", "is_active": True,
    },
    {
        "id": "rule_4", "name": "概念融合规则", "category": "construction",
        "description": "保存新概念后自动融合：合并同名/同义概念节点",
        "trigger_condition": "after_concept_save",
        "action_function": "func_9", "is_active": True,
    },
    {
        "id": "rule_5", "name": "概念关系融合规则", "category": "construction",
        "description": "保存新概念关系后自动融合：合并概念层重复关系边",
        "trigger_condition": "after_concept_relation_save",
        "action_function": "func_10", "is_active": True,
    },
    {
        "id": "rule_6", "name": "实例融合规则", "category": "construction",
        "description": "保存新实例后自动融合：合并同名/同义实例节点",
        "trigger_condition": "after_instance_save",
        "action_function": "func_11", "is_active": True,
    },
    {
        "id": "rule_7", "name": "实例关系融合规则", "category": "construction",
        "description": "保存新实例关系后自动融合：合并实例间重复关系边",
        "trigger_condition": "after_instance_relation_save",
        "action_function": "func_12", "is_active": True,
    },
    # =========================================================================
    # 领域类规则 (domain) — rule_8 ~ rule_12
    # =========================================================================
    {
        "id": "rule_8", "name": "新事件威胁评估规则", "category": "domain",
        "description": "当新事件被抽取入库后，基于事件类型和参与方自动评估威胁等级",
        "trigger_condition": "new_event_detected",
        "action_function": "func_13", "is_active": True,
    },
    {
        "id": "rule_9", "name": "事件后续研判规则", "category": "domain",
        "description": "分析当前事件可能引发的后续事件类型",
        "trigger_condition": "event_analysis_requested",
        "action_function": "func_14", "is_active": True,
    },
    {
        "id": "rule_10", "name": "事件持续时长估计规则", "category": "domain",
        "description": "根据事件类型和历史数据估算事件持续时长",
        "trigger_condition": "event_timeline_query",
        "action_function": "func_15", "is_active": True,
    },
    {
        "id": "rule_11", "name": "文本事件发现规则", "category": "domain",
        "description": "新文本入库后统计事件抽取覆盖情况",
        "trigger_condition": "text_ingested",
        "action_function": "func_16", "is_active": True,
    },
    {
        "id": "rule_12", "name": "事件关联分析规则", "category": "domain",
        "description": "检测到多个相关事件时，发现事件间的时序/参与方/地点关联",
        "trigger_condition": "multiple_events_detected",
        "action_function": "func_17", "is_active": True,
    },
]


def build_rules():
    """Create or reset Rule nodes in Neo4j and link to Functions."""
    driver = get_neo4j_driver()
    with driver.session() as s:
        s.run("MATCH (r:Rule) DETACH DELETE r")
        for rule in RULES:
            s.run(
                """
                CREATE (n:Rule {
                    id: $id, name: $name, description: $description,
                    trigger_condition: $trigger_condition, action_function: $action_function,
                    is_active: $is_active, category: $category, source: 'config'
                })
                """,
                id=rule["id"],
                name=rule["name"],
                description=rule["description"],
                trigger_condition=rule["trigger_condition"],
                action_function=rule["action_function"],
                is_active=rule["is_active"],
                category=rule.get("category", "construction"),
            )
            s.run(
                """
                MATCH (r:Rule {id: $rid}), (f:Function {id: $fid})
                CREATE (r)-[:TRIGGERS]->(f)
                """,
                rid=rule["id"],
                fid=rule["action_function"],
            )
    return {"rules_created": len(RULES)}


def get_rules(category=None):
    """Return list of Rule nodes, optionally filtered by category."""
    driver = get_neo4j_driver()
    if category:
        query = (
            "MATCH (r:Rule {category: $category}) "
            "OPTIONAL MATCH (r)-[:TRIGGERS]->(f:Function) "
            "RETURN r.id AS id, r.name AS name, r.description AS description, "
            "r.trigger_condition AS trigger_condition, r.action_function AS action_function, "
            "r.is_active AS is_active, r.source AS source, r.category AS category, "
            "f.name AS function_name ORDER BY r.id"
        )
        with driver.session() as s:
            rows = [dict(r) for r in s.run(query, category=category)]
    else:
        with driver.session() as s:
            rows = [
                dict(r)
                for r in s.run(
                    """
                    MATCH (r:Rule)
                    OPTIONAL MATCH (r)-[:TRIGGERS]->(f:Function)
                    RETURN r.id AS id, r.name AS name, r.description AS description,
                           r.trigger_condition AS trigger_condition,
                           r.action_function AS action_function,
                           r.is_active AS is_active, r.source AS source, r.category AS category,
                           f.name AS function_name ORDER BY r.id
                    """
                )
            ]
    return rows


def trigger_rule(rule_id):
    """Execute a rule by its ID. Supports extraction rules (1-3) and fusion rules (4-7)."""
    log.info("Triggering rule: %s", rule_id)
    rule = next((r for r in RULES if r["id"] == rule_id), None)
    if not rule:
        raise ValueError(f"Rule {rule_id} not found")

    action = rule["action_function"]

    # --- Extraction rules (1-3): LLM-based ---
    if action in ("func_5", "func_7", "func_8"):
        result = extract_from_text(SAMPLE_TEXT)
        if action == "func_5":
            filtered = {
                "concepts": result["concepts"],
                "concept_relations": result["concept_relations"],
            }
        elif action == "func_7":
            filtered = {"instances": result["instances"]}
        elif action == "func_8":
            filtered = {"instance_relations": result["instance_relations"]}
        else:
            filtered = result
        return {
            "rule_id": rule_id,
            "rule_name": rule["name"],
            "action_function": action,
            "result": filtered,
        }

    # --- Fusion rules (4-7): deduplication ---
    if action == "func_9":
        return {"rule_id": rule_id, "rule_name": rule["name"], "category": rule.get("category"),
                "action_function": action, "result": concept_fusion()}
    elif action == "func_10":
        return {"rule_id": rule_id, "rule_name": rule["name"], "category": rule.get("category"),
                "action_function": action, "result": concept_relation_fusion()}
    elif action == "func_11":
        return {"rule_id": rule_id, "rule_name": rule["name"], "category": rule.get("category"),
                "action_function": action, "result": instance_fusion()}
    elif action == "func_12":
        return {"rule_id": rule_id, "rule_name": rule["name"], "category": rule.get("category"),
                "action_function": action, "result": instance_relation_fusion()}

    # --- Domain rules (8-12): military analysis (simulated) ---
    if action in ("func_13", "func_14", "func_15", "func_16", "func_17"):
        from domain_functions import run_domain_function
        result = run_domain_function(action)
        return {"rule_id": rule_id, "rule_name": rule["name"], "category": rule.get("category"),
                "action_function": action, "result": result}

    raise ValueError(f"Unknown action function: {action}")


# ---------------------------------------------------------------------------
# Auto-trigger hooks — called by text_extractor after saving new data
# ---------------------------------------------------------------------------

def trigger_on_concept_save():
    """Auto-triggered after new concepts are saved via text extraction.
    Runs concept fusion (rule_4) to deduplicate."""
    log.info("Auto-trigger: concept fusion after concept save")
    result = concept_fusion()
    return {"triggered_by": "after_concept_save", "rule_ids": ["rule_4"], "result": result}


def trigger_on_concept_relation_save():
    """Auto-triggered after new concept relations are saved.
    Runs concept relation fusion (rule_5)."""
    log.info("Auto-trigger: concept relation fusion after relation save")
    result = concept_relation_fusion()
    return {"triggered_by": "after_concept_relation_save", "rule_ids": ["rule_5"], "result": result}


def trigger_on_instance_save():
    """Auto-triggered after new instances are saved.
    Runs instance fusion (rule_6)."""
    log.info("Auto-trigger: instance fusion after instance save")
    result = instance_fusion()
    return {"triggered_by": "after_instance_save", "rule_ids": ["rule_6"], "result": result}


def trigger_on_instance_relation_save():
    """Auto-triggered after new instance relations are saved.
    Runs instance relation fusion (rule_7)."""
    log.info("Auto-trigger: instance relation fusion after relation save")
    result = instance_relation_fusion()
    return {"triggered_by": "after_instance_relation_save", "rule_ids": ["rule_7"], "result": result}


def trigger_all_fusion():
    """Run all four fusion operations at once."""
    log.info("Auto-trigger: running all fusion operations")
    return run_all_fusion()

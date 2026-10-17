"""Function nodes representing extraction operations in the knowledge graph."""
from db import get_neo4j_driver

FUNCTIONS = [
    # =========================================================================
    # 构建类 (construction) — 知识图谱的抽取、构建、融合
    # =========================================================================
    # --- SQL来源 (order 1-4) ---
    {"id": "func_1", "name": "关系型数据库表概念构建", "category": "construction", "target_layer": "concept", "operation_type": "node", "description": "从MySQL实体表抽象出概念层节点", "order": 1},
    {"id": "func_2", "name": "关系型数据库表概念关系构建", "category": "construction", "target_layer": "concept", "operation_type": "relation", "description": "从MySQL外键和关系表抽象出概念层关系", "order": 2},
    {"id": "func_3", "name": "关系型数据库表实例数据抽取", "category": "construction", "target_layer": "instance", "operation_type": "node", "description": "从MySQL实体表记录抽取实例节点", "order": 3},
    {"id": "func_4", "name": "关系型数据库表实例关系抽取", "category": "construction", "target_layer": "instance", "operation_type": "relation", "description": "从MySQL外键和关联表抽取实例关系", "order": 4},
    # --- 文本来源 (order 5-8) ---
    {"id": "func_5", "name": "基于文本的概念抽取", "category": "construction", "target_layer": "concept", "operation_type": "node", "description": "使用大模型从非结构化文本中抽取概念", "order": 5},
    {"id": "func_6", "name": "基于文本的概念关系抽取", "category": "construction", "target_layer": "concept", "operation_type": "relation", "description": "使用大模型从文本中抽取概念之间的关系", "order": 6},
    {"id": "func_7", "name": "基于文本的实例抽取", "category": "construction", "target_layer": "instance", "operation_type": "node", "description": "使用大模型从文本中抽取具体实例", "order": 7},
    {"id": "func_8", "name": "基于文本的实例关系抽取", "category": "construction", "target_layer": "instance", "operation_type": "relation", "description": "使用大模型从文本中抽取实例之间的关系", "order": 8},
    # --- 知识融合 (order 9-12) ---
    {"id": "func_9", "name": "概念融合", "category": "construction", "target_layer": "concept", "operation_type": "node", "description": "合并重复/同义的概念节点，消除概念层冗余", "order": 9},
    {"id": "func_10", "name": "概念关系融合", "category": "construction", "target_layer": "concept", "operation_type": "relation", "description": "合并概念层重复的关系边", "order": 10},
    {"id": "func_11", "name": "实例融合", "category": "construction", "target_layer": "instance", "operation_type": "node", "description": "合并同名/同义的实例节点，消除实例层冗余", "order": 11},
    {"id": "func_12", "name": "实例关系融合", "category": "construction", "target_layer": "instance", "operation_type": "relation", "description": "合并实例间重复的关系边", "order": 12},
    # =========================================================================
    # 领域类 (domain) — 军事领域分析功能
    # =========================================================================
    {"id": "func_13", "name": "事件威胁等级分析", "category": "domain", "target_layer": "instance", "operation_type": "analysis", "description": "基于事件类型和参与方评估威胁等级", "order": 13},
    {"id": "func_14", "name": "事件后续进展研判", "category": "domain", "target_layer": "instance", "operation_type": "analysis", "description": "基于事件类型研判可能的后续进展", "order": 14},
    {"id": "func_15", "name": "事件持续时间计算", "category": "domain", "target_layer": "instance", "operation_type": "analysis", "description": "根据事件类型估算持续时长范围", "order": 15},
    {"id": "func_16", "name": "自然语言事件抽取统计", "category": "domain", "target_layer": "instance", "operation_type": "analysis", "description": "统计CMNEE文本的事件抽取覆盖情况", "order": 16},
    {"id": "func_17", "name": "事件关系分析", "category": "domain", "target_layer": "instance", "operation_type": "analysis", "description": "发现共享参与方/地点/装备的事件关联", "order": 17},
]


def build_functions():
    """Create or reset Function nodes in Neo4j."""
    driver = get_neo4j_driver()
    with driver.session() as s:
        s.run("MATCH (f:Function) DETACH DELETE f")
        for fn in FUNCTIONS:
            s.run(
                """
                CREATE (n:Function {
                    id: $id, name: $name, category: $category,
                    target_layer: $target_layer, operation_type: $operation_type,
                    description: $description, order: $order, source: 'config'
                })
                """,
                **fn,
            )
    return {"functions_created": len(FUNCTIONS)}


def get_functions(category=None):
    """Return list of Function nodes, optionally filtered by category."""
    driver = get_neo4j_driver()
    if category:
        query = (
            "MATCH (f:Function {category: $category}) "
            "RETURN f.id AS id, f.name AS name, f.category AS category, "
            "f.target_layer AS target_layer, f.operation_type AS operation_type, "
            "f.description AS description, f.order AS order, f.source AS source "
            "ORDER BY f.order"
        )
        with driver.session() as s:
            rows = [dict(r) for r in s.run(query, category=category)]
    else:
        with driver.session() as s:
            rows = [
                dict(r)
                for r in s.run(
                    "MATCH (f:Function) RETURN f.id AS id, f.name AS name, "
                    "f.category AS category, f.target_layer AS target_layer, "
                    "f.operation_type AS operation_type, f.description AS description, "
                    "f.order AS order, f.source AS source ORDER BY f.order"
                )
            ]
    return rows


def get_function_graph():
    """Return Function nodes as D3 graph format."""
    driver = get_neo4j_driver()
    with driver.session() as s:
        nodes = [
            dict(r)
            for r in s.run(
                "MATCH (f:Function) RETURN f.id AS id, f.name AS name, "
                "f.category AS category, f.target_layer AS target_layer, "
                "f.operation_type AS operation_type, f.description AS description, "
                "f.order AS order, f.source AS source ORDER BY f.order"
            )
        ]
        # Add category grouping edges and group nodes
        edges = []
        categories = {}
        CATEGORY_LABELS = {
            "construction": "知识构建",
            "domain": "领域分析",
        }
        for n in nodes:
            cat = n.get("category", "construction")
            if cat and cat not in categories:
                categories[cat] = f"cat_{cat}"
                edges.append({"source": f"cat_{cat}", "target": n["id"], "label": "属于", "type": "BELONGS_TO"})
            elif cat:
                edges.append({"source": f"cat_{cat}", "target": n["id"], "label": "属于", "type": "BELONGS_TO"})
        # Add category group nodes
        for cat, cid in categories.items():
            nodes.append({
                "id": cid,
                "name": CATEGORY_LABELS.get(cat, cat),
                "category": "group",
                "target_layer": "group",
                "operation_type": "group",
                "description": "",
                "order": 0,
                "source": "config",
            })
    return {"nodes": nodes, "edges": edges}

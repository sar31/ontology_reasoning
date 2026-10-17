"""QA over MySQL: NL2SQL directly queries MySQL and generates answers."""
import json
import logging
import re

from db import get_mysql_conn
from llm_client import call_qwen

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema description for NL2SQL
# ---------------------------------------------------------------------------

SCHEMA_TABLES = [
    {
        "table": "countries_regions",
        "description": "国家/地区",
        "columns": [
            ("id", "int", "主键"),
            ("name", "varchar", "中文名称"),
            ("name_en", "varchar", "英文名称"),
            ("code", "varchar", "国家代码"),
            ("continent", "varchar", "所在洲"),
            ("region_type", "enum", "类型: country/region/international_organization"),
            ("description", "text", "描述"),
        ],
    },
    {
        "table": "persons",
        "description": "人员",
        "columns": [
            ("id", "int", "主键"),
            ("full_name", "varchar", "全名(中文)"),
            ("name_en", "varchar", "英文名"),
            ("nationality_id", "int", "国籍ID → countries_regions.id"),
            ("role", "enum", "角色: political_leader/military_commander/intelligence_officer/terrorist/diplomat/other"),
            ("rank_title", "varchar", "军衔/职位"),
            ("current_status", "enum", "状态: active/detained/deceased/missing/retired"),
            ("threat_level", "enum", "威胁级别: low/medium/high/critical"),
            ("biography", "text", "简介"),
        ],
    },
    {
        "table": "organizations",
        "description": "组织",
        "columns": [
            ("id", "int", "主键"),
            ("name", "varchar", "中文名称"),
            ("name_en", "varchar", "英文名称"),
            ("abbreviation", "varchar", "缩写"),
            ("org_type", "enum", "类型: government/military/intelligence/terrorist/rebel/corporate/ngo/media/other"),
            ("country_id", "int", "所属国家ID → countries_regions.id"),
            ("ideology", "varchar", "意识形态"),
            ("threat_level", "enum", "威胁级别: low/medium/high/critical"),
            ("description", "text", "描述"),
        ],
    },
    {
        "table": "equipments",
        "description": "装备",
        "columns": [
            ("id", "int", "主键"),
            ("name", "varchar", "中文名称"),
            ("name_en", "varchar", "英文名称"),
            ("equipment_type", "enum", "类型: aircraft/naval_vessel/ground_vehicle/missile/firearm/artillery/radar_system/electronic_warfare/drone/nuclear/chemical/biological/cyber_weapon/other"),
            ("sub_type", "varchar", "子类型"),
            ("manufacturer", "varchar", "制造商"),
            ("origin_country_id", "int", "原产国ID → countries_regions.id"),
            ("operator_country_id", "int", "使用国ID → countries_regions.id"),
            ("status", "enum", "状态: active/retired/destroyed/captured/under_development"),
            ("quantity", "int", "数量"),
            ("capabilities", "text", "能力描述"),
            ("threat_level", "enum", "威胁级别: low/medium/high/critical"),
        ],
    },
    {
        "table": "facilities",
        "description": "设施",
        "columns": [
            ("id", "int", "主键"),
            ("name", "varchar", "中文名称"),
            ("name_en", "varchar", "英文名称"),
            ("facility_type", "enum", "类型: military_base/naval_base/air_base/missile_site/radar_station/command_center/intelligence_facility/nuclear_facility/chemical_plant/oil_refinery/port/airport/government_building/power_plant/communication_hub/other"),
            ("country_id", "int", "所在国家ID → countries_regions.id"),
            ("strategic_importance", "enum", "战略重要性: low/medium/high/critical"),
            ("status", "enum", "状态: operational/non_operational/destroyed/captured/under_construction"),
            ("description", "text", "描述"),
        ],
    },
    {
        "table": "events",
        "description": "事件",
        "columns": [
            ("id", "int", "主键"),
            ("title", "varchar", "事件标题"),
            ("event_type", "enum", "类型: military_conflict/terrorist_attack/political_crisis/diplomatic_tension/cyber_attack/intelligence_operation/military_exercise/weapon_test/border_incident/assassination/kidnapping/protest/coup_attempt/ceasefire_violation/sanctions/other"),
            ("severity", "enum", "严重性: low/medium/high/critical/catastrophic"),
            ("status", "enum", "状态: ongoing/concluded/investigating/unconfirmed"),
            ("start_time", "datetime", "开始时间"),
            ("end_time", "datetime", "结束时间"),
            ("primary_location", "varchar", "主要地点"),
            ("country_id", "int", "国家ID → countries_regions.id"),
            ("casualties_killed", "int", "死亡人数"),
            ("casualties_injured", "int", "受伤人数"),
            ("reliability", "enum", "可靠性: confirmed/likely/possible/unlikely/false"),
            ("summary", "text", "摘要"),
            ("detailed_description", "text", "详细描述"),
        ],
    },
    {
        "table": "event_persons",
        "description": "事件-人员关联",
        "columns": [
            ("id", "int", "主键"),
            ("event_id", "int", "事件ID → events.id"),
            ("person_id", "int", "人员ID → persons.id"),
            ("role", "enum", "角色: commander/perpetrator/victim/negotiator/witness/target/other"),
            ("involvement_description", "text", "参与描述"),
        ],
    },
    {
        "table": "event_organizations",
        "description": "事件-组织关联",
        "columns": [
            ("id", "int", "主键"),
            ("event_id", "int", "事件ID → events.id"),
            ("organization_id", "int", "组织ID → organizations.id"),
            ("role", "enum", "角色: attacker/defender/victim/mediator/supporter/observer/other"),
            ("involvement_description", "text", "参与描述"),
        ],
    },
    {
        "table": "event_equipments",
        "description": "事件-装备关联",
        "columns": [
            ("id", "int", "主键"),
            ("event_id", "int", "事件ID → events.id"),
            ("equipment_id", "int", "装备ID → equipments.id"),
            ("usage_type", "enum", "使用类型: used_by_attacker/used_by_defender/destroyed/captured/observed/other"),
            ("quantity", "int", "数量"),
        ],
    },
    {
        "table": "event_facilities",
        "description": "事件-设施关联",
        "columns": [
            ("id", "int", "主键"),
            ("event_id", "int", "事件ID → events.id"),
            ("facility_id", "int", "设施ID → facilities.id"),
            ("impact_type", "enum", "影响类型: attacked/defended/damaged/destroyed/captured/used_as_base/target/other"),
        ],
    },
]


def _build_schema_text():
    lines = ["=== MySQL Schema (数据库 benti) ==="]
    for t in SCHEMA_TABLES:
        lines.append(f"\n-- {t['description']} ({t['table']})")
        for col_name, col_type, col_desc in t["columns"]:
            lines.append(f"  {col_name} {col_type}  -- {col_desc}")
    return "\n".join(lines)


_SCHEMA_TEXT = _build_schema_text()

# ---------------------------------------------------------------------------
# NL2SQL
# ---------------------------------------------------------------------------

NL2SQL_PROMPT = f"""你是MySQL查询专家。根据用户问题生成只读SQL查询。

数据库Schema：
{_SCHEMA_TEXT}

重要规则：
1. 只生成 SELECT 语句，绝对禁止 INSERT / UPDATE / DELETE / DROP / CREATE / ALTER / TRUNCATE
2. 使用 JOIN 关联表，关联关系见各列注释中的 → 指向
3. 中文搜索使用 LIKE '%关键词%'
4. 英文名称搜索使用 name_en 列
5. 日期过滤使用 start_time 列
6. 默认 LIMIT 20
7. 对于聚合查询，使用 GROUP BY / COUNT / SUM 等
8. 请严格按JSON输出：{{"sql": "...", "explanation": "简要说明查询目的"}}
9. 不要输出任何其他内容，只输出JSON"""

# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

FORBIDDEN_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER",
    "TRUNCATE", "GRANT", "REVOKE", "EXEC", "EXECUTE", "CALL",
    "LOAD", "INTO OUTFILE", "INTO DUMPFILE", "SOURCE",
]


def _validate_sql(sql: str) -> bool:
    upper = sql.upper()
    for kw in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", upper):
            log.error("Forbidden SQL keyword: %s", kw)
            return False
    return True


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def ask(question: str) -> dict:
    """Ask a question using NL2SQL approach (Method 6)."""
    if not question or len(question.strip()) < 2:
        return {"answer": "问题太短", "method": "sql", "sources": []}

    # 1. NL -> SQL
    raw = call_qwen(NL2SQL_PROMPT, f"问题：{question}", temperature=0.1)
    sql = ""
    if isinstance(raw, dict):
        sql = raw.get("sql", "").strip()
        if sql.startswith("```"):
            sql = re.sub(r"^```\w*", "", sql)
            sql = re.sub(r"```$", "", sql)
            sql = sql.strip()

    if not sql:
        return {"answer": "无法生成有效SQL查询", "method": "sql", "sources": []}

    if not _validate_sql(sql):
        return {"answer": "生成的SQL不安全，已被拦截", "method": "sql", "sql": sql, "sources": []}

    log.info("Generated SQL: %s", sql)

    # 2. Execute SQL
    try:
        conn = get_mysql_conn()
        with conn.cursor() as cur:
            cur.execute(sql)
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()
        conn.close()
    except Exception as e:
        log.error("SQL execution failed: %s", e)
        return {"answer": f"SQL执行失败: {e}", "method": "sql", "sql": sql, "sources": []}

    # 3. Format results
    results = []
    for row in rows:
        if isinstance(row, dict):
            results.append({k: str(v) if v is not None else "" for k, v in row.items()})
        else:
            results.append(dict(zip(columns, [str(v) if v is not None else "" for v in row])))

    # 4. Generate answer from results
    context_text = json.dumps(results[:20], ensure_ascii=False, indent=2)
    answer_prompt = f"""你是知识库问答助手。请基于SQL查询结果，用中文简洁回答用户问题。

问题：{question}

SQL：{sql}

查询结果（共{len(results)}条）：
{context_text[:3000]}

要求：
1. 基于数据回答，不编造
2. 如果结果为空，明确说明"未找到相关数据"
3. 简洁准确，必要使用列表

请按JSON输出：{{"answer": "...", "sources": ["数据来源"]}}
只输出JSON。"""

    try:
        answer_raw = call_qwen("你是有帮助的问答助手。", answer_prompt, temperature=0.3)
        if isinstance(answer_raw, dict):
            return {
                "answer": answer_raw.get("answer", "答案生成失败"),
                "method": "sql",
                "sql": sql,
                "result_count": len(results),
                "results": results[:10],
                "sources": answer_raw.get("sources", []),
            }
    except Exception as e:
        log.error("Answer generation failed: %s", e)

    return {
        "answer": f"查询结果（共{len(results)}条）：\n" + context_text[:1000],
        "method": "sql",
        "sql": sql,
        "result_count": len(results),
        "results": results[:10],
        "sources": [],
    }

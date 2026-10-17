"""OpenAI-compatible client for DeepSeek API."""
import os
import json
import logging

from openai import OpenAI

log = logging.getLogger(__name__)

# DeepSeek V4 Flash configuration.
# The API key is read from the environment; never commit a key to this repository.
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"

_client = None


def get_client():
    global _client
    if _client is None:
        api_key = os.getenv("LLM_API_KEY")
        if not api_key:
            raise RuntimeError(
                "LLM_API_KEY is not set. Export your own key before running the "
                "LLM-dependent pipelines, e.g. `export LLM_API_KEY=<your-key>`."
            )
        _client = OpenAI(
            api_key=api_key,
            base_url=os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL),
        )
    return _client


def call_llm(system_prompt, user_prompt, model=None, temperature=0.1):
    """Call LLM API and return parsed JSON response."""
    client = get_client()
    model = model or os.getenv("LLM_MODEL", DEFAULT_MODEL)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        log.info("LLM raw response length: %d", len(content))
        return json.loads(content)
    except Exception as e:
        log.error("LLM call failed: %s", e)
        raise


# Backward-compatible alias
call_qwen = call_llm


EXTRACTION_SYSTEM_PROMPT = """你是知识图谱抽取专家。请从用户提供的新闻文本中抽取知识图谱数据。

已有概念类型（优先复用）：Country(国家/地区), Person(人员), Organization(组织), Equipment(装备), Facility(设施), Event(事件)

请严格按以下JSON格式输出，不要添加任何解释：
{
  "concepts": [
    {"name": "英文概念名", "label": "中文标签", "description": "概念描述"}
  ],
  "concept_relations": [
    {"source": "源概念英文名", "target": "目标概念英文名", "name": "关系英文代号", "label": "中文关系名"}
  ],
  "instances": [
    {"label": "概念英文名", "name": "实例名称", "properties": {"key": "value"}}
  ],
  "instance_relations": [
    {"source_name": "源实例名", "source_label": "源概念", "target_name": "目标实例名", "target_label": "目标概念", "relation_type": "关系类型", "properties": {}}
  ]
}

注意：
1. 优先复用已有概念类型，如果文本中出现全新概念可新增
2. 实例名称使用文本中出现的具体名称
3. 关系类型尽量使用已有类型，如PART_OF, NATIONAL_OF, BELONGS_TO, INVOLVED_IN等
4. 只输出JSON，不要任何其他文字"""

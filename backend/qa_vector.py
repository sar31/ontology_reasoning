"""QA Method 2: Vector search + MySQL Schema enhanced RAG."""
import json
import logging

from llm_client import call_qwen
from vector_store import search as vector_search
from qa_sql import _build_schema_text

log = logging.getLogger(__name__)

ANSWER_PROMPT = """你是知识问答助手。请基于检索到的文本片段和数据库Schema信息，用中文回答用户问题。

数据库Schema（供参考，了解有哪些表和列）：
{schema}

检索到的相关文本片段：
{texts}

回答规则：
1. 优先基于文本片段回答
2. 如果文本片段信息不足，可以结合Schema信息判断问题的类型
3. 答案必须基于提供的数据，不要编造
4. 如果信息不足，明确说明"根据现有数据无法回答"
5. 在回答末尾列出引用的数据来源

请按JSON输出：{{"answer": "...", "sources": ["来源1", "来源2"]}}
只输出JSON。"""


def ask(question: str, top_k: int = 5) -> dict:
    """Ask using vector search + MySQL Schema (Method 2)."""
    if not question or len(question.strip()) < 2:
        return {"answer": "问题太短", "method": "vector_mysql", "sources": []}

    # 1. Vector search
    chunks = vector_search(question, top_k=top_k)

    # 2. Build context
    schema_text = _build_schema_text()

    if chunks:
        text_context = "\n\n---\n".join(
            f"[片段 {i+1}] (来源: {c['metadata'].get('source_id', 'unknown')})\n{c['document'][:800]}"
            for i, c in enumerate(chunks)
        )
    else:
        text_context = "（向量数据库为空，未检索到相关文本。请基于Schema信息判断问题类型并说明无法回答。）"

    # 3. Generate answer
    prompt = ANSWER_PROMPT.format(schema=schema_text[:2000], texts=text_context[:3000])
    try:
        raw = call_qwen("你是知识问答助手。", f"问题：{question}\n\n{prompt}", temperature=0.3)
        if isinstance(raw, dict):
            return {
                "answer": raw.get("answer", ""),
                "method": "vector_mysql",
                "sources": raw.get("sources", []),
                "retrieved_chunks": len(chunks),
            }
    except Exception as e:
        log.error("Vector+MySQL QA failed: %s", e)

    return {
        "answer": "答案生成失败",
        "method": "vector_mysql",
        "sources": [],
        "retrieved_chunks": len(chunks),
    }

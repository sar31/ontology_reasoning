"""QA Method 4: Pure vector RAG (no structured data)."""
import json
import logging

from llm_client import call_qwen
from vector_store import search as vector_search

log = logging.getLogger(__name__)

ANSWER_PROMPT = """你是知识问答助手。请仅基于检索到的文本片段，用中文回答用户问题。

检索到的相关文本片段：
{texts}

回答规则：
1. 严格基于提供的文本片段回答，不要编造任何信息
2. 如果文本片段不足以回答问题，明确说明"根据现有文本数据无法回答"
3. 回答简洁、准确
4. 在回答末尾列出引用的文本来源

请按JSON输出：{{"answer": "...", "sources": ["来源1", "来源2"]}}
只输出JSON。"""


def ask(question: str, top_k: int = 5) -> dict:
    """Ask using pure vector search (Method 4)."""
    if not question or len(question.strip()) < 2:
        return {"answer": "问题太短", "method": "vector_only", "sources": []}

    # 1. Vector search
    chunks = vector_search(question, top_k=top_k)

    # 2. Build context
    if chunks:
        text_context = "\n\n---\n".join(
            f"[片段 {i+1}] (来源: {c['metadata'].get('source_id', 'unknown')})\n{c['document'][:800]}"
            for i, c in enumerate(chunks)
        )
    else:
        return {
            "answer": "向量数据库中暂无文本数据，无法回答。请先导入文本数据。",
            "method": "vector_only",
            "sources": [],
            "retrieved_chunks": 0,
        }

    # 3. Generate answer
    prompt = ANSWER_PROMPT.format(texts=text_context[:3500])
    try:
        raw = call_qwen("你是知识问答助手。", f"问题：{question}\n\n{prompt}", temperature=0.3)
        if isinstance(raw, dict):
            return {
                "answer": raw.get("answer", ""),
                "method": "vector_only",
                "sources": raw.get("sources", []),
                "retrieved_chunks": len(chunks),
            }
    except Exception as e:
        log.error("Vector-only QA failed: %s", e)

    return {
        "answer": "答案生成失败",
        "method": "vector_only",
        "sources": [],
        "retrieved_chunks": len(chunks),
    }

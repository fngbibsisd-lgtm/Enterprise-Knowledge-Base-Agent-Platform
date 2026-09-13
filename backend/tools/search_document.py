"""
工具：knowledge_search / get_document —— Agent 调用它们检索知识库文档。

knowledge_search 返回格式：{"found": bool, "sources": [{id, source, text, score}], "summary": str}
get_document 返回格式：{"found": bool, "source": str, "text": str, "summary": str}

上下文保护：预算集中在 core/tool_output.py（按工具分档）。工具层负责把返回体组织到预算之内，
executor 再渲染一次做兜底——工具层若超预算，executor 一截，文本就可能被从中间切断。
"""
from backend.core.config import get_settings
from backend.core.tool_output import MAX_TOP_K, MIN_ITEM_TEXT_CHARS, tool_result_limit, truncate
from backend.services import rag


async def knowledge_search_fn(
    query: str,
    top_k: int | None = None,
    source: str | None = None,
) -> dict:
    """搜索知识库文档，返回命中条目的文本（带引文 id，供最终回答用 [n] 标注）。"""
    settings = get_settings()
    try:
        requested = int(top_k) if top_k is not None else settings.agent_top_k
    except (TypeError, ValueError):
        requested = settings.agent_top_k  # 模型给了非数字,退回默认而不是报错浪费一轮
    requested = max(1, min(requested, MAX_TOP_K))

    result = await rag.search(query, settings, top_k=requested, source=source)
    if not result:
        return {"found": False, "sources": [], "summary": "未找到相关资料"}

    # 预算按条数分摊:limit 是整条结果的预算,不是每个片段的预算。
    # 若每个片段都给 limit,8 条就是 8×6000,executor 一截只剩第 1 条
    limit = tool_result_limit("knowledge_search", settings)
    per_chunk = max(MIN_ITEM_TEXT_CHARS, (limit - 300) // len(result))
    sources = [
        {
            "id": r.get("id"),
            "source": r.get("source", ""),
            "text": truncate(r.get("text", ""), per_chunk),
            "score": round(float(r.get("score", 0.0)), 4),
        }
        for r in result
    ]
    return {"found": True, "sources": sources, "summary": f"共找到{len(sources)}条相关资料"}


async def get_document_fn(source: str) -> dict:
    """读取指定文档全文（用于需要完整上下文的追问），软截断保护。"""
    settings = get_settings()
    doc = await rag.get_document_by_source(source, settings)
    text = (doc.get("text") or "").strip()
    if not text:
        return {"found": False, "source": source, "text": "", "summary": "未找到该文档"}
    limit = tool_result_limit("get_document", settings)
    return {
        "found": True,
        "source": source,
        "text": truncate(text, limit),
        "summary": f"文档《{source}》共{len(text)}字",
    }

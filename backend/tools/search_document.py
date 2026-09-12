"""
工具：knowledge_search / get_document —— Agent 调用它们检索知识库文档。

knowledge_search 返回格式：{"found": bool, "sources": [{id, source, text, score}], "summary": str}
get_document 返回格式：{"found": bool, "source": str, "text": str, "summary": str}

上下文保护：文本在工具层做软截断，执行器 executor 再统一做最终截断（agent_tool_result_max_chars）。
"""
from backend.core.config import get_settings
from backend.services import rag


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"...(截断,原文共{len(text)}字)"


async def knowledge_search_fn(
    query: str,
    top_k: int | None = None,
    source: str | None = None,
) -> dict:
    """搜索知识库文档，返回命中条目的文本（带稳定引文 id，供最终回答用 [n] 标注）。"""
    settings = get_settings()
    result = await rag.search(query, settings, top_k=top_k, source=source)
    if not result:
        return {"found": False, "sources": [], "summary": "未找到相关资料"}
    limit = settings.agent_tool_result_max_chars
    sources = [
        {
            "id": r.get("id"),
            "source": r.get("source", ""),
            "text": _truncate(r.get("text", ""), limit),
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
    limit = settings.agent_tool_result_max_chars * 4
    return {
        "found": True,
        "source": source,
        "text": _truncate(text, limit),
        "summary": f"文档《{source}》共{len(text)}字",
    }

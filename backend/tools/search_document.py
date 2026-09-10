"""
工具：knowledge_search —— Agent 调用它检索知识库文档。

返回格式：{"found": bool, "sources": [...], "summary": str}
"""
from backend.core.config import get_settings
from backend.services import rag


async def knowledge_search_fn(query: str) -> dict:
    """搜索知识库文档，返回 {"found": bool, "sources": [...], "summary": str}。"""
    settings = get_settings()
    result = await rag.search(query, settings)
    if not result:
        return {"found": False, "sources": [], "summary": "未找到相关资料"}
    return {"found": True, "sources": result, "summary": f"共找到{len(result)}条相关资料"}

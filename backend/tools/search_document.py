"""
工具：knowledge_search — Agent 调用它检索知识库文档。

返回格式：{"found": bool, "sources": [...], "summary": str}
"""

from backend.config import Config
from backend.services import rag
def knowledge_search_fn(query: str) -> dict:
    """
    搜索知识库文档，返回 {"found": bool, "sources": [...], "summary": str}。
    """
    config=Config()
    result=rag.search(query, config)
    if not result:
        return {"found":False, "sources":[], "summary":"未找到相关资料"}
    else:
        return {"found":True, "sources":result, "summary":f"共找到{len(result)}条相关资料"}


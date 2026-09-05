"""
Agent 工具定义

定义 Function Calling schema（tools 参数），告诉 LLM 有哪些工具可用、每个工具的参数格式；
并提供 get_tool_map() 把工具名映射到实际执行函数。
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "knowledge_search",
            "description": "搜索企业内部知识库文档,获取相关资料,当用户询问制度,流程,规定等文档类问题时使用此工具",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或问题,用自然语言描述要查找的内容"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "sql_query",
            "description": "搜索企业内部的结构化数据(上传记录,聊天记录),当用户询问统计,计数,历史记录等问题时使用,例如:'最近上传了几个文件','今天聊天次数'",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "要执行的SQL查询语句,只允许SELECT语句。可查询的两张表及其字段: uploaded_files(filename, md5_hash, chunk_count, created_at); chat_history(query, answer, sources, created_at)"
                    }
                },
                "required": ["sql"]
            }
        }
    },
]


def get_tool_map():
    """
    返回工具名 → 工具函数的映射字典，供 executor.py 根据 LLM 返回的工具名调用对应函数。
    """
    from backend.tools.search_document import knowledge_search_fn
    from backend.tools.query_database import sql_query_fn
    return {
        "knowledge_search": knowledge_search_fn,
        "sql_query": sql_query_fn
    }

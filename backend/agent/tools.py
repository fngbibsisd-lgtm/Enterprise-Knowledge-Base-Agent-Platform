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
            "description": (
                "搜索企业内部知识库文档,获取相关资料。当用户询问制度、流程、规定等文档类问题时使用。"
                "返回带稳定编号(id)的文档片段,最终回答需用 [id] 标注引用来源。"
                "若需要某文档的完整内容,先用本工具找到文档名,再调用 get_document。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或问题,用自然语言描述要查找的内容"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回的文档条数,默认8,最多10"
                    },
                    "source": {
                        "type": "string",
                        "description": "可选,按文件名过滤,只返回该文档的内容"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_document",
            "description": (
                "读取指定文档的内容,当需要某份文档的详细上下文时使用,参数 source 为文档文件名。"
                "长文档会分页返回:返回里 total_chars 是全文长度,has_more 为 true 表示还有内容,"
                "把返回的 next_offset 作为 offset 再次调用即可续读(不要自己算偏移)"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "文档文件名,例如 '2024年工作报告.pdf'"
                    },
                    "offset": {
                        "type": "integer",
                        "description": "从第几个字符开始读,默认0(从头读);续读时直接传上一次返回的 next_offset"
                    }
                },
                "required": ["source"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_tables",
            "description": "查看数据库中有哪些表及其字段结构,在写 SQL 之前先调用它了解表结构",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "sql_query",
            "description": (
                "查询企业结构化数据(上传记录、聊天记录等),当用户询问统计、计数、历史记录等问题时使用,"
                "例如:'最近上传了几个文件'。只允许单条SELECT语句,先调用 list_tables 了解表结构再写SQL"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "要执行的SELECT查询语句,只允许单条SELECT,不写LIMIT会自动补上限"
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
    from backend.tools.query_database import list_tables_fn, sql_query_fn
    from backend.tools.search_document import get_document_fn, knowledge_search_fn
    return {
        "knowledge_search": knowledge_search_fn,
        "get_document": get_document_fn,
        "list_tables": list_tables_fn,
        "sql_query": sql_query_fn,
    }


async def get_all_tools() -> tuple[list[dict], dict]:
    """合并手写工具 + MCP 工具，返回 (OpenAI schema 列表, 工具名→函数映射)。

    executor 用它取代「直接读 TOOLS / get_tool_map」，从而支持 MCP 动态工具。

    MCP 是可选能力，两条降级路径都不影响手写工具可用：
        - 没装 mcp 包（ImportError）
        - 装了但 server 连不上（get_mcp_tools 内部已兜底，返回空）
    """
    schema = list(TOOLS)
    tool_map = get_tool_map()
    try:
        from examples.mcp import mcp_client
    except ImportError as e:
        print(f"[MCP] 未安装 mcp 依赖，跳过 MCP 工具（pip install mcp 可启用）：{e}")
        return schema, tool_map

    mcp_schema, mcp_callables = await mcp_client.get_mcp_tools()
    schema.extend(mcp_schema)
    tool_map.update(mcp_callables)
    return schema, tool_map

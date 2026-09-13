"""
工具输出的预算与渲染 —— 全项目唯一出处。

为什么单独建一个叶子模块（不放在 agent/executor.py）：
    executor 要截断工具结果，tools/search_document.py 自己也要按预算组织返回体，
    而 executor.py 已经 `from backend.agent.tools import ...`。若把这两个函数留在 executor，
    tools 反向 import 就会形成循环。所以放到最底层的 core，双方都只依赖它。

两层截断的分工（**自洽是硬要求**）：
    - 工具层：按「整条结果」预算组织返回体，保证序列化后不超预算
      （get_document 的分页 next_offset 就建立在这个保证上；工具层若超预算，
       executor 一截，next_offset 可能落在被切掉的部分，模型照着跳就跳错）
    - executor：render_tool_result 再渲染一次，正常情况不触发截断，只是兜底

结构化结果（knowledge_search 的 sources 列表）走「逐条裁剪」而非文本截断：
    JSON 被从中间切断会让模型读到半条记录，甚至把 "score": 0.1234 截成 "score": 0.12，
    静默给出错误信息。宁可少给几条，也要保证模型看到的是合法 JSON。
"""
import json

# 单条 chunk 的最低字数：低于这个数就不如少给几条，否则每条只剩标题没内容
MIN_ITEM_TEXT_CHARS = 200

# JSON 外壳（found/summary/键名/引号）预留，避免按条数切分时刚好溢出
_ENVELOPE_RESERVE = 300

# knowledge_search 的 top_k 上限（与 tools.py 的 schema 描述一致）
MAX_TOP_K = 10


def tool_result_limit(tool_name: str, settings) -> int:
    """某工具「整条结果」的字符预算。

    按工具区分而不是一刀切：一条 knowledge_search 结果里通常有 5-8 个片段，
    一条 get_document 结果是一整篇文档，二者需要的大小完全不同。
    agent_tool_result_max_chars 保留作兜底（sql_query/list_tables/MCP 动态工具走它）。
    """
    if tool_name == "knowledge_search":
        return settings.agent_search_result_max_chars
    if tool_name == "get_document":
        return settings.agent_document_result_max_chars
    return settings.agent_tool_result_max_chars


def serialize(result) -> str:
    """把工具返回结果转成字符串(dict 转 JSON)。"""
    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False, default=str)
    return str(result)


def truncate(text: str, limit: int) -> str:
    """把文本截断到**至多** limit 字符，防止撑爆上下文。

    后缀也算在 limit 内：调用方（工具预算、分页）把 limit 当硬上限用，
    若返回 limit+17 就会让「序列化后不超预算」这条不变量在最外层失守。
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    note = f"...(已截断,原文{len(text)}字)"
    return text[: max(0, limit - len(note))] + note


def render_tool_result(name: str, result, settings) -> tuple[str, dict | None]:
    """渲染进 messages 的工具结果。

    返回 (给模型看的文本, 模型真正看到的那个结果 dict)。

    第二个返回值给 executor 收集 sources 事件用。executor 原来从**未截断**的原始 result
    里收来源，一旦结构化裁剪丢掉尾部条目，UI 的来源清单就会出现模型根本没看到的文档；
    返回 None 表示「这份文本已被从中间切断，别拿它去收来源」。
    """
    limit = tool_result_limit(name, settings)
    if isinstance(result, dict) and isinstance(result.get("sources"), list):
        return _render_list_result(result, limit)
    return truncate(serialize(result), limit), (result if isinstance(result, dict) else None)


def _render_list_result(result: dict, limit: int) -> tuple[str, dict | None]:
    """逐条裁剪 sources，保证序列化结果不超过 limit 且始终是合法 JSON。

    策略：先按「均分预算」把每条文本收紧，再逐条丢尾。每次都从**原文**重新截断
    （不是在上一次的结果上再截），否则会叠出两层"...(已截断)"后缀、且文本被反复砍。
    条数 ≤ 10，外层最多重试 11 次，代价可忽略。
    """
    items = [dict(i) for i in result["sources"] if isinstance(i, dict)]
    total = len(items)
    if total == 0:
        return truncate(serialize(result), limit), result

    for shown in range(total, 0, -1):
        kept = items[:shown]
        per_text = max(MIN_ITEM_TEXT_CHARS, (limit - _ENVELOPE_RESERVE) // shown)
        for item in kept:
            item["text"] = truncate(item.get("text", ""), per_text)
        visible = {**result, "sources": kept, "summary": _trimmed_summary(result, shown, total)}
        text = serialize(visible)
        if len(text) <= limit:
            return text, visible

    # 兜底：连一条的最低字数都放不下（外壳字段异常大），最后手段才是切断 JSON。
    # 这时 JSON 已不合法，无法判断模型到底看到哪几条，故返回 None（宁可不收来源）
    return truncate(serialize(result), limit), None


def _trimmed_summary(result: dict, shown: int, total: int) -> str:
    """裁剪后的 summary —— 让模型知道自己看到的是部分结果，别把"只有 3 条"当成事实。"""
    if shown == total:
        return result.get("summary") or f"共找到{total}条相关资料"
    return f"共找到{total}条相关资料,因长度限制仅展示前{shown}条"

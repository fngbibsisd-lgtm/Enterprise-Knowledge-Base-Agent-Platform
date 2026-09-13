"""
工具：knowledge_search / get_document —— Agent 调用它们检索知识库文档。

knowledge_search 返回格式：{"found": bool, "sources": [{id, source, text, score}], "summary": str}
get_document 返回格式：{"found": bool, "source": str, "offset": int, "text": str,
                        "returned_chars": int, "total_chars": int, "has_more": bool,
                        "next_offset": int, "summary": str}

上下文保护：预算集中在 core/tool_output.py（按工具分档）。工具层负责把返回体组织到预算之内，
executor 再渲染一次做兜底——工具层若超预算，executor 一截，文本就可能被从中间切断。

长文档分页（get_document）：一篇文档常常几万字，超过任何合理的单条预算。与其截断后让模型
以为「文档就这么多」，不如让它知道总量并显式续读。**offset 单位是字符**（与 total_chars 同
单位），不暴露 chunk 这个实现细节。next_offset 必须与模型真正看到的字数对齐——所以这里自己
按页切片，不用 truncate（后者会加"...(已截断)"后缀，让"读到第几字"失真）。
"""
from backend.core.config import get_settings
from backend.core.tool_output import (
    MAX_TOP_K,
    MIN_ITEM_TEXT_CHARS,
    serialize,
    tool_result_limit,
    truncate,
)
from backend.services import rag

# 单页最少字符数：外壳（source/summary 等）异常膨胀时的保护，正常远大于此
MIN_PAGE_CHARS = 500

# JSON 外壳预留（键名、引号、summary 等），避免按预算切页时刚好溢出
_PAGE_ENVELOPE_RESERVE = 400


def _clamp_offset(offset, total: int) -> int:
    """把模型给的 offset 钳到 [0, total]。

    非法值不报错而是钳住：报错会白烧一轮迭代，而且模型多半是被上一页的
    next_offset 带偏了一点，钳住后照样能读到内容。
    """
    try:
        start = int(offset)
    except (TypeError, ValueError):
        try:
            start = int(float(offset))  # 模型偶尔会传 "1000.0"
        except (TypeError, ValueError):
            start = 0
    return max(0, min(start, total))


def _page_summary(source: str, start: int, returned: int, total: int) -> str:
    end = start + returned
    if returned == 0:
        return f"文档《{source}》共{total}字,已到末尾,没有更多内容了"
    if end >= total:
        body = f"本次返回第{start + 1}-{end}字"
        return f"文档《{source}》共{total}字,{body},已读完" if start else f"文档《{source}》共{total}字,已返回全部内容"
    return (
        f"文档《{source}》共{total}字,本次返回第{start + 1}-{end}字,"
        f"还有{total - end}字未读;需要时用 offset={end} 续读"
    )


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


async def get_document_fn(source: str, offset: int = 0) -> dict:
    """读取指定文档（默认从头读，长文档按 offset 分页续读）。

    offset 必须带默认值：评测重放历史 trace 时，旧记录里只有 {"source": ...}，
    少一个默认值就会 TypeError，把「重放失败」误读成「当时调用失败」。
    """
    settings = get_settings()
    doc = await rag.get_document_by_source(source, settings)
    text = (doc.get("text") or "").strip()
    if not text:
        return {
            "found": False, "source": source, "offset": 0, "text": "",
            "returned_chars": 0, "total_chars": 0, "has_more": False,
            "next_offset": 0, "summary": "未找到该文档",
        }

    limit = tool_result_limit("get_document", settings)
    total = len(text)
    start = _clamp_offset(offset, total)

    # 自洽收敛：页大小按预算倒推，再按实际序列化长度微调。
    # 必须让工具层自己就装得下——否则 executor 一截，next_offset 可能落在被切掉的部分，
    # 模型照着跳就会跳错，而且是静默的。
    page_size = max(MIN_PAGE_CHARS, limit - _PAGE_ENVELOPE_RESERVE)
    while True:
        page = text[start:start + page_size]
        payload = {
            "found": True,
            "source": source,
            "offset": start,
            "text": page,
            "returned_chars": len(page),
            "total_chars": total,
            "has_more": start + len(page) < total,
            "next_offset": start + len(page),
            "summary": _page_summary(source, start, len(page), total),
        }
        body = serialize(payload)
        if len(body) <= limit or page_size <= MIN_PAGE_CHARS:
            return payload
        # 中文正文里换行/引号会被 JSON 转义，实际长度可能超出按字符数的估算，收一次再试
        page_size -= len(body) - limit + 32

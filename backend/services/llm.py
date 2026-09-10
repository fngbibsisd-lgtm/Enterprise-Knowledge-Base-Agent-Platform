"""LLM 调用（异步，AsyncOpenAI）。"""
from openai import AsyncOpenAI

from backend.core.config import Settings

_SYSTEM_PROMPT = """
你是一个企业内部知识库助手，你的回答必须基于下面给出的参考资料
规则：
- 你的回答使用得体的中文呈现
- 仅使用提供的参考资料生成回答
- 如果给出的资料没有相关信息，请明确说明“目前给出的资料不足以回答”
- 明确给出引用到的所有资料来源
- 使用 Markdown 排版，需要强调的术语直接用 **术语** 加粗（加粗符号必须紧贴文字，不要写成 **"术语"**）
""".strip()


def _client(settings: Settings) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)


def _build_context(sources: list[dict]) -> str:
    """把检索到的 sources 拼成参考资料上下文。"""
    parts = []
    for index, source in enumerate(sources or [], start=1):
        text = (source.get("text") or "").strip()
        name = (source.get("source") or "未知来源").strip()
        score = source.get("score")
        if not text:
            continue
        if score is not None:
            parts.append(f"[资料]{index} 来源:{name} (相关度:{score:.2f})\n{text}")
        else:
            parts.append(f"[资料]{index} 来源:{name} (相关度:无)\n{text}")
    return "\n".join(parts) if parts else "当前没有检索到相关资料"


async def generate_answer(query: str, sources: list[dict], settings: Settings) -> str:
    """基于检索结果调用 LLM 生成回答。"""
    client = _client(settings)
    user_prompt = f"""
参考资料:
{_build_context(sources)}

用户问题:
{query}

请根据以上资料回答用户问题.
""".strip()
    response = await client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=settings.max_tokens,
    )
    content = response.choices[0].message.content
    return content or "抱歉,目前模型无法返回有效回答"

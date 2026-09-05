"""
LLM 调用服务：创建 OpenAI 客户端 + 基于检索到的 sources 拼接上下文并生成回答。
"""

from openai import OpenAI
from backend.config import Config


def create_llm_client(config: Config) -> OpenAI:
    """
    创建并返回OpenAI客户端
    Args:
        config: 配置对象

    Returns:
        OpenAI 客户端实例
    """
    client=OpenAI(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
    )
    return client



def generate_answer(query: str, sources: list[dict], config: Config) -> str:
    """
    生成 LLM 回答
    Args:
        query: 用户问题
        sources: 检索到的参考资料
        config: 配置对象

    Returns:
        LLM 回答
    """
    client=create_llm_client(config)
    system_prompt="""
你是一个企业内部知识库助手，你的回答必须基于下面给出的参考资料
规则：
- 你的回答使用得体的中文呈现
- 仅使用提供的参考资料生成回答
- 如果给出的资料没有相关信息，请明确说明“目前给出的资料不足以回答”
- 明确给出引用到的所有资料来源
- 使用 Markdown 排版，需要强调的术语直接用 **术语** 加粗（加粗符号必须紧贴文字，不要写成 **"术语"**）
    """.strip()
    context_parts=[]
    for index, source in enumerate(sources or [],start=1):
        text=source.get("text","").strip()
        source_name=source.get("source","未知来源").strip()
        score=source.get("score")
        if not text:
            continue
        if score is not None:
            context_parts.append(
                f"[资料]{index} 来源:{source_name} (相关度:{score:.2f})\n{text}"
            )
        else:
            context_parts.append(
                f"[资料]{index} 来源:{source_name} (相关度:无)\n{text}"
            )
    if context_parts:
        context="\n".join(context_parts)
    else:
        context="当前没有检索到相关资料"
    user_prompt=f"""
    参考资料:
    {context}
    
    用户问题:
    {query}
    
    请根据以上资料回答用户问题.
    """.strip()
    response=client.chat.completions.create(
        model=getattr(config, "llm_model", "deepseek-chat"),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=getattr(config, "llm_temperature", 0.2),
        max_tokens=config.max_tokens,
    )
    content=response.choices[0].message.content
    if not content:
        return "抱歉,目前模型无法返回有效回答"
    return content


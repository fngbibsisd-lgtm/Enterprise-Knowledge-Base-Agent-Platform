"""
LLM 调用模块

职责：
    1. 拼接 prompt（system prompt + 检索到的上下文 + 用户问题）
    2. 调用 LLM API
    3. 返回生成的回答

核心函数（你需要实现）：
    - build_prompt(query, retrieved_chunks) -> str
    - generate_answer(query, retrieved_chunks, config) -> str

提示：
    - OpenAI SDK 兼容很多国产模型 API（DeepSeek、Qwen 等）
    - System prompt 的核心：限制模型只根据给定上下文回答，不编造
"""

from config import Config
from document import Document
from openai import OpenAI

def create_llm_client(config:Config)->OpenAI:
    return OpenAI(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
    )

def build_prompt(query: str, retrieved_chunks: list[tuple[Document, float]]) ->tuple[str, str]:
    """
    构造发给 LLM 的完整 prompt。

    Args:
        query: 用户问题
        retrieved_chunks: search() 的返回值 [(Document, score), ...]

    Returns:
        str: 拼接好的 prompt 文本

    你需要设计：
        1. System 部分：角色设定 + 回答规则（只用给定文档，不知道就说不知道）
        2. Context 部分：把 retrieved_chunks 的文本拼接进去，标注来源
        3. Question 部分：用户原始问题
    """
    system_promt=(
        "你是一个企业内部知识库助手，你的回答必须基于下面给出的参考资料\n"
        "规则：\n"
        "你的回答使用得体的中文呈现\n"
        "仅使用提供的参考资料生成回答\n"
        "如果给出的资料没有相关信息，请明确说明“目前给出的资料不足以回答”\n"
        "明确给出引用到的所有资料来源\n"
    )
    if not retrieved_chunks:
        context="(没有找到相关的资料)"
    else:
        context_parts=[]
        for i,(doc,score) in enumerate(retrieved_chunks,1):
            context_parts.append(
                f"[资料]{i} 来源:{doc.metadata.get('source','未知来源')} (相关度:{score:.2f})\n{doc.text}"
            )
        context="\n\n".join(context_parts)
    user_propmt=(
        f"=== 参考资料 ===\n"
        f"{context}\n\n"
        f"=== 用户问题 ===\n"
        f"{query}\n\n"
        f"请回答："
    )
    return system_promt,user_propmt


def generate_answer(
    query: str,
    retrieved_chunks: list[tuple[Document, float]],
    config: Config,
) -> str:
    """
    调用 LLM 生成回答。

    Args:
        query: 用户问题
        retrieved_chunks: 检索到的相关文档片段
        config: 配置对象

    Returns:
        str: LLM 生成的回答

    你需要实现：
        1. 调用 build_prompt()
        2. 调用 LLM API（openai SDK）
        3. 返回 response.choices[0].message.content
    """
    client=create_llm_client(config)
    system_prompt,user_prompt=build_prompt(query,retrieved_chunks)
    response=client.chat.completions.create(
        model=config.llm_model,
        messages=[
            {"role":"system","content":system_prompt},
            {"role":"user","content":user_prompt}
        ],
        temperature=0.3,
        max_tokens=1024,
    )
    return response.choices[0].message.content
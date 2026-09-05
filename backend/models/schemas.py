"""
Pydantic 请求 / 响应模型。
"""
from pydantic import BaseModel,Field
class ChatRequest(BaseModel):
    query: str

class ChatResponse(BaseModel):
    answer:str
    sources:list[dict]

class UploadResponse(BaseModel):
    filename:str
    message:str
from typing import Literal
class ResetRequest(BaseModel):
    since: Literal["2h","12h","24h","all"]=Field(
        ...,
        description="重置时间范围可选:2h  |  12h  |  24h  |  all",
    )


# ========== V0.3 Agent 相关模型 ==========

class AgentChatRequest(BaseModel):
    """Agent 聊天请求"""
    query: str


class AgentChatResponse(BaseModel):
    """Agent 聊天响应 — 比普通 ChatResponse 多了工具调用历史"""
    answer: str
    tool_calls: list[dict] = []   # 记录 Agent 调用了哪些工具、什么参数、什么结果
    iterations: int = 1           # 经过了轮 LLM 调用


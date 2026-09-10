"""聊天相关请求/响应模型。"""
from pydantic import BaseModel


class ChatRequest(BaseModel):
    query: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict]


class AgentChatRequest(BaseModel):
    query: str


class AgentChatResponse(BaseModel):
    answer: str
    tool_calls: list[dict] = []
    iterations: int = 1

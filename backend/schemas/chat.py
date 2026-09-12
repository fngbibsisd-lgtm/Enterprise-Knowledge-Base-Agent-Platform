"""聊天相关请求/响应模型。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
    sources: list[dict] = []


class AgentStreamRequest(BaseModel):
    query: str
    session_id: int | None = None


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    tool_calls: list[dict] | None = None
    sources: list[dict] | None = None
    created_at: datetime

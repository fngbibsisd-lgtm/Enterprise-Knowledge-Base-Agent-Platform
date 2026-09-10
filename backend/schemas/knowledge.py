"""知识库管理相关请求/响应模型。"""
from typing import Literal

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    filename: str
    message: str


class ResetRequest(BaseModel):
    since: Literal["2h", "12h", "24h", "all"] = Field(
        ...,
        description="重置时间范围可选：2h | 12h | 24h | all",
    )

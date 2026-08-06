"""Request/response shapes for the orchestrator's HTTP API."""

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    message: str
    sources: list[dict] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)
    backend: str


class UploadResponse(BaseModel):
    filename: str
    chunks: int
    topics: list[str]

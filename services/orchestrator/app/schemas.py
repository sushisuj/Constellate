"""Request/response shapes for the orchestrator's HTTP API."""

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    message: str
    sources: list[dict] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)
    backend: str
    flags: list[str] = Field(default_factory=list)


class UploadResponse(BaseModel):
    filename: str
    chunks: int
    topics: list[str]
    keywords: list[str] = Field(default_factory=list)
    diagram_count: int = 0


class SentimentRequest(BaseModel):
    text: str


class SentimentResponse(BaseModel):
    label: str  # "positive" | "negative" | "neutral" | "blocked"
    explanation: str
    backend: str
    flags: list[str] = Field(default_factory=list)

"""Request/response models for the HTTP API (they also define the OpenAPI schema
that the frontend's TypeScript types are generated from)."""

from typing import Any

from pydantic import BaseModel, Field

from app.config import get_settings

_settings = get_settings()


class ChatRequest(BaseModel):
    session_id: str = Field(
        min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$", examples=["3f2b9c1e8a7d4e21"]
    )
    message: str = Field(min_length=1, max_length=_settings.max_message_chars)


class HealthResponse(BaseModel):
    status: str
    model: str
    data_as_of: str | None
    documents: int
    document_chunks: int
    active_sessions: int


class ExampleGroup(BaseModel):
    category: str
    questions: list[str]


class DocumentInfo(BaseModel):
    slug: str
    doc_id: str
    title: str
    short_title: str
    version: str
    effective: str
    owner: str
    summary: str
    url: str


class TableInfo(BaseModel):
    name: str
    row_count: int
    columns: list[str]


class TablePreview(BaseModel):
    name: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int


class DataOverview(BaseModel):
    company: str
    data_as_of: str | None
    tables: list[TableInfo]

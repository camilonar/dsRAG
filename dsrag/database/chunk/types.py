from datetime import datetime
from typing import Any, Optional
from typing_extensions import TypedDict


class FormattedDocument(TypedDict):
    id: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    summary: Optional[str] = None
    created_on: Optional[datetime] = None
    supp_id: Optional[str] = None
    metadata: Optional[dict] = {}
    chunk_count: Optional[int] = 0


class ChunkSearchResult(TypedDict):
    """A ranked chunk returned by an optional text-search capability."""

    doc_id: str
    chunk_index: int
    chunk_text: str
    document_title: str
    section_title: str
    chunk_page_start: Optional[int]
    chunk_page_end: Optional[int]
    metadata: dict[str, Any]
    score: float
    rank: int

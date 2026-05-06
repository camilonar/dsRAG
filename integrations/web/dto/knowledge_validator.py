from typing import Optional

from fastapi import Query
from pydantic import BaseModel, Field


class AddDocumentModel(BaseModel):
    metadata: dict = Field(..., default_factory=dict)

class SearchDocumentModel(BaseModel):
    q: str = Field(..., max_length=300)
    kb_id: Optional[str] = Field(None)
    doc_ids: Optional[list[str]] = Field(Query(None, max_length=50))
    year: Optional[int] = Field(None, ge=1900, le=2100)
    court: Optional[str] = Field(None)
    p_type: Optional[str] = Field(None)
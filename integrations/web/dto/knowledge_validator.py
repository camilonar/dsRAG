from pydantic import BaseModel, Field


class AddDocumentModel(BaseModel):
    metadata: dict = Field(..., default_factory=dict)
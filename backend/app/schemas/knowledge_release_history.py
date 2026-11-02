"""Historical evidence is deliberately separate from a published answer."""
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.knowledge import KnowledgeQueryScope


class ReleaseBindingCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    document_ids: list[int] = Field(min_length=1, max_length=100)
    product_model_ids: list[int] = Field(min_length=1, max_length=100)
    country: str = Field(min_length=2, max_length=2)
    market: str = Field(pattern='^(domestic|overseas)$')
    release_line: str = Field(min_length=1, max_length=100)
    conditions: str = Field(default='', max_length=4000)
    evidence_reference: str = Field(min_length=1, max_length=4000)
    confirmed_by: str = Field(min_length=1, max_length=100)


class ReleaseTraceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(min_length=2, max_length=500)
    scope: KnowledgeQueryScope
    release_line: str | None = Field(default=None, min_length=1, max_length=100)

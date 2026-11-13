"""Explicit configuration and software identities for the read-only detail view."""
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.knowledge import KnowledgeQueryScope


class FeatureDetailRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scope: KnowledgeQueryScope | None = None
    configuration_version_id: int | None = Field(default=None, gt=0)

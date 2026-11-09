"""Inputs for selecting existing configuration identities into template drafts."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

PositiveReference = Annotated[int, Field(gt=0, strict=True)]


class TemplateCatalogSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    feature_id: PositiveReference
    group_id: PositiveReference
    category_ids: list[PositiveReference] = Field(min_length=1)


class TemplateCellDraft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    category_id: PositiveReference
    feature_id: PositiveReference
    new_support: Literal['supported', 'conditional', 'unsupported'] = 'unsupported'
    excludes: str | None = None

"""Explicit specification records and snapshot selection, without unit inference."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr

PositiveId = Annotated[int, Field(strict=True, gt=0)]


class ParameterRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ParameterField(ParameterRequest):
    key: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,49}$')
    label: str = Field(min_length=1, max_length=100)
    unit: str = Field(default='', max_length=30)
    type: Literal['number', 'text'] = 'number'


class ParameterTopicCreate(ParameterRequest):
    name: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=2, max_length=500)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    fields: list[ParameterField] = Field(min_length=1, max_length=20)


class ParameterSpecCreate(ParameterRequest):
    name: str = Field(min_length=1, max_length=200)
    ipn: str = Field(min_length=1, max_length=100)
    values: dict[str, StrictStr | StrictInt | StrictFloat]
    evidence_reference: str = Field(min_length=1, max_length=5000)
    confirmed_by: str = Field(min_length=1, max_length=100)
    is_active: bool = True


class ParameterSpecUpdate(ParameterSpecCreate):
    expected_revision: PositiveId


class ParameterPreviewRequest(ParameterRequest):
    config_version_id: PositiveId
    model_ids: list[PositiveId] = Field(min_length=1, max_length=200)

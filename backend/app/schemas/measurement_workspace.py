"""Closed operation schemas: source/evidence fields cannot be written through drafts."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class RevisionInput(StrictInput):
    revision: int = Field(ge=1)


class InitializeInput(StrictInput):
    batch_id: int = Field(ge=1)
    expected_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    version_number: str | None = Field(default=None, min_length=1, max_length=100)
    description: str = Field(default='', max_length=4000)


class RenameItem(RevisionInput):
    operation: Literal['rename_item']
    record_key: str
    cn_name: str = Field(max_length=10000)
    description: str = Field(max_length=10000)


class Assignments(StrictInput):
    categories: list[str] = Field(max_length=1000)
    modes: list[str] = Field(max_length=1000)

    @field_validator('categories', 'modes')
    @classmethod
    def codes(cls, value):
        if any(not code.strip() or code != code.strip() or len(code) > 100 for code in value) or len(set(value)) != len(value):
            raise ValueError('分类和模式代码必须非空、唯一且不含首尾空格')
        return sorted(value)


class AssignItem(RevisionInput, Assignments):
    operation: Literal['assign_item']
    record_key: str


class AddItem(RevisionInput, Assignments):
    operation: Literal['add_item']
    kind: Literal['measurement', 'calculation']
    item_id: str = Field(min_length=1, max_length=1000)
    cn_name: str = Field(max_length=10000)
    description: str = Field(max_length=10000)
    group: str = Field(default='', max_length=100)
    unit: str = Field(default='', max_length=100)
    enabled_raw: str = Field(default='', max_length=100)
    allow_existing_id: bool = False


class UpsertDictionary(RevisionInput):
    operation: Literal['upsert_dictionary']
    dimension: Literal['applications', 'modes']
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)

    @field_validator('code', 'name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip() or value != value.strip():
            raise ValueError('代码和名称不能为空或含首尾空格')
        return value


class ReorderDictionary(RevisionInput):
    operation: Literal['reorder_dictionary']
    dimension: Literal['applications', 'modes']
    codes: list[str] = Field(max_length=1000)


EditInput = Annotated[RenameItem | AssignItem | AddItem | UpsertDictionary | ReorderDictionary, Field(discriminator='operation')]


class UndoInput(RevisionInput):
    change_key: str = Field(min_length=1)


class PreviewInput(RevisionInput):
    version_number: str = Field(min_length=1, max_length=100)
    description: str = Field(default='', max_length=4000)

    @field_validator('version_number')
    @classmethod
    def nonblank(cls, value):
        if not value.strip() or value != value.strip():
            raise ValueError('版本号不能为空或含首尾空格')
        return value


class PublishInput(PreviewInput):
    signature: str = Field(pattern=r'^[a-f0-9]{64}$')

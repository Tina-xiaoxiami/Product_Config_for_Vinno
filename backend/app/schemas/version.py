"""
版本管理 schemas
"""
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any, Literal
import json


class ConfigVersionBase(BaseModel):
    version_number: Optional[str] = None
    version_name: Optional[str] = None
    description: Optional[str] = None


class ConfigVersionCreate(ConfigVersionBase):
    series_id: int


class ConfigVersionResponse(ConfigVersionBase):
    id: int
    series_id: int
    snapshot_data: Dict[str, Any]
    row_count: int
    changes_summary: Optional[Dict[str, Any]] = None
    published_by: Optional[str] = None
    published_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True

    @field_validator('snapshot_data', 'changes_summary', mode='before')
    @classmethod
    def parse_json(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except:
                return {}
        return v or {}


class VersionCompareRequest(BaseModel):
    """版本对比请求"""
    version_id_1: int
    version_id_2: int
    model_ids: Optional[List[int]] = None  # 可选的机型筛选
    compare_fields: Optional[List[Literal["current_config", "final_config", "selection_config", "rd_status"]]] = None
    name_columns: Optional[List[Literal["rd_name", "zh_desc", "en_desc", "v_code", "ipn"]]] = None
    only_diff: bool = False

    @field_validator("compare_fields", "name_columns")
    @classmethod
    def validate_columns(cls, value):
        if value is not None and (not value or len(value) != len(set(value))):
            raise ValueError("至少选择一列，且列不能重复")
        return value


class VersionDiffDetail(BaseModel):
    """版本差异详情"""
    type: str  # added/modified/deleted
    row_index: int
    rd_name: Optional[str] = None
    ipn: Optional[str] = None
    zh_desc: Optional[str] = None
    model_id: Optional[int] = None
    model_name: Optional[str] = None
    field_name: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None


class VersionMatrixRow(BaseModel):
    key: str
    rd_name: Optional[str] = None
    zh_desc: Optional[str] = None
    en_desc: Optional[str] = None
    v_code: Optional[str] = None
    ipn: Optional[str] = None
    change_type: Literal["added", "deleted", "modified", "unchanged"]
    old_values: Dict[str, Dict[str, Optional[str]]]
    new_values: Dict[str, Dict[str, Optional[str]]]


class VersionMatrixModel(BaseModel):
    id: int
    name: str


class VersionCompareResponse(BaseModel):
    """版本对比响应"""
    version_1: ConfigVersionResponse
    version_2: ConfigVersionResponse
    added: List[VersionDiffDetail]
    modified: List[VersionDiffDetail]
    deleted: List[VersionDiffDetail]
    summary: Dict[str, int]
    matrix_rows: List[VersionMatrixRow] = Field(default_factory=list)
    matrix_models: List[VersionMatrixModel] = Field(default_factory=list)


class ConfigVersionListResponse(BaseModel):
    items: List[ConfigVersionResponse]
    total: int
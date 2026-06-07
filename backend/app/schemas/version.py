"""
版本管理 schemas
"""
from datetime import datetime
from pydantic import BaseModel, field_validator
from typing import Optional, List, Dict, Any
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


class VersionDiffDetail(BaseModel):
    """版本差异详情"""
    type: str  # added/modified/deleted
    row_index: int
    rd_name: Optional[str] = None
    ipn: Optional[str] = None
    model_id: Optional[int] = None
    model_name: Optional[str] = None
    field_name: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None


class VersionCompareResponse(BaseModel):
    """版本对比响应"""
    version_1: ConfigVersionResponse
    version_2: ConfigVersionResponse
    added: List[VersionDiffDetail]
    modified: List[VersionDiffDetail]
    deleted: List[VersionDiffDetail]
    summary: Dict[str, int]


class ConfigVersionListResponse(BaseModel):
    items: List[ConfigVersionResponse]
    total: int
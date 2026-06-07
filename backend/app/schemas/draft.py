"""
草稿管理 schemas
"""
from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class DraftBatchBase(BaseModel):
    series_id: int
    filename: Optional[str] = None


class DraftBatchResponse(DraftBatchBase):
    id: str
    status: str
    total_count: int
    create_count: int
    update_count: int
    delete_count: int
    created_by: Optional[str] = None
    created_at: datetime
    submitted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DraftSubmitRequest(BaseModel):
    """草稿提交请求"""
    version_number: Optional[str] = None
    version_name: Optional[str] = None
    description: Optional[str] = None
    item_ids: Optional[List[int]] = None  # 部分提交时指定要提交的配置项ID列表，不传则提交全部
    model_ids: Optional[List[int]] = None  # 按机型过滤，仅提交指定机型的变更


class ConfigDraftBase(BaseModel):
    item_id: Optional[int] = None
    model_id: Optional[int] = None
    change_type: str
    field_name: Optional[str] = None
    new_value: Optional[str] = None
    old_value: Optional[str] = None


class ConfigDraftCreate(ConfigDraftBase):
    series_id: int
    batch_id: str


class ConfigDraftResponse(ConfigDraftBase):
    id: int
    series_id: int
    batch_id: str
    created_at: datetime

    class Config:
        from_attributes = True


class DraftStatsResponse(BaseModel):
    """草稿统计"""
    total: int
    create: int
    update: int
    delete: int


class BatchDiscardRequest(BaseModel):
    """批量撤销请求"""
    batch_ids: List[str]


class BatchDiscardResult(BaseModel):
    """批量撤销单个结果"""
    batch_id: str
    series_id: int
    success: bool
    message: str


class BatchDiscardResponse(BaseModel):
    """批量撤销响应"""
    discarded_count: int
    results: List[BatchDiscardResult]


class BatchSubmitRequest(BaseModel):
    """批量提交请求"""
    batch_ids: List[str]
    version_number: Optional[str] = None
    description: Optional[str] = None
    version_name: Optional[str] = None


class BatchSubmitResult(BaseModel):
    """批量提交单个结果"""
    batch_id: str
    series_id: int
    version_number: str
    changes: int
    success: bool
    message: str


class BatchSubmitResponse(BaseModel):
    """批量提交响应"""
    submitted_count: int
    results: List[BatchSubmitResult]
"""
配置数据 schemas
"""
from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class ConfigValueBase(BaseModel):
    current_config: Optional[str] = None
    final_config: Optional[str] = None
    selection_config: Optional[str] = None
    rd_status: Optional[str] = None


class ConfigValueResponse(ConfigValueBase):
    id: int
    item_id: int
    model_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConfigItemBase(BaseModel):
    category: Optional[str] = None
    row_index: int
    rd_name: Optional[str] = None
    v_code: Optional[str] = None
    ipn: Optional[str] = None
    zh_desc: Optional[str] = None
    en_desc: Optional[str] = None


class ConfigItemResponse(ConfigItemBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConfigRowResponse(BaseModel):
    """配置行响应（包含配置项和各型号的配置值）"""
    id: int
    category: Optional[str] = None
    row_index: int
    rd_name: Optional[str] = None
    v_code: Optional[str] = None
    ipn: Optional[str] = None
    zh_desc: Optional[str] = None
    en_desc: Optional[str] = None
    model_values: Dict[int, ConfigValueResponse] = {}  # model_id -> ConfigValue

    class Config:
        from_attributes = True


class ConfigDataFilter(BaseModel):
    """配置数据筛选条件"""
    series_id: Optional[int] = None
    model_ids: Optional[List[int]] = None
    category: Optional[str] = None
    search: Optional[str] = None


class ConfigCompareRequest(BaseModel):
    """配置对比请求"""
    model_ids: List[int]
    compare_fields: List[str] = ["current_config", "final_config", "selection_config", "rd_status"]
    show_only_diff: bool = False


class ConfigDiffItem(BaseModel):
    """配置差异项"""
    item_id: int
    row_index: int
    rd_name: Optional[str] = None
    ipn: Optional[str] = None
    v_code: Optional[str] = None
    zh_desc: Optional[str] = None
    en_desc: Optional[str] = None
    model_id: int
    model_name: str
    field_name: str
    values: Dict[int, Optional[str]]  # model_id -> value


class ConfigCompareResponse(BaseModel):
    """配置对比响应"""
    items: List[ConfigDiffItem]
    total: int
    diff_count: int


class EnumValueResponse(BaseModel):
    """枚举值响应"""
    selection_types: List[str] = []
    rd_statuses: List[str] = []


class BatchUpdateRequest(BaseModel):
    """批量更新请求"""
    item_ids: List[int]
    model_ids: Optional[List[int]] = None
    field_name: str
    value: str
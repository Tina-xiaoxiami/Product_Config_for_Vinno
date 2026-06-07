"""
产品型号 schemas
"""
from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List


class ProductModelBase(BaseModel):
    name: str
    description: Optional[str] = None
    status: Optional[str] = "生产中"
    column_start: Optional[int] = None
    column_end: Optional[int] = None
    sort_order: Optional[int] = 0


class ProductModelCreate(ProductModelBase):
    series_id: int


class ProductModelUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    sort_order: Optional[int] = None


class ProductModelResponse(ProductModelBase):
    id: int
    series_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProductModelListResponse(BaseModel):
    items: List[ProductModelResponse]
    total: int
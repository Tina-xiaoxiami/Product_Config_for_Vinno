"""
产品系列 schemas
"""
from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List


class ProductSeriesBase(BaseModel):
    name: str


class ProductSeriesCreate(ProductSeriesBase):
    pass


class ProductSeriesUpdate(BaseModel):
    name: Optional[str] = None


class ProductSeriesResponse(ProductSeriesBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProductSeriesListResponse(BaseModel):
    items: List[ProductSeriesResponse]
    total: int
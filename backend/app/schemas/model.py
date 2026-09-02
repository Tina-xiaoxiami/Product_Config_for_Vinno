"""
产品型号 schemas
"""
from datetime import datetime
from pydantic import BaseModel, Field
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


class ProductModelRegistrationPackage(BaseModel):
    registration_package_id: int
    country_code: str
    registration_number: str
    registration_package_name: str
    registration_model_id: int
    registration_model_name: str
    mapping_type: str


class ProductModelResponse(ProductModelBase):
    id: int
    series_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    registration_packages: List[ProductModelRegistrationPackage] = Field(
        default_factory=list
    )

    class Config:
        from_attributes = True


class ProductModelListResponse(BaseModel):
    items: List[ProductModelResponse]
    total: int

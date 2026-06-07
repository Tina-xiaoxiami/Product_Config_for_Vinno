"""
产品型号 API
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List

from app.database import get_db
from app.models import ProductSeries, ProductModel
from app.schemas.model import ProductModelCreate, ProductModelResponse, ProductModelListResponse, ProductModelUpdate

router = APIRouter()


@router.get("", response_model=ProductModelListResponse)
async def get_models(
    series_id: int = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """获取产品型号列表"""
    query = select(ProductModel)

    if series_id:
        query = query.where(ProductModel.series_id == series_id)

    query = query.order_by(ProductModel.sort_order).offset(skip).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    count_query = select(func.count()).select_from(ProductModel)
    if series_id:
        count_query = count_query.where(ProductModel.series_id == series_id)
    count_result = await db.execute(count_query)
    total = count_result.scalar()

    return ProductModelListResponse(items=items, total=total)


@router.get("/{model_id}", response_model=ProductModelResponse)
async def get_model(
    model_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取产品型号详情"""
    result = await db.execute(select(ProductModel).where(ProductModel.id == model_id))
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(status_code=404, detail="产品型号不存在")

    return model


@router.post("", response_model=ProductModelResponse)
async def create_model(
    data: ProductModelCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建产品型号"""
    # 检查系列是否存在
    result = await db.execute(select(ProductSeries).where(ProductSeries.id == data.series_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="产品系列不存在")

    model = ProductModel(
        series_id=data.series_id,
        name=data.name,
        description=data.description,
        status=data.status or "生产中",
        column_start=data.column_start,
        column_end=data.column_end,
        sort_order=data.sort_order or 0
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return model


@router.put("/{model_id}", response_model=ProductModelResponse)
async def update_model(
    model_id: int,
    data: ProductModelUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新产品型号"""
    result = await db.execute(select(ProductModel).where(ProductModel.id == model_id))
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(status_code=404, detail="产品型号不存在")

    if data.name is not None:
        model.name = data.name
    if data.description is not None:
        model.description = data.description
    if data.status is not None:
        model.status = data.status
    if data.sort_order is not None:
        model.sort_order = data.sort_order

    await db.commit()
    await db.refresh(model)
    return model


@router.delete("/{model_id}")
async def delete_model(
    model_id: int,
    db: AsyncSession = Depends(get_db)
):
    """删除产品型号"""
    result = await db.execute(select(ProductModel).where(ProductModel.id == model_id))
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(status_code=404, detail="产品型号不存在")

    await db.delete(model)
    await db.commit()
    return {"message": "删除成功"}
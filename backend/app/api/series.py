"""
产品系列 API
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List

from app.database import get_db
from app.models import ProductSeries
from app.schemas.series import (
    ProductSeriesCreate, ProductSeriesResponse, ProductSeriesUpdate, ProductSeriesListResponse
)

router = APIRouter()


@router.get("", response_model=ProductSeriesListResponse)
async def get_series_list(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """获取产品系列列表"""
    result = await db.execute(select(ProductSeries).offset(skip).limit(limit))
    items = result.scalars().all()

    count_result = await db.execute(select(func.count()).select_from(ProductSeries))
    total = count_result.scalar()

    return ProductSeriesListResponse(items=items, total=total)


@router.get("/{series_id}", response_model=ProductSeriesResponse)
async def get_series(
    series_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取产品系列详情"""
    result = await db.execute(select(ProductSeries).where(ProductSeries.id == series_id))
    series = result.scalar_one_or_none()

    if not series:
        raise HTTPException(status_code=404, detail="产品系列不存在")

    return series


@router.post("", response_model=ProductSeriesResponse)
async def create_series(
    data: ProductSeriesCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建产品系列"""
    series = ProductSeries(name=data.name)
    db.add(series)
    await db.commit()
    await db.refresh(series)
    return series


@router.put("/{series_id}", response_model=ProductSeriesResponse)
async def update_series(
    series_id: int,
    data: ProductSeriesUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新产品系列"""
    result = await db.execute(select(ProductSeries).where(ProductSeries.id == series_id))
    series = result.scalar_one_or_none()

    if not series:
        raise HTTPException(status_code=404, detail="产品系列不存在")

    if data.name:
        series.name = data.name

    await db.commit()
    await db.refresh(series)
    return series


@router.delete("/{series_id}")
async def delete_series(
    series_id: int,
    db: AsyncSession = Depends(get_db)
):
    """删除产品系列 - 级联删除型号、配置值、版本等"""
    from sqlalchemy import delete
    from app.models import ProductModel, ConfigValue, ConfigVersion, DraftBatch, ConfigDraft, ChangeLog, ImportHistory

    # 检查系列是否存在
    result = await db.execute(select(ProductSeries).where(ProductSeries.id == series_id))
    series = result.scalar_one_or_none()

    if not series:
        raise HTTPException(status_code=404, detail="产品系列不存在")

    # 获取该系列下的所有型号ID
    models_result = await db.execute(
        select(ProductModel.id).where(ProductModel.series_id == series_id)
    )
    model_ids = [m[0] for m in models_result.fetchall()]

    # 删除该系列下的配置值（通过型号关联）
    if model_ids:
        await db.execute(
            delete(ConfigValue).where(ConfigValue.model_id.in_(model_ids))
        )

    # 删除相关数据
    await db.execute(delete(ProductModel).where(ProductModel.series_id == series_id))
    await db.execute(delete(ConfigVersion).where(ConfigVersion.series_id == series_id))
    await db.execute(delete(DraftBatch).where(DraftBatch.series_id == series_id))
    await db.execute(delete(ConfigDraft).where(ConfigDraft.series_id == series_id))
    await db.execute(delete(ChangeLog).where(ChangeLog.series_id == series_id))
    await db.execute(delete(ImportHistory).where(ImportHistory.series_id == series_id))

    # 删除系列本身
    await db.delete(series)
    await db.commit()

    return {"message": "删除成功"}
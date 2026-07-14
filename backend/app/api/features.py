"""功能组和功能 API"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models.probe import FeatureGroup, Feature
from app.schemas.probe import (
    FeatureGroupCreate, FeatureGroupUpdate, FeatureGroupResponse, FeatureGroupListResponse,
    FeatureCreate, FeatureUpdate, FeatureResponse, FeatureListResponse,
)

router = APIRouter()

# ===== Feature Groups =====

@router.get("/groups", response_model=FeatureGroupListResponse)
async def list_groups(skip: int = 0, limit: int = 50, db: AsyncSession = Depends(get_db)):
    count_r = await db.execute(select(func.count()).select_from(FeatureGroup))
    total = count_r.scalar()
    result = await db.execute(select(FeatureGroup).order_by(FeatureGroup.sort_order).offset(skip).limit(limit))
    items = result.scalars().all()
    return FeatureGroupListResponse(items=items, total=total)


@router.post("/groups", response_model=FeatureGroupResponse)
async def create_group(data: FeatureGroupCreate, db: AsyncSession = Depends(get_db)):
    obj = FeatureGroup(**data.model_dump())
    db.add(obj); await db.commit(); await db.refresh(obj)
    return obj


@router.put("/groups/{group_id}", response_model=FeatureGroupResponse)
async def update_group(group_id: int, data: FeatureGroupUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FeatureGroup).where(FeatureGroup.id == group_id))
    obj = result.scalar_one_or_none()
    if not obj: raise HTTPException(status_code=404, detail="功能组不存在")
    for f, v in data.model_dump(exclude_unset=True).items(): setattr(obj, f, v)
    await db.commit(); await db.refresh(obj)
    return obj


@router.delete("/groups/{group_id}")
async def delete_group(group_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FeatureGroup).where(FeatureGroup.id == group_id))
    obj = result.scalar_one_or_none()
    if not obj: raise HTTPException(status_code=404, detail="功能组不存在")
    await db.delete(obj); await db.commit()
    return {"message": "删除成功"}


# ===== Features =====

@router.get("", response_model=FeatureListResponse)
async def list_features(
    group_id: int = None,
    skip: int = 0, limit: int = 200,
    db: AsyncSession = Depends(get_db)
):
    q = select(Feature)
    cq = select(func.count()).select_from(Feature)
    if group_id:
        q = q.where(Feature.group_id == group_id)
        cq = cq.where(Feature.group_id == group_id)
    count_r = await db.execute(cq)
    total = count_r.scalar()
    result = await db.execute(q.order_by(Feature.sort_order).offset(skip).limit(limit))
    return FeatureListResponse(items=result.scalars().all(), total=total)


@router.post("", response_model=FeatureResponse)
async def create_feature(data: FeatureCreate, db: AsyncSession = Depends(get_db)):
    obj = Feature(**data.model_dump())
    db.add(obj); await db.commit(); await db.refresh(obj)
    return obj


@router.put("/{feature_id}", response_model=FeatureResponse)
async def update_feature(feature_id: int, data: FeatureUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Feature).where(Feature.id == feature_id))
    obj = result.scalar_one_or_none()
    if not obj: raise HTTPException(status_code=404, detail="功能不存在")
    for f, v in data.model_dump(exclude_unset=True).items(): setattr(obj, f, v)
    await db.commit(); await db.refresh(obj)
    return obj


@router.delete("/{feature_id}")
async def delete_feature(feature_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Feature).where(Feature.id == feature_id))
    obj = result.scalar_one_or_none()
    if not obj: raise HTTPException(status_code=404, detail="功能不存在")
    await db.delete(obj); await db.commit()
    return {"message": "删除成功"}

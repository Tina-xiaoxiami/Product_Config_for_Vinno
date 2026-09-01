"""Unified product knowledge read APIs."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.knowledge import (
    FeatureKnowledgeItem,
    FeatureKnowledgeList,
    KnowledgeStats,
)
from app.services.knowledge_query import (
    get_feature_knowledge,
    get_knowledge_stats,
    list_feature_knowledge,
)


router = APIRouter()


@router.get("/features", response_model=FeatureKnowledgeList)
async def list_knowledge_features(
    q: str | None = Query(None, max_length=200),
    identity_status: str | None = Query(
        None,
        pattern="^(auto_matched|confirmed|related|pending)$",
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    items, total = await list_feature_knowledge(
        db,
        query=q,
        identity_status=identity_status,
        skip=skip,
        limit=limit,
    )
    return FeatureKnowledgeList(items=items, total=total, skip=skip, limit=limit)


@router.get("/features/{feature_id}", response_model=FeatureKnowledgeItem)
async def get_knowledge_feature(
    feature_id: int,
    db: AsyncSession = Depends(get_db),
):
    item = await get_feature_knowledge(db, feature_id)
    if item is None:
        raise HTTPException(status_code=404, detail="功能不存在")
    return FeatureKnowledgeItem(**item)


@router.get("/stats", response_model=KnowledgeStats)
async def knowledge_stats(db: AsyncSession = Depends(get_db)):
    return KnowledgeStats(**(await get_knowledge_stats(db)))

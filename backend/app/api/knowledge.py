"""Unified product knowledge read APIs."""

from pathlib import Path
import mimetypes

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.knowledge import (
    FeatureKnowledgeItem,
    FeatureKnowledgeList,
    KnowledgeDocumentList,
    KnowledgeStats,
)
from app.services.knowledge_documents import (
    get_registered_document,
    list_knowledge_documents,
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


@router.get("/documents", response_model=KnowledgeDocumentList)
async def list_documents(
    q: str | None = Query(None, max_length=200),
    document_type: str | None = Query(None, max_length=100),
    market: str | None = Query(None, pattern="^(domestic|overseas)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    items, total = await list_knowledge_documents(
        db,
        query=q,
        document_type=document_type,
        market=market,
        skip=skip,
        limit=limit,
    )
    return KnowledgeDocumentList(items=items, total=total, skip=skip, limit=limit)


@router.get("/documents/{document_id}/preview")
async def preview_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    document = await get_registered_document(db, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="资料不存在")

    path = Path(document["file_path"])
    if not path.is_absolute() or not path.is_file():
        raise HTTPException(status_code=410, detail="原文件不存在或尚未同步")

    media_type = document["mime_type"] or mimetypes.guess_type(path.name)[0]
    return FileResponse(
        path=path,
        media_type=media_type or "application/octet-stream",
        filename=document["file_name"],
        content_disposition_type="inline",
    )

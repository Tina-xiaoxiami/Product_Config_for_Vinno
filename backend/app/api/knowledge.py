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
    KnowledgeAnswerHistory,
    KnowledgeAnswerPublish,
    KnowledgeCandidateEvidenceList,
    KnowledgeDocumentList,
    KnowledgeDocumentExtractionItem,
    KnowledgeQuestionAsk,
    KnowledgeQuestionItem,
    KnowledgeQuestionList,
    KnowledgeQuestionResult,
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
from app.services.knowledge_qa import (
    KnowledgeQaError,
    ask_question,
    get_answer_history,
    get_question,
    list_questions,
    publish_answer,
)
from app.services.knowledge_content import (
    KnowledgeContentError,
    KnowledgeDocumentMissingError,
    extract_registered_document,
    get_question_candidate_evidence,
)


router = APIRouter()


@router.post("/questions/ask", response_model=KnowledgeQuestionResult)
async def ask_knowledge_question(
    data: KnowledgeQuestionAsk,
    db: AsyncSession = Depends(get_db),
):
    try:
        return KnowledgeQuestionResult(**(await ask_question(db, data.question)))
    except KnowledgeQaError as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/questions", response_model=KnowledgeQuestionList)
async def get_knowledge_questions(
    status: str | None = Query(None, pattern="^(pending|answered)$"),
    q: str | None = Query(None, max_length=200),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    items, total = await list_questions(
        db,
        status=status,
        query=q,
        skip=skip,
        limit=limit,
    )
    return KnowledgeQuestionList(items=items, total=total, skip=skip, limit=limit)


@router.get("/questions/{question_id}", response_model=KnowledgeQuestionItem)
async def get_knowledge_question(
    question_id: int,
    db: AsyncSession = Depends(get_db),
):
    item = await get_question(db, question_id)
    if item is None:
        raise HTTPException(status_code=404, detail="问题不存在")
    return KnowledgeQuestionItem(**item)


@router.put("/questions/{question_id}/answer", response_model=KnowledgeQuestionItem)
async def confirm_knowledge_answer(
    question_id: int,
    data: KnowledgeAnswerPublish,
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await publish_answer(
            db,
            question_id=question_id,
            **data.model_dump(),
        )
    except KnowledgeQaError as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="问题不存在")
    return KnowledgeQuestionItem(**item)


@router.get("/questions/{question_id}/history", response_model=KnowledgeAnswerHistory)
async def knowledge_answer_history(
    question_id: int,
    db: AsyncSession = Depends(get_db),
):
    items = await get_answer_history(db, question_id)
    if items is None:
        raise HTTPException(status_code=404, detail="问题不存在")
    return KnowledgeAnswerHistory(items=items)


@router.get(
    "/questions/{question_id}/candidates",
    response_model=KnowledgeCandidateEvidenceList,
)
async def knowledge_question_candidates(
    question_id: int,
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    items = await get_question_candidate_evidence(db, question_id, limit=limit)
    if items is None:
        raise HTTPException(status_code=404, detail="问题不存在")
    return KnowledgeCandidateEvidenceList(items=items)


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


@router.post(
    "/documents/{document_id}/extract",
    response_model=KnowledgeDocumentExtractionItem,
)
async def extract_document_content(
    document_id: int,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await extract_registered_document(db, document_id, force=force)
    except KnowledgeDocumentMissingError as exc:
        await db.rollback()
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except KnowledgeContentError as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="资料不存在")
    return KnowledgeDocumentExtractionItem(**item)


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

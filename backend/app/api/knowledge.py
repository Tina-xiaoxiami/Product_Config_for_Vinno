"""Unified product knowledge read APIs."""

import asyncio
from pathlib import Path
import mimetypes

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.knowledge import (
    DataReviewBatchList,
    DataReviewItem,
    DataReviewItemList,
    DataReviewItemUpdate,
    DataReviewRevisionList,
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
    LocalFileOpenRequest,
    LocalFileOpenResult,
)
from app.services.data_review import (
    get_data_review_item_history,
    list_data_review_batches,
    list_data_review_items,
    revise_data_review_item,
    stage_knowledge_document_review_items,
)
from app.services.knowledge_documents import (
    get_registered_document,
    list_knowledge_documents,
)
from app.services.local_file_actions import (
    LocalOpenError,
    is_local_host,
    open_local_path,
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
    merge_question,
    publish_answer,
)
from app.services.knowledge_content import (
    KnowledgeContentError,
    KnowledgeDocumentMissingError,
    extract_registered_document,
    get_question_candidate_evidence,
)


router = APIRouter()


def _database_path(db: AsyncSession) -> Path:
    bind = db.bind
    database = getattr(getattr(bind, "url", None), "database", None)
    if not database:
        raise HTTPException(status_code=500, detail="无法确定知识库数据库路径")
    return Path(str(database)).resolve()


@router.get("/review-batches", response_model=DataReviewBatchList)
async def get_review_batches(db: AsyncSession = Depends(get_db)):
    items = await list_data_review_batches(db)
    return DataReviewBatchList(items=items, total=len(items))


@router.get("/review-items", response_model=DataReviewItemList)
async def get_review_items(
    data_type: str = Query(..., min_length=1, max_length=80),
    batch_id: int = Query(..., ge=1),
    review_status: str | None = Query(
        None,
        pattern="^(auto_ready|needs_review|corrected|confirmed|excluded)$",
    ),
    q: str | None = Query(None, max_length=200),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    items, total = await list_data_review_items(
        db,
        data_type=data_type,
        batch_id=batch_id,
        review_status=review_status,
        query=q,
        skip=skip,
        limit=limit,
    )
    return DataReviewItemList(items=items, total=total, skip=skip, limit=limit)


@router.put("/review-items/{item_id}", response_model=DataReviewItem)
async def update_review_item(
    item_id: int,
    payload: DataReviewItemUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        return DataReviewItem(
            **revise_data_review_item(
                _database_path(db), item_id=item_id, **payload.model_dump()
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/review-items/{item_id}/history",
    response_model=DataReviewRevisionList,
)
async def get_review_item_history(item_id: int, db: AsyncSession = Depends(get_db)):
    items = get_data_review_item_history(_database_path(db), item_id=item_id)
    return DataReviewRevisionList(items=items)


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


@router.post(
    "/questions/{source_question_id}/merge/{target_question_id}",
    response_model=KnowledgeQuestionItem,
)
async def merge_knowledge_question(
    source_question_id: int,
    target_question_id: int,
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await merge_question(
            db,
            source_question_id=source_question_id,
            target_question_id=target_question_id,
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
    try:
        review = await asyncio.to_thread(
            stage_knowledge_document_review_items,
            _database_path(db),
            document_id=document_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return KnowledgeDocumentExtractionItem(**item, review=review)


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


@router.post("/documents/{document_id}/open-locally", response_model=LocalFileOpenResult)
async def open_document_locally(
    document_id: int,
    request: Request,
    payload: LocalFileOpenRequest = LocalFileOpenRequest(),
    db: AsyncSession = Depends(get_db),
):
    """用系统默认程序打开受控原件；仅限本机请求，路径只取自登记记录。"""

    if not is_local_host(request.client.host if request.client else None):
        raise HTTPException(status_code=403, detail="仅允许在本机打开受控原件")
    document = await get_registered_document(db, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="资料不存在")

    path = Path(str(document["file_path"] or ""))
    if not path.is_absolute() or not path.is_file():
        raise HTTPException(status_code=410, detail="原文件不存在或尚未同步")

    try:
        await asyncio.to_thread(
            open_local_path, path, reveal=payload.mode == "reveal"
        )
    except LocalOpenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LocalFileOpenResult(
        file_name=document["file_name"] or path.name,
        mode=payload.mode,
        file_path=str(path),
    )

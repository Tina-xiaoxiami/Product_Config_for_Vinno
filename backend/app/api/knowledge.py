"""Unified product knowledge read APIs."""

import asyncio
from pathlib import Path
import mimetypes

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.knowledge_feature_detail import FeatureDetailRequest
from app.services.knowledge_feature_detail import feature_detail
from app.services.knowledge_parameters import ParameterError
from app.services.knowledge_release_history import ReleaseHistoryError
from app.database import get_db
from app.services.knowledge_sources import CitationSourceError, answer_spreadsheet_citations, citation_evidence, verified_original
from app.services.knowledge_answer_review import (
    KnowledgeAnswerReviewError, KnowledgeAnswerReviewConflict,
    KnowledgeAnswerReviewUnavailable, review_answer,
)
from app.services.knowledge_scope import KnowledgeScopeError, KnowledgeScopeUnavailable, a_only_question, infer_question_scope, resolve_query_scope
from app.schemas.knowledge import (
    DataReviewBatchConfirmRequest,
    DataReviewBatchConfirmResult,
    DataReviewBatchList,
    DataReviewIssueSummary,
    DataReviewItem,
    DataReviewItemList,
    DataReviewItemUpdate,
    DataReviewRevisionList,
    FeatureKnowledgeItem,
    FeatureKnowledgeList,
    KnowledgeAnswerHistory,
    KnowledgeAnswerPublish,
    KnowledgeAnswerReviewRequest,
    KnowledgeCandidateEvidenceList,
    KnowledgeDocumentArchiveResult,
    KnowledgeDocumentList,
    KnowledgeDraftAnswerRevision,
    KnowledgeDocumentExtractionItem,
    KnowledgeQuestionAsk,
    KnowledgeNewDraft,
    KnowledgeQuestionDelete,
    KnowledgeQuestionItem,
    KnowledgeQuestionList,
    KnowledgeQuestionResult,
    KnowledgeStats,
    LocalFileOpenRequest,
    LocalFileOpenResult,
)
from app.services.data_review import (
    batch_revise_data_review_items,
    get_data_review_item_history,
    list_data_review_batches,
    list_data_review_items,
    revise_data_review_item,
    stage_knowledge_document_review_items,
    summarize_data_review_issues,
)
from app.services.knowledge_documents import (
    KnowledgeDocumentInUseError,
    archive_knowledge_document,
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
    delete_pending_question,
    save_answer_draft,
    get_answer_history,
    get_question,
    list_questions,
    merge_question,
    publish_answer,
)
from app.services.knowledge_parameters import topics_for_question
from app.services.knowledge_configuration_answers import configuration_answer_history, configuration_answers
from app.services.knowledge_reviewed_answers import reviewed_answer, reviewed_workbook_citation
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


@router.get("/review-items/issue-summary", response_model=DataReviewIssueSummary)
async def get_review_issue_summary(
    data_type: str = Query(..., min_length=1, max_length=80),
    batch_id: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_db),
):
    """一个批次的待修正问题分布：按问题类型给出条数，供批量处理入口使用。"""

    try:
        return DataReviewIssueSummary(
            **summarize_data_review_issues(
                _database_path(db), data_type=data_type, batch_id=batch_id
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/review-items/batch-confirm", response_model=DataReviewBatchConfirmResult)
async def batch_confirm_review_items(
    payload: DataReviewBatchConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
    """按问题类型批量确认或排除待修正行；默认只预览。

    与逐条修正同一套纪律：`dry_run=True`（默认）只返回将命中的行，显式
    `dry_run=false` 才落库，并为每行写一条留痕。冻结批次会被拒绝。
    """

    try:
        return DataReviewBatchConfirmResult(
            **batch_revise_data_review_items(
                _database_path(db), **payload.model_dump()
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
        scope = data.scope.model_dump() if data.scope else None
        if data.unified:
            if a_only_question(data.question):
                return KnowledgeQuestionResult(status="outside_scope", question=data.question, match_type="none", similarity=0)
            scope = await infer_question_scope(db, data.question, scope)
            reviewed = await reviewed_answer(
                db, data.question, scope, configuration_version_id=data.configuration_version_id,
            )
            if reviewed is not None:
                answered = reviewed["status"] == "configuration"
                return KnowledgeQuestionResult(
                    question=data.question, scope=scope, match_type="exact" if answered else "none",
                    similarity=1 if answered else 0, **reviewed,
                )
        topics = await topics_for_question(db, data.question)
        configured = await configuration_answers(
            db, data.question, scope, topics, configuration_version_id=data.configuration_version_id, unified=data.unified,
        )
        if configured is not None:
            return KnowledgeQuestionResult(
                status="configuration", question=data.question, match_type="exact", similarity=1,
                configuration_answers=configured, scope=await resolve_query_scope(db, scope) if data.unified else None,
            )
        result = await ask_question(db, data.question, scope=scope, record_unanswered=not data.unified)
        result['parameter_topics'] = topics
        return KnowledgeQuestionResult(**result)
    except (KnowledgeQaError, KnowledgeScopeError) as exc:
        await db.rollback()
        raise HTTPException(status_code=503 if isinstance(exc, KnowledgeScopeUnavailable) else 422, detail=str(exc)) from exc


@router.get("/reviewed-facts/{market}/{key}/sources/{source_index}")
async def locate_reviewed_fact_source(
    market: str, key: str, source_index: int, response: Response,
    version_id: str = Query(..., pattern=r"^[a-f0-9]{64}$"),
    db: AsyncSession = Depends(get_db),
):
    if market not in {"domestic", "overseas"} or source_index < 0:
        raise HTTPException(status_code=422, detail="市场或来源索引无效")
    try:
        result = await reviewed_workbook_citation(db, market, key, source_index, version_id)
    except CitationSourceError as error:
        raise HTTPException(status_code=error.status, detail=str(error)) from error
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/questions/configuration-history")
async def get_configuration_history(
    recipe: str = Query(..., pattern=r"^(?:runtime:(?:v10|v8|v6iq|v5iq|v6|v5|a5)|parameter:[1-9][0-9]{0,9})$"),
    model_id: int = Query(..., gt=0),
    db: AsyncSession = Depends(get_db),
):
    return {"items": await configuration_answer_history(db, recipe, model_id)}


@router.get("/questions/configuration-issues")
async def get_configuration_issues(db: AsyncSession = Depends(get_db)):
    from app.services.knowledge_cart_facts import cart_fact_issues, merge_configuration_issues
    from app.services.knowledge_configuration_answers import configuration_answer_issues

    issues = merge_configuration_issues(await configuration_answer_issues(db), await cart_fact_issues(db))
    return {"items": [issue for issue in issues if issue["kind"] == "owner_decision"],
            "source_gaps": [issue for issue in issues if issue["kind"] != "owner_decision"]}


@router.get("/questions", response_model=KnowledgeQuestionList)
async def get_knowledge_questions(
    status: str | None = Query(None, pattern="^(pending|answered)$"),
    q: str | None = Query(None, max_length=200),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    country: str | None = Query(None, max_length=10),
    market: str | None = Query(None, pattern="^(domestic|overseas)$"),
    product_model_id: int | None = Query(None, gt=0),
    software_version: str | None = Query(None, max_length=80),
    evidence_review: str | None = Query(None, pattern="^(all|needs_review|reviewed)$"),
    workflow: str | None = Query(None, pattern="^(draft|unanswered)$"),
    all_scopes: bool = False,
    managed: bool = False,
    db: AsyncSession = Depends(get_db),
):
    scope = {"country": country, "market": market, "product_model_id": product_model_id, "software_version": software_version}
    try:
        items, total = await list_questions(db, status=status, query=q, skip=skip, limit=limit,
                                            scope=scope if any(value is not None for value in scope.values()) else None,
                                            evidence_review=evidence_review, workflow=workflow, all_scopes=all_scopes, managed=managed)
    except KnowledgeScopeError as exc:
        raise HTTPException(status_code=503 if isinstance(exc, KnowledgeScopeUnavailable) else 422, detail=str(exc)) from exc
    return KnowledgeQuestionList(items=items, total=total, skip=skip, limit=limit)


@router.post("/questions/{question_id}/review", response_model=KnowledgeQuestionItem)
async def confirm_answer_review(question_id: int, data: KnowledgeAnswerReviewRequest,
                                db: AsyncSession = Depends(get_db)):
    try:
        item = await review_answer(db, question_id, **data.model_dump())
    except (KnowledgeAnswerReviewError, KnowledgeScopeError, KnowledgeQaError) as exc:
        await db.rollback()
        code = 409 if isinstance(exc, KnowledgeAnswerReviewConflict) else (
            503 if isinstance(exc, (KnowledgeAnswerReviewUnavailable, KnowledgeScopeUnavailable)) else 422
        )
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="问题或答案不存在")
    return KnowledgeQuestionItem(**item)


@router.get("/questions/{question_id}", response_model=KnowledgeQuestionItem)
async def get_knowledge_question(
    question_id: int,
    db: AsyncSession = Depends(get_db),
):
    item = await get_question(db, question_id)
    if item is None:
        raise HTTPException(status_code=404, detail="问题不存在")
    return KnowledgeQuestionItem(**item)


@router.delete("/questions/{question_id}", status_code=204, response_class=Response)
async def remove_pending_question(
    question_id: int, data: KnowledgeQuestionDelete, db: AsyncSession = Depends(get_db),
):
    try:
        deleted = await delete_pending_question(db, question_id, **data.model_dump())
    except KnowledgeQaError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="问题不存在")
    return Response(status_code=204)


@router.put("/questions/{question_id}/draft-answer", response_model=KnowledgeQuestionItem)
async def update_answer_draft(
    question_id: int, data: KnowledgeDraftAnswerRevision, db: AsyncSession = Depends(get_db),
):
    try:
        item = await save_answer_draft(db, question_id, **data.model_dump())
    except KnowledgeQaError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="问题不存在")
    return KnowledgeQuestionItem(**item)


@router.post("/questions/draft", response_model=KnowledgeQuestionItem)
async def create_scoped_answer_draft(data: KnowledgeNewDraft, db: AsyncSession = Depends(get_db)):
    try:
        values = data.model_dump()
        scope = values.pop("scope")
        item = await save_answer_draft(db, None, new_scope=scope, **values)
    except (KnowledgeQaError, KnowledgeScopeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return KnowledgeQuestionItem(**item)


@router.put("/questions/{question_id}/answer", response_model=KnowledgeQuestionItem)
async def confirm_knowledge_answer(
    question_id: int,
    data: KnowledgeAnswerPublish,
    db: AsyncSession = Depends(get_db),
):
    try:
        # Serialize with pending-question deletion before reading its state.
        await db.execute(text("BEGIN IMMEDIATE"))
        item = await publish_answer(
            db,
            question_id=question_id,
            **data.model_dump(),
        )
    except (KnowledgeQaError, KnowledgeScopeError) as exc:
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
        # Serialize with pending-question deletion before reading its state.
        await db.execute(text("BEGIN IMMEDIATE"))
        item = await merge_question(
            db,
            source_question_id=source_question_id,
            target_question_id=target_question_id,
        )
    except (KnowledgeQaError, KnowledgeScopeError) as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="问题不存在")
    return KnowledgeQuestionItem(**item)


@router.get("/questions/{question_id}/spreadsheet-citations")
async def spreadsheet_citations(
    question_id: int, response: Response, expected_version: int | None = Query(None, ge=1),
    draft_revision: int | None = Query(None, gt=0),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await answer_spreadsheet_citations(db, question_id, expected_version, draft_revision=draft_revision)
    except CitationSourceError as error:
        raise HTTPException(status_code=error.status, detail=str(error)) from error
    response.headers['Cache-Control'] = 'no-store'
    return result


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


@router.get("/feature-coverage")
async def feature_coverage(db: AsyncSession = Depends(get_db)):
    from app.services.feature_catalog import feature_catalog_coverage
    return await feature_catalog_coverage(db)


@router.get("/features", response_model=FeatureKnowledgeList)
async def list_knowledge_features(
    q: str | None = Query(None, max_length=200),
    identity_status: str | None = Query(
        None,
        pattern="^(auto_matched|confirmed|related|pending)$",
    ),
    missing_name: str | None = Query(None, pattern="^(cn|en)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    items, total = await list_feature_knowledge(
        db,
        query=q,
        identity_status=identity_status,
        missing_name=missing_name,
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


@router.get("/documents/{document_id}/evidence")
async def locate_citation(
    document_id: int,
    response: Response,
    version_id: str = Query(..., pattern=r"^[a-f0-9]{64}$"),
    page: int | None = Query(None, ge=1, le=10000),
    chunk_id: int | None = Query(None, ge=1),
    quote: str | None = Query(None, min_length=6, max_length=400),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await citation_evidence(db, document_id, version_id, page=page, chunk_id=chunk_id, quote=quote)
        response.headers['Cache-Control'] = 'no-store'
        return result
    except CitationSourceError as error:
        raise HTTPException(status_code=error.status, detail=str(error)) from error


@router.get("/documents/{document_id}/preview")
async def preview_document(
    document_id: int,
    version_id: str | None = Query(None, pattern=r"^[a-f0-9]{64}$"),
    db: AsyncSession = Depends(get_db),
):
    if version_id is not None:
        try:
            document, data = await verified_original(db, document_id, version_id)
        except CitationSourceError as error:
            raise HTTPException(status_code=error.status, detail=str(error)) from error
        from urllib.parse import quote as encode_filename
        return Response(data, media_type=document['mime_type'] or mimetypes.guess_type(document['file_name'])[0] or 'application/octet-stream',
                        headers={'Cache-Control': 'no-store', 'Content-Disposition': "inline; filename*=UTF-8''" + encode_filename(document['file_name'])})
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


@router.post(
    "/documents/{document_id}/archive",
    response_model=KnowledgeDocumentArchiveResult,
)
async def archive_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    """退役一份受控资料：不再出现在列表与检索中，并清除其派生数据（原件不动）。"""

    try:
        result = await archive_knowledge_document(db, document_id=document_id)
    except KnowledgeDocumentInUseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="资料不存在")
    return KnowledgeDocumentArchiveResult(**result)


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


@router.post('/features/{feature_id}/detail')
async def read_feature_detail(
    feature_id: int,
    data: FeatureDetailRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await feature_detail(db, feature_id, scope=data.scope.model_dump() if data.scope else None,
                                    configuration_version_id=data.configuration_version_id)
    except (KnowledgeScopeError, ParameterError, ReleaseHistoryError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if item is None:
        raise HTTPException(status_code=404, detail='功能不存在')
    return item

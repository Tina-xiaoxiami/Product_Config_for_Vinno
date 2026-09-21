"""功能发布 API：功能版本、首发版本查询、发布介绍与候选回填。

回答两类问题：
- 「某个功能在哪个版本发布」→ `GET /api/release/features/{feature_id}/versions`
- 「某个版本发布了哪些功能」→ `GET /api/release/versions?software_version=1.14.80`

候选回填默认只预览；只有显式 `apply=true` 才以 `review_status='pending'` 落库，
确认前不会进入正式结论。
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.release import (
    FeatureReleaseTimeline,
    ReleaseAttachmentDeleteResult,
    ReleaseBackfillPreview,
    ReleaseBackfillRequest,
    ReleaseBatchReviewRequest,
    ReleaseBatchReviewResult,
    ReleaseEvidenceDocumentList,
    ReleaseIntroductionHistory,
    ReleaseIntroductionItem,
    ReleaseIntroductionSave,
    ReleaseTemplateCreate,
    ReleaseTemplateItem,
    ReleaseTemplateList,
    ReleaseTemplateUpdate,
    ReleaseVersionCreate,
    ReleaseVersionItem,
    ReleaseVersionList,
    ReleaseVersionOverviewList,
    ReleaseVersionRevisionList,
    ReleaseVersionUpdate,
)
from app.services.feature_release_backfill import (
    apply_feature_version_candidates,
    preview_feature_version_candidates,
)
from app.services.release_documents import (
    DOCX_MIME_TYPE,
    ReleaseDocumentError,
    ReleaseDocumentSystemTemplateError,
    create_template,
    delete_template,
    export_release_document,
    list_templates,
    update_template,
)
from app.services.feature_release_versions import (
    FeatureReleaseAttachmentError,
    FeatureReleaseError,
    FeatureReleaseNotFoundError,
    add_introduction_attachment,
    batch_review_feature_versions,
    create_feature_version,
    delete_feature_version,
    delete_introduction_attachment,
    get_feature_release_timeline,
    get_feature_version,
    get_introduction,
    list_evidence_documents,
    list_feature_version_revisions,
    list_versions_by_software_version,
    list_introduction_history,
    list_release_versions_overview,
    save_introduction,
    update_feature_version,
)


router = APIRouter()


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FeatureReleaseAttachmentError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, FeatureReleaseNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    # 系统内置模板不可改不可删，属状态冲突而不是参数错误。
    if isinstance(exc, ReleaseDocumentSystemTemplateError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ReleaseDocumentError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/overview", response_model=ReleaseVersionOverviewList)
async def release_version_overview(db: AsyncSession = Depends(get_db)):
    items = await list_release_versions_overview(db)
    return ReleaseVersionOverviewList(items=items)


@router.get("/versions", response_model=ReleaseVersionList)
async def list_release_versions(
    software_version: str | None = Query(None, max_length=50),
    product_series: str | None = Query(None, max_length=100),
    market: str | None = Query(None, max_length=30),
    review_status: str | None = Query(None, pattern="^(pending|confirmed|rejected)$"),
    q: str | None = Query(None, max_length=200),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    items, total = await list_versions_by_software_version(
        db,
        software_version=software_version,
        product_series=product_series,
        market=market,
        review_status=review_status,
        query=q,
        skip=skip,
        limit=limit,
    )
    return ReleaseVersionList(items=items, total=total, skip=skip, limit=limit)


@router.get("/evidence-documents", response_model=ReleaseEvidenceDocumentList)
async def release_evidence_documents(
    version: str | None = Query(None, max_length=50),
    db: AsyncSession = Depends(get_db),
):
    items = await list_evidence_documents(db, version=version)
    return ReleaseEvidenceDocumentList(items=items)


@router.get("/features/{feature_id}/versions", response_model=FeatureReleaseTimeline)
async def feature_release_timeline(
    feature_id: int,
    product_series: str | None = Query(None, max_length=100),
    db: AsyncSession = Depends(get_db),
):
    timeline = await get_feature_release_timeline(
        db, feature_id, product_series=product_series
    )
    if timeline is None:
        raise HTTPException(status_code=404, detail="功能不存在")
    return FeatureReleaseTimeline(**timeline)


@router.post("/features/{feature_id}/versions", response_model=ReleaseVersionItem)
async def create_release_version(
    feature_id: int,
    data: ReleaseVersionCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await create_feature_version(db, feature_id, **data.model_dump())
    except FeatureReleaseError as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    return ReleaseVersionItem(**item)


@router.get("/versions/{version_id}", response_model=ReleaseVersionItem)
async def get_release_version(version_id: int, db: AsyncSession = Depends(get_db)):
    try:
        item = await get_feature_version(db, version_id)
    except FeatureReleaseError as exc:
        raise _http_error(exc) from exc
    return ReleaseVersionItem(**item)


@router.put("/versions/{version_id}", response_model=ReleaseVersionItem)
async def update_release_version(
    version_id: int,
    data: ReleaseVersionUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await update_feature_version(
            db,
            version_id,
            fields_set=set(data.model_fields_set),
            **data.model_dump(exclude_unset=True),
        )
    except FeatureReleaseError as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    return ReleaseVersionItem(**item)


@router.post("/versions/batch-review", response_model=ReleaseBatchReviewResult)
async def batch_review_release_versions(
    data: ReleaseBatchReviewRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量确认或驳回待复核的功能版本；默认只预览。

    与候选回填同一套纪律：`dry_run=True`（默认）只返回将命中的记录与分组计数，
    显式 `dry_run=false` 才落库，并为每一行写一条留痕。
    """

    try:
        result = await batch_review_feature_versions(db, **data.model_dump())
    except FeatureReleaseError as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    return ReleaseBatchReviewResult(**result)


@router.get(
    "/versions/{version_id}/revisions",
    response_model=ReleaseVersionRevisionList,
)
async def release_version_revisions(version_id: int, db: AsyncSession = Depends(get_db)):
    """一条功能版本的留痕：谁、什么时候、把哪一行从什么状态改成了什么状态。"""

    try:
        items = await list_feature_version_revisions(db, version_id)
    except FeatureReleaseError as exc:
        raise _http_error(exc) from exc
    return ReleaseVersionRevisionList(items=items)


@router.delete("/versions/{version_id}")
async def delete_release_version(version_id: int, db: AsyncSession = Depends(get_db)):
    try:
        await delete_feature_version(db, version_id)
    except FeatureReleaseError as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    return {"message": "删除成功"}


@router.get("/versions/{version_id}/introduction", response_model=ReleaseIntroductionItem)
async def get_release_introduction(version_id: int, db: AsyncSession = Depends(get_db)):
    introduction = await get_introduction(db, version_id)
    if introduction is None:
        raise HTTPException(status_code=404, detail="该功能版本还没有发布介绍")
    return ReleaseIntroductionItem(**introduction)


@router.put("/versions/{version_id}/introduction", response_model=ReleaseIntroductionItem)
async def save_release_introduction(
    version_id: int,
    data: ReleaseIntroductionSave,
    db: AsyncSession = Depends(get_db),
):
    try:
        introduction = await save_introduction(
            db,
            version_id,
            summary=data.summary,
            clinical_significance=data.clinical_significance,
            workflow=data.workflow,
            applications=data.applications,
            review_status=data.review_status,
            change_note=data.change_note,
            fields_set=set(data.model_fields_set),
        )
    except FeatureReleaseError as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    return ReleaseIntroductionItem(**introduction)


@router.get(
    "/versions/{version_id}/introduction/history",
    response_model=ReleaseIntroductionHistory,
)
async def release_introduction_history(
    version_id: int,
    db: AsyncSession = Depends(get_db),
):
    try:
        items = await list_introduction_history(db, version_id)
    except FeatureReleaseError as exc:
        raise _http_error(exc) from exc
    return ReleaseIntroductionHistory(items=items)


@router.post(
    "/versions/{version_id}/introduction/attachments",
    response_model=ReleaseIntroductionItem,
)
async def upload_release_attachment(
    version_id: int,
    file: UploadFile = File(...),
    sort_order: int = Query(0, ge=0),
    overwrite: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="附件内容为空")
    try:
        await add_introduction_attachment(
            db,
            version_id,
            file_name=file.filename or "",
            payload=payload,
            sort_order=sort_order,
            overwrite=overwrite,
        )
    except FeatureReleaseError as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    introduction = await get_introduction(db, version_id)
    return ReleaseIntroductionItem(**introduction)


@router.delete(
    "/introduction-attachments/{attachment_id}",
    response_model=ReleaseAttachmentDeleteResult,
)
async def delete_release_attachment(
    attachment_id: int,
    remove_file: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    try:
        await delete_introduction_attachment(
            db, attachment_id, remove_file=remove_file
        )
    except FeatureReleaseError as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    return ReleaseAttachmentDeleteResult(
        attachment_id=attachment_id,
        status="deleted",
        removed_file=remove_file,
    )


@router.post("/backfill", response_model=ReleaseBackfillPreview)
async def backfill_release_versions(
    data: ReleaseBackfillRequest,
    db: AsyncSession = Depends(get_db),
):
    """按 Release Note 正文生成候选；默认只预览，`apply=true` 才落库。"""

    preview = await preview_feature_version_candidates(
        db,
        product_series=data.product_series,
        software_versions=data.software_versions,
        feature_ids=data.feature_ids,
        limit=data.limit,
    )
    if not data.apply:
        return ReleaseBackfillPreview(**preview, applied=False, created=0)

    created = await apply_feature_version_candidates(db, preview["candidates"])
    refreshed = await preview_feature_version_candidates(
        db,
        product_series=data.product_series,
        software_versions=data.software_versions,
        feature_ids=data.feature_ids,
        limit=data.limit,
    )
    return ReleaseBackfillPreview(**refreshed, applied=True, created=created)


# --------------------------------------------------------------------------
# 文档模板与 Word 导出
# --------------------------------------------------------------------------


@router.get("/templates", response_model=ReleaseTemplateList)
async def release_templates(db: AsyncSession = Depends(get_db)):
    items = await list_templates(db)
    return ReleaseTemplateList(items=items)


@router.post("/templates", response_model=ReleaseTemplateItem)
async def create_release_template(
    data: ReleaseTemplateCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await create_template(db, **data.model_dump())
    except FeatureReleaseError as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    return ReleaseTemplateItem(**item)


@router.put("/templates/{template_id}", response_model=ReleaseTemplateItem)
async def update_release_template(
    template_id: int,
    data: ReleaseTemplateUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await update_template(
            db,
            template_id,
            fields_set=set(data.model_fields_set),
            **data.model_dump(exclude_unset=True),
        )
    except FeatureReleaseError as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    return ReleaseTemplateItem(**item)


@router.delete("/templates/{template_id}")
async def remove_release_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
):
    try:
        await delete_template(db, template_id)
    except FeatureReleaseError as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    return {"message": "删除成功"}


@router.get("/versions/{version_id}/introduction/export")
async def export_release_introduction(
    version_id: int,
    template_id: int | None = Query(None, ge=1),
    db: AsyncSession = Depends(get_db),
):
    """导出该功能版本的发布介绍 Word 文件。"""

    try:
        payload, filename = await export_release_document(
            db, version_id, template_id=template_id
        )
    except FeatureReleaseError as exc:
        raise _http_error(exc) from exc

    # 中文文件名同时给 RFC 5987 与 ASCII 兜底，避免旧客户端下载成乱码。
    ascii_name = "".join(
        character if character.isascii() and character not in '"\\' else "_"
        for character in filename
    ) or "release_introduction.docx"
    disposition = (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(filename)}"
    )
    return StreamingResponse(
        iter([payload]),
        media_type=DOCX_MIME_TYPE,
        headers={
            "Content-Disposition": disposition,
            "Content-Length": str(len(payload)),
        },
    )

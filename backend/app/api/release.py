"""功能发布 API：功能版本、首发版本查询、发布介绍与候选回填。

回答两类问题：
- 「某个功能在哪个版本发布」→ `GET /api/release/features/{feature_id}/versions`
- 「某个版本发布了哪些功能」→ `GET /api/release/versions?software_version=1.14.80`

候选回填默认只预览；只有显式 `apply=true` 才以 `review_status='pending'` 落库，
确认前不会进入正式结论。
"""

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.release import (
    FeatureReleaseTimeline,
    ReleaseAttachmentDeleteResult,
    ReleaseBackfillPreview,
    ReleaseBackfillRequest,
    ReleaseEvidenceDocumentList,
    ReleaseIntroductionHistory,
    ReleaseIntroductionItem,
    ReleaseIntroductionSave,
    ReleaseVersionCreate,
    ReleaseVersionItem,
    ReleaseVersionList,
    ReleaseVersionOverviewList,
    ReleaseVersionUpdate,
)
from app.services.feature_release_backfill import (
    apply_feature_version_candidates,
    preview_feature_version_candidates,
)
from app.services.feature_release_versions import (
    FeatureReleaseAttachmentError,
    FeatureReleaseError,
    FeatureReleaseNotFoundError,
    add_introduction_attachment,
    create_feature_version,
    delete_feature_version,
    delete_introduction_attachment,
    get_feature_release_timeline,
    get_feature_version,
    get_introduction,
    list_evidence_documents,
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

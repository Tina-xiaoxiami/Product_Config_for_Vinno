"""国内注册红线与产品策略查询 API。"""

import hashlib
import json
import mimetypes
from pathlib import Path
import tempfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.registration import (
    ConfiguredRegistrationModelList,
    RegistrationMasterProbeList,
    RegistrationModelList,
    RegistrationPackageList,
    RegistrationPackageMappingUpdate,
    RegistrationPackagePublishRequest,
    RegistrationPackageVersionItem,
    RegistrationPackageVersionList,
    RegistrationProbeStrategyList,
)
from app.services.registration_packages import (
    get_registration_package_version_mapping_review,
    RegistrationPackageError,
    publish_registration_package_version,
    stage_registration_package_draft,
    update_registration_package_version_mappings,
)
from app.services.registration_package_query import (
    get_registration_package_artifact,
    get_registration_package_version,
    list_registration_package_versions,
    list_registration_packages,
)
from app.services.registration_query import (
    list_configured_registration_models,
    list_product_registration_probes,
    list_registration_model_probes,
    list_registration_models,
)


router = APIRouter()


def _database_path(db: AsyncSession) -> Path:
    bind = db.bind
    database = getattr(getattr(bind, "url", None), "database", None)
    if not database:
        raise HTTPException(status_code=500, detail="无法确定注册数据库路径")
    return Path(str(database)).resolve()


async def _save_upload(upload: UploadFile, directory: Path, fallback_name: str) -> Path:
    content = await upload.read()
    if not content:
        raise HTTPException(status_code=400, detail=f"{fallback_name}不能为空")
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"{fallback_name}不能超过100MB")
    name = Path(upload.filename or fallback_name).name
    target = directory / name
    target.write_bytes(content)
    return target


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@router.get("/packages", response_model=RegistrationPackageList)
async def registration_packages(
    country_code: str = Query("CN", pattern="^[A-Z]{2}$"),
    db: AsyncSession = Depends(get_db),
):
    items = await list_registration_packages(db, country_code=country_code)
    return RegistrationPackageList(items=items, total=len(items))


@router.post("/packages/drafts")
async def create_registration_package_draft(
    certificate: UploadFile = File(...),
    difference: UploadFile = File(...),
    country_code: str = Form("CN", pattern="^[A-Z]{2}$"),
    unit_code: str = Form(...),
    display_name: str = Form(...),
    product_series: str | None = Form(None),
    registration_number: str = Form(...),
    certificate_version: str | None = Form(None),
    difference_version: str | None = Form(None),
    confirmed_by: str = Form(...),
    change_note: str | None = Form(None),
    effective_date: str | None = Form(None),
    mappings_json: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    try:
        mappings = None
        if mappings_json:
            raw_mappings = json.loads(mappings_json)
            mappings = {int(key): str(value) for key, value in raw_mappings.items()}
        with tempfile.TemporaryDirectory(prefix="registration-pair-") as temporary:
            directory = Path(temporary)
            certificate_path = await _save_upload(
                certificate, directory, "certificate.pdf"
            )
            difference_path = await _save_upload(
                difference, directory, "difference.xlsx"
            )
            return stage_registration_package_draft(
                _database_path(db),
                country_code=country_code,
                unit_code=unit_code,
                display_name=display_name,
                product_series=product_series,
                registration_number=registration_number,
                certificate_path=certificate_path,
                difference_path=difference_path,
                certificate_version=certificate_version,
                difference_version=difference_version,
                confirmed_by=confirmed_by,
                change_note=change_note,
                effective_date=effective_date,
                product_model_mappings=mappings,
            )
    except (json.JSONDecodeError, TypeError, ValueError, RegistrationPackageError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/package-versions/{version_id}/mappings")
async def update_registration_package_mappings(
    version_id: int,
    payload: RegistrationPackageMappingUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        return update_registration_package_version_mappings(
            _database_path(db),
            version_id=version_id,
            product_model_mappings=payload.mappings,
        )
    except RegistrationPackageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/package-versions/{version_id}/mappings")
async def registration_package_mappings(
    version_id: int,
    db: AsyncSession = Depends(get_db),
):
    try:
        return get_registration_package_version_mapping_review(
            _database_path(db), version_id=version_id
        )
    except RegistrationPackageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/package-versions/{version_id}/publish")
async def publish_registration_package(
    version_id: int,
    payload: RegistrationPackagePublishRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return publish_registration_package_version(
            _database_path(db),
            version_id=version_id,
            confirmed_by=payload.confirmed_by,
        )
    except RegistrationPackageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/packages/{package_id}/versions",
    response_model=RegistrationPackageVersionList,
)
async def registration_package_versions(
    package_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await list_registration_package_versions(db, package_id=package_id)
    if result is None:
        raise HTTPException(status_code=404, detail="注册资料包不存在")
    return RegistrationPackageVersionList(**result)


@router.get(
    "/package-versions/{version_id}",
    response_model=RegistrationPackageVersionItem,
)
async def registration_package_version(
    version_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await get_registration_package_version(db, version_id=version_id)
    if result is None:
        raise HTTPException(status_code=404, detail="注册资料包版本不存在")
    return RegistrationPackageVersionItem(**result)


@router.get("/package-versions/{version_id}/artifacts/{artifact_type}")
async def registration_package_artifact(
    version_id: int,
    artifact_type: str,
    db: AsyncSession = Depends(get_db),
):
    if artifact_type not in {"certificate", "difference"}:
        raise HTTPException(status_code=404, detail="注册原件类型不存在")
    artifact = await get_registration_package_artifact(
        db,
        version_id=version_id,
        artifact_type=artifact_type,
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="注册资料包版本不存在")
    path = Path(str(artifact["file_path"] or ""))
    if not path.is_absolute() or not path.is_file():
        raise HTTPException(status_code=410, detail="受控注册原件不存在")
    digest = _file_sha256(path)
    if digest != artifact["sha256"]:
        raise HTTPException(status_code=409, detail="受控注册原件哈希校验失败")
    media_type = artifact["mime_type"] or mimetypes.guess_type(path.name)[0]
    return FileResponse(
        path=path,
        media_type=media_type or "application/octet-stream",
        filename=artifact["file_name"] or path.name,
        content_disposition_type="inline",
    )


@router.get("/configured-models", response_model=ConfiguredRegistrationModelList)
async def configured_registration_models(
    country_code: str = Query("CN", pattern="^[A-Z]{2}$"),
    db: AsyncSession = Depends(get_db),
):
    items = await list_configured_registration_models(
        db,
        country_code=country_code,
    )
    return ConfiguredRegistrationModelList(items=items, total=len(items))


@router.get("/models", response_model=RegistrationModelList)
async def registration_models(
    country_code: str = Query("CN", pattern="^[A-Z]{2}$"),
    q: str | None = Query(None, max_length=200),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    items, total = await list_registration_models(
        db,
        country_code=country_code,
        query=q,
        skip=skip,
        limit=limit,
    )
    return RegistrationModelList(items=items, total=total, skip=skip, limit=limit)


@router.get(
    "/models/{registration_model_id}/probes",
    response_model=RegistrationMasterProbeList,
)
async def registration_model_probes(
    registration_model_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await list_registration_model_probes(
        db,
        registration_model_id=registration_model_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="注册型号不存在")
    return RegistrationMasterProbeList(**result)


@router.get("/probes", response_model=RegistrationProbeStrategyList)
async def product_registration_probes(
    product_model_id: int = Query(..., ge=1),
    q: str | None = Query(None, max_length=200),
    registration_status: str | None = Query(
        None,
        pattern="^(registered|unregistered)$",
    ),
    effective_status: str | None = Query(
        None,
        pattern="^(X|O|Δ|#|未定义)$",
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    result = await list_product_registration_probes(
        db,
        product_model_id=product_model_id,
        query=q,
        registration_status=registration_status,
        effective_status=effective_status,
        skip=skip,
        limit=limit,
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="产品型号尚未关联对应注册证及注册基础型号",
        )
    return RegistrationProbeStrategyList(**result)

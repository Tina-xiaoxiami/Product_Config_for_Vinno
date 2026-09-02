"""国内注册红线与产品策略查询 API。"""

import hashlib
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.registration import (
    ConfiguredRegistrationModelList,
    RegistrationMasterProbeList,
    RegistrationModelList,
    RegistrationPackageList,
    RegistrationPackageVersionItem,
    RegistrationPackageVersionList,
    RegistrationProbeStrategyList,
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
        raise HTTPException(status_code=404, detail="产品型号尚未关联注册基础型号")
    return RegistrationProbeStrategyList(**result)

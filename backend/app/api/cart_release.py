"""Read, retry and backfill Cart release checks from configuration history."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select

from app.database import get_db
from app.models import CartReleaseCheck, ConfigVersion
from app.services.cart_release import (
    cart_check_history, check_payload, get_cart_check, presentation_for_check,
    refresh_cart_for_facts, reserve_cart_backfill, save_cart_check,
)

from app.services.knowledge_sources import CitationSourceError


router = APIRouter()
PPTX_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


async def _version(db, version_id):
    version = await db.get(ConfigVersion, version_id)
    if version is None:
        raise HTTPException(404, "版本不存在")
    return version


@router.get("/{version_id}/cart-release")
async def read_check(version_id: int, download: bool = False, db=Depends(get_db)):
    version = await _version(db, version_id)
    check = await get_cart_check(db, version)
    if check is None:
        return {"status": "not_checked", "reason": "历史版本尚未检查，可补跑 Cart 检查"}
    return await _report(db, check, download, version=version)


async def _report(db, check, download, *, version=None):
    result = await _presentation_report(db, check, version=version)
    if download:
        return JSONResponse(result, headers={
            "Content-Disposition": f'attachment; filename="cart-config-{check.version_id}.json"',
        })
    return result


@router.post("/{version_id}/cart-release")
async def retry_check(version_id: int, db=Depends(get_db)):
    await reserve_cart_backfill(db)
    version = await _version(db, version_id)
    check = await get_cart_check(db, version)
    if check and check.report.get("facts"):
        await refresh_cart_for_facts(db, check.report["facts"], version_id=version_id)
        check = await get_cart_check(db, version)
    else:
        check = await save_cart_check(db, version, "backfill")
    await db.commit()
    result = await _presentation_report(db, check, version=version)
    return result


@router.get("/{version_id}/cart-release/history")
async def read_history(version_id: int, limit: int = Query(20, ge=1, le=100), db=Depends(get_db)):
    checks = await cart_check_history(db, await _version(db, version_id), limit)
    return {"items": [{
        "key": check.version_key, "origin": check.report["origin"], "status": check.report["status"],
        "artifact_sha256": check.artifact_sha256, "checked_at": check.checked_at.isoformat(),
    } for check in checks]}


@router.get("/{version_id}/cart-release/presentation")
async def download_presentation(version_id: int, db=Depends(get_db)):
    version = await _version(db, version_id)
    return await _presentation(db, await get_cart_check(db, version), version=version)


async def _presentation_report(db, check, *, version=None):
    result = check_payload(check)
    try:
        result["presentation"], _ = await presentation_for_check(db, check, version=version)
    except CitationSourceError as error:
        result["presentation_unavailable"] = str(error)
    return result


async def _presentation(db, check, *, version=None):
    try:
        presentation, data = await presentation_for_check(db, check, version=version, include_data=True)
    except CitationSourceError as error:
        raise HTTPException(error.status, str(error)) from error
    source, kind = presentation["source"], presentation["kind"]
    headers = {"X-Cart-Presentation-Kind": kind}
    if source:
        headers.update({"X-Cart-Source-Config-Id": str(source["id"]),
                        "X-Cart-Source-Config-Version": quote(source["number"])})
        filename = f"cart-{presentation['market']}-config-{source['id']}-{presentation['sha256'][:12]}-candidate.pptx"
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    else:
        headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(presentation['file'])}"
    return Response(data, media_type=PPTX_TYPE, headers=headers)


@router.post("/cart-release/backfill")
async def backfill_checks(
    series_id: int = Query(ge=1),
    after_id: int = Query(0, ge=0),
    through_id: int | None = Query(None, ge=1),
    limit: int = Query(10, ge=1, le=20),
    db=Depends(get_db),
):
    await reserve_cart_backfill(db)
    query = select(ConfigVersion).where(ConfigVersion.series_id == series_id, ConfigVersion.id > after_id)
    if through_id is not None:
        query = query.where(ConfigVersion.id <= through_id)
    versions = (await db.scalars(query.order_by(ConfigVersion.id).limit(limit + 1))).all()
    results = []
    for version in versions[:limit]:
        check = await save_cart_check(db, version, "backfill")
        results.append({"version_id": version.id, "status": check.report["status"]})
    await db.commit()
    return {"items": results, "next_after_id": results[-1]["version_id"] if len(versions) > limit else None}


async def _archived_check(db, key):
    check = await db.get(CartReleaseCheck, key) if len(key) == 64 else None
    if check is None:
        raise HTTPException(404, "Cart 检查记录不存在")
    return check


@router.get("/cart-release/archive/{key}")
async def read_archived_check(key: str, download: bool = False, db=Depends(get_db)):
    return await _report(db, await _archived_check(db, key), download)


@router.get("/cart-release/archive/{key}/presentation")
async def download_archived_presentation(key: str, db=Depends(get_db)):
    return await _presentation(db, await _archived_check(db, key))

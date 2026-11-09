"""应用定义 API"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field
from typing import Literal
import json
from app.database import get_db
from app.utils.time import utcnow
from app.models.probe import Application, ProbeModelApp, ProbeCategory, CategoryApplication, ApplicationVersion
from app.schemas.probe import (
    ApplicationCreate, ApplicationUpdate,
    ApplicationResponse, ApplicationListResponse,
)

from app.services.probe_applications import application_probe_usage, application_probes

router = APIRouter()


@router.get("", response_model=ApplicationListResponse)
async def list_applications(skip: int = 0, limit: int = 200, db: AsyncSession = Depends(get_db)):
    count_r = await db.execute(select(func.count()).select_from(Application))
    total = count_r.scalar()
    result = await db.execute(select(Application).order_by(Application.sort_order).offset(skip).limit(limit))
    apps = result.scalars().all()

    # Add usage count and probe_type info
    if apps:
        app_ids = [a.id for a in apps]
        usage_map = await application_probe_usage(db, app_ids)
        # Get probe_type info from CategoryApplication
        type_r = await db.execute(
            select(CategoryApplication.application_id, CategoryApplication.probe_type)
            .where(CategoryApplication.application_id.in_(app_ids))
            .distinct()
        )
        type_map = {}
        for row in type_r.fetchall():
            type_map.setdefault(row[0], set()).add(row[1])
        for a in apps:
            a.usage_count = usage_map.get(a.id, 0)
            a.probe_types = sorted(type_map.get(a.id, set()))

    return ApplicationListResponse(items=apps, total=total)


@router.get("/{app_id}/probes")
async def get_app_probes(app_id: int, db: AsyncSession = Depends(get_db)):
    """获取使用该应用的所有探头型号"""
    return await application_probes(db, app_id)

@router.post("", response_model=ApplicationResponse)
async def create_application(data: ApplicationCreate, db: AsyncSession = Depends(get_db)):
    obj = Application(**data.model_dump())
    db.add(obj); await db.commit(); await db.refresh(obj)
    return obj


@router.put("/{app_id}", response_model=ApplicationResponse)
async def update_application(app_id: int, data: ApplicationUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Application).where(Application.id == app_id))
    obj = result.scalar_one_or_none()
    if not obj: raise HTTPException(status_code=404, detail="应用不存在")
    for f, v in data.model_dump(exclude_unset=True).items(): setattr(obj, f, v)
    await db.commit(); await db.refresh(obj)
    return obj


@router.delete("/{app_id}")
async def delete_application(app_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Application).where(Application.id == app_id))
    obj = result.scalar_one_or_none()
    if not obj: raise HTTPException(status_code=404, detail="应用不存在")
    referenced = await db.scalar(select(CategoryApplication.id).where(CategoryApplication.application_id == app_id).limit(1))
    historical = await db.scalar(select(ProbeModelApp.id).where(ProbeModelApp.application_id == app_id).limit(1))
    if referenced is not None or historical is not None:
        raise HTTPException(409, "应用仍有类别关联或历史型号应用记录，不能直接删除")
    await db.delete(obj); await db.commit()
    return {"message": "删除成功"}


# ========== 应用版本管理 ==========
async def add_app_version(db, version_number=None, description=None):
    rows = await db.execute(select(CategoryApplication, Application)
        .join(Application, CategoryApplication.application_id == Application.id)
        .order_by(CategoryApplication.category_id, CategoryApplication.application_id, CategoryApplication.probe_type))
    snapshot = [{"category_id": ca.category_id, "application_id": ca.application_id,
                 "probe_type": ca.probe_type, "app_name": app.name} for ca, app in rows.all()]
    number = version_number or f"v{utcnow().strftime('%Y%m%d%H%M%S')}"
    version = ApplicationVersion(version_number=number, description=description or "应用关联变更",
                                 snapshot_data=json.dumps(snapshot, ensure_ascii=False))
    db.add(version)
    return version


class AssociationChange(BaseModel):
    action: Literal['add', 'remove']
    category_id: int = Field(gt=0)
    application_id: int = Field(gt=0)
    probe_type: Literal['regular', 'poc']


class AssociationBatch(BaseModel):
    changes: list[AssociationChange] = Field(min_length=1, max_length=1000)
    version_number: str | None = Field(default=None, min_length=1, max_length=50)
    description: str = Field(default='应用关联变更', max_length=4000)


@router.post('/associations/batch')
async def apply_association_batch(data: AssociationBatch, db: AsyncSession = Depends(get_db)):
    """Commit all category changes and their version snapshot as one transaction."""
    try:
        from app.services.write_serialization import serialize_catalog_write
        await serialize_catalog_write(db, 'category_applications')
        keys = set()
        for change in data.changes:
            key = (change.category_id, change.application_id, change.probe_type)
            if key in keys:
                raise HTTPException(422, '同一类别应用关联不能重复提交')
            keys.add(key)
            if await db.get(ProbeCategory, change.category_id) is None or await db.get(Application, change.application_id) is None:
                raise HTTPException(404, '探头类别或应用不存在，请刷新后核对')
            existing = await db.scalar(select(CategoryApplication).where(
                CategoryApplication.category_id == change.category_id,
                CategoryApplication.application_id == change.application_id,
                CategoryApplication.probe_type == change.probe_type))
            if change.action == 'add':
                if existing is None:
                    db.add(CategoryApplication(category_id=change.category_id,
                        application_id=change.application_id, probe_type=change.probe_type))
            else:
                if existing is None:
                    raise HTTPException(409, '应用关联已变化，请刷新后重新核对')
                await db.delete(existing)
        await db.flush()
        version = await add_app_version(db, data.version_number, data.description)
        await db.commit()
        return {'message': f'已提交 {len(data.changes)} 项变更并创建版本', 'version_number': version.version_number}
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(409, '应用关联或版本号已变化，请刷新后重新核对') from error
    except Exception:
        await db.rollback()
        raise


@router.post("/version")
async def create_app_version(data: dict = None, db: AsyncSession = Depends(get_db)):
    version = await add_app_version(db, (data or {}).get('version_number'), (data or {}).get('description'))
    await db.commit()
    return {"message": f"版本 {version.version_number} 已创建"}


@router.get("/versions")
async def list_app_versions(db: AsyncSession = Depends(get_db)):
    """获取应用版本列表"""
    result = await db.execute(select(ApplicationVersion).order_by(ApplicationVersion.id.desc()).limit(50))
    return [{"id": v.id, "version_number": v.version_number, "description": v.description, "created_at": v.created_at} for v in result.scalars().all()]


@router.post("/rollback/{version_id}")
async def rollback_app_version(version_id: int, db: AsyncSession = Depends(get_db)):
    """回滚应用到指定版本"""
    r = await db.execute(select(ApplicationVersion).where(ApplicationVersion.id == version_id))
    ver = r.scalar_one_or_none()
    if not ver: raise HTTPException(status_code=404, detail="版本不存在")

    snap = json.loads(ver.snapshot_data)
    # Delete current category-application associations
    dr = await db.execute(select(CategoryApplication))
    for ca in dr.scalars().all(): await db.delete(ca)
    await db.flush()
    # Rebuild from snapshot
    for item in snap:
        db.add(CategoryApplication(
            category_id=item["category_id"],
            application_id=item["application_id"],
            probe_type=item.get("probe_type", "regular"),
        ))
    await db.commit()
    return {"message": f"已回滚到版本 {ver.version_number}"}

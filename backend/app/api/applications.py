"""应用定义 API"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import json
from app.database import get_db
from app.models.probe import Application, ProbeModelApp, ProbeModel, CategoryApplication, ApplicationVersion
from app.schemas.probe import (
    ApplicationCreate, ApplicationUpdate,
    ApplicationResponse, ApplicationListResponse,
)

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
        usage_r = await db.execute(
            select(ProbeModelApp.application_id, func.count(ProbeModelApp.id))
            .where(ProbeModelApp.application_id.in_(app_ids))
            .group_by(ProbeModelApp.application_id)
        )
        usage_map = {row[0]: row[1] for row in usage_r.fetchall()}
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
    result = await db.execute(
        select(ProbeModelApp, ProbeModel)
        .join(ProbeModel, ProbeModelApp.probe_model_id == ProbeModel.id)
        .where(ProbeModelApp.application_id == app_id)
        .order_by(ProbeModel.model_number)
    )
    return [{"probe_id": r.ProbeModel.id, "model_number": r.ProbeModel.model_number} for r in result.all()]


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
    await db.delete(obj); await db.commit()
    return {"message": "删除成功"}


# ========== 应用版本管理 ==========
@router.post("/version")
async def create_app_version(data: dict = None, db: AsyncSession = Depends(get_db)):
    """创建应用关联的快照版本"""
    r = await db.execute(
        select(CategoryApplication, Application)
        .join(Application, CategoryApplication.application_id == Application.id)
    )
    snap = []
    for ca, app in r.all():
        snap.append({
            "category_id": ca.category_id,
            "application_id": ca.application_id,
            "probe_type": ca.probe_type,
            "app_name": app.name,
        })
    ver_num = (data or {}).get("version_number") or f"v{__import__('datetime').datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    description = (data or {}).get("description") or "应用关联变更"
    db.add(ApplicationVersion(version_number=ver_num, description=description, snapshot_data=json.dumps(snap, ensure_ascii=False)))
    await db.commit()
    return {"message": f"版本 {ver_num} 已创建"}


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

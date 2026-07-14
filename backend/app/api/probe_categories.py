"""探头类别 API"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models.probe import ProbeCategory, CategoryApplication, Application
from app.schemas.probe import (
    ProbeCategoryCreate, ProbeCategoryUpdate,
    ProbeCategoryResponse, ProbeCategoryListResponse,
)

router = APIRouter()


@router.get("", response_model=ProbeCategoryListResponse)
async def list_categories(
    skip: int = 0, limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    count_r = await db.execute(select(func.count()).select_from(ProbeCategory))
    total = count_r.scalar()
    result = await db.execute(
        select(ProbeCategory).order_by(ProbeCategory.sort_order).offset(skip).limit(limit)
    )
    items = result.scalars().all()
    return ProbeCategoryListResponse(items=items, total=total)


@router.get("/{category_id}", response_model=ProbeCategoryResponse)
async def get_category(category_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProbeCategory).where(ProbeCategory.id == category_id))
    item = result.scalar_one_or_none()
    if not item:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="探头类别不存在")
    return item


@router.post("", response_model=ProbeCategoryResponse)
async def create_category(data: ProbeCategoryCreate, db: AsyncSession = Depends(get_db)):
    obj = ProbeCategory(**data.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.put("/{category_id}", response_model=ProbeCategoryResponse)
async def update_category(category_id: int, data: ProbeCategoryUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProbeCategory).where(ProbeCategory.id == category_id))
    obj = result.scalar_one_or_none()
    if not obj:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="探头类别不存在")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/{category_id}")
async def delete_category(category_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProbeCategory).where(ProbeCategory.id == category_id))
    obj = result.scalar_one_or_none()
    if not obj:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="探头类别不存在")
    await db.delete(obj)
    await db.commit()
    return {"message": "删除成功"}


@router.get("/{category_id}/apps")
async def get_category_apps(category_id: int, db: AsyncSession = Depends(get_db)):
    """获取探头类别的应用列表（按常规/POC 分组）"""
    result = await db.execute(
        select(CategoryApplication, Application)
        .join(Application, CategoryApplication.application_id == Application.id)
        .where(CategoryApplication.category_id == category_id)
    )
    grouped = {"regular": [], "poc": []}
    for ca, app in result.all():
        grouped.setdefault(ca.probe_type, []).append({"id": app.id, "name": app.name, "en_name": app.en_name})
    return grouped


@router.get("/{category_id}/available-apps")
async def get_available_apps(category_id: int, db: AsyncSession = Depends(get_db)):
    """获取可添加到该类别的应用列表（排除已关联的）"""
    # 已关联的应用 ID
    linked = await db.execute(
        select(CategoryApplication.application_id)
        .where(CategoryApplication.category_id == category_id)
    )
    linked_ids = {row[0] for row in linked.fetchall()}

    from app.models.probe import Application
    all_apps = await db.execute(
        select(Application).order_by(Application.sort_order)
    )
    return [{"id": a.id, "name": a.name, "en_name": a.en_name} for a in all_apps.scalars().all() if a.id not in linked_ids]


@router.post("/{category_id}/apps")
async def add_category_app(category_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    """添加应用到探头类别"""
    app_id = data.get("application_id")
    probe_type = data.get("probe_type", "regular")
    if not app_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="application_id 不能为空")
    if probe_type not in ("regular", "poc"):
        raise HTTPException(status_code=400, detail="probe_type 必须为 regular 或 poc")
    # 检查是否已存在
    r = await db.execute(select(CategoryApplication).where(
        CategoryApplication.category_id == category_id,
        CategoryApplication.application_id == app_id,
        CategoryApplication.probe_type == probe_type))
    if r.scalar_one_or_none():
        return {"message": "已存在"}
    ca = CategoryApplication(category_id=category_id, application_id=app_id, probe_type=probe_type)
    db.add(ca)
    await db.commit()
    return {"message": "添加成功"}


@router.delete("/{category_id}/apps/{application_id}")
async def remove_category_app(
    category_id: int, application_id: int,
    probe_type: str = "regular",
    db: AsyncSession = Depends(get_db)
):
    """从探头类别移除应用"""
    from fastapi import HTTPException
    r = await db.execute(select(CategoryApplication).where(
        CategoryApplication.category_id == category_id,
        CategoryApplication.application_id == application_id,
        CategoryApplication.probe_type == probe_type))
    ca = r.scalar_one_or_none()
    if not ca:
        raise HTTPException(status_code=404, detail="该关联不存在")
    await db.delete(ca)
    await db.commit()
    return {"message": "删除成功"}

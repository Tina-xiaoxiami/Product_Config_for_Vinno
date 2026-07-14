"""模板配置 API"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json
from app.database import get_db
from app.models.probe import TemplateFeature, TemplateDraft, TemplateVersion, FeatureGroup, Feature, ProbeCategory
from app.schemas.probe import TemplateFeatureCreate, TemplateFeatureUpdate, TemplateFeatureResponse

router = APIRouter()


@router.get("/by-category/{category_id}", response_model=list[TemplateFeatureResponse])
async def list_by_category(category_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TemplateFeature).where(TemplateFeature.category_id == category_id)
    )
    return result.scalars().all()


@router.post("/save-draft")
async def save_draft(data: dict, db: AsyncSession = Depends(get_db)):
    """保存模板草稿 { category_id, feature_id, new_support, excludes? }"""
    cat_id = data.get("category_id"); feat_id = data.get("feature_id")
    new_support = data.get("new_support", "unsupported")
    excludes = data.get("excludes")

    r = await db.execute(select(TemplateFeature).where(
        TemplateFeature.category_id == cat_id, TemplateFeature.feature_id == feat_id))
    existing = r.scalar_one_or_none()
    old_support = existing.default_support if existing else None
    old_excludes = existing.default_excludes if existing else None

    dr = await db.execute(select(TemplateDraft).where(
        TemplateDraft.category_id == cat_id, TemplateDraft.feature_id == feat_id))
    draft = dr.scalar_one_or_none()
    if draft:
        draft.new_support = new_support; draft.new_excludes = excludes
    else:
        draft = TemplateDraft(category_id=cat_id, feature_id=feat_id, old_support=old_support, new_support=new_support, old_excludes=old_excludes, new_excludes=excludes)
        db.add(draft)
    await db.commit()
    return {"message": "草稿已保存", "id": draft.id}


@router.get("/drafts")
async def get_drafts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TemplateDraft).order_by(TemplateDraft.created_at.desc()))
    drafts = []
    for d in result.scalars().all():
        cat_r = await db.execute(select(ProbeCategory).where(ProbeCategory.id == d.category_id))
        feat_r = await db.execute(select(Feature).where(Feature.id == d.feature_id))
        cat = cat_r.scalar_one_or_none(); feat = feat_r.scalar_one_or_none()
        drafts.append({
            "id": d.id, "category_id": d.category_id, "feature_id": d.feature_id,
            "category_name": cat.name if cat else "", "feature_name": feat.name if feat else "",
            "old_support": d.old_support, "new_support": d.new_support,
            "created_at": d.created_at,
        })
    return {"drafts": drafts, "total": len(drafts)}


@router.post("/submit")
async def submit_drafts(data: dict = None, db: AsyncSession = Depends(get_db)):
    """提交草稿：应用变更 + 创建模板版本快照"""
    dr = await db.execute(select(TemplateDraft))
    drafts = dr.scalars().all()
    if not drafts: raise HTTPException(status_code=400, detail="没有待提交的草稿")

    applied = 0
    for d in drafts:
        r = await db.execute(select(TemplateFeature).where(
            TemplateFeature.category_id == d.category_id, TemplateFeature.feature_id == d.feature_id))
        tf = r.scalar_one_or_none()
        if d.new_support == "unsupported":
            if tf: await db.delete(tf)
        else:
            if not tf:
                tf = TemplateFeature(category_id=d.category_id, feature_id=d.feature_id, default_support=d.new_support, default_excludes=d.new_excludes)
                db.add(tf)
            else:
                tf.default_support = d.new_support
                tf.default_excludes = d.new_excludes
        await db.delete(d); applied += 1

    # Create version snapshot
    all_tpl = await db.execute(select(TemplateFeature))
    snap = [{"category_id": t.category_id, "feature_id": t.feature_id, "default_support": t.default_support, "default_excludes": t.default_excludes} for t in all_tpl.scalars().all()]
    ver_num = (data or {}).get("version_number") or f"v{__import__('datetime').datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    db.add(TemplateVersion(version_number=ver_num, snapshot_data=json.dumps(snap, ensure_ascii=False)))
    await db.commit()
    return {"message": f"提交成功，版本 {ver_num}，应用 {applied} 项变更"}


@router.post("/discard")
async def discard_drafts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TemplateDraft))
    drafts = result.scalars().all()
    for d in drafts: await db.delete(d)
    await db.commit()
    return {"message": f"已废弃 {len(drafts)} 条草稿"}


@router.get("/versions")
async def get_versions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TemplateVersion).order_by(TemplateVersion.id.desc()).limit(50))
    return [{"id": v.id, "version_number": v.version_number, "description": v.description, "created_at": v.created_at} for v in result.scalars().all()]


@router.post("/rollback/{version_id}")
async def rollback_version(version_id: int, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(TemplateVersion).where(TemplateVersion.id == version_id))
    ver = r.scalar_one_or_none()
    if not ver: raise HTTPException(status_code=404, detail="版本不存在")

    snap = json.loads(ver.snapshot_data)
    # Delete current
    dr = await db.execute(select(TemplateFeature))
    for tf in dr.scalars().all(): await db.delete(tf)
    await db.flush()
    # Rebuild
    for item in snap:
        db.add(TemplateFeature(category_id=item["category_id"], feature_id=item["feature_id"], default_support=item.get("default_support","unsupported"), default_excludes=item.get("default_excludes")))
    await db.commit()
    return {"message": f"已回滚到版本 {ver.version_number}"}


@router.post("", response_model=TemplateFeatureResponse)
async def create_or_update(data: TemplateFeatureCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TemplateFeature).where(
        TemplateFeature.category_id == data.category_id, TemplateFeature.feature_id == data.feature_id))
    obj = result.scalar_one_or_none()
    if obj:
        for f, v in data.model_dump(exclude_unset=True).items(): setattr(obj, f, v)
    else:
        obj = TemplateFeature(**data.model_dump()); db.add(obj)
    await db.commit(); await db.refresh(obj)
    return obj


@router.delete("/{tf_id}")
async def delete_template(tf_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TemplateFeature).where(TemplateFeature.id == tf_id))
    obj = result.scalar_one_or_none()
    if not obj: raise HTTPException(status_code=404, detail="模板配置不存在")
    await db.delete(obj); await db.commit()
    return {"message": "删除成功"}

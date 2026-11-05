"""模板配置 API"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json
from app.database import get_db
from app.utils.time import utcnow
from app.models.probe import TemplateFeature, TemplateDraft, TemplateVersion, TemplateCatalogDraft, Feature
from app.schemas.probe import TemplateFeatureCreate, TemplateFeatureUpdate, TemplateFeatureResponse
from app.schemas.template_feature_catalog import TemplateCatalogSelection, TemplateCellDraft
from app.services.template_feature_catalog import (
    template_write, template_catalog, stage_template_feature, validate_cell_target,
    draft_report, apply_membership_drafts, version_snapshot, validate_snapshot,
)

router = APIRouter()


@router.get('/catalog')
async def get_catalog(db: AsyncSession = Depends(get_db)):
    return await template_catalog(db)


@router.post('/catalog-draft')
async def add_catalog_draft(data: TemplateCatalogSelection, db: AsyncSession = Depends(get_db)):
    async with template_write(db):
        result = await stage_template_feature(db, data.feature_id, data.group_id, data.category_ids)
    return result


@router.get("/by-category/{category_id}", response_model=list[TemplateFeatureResponse])
async def list_by_category(category_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TemplateFeature).where(TemplateFeature.category_id == category_id)
    )
    return result.scalars().all()


@router.post("/save-draft")
async def save_draft(data: TemplateCellDraft, db: AsyncSession = Depends(get_db)):
    """保存模板草稿 { category_id, feature_id, new_support, excludes? }"""
    cat_id, feat_id = data.category_id, data.feature_id
    async with template_write(db):
        await validate_cell_target(db, feat_id, cat_id)
        existing = await db.scalar(select(TemplateFeature).where(
            TemplateFeature.category_id == cat_id, TemplateFeature.feature_id == feat_id))
        old_support = existing.default_support if existing else None
        old_excludes = existing.default_excludes if existing else None
        draft = await db.scalar(select(TemplateDraft).where(
            TemplateDraft.category_id == cat_id, TemplateDraft.feature_id == feat_id))
        if draft:
            setattr(draft, 'new_support', data.new_support)
            setattr(draft, 'new_excludes', data.excludes)
        else:
            draft = TemplateDraft(category_id=cat_id, feature_id=feat_id, old_support=old_support,
                                  new_support=data.new_support, old_excludes=old_excludes, new_excludes=data.excludes)
            db.add(draft)
    return {"message": "草稿已保存", "id": draft.id}


@router.get("/drafts")
async def get_drafts(db: AsyncSession = Depends(get_db)):
    return await draft_report(db)


@router.post("/submit")
async def submit_drafts(data: dict | None = None, db: AsyncSession = Depends(get_db)):
    """提交草稿：应用变更 + 创建模板版本快照"""
    async with template_write(db):
        drafts = list((await db.scalars(select(TemplateDraft))).all())
        additions = await apply_membership_drafts(db, drafts)
        if not drafts:
            raise HTTPException(status_code=400, detail="没有待提交的草稿")
        applied = 0
        for d in drafts:
            tf = await db.scalar(select(TemplateFeature).where(
                TemplateFeature.category_id == d.category_id, TemplateFeature.feature_id == d.feature_id))
            if d.new_support == "unsupported":
                if tf:
                    await db.delete(tf)
            else:
                if not tf:
                    tf = TemplateFeature(category_id=d.category_id, feature_id=d.feature_id,
                                         default_support=d.new_support, default_excludes=d.new_excludes)
                    db.add(tf)
                else:
                    tf.default_support = d.new_support
                    tf.default_excludes = d.new_excludes
            await db.delete(d)
            applied += 1
        for addition in additions:
            await db.delete(addition)
        snap = await version_snapshot(db)
        ver_num = (data or {}).get("version_number") or f"v{utcnow().strftime('%Y%m%d%H%M%S')}"
        db.add(TemplateVersion(version_number=ver_num, snapshot_data=json.dumps(snap, ensure_ascii=False)))
    return {"message": f"提交成功，版本 {ver_num}，应用 {applied} 项变更", 'catalog_additions': len(additions)}


@router.post("/discard")
async def discard_drafts(db: AsyncSession = Depends(get_db)):
    async with template_write(db):
        drafts = (await db.scalars(select(TemplateDraft))).all()
        additions = (await db.scalars(select(TemplateCatalogDraft))).all()
        for draft in drafts:
            await db.delete(draft)
        for addition in additions:
            await db.delete(addition)
    return {"message": f"已废弃 {len(drafts)} 条草稿及 {len(additions)} 项待选功能"}


@router.get("/versions")
async def get_versions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TemplateVersion).order_by(TemplateVersion.id.desc()).limit(50))
    return [{"id": v.id, "version_number": v.version_number, "description": v.description, "created_at": v.created_at} for v in result.scalars().all()]


@router.post("/rollback/{version_id}")
async def rollback_version(version_id: int, db: AsyncSession = Depends(get_db)):
    async with template_write(db):
        ver = await db.get(TemplateVersion, version_id)
        if ver is None:
            raise HTTPException(status_code=404, detail="版本不存在")
        if (await db.scalar(select(TemplateDraft.id).limit(1)) is not None
                or await db.scalar(select(TemplateCatalogDraft.feature_id).limit(1)) is not None):
            raise HTTPException(409, '存在待提交模板草稿，请先提交或废弃后再回滚')
        templates, members = await validate_snapshot(db, str(ver.snapshot_data))
        for tf in (await db.scalars(select(TemplateFeature))).all():
            await db.delete(tf)
        await db.flush()
        for item in templates:
            db.add(TemplateFeature(category_id=item['category_id'], feature_id=item['feature_id'],
                                   default_support=item.get('default_support', 'unsupported'), default_excludes=item.get('default_excludes')))
        if members is not None:
            selected = {item['feature_id']: item['group_id'] for item in members}
            for feature in (await db.scalars(select(Feature))).all():
                setattr(feature, 'probe_matrix_enabled', feature.id in selected)
                if feature.id in selected:
                    feature.group_id = selected[feature.id]
    message = f"已回滚到版本 {ver.version_number}"
    if members is None:
        message += '；旧快照不含成员及分类，保留当前模板成员分类，仅恢复支持配置'
    return {'message': message, 'membership_restored': members is not None}


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

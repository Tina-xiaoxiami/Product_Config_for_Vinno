"""Use existing identities, cell drafts and versions for template membership.

The API owns each write transaction. Selection never creates a feature identity
or changes committed membership until the ordinary template submission succeeds.
"""
from contextlib import asynccontextmanager
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.probe import Feature, FeatureGroup, ProbeCategory, TemplateCatalogDraft, TemplateDraft, TemplateFeature
from app.services.knowledge_query import list_feature_knowledge
from app.services.write_serialization import serialize_catalog_write

SUPPORT_STATES = {'supported', 'conditional', 'unsupported'}


@asynccontextmanager
async def template_write(db: AsyncSession):
    try:
        await serialize_catalog_write(db, 'features')
        yield
        await db.commit()
    except (IntegrityError, OperationalError) as error:
        await db.rollback()
        raise HTTPException(409, '模板草稿或引用已变化，提交未生效，请刷新后核对') from error
    except Exception:
        await db.rollback()
        raise


def feature_state(feature: Feature) -> dict:
    return {'probe_matrix_enabled': bool(feature.probe_matrix_enabled), 'group_id': feature.group_id}


async def template_catalog(db: AsyncSession) -> dict:
    features = (await db.scalars(select(Feature).order_by(Feature.sort_order, Feature.id))).all()
    names, _ = await list_feature_knowledge(db, limit=max(1, len(features)))
    by_id = {row['id']: row for row in names}
    additions = {row.feature_id: row for row in (await db.scalars(select(TemplateCatalogDraft))).all()}
    groups = (await db.scalars(select(FeatureGroup).order_by(FeatureGroup.sort_order, FeatureGroup.id))).all()
    items = []
    matrix = []
    for feature in features:
        identity = by_id.get(feature.id, {})
        pending = additions.get(feature.id)
        name = identity.get('display_cn_name') or feature.primary_cn_name or feature.name
        item = {'id': feature.id, 'name': name, 'primary_cn_name': name,
                'primary_en_name': feature.primary_en_name or '', 'ipn': feature.ipn or '',
                'group_id': feature.group_id, 'probe_matrix_enabled': bool(feature.probe_matrix_enabled),
                'pending': pending is not None}
        if pending is not None:
            item['pending_group_id'] = pending.group_id
        items.append(item)
        if feature.probe_matrix_enabled or pending is not None:
            matrix.append({**item, 'group_id': pending.group_id if pending is not None else feature.group_id,
                           'original_group_id': feature.group_id})
    return {'items': items, 'matrix_items': matrix, 'total': len(items),
            'groups': [{'id': group.id, 'name': group.name, 'sort_order': group.sort_order} for group in groups]}


async def stage_template_feature(db: AsyncSession, feature_id: int, group_id: int, category_ids: list[int]) -> dict:
    feature = await db.get(Feature, feature_id)
    if feature is None or await db.get(FeatureGroup, group_id) is None:
        raise HTTPException(422, '功能或共用功能分类不存在，请刷新后核对')
    categories = set((await db.scalars(select(ProbeCategory.id).where(ProbeCategory.id.in_(category_ids)))).all())
    if categories != set(category_ids):
        raise HTTPException(422, '所选探头类别不存在，请刷新后核对')
    if feature.probe_matrix_enabled or await db.get(TemplateCatalogDraft, feature_id) is not None:
        raise HTTPException(409, '该功能已入选或已在待提交列表，请在模板矩阵中编辑')
    if (await db.scalar(select(TemplateFeature.id).where(TemplateFeature.feature_id == feature_id).limit(1)) is not None
            or await db.scalar(select(TemplateDraft.id).where(TemplateDraft.feature_id == feature_id).limit(1)) is not None):
        raise HTTPException(409, '该功能存在历史模板或草稿记录，不能覆盖，请先核对')
    db.add(TemplateCatalogDraft(feature_id=feature_id, group_id=group_id,
                                expected_state=json.dumps(feature_state(feature), sort_keys=True)))
    for category_id in sorted(categories):
        db.add(TemplateDraft(category_id=category_id, feature_id=feature_id,
                              old_support=None, old_excludes=None, new_support='supported', new_excludes=None))
    return {'message': '功能已加入模板草稿，提交后生效', 'feature_id': feature_id, 'draft_count': len(categories)}


async def validate_cell_target(db: AsyncSession, feature_id: int, category_id: int) -> None:
    feature = await db.get(Feature, feature_id)
    if feature is None or await db.get(ProbeCategory, category_id) is None:
        raise HTTPException(422, '功能或探头类别不存在，请刷新后核对')
    if not feature.probe_matrix_enabled and await db.get(TemplateCatalogDraft, feature_id) is None:
        raise HTTPException(409, '功能尚未选入模板，请先从功能库添加')


async def draft_report(db: AsyncSession) -> dict:
    rows = (await db.scalars(select(TemplateDraft).order_by(TemplateDraft.created_at.desc(), TemplateDraft.id))).all()
    features = {row.id: row for row in (await db.scalars(select(Feature))).all()}
    categories = {row.id: row for row in (await db.scalars(select(ProbeCategory))).all()}
    groups = {row.id: row for row in (await db.scalars(select(FeatureGroup))).all()}
    additions = (await db.scalars(select(TemplateCatalogDraft).order_by(TemplateCatalogDraft.created_at, TemplateCatalogDraft.feature_id))).all()
    drafts = [{'id': row.id, 'category_id': row.category_id, 'feature_id': row.feature_id,
               'category_name': categories[row.category_id].name if row.category_id in categories else '',
               'feature_name': features[row.feature_id].primary_cn_name or features[row.feature_id].name if row.feature_id in features else '',
               'old_support': row.old_support, 'new_support': row.new_support,
               'old_excludes': row.old_excludes, 'new_excludes': row.new_excludes, 'created_at': row.created_at} for row in rows]
    catalog = [{'feature_id': row.feature_id, 'group_id': row.group_id,
                'feature_name': features[row.feature_id].primary_cn_name or features[row.feature_id].name if row.feature_id in features else '',
                'group_name': groups[row.group_id].name if row.group_id in groups else '',
                'category_ids': sorted({draft.category_id for draft in rows if draft.feature_id == row.feature_id and draft.new_support != 'unsupported'}),
                'created_at': row.created_at} for row in additions]
    return {'drafts': drafts, 'total': len(rows), 'catalog_additions': catalog, 'catalog_additions_count': len(catalog)}


async def apply_membership_drafts(db: AsyncSession, drafts: list[TemplateDraft]) -> list[TemplateCatalogDraft]:
    additions = list((await db.scalars(select(TemplateCatalogDraft))).all())
    pending_ids = {row.feature_id for row in additions}
    for addition in additions:
        feature = await db.get(Feature, addition.feature_id)
        try:
            expected = json.loads(str(addition.expected_state))
        except (TypeError, ValueError):
            expected = None
        if (feature is None or feature_state(feature) != expected or feature.probe_matrix_enabled
                or await db.get(FeatureGroup, addition.group_id) is None):
            raise HTTPException(409, '待选功能的成员状态或共用分类已变化，请废弃草稿后重新核对')
        if (not any(row.feature_id == addition.feature_id for row in drafts)
                or await db.scalar(select(TemplateFeature.id).where(TemplateFeature.feature_id == addition.feature_id).limit(1)) is not None):
            raise HTTPException(409, '待选功能的草稿或历史模板已变化，不能覆盖')
    seen = set()
    for draft in drafts:
        key = (draft.category_id, draft.feature_id)
        if key in seen or draft.new_support not in SUPPORT_STATES:
            raise HTTPException(409, '模板草稿存在重复或无效状态，请核对后重新保存')
        seen.add(key)
        feature = await db.get(Feature, draft.feature_id)
        if (feature is None or not feature.probe_matrix_enabled and feature.id not in pending_ids
                or await db.get(ProbeCategory, draft.category_id) is None):
            raise HTTPException(409, '模板草稿引用的功能或探头类别已变化')
        live = await db.scalar(select(TemplateFeature).where(TemplateFeature.category_id == draft.category_id,
                                                           TemplateFeature.feature_id == draft.feature_id))
        current = (live.default_support, live.default_excludes) if live else (None, None)
        if current != (draft.old_support, draft.old_excludes):
            raise HTTPException(409, '模板支持状态已被其他操作修改，请重新核对草稿')
    for addition in additions:
        feature = await db.get(Feature, addition.feature_id)
        assert feature is not None  # References were checked under the same writer lock.
        setattr(feature, 'probe_matrix_enabled', True)
        feature.group_id = addition.group_id
    return additions


async def version_snapshot(db: AsyncSession) -> dict:
    await db.flush()
    templates = (await db.scalars(select(TemplateFeature).order_by(TemplateFeature.category_id, TemplateFeature.feature_id))).all()
    features = (await db.scalars(select(Feature).where(Feature.probe_matrix_enabled.is_(True)).order_by(Feature.id))).all()
    snapshot = {'schema_version': 2,
                'templates': [{'category_id': row.category_id, 'feature_id': row.feature_id,
                               'default_support': row.default_support, 'default_excludes': row.default_excludes} for row in templates],
                'features': [{'feature_id': row.id, 'group_id': row.group_id} for row in features]}
    try:
        await validate_snapshot(db, json.dumps(snapshot))
    except HTTPException as error:
        raise HTTPException(409, '当前模板存在未入选、重复或失效的支持记录，不能创建新版本，请先核对；历史未被清除') from error
    return snapshot


def _positive(value: Any) -> bool:
    return type(value) is int and value > 0


def read_template_snapshot(raw: str) -> tuple[list[dict], list[dict] | None]:
    """One structural contract for legacy cells and membership-aware versions."""
    try:
        snapshot = json.loads(raw)
        members = None
        if isinstance(snapshot, dict):
            if type(snapshot.get('schema_version')) is not int or snapshot['schema_version'] != 2:
                raise ValueError
            templates, members = snapshot['templates'], snapshot['features']
            if not isinstance(members, list):
                raise ValueError
        else:
            templates = snapshot
        if not isinstance(templates, list):
            raise ValueError
        seen = set()
        for row in templates:
            if (not isinstance(row, dict) or not _positive(row.get('feature_id')) or not _positive(row.get('category_id'))
                    or row.get('default_support', 'unsupported') not in SUPPORT_STATES
                    or row.get('default_excludes') is not None and not isinstance(row['default_excludes'], str)):
                raise ValueError
            key = (row['category_id'], row['feature_id'])
            if key in seen:
                raise ValueError
            seen.add(key)
        seen_members = set()
        for row in members or []:
            if (not isinstance(row, dict) or not _positive(row.get('feature_id')) or not _positive(row.get('group_id'))
                    or row['feature_id'] in seen_members):
                raise ValueError
            seen_members.add(row['feature_id'])
        if members is not None and any(row['feature_id'] not in seen_members for row in templates):
            raise ValueError
        return templates, members
    except (ValueError, TypeError, KeyError) as error:
        raise ValueError('模板版本快照结构无效') from error


async def validate_snapshot(db: AsyncSession, raw: str) -> tuple[list[dict], list[dict] | None]:
    try:
        templates, members = read_template_snapshot(raw)
        feature_ids = set((await db.scalars(select(Feature.id))).all())
        group_ids = set((await db.scalars(select(FeatureGroup.id))).all())
        category_ids = set((await db.scalars(select(ProbeCategory.id))).all())
        if (any(row['feature_id'] not in feature_ids or row['category_id'] not in category_ids for row in templates)
                or any(row['feature_id'] not in feature_ids or row['group_id'] not in group_ids for row in members or [])):
            raise ValueError
        return templates, members
    except ValueError as error:
        raise HTTPException(422, '模板版本快照无效或引用已不存在，未执行回滚') from error

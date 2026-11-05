"""Complete the existing identity registry from configuration, without committing."""
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import ConfigItem
from app.models.probe import Feature, FeatureGroup
from app.models.knowledge import FeatureConfigItemLink, FeatureName
from app.services.feature_identity import clean_feature_name


def _ipn(value):
    return (value or '').strip().upper()


def probe_matrix_scope():
    """One scope for probe readers, template initialization and bulk operations."""
    return Feature.probe_matrix_enabled.is_(True)


async def _catalog_state(db):
    items = list((await db.scalars(select(ConfigItem).where(
        func.lower(func.trim(ConfigItem.category)) == 'optional features'
    ).order_by(ConfigItem.row_index, ConfigItem.id))).all())
    features = list((await db.scalars(select(Feature))).all())
    linked = list((await db.execute(select(FeatureConfigItemLink.config_item_id, ConfigItem.ipn)
        .join(ConfigItem, ConfigItem.id == FeatureConfigItemLink.config_item_id)
        .where(FeatureConfigItemLink.review_status == 'approved'))).all())
    occupied_ids = {row.config_item_id for row in linked} | {f.config_item_id for f in features if f.config_item_id}
    occupied_ipns = {_ipn(row.ipn) for row in linked if _ipn(row.ipn)} | {_ipn(f.ipn) for f in features if _ipn(f.ipn)}
    return items, features, occupied_ids, occupied_ipns


async def sync_optional_feature_catalog(db: AsyncSession) -> dict:
    """Add missing identities only; caller owns commit, SAVEPOINT and rollback.

    Approved related/version IPNs and existing primary ownership all count as
    occupied. Existing identities, names, relationships and probe rows are untouched.
    """
    await db.flush()
    items, _, occupied_ids, occupied_ipns = await _catalog_state(db)
    frequencies = Counter(_ipn(item.ipn) for item in items if _ipn(item.ipn))
    candidates = [item for item in items if item.id not in occupied_ids and _ipn(item.ipn) not in occupied_ipns
                  and _ipn(item.ipn) and frequencies[_ipn(item.ipn)] == 1]
    if not candidates:
        return {'created': 0}
    group = await db.scalar(select(FeatureGroup).where(FeatureGroup.name == '配置功能（未分类）'))
    if group is None:
        group = FeatureGroup(name='配置功能（未分类）', sort_order=(await db.scalar(select(func.max(FeatureGroup.sort_order))) or 0) + 1)
        db.add(group)
        await db.flush()
    for item in candidates:
        cn, en = clean_feature_name(item.zh_desc or ''), clean_feature_name(item.en_desc or '')
        feature = Feature(group_id=group.id, name=cn or en or f'IPN {_ipn(item.ipn)}',
                          ipn=_ipn(item.ipn), config_item_id=item.id, primary_cn_name=cn, primary_en_name=en,
                          identity_status='auto_matched', sort_order=item.row_index, probe_matrix_enabled=False)
        db.add(feature)
        await db.flush()
        db.add(FeatureConfigItemLink(feature_id=feature.id, config_item_id=item.id, relation_type='primary',
                                    source='config_catalog', review_status='approved'))
        for language, name, source in [('cn', cn, 'config_items.zh_desc'), ('en', en, 'config_items.en_desc')]:
            if name:
                db.add(FeatureName(feature_id=feature.id, language=language, name=name, normalized_name=name.casefold(),
                                   name_type='primary', source=source, review_status='approved'))
    await db.flush()
    return {'created': len(candidates)}


async def feature_catalog_coverage(db: AsyncSession) -> dict:
    """Read-only source coverage, distinct from identity confirmation or evidence quality."""
    items, features, occupied_ids, occupied_ipns = await _catalog_state(db)
    covered = [item for item in items if item.id in occupied_ids or _ipn(item.ipn) in occupied_ipns]
    covered_ids = {item.id for item in covered}
    covered_ipns = {_ipn(item.ipn) for item in covered if _ipn(item.ipn)}
    frequencies = Counter(_ipn(item.ipn) for item in items if _ipn(item.ipn))
    unlinked = [{'config_item_id': item.id, 'ipn': item.ipn or '', 'v_code': item.v_code or '',
                 'cn_name': clean_feature_name(item.zh_desc or ''), 'en_name': clean_feature_name(item.en_desc or ''),
                 'reason': '缺少IPN，待核对' if not _ipn(item.ipn) else 'IPN在配置源中重复，待核对'
                     if frequencies[_ipn(item.ipn)] > 1 else '尚未建立功能身份'}
                for item in items if item.id not in covered_ids]
    return {'catalog_identities': len(features),
            'configured_items': len(items), 'configured_ipns': len(frequencies), 'covered_items': len(covered),
            'covered_ipns': len(covered_ipns),
            'unlinked_count': len(unlinked), 'unlinked_items': unlinked,
            'missing_cn_names': sum(not (f.primary_cn_name or '').strip() for f in features),
            'missing_en_names': sum(not (f.primary_en_name or '').strip() for f in features)}

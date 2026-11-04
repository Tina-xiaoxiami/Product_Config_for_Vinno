"""Explicit standard-name synchronization, including names with no warning marker."""
import re
import unicodedata
from uuid import uuid4
from sqlalchemy import select
from app.models.feature_standard import FeatureNameReview
from app.models.config import ConfigItem
from app.services.feature_identity import clean_feature_name
from app.services.feature_master_data import set_feature_primary_names
from app.services.feature_name_standards import _load_feature_index, list_feature_name_standards
from app.services.feature_name_reviews import encode
from app.services.write_serialization import serialize_catalog_write


def identity_keys(value):
    """Explicit labels only: preserve +, -, dimensions and compound identifiers."""
    value = clean_feature_name(value)
    values = {value}
    if '(' in value:
        values.add(value.split('(', 1)[0].strip())
    values.update(re.findall(r'\(([A-Za-z][A-Za-z0-9+\-]{0,30})\)', value))
    prefix = re.match(r'^([A-Za-z][A-Za-z0-9+\-]*)(?=[\u3400-\u9fff])', value)
    if prefix:
        values.add(prefix.group(1))
    for text in list(values):
        trimmed = re.sub(r'^超声', '', text)
        trimmed = re.sub(r'(功能|技术|成像|模式|软件)$', '', trimmed)
        if len(trimmed) >= 4:
            values.add(trimmed)
    return {re.sub(r'\s+', '', unicodedata.normalize('NFKC', text)).casefold().rstrip('：:') for text in values if text}


def plan_standard_sync(standards, features):
    standard_keys = [set().union(*(identity_keys(row.get(key, '')) for key in ('cn_name', 'en_name', 'ui_label'))) for row in standards]
    checked, skipped = [], []
    for feature in features.values():
        main = set().union(*(identity_keys(name) for name in [feature['legacy_name'], feature['cn_name'], feature['en_name'], *feature['names_cn'], *feature['names_en']] if name))
        linked = set().union(*(identity_keys(name) for name in feature.get('identity_names', [])))
        scores = [3 if main & keys else 2 if linked & keys else 0 for keys in standard_keys]
        best = max(scores, default=0)
        candidates = [row for row, score in zip(standards, scores) if score == best and best > 0]
        # Multiple IPN versions may share one definition. A feature must still
        # resolve to one exact canonical pair; never merge or rewrite identities.
        targets = {(row['cn_name'], row.get('en_name') or row.get('short_en', '')) for row in candidates}
        reason = None
        if not candidates:
            reason = '未找到明确对应的标准名称'
        elif len(targets) > 1:
            reason = '同时对应多个标准定义'
        elif len(feature['primary_links']) > 1:
            reason = '存在多个主IPN链接'
        if reason:
            skipped.append({'feature_id':feature['id'], 'name':feature['cn_name'] or feature['legacy_name'], 'reason':reason})
            continue
        target_cn, target_en = next(iter(targets))
        target_cn = clean_feature_name(target_cn or feature['cn_name'])
        target_en = clean_feature_name(target_en or feature['en_name'])
        if not target_cn or not target_en:
            skipped.append({'feature_id':feature['id'], 'name':feature['legacy_name'], 'reason':'标准和当前数据均缺少中英文名称'})
            continue
        before = {'name':feature['legacy_name'], 'cn':feature['cn_name'], 'en':feature['en_name']}
        checked.append({'feature_id':feature['id'], 'before':before, 'cn':target_cn, 'en':target_en,
                        'changed':before != {'name':target_cn,'cn':target_cn,'en':target_en}})
    return {'checked':checked, 'skipped':skipped}


async def build_standard_sync_plan(db):
    standards = await list_feature_name_standards(db)
    features = (await _load_feature_index(db))['features']
    ids = {link['item_id'] for feature in features.values() for link in feature['primary_links']}
    ids.update(feature['config_item_id'] for feature in features.values() if feature.get('config_item_id'))
    items = dict((await db.execute(select(ConfigItem.id, ConfigItem.rd_name).where(ConfigItem.id.in_(ids)))).all()) if ids else {}
    for feature in features.values():
        source_ids = {link['item_id'] for link in feature['primary_links']}
        if feature.get('config_item_id'):
            source_ids.add(feature['config_item_id'])
        feature['identity_names'] = [items[key] for key in source_ids if items.get(key)]
    return plan_standard_sync(standards, features)


async def sync_all_standard_names(db, confirmed_by='local_user'):
    await serialize_catalog_write(db, 'features')
    plan = await build_standard_sync_plan(db)
    batch = str(uuid4())
    try:
        for row in plan['checked']:
            await set_feature_primary_names(db,row['feature_id'],row['cn'],row['en'])
            snapshot = {'action':'sync_standard', 'batch_id':batch, **row}
            import hashlib
            db.add(FeatureNameReview(feature_id=row['feature_id'],baseline='standard',
                fingerprint=hashlib.sha256(encode(snapshot).encode()).hexdigest(),snapshot_data=encode(snapshot),
                note='统一按标准表更新与核对（含无异常标记功能）',confirmed_by=confirmed_by))
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return {'batch_id':batch, **plan}

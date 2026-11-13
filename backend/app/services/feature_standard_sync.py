"""Explicit standard-name synchronization, including names with no warning marker."""
import re
import hashlib
import unicodedata
from uuid import uuid4
from sqlalchemy import select
from app.models.feature_standard import FeatureNameReview
from app.models.config import ConfigItem
from app.services.feature_identity import clean_feature_name
from app.services.feature_master_data import set_feature_primary_names
from app.services.feature_name_standards import _load_feature_index, list_feature_name_standards, StandardRow
from app.services.feature_name_reviews import encode
from app.services.write_serialization import serialize_catalog_write


def identity_keys(value):
    """Explicit labels only: preserve +, -, dimensions and compound identifiers."""
    value = clean_feature_name(value)
    values = {value}
    if '(' in value and not re.search(r'\([^)]*(?:[234]d|[二三四]维|v\d+(?:\.\d+)*|版本)[^)]*\)',value,re.I):
        values.add(value.split('(', 1)[0].strip())
    values.update(re.findall(r'\(([A-Za-z][A-Za-z0-9+\-]{0,30})\)', value))
    prefix = re.match(r'^([A-Za-z][A-Za-z0-9+\-]*)(?=[\u3400-\u9fff])', value)
    # A single letter in a mixed label is not an explicit abbreviation (B线 is not B).
    if prefix and len(prefix.group(1)) > 1:
        values.add(prefix.group(1))
    for text in list(values):
        trimmed = re.sub(r'^超声', '', text)
        trimmed = re.sub(r'(功能|技术|成像|模式|软件)$', '', trimmed)
        if len(trimmed) >= 4:
            values.add(trimmed)
    return {re.sub(r'\s+', '', unicodedata.normalize('NFKC', text)).casefold().rstrip('：:') for text in values if text and not re.fullmatch(r'(?:v\d+(?:\.\d+)*|[234]d|ngs|pro|plus|basic|advanced)',text.strip(),re.I)}


def compatible_identity(feature, standard):
    source_names = [feature['legacy_name'], feature['cn_name'], feature['en_name']]
    target_names = [standard.get('cn_name',''),standard.get('en_name',''),standard.get('ui_label','')]
    def versions(names):
        return {part.casefold().replace('二维','2d').replace('三维','3d').replace('四维','4d') for value in names if value
                for part in re.findall(r'([234]D|[二三四]维|V\d+(?:\.\d+)*)(?![A-Za-z0-9])',clean_feature_name(value),re.I)}
    source_versions, target_versions = versions(source_names), versions(target_names)
    if source_versions and target_versions and source_versions.isdisjoint(target_versions):
        return False
    def variants(names):
        result = {}
        for value in names:
            for root, plus in re.findall(r'([A-Za-z][A-Za-z0-9]*)(\+?)',value or ''):
                result.setdefault(root.casefold(),set()).add(bool(plus))
        return result
    source_tokens, target_tokens = variants(source_names), variants(target_names)
    return not any(source_tokens[key] != target_tokens[key] and (True in source_tokens[key] or True in target_tokens[key])
                   for key in source_tokens.keys() & target_tokens.keys())


def plan_standard_sync(standards, features):
    standard_keys = [set().union(*(identity_keys(row.get(key, '')) for key in ('cn_name', 'en_name', 'ui_label'))) for row in standards]
    checked, skipped = [], []
    for feature in features.values():
        main = set().union(*(identity_keys(name) for name in [feature['legacy_name'], feature['cn_name'], feature['en_name'], *feature['names_cn'], *feature['names_en']] if name))
        linked = set().union(*(identity_keys(name) for name in feature.get('identity_names', [])))
        scores = [(3 if main & keys else 2 if linked & keys else 0) if compatible_identity(feature,row) else 0
                  for row,keys in zip(standards,standard_keys)]
        best = max(scores, default=0)
        candidates = [row for row, score in zip(standards, scores) if score == best and best > 0]
        # Multiple IPN versions may share one definition. A feature must still
        # resolve to one exact canonical pair; never merge or rewrite identities.
        targets = {(row['cn_name'], row.get('en_name') or StandardRow(ui_label=row.get('ui_label', '')).short_en()) for row in candidates}
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
            if row['changed']:
                await set_feature_primary_names(db,row['feature_id'],row['cn'],row['en'])
            snapshot = {'action':'sync_standard', 'batch_id':batch, **row}
            db.add(FeatureNameReview(feature_id=row['feature_id'],baseline='standard',
                fingerprint=hashlib.sha256(encode(snapshot).encode()).hexdigest(),snapshot_data=encode(snapshot),
                note='统一按标准表更新与核对（含无异常标记功能）',confirmed_by=confirmed_by))
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return {'batch_id':batch, **plan}

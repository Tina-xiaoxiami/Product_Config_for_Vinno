"""Apply the naming standard while preserving feature identities and historical names."""
from copy import deepcopy
import hashlib
import json
from fastapi import HTTPException
from sqlalchemy import inspect, select, update
from app.models.probe import Feature
from app.models.feature_standard import FeatureNameReview, FeatureDisplayName
from app.utils.time import utcnow


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


async def storage_ready(db):
    connection = await db.connection()
    return await connection.run_sync(lambda c: inspect(c).has_table('feature_name_reviews'))


async def decorate_checks(db, features, flags):
    from app.services.feature_name_standards import StandardRow, _match_score
    connection = await db.connection()
    ready = await connection.run_sync(lambda c: inspect(c).has_table('feature_display_names'))
    display_names = {row.feature_id: row.name for row in (await db.scalars(select(FeatureDisplayName))).all()} if ready else {}
    for fid, flag in flags.items():
        flag['feature_display_name'] = display_names.get(int(fid)) or features[int(fid)]['legacy_name'] or features[int(fid)]['cn_name']
        feature = features[int(fid)]
        identity = {key: feature.get(key) for key in ('id', 'legacy_name', 'cn_name', 'en_name', 'config_ipn', 'config_item_id', 'primary_ipn')}
        identity['primary_links'] = [{'item_id': link['item_id'], 'ipn': link['ipn']} for link in feature['primary_links']]
        identity.update(names_cn=sorted(feature['names_cn']), names_en=sorted(feature['names_en']))
        for check in flag['checks']:
            snapshot = {'feature': identity, 'check': deepcopy(check)}
            digest = hashlib.sha256(encode(snapshot).encode()).hexdigest()
            safe = False
            if check['baseline'] == 'standard' and check['severity'] in {'differs', 'style'}:
                standard = StandardRow(cn_name=check['standard_cn_name'], en_name=check['standard_en_name'])
                scores = {key: _match_score(standard, item)[0] for key, item in features.items()}
                best = max(scores.values(), default=0)
                safe = best >= 1.5 and [key for key, score in scores.items() if score == best] == [int(fid)]
            check.update(fingerprint=digest, identity_ambiguous=len(feature['primary_links']) > 1,
                         confirmable=False, can_apply=bool(safe and len(feature['primary_links']) <= 1 and check.get('standard_cn_name') and check.get('standard_en_name')),
                         reviewed=False, review_id=None, review_snapshot=snapshot)
    return flags


async def review_detail(db, feature_id):
    from app.services.feature_name_standards import audit_feature_names
    feature = await db.get(Feature, feature_id)
    if feature is None:
        raise HTTPException(404, '功能不存在')
    audit = await audit_feature_names(db)
    flag = audit['review_flags']['by_feature'].get(str(feature_id), {})
    rows = (await db.scalars(select(FeatureNameReview).where(FeatureNameReview.feature_id == feature_id).order_by(FeatureNameReview.id.desc()).limit(50))).all() if await storage_ready(db) else []
    history = []
    for row in rows:
        snapshot = json.loads(row.snapshot_data)
        history.append({'id': row.id, 'baseline': row.baseline, 'fingerprint': row.fingerprint,
                        'snapshot': snapshot, 'action': snapshot.get('action', 'legacy_confirmation'),
                        'note': row.note, 'confirmed_by': row.confirmed_by, 'confirmed_at': row.confirmed_at.isoformat(),
                        'revoked_at': row.revoked_at.isoformat() if row.revoked_at else None, 'effective': False})
    return {'feature_id': feature_id, 'name': feature.primary_cn_name or feature.name,
            'primary_cn_name': feature.primary_cn_name, 'primary_en_name': feature.primary_en_name,
            'display_name': await get_display_name(db, feature_id), 'default_display_name': feature.name,
            'checks': flag.get('checks', []), 'history': history}


async def confirm_differences(db, feature_id, checks, note, confirmed_by):
    raise HTTPException(422, '名称须与标准表一致，不再支持确认沿用；请按标准表更新名称。配置表仅检查链接关系。')


async def apply_standard_names(db, feature_id, fingerprint, note, confirmed_by):
    if not await storage_ready(db):
        raise HTTPException(503, '名称核对记录尚未初始化，请重启本地服务')
    result = await db.execute(update(Feature).where(Feature.id == feature_id).values(id=Feature.id))
    if result.rowcount != 1:
        raise HTTPException(404, '功能不存在')
    detail = await review_detail(db, feature_id)
    check = next((item for item in detail['checks'] if item['baseline'] == 'standard'), None)
    if not check or check['fingerprint'] != fingerprint:
        raise HTTPException(409, '名称、标准表或链接关系已经变化，请刷新后重试')
    if not check['can_apply']:
        raise HTTPException(422, '标准对应关系不明确、未收录或名称已一致，请先核对主数据')
    from app.services.feature_master_data import set_feature_primary_names, FeatureMasterDataError
    try:
        await set_feature_primary_names(db, feature_id, check['standard_cn_name'], check['standard_en_name'])
    except FeatureMasterDataError as error:
        await db.rollback()
        raise HTTPException(422, str(error)) from error
    snapshot = {**check['review_snapshot'], 'action': 'apply_standard',
                'applied': {'cn': check['standard_cn_name'], 'en': check['standard_en_name']}}
    db.add(FeatureNameReview(feature_id=feature_id, baseline='standard', fingerprint=fingerprint,
                            snapshot_data=encode(snapshot), note=note, confirmed_by=confirmed_by))
    await db.commit()
    feature = await db.get(Feature, feature_id)
    await db.refresh(feature)
    return await review_detail(db, feature_id)


async def revoke_confirmation(db, feature_id, review_id):
    if not await storage_ready(db):
        raise HTTPException(503, '名称核对记录尚未初始化，请重启本地服务')
    row = await db.get(FeatureNameReview, review_id)
    if row is None or row.feature_id != feature_id or row.revoked_at is not None:
        raise HTTPException(409, '核对记录不存在或已撤销，请刷新')
    if json.loads(row.snapshot_data).get('action') in {'apply_standard', 'sync_standard', 'display_name'}:
        raise HTTPException(422, '这是名称更新记录，不是可撤销的差异确认；名称请在功能管理中维护')
    row.revoked_at = utcnow()
    await db.commit()
    return await review_detail(db, feature_id)


async def get_display_name(db, feature_id):
    connection = await db.connection()
    if not await connection.run_sync(lambda c: inspect(c).has_table('feature_display_names')):
        return ''
    row = await db.get(FeatureDisplayName, feature_id)
    return row.name if row else ''


async def set_display_name(db, feature_id, name):
    from app.services.write_serialization import serialize_catalog_write
    await serialize_catalog_write(db, 'features')
    if await db.get(Feature, feature_id) is None:
        raise HTTPException(404, '功能不存在')
    connection = await db.connection()
    if not await connection.run_sync(lambda c: inspect(c).has_table('feature_display_names')):
        raise HTTPException(503, '显示名称存储尚未初始化，请重启服务')
    row = await db.get(FeatureDisplayName, feature_id)
    if row is None:
        db.add(FeatureDisplayName(feature_id=feature_id, name=name.strip()))
    else:
        row.name = name.strip()
    await db.commit()
    return await review_detail(db, feature_id)

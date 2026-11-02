"""Confirm exact naming differences without changing source facts or feature identity."""
from copy import deepcopy
import hashlib
import json
from fastapi import HTTPException
from sqlalchemy import inspect, select, update
from app.models.probe import Feature
from app.models.feature_standard import FeatureNameReview
from app.utils.time import utcnow

CONFIRMABLE = {'differs', 'style', 'uncovered'}

def encode(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))

async def storage_ready(db):
    connection=await db.connection()
    return await connection.run_sync(lambda c: inspect(c).has_table('feature_name_reviews'))

async def decorate_checks(db, features, flags):
    rows=(await db.scalars(select(FeatureNameReview).order_by(FeatureNameReview.id.desc()))).all() if await storage_ready(db) else []
    latest={}
    for row in rows:
        latest.setdefault((row.feature_id,row.baseline),row)
    for fid,flag in flags.items():
        feature=features[int(fid)]
        identity={key:feature.get(key) for key in ('id','legacy_name','cn_name','en_name','config_ipn','config_item_id','primary_ipn','primary_links')}
        identity.update(names_cn=sorted(feature['names_cn']),names_en=sorted(feature['names_en']))
        for check in flag['checks']:
            snapshot={'feature':identity,'check':deepcopy(check)}
            digest=hashlib.sha256(encode(snapshot).encode()).hexdigest()
            review=latest.get((int(fid),check['baseline']))
            check.update(fingerprint=digest,identity_ambiguous=len(feature['primary_links'])>1,
                         confirmable=check['severity'] in CONFIRMABLE and len(feature['primary_links'])<=1,
                         reviewed=bool(review and review.revoked_at is None and review.fingerprint==digest))
            check['review_id']=review.id if check['reviewed'] else None
            check['review_snapshot']=snapshot
    return flags

async def review_detail(db,feature_id):
    from app.services.feature_name_standards import audit_feature_names
    feature=await db.get(Feature,feature_id)
    if feature is None:
        raise HTTPException(404,'功能不存在')
    audit=await audit_feature_names(db)
    flag=audit['review_flags']['by_feature'].get(str(feature_id),{})
    rows=(await db.scalars(select(FeatureNameReview).where(FeatureNameReview.feature_id==feature_id).order_by(FeatureNameReview.id.desc()).limit(50))).all() if await storage_ready(db) else []
    return {'feature_id':feature_id,'name':feature.primary_cn_name or feature.name,
            'checks':flag.get('checks',[]),'history':[{'id':r.id,'baseline':r.baseline,'fingerprint':r.fingerprint,
            'snapshot':json.loads(r.snapshot_data),'note':r.note,'confirmed_by':r.confirmed_by,
            'confirmed_at':r.confirmed_at.isoformat(),'revoked_at':r.revoked_at.isoformat() if r.revoked_at else None,
            'effective':any(c.get('review_id')==r.id and c['reviewed'] for c in flag.get('checks',[]))} for r in rows]}

async def confirm_differences(db,feature_id,checks,note,confirmed_by):
    if not await storage_ready(db):
        raise HTTPException(503,'名称核对记录尚未初始化，请重启本地服务')
    # Serialize source validation and confirmation in the same write transaction.
    result=await db.execute(update(Feature).where(Feature.id==feature_id).values(id=Feature.id))
    if result.rowcount!=1:
        raise HTTPException(404,'功能不存在')
    detail=await review_detail(db,feature_id)
    available={c['baseline']:c for c in detail['checks']}
    if not checks or set(checks)-{'standard','config'}:
        raise HTTPException(422,'请选择要确认的名称差异')
    for baseline,digest in checks.items():
        check=available.get(baseline)
        if not check or digest!=check['fingerprint'] or check['reviewed']:
            raise HTTPException(409,'名称、IPN或基准已经变化，请刷新后重新核对')
        if not check['confirmable']:
            raise HTTPException(422,'功能对应关系尚不明确，请先核对主数据，不能直接清除提示')
        db.add(FeatureNameReview(feature_id=feature_id,baseline=baseline,fingerprint=digest,
               snapshot_data=encode(check['review_snapshot']),note=note,confirmed_by=confirmed_by))
    await db.commit()
    return await review_detail(db,feature_id)

async def revoke_confirmation(db,feature_id,review_id):
    if not await storage_ready(db):
        raise HTTPException(503,'名称核对记录尚未初始化，请重启本地服务')
    result=await db.execute(update(FeatureNameReview).where(FeatureNameReview.id==review_id,
        FeatureNameReview.feature_id==feature_id,FeatureNameReview.revoked_at.is_(None)).values(revoked_at=utcnow()))
    if result.rowcount!=1:
        raise HTTPException(409,'核对记录不存在或已撤销，请刷新')
    await db.commit()
    return await review_detail(db,feature_id)

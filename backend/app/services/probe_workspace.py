"""One calculation path for probe drafts, previews, publication and exports."""
from copy import deepcopy
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from app.models import ConfigItem, ConfigVersion, ProductModel, ProductSeries
from app.models.probe import ProbeModel, ProbeModelVariant, Feature, ProductProbeConfig, Application, CategoryApplication
from app.models.probe_workspace import ProbeWorkspace, ProbeWorkspaceMember
from app.services.model_identity import active_model_filter
from app.services.whitepaper_subseries import get_subseries_editor, SubseriesSourceError
from app.services.config_history import build_series_snapshot
from app.services.config_publication import resolve_version_number, ensure_no_pending_drafts
from app.services.registration_rules import normalize_business_name


STATUSES = {'supported', 'conditional', 'unsupported', 'pending'}
RULE_FIELDS = {'defined_status', 'current_status', 'defined_excludes', 'current_excludes', 'notes'}
RULE_FIELDS.add('priority')
PRIORITIES = {None, '标1', '标2', '标3', '新', '新(未优化)', '新(未发放)'}


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def signature(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def row_key(row):
    return f"{row['probe_model_id']}:{row.get('variant_id') or 0}:{row['feature_id']}"


async def shared_scope(db, groups, combinations):
    models = list((await db.scalars(select(ProductModel).where(active_model_filter()).order_by(ProductModel.id))).all())
    parents = {r.id: r.name for r in (await db.execute(select(ProductSeries.id, ProductSeries.name))).all()}
    try:
        shared = get_subseries_editor(models, parents)
    except SubseriesSourceError as error:
        raise HTTPException(503, str(error)) from error
    selected = []
    for names, field in ((groups, 'groups'), (combinations, 'combinations')):
        lookup = {g['name']: g for g in shared[field]}
        for name in dict.fromkeys(names):
            if name not in lookup:
                raise HTTPException(409, f'子系列或组合 {name} 已变化，请刷新')
            group = lookup[name]
            if group.get('missing_models') or group.get('unresolved_refs'):
                raise HTTPException(422, f'{name} 存在未匹配机型，请先核对子系列')
            selected.extend(group['model_ids'])
    if not selected:
        raise HTTPException(422, '请至少选择一个有效子系列或组合')
    return {'groups': sorted(set(groups)), 'combinations': sorted(set(combinations)),
            'revision': shared['revision'], 'model_ids': sorted(set(selected))}


async def catalog(db):
    probes = list((await db.scalars(select(ProbeModel).order_by(ProbeModel.id))).all())
    variants = list((await db.scalars(select(ProbeModelVariant).order_by(ProbeModelVariant.id))).all())
    features = list((await db.scalars(select(Feature).order_by(Feature.id))).all())
    links = (await db.execute(select(CategoryApplication.category_id, Application.name).join(Application))).all()
    return {
        'probes': [{'id': p.id, 'name': p.model_number, 'category_id': p.category_id} for p in probes],
        'variants': [{'id': v.id, 'probe_model_id': v.probe_model_id, 'ipn': v.ipn, 'internal_model': v.internal_model} for v in variants],
        'features': [{'id': f.id, 'name': f.name, 'ipn': f.ipn, 'config_item_id': f.config_item_id} for f in features],
        'applications': {str(p.category_id): sorted({r.name for r in links if r.category_id == p.category_id}) for p in probes},
    }


async def validate_document(db, document, *, refresh=False):
    document = deepcopy(document)
    try:
        old_scope = document['scope']
        actual = await shared_scope(db, old_scope['groups'], old_scope['combinations'])
        if not refresh and old_scope != actual:
            raise HTTPException(409, '子系列成员或共享定义已变化，请更新范围并重新核对草稿')
        document['scope'] = actual
        cat = await catalog(db)
        probe_ids = {p['id'] for p in cat['probes']}
        feature_ids = {f['id'] for f in cat['features']}
        variants = {v['id']: v for v in cat['variants']}
        rows = document['rows']
        if not isinstance(rows, list) or len(rows) > 20000:
            raise ValueError('总集条目格式或数量无效')
        keys = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) - RULE_FIELDS - {'probe_model_id', 'variant_id', 'feature_id'}:
                raise ValueError('总集包含未知字段')
            if row['probe_model_id'] not in probe_ids or row['feature_id'] not in feature_ids:
                raise ValueError('总集包含未知探头或功能编号')
            variant = row.get('variant_id')
            if variant and (variant not in variants or variants[variant]['probe_model_id'] != row['probe_model_id']):
                raise ValueError('探头变体不属于该探头')
            if not variant and any(v['probe_model_id'] == row['probe_model_id'] for v in cat['variants']):
                raise ValueError('该探头有物料变体，请选择明确的探头/IPN')
            key = row_key(row)
            if key in keys:
                raise ValueError('总集包含重复的探头变体与功能')
            keys.add(key)
            validate_rule(row)
            row.setdefault('variant_id', None)
            row.setdefault('priority', None)
            row.setdefault('notes', '')
            for side in ('defined', 'current'):
                row.setdefault(side + '_status', 'pending')
                row.setdefault(side + '_excludes', [])
                row[side + '_excludes'] = sorted(set(row[side + '_excludes']))
                if row[side + '_status'] == 'supported' and row[side + '_excludes']:
                    row[side + '_status'] = 'conditional'
        overrides = document['overrides']
        if not isinstance(overrides, dict):
            raise ValueError('机型差异必须是对象')
        for model, changes in overrides.items():
            if str(int(model)) != model or int(model) not in actual['model_ids']:
                raise ValueError('差异机型不在所选范围内')
            if not isinstance(changes, dict):
                raise ValueError('机型差异格式无效')
            for key, rule in changes.items():
                if key not in keys or not isinstance(rule, dict) or set(rule) - RULE_FIELDS:
                    raise ValueError('机型差异引用无效条目或字段')
                validate_rule(rule)
        return {'scope': actual, 'rows': rows, 'overrides': overrides}
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise HTTPException(422, f'探头配置格式无效：{error}') from error


def validate_rule(rule):
    if rule.get('priority') not in PRIORITIES:
        raise ValueError('优先级标记无效')
    for field in ('defined_status', 'current_status'):
        if field in rule and rule[field] not in STATUSES:
            raise ValueError(f'{field} 必须是支持、条件支持、不支持或待确认')
    for field in ('defined_excludes', 'current_excludes'):
        if field in rule and (not isinstance(rule[field], list) or not all(isinstance(v, str) and v.strip() for v in rule[field])):
            raise ValueError('排除应用必须是非空名称的数组；清空请使用 []')
    if 'notes' in rule and (not isinstance(rule['notes'], str) or len(rule['notes']) > 4000):
        raise ValueError('说明格式无效或过长')


def legacy_excludes(value):
    if not value:
        return []
    try:
        parsed = json.loads(value)
        result = parsed.get('excludes', []) if isinstance(parsed, dict) else parsed
        return result if isinstance(result, list) and all(isinstance(v, str) for v in result) else []
    except (ValueError, TypeError):
        return []


async def initial_document(db, scope):
    """Keep legacy differences as unconfirmed draft values; never infer consensus."""
    cat = await catalog(db)
    rows, overrides = {}, {}
    legacy = list((await db.scalars(select(ProductProbeConfig).where(
        ProductProbeConfig.product_model_id.in_(scope['model_ids'])))).all())
    for cfg in legacy:
        variants = [v['id'] for v in cat['variants'] if v['probe_model_id'] == cfg.probe_model_id] or [None]
        for variant in variants:
            row = {'probe_model_id': cfg.probe_model_id, 'variant_id': variant, 'feature_id': cfg.feature_id,
                   'defined_status': 'pending', 'current_status': 'pending', 'defined_excludes': [], 'current_excludes': [], 'notes': '', 'priority': None}
            key = row_key(row)
            rows[key] = row
            overrides.setdefault(str(cfg.product_model_id), {})[key] = {
                'defined_status': cfg.defined_status, 'current_status': cfg.current_status,
                'defined_excludes': legacy_excludes(cfg.defined_excludes),
                'current_excludes': legacy_excludes(cfg.current_excludes),
                'priority': cfg.priority,
                'notes': f'历史数据待核对；{cfg.notes or ""}',
            }
    return {'scope': scope, 'rows': list(rows.values()), 'overrides': overrides}


async def ensure_no_overlap(db, document, workspace_id=None):
    ids = set(document['scope']['model_ids'])
    for other in (await db.scalars(select(ProbeWorkspace))).all():
        if other.id == workspace_id:
            continue
        # Both the live membership and pending scope reserve their own models.
        for value in (other.published_data, other.draft_data):
            if value and ids.intersection(json.loads(value)['scope']['model_ids']):
                raise HTTPException(409, f'机型已属于共同总集 {other.id}（{other.name}），请打开已有总集维护，避免重复配置')


def config_gate(value):
    """Preserve special/unknown source marks instead of inventing support."""
    value = normalize_business_name(value).replace('∆', 'Δ')
    if value in {'X', 'O', 'Δ'}:
        return 'supported'
    if value.upper() == 'N/A':
        return 'not_applicable'
    return 'pending'


async def reserve_members(db, item, document, *, published=False):
    ids = set(document['scope']['model_ids'])
    if not published and item.published_data:
        ids.update(json.loads(item.published_data)['scope']['model_ids'])
    await db.execute(delete(ProbeWorkspaceMember).where(ProbeWorkspaceMember.workspace_id == item.id))
    db.add_all(ProbeWorkspaceMember(model_id=mid, workspace_id=item.id) for mid in sorted(ids))
    try:
        await db.flush()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(409, '机型已被其他总集占用，请刷新并复用已有总集') from error


def calculate_results(document, snapshots, cat):
    probes = {p['id']: p for p in cat['probes']}
    variants = {v['id']: v for v in cat['variants']}
    features = {f['id']: f for f in cat['features']}
    models = {m['id']: m for snap in snapshots.values() for m in snap['models']}
    results = []
    for mid in document['scope']['model_ids']:
        items = [item for snap in snapshots.values() for item in snap['items'] if str(mid) in item.get('values', {})]
        for row in document['rows']:
            key = row_key(row)
            rule = {**row, **document['overrides'].get(str(mid), {}).get(key, {})}
            probe, feature = probes.get(row['probe_model_id'], {}), features.get(row['feature_id'], {})
            variant = variants.get(row.get('variant_id'), {})
            identity_missing = not probe or not feature or bool(row.get('variant_id') and not variant)
            probe_items = [i for i in items if i['category'] == 'Probes' and (
                (variant.get('ipn') and i.get('ipn') == variant['ipn']) or
                (not row.get('variant_id') and i.get('rd_name') == probe.get('name')))] if not identity_missing else []
            feature_items = [i for i in items if (
                i['id'] == feature.get('config_item_id') if feature.get('config_item_id')
                else bool(feature.get('ipn')) and i.get('ipn') == feature['ipn'])] if not identity_missing else []
            sources = {'probe': probe_items[0]['values'][str(mid)] if len(probe_items) == 1 else {},
                       'feature': feature_items[0]['values'][str(mid)] if len(feature_items) == 1 else {}}
            result = {'key': key, 'model_id': mid, 'model_name': models.get(mid, {}).get('name', str(mid)),
                      'probe_name': probe.get('name', f"探头 #{row['probe_model_id']}（身份缺失）"), 'ipn': variant.get('ipn'), 'feature_name': feature.get('name', f"功能 #{row['feature_id']}（身份缺失）"),
                      'source': sources, 'notes': rule.get('notes', ''),
                      'priority': rule.get('priority'),
                      'has_override': key in document['overrides'].get(str(mid), {})}
            for kind, value in sources.items():
                result[kind + '_configuration'] = ' · '.join(
                    f"{label}：{value.get(field) or '待确认'}" for label, field in
                    [('定义', 'final_config'), ('现状', 'current_config'), ('选型', 'selection_config')])
            for side, config_field in (('defined', 'final_config'), ('current', 'current_config')):
                status = rule.get(side + '_status', 'pending')
                gates = [config_gate(v.get(config_field)) for v in sources.values()]
                if 'not_applicable' in gates:
                    status, reason = 'not_applicable', '该机型主配置明确为 N/A'
                elif 'pending' in gates:
                    status, reason = 'pending', '主配置缺失、映射不唯一或标记待核对'
                else:
                    reason = '机型特有差异' if result['has_override'] else '共同总集'
                result[side + '_status'] = status
                result[side + '_reason'] = reason
                result[side + '_excludes'] = rule.get(side + '_excludes', [])
                if status in {'supported', 'conditional'} and any(
                    app not in cat.get('applications', {}).get(str(probe.get('category_id')), [])
                    for app in result[side + '_excludes']
                ):
                    result[side + '_status'] = 'pending'
                    result[side + '_reason'] = '排除应用不在该探头类别的已确认应用范围内，请核对'
                    continue
                if status in {'supported', 'conditional'} and result[side + '_excludes']:
                    result[side + '_status'] = 'conditional'
            results.append(result)
    return results


async def context(db, document, *, publishing=False, version_number=None):
    ids = document['scope']['model_ids']
    models = list((await db.scalars(select(ProductModel).where(ProductModel.id.in_(ids), active_model_filter()))).all())
    if len(models) != len(ids):
        raise HTTPException(409, '机型身份已变化，请重新核对范围')
    snapshots, numbers = {}, {}
    for sid in sorted({m.series_id for m in models}):
        if publishing:
            await ensure_no_pending_drafts(db, sid)
            numbers[str(sid)] = await resolve_version_number(db, sid, version_number)
        snapshots[str(sid)] = await build_series_snapshot(db, sid, include_probes=False)
    return snapshots, numbers, await catalog(db)


async def attach_published_probes(db, snapshot, replacement=None):
    """Normal configuration releases freeze applicable probe rules as well."""
    snapshot = deepcopy(snapshot)
    model_ids = {m['id'] for m in snapshot['models']}
    if not model_ids:
        return snapshot
    documents = {w.id: json.loads(w.published_data) for w in
                 (await db.scalars(select(ProbeWorkspace).where(ProbeWorkspace.published_data.isnot(None)))).all()}
    if replacement:
        documents[replacement[0]] = replacement[1]
    relevant = [(wid, doc) for wid, doc in documents.items() if model_ids.intersection(doc['scope']['model_ids'])]
    if relevant:
        cat = await catalog(db)
        snapshot['probe_configuration'] = []
        for wid, doc in relevant:
            scoped = deepcopy(doc)
            scoped['scope']['model_ids'] = sorted(model_ids.intersection(doc['scope']['model_ids']))
            snapshot['probe_configuration'].append({'workspace_id': wid, 'data': doc,
                'results': calculate_results(scoped, {'current': snapshot}, cat)})
    return snapshot


def document_diff(before, after):
    before = before or {'rows': [], 'overrides': {}}
    old, new = {row_key(r): r for r in before['rows']}, {row_key(r): r for r in after['rows']}
    return {'added': len(new.keys() - old.keys()), 'deleted': len(old.keys() - new.keys()),
            'modified': sum(old[k] != new[k] for k in old.keys() & new.keys()),
            'model_differences_changed': before['overrides'] != after['overrides'],
            'scope_changed': before.get('scope') != after['scope']}

"""Controlled specification values matched against immutable published snapshots."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.config_history import build_snapshot_item_comparison_index
from app.services.feature_identity import clean_feature_name
from app.services.model_identity import normalize_snapshot
from app.services.knowledge_qa import normalize_question

TABLES = {'knowledge_parameter_topics', 'knowledge_parameter_specs', 'knowledge_parameter_revisions'}
SELECTION_LABELS = {'X': '标配', 'O': '选配', 'Δ': '招标支持', '∆': '招标支持', '#': '未注册或不允许支持'}


class ParameterError(ValueError):
    pass


class ParameterConflict(ParameterError):
    pass


class ParameterUnavailable(ParameterError):
    pass


class ParameterNotFound(ParameterError):
    pass


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


async def available(db: AsyncSession) -> bool:
    tables = set((await db.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))).scalars())
    return TABLES <= tables


async def _require(db: AsyncSession) -> None:
    if not await available(db):
        raise ParameterUnavailable('参数型答案尚未初始化，请更新服务后再保存或预览')


async def _topic(db: AsyncSession, topic_id: int) -> dict:
    await _require(db)
    row = (await db.execute(text('SELECT * FROM knowledge_parameter_topics WHERE id=:id'), {'id': topic_id})).mappings().one_or_none()
    if row is None:
        raise ParameterNotFound('参数主题不存在')
    item = dict(row)
    item['aliases'] = json.loads(item.pop('aliases_json'))
    item['fields'] = json.loads(item.pop('fields_json'))
    return item


async def list_topics(db: AsyncSession) -> dict:
    if not await available(db):
        return {'available': False, 'items': [], 'total': 0}
    ids = (await db.execute(text('SELECT id FROM knowledge_parameter_topics ORDER BY id'))).scalars().all()
    items = [await _topic(db, item_id) for item_id in ids]
    return {'available': True, 'items': items, 'total': len(items)}


async def create_topic(db: AsyncSession, payload: dict) -> dict:
    await db.execute(text('BEGIN IMMEDIATE'))
    try:
        await _require(db)
        name, question = payload['name'].strip(), payload['question'].strip()
        if not name or len(normalize_question(question)) < 2:
            raise ParameterError('主题名称和问题不能为空')
        fields = payload['fields']
        keys = [field['key'] for field in fields]
        if len(set(keys)) != len(keys):
            raise ParameterError('参数字段键不能重复')
        for field in fields:
            field['label'], field['unit'] = field['label'].strip(), field['unit'].strip()
            if not field['label'] or (field['type'] == 'number' and not field['unit']):
                raise ParameterError('数值参数须填写名称和单位')
        normalized = normalize_question(question)
        if (await db.execute(text('SELECT id FROM knowledge_parameter_topics WHERE normalized_question=:q'), {'q': normalized})).first():
            raise ParameterConflict('相同问题的参数主题已存在')
        aliases = list(dict.fromkeys(alias.strip() for alias in payload.get('aliases', []) if alias.strip()))
        result = await db.execute(text('''INSERT INTO knowledge_parameter_topics
            (name,question,normalized_question,aliases_json,fields_json)
            VALUES (:name,:question,:normalized,:aliases,:fields) RETURNING id'''),
            {'name': name, 'question': question, 'normalized': normalized, 'aliases': _json(aliases), 'fields': _json(fields)})
        topic_id = result.scalar_one()
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return await _topic(db, topic_id)


async def _spec(db: AsyncSession, spec_id: int, topic_id: int) -> dict:
    row = (await db.execute(text('SELECT * FROM knowledge_parameter_specs WHERE id=:id AND topic_id=:topic'), {'id': spec_id, 'topic': topic_id})).mappings().one_or_none()
    if row is None:
        raise ParameterNotFound('参数规格不存在')
    item = dict(row)
    item['values'] = json.loads(item.pop('values_json'))
    item['is_active'] = bool(item['is_active'])
    descriptions = (await db.execute(text('SELECT zh_desc FROM config_items WHERE TRIM(ipn)=:ipn'), {'ipn': item['ipn']})).scalars().all()
    item['current_cn_name'] = clean_feature_name(descriptions[0]) if len(descriptions) == 1 else None
    item['identity_issue'] = None if len(descriptions) == 1 else '当前IPN不存在或对应多个配置项'
    return item


async def list_specs(db: AsyncSession, topic_id: int) -> dict:
    if not await available(db):
        return {'available': False, 'items': [], 'total': 0}
    await _topic(db, topic_id)
    ids = (await db.execute(text('SELECT id FROM knowledge_parameter_specs WHERE topic_id=:id ORDER BY id'), {'id': topic_id})).scalars().all()
    items = [await _spec(db, item_id, topic_id) for item_id in ids]
    return {'available': True, 'items': items, 'total': len(items)}


def _validated_values(topic: dict, values: dict) -> dict:
    if set(values) != {field['key'] for field in topic['fields']}:
        raise ParameterError('请填写所有参数，且不能增加未定义字段')
    for field in topic['fields']:
        value = values[field['key']]
        if isinstance(value, bool) or not str(value).strip() or len(str(value)) > 500:
            raise ParameterError(f"参数{field['label']}无效")
        if field['type'] == 'number':
            try:
                if not Decimal(str(value)).is_finite():
                    raise InvalidOperation
            except InvalidOperation:
                raise ParameterError(f"参数{field['label']}须为有限数值，单位单独维护") from None
        elif not isinstance(value, str):
            raise ParameterError(f"参数{field['label']}须为文本")
    return values


async def save_spec(db: AsyncSession, topic_id: int, payload: dict, spec_id: int | None = None) -> dict:
    await db.execute(text('BEGIN IMMEDIATE'))
    try:
        topic = await _topic(db, topic_id)
        values = _validated_values(topic, payload['values'])
        cleaned = {field: payload[field].strip() for field in ('name', 'ipn', 'evidence_reference', 'confirmed_by')}
        if not all(cleaned.values()):
            raise ParameterError('规格名称、IPN、依据和实际核对人均须填写')
        matches = (await db.execute(text('SELECT id FROM config_items WHERE TRIM(ipn)=:ipn'), {'ipn': cleaned['ipn']})).all()
        if len(matches) != 1:
            raise ParameterError('IPN不存在或对应多个配置项，请先核实身份')
        active = payload.get('is_active', True)
        if active and (await db.execute(text('''SELECT id FROM knowledge_parameter_specs
            WHERE topic_id=:topic AND ipn=:ipn AND is_active=1 AND (:id IS NULL OR id<>:id)'''),
            {'topic': topic_id, 'ipn': cleaned['ipn'], 'id': spec_id})).first():
            raise ParameterConflict('本主题已有该IPN的启用规格，请编辑已有记录')
        params = {**cleaned, 'topic': topic_id, 'values': _json(values), 'active': int(active)}
        if spec_id is None:
            result = await db.execute(text('''INSERT INTO knowledge_parameter_specs
                (topic_id,name,ipn,values_json,evidence_reference,confirmed_by,revision,is_active)
                VALUES (:topic,:name,:ipn,:values,:evidence_reference,:confirmed_by,1,:active) RETURNING id'''), params)
            spec_id, revision = int(result.scalar_one()), 1
        else:
            old = await _spec(db, spec_id, topic_id)
            if old['revision'] != payload['expected_revision']:
                raise ParameterConflict('规格已被修改，请刷新后再保存')
            revision = old['revision'] + 1
            await db.execute(text('''UPDATE knowledge_parameter_specs SET name=:name,ipn=:ipn,values_json=:values,
                evidence_reference=:evidence_reference,confirmed_by=:confirmed_by,revision=:revision,
                is_active=:active,updated_at=CURRENT_TIMESTAMP WHERE id=:id'''),
                {**params, 'id': spec_id, 'revision': revision})
        await db.execute(text('''INSERT INTO knowledge_parameter_revisions (spec_id,revision,payload_json)
            VALUES (:id,:revision,:payload)'''), {'id': spec_id, 'revision': revision, 'payload': _json({**cleaned, 'values': values, 'is_active': active})})
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return await _spec(db, spec_id, topic_id)


async def _snapshot(db: AsyncSession, version_id: int) -> tuple[dict, dict]:
    row = (await db.execute(text('''SELECT v.id,v.series_id,v.version_number,v.snapshot_data,s.name AS series
        FROM config_versions v JOIN product_series s ON s.id=v.series_id WHERE v.id=:id'''), {'id': version_id})).mappings().one_or_none()
    if row is None:
        raise ParameterNotFound('配置快照不存在')
    try:
        source = json.loads(row['snapshot_data'])
        if not isinstance(source, dict) or not isinstance(source.get('models'), list):
            raise ValueError('快照缺少有效机型列表')
        snapshot = await normalize_snapshot(db, row['series_id'], source)
        models = snapshot['models']
        ids = [int(model['id']) for model in models]
        if not models or len(ids) != len(set(ids)):
            raise ValueError('快照机型列表为空或存在重复身份')
        for model in models:
            current = (await db.execute(text('SELECT series_id FROM product_models WHERE id=:id'), {'id': model['id']})).scalar_one_or_none()
            if current != row['series_id']:
                raise ValueError('快照机型不属于所选系列或身份缺失')
        build_snapshot_item_comparison_index(snapshot)
    except (ValueError, TypeError, KeyError) as error:
        raise ParameterError(f'配置快照无效：{error}') from error
    return {'id': row['id'], 'series_id': row['series_id'], 'series': row['series'], 'version_number': row['version_number']}, snapshot


async def snapshot_options(db: AsyncSession, version_id: int) -> dict:
    metadata, snapshot = await _snapshot(db, version_id)
    return {**metadata, 'models': [{'id': int(model['id']), 'name': model['name']} for model in snapshot['models']]}


def _format_values(topic: dict, values: dict) -> str:
    return '、'.join(f"{field['label']} {values[field['key']]} {field['unit']}".rstrip() for field in topic['fields'])


async def preview(db: AsyncSession, topic_id: int, version_id: int, model_ids: list[int]) -> dict:
    topic = await _topic(db, topic_id)
    metadata, snapshot = await _snapshot(db, version_id)
    models = {int(model['id']): model['name'] for model in snapshot['models']}
    if not model_ids or any(model_id not in models for model_id in model_ids):
        raise ParameterError('请选择所选快照中的完整机型')
    specs = [spec for spec in (await list_specs(db, topic_id))['items'] if spec['is_active']]
    items = build_snapshot_item_comparison_index(snapshot)
    rows = []
    for model_id in dict.fromkeys(model_ids):
        matches, issues, statements = [], [], []
        for spec in specs:
            item = items.get(('ipn', spec['ipn']))
            if item is None:
                issues.append(f"IPN {spec['ipn']} 在此快照中无配置项")
                continue
            values = item.get('values', {})
            if not isinstance(values, dict) or not isinstance(values.get(str(model_id), {}), dict):
                raise ParameterError('快照配置值格式无效')
            config = values.get(str(model_id), {})
            selection = str(config.get('selection_config') or '').strip()
            usable = selection in {'X', 'O', 'Δ', '∆'}
            label = SELECTION_LABELS.get(selection, '正式选型未明确')
            match = {'spec_id': spec['id'], 'name': spec['name'], 'ipn': spec['ipn'], 'values': spec['values'],
                     'selection_config': selection, 'selection_label': label, 'usable': usable,
                     'snapshot_cn_name': item.get('zh_desc') or '', 'current_cn_name': spec['current_cn_name'],
                     'current_config_note': config.get('current_config') or '', 'evidence_reference': spec['evidence_reference'],
                     'confirmed_by': spec['confirmed_by'], 'revision': spec['revision']}
            try:
                _validated_values(topic, spec['values'])
            except ParameterError as error:
                usable = match['usable'] = False
                issues.append(str(error))
            matches.append(match)
            if usable:
                statements.append(f"{label} {spec['name']}（IPN {spec['ipn']}）：{_format_values(topic, spec['values'])}")
            else:
                issues.append(f"{spec['name']}（IPN {spec['ipn']}）：{label}")
        status = 'missing_spec' if not matches else 'needs_review' if issues else 'matched'
        answer = f"{models[model_id]}：" + ('；'.join(statements) if statements else '未找到可明确提供的规格参数')
        if issues:
            answer += '。待核实：' + '；'.join(issues)
        rows.append({'model_id': model_id, 'model_name': models[model_id], 'status': status, 'matches': matches, 'issues': issues, 'answer_text': answer})
    return {'topic': topic, 'snapshot': metadata, 'rows': rows, 'answer_text': '\n'.join(row['answer_text'] for row in rows)}

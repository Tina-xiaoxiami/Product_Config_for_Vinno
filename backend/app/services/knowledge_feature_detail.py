"""Read-only composition of existing identity, snapshot and evidence rules."""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.config_history import build_snapshot_item_comparison_index
from app.services.knowledge_content import find_candidate_evidence
from app.services.knowledge_parameters import SELECTION_LABELS, ParameterError, answer_snapshot
from app.services.knowledge_query import get_feature_knowledge
from app.services.knowledge_release_history import trace_release_history
from app.services.knowledge_scope import missing_scope_fields, resolve_query_scope


async def feature_detail(
    db: AsyncSession, feature_id: int, *, scope: dict | None,
    configuration_version_id: int | None = None,
) -> dict | None:
    feature = await get_feature_knowledge(db, feature_id)
    if feature is None:
        return None
    result = {'feature': feature, 'scope': None, 'status': 'needs_scope',
              'missing_fields': missing_scope_fields(scope), 'configuration': None,
              'citations': [], 'history': None, 'issues': []}
    resolved = await resolve_query_scope(db, scope)
    if resolved is None:
        return result
    result.update(scope=resolved, status='ready')
    if configuration_version_id is None:
        result['issues'].append('请选择已发布配置快照')
    else:
        series_id = (await db.execute(text('SELECT series_id FROM product_models WHERE id=:id'),
                                     {'id': resolved['product_model_id']})).scalar_one()
        metadata, snapshot = await answer_snapshot(
            db, series_id, configuration_version_id=configuration_version_id)
        model_id = resolved['product_model_id']
        model = next((row for row in snapshot['models'] if int(row['id']) == model_id), None)
        if model is None:
            raise ParameterError('所选配置快照没有该完整机型')
        index = build_snapshot_item_comparison_index(snapshot)
        rows = []
        for link in feature['ipns']:
            ipn = str(link['ipn'] or '').strip()
            item = index.get(('ipn', ipn)) if ipn else None
            values = (item or {}).get('values', {})
            if not isinstance(values, dict) or not isinstance(values.get(str(model_id), {}), dict):
                raise ParameterError('快照配置值格式无效')
            config = values.get(str(model_id), {})
            selection = str(config.get('selection_config') or '').strip() or None
            rows.append({'ipn': ipn, 'relation_type': link['relation_type'],
                         'status': 'matched' if item else 'missing',
                         'snapshot_name': (item or {}).get('zh_desc') or '',
                         'selection_config': selection,
                         'selection_label': SELECTION_LABELS.get(selection, '正式选型未明确'),
                         'current_config_note': config.get('current_config') or ''})
        result['configuration'] = {'snapshot': metadata, 'model': model, 'items': rows}
        if not rows:
            result['issues'].append('功能尚无已确认IPN关联，不能按同名推断配置')
        if any(row['status'] == 'missing' for row in rows):
            result['issues'].append('部分关联IPN未出现在该快照，不能据此判断不支持')
    # Names retrieve candidate text only; they never establish identity or applicability.
    query = feature['legacy_name'] or feature['primary_cn_name'] or feature['primary_en_name']
    candidates = await find_candidate_evidence(db, query, scope=resolved, limit=12)
    result['citations'] = [row for row in candidates if row.get('version_id')]
    if not result['citations']:
        result['issues'].append('未找到当前机型与资料版本的可定位正文；不跨系列补全参数或说明')
    result['history'] = await trace_release_history(db, query, resolved)
    return result

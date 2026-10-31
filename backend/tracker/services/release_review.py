"""Versioned human Release Note reconciliation, independent of model summaries."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import re
from typing import Any

_NAMESPACE = 'release-review-v1'
_FIELDS = ('version', 'source_id', 'preview_id', 'locator', 'title', 'text', 'content',
           'verification', 'review_status', 'status', 'operation', 'before', 'after', 'reason')


class ReviewConflict(ValueError):
    """The source set or manual revision changed; the caller must reload."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _hash(value: Any) -> str:
    return sha256(_json(value).encode('utf-8')).hexdigest()


def _context(project_id, query, target):
    if type(project_id) is not int or project_id < 1 or not isinstance(query, str) or not query.strip():
        raise ValueError('项目和功能名称无效。')
    if not isinstance(target, str):
        raise ValueError('目标版本无效。')
    return {'project_id': project_id, 'q': re.sub(r'\s+', ' ', query).strip().casefold(), 'target': target.strip()}


def _identity(event):
    return _hash([event.get('version', ''), event.get('source_id') or event.get('preview_id') or '',
                  event.get('locator', ''), event.get('text') or event.get('content') or ''])


def _pending_events(answer):
    values = answer.get('automatic_pending_changes', [*answer.get('unresolved_changes', []), *answer.get('resolved_changes', [])])
    return {_identity(event): {**event, 'id': _identity(event)} for event in values}


def _events(answer):
    values = [*answer.get('automatic_applied_changes', answer.get('applied_changes', [])), *_pending_events(answer).values()]
    pool = {_identity(event): {**event, 'id': _identity(event)} for event in values}
    ordered = {}
    for row in answer.get('timeline', []):
        identity = _identity(row)
        if identity in pool:
            ordered[identity] = pool[identity]
    return {**ordered, **pool}


def _event_fingerprint(event):
    return _hash({key: event.get(key) for key in _FIELDS})


def _scope(answer, project_id, query, target):
    context = _context(project_id, query, target)
    events = _events(answer)
    fingerprint = _hash({'context': context,
        'baseline': {key: answer.get('baseline', {}).get(key) for key in _FIELDS} if answer.get('baseline') else None,
        'automatic_content': answer.get('automatic_content', answer.get('content', '')),
        'timeline': sorted([{key: event.get(key) for key in _FIELDS} for event in answer.get('timeline', [])], key=_json),
        'pending': sorted([{key: event.get(key) for key in _FIELDS} for event in _pending_events(answer).values()], key=_json),
        'applied': sorted([{key: event.get(key) for key in _FIELDS} for event in answer.get('automatic_applied_changes', answer.get('applied_changes', []))], key=_json),
        'baseline_gap': answer.get('baseline_gap'), 'earliest_record_version': answer.get('earliest_record_version')})
    return context, _NAMESPACE + ':' + _hash(context), fingerprint, events


def _decode(row):
    if row is None:
        return None
    try:
        saved = json.loads(row['content'])
    except (ValueError, TypeError) as error:
        raise ValueError('人工核对修订数据损坏，请查看历史记录。') from error
    if not isinstance(saved, dict) or saved.get('schema') != _NAMESPACE or not isinstance(saved.get('content'), str) or not isinstance(saved.get('decisions'), list):
        raise ValueError('人工核对修订格式无效。')
    return saved


def _migrate_content(saved, answer, fingerprint):
    content = saved['content']
    if saved.get('schema_version') == 2:
        return content, ''
    if saved.get('_source_fingerprint') != fingerprint:
        return content, '旧版人工正文已完整保留；来源已变化，缺少旧来源证据，未按当前更新日志猜测删除任何原句。'
    removed = 0
    for event in answer.get('automatic_applied_changes', answer.get('applied_changes', [])):
        text = str(event.get('after') or '').strip()
        if event.get('operation') != 'append' or not text or content.count(text) != 1:
            continue
        match = re.search(r'(?m)^[ \t]*' + re.escape(text) + r'[ \t]*$', content)
        if match:
            revised = (content[:match.start()] + content[match.end():]).strip()
            if revised:
                content = revised
                removed += 1
    notice = '旧版人工正文已兼容保留；仅将唯一匹配且未改写的系统追加原句移出正文，历史记录未重写。'
    if not removed:
        notice = '旧版人工正文已兼容保留；未猜测删除或改写任何手工字句，历史记录未重写。'
    return content, notice


def _valid_decisions(saved, fingerprint, events):
    valid, stale = [], list(saved.get('stale_decisions', [])) if saved else []
    for decision in saved.get('decisions', []) if saved else []:
        event = events.get(decision['id'])
        matches = event is not None and (decision.get('event_fingerprint') == _event_fingerprint(event)
            if saved.get('schema_version') == 2 else saved.get('_source_fingerprint') == fingerprint)
        plain = {key: decision[key] for key in ('id', 'action')}
        if matches:
            valid.append(plain)
        else:
            stale.append(plain)
    return valid, stale


def _load_rows(connection, key, project_id):
    return connection.execute('SELECT * FROM scenario_description_revisions WHERE context_key=? AND project_id=? ORDER BY revision', (key, project_id)).fetchall()


def _history_states(rows, answer, fingerprint):
    previous_content = (answer.get('baseline') or {}).get('content', '')
    previous_decisions = []
    body_revision = log_revision = 0
    states = []
    events = _events(answer)
    for row in rows:
        saved = _decode(row)
        saved['_source_fingerprint'] = row['source_fingerprint']
        content, notice = _migrate_content(saved, answer, fingerprint)
        decisions = [{key: item[key] for key in ('id', 'action')} for item in saved['decisions']]
        body_changed = saved.get('body_changed', content != previous_content)
        log_changed = saved.get('log_changed', {item['id']: item['action'] for item in decisions} != {item['id']: item['action'] for item in previous_decisions})
        body_revision = saved.get('body_revision', body_revision + int(body_changed))
        log_revision = saved.get('log_revision', log_revision + int(log_changed))
        legacy_change = {'operation': 'legacy_manual', 'reason': '兼容保留的历史手工正文，修订版本未登记', 'source_version': None}
        if saved.get('schema_version') != 2 and row['source_fingerprint'] == fingerprint and body_changed:
            previous_actions = {item['id']: item['action'] for item in previous_decisions}
            included = [item for item in decisions if item['action'] == 'include' and previous_actions.get(item['id']) != 'include']
            if len(included) == 1 and included[0]['id'] in events:
                event = events[included[0]['id']]
                legacy_change = {'operation': 'legacy_include', 'reason': '兼容关联：同期唯一新增的纳入并修改正文决定；原历史记录未重写',
                                 'event_id': included[0]['id'], 'source_version': event.get('version')}
        states.append({'row': row, 'saved': saved, 'content': content, 'migration_notice': notice, 'legacy_body_change': legacy_change,
                       'body_changed': body_changed, 'log_changed': log_changed,
                       'body_revision': body_revision, 'log_revision': log_revision})
        previous_content, previous_decisions = content, decisions
    return states


def decorate_release_review(database, answer, project_id, query, target=''):
    context, key, fingerprint, events = _scope(answer, project_id, query, target)
    with database.connect() as connection:
        rows = _load_rows(connection, key, project_id)
    states = _history_states(rows, answer, fingerprint)
    latest = states[-1] if states else None
    saved = latest['saved'] if latest else None
    decisions, stale_decisions = _valid_decisions(saved, fingerprint, events)
    by_id = {item['id']: item['action'] for item in decisions}
    pending_ids = set(_pending_events(answer))
    recheck_ids = {item['id'] for item in stale_decisions if item['id'] in events}
    output = deepcopy(answer)
    output['automatic_content'] = answer.get('automatic_content', answer.get('content', ''))
    output['automatic_applied_changes'] = deepcopy(answer.get('automatic_applied_changes', answer.get('applied_changes', [])))
    output['automatic_pending_changes'] = list(_pending_events(answer).values())
    output['applied_changes'] = []
    output['content'] = latest['content'] if latest else (answer.get('baseline') or {}).get('content', '')
    output['change_log'] = [{**event, 'origin': 'pending' if identity in pending_ids else 'system',
        'log_status': ('ignored' if by_id[identity] == 'ignore' else 'adopted') if identity in by_id else ('pending' if identity in pending_ids or identity in recheck_ids else 'recognized'),
        **({'review_action': by_id[identity]} if identity in by_id else {})} for identity, event in events.items()]
    output['unresolved_changes'] = [event for identity, event in events.items() if (identity in pending_ids or identity in recheck_ids) and identity not in by_id]
    output['resolved_changes'] = [{**event, 'review_action': by_id[identity]} for identity, event in events.items() if identity in by_id]
    output['review'] = {'revision': rows[-1]['revision'] if rows else 0, 'source_fingerprint': fingerprint,
        'body_revision': latest['body_revision'] if latest else 0, 'log_revision': latest['log_revision'] if latest else 0,
        'content': latest['content'] if latest else None, 'decisions': decisions, 'stale_decisions': stale_decisions,
        'stale': bool(rows and rows[-1]['source_fingerprint'] != fingerprint), 'context': context,
        'migration_notice': latest['migration_notice'] if latest else ''}
    return output


def _validate_content_decisions(content, decisions, events):
    if not isinstance(content, str) or not content.strip() or len(content) > 100000:
        raise ValueError('正文不能为空，且不得超过100000字。')
    if not isinstance(decisions, list) or len(decisions) > len(events):
        raise ValueError('人工核对决定无效。')
    seen = set()
    for decision in decisions:
        if (not isinstance(decision, dict) or set(decision) != {'id', 'action'}
                or not isinstance(decision['id'], str) or decision['id'] not in events
                or decision['action'] not in ('ignore', 'adopt', 'include') or decision['id'] in seen):
            raise ValueError('核对决定必须指向当前变更记录，且不能重复。')
        seen.add(decision['id'])
    return content.strip(), decisions


def _append(database, answer, project_id, query, target, payload, *, restore=False):
    context, key, fingerprint, events = _scope(answer, project_id, query, target)
    if not answer.get('baseline'):
        raise ValueError('当前没有可人工核对的Release Note完整基线。')
    if not isinstance(payload, dict) or type(payload.get('revision')) is not int or payload['revision'] < 0:
        raise ValueError('修订号无效。')
    if payload.get('source_fingerprint') != fingerprint:
        raise ReviewConflict('Release Note来源已变化，请重新查询后核对。')
    with database.transaction() as connection:
        rows = _load_rows(connection, key, project_id)
        latest_revision = rows[-1]['revision'] if rows else 0
        if latest_revision != payload['revision']:
            raise ReviewConflict('已有更新的人工核对修订，请刷新后再保存。')
        states = _history_states(rows, answer, fingerprint)
        latest = states[-1] if states else None
        previous = latest['content'] if latest else answer['baseline']['content']
        current_decisions, stale_decisions = _valid_decisions(latest['saved'] if latest else None, fingerprint, events)
        content, decisions = previous, current_decisions
        body_change = payload.get('body_change', {})
        changed = []
        if (not isinstance(body_change, dict) or set(body_change) - {'event_id', 'operation', 'reason'}
                or any(not isinstance(value, str) or len(value) > 2000 for value in body_change.values())):
            raise ValueError('正文修订说明无效。')
        if restore:
            revision = payload.get('restore_revision')
            kind = payload.get('kind', 'body')
            if type(revision) is not int or revision < 0 or kind not in ('body', 'log'):
                raise ValueError('待恢复的修订号或类型无效。')
            old = next((item for item in states if item['row']['revision'] == revision), None)
            if revision and old is None:
                raise ValueError('待恢复的修订不存在。')
            if kind == 'body':
                content = old['content'] if old else answer['baseline']['content']
                body_change = {'operation': 'restore', 'reason': f'恢复正文修订 {revision}', 'restore_revision': revision}
            else:
                snapshot = {**old['saved'], 'stale_decisions': []} if old else None
                decisions, invalid = _valid_decisions(snapshot, fingerprint, events)
                if invalid:
                    raise ReviewConflict('历史日志决定的来源已变化，不能直接恢复。')
        else:
            content, decisions = _validate_content_decisions(payload.get('content'), payload.get('decisions'), events)
            previous_actions = {item['id']: item['action'] for item in current_decisions}
            changed = [item for item in decisions if previous_actions.get(item['id']) != item['action']]
            removed = set(previous_actions) - {item['id'] for item in decisions}
            if content != previous and (changed or removed) and not any(item['action'] == 'include' for item in changed):
                raise ValueError('采纳或忽略更新日志不能同时改写正文，请使用正文编辑或采纳并修改正文。')
            if any(item['action'] == 'include' for item in changed) and content == previous:
                raise ValueError('采纳并修改正文必须包含实际正文修订；仅采纳日志请使用adopt。')
        content, decisions = _validate_content_decisions(content, decisions, events)
        if body_change.get('event_id') and body_change['event_id'] not in events:
            raise ValueError('正文修订关联的变更记录无效。')
        if any(not isinstance(value, str) for field, value in body_change.items() if field in ('event_id', 'operation', 'reason')):
            raise ValueError('正文修订说明必须为文本。')
        body_changed = content != previous
        log_changed = {item['id']: item['action'] for item in decisions} != {item['id']: item['action'] for item in current_decisions}
        if body_changed:
            included = [item for item in changed if item['action'] == 'include']
            if len(included) == 1 and not body_change.get('event_id'):
                body_change = {**body_change, 'event_id': included[0]['id']}
            event = events.get(body_change.get('event_id'), {})
            body_change = {'operation': 'edit', 'reason': '手工修订正文', **body_change, 'source_version': event.get('version')}
        body_revision = (latest['body_revision'] if latest else 0) + int(body_changed)
        log_revision = (latest['log_revision'] if latest else 0) + int(log_changed)
        packed = _json({'schema': _NAMESPACE, 'schema_version': 2, 'context': context, 'content': content,
            'decisions': [{**item, 'event_fingerprint': _event_fingerprint(events[item['id']])} for item in decisions],
            'stale_decisions': stale_decisions, 'body_revision': body_revision, 'log_revision': log_revision,
            'body_changed': body_changed, 'log_changed': log_changed,
            'body_change': {**body_change, 'before': previous, 'after': content} if body_changed else {}})
        connection.execute('INSERT INTO scenario_description_revisions(context_key,revision,project_id,content,source_fingerprint) VALUES (?,?,?,?,?)',
                           (key, latest_revision + 1, project_id, packed, fingerprint))
    return decorate_release_review(database, answer, project_id, query, target)


def save_release_review(database, answer, project_id, query, target, payload):
    return _append(database, answer, project_id, query, target, payload)


def list_release_review_history(database, answer, project_id, query, target='', kind='body'):
    if kind not in ('body', 'log'):
        raise ValueError('修订类型无效。')
    context, key, fingerprint, events = _scope(answer, project_id, query, target)
    with database.connect() as connection:
        rows = _load_rows(connection, key, project_id)
    history = []
    for item in reversed(_history_states(rows, answer, fingerprint)):
        if not item[kind + '_changed']:
            continue
        saved = item['saved']
        decisions, invalid = _valid_decisions(saved, fingerprint, events)
        _, invalid_restore = _valid_decisions({**saved, 'stale_decisions': []}, fingerprint, events)
        change = saved.get('body_change', {}) if saved.get('schema_version') == 2 else item['legacy_body_change']
        if change.get('event_id') in events:
            change = {**change, 'source_version': events[change['event_id']].get('version')}
        history.append({'revision': item['row']['revision'], 'body_revision': item['body_revision'], 'log_revision': item['log_revision'],
            'kind': kind, 'created_at': item['row']['created_at'], 'source_fingerprint': item['row']['source_fingerprint'],
            'content': item['content'], 'decisions': decisions, 'stale_decisions': invalid,
            'body_change': change, 'restorable': bool(answer.get('baseline')) and (kind == 'body' or not invalid_restore)})
    return {'context': context, 'source_fingerprint': fingerprint, 'kind': kind, 'history': history + [
        {'revision': 0, 'body_revision': 0, 'log_revision': 0, 'kind': kind, 'created_at': '', 'source_fingerprint': fingerprint,
         'content': (answer.get('baseline') or {}).get('content', ''), 'decisions': [], 'body_change': {}, 'restorable': bool(answer.get('baseline'))}]}


def restore_release_review(database, answer, project_id, query, target, payload):
    return _append(database, answer, project_id, query, target, payload, restore=True)

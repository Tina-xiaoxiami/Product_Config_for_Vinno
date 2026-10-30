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


def _events(answer):
    # Accept both fresh answers and decorated answers without losing pending rows.
    values = [*answer.get('unresolved_changes', []), *answer.get('resolved_changes', [])]
    return {_identity(event): {**event, 'id': _identity(event)} for event in values}


def _scope(answer, project_id, query, target):
    context = _context(project_id, query, target)
    events = _events(answer)
    fingerprint = _hash({'context': context,
        'baseline': {key: answer.get('baseline', {}).get(key) for key in _FIELDS} if answer.get('baseline') else None,
        'automatic_content': answer.get('automatic_content', answer.get('content', '')),
        'timeline': sorted([{key: event.get(key) for key in _FIELDS} for event in answer.get('timeline', [])], key=_json),
        'pending': sorted([{key: event.get(key) for key in _FIELDS} for event in events.values()], key=_json),
        'applied': sorted([{key: event.get(key) for key in _FIELDS} for event in answer.get('applied_changes', [])], key=_json),
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


def decorate_release_review(database, answer, project_id, query, target=''):
    context, key, fingerprint, events = _scope(answer, project_id, query, target)
    with database.connect() as connection:
        row = connection.execute('SELECT * FROM scenario_description_revisions WHERE context_key=? AND project_id=? ORDER BY revision DESC LIMIT 1', (key, project_id)).fetchone()
    saved = _decode(row)
    stale = bool(row and row['source_fingerprint'] != fingerprint)
    output = deepcopy(answer)
    output['automatic_content'] = answer.get('automatic_content', answer.get('content', ''))
    output['content'] = output['automatic_content']
    output['unresolved_changes'] = list(events.values())
    output['resolved_changes'] = []
    output['review'] = {'revision': row['revision'] if row else 0, 'source_fingerprint': fingerprint,
                        'content': saved['content'] if saved else None,
                        'decisions': saved['decisions'] if saved else [], 'stale': stale, 'context': context}
    if saved and not stale:
        decisions = {decision['id']: decision['action'] for decision in saved['decisions']}
        output['content'] = saved['content']
        output['resolved_changes'] = [{**event, 'review_action': decisions[identity]} for identity, event in events.items() if identity in decisions]
        output['unresolved_changes'] = [event for identity, event in events.items() if identity not in decisions]
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
                or decision['action'] not in ('ignore', 'include') or decision['id'] in seen):
            raise ValueError('核对决定必须指向当前待核记录，且不能重复。')
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
        latest = connection.execute('SELECT COALESCE(MAX(revision),0) FROM scenario_description_revisions WHERE context_key=? AND project_id=?', (key, project_id)).fetchone()[0]
        if latest != payload['revision']:
            raise ReviewConflict('已有更新的人工核对修订，请刷新后再保存。')
        if restore:
            revision = payload.get('restore_revision')
            if type(revision) is not int or revision < 0:
                raise ValueError('待恢复的修订号无效。')
            if revision == 0:
                content, decisions = _validate_content_decisions(answer.get('automatic_content', answer.get('content')), [], events)
            else:
                row = connection.execute('SELECT * FROM scenario_description_revisions WHERE context_key=? AND project_id=? AND revision=?', (key, project_id, revision)).fetchone()
                if row is None:
                    raise ValueError('待恢复的修订不存在。')
                if row['source_fingerprint'] != fingerprint:
                    raise ReviewConflict('历史修订的来源与当前不同，不能直接恢复。')
                saved = _decode(row)
                content, decisions = _validate_content_decisions(saved['content'], saved['decisions'], events)

        else:
            content, decisions = _validate_content_decisions(payload.get('content'), payload.get('decisions'), events)
        packed = _json({'schema': _NAMESPACE, 'context': context, 'content': content, 'decisions': decisions})
        connection.execute('INSERT INTO scenario_description_revisions(context_key,revision,project_id,content,source_fingerprint) VALUES (?,?,?,?,?)',
                           (key, latest + 1, project_id, packed, fingerprint))
    return decorate_release_review(database, answer, project_id, query, target)


def save_release_review(database, answer, project_id, query, target, payload):
    return _append(database, answer, project_id, query, target, payload)


def list_release_review_history(database, answer, project_id, query, target=''):
    context, key, fingerprint, _ = _scope(answer, project_id, query, target)
    with database.connect() as connection:
        rows = connection.execute('SELECT * FROM scenario_description_revisions WHERE context_key=? AND project_id=? ORDER BY revision DESC', (key, project_id)).fetchall()
    return {'context': context, 'source_fingerprint': fingerprint, 'history': [
        {'revision': row['revision'], 'created_at': row['created_at'], 'source_fingerprint': row['source_fingerprint'],
         'content': _decode(row)['content'], 'decisions': _decode(row)['decisions'],
         'restorable': row['source_fingerprint'] == fingerprint} for row in rows] + [{'revision': 0, 'created_at': '', 'source_fingerprint': fingerprint, 'content': answer.get('automatic_content', answer.get('content', '')), 'decisions': [], 'restorable': bool(answer.get('baseline'))} ]}


def restore_release_review(database, answer, project_id, query, target, payload):
    return _append(database, answer, project_id, query, target, payload, restore=True)

"""Evidence-scoped, cached model descriptions with independent manual revisions."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any

from tracker.domain import version_key
from tracker.services.description_model import SYSTEM_PROMPT
from tracker.services.release_evidence import release_evidence

DESCRIPTION_TABLES = (
    '''CREATE TABLE IF NOT EXISTS scenario_description_cache (
        context_key TEXT PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
        fingerprint TEXT NOT NULL, baseline_hash TEXT NOT NULL, model TEXT NOT NULL,
        result_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS scenario_description_revisions (
        context_key TEXT NOT NULL, revision INTEGER NOT NULL, project_id INTEGER NOT NULL REFERENCES projects(id),
        content TEXT NOT NULL, source_fingerprint TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(context_key, revision))''',
    '''CREATE TABLE IF NOT EXISTS scenario_description_attempts (
        id INTEGER PRIMARY KEY, context_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
        day TEXT NOT NULL, reserved_tokens INTEGER NOT NULL, used_tokens INTEGER,
        status TEXT NOT NULL DEFAULT 'running', error TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''',
)
# The local application serves one process; serialize identical query bursts and budget reservations.
_GENERATION_LOCK = threading.RLock()
_PROMPT_VERSION = 'feature-description-v1'


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _normalize(text):
    return ' '.join(str(text or '').casefold().split())


def _language(text, scope=''):
    if '海外' in scope:
        return 'en'
    if '国内' in scope:
        return 'cn'
    return 'cn' if re.search(r'[\u4e00-\u9fff]', text) else 'en'


def _change_text(database, change, language, query):
    """Return complete records or explicitly incomplete context; never clipped search snippets."""
    own_text = change.get('description_' + language) or change.get('raw_' + language)
    if own_text:
        return str(own_text), True
    other = 'en' if language == 'cn' else 'cn'
    if change.get('description_' + other) or change.get('raw_' + other):
        return '', False
    if (change.get('title_en') and not change.get('title_cn') and language == 'cn'
            or change.get('title_cn') and not change.get('title_en') and language == 'en'):
        return '', False
    source = str(change.get('preview_id') or '')
    if source.startswith('release:'):
        full = release_evidence(database, source, change.get('locator', ''), query=query, limit=None)
        if not full:
            return '', False
        if full.get('section') and full['section'].get('complete'):
            return full['section']['content'], True
        if source.startswith('release:source:'):
            # Preserve nearby platform/probe restrictions around every hit. These windows
            # are context only: without a verified boundary they cannot establish a fact.
            chunks = {item['locator']: item['text'] for item in full.get('chunks', [])}
            for match in full.get('matches', []):
                if match['locator'] in chunks:
                    continue
                nearby = release_evidence(database, source, match['locator'], query=query, limit=None)
                chunks.update({item['locator']: item['text'] for item in (nearby or {}).get('chunks', [])})
            return '\n'.join(text for _, text in sorted(chunks.items(), key=lambda item: int(item[0].split()[-1]))), False
        texts = [chunk['text'] for chunk in full.get('chunks', [])
                 if chunk['locator'] == ('中文记录' if language == 'cn' else 'English record')
                 and _normalize(query) in _normalize(chunk['text'])]
        return '\n'.join(texts), True
    text = str(change.get('matched_text') or change.get('title_' + language) or '')
    if '...' in text or '…' in text or _language(text) != language:
        return '', False
    return text, False


def _collect(database, answer, query):
    baseline = answer['baseline']
    detail = baseline['detail_evidence']
    text = answer['section']['content']
    language = _language(text, detail.get('scope') or baseline.get('scope') or '')
    evidence = [{'id': 'baseline', 'text': text, 'versions': [baseline['version']],
                 'scope': detail.get('scope') or baseline.get('scope') or '适用范围未登记',
                 'state': '基线原文', 'complete': True, 'preview_id': detail['source_id'],
                 'locator': answer['section'].get('locator') or detail.get('locator', '')}]
    groups = {}
    excluded = 0
    for change in sorted(answer.get('later_changes', []), key=lambda row: (version_key(row.get('version') or ''), _json(row))):
        if change.get('category') in {'bug', 'image'} or change.get('review_status') == 'rejected':
            excluded += 1
            continue
        content, complete = _change_text(database, change, language, query)
        content = content.strip()
        if not content or _normalize(content) == _normalize(text):
            excluded += 1
            continue
        # Approval and explicit scope stay part of identity; unreviewed text cannot inherit approval.
        state = '已审核版本记录' if change.get('review_status') == 'approved' else '原文提及，范围和变化待核对'
        scope = change.get('scope') or '适用范围未登记'
        key = _hash([_normalize(content), state, scope, complete])
        if key not in groups:
            groups[key] = {'id': key[:16], 'text': content, 'versions': [], 'scope': scope,
                           'state': state, 'complete': complete, 'preview_id': change.get('preview_id', ''), 'locator': change.get('locator', '')}
        if change.get('version') not in groups[key]['versions']:
            groups[key]['versions'].append(change.get('version'))
    evidence.extend(groups.values())
    return evidence, excluded


def _validate(result, evidence):
    sources = {item['id']: item['text'] for item in evidence if item.get('complete', True)}
    if not isinstance(result, dict) or not isinstance(result.get('paragraphs'), list) or not result['paragraphs']:
        raise ValueError('模型说明没有有效段落，已保留原说明。')
    if len(result['paragraphs']) > 100:
        raise ValueError('模型段落数量超出限制。')
    for paragraph in result['paragraphs']:
        if not isinstance(paragraph, dict) or not isinstance(paragraph.get('text'), str) or not paragraph['text'].strip():
            raise ValueError('模型段落格式无效。')
        citations = paragraph.get('citations')
        if not isinstance(citations, list) or not citations:
            raise ValueError('模型段落缺少原文引用。')
        for citation in citations:
            if not isinstance(citation, dict):
                raise ValueError('模型引用格式无效。')
            quote, source = citation.get('quote'), citation.get('id')
            if (not isinstance(source, str) or source not in sources or not isinstance(quote, str)
                    or len(quote.strip()) < 4 or quote not in sources[source]):
                raise ValueError('模型引用未通过逐字原文校验，已保留原说明。')
    unresolved = result.get('unresolved', [])
    if not isinstance(unresolved, list) or any(not isinstance(item, str) for item in unresolved):
        raise ValueError('模型待核对信息格式无效。')
    content = '\n\n'.join(item['text'].strip() for item in result['paragraphs'])
    if len(content) > 50000:
        raise ValueError('模型说明长度超出限制。')
    return content


def _generate(database, key, project_id, fingerprint, baseline_hash, evidence, model, allow_generation):
    with _GENERATION_LOCK:
        with database.connect() as connection:
            cache = connection.execute('SELECT * FROM scenario_description_cache WHERE context_key=?', (key,)).fetchone()
            last = connection.execute('SELECT * FROM scenario_description_attempts WHERE context_key=? AND fingerprint=? ORDER BY id DESC LIMIT 1', (key, fingerprint)).fetchone()
        if cache and cache['fingerprint'] == fingerprint:
            return json.loads(cache['result_json']), 'ready', '', cache
        if not model or not model.configured:
            return None, 'unconfigured', '请在 API 设置中配置 DeepSeek 或 OpenAI 后启用自动整理。', cache
        if not allow_generation:
            return None, 'deferred', '资料已更新，请重新查询获取最新自动稿。', cache
        if last and last['status'] in {'failed', 'running'}:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(last['created_at']).replace(tzinfo=timezone.utc)).total_seconds()
            if age < 600:
                return None, 'deferred', last['error'] or '自动整理正在处理或等待重试，请稍后刷新。', cache
        current = None
        new_evidence = evidence
        if cache and cache['baseline_hash'] == baseline_hash and cache['model'] == model.identity:
            previous_ids = {item['id'] for item in json.loads(cache['evidence_json'])}
            if previous_ids.issubset({item['id'] for item in evidence}):
                current = json.loads(cache['result_json'])
                new_evidence = [item for item in evidence if item['id'] not in previous_ids]
        payload = {'current_description': current, 'evidence': new_evidence,
                   'scope': evidence[0]['scope'], 'task': '合并新增资料并保留已有来源ID与原文引用'}
        packed = _json(payload)
        if len(packed) > model.max_input_chars:
            return None, 'input_limit', '相关资料超出单次整理上限，已保留当前说明，可手工修订。', cache
        # UTF-8 bytes provide a conservative token reservation; never charge an estimate as actual usage.
        reserved = len((SYSTEM_PROMPT + packed).encode()) + model.max_output_tokens + 512
        day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
        with database.transaction() as connection:
            spent = connection.execute('SELECT COALESCE(SUM(COALESCE(used_tokens,reserved_tokens)),0) FROM scenario_description_attempts WHERE day=?', (day,)).fetchone()[0]
            if spent + reserved > model.daily_budget:
                return None, 'budget_limit', '已达到每日自动整理 token 预算，保留当前说明。', cache
            attempt = connection.execute('INSERT INTO scenario_description_attempts(context_key,fingerprint,day,reserved_tokens) VALUES (?,?,?,?)', (key, fingerprint, day, reserved)).lastrowid
        usage = {}
        try:
            result, usage = model.generate(payload)
            _validate(result, evidence)
            with database.transaction() as connection:
                connection.execute('''INSERT INTO scenario_description_cache(context_key,project_id,fingerprint,baseline_hash,model,result_json,evidence_json)
                    VALUES (?,?,?,?,?,?,?) ON CONFLICT(context_key) DO UPDATE SET fingerprint=excluded.fingerprint,
                    baseline_hash=excluded.baseline_hash,model=excluded.model,result_json=excluded.result_json,
                    evidence_json=excluded.evidence_json,created_at=CURRENT_TIMESTAMP''',
                    (key, project_id, fingerprint, baseline_hash, model.identity, _json(result), _json(evidence)))
                connection.execute("UPDATE scenario_description_attempts SET status='complete',used_tokens=? WHERE id=?", (_usage(usage), attempt))
            return result, 'ready', '', cache
        except (ValueError, TypeError) as error:
            message = str(error) if isinstance(error, ValueError) else '模型回复格式无效，已保留当前说明。'
            with database.connect() as connection:
                connection.execute("UPDATE scenario_description_attempts SET status='failed',error=?,used_tokens=? WHERE id=?", (message, _usage(usage), attempt))
            return None, 'failed', message, cache


def _usage(usage):
    if not isinstance(usage, dict):
        return None
    total = usage.get('total_tokens')
    return total if type(total) is int and total >= 0 else None


def describe_feature(database, answer, project_id, query, model='', target_version='', section_choice='', generator=None, allow_generation=True):
    if not answer.get('baseline') or not answer.get('section'):
        return None
    context = {'q': _normalize(query), 'model': model or answer.get('models', {}).get('selected', ''),
               'target': target_version, 'section': section_choice, 'document': answer.get('selected_document', '')}
    key = _hash([project_id, context])
    evidence, excluded = _collect(database, answer, query)
    # Duplicate mentions in a new version do not change the semantic input or trigger another model call.
    semantic = sorted([{field: row[field] for field in ('id', 'text', 'scope', 'state', 'complete')} for row in evidence], key=lambda row: row['id'])
    baseline_hash = _hash(evidence[0])
    fingerprint = _hash([_PROMPT_VERSION, generator.identity if generator else '', semantic])
    result, status, error, previous = _generate(database, key, project_id, fingerprint, baseline_hash, evidence, generator, allow_generation)
    if result is None and previous:
        result = json.loads(previous['result_json'])
    automatic_content = _validate(result, json.loads(previous['evidence_json']) if status != 'ready' and previous else evidence) if result else answer['section']['content']
    with database.connect() as connection:
        saved = connection.execute('SELECT * FROM scenario_description_revisions WHERE context_key=? ORDER BY revision DESC LIMIT 1', (key,)).fetchone()
        used = connection.execute('SELECT COALESCE(SUM(used_tokens),0), COUNT(*) FROM scenario_description_attempts WHERE day=?', (datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat(),)).fetchone()
    return {'key': key, 'project_id': project_id, 'context': context, 'source_fingerprint': fingerprint,
            'content': saved['content'] if saved else automatic_content, 'automatic_content': automatic_content,
            'edited': bool(saved), 'revision': saved['revision'] if saved else 0,
            'sources_changed': bool(saved and saved['source_fingerprint'] != fingerprint),
            'status': status, 'error': error, 'evidence': evidence, 'excluded_count': excluded,
            'unresolved': result.get('unresolved', []) if result else [],
            'usage': {'today_tokens': used[0], 'today_requests': used[1]}}


def save_feature_description(database, description, content, expected_revision, source_fingerprint):
    if not description:
        raise ValueError('当前没有可修订的功能说明，请重新查询。')
    if not isinstance(content, str) or not content.strip() or len(content) > 100000:
        raise ValueError('说明不能为空，且不得超过 100000 字。')
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError('修订号无效，请重新查询。')
    if source_fingerprint != description['source_fingerprint']:
        raise ValueError('资料已变化，请重新查询后保存。')
    with database.transaction() as connection:
        latest = connection.execute('SELECT COALESCE(MAX(revision),0) FROM scenario_description_revisions WHERE context_key=?', (description['key'],)).fetchone()[0]
        if latest != expected_revision:
            raise ValueError('已有新的手工修订，请重新查询后再保存。')
        connection.execute('INSERT INTO scenario_description_revisions(context_key,revision,project_id,content,source_fingerprint) VALUES (?,?,?,?,?)',
            (description['key'], latest + 1, description['project_id'], content.strip(), source_fingerprint))
    return {**description, 'content': content.strip(), 'edited': True, 'revision': latest + 1, 'sources_changed': False}

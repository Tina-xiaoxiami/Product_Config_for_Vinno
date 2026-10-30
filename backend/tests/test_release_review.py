from copy import deepcopy
import json

import pytest

from tracker.database import Database
from tracker.services.release_review import (
    ReviewConflict, decorate_release_review, list_release_review_history,
    restore_release_review, save_release_review,
)


@pytest.fixture
def database(tmp_path):
    db = Database(tmp_path / 'review.db')
    db.initialize()
    return db


def answer():
    baseline = {'version': '1.0.0', 'content': 'VATT完整初始说明', 'source_id': 'release:source:1', 'locator': '原文行 1', 'verification': 'unverified'}
    events = [{'version': '1.1.0', 'text': 'VATT新增细节', 'source_id': 'release:change:2', 'locator': '中文记录', 'verification': 'approved', 'operation': 'pending', 'reason': '范围待核对'},
              {'version': '1.2.0', 'text': 'VATT无关说明', 'source_id': 'release:change:3', 'locator': '中文记录', 'verification': 'unverified', 'operation': 'pending', 'reason': '范围待核对'}]
    return {'baseline': baseline, 'content': baseline['content'], 'timeline': [baseline, *deepcopy(events)],
            'applied_changes': [], 'unresolved_changes': events,
            'illustrations': [{'section': {'blocks': [{'type': 'image', 'data_url': 'data:image/png;base64,AAAA'}]}}]}


def payload(decorated, content='人工完整说明', decisions=None):
    return {'revision': decorated['review']['revision'], 'source_fingerprint': decorated['review']['source_fingerprint'],
            'content': content, 'decisions': decisions or []}


def test_save_include_ignore_and_refresh_preserves_original_evolution(database):
    raw = answer()
    initial = decorate_release_review(database, raw, 1, 'VATT')
    ids = [event['id'] for event in initial['unresolved_changes']]
    decisions = [{'id': ids[0], 'action': 'include'}, {'id': ids[1], 'action': 'ignore'}]
    saved = save_release_review(database, raw, 1, 'VATT', '', payload(initial, decisions=decisions))
    assert saved['content'] == '人工完整说明'
    assert saved['automatic_content'] == raw['content']
    assert saved['unresolved_changes'] == []
    assert [event['review_action'] for event in saved['resolved_changes']] == ['include', 'ignore']
    assert saved['timeline'] == raw['timeline']
    assert saved['illustrations'] == raw['illustrations']
    assert saved['review']['revision'] == 1
    reopened = Database(database.path)
    assert decorate_release_review(reopened, answer(), 1, 'VATT')['content'] == saved['content']
    # Decorated inputs retain identical source identity and all original pending rows.
    repeated = decorate_release_review(database, saved, 1, 'VATT')
    assert repeated == saved
    assert raw == answer()
    with database.connect() as connection:
        row = connection.execute('SELECT * FROM scenario_description_revisions').fetchone()
    assert row['context_key'].startswith('release-review-v1:')
    assert [{key: item[key] for key in ('id', 'action')} for item in json.loads(row['content'])['decisions']] == decisions


def test_scope_and_model_summary_namespace_are_isolated(database):
    initial = decorate_release_review(database, answer(), 1, 'VATT')
    save_release_review(database, answer(), 1, 'VATT', '', payload(initial))
    assert decorate_release_review(database, answer(), 1, 'OTHER')['review']['revision'] == 0
    assert decorate_release_review(database, answer(), 1, 'VATT', '1.1.0')['review']['revision'] == 0
    assert decorate_release_review(database, answer(), 2, 'VATT')['review']['revision'] == 0
    with database.transaction() as connection:
        connection.execute('INSERT INTO scenario_description_revisions(context_key,revision,project_id,content,source_fingerprint) VALUES (?,?,?,?,?)',
                           ('old-model-summary-key', 1, 1, '旧大模型摘要', 'old'))
    assert decorate_release_review(database, answer(), 1, 'VATT')['content'] == '人工完整说明'


def test_source_change_preserves_old_revision_but_never_applies_it(database):
    initial = decorate_release_review(database, answer(), 1, 'VATT')
    save_release_review(database, answer(), 1, 'VATT', '', payload(initial))
    changed = answer()
    changed['unresolved_changes'][0]['verification'] = 'unverified'
    current = decorate_release_review(database, changed, 1, 'VATT')
    assert current['review']['stale']
    assert current['review']['content'] == '人工完整说明'
    assert current['content'] == '人工完整说明'
    assert len(current['unresolved_changes']) == 2
    with pytest.raises(ReviewConflict):
        save_release_review(database, changed, 1, 'VATT', '', payload(initial))
    assert list_release_review_history(database, changed, 1, 'VATT')['history'][0]['restorable'] is True
    restored = restore_release_review(database, changed, 1, 'VATT', '', {**payload(current), 'restore_revision': 1})
    assert restored['content'] == '人工完整说明'


def test_compare_and_swap_conflict_and_restore_create_new_revision(database):
    raw = answer()
    initial = decorate_release_review(database, raw, 1, 'VATT')
    first = save_release_review(database, raw, 1, 'VATT', '', payload(initial, '第一稿'))
    with pytest.raises(ReviewConflict):
        save_release_review(database, raw, 1, 'VATT', '', payload(initial, '过期覆盖'))
    second = save_release_review(database, raw, 1, 'VATT', '', payload(first, '第二稿'))
    restored = restore_release_review(database, raw, 1, 'VATT', '', {**payload(second), 'restore_revision': 1})
    assert restored['review']['revision'] == 3
    assert restored['content'] == '第一稿'
    assert [item['content'] for item in list_release_review_history(database, raw, 1, 'VATT')['history']] == ['第一稿', '第二稿', '第一稿', raw['content']]


@pytest.mark.parametrize('decisions', [[{'id': 'unknown', 'action': 'include'}], [{'id': 'known', 'action': 'invalid'}],
                                      [{'id': 'known', 'action': 'ignore'}, {'id': 'known', 'action': 'include'}],
                                      [{'id': 'known', 'action': 'ignore', 'extra': True}], 'invalid'])
def test_invalid_decisions_never_write(database, decisions):
    raw = answer()
    initial = decorate_release_review(database, raw, 1, 'VATT')
    if isinstance(decisions, list):
        decisions = [{**decision, 'id': initial['unresolved_changes'][0]['id'] if decision['id'] == 'known' else decision['id']} for decision in decisions]
    data = payload(initial)
    data['decisions'] = decisions
    with pytest.raises(ValueError):
        save_release_review(database, raw, 1, 'VATT', '', data)
    assert [row['revision'] for row in list_release_review_history(database, raw, 1, 'VATT')['history']] == [0]


def test_image_base64_does_not_invalidate_human_review(database):
    initial = decorate_release_review(database, answer(), 1, 'VATT')
    changed = answer()
    changed['illustrations'][0]['section']['blocks'][0]['data_url'] = 'data:image/png;base64,BBBB'
    assert decorate_release_review(database, changed, 1, 'VATT')['review']['source_fingerprint'] == initial['review']['source_fingerprint']


def test_concurrent_saves_have_only_one_winner(database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    initial = decorate_release_review(database, answer(), 1, 'VATT')
    barrier = Barrier(2)

    def save(content):
        barrier.wait()
        try:
            return save_release_review(Database(database.path), answer(), 1, 'VATT', '', payload(initial, content))['content']
        except ReviewConflict:
            return 'conflict'

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ['first writer', 'second writer']))
    assert results.count('conflict') == 1
    assert [row['revision'] for row in list_release_review_history(database, answer(), 1, 'VATT')['history']] == [1, 0]


def test_restore_body_original_preserves_log_decisions(database):
    raw = answer()
    initial = decorate_release_review(database, raw, 1, 'VATT')
    ignored = save_release_review(database, raw, 1, 'VATT', '', payload(initial, raw['content'], [{'id': initial['unresolved_changes'][0]['id'], 'action': 'ignore'}]))
    saved = save_release_review(database, raw, 1, 'VATT', '', payload(ignored, '人工稿', ignored['review']['decisions']))
    restored = restore_release_review(database, raw, 1, 'VATT', '', {**payload(saved), 'restore_revision': 0})
    assert restored['content'] == raw['baseline']['content']
    assert len(restored['unresolved_changes']) == 1
    assert restored['review']['revision'] == 3
    assert restored['review']['body_revision'] == 2
    assert restored['review']['log_revision'] == 1
    assert [item['revision'] for item in list_release_review_history(database, raw, 1, 'VATT')['history']] == [3, 2, 0]
    assert [item['revision'] for item in list_release_review_history(database, raw, 1, 'VATT', kind='log')['history']] == [1, 0]


def test_system_append_and_adoption_are_log_only_without_body_revision(database):
    raw = answer()
    addition = {'version': '1.3.0', 'source_id': 'release:change:4', 'locator': '中文记录', 'text': '新增支持R²。', 'operation': 'append', 'after': '新增支持R²。', 'verification': 'approved'}
    raw['applied_changes'] = [addition]
    raw['timeline'].append(addition)
    raw['content'] += '\n\n新增支持R²。'
    initial = decorate_release_review(database, raw, 1, 'VATT')
    assert initial['content'] == raw['baseline']['content']
    assert initial['automatic_content'] == raw['content']
    assert initial['applied_changes'] == []
    system = next(item for item in initial['change_log'] if item['origin'] == 'system')
    assert system['log_status'] == 'recognized'
    adopted = save_release_review(database, raw, 1, 'VATT', '', payload(initial, initial['content'], [{'id': system['id'], 'action': 'adopt'}]))
    assert adopted['content'] == raw['baseline']['content']
    assert adopted['review']['body_revision'] == 0
    assert adopted['review']['log_revision'] == 1
    assert [row['revision'] for row in list_release_review_history(database, raw, 1, 'VATT')['history']] == [0]
    assert [row['revision'] for row in list_release_review_history(database, raw, 1, 'VATT', kind='log')['history']] == [1, 0]
    with pytest.raises(ValueError, match='不能同时改写正文'):
        save_release_review(database, raw, 1, 'VATT', '', payload(adopted, '误写正文', [{'id': system['id'], 'action': 'ignore'}]))


def test_include_creates_body_revision_with_event_metadata_and_log_restore_keeps_body(database):
    raw = answer()
    initial = decorate_release_review(database, raw, 1, 'VATT')
    event = initial['unresolved_changes'][0]
    included = save_release_review(database, raw, 1, 'VATT', '', {**payload(initial, '手工修改后的说明', [{'id': event['id'], 'action': 'include'}]),
        'body_change': {'event_id': event['id'], 'operation': 'replace', 'reason': '纳入1.1版本的精确修改'}})
    assert included['review']['body_revision'] == included['review']['log_revision'] == 1
    history = list_release_review_history(database, raw, 1, 'VATT')['history'][0]
    assert history['body_change']['source_version'] == '1.1.0'
    assert history['body_change']['before'] == raw['baseline']['content']
    assert history['body_change']['after'] == '手工修改后的说明'
    restored = restore_release_review(database, raw, 1, 'VATT', '', {**payload(included), 'restore_revision': 0, 'kind': 'log'})
    assert restored['content'] == included['content']
    assert restored['review']['body_revision'] == 1
    assert restored['review']['log_revision'] == 2
    assert not restored['review']['decisions']
    assert len(restored['unresolved_changes']) == 2


def test_new_sources_preserve_body_and_only_unchanged_event_decisions(database):
    raw = answer()
    initial = decorate_release_review(database, raw, 1, 'VATT')
    ids = [row['id'] for row in initial['unresolved_changes']]
    first = save_release_review(database, raw, 1, 'VATT', '', payload(initial, initial['content'], [{'id': ids[0], 'action': 'adopt'}, {'id': ids[1], 'action': 'ignore'}]))
    saved = save_release_review(database, raw, 1, 'VATT', '', payload(first, '保留我的9E标配手工说明', first['review']['decisions']))
    changed = answer()
    changed['unresolved_changes'][1]['verification'] = 'approved'
    changed['unresolved_changes'].append({'version': '1.4.0', 'source_id': 'release:change:5', 'text': '新增变化', 'operation': 'pending'})
    changed['content'] += '\n新的自动拼接内容'
    reopened = decorate_release_review(database, changed, 1, 'VATT')
    assert reopened['content'] == saved['content']
    assert reopened['review']['stale']
    assert reopened['review']['decisions'] == [{'id': ids[0], 'action': 'adopt'}]
    assert reopened['review']['stale_decisions'] == [{'id': ids[1], 'action': 'ignore'}]
    assert len(reopened['unresolved_changes']) == 2
    assert reopened['review']['body_revision'] == 1


def test_v1_migration_keeps_manual_text_removes_only_exact_auto_append_without_writes(database):
    from tracker.services.release_review import _scope
    raw = answer()
    original = raw['baseline']['content']
    addition = {'version': '1.80.0', 'source_id': 'release:change:4', 'locator': '中文记录', 'text': '新增支持R²。', 'operation': 'append', 'after': '新增支持R²。'}
    raw['applied_changes'] = [addition]
    raw['timeline'].append(addition)
    raw['content'] += '\n\n新增支持R²。'
    context, key, fingerprint, events = _scope(raw, 1, 'VATT', '')
    legacy_content = raw['content'] + '\n\n手工兼容性：9E标配，其他机型选配。'
    identity = next(iter(events))
    packed = json.dumps({'schema': 'release-review-v1', 'context': context, 'content': legacy_content,
                         'decisions': [{'id': identity, 'action': 'include'}]}, ensure_ascii=False)
    with database.transaction() as connection:
        connection.execute('INSERT INTO scenario_description_revisions(context_key,revision,project_id,content,source_fingerprint) VALUES (?,?,?,?,?)', (key, 1, 1, packed, fingerprint))
    migrated = decorate_release_review(database, raw, 1, 'VATT')
    assert original in migrated['content']
    assert '手工兼容性：9E标配，其他机型选配。' in migrated['content']
    assert '新增支持R²。' not in migrated['content']
    assert migrated['review']['decisions'] == [{'id': identity, 'action': 'include'}]
    assert not migrated['review']['stale']
    assert '旧版人工正文已兼容保留' in migrated['review']['migration_notice']
    history = list_release_review_history(database, raw, 1, 'VATT')['history'][0]
    assert history['body_change']['source_version'] == '1.1.0'
    assert '兼容关联' in history['body_change']['reason']
    with database.connect() as connection:
        assert connection.execute('SELECT content FROM scenario_description_revisions WHERE context_key=?', (key,)).fetchone()['content'] == packed


def test_v1_migration_never_removes_rewritten_or_inline_handwritten_sentences(database):
    from tracker.services.release_review import _scope
    raw = answer()
    addition = {'version': '1.80.0', 'source_id': 'release:change:4', 'text': '新增支持R²。', 'operation': 'append', 'after': '新增支持R²。'}
    raw['applied_changes'] = [addition]
    _, key, fingerprint, _ = _scope(raw, 1, 'VATT', '')
    handwritten = '手工记录：新增支持R²。仅适用于9E，需额外校准。'
    with database.transaction() as connection:
        connection.execute('INSERT INTO scenario_description_revisions(context_key,revision,project_id,content,source_fingerprint) VALUES (?,?,?,?,?)',
                           (key, 1, 1, json.dumps({'schema': 'release-review-v1', 'content': handwritten, 'decisions': []}), fingerprint))
    assert decorate_release_review(database, raw, 1, 'VATT')['content'] == handwritten


def test_v1_source_fingerprint_algorithm_remains_compatible(database):
    from hashlib import sha256
    from tracker.services.release_review import _FIELDS
    raw = answer()
    addition = {'version': '1.3.0', 'source_id': 'release:change:4', 'text': '新增支持A', 'operation': 'append', 'after': '新增支持A'}
    raw['applied_changes'] = [addition]
    raw['timeline'].append(addition)
    raw['content'] += '\n新增支持A'
    packed = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    fields = lambda value: {key: value.get(key) for key in _FIELDS}
    old_scope = {'context': {'project_id': 1, 'q': 'vatt', 'target': ''}, 'baseline': fields(raw['baseline']),
                 'automatic_content': raw['content'], 'timeline': sorted([fields(row) for row in raw['timeline']], key=packed),
                 'pending': sorted([fields(row) for row in raw['unresolved_changes']], key=packed),
                 'applied': [fields(addition)], 'baseline_gap': None, 'earliest_record_version': None}
    expected = sha256(packed(old_scope).encode()).hexdigest()
    initial = decorate_release_review(database, raw, 1, 'VATT')
    assert initial['review']['source_fingerprint'] == expected
    assert decorate_release_review(database, initial, 1, 'VATT')['review']['source_fingerprint'] == expected


def test_changed_system_event_is_pending_again_and_stale_audit_does_not_block_valid_log_restore(database):
    raw = answer()
    addition = {'version': '1.3.0', 'source_id': 'release:change:4', 'text': '新增支持A', 'operation': 'append', 'after': '新增支持A', 'verification': 'unverified'}
    raw['applied_changes'] = [addition]
    initial = decorate_release_review(database, raw, 1, 'VATT')
    system = next(row for row in initial['change_log'] if row['origin'] == 'system')
    saved = save_release_review(database, raw, 1, 'VATT', '', payload(initial, initial['content'], [{'id': system['id'], 'action': 'adopt'}]))
    changed = deepcopy(raw)
    changed['applied_changes'][0]['verification'] = 'approved'
    current = decorate_release_review(database, changed, 1, 'VATT')
    assert any(row['id'] == system['id'] for row in current['unresolved_changes'])
    assert next(row for row in current['change_log'] if row['id'] == system['id'])['log_status'] == 'pending'
    revised = save_release_review(database, changed, 1, 'VATT', '', payload(current, current['content'], [{'id': system['id'], 'action': 'adopt'}]))
    assert revised['review']['stale_decisions']
    latest_history = list_release_review_history(database, changed, 1, 'VATT', kind='log')['history'][0]
    assert latest_history['restorable']
    restored = restore_release_review(database, changed, 1, 'VATT', '', {**payload(revised), 'restore_revision': latest_history['revision'], 'kind': 'log'})
    assert restored['review']['decisions'] == revised['review']['decisions']


def test_legacy_handwritten_sentence_matching_new_append_is_not_removed(database):
    from tracker.services.release_review import _scope
    original = answer()
    _, key, fingerprint, _ = _scope(original, 1, 'VATT', '')
    hand_sentence = '新增支持R²。'
    old_body = original['baseline']['content'] + '\n\n' + hand_sentence
    packed = json.dumps({'schema': 'release-review-v1', 'content': old_body, 'decisions': []}, ensure_ascii=False)
    with database.transaction() as connection:
        connection.execute('INSERT INTO scenario_description_revisions(context_key,revision,project_id,content,source_fingerprint) VALUES (?,?,?,?,?)',
                           (key, 1, 1, packed, fingerprint))
    newer = answer()
    addition = {'version': '1.90.0', 'source_id': 'release:change:9', 'text': hand_sentence, 'operation': 'append', 'after': hand_sentence}
    newer['applied_changes'] = [addition]
    newer['timeline'].append(addition)
    newer['content'] += '\n\n' + hand_sentence
    result = decorate_release_review(database, newer, 1, 'VATT')
    assert result['content'] == old_body
    assert result['review']['stale']
    assert '缺少旧来源证据' in result['review']['migration_notice']
    with database.connect() as connection:
        assert connection.execute('SELECT content FROM scenario_description_revisions WHERE context_key=?', (key,)).fetchone()['content'] == packed


def test_legacy_append_removed_from_current_source_keeps_body_and_schema2_remains_stable(database):
    from tracker.services.release_review import _scope
    original = answer()
    addition = {'version': '1.80.0', 'source_id': 'release:change:9', 'text': '新增支持R²。', 'operation': 'append', 'after': '新增支持R²。'}
    original['applied_changes'] = [addition]
    original['timeline'].append(addition)
    original['content'] += '\n\n新增支持R²。'
    old_body = original['content'] + '\n\n手工兼容：仅9E标配。'
    _, key, fingerprint, _ = _scope(original, 1, 'VATT', '')
    packed = json.dumps({'schema': 'release-review-v1', 'content': old_body, 'decisions': []}, ensure_ascii=False)
    with database.transaction() as connection:
        connection.execute('INSERT INTO scenario_description_revisions(context_key,revision,project_id,content,source_fingerprint) VALUES (?,?,?,?,?)',
                           (key, 1, 1, packed, fingerprint))
    current = decorate_release_review(database, answer(), 1, 'VATT')
    assert current['content'] == old_body
    assert '未按当前更新日志猜测删除' in current['review']['migration_notice']
    with database.connect() as connection:
        assert connection.execute('SELECT content FROM scenario_description_revisions WHERE context_key=?', (key,)).fetchone()['content'] == packed
    migrated = save_release_review(database, answer(), 1, 'VATT', '', payload(current, current['content']))
    assert migrated['content'] == old_body
    # Even if the old exact source set returns, a stored schema2 body is immutable.
    returned = decorate_release_review(database, original, 1, 'VATT')
    assert returned['content'] == old_body
    assert returned['review']['migration_notice'] == ''


@pytest.mark.parametrize('decision_count,source_changed', [(2, False), (1, True)])
def test_legacy_body_association_requires_unique_include_and_same_sources(database, decision_count, source_changed):
    from tracker.services.release_review import _scope
    raw = answer()
    _, key, fingerprint, events = _scope(raw, 1, 'VATT', '')
    decisions = [{'id': identity, 'action': 'include'} for identity in list(events)[:decision_count]]
    with database.transaction() as connection:
        connection.execute('INSERT INTO scenario_description_revisions(context_key,revision,project_id,content,source_fingerprint) VALUES (?,?,?,?,?)',
                           (key, 1, 1, json.dumps({'schema': 'release-review-v1', 'content': '手工兼容说明', 'decisions': decisions}), fingerprint))
    if source_changed:
        raw['content'] += '\n新来源'
    history = list_release_review_history(database, raw, 1, 'VATT')['history'][0]
    assert history['body_change']['source_version'] is None
    assert 'event_id' not in history['body_change']

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
    assert json.loads(row['content'])['decisions'] == decisions


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
    assert current['content'] == changed['content']
    assert len(current['unresolved_changes']) == 2
    with pytest.raises(ReviewConflict):
        save_release_review(database, changed, 1, 'VATT', '', payload(initial))
    assert list_release_review_history(database, changed, 1, 'VATT')['history'][0]['restorable'] is False
    with pytest.raises(ReviewConflict):
        restore_release_review(database, changed, 1, 'VATT', '', {**payload(current), 'restore_revision': 1})


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


def test_restore_automatic_original_undoes_first_decision_without_erasing_history(database):
    raw = answer()
    initial = decorate_release_review(database, raw, 1, 'VATT')
    saved = save_release_review(database, raw, 1, 'VATT', '', payload(initial, '人工稿', [{'id': initial['unresolved_changes'][0]['id'], 'action': 'ignore'}]))
    restored = restore_release_review(database, raw, 1, 'VATT', '', {**payload(saved), 'restore_revision': 0})
    assert restored['content'] == raw['content']
    assert len(restored['unresolved_changes']) == 2
    assert restored['review']['revision'] == 2
    history = list_release_review_history(database, raw, 1, 'VATT')['history']
    assert [item['revision'] for item in history] == [2, 1, 0]
    assert history[-1]['content'] == raw['content']

from tracker.services.release_evolution import release_evolution_answer


class Data:
    def __init__(self, hits, releases=(), changes=None):
        self.hits, self.releases, self.changes = hits, releases, changes or {}

    def search_release_history(self, query, project_id):
        assert project_id == 1
        return {'results': self.hits}

    def list_releases(self, project_id):
        assert project_id == 1
        return self.releases

    def list_changes(self, release_id):
        return self.changes.get(release_id, [])


def hit(sid, version, **kwargs):
    return {'preview_id': f'release:source:{sid}', 'version': version, **kwargs}


def section(text, title='新增 VATT'):
    return {'title': title, 'complete': True, 'content': text, 'locator': '原文行 12'}


def setup(monkeypatch, sections):
    monkeypatch.setattr('tracker.services.release_evolution.source_sections', lambda db, sid: sections[sid])
    monkeypatch.setattr('tracker.services.release_evolution._release_source_language', lambda db, sid, project: 'cn')


def test_baseline_is_numeric_earliest_and_deduplicates_sources(monkeypatch):
    setup(monkeypatch, {1: [section('测量范围是A。')], 2: [section('新增支持B。')], 3: [section('测量范围是A。')]})
    result = release_evolution_answer(Data([hit(2, '1.10.0'), hit(1, '1.9.0'), hit(3, '1.9.0')]), 1, 'VATT')
    assert result['baseline']['version'] == '1.9.0'
    assert result['content'] == '测量范围是A。\n\n新增支持B。'
    assert result['applied_changes'][0]['operation'] == 'append'
    assert result['applied_changes'][0]['source_id'] == 'release:source:2'
    assert '不等于已证实绝对首次支持' in result['coverage_notice']


def test_precise_amendments_are_applied_in_version_order(monkeypatch):
    setup(monkeypatch, {1: [section('支持A。支持B。')]})
    releases = [{'id': 3, 'version': '1.12.0'}, {'id': 2, 'version': '1.11.0'}]
    changes = {2: [{'id': 20, 'category': 'function', 'title_cn': 'VATT修改', 'description_cn': '将“A”改为“C”', 'review_status': 'approved'}],
               3: [{'id': 30, 'category': 'function', 'title_cn': 'VATT修改', 'description_cn': '删除“支持B。”', 'review_status': 'approved'}]}
    result = release_evolution_answer(Data([hit(1, '1.10.0')], releases, changes), 1, 'VATT')
    assert result['content'] == '支持C。'
    assert [row['operation'] for row in result['applied_changes']] == ['replace', 'delete']
    assert result['applied_changes'][0]['before'] == 'A'
    assert result['applied_changes'][0]['after'] == 'C'


def test_target_bound_and_project_language_rejection(monkeypatch):
    setup(monkeypatch, {1: [section('初始说明')], 2: [section('新增支持B。')], 3: [section('新增支持C。')]})
    monkeypatch.setattr('tracker.services.release_evolution._release_source_language', lambda db, sid, project: 'en' if sid == 3 else 'cn')
    hits = [hit(1, '1.0.0'), hit(2, '1.2.0'), hit(3, '1.1.0'), hit(4, '1.1.0', project_id=2), hit(5, '1.1.0', verification='rejected')]
    answer = release_evolution_answer(Data(hits), 1, 'VATT', '1.1.0')
    assert answer['content'] == '初始说明'
    assert answer['applied_changes'] == []
    assert release_evolution_answer(Data(hits), 1, 'VATT', '0.9.0')['baseline'] is None


def test_ambiguous_modifications_and_unreviewed_records_stay_pending(monkeypatch):
    setup(monkeypatch, {1: [section('A A')], 2: [section('提升了性能。', title='VATT优化')]})
    releases = [{'id': 2, 'version': '1.1.0'}]
    changes = {2: [
        {'id': 1, 'category': 'function', 'title_cn': 'VATT', 'description_cn': '将“A”改为“B”', 'review_status': 'approved'},
        {'id': 2, 'category': 'function', 'title_cn': 'VATT', 'description_cn': '新增支持C。', 'review_status': 'pending'},
        {'id': 3, 'category': 'function', 'title_cn': 'VATT', 'description_cn': '新增支持D。', 'review_status': 'rejected'},
        {'id': 4, 'category': 'config', 'title_cn': 'VATT', 'description_cn': '新增支持E。', 'review_status': 'approved'},
    ]}
    answer = release_evolution_answer(Data([hit(1, '1.0.0'), hit(2, '1.1.0')], releases, changes), 1, 'VATT')
    assert answer['content'] == 'A A'
    assert answer['status'] == 'needs_review'
    assert len(answer['unresolved_changes']) == 3
    assert answer['applied_changes'] == []


def test_same_version_baseline_conflict_does_not_pick_a_source(monkeypatch):
    setup(monkeypatch, {1: [section('A')], 2: [section('B')]})
    answer = release_evolution_answer(Data([hit(1, '1.0.0'), hit(2, '1.0.0')]), 1, 'VATT')
    assert answer['status'] == 'baseline_conflict'
    assert answer['baseline'] is None
    assert len(answer['section_options']) == 2


def test_newer_matching_section_is_not_a_replacement_snapshot(monkeypatch):
    setup(monkeypatch, {1: [section('完整原始描述')], 2: [section('新版本说明并不证明可替代原始段落', title='VATT优化')],
                        3: [section('完整描述更新为：明确替代的新原文', title='VATT说明')]})
    answer = release_evolution_answer(Data([hit(1, '1.0.0'), hit(2, '1.1.0'), hit(3, '1.2.0')]), 1, 'VATT')
    assert answer['content'] == '明确替代的新原文'
    assert answer['applied_changes'][0]['operation'] == 'replace_full'
    assert answer['unresolved_changes'][0]['version'] == '1.1.0'


def test_missing_earlier_full_section_never_claims_complete_evolution(monkeypatch):
    setup(monkeypatch, {1: [section('更晚可读取的完整说明')]})
    hits = [{'preview_id': 'release:change:1', 'version': '1.0.0'}, hit(1, '1.1.0')]
    answer = release_evolution_answer(Data(hits), 1, 'VATT')
    assert answer['earliest_record_version'] == '1.0.0'
    assert answer['baseline_gap']
    assert answer['status'] == 'needs_review'
    assert '不能视为完整演进结果' in answer['coverage_notice']


def test_conflicting_later_sections_block_all_same_version_events(monkeypatch):
    setup(monkeypatch, {1: [section('支持A。')], 2: [section('新增支持B。')], 3: [section('新增支持C。')]})
    changes = {2: [{'id': 20, 'category': 'function', 'title_cn': 'VATT', 'description_cn': '新增支持D。', 'review_status': 'approved'}]}
    answer = release_evolution_answer(Data([hit(1, '1.0.0'), hit(2, '1.1.0'), hit(3, '1.1.0')], [{'id': 2, 'version': '1.1.0'}], changes), 1, 'VATT')
    assert answer['content'] == '支持A。'
    assert not answer['applied_changes']
    assert len(answer['unresolved_changes']) == 3
    assert all('所有变更均待核对' in row['reason'] for row in answer['unresolved_changes'])


def test_same_version_non_additive_edits_never_depend_on_row_order(monkeypatch):
    setup(monkeypatch, {1: [section('支持A。')]})
    changes = [
        {'id': 20, 'category': 'function', 'title_cn': 'VATT', 'description_cn': '将“A”改为“B”', 'review_status': 'approved'},
        {'id': 21, 'category': 'function', 'title_cn': 'VATT', 'description_cn': '将“B”改为“C”', 'review_status': 'approved'},
    ]
    answers = [release_evolution_answer(Data([hit(1, '1.0.0')], [{'id': 2, 'version': '1.1.0'}], {2: order}), 1, 'VATT') for order in [changes, list(reversed(changes))]]
    assert answers[0] == answers[1]
    assert answers[0]['content'] == '支持A。'
    assert len(answers[0]['unresolved_changes']) == 2
    assert not answers[0]['applied_changes']


def test_duplicate_prefixed_and_bare_change_is_applied_once(monkeypatch):
    setup(monkeypatch, {1: [section('支持A。')]})
    changes = [
        {'id': 20, 'category': 'function', 'title_cn': 'VATT', 'description_cn': '将“A”改为“B”', 'review_status': 'approved'},
        {'id': 21, 'category': 'function', 'title_cn': 'VATT', 'description_cn': 'VATT：将“A”改为“B”', 'review_status': 'approved'},
    ]
    answer = release_evolution_answer(Data([hit(1, '1.0.0')], [{'id': 2, 'version': '1.1.0'}], {2: changes}), 1, 'VATT')
    assert answer['content'] == '支持B。'
    assert len(answer['applied_changes']) == 1
    assert not answer['unresolved_changes']


def test_explicit_subject_scoped_additions_preserve_whole_sentences(monkeypatch):
    setup(monkeypatch, {1: [section('VATT原始完整说明')]})
    texts = ['VATT默认增加R²和Depth结果显示；', '剪切波、VATT等功能下Update新增支持开始采集功能；']
    changes = [{'id': 20 + index, 'category': 'function', 'title_cn': 'VATT', 'description_cn': text,
                'review_status': 'approved'} for index, text in enumerate(texts)]
    answer = release_evolution_answer(Data([hit(1, '1.51.70')], [{'id': 2, 'version': '1.51.80'}], {2: changes}), 1, 'VATT')
    assert len(answer['applied_changes']) == 2
    assert all(row['operation'] == 'append' for row in answer['applied_changes'])
    assert not answer['unresolved_changes']
    assert all(text in answer['content'] for text in texts)


def test_addition_recognition_never_absorbs_replacement_deletion_or_bugfix(monkeypatch):
    setup(monkeypatch, {1: [section('VATT原始完整说明')]})
    texts = ['VATT默认增加R²，删除Depth；', '修复VATT默认增加结果时的错误；',
             '剪切波、VATT等功能下Update新增支持后改为手动；', 'VATT默认增加显示，替换原结果；']
    changes = [{'id': 20 + index, 'category': 'function', 'title_cn': 'VATT', 'description_cn': text,
                'review_status': 'approved'} for index, text in enumerate(texts)]
    answer = release_evolution_answer(Data([hit(1, '1.51.70')], [{'id': 2, 'version': '1.51.80'}], {2: changes}), 1, 'VATT')
    assert answer['content'] == 'VATT原始完整说明'
    assert not answer['applied_changes']
    assert len(answer['unresolved_changes']) == len(texts)


def test_baseline_images_are_loaded_once_for_exact_baseline_chapter(monkeypatch):
    calls = []
    base = {**section('VATT基线完整内容'), 'has_images': True, 'source_id': 'release:source:1'}
    later = {**section('VATT后续变化'), 'has_images': True, 'source_id': 'release:source:2'}
    image = {'type': 'image', 'data_url': 'data:image/png;base64,iVBORw0KGgo=', 'locator': '段落 13'}

    def read(db, sid, *, image_locator=''):
        calls.append((sid, image_locator))
        if image_locator:
            assert sid == 1
            assert image_locator == base['locator']
            return [{**base, 'images_complete': True, 'blocks': [image]}]
        return [base if sid == 1 else later]

    monkeypatch.setattr('tracker.services.release_evolution.source_sections', read)
    monkeypatch.setattr('tracker.services.release_evolution._release_source_language', lambda *args: 'cn')
    answer = release_evolution_answer(Data([hit(1, '1.0.0'), hit(2, '1.1.0')]), 1, 'VATT')
    assert answer['baseline']['section']['blocks'] == [image]
    assert answer['baseline']['section']['images_complete']
    assert answer['content'] == base['content']
    assert [call for call in calls if call[1]] == [(1, base['locator'])]


def test_unavailable_or_mismatched_image_source_does_not_change_text(monkeypatch):
    base = {**section('VATT原文说明'), 'has_images': True, 'source_id': 'release:source:1'}
    monkeypatch.setattr('tracker.services.release_evolution._release_source_language', lambda *args: 'cn')
    for bad in [[], [{**base, 'content': '原文件已经变化'}], [{**base, 'locator': '原文行 99'}],
                [{**base, 'source_id': 'release:source:2'}]]:
        def read(db, sid, *, image_locator=''):
            return bad if image_locator else [base]
        monkeypatch.setattr('tracker.services.release_evolution.source_sections', read)
        answer = release_evolution_answer(Data([hit(1, '1.0.0')]), 1, 'VATT')
        assert answer['content'] == base['content']
        assert answer['baseline']['section']['has_images']
        assert not answer['baseline']['section']['images_complete']
        assert not any(block['type'] == 'image' for block in answer['baseline']['section']['blocks'])


def test_unsupported_baseline_images_keep_unavailable_marker(monkeypatch):
    base = {**section('VATT原文说明'), 'has_images': True, 'source_id': 'release:source:1'}
    block = {'type': 'image', 'unavailable': True, 'locator': '段落 13'}
    monkeypatch.setattr('tracker.services.release_evolution.source_sections',
                        lambda db, sid, *, image_locator='': [{**base, 'images_complete': False, 'blocks': [block]}] if image_locator else [base])
    monkeypatch.setattr('tracker.services.release_evolution._release_source_language', lambda *args: 'cn')
    answer = release_evolution_answer(Data([hit(1, '1.0.0')]), 1, 'VATT')
    assert answer['baseline']['section']['blocks'] == [block]
    assert not answer['baseline']['section']['images_complete']
    assert answer['content'] == base['content']

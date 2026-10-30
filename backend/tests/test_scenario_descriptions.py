import pytest

from tracker.database import Database


@pytest.fixture
def database(tmp_path):
    db = Database(tmp_path / 'descriptions.db')
    db.initialize()
    return db


def answer(changes=None):
    return {'selected_document': 'document:cn', 'models': {'selected': 'model:6s'},
            'baseline': {'version': '1.51.80', 'detail_evidence': {
                'source_id': 'controlled:1:docx', 'scope': '国内 · 6S'}},
            'section': {'content': 'VAid Liver 肝脏自动检测分析\n实时检测病灶，冻结后自动测量。', 'locator': '5.23'},
            'later_changes': changes or []}


def describe(db, data=None, **kwargs):
    from tracker.services.scenario_descriptions import describe_feature
    return describe_feature(db, data or answer(), 1, 'VAid Liver', **kwargs)


def save(db, description, content='手工补充后的说明'):
    from tracker.services.scenario_descriptions import save_feature_description
    return save_feature_description(db, description, content, description['revision'], description['source_fingerprint'])


def test_default_automatically_combines_baseline_and_deduplicated_later_changes(database):
    change = {'version': '1.51.81', 'category': 'function', 'review_status': 'approved',
              'description_cn': 'VAid Liver 支持腹部精细应用', 'preview_id': 'release:change:99'}
    second = {**change, 'version': '1.51.82', 'preview_id': 'release:change:100'}
    description = describe(database, answer([second, change]))
    assert '实时检测病灶' in description['content']
    assert description['content'].count('VAid Liver 支持腹部精细应用') == 1
    assert '1.51.81' in description['content'] and '1.51.82' in description['content']
    assert description['content'] == description['automatic_content']
    assert description['edited'] is False


def test_manual_revision_survives_reopen_and_new_evidence(database):
    original = describe(database)
    saved = save(database, original)
    assert saved['revision'] == 1
    reopened = Database(database.path)
    reopened.initialize()
    changed = answer([{'version': '1.51.82', 'description_cn': 'VAid Liver 新增应用', 'category': 'function'}])
    result = describe(reopened, changed)
    assert result['content'] == '手工补充后的说明'
    assert result['edited'] and result['sources_changed']
    assert '新增应用' in result['automatic_content']


def test_revision_scope_isolated_by_document_model_target_and_query(database):
    save(database, describe(database))
    data = answer()
    data['selected_document'] = 'document:en'
    assert not describe(database, data)['edited']
    assert not describe(database, model='model:other')['edited']
    assert not describe(database, target_version='1.51.81')['edited']
    from tracker.services.scenario_descriptions import describe_feature
    assert not describe_feature(database, answer(), 1, 'VAid Kidney')['edited']
    assert describe_feature(database, answer(), 1, '  vaid   liver  ')['edited']


def test_saves_detect_stale_revision_and_source_changes(database):
    from tracker.services.scenario_descriptions import save_feature_description
    original = describe(database)
    save(database, original)
    with pytest.raises(ValueError, match='修订'):
        save(database, original, '另一个窗口的旧稿')
    current = describe(database)
    with pytest.raises(ValueError, match='资料'):
        save_feature_description(database, current, '新稿', current['revision'], 'old-fingerprint')
    assert describe(database)['content'] == '手工补充后的说明'


@pytest.mark.parametrize('content', ['', '  ', None, 123, 'x' * 100001], ids=['empty', 'whitespace', 'null', 'number', 'oversized'])
def test_invalid_content_never_overwrites_revision(database, content):
    with pytest.raises(ValueError):
        save(database, describe(database), content)
    assert not describe(database)['edited']


def test_different_language_not_folded_into_domestic_description(database):
    changes = [
        {'version': '1.51.81', 'category': 'source', 'locator': 'English record',
         'matched_text': 'VAid Liver Abd General applications', 'title_en': 'English Release Note'},
        {'version': '1.51.81', 'category': 'config', 'description_cn': 'VAid Liver 支持腹部精细应用'},
    ]
    result = describe(database, answer(changes))
    assert 'Abd General' not in result['automatic_content']
    assert '腹部精细' in result['automatic_content']
    assert result['excluded_count'] == 1


def test_snapshot_reads_complete_record_instead_of_truncated_search_excerpt(database):
    rid = database.upsert_release('1.51.81')
    database.stage_release_pair(rid, [{'path': '/readonly/cn.docx', 'language': 'cn', 'sha256': 'test',
        'content': '平台说明\nVAid Liver 支持腹部常规、腹部穿透、腹部精细应用，不支持测试探头。\nVAid HRI 其他功能'}], [], [])
    with database.connect() as connection:
        sid = connection.execute('SELECT id FROM source_documents WHERE release_id=?', (rid,)).fetchone()[0]
    change = {'version': '1.51.81', 'category': 'source', 'evidence_type': 'clue',
              'preview_id': f'release:source:{sid}', 'locator': '原文行 2', 'matched_text': '...VAid Liver 支持腹部常规...'}
    result = describe(database, answer([change]))
    assert '不支持测试探头' in result['automatic_content']
    assert 'VAid HRI' not in result['automatic_content']
    assert '原文提及' in result['automatic_content']


def test_no_verified_baseline_has_no_generated_description(database):
    data = answer()
    data['baseline'] = None
    assert describe(database, data) is None


def test_source_order_does_not_make_revision_appear_outdated(database):
    changes = [{'version': '1.51.81', 'description_cn': text, 'category': 'function'}
               for text in ['VAid Liver 应用甲', 'VAid Liver 应用乙']]
    first = describe(database, answer(changes))
    save(database, first)
    assert not describe(database, answer(list(reversed(changes))))['sources_changed']

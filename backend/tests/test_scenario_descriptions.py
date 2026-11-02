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


class FakeModel:
    configured = True
    identity = 'test/model'
    daily_budget = 100000
    max_input_chars = 16000
    max_output_tokens = 2500

    def __init__(self):
        self.calls = []

    def generate(self, payload):
        self.calls.append(payload)
        old = payload.get('current_description') or {'paragraphs': []}
        paragraphs = list(old['paragraphs'])
        paragraphs.extend({'text': row['text'] + ('（原文提及）' if '原文提及' in row['state'] else ''),
            'citations': [{'id': row['id'], 'quote': row['text'][:120]}]} for row in payload['evidence'] if row.get('complete', True))
        return {'paragraphs': paragraphs, 'unresolved': []}, {'total_tokens': 120}


def describe(db, data=None, **kwargs):
    from tracker.services.scenario_descriptions import describe_feature
    return describe_feature(db, data or answer(), 1, 'VAid Liver', generator=kwargs.pop('generator', FakeModel()), **kwargs)


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
    assert description['evidence'][1]['versions'] == ['1.51.81', '1.51.82']
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
    assert describe_feature(database, answer(), 1, '  vaid   liver  ', generator=FakeModel())['edited']


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
    assert '不支持测试探头' in result['evidence'][1]['text']
    assert result['evidence'][1]['complete'] is False
    assert '原文提及' in result['evidence'][1]['state']


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


def test_model_cache_and_incremental_prompt_avoid_repeated_tokens(database):
    generator = FakeModel()
    first = describe(database, generator=generator)
    assert first['status'] == 'ready'
    describe(database, generator=generator)
    assert len(generator.calls) == 1
    changes = [{'version': '1.51.81', 'description_cn': 'VAid Liver 新增腹部精细应用', 'category': 'function'}]
    describe(database, answer(changes), generator=generator)
    assert len(generator.calls) == 2
    payload = generator.calls[1]
    assert payload['current_description']
    assert [row['text'] for row in payload['evidence']] == ['VAid Liver 新增腹部精细应用']
    describe(database, answer(changes + [{**changes[0], 'version': '1.51.82'}]), generator=generator)
    assert len(generator.calls) == 2


def test_invalid_model_citations_preserve_last_good_description_and_cool_down(database):
    generator = FakeModel()
    good = describe(database, generator=generator)
    def bad(payload):
        generator.calls.append(payload)
        return {'paragraphs': [{'text': '未证实的支持结论', 'citations': [{'id': 'unknown', 'quote': '捏造引用'}]}]}, {'total_tokens': 30}
    generator.generate = bad
    changed = answer([{'version': '1.51.81', 'category': 'function', 'description_cn': 'VAid Liver 新增应用'}])
    result = describe(database, changed, generator=generator)
    assert result['status'] == 'failed'
    assert result['content'] == good['content']
    assert '逐字原文校验' in result['error']
    describe(database, changed, generator=generator)
    assert len(generator.calls) == 2


def test_budget_and_unconfigured_provider_do_not_call_model(database):
    generator = FakeModel()
    generator.daily_budget = 0
    assert describe(database, generator=generator)['status'] == 'budget_limit'
    assert generator.calls == []
    generator.configured = False
    assert describe(database, generator=generator)['status'] == 'unconfigured'


def test_changed_or_removed_evidence_forces_complete_regeneration(database):
    generator = FakeModel()
    changes = [{'version': '1.51.81', 'category': 'function', 'description_cn': 'VAid Liver 新增应用'}]
    describe(database, answer(changes), generator=generator)
    changes[0]['description_cn'] = 'VAid Liver 修改支持范围'
    describe(database, answer(changes), generator=generator)
    assert generator.calls[-1]['current_description'] is None
    assert generator.calls[-1]['evidence'][0]['id'] == 'baseline'


def test_incomplete_snapshot_keeps_multiline_scope_but_cannot_be_promoted_to_fact(database):
    rid = database.upsert_release('1.51.81')
    database.stage_release_pair(rid, [{'path':'/readonly/multiline.docx','language':'cn','sha256':'multiline',
        'content':'仅支持MLP平台，不适用于6S。\nVAid Liver 新增腹部精细应用。\n仅支持BP4-9，不支持X4-12L。'}], [], [])
    with database.connect() as sql:
        sid = sql.execute('SELECT id FROM source_documents WHERE release_id=?',(rid,)).fetchone()[0]
    data = answer([{'version':'1.51.81','category':'source','preview_id':f'release:source:{sid}', 'locator':'原文行 2'}])
    result = describe(database, data)
    context = result['evidence'][1]
    assert '不适用于6S' in context['text'] and '不支持X4-12L' in context['text']
    assert context['complete'] is False
    from tracker.services.scenario_descriptions import _validate
    with pytest.raises(ValueError, match='原文校验'):
        _validate({'paragraphs':[{'text':'6S支持腹部精细应用','citations':[{'id':context['id'],'quote':'VAid Liver 新增腹部精细应用。'}]}]}, result['evidence'])

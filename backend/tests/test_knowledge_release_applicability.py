"""Source-written applicability is a fact, not an unfilled manual approval."""
from contextlib import closing
import sqlite3
import pytest
from app.services.knowledge_release_applicability import extract_source_applicability, model_facts
from test_knowledge_release_history import database, _client, _document, _trace, SCOPE

POC = '''1.14.40(VINNO 5EXP/6/8 POC)
Release Note
前言
POC机型首次发放，包括 V5 EXP(V10920),V6(V10921),V8(V10922)三款机型。
与目前已发布的 V5 EXP(V10920),V6(V10116),V8(V10019)相比，有以下改变。
注意，该版本不支持已发布的 V5 EXP(V10920),V6(V10116),V8(V10019)
机器的升级。'''
LUCID = '''1.14.61(VINNO 6/6PRO/6EXP/5EXP)
Release Note
注意：此次更新涉及硬件更新，故不支持已发货机器的升级！
升级为 VLucid+平台，内存升级。
V6更新为综合版配置；新增V6S和V5S机型发放，用于POC市场。'''
NEXT = '''1.14.65(VINNO 3/5/6 系列)
Release Note
注意：针对V3和V5系列来说，此次更新涉及硬件更新，故不支持已发货机器的升级！
升级为VLucid+平台，内存升级。
另外，本版本同样适用于V6系列的VLucid+平台，即支持从1.14.61版本进行升级。'''


def extract(content, version='1.14.65'):
    document = {'id': 500, 'version': version, 'title': 'Release Note', 'country': None, 'market': 'unspecified'}
    chunks = [{'content': content, 'source_ref': '第3页', 'page_number': 3}]
    return extract_source_applicability(document, chunks)


def test_source_models_versions_and_poc_identity_do_not_include_comparison_as_new_hardware():
    facts = extract(POC, '1.14.40')
    assert facts['version']['value'] == '1.14.40'
    assert {'VINNO 5EXP', 'VINNO 6', 'VINNO 8'} <= {x['name'] for x in facts['models']}
    profile = next(x for x in model_facts(facts, 'VINNO 6')['profiles'] if x['name'] == 'POC')
    assert profile['v_codes'] == ['V10921']
    restriction = model_facts(facts, 'VINNO 6')['restrictions'][0]
    assert 'V10116' in restriction['excluded_v_codes']
    assert 'V10921' not in restriction['excluded_v_codes']
    assert facts['country']['status'] == 'not_stated'
    assert facts['field_evidence'] and all(x['source_ref'] for x in facts['field_evidence'])


def test_model_specific_restriction_is_not_generalized_from_v3_v5_to_v6():
    facts = extract(NEXT)
    six = model_facts(facts, 'VINNO 6')
    assert not six['restrictions']
    assert six['profiles'][0]['name'] == 'VLucid+'
    assert six['upgrades'][0]['from_version'] == '1.14.61'
    assert six['upgrades'][0]['to_version'] == '1.14.65'
    assert model_facts(facts, 'VINNO 3')['restrictions']
    assert not model_facts(facts, 'VINNO 6PRO')['applicable']


def test_new_declared_models_and_existing_series_are_not_guessed_from_plain_mentions():
    facts = extract(LUCID, '1.14.61')
    assert {'VINNO 6S', 'VINNO 5S'} <= {x['name'] for x in facts['models']}
    assert model_facts(facts, 'VINNO 6PRO')['restrictions']
    insufficient = extract('1.14.65\n与旧V6相比，功能不变。')
    assert not insufficient['models']
    conflict = extract('1.14.61(VINNO 6)\nRelease Note', '1.14.65')
    assert conflict['status'] == 'conflict'
    assert conflict['issues'][0]['field'] == 'version'


@pytest.mark.asyncio
async def test_explicit_source_facts_are_traced_without_country_or_manual_bindings(database):
    for doc_id, version, content in [(1, '1.14.40', POC), (2, '1.14.61', LUCID), (3, '1.14.65', NEXT)]:
        _document(database, doc_id, version, content, country=None, market='unspecified')
    client, engine = await _client(database)
    before = database.read_bytes()
    async with client:
        result = await _trace(client, scope={**SCOPE, 'country': None})
        assert result['assessment'] == 'no_record'
        assert result['coverage']['document_count'] == 3
        assert result['coverage']['versions'] == ['1.14.40', '1.14.61', '1.14.65']
        assert not result['coverage']['unresolved_documents']
        assert result['confirmation_items'] == []
        assert len(result['source_documents']) == 3
        assert all(x['source_applicability']['provenance'] == 'source_extract' for x in result['source_documents'])
        lucid = next(x for x in result['chains'] if 'VLucid+' in x['release_line'])
        assert {x['version'] for x in lucid['documents']} == {'1.14.61', '1.14.65'}
        assert not any('针对V3' in x['excerpt'] for x in lucid['detected_conditions'])
        decision = await _trace(client, query='这台旧V6能升级吗？', scope={**SCOPE, 'country': None})
        assert len(decision['confirmation_items']) == 1
        item = decision['confirmation_items'][0]
        assert item['field'] == 'device_hardware' and item['evidence_refs']
        assert any('V10921' in option for option in item['options'])
    assert database.read_bytes() == before
    await engine.dispose()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute('SELECT count(*) FROM knowledge_release_bindings').fetchone()[0] == 0


@pytest.mark.asyncio
async def test_original_country_conflicts_and_stale_sources_remain_excluded(database):
    _document(database, 1, '1.14.40', POC, country='US', market='overseas')
    _document(database, 2, '1.14.61', LUCID, country=None, market='unspecified')
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE knowledge_document_extractions SET status='stale' WHERE document_id=2")
    client, engine = await _client(database)
    async with client:
        result = await _trace(client)
        assert result['coverage']['document_count'] == 0
        assert not result['source_documents']
    await engine.dispose()


def test_comparison_model_is_not_a_positive_declaration():
    facts = extract('Release Note 1.14.65\n本版本适用于V5，与V6相比，性能有所提升。')
    assert {row['name'] for row in facts['models']} == {'VINNO 5'}
    assert not model_facts(facts, 'VINNO 6')['applicable']


def test_different_model_upgrade_after_contrast_is_not_lost_or_prohibited():
    facts = extract('1.14.65(VINNO 3/5/6 系列)\nRelease Note\n不支持已发货V3和V5机器升级，但V6的VLucid+平台支持从1.14.61版本进行升级。')
    assert not model_facts(facts, 'VINNO 6')['restrictions']
    assert model_facts(facts, 'VINNO 6')['upgrades'][0]['from_version'] == '1.14.61'
    assert model_facts(facts, 'VINNO 3')['restrictions']


def test_source_field_evidence_assigns_each_product_vcode_to_its_model():
    facts = extract(POC, '1.14.40')
    profile = next(row for row in facts['field_evidence'] if row['field'] == 'profiles')
    assert 'VINNO 6 POC：V10921' in profile['value']
    assert 'VINNO 8 POC：V10922' in profile['value']


@pytest.mark.asyncio
async def test_body_version_is_used_when_registration_version_is_missing(database):
    _document(database, 1, '1.14.40', POC, country=None, market='unspecified')
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute('UPDATE knowledge_documents SET version=NULL WHERE id=1')
    client, engine = await _client(database)
    async with client:
        result = await _trace(client)
        assert result['coverage']['versions'] == ['1.14.40']
        assert result['source_documents'][0]['source_applicability']['version']['value'] == '1.14.40'
    await engine.dispose()

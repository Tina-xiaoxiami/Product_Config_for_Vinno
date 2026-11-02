"""Latest unified notes declare their product scope in the overview, not the brand cover."""
from contextlib import closing
import sqlite3
import pytest
from app.services.knowledge_release_applicability import extract_source_applicability, model_facts, source_chain_groups
from test_knowledge_release_history import database, _client, _document, _trace, SCOPE

CN80 = '''1.14.80(VINNO 系列)
Release Note
此版本为 V 系列合并版本,支持 VLucid+平台 V5、V6、V10 系列产品。
V5/6 系列(原1.14.X版本)支持patch升级;
V10系列支持OS升级(如不需要支持新打印机和网卡,也可以用patch升级)。
注:此次版本不适用于老V5、V6、V8机器(版本为1.12.X)。'''
CN81 = '''1.14.81(VINNO 系列)
Release Note
此版本为V系列合并版本,支持VLucid+平台V5、V6、V10系列产品。
注:适用于1.14.X版本升级,升级方式为OS。
修复V10系列默认UI布局下，缺少针增益和自动穿刺增强按钮的问题。'''
EN81 = '''1.14.81 (VINNO10/6/5 series)
Release Note
This is a unified release for the V series, supporting V5, V6 and V10 series products based on the VLucid+ platform.
Note: Supports upgrades from version 1.14.X via an OS upgrade.
Fixed missing needle gain and Auto Needle buttons in the default UI layout on V10 series systems.'''


def facts(content, version):
    return extract_source_applicability({'id': 88, 'version': version, 'country': None, 'market': 'unspecified'},
        [{'content': content, 'source_ref': '第3页', 'page_number': 3}])


@pytest.mark.parametrize('content,version', [(CN80,'1.14.80'), (CN81,'1.14.81'), (EN81,'1.14.81')])
def test_unified_release_overview_declares_models_and_platform_after_brand_only_cover(content, version):
    result = facts(content, version)
    assert result['status'] == 'extracted'
    assert result['version']['value'] == version
    assert {'VINNO 5', 'VINNO 6', 'VINNO 10'} <= {row['name'] for row in result['models']}
    six = model_facts(result, 'VINNO 6')
    assert six['applicable'] and any(profile['name'] == 'VLucid+' for profile in six['profiles'])
    assert result['country']['status'] == result['market']['status'] == 'not_stated'


@pytest.mark.parametrize('content', [CN81, EN81])
def test_wildcard_upgrade_source_remains_literal_with_method_and_never_connects_numeric_versions(content):
    result = facts(content, '1.14.81')
    upgrade = model_facts(result, 'VINNO 6')['upgrades'][0]
    assert upgrade['from_version'] == '1.14.X'
    assert upgrade['from_version_kind'] == 'pattern'
    assert upgrade['method'] == 'OS'
    source = facts('1.14.65(VINNO 6)\nRelease Note\n升级为VLucid+平台。', '1.14.65')
    groups = source_chain_groups([{'document': {'id':1,'version':'1.14.65'},'facts':source},
        {'document': {'id':2,'version':'1.14.81'},'facts':result}], 'VINNO 6')
    assert groups[1] != groups[2]
    assert any('1.14.X' in row['value'] and 'OS' in row['value'] for row in result['field_evidence'] if row['field']=='upgrades')


def test_legacy_hardware_range_does_not_exclude_all_v6_and_function_support_is_not_release_applicability():
    six = model_facts(facts(CN80, '1.14.80'), 'VINNO 6')
    assert six['applicable'] and not six['explicitly_excluded']
    legacy = next(row for row in six['restrictions'] if row['kind']=='source_version_hardware_exclusion')
    assert legacy['source_version_pattern'] == '1.12.X' and legacy['hardware_label'] == '旧机器'
    scoped = facts('1.14.81(VINNO 系列)\nRelease Note\n自动测量功能支持V6。', '1.14.81')
    assert not model_facts(scoped, 'VINNO 6')['applicable']


@pytest.mark.asyncio
async def test_latest_button_fixes_remain_v10_events_not_v6_additions(database):
    _document(database, 5, '1.14.80', CN80, country=None, market='unspecified')
    _document(database, 6, '1.14.81', CN81, country=None, market='unspecified')
    _document(database, 7, '1.14.81', EN81, country=None, market='unspecified')
    client, engine = await _client(database)
    async with client:
        six = await _trace(client, query='针增益调节', scope={**SCOPE,'software_version':'1.14.81'})
        assert {5,6,7} <= {row['document_id'] for row in six['source_documents']}
        assert not six['events'] and six['assessment']=='no_record'
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("UPDATE product_models SET name='VINNO 10' WHERE id=902")
        for query,expected in [('针增益调节',6),('针增益调节',7)]:
            ten = await _trace(client, query=query, scope={**SCOPE,'product_model_id':902,'software_version':'1.14.81'})
            event = next(row for row in ten['events'] if row['document_id']==expected)
            assert event['change_type'] in ('fixed','optimized')
            assert event['change_type']!='added'
    await engine.dispose()


def test_child_gain_aliases_share_existing_query_forms_without_aliasing_parent_feature():
    from app.services.knowledge_content import _query_forms
    forms = _query_forms('针增益调节')
    assert '针增益' in forms and 'needlegain' in forms
    assert '穿刺增强' not in forms


def test_english_combined_upgrade_methods_are_preserved_without_selecting_one():
    content = '''1.14.80 (VINNO10/6/5 series)
Release Note
This version is a consolidated V Series release, supporting VLucid+ platform V5, V6, and V10 series products.
V5/6 series (original version 1.14.X): Supports patch & OS upgrade (If you do not need to support the Slovak input method, you can choose the patch upgrade).'''
    upgrade = model_facts(facts(content,'1.14.80'),'VINNO 6')['upgrades'][0]
    assert upgrade['methods'] == ['patch','OS']
    assert upgrade['method'] is None
    assert upgrade['from_version'] == '1.14.X'


def test_upgrade_paragraphs_do_not_lend_a_source_version_to_a_different_model():
    content = '''1.14.80 (VINNO10/6/5 series)
Release Note
This version is a consolidated V Series release, supporting VLucid+ platform V5, V6, and V10 series products.
V5/6 series (original version 1.14.X): Supports patch & OS upgrade (If you do not
need to support the Slovak input method, you can choose the patch upgrade)
V10 series: Supports patch & OS upgrade (If you do not need to support new printers,
Bluetooth, and the Slovak input method, you can choose the patch upgrade)'''
    result = facts(content, '1.14.80')
    six = model_facts(result,'VINNO 6')['upgrades']
    ten = model_facts(result,'VINNO 10')['upgrades']
    assert six[0]['from_version'] == '1.14.X' and six[0]['methods']==['patch','OS']
    assert ten[0]['from_version'] is None and ten[0]['from_version_kind']=='not_stated'
    assert ten[0]['methods']==['patch','OS']
    cn_ten = model_facts(facts(CN80,'1.14.80'),'VINNO 10')['upgrades'][0]
    assert cn_ten['methods']==['OS','patch'] and cn_ten['from_version'] is None


def test_upgrade_note_is_not_assigned_to_the_following_configuration_section_model():
    content = EN81.replace('Fixed missing needle gain and Auto Needle buttons in the default UI layout on V10 series systems.',
        '2. Configuration changes\nV10 Probes change list:\nProbe Vcode V10\nS1-6PE V20086 Added\nBP4-9 V20129 Changed from ∆ to support.')
    result = facts(content, '1.14.81')
    upgrade = model_facts(result, 'VINNO 6')['upgrades'][0]
    assert upgrade['from_version']=='1.14.X' and upgrade['methods']==['OS']
    assert 'Probes change list' not in upgrade['excerpt']


@pytest.mark.parametrize('statement', [
    '自动测量功能适用于V6。',
    '本版本的自动测量功能适用于V6。',
    '本版本适用于V6的自动测量功能。',
    '自动测量功能适用型号：V6。',
])
def test_function_applicability_does_not_complete_brand_cover_release_scope(statement):
    result = facts('1.14.81(VINNO 系列)\nRelease Note\n' + statement, '1.14.81')
    assert not model_facts(result, 'VINNO 6')['applicable']
    assert result['models'] == []


@pytest.mark.parametrize('statement', ['本版本适用于V6。', '本版本同样适用于V6系列的VLucid+平台。', '适用型号：VINNO 6。'])
def test_explicit_release_subject_or_model_field_still_completes_brand_cover(statement):
    result = facts('1.14.81(VINNO 系列)\nRelease Note\n' + statement, '1.14.81')
    assert model_facts(result, 'VINNO 6')['applicable']

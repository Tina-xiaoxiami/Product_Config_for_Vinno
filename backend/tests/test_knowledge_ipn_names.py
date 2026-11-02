"""IPN-bound current names are a display projection, never a content migration."""

from contextlib import closing
import sqlite3

import pytest

from test_knowledge_api import _create_knowledge_database, _client_for as feature_client
from test_knowledge_qa_api import _create_qa_database, _client_for
from app.services.knowledge_qa import normalize_question

SCOPE = {"country": "CN", "market": "domestic", "product_model_id": 901, "software_version": "1.14.80"}


def _database(path):
    _create_qa_database(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript("""
        CREATE TABLE config_items(id INTEGER PRIMARY KEY,ipn TEXT,rd_name TEXT,zh_desc TEXT,en_desc TEXT);
        INSERT INTO config_items VALUES
          (1,'6000317','Pleura','胸膜自动测量','Pleural measurement'),
          (2,'3201201','Storage','DICOM3.0基础功能','DICOM storage'),
          (3,'3201203','Network','DICOM3.0接口','DICOM network'),
          (4,'6000393','LVStudy','LV Study自动测量(2D)','LV Study'),
          (5,'6000018','Elastic','Elastic imaging压力式弹性成像','Elastic imaging');
        """)
        for qid, question, answer in [
            (1, '胸膜自动识别在V10系列是标配吗？', '结论：胸膜自动识别（IPN 6000317）为选配。'),
            (2, 'DICOM3.0基础功能的配置？', '结论：DICOM3.0基础功能（IPN 3201201）为标配。该功能不等同于DICOM接口包（IPN 3201203）。'),
            (3, 'LV Study自动测量在V10系列是标配吗？', '结论：LV Study自动测量(2D)（IPN 6000393）为选配。'),
            (4, '版本发布了什么？', '新增胸膜自动识别。'),
            (5, '压力式弹性成像如何配置？', '结论：压力式弹性成像（IPN 6000018）为选配。'),
        ]:
            connection.execute('INSERT INTO knowledge_questions(id,question_text,normalized_question,status) VALUES(?,?,?,\'answered\')', (qid, question, normalize_question(question)))
            connection.execute('INSERT INTO knowledge_answers(id,question_id,answer_text) VALUES(?,?,?)', (qid, qid, answer))
        connection.execute("INSERT INTO knowledge_question_phrasings(question_id,phrasing_text,normalized_phrasing,phrasing_type) VALUES(1,'旧胸膜功能怎么配','旧胸膜功能怎么配','observed')")


@pytest.mark.asyncio
async def test_current_names_are_projected_but_stored_question_answer_and_versions_stay_raw(tmp_path):
    path = tmp_path / 'qa.db'; _database(path)
    client, engine = await _client_for(path)
    before = path.read_bytes()
    async with client:
        first = (await client.get('/api/knowledge/questions/1')).json()
        dicom = (await client.get('/api/knowledge/questions/2')).json()
        lv = (await client.get('/api/knowledge/questions/3')).json()
        release = (await client.get('/api/knowledge/questions/4')).json()
        elastic = (await client.get('/api/knowledge/questions/5')).json()
    await engine.dispose()
    assert first['display_question_text'] == '胸膜自动测量在V10系列是标配吗？'
    assert '胸膜自动测量（IPN 6000317）' in first['answer']['display_answer_text']
    assert '胸膜自动识别' in first['answer']['answer_text']
    assert first['question_text'].startswith('胸膜自动识别') and first['answer']['version'] == 1
    assert '不等同于DICOM3.0接口（IPN 3201203）' in dicom['answer']['display_answer_text']
    assert lv['display_question_text'] == 'LV Study自动测量(2D)在V10系列是标配吗？'
    assert release['answer']['display_answer_text'] == '新增胸膜自动测量。'
    assert elastic['answer']['display_answer_text'].count('Elastic imaging') == 1
    assert path.read_bytes() == before


@pytest.mark.asyncio
async def test_search_matches_current_historical_observed_and_ipn_before_pagination(tmp_path):
    path = tmp_path / 'qa.db'; _database(path)
    client, engine = await _client_for(path)
    async with client:
        for query, total in [('胸膜自动测量', 2), ('胸膜自动识别', 2), ('旧胸膜功能', 1), ('3201203', 1)]:
            first = (await client.get('/api/knowledge/questions', params={'q':query,'limit':1})).json()
            assert first['total'] == total, (query, first)
            assert len(first['items']) == 1
            last = (await client.get('/api/knowledge/questions', params={'q':query,'skip':1,'limit':1})).json()
            assert last['total'] == total
            assert len(last['items']) == total - 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_current_and_historical_question_names_reuse_only_same_scope(tmp_path):
    path = tmp_path / 'qa.db'; _database(path)
    client, engine = await _client_for(path)
    async with client:
        question = (await client.post('/api/knowledge/questions/ask', json={'question':'胸膜自动识别在V10系列是标配吗？','scope':SCOPE})).json()
        qid = question['question_id']
        saved = await client.put(f'/api/knowledge/questions/{qid}/answer', json={'answer_text':'结论：胸膜自动识别（IPN 6000317）为选配。','alias_questions':[],'citations':[],'change_note':'Test owner confirmation'})
        assert saved.status_code == 200
        current = (await client.post('/api/knowledge/questions/ask', json={'question':'胸膜自动测量在V10系列是标配吗？','scope':SCOPE})).json()
        old = (await client.post('/api/knowledge/questions/ask', json={'question':'胸膜自动识别在V10系列是标配吗？','scope':SCOPE})).json()
        other = (await client.post('/api/knowledge/questions/ask', json={'question':'胸膜自动测量在V10系列是标配吗？','scope':{**SCOPE,'software_version':'1.14.81'}})).json()
    await engine.dispose()
    assert current['question_id'] == old['question_id'] == qid
    assert current['answer']['display_answer_text'].startswith('结论：胸膜自动测量')
    assert current['display_question'] == '胸膜自动测量在V10系列是标配吗？'
    assert other['status'] == 'pending' and other['question_id'] != qid


@pytest.mark.asyncio
async def test_duplicate_ipn_and_ambiguous_alias_keep_original_text(tmp_path):
    path = tmp_path / 'qa.db'; _database(path)
    with closing(sqlite3.connect(path)) as c, c:
        c.execute("INSERT INTO config_items VALUES(6,'6000317','Other','另一名称','Other')")
    client, engine = await _client_for(path)
    async with client:
        result = (await client.get('/api/knowledge/questions/1')).json()
        release = (await client.get('/api/knowledge/questions/4')).json()
    await engine.dispose()
    assert result['display_question_text'] == result['question_text']
    assert result['answer']['display_answer_text'] == result['answer']['answer_text']
    assert release['answer']['display_answer_text'] == release['answer']['answer_text']


@pytest.mark.asyncio
async def test_feature_catalog_uses_only_unique_approved_primary_ipn_current_description(tmp_path):
    path = tmp_path / 'features.db'; _create_knowledge_database(path)
    with closing(sqlite3.connect(path)) as c, c:
        c.execute("UPDATE config_items SET zh_desc='当前超微细血流成像【启用】' WHERE id=84")
        c.execute("INSERT INTO feature_names(feature_id,language,name,normalized_name,name_type,source,review_status) VALUES(7,'cn','不应命中','不应命中','alias','test','pending')")
    client, engine = await feature_client(path)
    async with client:
        item = (await client.get('/api/knowledge/features/7')).json()
        historical = (await client.get('/api/knowledge/features', params={'q':'超微细血流成像'})).json()
        rejected = (await client.get('/api/knowledge/features', params={'q':'不应命中'})).json()
        related = (await client.get('/api/knowledge/features/31')).json()
    await engine.dispose()
    assert item['display_cn_name'] == '当前超微细血流成像'
    assert item['primary_cn_name'] == '超微细血流成像'
    assert historical['total'] == 1 and rejected['total'] == 0
    assert not related['display_cn_name']


@pytest.mark.asyncio
async def test_approved_function_alias_searches_qa_but_pending_alias_does_not(tmp_path):
    path = tmp_path / 'qa.db'; _database(path)
    with closing(sqlite3.connect(path)) as c, c:
        c.executescript("""
        CREATE TABLE features(id INTEGER PRIMARY KEY,ipn TEXT);
        CREATE TABLE feature_config_item_links(feature_id INTEGER,config_item_id INTEGER,relation_type TEXT,review_status TEXT);
        CREATE TABLE feature_names(feature_id INTEGER,language TEXT,name TEXT,name_type TEXT,review_status TEXT);
        INSERT INTO features VALUES(1,'6000317');
        INSERT INTO feature_config_item_links VALUES(1,1,'primary','approved');
        INSERT INTO feature_names VALUES(1,'cn','胸膜智能识别','alias','approved'),(1,'cn','未批准完全不同的名称','alias','pending');
        """)
    client, engine = await _client_for(path)
    async with client:
        approved = (await client.get('/api/knowledge/questions', params={'q':'胸膜智能识别'})).json()
        pending = (await client.get('/api/knowledge/questions', params={'q':'未批准完全不同的名称'})).json()
    await engine.dispose()
    assert approved['total'] == 2 and pending['total'] == 0


@pytest.mark.asyncio
async def test_current_projection_refreshes_each_request_and_does_not_change_evidence(tmp_path):
    path = tmp_path / 'qa.db'; _database(path)
    with closing(sqlite3.connect(path)) as c, c:
        c.execute("INSERT INTO knowledge_answer_citations(answer_id,document_id,excerpt) VALUES(1,1,'胸膜自动识别原文')")
    client, engine = await _client_for(path)
    async with client:
        first = (await client.get('/api/knowledge/questions/1')).json()
        with closing(sqlite3.connect(path)) as c, c:
            c.execute("UPDATE config_items SET zh_desc='新版胸膜自动测量' WHERE id=1")
        second = (await client.get('/api/knowledge/questions/1')).json()
    await engine.dispose()
    assert first['display_question_text'].startswith('胸膜自动测量')
    assert second['display_question_text'].startswith('新版胸膜自动测量')
    assert second['answer']['citations'][0]['excerpt'] == '胸膜自动识别原文'
    assert second['answer']['answer_text'] == first['answer']['answer_text']
    assert second['evidence_review']['fingerprint'] == first['evidence_review']['fingerprint']


@pytest.mark.asyncio
async def test_ambiguous_current_name_does_not_select_first_of_different_ipns(tmp_path):
    path = tmp_path / 'qa.db'; _database(path)
    with closing(sqlite3.connect(path)) as c, c:
        c.execute("INSERT INTO config_items VALUES(6,'6000318','OtherPleura','胸膜自动测量','Other')")
    client, engine = await _client_for(path)
    async with client:
        for question, answer in [('胸膜自动识别在V10系列是标配吗？','结论：胸膜自动识别（IPN 6000317）为选配。'),
                                 ('另一胸膜功能在V10系列是标配吗？','结论：另一胸膜功能（IPN 6000318）为标配。')]:
            qid = (await client.post('/api/knowledge/questions/ask', json={'question':question,'scope':SCOPE})).json()['question_id']
            saved = await client.put(f'/api/knowledge/questions/{qid}/answer', json={'answer_text':answer,'alias_questions':[],'citations':[],'change_note':'Explicit test confirmation'})
            assert saved.status_code == 200
        result = (await client.post('/api/knowledge/questions/ask', json={'question':'胸膜自动测量在V10系列是标配吗？','scope':SCOPE})).json()
    await engine.dispose()
    assert result['status'] == 'pending' and result['answer'] is None


def test_ambiguous_long_name_blocks_a_unique_short_substring_projection():
    from app.services.knowledge_names import KnowledgeNameContext
    context = KnowledgeNameContext(current={'1111111':'新自动测量','2222222':'自动测量(2D)','3333333':'自动测量(2D)'},
                                   item_ids={'1111111':1,'2222222':2,'3333333':3})
    context.add_alias('自动测量','1111111')
    context.add_alias('自动测量(2D)','2222222')
    context.add_alias('自动测量(2D)','3333333')
    assert context.project('自动测量(2D)为选配') == ('自动测量(2D)为选配', [])


def test_narrative_prefix_is_not_registered_as_a_feature_name():
    from app.services.knowledge_names import _anchors
    assert _anchors('结论：新增胸膜自动识别（IPN 6000317）为选配。') == []
    assert _anchors('结论：胸膜自动识别（IPN 6000317）为选配。', question='胸膜自动识别如何配置？') == [('胸膜自动识别','6000317')]


@pytest.mark.asyncio
async def test_explicit_ipn_disambiguates_same_current_name_and_never_selects_comparison_ipn(tmp_path):
    path = tmp_path / 'qa.db'; _database(path)
    with closing(sqlite3.connect(path)) as c, c:
        c.execute("INSERT INTO config_items VALUES(6,'6000318','OtherPleura','胸膜自动测量','Other')")
    client, engine = await _client_for(path)
    async with client:
        qid = (await client.post('/api/knowledge/questions/ask', json={'question':'胸膜自动识别在V10系列是标配吗？','scope':SCOPE})).json()['question_id']
        await client.put(f'/api/knowledge/questions/{qid}/answer', json={'answer_text':'结论：胸膜自动识别（IPN 6000317）为选配。','alias_questions':[],'citations':[],'change_note':'Explicit test confirmation'})
        explicit = (await client.post('/api/knowledge/questions/ask', json={'question':'胸膜自动测量（IPN 6000317）在V10系列是标配吗？','scope':SCOPE})).json()
        wrong = (await client.post('/api/knowledge/questions/ask', json={'question':'胸膜自动测量（IPN 6000318）在V10系列是标配吗？','scope':SCOPE})).json()
    await engine.dispose()
    assert explicit['status'] == 'answered' and explicit['question_id'] == qid
    assert wrong['status'] == 'pending'


@pytest.mark.asyncio
@pytest.mark.parametrize('prefix',['新增','并非','不是','建议','仅新增','请确保','尚未支持'])
async def test_narrative_prefix_remains_intact_when_name_is_bound_by_the_question(tmp_path, prefix):
    path = tmp_path / 'qa.db'; _database(path)
    with closing(sqlite3.connect(path)) as c, c:
        c.execute('UPDATE knowledge_answers SET answer_text=? WHERE id=1', (f'结论：{prefix}胸膜自动识别（IPN 6000317）为选配。',))
    client, engine = await _client_for(path)
    async with client:
        result = (await client.get('/api/knowledge/questions/1')).json()
    await engine.dispose()
    assert result['answer']['display_answer_text'] == f'结论：{prefix}胸膜自动测量（IPN 6000317）为选配。'


@pytest.mark.asyncio
async def test_two_primary_links_do_not_become_unique_after_dropping_invalid_ipn(tmp_path):
    path = tmp_path / 'features.db'; _create_knowledge_database(path)
    with closing(sqlite3.connect(path)) as c, c:
        c.execute("INSERT INTO config_items VALUES(500,'6000294','Other','Duplicate','Other')")
        c.execute("INSERT INTO feature_config_item_links(feature_id,config_item_id,relation_type,source,review_status) VALUES(7,96,'primary','test','approved')")
    client, engine = await feature_client(path)
    async with client:
        result = (await client.get('/api/knowledge/features/7')).json()
    await engine.dispose()
    assert result['display_cn_name'] is None


@pytest.mark.asyncio
async def test_seed_current_name_reuses_projected_legacy_question_without_a_duplicate(tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.services.knowledge_question_seed import seed_pending_questions, SeedQuestionSpec
    path = tmp_path / 'qa.db'; _database(path)
    engine = create_async_engine(f'sqlite+aiosqlite:///{path}')
    before = path.read_bytes()
    async with async_sessionmaker(engine)() as session:
        result = await seed_pending_questions(session, [SeedQuestionSpec(category='配置',question='Elastic imaging压力式弹性成像如何配置？')], apply=False)
    await engine.dispose()
    assert result['summary']['covered'] == 1
    assert result['items'][0]['published_similarity'] == 1.0
    assert result['items'][0]['question_id'] == 5
    assert path.read_bytes() == before

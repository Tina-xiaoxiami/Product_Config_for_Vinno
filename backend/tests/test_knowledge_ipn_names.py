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

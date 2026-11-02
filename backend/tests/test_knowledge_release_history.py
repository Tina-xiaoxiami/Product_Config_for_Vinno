"""Historical evidence stays scoped and never becomes an implicit published answer."""
from contextlib import closing
import hashlib
import sqlite3

import pytest

from test_knowledge_qa_api import _client_for, _create_qa_database

SCOPE = {"country": "CN", "market": "domestic", "product_model_id": 901,
         "software_version": "1.14.65"}


def _document(path, doc_id, version, content, *, model='VINNO 6', country='CN', market='domestic'):
    source = path.parent / f'source-{doc_id}.pdf'
    source.write_bytes(f'controlled source {doc_id}'.encode())
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    with closing(sqlite3.connect(path)) as c, c:
        c.execute('''INSERT OR REPLACE INTO knowledge_documents
            (id,document_type,title,file_name,file_path,version,market,country,product_series,mime_type,sha256)
            VALUES (?, 'release_note', ?, ?, ?, ?, ?, ?, ?, 'application/pdf', ?)''',
            (doc_id, f'{model} Release Note {version}', source.name, str(source), version, market, country, model, sha))
        c.execute('''INSERT OR REPLACE INTO knowledge_document_extractions
            (document_id,extractor_version,source_sha256,status,chunk_count) VALUES (?, 'test', ?, 'completed', 1)''', (doc_id, sha))
        c.execute('DELETE FROM knowledge_document_chunks WHERE document_id=?', (doc_id,))
        c.execute('''INSERT INTO knowledge_document_chunks
            (document_id,chunk_index,page_number,source_ref,content,normalized_content,content_hash)
            VALUES (?,0,2,'第2页',?,?,?)''', (doc_id, content, ''.join(content.split()).lower(), hashlib.sha256(content.encode()).hexdigest()))


@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'history.db'
    _create_qa_database(path)
    with closing(sqlite3.connect(path)) as c, c:
        c.executescript('''
        CREATE TABLE knowledge_release_bindings (
            id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL, product_model_id INTEGER NOT NULL,
            country TEXT NOT NULL, market TEXT NOT NULL, release_line TEXT NOT NULL,
            conditions TEXT NOT NULL DEFAULT '', evidence_reference TEXT NOT NULL, confirmed_by TEXT NOT NULL,
            document_fingerprint TEXT NOT NULL, model_name TEXT NOT NULL, series_name TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1, revision INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        ''')
    _document(path, 1, '1.14.40', 'Release Note 1.14.40\n新增穿刺针增益调节，0、1、2三档可调。')
    _document(path, 2, '1.14.61', 'Release Note 1.14.61\n调整图像处理算法。')
    _document(path, 3, '1.14.80', 'Release Note 1.14.80\n取消针增益调节。')
    _document(path, 4, '1.14.40', 'Release Note 1.14.40\n新增穿刺针增益调节。', model='VINNO 10E')
    return path


async def _client(path):
    client, engine = await _client_for(path)
    with closing(sqlite3.connect(path)) as c, c:
        c.execute("UPDATE product_models SET name='VINNO 6' WHERE id=901")
    try:
        from app.api.knowledge_release_history import router
    except ModuleNotFoundError as exc:
        if exc.name != 'app.api.knowledge_release_history':
            raise
    else:
        client._transport.app.include_router(router, prefix='/api/knowledge')
    return client, engine


async def _bind(client, document_ids=(1, 2, 3), **overrides):
    payload = {'document_ids': list(document_ids), 'product_model_ids': [901],
               'country': 'CN', 'market': 'domestic', 'release_line': 'V6-main',
               'conditions': '', 'evidence_reference': '明确适用完整机型及市场的受控记录',
               'confirmed_by': 'Fixture reviewer', **overrides}
    response = await client.post('/api/knowledge/release-history/bindings', json=payload)
    assert response.status_code == 200, response.text
    return response.json()['items']


async def _trace(client, query='针增益调节', scope=SCOPE, **extra):
    response = await client.post('/api/knowledge/release-history/trace', json={'query': query, 'scope': scope, **extra})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_history_traces_earlier_scoped_notes_excludes_future_and_wrong_model_without_publishing(database):
    client, engine = await _client(database)
    async with client:
        await _bind(client)
        await _bind(client, (4,), product_model_ids=[902], release_line='V10')
        before = database.read_bytes()
        result = await _trace(client)
        assert result['assessment'] == 'evidence_found'
        assert [x['event_version'] for x in result['events']] == ['1.14.40']
        assert result['events'][0]['source_ref'] == '第2页'
        assert result['coverage']['versions'] == ['1.14.40', '1.14.61']
        assert result['coverage']['excluded_documents']
        assert database.read_bytes() == before
    await engine.dispose()
    with closing(sqlite3.connect(database)) as c:
        assert c.execute('SELECT COUNT(*) FROM knowledge_answers').fetchone()[0] == 0


@pytest.mark.asyncio
async def test_parent_feature_and_missing_child_record_never_mean_child_is_supported_or_unsupported(database):
    _document(database, 1, '1.14.40', 'Release Note 1.14.40\n新增穿刺增强，标配。')
    client, engine = await _client(database)
    async with client:
        await _bind(client, (1, 2))
        result = await _trace(client)
        assert result['assessment'] == 'no_record'
        assert result['events'] == []
        assert '不等于不支持' in result['conclusion']
    await engine.dispose()


@pytest.mark.asyncio
async def test_ask_fallback_includes_history_trace_but_keeps_pending_answer_status(database):
    client, engine = await _client(database)
    async with client:
        await _bind(client, (1, 2))
        response = await client.post('/api/knowledge/questions/ask', json={'question': 'V6是否支持针增益调节？', 'scope': SCOPE})
        result = response.json()
        assert result['status'] == 'pending'
        assert result['answer'] is None
        assert result['history_trace']['events'][0]['document_id'] == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_unconfirmed_scope_materials_are_visible_but_never_enter_applicable_chains(database):
    _document(database, 5, '1.14.65', 'Release Note 1.14.65\n新增针增益调节。', country=None, market='unspecified')
    client, engine = await _client(database)
    async with client:
        result = await _trace(client)
        assert result['assessment'] == 'scope_unconfirmed'
        assert result['events'] == []
        unresolved = next(x for x in result['coverage']['unresolved_documents'] if x['document_id'] == 5)
        assert unresolved['candidate_events']
        assert unresolved['reasons']
    await engine.dispose()


@pytest.mark.asyncio
async def test_narrative_negation_and_other_changes_on_same_line_do_not_become_added_child_evidence(database):
    _document(database, 1, '1.14.40', 'Release Note 1.14.40\n新增穿刺增强；针增益调节保持不变。\n未新增针增益调节。')
    client, engine = await _client(database)
    async with client:
        await _bind(client, (1,))
        result = await _trace(client)
        assert all(event['change_type'] != 'added' for event in result['events'])
        assert result['assessment'] == 'conditional_evidence'
    await engine.dispose()


@pytest.mark.asyncio
async def test_same_version_contradictory_events_require_review_and_later_removal_is_visible(database):
    _document(database, 2, '1.14.40', 'Release Note 1.14.40\n取消针增益调节。')
    client, engine = await _client(database)
    async with client:
        await _bind(client, (1, 2, 3))
        conflict = await _trace(client)
        assert conflict['assessment'] == 'conflicting_evidence'
        later = await _trace(client, scope={**SCOPE, 'software_version': '1.14.80'})
        assert any(event['change_type'] == 'removed' for event in later['events'])
    await engine.dispose()


@pytest.mark.asyncio
async def test_generic_pending_question_does_not_fail_because_history_topic_is_not_specific(database):
    client, engine = await _client(database)
    async with client:
        response = await client.post('/api/knowledge/questions/ask', json={'question': '是否支持功能？', 'scope': SCOPE})
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'pending'
    await engine.dispose()

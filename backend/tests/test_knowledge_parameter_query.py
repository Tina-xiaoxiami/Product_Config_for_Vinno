"""Saved parameter questions offer explicit snapshot matching, never formal answers."""
from contextlib import closing
import json
import sqlite3

import pytest

from app.services.knowledge_qa import normalize_question
from test_knowledge_qa_api import TEST_QUERY_SCOPE, _client_for, _create_qa_database


QUESTION = '各型号电池容量是多少？'
ALIAS = '电池容量分别是多少？'


def _topics(path, topics=None):
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript('''
            CREATE TABLE knowledge_parameter_topics (
                id INTEGER PRIMARY KEY, name TEXT, question TEXT,
                normalized_question TEXT, aliases_json TEXT, fields_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE knowledge_parameter_specs (id INTEGER PRIMARY KEY);
            CREATE TABLE knowledge_parameter_revisions (id INTEGER PRIMARY KEY);
        ''')
        for topic_id, question, aliases in topics or [(1, QUESTION, [ALIAS])]:
            connection.execute('INSERT INTO knowledge_parameter_topics '
                               '(id,name,question,normalized_question,aliases_json,fields_json) '
                               'VALUES (?,?,?,?,?,?)',
                               (topic_id, f'参数主题{topic_id}', question,
                                normalize_question(question), json.dumps(aliases), '[]'))


async def _ask(client, question=QUESTION, *, scope=TEST_QUERY_SCOPE):
    payload = {'question': question}
    if scope is not None:
        payload['scope'] = scope
    response = await client.post('/api/knowledge/questions/ask', json=payload)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_parameter_candidates_preserve_all_qa_statuses_and_missing_scope_is_read_only(tmp_path):
    path = tmp_path / 'query.db'
    _create_qa_database(path)
    _topics(path)
    client, engine = await _client_for(path)
    try:
        async with client:
            before = path.read_bytes()
            clarification = await _ask(client, scope=None)
            assert clarification['status'] == 'needs_clarification'
            assert clarification['question_id'] is None and clarification['answer'] is None
            assert path.read_bytes() == before
            candidate = {'id': 1, 'name': '参数主题1', 'question': QUESTION, 'match_type': 'question'}
            assert clarification['parameter_topics'] == [candidate]
            pending = await _ask(client)
            assert pending['status'] == 'pending' and pending['answer'] is None
            assert pending['parameter_topics'] == [candidate]
            published = await client.put(f"/api/knowledge/questions/{pending['question_id']}/answer",
                                        json={'answer_text': '按已确认的资料选择对应电池规格。',
                                              'alias_questions': [], 'citations': []})
            assert published.status_code == 200, published.text
            answered = await _ask(client)
            assert answered['status'] == 'answered'
            assert answered['answer'] == published.json()['answer']
            assert answered['question_id'] == pending['question_id']
            assert answered['parameter_topics'] == [candidate]
            with closing(sqlite3.connect(path)) as connection:
                assert connection.execute('SELECT count(*) FROM knowledge_questions').fetchone()[0] == 1
                assert connection.execute('SELECT count(*) FROM knowledge_parameter_specs').fetchone()[0] == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_explicit_aliases_return_all_collisions_in_id_order_without_automatic_selection(tmp_path):
    path = tmp_path / 'alias.db'
    _create_qa_database(path)
    _topics(path, [(3, '电池能量是多少？', [ALIAS, ALIAS]), (1, QUESTION, [ALIAS])])
    client, engine = await _client_for(path)
    try:
        async with client:
            result = await _ask(client, ' 电池容量分别是多少? ', scope=None)
            assert result['status'] == 'needs_clarification' and result['answer'] is None
            assert [(item['id'], item['match_type']) for item in result['parameter_topics']] == [(1, 'alias'), (3, 'alias')]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('query', [
    '电池容量', '电池容量分别是多少？是否支持快充？', '各型号电池容量不是这个值吗？',
    'V6电池容量是多少？', 'V6是否不支持针增益调节？', 'V10是否支持针增益调节？',
])
async def test_parameter_lookup_never_uses_substrings_similarity_names_or_removed_identifiers(tmp_path, query):
    path = tmp_path / 'exact.db'
    _create_qa_database(path)
    _topics(path, [(1, QUESTION, [ALIAS]), (2, 'V6是否支持针增益调节？', [])])
    client, engine = await _client_for(path)
    try:
        async with client:
            result = await _ask(client, query, scope=None)
            assert result['parameter_topics'] == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('with_topics', [False, True])
async def test_legacy_or_partial_parameter_schema_does_not_break_existing_qa(tmp_path, with_topics):
    path = tmp_path / 'legacy.db'
    _create_qa_database(path)
    if with_topics:
        _topics(path)
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute('DROP TABLE knowledge_parameter_specs')
    client, engine = await _client_for(path)
    try:
        async with client:
            clarification = await _ask(client, scope=None)
            assert clarification['parameter_topics'] == []
            assert clarification['status'] == 'needs_clarification'
            pending = await _ask(client)
            assert pending['status'] == 'pending' and pending['answer'] is None
            assert pending['parameter_topics'] == []
    finally:
        await engine.dispose()

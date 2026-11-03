"""The feature editor reads authoritative WP descriptions without copying them."""
import copy
import io
import json
import sqlite3
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import get_db


def source_feature(identifier='wp-a', ipns=('A',), **overrides):
    record = {'revision': 7, 'name': '白皮书标题', 'body': ['默认说明'],
              'source': {'kind': 'manual', 'series': 'master', 'version': '1.0', 'path': '/private/source.docx'},
              'created_at': '2026-11-03'}
    feature = {'id': identifier, 'configuration_items': [{'ipn': ipn} for ipn in ipns],
        'bindings': [{'series': 'R&V10 series-China', 'version': '1.14.81'}],
        'series_description_views': {'master': {'zh': [record], 'en': []},
            'R&V10 series': {'zh': [{**record, 'revision': 9, 'body': ['V10说明']}], 'en': []},
            'Tulip': {'zh': [{**record, 'revision': 99, 'body': ['另一系列说明']}], 'en': []}},
        'descriptions': {'zh': [{**record, 'revision': 100, 'body': ['不能直接用的完整历史末条']}], 'en': []}}
    return {**feature, **overrides}


@pytest.fixture
def library():
    return {'revision': 706, 'features': [source_feature(), source_feature('wp-b', ('B',))]}


async def harness(tmp_path):
    from app.api.features import router
    path = tmp_path / 'features.db'
    with sqlite3.connect(path) as c:
        c.executescript('''
            CREATE TABLE features(id INTEGER PRIMARY KEY, name TEXT, primary_cn_name TEXT, primary_en_name TEXT, ipn TEXT);
            CREATE TABLE config_items(id INTEGER PRIMARY KEY,ipn TEXT);
            CREATE TABLE feature_config_item_links(id INTEGER PRIMARY KEY, feature_id INTEGER, config_item_id INTEGER, relation_type TEXT, review_status TEXT);
            INSERT INTO features VALUES (1,'旧名','配置中文','Config English','A'),(2,'同名','配置中文','Same title','X'),(3,'无批准IPN','无批准IPN','','B'),(4,'空IPN','空IPN','','');
            INSERT INTO config_items VALUES (1,'A'),(2,'B'),(3,'X'),(4,'');
            INSERT INTO feature_config_item_links VALUES (1,1,1,'primary','approved'),(2,1,2,'version_variant','approved'),(3,2,3,'primary','approved'),(4,3,2,'primary','pending'),(5,4,4,'primary','approved');
        ''')
    engine = create_async_engine(f'sqlite+aiosqlite:///{path}')
    sessions = async_sessionmaker(engine)
    app = FastAPI()
    app.include_router(router, prefix='/api/features')
    async def override():
        async with sessions() as session:
            yield session
    app.dependency_overrides[get_db] = override
    return path, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test'), engine


@pytest.mark.asyncio
async def test_exact_approved_ipns_preserve_names_relations_and_projected_scopes(tmp_path, monkeypatch, library):
    from app.services import whitepaper_feature_library as bridge
    monkeypatch.setattr(bridge, '_read_library', lambda url: library)
    path, client, engine = await harness(tmp_path)
    before = path.read_bytes()
    async with client:
        response = await client.get('/api/features/whitepaper-library')
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['source']['available'] and result['source']['revision'] == 706
        assert result['summary'] == {'configured': 4, 'linked': 1, 'ambiguous': 0, 'unlinked': 1, 'no_ipn': 2}
        first = result['items'][0]
        assert first['cn_name'] == '配置中文' and first['en_name'] == 'Config English'
        assert first['status'] == 'linked' and len(first['matches']) == 2
        assert first['matches'][1]['matched_ipns'] == [{'ipn': 'B', 'relation_type': 'version_variant'}]
        descriptions = first['matches'][0]['descriptions']
        assert {(x['scope'], x['language']) for x in descriptions} == {('master','zh'),('master','en'),('R&V10 series','zh'),('R&V10 series','en')}
        assert next(x for x in descriptions if x['scope']=='R&V10 series' and x['language']=='zh')['body'] == ['V10说明']
        assert next(x for x in descriptions if x['scope']=='master' and x['language']=='en')['revision'] is None
        assert '/private' not in json.dumps(result) and '另一系列说明' not in json.dumps(result)
        assert '不能直接用' not in json.dumps(result)
        assert result['items'][1]['status'] == 'unlinked'  # same name is not identity
        assert all(x['status']=='no_ipn' for x in result['items'][2:])
    await engine.dispose()
    assert path.read_bytes() == before


@pytest.mark.asyncio
async def test_same_ipn_multiple_wp_ids_is_ambiguous_and_live_changes_are_not_cached(tmp_path, monkeypatch, library):
    from app.services import whitepaper_feature_library as bridge
    monkeypatch.setattr(bridge, '_read_library', lambda url: copy.deepcopy(library))
    path, client, engine = await harness(tmp_path)
    async with client:
        library['features'].append(source_feature('wp-other', ('A','A')))
        first = (await client.get('/api/features/whitepaper-library', params={'feature_id':1})).json()
        assert first['summary']['configured'] == 1 and first['summary']['ambiguous'] == 1
        assert first['items'][0]['status'] == 'ambiguous' and len(first['items'][0]['matches']) == 3
        library['features'][0]['series_description_views']['master']['zh'][-1]['body'] = ['即时更新']
        library['revision'] = 707
        second = (await client.get('/api/features/whitepaper-library', params={'feature_id':1})).json()
        assert second['source']['revision'] == 707
        assert second['items'][0]['matches'][0]['descriptions'][0]['body'] == ['即时更新']
        assert (await client.get('/api/features/whitepaper-library', params={'feature_id':999})).status_code == 404
        assert (await client.get('/api/features/whitepaper-library', params={'feature_id':0})).status_code == 422
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [TimeoutError('timeout'), OSError('offline'), ValueError('bad JSON')])
async def test_source_failure_is_explicit_without_disabling_native_features(tmp_path, monkeypatch, failure):
    from app.services import whitepaper_feature_library as bridge
    def fail(url): raise failure
    monkeypatch.setattr(bridge, '_read_library', fail)
    path, client, engine = await harness(tmp_path)
    async with client:
        response = await client.get('/api/features/whitepaper-library')
        assert response.status_code == 200
        result = response.json()
        assert result['source']['available'] is False and result['source']['message']
        assert result['summary']['configured'] == 4 and all(x['status']=='unavailable' for x in result['items'])
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', [{}, {'revision':1,'features':{}}, {'revision':1,'features':[{}]}, {'revision':1,'features':[source_feature(),source_feature()]}])
async def test_malformed_source_does_not_become_successful_empty_library(tmp_path, monkeypatch, bad):
    from app.services import whitepaper_feature_library as bridge
    monkeypatch.setattr(bridge, '_read_library', lambda url: bad)
    path, client, engine = await harness(tmp_path)
    async with client:
        result = (await client.get('/api/features/whitepaper-library')).json()
        assert result['source']['available'] is False
    await engine.dispose()


@pytest.mark.parametrize('url', ['http://example.com','http://127.0.0.1@evil.invalid','file:///private/data','http://127.0.0.1:43121/private','http://localhost:43121/?url=x'])
def test_workbench_url_is_loopback_only_without_arbitrary_paths(monkeypatch, url):
    from app.services import whitepaper_feature_library as bridge
    monkeypatch.setenv('WHITEPAPER_WORKBENCH_URL',url)
    with pytest.raises(ValueError): bridge.workbench_url()


def test_reader_rejects_redirect_and_oversize(monkeypatch):
    from app.services import whitepaper_feature_library as bridge
    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302);self.send_header('Location','http://example.invalid/private');self.end_headers()
        def log_message(self,*args): pass
    server = ThreadingHTTPServer(('127.0.0.1',0),Redirect)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with pytest.raises(urllib.error.HTTPError): bridge._read_library(f'http://127.0.0.1:{server.server_port}')
    finally:
        server.shutdown();server.server_close();thread.join()
    class Opener:
        def open(self,request,timeout): return io.BytesIO(b' '*33)
    monkeypatch.setattr(bridge,'MAX_LIBRARY_BYTES',32)
    monkeypatch.setattr(bridge,'build_opener',lambda *handlers: Opener())
    with pytest.raises(ValueError):bridge._read_library('http://127.0.0.1:43121')

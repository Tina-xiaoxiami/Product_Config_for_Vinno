"""Product scope and deterministic rules stay outside the shared model runner."""
import hashlib
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.models import ProductSeries, ProductModel
from app.models.knowledge import KnowledgeDocument, KnowledgeDocumentExtraction, KnowledgeDocumentChunk
from app.api.knowledge_document_answer import router
from app.services import knowledge_document_answer as service


SCOPE = {'market': 'domestic', 'product_model_id': 1, 'software_version': '1.14.81'}
PAGE = '穿刺增强支持针增益调节。仅适用于新平台，请核对机器硬件。'


@asynccontextmanager
async def setup(tmp_path, monkeypatch):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "answer.db"}')
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    source = tmp_path / 'source.pdf'
    source.write_bytes(b'synthetic PDF identity; original pages represented in extraction fixture')
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    async with factory() as db:
        db.add_all([ProductSeries(id=1, name='V-China'), ProductSeries(id=2, name='V-Oversea'),
                    ProductModel(id=1, series_id=1, name='VINNO 6'), ProductModel(id=2, series_id=2, name='VINNO 6')])
        await db.flush()
        for ident, model, version in [(1, 'VINNO 6', '1.14.81'), (2, 'VINNO 10', '1.14.81'), (3, 'VINNO 6', '1.14.82')]:
            document_path = source if ident == 1 else tmp_path / f'source-{ident}.pdf'
            if ident != 1:
                document_path.write_bytes(source.read_bytes())
            db.add(KnowledgeDocument(id=ident, document_type='manual', title=f'合成资料{ident}', file_name='source.pdf',
                                    file_path=str(document_path), version=version, market='domestic', country='CN',
                                    product_series=model, mime_type='application/pdf', sha256=sha, source_status='active'))
            await db.flush()
            db.add(KnowledgeDocumentExtraction(document_id=ident, source_sha256=sha, status='completed', extractor_version='test'))
            db.add(KnowledgeDocumentChunk(document_id=ident, chunk_index=0, page_number=1, source_ref='第1页', content=PAGE, normalized_content=PAGE, content_hash=hashlib.sha256(PAGE.encode()).hexdigest()))
        await db.commit()
    monkeypatch.setattr(service, 'trace_release_history', empty_trace)
    app = FastAPI()
    app.include_router(router, prefix='/api/knowledge')
    async def database():
        async with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            yield client, factory, source
    finally:
        await engine.dispose()


async def empty_trace(*args, **kwargs):
    return {'chains': [], 'source_documents': [], 'confirmation_items': [], 'coverage': {}}


def result(payload):
    page = payload['pages'][0]
    return {'status': 'draft', 'claims': [{'text': '仅适用于新平台。', 'kind': 'source_statement', 'support_status': 'direct',
                                         'citations': [{'document_id': page['id'], 'pdf_page': page['page'], 'original_excerpt': PAGE, 'version_id': page['version_id']}]}],
            'gaps': [], 'coverage': {}, 'visual_review': {'status': 'model_checked', 'human_reviewed': False}, 'metrics': {'model_calls': 4}, 'runtime_identity': {'protocol_version': 1}}


@pytest.mark.asyncio
async def test_draft_only_reads_scope_eligible_pages_and_remaps_citations_without_qa_writes(tmp_path, monkeypatch):
    calls = []
    def run(payload, **kwargs):
        calls.append(payload)
        assert payload['pages'][0]['requires_visual_review'] is True
        assert kwargs['sources'][0]['id'] == 'kb-1'
        assert kwargs['sources'][0]['version_id'] == payload['pages'][0]['version_id']
        assert kwargs['sources'][0]['file_path'].endswith('source.pdf')
        return result(payload)
    monkeypatch.setattr(service, 'run_shared_evidence', run)
    async with setup(tmp_path, monkeypatch) as (client, factory, _):
        r = await client.post('/api/knowledge/document-answer', json={'question': '针增益调节怎样使用？', 'scope': SCOPE})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data['status'] == 'draft'
        assert [p['id'] for p in calls[0]['pages']] == ['kb-1']
        assert set(calls[0]['pages'][0]) == {'id', 'page', 'text', 'version_id', 'title', 'file_name', 'year', 'source_url', 'requires_visual_review'}
        cite = data['claims'][0]['citations'][0]
        assert cite['document_id'] == 1 and cite['page'] == 1
        assert cite['preview_url'] == f"/api/knowledge/documents/1/preview?version_id={calls[0]['pages'][0]['version_id']}#page=1"
        assert data['coverage']['document_count'] == 1
        assert data['visual_review']['status'] == 'model_checked'
        async with factory() as db:
            assert (await db.execute(text('SELECT count(*) FROM knowledge_questions'))).scalar() == 0
            assert (await db.execute(text('SELECT count(*) FROM knowledge_answers'))).scalar() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('question', ['该功能是标配还是选配？', 'V6电池容量是多少？', 'VINNO 6注册支持这个探头吗？', 'Is VINNO 6 standard or optional?', 'What is the battery capacity?', 'Is this probe registered?'])
async def test_configuration_registration_and_parameter_questions_never_call_a_model(tmp_path, monkeypatch, question):
    def forbidden(_):
        pytest.fail('deterministic question sent to model')
    monkeypatch.setattr(service, 'run_shared_evidence', forbidden)
    async with setup(tmp_path, monkeypatch) as (client, _, _):
        data = (await client.post('/api/knowledge/document-answer', json={'question': question, 'scope': SCOPE})).json()
        assert data['status'] == 'deterministic_required'
        assert data['claims'] == []


@pytest.mark.asyncio
async def test_stale_extraction_or_original_produces_a_gap_and_no_model_call(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'run_shared_evidence', lambda _: pytest.fail('bad source entered model'))
    async with setup(tmp_path, monkeypatch) as (client, _, source):
        source.write_bytes(b'changed original')
        data = (await client.post('/api/knowledge/document-answer', json={'question': '针增益怎样使用？', 'scope': SCOPE})).json()
        assert data['status'] == 'no_evidence'
        assert data['gaps'] and not data['claims']


@pytest.mark.asyncio
async def test_sources_changed_during_generation_invalidate_every_claim(tmp_path, monkeypatch):
    async with setup(tmp_path, monkeypatch) as (client, _, source):
        def run(payload, **kwargs):
            answer = result(payload)
            source.write_bytes(b'changed during inference')
            return answer
        monkeypatch.setattr(service, 'run_shared_evidence', run)
        data = (await client.post('/api/knowledge/document-answer', json={'question': '针增益怎样使用？', 'scope': SCOPE})).json()
        assert data['status'] == 'unavailable'
        assert data['claims'] == []
        assert data['metrics']['model_calls'] == 4


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['document', 'page', 'quote'])
async def test_fabricated_reference_identity_or_quote_is_rejected(tmp_path, monkeypatch, change):
    def run(payload, **kwargs):
        answer = result(payload)
        cite = answer['claims'][0]['citations'][0]
        cite['preview_url'] = 'https://evil.invalid/'
        cite[{'document': 'document_id', 'page': 'pdf_page', 'quote': 'original_excerpt'}[change]] = {'document': 'kb-2', 'page': 99, 'quote': '这句话不在原文中，不能成为引用。'}[change]
        return answer
    monkeypatch.setattr(service, 'run_shared_evidence', run)
    async with setup(tmp_path, monkeypatch) as (client, _, _):
        data = (await client.post('/api/knowledge/document-answer', json={'question': '针增益怎样使用？', 'scope': SCOPE})).json()
        assert data['status'] == 'validation_failed' and not data['claims']
        assert data['metrics']['model_calls'] == 4


@pytest.mark.asyncio
async def test_runner_timeout_does_not_report_zero_model_calls(tmp_path, monkeypatch):
    from app.integrations.guideline_evidence import SharedEvidenceUnavailable
    def fail(_, **kwargs):
        raise SharedEvidenceUnavailable('共享运行器超时')
    monkeypatch.setattr(service, 'run_shared_evidence', fail)
    async with setup(tmp_path, monkeypatch) as (client, _, _):
        data = (await client.post('/api/knowledge/document-answer', json={'question': '针增益怎样使用？', 'scope': SCOPE})).json()
        assert data['status'] == 'unavailable' and data['metrics']['model_calls'] is None


@pytest.mark.asyncio
async def test_missing_scope_does_not_call_runner_and_does_not_record_a_question(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'run_shared_evidence', lambda _: pytest.fail('missing scope entered model'))
    async with setup(tmp_path, monkeypatch) as (client, factory, _):
        r = await client.post('/api/knowledge/document-answer', json={'question': '如何调节？', 'scope': {}})
        assert r.status_code == 422
        async with factory() as db:
            assert (await db.execute(text('SELECT count(*) FROM knowledge_questions'))).scalar() == 0


@pytest.mark.asyncio
async def test_unreferencable_short_pages_are_reported_before_shared_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'run_shared_evidence', lambda _: pytest.fail('blank page passed to runner'))
    async with setup(tmp_path, monkeypatch) as (client, factory, _):
        async with factory() as db:
            await db.execute(text("UPDATE knowledge_document_chunks SET content='1' WHERE document_id=1"))
            await db.commit()
        data = (await client.post('/api/knowledge/document-answer', json={'question': '针增益怎样使用？', 'scope': SCOPE})).json()
        assert data['status'] == 'no_evidence' and data['gaps']


@pytest.mark.asyncio
async def test_same_market_same_name_in_another_series_requires_identity_resolution(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'run_shared_evidence', lambda _: pytest.fail('ambiguous name sent to model'))
    async with setup(tmp_path, monkeypatch) as (client, factory, _):
        async with factory() as db:
            db.add(ProductSeries(id=3, name='Other-China'))
            db.add(ProductModel(id=3, series_id=3, name='VINNO 6'))
            await db.commit()
        data = (await client.post('/api/knowledge/document-answer', json={'question': '针增益怎样使用？', 'scope': SCOPE})).json()
        assert data['status'] == 'no_evidence' and data['gaps']


@pytest.mark.asyncio
async def test_insufficient_history_topic_returns_actionable_validation_instead_of_server_error(tmp_path, monkeypatch):
    from app.services.knowledge_release_history import ReleaseHistoryError
    async def unclear(*args, **kwargs):
        raise ReleaseHistoryError('请明确要追溯的功能或主题')
    async with setup(tmp_path, monkeypatch) as (client, _, _):
        monkeypatch.setattr(service, 'trace_release_history', unclear)
        r = await client.post('/api/knowledge/document-answer', json={'question': 'V6支持吗', 'scope': SCOPE})
        assert r.status_code == 422 and '主题' in r.json()['detail']


@pytest.mark.asyncio
async def test_corrupt_chunk_hash_is_not_accepted_as_original_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'run_shared_evidence', lambda *a, **k: pytest.fail('corrupt extraction sent to model'))
    async with setup(tmp_path, monkeypatch) as (client, factory, _):
        async with factory() as db:
            await db.execute(text("UPDATE knowledge_document_chunks SET content='tampered without updating the extraction hash' WHERE document_id=1"))
            await db.commit()
        data = (await client.post('/api/knowledge/document-answer', json={'question': '针增益怎样使用？', 'scope': SCOPE})).json()
        assert data['status'] == 'no_evidence' and data['gaps']

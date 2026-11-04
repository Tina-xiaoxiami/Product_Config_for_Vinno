"""A citation resolves only against its registered source version and location."""
import hashlib
from contextlib import asynccontextmanager
from io import BytesIO

import httpx
import pytest
from fastapi import FastAPI
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import knowledge
from app.database import Base, get_db
from app.models.knowledge import KnowledgeDocument, KnowledgeDocumentExtraction, KnowledgeDocumentChunk

PAGE = 'Only the new platform supports needle gain. Check the hardware first.'


@asynccontextmanager
async def source_client(tmp_path, suffix='.pdf'):
    path = tmp_path / ('source' + suffix)
    if suffix == '.pdf':
        output = BytesIO(); canvas = Canvas(output)
        canvas.drawString(20, 750, PAGE); canvas.showPage(); canvas.save()
        path.write_bytes(output.getvalue())
    else:
        path.write_bytes(b'synthetic non-PDF original; locator comes from registered extraction')
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "sources.db"}')
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db.add(KnowledgeDocument(id=1, document_type='manual', title='Test source', file_name=path.name,
            file_path=str(path), sha256=sha, source_status='active', mime_type='application/pdf' if suffix == '.pdf' else None))
        await db.flush()
        db.add(KnowledgeDocumentExtraction(document_id=1, source_sha256=sha, status='completed', extractor_version='test'))
        db.add(KnowledgeDocumentChunk(id=1, document_id=1, chunk_index=0, page_number=1 if suffix == '.pdf' else None,
            source_ref='第1页' if suffix == '.pdf' else 'Sheet1!第5行', content=PAGE, normalized_content=PAGE,
            content_hash=hashlib.sha256(PAGE.encode()).hexdigest()))
        await db.commit()
    app = FastAPI(); app.include_router(knowledge.router, prefix='/api/knowledge')
    async def database():
        async with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            yield client, factory, path, sha
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_pdf_citation_returns_verified_page_context_and_version_locked_original(tmp_path):
    async with source_client(tmp_path) as (client, _, path, sha):
        response = await client.get('/api/knowledge/documents/1/evidence', params={'version_id': sha, 'page': 1, 'quote': 'Check the hardware first.'})
        assert response.status_code == 200, response.text
        assert response.headers.get('cache-control') == 'no-store'
        data = response.json()
        assert data['text'] == PAGE and data['page'] == 1
        assert data['quote'] == 'Check the hardware first.'
        assert data['verification'] == {'source': 'hash_verified', 'extraction': 'hash_verified', 'quote': 'matched'}
        assert data['preview_url'] == f'/api/knowledge/documents/1/preview?version_id={sha}#page=1'
        preview = await client.get(data['preview_url'])
        assert preview.status_code == 200 and preview.content == path.read_bytes()
        assert preview.headers.get('cache-control') == 'no-store'


@pytest.mark.asyncio
@pytest.mark.parametrize('suffix', ['.docx', '.xlsx'])
async def test_non_pdf_chunk_locator_keeps_real_source_ref_without_fake_pdf_page(tmp_path, suffix):
    async with source_client(tmp_path, suffix) as (client, _, _, sha):
        response = await client.get('/api/knowledge/documents/1/evidence', params={'version_id': sha, 'chunk_id': 1})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['source_ref'] == 'Sheet1!第5行' and data['page'] is None
        assert data['chunk_id'] == 1 and data['text'] == PAGE
        assert data['verification']['quote'] == 'not_requested'
        assert '#page' not in data['preview_url']


@pytest.mark.asyncio
@pytest.mark.parametrize('failure,expected', [('file',409), ('extraction',409), ('chunk',409), ('version',409), ('quote',422), ('page',404), ('retired',404), ('missing',410)])
async def test_invalid_or_changed_citation_never_opens_the_current_file_silently(tmp_path, failure, expected):
    async with source_client(tmp_path) as (client, factory, path, sha):
        params = {'version_id': sha, 'page': 1, 'quote': 'Check the hardware first.'}
        if failure == 'file': path.write_bytes(b'replaced')
        if failure == 'missing': path.unlink()
        if failure == 'version': params['version_id'] = 'a' * 64
        if failure == 'quote': params['quote'] = 'Unsupported invented original quote.'
        if failure == 'page': params['page'] = 2
        async with factory() as db:
            if failure == 'extraction': await db.execute(text("UPDATE knowledge_document_extractions SET source_sha256=:sha"), {'sha': 'b'*64})
            if failure == 'chunk': await db.execute(text("UPDATE knowledge_document_chunks SET content='tampered extraction'"))
            if failure == 'retired': await db.execute(text("UPDATE knowledge_documents SET source_status='archived'"))
            await db.commit()
        response = await client.get('/api/knowledge/documents/1/evidence', params=params)
        assert response.status_code == expected, response.text
        assert str(path) not in response.text
        if failure in {'file','version','missing','retired'}:
            response = await client.get('/api/knowledge/documents/1/preview', params={'version_id': params['version_id']})
            assert response.status_code == expected


@pytest.mark.asyncio
@pytest.mark.parametrize('params', [{}, {'version_id': 'bad', 'page': 1}, {'page': 1}, {'page': 0}, {'page': 1, 'chunk_id': 1}, {'chunk_id': -1}])
async def test_location_and_version_are_explicit_not_guessed(tmp_path, params):
    async with source_client(tmp_path) as (client, _, _, sha):
        if params and 'version_id' not in params and params != {'page': 1}:
            params = {'version_id': sha, **params}
        response = await client.get('/api/knowledge/documents/1/evidence', params=params)
        assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_candidate_locator_carries_source_version_and_excludes_stale_extractions(tmp_path):
    from app.services.knowledge_content import find_candidate_evidence
    from app.services.knowledge_qa import normalize_question
    from app.schemas.knowledge import KnowledgeCandidateEvidence
    async with source_client(tmp_path, '.xlsx') as (_, factory, _, sha):
        async with factory() as db:
            await db.execute(text('UPDATE knowledge_document_chunks SET normalized_content=:value'), {'value': normalize_question(PAGE)})
            await db.commit()
            candidates = await find_candidate_evidence(db, 'needle gain')
            assert candidates
            item = KnowledgeCandidateEvidence(**candidates[0]).model_dump()
            assert item['version_id'] == sha and item['chunk_id'] == 1
            await db.execute(text('UPDATE knowledge_document_extractions SET source_sha256=:sha'), {'sha': 'b'*64})
            await db.commit()
            assert not await find_candidate_evidence(db, 'needle gain')

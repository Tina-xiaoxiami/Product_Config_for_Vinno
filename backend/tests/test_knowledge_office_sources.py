"""Synthetic Office citations bind original package structure, never PDF pages."""
from contextlib import asynccontextmanager
import hashlib
from io import BytesIO

import httpx
import pytest
from docx import Document
from fastapi import FastAPI
from openpyxl import Workbook
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import knowledge
from app.api.knowledge_document_answer import router as answer_router
from app.database import Base, get_db
from app.models import ProductModel, ProductSeries
from app.models.knowledge import KnowledgeDocument
from app.services import knowledge_document_answer


@asynccontextmanager
async def office_client(tmp_path, suffix):
    path = tmp_path / ('synthetic' + suffix)
    if suffix == '.docx':
        document = Document()
        document.add_paragraph('')
        document.add_heading('规格说明', level=1)
        document.add_paragraph('段落中的原始功能描述，保留条件。')
        table = document.add_table(rows=2, cols=3)
        table.cell(0, 0).text = '项目'
        table.cell(0, 2).text = '数值'
        table.cell(1, 0).text = '针增益'
        table.cell(1, 2).text = '2.5 mm'
        document.add_paragraph('表格之后的原文段落。')
        document.save(path)
    else:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = '规格 表'
        sheet['A5'] = '电池规格'
        sheet['C5'] = '300 mAh'
        sheet['E5'] = '=SUM(1,1)'
        workbook.create_sheet('其他').cell(5, 3, '另一工作表的原文')
        stream = BytesIO(); workbook.save(stream); workbook.close()
        path.write_bytes(stream.getvalue())
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "office.db"}')
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db.add(ProductSeries(id=1, name='Office-China'))
        db.add(ProductModel(id=1, series_id=1, name='VINNO 6'))
        db.add(KnowledgeDocument(id=1, document_type='manual', title='合成Office资料',
            file_name=path.name, file_path=str(path), sha256=sha, source_status='active',
            market='domestic', country='CN', product_series='VINNO 6', version='1.14.81'))
        await db.commit()
    app = FastAPI(); app.include_router(knowledge.router, prefix='/api/knowledge')
    app.include_router(answer_router, prefix='/api/knowledge')
    async def database():
        async with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            yield client, factory, path, sha
    finally:
        await engine.dispose()


async def extract(client):
    response = await client.post('/api/knowledge/documents/1/extract')
    assert response.status_code == 200, response.text
    return response.json()


async def chunk_for(factory, phrase):
    async with factory() as db:
        return (await db.execute(text('SELECT id FROM knowledge_document_chunks WHERE content LIKE :phrase ORDER BY chunk_index LIMIT 1'),
            {'phrase': '%' + phrase + '%'})).scalar_one()


@pytest.mark.asyncio
async def test_docx_paragraph_and_table_return_original_body_positions_from_registered_bytes(tmp_path):
    async with office_client(tmp_path, '.docx') as (client, factory, path, sha):
        await extract(client)
        for phrase, kind, body, extra in [('段落中的', 'paragraph', 3, {'paragraph_index':3}),
                ('2.5 mm', 'table_row',4, {'table_index':1,'row_index':2}),
                ('表格之后', 'paragraph',5, {'paragraph_index':4})]:
            chunk = await chunk_for(factory, phrase)
            response = await client.get('/api/knowledge/documents/1/evidence', params={'version_id':sha,'chunk_id':chunk})
            assert response.status_code == 200, response.text
            data = response.json(); locator = data['locator']
            assert locator['schema_version'] == 1 and locator['format'] == 'docx' and locator['kind'] == kind
            assert locator['body_index'] == body and locator['part'] == 'word/document.xml'
            assert all(locator[k] == value for k, value in extra.items())
            assert locator['document_id'] == 1 and locator['source_sha256'] == sha
            assert data['page'] is None and '#page' not in data['preview_url']
            assert data['verification']['structure'] == 'matched'
            assert data['verification']['visual'] == 'not_checked'
            assert data['model_answer_eligible'] is False
        preview = await client.get(data['preview_url'])
        assert preview.status_code == 200 and preview.content == path.read_bytes()


@pytest.mark.asyncio
async def test_xlsx_citation_retains_sheet_and_real_cell_addresses_and_uncomputed_formula(tmp_path):
    async with office_client(tmp_path, '.xlsx') as (client, factory, path, sha):
        await extract(client); chunk = await chunk_for(factory, '300 mAh')
        response = await client.get('/api/knowledge/documents/1/evidence',params={'version_id':sha,'chunk_id':chunk,'quote':'300 mAh'})
        assert response.status_code == 200, response.text
        data = response.json(); locator = data['locator']
        assert locator['format'] == 'xlsx' and locator['kind'] == 'worksheet_row'
        assert locator['sheet_name'] == '规格 表' and locator['sheet_index'] == 1 and locator['row_index'] == 5
        assert locator['range'] == 'A5:E5' and locator['document_id'] == 1 and locator['source_sha256'] == sha
        assert [cell['cell'] for cell in locator['cells']] == ['A5','C5','E5']
        assert locator['cells'][1]['text'] == '300 mAh'
        assert locator['cells'][2]['value_type'] == 'formula' and locator['cells'][2]['formula_state'] == 'not_evaluated'
        assert '=SUM(1,1)' in data['text']
        assert data['verification']['quote'] == 'matched' and data['verification']['structure'] == 'matched'
        assert data['verification']['visual'] == 'not_checked' and data['model_answer_eligible'] is False
        assert data['page'] is None and '#page' not in data['preview_url']
        assert response.headers['cache-control'] == 'no-store'
        second = await chunk_for(factory, '另一工作表')
        located = (await client.get('/api/knowledge/documents/1/evidence',params={'version_id':sha,'chunk_id':second})).json()
        assert located['locator']['sheet_name'] == '其他' and located['locator']['sheet_index'] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('suffix',['.docx','.xlsx'])
@pytest.mark.parametrize('change',['content_and_hash','source_ref','chunk_index','extractor_version','original'])
async def test_office_structure_is_replayed_not_trusted_from_an_old_or_forged_index(tmp_path,suffix,change):
    async with office_client(tmp_path,suffix) as (client,factory,path,sha):
        await extract(client); chunk = await chunk_for(factory,'段落中的' if suffix=='.docx' else '300 mAh')
        async with factory() as db:
            if change == 'content_and_hash':
                forged='这不是原文中的内容，请拒绝伪造的结构引用。'
                await db.execute(text('UPDATE knowledge_document_chunks SET content=:content,content_hash=:sha WHERE id=:id'),
                    {'content':forged,'sha':hashlib.sha256(forged.encode()).hexdigest(),'id':chunk})
            if change == 'source_ref': await db.execute(text("UPDATE knowledge_document_chunks SET source_ref='伪造的单元格Z99' WHERE id=:id"),{'id':chunk})
            if change == 'chunk_index': await db.execute(text('UPDATE knowledge_document_chunks SET chunk_index=999 WHERE id=:id'),{'id':chunk})
            if change == 'extractor_version': await db.execute(text("UPDATE knowledge_document_extractions SET extractor_version='2' WHERE document_id=1"))
            await db.commit()
        if change == 'original': path.write_bytes(b'changed original')
        response = await client.get('/api/knowledge/documents/1/evidence',params={'version_id':sha,'chunk_id':chunk})
        assert response.status_code == 409, response.text
        assert str(path) not in response.text and 'locator' not in response.json()


@pytest.mark.asyncio
async def test_old_xls_is_explicitly_unsupported_and_mime_does_not_enable_xlsx_parser(tmp_path):
    async with office_client(tmp_path,'.xls') as (client,factory,_,_):
        async with factory() as db:
            await db.execute(text("UPDATE knowledge_documents SET mime_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' WHERE id=1"))
            await db.commit()
        response=await client.post('/api/knowledge/documents/1/extract')
        assert response.status_code==422 and 'XLS' in response.text


@pytest.mark.asyncio
async def test_office_locators_cannot_be_used_as_pdf_pages_or_arbitrary_paths(tmp_path):
    async with office_client(tmp_path,'.xlsx') as (client,factory,path,sha):
        await extract(client)
        response=await client.get('/api/knowledge/documents/1/evidence',params={'version_id':sha,'page':1})
        assert response.status_code==422
        response=await client.get('/api/knowledge/documents/999/evidence',params={'version_id':sha,'chunk_id':1,'file_path':str(path)})
        assert response.status_code==404


@pytest.mark.asyncio
async def test_office_is_not_added_to_production_model_answers_by_the_locator_contract(tmp_path,monkeypatch):
    def forbidden(*args,**kwargs): pytest.fail('Office contract enabled a paid model')
    async def no_history(*args,**kwargs): return {'chains':[],'source_documents':[]}
    monkeypatch.setattr(knowledge_document_answer,'run_shared_evidence',forbidden)
    monkeypatch.setattr(knowledge_document_answer,'trace_release_history',no_history)
    async with office_client(tmp_path,'.docx') as (client,factory,_,_):
        await extract(client)
        response=await client.post('/api/knowledge/document-answer',json={'question':'段落中的功能描述是什么？',
            'scope':{'market':'domestic','product_model_id':1,'software_version':'1.14.81'}})
        assert response.status_code==200 and response.json()['status']=='no_evidence'
        assert response.json()['metrics']['model_calls']==0
        async with factory() as db:
            assert (await db.execute(text('SELECT count(*) FROM knowledge_answers'))).scalar()==0

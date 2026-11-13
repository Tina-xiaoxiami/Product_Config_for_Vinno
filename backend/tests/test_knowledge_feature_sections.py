"""Feature sections reuse indexed DOCX headings, with the normal evidence scope."""
import hashlib

import pytest
from app.models.knowledge import KnowledgeDocument, KnowledgeDocumentChunk, KnowledgeDocumentExtraction
from app.services.knowledge_content import find_candidate_evidence
from app.services.knowledge_feature_detail import feature_detail
from app.services.knowledge_qa import normalize_question
from app.services.knowledge_scope import resolve_query_scope
from test_knowledge_parameters import client_for
from test_knowledge_feature_detail import seed, SCOPE

async def sections(factory):
    async with factory() as db:
        for doc_id, version, source_hash, suffix in [(1, '1.14.80', 'a'*64, 'docx'), (2, '1.14.90', 'a'*64, 'docx'), (3, '1.14.80', 'b'*64, 'docx'), (4, '1.14.80', 'a'*64, 'xlsx')]:
            db.add(KnowledgeDocument(id=doc_id, document_type='whitepaper', title=f'资料{doc_id}', file_name=f'source{doc_id}.{suffix}', file_path=f'/synthetic/{doc_id}.{suffix}', version=version, market='domestic', product_series='VINNO 6', sha256='a'*64))
            db.add(KnowledgeDocumentExtraction(document_id=doc_id, extractor_version='test', source_sha256=source_hash, status='completed', chunk_count=4))
            for index, (section, content) in enumerate([('VATT', 'VATT'), ('VATT', '支持单帧及多帧连续测量'), ('VShear', '支持可信度图显示'), ('NVATT2', '其他对象内容')]):
                db.add(KnowledgeDocumentChunk(id=doc_id*10+index,document_id=doc_id,chunk_index=index,section_name=section,source_ref=f'段落{index+1} · {section}',content=content,normalized_content=normalize_question(content),content_hash=hashlib.sha256(content.encode()).hexdigest()))
        await db.commit()

@pytest.mark.asyncio
async def test_detail_includes_same_heading_body_but_not_adjacent_or_unscoped_content(tmp_path):
    async with client_for(tmp_path) as (_, factory):
        await seed(factory)
        await sections(factory)
        async with factory() as db:
            result = await feature_detail(db,1,scope=SCOPE,configuration_version_id=1)
            ids={row['chunk_id'] for row in result['citations']}
            assert 11 in ids, '同标题正文必须可见，不能只有标题'
            assert ids.isdisjoint({12,13,20,21,30,31,41}), ids
            body=next(row for row in result['citations'] if row['chunk_id']==11)
            assert body['excerpt']=='支持单帧及多帧连续测量'
            assert body['source_ref']=='段落2 · VATT' and body['version_id']=='a'*64

@pytest.mark.asyncio
async def test_opt_in_heading_context_does_not_change_plain_question_search(tmp_path):
    async with client_for(tmp_path) as (_, factory):
        await sections(factory)
        async with factory() as db:
            scope=await resolve_query_scope(db,SCOPE)
            plain=await find_candidate_evidence(db,'VATT',scope=scope,limit=50)
            expanded=await find_candidate_evidence(db,'VATT',scope=scope,limit=50,include_section_context=True)
            assert 11 not in {row['chunk_id'] for row in plain}
            assert 11 in {row['chunk_id'] for row in expanded}
            assert 41 not in {row['chunk_id'] for row in expanded}
            assert all('section_name' not in row for row in plain)

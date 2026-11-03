from unittest.mock import patch

import pytest

from app.services.knowledge_content import ExtractedBlock
from app.services.registration_file_preview import preview_certificate, preview_difference
from test_registration_import import _write_registration_workbook


def test_certificate_preview_extracts_only_unique_labeled_values(tmp_path):
    path = tmp_path / 'certificate.pdf'
    path.touch()
    text = '注册证编号：湘械注准20222062053\n注册日期：2022年8月19日\n有效期至：2027年8月18日'
    with patch('app.services.registration_file_preview._pdf_blocks', return_value=[ExtractedBlock(text, '第1页', 1)]):
        result = preview_certificate(path)
    assert result['fields']['registration_number'] == '湘械注准20222062053'
    assert result['fields']['effective_date'] == '2022-08-19'
    assert result['evidence']['registration_number'] == '第1页'


def test_certificate_preview_does_not_guess_ambiguous_or_unlabeled_dates(tmp_path):
    path = tmp_path / 'certificate.pdf'
    path.touch()
    text = '注册证编号：湘械注准20222062053\n注册证编号：湘械注准20222062054\n有效期至：2027年8月18日'
    with patch('app.services.registration_file_preview._pdf_blocks', return_value=[ExtractedBlock(text, '第1页', 1)]):
        result = preview_certificate(path)
    assert result['fields'] == {}
    assert result['warnings']


def test_difference_preview_uses_existing_workbook_parser(tmp_path):
    path = tmp_path / 'difference.xlsx'
    _write_registration_workbook(path)
    result = preview_difference(path)
    assert result['model_count'] > 0
    assert result['probe_count'] > 0


@pytest.mark.asyncio
async def test_file_preview_endpoint_uses_upload_without_creating_a_draft(tmp_path):
    import httpx
    from fastapi import FastAPI
    from app.api.registration import router

    path = tmp_path / 'difference.xlsx'
    _write_registration_workbook(path)
    app = FastAPI()
    app.include_router(router, prefix='/api/registrations')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/api/registrations/packages/file-preview', data={'kind': 'difference'}, files={'file': ('difference.xlsx', path.read_bytes())})
        assert response.status_code == 200
        assert response.json()['model_count'] > 0
        bad = await client.post('/api/registrations/packages/file-preview', data={'kind': 'certificate'}, files={'file': ('bad.xlsx', b'bad')})
        assert bad.status_code == 400


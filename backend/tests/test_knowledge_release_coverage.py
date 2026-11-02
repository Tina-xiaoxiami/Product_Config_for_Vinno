"""Coverage inventories configured sources without importing or assuming release continuity."""
from contextlib import closing
import hashlib
import sqlite3

import pytest

from test_knowledge_release_history import database, _client, _document, _trace, SCOPE


def configure(monkeypatch, tmp_path, **overrides):
    from app.services import knowledge_release_coverage as coverage
    config = {'RELEASE_NOTE_ROOT': str(tmp_path / 'releases'), 'SOURCE_ROOTS': [],
              'CONTROLLED_EXTRACTION_ROOTS': [], 'CONTROLLED_MATERIALS_ROOT': None, **overrides}
    monkeypatch.setattr(coverage, 'load_release_workbench_config', lambda **kwargs: config)
    return coverage, config


def write(root, name, content=b'new release'):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


@pytest.mark.asyncio
async def test_inventory_exposes_unregistered_and_unrecognized_without_inventing_versions(database, tmp_path, monkeypatch):
    _, config = configure(monkeypatch, tmp_path)
    root = tmp_path / 'releases'
    write(root, '1.14.81/V系列 Rlease Note_1.14.81.pdf')
    _document(database, 22, '1.14.80', 'Release Note 1.14.80\n自动测量功能适用于V6。')
    before = database.read_bytes()
    client, engine = await _client(database)
    # The fixture client changes the test model name; take the read-only snapshot after setup.
    before = database.read_bytes()
    async with client:
        response = await client.post('/api/knowledge/release-history/coverage', json={'scope': SCOPE})
        assert response.status_code == 200, response.text
        report = response.json()
        assert report['completeness'] == 'gaps_found'
        pending = next(item for item in report['items'] if item['file_name'].endswith('1.14.81.pdf'))
        assert pending['registration_status'] == 'unregistered'
        assert pending['language'] == 'unknown' and pending['applicability_status'] == 'unrecognized'
        old = next(item for item in report['items'] if 22 in item['document_ids'])
        assert old['applicability_status'] == 'unrecognized'
        assert all(item['version'] != '1.14.79' for item in report['items'])
    await engine.dispose()
    assert database.read_bytes() == before


@pytest.mark.asyncio
async def test_future_and_explicit_other_model_are_retained_but_not_current_gaps(database, tmp_path, monkeypatch):
    configure(monkeypatch, tmp_path)
    (tmp_path / 'releases').mkdir()
    _document(database, 10, '1.14.90', '1.14.90(VINNO6)\nRelease Note')
    _document(database, 11, '1.14.60', '1.14.60(VINNO10)\nRelease Note')
    client, engine = await _client(database)
    async with client:
        report = (await client.post('/api/knowledge/release-history/coverage', json={'scope': SCOPE})).json()
        future = next(row for row in report['items'] if 10 in row['document_ids'])
        other = next(row for row in report['items'] if 11 in row['document_ids'])
        assert future['range_status'] == 'after_target'
        assert other['applicability_status'] == 'not_applicable'
        assert not future['is_gap'] and not other['is_gap']
    await engine.dispose()


def test_scanner_hash_identity_nested_files_and_safe_boundaries(tmp_path, monkeypatch):
    coverage, config = configure(monkeypatch, tmp_path)
    root = tmp_path / 'releases'
    write(root, '1.2/Release Note.pdf', b'one')
    write(root, '1.3/Release Note.pdf', b'two')
    write(root, 'nested/Rlease Note copy.pdf', b'one')
    write(root, '.hidden/Release Note.pdf')
    write(root, '~$Release Note.docx')
    write(root, 'legacy/Release Note.doc')
    outside = write(tmp_path, 'outside.pdf')
    (root / 'Release Note-link.pdf').symlink_to(outside)
    result = coverage.scan_configured_sources(config)
    assert len(result['files']) == 4
    assert len({row['sha256'] for row in result['files']}) == 3
    assert result['roots'][0]['status'] == 'scanned'
    broad = tmp_path / 'broad'
    write(broad, 'unrelated.pdf')
    write(broad, 'release note/nested/file.pdf')
    result = coverage.scan_configured_sources({'SOURCE_ROOTS': [str(broad)]})
    assert len(result['files']) == 1


@pytest.mark.parametrize('mode,expected', [('missing','missing'),('denied','error')])
def test_scanner_reports_root_failures(tmp_path, monkeypatch, mode, expected):
    coverage, config = configure(monkeypatch, tmp_path)
    if mode == 'denied':
        root = tmp_path / 'releases'
        root.mkdir()
        monkeypatch.setattr(coverage.os, 'scandir', lambda path: (_ for _ in ()).throw(PermissionError('denied')))
    report = coverage.scan_configured_sources(config)
    assert report['roots'][0]['status'] == expected


@pytest.mark.asyncio
async def test_same_hash_keeps_every_registration_quality_and_missing_controlled_file(database, tmp_path, monkeypatch):
    configure(monkeypatch, tmp_path)
    (tmp_path / 'releases').mkdir()
    content = '1.14.61(VINNO6)\nRelease Note'
    _document(database, 10, '1.14.61', content)
    _document(database, 11, '1.14.61', content)
    with closing(sqlite3.connect(database)) as connection, connection:
        first = connection.execute('SELECT file_path,sha256 FROM knowledge_documents WHERE id=10').fetchone()
        connection.execute("UPDATE knowledge_documents SET file_path=?,sha256=? WHERE id=11", first)
        connection.execute("UPDATE knowledge_document_extractions SET status='stale' WHERE document_id=11")
    client, engine = await _client(database)
    async with client:
        report = (await client.post('/api/knowledge/release-history/coverage', json={})).json()
        item = next(row for row in report['items'] if 10 in row['document_ids'])
        assert {10,11} <= set(item['document_ids'])
        assert item['extraction_status'] == 'stale' and item['is_gap']
        assert any('11' in issue['reason'] for issue in item['issues'])
        from pathlib import Path
        Path(first[0]).unlink()
        report = (await client.post('/api/knowledge/release-history/coverage', json={})).json()
        item = next(row for row in report['items'] if 10 in row['document_ids'])
        assert any(issue['code'] == 'source_unavailable' for issue in item['issues'])
        assert item['is_gap']
    await engine.dispose()


@pytest.mark.asyncio
async def test_api_forbids_paths_and_partial_scope_and_reports_unconfigured(database, tmp_path, monkeypatch):
    configure(monkeypatch, tmp_path, RELEASE_NOTE_ROOT=None)
    client, engine = await _client(database)
    async with client:
        assert (await client.post('/api/knowledge/release-history/coverage', json={'path':'/tmp'})).status_code == 422
        assert (await client.post('/api/knowledge/release-history/coverage', json={'scope':{'software_version':'1.14.81'}})).status_code == 422
        report = (await client.post('/api/knowledge/release-history/coverage', json={})).json()
        assert report['scan_status'] == 'not_configured' and report['completeness'] != 'no_known_gaps'
        trace = await _trace(client)
        assert trace['coverage']['completeness'] == 'unverified'
        assert '已登记' in trace['coverage']['coverage_message']
    await engine.dispose()

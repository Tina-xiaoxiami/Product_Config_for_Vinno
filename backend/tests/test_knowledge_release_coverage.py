"""Coverage inventories configured sources without importing or assuming release continuity."""
from contextlib import closing
from pathlib import Path
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
        other = Path(connection.execute('SELECT file_path FROM knowledge_documents WHERE id=11').fetchone()[0])
        other.write_bytes(Path(first[0]).read_bytes())
        connection.execute("UPDATE knowledge_documents SET sha256=? WHERE id=11", (first[1],))
        connection.execute("UPDATE knowledge_document_extractions SET status='stale' WHERE document_id=11")
    client, engine = await _client(database)
    async with client:
        report = (await client.post('/api/knowledge/release-history/coverage', json={})).json()
        item = next(row for row in report['items'] if 10 in row['document_ids'])
        assert {10,11} <= set(item['document_ids'])
        assert item['extraction_status'] == 'stale' and item['is_gap']
        assert any('11' in issue['reason'] for issue in item['issues'])
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


@pytest.mark.asyncio
async def test_valid_source_resolves_filename_typo_without_blocking_complete_inventory(database, tmp_path, monkeypatch):
    controlled = tmp_path / 'controlled'
    raw = tmp_path / 'release note'
    configure(monkeypatch, tmp_path, RELEASE_NOTE_ROOT=None, CONTROLLED_MATERIALS_ROOT=str(controlled), SOURCE_ROOTS=[str(raw)])
    _document(database, 10, '1.14.80', '1.14.80(VINNO6)\nRelease Note', country=None, market='unspecified')
    with closing(sqlite3.connect(database)) as connection, connection:
        old = Path(connection.execute('SELECT file_path FROM knowledge_documents WHERE id=10').fetchone()[0])
        new = write(controlled, '发布记录/1.14.80/Release Note_1.4.80.pdf', old.read_bytes())
        write(raw, 'Release Note_1.14.80_压缩副本.pdf', old.read_bytes())
        connection.execute('UPDATE knowledge_documents SET file_path=? WHERE id=10', (str(new),))
        connection.execute('DELETE FROM knowledge_document_chunks WHERE document_id!=10')
        connection.execute('DELETE FROM knowledge_document_extractions WHERE document_id!=10')
        connection.execute('DELETE FROM knowledge_documents WHERE id!=10')
    client, engine = await _client(database)
    async with client:
        report = (await client.post('/api/knowledge/release-history/coverage', json={'scope': {**SCOPE,'software_version':'1.14.80'}})).json()
        item = report['items'][0]
        assert item['version']=='1.14.80' and item['version_basis']=='source_extract'
        assert any(issue['code']=='candidate_version_mismatch' for issue in item['issues'])
        assert any(issue['code']=='source_alias_label' for issue in item['issues'])
        assert not any(issue['code']=='release_qualification_unverified' for issue in item['issues'])
        assert not item['is_gap']
        assert report['completeness']=='no_known_gaps' and report['totals']['ready']==1
    await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_and_candidate_version_conflicts_remain_visible_without_filename_country_inference(database, tmp_path, monkeypatch):
    configure(monkeypatch, tmp_path)
    write(tmp_path / 'releases', '1.14.80/CN_Release Note_1.14.81.doc')
    client, engine = await _client(database)
    async with client:
        report = (await client.post('/api/knowledge/release-history/coverage', json={})).json()
        item = next(row for row in report['items'] if row['file_name'].endswith('.doc'))
        assert item['extraction_status']=='unsupported' and item['version'] is None
        assert item['language']=='unknown'
        assert any(issue['code']=='candidate_version_conflict' for issue in item['issues'])
        assert report['scope'] is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_extraction_roots_are_original_sources_not_controlled_copies(database, tmp_path, monkeypatch):
    raw = tmp_path / 'raw release note'
    configure(monkeypatch, tmp_path, RELEASE_NOTE_ROOT=None, CONTROLLED_EXTRACTION_ROOTS=[str(raw)])
    _document(database, 10, '1.14.61', '1.14.61(VINNO6)\nRelease Note')
    with closing(sqlite3.connect(database)) as connection:
        original = Path(connection.execute('SELECT file_path FROM knowledge_documents WHERE id=10').fetchone()[0])
    write(raw, 'Release Note.pdf', original.read_bytes())
    client, engine = await _client(database)
    async with client:
        report = (await client.post('/api/knowledge/release-history/coverage', json={})).json()
        item = next(row for row in report['items'] if 10 in row['document_ids'])
        assert any(issue['code']=='uncontrolled' for issue in item['issues'])
        assert item['is_gap']
    await engine.dispose()


@pytest.mark.asyncio
async def test_target_model_source_conflict_is_unresolved_gap_not_other_model(database, tmp_path, monkeypatch):
    controlled = tmp_path / 'controlled'
    configure(monkeypatch, tmp_path, RELEASE_NOTE_ROOT=None, CONTROLLED_MATERIALS_ROOT=str(controlled))
    _document(database, 10, '1.14.65', '1.14.61(VINNO6)\n1.14.65(VINNO6)')
    with closing(sqlite3.connect(database)) as connection, connection:
        original = Path(connection.execute('SELECT file_path FROM knowledge_documents WHERE id=10').fetchone()[0])
        controlled_file = write(controlled, '发布记录/Release Note.pdf', original.read_bytes())
        connection.execute('UPDATE knowledge_documents SET file_path=? WHERE id=10', (str(controlled_file),))
        connection.execute('DELETE FROM knowledge_document_chunks WHERE document_id!=10')
        connection.execute('DELETE FROM knowledge_document_extractions WHERE document_id!=10')
        connection.execute('DELETE FROM knowledge_documents WHERE id!=10')
    client, engine = await _client(database)
    async with client:
        report = (await client.post('/api/knowledge/release-history/coverage', json={'scope': SCOPE})).json()
        item = report['items'][0]
        assert item['applicability_status']=='unrecognized'
        assert item['is_gap']
        assert any(issue['code']=='source_fact_conflict' for issue in item['issues'])
        assert report['completeness']=='gaps_found'
        assert report['totals']['ready']==0 and report['totals']['gaps']==1 and report['totals']['unresolved']==1
    await engine.dispose()

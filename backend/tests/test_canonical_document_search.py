"""Canonical file registration feeds search without rewriting tracker evidence."""
import sqlite3

import pytest

from tracker.database import Database
from tracker.services.search_index import SearchIndex, file_sha256
from tracker.services.unified_search import (
    refresh_search_index, resolve_source_candidate, sync_search_roots_and_metadata,
    search_source_coverage, unified_search,
)


def catalog_case(tmp_path):
    root = tmp_path / 'materials'
    root.mkdir()
    path = root / 'note.txt'
    path.write_text('CanonicalNeedle actual source content', encoding='utf-8')
    canonical = tmp_path / 'canonical.db'
    with sqlite3.connect(canonical) as connection:
        connection.execute('''CREATE TABLE knowledge_documents (
            id INTEGER PRIMARY KEY, title TEXT, document_type TEXT, file_path TEXT,
            version TEXT, market TEXT, product_series TEXT, sha256 TEXT, source_status TEXT)''')
        connection.execute('''INSERT INTO knowledge_documents VALUES (
            1, 'Canonical Note', 'release_note', ?, '1.14.81', 'domestic', 'VINNO 10', ?, 'active')''',
            (str(path), file_sha256(path)))
    tracker = Database(tmp_path / 'tracker.db')
    tracker.initialize()
    index = SearchIndex(tmp_path / 'index.db')
    roots = dict(materials_root=root, training_root=None, canonical_database=canonical)
    return tracker, index, canonical, path, roots


def search(tracker, index, canonical):
    return unified_search(tracker, index, None, query='CanonicalNeedle', sources={'controlled'},
                          canonical_database=canonical)


def test_canonical_only_registration_is_indexed_classified_and_previewable(tmp_path):
    tracker, index, canonical, path, roots = catalog_case(tmp_path)
    refreshed = refresh_search_index(tracker, index, **roots)
    assert refreshed['indexed'] == 1 and not refreshed['source_errors'].get('controlled')
    result = search(tracker, index, canonical)
    assert result['total'] == 1
    item = result['results'][0]
    assert item['source_group'] == 'release_note' and item['verification'] == 'unverified'
    assert item['canonical_document_id'] == 1
    assert resolve_source_candidate(tracker, item['preview_id'], **roots)['path'] == path
    assert index.preview(item['preview_id'])['chunks'][0]['text'] == 'CanonicalNeedle actual source content'
    assert tracker.list_documents() == []


def test_duplicate_tracker_aliases_share_one_search_hit_and_keep_previews(tmp_path):
    tracker, index, canonical, path, roots = catalog_case(tmp_path)
    aliases = []
    for number in (1, 2):
        doc = tracker.add_document('Canonical Note', doc_type='发布记录', model_scope='VINNO 10')
        version = tracker.add_document_version(doc, version_label='1.14.81', path_pdf=str(path), sha256=file_sha256(path))
        aliases.append(f'controlled:{version}:pdf')
    before = tracker.list_documents()
    refresh_search_index(tracker, index, **roots)
    result = search(tracker, index, canonical)
    assert result['total'] == 1 and result['source_counts']['controlled'] == 1
    for alias in aliases:
        assert resolve_source_candidate(tracker, alias, **roots)['path'] == path
        assert index.preview(alias) is not None
    assert search_source_coverage(tracker, index, **roots)['controlled']['registered_files'] == 1
    assert tracker.list_documents() == before


def test_canonical_archive_blocks_tracker_aliases_and_old_search_index(tmp_path):
    tracker, index, canonical, path, roots = catalog_case(tmp_path)
    doc = tracker.add_document('Canonical Note', doc_type='发布记录')
    version = tracker.add_document_version(doc, path_pdf=str(path), sha256=file_sha256(path))
    refresh_search_index(tracker, index, **roots)
    with sqlite3.connect(canonical) as connection:
        connection.execute("UPDATE knowledge_documents SET source_status='archived'")
    # Even callers that have not run maintenance cannot search the archived file.
    assert search(tracker, index, canonical)['total'] == 0
    assert resolve_source_candidate(tracker, f'controlled:{version}:pdf', **roots) is None
    sync_search_roots_and_metadata(tracker, index, **roots)
    assert search(tracker, index, canonical)['total'] == 0
    assert len(tracker.list_document_versions(doc)) == 1


def test_tracker_archived_records_are_not_candidates_without_canonical_bridge(tmp_path):
    tracker, index, _, path, roots = catalog_case(tmp_path)
    roots.pop('canonical_database')
    doc = tracker.add_document('Old note', doc_type='发布记录')
    version = tracker.add_document_version(doc, path_pdf=str(path), sha256=file_sha256(path))
    with tracker.connect() as connection:
        connection.execute("UPDATE kh_documents SET status='archived' WHERE id=?", (doc,))
    refresh_search_index(tracker, index, **roots)
    assert resolve_source_candidate(tracker, f'controlled:{version}:pdf', **roots) is None


def test_unavailable_canonical_registry_fails_closed_without_erasing_alias_index(tmp_path):
    tracker, index, canonical, path, roots = catalog_case(tmp_path)
    refresh_search_index(tracker, index, **roots)
    with sqlite3.connect(index.path) as connection:
        source_ids = {row[0] for row in connection.execute('SELECT source_id FROM search_sources')}
    canonical.rename(canonical.with_suffix('.offline'))
    refreshed = refresh_search_index(tracker, index, **roots)
    assert 'controlled' in refreshed['source_errors']
    with sqlite3.connect(index.path) as connection:
        assert {row[0] for row in connection.execute('SELECT source_id FROM search_sources')} == source_ids
    result = search(tracker, index, canonical)
    assert result['total'] == 0 and 'controlled' in result['source_errors']


def test_integrated_app_reads_canonical_registry_for_search_preview_and_lifecycle(tmp_path):
    from tracker.app import create_app
    from app.integrations.release_workbench import close_release_workbench
    tracker, index, canonical, path, roots = catalog_case(tmp_path)
    app = create_app({'TESTING': True, 'INTEGRATED_MODE': True,
                     'DATABASE_PATH': tracker.path, 'SEARCH_INDEX_PATH': index.path,
                     'PRODUCT_CONFIG_DATABASE': canonical,
                     'CONTROLLED_MATERIALS_ROOT': path.parent, 'TRAINING_ROOT': None,
                     'RELEASE_NOTE_ROOT': None, 'SOURCE_ROOTS': [], 'CONTROLLED_EXTRACTION_ROOTS': []})
    client = app.test_client()
    try:
        assert client.post('/api/v1/workbench/search-index/refresh', json={}).status_code == 200
        response = client.get('/api/v1/workbench/search', query_string={'q': 'CanonicalNeedle', 'sources': 'controlled'})
        assert response.status_code == 200
        result = response.get_json()['data']
        assert result['total'] == 1 and result['results'][0]['canonical_document_id'] == 1
        preview = '/api/v1/workbench/search-index/sources/canonical:1:file/preview'
        assert client.get(preview).status_code == 200
        with sqlite3.connect(canonical) as connection:
            connection.execute("UPDATE knowledge_documents SET source_status='archived'")
        assert client.get('/api/v1/workbench/search', query_string={'q': 'CanonicalNeedle', 'sources': 'controlled'}).get_json()['data']['total'] == 0
        assert client.get(preview).status_code == 404
        canonical.rename(canonical.with_suffix('.offline'))
        assert client.get(preview).status_code == 503
    finally:
        close_release_workbench(app)


def test_canonical_coarse_scope_does_not_replace_or_revoke_reviewed_tracker_scope(tmp_path):
    tracker, index, canonical, path, roots = catalog_case(tmp_path)
    with sqlite3.connect(canonical) as connection:
        connection.execute("UPDATE knowledge_documents SET product_series='V series'")
    doc = tracker.add_document('Exact source', doc_type='发布记录', model_scope='VINNO 10、VINNO 10E')
    version = tracker.add_document_version(doc, version_label='1.14.81', path_pdf=str(path),
                                          sha256=file_sha256(path), verified_at='2026-11-02')
    alias = f'controlled:{version}:pdf'
    refresh_search_index(tracker, index, **roots)
    candidate = resolve_source_candidate(tracker, alias, **roots)
    assert candidate['scope'] == '国内 · VINNO 10、VINNO 10E' and candidate['has_verification']
    result = unified_search(tracker, index, None, query='CanonicalNeedle', sources={'controlled'},
                            canonical_database=canonical, model='VINNO 10E', verification='verified')
    assert result['total'] == 1 and result['results'][0]['preview_id'] == alias
    assert result['results'][0]['document_metadata']['model_scope'] == 'VINNO 10、VINNO 10E'


def test_archiving_registered_file_also_blocks_its_tracker_extraction_alias(tmp_path):
    tracker, index, canonical, path, roots = catalog_case(tmp_path)
    extracted = path.parent / 'extract.txt'
    extracted.write_text('CanonicalNeedle extracted wording', encoding='utf-8')
    document = tracker.add_document('Note and extraction', doc_type='发布记录')
    version = tracker.add_document_version(document, path_pdf=str(path), path_docx=str(extracted), sha256=file_sha256(path))
    refresh_search_index(tracker, index, **roots)
    with sqlite3.connect(canonical) as connection:
        connection.execute("UPDATE knowledge_documents SET source_status='archived'")
    assert resolve_source_candidate(tracker, f'controlled:{version}:docx', **roots) is None
    assert search(tracker, index, canonical)['total'] == 0


def test_restoring_authoritative_catalog_recovers_sources_without_changing_history(tmp_path):
    tracker, index, canonical, path, roots = catalog_case(tmp_path)
    document = tracker.add_document('Prior evidence', doc_type='发布记录')
    version = tracker.add_document_version(document, path_pdf=str(path), sha256=file_sha256(path))
    before = tracker.list_document_versions(document)
    refresh_search_index(tracker, index, **roots)
    offline = canonical.with_suffix('.offline')
    canonical.rename(offline)
    assert 'controlled' in sync_search_roots_and_metadata(tracker, index, **roots)
    offline.rename(canonical)
    assert 'controlled' not in refresh_search_index(tracker, index, **roots)['source_errors']
    result = search(tracker, index, canonical)
    assert result['total'] == 1
    assert set(result['results'][0]['source_aliases']) == {f'controlled:{version}:pdf', 'canonical:1:file'}
    assert tracker.list_document_versions(document) == before


def test_new_canonical_alias_reuses_complete_unchanged_indexed_text(tmp_path, monkeypatch):
    from tracker.services import unified_search as service
    tracker, index, canonical, path, roots = catalog_case(tmp_path)
    document = tracker.add_document('Already indexed', doc_type='发布记录')
    version = tracker.add_document_version(document, path_pdf=str(path), sha256=file_sha256(path))
    legacy_roots = {key: value for key, value in roots.items() if key != 'canonical_database'}
    refresh_search_index(tracker, index, **legacy_roots)
    def unexpected_parse(_):
        raise AssertionError('An identical already-indexed file must not be parsed again')
    monkeypatch.setattr(service, 'extract_file', unexpected_parse)
    refreshed = refresh_search_index(tracker, index, **roots)
    assert refreshed['indexed'] == 1 and refreshed['failed'] == 0
    assert index.preview('canonical:1:file')['chunks'] == index.preview(f'controlled:{version}:pdf')['chunks']
    assert search(tracker, index, canonical)['total'] == 1

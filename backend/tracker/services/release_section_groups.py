"""Associate page results only when the same complete release chapter is proven."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re

from tracker.services.release_sections import source_sections, controlled_word_sections, section_for_locator
from tracker.services.search_index import file_snapshot


def _single_version(item):
    version = str(item.get('version') or '').strip()
    if not re.fullmatch(r'\d+(?:\.\d+){2,3}', version):
        return ''
    versions = set(item.get('matched_versions') or ()) | {
        match.get('version') for match in item.get('version_matches') or () if match.get('version')
    }
    if len(versions) > 1 or versions and version not in versions:
        return ''
    return version


def _matches_chapter_text(item, section):
    matched = ' '.join(str(item.get('matched_text') or '').split())
    return not matched or matched in ' '.join(str(section.get('content') or '').split())


def assign_release_section_groups(database, index, items, source_cache, resolve_controlled=None):
    """Enrich page items without changing their source, verification or scope."""
    candidates = {}
    for item in items:
        detail = item.get('detail_evidence') or {}
        source_id = detail.get('source_id') or ''
        match = re.fullmatch(r'release:source:([1-9]\d*)', source_id)
        version = _single_version(item)
        if item.get('source_type') != 'release' or not match or not version or not item.get('project_id'):
            continue
        source_number = int(match.group(1))
        with database.connect() as connection:
            row = connection.execute('''SELECT s.path, s.sha256, s.language, r.project_id, r.version
                FROM source_documents s JOIN releases r ON r.id=s.release_id WHERE s.id=?''', (source_number,)).fetchone()
        if not row or row['project_id'] != item['project_id'] or row['version'] != version or not row['sha256']:
            continue
        sections = source_sections(database, source_number, cache=source_cache)
        section = section_for_locator(sections, detail.get('locator') or '')
        if (not section or section['locator'] != detail.get('locator') or not section.get('section_number')
                or not section.get('complete') or not section.get('text_complete')
                or not _matches_chapter_text(item, section)):
            continue
        try:
            snapshot = file_snapshot(row['path'])
        except (OSError, ValueError, RuntimeError):
            continue
        if snapshot.digest != row['sha256']:
            continue
        identity = (source_number, row['project_id'], version, row['language'], section['locator'])
        entry = candidates.setdefault(identity, {'snapshot': snapshot, 'section': section, 'source_row': dict(row), 'release': [], 'controlled': []})
        entry['release'].append(item)

    for item in items:
        detail = item.get('detail_evidence') or {}
        preview_id = item.get('preview_id') or ''
        version = _single_version(item)
        if (item.get('source_type') != 'controlled' or item.get('source_group') != 'release_note'
                or item.get('file_format') != 'docx' or item.get('is_stale') or not version
                or detail.get('source_id') != preview_id or not detail.get('locator')):
            continue
        meta = index.source_metadata(preview_id)
        if not meta or meta['status'] != 'indexed' or not meta.get('file_sha256'):
            continue
        try:
            source_path = Path(meta['path']).resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        compatible = []
        for identity, entry in candidates.items():
            snapshot, section = entry['snapshot'], entry['section']
            if (identity[2] != version or source_path != snapshot.path or meta['file_sha256'] != snapshot.digest
                    or section['section_number'] != detail.get('section_number') or section['title'] != detail.get('title')):
                continue
            if not index.source_signature_matches(preview_id, source_path):
                continue
            controlled = section_for_locator(controlled_word_sections(source_path, meta['file_sha256'], preview_id), detail['locator'])
            if (not controlled or not controlled.get('complete') or not controlled.get('text_complete')
                    or controlled['locator'] != detail['locator']
                    or controlled['section_number'] != section['section_number']
                    or controlled['title'] != section['title'] or controlled['content'] != section['content']
                    or not _matches_chapter_text(item, controlled)):
                continue
            # A shared path/hash/version must not silently choose between projects.
            with database.connect() as connection:
                rows = connection.execute('''SELECT s.path, s.language, r.project_id FROM source_documents s
                    JOIN releases r ON r.id=s.release_id WHERE s.sha256=? AND r.version=?''',
                    (snapshot.digest, version)).fetchall()
            projects_and_languages = set()
            for row in rows:
                try:
                    if Path(row['path']).resolve(strict=True) == snapshot.path:
                        projects_and_languages.add((row['project_id'], row['language']))
                except (OSError, RuntimeError):
                    continue
            if projects_and_languages == {(identity[1], identity[3])}:
                compatible.append(entry)
        if len(compatible) == 1:
            compatible[0]['controlled'].append(item)

    for identity, entry in candidates.items():
        # Recheck current registration, roots, section and index after evidence collection.
        with database.connect() as connection:
            row = connection.execute('''SELECT s.path, s.sha256, s.language, r.project_id, r.version
                FROM source_documents s JOIN releases r ON r.id=s.release_id WHERE s.id=?''', (identity[0],)).fetchone()
        if not row or dict(row) != entry['source_row']:
            continue
        try:
            if file_snapshot(entry['snapshot'].path) != entry['snapshot']:
                continue
        except (OSError, ValueError, RuntimeError):
            continue
        current_section = section_for_locator(source_sections(database, identity[0], cache={}), identity[4])
        if not current_section or current_section != entry['section']:
            continue
        valid_controlled = []
        for item in entry['controlled']:
            if resolve_controlled is None:
                continue
            current_candidate = resolve_controlled(item['preview_id'])
            if (not current_candidate or current_candidate.get('doc_type') != '发布记录'
                    or current_candidate.get('file_role') != 'docx' or current_candidate.get('scope') != item.get('scope')):
                continue
            meta = index.source_metadata(item['preview_id'])
            if not meta or meta['status'] != 'indexed' or meta['file_sha256'] != entry['snapshot'].digest:
                continue
            with database.connect() as connection:
                document = connection.execute('''SELECT d.doc_type, v.path_docx FROM kh_document_versions v
                    JOIN kh_documents d ON d.id=v.document_id WHERE v.id=?''', (item.get('document_version_id'),)).fetchone()
            try:
                if (not document or document['doc_type'] != '发布记录' or not document['path_docx']
                        or Path(document['path_docx']).resolve(strict=True) != entry['snapshot'].path
                        or current_candidate['path'].resolve(strict=True) != entry['snapshot'].path
                        or Path(meta['path']).resolve(strict=True) != entry['snapshot'].path
                        or not index.source_signature_matches(item['preview_id'], entry['snapshot'].path)):
                    continue
            except (OSError, RuntimeError):
                continue
            valid_controlled.append(item)
        # Distinct controlled ranges remain separate, even when their files match.
        scopes = {str(item.get('scope') or '') for item in valid_controlled}
        members = entry['release'] + (valid_controlled if len(scopes) <= 1 else [])
        if len(members) < 2:
            continue
        group_id = sha256(repr(identity).encode('utf-8')).hexdigest()
        for item in members:
            item['chapter_group_id'] = group_id

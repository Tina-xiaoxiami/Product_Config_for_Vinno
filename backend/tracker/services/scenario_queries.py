"""Read-only task answers built from the existing evidence and release data."""
from __future__ import annotations

import re
from typing import Any, Callable

from tracker.domain import version_key
from tracker.services.release_evidence import release_evidence
from tracker.services.release_sections import source_sections

_VERSION = re.compile(r'^\d+(?:\.\d+)+$')


def _version(value: Any) -> tuple[int, ...] | None:
    text = str(value or '').strip()
    return version_key(text) if _VERSION.fullmatch(text) else None


def probe_answer(database: Any, project_id: int, query: str, code: str = '', series: str = '') -> dict[str, Any]:
    needle = query.strip().casefold()
    rows = [row for row in database.list_probe_versions() if needle and needle in {
        str(row.get('probe_model') or '').casefold(), str(row.get('probe_code') or '').casefold()}]
    identities: dict[tuple[str, str], dict[str, str]] = {}
    histories: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = (row['probe_code'], row['series_code'])
        if key[0] not in histories:
            histories[key[0]] = database.search_release_history(key[0], project_id=project_id)['results']
        for item in histories[key[0]]:
            cells = [cell.strip().casefold() for cell in str(item.get('matched_text') or '').split('|')]
            if (str(item.get('preview_id') or '').startswith('release:table:') and key[0].casefold() in cells
                    and (key[1].casefold() in cells or f'{key[1].casefold()}系列' in cells)):
                identities[key] = {'code': key[0], 'series': key[1], 'model': row.get('probe_model') or ''}
                break
    result: dict[str, Any] = {'identities': list(identities.values()), 'selected': None, 'evidence': None, 'candidates': []}
    if not code and len(identities) == 1:
        code, series = next(iter(identities))
    if (code, series) not in identities:
        return result
    result['selected'] = identities[(code, series)]
    additions = [row for row in rows if row['probe_code'] == code and row['series_code'] == series
                 and row['state'] == 'added' and _version(row.get('software_version')) is not None]
    result['candidates'] = sorted(additions, key=lambda row: _version(row['software_version']) or ())
    history = histories[code]
    evidence = []
    for item in history:
        if not str(item.get('preview_id') or '').startswith('release:table:') or _version(item.get('version')) is None:
            continue
        cells = [cell.strip().casefold() for cell in str(item.get('matched_text') or '').split('|')]
        if (code.casefold() in cells and (series.casefold() in cells or f'{series.casefold()}系列' in cells)
                and any(re.fullmatch(r'(?:新增|added)(?:\s*[,，].*)?', cell) for cell in cells)
                and any(_version(row['software_version']) == _version(item['version']) for row in additions)):
            evidence.append(item)
    if evidence:
        result['evidence'] = min(evidence, key=lambda item: _version(item['version']) or ())
    return result


def feature_answer(database: Any, project_id: int, query: str, model: str,
                   search: Callable[..., dict[str, Any]], preview: Callable[..., dict[str, Any] | None],
                   target_version: str = '', document: str = '', section_choice: str = '') -> dict[str, Any]:
    target_key = _version(target_version)
    if target_version and target_key is None:
        raise ValueError('目标版本格式不正确。')
    page = 1
    items: list[dict[str, Any]] = []
    result: dict[str, Any] = {}
    while page <= 5:
        result = search(page, model)
        items.extend(result.get('results', []))
        model = result.get('whitepaper_models', {}).get('selected', model)
        if len(items) >= result.get('total', 0):
            break
        page += 1
    complete = len(items) >= result.get('total', 0) and not result.get('source_errors')
    response: dict[str, Any] = {'models': result.get('whitepaper_models', {}), 'baseline': None,
                                'section': None, 'later_changes': [], 'coverage_complete': complete,
                                'source_errors': result.get('source_errors', {}), 'latest_certified': False,
                                'unresolved_candidates': 0, 'documents': [], 'selected_document': '',
                                'section_options': []}
    # A registered document groups its own versions. Distinct documents cannot be
    # assumed to share language, market or scope even when their model labels match.
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        document_key = str(item.get('_scenario_document_id') or item.get('preview_id') or '')
        if document_key:
            groups.setdefault(document_key, []).append(item)
    response['documents'] = [{'value': key, 'label': str(group[0].get('_scenario_document_label') or group[0].get('title') or '未命名资料'),
                              'scope': str(group[0].get('scope') or '适用范围未登记')}
                             for key, group in groups.items()]
    if not document and len(groups) == 1:
        document = next(iter(groups))
    if document not in groups:
        return response
    response['selected_document'] = document
    items = groups[document]
    unresolved = sum(1 for item in items if _version(item.get('version')) is None)
    candidates: list[tuple[tuple[int, ...], dict[str, Any]]] = []
    incomplete_versions: list[tuple[int, ...]] = []
    for item in items:
        key = _version(item.get('version'))
        if key is None or (target_key is not None and key > target_key):
            continue
        if not item.get('detail_evidence') or item.get('is_stale'):
            incomplete_versions.append(key)
        else:
            candidates.append((key, item))
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    found: list[tuple[dict[str, Any], dict[str, Any]]] = []
    selected_key: tuple[int, ...] | None = None
    for key, item in candidates:
        if selected_key is not None and key < selected_key:
            break
        detail = item['detail_evidence']
        source = preview(detail['source_id'], detail.get('locator', ''), query)
        section = source.get('section') or {} if source else {}
        if not source or source.get('stale') or source.get('locator_status') == 'unresolved' or not section.get('complete') or not section.get('content'):
            unresolved += 1
            continue
        selected_key = key
        found.append((item, section))
    if not found or selected_key is None:
        response['unresolved_candidates'] = unresolved + len(incomplete_versions)
        return response
    unresolved += sum(1 for value in incomplete_versions if value >= selected_key)
    texts = {re.sub(r'\s+', ' ', str(section['content'])).strip() for _, section in found}
    if len(texts) > 1:
        response['section_options'] = [{'value': str(item['detail_evidence']['source_id']) + '|' + str(section.get('locator') or item['detail_evidence'].get('locator') or ''),
                                         'label': str(item['detail_evidence'].get('title') or item.get('title') or '章节'),
                                         'version': item['version'], 'scope': item.get('scope') or ''}
                                        for item, section in found]
        selected = next(((item, section) for item, section in found if str(item['detail_evidence']['source_id']) + '|' + str(section.get('locator') or item['detail_evidence'].get('locator') or '') == section_choice), None)
        if selected is None:
            response['unresolved_candidates'] = unresolved
            return response
        item, section = selected
    else:
        item, section = found[0]
    response['baseline'], response['section'] = item, section
    response['latest_certified'] = complete and unresolved == 0 and len(texts) == 1
    response['unresolved_candidates'] = unresolved
    baseline_key = _version(item['version'])
    needle = query.strip().casefold()
    if baseline_key is None:
        return response
    for release in database.list_releases(project_id):
        key = _version(release.get('version'))
        if key is None or key <= baseline_key or (target_key is not None and key > target_key):
            continue
        for change in database.list_changes(release['id']):
            if change.get('review_status') == 'rejected':
                continue
            if needle and any(needle in str(change.get(field) or '').casefold() for field in ('title_cn', 'title_en', 'description_cn', 'description_en')):
                kind = 'record' if change.get('review_status') == 'approved' else 'clue'
                response['later_changes'].append({**change, 'version': release['version'], 'preview_id': f"release:change:{change['id']}", 'evidence_type': kind})
    history = database.search_release_history(query, project_id=project_id)['results']
    for evidence in history:
        key = _version(evidence.get('version'))
        if (key is not None and key > baseline_key and (target_key is None or key <= target_key)
                and evidence.get('evidence_kind') in {'pending', 'source_snapshot'}):
            response['later_changes'].append({**evidence, 'evidence_type': 'clue'})
    response['later_changes'].sort(key=lambda change: _version(change.get('version')) or ())
    return response


def version_answer(database: Any, project_id: int, target: str, base: str,
                   compare: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    releases = database.list_releases(project_id)
    by_version = {release['version']: release for release in releases}
    response: dict[str, Any] = {'versions': list(by_version), 'target': None, 'comparison': None}
    if target not in by_version:
        return response
    release = by_version[target]
    response['target'] = {**release, 'changes': database.list_changes(release['id'])}
    if base:
        if base not in by_version:
            raise ValueError('对比基准版本不存在。')
        response['comparison'] = compare(by_version[base], release)
    return response


def _release_source_language(database, source_id, project_id):
    with database.connect() as connection:
        row = connection.execute("""SELECT s.language FROM source_documents s
            JOIN releases r ON r.id=s.release_id WHERE s.id=? AND s.is_final=1 AND r.project_id=?""",
            (source_id, project_id)).fetchone()
    return row['language'] if row else ''


def release_feature_answer(database, project_id, query, model, target_version='', document='', section_choice=''):
    """Fallback only to verified, matching, same-project Chinese release sections.

    The release project does not prove applicability to the selected device model.
    Keep that limitation visible instead of inheriting a whitepaper's model scope.
    """
    chain = f'release-project:{project_id}:cn'
    items = []
    seen = set()
    for hit in database.search_release_history(query, project_id=project_id)['results']:
        source = str(hit.get('preview_id') or '')
        if not re.fullmatch(r'release:source:\d+', source) or source in seen:
            continue
        seen.add(source)
        source_id = int(source.rsplit(':', 1)[-1])
        if _release_source_language(database, source_id, project_id) != 'cn':
            continue
        for section in source_sections(database, source_id):
            title = str(section.get('title') or '')
            if not section.get('complete') or not section.get('content') or query.casefold() not in title.casefold():
                continue
            scope = f"{hit.get('project_name') or '当前项目'} · 国内 · 机型范围待核对"
            items.append({'_scenario_document_id': chain, '_scenario_document_label': 'Release Note 完整功能章节',
                'version': hit['version'], 'title': title, 'scope': scope,
                'detail_evidence': {'source_id': source, 'locator': section['locator'],
                    'title': title, 'scope': scope, 'verification': 'unverified'}})
    def search(page, selected_model):
        return {'results': items, 'total': len(items), 'source_errors': {},
                'whitepaper_models': {'selected': model, 'options': []}}
    def preview(source, locator, needle):
        return release_evidence(database, source, locator, query=needle)
    result = feature_answer(database, project_id, query, model, search, preview,
                            target_version, document or chain, section_choice)
    result['latest_certified'] = False
    return result


def release_fallback_allowed(answer):
    pending_document_choice = bool(answer.get('documents') and not answer.get('selected_document'))
    return not answer.get('baseline') and not pending_document_choice and not answer.get('section_options')

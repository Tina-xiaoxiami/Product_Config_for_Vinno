"""Conservative Release Note revisions: exact source text, never model summaries."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tracker.services.release_sections import source_sections
from tracker.services.scenario_queries import _release_source_language, _version

_NOTICE = ('仅覆盖已登记且可核实的中文 Release Note。基线为最早可读取的完整章节，'
           '不等于已证实绝对首次支持；机型适用范围仍以原文为准。无法明确定位的修改不自动合并。')


def _normal(value: str) -> str:
    return re.sub(r'\s+', ' ', value).strip()


def _matches(query: str, value: str) -> bool:
    return query.casefold() in value.casefold()


def _body(section: dict[str, Any]) -> str:
    content = str(section['content']).strip()
    lines = content.splitlines()
    if lines and _normal(lines[0]) == _normal(str(section.get('title') or '')):
        return '\n'.join(lines[1:]).strip() or content
    return content


def _is_additive(text: str, query: str = '') -> bool:
    """Recognize explicit additions, retaining their complete subject and conditions."""
    if '\n' in text or re.search(r'取消|不再|改为|替换|删除|移除|修复|解决|错误|不支持|未支持|禁止|不新增|未新增|bug', text, re.I):
        return False
    if re.fullmatch(r'新增(?:支持|功能[：:]|[：:])[^\n]+', text):
        return True
    if not query:
        return False
    subject = re.escape(query)
    return bool(re.fullmatch(subject + r'(?:功能)?默认增加[^\n]+', text, re.I)
                or re.fullmatch(r'[^。；;\n]*' + subject + r'(?:等功能|功能)下[^。；;\n]+新增支持[^\n]+', text, re.I))


def _apply(content: str, text: str, query: str = '') -> tuple[str, str, str, str] | None:
    """Only quoted exact anchors and explicitly additive sentences are executable."""
    quoted = r'[“「"]([^”」"\n]+)[”」"]'
    snapshot = re.fullmatch(r'(?:完整描述|完整功能描述)(?:更新为|替换为)[：:]\s*([\s\S]+)', text)
    if snapshot:
        return snapshot.group(1), 'replace_full', content, snapshot.group(1)
    replacement = re.fullmatch(r'(?:将|把|原文)?\s*' + quoted + r'\s*(?:修改为|改为|替换为|调整为)\s*' + quoted + r'[。；;]?', text)
    if replacement:
        before, after = replacement.groups()
        if content.count(before) == 1:
            return content.replace(before, after, 1), 'replace', before, after
        return None
    deletion = re.fullmatch(r'(?:删除|移除)\s*' + quoted + r'[。；;]?', text)
    if deletion:
        before = deletion.group(1)
        if content.count(before) == 1:
            return content.replace(before, '', 1).strip(), 'delete', before, ''
        return None
    # A single explicit new ability can be retained verbatim, including its limits.
    if _is_additive(text, query):
        if _normal(text) in _normal(content):
            return content, 'unchanged', '', ''
        return content.rstrip() + '\n\n' + text, 'append', '', text
    return None


def _baseline_section(database: Any, baseline: dict[str, Any], *, include_images: bool = True) -> dict[str, Any]:
    """Read only the selected verified chapter images; keep text on failure."""
    fallback = {'source_id': baseline['source_id'], 'locator': baseline['locator'],
                'title': baseline['title'], 'content': baseline['content'], 'complete': True,
                'has_images': baseline['has_images'],
                'images_complete': not baseline['has_images'],
                'blocks': [{'type': 'text', 'locator': baseline['locator'], 'text': baseline['content']}]}
    if not include_images or not baseline['has_images']:
        return fallback
    try:
        source_id = int(baseline['source_id'].rsplit(':', 1)[-1])
        # source_sections verifies the registered file path, current hash and
        # imported snapshot, and enforces image type/count/size limits.
        sections = source_sections(database, source_id, image_locator=baseline['locator'])
        exact = [section for section in sections
                 if section.get('locator') == baseline['locator']
                 and section.get('source_id') == baseline['source_id']
                 and section.get('title') == baseline['title']
                 and section.get('content') == baseline['content']
                 and section.get('complete')]
        if len(exact) == 1:
            return exact[0]
    except (OSError, ValueError, RuntimeError):
        pass
    return fallback


def _source_document_metadata(database: Any, project_id: int) -> dict[str, dict[str, Any]]:
    """Read same-project file identity; never expose canonical paths in responses."""
    if not hasattr(database, 'connect'):
        return {}
    with database.connect() as connection:
        rows = connection.execute("""SELECT s.id,s.path,s.filename,s.sha256,r.version
            FROM source_documents s JOIN releases r ON r.id=s.release_id
            WHERE r.project_id=?""", (project_id,)).fetchall()
    result = {}
    for row in rows:
        try:
            canonical = str(Path(row['path']).expanduser().resolve()) if row['path'] else ''
        except (OSError, RuntimeError, ValueError):
            canonical = ''
        filename = Path(row['filename']).name if row['filename'] else f"Release Note #{row['id']}"
        result[f"release:source:{row['id']}"] = {'canonical_path': canonical, 'filename': filename,
            'sha256': row['sha256'], 'version': row['version'],
            'source_label': f"{filename} · 记录 #{row['id']}"}
    return result


def _group_unreadable_sources(unreadable, metadata, readable_files):
    groups = {}
    for item in unreadable:
        path = metadata.get(item['source_id'], {}).get('canonical_path')
        key = (_version(item['version']), path or item['source_id'])
        groups.setdefault(key, []).append(item)
    remaining, superseded = [], []
    for key, items in groups.items():
        ordered = sorted(items, key=lambda item: int(item['source_id'].rsplit(':', 1)[-1]))
        representative = {**ordered[-1], 'related_source_ids': [item['source_id'] for item in ordered],
                          'record_count': len(ordered)}
        if key in readable_files:
            superseded.append(representative)
        else:
            remaining.append(representative)
    return remaining, superseded


def release_evolution_answer(database: Any, project_id: int, query: str, target_version: str = '') -> dict[str, Any]:
    """Build the earliest full section plus traceable, deterministic later patches."""
    query = query.strip()
    if not query or len(query) > 200:
        raise ValueError('请输入不超过200字的功能名称。')
    target = _version(target_version)
    if target_version and target is None:
        raise ValueError('目标版本格式不正确。')
    result: dict[str, Any] = {'baseline': None, 'content': '', 'applied_changes': [],
                            'unresolved_changes': [], 'timeline': [], 'section_options': [],
                            'coverage_notice': _NOTICE, 'status': 'missing_baseline',
                            'target_version': target_version, 'illustrations': [],
                            'illustrations_version': '', 'illustrations_complete': True,
                            'illustrations_truncated': False, 'illustration_notice': ''}
    history = database.search_release_history(query, project_id=project_id)['results']
    dated = [hit for hit in history if _version(hit.get('version')) is not None
             and (target is None or _version(hit['version']) <= target)
             and (hit.get('project_id') is None or hit['project_id'] == project_id)
             and hit.get('verification') != 'rejected']
    earliest = min(dated, key=lambda hit: _version(hit['version'])) if dated else None
    result['earliest_record_version'] = earliest['version'] if earliest else ''
    sections: dict[tuple[int, ...], list[dict[str, Any]]] = {}
    seen_sources: set[str] = set()
    image_candidates: dict[tuple[int, ...], list[dict[str, Any]]] = {}
    unreadable_sources: list[dict[str, Any]] = []
    source_documents = _source_document_metadata(database, project_id)
    readable_files: set[tuple[tuple[int, ...], str]] = set()
    for hit in history:
        source = str(hit.get('preview_id') or '')
        version = _version(hit.get('version'))
        if (not re.fullmatch(r'release:source:\d+', source) or source in seen_sources or version is None
                or (target is not None and version > target) or hit.get('verification') == 'rejected'
                or (hit.get('project_id') is not None and hit['project_id'] != project_id)):
            continue
        seen_sources.add(source)
        source_id = int(source.rsplit(':', 1)[-1])
        if _release_source_language(database, source_id, project_id) != 'cn':
            continue
        file_metadata = source_documents.get(source, {})
        if file_metadata.get('version') and _version(file_metadata['version']) != version:
            continue
        file_info = {key: file_metadata.get(key) or '' for key in ('filename', 'source_label')}
        if not file_info['source_label']:
            file_info['source_label'] = f'Release Note · 记录 #{source_id}'
        source_metadata = source_sections(database, source_id)
        if source_metadata and file_metadata.get('canonical_path'):
            readable_files.add((version, file_metadata['canonical_path']))
        if not source_metadata:
            unreadable_sources.append({'version': hit['version'], 'source_id': source, 'locator': '', 'title': query, **file_info})
        for section in source_metadata:
            title = str(section.get('title') or '')
            if (not section.get('complete') or not section.get('content') or not _matches(query, title)
                    or re.search(r'目录|配置表|配置变更|Contents', title, re.I)):
                continue
            item = {'version': hit['version'], 'content': str(section['content']).strip(),
                    'source_id': source, 'locator': section.get('locator') or '', 'title': title,
                    'text': _body(section), 'verification': 'unverified',
                    'has_images': bool(section.get('has_images')), **file_info}
            if item['has_images']:
                image_candidates.setdefault(version, []).append(item)
            bucket = sections.setdefault(version, [])
            if not any(_normal(old['text']) == _normal(item['text']) for old in bucket):
                bucket.append(item)
    unreadable_sources, superseded_sources = _group_unreadable_sources(unreadable_sources, source_documents, readable_files)
    if superseded_sources:
        result['illustrations_superseded_sources'] = superseded_sources
    latest_unreadable = max(unreadable_sources, key=lambda item: _version(item['version']) or ()) if unreadable_sources else None
    latest_images = max(image_candidates) if image_candidates else None
    blocked_images = bool(latest_unreadable and (latest_images is None or (_version(latest_unreadable['version']) or ()) >= latest_images))
    if blocked_images and latest_unreadable is not None:
        result['illustrations_version'] = latest_unreadable['version']
        result['illustrations_complete'] = False
        result['illustration_notice'] = (f"{latest_unreadable['version']}版本的相关中文Release Note无法读取，"
            '较近版本图示未能核实；未展示旧图作为最新图示，请打开该版本原文核对。')
        result['illustrations_unverified_sources'] = [item for item in unreadable_sources
            if latest_images is None or (_version(item['version']) or ()) >= latest_images]
    elif image_candidates:
        latest = max(image_candidates)
        candidates = sorted(image_candidates[latest], key=lambda item: (item['title'], item['locator'], item['source_id']))
        unique: dict[tuple[str, str], dict[str, Any]] = {}
        for item in candidates:
            unique.setdefault((item['source_id'], item['locator']), item)
        selected = list(unique.values())
        result['illustrations_version'] = selected[0]['version']
        result['illustrations_truncated'] = len(selected) > 3
        for item in selected[:3]:
            result['illustrations'].append({key: item[key] for key in ('version', 'source_id', 'locator', 'title', 'filename', 'source_label')})
            result['illustrations'][-1]['section'] = _baseline_section(database, item)
        result['illustrations_complete'] = (not result['illustrations_truncated']
            and all(item['section'].get('images_complete') is True for item in result['illustrations']))
        notices = []
        if result['illustrations_truncated']:
            notices.append('最新含图版本的相关章节超过3个，仅展示前3个，其余请查看该版本原文。')
        if any(item['section'].get('images_complete') is not True for item in result['illustrations']):
            notices.append('最新含图版本的部分图示无法读取，请查看该版本原文；未以旧版图片替代。')
        result['illustration_notice'] = ' '.join(notices)
    if not sections:
        return result
    first = min(sections)
    if len(sections[first]) != 1:
        result['section_options'] = sections[first]
        result['status'] = 'baseline_conflict'
        return result
    baseline = sections[first][0]
    baseline['section'] = _baseline_section(database, baseline, include_images=False)
    result['baseline'] = baseline
    result['baseline_gap'] = bool(earliest and _version(earliest['version']) < first)
    if result['baseline_gap'] and earliest is not None:
        result['coverage_notice'] += f" 已有更早的{earliest['version']}记录，但缺少可读取的完整章节，当前正文不能视为完整演进结果。"
    result['content'] = baseline['content']
    result['timeline'].append({**{key: value for key, value in baseline.items() if key != 'section'}, 'operation': 'baseline'})
    events: list[dict[str, Any]] = []
    for key, rows in sections.items():
        if key <= first:
            continue
        for row in rows:
            events.append({**row, 'conflict': len(rows) > 1, 'reason': '同版本完整章节存在不同正文' if len(rows) > 1 else ''})
    for release in database.list_releases(project_id):
        key = _version(release.get('version'))
        if key is None or key <= first or (target is not None and key > target):
            continue
        for change in database.list_changes(release['id']):
            text = str(change.get('description_cn') or change.get('title_cn') or '').strip()
            if (change.get('review_status') == 'rejected' or change.get('category') not in {'function', 'image'}
                    or not any(_matches(query, str(change.get(field) or '')) for field in ('title_cn', 'title_en', 'description_cn', 'description_en'))):
                continue
            events.append({'version': release['version'], 'text': text, 'content': text,
                           'source_id': f"release:change:{change['id']}", 'locator': '中文记录',
                           'verification': change.get('review_status') or 'unverified',
                           'reason': '' if change.get('review_status') == 'approved' and text else '尚未审核或缺少中文原文'})
    def operation_text(event):
        return re.sub(r'^' + re.escape(query) + r'\s*[：:]\s*', '', event['text'], flags=re.I)

    def additive(event):
        return _is_additive(operation_text(event), query)

    conflicts = {key for key, rows in sections.items() if len(rows) > 1}
    non_additions: dict[tuple[int, ...], set[str]] = {}
    for event in events:
        key = _version(event['version'])
        if key is not None and not event.get('reason') and not additive(event):
            non_additions.setdefault(key, set()).add(_normal(operation_text(event)))
    for event in events:
        key = _version(event['version'])
        if key in conflicts:
            event['reason'] = '同版本完整章节存在不同正文，该版本所有变更均待核对'
        elif len(non_additions.get(key, set())) > 1 and not additive(event):
            event['reason'] = '同版本有多个非新增变更，执行顺序待核对'
    # Apply at most one non-additive operation before independent additions. Never
    # let database row ordering create an implied sequence of edits.
    events.sort(key=lambda row: (_version(row['version']) or (), additive(row),
                                 _normal(operation_text(row)), bool(row.get('reason')),
                                 row.get('verification') != 'approved', row['source_id']))
    seen: set[tuple[tuple[int, ...] | None, str]] = set()
    for event in events:
        signature = (_version(event['version']), _normal(operation_text(event)))
        if signature in seen:
            continue
        seen.add(signature)
        if _normal(event['text']) == _normal(baseline['text']):
            continue
        patch = None if event.get('reason') else _apply(result['content'], operation_text(event), query)
        if patch is None:
            entry = {**event, 'operation': 'pending', 'reason': event.get('reason') or '无法明确定位新增、替换或删除范围，保留原文待核对'}
            result['unresolved_changes'].append(entry)
        else:
            content, operation, before, after = patch
            if operation == 'unchanged':
                continue
            result['content'] = content
            entry = {**event, 'operation': operation, 'before': before, 'after': after}
            result['applied_changes'].append(entry)
        result['timeline'].append(entry)
    result['status'] = 'needs_review' if result['unresolved_changes'] or result['baseline_gap'] else 'assembled'
    return result

"""Read the stored record behind a release search hit, without exposing paths."""
from __future__ import annotations

import json
from typing import Any

from tracker.database import Database
from tracker.services.release_sections import referenced_sections, section_for_locator, source_sections


def release_evidence(database: Database, source_id: str, locator: str = '', *, query: str = '', limit: int | None = 200) -> dict[str, Any] | None:
    parts = source_id.split(':')
    if len(parts) != 3 or not parts[2].isdigit():
        return None
    kind, record_id = parts[1], int(parts[2])
    tables = {'source': 'source_documents', 'change': 'change_events',
              'candidate': 'import_candidates', 'feature': 'features', 'table': 'release_table_rows'}
    if kind not in tables:
        return None
    with database.connect() as connection:
        row = connection.execute(f'SELECT * FROM {tables[kind]} WHERE id=?', (record_id,)).fetchone()
        if row is None:
            return None
        record = dict(row)
        release = connection.execute('SELECT r.version, p.name FROM releases r JOIN projects p ON p.id=r.project_id WHERE r.id=?',
                                     (record.get('release_id'),)).fetchone()
    scope = f'{release["name"]} · {release["version"]}' if release else '当前功能说明 · 不代表历史版本状态'
    section = None
    matches = []
    if kind == 'source':
        chunks = [{'locator': f'原文行 {n}', 'text': line} for n, line in enumerate(record['content'].splitlines(), 1) if line.strip()]
        matches = [chunk for chunk in chunks if query and query.casefold() in chunk['text'].casefold()]
        selected = locator or (matches[0]['locator'] if matches else '')
        section = section_for_locator(source_sections(database, record_id, image_locator=selected), selected)
        if section:
            chunks = []
            for block in section['blocks']:
                if block['type'] != 'text':
                    continue
                if chunks and chunks[-1]['locator'] == block['locator']:
                    chunks[-1]['text'] += block['text']
                else:
                    chunks.append({'locator': block['locator'], 'text': block['text']})
        elif selected:
            position = next((n for n, chunk in enumerate(chunks) if chunk['locator'] == selected), 0)
            chunks = chunks[max(0, position - 3):position + 4]
        title = record['filename']
        notice = '导入时原文快照；反映该次导入内容，不保证与磁盘原件当前内容一致。'
        if section and section['has_images']:
            notice += (' 本章节包含图片，请在完整预览中查看。' if section['images_complete'] else ' 本章节部分图片无法显示，请查看原文件核对图文。')
        elif not section:
            notice += ' 未能核实完整章节，以下仅为定位附近的原文。'
    elif kind == 'table':
        fields = json.loads(record['data_json'])
        details = '\n'.join(f'{key}：{value}' for key, value in fields.items())
        chunks = [{'locator': '表格记录', 'text': record['summary'] + '\n' + details}]
        title = record['item_name']
        notice = '导入时表格记录；配置快照或提及不能单独证明首次支持。'
    else:
        cn_field, en_field = {'candidate': ('raw_cn', 'raw_en'),
                              'feature': ('cn_description', 'en_description'),
                              'change': ('description_cn', 'description_en')}[kind]
        cn, en = record.get(cn_field, ''), record.get(en_field, '')
        title = record.get('cn_name') or record.get('title_cn') or record.get('title_en') or '版本记录'
        chunks = [{'locator': '中文记录', 'text': (record.get('title_cn', '') + '\n' + cn).strip()},
                  {'locator': 'English record', 'text': (record.get('title_en', '') + '\n' + en).strip()}]
        notice = '当前功能说明，不用于判断历史首次支持。' if kind == 'feature' else '保存的版本条目；以当时原文和适用范围为准。'
    locator_status = ('query' if not locator else 'exact' if any(chunk['locator'] == locator for chunk in chunks) else 'unresolved')
    return {'locator_status': locator_status, 'source_id': source_id, 'source_type': 'release', 'file_format': 'txt',
            'title': title, 'scope': scope, 'verification': ('pending_review' if kind == 'candidate' else
                                                          'unverified' if kind == 'source' else 'approved'),
            'is_current': kind == 'feature', 'stale': False, 'downloadable': False,
            'notice': notice, 'section': section, 'matches': matches, 'match_count': len(matches),
            'chunks': chunks[:limit], 'truncated': limit is not None and len(chunks) > limit}


def release_section_detail(section: dict) -> dict:
    return {'source_id': section['source_id'], 'locator': section['locator'],
            'section_number': section['section_number'], 'title': section['title'],
            'excerpt': section['content'][:500], 'has_images': section['has_images'],
            'verification': 'unverified', 'evidence_kind': 'source_snapshot',
            'source_label': 'Release Note 原文',
            'notice': '导入时原文快照，仍需核对来源与适用范围。'}


def preferred_release_detail(database: Database, source_id: str, *, locator: str = '', cache: dict | None = None) -> tuple[dict | None, str | None]:
    parts = source_id.split(':')
    if len(parts) != 3 or parts[1] not in {'table', 'change'} or not parts[2].isdigit():
        return None, None
    kind, record_id = parts[1], int(parts[2])
    with database.connect() as connection:
        if kind == 'table':
            row = connection.execute("""SELECT row.summary, row.data_json, table_data.source_document_id
                FROM release_table_rows row JOIN release_tables table_data ON table_data.id=row.table_id
                JOIN source_documents source ON source.id=table_data.source_document_id
                WHERE row.id=? AND table_data.release_id=row.release_id
                  AND source.release_id=row.release_id AND source.language=row.language
                  AND table_data.language=row.language""", (record_id,)).fetchone()
            if row is None:
                return None, None
            text, title, sources = row['summary'] + ' ' + row['data_json'], '', [row['source_document_id']]
        else:
            row = connection.execute('SELECT * FROM change_events WHERE id=?', (record_id,)).fetchone()
            language = {'中文记录': 'cn', 'English record': 'en'}.get(locator)
            if row is None or not language:
                return None, None
            title = row['title_cn'] if language == 'cn' else row['title_en']
            description = row['description_cn'] if language == 'cn' else row['description_en']
            text = (title or '') + ' ' + (description or '')
            sources = [entry[0] for entry in connection.execute(
                'SELECT id FROM source_documents WHERE release_id=? AND language=? AND (? IS NULL OR id=?)',
                (row['release_id'], language, row['source_document_id'], row['source_document_id']))]
    values = referenced_sections(text)
    if len(values) > 1:
        return None, '记录引用多个章节，请查看原配置记录并逐一核实。'
    if not values and (kind != 'change' or not title.strip()):
        return None, None
    if len(sources) != 1:
        return None, '未能唯一核实同版本同语言原文件，请查看原记录。'
    available = source_sections(database, int(sources[0]), cache=cache)
    if values:
        number = next(iter(values))
        sections = [section for section in available if section['section_number'] == number]
    else:
        # Only an exact title match is evidence; never infer from a query or substring.
        exact_title = ' '.join(title.split())
        sections = [section for section in available if ' '.join(section['title'].split()) == exact_title]
    if len(sections) != 1:
        return None, '未能核实同版本同语言完整章节或匹配不唯一，请查看原记录与原文件。'
    return release_section_detail(sections[0]), None

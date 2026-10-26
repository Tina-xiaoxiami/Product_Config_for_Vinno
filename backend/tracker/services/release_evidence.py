"""Read the stored record behind a release search hit, without exposing paths."""
from __future__ import annotations

import json
from typing import Any

from tracker.database import Database


def release_evidence(database: Database, source_id: str, locator: str = '', *, limit: int | None = 200) -> dict[str, Any] | None:
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
    if kind == 'source':
        chunks = [{'locator': f'原文行 {n}', 'text': line} for n, line in enumerate(record['content'].splitlines(), 1) if line.strip()]
        position = next((n for n, chunk in enumerate(chunks) if chunk['locator'] == locator), 0)
        # Bring the actual neighboring paragraphs along even for late-page hits.
        neighbors = sorted(range(max(0, position - 3), min(len(chunks), position + 4)),
                           key=lambda n: (abs(n - position), n))
        neighborhood = [chunks[n] for n in neighbors]
        chunks = neighborhood + [chunk for chunk in chunks if chunk not in neighborhood]
        title = record['filename']
        notice = '导入时原文快照；反映该次导入内容，不保证与磁盘原件当前内容一致。'
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
    chunks.sort(key=lambda chunk: chunk['locator'] != locator)
    return {'source_id': source_id, 'source_type': 'release', 'file_format': 'txt',
            'title': title, 'scope': scope, 'verification': ('pending_review' if kind == 'candidate' else
                                                          'unverified' if kind == 'source' else 'approved'),
            'is_current': kind == 'feature', 'stale': False, 'downloadable': False,
            'notice': notice, 'chunks': chunks[:limit], 'truncated': limit is not None and len(chunks) > limit}

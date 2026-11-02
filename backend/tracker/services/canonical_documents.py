"""Read-only current-file projection over the canonical product document registry.

Tracker version IDs remain evidence identities. This adapter never migrates them
or equates a current file registration with an approved historical version.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
from typing import Any


class CanonicalCatalogUnavailable(RuntimeError):
    """The authoritative lifecycle cannot be checked; do not revive cached files."""


_DOCUMENT_TYPES = {
    'manual': '说明书', 'whitepaper': '白皮书', 'release_note': '发布记录',
    'registration_certificate': '注册资料', 'registration_difference': '注册差异表',
    'registration_tracking': '注册跟踪表',
}
_RETIRED = frozenset({'archived', 'retired', 'deleted', '已归档', '已退役', '已失效', '失效', '无效'})


def is_retired(status: Any) -> bool:
    return str(status or '').strip().casefold() in _RETIRED


def normalized_path(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def read_catalog(database: str | Path | None) -> dict[str, dict[str, Any]]:
    """Read a consistent registry snapshot; never create a missing database."""
    if database is None:
        return {}
    try:
        path = Path(database).expanduser().resolve(strict=True)
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA query_only = ON')
            rows = connection.execute('''SELECT id, title, document_type, file_path,
                version, market, product_series, sha256, source_status FROM knowledge_documents''').fetchall()
        catalog = {}
        for record in rows:
            if not Path(record['file_path']).expanduser().is_absolute():
                raise CanonicalCatalogUnavailable('主资料登记含非绝对路径，请先核对登记；受控资料检索暂不可用。')
            key = normalized_path(record['file_path'])
            if key in catalog:
                raise CanonicalCatalogUnavailable('主资料登记存在重复物理路径，请先核对登记；受控资料检索暂不可用。')
            catalog[key] = dict(record)
        return catalog
    except CanonicalCatalogUnavailable:
        raise
    except (OSError, RuntimeError, sqlite3.Error, TypeError) as error:
        raise CanonicalCatalogUnavailable('主资料登记当前不可读取；受控资料检索已暂停，请恢复来源后更新索引。') from error


def document_metadata(row: dict[str, Any]) -> dict[str, Any]:
    return {'title': row['title'], 'doc_type': _DOCUMENT_TYPES.get(row['document_type'], row['document_type']),
            'model_scope': row['product_series'] or ''}


def _scope(row: dict[str, Any]) -> str:
    market = {'domestic': '国内', 'overseas': '海外'}.get(row['market'], row['market'] or '')
    return ' · '.join(value for value in (market, row['product_series']) if value) or '适用范围未登记'


def project_records(records: list[dict[str, Any]], database: str | Path | None,
                    roots: tuple[str | Path | None, ...], access) -> list[dict[str, Any]]:
    """Keep tracker aliases, add stable canonical IDs and honor canonical retirement."""
    if database is None:
        return records
    catalog = read_catalog(database)
    projected = []
    blocked_versions = {record.get('document_version_id') for record in records
                        if (canonical := catalog.get(normalized_path(record['path']))) is not None
                        and canonical['source_status'] != 'active'}
    for record in records:
        if record.get('document_version_id') in blocked_versions:
            continue
        canonical = catalog.get(normalized_path(record['path']))
        if canonical is not None:
            if canonical['source_status'] != 'active':
                continue
            record = dict(record)
            # Registration metadata is not an evidence-scope decision. In particular,
            # a coarse product_series must not replace a reviewed concrete model list.
            record['canonical_document_id'] = canonical['id']
        projected.append(record)
    for path, row in catalog.items():
        if row['source_status'] != 'active':
            continue
        file_path = Path(path)
        projected.append({
            'source_id': f"canonical:{row['id']}:file", 'source_type': 'controlled',
            'title': str(row['title']) + (f" · {row['version']}" if row['version'] else ''),
            'path': file_path, 'scope': _scope(row), 'verification': 'unverified', 'is_current': True,
            'canonical_document_id': row['id'], 'document_metadata': document_metadata(row),
            'doc_type': document_metadata(row)['doc_type'], 'file_role': 'registered_file',
            'evidence_count': 0, 'access_status': access(file_path, roots),
            'has_verification': False, 'verification_sha256': '',
        })
    return projected

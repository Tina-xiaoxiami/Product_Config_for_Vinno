"""Read-only coverage of configured Release Note candidates and registered sources.

The workbench's importer requires paired DOCX files in a direct version directory;
coverage instead enumerates nested PDF/DOCX/legacy candidates without importing them.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.integrations.release_workbench import load_release_workbench_config
from app.services.knowledge_content import _file_sha256
from app.services.feature_release_versions import version_sort_key
from app.services.knowledge_release_applicability import extract_source_applicability, model_facts
from app.services.knowledge_release_history import _documents, _quality, ReleaseHistoryError
from app.services.knowledge_scope import resolve_query_scope

_RN = re.compile(r'r(?:e)?lease[\s_-]*notes?|发布记录|版本发布说明', re.I)
_VERSION = re.compile(r'(?<![\d.])\d+(?:\.\d+){1,3}(?![\d.])')
_MESSAGE = '仅检查服务端已配置目录中的Release Note候选及已登记资料，不假设软件版本连续，也不代表全部历史发布资料。'
_INFORMATIONAL = {'index_mismatch', 'candidate_version_mismatch', 'source_alias_label'}


def _roots(config: dict) -> list[dict]:
    result = []
    for label, values, controlled, broad in (
        ('RELEASE_NOTE_ROOT', [config.get('RELEASE_NOTE_ROOT')], False, False),
        ('CONTROLLED_EXTRACTION_ROOTS', config.get('CONTROLLED_EXTRACTION_ROOTS') or [], False, True),
        ('SOURCE_ROOTS', config.get('SOURCE_ROOTS') or [], False, True),
        ('CONTROLLED_MATERIALS_ROOT/发布记录',
         [str(Path(config['CONTROLLED_MATERIALS_ROOT']) / '发布记录')] if config.get('CONTROLLED_MATERIALS_ROOT') else [], True, False),
    ):
        for value in values:
            if value:
                result.append({'label': label, 'path': str(Path(value).expanduser()), 'controlled': controlled, 'broad': broad})
    return result


def scan_configured_sources(config: dict) -> dict:
    """Blocking I/O; callers must run this in a worker thread. Never follow links."""
    roots, files = [], []
    for spec in _roots(config):
        root = Path(spec['path'])
        report = {'label': spec['label'], 'path': str(root), 'status': 'scanned'}
        roots.append(report)
        errors = []
        try:
            if root.is_symlink():
                raise OSError('配置根目录为符号链接，未扫描')
            if not root.exists():
                report.update(status='missing', error='已配置目录不存在')
                continue
            if not root.is_dir():
                raise OSError('配置路径不是目录')
            resolved = root.resolve(strict=True)

            def walk(directory: Path) -> None:
                try:
                    with os.scandir(directory) as entries:
                        for entry in entries:
                            if entry.name.startswith(('.', '~$', '~')) or entry.is_symlink():
                                continue
                            path = Path(entry.path)
                            try:
                                path.resolve(strict=True).relative_to(resolved)
                                if entry.is_dir(follow_symlinks=False):
                                    walk(path)
                                elif entry.is_file(follow_symlinks=False) and path.suffix.lower() in {'.pdf', '.docx', '.doc'}:
                                    if spec['broad'] and not _RN.search(str(path.relative_to(resolved)) + '/' + root.name):
                                        continue
                                    files.append({'path': str(path.resolve()), 'file_name': path.name,
                                                  'sha256': _file_sha256(path), 'controlled': spec['controlled']})
                            except (OSError, ValueError) as error:
                                errors.append(f'{path}: {error}')
                except OSError as error:
                    errors.append(f'{directory}: {error}')
            walk(root)
        except OSError as error:
            errors.append(str(error))
        if errors:
            report.update(status='error', error='；'.join(errors))
    return {'roots': roots, 'files': files}


def _issue(code: str, reason: str, action: str) -> dict:
    return {'code': code, 'reason': reason, 'action': action}


def _candidate_versions(locations: list[str]) -> set[str]:
    return {value for location in locations for part in (Path(location).stem, Path(location).parent.name)
            for value in _VERSION.findall(part)}


async def release_coverage(session, supplied_scope: dict | None = None) -> dict:
    scope = await resolve_query_scope(session, supplied_scope) if supplied_scope is not None else None
    if supplied_scope is not None and scope is None:
        raise ReleaseHistoryError('查询范围不完整，请补齐市场、完整机型和目标软件版本，或明确选择全局检查')
    report: dict[str, Any] = {'checked_at': datetime.now(timezone.utc).isoformat(),
        'boundary': 'configured_directories_and_registered_release_notes', 'message': _MESSAGE,
        'scan_status': 'unavailable', 'completeness': 'unverified', 'scope': scope, 'roots': [],
        'totals': {'files': 0, 'registered': 0, 'ready': 0, 'gaps': 0, 'later': 0, 'unresolved': 0}, 'items': []}
    try:
        canonical = session.get_bind().url.database
        config = await asyncio.to_thread(load_release_workbench_config, canonical_database=canonical)
        scan = await asyncio.to_thread(scan_configured_sources, config)
    except (OSError, ValueError, TypeError) as error:
        report['message'] += f' 配置或来源扫描不可用：{error}'
        scan = {'roots': [], 'files': []}
    else:
        roots = scan['roots']
        report['scan_status'] = ('not_configured' if not roots else 'checked' if all(row['status']=='scanned' for row in roots)
                                 else 'partial' if any(row['status']=='scanned' for row in roots) or scan['files'] else 'unavailable')
    report['roots'] = scan['roots']
    try:
        documents = await _documents(session)
        chunks: dict[int, list] = {}
        rows = (await session.execute(text('''SELECT c.document_id,c.source_ref,c.page_number,c.content
            FROM knowledge_document_chunks c JOIN knowledge_documents d ON d.id=c.document_id
            WHERE d.document_type='release_note' ORDER BY c.document_id,c.chunk_index'''))).mappings()
        for row in rows:
            chunks.setdefault(row['document_id'], []).append(dict(row))
    except SQLAlchemyError:
        report['message'] += ' 登记或提取台账不可用。'
        report['scan_status'] = 'partial' if scan['files'] else 'unavailable'
        return report
    groups: dict[str, dict] = {}
    for file in scan['files']:
        group = groups.setdefault(file['sha256'], {'files': [], 'documents': []})
        if not any(row['path']==file['path'] and row['controlled']==file['controlled'] for row in group['files']):
            group['files'].append(file)
    for document in documents:
        key = document['sha256'] or f"document:{document['id']}"
        groups.setdefault(key, {'files': [], 'documents': []})['documents'].append(document)
    for key, group in groups.items():
        registered = group['documents']
        locations = sorted({row['path'] for row in group['files']} | {row['file_path'] for row in registered})
        item: dict[str, Any] = {'key': key, 'file_name': Path(locations[0]).name if locations else '', 'version': None,
                'version_basis': 'unknown', 'language': 'unknown', 'source_locations': locations,
                'document_ids': [row['id'] for row in registered],
                'registration_status': 'registered' if registered else 'unregistered',
                'extraction_status': 'not_registered', 'applicability_status': 'not_requested' if scope is None else 'unrecognized',
                'range_status': 'not_requested' if scope is None else 'unknown', 'issues': [], 'is_gap': False}
        issues = item['issues']
        versions, applicable, source_models, statuses = set(), [], [], []
        for document in registered:
            reasons = await _quality(document)
            # A valid cover can repair a missing/stale index version in a read-only projection.
            quality = [reason for reason in reasons if reason != '缺少明确软件版本']
            extracted = document['extraction_status']
            statuses.append('stale' if document['extraction_sha256'] != document['sha256'] or extracted=='stale'
                            else extracted if extracted in {'completed','failed','pending'} else 'pending')
            for reason in quality:
                code = ('source_unavailable' if '原件不可用' in reason or '无法读取' in reason else
                        'source_changed' if '摘要' in reason else 'extraction_unready' if '提取' in reason else 'inactive')
                issues.append(_issue(code, f"登记资料#{document['id']}：{reason}", '核对受控原件并重新提取，保留原始来源'))
            if not quality:
                facts = extract_source_applicability(document, chunks.get(document['id'], []))
                if facts['version']:
                    versions.add(facts['version']['value'])
                for issue in facts['issues']:
                    issues.append(_issue('source_fact_conflict', f"登记资料#{document['id']}，字段{issue['field']}：{issue.get('reason') or issue.get('question')}", '核对所引原文中互相矛盾的声明'))
                for issue in facts['index_issues']:
                    issues.append(_issue('index_mismatch', f"登记资料#{document['id']}，字段{issue['field']}：登记值{issue['registered_value']}，原文值{issue['source_value']}。{issue['reason']}", '按明确原文修正登记索引'))
                source_models.extend(facts['models'])
                if scope:
                    model = model_facts(facts, scope['model_name'])
                    country_mismatch = document['country'] and scope['country'] and document['country'] != scope['country']
                    market_mismatch = document['market'] in {'domestic','overseas'} and document['market'] != scope['market']
                    applicable.append('applicable' if model['applicable'] and not country_mismatch and not market_mismatch
                                      else 'not_applicable' if model['explicitly_excluded'] or (facts['models'] and not model['models']) or country_mismatch or market_mismatch else 'unrecognized')
            if not quality and not chunks.get(document['id']):
                issues.append(_issue('extraction_empty', f"登记资料#{document['id']}无已提取正文", '重新提取受控原件'))
        if statuses:
            item['extraction_status'] = next((value for value in ('stale','failed','pending') if value in statuses), 'completed')
            item['preview_url'] = f"/api/knowledge/documents/{registered[0]['id']}/preview"
        else:
            issues.append(_issue('unregistered', '来源候选尚未登记', '先核对正式发布资格及适用范围，再按现有受控入库流程处理'))
        if not any(file['controlled'] for file in group['files']):
            issues.append(_issue('uncontrolled', '未在配置的受控目录中找到相同摘要文件', '核对受控副本及扫描目录配置'))
        if any(Path(location).suffix.lower()=='.doc' for location in locations):
            item['extraction_status'] = 'unsupported'
            issues.append(_issue('unsupported_format', '旧版DOC仅列为候选，不支持当前正文提取', '通过既有文档流程准备受控可提取版本'))
        if any(re.search(r'副本|瘦身|压缩|软件验证|材料', Path(location).stem + '/' + Path(location).parent.name) for location in locations):
            if versions and source_models:
                issues.append(_issue('source_alias_label', '相同摘要的来源别名含副本或中间材料标记，已保留来源路径；有效原文声明仍可用', '需要时核对来源别名，无需重复确认明确原文事实'))
            else:
                issues.append(_issue('release_qualification_unverified', '候选名称含副本、验证或中间材料标记，不能视为正式发布', '核对最终发布资格，不直接批量入库'))
        candidates = _candidate_versions(locations)
        if len(versions)==1:
            item.update(version=next(iter(versions)), version_basis='source_extract')
            if candidates and candidates != versions:
                issues.append(_issue('candidate_version_mismatch', '来源名称候选版本与正文版本不同', '核对文件命名及正式发布资格，以明确原文为依据'))
        elif len(versions)>1:
            issues.append(_issue('source_version_conflict', '同摘要登记资料的正文版本互相矛盾', '核对所引受控正文与提取记录'))
        elif len(candidates)==1:
            item.update(version=next(iter(candidates)), version_basis='filename_candidate')
        elif len(candidates)>1:
            issues.append(_issue('candidate_version_conflict', '文件名与所在目录存在多个候选版本', '核对原文版本，不能仅按文件名绑定'))
        else:
            issues.append(_issue('version_unrecognized', '尚未从可靠原文识别版本', '提取或核对正文版本'))
        if scope:
            item['applicability_status'] = ('applicable' if applicable and all(value=='applicable' for value in applicable)
                                          else 'not_applicable' if applicable and all(value=='not_applicable' for value in applicable) else 'unrecognized')
            if item['version']:
                item['range_status'] = 'after_target' if version_sort_key(item['version']) > version_sort_key(scope['software_version']) else 'within_target'
            if item['applicability_status']=='unrecognized':
                issues.append(_issue('applicability_unrecognized', '尚未从有效原文确定本次机型适用范围，不能断言该型号缺失此版本', '核对候选正文中的整版适用声明'))
        elif not source_models:
            issues.append(_issue('applicability_unrecognized', '尚未从有效原文识别整版适用型号', '核对候选正文中的整版适用声明'))
        outside = item['range_status']=='after_target' or item['applicability_status']=='not_applicable'
        material_issues = [issue for issue in issues if issue['code'] not in _INFORMATIONAL]
        item['is_gap'] = bool(material_issues) and not outside
        report['items'].append(item)
    totals = report['totals']
    totals.update(files=len({file['path'] for file in scan['files']}), registered=len(documents),
        ready=sum(item['registration_status']=='registered' and not any(issue['code'] not in _INFORMATIONAL for issue in item['issues']) for item in report['items']),
        gaps=sum(item['is_gap'] for item in report['items']), later=sum(item['range_status']=='after_target' for item in report['items']),
        unresolved=sum(any(issue['code'] in {'version_unrecognized','candidate_version_conflict','applicability_unrecognized','source_version_conflict','source_fact_conflict','release_qualification_unverified'} for issue in item['issues']) for item in report['items']))
    report['completeness'] = ('gaps_found' if totals['gaps'] else 'no_known_gaps'
                              if report['scan_status']=='checked' and not totals['unresolved'] else 'unverified')
    return report

"""Read-only applicability suggestions from the same safe, current previews as search.

Rule confidence expresses the strength of the source declaration, not a
statistical probability. Suggestions never change a scope or a review status.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tracker.database import Database
from tracker.services.document_scopes import MAX_MODEL_SCOPE_LENGTH, matches_model_scope
from tracker.services.search_index import SearchIndex
from tracker.services.unified_search import resolve_source_candidate

_SUFFIX = r'(?:Super|Max|Pro|Exp|Plus|Elite|Expert|Mega|Premium|Prime|Senior)'
_TOKEN = rf'(?:G[12]|\d{{1,3}}(?:\s*(?:EXP|PRO|[EPLGST])(?![a-z]))?(?:\s+{_SUFFIX}(?![a-z]))?|{_SUFFIX}(?![a-z]))'
_MODEL = re.compile(rf'\b(VINNO|ULTIMUS)\s*({_TOKEN})(?![a-z0-9])', re.I)
_CONTINUATION = re.compile(rf'\s*[/_、,，]\s*({_TOKEN})(?![a-z0-9])', re.I)
_EZONO = re.compile(r'\beZono\s*\d{3,5}(?!\d)', re.I)
_EDITION = re.compile(r'\s*(综合版|全身应用版|妇产版)')
_LABEL = re.compile(r'(?:适用机型|适用型号|产品型号|型号规格|型号|models?)\s*[:：]', re.I)
_STOP = re.compile(r'(?:版本|日期|出版|联系方式|适用范围|version|date)\s*[:：]|功能|Applicable\s+models|[。；\n]', re.I)
_FAMILY = re.compile(r'\b(VINNO|ULTIMUS)\s*(?:系列|Series(?![a-z]))', re.I)


def _models(text: str) -> list[str]:
    # Filenames concatenate headings with names; headings are not model suffixes.
    text = re.sub(r'Release\s*Note', ' Release Note', text, flags=re.I)
    text = re.sub(r'\b(?:V\s*I\s*N\s*N\s*O|U\s*L\s*T\s*I\s*M\s*U\s*S)\b',
                  lambda m: re.sub(r'\s', '', m[0]), text, flags=re.I)
    text = re.sub(r'(?<=\d)(?:\s*E\s*X\s*P|\s*P\s*R\s*O)(?![a-z])',
                  lambda m: re.sub(r'\s', '', m[0]).upper(), text, flags=re.I)
    result: list[str] = []

    def add(brand: str, token: str, tail: str = '') -> None:
        token = re.sub(r'(?<=\d)\s+(?=[EPLGST]\b)', '', token, flags=re.I)
        token = re.sub(r'(\d)(exp|pro)\b', lambda m: m[1] + m[2].upper(), token, flags=re.I)
        token = re.sub(r'(\d)([eplgst])\b', lambda m: m[1] + m[2].upper(), token, flags=re.I)
        token = re.sub(_SUFFIX, lambda m: m[0].capitalize(), token, flags=re.I) if ' ' in token or not token[0].isdigit() else token
        edition = _EDITION.match(tail)
        result.append(f'{brand.upper()} {token.strip()}' + (f' {edition[1]}' if edition else ''))

    for match in _MODEL.finditer(text):
        add(match[1], match[2], text[match.end():])
        offset = match.end()
        while continuation := _CONTINUATION.match(text, offset):
            add(match[1], continuation[1], text[continuation.end():])
            offset = continuation.end()
    result.extend('eZono' + re.sub(r'\D', '', match[0]) for match in _EZONO.finditer(text))
    return list(dict.fromkeys(result))


def suggestion_matches(suggestion: dict[str, Any], model: str) -> bool:
    """Exact model suggestions only; a series does not imply every variant."""
    return suggestion.get('status') == 'suggested' and matches_model_scope(
        '、'.join(suggestion.get('models', [])), model, include_unknown=False)


def suggest_document_scope(database: Database, index: SearchIndex, document: dict[str, Any],
                           *, candidates: dict[str, dict[str, Any]] | None = None, **roots: Any) -> dict[str, Any]:
    """Resolve current files on each read; stale or revoked evidence is unusable."""
    version = next((row for row in database.list_document_versions(document['id'])
                    if row['id'] == document['current_version_id']), None)
    result: dict[str, Any] = {
        'document_id': document['id'], 'version_id': document['current_version_id'],
        'status': 'unmatched', 'confidence': 'none', 'scope_kind': 'model',
        'models': [], 'families': [], 'model_scope': '', 'basis': '', 'evidence': [],
        'message': '未找到明确的机型声明，可打开原文补充范围。',
    }
    if version is None:
        result.update(status='unavailable', message='当前版本尚未登记。')
        return result
    if document['status'] != '有效' or version['status'] != '有效':
        result.update(status='unavailable', message='资料或当前版本已失效，不提供适用范围建议。')
        return result

    previews = []
    unavailable = False
    for role in ('pdf', 'docx'):
        if not version[f'path_{role}']:
            continue
        source_id = f"controlled:{version['id']}:{role}"
        try:
            candidate = candidates.get(source_id) if candidates is not None else resolve_source_candidate(database, source_id, **roots)
            metadata = index.source_metadata(source_id) if candidate else None
            if not candidate or candidate.get('access_status', 'accessible') != 'accessible' or not metadata or Path(metadata['path']).resolve() != candidate['path'].resolve():
                unavailable = True
                continue
            preview = index.preview(source_id)
            if not preview or preview['stale']:
                unavailable = True
                continue
            previews.append((source_id, preview))
        except OSError:
            unavailable = True
    # Do not hide a changed original behind an otherwise readable extraction.
    if unavailable or not previews:
        result.update(status='unavailable', message='来源已变化、未接入或尚未索引；更新资料索引后重新匹配。')
        return result

    title_models = _models(document['title'])
    if re.search(r'注册型号差异', document['title']):
        title_models = [model for model in title_models if not re.fullmatch(r'ULTIMUS G[12]', model)]
    is_release = document['doc_type'] == '发布记录' or bool(re.search(r'Release\s*Note', document['title'], re.I))
    declarations: list[dict[str, Any]] = []
    covers: list[dict[str, Any]] = []

    def evidence(models: list[str], source: str, locator: str, text: str, kind: str) -> dict[str, Any]:
        return {'models': models, 'preview_id': source, 'locator': locator,
                'excerpt': text[:3000], 'kind': kind}

    for source_id, preview in previews:
        table_column: int | None = None
        table_location = ''
        for position, chunk in enumerate(preview['chunks']):
            text, locator = chunk['text'], chunk['locator']
            if preview['file_format'] == 'md' and ' · ' in text:
                text = text.split(' · ', 1)[1]
            # Spreadsheet applicability tables explicitly name the model column.
            cells = [cell.strip() for cell in text.split(' | ')]
            if len(cells) > 1:
                if is_release:
                    continue
                if '型号' in cells:
                    if cells[0] not in {'型号', '序号'} or any(cell in {'功能', '功能名称', '性能', '参数', '探头', '探头型号', '应用', '临床应用'} for cell in cells):
                        table_column = None
                        continue
                    table_column, table_location = cells.index('型号'), locator.split(' · ')[0]
                    header_models = _models(' '.join(cells[table_column + 1:]))
                    if header_models:
                        declarations.append(evidence(header_models, source_id, locator, text, 'model_table'))
                elif table_column is not None and locator.split(' · ')[0] == table_location and len(cells) > table_column:
                    models = _models(cells[table_column])
                    if models:
                        declarations.append(evidence(models, source_id, locator, text, 'model_table'))
                continue

            label = _LABEL.search(text) if not is_release else None
            if label:
                prefix = text[max(0, label.start() - 80):label.start()].strip()
                global_context = bool(re.search(r'本(?:资料|文档|手册|版本)|用户手册|产品(?:适用)?$', prefix))
                generic_applicability = label[0].startswith('适用')
                if (re.search(r'功能|Applicable\s*$|变更前', prefix, re.I)
                        or generic_applicability and not global_context and not (position == 0 and not prefix)
                        or not generic_applicability and prefix and not global_context and not label[0].startswith('产品型号')):
                    label = None
            declaration = ''
            registration = re.search(r'(?:型号[、，]?规格|规格型号)(?:变更|，由|\s)', text) if not is_release else None
            after_field = re.search(r'变更后\s*(?:型号[、，]?规格|规格型号)\s*[:：]?\s*', text) if not is_release else None
            if after_field:
                declaration = re.split(r'[。；]|结构及组成|主要组成', text[after_field.end():], maxsplit=1)[0]
            elif registration:
                declaration = re.split(r'结构及组成|主要组成|产品技术要求|备\s*注|变更情况', text[registration.end():])[0]
                if '变更后' in declaration:
                    declaration = declaration.split('变更后', 1)[1]
                elif '变更为' in declaration:
                    declaration = declaration.split('变更为', 1)[1]
                elif declaration.startswith('前') or '变更前' in declaration:
                    continue
                if '“' in declaration and '”' in declaration:
                    declaration = declaration.split('“', 1)[1].split('”', 1)[0]
            elif label:
                declaration = _STOP.split(text[label.end():], maxsplit=1)[0]
            elif not is_release and '以下简称本产品' in text:
                declaration = re.split(r'[（(]以下简称本产品', text, maxsplit=1)[0]
                declaration = re.split(r'简介', declaration)[-1]
            if declaration and (models := _models(declaration)):
                excerpt = text[label.start():label.end()] + declaration if label else declaration
                declarations.append(evidence(models, source_id, locator, excerpt, 'model_declaration'))
                continue
            # Covers and release headings precede technical content. Ordinary
            # comparisons or examples elsewhere never become scope evidence.
            cover = locator == '第 1 页' or (position < 8 and not locator.startswith('第 '))
            cover_text = re.split(r'Release\s*Note', text, maxsplit=1, flags=re.I)[0] if is_release else re.split(r'[。；]|性能比较|对比|测试示例', text, maxsplit=1)[0]
            heading = re.search(r'(?:白皮书|用户手册|技术手册|Release\s*Note|^\s*(?:VINNO|ULTIMUS)\s*\d|\d+\.\d+\.\d+\s*[（(])', text, re.I)
            models = _models(cover_text[:500]) if cover and heading else []
            if models:
                covers.append(evidence(models, source_id, locator, cover_text[:500], 'cover'))

    # Original and extraction must agree on explicit scope when both declare it.
    evidence_rows = []
    conflict = False
    source_sets = []
    for source, _ in previews:
        source_declarations = [row for row in declarations if row['preview_id'] == source]
        source_covers = [row for row in covers if row['preview_id'] == source]
        declared = {model for row in source_declarations for model in row['models']}
        covered = {model for row in source_covers for model in row['models']}
        source_rows = source_declarations or source_covers
        if source_rows:
            source_sets.append({model for row in source_rows for model in row['models']})
            evidence_rows.extend(source_rows)
        if declared and covered and not covered.issubset(declared):
            conflict = True
            evidence_rows.extend(source_covers)
    models = list(dict.fromkeys(model for row in evidence_rows for model in row['models']))
    conflict = conflict or len(source_sets) > 1 and any(values != source_sets[0] for values in source_sets[1:])
    if title_models and models and not set(title_models).issubset(models):
        conflict = True
    if not models and title_models:
        models = title_models
    if title_models:
        evidence_rows = evidence_rows + [evidence(title_models, '', '资料标题', document['title'], 'title')]
    if not models:
        family_rows = [evidence([m[1].upper()], source, chunk['locator'], chunk['text'][:500], 'family')
                       for source, preview in previews for chunk in preview['chunks'][:8]
                       if (m := _FAMILY.search(chunk['text'][:500]))]
        if family_rows:
            result.update(status='suggested', confidence='medium', scope_kind='family',
                          families=list(dict.fromkeys(family for row in family_rows for family in row['models'])),
                          evidence=family_rows, message='已识别资料所属系列，具体适用机型尚需确认；不自动扩展到所有机型。')
        return result
    series = any(re.search(r'系列|\bseries\b', row['excerpt'], re.I) for row in evidence_rows)
    scope = '、'.join(models)
    result.update(models=models, evidence=evidence_rows, scope_kind='series' if series else 'model',
                  status='conflict' if conflict else 'suggested',
                  confidence='low' if conflict else 'medium' if series or not declarations and not covers else 'high',
                  model_scope='' if conflict or len(scope) > MAX_MODEL_SCOPE_LENGTH else scope,
                  basis='智能匹配建议：' + '；'.join(f"{row['locator']}：{row['excerpt']}" for row in evidence_rows[:3])[:1800],
                  message='标题与正文或原件与抽取源的范围不一致，请核对原文。' if conflict else
                  '原文列出适用系列，仅匹配列出的名称，不扩展其派生机型。' if series else
                  '仅标题提供机型线索，需核对原文。' if not declarations and not covers else '已从原文机型声明识别范围，待确认。')
    if len(scope) > MAX_MODEL_SCOPE_LENGTH:
        result['message'] += ' 型号清单较长，请按实际使用范围选择机型。'
    return result

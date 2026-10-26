"""Explicit search vocabulary and version constraints, shared by saved searches."""
from __future__ import annotations

import re

from tracker.domain import version_key, matching_excerpt


TASKS = {'search', 'earliest', 'version', 'family'}
VERSION_PATTERN = r'(?<![\d.])(\d+\.\d+\.\d+)(?![\d.])'
SCENARIO_TERMS = ('无中断转换', '后台转换', '后台导出', '后台备份', '用户界面保持响应', '继续扫查')
FAMILY_PATTERN = re.compile(r'(?<![A-Za-z0-9])V(Aid|Aim)\s*(\+|＋|Plus\b)?(?![A-Za-z0-9+＋])', re.I)


def parse_version_selection(value: str = '') -> tuple[str, ...]:
    """Normalize a bounded union of explicit versions and major/minor series."""
    if not isinstance(value, str) or len(value) > 400:
        raise ValueError('版本选择最多 400 个字符。')
    tokens = [token for token in re.split(r'[,，、;；\s]+', value.strip()) if token]
    if len(tokens) > 20:
        raise ValueError('一次最多选择 20 个版本或系列。')
    selected = []
    for token in tokens:
        match = re.fullmatch(r'(\d{1,5})\.(\d{1,5})\.(\d{1,5}|[xX]{1,2}|\*)', token)
        if not match:
            raise ValueError('版本格式无效；可填写 1.14.XX 或 1.51.20,1.51.21。')
        major, minor, patch = match.groups()
        selected.append(f'{int(major)}.{int(minor)}.{int(patch) if patch.isdigit() else "*"}')
    return tuple(dict.fromkeys(selected))


def validate_search_task(task: str, version_from: str, version_to: str, versions: str = '') -> None:
    if task not in TASKS:
        raise ValueError('请选择查找资料、查首次记载、查某版本是否提及或查功能包含哪些能力。')
    for value in (version_from, version_to):
        if not isinstance(value, str) or value and not re.fullmatch(r'\d{1,5}\.\d{1,5}\.\d{1,5}', value):
            raise ValueError('版本须填写三个数字段，例如 1.14.0 至 1.14.100；不支持 XX 通配符。')
    if version_from and version_to and version_key(version_from) > version_key(version_to):
        raise ValueError('起始版本不能晚于结束版本。')
    selected = parse_version_selection(versions)
    if selected and (version_from or version_to):
        raise ValueError('版本选择和起止范围不能同时填写，请保留一种方式。')
    if task == 'version' and not selected and (not version_from or version_from != version_to):
        raise ValueError('请选择要核对的版本或系列；也可将起始和结束版本设为同一版本。')


def in_version_range(version: str, version_from: str = '', version_to: str = '',
                     selected_versions: tuple[str, ...] = ()) -> bool:
    if selected_versions:
        if not version:
            return False
        key = version_key(version)
        return any(key[:2] == version_key(item[:-2]) if item.endswith('.*')
                   else key == version_key(item) for item in selected_versions)
    if not version_from and not version_to:
        return True
    return bool(version and (not version_from or version_key(version) >= version_key(version_from))
                and (not version_to or version_key(version) <= version_key(version_to)))


def located_version(locator: str, title: str = '') -> str:
    """A sheet's version wins over a workbook title; ambiguous labels stay unknown."""
    for text in (locator, title):
        matches = list(dict.fromkeys(re.findall(VERSION_PATTERN, text)))
        if matches:
            return matches[0] if len(matches) == 1 else ''
    return ''


def family_name(query: str) -> str:
    match = FAMILY_PATTERN.fullmatch(query.strip())
    return f'V{match[1].lower()}{"+" if match[2] else ""}' if match else ''


def family_mentions(text: str, query: str) -> bool:
    return family_position(text, query) >= 0


def family_position(text: str, query: str) -> int:
    family = family_name(query)
    if not family:
        return text.casefold().find(query.casefold())
    return next((m.start() for m in FAMILY_PATTERN.finditer(text)
                 if f'V{m[1].lower()}{"+" if m[2] else ""}' == family), -1)


def family_excerpt(text: str, query: str) -> str:
    return matching_excerpt(text, query, radius=180, match_index=family_position(text.strip(), query))


def search_terms(query: str, expand_related: bool, task: str) -> list[str]:
    terms = [query]
    family = family_name(query)
    if family.endswith('+') and task == 'family':
        base = 'VAid' if family == 'Vaid+' else 'VAim'
        terms.extend(base + suffix for suffix in ('+', '＋', ' Plus', 'Plus', ' +', ' ＋'))
    # A workflow description needs both the operation and concurrent interaction.
    scenario = (any(word in query for word in ('导出', '备份', '转换'))
                and any(word in query for word in ('后台', '异步', '继续', '扫查', '操作', '无中断', '响应')))
    if expand_related and (scenario or query in SCENARIO_TERMS):
        terms.extend(SCENARIO_TERMS)
    return list(dict.fromkeys(terms))

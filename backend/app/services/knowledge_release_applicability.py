"""Derive source-written release applicability without inventing an approval."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

_VERSION = r'\d+\.\d+(?:\.\d+){1,2}'
_COVER = re.compile(rf'^\s*({_VERSION})\s*[（(]([^）)]+)[）)]', re.I)
_MODEL = re.compile(r'(?<![A-Za-z0-9])(?:VINNO\s*|V\s*)(\d{1,2}\s*(?:PRO|EXP|POC|SUPER|S|P|E|L|T)?)(?![A-Za-z0-9])', re.I)
_SHORT = re.compile(r'/\s*(?:VINNO\s*|V\s*)?(\d{1,2}\s*(?:PRO|EXP|POC|SUPER|S|P|E|L|T)?)(?![A-Za-z0-9])', re.I)
_CODE = re.compile(r'((?:VINNO\s*|V\s*)\d{1,2}\s*(?:PRO|EXP|POC|SUPER|S|P|E|L|T)?)\s*[（(]\s*(V\d{4,})\s*[）)]', re.I)


def canonical_model(value: str) -> str:
    token = re.sub(r'\s+', '', value).upper()
    token = re.sub(r'^(?:VINNO|V)', '', token)
    # POC is a separately preserved source profile, not a suffix to discard silently.
    token = re.sub(r'POC$', '', token)
    return 'VINNO ' + token


def _models(value: str) -> list[str]:
    found = [canonical_model(match[1]) for match in _MODEL.finditer(value)]
    if found:
        found.extend(canonical_model(match[1]) for match in _SHORT.finditer(value))
    return list(dict.fromkeys(found))


def _codes(value: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for match in _CODE.finditer(value):
        result.setdefault(canonical_model(match[1]), []).append(match[2].upper())
    return result


def _reference(document: dict, chunk: dict, excerpt: str) -> dict:
    return {'document_id': document['id'], 'source_ref': chunk['source_ref'],
            'page_number': chunk.get('page_number'), 'excerpt': excerpt.strip(),
            'preview_url': f"/api/knowledge/documents/{document['id']}/preview"}


def extract_source_applicability(document: dict, chunks: list[dict]) -> dict:
    result: dict = {'provenance': 'source_extract', 'status': 'incomplete', 'models': [], 'version': None,
        'profiles': [], 'upgrades': [], 'restrictions': [], 'field_evidence': [], 'issues': [],
        'country': {'value': document.get('country'), 'status': 'registered' if document.get('country') else 'not_stated'},
        'market': {'value': document.get('market') if document.get('market') not in ('', None, 'unspecified') else None,
                   'status': 'registered' if document.get('market') not in ('', None, 'unspecified') else 'not_stated'}}
    declared: dict[str, dict] = {}
    cover_models: list[str] = []

    def fact(field: str, label: str, value: str, ref: dict) -> None:
        row = {'field': field, 'label': label, 'value': value, **ref}
        if row not in result['field_evidence']:
            result['field_evidence'].append(row)

    def declare(names: list[str], scope: str, ref: dict) -> None:
        for name in names:
            if name not in declared or (scope == 'exact' and declared[name]['scope'] == 'series'):
                declared[name] = {'name': name, 'scope': scope, **ref}
        if names:
            fact('models', '适用型号', '、'.join(names) + ('（系列）' if scope == 'series' else ''), ref)

    # Only body-written cover/model declarations qualify; metadata titles alone do not.
    for chunk in chunks:
        for raw in chunk['content'].splitlines():
            line = unicodedata.normalize('NFKC', raw)
            cover = _COVER.search(line)
            if cover and _models(cover[2]):
                ref = _reference(document, chunk, raw)
                if result['version'] is None:
                    result['version'] = {'value': cover[1], **ref}
                    fact('version', '软件版本', cover[1], ref)
                    cover_models = _models(cover[2])
                    declare(cover_models, 'series' if '系列' in cover[2] else 'exact', ref)
            elif result['version'] is None:
                match = re.search(rf'(?:Release\s*Note|软件版本|版本)\s*[:：_ ]*({_VERSION})|^\s*({_VERSION})\s*(?:版本|Release\s*Note)', line, re.I)
                if match:
                    version = match[1] or match[2]
                    ref = _reference(document, chunk, raw)
                    result['version'] = {'value': version, **ref}
                    fact('version', '软件版本', version, ref)
    subjects = list(cover_models)
    for chunk in chunks:
        # PDF wraps are retained in the reference; sentence matching uses folded whitespace.
        for raw in re.split(r'[。！？!?；;]', chunk['content']):
            sentence = re.sub(r'\s+', '', unicodedata.normalize('NFKC', raw))
            if not sentence:
                continue
            ref = _reference(document, chunk, raw)
            names = _models(sentence)
            positive = bool(re.search(r'适用于|适用型号|首次发放.*包括|新增.*机型', sentence))
            if positive and not re.search(r'不适用|未适用|不支持.*(?:升级|型号)', sentence):
                declare(names, 'series' if re.search(r'V\d+(?:PRO|EXP)?系列', sentence, re.I) else 'exact', ref)
            explicit_subject = re.search(r'针对(.+?)(?:来说|此次|本次|，|,)', sentence)
            if explicit_subject:
                names = _models(explicit_subject[1])
                subjects = names
            elif re.search(r'另外|同样适用|适用型号|首次发放.*包括|新增.*机型', sentence) and names:
                subjects = names
            applies_to = names if names and (positive or explicit_subject) else list(subjects or cover_models)
            if re.search(r'不支持.*升级|不能.*升级|不允许.*升级|不适用.*(?:机器|型号)', sentence):
                # Explicitly excluded models/code lists supersede a global document subject.
                excluded = names if explicit_subject else _models(sentence)
                restriction = {'kind': 'not_upgradable', 'applies_to': excluded or applies_to,
                               'excluded_v_codes': [code for values in _codes(sentence).values() for code in values],
                               'v_codes_by_model': _codes(sentence), **ref}
                if restriction not in result['restrictions']:
                    result['restrictions'].append(restriction)
                    fact('restrictions', '升级限制', '、'.join(restriction['applies_to']) + '：' + sentence, ref)
                continue
            platform = 'VLucid+' if re.search(r'VLucid\+', sentence, re.I) else 'POC' if re.search(r'POC.*首次发放|新增.*用于POC', sentence, re.I) else None
            if platform and applies_to:
                codes = _codes(sentence) if positive else {}
                profile = {'name': platform, 'applies_to': applies_to,
                           'v_codes': [code for values in codes.values() for code in values], 'v_codes_by_model': codes, **ref}
                if profile not in result['profiles']:
                    result['profiles'].append(profile)
                    fact('profiles', '硬件平台/机型规格', platform + '：' + '、'.join(applies_to) + ('；' + '、'.join(profile['v_codes']) if profile['v_codes'] else ''), ref)
            upgrade = re.search(rf'(?:支持)?从({_VERSION})(?:版本)?(?:进行)?升级', sentence)
            if upgrade and applies_to:
                row = {'from_version': upgrade[1], 'to_version': result['version']['value'] if result['version'] else None,
                       'platform': platform, 'applies_to': applies_to, **ref}
                result['upgrades'].append(row)
                fact('upgrades', '明确升级路径', f"{upgrade[1]} → {row['to_version']}（{'、'.join(applies_to)}，{platform or '平台未单列'}）", ref)
    result['models'] = list(declared.values())
    if result['version'] and document.get('version') and result['version']['value'] != document['version']:
        result['issues'].append({'field': 'version', 'question': '原文版本与登记版本不一致，哪一项需要纠正？',
            'reason': f"登记为{document['version']}，原文封面为{result['version']['value']}", 'evidence_refs': [result['version']]})
    if result['issues']:
        result['status'] = 'conflict'
    elif result['models'] and result['version']:
        result['status'] = 'extracted'
    return result


def model_facts(facts: dict, model_name: str) -> dict:
    name = canonical_model(model_name)
    matching = [row for row in facts['models'] if row['name'] == name]
    result: dict[str, Any] = {'applicable': bool(matching) and facts['status'] == 'extracted',
              'models': matching, 'profiles': [], 'upgrades': [], 'restrictions': []}
    for field in ('profiles', 'upgrades', 'restrictions'):
        for row in facts[field]:
            if name not in row['applies_to']:
                continue
            item = {**row}
            if row.get('v_codes_by_model'):
                key = 'excluded_v_codes' if field == 'restrictions' else 'v_codes'
                item[key] = row['v_codes_by_model'].get(name, [])
            result[field].append(item)
    return result


def source_chain_groups(rows: list[dict], model_name: str) -> dict[int, str]:
    """Join documents only through an explicit, matching-platform upgrade edge."""
    parents = {row['document']['id']: row['document']['id'] for row in rows}
    def find(value):
        while parents[value] != value:
            value = parents[value]
        return value
    for target in rows:
        target_facts = model_facts(target['facts'], model_name)
        for upgrade in target_facts['upgrades']:
            if not upgrade['platform']:
                continue
            for source in rows:
                source_facts = model_facts(source['facts'], model_name)
                if (source['document']['version'] == upgrade['from_version']
                        and target['document']['version'] == upgrade['to_version']
                        and source['document'].get('country') == target['document'].get('country')
                        and source['document'].get('market') == target['document'].get('market')
                        and any(profile['name'] == upgrade['platform'] for profile in source_facts['profiles'])):
                    parents[find(target['document']['id'])] = find(source['document']['id'])
    groups = {}
    for row in rows:
        own = model_facts(row['facts'], model_name)
        profiles = '、'.join(sorted({value['name'] for value in own['profiles']}))
        root = next(item for item in rows if item['document']['id'] == find(row['document']['id']))
        groups[row['document']['id']] = f"原文：{canonical_model(model_name)} · {profiles or '平台未单列'} · {root['document']['version']}"
    return groups


def scoped_condition_evidence(facts: dict, model_name: str) -> list[dict]:
    scoped = model_facts(facts, model_name)
    result = []
    for row in scoped['profiles'] + scoped['upgrades'] + scoped['restrictions']:
        item = {key: row[key] for key in ('document_id', 'source_ref', 'page_number', 'excerpt', 'preview_url')}
        item['applies_to'] = row['applies_to']
        if item not in result:
            result.append(item)
    return result


def device_confirmation(query: str, rows: list[dict], model_name: str) -> list[dict]:
    if not re.search(r'这台|现有|旧机|旧.*V|已发货|升级', query, re.I):
        return []
    options = []
    evidence = []
    for row in rows:
        scoped = model_facts(row['facts'], model_name)
        for profile in scoped['profiles']:
            option = profile['name'] + ('（' + '、'.join(profile['v_codes']) + '）' if profile['v_codes'] else '')
            if option not in options:
                options.append(option)
            evidence.append({key: profile[key] for key in ('document_id', 'source_ref', 'page_number', 'excerpt', 'preview_url')})
        for restriction in scoped['restrictions']:
            if restriction['excluded_v_codes']:
                option = '原文排除升级的旧硬件（' + '、'.join(restriction['excluded_v_codes']) + '）'
                if option not in options:
                    options.append(option)
    # A concrete platform or V-code already supplied in the question is not missing.
    if len(options) < 2 or any(token and token.casefold() in query.casefold()
            for token in [part for option in options for part in re.findall(r'VLucid\+|V\d{4,}|POC', option, re.I)]):
        return []
    return [{'id': 'device_hardware', 'field': 'device_hardware',
             'question': f"需要判断的这台{model_name}属于哪种硬件/产品V代码？",
             'reason': '原文已分别明确新平台与旧机升级限制，但机型名称本身未给出这台设备的硬件身份。',
             'required_for': 'device_upgrade_decision', 'options': options, 'evidence_refs': evidence}]

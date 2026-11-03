"""Live read-only projection of the existing whitepaper feature library.

Configuration owns names and approved IPN relations. WP owns description revisions
and their already-resolved series views; neither side is copied into the other.
"""
from __future__ import annotations

import asyncio
from html.parser import HTMLParser
import json
import os
import re
from typing import Any
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MAX_LIBRARY_BYTES = 16 * 1024 * 1024
REQUEST_TIMEOUT = 6


class WhitepaperFeatureNotFound(ValueError):
    """The requested local identity does not exist."""


def workbench_url() -> str:
    value = os.environ.get('WHITEPAPER_WORKBENCH_URL', 'http://127.0.0.1:43121').strip()
    parsed = urlsplit(value)
    if (parsed.scheme not in {'http', 'https'} or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {'', '/'} or parsed.query or parsed.fragment
            or parsed.port == 0):
        raise ValueError('白皮书服务地址必须是本机HTTP服务根地址')
    return f'{parsed.scheme}://{parsed.netloc}'


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read_library(base_url: str) -> Any:
    request = Request(base_url + '/api/feature-library', headers={'Accept': 'application/json'})
    # Do not send local product content through an environment-configured proxy.
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=REQUEST_TIMEOUT) as response:
        content = response.read(MAX_LIBRARY_BYTES + 1)
    if len(content) > MAX_LIBRARY_BYTES:
        raise ValueError('白皮书功能库响应超过读取上限')
    return json.loads(content)


def _validate_library(payload: Any) -> dict:
    if (not isinstance(payload, dict) or not isinstance(payload.get('revision'), int)
            or isinstance(payload['revision'], bool) or not isinstance(payload.get('features'), list)):
        raise ValueError('白皮书功能库响应格式无效')
    seen = set()
    for feature in payload['features']:
        if not isinstance(feature, dict) or not isinstance(feature.get('id'), str) or not feature['id'] or feature['id'] in seen:
            raise ValueError('白皮书功能身份缺失或重复')
        seen.add(feature['id'])
        if feature.get('configuration_errors'):
            raise ValueError('白皮书功能库未能读取其配置关联，当前不能判断是否已关联')
        if not isinstance(feature.get('configuration_items'), list) or not isinstance(feature.get('series_description_views'), dict):
            raise ValueError('白皮书配置关联或系列描述投影无效')
        if not isinstance(feature.get('bindings'), list):
            raise ValueError('白皮书系列关联无效')
        for item in feature['configuration_items']:
            if not isinstance(item, dict) or not isinstance(item.get('ipn', ''), str):
                raise ValueError('白皮书IPN投影无效')
    return payload


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {'script', 'style'}:
            self.hidden_depth += 1
        elif not self.hidden_depth and tag in {'p', 'div', 'br', 'li', 'tr'}:
            self.parts.append('\n')

    def handle_endtag(self, tag: str) -> None:
        if tag in {'script', 'style'}:
            self.hidden_depth = max(0, self.hidden_depth - 1)
        elif not self.hidden_depth and tag in {'p', 'div', 'li', 'tr'}:
            self.parts.append('\n')

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


def _body(record: dict) -> list[str]:
    paragraphs = record.get('body', [])
    if not isinstance(paragraphs, list) or any(not isinstance(value, str) for value in paragraphs):
        raise ValueError('白皮书描述正文格式无效')
    result: list[str] = []
    for paragraph in paragraphs:
        if record.get('body_format') == 'html' or re.search(r'</?[A-Za-z][^>]*>', paragraph):
            parser = _PlainText()
            parser.feed(paragraph)
            result.extend(value.strip() for value in ''.join(parser.parts).splitlines() if value.strip())
        else:
            result.append(paragraph)
    return result


def _descriptions(feature: dict) -> list[dict]:
    views = feature['series_description_views']
    scopes = ['master']
    for binding in feature['bindings']:
        if not isinstance(binding, dict):
            raise ValueError('白皮书系列关联格式无效')
        series = binding.get('series')
        if isinstance(series, str):
            scope = re.sub(r'-(?:China|Oversea)$', '', series)
            if scope in views and scope not in scopes:
                scopes.append(scope)
    result = []
    for scope in scopes:
        languages = views.get(scope, {})
        if not isinstance(languages, dict):
            raise ValueError('白皮书系列描述格式无效')
        for language in ('zh', 'en'):
            history = languages.get(language, [])
            if not isinstance(history, list):
                raise ValueError('白皮书描述修订格式无效')
            record = history[-1] if history else {}
            if not isinstance(record, dict):
                raise ValueError('白皮书描述修订格式无效')
            if (record.get('revision') is not None and (not isinstance(record['revision'], int) or isinstance(record['revision'], bool))
                    or record.get('created_at') is not None and not isinstance(record['created_at'], str)
                    or record.get('name') is not None and not isinstance(record['name'], str)):
                raise ValueError('白皮书描述修订字段无效')
            source = record.get('source') or {}
            if not isinstance(source, dict):
                raise ValueError('白皮书描述来源格式无效')
            result.append({'scope': scope, 'language': language, 'revision': record.get('revision'),
                'name': str(record.get('name') or ''), 'body': _body(record),
                'created_at': record.get('created_at'),
                'source': {key: source[key] for key in ('kind', 'series', 'version')
                           if isinstance(source.get(key), (str, int, float)) and not isinstance(source[key], bool)}})
    return result


def _match(source: dict, ipns: list[dict]) -> dict:
    descriptions = _descriptions(source)
    if any(not isinstance(row.get(key, ''), str) for row in source['bindings'] for key in ('series', 'version')):
        raise ValueError('白皮书系列关联字段无效')
    return {'id': source['id'], 'name': next((row['name'] for row in descriptions if row['name']), source['id']),
            'matched_ipns': ipns,
            'bindings': [{'series': row.get('series', ''), 'version': row.get('version', '')}
                         for row in source['bindings']], 'descriptions': descriptions}


async def feature_whitepaper_library(session: AsyncSession, feature_id: int | None = None) -> dict:
    rows = (await session.execute(text('''SELECT id,name,primary_cn_name,primary_en_name
        FROM features WHERE (:id IS NULL OR id=:id) ORDER BY id'''), {'id': feature_id})).mappings().all()
    if feature_id is not None and not rows:
        raise WhitepaperFeatureNotFound('功能不存在')
    links = (await session.execute(text('''SELECT l.feature_id,c.ipn,l.relation_type
        FROM feature_config_item_links l JOIN config_items c ON c.id=l.config_item_id
        WHERE l.review_status='approved' AND (:id IS NULL OR l.feature_id=:id)
        ORDER BY l.feature_id,CASE l.relation_type WHEN 'primary' THEN 0 ELSE 1 END,l.id'''),
        {'id': feature_id})).mappings().all()
    by_feature: dict[int, list[dict]] = {}
    for link in links:
        ipn = str(link['ipn'] or '').strip().upper()
        entry = {'ipn': ipn, 'relation_type': link['relation_type']}
        if ipn and entry not in by_feature.setdefault(link['feature_id'], []):
            by_feature[link['feature_id']].append(entry)
    items = [{'feature_id': row['id'], 'cn_name': row['primary_cn_name'] or row['name'] or '',
              'en_name': row['primary_en_name'] or '', 'ipns': by_feature.get(row['id'], []),
              'status': 'unavailable', 'matches': []} for row in rows]
    source: dict[str, Any] = {'available': False, 'service_url': '', 'library_url': '',
        'revision': None, 'feature_count': 0, 'message': ''}
    summary = {'configured': len(rows), 'linked': 0, 'ambiguous': 0, 'unlinked': 0, 'no_ipn': 0}
    try:
        url = workbench_url()
        source.update(service_url=url, library_url=url + '/#/features')
        payload = _validate_library(await asyncio.to_thread(_read_library, url))
        index: dict[str, dict[str, dict]] = {}
        for feature in payload['features']:
            for config_item in feature['configuration_items']:
                ipn = config_item.get('ipn', '').strip().upper()
                if ipn:
                    index.setdefault(ipn, {})[feature['id']] = feature
        for item in items:
            matches: dict[str, dict] = {}
            ambiguous = False
            for ipn in item['ipns']:
                candidates = index.get(ipn['ipn'], {})
                ambiguous = ambiguous or len(candidates) > 1
                for identifier, feature in candidates.items():
                    candidate = matches.setdefault(identifier, {'source': feature, 'ipns': []})
                    candidate['ipns'].append(ipn)
            item['matches'] = [_match(candidate['source'], candidate['ipns']) for candidate in matches.values()]
            item['status'] = ('no_ipn' if not item['ipns'] else 'ambiguous' if ambiguous else 'linked' if matches else 'unlinked')
            summary[item['status']] += 1
        source.update(available=True, revision=payload['revision'], feature_count=len(payload['features']),
                      message='直接读取白皮书功能库当前修订；配置名称与IPN关系沿用基础数据，描述按原库系列投影展示')
    except (OSError, ValueError, TypeError) as error:
        source['message'] = ('白皮书功能库连接超时，请检查本机白皮书工作台' if isinstance(error, TimeoutError)
                             else '白皮书功能库读取失败，请检查本机白皮书服务地址、服务状态及返回格式')
        for item in items:
            item.update(status='unavailable', matches=[])
        summary.update(linked=0, ambiguous=0, unlinked=0, no_ipn=0)
    return {'source': source, 'summary': summary, 'items': items}

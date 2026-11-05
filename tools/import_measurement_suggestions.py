"""Import source-bound public-reference candidates without confirming any entry."""
import argparse
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_FILE = Path(__file__).resolve().parents[1] / 'backend/resources/measurement_calculation_suggestions_1.51.90.json'


def build_manifest(bundle: dict, library: dict, batch_id: int | None = None) -> dict:
    source = bundle['source_workbook']
    matches = [batch for batch in library['batches']
               if batch['sha256'] == source['sha256'] and batch['version'] == source['version']
               and (batch_id is None or batch['id'] == batch_id)]
    if len(matches) != 1:
        raise ValueError('未找到唯一匹配的来源版本与 SHA-256，未写入任何建议')
    return {'batch_id': matches[0]['id'], 'expected_sha256': source['sha256'],
            'expected_version': source['version'], 'schema_version': bundle['schema_version'],
            'candidates': bundle['candidates']}


def request_json(url: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    request = Request(url, data=body, headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', type=Path, default=DEFAULT_FILE)
    parser.add_argument('--base-url', default='http://127.0.0.1:8086')
    parser.add_argument('--batch-id', type=int)
    parser.add_argument('--apply', action='store_true', help='写入待核对候选；不会确认或改写原表')
    args = parser.parse_args()
    try:
        bundle = json.loads(args.file.read_text())
        base_url = args.base_url.rstrip('/')
        manifest = build_manifest(bundle, request_json(base_url + '/api/measurements'), args.batch_id)
        print(json.dumps({'batch_id': manifest['batch_id'], 'version': manifest['expected_version'],
                          'coverage': bundle['coverage'], 'apply': args.apply}, ensure_ascii=False))
        if args.apply:
            result = request_json(base_url + '/api/measurements/enrichment/import', manifest)
            print(json.dumps({'created': result['created'], 'reused': result['reused'], 'status': '待人工核对'}, ensure_ascii=False))
        return 0
    except HTTPError as error:
        detail = error.read().decode(errors='replace')[:1500]
        print(f'导入失败（HTTP {error.code}）：{detail}')
    except (OSError, URLError, ValueError, KeyError) as error:
        print(f'导入未完成：{error}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())

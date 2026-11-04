"""Call the existing guideline evidence runtime, keeping credentials in its owner."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

CONFIG_PATH = Path(__file__).resolve().parents[2] / 'config' / 'knowledge_evidence.local.json'


class SharedEvidenceUnavailable(ValueError):
    pass


def _configuration() -> tuple[Path, str, dict]:
    try:
        path = Path(os.environ.get('KNOWLEDGE_EVIDENCE_CONFIG', str(CONFIG_PATH))).expanduser()
        config = json.loads(path.read_text())
        root = Path(config['guideline_project']).expanduser().resolve()
        if not (root / 'guidelines' / 'product_evidence.py').is_file():
            raise ValueError('shared runtime missing')
        python = str(config.get('python_executable') or sys.executable)
        environment = os.environ | {'PYTHONPATH': str(root), 'PYTHONIOENCODING': 'utf-8'}
        for key, variable in [('model_settings', 'VINNO_PRODUCT_MODEL_SETTINGS'), ('meili_key_file', 'VINNO_PRODUCT_MEILI_KEY_FILE'), ('meili_address', 'VINNO_PRODUCT_MEILI_ADDRESS')]:
            if config.get(key):
                environment[variable] = str(config[key])
        return root, python, environment
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SharedEvidenceUnavailable('共享资料问答尚未配置，请配置指南检索与模型运行器') from error


def capabilities() -> dict:
    try:
        _configuration()
        return {'available': True, 'reason': '使用指南管理的共享检索、模型与引用核验能力；按需调用，不自动发布'}
    except SharedEvidenceUnavailable as error:
        return {'available': False, 'reason': str(error)}


def run_shared_evidence(payload: dict, *, sources: list[dict] | None = None) -> dict:
    root, python, environment = _configuration()
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > 4 * 1024 * 1024:
        raise SharedEvidenceUnavailable('适用资料超过单次处理上限，请缩小查询范围')
    # Source authorization is a server-only argument, never part of HTTP/model input.
    environment.pop('VINNO_PRODUCT_SOURCE_MANIFEST', None)
    if sources is not None:
        allowed = {(p['id'], p['version_id']) for p in payload.get('pages', [])}
        if (not isinstance(sources, list) or len(sources) > 500
                or any(not isinstance(source, dict) or set(source) != {'id', 'version_id', 'file_path'}
                       or (source['id'], source['version_id']) not in allowed
                       or not isinstance(source['file_path'], str) or not Path(source['file_path']).is_absolute()
                       or Path(source['file_path']).suffix.lower() != '.pdf' for source in sources)
                or len({(s['id'], s['version_id']) for s in sources}) != len(sources)
                or {(s['id'], s['version_id']) for s in sources} != allowed):
            raise SharedEvidenceUnavailable('原页授权与本次资料范围不一致，未调用模型')
    # Fixed module invocation; no executable, path or environment is accepted from HTTP.
    with tempfile.TemporaryDirectory(prefix='vinno-evidence-') as private, tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        if sources:
            manifest = Path(private) / 'sources.json'
            with manifest.open('x', encoding='utf-8') as stream:
                os.chmod(manifest, 0o600)
                json.dump(sources, stream, ensure_ascii=False)
            environment['VINNO_PRODUCT_SOURCE_MANIFEST'] = str(manifest)
        try:
            completed = subprocess.run([python, '-m', 'guidelines.product_evidence'], input=encoded,
                                       cwd=root, env=environment, stdout=output, stderr=errors,
                                       timeout=210, check=False)
            if completed.returncode != 0 or output.tell() > 2 * 1024 * 1024:
                raise SharedEvidenceUnavailable('共享资料问答未完成，请检查本机运行器或模型设置后重试')
            output.seek(0)
            result = json.load(output)
            if not isinstance(result, dict):
                raise ValueError('invalid runtime response')
            return result
        except (subprocess.TimeoutExpired, OSError, ValueError) as error:
            raise SharedEvidenceUnavailable('共享资料问答暂时不可用；未发布任何答案，请稍后重试') from error

import json
import stat

import pytest

from tracker.services.description_settings import ModelSettings
from tracker.services.description_model import DescriptionModel


def test_separate_provider_profiles_never_echo_keys(tmp_path):
    path = tmp_path / 'model.json'
    settings = ModelSettings(path)
    settings.save('deepseek-flash', 'synthetic-deepseek', provider='deepseek', daily_tokens=10000)
    result = settings.save('gpt-6.1-terra', 'synthetic-openai', provider='openai')
    assert result['provider'] == 'openai'
    assert result['providers']['deepseek']['configured']
    assert result['providers']['openai']['configured']
    assert 'synthetic' not in json.dumps(result)
    settings.save('deepseek-flash', '', provider='deepseek')
    assert settings.read()['api_key'] == 'synthetic-deepseek'
    assert result['daily_tokens'] == 10000
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize('payload', [dict(provider='other'), dict(model='not a model'), dict(api_key='contains whitespace'), dict(daily_tokens=-1), dict(daily_tokens=True)])
def test_invalid_settings_do_not_write(tmp_path, payload):
    settings = ModelSettings(tmp_path / 'model.json')
    with pytest.raises(ValueError):
        settings.save(**payload)
    assert not settings.path.exists()


@pytest.mark.parametrize('provider,model,endpoint', [('deepseek','deepseek-flash','/chat/completions'), ('openai','gpt-6.1-terra','/responses')])
def test_transports_have_provider_specific_limits_and_json_output(tmp_path, monkeypatch, provider, model, endpoint):
    settings = ModelSettings(tmp_path / 'model.json')
    settings.save(model, 'synthetic-test', provider=provider)
    captured = []
    content = {'paragraphs': [{'text': '原文功能', 'citations': [{'id': 'baseline', 'quote': '原文功能'}]}], 'unresolved': []}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            if provider == 'deepseek':
                body = {'choices': [{'finish_reason':'stop','message':{'content':json.dumps(content)}}]}
            else:
                body = {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(content)}]}]}
            return json.dumps({**body,'usage':{'total_tokens':42}}).encode()
    class Opener:
        def open(self, request, timeout):
            captured.append(request)
            return Response()
    monkeypatch.setattr('tracker.services.description_model.build_opener', lambda *args: Opener())
    result, usage = DescriptionModel(settings).generate({'evidence':[]})
    assert result == content and usage['total_tokens'] == 42
    assert captured[0].full_url.endswith(endpoint)
    body = json.loads(captured[0].data)
    assert body['model'] == model
    if provider == 'deepseek':
        assert body['thinking'] == {'type':'disabled'}
        assert body['max_tokens'] == 2500
    else:
        assert body['store'] is False
        assert body['max_output_tokens'] == 2500
        assert 'json' in body['input'].casefold(), 'Responses JSON mode requires json in input, not only instructions'


def test_transport_supplies_trusted_ca_bundle_on_python_without_system_roots(tmp_path, monkeypatch):
    import ssl
    from urllib.request import HTTPSHandler
    settings = ModelSettings(tmp_path / 'model.json')
    settings.save('gpt-6.1-terra', 'synthetic-test', provider='openai')
    captured = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return json.dumps({'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{}'}]}]}).encode()
    class Opener:
        def open(self, request, timeout): return Response()
    def opener(*handlers):
        captured.extend(handlers)
        return Opener()
    monkeypatch.setattr('tracker.services.description_model.build_opener', opener)
    DescriptionModel(settings).generate({})
    handler = next((item for item in captured if isinstance(item, HTTPSHandler)), None)
    assert handler is not None, 'No explicit TLS context: macOS Python may have no system CA bundle'
    assert handler._context.verify_mode == ssl.CERT_REQUIRED
    assert handler._context.check_hostname
    assert handler._context.get_ca_certs()

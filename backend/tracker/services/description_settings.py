"""Private provider profiles, adapted from guidelines.model.ModelSettings.

Vendored locally because the separate guide application is not a deployment dependency.
The settings structure and no-key-echo behavior intentionally match its settings panel.
"""
from __future__ import annotations
import json
import os
import re
import tempfile
import threading
from pathlib import Path

PROVIDERS = {
    "deepseek": {"label": "DeepSeek", "model": "deepseek-flash", "env": "DEEPSEEK_API_KEY", "endpoint": "https://api.deepseek.com"},
    "openai": {"label": "OpenAI", "model": "gpt-6.1-terra", "env": "OPENAI_API_KEY", "endpoint": "https://api.openai.com/v1"},
}

class ModelSettings:
    def __init__(self, path: Path | None = None):
        self.path = path or Path.home() / ".config/vinno-product-config/model.json"
        self.lock = threading.Lock()

    @staticmethod
    def _provider(provider):
        if not isinstance(provider, str) or provider not in PROVIDERS:
            raise ValueError("请选择 DeepSeek 或 OpenAI")
        return provider

    def _load(self) -> dict:
        raw = json.loads(self.path.read_text()) if self.path.exists() else {}
        if not isinstance(raw, dict):
            raise TypeError("模型配置格式无效")
        profiles = raw.get("providers", {})
        if not isinstance(profiles, dict):
            raise TypeError("模型配置格式无效")
        result = {
            "schema_version": 2,
            "daily_tokens": raw.get("daily_tokens", 100000),
            "provider": self._provider(raw.get("provider", "deepseek")),
            "providers": {},
        }
        for provider, defaults in PROVIDERS.items():
            profile = profiles.get(
                provider,
                raw if provider == "deepseek" and "providers" not in raw else {},
            )
            if not isinstance(profile, dict):
                raise TypeError("服务商配置格式无效")
            result["providers"][provider] = {
                "model": profile.get("model", defaults["model"]),
                "api_key": profile.get("api_key") or "",
            }
        return result

    def read(self, provider: str | None = None) -> dict:
        with self.lock:
            data = self._load()
        provider = self._provider(
            provider if provider is not None else data["provider"]
        )
        profile = data["providers"][provider]
        return profile | {
            "provider": provider,
            "api_key": profile["api_key"]
            or os.environ.get(PROVIDERS[provider]["env"], ""),
        }

    def public(self) -> dict:
        with self.lock:
            data = self._load()
        profiles = {
            p: {
                "label": defaults["label"],
                "model": data["providers"][p]["model"],
                "configured": bool(
                    data["providers"][p]["api_key"]
                    or os.environ.get(defaults["env"], "")
                ),
                "endpoint": defaults["endpoint"],
            }
            for p, defaults in PROVIDERS.items()
        }
        return profiles[data["provider"]] | {
            "provider": data["provider"],
            "daily_tokens": data["daily_tokens"],
            "providers": profiles,
        }

    def save(
        self,
        model: str | None = None,
        api_key: str = "",
        *,
        provider: str | None = None,
        activate: bool = True,
        daily_tokens: int | None = None,
    ) -> dict:
        if (
            not isinstance(api_key, str)
            or len(api_key) > 512
            or any(c.isspace() for c in api_key)
        ):
            raise ValueError("密钥格式不正确")
        if type(activate) is not bool:
            raise ValueError("服务商选择参数无效")
        if daily_tokens is not None and (type(daily_tokens) is not int or not 0 <= daily_tokens <= 10000000):
            raise ValueError("每日 token 上限须为 0 至 10000000 的整数。")
        with self.lock:
            data = self._load()
            if daily_tokens is not None:
                data["daily_tokens"] = daily_tokens
            provider = self._provider(
                provider if provider is not None else data["provider"]
            )
            current = data["providers"][provider]
            selected_model = current["model"] if model is None else model
            pattern = (
                r"deepseek-[a-z0-9.-]{1,70}"
                if provider == "deepseek"
                else r"(?:gpt-|o[134](?:-|$))[a-zA-Z0-9._:-]*"
            )
            if (
                not isinstance(selected_model, str)
                or len(selected_model) > 100
                or not re.fullmatch(pattern, selected_model)
            ):
                raise ValueError(f"请填写 {PROVIDERS[provider]['label']} 官方模型标识")
            data["providers"][provider] = {
                "model": selected_model,
                "api_key": api_key or current["api_key"],
            }
            if activate:
                data["provider"] = provider
            self._write(data)
        return self.public()

    def select(self, provider: str) -> dict:
        provider = self._provider(provider)
        with self.lock:
            data = self._load()
            data["provider"] = provider
            self._write(data)
        return self.public()

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as stream:
            temp = Path(stream.name)
            try:
                os.chmod(temp, 0o600)
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
                os.replace(temp, self.path)
            finally:
                temp.unlink(missing_ok=True)

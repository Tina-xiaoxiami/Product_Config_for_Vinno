"""受控资料的适用范围口径，供登记、搜索和机型工作页共同使用。"""

from __future__ import annotations

import re
from typing import Mapping


DOCUMENT_CATEGORIES = frozenset({"发布记录", "白皮书", "说明书", "注册资料", "注册跟踪表"})
MAX_MODEL_SCOPE_LENGTH = 5000
_SCOPE_SEPARATOR = re.compile(r"[,，、;；/|]+")


def normalize_model_scope(value: str) -> str:
    """规范显式多机型分隔符，保留用户提供的机型，不推断简称。"""
    models = dict.fromkeys(" ".join(part.split()) for part in _SCOPE_SEPARATOR.split(str(value or "")))
    return "、".join(model for model in models if model)


def matches_model_scope(
    model_scope: str, model: str, *, include_unknown: bool = True,
    aliases: Mapping[str, str] | None = None,
) -> bool:
    """精确匹配显式范围；别名只能来自调用方已经确认的映射。"""
    scope = normalize_model_scope(model_scope)
    if not scope:
        return include_unknown
    if not str(model or "").strip():
        return True
    normalized_aliases = {
        " ".join(str(key).split()).casefold(): " ".join(str(value).split()).casefold()
        for key, value in (aliases or {}).items()
    }

    def canonical(value: str) -> str:
        normalized = " ".join(value.split()).casefold()
        return normalized_aliases.get(normalized, normalized)

    return canonical(str(model)) in {canonical(value) for value in scope.split("、")}

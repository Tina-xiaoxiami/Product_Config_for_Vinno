"""Build a safe, read-only preview of the IPN-based feature identity migration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
import unicodedata


class IdentityValidationError(ValueError):
    """Raised when source configuration identities are not safe to migrate."""


@dataclass(frozen=True)
class ConfigItemIdentity:
    id: int
    ipn: str
    rd_name: str
    zh_desc: str
    en_desc: str


@dataclass(frozen=True)
class LegacyFeature:
    id: int
    name: str
    ipn: str


@dataclass(frozen=True)
class FeatureName:
    language: str
    name: str
    name_type: str
    source: str


@dataclass(frozen=True)
class FeatureIdentity:
    legacy_feature_id: int
    config_item_id: int
    ipn: str
    primary_cn_name: str
    primary_en_name: str
    names: tuple[FeatureName, ...]
    status: str = "auto_matched"


@dataclass(frozen=True)
class PendingIdentity:
    legacy_feature_id: int
    legacy_name: str
    reason: str
    candidate_ipns: tuple[str, ...] = ()


@dataclass(frozen=True)
class FeatureIdentityPreview:
    identities: list[FeatureIdentity]
    pending: list[PendingIdentity]


def _normalize_ipn(value: str) -> str:
    return str(value or "").strip().upper()


_STATUS_SUFFIX = re.compile(r"\s*(?:【|\[)\s*(?:启用|禁用|停用)\s*(?:】|\])\s*$")


def clean_feature_name(value: str) -> str:
    """Return a business name without an internal trailing status marker."""

    cleaned = unicodedata.normalize("NFKC", str(value or ""))
    cleaned = _STATUS_SUFFIX.sub("", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _normalize_name(value: str) -> str:
    return clean_feature_name(value).casefold()


def _language_of(name: str) -> str:
    name = clean_feature_name(name)
    cjk_count = len(re.findall(r"[\u3400-\u9fff]", name))
    latin_count = len(re.findall(r"[A-Za-z]", name))
    return "cn" if cjk_count > latin_count else "en"


def _source_names(item: ConfigItemIdentity) -> tuple[str, ...]:
    return tuple(
        cleaned
        for value in (item.rd_name, item.zh_desc, item.en_desc)
        if (cleaned := clean_feature_name(value))
    )


def _validate_config_items(
    items: list[ConfigItemIdentity],
) -> dict[str, ConfigItemIdentity]:
    by_ipn: dict[str, ConfigItemIdentity] = {}
    for item in items:
        ipn = _normalize_ipn(item.ipn)
        if not ipn:
            raise IdentityValidationError(f"配置项 {item.id} 缺少IPN")
        if ipn in by_ipn:
            raise IdentityValidationError(
                f"检测到重复IPN：{ipn}（配置项 {by_ipn[ipn].id}、{item.id}）"
            )
        by_ipn[ipn] = item
    return by_ipn


def _append_name(
    names: list[FeatureName],
    seen: set[tuple[str, str]],
    *,
    language: str,
    name: str,
    name_type: str,
    source: str,
) -> None:
    cleaned = clean_feature_name(name)
    if not cleaned:
        return
    identity = (language, _normalize_name(cleaned))
    if identity in seen:
        return
    seen.add(identity)
    names.append(FeatureName(language, cleaned, name_type, source))


def _build_identity(
    item: ConfigItemIdentity,
    legacy: LegacyFeature,
    *,
    status: str = "auto_matched",
) -> FeatureIdentity:
    names: list[FeatureName] = []
    seen: set[tuple[str, str]] = set()
    _append_name(
        names,
        seen,
        language="cn",
        name=item.zh_desc,
        name_type="primary",
        source="config_items.zh_desc",
    )
    _append_name(
        names,
        seen,
        language="en",
        name=item.en_desc,
        name_type="primary",
        source="config_items.en_desc",
    )
    if status == "confirmed" or _normalize_name(legacy.name) != _normalize_name(item.rd_name):
        _append_name(
            names,
            seen,
            language=_language_of(legacy.name),
            name=legacy.name,
            name_type="alias",
            source="legacy_features.name",
        )
    return FeatureIdentity(
        legacy_feature_id=legacy.id,
        config_item_id=item.id,
        ipn=_normalize_ipn(item.ipn),
        primary_cn_name=clean_feature_name(item.zh_desc),
        primary_en_name=clean_feature_name(item.en_desc),
        names=tuple(names),
        status=status,
    )


def build_feature_identity_preview(
    *,
    config_items: list[ConfigItemIdentity],
    legacy_features: list[LegacyFeature],
    confirmed_ipn_by_legacy_feature_id: Mapping[int, str] | None = None,
) -> FeatureIdentityPreview:
    """Match legacy features to one IPN without changing source data."""

    by_ipn = _validate_config_items(config_items)
    confirmed_mappings = confirmed_ipn_by_legacy_feature_id or {}
    by_name: dict[str, list[ConfigItemIdentity]] = {}
    for item in config_items:
        for source_name in {_normalize_name(name) for name in _source_names(item)}:
            if source_name:
                by_name.setdefault(source_name, []).append(item)

    identities: list[FeatureIdentity] = []
    pending: list[PendingIdentity] = []
    for legacy in legacy_features:
        if legacy.id in confirmed_mappings:
            confirmed_ipn = _normalize_ipn(confirmed_mappings[legacy.id])
            item = by_ipn.get(confirmed_ipn)
            if item is None:
                raise IdentityValidationError(
                    f"功能 {legacy.id} 的确认映射指向未知IPN：{confirmed_ipn}"
                )
            identities.append(_build_identity(item, legacy, status="confirmed"))
            continue

        legacy_ipn = _normalize_ipn(legacy.ipn)
        if legacy_ipn:
            item = by_ipn.get(legacy_ipn)
            if item is None:
                pending.append(
                    PendingIdentity(
                        legacy.id,
                        legacy.name,
                        "unknown_ipn",
                        (legacy_ipn,),
                    )
                )
                continue
            identities.append(_build_identity(item, legacy))
            continue

        candidates = {
            item.ipn: item
            for item in by_name.get(_normalize_name(legacy.name), [])
        }
        if len(candidates) == 1:
            identities.append(_build_identity(next(iter(candidates.values())), legacy))
        elif len(candidates) > 1:
            pending.append(
                PendingIdentity(
                    legacy.id,
                    legacy.name,
                    "ambiguous_name",
                    tuple(sorted(_normalize_ipn(ipn) for ipn in candidates)),
                )
            )
        else:
            pending.append(
                PendingIdentity(
                    legacy.id,
                    legacy.name,
                    "no_exact_ipn_match",
                )
            )

    return FeatureIdentityPreview(identities, pending)

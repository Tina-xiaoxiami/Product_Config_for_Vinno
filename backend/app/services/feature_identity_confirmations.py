"""Product-owner confirmed legacy feature merges used by data migration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConfirmedFeatureMapping:
    legacy_feature_id: int
    legacy_name: str
    target_ipn: str
    confirmed_at: str
    confirmed_by: str = "product_owner"


CONFIRMED_FEATURE_MAPPINGS: tuple[ConfirmedFeatureMapping, ...] = (
    ConfirmedFeatureMapping(
        legacy_feature_id=4,
        legacy_name="穿刺引导&穿刺增强",
        target_ipn="6000034",
        confirmed_at="2026-09-01",
    ),
    ConfirmedFeatureMapping(
        legacy_feature_id=7,
        legacy_name="SMF",
        target_ipn="6000273",
        confirmed_at="2026-09-01",
    ),
)


def confirmed_ipn_by_legacy_feature_id() -> dict[int, str]:
    """Return the reviewed migration overrides, rejecting conflicting entries."""

    result: dict[int, str] = {}
    for item in CONFIRMED_FEATURE_MAPPINGS:
        target_ipn = item.target_ipn.strip().upper()
        if not target_ipn:
            raise ValueError(f"功能 {item.legacy_feature_id} 的确认IPN为空")
        if item.legacy_feature_id in result:
            raise ValueError(f"重复的确认功能ID：{item.legacy_feature_id}")
        result[item.legacy_feature_id] = target_ipn
    return result

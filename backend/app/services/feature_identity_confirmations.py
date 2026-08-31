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


@dataclass(frozen=True)
class ConfirmedFeatureRelation:
    legacy_feature_id: int
    legacy_name: str
    relation_type: str
    target_ipns: tuple[str, ...]
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
    ConfirmedFeatureMapping(10, "向量血流", "6000349", "2026-09-01"),
    ConfirmedFeatureMapping(11, "常规造影", "6000019", "2026-09-01"),
    ConfirmedFeatureMapping(17, "EI", "6000018", "2026-09-01"),
    ConfirmedFeatureMapping(18, "SWE", "6000190", "2026-09-01"),
    ConfirmedFeatureMapping(25, "ECG", "6000321", "2026-09-01"),
    ConfirmedFeatureMapping(27, "AMAS", "6000167", "2026-09-01"),
    ConfirmedFeatureMapping(28, "Strain", "6000169", "2026-09-01"),
    ConfirmedFeatureMapping(33, "Vaid Carotid", "6000356", "2026-09-01"),
)


CONFIRMED_FEATURE_RELATIONS: tuple[ConfirmedFeatureRelation, ...] = (
    ConfirmedFeatureRelation(
        19,
        "点式剪切波",
        "related",
        ("6000190",),
        "2026-09-01",
    ),
    ConfirmedFeatureRelation(
        31,
        "Vmind OB",
        "version_variant",
        ("6000294", "6000415"),
        "2026-09-01",
    ),
    ConfirmedFeatureRelation(
        32,
        "STIC",
        "version_variant",
        ("3200476", "6000323"),
        "2026-09-01",
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


def confirmed_relations_by_legacy_feature_id(
) -> dict[int, tuple[str, tuple[str, ...]]]:
    """Return reviewed one-to-many IPN relationships for legacy features."""

    allowed_relation_types = {"related", "version_variant"}
    result: dict[int, tuple[str, tuple[str, ...]]] = {}
    for item in CONFIRMED_FEATURE_RELATIONS:
        if item.legacy_feature_id in result:
            raise ValueError(f"重复的关系功能ID：{item.legacy_feature_id}")
        if item.relation_type not in allowed_relation_types:
            raise ValueError(f"未知功能关系：{item.relation_type}")
        target_ipns = tuple(
            dict.fromkeys(ipn.strip().upper() for ipn in item.target_ipns if ipn.strip())
        )
        if not target_ipns:
            raise ValueError(f"功能 {item.legacy_feature_id} 缺少关联IPN")
        result[item.legacy_feature_id] = (item.relation_type, target_ipns)
    return result

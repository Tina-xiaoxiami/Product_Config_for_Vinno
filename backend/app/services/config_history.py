"""Series-scoped configuration snapshots and safe historical restoration."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ConfigItem, ConfigValue, ProductModel
from app.services.model_identity import (
    active_model_filter,
    model_identity_metadata,
    normalize_snapshot,
)


VALUE_FIELDS = ("current_config", "final_config", "selection_config", "rd_status")
ITEM_FIELDS = ("category", "row_index", "rd_name", "v_code", "ipn", "zh_desc", "en_desc")
NO_IPN_IDENTITY_FIELDS = ("category", "row_index", "rd_name", "v_code")


def _item_payload(item: ConfigItem) -> dict:
    return {"id": item.id, **{field: getattr(item, field) for field in ITEM_FIELDS}}


def _value_payload(value: ConfigValue) -> dict:
    return {field: getattr(value, field) for field in VALUE_FIELDS}


async def build_series_snapshot(db: AsyncSession, series_id: int) -> dict:
    """Build a canonical snapshot without pulling in another series' items."""
    models = list(
        (
            await db.execute(
                select(ProductModel)
                .where(ProductModel.series_id == series_id, active_model_filter())
                .order_by(ProductModel.sort_order, ProductModel.id)
            )
        )
        .scalars()
        .all()
    )
    model_ids = [model.id for model in models]
    identities = await model_identity_metadata(db, model_ids)

    snapshot_models = []
    for model in models:
        entry = {"id": model.id, "name": model.name}
        source_uuid = identities.get(model.id, {}).get("source_uuid")
        if source_uuid:
            entry["source_uuid"] = source_uuid
        snapshot_models.append(entry)

    if not model_ids:
        return {"models": snapshot_models, "items": []}

    values = list(
        (
            await db.execute(
                select(ConfigValue)
                .where(ConfigValue.model_id.in_(model_ids))
                .order_by(ConfigValue.item_id, ConfigValue.model_id)
            )
        )
        .scalars()
        .all()
    )
    item_ids = list(dict.fromkeys(value.item_id for value in values))
    if not item_ids:
        return {"models": snapshot_models, "items": []}

    items = list(
        (
            await db.execute(
                select(ConfigItem)
                .where(ConfigItem.id.in_(item_ids))
                .order_by(ConfigItem.row_index, ConfigItem.id)
            )
        )
        .scalars()
        .all()
    )
    value_map: dict[int, dict[str, dict]] = {}
    for value in values:
        value_map.setdefault(value.item_id, {})[str(value.model_id)] = _value_payload(value)

    return {
        "models": snapshot_models,
        "items": [
            {**_item_payload(item), "values": value_map[item.id]}
            for item in items
            if item.id in value_map
        ],
    }


def _same_ipn(left, right) -> bool:
    return left is not None and right is not None and str(left).strip() == str(right).strip()


def _no_ipn_identity(item: ConfigItem | dict) -> tuple:
    def value(field):
        return item.get(field) if isinstance(item, dict) else getattr(item, field)

    return tuple(value(field) for field in NO_IPN_IDENTITY_FIELDS)


def _has_reliable_no_ipn_identity(item_info: dict) -> bool:
    return item_info.get("row_index") is not None and bool(
        item_info.get("rd_name") or item_info.get("v_code")
    )


def snapshot_item_comparison_identity(item_info: dict) -> tuple:
    """Return a stable, collision-checkable identity for snapshot comparison."""
    ipn = str(item_info.get("ipn") or "").strip()
    if ipn:
        return ("ipn", ipn)

    snapshot_id = item_info.get("id")
    try:
        snapshot_id = int(snapshot_id) if snapshot_id is not None else None
    except (TypeError, ValueError):
        raise ValueError(f"快照配置项编号 {snapshot_id} 无效") from None
    if snapshot_id is not None:
        return ("snapshot", snapshot_id)

    if _has_reliable_no_ipn_identity(item_info):
        return ("metadata", _no_ipn_identity(item_info))
    raise ValueError("无 IPN 配置项缺少可用于版本比较的稳定身份")


def build_snapshot_item_comparison_index(snapshot: dict) -> dict[tuple, dict]:
    """Index snapshot items without silently overwriting identity collisions."""
    if not isinstance(snapshot, dict):
        raise ValueError("快照格式无效")
    items = snapshot.get("items", [])
    if not isinstance(items, list):
        raise ValueError("快照配置项列表格式无效")

    index = {}
    for item_info in items:
        if not isinstance(item_info, dict):
            raise ValueError("快照配置项格式无效")
        identity = snapshot_item_comparison_identity(item_info)
        if identity in index:
            raise ValueError(f"快照中多个配置项指向同一身份 {identity[1]}")
        index[identity] = item_info
    return index


def normalize_config_comparison_value(value):
    """Apply the empty-value semantics used by configuration comparisons."""
    return value if value not in [None, "", "N/A"] else None


def build_snapshot_semantic_value_index(
    snapshot: dict,
    model_ids: Iterable[int] | None = None,
) -> dict[tuple, dict]:
    """Index meaningful snapshot values and prune empty model/item entries."""
    requested_model_ids = (
        {int(model_id) for model_id in model_ids}
        if model_ids is not None
        else None
    )
    semantic_index = {}
    for identity, item_info in build_snapshot_item_comparison_index(snapshot).items():
        raw_values = item_info.get("values", {})
        if not isinstance(raw_values, dict):
            raise ValueError(f"快照配置项 {item_info.get('id')} 的配置值格式无效")

        semantic_values = {}
        for raw_model_id, value_info in raw_values.items():
            try:
                model_id = int(raw_model_id)
            except (TypeError, ValueError):
                raise ValueError(f"快照机型编号 {raw_model_id} 无效") from None
            if requested_model_ids is not None and model_id not in requested_model_ids:
                continue
            if not isinstance(value_info, dict):
                raise ValueError(
                    f"快照配置项 {item_info.get('id')} 的配置值格式无效"
                )
            normalized = {
                field: normalize_config_comparison_value(value_info.get(field))
                for field in VALUE_FIELDS
            }
            if any(value is not None for value in normalized.values()):
                semantic_values[str(model_id)] = normalized

        if semantic_values:
            semantic_index[identity] = {**item_info, "values": semantic_values}
    return semantic_index


def _resolve_existing_item(item_info: dict, items: Iterable[ConfigItem]) -> ConfigItem | None:
    existing_items = list(items)
    snapshot_id = item_info.get("id")
    try:
        snapshot_id = int(snapshot_id) if snapshot_id is not None else None
    except (TypeError, ValueError):
        raise ValueError(f"快照配置项编号 {snapshot_id} 无效") from None
    snapshot_ipn = item_info.get("ipn")
    by_id = next((item for item in existing_items if item.id == snapshot_id), None)

    if by_id is not None:
        if snapshot_ipn:
            if _same_ipn(by_id.ipn, snapshot_ipn):
                return by_id
        elif not by_id.ipn:
            code = str(item_info.get("v_code") or "").strip()
            existing_code = str(by_id.v_code or "").strip()
            name = str(item_info.get("rd_name") or "").strip()
            existing_name = str(by_id.rd_name or "").strip()
            if code and existing_code:
                if code == existing_code:
                    return by_id
            elif name and name == existing_name:
                return by_id

    if snapshot_ipn:
        matches = [item for item in existing_items if _same_ipn(item.ipn, snapshot_ipn)]
        if len(matches) > 1:
            raise ValueError(f"IPN {snapshot_ipn} 对应多个配置项，无法安全恢复")
        return matches[0] if matches else None

    if not _has_reliable_no_ipn_identity(item_info):
        if by_id is not None:
            raise ValueError(f"无 IPN 配置项 {snapshot_id} 的身份元数据不足")
        return None

    identity = _no_ipn_identity(item_info)
    matches = [
        item
        for item in existing_items
        if not item.ipn and _no_ipn_identity(item) == identity
    ]
    if len(matches) > 1:
        raise ValueError(f"无 IPN 配置项 {snapshot_id} 的元数据对应多个现有配置项")
    if matches:
        return matches[0]
    if by_id is not None:
        raise ValueError(f"无 IPN 配置项 {snapshot_id} 的历史编号与当前功能身份冲突")
    return None


def resolve_snapshot_item(item: ConfigItem, snapshot: dict) -> dict | None:
    """Find a historical baseline using the same identity rules as restoration."""
    matches = []
    conflicts = []
    for entry in snapshot.get("items", []):
        try:
            resolved = _resolve_existing_item(entry, [item])
        except ValueError as error:
            conflicts.append(error)
            continue
        if resolved is item:
            matches.append(entry)
    if len(matches) > 1:
        raise ValueError(f"配置项 {item.id} 对应多个历史身份，无法唯一确认基线")
    if matches:
        return matches[0]
    if conflicts:
        raise conflicts[0]
    return None


async def restore_series_snapshot(db: AsyncSession, series_id: int, snapshot: dict) -> int:
    """Restore one series while preserving global item metadata and unrelated history."""
    normalized = await normalize_snapshot(db, series_id, snapshot)
    active_models = list(
        (
            await db.execute(
                select(ProductModel).where(
                    ProductModel.series_id == series_id,
                    active_model_filter(),
                )
            )
        )
        .scalars()
        .all()
    )
    active_model_ids = {model.id for model in active_models}
    snapshot_model_ids = {int(model["id"]) for model in normalized.get("models", [])}
    unknown_model_ids = snapshot_model_ids - active_model_ids
    if unknown_model_ids:
        raise ValueError(
            f"快照中的机型 {sorted(unknown_model_ids)} 不是目标系列的有效机型"
        )

    all_items = list((await db.execute(select(ConfigItem).order_by(ConfigItem.id))).scalars().all())
    resolved_items: list[tuple[ConfigItem | None, dict]] = []
    resolved_keys = set()
    for item_info in normalized.get("items", []):
        raw_values = item_info.get("values", {})
        if not isinstance(raw_values, dict):
            raise ValueError(f"快照配置项 {item_info.get('id')} 的配置值格式无效")
        value_model_ids = {int(model_id) for model_id in raw_values}
        unexpected_model_ids = value_model_ids - snapshot_model_ids
        if unexpected_model_ids:
            raise ValueError(
                f"快照配置项 {item_info.get('id')} 引用了未声明的机型 "
                f"{sorted(unexpected_model_ids)}"
            )
        values = {str(int(model_id)): value_info for model_id, value_info in raw_values.items()}
        if not values:
            continue
        if any(not isinstance(value_info, dict) for value_info in values.values()):
            raise ValueError(f"快照配置项 {item_info.get('id')} 的配置值格式无效")

        item = _resolve_existing_item(item_info, all_items)
        if item is not None:
            logical_key = ("existing", item.id)
        elif item_info.get("ipn"):
            logical_key = ("ipn", str(item_info["ipn"]).strip())
        elif _has_reliable_no_ipn_identity(item_info):
            logical_key = ("metadata", _no_ipn_identity(item_info))
        else:
            logical_key = ("snapshot", item_info.get("id"))
        if logical_key in resolved_keys:
            raise ValueError(f"快照中多个配置项指向同一身份 {logical_key[1]}")
        if item is None and item_info.get("row_index") is None:
            raise ValueError(f"缺失的配置项 {item_info.get('id')} 没有可用的行号")
        resolved_keys.add(logical_key)
        resolved_items.append((item, {**item_info, "values": values}))

    if active_model_ids:
        await db.execute(delete(ConfigValue).where(ConfigValue.model_id.in_(active_model_ids)))

    restored_count = 0
    for item, item_info in resolved_items:
        if item is None:
            item = ConfigItem(**{field: item_info.get(field) for field in ITEM_FIELDS})
            db.add(item)
            await db.flush()
            all_items.append(item)

        for model_id, value_info in item_info["values"].items():
            db.add(
                ConfigValue(
                    item_id=item.id,
                    model_id=int(model_id),
                    **{field: value_info.get(field) for field in VALUE_FIELDS},
                )
            )
            restored_count += 1

    await db.flush()
    return restored_count

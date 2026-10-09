"""Stable source identities and historical aliases for imported product models."""
from copy import deepcopy
import json
from uuid import UUID

from sqlalchemy import inspect, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product_model import ProductModel, ProductModelIdentity
from app.models.draft import ConfigDraft, DraftBatch

MERGED_STATUS = "已合并"


def active_model_filter():
    return or_(ProductModel.status.is_(None), ProductModel.status != MERGED_STATUS)


def parse_model_header(raw: str) -> tuple[str, str | None]:
    parts = str(raw).split("//", 1)
    name = parts[0].strip()
    if not name:
        raise ValueError("机型名称不能为空")
    if len(parts) == 1:
        return name, None
    try:
        return name, str(UUID(parts[1].strip()))
    except ValueError as error:
        raise ValueError(f"机型 {name} 的源编号不是有效 UUID") from error


async def identity_records(db: AsyncSession, series_id: int | None = None):
    connection = await db.connection()
    exists = await connection.run_sync(lambda conn: inspect(conn).has_table(ProductModelIdentity.__tablename__))
    if not exists:
        return []  # Legacy databases/tests without this additive table.
    query = select(ProductModelIdentity, ProductModel).join(ProductModel, ProductModel.id == ProductModelIdentity.model_id)
    if series_id is not None:
        query = query.where(ProductModelIdentity.series_id == series_id)
    return list((await db.execute(query)).all())


async def inspect_import_model(
    db: AsyncSession,
    series_id: int,
    raw: str,
) -> tuple[str, str | None, ProductModel | None, ProductModelIdentity | None]:
    """Resolve an import header and validate identity conflicts without writing."""
    name, source_uuid = parse_model_header(raw)
    records = await identity_records(db, series_id)
    known = next(((identity, model) for identity, model in records if source_uuid and identity.source_uuid == source_uuid), None)
    names = (await db.execute(select(ProductModel).where(ProductModel.series_id == series_id, ProductModel.name == name, active_model_filter()))).scalars().all()
    if len(names) > 1:
        raise ValueError(f"系列内存在重复机型名 {name}，请先核对身份")
    named = names[0] if names else None
    if known:
        identity, model = known
        if named is not None and named.id != model.id:
            raise ValueError(f"机型 {name} 的源编号与现有记录冲突")
        if any(candidate.id != model.id and name in json.loads(record.aliases_json) for record, candidate in records):
            raise ValueError(f"机型 {name} 已是另一身份的曾用名，不能自动改名")
    else:
        alias_matches = [(identity, model) for identity, model in records if name in json.loads(identity.aliases_json)]
        if len(alias_matches) > 1:
            raise ValueError(f"机型曾用名 {name} 对应多个身份")
        if named is not None and any(candidate.id != named.id for _, candidate in alias_matches):
            raise ValueError(f"机型 {name} 已是另一身份的曾用名，不能绑定新的记录")
        model = named or (alias_matches[0][1] if alias_matches else None)
        identity = next((identity for identity, candidate in records if model is not None and candidate.id == model.id), None)
        if identity is not None and source_uuid and identity.source_uuid != source_uuid:
            raise ValueError(f"同名机型 {name} 的源编号不同，不能自动合并")
    return name, source_uuid, model, identity


async def resolve_import_model_readonly(db: AsyncSession, series_id: int, raw: str) -> ProductModel | None:
    """Validate the same identity rules as import, without creating or changing rows."""
    _, _, model, _ = await inspect_import_model(db, series_id, raw)
    return model


async def resolve_import_model(db: AsyncSession, series_id: int, raw: str, start: int, end: int, order: int) -> ProductModel:
    name, source_uuid, model, identity = await inspect_import_model(db, series_id, raw)
    if model is None:
        model = ProductModel(series_id=series_id, name=name, sort_order=order)
        db.add(model)
        await db.flush()
    if identity is None and source_uuid:
        identity = ProductModelIdentity(series_id=series_id, model_id=model.id, source_uuid=source_uuid, aliases_json="[]", historical_ids_json="[]")
        db.add(identity)
    if identity is not None:
        aliases = list(dict.fromkeys([*json.loads(identity.aliases_json), model.name, name]))
        identity.aliases_json = json.dumps(aliases, ensure_ascii=False)
    model.name = name
    model.column_start = start
    model.column_end = end
    await db.flush()
    return model


async def register_existing_identity(db: AsyncSession, series_id: int, source_uuid: str, current_name: str, previous_names: list[str]) -> dict:
    """Bind names verified from same-UUID workbooks; retain retired rows for history."""
    source_uuid = str(UUID(source_uuid))
    names = list(dict.fromkeys([*previous_names, current_name]))
    candidates = (await db.execute(select(ProductModel).where(ProductModel.series_id == series_id, ProductModel.name.in_(names)))).scalars().all()
    current = [model for model in candidates if model.name == current_name and model.status != MERGED_STATUS]
    if not current:
        current = [model for model in candidates if model.status != MERGED_STATUS]
    if len(current) != 1:
        raise ValueError(f"无法唯一确认 {current_name} 的当前机型记录")
    canonical = current[0]
    records = await identity_records(db, series_id)
    source = next((record for record, _ in records if record.source_uuid == source_uuid), None)
    if source is not None and source.model_id != canonical.id:
        raise ValueError(f"{current_name} 的源编号已绑定另一记录")
    for record, model in records:
        if record.source_uuid != source_uuid and (model.id == canonical.id or set(names).intersection(json.loads(record.aliases_json))):
            raise ValueError(f"{current_name} 与其他源编号冲突")
    if source is None:
        source = ProductModelIdentity(series_id=series_id, model_id=canonical.id, source_uuid=source_uuid, aliases_json="[]", historical_ids_json="[]")
        db.add(source)
    aliases = list(dict.fromkeys([*json.loads(source.aliases_json), *names]))
    retired_ids = set(json.loads(source.historical_ids_json))
    retired = []
    for model in candidates:
        if model.id == canonical.id:
            continue
        pending = await db.scalar(select(ConfigDraft.id).join(DraftBatch, DraftBatch.id == ConfigDraft.batch_id).where(ConfigDraft.model_id == model.id, DraftBatch.status == "draft").limit(1))
        if pending is not None:
            raise ValueError(f"历史机型 {model.name} 尚有未提交草稿，不能自动归档")
        model.status = MERGED_STATUS
        retired_ids.add(model.id)
        if not canonical.config_group and model.config_group:
            canonical.config_group = model.config_group
        retired.append(model.id)
    canonical.name = current_name
    source.aliases_json = json.dumps(aliases, ensure_ascii=False)
    source.historical_ids_json = json.dumps(sorted(retired_ids))
    await db.flush()
    return {"model_id": canonical.id, "name": current_name, "source_uuid": source_uuid, "historical_model_ids": retired}


async def model_identity_metadata(db: AsyncSession, model_ids: list[int]) -> dict[int, dict]:
    wanted = set(model_ids)
    return {model.id: {"source_uuid": identity.source_uuid, "aliases": json.loads(identity.aliases_json)} for identity, model in await identity_records(db) if model.id in wanted}


async def normalize_snapshot(db: AsyncSession, series_id: int, snapshot: dict) -> dict:
    """Resolve aliases for use, without modifying stored historical snapshots."""
    result = deepcopy(snapshot)
    records = await identity_records(db, series_id)
    by_uuid = {record.source_uuid: (record, model) for record, model in records}
    by_id: dict[int, tuple[ProductModelIdentity, ProductModel]] = {}
    by_name: dict[str, list[tuple[ProductModelIdentity, ProductModel]]] = {}
    for record, model in records:
        for model_id in [model.id, *json.loads(record.historical_ids_json)]:
            if model_id in by_id and by_id[model_id][1].id != model.id:
                raise ValueError(f"历史机型编号 {model_id} 对应多个身份")
            by_id[model_id] = (record, model)
        for name in set([model.name, *json.loads(record.aliases_json)]):
            by_name.setdefault(name, []).append((record, model))
    original_ids = {int(entry["id"]) for entry in result.get("models", [])}
    id_map = {}
    normalized_models = {}
    for entry in result.get("models", []):
        old_id = int(entry["id"])
        known = by_id.get(old_id) or by_uuid.get(entry.get("source_uuid"))
        if known is None:
            matches = by_name.get(entry.get("name"), [])
            if len(matches) > 1:
                raise ValueError(f"历史机型名称 {entry.get('name')} 对应多个身份")
            known = matches[0] if matches else None
        if known:
            identity, model = known
            if entry.get("source_uuid") and entry["source_uuid"] != identity.source_uuid:
                raise ValueError(f"历史机型 {entry.get('name')} 的编号与源身份冲突")
            canonical = {**entry, "id": model.id, "name": model.name, "source_uuid": identity.source_uuid}
        else:
            canonical = entry
        new_id = int(canonical["id"])
        id_map[old_id] = new_id
        if new_id not in normalized_models or old_id == new_id:
            normalized_models[new_id] = canonical
    result["models"] = list(normalized_models.values())
    for item in result.get("items", []):
        merged = {}
        for old_id, value in item.get("values", {}).items():
            old_id = int(old_id)
            new_id = id_map.get(old_id, old_id)
            # Canonical presence governs every item, including absent values.
            # Only older snapshots without that record inherit alias values.
            if old_id != new_id and new_id in original_ids:
                continue
            merged[str(new_id)] = value
        item["values"] = merged
    return result

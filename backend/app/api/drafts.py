"""
草稿管理 API
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from copy import deepcopy
import json
import hashlib
import uuid

from app.database import get_db
from app.utils.time import utcnow
from app.models import DraftBatch, ConfigDraft, ProductSeries, ConfigItem, ConfigValue, ProductModel, ConfigVersion
from app.schemas.draft import (
    DraftBatchResponse, DraftSubmitRequest,
    ConfigDraftCreate, DraftStatsResponse,
    BatchDiscardRequest, BatchDiscardResponse, BatchDiscardResult,
    BatchSubmitRequest, BatchSubmitResponse, BatchSubmitResult
)
from app.utils import generate_next_version

from app.services.config_history import (
    build_series_snapshot,
    resolve_snapshot_item,
    restore_series_snapshot,
)
from app.services.model_identity import MERGED_STATUS, normalize_snapshot

router = APIRouter()

CONFIG_FIELDS = (
    "current_config", "final_config", "selection_config", "rd_status"
)
CHANGE_TYPES = ("create", "update", "delete")


async def _drafts_for_batch(db: AsyncSession, batch_id: str) -> list[ConfigDraft]:
    result = await db.execute(
        select(ConfigDraft)
        .where(ConfigDraft.batch_id == batch_id)
        .order_by(ConfigDraft.id)
    )
    return list(result.scalars().all())


def _draft_counts(drafts: list[ConfigDraft]) -> dict[str, int]:
    counts = {"total": len(drafts), "create": 0, "update": 0, "delete": 0}
    for draft in drafts:
        if draft.change_type in CHANGE_TYPES:
            counts[draft.change_type] += 1
    return counts


def _set_batch_counts(batch: DraftBatch, counts: dict[str, int]) -> None:
    batch.total_count = counts["total"]
    batch.create_count = counts["create"]
    batch.update_count = counts["update"]
    batch.delete_count = counts["delete"]


async def _refresh_batch_counts(db: AsyncSession, batch: DraftBatch) -> dict[str, int]:
    await db.flush()
    counts = _draft_counts(await _drafts_for_batch(db, batch.id))
    _set_batch_counts(batch, counts)
    return counts


async def _latest_version(db: AsyncSession, series_id: int) -> Optional[ConfigVersion]:
    return await db.scalar(
        select(ConfigVersion)
        .where(ConfigVersion.series_id == series_id)
        .order_by(ConfigVersion.id.desc())
        .limit(1)
    )


async def _latest_snapshot(db: AsyncSession, series_id: int) -> dict:
    version = await _latest_version(db, series_id)
    if not version or not version.snapshot_data:
        return {"models": [], "items": []}
    return await normalize_snapshot(db, series_id, json.loads(version.snapshot_data))


def _snapshot_item(snapshot: dict, item: ConfigItem) -> Optional[dict]:
    try:
        return resolve_snapshot_item(item, snapshot)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _snapshot_pair(snapshot: dict, item: ConfigItem, model_id: int) -> Optional[dict]:
    snapshot_item = _snapshot_item(snapshot, item)
    if not snapshot_item:
        return None
    values = snapshot_item.get("values") or {}
    value = values.get(str(model_id), values.get(model_id))
    return deepcopy(value) if value is not None else None


def _set_snapshot_pair(
    snapshot: dict, item: ConfigItem, model_id: int, value: Optional[dict]
) -> None:
    snapshot_item = _snapshot_item(snapshot, item)
    if not snapshot_item:
        return
    values = snapshot_item.setdefault("values", {})
    values.pop(model_id, None)
    values.pop(str(model_id), None)
    if value is not None:
        values[str(model_id)] = deepcopy(value)


async def _config_value(
    db: AsyncSession, item_id: int, model_id: int
) -> Optional[ConfigValue]:
    return await db.scalar(
        select(ConfigValue).where(
            ConfigValue.item_id == item_id,
            ConfigValue.model_id == model_id,
        )
    )


async def _validate_target(
    db: AsyncSession,
    batch: DraftBatch,
    series_id: int,
    item_id: Optional[int],
    model_id: Optional[int],
) -> tuple[ConfigItem, ProductModel]:
    if batch.status != "draft":
        raise HTTPException(status_code=400, detail="草稿批次不是待编辑状态")
    if series_id != batch.series_id:
        raise HTTPException(status_code=400, detail="草稿系列与批次系列不一致")
    if item_id is None or model_id is None:
        raise HTTPException(status_code=400, detail="草稿必须指定配置项和机型")
    item = await db.get(ConfigItem, item_id)
    model = await db.get(ProductModel, model_id)
    if not item:
        raise HTTPException(status_code=400, detail="配置项不存在")
    if not model:
        raise HTTPException(status_code=400, detail="机型不存在")
    if model.series_id != batch.series_id:
        raise HTTPException(status_code=400, detail="机型不属于草稿批次系列")
    if model.status == MERGED_STATUS:
        raise HTTPException(status_code=400, detail="已合并机型不能创建草稿")
    return item, model


async def _validate_stored_drafts(
    db: AsyncSession, batch: DraftBatch, drafts: list[ConfigDraft]
) -> dict[int, ConfigItem]:
    items = {}
    for draft in drafts:
        if draft.change_type not in CHANGE_TYPES:
            raise HTTPException(status_code=400, detail=f"草稿 {draft.id} 的变更类型无效")
        if draft.change_type == "update" and draft.field_name not in CONFIG_FIELDS:
            raise HTTPException(status_code=400, detail=f"草稿 {draft.id} 的字段无效")
        if draft.field_name is not None and draft.field_name not in CONFIG_FIELDS:
            raise HTTPException(status_code=400, detail=f"草稿 {draft.id} 的字段无效")
        item, _ = await _validate_target(
            db, batch, draft.series_id, draft.item_id, draft.model_id
        )
        items[item.id] = item
    return items


@router.get("/batch/current/{series_id}")
async def get_current_draft_batch(
    series_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取当前用户的草稿批次（未提交的）"""
    # 查找该系列下状态为 draft 的最新批次
    result = await db.execute(
        select(DraftBatch)
        .where(
            DraftBatch.series_id == series_id,
            DraftBatch.status == "draft"
        )
        .order_by(DraftBatch.created_at.desc())
        .limit(1)
    )
    batch = result.scalar_one_or_none()

    if not batch:
        return {"exists": False}

    # 获取草稿列表（限制最多 5000 条，避免响应过大）
    DRAFT_LIMIT = 5000
    all_drafts = await _drafts_for_batch(db, batch.id)
    counts = _draft_counts(all_drafts)
    drafts = all_drafts[:DRAFT_LIMIT]

    # 批量查询配置项名称
    item_ids = [d.item_id for d in drafts if d.item_id]
    items_map = {}
    if item_ids:
        items_result = await db.execute(
            select(ConfigItem).where(ConfigItem.id.in_(item_ids))
        )
        items_map = {i.id: {"rd_name": i.rd_name, "ipn": i.ipn} for i in items_result.scalars().all()}

    # 删除草稿的旧值来自最近发布版本；工作区可能已经移除了该配置对。
    snapshot_values_map = {}
    baseline = await _latest_snapshot(db, series_id)
    for d in drafts:
        item = items_map.get(d.item_id)
        if d.change_type == "delete" and item and d.model_id:
            db_item = await db.get(ConfigItem, d.item_id)
            pair = _snapshot_pair(baseline, db_item, d.model_id)
            if pair is not None:
                snapshot_values_map[(d.item_id, d.model_id)] = pair

    return {
        "exists": True,
        "batch": {
            "id": batch.id,
            "series_id": batch.series_id,
            "status": batch.status,
            "total_count": counts["total"],
            "create_count": counts["create"],
            "update_count": counts["update"],
            "delete_count": counts["delete"],
            "created_at": batch.created_at.isoformat() if batch.created_at else None
        },
        "drafts": [
            {
                "id": d.id,
                "change_type": d.change_type,
                "item_id": d.item_id,
                "model_id": d.model_id,
                "field_name": d.field_name,
                "old_value": d.old_value,
                "new_value": d.new_value,
                "rd_name": items_map.get(d.item_id, {}).get("rd_name") if d.item_id else None,
                "ipn": items_map.get(d.item_id, {}).get("ipn") if d.item_id else None,
                "snapshot_values": (
                    json.dumps(snapshot_values_map.get(
                        (d.item_id, d.model_id)
                    ))
                    if d.change_type == "delete" and d.item_id and d.model_id
                    and (d.item_id, d.model_id) in snapshot_values_map
                    else None
                )
            }
            for d in drafts
        ]
    }


@router.get("/batch/{batch_id}", response_model=DraftBatchResponse)
async def get_draft_batch(
    batch_id: str,
    db: AsyncSession = Depends(get_db)
):
    """获取草稿批次详情"""
    result = await db.execute(select(DraftBatch).where(DraftBatch.id == batch_id))
    batch = result.scalar_one_or_none()

    if not batch:
        raise HTTPException(status_code=404, detail="草稿批次不存在")

    _set_batch_counts(batch, _draft_counts(await _drafts_for_batch(db, batch_id)))
    return batch


@router.get("/batch/{batch_id}/stats", response_model=DraftStatsResponse)
async def get_draft_stats(
    batch_id: str,
    db: AsyncSession = Depends(get_db)
):
    """获取草稿统计"""
    result = await db.execute(select(DraftBatch).where(DraftBatch.id == batch_id))
    batch = result.scalar_one_or_none()

    if not batch:
        raise HTTPException(status_code=404, detail="草稿批次不存在")

    return DraftStatsResponse(**_draft_counts(await _drafts_for_batch(db, batch_id)))


@router.get("/batch/{batch_id}/drafts")
async def get_draft_list(
    batch_id: str,
    db: AsyncSession = Depends(get_db)
):
    """获取草稿列表"""
    result = await db.execute(
        select(ConfigDraft).where(ConfigDraft.batch_id == batch_id)
    )
    drafts = result.scalars().all()

    # 获取关联信息
    items_result = await db.execute(select(ConfigItem))
    items = {i.id: i for i in items_result.scalars().all()}

    models_result = await db.execute(select(ProductModel))
    models = {m.id: m for m in models_result.scalars().all()}

    draft_list = []
    for d in drafts:
        item = items.get(d.item_id)
        model = models.get(d.model_id)

        draft_list.append({
            "id": d.id,
            "item_id": d.item_id,
            "model_id": d.model_id,
            "change_type": d.change_type,
            "rd_name": item.rd_name if item else None,
            "ipn": item.ipn if item else None,
            "model_name": model.name if model else None,
            "field_name": d.field_name,
            "old_value": d.old_value,
            "new_value": d.new_value
        })

    return {"items": draft_list, "total": len(draft_list)}


@router.post("/batch")
async def create_draft_batch(
    series_id: int,
    filename: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """创建草稿批次"""
    if not await db.get(ProductSeries, series_id):
        raise HTTPException(status_code=404, detail="产品系列不存在")
    # 检查是否有未提交的草稿
    result = await db.execute(
        select(DraftBatch)
        .where(DraftBatch.series_id == series_id, DraftBatch.status == "draft")
    )
    existing = result.scalar_one_or_none()

    if existing:
        _set_batch_counts(
            existing, _draft_counts(await _drafts_for_batch(db, existing.id))
        )
        return existing

    batch = DraftBatch(
        id=str(uuid.uuid4()),
        series_id=series_id,
        filename=filename
    )

    db.add(batch)
    await db.commit()
    await db.refresh(batch)

    return batch


@router.post("/draft")
async def create_draft(
    data: ConfigDraftCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建草稿项"""
    batch = await db.get(DraftBatch, data.batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="草稿批次不存在")
    item, _ = await _validate_target(
        db, batch, data.series_id, data.item_id, data.model_id
    )
    if data.change_type == "update" and data.field_name is None:
        raise HTTPException(status_code=400, detail="更新草稿必须指定配置字段")

    existing = await db.scalar(
        select(ConfigDraft).where(
            ConfigDraft.batch_id == data.batch_id,
            ConfigDraft.item_id == data.item_id,
            ConfigDraft.model_id == data.model_id,
            ConfigDraft.field_name == data.field_name
        )
    )
    if existing:
        # old_value 是首次编辑前的权威基线，重复编辑不可覆盖。
        existing.new_value = data.new_value
        existing.change_type = data.change_type
        await _sync_config_value(db, data)
        await _refresh_batch_counts(db, batch)
        await db.commit()
        return {"message": "草稿已更新", "draft_id": existing.id}

    old_value = None
    if data.field_name is not None:
        value = await _config_value(db, data.item_id, data.model_id)
        if value is not None:
            old_value = getattr(value, data.field_name)
        else:
            baseline = _snapshot_pair(
                await _latest_snapshot(db, batch.series_id), item, data.model_id
            )
            old_value = baseline.get(data.field_name) if baseline else None
    draft = ConfigDraft(
        series_id=batch.series_id,
        batch_id=batch.id,
        change_type=data.change_type,
        item_id=data.item_id,
        model_id=data.model_id,
        field_name=data.field_name,
        new_value=data.new_value,
        old_value=old_value
    )
    db.add(draft)
    await _sync_config_value(db, data)
    await _refresh_batch_counts(db, batch)
    await db.commit()
    await db.refresh(draft)
    return {"message": "草稿已保存", "draft_id": draft.id}


async def _sync_config_value(db, data):
    """将草稿的 new_value 同步写入 DB ConfigValue"""
    if not data.field_name:
        return
    cv = await _config_value(db, data.item_id, data.model_id)
    if cv:
        setattr(cv, data.field_name, data.new_value)
    else:
        cv = ConfigValue(
            item_id=data.item_id,
            model_id=data.model_id,
        )
        setattr(cv, data.field_name, data.new_value)
        db.add(cv)


async def _rewind_snapshot_for_remaining_drafts(
    db: AsyncSession,
    series_id: int,
    snapshot: dict,
    remaining: list[ConfigDraft],
    items: dict[int, ConfigItem],
) -> dict:
    """从 working snapshot 撤除尚未提交的草稿变更。"""
    if not remaining:
        return snapshot
    baseline = await _latest_snapshot(db, series_id)
    for draft in remaining:
        item = items[draft.item_id]
        baseline_pair = _snapshot_pair(baseline, item, draft.model_id)
        if draft.change_type == "create" and draft.field_name is None:
            _set_snapshot_pair(snapshot, item, draft.model_id, None)
        elif draft.change_type == "delete" and draft.field_name is None:
            _set_snapshot_pair(snapshot, item, draft.model_id, baseline_pair)
        else:
            pair = _snapshot_pair(snapshot, item, draft.model_id) or {
                field: None for field in CONFIG_FIELDS
            }
            pair[draft.field_name] = (
                baseline_pair.get(draft.field_name)
                if baseline_pair is not None
                else draft.old_value
            )
            _set_snapshot_pair(snapshot, item, draft.model_id, pair)
    return snapshot


async def _resolve_version_number(
    db: AsyncSession, series_id: int, requested: Optional[str]
) -> str:
    last_version = await _latest_version(db, series_id)
    version_number = requested or generate_next_version(
        last_version.version_number if last_version else None
    )
    duplicate = await db.scalar(
        select(ConfigVersion.id).where(
            ConfigVersion.series_id == series_id,
            ConfigVersion.version_number == version_number,
        )
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=400,
            detail=f"版本号 {version_number} 在该系列中已存在",
        )
    return version_number


def _select_submission_drafts(all_drafts: list[ConfigDraft], data: DraftSubmitRequest) -> list[ConfigDraft]:
    """Use the same explicit item/model scope for preview and publication."""
    item_ids = set(data.item_ids) if data.item_ids is not None else None
    model_ids = set(data.model_ids) if data.model_ids is not None else None
    if item_ids == set() or model_ids == set():
        return []
    return [draft for draft in all_drafts
            if (item_ids is None or draft.item_id in item_ids)
            and (model_ids is None or draft.model_id is None or draft.model_id in model_ids)]


async def _submission_signature(db: AsyncSession, batch: DraftBatch, all_drafts: list[ConfigDraft], data: DraftSubmitRequest) -> str:
    """Detect additions, edits, removals and scope changes after user review."""
    latest = await _latest_version(db, batch.series_id)
    payload = {
        "working_snapshot": await build_series_snapshot(db, batch.series_id),
        "baseline": [latest.id, latest.snapshot_data] if latest else None,
        "batch": [batch.id, batch.series_id, batch.status],
        "items": sorted(set(data.item_ids)) if data.item_ids is not None else None,
        "models": sorted(set(data.model_ids)) if data.model_ids is not None else None,
        "drafts": [[draft.id, draft.series_id, draft.item_id, draft.model_id,
                    draft.change_type, draft.field_name, draft.old_value, draft.new_value]
                   for draft in sorted(all_drafts, key=lambda draft: draft.id)],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


@router.post("/batch/{batch_id}/submit-preview")
async def preview_draft_submission(batch_id: str, data: DraftSubmitRequest, db: AsyncSession = Depends(get_db)):
    batch = await db.get(DraftBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="草稿批次不存在")
    if batch.status != "draft":
        raise HTTPException(status_code=400, detail="草稿已提交或已废弃")
    all_drafts = await _drafts_for_batch(db, batch_id)
    items = await _validate_stored_drafts(db, batch, all_drafts)
    selected = _select_submission_drafts(all_drafts, data)
    model_ids = {draft.model_id for draft in selected if draft.model_id is not None}
    models = list((await db.execute(select(ProductModel).where(ProductModel.id.in_(model_ids)))).scalars().all()) if model_ids else []
    model_names = {model.id: model.name for model in models}
    series = await db.get(ProductSeries, batch.series_id)
    fields = {field for draft in selected for field in ((draft.field_name,) if draft.field_name else CONFIG_FIELDS)}
    counts = _draft_counts(selected)
    return {
        "batch_id": batch.id, "series_id": batch.series_id,
        "series_name": series.name if series else str(batch.series_id),
        "signature": await _submission_signature(db, batch, all_drafts, data),
        "total_items": len({draft.item_id for draft in selected}),
        "total_changes": len(selected), "total_models": len(model_ids),
        "fields": [field for field in CONFIG_FIELDS if field in fields],
        "models": [{"id": model.id, "name": model.name} for model in models],
        "change_counts": {kind: counts[kind] for kind in CHANGE_TYPES},
        "remaining_changes": len(all_drafts) - len(selected),
        "drafts": [{"item_id": draft.item_id, "model_id": draft.model_id,
                    "field_name": draft.field_name, "change_type": draft.change_type,
                    "rd_name": items[draft.item_id].rd_name, "model_name": model_names.get(draft.model_id),
                    "old_value": draft.old_value, "new_value": draft.new_value} for draft in selected],
    }


@router.post("/batch/{batch_id}/submit")
async def submit_draft_batch(
    batch_id: str,
    data: DraftSubmitRequest,
    db: AsyncSession = Depends(get_db)
):
    """提交草稿批次"""
    result = await db.execute(select(DraftBatch).where(DraftBatch.id == batch_id))
    batch = result.scalar_one_or_none()

    if not batch:
        raise HTTPException(status_code=404, detail="草稿批次不存在")

    if batch.status != "draft":
        raise HTTPException(status_code=400, detail="草稿已提交或已废弃")

    # 查询草稿
    drafts_result = await db.execute(
        select(ConfigDraft).where(ConfigDraft.batch_id == batch_id)
    )
    all_drafts = drafts_result.scalars().all()

    if not all_drafts:
        raise HTTPException(status_code=400, detail="没有待提交的草稿")
    validated_items = await _validate_stored_drafts(db, batch, all_drafts)

    if data.expected_signature is not None and data.expected_signature != await _submission_signature(db, batch, all_drafts, data):
        raise HTTPException(status_code=409, detail="草稿或提交范围已变化，请重新核对发布预览")
    drafts = _select_submission_drafts(all_drafts, data)
    processed_count = len(drafts)
    if not drafts:
        raise HTTPException(status_code=400, detail="筛选条件没有匹配的草稿")
    version_number = await _resolve_version_number(
        db, batch.series_id, data.version_number
    )

    # 提取所有需要更新的 (item_id, model_id) 组合
    update_drafts = [
        d for d in drafts
        if d.change_type == "update" and d.item_id and d.model_id
    ]

    if update_drafts:
        ids = [d.item_id for d in update_drafts]
        mids = [d.model_id for d in update_drafts]

        values_result = await db.execute(
            select(ConfigValue).where(
                ConfigValue.item_id.in_(ids),
                ConfigValue.model_id.in_(mids)
            )
        )
        values_map = {(v.item_id, v.model_id): v for v in values_result.scalars().all()}

        for draft in update_drafts:
            value = values_map.get((draft.item_id, draft.model_id))
            if value and draft.field_name:
                setattr(value, draft.field_name, draft.new_value)

    # 处理删除类型的草稿
    delete_drafts = [
        d for d in drafts
        if d.change_type == "delete" and d.item_id
    ]
    if delete_drafts:
        for draft in delete_drafts:
            val = await _config_value(db, draft.item_id, draft.model_id)
            if val:
                fields = (draft.field_name,) if draft.field_name else CONFIG_FIELDS
                for field in fields:
                    setattr(val, field, None)

    # 删除已处理的草稿（部分提交时去除已提交项，全量提交时清除全部）
    for draft in drafts:
        await db.delete(draft)

    counts = await _refresh_batch_counts(db, batch)
    remaining_drafts = await _drafts_for_batch(db, batch_id)

    snapshot = await build_series_snapshot(db, batch.series_id)
    snapshot = await _rewind_snapshot_for_remaining_drafts(
        db, batch.series_id, snapshot, remaining_drafts, validated_items
    )

    # 创建版本记录
    version = ConfigVersion(
        series_id=batch.series_id,
        version_number=version_number,
        version_name=data.version_name,
        description=data.description,
        snapshot_data=json.dumps(snapshot, ensure_ascii=False),
        row_count=len(snapshot.get("items", [])),
        published_by="system"
    )
    db.add(version)

    # 更新批次状态（部分提交后若还有剩余草稿则不标记为 submitted）
    if counts["total"] == 0:
        batch.status = "submitted"
        batch.submitted_at = utcnow()
    # 有剩余草稿时保持 draft 状态

    await db.commit()
    await db.refresh(version)

    return {
        "message": "提交成功",
        "version_number": version_number,
        "changes": processed_count
    }


async def _process_single_batch_submit(
    batch_id: str,
    description: Optional[str] = None,
    version_name: Optional[str] = None,
    version_number: Optional[str] = None,
    db: AsyncSession = None,
    expected_signature: Optional[str] = None
) -> dict:
    """处理单个批次提交（提取公共逻辑供批量使用）"""
    result = await db.execute(select(DraftBatch).where(DraftBatch.id == batch_id))
    batch = result.scalar_one_or_none()

    if not batch:
        return {"success": False, "message": "草稿批次不存在"}

    if batch.status != "draft":
        return {"success": False, "message": f"草稿已提交或已废弃 (status={batch.status})"}

    # 查询草稿
    drafts_result = await db.execute(
        select(ConfigDraft).where(ConfigDraft.batch_id == batch_id)
    )
    all_drafts = drafts_result.scalars().all()
    if not all_drafts:
        return {"success": False, "message": "草稿批次中没有草稿项"}
    if expected_signature is not None and expected_signature != await _submission_signature(db, batch, all_drafts, DraftSubmitRequest()):
        return {"success": False, "message": "草稿已变化，请重新核对发布预览"}
    try:
        await _validate_stored_drafts(db, batch, all_drafts)
        version_number = await _resolve_version_number(
            db, batch.series_id, version_number
        )
    except HTTPException as error:
        return {"success": False, "message": error.detail}

    # 处理更新类型的草稿
    update_drafts = [
        d for d in all_drafts
        if d.change_type == "update" and d.item_id and d.model_id
    ]
    if update_drafts:
        ids = [d.item_id for d in update_drafts]
        mids = [d.model_id for d in update_drafts]

        values_result = await db.execute(
            select(ConfigValue).where(
                ConfigValue.item_id.in_(ids),
                ConfigValue.model_id.in_(mids)
            )
        )
        values_map = {(v.item_id, v.model_id): v for v in values_result.scalars().all()}

        for draft in update_drafts:
            value = values_map.get((draft.item_id, draft.model_id))
            if value and draft.field_name:
                setattr(value, draft.field_name, draft.new_value)

    # 处理删除类型的草稿
    delete_drafts = [
        d for d in all_drafts
        if d.change_type == "delete" and d.item_id
    ]
    if delete_drafts:
        for draft in delete_drafts:
            val = await _config_value(db, draft.item_id, draft.model_id)
            if val:
                fields = (draft.field_name,) if draft.field_name else CONFIG_FIELDS
                for field in fields:
                    setattr(val, field, None)

    # 删除所有草稿
    for draft in all_drafts:
        await db.delete(draft)

    snapshot = await build_series_snapshot(db, batch.series_id)

    # 创建版本记录
    version = ConfigVersion(
        series_id=batch.series_id,
        version_number=version_number,
        version_name=version_name,
        description=description,
        snapshot_data=json.dumps(snapshot, ensure_ascii=False),
        row_count=len(snapshot.get("items", [])),
        published_by="system"
    )
    db.add(version)

    # 更新批次状态
    batch.status = "submitted"
    batch.submitted_at = utcnow()
    batch.total_count = 0
    batch.create_count = 0
    batch.update_count = 0
    batch.delete_count = 0

    return {
        "success": True,
        "message": "提交成功",
        "series_id": batch.series_id,
        "version_number": version_number,
        "changes": len(all_drafts)
    }


@router.post("/batch/discard", response_model=BatchDiscardResponse)
async def batch_discard_drafts(
    data: BatchDiscardRequest,
    db: AsyncSession = Depends(get_db)
):
    """批量撤销草稿批次"""
    results = []

    for batch_id in data.batch_ids:
        try:
            # 使用现有的 discard 逻辑
            result = await db.execute(select(DraftBatch).where(DraftBatch.id == batch_id))
            batch = result.scalar_one_or_none()

            if not batch:
                results.append(BatchDiscardResult(
                    batch_id=batch_id, series_id=0,
                    success=False, message="草稿批次不存在"
                ))
                continue
            if batch.status != "draft":
                results.append(BatchDiscardResult(
                    batch_id=batch_id,
                    series_id=batch.series_id,
                    success=False,
                    message=f"草稿已提交或已废弃 (status={batch.status})",
                ))
                continue

            series_id = batch.series_id

            await restore_series_snapshot(db, series_id, await _latest_snapshot(db, series_id))

            # 删除该批次的所有 ConfigDraft
            drafts_to_del = await db.execute(
                select(ConfigDraft).where(ConfigDraft.batch_id == batch_id)
            )
            for draft in drafts_to_del.scalars().all():
                await db.delete(draft)

            # 重置统计并废弃
            batch.total_count = 0
            batch.create_count = 0
            batch.update_count = 0
            batch.delete_count = 0
            batch.status = "discarded"
            await db.commit()

            results.append(BatchDiscardResult(
                batch_id=batch_id, series_id=series_id,
                success=True, message="数据已回滚"
            ))
        except Exception as e:
            results.append(BatchDiscardResult(
                batch_id=batch_id, series_id=0,
                success=False, message=str(e)
            ))
            await db.rollback()  # 回滚事务以便后续继续

    return BatchDiscardResponse(
        discarded_count=sum(1 for r in results if r.success),
        results=results
    )


@router.post("/batch/submit", response_model=BatchSubmitResponse)
async def batch_submit_drafts(
    data: BatchSubmitRequest,
    db: AsyncSession = Depends(get_db)
):
    """批量提交草稿批次"""
    results = []

    for batch_id in data.batch_ids:
        try:
            if data.expected_signatures is not None and batch_id not in data.expected_signatures:
                raise HTTPException(status_code=409, detail="缺少该系列发布预览，请重新核对")
            result = await _process_single_batch_submit(
                batch_id=batch_id,
                description=data.description,
                version_name=data.version_name,
                version_number=data.version_number,
                db=db,
                expected_signature=data.expected_signatures.get(batch_id) if data.expected_signatures is not None else None
            )
            if result["success"]:
                await db.commit()
                results.append(BatchSubmitResult(
                    batch_id=batch_id,
                    series_id=result["series_id"],
                    version_number=result["version_number"],
                    changes=result["changes"],
                    success=True,
                    message=result["message"]
                ))
            else:
                await db.rollback()
                results.append(BatchSubmitResult(
                    batch_id=batch_id,
                    series_id=0,
                    version_number="",
                    changes=0,
                    success=False,
                    message=result["message"]
                ))
        except Exception as e:
            await db.rollback()
            results.append(BatchSubmitResult(
                batch_id=batch_id,
                series_id=0,
                version_number="",
                changes=0,
                success=False,
                message=str(e)
            ))

    return BatchSubmitResponse(
        submitted_count=sum(1 for r in results if r.success),
        results=results
    )


@router.delete("/batch/{batch_id}")
async def discard_draft_batch(
    batch_id: str,
    db: AsyncSession = Depends(get_db)
):
    """废弃草稿批次（回滚 ConfigValue 和 ConfigItem 数据到最近一次提交版本）"""
    try:
        result = await db.execute(select(DraftBatch).where(DraftBatch.id == batch_id))
        batch = result.scalar_one_or_none()

        if not batch:
            raise HTTPException(status_code=404, detail="草稿批次不存在")
        if batch.status != "draft":
            raise HTTPException(status_code=400, detail="草稿已提交或已废弃")

        series_id = batch.series_id

        # 先删草稿（避免后续操作受 FK 约束影响）
        drafts_to_delete = await db.execute(
            select(ConfigDraft).where(ConfigDraft.batch_id == batch_id)
        )
        for draft in drafts_to_delete.scalars().all():
            await db.delete(draft)

        await restore_series_snapshot(db, series_id, await _latest_snapshot(db, series_id))

        # 重置批次统计
        batch.total_count = 0
        batch.create_count = 0
        batch.update_count = 0
        batch.delete_count = 0

        # 设置批次状态
        batch.status = "discarded"

        await db.commit()

        return {"message": "草稿已废弃，数据已回滚"}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"废弃失败: {str(e)}")


async def _restore_then_delete_draft(db: AsyncSession, draft: ConfigDraft) -> None:
    """撤销单条草稿对 working ConfigValue 的同步改动。"""
    batch = await db.get(DraftBatch, draft.batch_id)
    if not batch or batch.status != "draft":
        raise HTTPException(status_code=400, detail="草稿批次不是待编辑状态")
    value = await _config_value(db, draft.item_id, draft.model_id)
    if draft.change_type == "update" and draft.field_name in CONFIG_FIELDS:
        if value is None:
            value = ConfigValue(item_id=draft.item_id, model_id=draft.model_id)
            db.add(value)
        setattr(value, draft.field_name, draft.old_value)
    elif draft.change_type == "create" and value is not None:
        if draft.field_name:
            setattr(value, draft.field_name, draft.old_value)
        else:
            await db.delete(value)
    elif draft.change_type == "delete":
        item = await db.get(ConfigItem, draft.item_id)
        baseline = (
            _snapshot_pair(await _latest_snapshot(db, draft.series_id), item, draft.model_id)
            if item else None
        )
        if baseline is None:
            if value is not None:
                if draft.field_name:
                    setattr(value, draft.field_name, draft.old_value)
                else:
                    await db.delete(value)
        else:
            if value is None:
                value = ConfigValue(item_id=draft.item_id, model_id=draft.model_id)
                db.add(value)
            fields = (draft.field_name,) if draft.field_name else CONFIG_FIELDS
            for field in fields:
                setattr(value, field, baseline.get(field))
    await db.delete(draft)
    await _refresh_batch_counts(db, batch)


# 静态路由必须声明在 /draft/{draft_id} 前。
@router.delete("/draft/by-key")
async def delete_draft_by_key(
    batch_id: str,
    item_id: int,
    model_id: int,
    field_name: str,
    db: AsyncSession = Depends(get_db)
):
    """根据条件删除草稿并恢复 working value。"""
    if field_name not in CONFIG_FIELDS:
        raise HTTPException(status_code=422, detail="配置字段无效")
    draft = await db.scalar(
        select(ConfigDraft).where(
            ConfigDraft.batch_id == batch_id,
            ConfigDraft.item_id == item_id,
            ConfigDraft.model_id == model_id,
            ConfigDraft.field_name == field_name
        )
    )
    if not draft:
        return {"message": "草稿不存在", "deleted": False}
    await _restore_then_delete_draft(db, draft)
    await db.commit()
    return {"message": "删除成功", "deleted": True}


@router.delete("/draft/{draft_id}")
async def delete_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db)
):
    """删除单个草稿"""
    result = await db.execute(select(ConfigDraft).where(ConfigDraft.id == draft_id))
    draft = result.scalar_one_or_none()

    if not draft:
        raise HTTPException(status_code=404, detail="草稿不存在")

    await _restore_then_delete_draft(db, draft)
    await db.commit()

    return {"message": "删除成功"}

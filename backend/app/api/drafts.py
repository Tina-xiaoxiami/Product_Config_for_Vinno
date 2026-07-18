"""
草稿管理 API
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from typing import List, Optional
import json
import uuid

from app.database import get_db
from app.models import DraftBatch, ConfigDraft, ProductSeries, ConfigItem, ConfigValue, ProductModel, ConfigVersion
from app.schemas.draft import (
    DraftBatchResponse, DraftSubmitRequest,
    ConfigDraftCreate, ConfigDraftResponse, DraftStatsResponse,
    BatchDiscardRequest, BatchDiscardResponse, BatchDiscardResult,
    BatchSubmitRequest, BatchSubmitResponse, BatchSubmitResult
)
from app.utils import generate_next_version

router = APIRouter()


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
    drafts_result = await db.execute(
        select(ConfigDraft)
        .where(ConfigDraft.batch_id == batch.id)
        .limit(DRAFT_LIMIT)
    )
    drafts = drafts_result.scalars().all()

    # 批量查询配置项名称
    item_ids = [d.item_id for d in drafts if d.item_id]
    items_map = {}
    if item_ids:
        items_result = await db.execute(
            select(ConfigItem).where(ConfigItem.id.in_(item_ids))
        )
        items_map = {i.id: {"rd_name": i.rd_name, "ipn": i.ipn} for i in items_result.scalars().all()}

    # 为删除草稿构建当前值索引：直接从数据库读取当前 ConfigValue
    # （delete 草稿的 (item_id, model_id) 对，current_config/final_config/selection_config/rd_status 即为旧值）
    snapshot_values_map = {}
    delete_item_model_pairs = set()
    for d in drafts:
        if d.change_type == "delete" and d.item_id and d.model_id:
            delete_item_model_pairs.add((d.item_id, d.model_id))
    if delete_item_model_pairs:
        # 分批查询避免 SQL 过大
        for item_id, model_id in delete_item_model_pairs:
            cv_result = await db.execute(
                select(ConfigValue).where(
                    ConfigValue.item_id == item_id,
                    ConfigValue.model_id == model_id
                )
            )
            cv = cv_result.scalar_one_or_none()
            if cv:
                # 用 (item_id, model_id) 做 key，因为 IPN 可能为空
                snapshot_values_map[(item_id, model_id)] = {
                    "current_config": cv.current_config,
                    "final_config": cv.final_config,
                    "selection_config": cv.selection_config,
                    "rd_status": cv.rd_status
                }

    return {
        "exists": True,
        "batch": {
            "id": batch.id,
            "series_id": batch.series_id,
            "status": batch.status,
            "total_count": batch.total_count,
            "create_count": batch.create_count,
            "update_count": batch.update_count,
            "delete_count": batch.delete_count,
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

    return DraftStatsResponse(
        total=batch.total_count,
        create=batch.create_count,
        update=batch.update_count,
        delete=batch.delete_count
    )


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
    # 检查是否有未提交的草稿
    result = await db.execute(
        select(DraftBatch)
        .where(DraftBatch.series_id == series_id, DraftBatch.status == "draft")
    )
    existing = result.scalar_one_or_none()

    if existing:
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
    # 检查批次是否存在
    batch_result = await db.execute(select(DraftBatch).where(DraftBatch.id == data.batch_id))
    batch = batch_result.scalar_one_or_none()

    if not batch:
        raise HTTPException(status_code=404, detail="草稿批次不存在")

    # 检查是否已存在相同的草稿
    existing_result = await db.execute(
        select(ConfigDraft).where(
            ConfigDraft.batch_id == data.batch_id,
            ConfigDraft.item_id == data.item_id,
            ConfigDraft.model_id == data.model_id,
            ConfigDraft.field_name == data.field_name
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        # 更新现有草稿
        existing.new_value = data.new_value
        existing.old_value = data.old_value
        existing.change_type = data.change_type
        # 同步更新 DB ConfigValue
        await _sync_config_value(db, data)
        await db.commit()
        return {"message": "草稿已更新", "draft_id": existing.id}
    else:
        # 创建新草稿
        draft = ConfigDraft(
            series_id=data.series_id,
            batch_id=data.batch_id,
            change_type=data.change_type,
            item_id=data.item_id,
            model_id=data.model_id,
            field_name=data.field_name,
            new_value=data.new_value,
            old_value=data.old_value
        )
        db.add(draft)

        # 更新批次统计
        if data.change_type == "create":
            batch.create_count += 1
        elif data.change_type == "update":
            batch.update_count += 1
        elif data.change_type == "delete":
            batch.delete_count += 1
        batch.total_count += 1

        # 同步更新 DB ConfigValue
        await _sync_config_value(db, data)
        await db.commit()
        await db.refresh(draft)
        return {"message": "草稿已保存", "draft_id": draft.id}


async def _sync_config_value(db, data):
    """将草稿的 new_value 同步写入 DB ConfigValue"""
    if not data.field_name or data.field_name not in (
        "final_config", "current_config", "selection_config", "rd_status"
    ):
        return
    result = await db.execute(
        select(ConfigValue).where(
            ConfigValue.item_id == data.item_id,
            ConfigValue.model_id == data.model_id,
        )
    )
    cv = result.scalar_one_or_none()
    if cv:
        setattr(cv, data.field_name, data.new_value)
    else:
        # 无现有 ConfigValue → 创建
        cv = ConfigValue(
            item_id=data.item_id,
            model_id=data.model_id,
        )
        setattr(cv, data.field_name, data.new_value)
        db.add(cv)


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

    # 部分提交：根据 item_ids / model_ids 过滤要处理的草稿
    item_ids_filter = set(data.item_ids) if data.item_ids else None
    model_ids_filter = set(data.model_ids) if data.model_ids else None
    is_partial = bool(item_ids_filter or model_ids_filter)

    if model_ids_filter and not item_ids_filter:
        # 按机型过滤：model_id=None（旧数据/全局变更）则包含，否则按 model_id 匹配
        drafts = [
            d for d in all_drafts
            if d.model_id is None or d.model_id in model_ids_filter
        ]
    elif item_ids_filter and not model_ids_filter:
        # 按配置项过滤
        drafts = [d for d in all_drafts if d.item_id in item_ids_filter]
    elif item_ids_filter and model_ids_filter:
        # 同时按配置项和机型过滤：model_id=None 也包含
        drafts = [
            d for d in all_drafts
            if d.item_id in item_ids_filter and (d.model_id is None or d.model_id in model_ids_filter)
        ]
    else:
        drafts = all_drafts
    processed_count = len(drafts)

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
        delete_item_ids = [d.item_id for d in delete_drafts]
        models_in_series = await db.execute(
            select(ProductModel).where(ProductModel.series_id == batch.series_id)
        )
        series_model_ids = [m.id for m in models_in_series.scalars().all()]
        if series_model_ids:
            delete_values_result = await db.execute(
                select(ConfigValue).where(
                    ConfigValue.item_id.in_(delete_item_ids),
                    ConfigValue.model_id.in_(series_model_ids)
                )
            )
            for val in delete_values_result.scalars().all():
                val.final_config = None
                val.current_config = None
                val.selection_config = None
                val.rd_status = None

    # 删除已处理的草稿（部分提交时去除已提交项，全量提交时清除全部）
    for draft in drafts:
        await db.delete(draft)

    # 部分提交：更新批次统计
    if is_partial:
        remaining_result = await db.execute(
            select(ConfigDraft.change_type, func.count()).where(
                ConfigDraft.batch_id == batch_id
            ).group_by(ConfigDraft.change_type)
        )
        type_counts = dict(remaining_result.all())
        batch.create_count = type_counts.get("create", 0)
        batch.update_count = type_counts.get("update", 0)
        batch.delete_count = type_counts.get("delete", 0)
        batch.total_count = sum(type_counts.values())

    # 创建版本
    version_number = data.version_number
    if not version_number:
        last_version_result = await db.execute(
            select(ConfigVersion)
            .where(ConfigVersion.series_id == batch.series_id)
            .order_by(ConfigVersion.id.desc())
            .limit(1)
        )
        last_version = last_version_result.scalar_one_or_none()
        version_number = generate_next_version(last_version.version_number if last_version else None)

    # 获取当前数据创建快照
    models_result = await db.execute(
        select(ProductModel).where(ProductModel.series_id == batch.series_id)
    )
    models = models_result.scalars().all()
    model_ids = [m.id for m in models]

    items_result = await db.execute(select(ConfigItem).order_by(ConfigItem.row_index))
    items = items_result.scalars().all()

    values_result = await db.execute(
        select(ConfigValue).where(ConfigValue.model_id.in_(model_ids))
    )
    values = values_result.scalars().all()

    # 构建快照数据
    value_map = {}
    for v in values:
        if v.item_id not in value_map:
            value_map[v.item_id] = {}
        value_map[v.item_id][v.model_id] = {
            "current_config": v.current_config,
            "final_config": v.final_config,
            "selection_config": v.selection_config,
            "rd_status": v.rd_status
        }

    snapshot = {
        "models": [{"id": m.id, "name": m.name} for m in models],
        "items": [
            {
                "id": item.id,
                "category": item.category,
                "row_index": item.row_index,
                "rd_name": item.rd_name,
                "v_code": item.v_code,
                "ipn": item.ipn,
                "zh_desc": item.zh_desc,
                "en_desc": item.en_desc,
                "values": value_map.get(item.id, {})
            }
            for item in items
        ]
    }

    # 创建版本记录
    version = ConfigVersion(
        series_id=batch.series_id,
        version_number=version_number,
        version_name=data.version_name,
        description=data.description,
        snapshot_data=json.dumps(snapshot, ensure_ascii=False),
        row_count=len(items),
        published_by="system"
    )
    db.add(version)

    # 更新批次状态（部分提交后若还有剩余草稿则不标记为 submitted）
    remaining_count = batch.total_count  # 已重算
    if remaining_count == 0:
        batch.status = "submitted"
        batch.submitted_at = datetime.utcnow()
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
    db: AsyncSession = None
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
        delete_item_ids = [d.item_id for d in delete_drafts]
        models_in_series = await db.execute(
            select(ProductModel).where(ProductModel.series_id == batch.series_id)
        )
        series_model_ids = [m.id for m in models_in_series.scalars().all()]
        if series_model_ids:
            delete_values_result = await db.execute(
                select(ConfigValue).where(
                    ConfigValue.item_id.in_(delete_item_ids),
                    ConfigValue.model_id.in_(series_model_ids)
                )
            )
            for val in delete_values_result.scalars().all():
                val.final_config = None
                val.current_config = None
                val.selection_config = None
                val.rd_status = None

    # 删除所有草稿
    for draft in all_drafts:
        await db.delete(draft)

    # 生成版本号
    last_version_result = await db.execute(
        select(ConfigVersion)
        .where(ConfigVersion.series_id == batch.series_id)
        .order_by(ConfigVersion.id.desc())
        .limit(1)
    )
    last_version = last_version_result.scalar_one_or_none()

    if version_number:
        # 用户指定了版本号，检查是否与系列内已有版本号重复
        existing = await db.execute(
            select(ConfigVersion).where(
                ConfigVersion.series_id == batch.series_id,
                ConfigVersion.version_number == version_number
            ).limit(1)
        )
        if existing.scalar_one_or_none():
            return {
                "success": False,
                "message": f"版本号 {version_number} 在该系列中已存在"
            }
    else:
        version_number = generate_next_version(last_version.version_number if last_version else None)

    # 获取当前数据创建快照
    models_result = await db.execute(
        select(ProductModel).where(ProductModel.series_id == batch.series_id)
    )
    models = models_result.scalars().all()
    model_ids = [m.id for m in models]

    items_result = await db.execute(select(ConfigItem).order_by(ConfigItem.row_index))
    items = items_result.scalars().all()

    values_result = await db.execute(
        select(ConfigValue).where(ConfigValue.model_id.in_(model_ids))
    )
    values = values_result.scalars().all()

    # 构建快照数据
    value_map = {}
    for v in values:
        if v.item_id not in value_map:
            value_map[v.item_id] = {}
        value_map[v.item_id][v.model_id] = {
            "current_config": v.current_config,
            "final_config": v.final_config,
            "selection_config": v.selection_config,
            "rd_status": v.rd_status
        }

    snapshot = {
        "models": [{"id": m.id, "name": m.name} for m in models],
        "items": [
            {
                "id": item.id,
                "category": item.category,
                "row_index": item.row_index,
                "rd_name": item.rd_name,
                "v_code": item.v_code,
                "ipn": item.ipn,
                "zh_desc": item.zh_desc,
                "en_desc": item.en_desc,
                "values": value_map.get(item.id, {})
            }
            for item in items
        ]
    }

    # 创建版本记录
    version = ConfigVersion(
        series_id=batch.series_id,
        version_number=version_number,
        version_name=version_name,
        description=description,
        snapshot_data=json.dumps(snapshot, ensure_ascii=False),
        row_count=len(items),
        published_by="system"
    )
    db.add(version)

    # 更新批次状态
    batch.status = "submitted"
    batch.submitted_at = datetime.utcnow()
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

            series_id = batch.series_id

            # 查询该系列下所有机型
            models_result = await db.execute(
                select(ProductModel).where(ProductModel.series_id == series_id)
            )
            models = models_result.scalars().all()
            series_model_ids = [m.id for m in models]

            # 查询最后一个已提交的 ConfigVersion
            last_version_result = await db.execute(
                select(ConfigVersion)
                .where(ConfigVersion.series_id == series_id)
                .order_by(ConfigVersion.id.desc())
                .limit(1)
            )
            last_version = last_version_result.scalar_one_or_none()

            if last_version and last_version.snapshot_data:
                snapshot = json.loads(last_version.snapshot_data)

                if series_model_ids:
                    vals_to_del = await db.execute(
                        select(ConfigValue).where(ConfigValue.model_id.in_(series_model_ids))
                    )
                    for val in vals_to_del.scalars().all():
                        await db.delete(val)
                    await db.flush()

                # 用 IPN 匹配重建 ConfigValue（同 discard_draft_batch）
                db_items_result = await db.execute(select(ConfigItem))
                ipn_to_db_item = {}
                for item in db_items_result.scalars().all():
                    if item.ipn:
                        ipn_to_db_item[str(item.ipn).strip()] = item

                snapshot_ipns = set()
                for item_data in snapshot.get("items", []):
                    ipn = str(item_data.get("ipn", "")).strip() if item_data.get("ipn") else None
                    if not ipn:
                        continue
                    snapshot_ipns.add(ipn)
                    db_item = ipn_to_db_item.get(ipn)
                    if not db_item:
                        db_item = ConfigItem(
                            category=item_data.get("category"),
                            row_index=item_data.get("row_index"),
                            rd_name=item_data.get("rd_name"),
                            v_code=item_data.get("v_code"),
                            ipn=item_data.get("ipn"),
                            zh_desc=item_data.get("zh_desc"),
                            en_desc=item_data.get("en_desc"),
                        )
                        db.add(db_item)
                        await db.flush()
                        ipn_to_db_item[ipn] = db_item
                    for field in ("category", "rd_name", "v_code", "zh_desc", "en_desc", "row_index"):
                        snap_val = item_data.get(field)
                        if snap_val is not None:
                            setattr(db_item, field, snap_val)
                    for model_id_str, value_data in (item_data.get("values") or {}).items():
                        model_id = int(model_id_str)
                        if model_id not in series_model_ids:
                            continue
                        new_value = ConfigValue(
                            item_id=db_item.id,
                            model_id=model_id,
                            current_config=value_data.get("current_config"),
                            final_config=value_data.get("final_config"),
                            selection_config=value_data.get("selection_config"),
                            rd_status=value_data.get("rd_status")
                        )
                        db.add(new_value)

                # 清理快照中没有的 ConfigItem（未被其他系列引用才删）
                all_items = await db.execute(select(ConfigItem))
                for item in all_items.scalars().all():
                    item_ipn = str(item.ipn).strip() if item.ipn else None
                    if item_ipn and item_ipn in snapshot_ipns:
                        continue
                    remaining = await db.execute(
                        select(ConfigValue).where(ConfigValue.item_id == item.id).limit(1)
                    )
                    if not remaining.scalar_one_or_none():
                        await db.delete(item)
            else:
                if series_model_ids:
                    vals_to_del = await db.execute(
                        select(ConfigValue).where(ConfigValue.model_id.in_(series_model_ids))
                    )
                    for val in vals_to_del.scalars().all():
                        await db.delete(val)

                all_items = await db.execute(select(ConfigItem))
                for item in all_items.scalars().all():
                    remaining = await db.execute(
                        select(ConfigValue).where(ConfigValue.item_id == item.id).limit(1)
                    )
                    if not remaining.scalar_one_or_none():
                        await db.delete(item)

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

    await db.commit()

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
            result = await _process_single_batch_submit(
                batch_id=batch_id,
                description=data.description,
                version_name=data.version_name,
                version_number=data.version_number,
                db=db
            )
            if result["success"]:
                results.append(BatchSubmitResult(
                    batch_id=batch_id,
                    series_id=result["series_id"],
                    version_number=result["version_number"],
                    changes=result["changes"],
                    success=True,
                    message=result["message"]
                ))
            else:
                results.append(BatchSubmitResult(
                    batch_id=batch_id,
                    series_id=0,
                    version_number="",
                    changes=0,
                    success=False,
                    message=result["message"]
                ))
        except Exception as e:
            results.append(BatchSubmitResult(
                batch_id=batch_id,
                series_id=0,
                version_number="",
                changes=0,
                success=False,
                message=str(e)
            ))

    await db.commit()

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

        series_id = batch.series_id

        # 查询该系列下所有机型
        models_result = await db.execute(
            select(ProductModel).where(ProductModel.series_id == series_id)
        )
        models = models_result.scalars().all()
        series_model_ids = [m.id for m in models]

        # 查询该系列最后一个已提交的 ConfigVersion
        last_version_result = await db.execute(
            select(ConfigVersion)
            .where(ConfigVersion.series_id == series_id)
            .order_by(ConfigVersion.id.desc())
            .limit(1)
        )
        last_version = last_version_result.scalar_one_or_none()

        # 先删草稿（避免后续操作受 FK 约束影响）
        drafts_to_delete = await db.execute(
            select(ConfigDraft).where(ConfigDraft.batch_id == batch_id)
        )
        for draft in drafts_to_delete.scalars().all():
            await db.delete(draft)

        if last_version and last_version.snapshot_data:
            # 有快照：恢复到最近一次提交版本的状态
            snapshot = json.loads(last_version.snapshot_data)

            # 删除该系列所有机型的 ConfigValue
            if series_model_ids:
                delete_values = await db.execute(
                    select(ConfigValue).where(ConfigValue.model_id.in_(series_model_ids))
                )
                for val in delete_values.scalars().all():
                    await db.delete(val)
                await db.flush()  # 确保删除先提交，避免重建时 UNIQUE 约束冲突

            # 从快照重建 ConfigValue（用 IPN 匹配，不再依赖自增 ID）
            # 构建：当前 DB 中 IPN → ConfigItem 映射
            db_items_result = await db.execute(select(ConfigItem))
            ipn_to_db_item = {}
            for item in db_items_result.scalars().all():
                if item.ipn:
                    ipn_to_db_item[str(item.ipn).strip()] = item

            snapshot_ipns = set()
            for item_data in snapshot.get("items", []):
                ipn = str(item_data.get("ipn", "")).strip() if item_data.get("ipn") else None
                if not ipn:
                    continue
                snapshot_ipns.add(ipn)
                # 用 IPN 查找当前 DB 中对应的 ConfigItem
                db_item = ipn_to_db_item.get(ipn)
                if not db_item:
                    # DB 中不存在 → 从快照创建
                    db_item = ConfigItem(
                        category=item_data.get("category"),
                        row_index=item_data.get("row_index"),
                        rd_name=item_data.get("rd_name"),
                        v_code=item_data.get("v_code"),
                        ipn=item_data.get("ipn"),
                        zh_desc=item_data.get("zh_desc"),
                        en_desc=item_data.get("en_desc"),
                    )
                    db.add(db_item)
                    await db.flush()
                    ipn_to_db_item[ipn] = db_item

                db_item_id = db_item.id
                # 更新 ConfigItem 字段到快照版本
                for field in ("category", "rd_name", "v_code", "zh_desc", "en_desc", "row_index"):
                    snap_val = item_data.get(field)
                    if snap_val is not None:
                        setattr(db_item, field, snap_val)

                # 重建 ConfigValues
                values_map = item_data.get("values", {})
                for model_id_str, value_data in values_map.items():
                    model_id = int(model_id_str)
                    if model_id not in series_model_ids:
                        continue
                    new_value = ConfigValue(
                        item_id=db_item_id,
                        model_id=model_id,
                        current_config=value_data.get("current_config"),
                        final_config=value_data.get("final_config"),
                        selection_config=value_data.get("selection_config"),
                        rd_status=value_data.get("rd_status")
                    )
                    db.add(new_value)

            # 清理 DB 中存在但快照中没有的 ConfigItem（未被其他系列引用才删）
            all_items = await db.execute(select(ConfigItem))
            for item in all_items.scalars().all():
                item_ipn = str(item.ipn).strip() if item.ipn else None
                if item_ipn and item_ipn in snapshot_ipns:
                    continue  # 在快照中，保留
                # 不在快照中 → 检查是否被其他系列引用
                remaining = await db.execute(
                    select(ConfigValue).where(ConfigValue.item_id == item.id).limit(1)
                )
                if not remaining.scalar_one_or_none():
                    await db.delete(item)
        else:
            # 没有快照（从未提交过版本）：删除该系列所有相关数据
            if series_model_ids:
                values_to_delete = await db.execute(
                    select(ConfigValue).where(ConfigValue.model_id.in_(series_model_ids))
                )
                for val in values_to_delete.scalars().all():
                    await db.delete(val)

            # 删除所有没有其他系列引用的 ConfigItem
            all_items = await db.execute(select(ConfigItem))
            for item in all_items.scalars().all():
                remaining = await db.execute(
                    select(ConfigValue).where(ConfigValue.item_id == item.id).limit(1)
                )
                if not remaining.scalar_one_or_none():
                    await db.delete(item)

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

    # 更新批次统计
    batch_result = await db.execute(select(DraftBatch).where(DraftBatch.id == draft.batch_id))
    batch = batch_result.scalar_one_or_none()

    if batch:
        if draft.change_type == "create":
            batch.create_count = max(0, batch.create_count - 1)
        elif draft.change_type == "update":
            batch.update_count = max(0, batch.update_count - 1)
        elif draft.change_type == "delete":
            batch.delete_count = max(0, batch.delete_count - 1)
        batch.total_count = max(0, batch.total_count - 1)

    await db.delete(draft)
    await db.commit()

    return {"message": "删除成功"}


@router.delete("/draft/by-key")
async def delete_draft_by_key(
    batch_id: str,
    item_id: int,
    model_id: int,
    field_name: str,
    db: AsyncSession = Depends(get_db)
):
    """根据条件删除草稿"""
    result = await db.execute(
        select(ConfigDraft).where(
            ConfigDraft.batch_id == batch_id,
            ConfigDraft.item_id == item_id,
            ConfigDraft.model_id == model_id,
            ConfigDraft.field_name == field_name
        )
    )
    draft = result.scalar_one_or_none()

    if not draft:
        return {"message": "草稿不存在", "deleted": False}

    # 更新批次统计
    batch_result = await db.execute(select(DraftBatch).where(DraftBatch.id == draft.batch_id))
    batch = batch_result.scalar_one_or_none()

    if batch:
        if draft.change_type == "create":
            batch.create_count = max(0, batch.create_count - 1)
        elif draft.change_type == "update":
            batch.update_count = max(0, batch.update_count - 1)
        elif draft.change_type == "delete":
            batch.delete_count = max(0, batch.delete_count - 1)
        batch.total_count = max(0, batch.total_count - 1)

    await db.delete(draft)
    await db.commit()

    return {"message": "删除成功", "deleted": True}
"""
导入导出 API
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from pydantic import BaseModel
import io
import json
from pathlib import Path


class ExportRequest(BaseModel):
    """导出请求参数"""
    series_id: int
    include_main_unit: bool = False
    item_ids: Optional[str] = None
    categories: Optional[str] = None
    search: Optional[str] = None
    model_ids: Optional[str] = None
    visible_fields: Optional[str] = None
    draft_changes: Optional[str] = None
    deleted_items: Optional[str] = None
    new_items: Optional[str] = None
import uuid
from datetime import datetime
from urllib.parse import quote

from app.database import get_db
from app.models import (
    ProductSeries, ProductModel, ConfigItem, ConfigValue,
    DraftBatch, ConfigDraft, ImportHistory, ConfigVersion
)
import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.comments import Comment

from app.services.config_workbook import (
    CONFIG_FIELDS,
    config_item_fingerprint,
    load_config_workbook,
    merged_cell_starts,
    parse_config_categories,
    parse_config_rows,
    parse_workbook_structure,
    read_patch_metadata,
    workbook_import_mode,
    write_patch_metadata,
)
from app.services.model_identity import (
    active_model_filter,
    model_identity_metadata,
    normalize_snapshot,
    parse_model_header,
    resolve_import_model,
    resolve_import_model_readonly,
)
from app.services.config_history import resolve_snapshot_item

router = APIRouter()


def parse_merged_cells(ws):
    """解析合并单元格信息，返回每个合并区域的起始单元格值"""
    return merged_cell_starts(ws)


async def _load_unique_existing_items(db: AsyncSession, rows: list[dict]) -> dict[str, ConfigItem]:
    """Load IPN identities without silently choosing between duplicate database rows."""
    ipns = {row["ipn"] for row in rows if row["ipn"]}
    if not ipns:
        return {}
    result = await db.execute(select(ConfigItem).where(func.trim(ConfigItem.ipn).in_(ipns)))
    items_by_ipn: dict[str, list[ConfigItem]] = {}
    for item in result.scalars().all():
        normalized_ipn = str(item.ipn).strip()
        items_by_ipn.setdefault(normalized_ipn, []).append(item)
    ambiguous = next(
        ((ipn, items) for ipn, items in items_by_ipn.items() if len(items) > 1),
        None,
    )
    if ambiguous:
        ipn, items = ambiguous
        raise HTTPException(
            status_code=400,
            detail=f"IPN {ipn} 在数据库中对应 {len(items)} 条配置项，无法安全导入",
        )
    return {ipn: items[0] for ipn, items in items_by_ipn.items()}


async def _validate_patch_scope_readonly(
    db: AsyncSession,
    structure,
    rows: list[dict],
    patch_metadata: dict | None,
) -> None:
    """Apply patch series, model, field, and item identity checks without writes."""
    if patch_metadata is None:
        return

    resolved_model_ids = []
    for series_info, parsed_models in structure:
        series = await db.scalar(
            select(ProductSeries).where(ProductSeries.name == series_info.name)
        )
        if series is None or patch_metadata["series_id"] != series.id:
            raise HTTPException(status_code=400, detail="补丁工作簿与目标产品系列不一致")
        for index, model_columns in enumerate(parsed_models):
            try:
                model = await resolve_import_model_readonly(
                    db,
                    series.id,
                    model_columns.raw_header,
                )
            except ValueError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
            expected_ids = patch_metadata["model_ids"]
            expected_id = expected_ids[index] if index < len(expected_ids) else None
            if model is None or model.id != expected_id:
                raise HTTPException(
                    status_code=400,
                    detail="补丁工作簿机型范围已改变，请重新导出后再导入",
                )
            if set(model_columns.field_columns) != set(patch_metadata["fields"]):
                raise HTTPException(
                    status_code=400,
                    detail="补丁工作簿字段范围已改变，请重新导出后再导入",
                )
            resolved_model_ids.append(model.id)

    if resolved_model_ids != patch_metadata["model_ids"]:
        raise HTTPException(
            status_code=400,
            detail="补丁工作簿机型范围已改变，请重新导出后再导入",
        )

    refs = patch_metadata["item_refs"]
    ref_ids = {ref["id"] for ref in refs.values()}
    referenced_items = {}
    if ref_ids:
        result = await db.execute(select(ConfigItem).where(ConfigItem.id.in_(ref_ids)))
        referenced_items = {item.id: item for item in result.scalars().all()}
    for row_idx, ref in refs.items():
        item = referenced_items.get(ref["id"])
        if item is None or config_item_fingerprint(item) != ref["fingerprint"]:
            raise HTTPException(
                status_code=400,
                detail=f"第 {row_idx} 行配置项身份已失效，请重新导出后再导入",
            )
    for row in rows:
        ref = refs.get(row["row_idx"])
        if ref and config_item_fingerprint(row) != ref["fingerprint"]:
            raise HTTPException(
                status_code=400,
                detail=f"第 {row['row_idx']} 行配置项身份与导出记录不一致",
            )


@router.post("/import")
async def import_excel(
    file: UploadFile = File(...),
    series_name: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    导入Excel文件

    Excel结构：
    - 第1行：产品系列（合并单元格）
    - 第2行：产品型号（合并单元格，每个型号跨4列）
    - 第3行：配置状态（最终配置、当前配置、选型类别、研发状态）
    - 第4行：分类标题行（如 Main Unit）
    - 第5行开始：配置数据行

    A-E列固定：研发名称、V代码、IPN号、中文描述、英文描述
    """
    if not (file.filename or '').casefold().endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="只支持Excel文件(.xlsx, .xls)")

    # 读取文件
    content = await file.read()
    try:
        wb = load_config_workbook(content, file.filename)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    ws = wb.active
    try:
        import_mode = workbook_import_mode(wb)
        patch_metadata = read_patch_metadata(wb)
        merged_info = parse_merged_cells(ws)
        structure = parse_workbook_structure(
            ws,
            fallback_name=series_name or Path(file.filename).stem,
            merged_info=merged_info,
        )
        parsed_rows = parse_config_rows(ws)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    validated_existing_items = await _load_unique_existing_items(db, parsed_rows)
    await _validate_patch_scope_readonly(db, structure, parsed_rows, patch_metadata)

    results = []
    change_log = []  # 变更记录

    try:
        for series_info, parsed_models in structure:
            current_series_name = series_info.name

            # 创建或获取产品系列
            series_result = await db.execute(
                select(ProductSeries).where(ProductSeries.name == current_series_name)
            )
            series = series_result.scalar_one_or_none()

            if not series:
                series = ProductSeries(name=current_series_name)
                db.add(series)
                await db.flush()
            if patch_metadata and patch_metadata["series_id"] != series.id:
                raise HTTPException(status_code=400, detail="补丁工作簿与目标产品系列不一致")

            # 解析产品型号和第3行字段标签，非连续系列范围保持独立。
            models = []
            model_fields = {}
            model_allows_pair_delete = {}
            for model_columns in parsed_models:
                try:
                    model = None
                    if import_mode == "patch":
                        model = await resolve_import_model_readonly(
                            db, series.id, model_columns.raw_header
                        )
                        expected_ids = patch_metadata["model_ids"]
                        expected_id = (
                            expected_ids[len(models)]
                            if len(models) < len(expected_ids)
                            else None
                        )
                        if model is None or model.id != expected_id:
                            raise HTTPException(
                                status_code=400,
                                detail="补丁工作簿机型范围已改变，请重新导出后再导入",
                            )
                        if set(model_columns.field_columns) != set(patch_metadata["fields"]):
                            raise HTTPException(
                                status_code=400,
                                detail="补丁工作簿字段范围已改变，请重新导出后再导入",
                            )
                    else:
                        model = await resolve_import_model(
                            db,
                            series.id,
                            model_columns.raw_header,
                            model_columns.start,
                            model_columns.end,
                            len(models),
                        )
                except ValueError as error:
                    raise HTTPException(status_code=400, detail=str(error)) from error
                if model.id in {entry.id for entry in models}:
                    raise HTTPException(status_code=400, detail=f"机型 {model.name} 在同一系列的文件中出现多次")
                models.append(model)
                model_fields[model.id] = model_columns.field_columns
                model_allows_pair_delete[model.id] = model_columns.supports_pair_deletion
            if patch_metadata and [model.id for model in models] != patch_metadata["model_ids"]:
                raise HTTPException(
                    status_code=400,
                    detail="补丁工作簿机型范围已改变，请重新导出后再导入",
                )

            # 获取最后发布的版本快照（用于对照变更）
            last_version_result = await db.execute(
                select(ConfigVersion)
                .where(ConfigVersion.series_id == series.id)
                .order_by(ConfigVersion.id.desc())
                .limit(1)
            )
            last_version = last_version_result.scalar_one_or_none()
            # 用IPN索引快照数据（回滚会重建ConfigItem导致ID变化，IPN是稳定标识）
            snapshot_raw_data = None
            # 预计算快照值字典：{(ipn_str, 型号名称, 字段名): value}，O(1) 查询
            snapshot_values = {}
            snapshot_no_ipn_values = {}
            # 快照中的 (IPN, 型号名称) 对集合，用于判定新增/删除/修改
            snapshot_pairs = set()
            snapshot_no_ipn_pairs = set()
            snapshot_model_name_map = {}
            if last_version and last_version.snapshot_data:
                snapshot_raw_data = await normalize_snapshot(db, series.id, json.loads(last_version.snapshot_data))
                # 构建快照中型号ID→名称映射（回滚后model_id也会变，需用名称匹配）
                for m in snapshot_raw_data.get("models", []):
                    mid = m.get("id")
                    if mid:
                        snapshot_model_name_map[mid] = m.get("name")

                for item_entry in snapshot_raw_data.get("items", []):
                    # 与 Excel 解析保持一致，跳过 Main Unit 类别的项
                    if item_entry.get("category") == "Main Unit":
                        continue
                    ipn = item_entry.get("ipn")
                    if not ipn:
                        continue
                    ipn_str = str(ipn).strip()
                    for snap_model_id_str, model_vals in item_entry.get("values", {}).items():
                        snap_model_name = snapshot_model_name_map.get(int(snap_model_id_str))
                        if not snap_model_name:
                            continue
                        snapshot_pairs.add((ipn_str, snap_model_name))
                        for field in ("final_config", "current_config", "selection_config", "rd_status"):
                            val = model_vals.get(field) if model_vals else None
                            snapshot_values[(ipn_str, snap_model_name, field)] = val

            # 计算快照中所有字段均为 N/A 值的配对 —— 这些应视为"新增"而非"修改"
            NA_VALUES = {'N/A', '', None, '-', 'None', 'null', '未定义'}

            def normalize_import_value(value):
                if value is None:
                    return None
                normalized = str(value).strip()
                if not normalized:
                    return None
                if import_mode == "patch" and normalized in NA_VALUES:
                    return None
                return normalized

            snapshot_all_na_pairs = set()
            snapshot_no_ipn_all_na_pairs = set()
            for ipn_str, snap_model_name in snapshot_pairs:
                all_na = all(
                    snapshot_values.get((ipn_str, snap_model_name, f)) in NA_VALUES
                    for f in ("final_config", "current_config", "selection_config", "rd_status")
                )
                if all_na:
                    snapshot_all_na_pairs.add((ipn_str, snap_model_name))

            # Resolve every current no-IPN item through the canonical snapshot rules.
            # This supplies safe identities for full-sync reuse and omission detection.
            resolved_no_ipn_items = {}
            no_ipn_items_by_import_identity = {}
            if snapshot_raw_data and models:
                current_items_result = await db.execute(
                    select(ConfigItem)
                    .join(ConfigValue, ConfigValue.item_id == ConfigItem.id)
                    .where(ConfigValue.model_id.in_([model.id for model in models]))
                    .distinct()
                )
                for current_item in current_items_result.scalars().all():
                    if current_item.ipn:
                        continue
                    try:
                        snapshot_item = resolve_snapshot_item(
                            current_item, snapshot_raw_data
                        )
                    except ValueError as error:
                        raise HTTPException(status_code=400, detail=str(error)) from error
                    if not snapshot_item:
                        continue
                    resolved_no_ipn_items[current_item.id] = current_item
                    identity = (
                        snapshot_item.get("category"),
                        snapshot_item.get("row_index"),
                        snapshot_item.get("rd_name"),
                        snapshot_item.get("v_code"),
                    )
                    if identity in no_ipn_items_by_import_identity:
                        raise HTTPException(
                            status_code=400,
                            detail="发布快照中无 IPN 配置项身份不唯一",
                        )
                    no_ipn_items_by_import_identity[identity] = current_item
                    for snapshot_model_id, model_values in (
                        snapshot_item.get("values") or {}
                    ).items():
                        model_name = snapshot_model_name_map.get(int(snapshot_model_id))
                        if not model_name:
                            continue
                        pair = (current_item.id, model_name)
                        snapshot_no_ipn_pairs.add(pair)
                        for field in CONFIG_FIELDS:
                            snapshot_no_ipn_values[
                                (current_item.id, model_name, field)
                            ] = model_values.get(field) if model_values else None
                        if all(
                            snapshot_no_ipn_values.get(
                                (current_item.id, model_name, field)
                            ) in NA_VALUES
                            for field in CONFIG_FIELDS
                        ):
                            snapshot_no_ipn_all_na_pairs.add(pair)

            # 解析配置数据（从第5行开始）
            items_created = 0
            values_created = 0

            # 批量收集待创建的配置项和配置值
            items_to_create = parsed_rows

            # 已在任何写入前验证 IPN 在数据库中只对应一个配置项。
            existing_items_map = dict(validated_existing_items)
            patch_items_by_row = {}
            if patch_metadata:
                refs = patch_metadata["item_refs"]
                ref_ids = {ref["id"] for ref in refs.values()}
                referenced_items = {}
                if ref_ids:
                    rows = await db.execute(select(ConfigItem).where(ConfigItem.id.in_(ref_ids)))
                    referenced_items = {item.id: item for item in rows.scalars().all()}
                for row_idx, ref in refs.items():
                    item = referenced_items.get(ref["id"])
                    if item is None or config_item_fingerprint(item) != ref["fingerprint"]:
                        raise HTTPException(
                            status_code=400,
                            detail=f"第 {row_idx} 行配置项身份已失效，请重新导出后再导入",
                        )
                    patch_items_by_row[row_idx] = item
                for item_data in items_to_create:
                    ref = refs.get(item_data["row_idx"])
                    if ref and config_item_fingerprint(item_data) != ref["fingerprint"]:
                        raise HTTPException(
                            status_code=400,
                            detail=f"第 {item_data['row_idx']} 行配置项身份与导出记录不一致",
                        )

            # 批量创建配置项
            created_items = []
            changes = []  # 记录该系列的变更
            draft_changes = []  # 记录草稿级变更（用于创建 ConfigDraft）
            processed_ipns = {}  # 跟踪本次导入已处理的 IPN，避免同文件内重复

            for item_data in items_to_create:
                ipn_str = item_data['ipn']
                change_type = None
                patch_item = patch_items_by_row.get(item_data["row_idx"])
                no_ipn_snapshot_item = None
                if not ipn_str and patch_item is None:
                    no_ipn_snapshot_item = no_ipn_items_by_import_identity.get(
                        (
                            item_data["category"],
                            item_data["row_idx"],
                            item_data["rd_name"],
                            item_data["v_code"],
                        )
                    )

                # 检查是否已存在（数据库中或本次导入中）
                if patch_item is not None or no_ipn_snapshot_item is not None or (
                    ipn_str and (ipn_str in existing_items_map or ipn_str in processed_ipns)
                ):
                    # 优先使用数据库中已存在的，否则使用本次导入创建的
                    if patch_item is not None:
                        item = patch_item
                    elif no_ipn_snapshot_item is not None:
                        item = no_ipn_snapshot_item
                    elif ipn_str in existing_items_map:
                        item = existing_items_map[ipn_str]
                    else:
                        item = processed_ipns[ipn_str]
                        # 跳过重复项的处理，直接添加配置值
                        created_items.append({"item": item, "data": item_data, "change_type": change_type})
                        continue

                    # 检查是否有字段变化
                    has_changes = (
                        item.rd_name != item_data['rd_name'] or
                        item.v_code != item_data['v_code'] or
                        item.zh_desc != item_data['zh_desc'] or
                        item.en_desc != item_data['en_desc'] or
                        item.category != item_data['category']
                    )
                    if has_changes:
                        change_type = "update"
                        changes.append({
                            "type": "update",
                            "item_id": item.id,
                            "ipn": ipn_str,
                            "rd_name": item_data['rd_name'],
                            "message": f"更新配置项: {item_data['rd_name']} ({ipn_str})"
                        })
                    # 更新现有记录的字段
                    item.rd_name = item_data['rd_name']
                    item.v_code = item_data['v_code']
                    item.zh_desc = item_data['zh_desc']
                    item.en_desc = item_data['en_desc']
                    if import_mode != "patch":
                        item.row_index = item_data['row_idx']
                    item.category = item_data['category']
                else:
                    # 创建新的配置项
                    change_type = "create"
                    item = ConfigItem(
                        category=item_data['category'],
                        row_index=item_data['row_idx'],
                        rd_name=item_data['rd_name'],
                        v_code=item_data['v_code'],
                        ipn=item_data['ipn'],
                        zh_desc=item_data['zh_desc'],
                        en_desc=item_data['en_desc']
                    )
                    db.add(item)
                    # 记录到已处理字典中
                    if ipn_str:
                        existing_items_map[ipn_str] = item
                        processed_ipns[ipn_str] = item

                created_items.append({"item": item, "data": item_data, "change_type": change_type})
                items_created += 1

            # 批量 flush 以获取所有 item.id
            await db.flush()

            # 将新建的配置项记录到 changes 中（用于后续创建草稿）
            for item_info in created_items:
                if item_info["change_type"] == "create" and item_info["item"].id:
                    changes.append({
                        "type": "create",
                        "item_id": item_info["item"].id,
                        "ipn": item_info["data"].get("ipn"),
                        "rd_name": item_info["data"].get("rd_name"),
                        "message": f"新建配置项: {item_info['data'].get('rd_name')} ({item_info['data'].get('ipn') or '无IPN'})"
                    })

            # 无 IPN 项通过共享快照身份解析器定位发布基线，避免 recycled ID 误配。
            if snapshot_raw_data:
                for item_info in created_items:
                    item = item_info["item"]
                    if item.ipn:
                        continue
                    try:
                        snapshot_item = resolve_snapshot_item(item, snapshot_raw_data)
                    except ValueError as error:
                        raise HTTPException(status_code=400, detail=str(error)) from error
                    if not snapshot_item:
                        continue
                    for snapshot_model_id, model_values in (
                        snapshot_item.get("values") or {}
                    ).items():
                        model_name = snapshot_model_name_map.get(int(snapshot_model_id))
                        if not model_name:
                            continue
                        pair = (item.id, model_name)
                        snapshot_no_ipn_pairs.add(pair)
                        for field in CONFIG_FIELDS:
                            snapshot_no_ipn_values[(item.id, model_name, field)] = (
                                model_values.get(field) if model_values else None
                            )
                        if all(
                            snapshot_no_ipn_values.get((item.id, model_name, field))
                            in NA_VALUES
                            for field in CONFIG_FIELDS
                        ):
                            snapshot_no_ipn_all_na_pairs.add(pair)

            # 批量查询已存在的 ConfigValue（按 item_id + model_id）
            item_ids = [item_info["item"].id for item_info in created_items if item_info["item"].id]
            model_ids = [m.id for m in models if m.id]
            existing_values_map = {}

            # 首先查询数据库中已存在的配置值
            if item_ids and model_ids:
                existing_values_result = await db.execute(
                    select(ConfigValue).where(
                        ConfigValue.item_id.in_(item_ids),
                        ConfigValue.model_id.in_(model_ids)
                    )
                )
                for val in existing_values_result.scalars().all():
                    existing_values_map[(val.item_id, val.model_id)] = val

            # 批量创建配置值 - 使用字典避免重复
            values_to_create = {}  # key: (item_id, model_id), value: ConfigValue
            excel_pairs = set()  # 跟踪Excel中所有 (IPN, 型号名) 对
            excel_no_ipn_pairs = set()
            touched_field_keys = set()
            touched_pair_ids = set()
            authoritative_pair_ids = set()
            excluded_pair_ids = (
                patch_metadata["excluded_pairs"] if patch_metadata else set()
            )

            for item_info in created_items:
                item = item_info["item"]
                item_data = item_info["data"]
                item_ipn = str(item.ipn).strip() if item and item.ipn else None

                for model in models:
                    if (item.id, model.id) in excluded_pair_ids:
                        continue
                    imported_values = {
                        field_name: ws.cell(
                            row=item_data['row_idx'],
                            column=column,
                        ).value
                        for field_name, column in model_fields[model.id].items()
                    }
                    touched_pair_ids.add((item.id, model.id))
                    if model_allows_pair_delete.get(model.id, False):
                        authoritative_pair_ids.add((item.id, model.id))
                    touched_field_keys.update(
                        (item.id, model.id, field_name)
                        for field_name in imported_values
                    )

                    # 追踪Excel中的 (IPN, 型号名) 对
                    # 部分字段工作簿不能据此推断整项删除；已有配对始终视为仍存在。
                    pair_key = (item_ipn, model.name) if item_ipn else None
                    no_ipn_pair_key = (item.id, model.name) if not item_ipn else None
                    excel_values = [
                        str(value).strip() if value is not None else None
                        for value in imported_values.values()
                    ]
                    has_meaningful = any(v and v not in NA_VALUES for v in excel_values)
                    if pair_key:
                        if has_meaningful or (
                            pair_key in snapshot_pairs
                            and not model_allows_pair_delete[model.id]
                        ):
                            excel_pairs.add(pair_key)
                    elif has_meaningful or (
                        no_ipn_pair_key in snapshot_no_ipn_pairs
                        and not model_allows_pair_delete[model.id]
                    ):
                        excel_no_ipn_pairs.add(no_ipn_pair_key)

                    key = (item.id, model.id)
                    if key in existing_values_map:
                        val = existing_values_map[key]
                        for field_name, excel_value in imported_values.items():
                            new_val = normalize_import_value(excel_value)
                            # 如果该 (IPN, 型号) 对在快照中不存在，则不创建"修改"草稿
                            # 该对会由下面的"新增"逻辑处理
                            if pair_key and pair_key not in snapshot_pairs:
                                # 注意：仍要更新ConfigValue（不跳过），仅跳过草稿创建
                                pass
                            # 快照中该配对4字段全为N/A：更新ConfigValue但不产生修改草稿（归类为"新增"）
                            has_snapshot_pair = (
                                pair_key in snapshot_pairs
                                if pair_key
                                else no_ipn_pair_key in snapshot_no_ipn_pairs
                            )
                            snapshot_pair_is_empty = (
                                pair_key in snapshot_all_na_pairs
                                if pair_key
                                else no_ipn_pair_key in snapshot_no_ipn_all_na_pairs
                            )
                            skip_draft = not has_snapshot_pair or snapshot_pair_is_empty
                            # Patch 中的 N/A 占位符与已有空值语义相同，不改写原始表示。
                            if normalize_import_value(getattr(val, field_name)) != new_val:
                                setattr(val, field_name, new_val)
                            if skip_draft:
                                continue
                            # 快照对比仅用于决定是否产生草稿
                            snap_val = (
                                snapshot_values.get((item_ipn, model.name, field_name))
                                if item_ipn
                                else snapshot_no_ipn_values.get(
                                    (item.id, model.name, field_name)
                                )
                            )
                            snap_val_str = normalize_import_value(snap_val)
                            if snap_val_str != new_val:
                                draft_changes.append({
                                    "change_type": "update",
                                    "item_id": item.id,
                                    "model_id": model.id,
                                    "field_name": field_name,
                                    "old_value": snap_val_str,
                                    "new_value": new_val,
                                    "rd_name": item_data.get('rd_name'),
                                })
                    elif key not in values_to_create:
                        # 创建新的配置值
                        value = ConfigValue(
                            item_id=item.id,
                            model_id=model.id,
                            **{
                                field_name: normalize_import_value(excel_value)
                                for field_name, excel_value in imported_values.items()
                            },
                        )
                        for field_name, excel_value in imported_values.items():
                            new_val = normalize_import_value(excel_value)
                            has_snapshot_pair = (
                                pair_key in snapshot_pairs
                                if pair_key
                                else no_ipn_pair_key in snapshot_no_ipn_pairs
                            )
                            snapshot_pair_is_empty = (
                                pair_key in snapshot_all_na_pairs
                                if pair_key
                                else no_ipn_pair_key in snapshot_no_ipn_all_na_pairs
                            )
                            if not has_snapshot_pair or snapshot_pair_is_empty:
                                continue
                            # 从预计算快照值字典O(1)取值
                            snap_val = (
                                snapshot_values.get((item_ipn, model.name, field_name))
                                if item_ipn
                                else snapshot_no_ipn_values.get(
                                    (item.id, model.name, field_name)
                                )
                            )
                            old_val_str = normalize_import_value(snap_val)
                            if old_val_str == new_val:
                                continue  # 快照值和Excel值相同，不创建草稿
                            draft_changes.append({
                                "change_type": "update",
                                "item_id": item.id,
                                "model_id": model.id,
                                "field_name": field_name,
                                "old_value": old_val_str,
                                "new_value": new_val,
                                "rd_name": item_data.get('rd_name'),
                            })
                        values_to_create[key] = value
                        values_created += 1

            # 批量添加新配置值
            for value in values_to_create.values():
                db.add(value)

            # 记录导入历史
            history = ImportHistory(
                series_id=series.id,
                filename=file.filename,
                records_count=items_created,
                status="success"
            )
            db.add(history)

            results.append({
                "series": current_series_name,
                "models": len(models),
                "items": items_created,
                "values": values_created,
                "changes": changes
            })
            change_log.extend(changes)

            # 构建 item_id → item 映射（用于后续查询）
            all_items_by_id = {}
            for item in existing_items_map.values():
                if item and item.id:
                    all_items_by_id[item.id] = item
            for item in processed_ipns.values():
                if item and item.id:
                    all_items_by_id[item.id] = item
            for item_info in created_items:
                item = item_info["item"]
                if item and item.id:
                    all_items_by_id[item.id] = item

            # 保存 Excel 中原有的型号列表（用于删除检测，不包含 DB 补充的）
            excel_models = list(models)

            # 补充该系列所有型号到 models 列表和 excel_pairs
            # 确保后续变更检测覆盖该系列所有型号，而不是仅限于当前文件列范围
            series_models_from_db = await db.execute(
                select(ProductModel).where(active_model_filter()).where(ProductModel.series_id == series.id)
            )
            series_model_names = {m.name for m in models}
            for m in series_models_from_db.scalars().all():
                if m.name not in series_model_names:
                    models.append(m)
            # 注意：不补充已有ConfigValue配对到excel_pairs
            # excel_pairs 必须仅包含 Excel 中实际有意义的配对（含于第436-448行的NA过滤）
            # 否则全N/A的配对被误加入 excel_pairs 会变成"新增"

            # 创建草稿批次和草稿记录（用于前端展示变更）
            real_create_pairs = (excel_pairs - snapshot_pairs) | (excel_pairs & snapshot_all_na_pairs)
            real_no_ipn_create_pairs = (
                (excel_no_ipn_pairs - snapshot_no_ipn_pairs)
                | (excel_no_ipn_pairs & snapshot_no_ipn_all_na_pairs)
            )
            deletable_model_names = {
                model.name
                for model in excel_models
                if model_allows_pair_delete.get(model.id, False)
            }
            real_delete_pairs = set()
            real_no_ipn_delete_pairs = set()
            if import_mode == "full":
                real_delete_pairs = {
                    pair
                    for pair in (snapshot_pairs - excel_pairs) - snapshot_all_na_pairs
                    if pair[1] in deletable_model_names
                }
                real_no_ipn_delete_pairs = {
                    pair
                    for pair in (
                        (snapshot_no_ipn_pairs - excel_no_ipn_pairs)
                        - snapshot_no_ipn_all_na_pairs
                    )
                    if pair[1] in deletable_model_names
                }
            need_draft = (
                bool(draft_changes)
                or bool(real_create_pairs)
                or bool(real_delete_pairs)
                or bool(real_no_ipn_create_pairs)
                or bool(real_no_ipn_delete_pairs)
            )
            draft_result = await db.execute(
                select(DraftBatch).where(
                    DraftBatch.series_id == series.id,
                    DraftBatch.status == "draft"
                ).order_by(DraftBatch.created_at.desc()).limit(1)
            )
            draft_batch = draft_result.scalar_one_or_none()
            if need_draft or draft_batch is not None:

                if not draft_batch:
                    draft_batch = DraftBatch(
                        id=str(uuid.uuid4()),
                        series_id=series.id,
                        filename=file.filename,
                        status="draft",
                        total_count=0,
                        create_count=0,
                        update_count=0,
                        delete_count=0
                    )
                    db.add(draft_batch)
                    # 新增批次，无需清除草稿
                    batch_is_new = True
                else:
                    batch_is_new = False
                    # 确保计数不为 None（新创建的 DraftBatch 有 default=0，但从数据库加载的可能为 NULL）
                    if draft_batch.total_count is None:
                        draft_batch.total_count = 0
                    if draft_batch.create_count is None:
                        draft_batch.create_count = 0
                    if draft_batch.update_count is None:
                        draft_batch.update_count = 0
                    if draft_batch.delete_count is None:
                        draft_batch.delete_count = 0

                # 非新增批次：保留旧草稿，导入产生的新变更去重后追加
                existing_drafts_by_key = {}  # (change_type, item_id, model_id, field_name) -> draft
                if not batch_is_new:
                    old_drafts = await db.execute(
                        select(ConfigDraft).where(ConfigDraft.batch_id == draft_batch.id)
                    )
                    for d in old_drafts.scalars().all():
                        existing_drafts_by_key[
                            (d.change_type, d.item_id, d.model_id, d.field_name)
                        ] = d

                # === 先筛选draft_changes：将"Excel全N/A但快照有有效值"的配对转为删除 ===
                # 必须在创建DB草稿之前完成，避免update草稿和delete草稿同时存在
                update_to_delete = set()  # (item_id, model_id) 转为删除的项
                converted_to_delete_pairs = set()  # (ipn, model_name)，避免 deleted_pairs 重复

                # 构建 item_id→ipn, model_id→name 映射
                item_id_to_ipn = {}
                for item in all_items_by_id.values():
                    if item and item.ipn:
                        item_id_to_ipn[item.id] = str(item.ipn).strip()
                model_id_to_name = {}
                for m in models:
                    if m.id:
                        model_id_to_name[m.id] = m.name

                # 按(item_id, model_id)分组
                groups = {}
                for entry in draft_changes:
                    key = (entry['item_id'], entry['model_id'])
                    if key not in groups:
                        groups[key] = []
                    groups[key].append(entry)

                filtered_changes = []
                for key, entries in groups.items():
                    item_id, model_id = key
                    ipn = item_id_to_ipn.get(item_id)
                    model_name = model_id_to_name.get(model_id)
                    pair_key = (ipn, model_name) if ipn and model_name else None

                    # 该配对应转为删除的判断：
                    # 快照中有有效值 且 Excel全为N/A（不在excel_pairs） 且 快照不全为N/A
                    should_be_delete = (
                        import_mode == "full" and
                        pair_key and
                        pair_key in snapshot_pairs and
                        pair_key not in excel_pairs and
                        pair_key not in snapshot_all_na_pairs and
                        model_allows_pair_delete.get(model_id, False)
                    )
                    if should_be_delete:
                        update_to_delete.add(key)
                        converted_to_delete_pairs.add(pair_key)
                        continue
                    filtered_changes.extend(entries)

                draft_changes = filtered_changes

                # 以本次工作簿触及的字段/配对为边界，对现有草稿做替换式协调。
                # 未触及字段继续保留；同一字段最初的 old_value 始终保留。
                desired_updates = {
                    ("update", entry["item_id"], entry["model_id"], entry["field_name"]): entry
                    for entry in draft_changes
                }
                models_by_name = {m.name: m for m in models}
                pairs_to_create = (excel_pairs - snapshot_pairs) | (
                    excel_pairs & snapshot_all_na_pairs
                )
                desired_pair_types = {
                    (pair_item.id, models_by_name[pair_model_name].id): "create"
                    for pair_ipn, pair_model_name in pairs_to_create
                    if (pair_item := (
                        existing_items_map.get(pair_ipn)
                        or processed_ipns.get(pair_ipn)
                    )) is not None
                    and pair_item.id
                    and pair_model_name in models_by_name
                }
                desired_pair_types.update({
                    (item_id, models_by_name[model_name].id): "create"
                    for item_id, model_name in real_no_ipn_create_pairs
                    if model_name in models_by_name
                })
                desired_pair_types.update({
                    (item_id, model_id): "delete"
                    for item_id, model_id in update_to_delete
                })
                desired_pair_types.update({
                    (item_id, models_by_name[model_name].id): "delete"
                    for item_id, model_name in real_no_ipn_delete_pairs
                    if model_name in models_by_name
                })

                for key, existing_draft in list(existing_drafts_by_key.items()):
                    change_type, item_id, model_id, field_name = key
                    pair_id = (item_id, model_id)
                    should_remove = False
                    if change_type == "update":
                        should_remove = (
                            pair_id in desired_pair_types
                            or (
                                (item_id, model_id, field_name) in touched_field_keys
                                and key not in desired_updates
                            )
                        )
                    elif (
                        pair_id in touched_pair_ids
                        and pair_id in authoritative_pair_ids
                    ):
                        should_remove = desired_pair_types.get(pair_id) != change_type
                    if should_remove:
                        await db.delete(existing_draft)
                        existing_drafts_by_key.pop(key)

                # === 创建或更新字段草稿（已排除应转为新增/删除的配对） ===
                for entry in draft_changes:
                    draft_key = ("update", entry["item_id"], entry["model_id"], entry["field_name"])
                    existing_draft = existing_drafts_by_key.get(draft_key)
                    if existing_draft is not None:
                        existing_draft.new_value = entry["new_value"]
                    else:
                        draft = ConfigDraft(
                            series_id=series.id,
                            batch_id=draft_batch.id,
                            change_type=entry["change_type"],
                            item_id=entry["item_id"],
                            model_id=entry["model_id"],
                            field_name=entry["field_name"],
                            old_value=entry["old_value"],
                            new_value=entry["new_value"]
                        )
                        db.add(draft)

                # 为"全部Excel值为N/A"的配对创建删除草稿
                for (del_item_id, del_model_id) in update_to_delete:
                    draft_key = ("delete", del_item_id, del_model_id, None)
                    if draft_key in existing_drafts_by_key:
                        continue
                    delete_draft = ConfigDraft(
                        series_id=series.id,
                        batch_id=draft_batch.id,
                        change_type="delete",
                        item_id=del_item_id,
                        model_id=del_model_id,
                        field_name=None,
                        old_value=None,
                        new_value=None
                    )
                    db.add(delete_draft)

                # 按机型创建"新增"草稿：每个 (IPN, 型号名) 对在 Excel 中有但快照中没有的
                # 或被快照标记为"全 N/A"（视为无数据）的配对
                for (pair_ipn, pair_model_name) in pairs_to_create:
                    # 查找 ConfigItem
                    pair_item = existing_items_map.get(pair_ipn) or processed_ipns.get(pair_ipn)
                    if not pair_item or not pair_item.id:
                        continue
                    # 查找 ProductModel
                    pair_model = models_by_name.get(pair_model_name)
                    if not pair_model or not pair_model.id:
                        continue
                    draft_key = ("create", pair_item.id, pair_model.id, None)
                    if draft_key in existing_drafts_by_key:
                        continue  # 已有相同新增草稿，跳过
                    create_draft = ConfigDraft(
                        series_id=series.id,
                        batch_id=draft_batch.id,
                        change_type="create",
                        item_id=pair_item.id,
                        model_id=pair_model.id,
                        field_name=None,
                        old_value=None,
                        new_value=pair_item.rd_name
                    )
                    db.add(create_draft)

                for pair_item_id, pair_model_name in real_no_ipn_create_pairs:
                    pair_item = all_items_by_id.get(pair_item_id)
                    pair_model = models_by_name.get(pair_model_name)
                    if not pair_item or not pair_model:
                        continue
                    draft_key = ("create", pair_item.id, pair_model.id, None)
                    if draft_key in existing_drafts_by_key:
                        continue
                    db.add(
                        ConfigDraft(
                            series_id=series.id,
                            batch_id=draft_batch.id,
                            change_type="create",
                            item_id=pair_item.id,
                            model_id=pair_model.id,
                            field_name=None,
                            old_value=None,
                            new_value=pair_item.rd_name,
                        )
                    )

                # 按机型创建"删除"草稿：快照中有但 Excel 中没有的配对
                # 排除快照中所有字段均为 N/A 的配对（视为无数据，不产生删除）
                deleted_pairs = set()
                if import_mode == "full":
                    deleted_pairs = (
                        (snapshot_pairs - excel_pairs)
                        - snapshot_all_na_pairs
                        - converted_to_delete_pairs
                    )
                # 过滤：只保留 Excel 中实际存在的型号（DB 补充的型号不产生删除草稿）
                deleted_pairs = {
                    (ipn, model_name)
                    for ipn, model_name in deleted_pairs
                    if model_name in deletable_model_names
                }
                if deleted_pairs:
                    # 批量查询所有可能需要的 ConfigItem 和 ProductModel
                    del_ipns = {p[0] for p in deleted_pairs}
                    del_model_names = {p[1] for p in deleted_pairs}
                    # 批量查 ConfigItem
                    del_items_by_ipn = {}
                    if del_ipns:
                        # 先收集内存中已有的
                        for ipn in del_ipns:
                            item = existing_items_map.get(ipn) or processed_ipns.get(ipn)
                            if item and item.id:
                                del_items_by_ipn[ipn] = item
                        # 再查库中遗漏的
                        missing_ipns = del_ipns - set(del_items_by_ipn.keys())
                        if missing_ipns:
                            del_items_result = await db.execute(
                                select(ConfigItem).where(ConfigItem.ipn.in_(missing_ipns))
                            )
                            for item in del_items_result.scalars().all():
                                if item.ipn:
                                    del_items_by_ipn[item.ipn] = item
                    # 批量查 ProductModel
                    del_models_by_name = {m.name: m for m in models}
                    missing_model_names = del_model_names - set(del_models_by_name.keys())
                    if missing_model_names:
                        del_models_result = await db.execute(
                            select(ProductModel).where(
                                ProductModel.series_id == series.id,
                                ProductModel.name.in_(missing_model_names)
                            )
                        )
                        for m in del_models_result.scalars().all():
                            del_models_by_name[m.name] = m

                    for (del_ipn, del_model_name) in deleted_pairs:
                        del_item = del_items_by_ipn.get(del_ipn)
                        del_model = del_models_by_name.get(del_model_name)
                        if not del_item or not del_item.id or not del_model or not del_model.id:
                            continue

                        # 检查该项在该机型下是否有有效值，跳过全 N/A 的垃圾数据
                        cv_result = await db.execute(
                            select(ConfigValue).where(
                                ConfigValue.item_id == del_item.id,
                                ConfigValue.model_id == del_model.id
                            )
                        )
                        cv = cv_result.scalar_one_or_none()
                        if cv:
                            has_meaningful = any(
                                getattr(cv, f, None) not in (None, '', 'N/A', '-')
                                for f in ('current_config', 'final_config', 'selection_config', 'rd_status')
                            )
                        else:
                            # ConfigValue 可能已被 clear_existing 删除，从快照判断
                            has_meaningful = any(
                                snapshot_values.get((del_ipn, del_model_name, f))
                                not in (None, '', 'N/A', '-')
                                for f in ('final_config', 'current_config', 'selection_config', 'rd_status')
                            )

                        if not has_meaningful:
                            # 全部 N/A，跳过（避免垃圾数据的删除草稿污染界面）
                            if del_item.ipn:
                                del_ipns.discard(del_ipn)
                            continue

                        delete_key = ("delete", del_item.id, del_model.id, None)
                        if delete_key in existing_drafts_by_key:
                            continue

                        delete_draft = ConfigDraft(
                            series_id=series.id,
                            batch_id=draft_batch.id,
                            change_type="delete",
                            item_id=del_item.id,
                            model_id=del_model.id,
                            field_name=None,
                            old_value=None,
                            new_value=None
                        )
                        db.add(delete_draft)

                for del_item_id, del_model_name in real_no_ipn_delete_pairs:
                    del_item = resolved_no_ipn_items.get(del_item_id)
                    del_model = models_by_name.get(del_model_name)
                    if not del_item or not del_model:
                        continue
                    delete_key = ("delete", del_item.id, del_model.id, None)
                    if delete_key in existing_drafts_by_key:
                        continue
                    db.add(
                        ConfigDraft(
                            series_id=series.id,
                            batch_id=draft_batch.id,
                            change_type="delete",
                            item_id=del_item.id,
                            model_id=del_model.id,
                            field_name=None,
                            old_value=None,
                            new_value=None,
                        )
                    )

                # 统一统计该批次所有草稿，更新计数器
                if draft_batch:
                    await db.flush()
                    all_drafts = await db.execute(
                        select(ConfigDraft).where(ConfigDraft.batch_id == draft_batch.id)
                    )
                    total = 0; c = 0; u = 0; d = 0
                    for dr in all_drafts.scalars().all():
                        total += 1
                        if dr.change_type == "create": c += 1
                        elif dr.change_type == "update": u += 1
                        elif dr.change_type == "delete": d += 1
                    draft_batch.total_count = total
                    draft_batch.create_count = c
                    draft_batch.update_count = u
                    draft_batch.delete_count = d

        await db.commit()

    except HTTPException:
        # 重新抛出HTTP异常
        await db.rollback()
        raise
    except Exception as e:
        # 其他异常，回滚事务
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"导入失败：{str(e)}")

    return {
        "message": "导入成功",
        "details": results,
        "total_series": len(results),
        "change_log": change_log
    }


@router.post("/import/cleanup-duplicate-models")
async def cleanup_duplicate_models(db: AsyncSession = Depends(get_db)):
    """只读诊断跨系列同名机型；自动删除已永久禁用。"""
    name_groups_result = await db.execute(
        select(
            ProductModel.name,
            func.count(ProductModel.id).label('total_instances'),
            func.count(func.distinct(ProductModel.series_id)).label('series_count')
        ).group_by(ProductModel.name)
        .having(func.count(func.distinct(ProductModel.series_id)) > 1)
    )
    duplicate_names_rows = name_groups_result.fetchall()
    duplicate_names = [r[0] for r in duplicate_names_rows]

    if not duplicate_names:
        return {
            "message": "没有发现重复的机型归属；自动清理已禁用",
            "deleted": [],
            "kept": [],
            "candidates": [],
        }

    duplicate_models = (
        await db.execute(
            select(ProductModel)
            .where(ProductModel.name.in_(duplicate_names))
            .order_by(ProductModel.name, ProductModel.id)
        )
    ).scalars().all()
    series_ids = {model.series_id for model in duplicate_models}
    series_by_id = {
        series.id: series.name
        for series in (
            await db.execute(select(ProductSeries).where(ProductSeries.id.in_(series_ids)))
        ).scalars().all()
    }
    grouped = {}
    for model in duplicate_models:
        grouped.setdefault(model.name, []).append(
            {
                "model_id": model.id,
                "series_id": model.series_id,
                "series_name": series_by_id.get(model.series_id, "Unknown"),
            }
        )
    candidates = [
        {"model_name": model_name, "instances": grouped[model_name]}
        for model_name in sorted(grouped)
    ]

    return {
        "message": f"发现 {len(candidates)} 组跨系列同名机型；自动清理已禁用，请人工核对身份",
        "deleted": [],
        "kept": [],
        "candidates": candidates,
    }


@router.post("/export")
async def export_excel(
    body: ExportRequest,
    db: AsyncSession = Depends(get_db)
):
    """导出Excel文件（所见即所得——由前端传入已筛选的行ID、机型ID和可见列字段）"""
    series_id = body.series_id
    include_main_unit = body.include_main_unit
    item_ids = body.item_ids
    categories = body.categories
    search = body.search
    model_ids = body.model_ids
    visible_fields = body.visible_fields
    draft_changes = body.draft_changes
    deleted_items = body.deleted_items
    new_items = body.new_items
    # 解析可见配置列
    ALL_CONFIG_FIELDS = list(CONFIG_FIELDS)
    FIELD_LABELS = {
        'final_config': '最终配置',
        'current_config': '当前配置',
        'selection_config': '选型类别',
        'rd_status': '研发状态',
    }
    if visible_fields:
        field_list = [f.strip() for f in visible_fields.split(',') if f.strip() in ALL_CONFIG_FIELDS]
    else:
        field_list = list(ALL_CONFIG_FIELDS)
    field_count = len(field_list)

    # 解析草稿变更记录
    draft_changes_map = {}
    if draft_changes:
        try:
            import json
            draft_changes_map = json.loads(draft_changes)
        except (json.JSONDecodeError, TypeError):
            pass

    # 解析删除项和新增项
    deleted_items_map = {}
    if deleted_items:
        try:
            import json
            deleted_items_map = json.loads(deleted_items)
        except (json.JSONDecodeError, TypeError):
            pass

    new_items_map = {}
    if new_items:
        try:
            import json
            new_items_map = json.loads(new_items)
        except (json.JSONDecodeError, TypeError):
            pass
    # 获取产品系列
    series_result = await db.execute(
        select(ProductSeries).where(ProductSeries.id == series_id)
    )
    series = series_result.scalar_one_or_none()

    if not series:
        raise HTTPException(status_code=404, detail="产品系列不存在")

    # 获取型号（支持按 model_ids 筛选）
    models_query = select(ProductModel).where(active_model_filter()).where(ProductModel.series_id == series_id)
    if model_ids:
        id_list = [int(x.strip()) for x in model_ids.split(',') if x.strip()]
        if id_list:
            models_query = models_query.where(ProductModel.id.in_(id_list))
    models_query = models_query.order_by(ProductModel.sort_order)
    models_result = await db.execute(models_query)
    models = models_result.scalars().all()

    if not models:
        raise HTTPException(status_code=400, detail="该系列下没有产品型号")

    identity_metadata = await model_identity_metadata(db, [m.id for m in models])

    # 获取配置项（按 item_ids 筛选——所见即所得；无 item_ids 时回退到 categories/search）
    items_query = select(ConfigItem).order_by(ConfigItem.row_index)
    if item_ids:
        id_list = [int(x.strip()) for x in item_ids.split(',') if x.strip()]
        if id_list:
            items_query = items_query.where(ConfigItem.id.in_(id_list))
    else:
        if categories:
            category_list = [c.strip() for c in categories.split(',') if c.strip()]
            if category_list:
                items_query = items_query.where(ConfigItem.category.in_(category_list))
        if search:
            items_query = items_query.where(
                (ConfigItem.rd_name.contains(search)) |
                (ConfigItem.ipn.contains(search)) |
                (ConfigItem.v_code.contains(search)) |
                (ConfigItem.zh_desc.contains(search)) |
                (ConfigItem.en_desc.contains(search))
            )
        if not include_main_unit:
            items_query = items_query.where(ConfigItem.category != "Main Unit")

    items_result = await db.execute(items_query)
    items = items_result.scalars().all()
    items = [
        item
        for item in items
        if not all(f"{item.id}_{model.id}" in deleted_items_map for model in models)
    ]
    excluded_pairs = [
        (item.id, model.id)
        for item in items
        for model in models
        if f"{item.id}_{model.id}" in deleted_items_map
    ]

    # 获取配置值
    model_id_list = [m.id for m in models]
    values_result = await db.execute(
        select(ConfigValue).where(ConfigValue.model_id.in_(model_id_list))
    )
    values = values_result.scalars().all()

    # 构建索引
    value_map = {}
    for v in values:
        if v.item_id not in value_map:
            value_map[v.item_id] = {}
        value_map[v.item_id][v.model_id] = v

    # 创建Excel
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "配置数据"

    # 定义样式
    header_font = Font(bold=True, size=11)
    header_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    category_fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    center_align = Alignment(horizontal='center', vertical='center')
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    # 草稿变更样式
    deleted_fill = PatternFill(start_color="FFCCCC", end_color="FFCCCC", fill_type="solid")
    deleted_font = Font(strike=True, color="CC0000")
    new_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    updated_fill = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")

    # 第1行：产品系列
    ws.cell(row=1, column=1, value="研发名称")
    ws.cell(row=1, column=2, value="V代码")
    ws.cell(row=1, column=3, value="IPN号")
    ws.cell(row=1, column=4, value="中文描述")
    ws.cell(row=1, column=5, value="英文描述")

    col = 6
    for model in models:
        ws.cell(row=1, column=col, value=series.name)
        ws.merge_cells(start_row=1, start_column=col, end_row=1, end_column=col + field_count - 1)
        col += field_count

    # 第2行：产品型号
    col = 6
    for model in models:
        source_uuid = identity_metadata.get(model.id, {}).get("source_uuid")
        ws.cell(row=2, column=col, value=f"{model.name}//{source_uuid}" if source_uuid else model.name)
        ws.merge_cells(start_row=2, start_column=col, end_row=2, end_column=col + field_count - 1)
        col += field_count

    # 第3行：配置状态
    ws.cell(row=3, column=1, value="")  # A列
    ws.cell(row=3, column=2, value="")  # B列
    ws.cell(row=3, column=3, value="")  # C列
    ws.cell(row=3, column=4, value="")  # D列
    ws.cell(row=3, column=5, value="")  # E列

    col = 6
    for _ in models:
        for fi, field_name in enumerate(field_list):
            ws.cell(row=3, column=col + fi, value=FIELD_LABELS[field_name])
        col += field_count

    # 设置表头样式
    for row in range(1, 4):
        for col in range(1, ws.max_column + 1):
            cell = ws.cell(row=row, column=col)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center_align
            cell.border = thin_border

    # 写入数据
    row_idx = 5
    current_category = None
    item_refs = {}

    for item in items:
        # 如果分类变化，插入分类行
        if item.category and item.category != current_category:
            current_category = item.category
            ws.cell(row=row_idx, column=1, value=current_category)
            ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=ws.max_column)
            ws.cell(row=row_idx, column=1).fill = category_fill
            ws.cell(row=row_idx, column=1).font = Font(bold=True)
            ws.cell(row=row_idx, column=1).alignment = center_align
            row_idx += 1

        # 写入固定列
        ws.cell(row=row_idx, column=1, value=item.rd_name)
        ws.cell(row=row_idx, column=2, value=item.v_code)
        ws.cell(row=row_idx, column=3, value=item.ipn)
        ws.cell(row=row_idx, column=4, value=item.zh_desc)
        ws.cell(row=row_idx, column=5, value=item.en_desc)
        item_refs[row_idx] = {
            "id": item.id,
            "fingerprint": config_item_fingerprint(item),
        }

        # 写入配置值（仅可见列，含样式：绿=新增，红+删除线=删除，黄=修改）
        col = 6
        for model in models:
            model_val = value_map.get(item.id, {}).get(model.id)
            item_model_key = f"{item.id}_{model.id}"
            is_deleted = item_model_key in deleted_items_map
            is_new = item_model_key in new_items_map
            for fi, field_name in enumerate(field_list):
                cell = ws.cell(row=row_idx, column=col + fi)
                # 基础值：优先从删除快照取（因为删除了，DB值可能已不可靠）
                if is_deleted:
                    raw_value = None
                else:
                    raw_value = getattr(model_val, field_name, '') if model_val else ''
                # 检查是否有逐格草稿变更
                change_key = f"{item.id}_{model.id}_{field_name}"
                has_update_change = False
                has_create_change = False
                if change_key in draft_changes_map:
                    dc = draft_changes_map[change_key]
                    if dc.get('changeType') == 'update' and dc.get('oldValue') is not None:
                        old_val = dc.get('oldValue', '') or '-'
                        new_val = dc.get('newValue', raw_value) or '-'
                        raw_value = new_val
                        cell.comment = Comment(
                            f"草稿变更：{old_val} → {new_val}",
                            "VINNO",
                        )
                        has_update_change = True
                    elif dc.get('changeType') == 'create':
                        raw_value = dc.get('newValue', raw_value) or '-'
                        has_create_change = True
                # 应用样式
                display_value = raw_value or '-'
                if is_deleted:
                    cell.value = display_value
                    cell.fill = deleted_fill
                    cell.font = deleted_font
                elif has_update_change:
                    cell.value = display_value
                    cell.fill = updated_fill
                elif is_new or has_create_change:
                    cell.value = display_value
                    cell.fill = new_fill
                else:
                    cell.value = display_value
                cell.border = thin_border
            col += field_count

        # 设置边框
        for col in range(1, ws.max_column + 1):
            ws.cell(row=row_idx, column=col).border = thin_border

        row_idx += 1

    # 设置列宽
    ws.column_dimensions['A'].width = 35  # 研发名称
    ws.column_dimensions['B'].width = 12  # V代码
    ws.column_dimensions['C'].width = 12  # IPN号
    ws.column_dimensions['D'].width = 20  # 中文描述
    ws.column_dimensions['E'].width = 20  # 英文描述

    col = 6
    for _ in models:
        for fi in range(field_count):
            ws.column_dimensions[get_column_letter(col + fi)].width = 12
        col += field_count

    write_patch_metadata(
        wb,
        series_id=series.id,
        item_ids=[item.id for item in items],
        model_ids=[model.id for model in models],
        fields=field_list,
        item_refs=item_refs,
        excluded_pairs=excluded_pairs,
    )

    # 保存到内存
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"{series.name}_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}"
        }
    )


@router.get("/template")
async def download_template():
    """下载导入模板"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "配置数据"

    # 表头
    headers = ["研发名称", "V代码", "IPN号", "中文描述", "英文描述"]
    for col, header in enumerate(headers, 1):
        ws.cell(row=1, column=col, value=header)

    # 示例数据
    sample_data = [
        ["示例配置项1", "V001", "IPN-001", "中文描述1", "English Desc 1"],
        ["示例配置项2", "V002", "IPN-002", "中文描述2", "English Desc 2"],
    ]
    for row_idx, row_data in enumerate(sample_data, 2):
        for col_idx, value in enumerate(row_data, 1):
            ws.cell(row=row_idx, column=col_idx, value=value)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=config_template.xlsx"}
    )


@router.post("/preview")
async def preview_import(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """
    预览导入Excel文件（不实际导入）

    返回解析后的数据摘要，供用户确认后再导入
    """
    if not (file.filename or '').casefold().endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="只支持Excel文件(.xlsx, .xls)")

    # 读取文件
    content = await file.read()
    try:
        wb = load_config_workbook(content, file.filename)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    ws = wb.active
    try:
        workbook_import_mode(wb)
        patch_metadata = read_patch_metadata(wb)
        merged_info = parse_merged_cells(ws)
        structure = parse_workbook_structure(
            ws,
            fallback_name=Path(file.filename).stem,
            merged_info=merged_info,
        )
        parsed_rows = parse_config_rows(ws)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    await _load_unique_existing_items(db, parsed_rows)
    await _validate_patch_scope_readonly(db, structure, parsed_rows, patch_metadata)

    # 解析结果
    preview_result = {
        'filename': file.filename,
        'total_rows': ws.max_row,
        'total_cols': ws.max_column,
        'series': [],
        'summary': {
            'total_models': 0,
            'total_items': 0,
            'categories': []
        }
    }

    # 解析型号和数据
    for series_info, parsed_models in structure:
        series = await db.scalar(
            select(ProductSeries).where(ProductSeries.name == series_info.name)
        )
        models = []
        seen_identity_keys = set()
        for parsed_model in parsed_models:
            try:
                model_name, source_uuid = parse_model_header(parsed_model.raw_header)
                existing = None
                if series is not None:
                    existing = await resolve_import_model_readonly(
                        db,
                        series.id,
                        parsed_model.raw_header,
                    )
            except ValueError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
            identity_key = (
                ("model", existing.id)
                if existing is not None
                else ("source", source_uuid)
                if source_uuid
                else ("name", model_name)
            )
            if identity_key in seen_identity_keys:
                raise HTTPException(
                    status_code=400,
                    detail=f"机型 {model_name} 在同一系列的文件中出现多次",
                )
            seen_identity_keys.add(identity_key)
            models.append(model_name)

        items = parsed_rows
        categories = parse_config_categories(ws)

        preview_result['series'].append({
            'name': series_info.name,
            'models': models,
            'item_count': len(items)
        })

        preview_result['summary']['total_models'] += len(models)
        preview_result['summary']['total_items'] += len(items)
        preview_result['summary']['categories'].extend(list(categories))

    preview_result['summary']['categories'] = list(set(preview_result['summary']['categories']))

    return preview_result

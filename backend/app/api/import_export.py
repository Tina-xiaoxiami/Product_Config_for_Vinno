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

from app.database import get_db
from app.models import (
    ProductSeries, ProductModel, ConfigItem, ConfigValue,
    DraftBatch, ConfigDraft, ImportHistory, ConfigVersion
)
import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

from app.services.config_workbook import (
    CONFIG_FIELDS,
    merged_cell_starts,
    parse_model_columns,
    parse_series_columns,
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

router = APIRouter()


def parse_merged_cells(ws):
    """解析合并单元格信息，返回每个合并区域的起始单元格值"""
    return merged_cell_starts(ws)


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
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="只支持Excel文件(.xlsx, .xls)")

    # 读取文件
    content = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(content))
    ws = wb.active
    try:
        import_mode = workbook_import_mode(wb)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    # 解析合并单元格
    merged_info = parse_merged_cells(ws)

    fallback_name = series_name or file.filename.replace('.xlsx', '').replace('.xls', '')
    series_list = parse_series_columns(
        ws,
        fallback_name=fallback_name,
        merged_info=merged_info,
    )

    results = []
    change_log = []  # 变更记录

    try:
        for series_info in series_list:
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

            # 解析产品型号和第3行字段标签，非连续系列范围保持独立。
            models = []
            model_fields = {}
            model_allows_pair_delete = {}
            for model_columns in parse_model_columns(ws, series_info.ranges, merged_info=merged_info):
                try:
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
            # 快照中的 (IPN, 型号名称) 对集合，用于判定新增/删除/修改
            snapshot_pairs = set()
            if last_version and last_version.snapshot_data:
                snapshot_raw_data = await normalize_snapshot(db, series.id, json.loads(last_version.snapshot_data))
                # 构建快照中型号ID→名称映射（回滚后model_id也会变，需用名称匹配）
                snapshot_model_name_map = {}
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
            for ipn_str, snap_model_name in snapshot_pairs:
                all_na = all(
                    snapshot_values.get((ipn_str, snap_model_name, f)) in NA_VALUES
                    for f in ("final_config", "current_config", "selection_config", "rd_status")
                )
                if all_na:
                    snapshot_all_na_pairs.add((ipn_str, snap_model_name))

            # 解析配置数据（从第5行开始）
            current_category = None
            items_created = 0
            values_created = 0

            # 批量收集待创建的配置项和配置值
            items_to_create = []
            all_ipns = set()

            for row_idx in range(4, ws.max_row + 1):
                first_col = ws.cell(row=row_idx, column=1).value

                # 检查是否是分类标题行
                if first_col and isinstance(first_col, str):
                    stripped = first_col.strip()
                    # 识别分类标题（6种分类）
                    valid_categories = [
                        "Main Unit",
                        "Optional Features",
                        "Optional peripherals",
                        "*Optional peripherals(Preassemble in Factory)",
                        "Probes",
                        "Biopsy guide"
                    ]
                    if stripped in valid_categories or stripped.startswith("Optional"):
                        current_category = stripped
                        continue

                # 跳过Main Unit分类的数据
                if current_category == "Main Unit":
                    continue

                # 解析固定列（A-E列）
                rd_name = ws.cell(row=row_idx, column=1).value
                v_code = ws.cell(row=row_idx, column=2).value
                ipn = ws.cell(row=row_idx, column=3).value
                zh_desc = ws.cell(row=row_idx, column=4).value
                en_desc = ws.cell(row=row_idx, column=5).value

                # 跳过空行
                if not rd_name and not ipn:
                    continue

                ipn_str = str(ipn).strip() if ipn else None
                if ipn_str:
                    all_ipns.add(ipn_str)

                # 收集配置项数据（待批量创建）
                items_to_create.append({
                    'row_idx': row_idx,
                    'category': current_category or "Optional Features",
                    'rd_name': str(rd_name).strip() if rd_name else None,
                    'v_code': str(v_code).strip() if v_code else None,
                    'ipn': ipn_str,
                    'zh_desc': str(zh_desc).strip() if zh_desc else None,
                    'en_desc': str(en_desc).strip() if en_desc else None,
                })

            # 批量查询已存在的 ConfigItem（按 IPN）
            existing_items_map = {}
            if all_ipns:
                existing_items_result = await db.execute(
                    select(ConfigItem).where(ConfigItem.ipn.in_(all_ipns))
                )
                for item in existing_items_result.scalars().all():
                    existing_items_map[item.ipn] = item

            # 批量创建配置项
            created_items = []
            changes = []  # 记录该系列的变更
            draft_changes = []  # 记录草稿级变更（用于创建 ConfigDraft）
            processed_ipns = {}  # 跟踪本次导入已处理的 IPN，避免同文件内重复

            for item_data in items_to_create:
                ipn_str = item_data['ipn']
                change_type = None

                # 检查是否已存在（数据库中或本次导入中）
                if ipn_str and (ipn_str in existing_items_map or ipn_str in processed_ipns):
                    # 优先使用数据库中已存在的，否则使用本次导入创建的
                    if ipn_str in existing_items_map:
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

            for item_info in created_items:
                item = item_info["item"]
                item_data = item_info["data"]
                item_ipn = str(item.ipn).strip() if item and item.ipn else None

                for model in models:
                    imported_values = {
                        field_name: ws.cell(
                            row=item_data['row_idx'],
                            column=column,
                        ).value
                        for field_name, column in model_fields[model.id].items()
                    }

                    # 追踪Excel中的 (IPN, 型号名) 对
                    # 部分字段工作簿不能据此推断整项删除；已有配对始终视为仍存在。
                    pair_key = (item_ipn, model.name) if item_ipn else None
                    if pair_key:
                        excel_values = [
                            str(value).strip() if value is not None else None
                            for value in imported_values.values()
                        ]
                        has_meaningful = any(v and v not in NA_VALUES for v in excel_values)
                        if has_meaningful or (
                            pair_key in snapshot_pairs
                            and not model_allows_pair_delete[model.id]
                        ):
                            excel_pairs.add(pair_key)

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
                            skip_draft = (
                                (pair_key and pair_key not in snapshot_pairs) or
                                (pair_key and pair_key in snapshot_all_na_pairs)
                            )
                            # Patch 中的 N/A 占位符与已有空值语义相同，不改写原始表示。
                            if normalize_import_value(getattr(val, field_name)) != new_val:
                                setattr(val, field_name, new_val)
                            if skip_draft:
                                continue
                            # 快照对比仅用于决定是否产生草稿
                            snap_val = snapshot_values.get((item_ipn, model.name, field_name))
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
                            # 如果该 (IPN, 型号) 对在快照中不存在，则不创建"修改"草稿
                            # 该对会由下面的"新增"逻辑处理
                            if pair_key and pair_key not in snapshot_pairs:
                                continue
                            # 快照中该配对4字段全为N/A，视为无数据，不产生修改草稿
                            if pair_key and pair_key in snapshot_all_na_pairs:
                                continue
                            # 从预计算快照值字典O(1)取值
                            snap_val = snapshot_values.get((item_ipn, model.name, field_name))
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
            deletable_model_names = {
                model.name
                for model in excel_models
                if model_allows_pair_delete.get(model.id, False)
            }
            real_delete_pairs = set()
            if import_mode == "full":
                real_delete_pairs = {
                    pair
                    for pair in (snapshot_pairs - excel_pairs) - snapshot_all_na_pairs
                    if pair[1] in deletable_model_names
                }
            need_draft = bool(draft_changes) or bool(real_create_pairs) or bool(real_delete_pairs)
            if need_draft:
                draft_result = await db.execute(
                    select(DraftBatch).where(
                        DraftBatch.series_id == series.id,
                        DraftBatch.status == "draft"
                    ).order_by(DraftBatch.created_at.desc()).limit(1)
                )
                draft_batch = draft_result.scalar_one_or_none()

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
                existing_drafts_by_key = set()  # (change_type, item_id, model_id, field_name)
                if not batch_is_new:
                    old_drafts = await db.execute(
                        select(ConfigDraft).where(ConfigDraft.batch_id == draft_batch.id)
                    )
                    for d in old_drafts.scalars().all():
                        existing_drafts_by_key.add((d.change_type, d.item_id, d.model_id, d.field_name))

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

                # === 创建更新草稿（已排除应转为删除的配对） ===
                for entry in draft_changes:
                    draft_key = ("update", entry["item_id"], entry["model_id"], entry["field_name"])
                    if draft_key in existing_drafts_by_key:
                        continue
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
                models_by_name = {m.name: m for m in models}
                pairs_to_create = (excel_pairs - snapshot_pairs) | (excel_pairs & snapshot_all_na_pairs)
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

                # 统一统计该批次所有草稿，更新计数器
                if need_draft and draft_batch:
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
                    snap = deleted_items_map[item_model_key]
                    raw_value = snap.get(field_name, '') if isinstance(snap, dict) else ''
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
                        if old_val != '-':
                            raw_value = f"{old_val} → {new_val}"
                        else:
                            raw_value = new_val
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
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}"
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
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="只支持Excel文件(.xlsx, .xls)")

    # 读取文件
    content = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(content))
    ws = wb.active

    # 解析合并单元格
    merged_info = parse_merged_cells(ws)

    series_list = parse_series_columns(
        ws,
        fallback_name=file.filename.replace('.xlsx', '').replace('.xls', ''),
        merged_info=merged_info,
    )

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
    for series_info in series_list:
        try:
            parsed_models = parse_model_columns(
                ws,
                series_info.ranges,
                merged_info=merged_info,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

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

        # 解析配置项
        items = []
        categories = set()
        current_category = None

        for row_idx in range(4, ws.max_row + 1):
            first_col = ws.cell(row=row_idx, column=1).value

            if first_col and isinstance(first_col, str):
                stripped = first_col.strip()
                valid_categories = [
                    "Main Unit",
                    "Optional Features",
                    "Optional peripherals",
                    "*Optional peripherals(Preassemble in Factory)",
                    "Probes",
                    "Biopsy guide"
                ]
                if stripped in valid_categories or stripped.startswith("Optional"):
                    current_category = stripped
                    categories.add(stripped)
                    continue

            if current_category == "Main Unit":
                continue

            rd_name = ws.cell(row=row_idx, column=1).value
            ipn = ws.cell(row=row_idx, column=3).value

            if not rd_name and not ipn:
                continue

            items.append({
                'rd_name': str(rd_name).strip() if rd_name else None,
                'ipn': str(ipn).strip() if ipn else None,
                'category': current_category or 'Optional Features'
            })

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

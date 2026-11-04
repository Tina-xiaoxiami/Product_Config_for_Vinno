"""探头配置 Excel 导入 API"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import io, json
import re
from app.database import get_db
from app.models.probe import (
    ProbeCategory, ProbeModel, Application, CategoryApplication,
    FeatureGroup, Feature, TemplateFeature,
    ProductProbeModel, ProductProbeConfig,
)
from app.models.product_model import ProductModel
import openpyxl
from app.services.probe_exclusion_rules import expand_exclusion_name, parse_exclusions

router = APIRouter()

NA_VALUES = {'', None, 'N/A', '-', 'None', 'null', '未定义'}


def _parse_merged_cells(ws):
    merged = {}
    for rng in ws.merged_cells.ranges:
        merged[(rng.min_row, rng.min_col)] = {
            'value': ws.cell(row=rng.min_row, column=rng.min_col).value,
            'max_col': rng.max_col, 'max_row': rng.max_row,
        }
    return merged


@router.post("/import-template")
async def import_template(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """导入模板 Excel：探头-功能配置模板.xlsx"""
    try:
        return await _import_template(file, db)
    except Exception:
        await db.rollback()
        raise


async def _import_template(file: UploadFile, db: AsyncSession):
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="只支持 Excel 文件")

    content = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(content))
    ws = wb.active
    merged_info = _parse_merged_cells(ws)

    # Parse feature groups from row 1 (merged cells)
    # Row 1: merged cells for groups, Row 2: feature names
    group_map = {}  # col_start -> group_name
    group_order = []
    for (row, col), info in sorted(merged_info.items()):
        if row == 1 and info['value']:
            name = str(info['value']).strip()
            if name and '探头-功能配置' not in name:
                group_map[col] = name
                group_order.append((col, name, info['max_col']))

    # Create feature groups
    group_db = {}
    for sort_i, (_, gname, max_col) in enumerate(group_order):
        r = await db.execute(select(FeatureGroup).where(FeatureGroup.name == gname))
        g = r.scalar_one_or_none()
        if not g:
            g = FeatureGroup(name=gname, sort_order=sort_i)
            db.add(g); await db.flush()
        group_db[gname] = g

    # Parse features from row 2 (column by column)
    feature_map = {}  # col -> feature_id
    for col in range(5, ws.max_column + 1):  # E onwards
        val = ws.cell(row=2, column=col).value
        if not val: continue
        name = str(val).strip().replace('\n', ' ')
        # Find which group this column belongs to
        parent_group = None
        for col_start, gname, max_col in group_order:
            if col_start <= col <= max_col:
                parent_group = group_db[gname]
                break
        if not parent_group:
            continue
        r = await db.execute(select(Feature).where(Feature.name == name, Feature.group_id == parent_group.id))
        f = r.scalar_one_or_none()
        if not f:
            f = Feature(name=name, group_id=parent_group.id, sort_order=col)
            db.add(f); await db.flush()
        feature_map[col] = f

    # Parse probe categories and models from rows 3+
    application_map = {}  # name -> Application
    cat_created = {}  # name -> category
    model_created = {}  # (cat_id, model_number) -> probe_model
    unresolved_exclusions = []

    for row_idx in range(3, ws.max_row + 1):
        cat_name = ws.cell(row=row_idx, column=1).value  # A: category
        probes_str = ws.cell(row=row_idx, column=2).value  # B: probe models
        apps_str = ws.cell(row=row_idx, column=3).value  # C: applications
        poc_apps_str = ws.cell(row=row_idx, column=4).value  # D: POC applications

        if not cat_name or not probes_str:
            continue
        cat_name = str(cat_name).strip()

        # Create category if needed
        if cat_name not in cat_created:
            r = await db.execute(select(ProbeCategory).where(ProbeCategory.name == cat_name))
            cat = r.scalar_one_or_none()
            if not cat:
                cat = ProbeCategory(name=cat_name, sort_order=row_idx)
                db.add(cat); await db.flush()
            cat_created[cat_name] = cat
        else:
            cat = cat_created[cat_name]

        # Parse probe models (comma/space separated)
        probe_names = [p.strip() for p in probes_str.replace('，', ',').split(',') if p.strip()]
        # Also handle Chinese punctuation
        probe_names = [p for name in probe_names for p in name.split() if p.strip()]

        # Actually, probe models are comma-separated like "SR1-10C, S1-8CX, S1-8CM"
        # Some have spaces mixed in
        probe_entries = []
        for token in probes_str.replace('，', ',').split(','):
            token = token.strip()
            if not token: continue
            # Some entries have multiple models separated by spaces
            for sub in token.split():
                sub = sub.strip(',').strip()
                if sub:
                    probe_entries.append(sub)

        probe_db_list = []
        for pn in probe_entries:
            if not pn or len(pn) < 2: continue
            key = (cat.id, pn)
            if key in model_created:
                probe_db_list.append(model_created[key])
                continue
            r = await db.execute(select(ProbeModel).where(
                ProbeModel.category_id == cat.id, ProbeModel.model_number == pn))
            pm = r.scalar_one_or_none()
            if not pm:
                pm = ProbeModel(category_id=cat.id, model_number=pn, sort_order=len(probe_db_list))
                db.add(pm); await db.flush()
            model_created[key] = pm
            probe_db_list.append(pm)

        # Parse applications — 分别处理常规应用和 POC 应用
        async def _link_apps(apps_str, probe_type):
            if not apps_str: return
            for token in re.split(r'[,，、]', str(apps_str)):
                token = token.strip()
                if not token: continue
                if token in application_map:
                    app = application_map[token]
                else:
                    r = await db.execute(select(Application).where(Application.name == token))
                    app = r.scalar_one_or_none()
                    if not app:
                        app = Application(name=token, sort_order=len(application_map))
                        db.add(app); await db.flush()
                    application_map[token] = app
                # Link category to application with probe_type
                r = await db.execute(select(CategoryApplication).where(
                    CategoryApplication.category_id == cat.id,
                    CategoryApplication.application_id == app.id,
                    CategoryApplication.probe_type == probe_type))
                if not r.scalar_one_or_none():
                    db.add(CategoryApplication(category_id=cat.id, application_id=app.id, probe_type=probe_type))

        await _link_apps(apps_str, "regular")
        await _link_apps(apps_str if str(poc_apps_str).strip() == "同常规" else poc_apps_str, "poc")
        application_names = sorted(set((await db.scalars(
            select(Application.name).join(CategoryApplication, CategoryApplication.application_id == Application.id)
            .where(CategoryApplication.category_id == cat.id)
        )).all()))

        # Parse feature support values and create template_features
        for col, feature in feature_map.items():
            val = ws.cell(row=row_idx, column=col).value
            cell_str = str(val).strip() if val else ''
            support = "unsupported"
            try:
                exclude_list = parse_exclusions(cell_str, application_names)
            except ValueError as error:
                raise HTTPException(422, f"{ws.title}!{ws.cell(row_idx, col).coordinate}：{error}；原文：{cell_str}") from error
            excludes = json.dumps(exclude_list, ensure_ascii=False) if exclude_list is not None else None
            unknown = [name for name in (exclude_list or []) if name not in application_names]
            if unknown:
                unresolved_exclusions.append({
                    "category": cat_name, "feature": feature.name,
                    "worksheet": ws.title, "cell": ws.cell(row_idx, col).coordinate,
                    "raw_text": cell_str, "application_names": application_names,
                    "unresolved_names": unknown,
                    "reason": "限制名称无法唯一匹配该类别的已确认应用，已保留完整原文；请核对原件与类别应用范围",
                })

            if '√' in cell_str:
                support = "supported"

            if support == "unsupported" and not cell_str:
                continue  # Skip empty cells (no explicit template entry)

            r = await db.execute(select(TemplateFeature).where(
                TemplateFeature.category_id == cat.id,
                TemplateFeature.feature_id == feature.id))
            tf = r.scalar_one_or_none()
            if not tf:
                tf = TemplateFeature(
                    category_id=cat.id, feature_id=feature.id,
                    default_support=support, default_excludes=excludes)
                db.add(tf)
            else:
                tf.default_support = support
                tf.default_excludes = excludes

    await db.commit()
    return {"message": f"导入完成：{len(group_db)} 功能组，{len(feature_map)} 功能，{len(cat_created)} 探头类别，{len(model_created)} 探头型号，{len(application_map)} 应用",
            "unresolved_exclusions": unresolved_exclusions}


@router.post("/import-product")
async def import_product(
    file: UploadFile = File(...),
    product_model_id: int = Form(None),
    product_model_name: str = Form(None),
    config_group: str = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """导入产品 Excel：VINNO 6_探头-功能配置.xlsx（支持按 config_group 批量导入）"""
    raise HTTPException(409, "请使用共同总集的 Excel 草稿导入入口，避免直接覆盖正式配置")


@router.post("/fill-template-excludes")
async def fill_template_excludes(db: AsyncSession = Depends(get_db)):
    """智能填充模板配置中的应用限制（排除列表）

    算法：
    1. 收集所有已经有排除列表的 TemplateFeature，按 feature_id 聚合
    2. 仅在来源类别应用目录中能唯一匹配时展开合并名称
    3. 对每个排除列表为 NULL 的 TemplateFeature（保留明确清空的 []）：
       a. 获取该类别关联的所有应用名称
       b. 对同一 feature 下其他类别中出现过的排除项，如果该类别也有同名应用，则加入排除
    """
    # 1. Get all template features grouped by feature
    r = await db.execute(select(TemplateFeature))
    all_tfs = r.scalars().all()

    # Resolve source restrictions against their own category, not a global list.
    r = await db.execute(
        select(CategoryApplication, Application)
        .join(Application, CategoryApplication.application_id == Application.id)
    )
    cat_apps_map = {}  # category_id -> set of app names
    for ca, app in r.all():
        if ca.category_id not in cat_apps_map:
            cat_apps_map[ca.category_id] = set()
        cat_apps_map[ca.category_id].add(app.name)

    eligible_ids = set()
    feat_excludes_map = {}
    for tf in all_tfs:
        if tf.default_support not in {"supported", "conditional"}:
            continue
        try:
            payload = json.loads(tf.default_excludes) if tf.default_excludes is not None else None
        except (json.JSONDecodeError, TypeError):
            continue
        names = payload.get("excludes", []) if isinstance(payload, dict) else payload
        if names is not None and (not isinstance(names, list) or not all(isinstance(name, str) for name in names)):
            continue
        eligible_ids.add(tf.id)
        source_apps = cat_apps_map.get(tf.category_id, set())
        for name in names or []:
            expanded = expand_exclusion_name(name, source_apps)
            # Unknown/ambiguous evidence stays on its source record. It must not
            # create inferred restrictions in another category.
            if all(value in source_apps for value in expanded):
                feat_excludes_map.setdefault(tf.feature_id, set()).update(expanded)

    # 4. Fill empty excludes
    updated = 0
    for tf in all_tfs:
        if tf.id not in eligible_ids or tf.default_excludes is not None:
            continue
        if tf.feature_id not in feat_excludes_map:
            continue
        cat_apps = cat_apps_map.get(tf.category_id, set())
        if not cat_apps:
            continue

        # Find which of the feature's commonly-excluded apps exist in this category
        union_excludes = feat_excludes_map[tf.feature_id]
        applicable = sorted(app for app in union_excludes if app in cat_apps)
        if applicable:
            tf.default_excludes = json.dumps(applicable, ensure_ascii=False)
            updated += 1

    await db.commit()
    return {"message": f"智能填充完成，更新了 {updated} 条模板配置的排除应用列表"}

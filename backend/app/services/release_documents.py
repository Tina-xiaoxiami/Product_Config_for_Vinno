"""发布介绍 Word 导出与文档模板。

模板语义（与 A 侧的空壳实现相反）：

- `sections` 决定文档包含哪些章节以及章节顺序；章节内容为空时自动跳过。
- `variables` 是变量白名单：没有声明的变量即使有值也不输出。
- 模板不存在时不报错，直接使用内置默认模板（与 A 侧"静默回退"一致）；
  但系统内置模板不可修改、不可删除。
"""

from __future__ import annotations

import json
import re
from io import BytesIO

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.feature_release_versions import (
    FeatureReleaseError,
    FeatureReleaseNotFoundError,
    get_feature_version,
    get_introduction,
)


DEFAULT_TEMPLATE_CODE = "default_release_intro"
DEFAULT_TEMPLATE_NAME = "默认发布介绍模板"
DEFAULT_TEMPLATE_DESCRIPTION = "系统默认的发布介绍文档模板"

# 章节顺序即默认文档顺序；标签沿用 A 侧种子，便于与既有材料对照。
RELEASE_SECTIONS = (
    ("basic_info", "基本信息"),
    ("summary", "功能概述"),
    ("clinical_significance", "临床意义"),
    ("workflow", "工作流程"),
    ("parameters", "参数介绍"),
    ("applications", "适用范围"),
    ("change_log", "变更说明"),
)
RELEASE_SECTION_KEYS = dict(RELEASE_SECTIONS)
RELEASE_SECTION_LABELS = tuple(label for _, label in RELEASE_SECTIONS)

# 变量白名单与来源一一对应，避免出现"声明了却没人填"的变量。
RELEASE_VARIABLE_KEYS = (
    "function_name",
    "function_version",
    "function_category",
    "function_status",
    "release_date",
    "summary",
    "clinical_significance",
    "workflow",
    "applications",
    "parameters",
    "change_log",
)

BASIC_INFO_VARIABLES = (
    ("function_name", "功能名称"),
    ("function_version", "功能版本"),
    ("function_category", "功能分类"),
    ("function_status", "当前状态"),
    ("release_date", "发布日期"),
)

LIFECYCLE_LABELS = {
    "undefined": "未定义",
    "developing": "开发中",
    "pending": "待确认",
    "released": "已发布",
    "offline": "已下线",
    "deprecated": "已废弃",
}

PARAMETER_HEADERS = ("配置项名称", "V 代码", "IPN", "英文描述")

TEMPLATE_CODE_PATTERN = re.compile(r"^[a-z0-9_]{3,80}$")
DOCX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


class ReleaseDocumentError(FeatureReleaseError):
    """Raised when a template or an export request breaks the release rules."""


class ReleaseDocumentSystemTemplateError(ReleaseDocumentError):
    """Raised when someone tries to modify or delete the built-in template."""


def default_template() -> dict:
    return {
        "id": None,
        "code": DEFAULT_TEMPLATE_CODE,
        "name": DEFAULT_TEMPLATE_NAME,
        "description": DEFAULT_TEMPLATE_DESCRIPTION,
        "sections": list(RELEASE_SECTION_LABELS),
        "variables": list(RELEASE_VARIABLE_KEYS),
        "active": True,
        "is_system": True,
    }


def _document_class():
    """Import python-docx lazily so the API stays importable without it."""

    try:
        from docx import Document
    except ImportError as error:  # pragma: no cover - dependency guard
        raise ReleaseDocumentError(
            "导出 Word 需要 python-docx，请先安装依赖（requirements.txt 已声明）"
        ) from error
    return Document


def _normalize_sections(sections) -> list[str]:
    if sections is None:
        return list(RELEASE_SECTION_LABELS)
    if isinstance(sections, str):
        try:
            sections = json.loads(sections or "[]")
        except ValueError as error:
            raise ReleaseDocumentError("模板章节格式不正确") from error
    cleaned = [str(item).strip() for item in sections or []]
    unknown = [item for item in cleaned if item not in RELEASE_SECTION_LABELS and item not in RELEASE_SECTION_KEYS]
    if unknown:
        raise ReleaseDocumentError(f"模板章节不受支持：{'、'.join(unknown)}")
    return [RELEASE_SECTION_KEYS.get(item, item) for item in cleaned]


def _normalize_variables(variables) -> list[str]:
    if variables is None:
        return list(RELEASE_VARIABLE_KEYS)
    if isinstance(variables, str):
        try:
            variables = json.loads(variables or "[]")
        except ValueError as error:
            raise ReleaseDocumentError("模板变量格式不正确") from error
    cleaned = [str(item).strip() for item in variables or []]
    unknown = [item for item in cleaned if item not in RELEASE_VARIABLE_KEYS]
    if unknown:
        raise ReleaseDocumentError(f"模板变量不受支持：{'、'.join(unknown)}")
    return cleaned


def _variable_values(
    feature: dict,
    version: dict,
    introduction: dict | None,
    parameters: list[dict],
) -> dict:
    introduction = introduction or {}
    applications = introduction.get("applications") or []
    return {
        "function_name": feature.get("primary_cn_name")
        or feature.get("legacy_name")
        or feature.get("name")
        or "功能",
        "function_version": version.get("software_version") or "",
        "function_category": feature.get("group_name") or "",
        # 未定义的生命周期不写进对外文档：候选行默认就是 undefined，
        # 在客户材料里显示"当前状态：未定义"只会造成误解。
        "function_status": (
            LIFECYCLE_LABELS.get(version.get("lifecycle_status") or "", "")
            if (version.get("lifecycle_status") or "undefined") != "undefined"
            else ""
        ),
        "release_date": version.get("release_date") or "",
        "summary": introduction.get("summary") or "",
        "clinical_significance": introduction.get("clinical_significance") or "",
        "workflow": introduction.get("workflow") or "",
        "applications": "、".join(str(item) for item in applications),
        # 参数介绍以表格呈现，这里的文本值只用于"该变量是否有内容"的判断。
        "parameters": "、".join(
            str(item.get("zh_desc") or item.get("rd_name") or item.get("v_code") or "")
            for item in parameters
            if item.get("zh_desc") or item.get("rd_name") or item.get("v_code")
        ),
        "change_log": version.get("change_note") or "",
    }


def render_release_document(
    *,
    feature: dict,
    version: dict,
    introduction: dict | None,
    parameters: list[dict] | None,
    template: dict | None = None,
) -> tuple[bytes, str]:
    """Render the introduction of one feature version into a Word document."""

    Document = _document_class()
    template = template or default_template()
    sections = _normalize_sections(template.get("sections"))
    variables = _normalize_variables(template.get("variables"))
    parameters = parameters or []
    values = _variable_values(feature, version, introduction, parameters)

    document = Document()
    _configure_page(document)

    name = values["function_name"]
    title = document.add_paragraph(f"{name} 发布介绍", style="Title")
    title.alignment = _center()
    title.paragraph_format.space_after = _pt(20)

    for label in sections:
        if label == "基本信息":
            rows = [
                (label_text, values[key])
                for key, label_text in BASIC_INFO_VARIABLES
                if key in variables and values.get(key)
            ]
            if not rows:
                continue
            _add_heading(document, label)
            for label_text, value in rows:
                _add_key_value(document, label_text, str(value))
        elif label == "参数介绍":
            if "parameters" not in variables or not parameters:
                continue
            _add_heading(document, label)
            _add_parameters_table(document, parameters)
        else:
            key = next(
                (key for key, label_text in RELEASE_SECTIONS if label_text == label), None
            )
            if key is None or key not in variables:
                continue
            value = values.get(key)
            if not value:
                continue
            _add_heading(document, label)
            _add_paragraph(document, str(value))

    buffer = BytesIO()
    document.save(buffer)
    filename = f"{name}_{values['function_version'] or '未标版本'}.docx"
    return buffer.getvalue(), filename


def _pt(value: float):
    from docx.shared import Pt

    return Pt(value)


def _center():
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    return WD_ALIGN_PARAGRAPH.CENTER


def _configure_page(document) -> None:
    from docx.shared import Cm, Mm

    for section in document.sections:
        section.page_width = Mm(210)
        section.page_height = Mm(297)
        section.left_margin = Cm(2.54)
        section.right_margin = Cm(2.54)
        section.top_margin = Cm(2.54)
        section.bottom_margin = Cm(2.54)


def _add_heading(document, text_value: str) -> None:
    heading = document.add_heading(text_value, level=1)
    heading.paragraph_format.space_before = _pt(10)
    heading.paragraph_format.space_after = _pt(10)


def _add_paragraph(document, text_value: str) -> None:
    paragraph = document.add_paragraph(text_value)
    paragraph.paragraph_format.space_after = _pt(10)


def _add_key_value(document, label: str, value: str) -> None:
    paragraph = document.add_paragraph()
    run = paragraph.add_run(f"{label}：")
    run.bold = True
    paragraph.add_run(value)
    paragraph.paragraph_format.space_after = _pt(5)


def _add_parameters_table(document, parameters: list[dict]) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    table = document.add_table(rows=1, cols=len(PARAMETER_HEADERS))
    table.style = "Table Grid"
    header_cells = table.rows[0].cells
    for index, header in enumerate(PARAMETER_HEADERS):
        cell = header_cells[index]
        cell.text = header
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        shading = OxmlElement("w:shd")
        shading.set(qn("w:val"), "clear")
        shading.set(qn("w:fill"), "E8E8E8")
        cell._tc.get_or_add_tcPr().append(shading)

    for item in parameters:
        cells = table.add_row().cells
        cells[0].text = str(item.get("zh_desc") or item.get("rd_name") or "-")
        cells[1].text = str(item.get("v_code") or "-")
        cells[2].text = str(item.get("ipn") or "-")
        cells[3].text = str(item.get("en_desc") or "-")

    width = OxmlElement("w:tblW")
    width.set(qn("w:type"), "pct")
    width.set(qn("w:w"), "5000")
    table._tbl.tblPr.append(width)


# --------------------------------------------------------------------------
# 模板读写
# --------------------------------------------------------------------------


def _template_payload(row) -> dict:
    return {
        "id": int(row.id),
        "code": row.code,
        "name": row.name,
        "description": row.description,
        "sections": _normalize_sections(row.sections_json),
        "variables": _normalize_variables(row.variables_json),
        "active": bool(row.active),
        "is_system": bool(row.is_system),
    }


_TEMPLATE_COLUMNS = "id, code, name, description, sections_json, variables_json, active, is_system"


async def list_templates(session: AsyncSession) -> list[dict]:
    result = await session.execute(
        text(
            f"""
            SELECT {_TEMPLATE_COLUMNS}
            FROM release_document_templates
            ORDER BY is_system DESC, code
            """
        )
    )
    rows = [_template_payload(row) for row in result]
    if not any(row["code"] == DEFAULT_TEMPLATE_CODE for row in rows):
        rows.insert(0, default_template())
    return rows


async def get_template(session: AsyncSession, template_id: int) -> dict | None:
    result = await session.execute(
        text(
            f"""
            SELECT {_TEMPLATE_COLUMNS}
            FROM release_document_templates
            WHERE id = :template_id
            """
        ),
        {"template_id": template_id},
    )
    row = result.one_or_none()
    return _template_payload(row) if row is not None else None


def _validate_template_input(
    *,
    code: str | None,
    name: str | None,
    sections,
    variables,
) -> tuple[str | None, str, list[str], list[str]]:
    cleaned_code = str(code or "").strip().lower() or None
    if cleaned_code is not None and not TEMPLATE_CODE_PATTERN.match(cleaned_code):
        raise ReleaseDocumentError("模板代码只能用小写字母、数字和下划线，长度 3-80")
    cleaned_name = str(name or "").strip()
    if not cleaned_name:
        raise ReleaseDocumentError("模板名称不能为空")
    normalized_sections = _normalize_sections(sections)
    if not normalized_sections:
        raise ReleaseDocumentError("模板至少需要保留一个章节")
    normalized_variables = _normalize_variables(variables)
    return cleaned_code, cleaned_name, normalized_sections, normalized_variables


async def create_template(
    session: AsyncSession,
    *,
    code: str,
    name: str,
    description: str | None = None,
    sections=None,
    variables=None,
    active: bool = True,
) -> dict:
    cleaned_code, cleaned_name, normalized_sections, normalized_variables = (
        _validate_template_input(code=code, name=name, sections=sections, variables=variables)
    )
    if cleaned_code == DEFAULT_TEMPLATE_CODE:
        raise ReleaseDocumentError("默认模板代码已被内置模板占用")
    existing = await session.execute(
        text("SELECT id FROM release_document_templates WHERE code = :code"),
        {"code": cleaned_code},
    )
    if existing.one_or_none() is not None:
        raise ReleaseDocumentError("模板代码已存在")

    result = await session.execute(
        text(
            """
            INSERT INTO release_document_templates (
                code, name, description, sections_json, variables_json, active, is_system
            ) VALUES (
                :code, :name, :description, :sections_json, :variables_json, :active, 0
            )
            RETURNING id
            """
        ),
        {
            "code": cleaned_code,
            "name": cleaned_name,
            "description": description,
            "sections_json": json.dumps(normalized_sections, ensure_ascii=False),
            "variables_json": json.dumps(normalized_variables, ensure_ascii=False),
            "active": 1 if active else 0,
        },
    )
    template_id = int(result.scalar_one())
    await session.commit()
    return await get_template(session, template_id)


async def update_template(
    session: AsyncSession,
    template_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
    sections=None,
    variables=None,
    active: bool | None = None,
    fields_set: set[str] | None = None,
) -> dict:
    current = await get_template(session, template_id)
    if current is None:
        raise FeatureReleaseNotFoundError("模板不存在")
    if current["is_system"]:
        raise ReleaseDocumentSystemTemplateError("系统内置模板不可修改")

    provided = fields_set if fields_set is not None else set()
    assignments: dict[str, object] = {}
    if "name" in provided or name is not None:
        _, cleaned_name, _, _ = _validate_template_input(
            code=None, name=name, sections=current["sections"], variables=current["variables"]
        )
        assignments["name"] = cleaned_name
    if "description" in provided:
        assignments["description"] = description
    if "sections" in provided or sections is not None:
        normalized = _normalize_sections(sections)
        if not normalized:
            raise ReleaseDocumentError("模板至少需要保留一个章节")
        assignments["sections_json"] = json.dumps(normalized, ensure_ascii=False)
    if "variables" in provided or variables is not None:
        assignments["variables_json"] = json.dumps(
            _normalize_variables(variables), ensure_ascii=False
        )
    if active is not None or "active" in provided:
        assignments["active"] = 1 if active else 0

    if assignments:
        clause = ", ".join(f"{column} = :{column}" for column in assignments)
        await session.execute(
            text(
                f"""
                UPDATE release_document_templates
                SET {clause}, updated_at = CURRENT_TIMESTAMP
                WHERE id = :template_id
                """
            ),
            {**assignments, "template_id": template_id},
        )
        await session.commit()
    return await get_template(session, template_id)


async def delete_template(session: AsyncSession, template_id: int) -> None:
    current = await get_template(session, template_id)
    if current is None:
        raise FeatureReleaseNotFoundError("模板不存在")
    if current["is_system"]:
        raise ReleaseDocumentSystemTemplateError("系统内置模板不可删除")
    await session.execute(
        text("DELETE FROM release_document_templates WHERE id = :template_id"),
        {"template_id": template_id},
    )
    await session.commit()


# --------------------------------------------------------------------------
# 导出
# --------------------------------------------------------------------------


async def _feature_with_group(session: AsyncSession, feature_id: int) -> dict:
    result = await session.execute(
        text(
            """
            SELECT feature.id, feature.name AS legacy_name, feature.ipn,
                   feature.primary_cn_name, feature.primary_en_name,
                   group_table.name AS group_name
            FROM features feature
            JOIN feature_groups group_table ON group_table.id = feature.group_id
            WHERE feature.id = :feature_id
            """
        ),
        {"feature_id": feature_id},
    )
    row = result.one_or_none()
    if row is None:
        raise FeatureReleaseNotFoundError("功能不存在")
    return {
        "id": int(row.id),
        "legacy_name": row.legacy_name,
        "ipn": row.ipn,
        "primary_cn_name": row.primary_cn_name,
        "primary_en_name": row.primary_en_name,
        "group_name": row.group_name,
    }


async def _feature_parameters(session: AsyncSession, feature_id: int) -> list[dict]:
    result = await session.execute(
        text(
            """
            SELECT item.v_code, item.ipn, item.rd_name, item.zh_desc, item.en_desc
            FROM feature_config_item_links link
            JOIN config_items item ON item.id = link.config_item_id
            WHERE link.feature_id = :feature_id
              AND link.review_status = 'approved'
            ORDER BY item.row_index, item.id
            """
        ),
        {"feature_id": feature_id},
    )
    return [
        {
            "v_code": row.v_code,
            "ipn": row.ipn,
            "rd_name": row.rd_name,
            "zh_desc": row.zh_desc,
            "en_desc": row.en_desc,
        }
        for row in result
    ]


async def export_release_document(
    session: AsyncSession,
    version_id: int,
    *,
    template_id: int | None = None,
) -> tuple[bytes, str]:
    """Assemble the Word file for one feature version."""

    version = await get_feature_version(session, version_id)
    feature = await _feature_with_group(session, int(version["feature_id"]))
    introduction = await get_introduction(session, version_id)

    template = None
    if template_id is not None:
        template = await get_template(session, template_id)
        if template is None:
            raise FeatureReleaseNotFoundError("模板不存在")
    if template is None:
        candidates = await list_templates(session)
        template = next(
            (item for item in candidates if item["code"] == DEFAULT_TEMPLATE_CODE and item["active"]),
            default_template(),
        )

    parameters = await _feature_parameters(session, int(version["feature_id"]))
    return render_release_document(
        feature=feature,
        version=version,
        introduction=introduction,
        parameters=parameters,
        template=template,
    )

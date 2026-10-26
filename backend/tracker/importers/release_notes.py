from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from pathlib import Path


VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")
VCODE_PATTERN = re.compile(r"\bV\d{5}\b", re.IGNORECASE)


@dataclass(frozen=True)
class ReleaseNotePair:
    version: str
    chinese_path: Path | None
    english_path: Path | None
    status: str
    issues: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ReleaseNoteCandidate:
    category: str
    language: str
    title: str
    text: str
    location: str
    # 分类依据，用于复核与审计：mapping / keyword / item / carried / ignored / unclassified / table
    basis: str = ""
    # 中英配对使用的文本。配置表行按“型号（V代码）”配对：适用性符号（X/O/△）与图例
    # 在两侧几乎相同，若参与配对会把不相干的两行配成一对。留空表示用 text 配对。
    pair_text: str = ""


SECTION_HEADINGS = {
    "升级注意事项": "remark",
    "upgrade notes": "remark",
    "配置变更": "config",
    "configuration update": "config",
    "configuration change": "config",
    "优化内容": "image",
    "optimization": "image",
    "图像优化": "image",
    "图像": "image",
    "image": "image",
    "image optimization": "image",
    "image optimized": "image",
    "其他图像优化": "image",
    "other image optimizations": "image",
    "基础图像优化": "image",
    "basic image optimization": "image",
    "问题修复": "bug",
    "bug fixed": "bug",
    "bug 修复": "bug",
    "bug fixes": "bug",
    "bug repair": "bug",
    "ui及功能优化": "function",
    "ui and functional optimizations": "function",
    "功能优化": "function",
    "function optimized": "function",
    "function optimization": "function",
    "functional optimization": "function",
    "软件优化": "function",
    "software optimization": "function",
    "通用优化": "function",
    "general optimization": "function",
    "新面板/ui": "function",
    "new panels & ui": "function",
    "造影/超快造影/vflash/urm": "function",
    "cbi & ufr cbi & vflash & urm": "function",
    "smf": "function",
}

PLACEHOLDER_VALUES = {"无", "na", "n/a", "none", "nil", "—", "-"}

# 分类依据：每个候选都能回答“为什么归到这一类”，供复核与审计。
BASIS_MAPPING = "mapping"          # 章节标题精确命中 SECTION_HEADINGS
BASIS_KEYWORD = "keyword"          # 章节标题命中关键词规则
BASIS_ITEM = "item"                # 条目自身名称模式（优先于章节分类）
BASIS_CARRIED = "carried"          # 在已确定分类的章节内，显式继承该分类
BASIS_IGNORED = "ignored"          # 前言/概述/目录等非条目章节，有意跳过
BASIS_UNCLASSIFIED = "unclassified"  # 无法判定 → 保留内容，交人工待确认
BASIS_TABLE = "table"              # 由配置/物料变更表的一行生成（型号即条目本体）

# 无法判定分类时使用的分类名：内容保留而不是丢弃。
UNCLASSIFIED = "unclassified"

# 配置/兼容性说明：适用机型、版本前提、兼容性限制。与知识中枢
# kh_categories.config_note 同名（《V10-候选审核结论》：兼容性、配置说明，不进功能库）。
CONFIG_NOTE = "config_note"

# 「兼容性/适用性说明」条目的判定模式。要求整条就是一句适用性或版本前提声明，
# 而不是“正文里提到适用”。因此：
#   - 只在文本较短、且由这些句式**开头**时命中；
#   - 不认裸词“兼容性”（否则“优化DICOM功能，提升DICOM的兼容性和稳定性”这种功能
#     条目会被误收）。
# 命中后条目默认归 CONFIG_NOTE，人工仍可在审核区改分类。
COMPATIBILITY_ITEM_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 适用于非URM机型（model type不等于0或15）。／ 适用所有发放机型，包括…
    re.compile(r"^适用于.{0,24}(机型|型号|机器|设备)"),
    re.compile(r"^适用[^。；;]{0,12}(机型|型号)"),
    re.compile(r"^适用(范围)?[:：]"),
    # 同上，括号里写 model type 的写法（必须由“适用”引导，否则
    # “部分7P机型（model type 为2），ReadZoom下旋转Rotate报错”这类缺陷条目会被误收）
    re.compile(r"^适用[^。；;]{0,30}[（(]\s*model\s*type", re.IGNORECASE),
    re.compile(r"^model\s*type\s*(不等于|不为|≠|=|为|is|!=)", re.IGNORECASE),
    # 基于1.13.30以上版本升级。／ Please upgrade based on the version 1.13.30 or above.
    re.compile(r"^基于\s*\d+(?:\.\d+)*\s*(以上|及以上|以后|起)版本"),
    re.compile(r"^(需|需先|必须先)?(升级)?(自|从)\s*\d+(?:\.\d+)+\s*(以上|及以上)?版本"),
    re.compile(r"^please\s+upgrade\s+based\s+on", re.IGNORECASE),
    # 升级方式为patch，支持从1.51.20版本升级。／ Applicable to the 1.51.20 version upgrade
    re.compile(r"^(升级方式为\S+[，,])?\s*(支持)?从\s*\d+(?:\.\d+)+\s*版本升级"),
    # 补充兼容性说明：／ Supplementary Compatibility Note:
    re.compile(r"^(补充)?兼容性说明"),
    re.compile(r"^supplementary\s+compatib", re.IGNORECASE),
    # ULTIMUS系列兼容版本，同样适用所有9E（URM）…／ ULTIMUS series compatible version, also for 9E and 9.
    re.compile(r"^.{0,24}兼容版本.{0,40}(适用|支持)"),
    re.compile(r"^.{0,30}compatible\s+version", re.IGNORECASE),
    # 历史设备不支持升级类（必须句首，避免命中“修复了不支持在线升级的问题”这类条目）
    re.compile(r"^(不支持|无法|不能|不再支持)(在线|直接)?升级"),
    # 英文：E3-8T:Due to hardware differences, upgrade for already shipped devices is not supported.
    re.compile(r"hardware\s+differences?", re.IGNORECASE),
    re.compile(r"upgrad\w*[^.]{0,60}(not|no longer)\s+supported", re.IGNORECASE),
    re.compile(r"^upgrade[^.]{0,40}(is\s+)?not\s+supported", re.IGNORECASE),
    re.compile(r"^applies\s+to[^.]{0,30}(models?|machines?|devices?)", re.IGNORECASE),
    re.compile(r"^applicable\s+to\s+the\s+\d+(?:\.\d+)*\s+version", re.IGNORECASE),
    re.compile(r"^only\s+(for|applies)[^.]{0,30}(models?|machines?|devices?)", re.IGNORECASE),
    re.compile(r"^compatib\w+\s+(notes?|statement)", re.IGNORECASE),
)
# 带缺陷或变更动作的描述不是兼容性声明：宁可漏收（仍按原分类进审核），也不能把
# Bug/功能条目改成兼容性说明——那会让已批准的缺陷从版本记录里消失。
COMPATIBILITY_EXCLUSION_PATTERN = re.compile(
    r"(报错|失败|异常|崩溃|闪退|卡顿|抖动|花屏|死机|无响应"
    r"|修复|解决|新增|优化|导入|上架|下架|提升|改进|调整|变更|支持新增"
    r"|crash|error|fail|fix|added|optimiz|improv)",
    re.IGNORECASE,
)
# 超过这个长度的条目不再按“一句话声明”判定，避免吃掉正文。
COMPATIBILITY_ITEM_MAX_LENGTH = 120

# 明确不产生条目的章节（前言、概述、目录等）。与“无法判定”不同，这是有意跳过。
IGNORED_SECTIONS = (
    "概述", "前言", "目录", "简介",
    "overview", "preface", "contents", "introduction", "abstract",
)

# 章节标题关键词规则，按顺序匹配，命中即返回。
# 要求：只收录能明确指示分类的词，避免把“优化”这类泛词纳入。
SECTION_KEYWORD_RULES: tuple[tuple[str, str], ...] = (
    ("图像优化", "image"),
    ("image optimization", "image"),
    ("探头更新", "probe"),
    ("探头导入", "probe"),
    ("探头配置", "probe"),
    ("probe update", "probe"),
    ("配置变更", "config"),
    ("配置更新", "config"),
    ("配置总览", "config"),
    ("配置差异", "config"),
    ("configuration change", "config"),
    ("configuration update", "config"),
    # 升级须知/适用范围：与既有「升级注意事项」同类，归 remark。
    ("升级", "remark"),
    ("适用范围", "remark"),
    ("upgrade", "remark"),
    ("scope", "remark"),
    ("问题修复", "bug"),
    ("bug fix", "bug"),
    ("功能相关", "function"),
    ("功能优化", "function"),
    ("functional optimization", "function"),
    ("function optimization", "function"),
    ("functionality", "function"),
    # 裸标题「功能 / Feature」在 V10 中文文档中即“功能相关更新”章节（实测内容为
    # 远程会诊、剪切波、VAid、Auto 系列等）。更具体的规则（图像优化、探头配置）
    # 排在其前，因此不会被抢走。
    ("功能", "function"),
    ("feature", "function"),
    ("functions", "function"),
    # 兜底：Release Note 中名为“X优化 / X optimization”的章节即功能优化章节。
    # 放在最后，确保更具体的规则（图像优化、探头更新等）优先命中。
    ("优化", "function"),
    ("optimization", "function"),
)

# 条目自身名称模式：在章节分类不可靠时用于纠正单条归属。
ITEM_PATTERN_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"probe\s*update|^added\s+\S*\d|探头更新|探头导入", re.IGNORECASE), "probe"),
    (re.compile(r"image\s*optimization|图像优化", re.IGNORECASE), "image"),
    # 「Bug修正」这类子标题出现在“功能”章节内，但内容是缺陷修复，应归 bug。
    (re.compile(r"^bug\b|^bug修正|^修复|^修正|^fixed\b", re.IGNORECASE), "bug"),
)

OPERATION_MARKERS = (
    "操作步骤",
    "使用步骤",
    "工作流：",
    "与“智能选帧”的区别",
    "补充：",
    "operation steps",
    "workflow:",
    "steps:",
    "how to use",
)
CONTAINER_HEADINGS = {
    "软件常规功能/性能优化",
    "general software function/performance optimization",
    "主显示器布局及相关功能优化",
    "main display layout and related function optimization",
    "测量及worksheet优化",
    "measurement and worksheet optimization",
    "功能优化",
    "function optimization",
    "urm测量优化",
    "urm measurement optimization",
    "其他bug修复",
    "other bug fixes",
    "用户体验优化",
    "user experience optimization",
    "其它",
    "其他",
    "others",
    "other",
}


# 表格的“说明性文字”：图例、引导句、注脚。它们本身不是条目，而是紧邻表格的注解。
# 当同一章节内存在可生成条目的配置/物料变更表时，这些文字并入条目的说明行，
# 既不再单独占一条待确认，也不会被丢弃；章节内没有这类表格时行为保持不变。
LEGEND_MARKERS = (
    "标配支持",
    "选配支持",
    "不支持",
    "招标支持",
    "标准支持",
    "optional support",
    "not supported",
    "standard support",
)
FOOTNOTE_PREFIXES = (
    "注：",
    "注:",
    "备注",
    "另，",
    "另：",
    "另:",
    "说明：",
    "说明:",
    "note:",
    "note：",
    "notes:",
    "notes：",
    "n.b.",
)
# “……如下：”这类引导句的最大长度；超过则视为正文，而不是表格引导句。
COMPANION_LEAD_IN_LIMIT = 60


def _normalized_heading(text: str) -> str:
    return re.sub(r"[\s:：。.;；]+", "", text).casefold()


NORMALIZED_SECTION_HEADINGS = {
    _normalized_heading(heading): category for heading, category in SECTION_HEADINGS.items()
}


def _section_category(text: str) -> str | None:
    return NORMALIZED_SECTION_HEADINGS.get(_normalized_heading(text))


def _is_placeholder(text: str) -> bool:
    normalized = re.sub(r"[\s。.;；:：]+", "", text).casefold()
    return normalized in PLACEHOLDER_VALUES


def _heading_level(paragraph: object) -> int | None:
    style_name = str(getattr(getattr(paragraph, "style", None), "name", ""))
    match = re.search(r"(?:heading|标题)\s*(\d+)", style_name, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _list_level(paragraph: object) -> int | None:
    properties = getattr(getattr(paragraph, "_p", None), "pPr", None)
    numbering = properties.numPr if properties is not None else None
    if numbering is None or numbering.ilvl is None:
        return None
    return int(numbering.ilvl.val)


def _is_operation_marker(text: str) -> bool:
    folded = text.strip().casefold()
    return any(folded.startswith(marker.casefold()) for marker in OPERATION_MARKERS)


def _is_container_heading(text: str) -> bool:
    return text.strip().casefold() in CONTAINER_HEADINGS


def _strip_parentheticals(text: str) -> str:
    """去掉括号补充说明，例如“功能相关更新（示意图皆为V10）”→“功能相关更新”。"""
    stripped = re.sub(r"[（(][^）)]*[）)]", "", text)
    return re.sub(r"[【\[][^】\]]*[】\]]", "", stripped).strip()


def _keyword_category(text: str) -> str | None:
    """按关键词规则判定章节分类；只认能明确指示分类的词。"""
    haystack = _strip_parentheticals(text).casefold()
    if not haystack:
        return None
    for keyword, category in SECTION_KEYWORD_RULES:
        if re.sub(r"\s+", "", keyword) in re.sub(r"\s+", "", haystack):
            return category
    return None


def _is_ignored_section(text: str) -> bool:
    """前言、概述、目录等非条目章节，有意跳过而不是“丢弃”。"""
    candidate = _strip_parentheticals(text).strip().casefold()
    return candidate in IGNORED_SECTIONS


def _item_category(title: str) -> str | None:
    """条目自身名称模式；用于纠正被章节分类错挂的单条。"""
    for pattern, category in ITEM_PATTERN_RULES:
        if pattern.search(title):
            return category
    return None


def _is_compatibility_statement(text: str) -> bool:
    """整条是否为“配置/兼容性说明”（适用机型、版本前提、兼容性限制）。

    实例（1.50.11/1.50.12/1.51.20 升级注意事项）：
    - 适用于非URM机型（model type不等于0或15）。
    - 基于1.13.30以上版本升级。
    - 补充兼容性说明：
    - E3-8T:Due to hardware differences, upgrade for already shipped devices is not supported.

    反例（必须是功能/图像条目，不能被收进来）：
    - 优化DICOM功能，提升DICOM的兼容性和稳定性；
    - URM分析新增“肾小球成像”功能，适用于“肾脏”应用。
    - 部分7P机型（model type 为2），ReadZoom下旋转Rotate报错（这是 Bug）。

    因此模式一律要求**从句首开始**，并且只在整条较短时生效；不认“兼容性”这类裸词；
    带缺陷/变更动作的描述一律排除。
    """
    stripped = " ".join(text.split())
    if not stripped or len(stripped) > COMPATIBILITY_ITEM_MAX_LENGTH:
        return False
    if COMPATIBILITY_EXCLUSION_PATTERN.search(stripped):
        return False
    return any(pattern.search(stripped) for pattern in COMPATIBILITY_ITEM_PATTERNS)


def _heading_decision(text: str, heading_level: int) -> tuple[str | None, str]:
    """返回 (分类, 依据)。

    只有一级标题才可能是“章节分类”。二级及以下标题在这些 Release Note 中表示
    具体条目（如 `S1-8CM图像优化`、`新增S1-8CM探头导入`），必须保留为条目，
    否则会被关键词判定吞掉、导致内容丢失。条目自身的分类由 `_item_category` 判定。
    """
    mapped = _section_category(text)
    if mapped is not None:
        return mapped, BASIS_MAPPING
    if heading_level > 1:
        return None, BASIS_CARRIED
    if _is_ignored_section(text):
        return None, BASIS_IGNORED
    keyword = _keyword_category(text)
    if keyword is not None:
        return keyword, BASIS_KEYWORD
    return UNCLASSIFIED, BASIS_UNCLASSIFIED


def _filename_version(path: Path) -> str | None:
    match = re.search(r"(\d+\.\d+\.\d+)\s*$", path.stem.strip())
    return match.group(1) if match else None


def is_final_release_note(path: Path, version: str) -> bool:
    stem = path.stem.strip()
    return (
        path.suffix.lower() == ".docx"
        and "releasenote" in re.sub(r"\s+", "", stem).casefold()
        and _filename_version(path) is not None
    )


def scan_release_note_directory(
    root: str | Path, file_keywords: list[str] | tuple[str, ...] | None = None
) -> list[ReleaseNotePair]:
    root_path = Path(root)
    pairs: list[ReleaseNotePair] = []
    if not root_path.exists():
        return pairs

    version_directories = [
        path for path in root_path.iterdir() if path.is_dir() and VERSION_PATTERN.fullmatch(path.name)
    ]
    version_directories.sort(key=lambda path: tuple(int(part) for part in path.name.split(".")))

    for directory in version_directories:
        normalized_keywords = [
            re.sub(r"\s+", "", keyword).casefold()
            for keyword in (file_keywords or [])
            if keyword.strip()
        ]
        candidates = [
            path
            for path in directory.iterdir()
            if path.is_file() and is_final_release_note(path, directory.name)
            and (
                not normalized_keywords
                or any(
                    keyword in re.sub(r"\s+", "", path.stem).casefold()
                    for keyword in normalized_keywords
                )
            )
        ]
        chinese = [path for path in candidates if CJK_PATTERN.search(path.stem)]
        english = [path for path in candidates if not CJK_PATTERN.search(path.stem)]

        def select_final(paths: list[Path], language: str) -> Path | None:
            if len(paths) == 1:
                return paths[0]
            if language == "cn":
                expected = re.sub(r"\s+", "", f"ULTIMUS系列ReleaseNote_{directory.name}").casefold()
                canonical = [
                    path
                    for path in paths
                    if re.sub(r"\s+", "", path.stem).casefold() == expected
                ]
                if len(canonical) == 1:
                    return canonical[0]
            exact_version = [path for path in paths if _filename_version(path) == directory.name]
            if len(exact_version) == 1:
                return exact_version[0]
            return None

        chinese_final = select_final(chinese, "cn")
        english_final = select_final(english, "en")
        issues = []
        warnings = []
        if chinese_final is None:
            issues.append(f"需要 1 个中文最终版文件，实际找到 {len(chinese)} 个")
        if english_final is None:
            issues.append(f"需要 1 个英文最终版文件，实际找到 {len(english)} 个")
        for language, selected in (("中文", chinese_final), ("英文", english_final)):
            if selected is None:
                continue
            filename_version = _filename_version(selected)
            if filename_version != directory.name:
                warnings.append(
                    f"{language}文件名版本 {filename_version} 与文件夹版本 {directory.name} 不一致；按文件夹版本归档"
                )
        pairs.append(
            ReleaseNotePair(
                version=directory.name,
                chinese_path=chinese_final,
                english_path=english_final,
                status="ready" if not issues else "needs_review",
                issues=tuple(issues),
                warnings=tuple(warnings),
            )
        )
    return pairs


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_docx_fragments(path: str | Path) -> list[dict[str, str | int]]:
    """Extract paragraphs and table cells while preserving usable evidence locations."""
    from docx import Document

    document = Document(str(path))
    fragments: list[dict[str, str | int]] = []
    for index, paragraph in enumerate(document.paragraphs):
        text = paragraph.text.strip()
        if text:
            fragments.append({"kind": "paragraph", "location": index, "text": text})
    for table_index, table in enumerate(document.tables):
        for row_index, row in enumerate(table.rows):
            for cell_index, cell in enumerate(row.cells):
                text = "\n".join(
                    paragraph.text.strip() for paragraph in cell.paragraphs if paragraph.text.strip()
                )
                if text:
                    fragments.append(
                        {
                            "kind": "table_cell",
                            "location": f"{table_index}:{row_index}:{cell_index}",
                            "text": text,
                        }
                    )
    return fragments


def _table_payload(table: object, table_index: int) -> dict[str, object] | None:
    """把一张 Word 表转成 headers/rows 结构；空表返回 None。"""
    matrix: list[list[str]] = []
    for row in table.rows:
        values = []
        for cell in row.cells:
            text = "\n".join(
                paragraph.text.strip()
                for paragraph in cell.paragraphs
                if paragraph.text.strip()
            )
            image_count = len(cell._tc.xpath(".//a:blip"))
            if image_count:
                image_marker = f"[图片×{image_count}]"
                text = f"{text}\n{image_marker}" if text else image_marker
            values.append(text)
        if any(values):
            matrix.append(values)
    if not matrix:
        return None
    return {"index": table_index, "headers": matrix[0], "rows": matrix[1:]}


def _document_nodes(document: object) -> list[dict[str, object]]:
    """按文档顺序返回顶层段落与表格。

    段落序号与 `document.paragraphs` 一致（表格内的段落不计入），因此
    `paragraph:{index}` 证据位置与既有数据共用同一套编号。
    """
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    nodes: list[dict[str, object]] = []
    paragraph_index = 0
    table_index = 0
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            nodes.append(
                {
                    "kind": "paragraph",
                    "paragraph": Paragraph(child, document),
                    "index": paragraph_index,
                }
            )
            paragraph_index += 1
        elif child.tag.endswith("}tbl"):
            table = Table(child, document)
            nodes.append(
                {
                    "kind": "table",
                    "payload": _table_payload(table, table_index),
                    "index": table_index,
                }
            )
            table_index += 1
    return nodes


def _table_change_classification(
    payload: dict[str, object] | None, language: str
) -> dict[str, object] | None:
    """判断一张表是否为“变更清单”，是则返回其分类结果。

    只有逐行代表一次变更的表才逐行生成条目：

    - `material_change`（物料型号/IPN/变更说明）本身就是变更清单；
    - `configuration_matrix` 仅在 `partial_update`（行数较少）时是变更清单；
      50 行以上的表是**全量快照**（例如某版本给出的完整配置矩阵），属于参考状态
      而不是变更，逐行抽成候选只会淹没有效条目——它仍可在“查看配置表”与版本中心查看；
    - `support_scope`（各功能支持的探头/应用）同样是参考状态。
    """
    if payload is None:
        return None
    classified = classify_release_table(payload, language)
    if classified["table_type"] == "material_change":
        return classified
    if (
        classified["table_type"] == "configuration_matrix"
        and classified["snapshot_mode"] == "partial_update"
    ):
        return classified
    return None


def _record_title(record: dict[str, object]) -> str:
    """条目名：型号（V代码）。型号是核心；代码缺失时只保留型号。"""
    name = str(record.get("item_name") or "").strip()
    code = str(record.get("item_code") or "").strip()
    if name and code:
        return f"{name}（{code}）"
    return name or code


def _table_candidate(
    classified: dict[str, object],
    record: dict[str, object],
    category: str,
    language: str,
    table_index: int,
) -> ReleaseNoteCandidate:
    """把变更表的一行变成一个条目：标题＝型号，正文＝该行全部原始信息。

    行内所有非空字段都保留（含 IPN、适用机型、变更说明、各机型适用性），
    审核时不必再打开配置表原文。
    """
    title = _record_title(record)
    lines = [title]
    data = {
        header: value for header, value in (record.get("data") or {}).items()
        if str(value).strip()
    }
    if classified["table_type"] == "configuration_matrix" and len(data) > 3:
        # 宽矩阵（各机型适用性列）合并成一行，避免一条条目占十几行。
        # 表头里可能带换行（如“9E⏎(URM)”），压成单空格才不会把这一行拆断。
        pairs = [
            f"{re.sub(r'\s+', ' ', header).strip()}：{re.sub(r'\s+', ' ', value).strip()}"
            for header, value in data.items()
        ]
        lines.append("适用配置：" + "；".join(pairs))
    else:
        # 窄表（配置/更新说明、产品系列等）逐字段成行，读起来就是一句话。
        for header, value in data.items():
            lines.append(f"{header}：{value}")
    return ReleaseNoteCandidate(
        category=category,
        language=language,
        title=title,
        text="\n".join(lines),
        # 原始 Word 行号（含表头行），供人工回原文核对。
        location=f"table:{table_index}:{int(record.get('row_index', 0)) + 2}",
        basis=BASIS_TABLE,
        pair_text=title,
    )


def _is_table_companion(text: str) -> bool:
    """图例、引导句、注脚：它们不是条目，而是表格的注解。"""
    stripped = text.strip()
    if not stripped:
        return False
    folded = stripped.casefold()
    if any(folded.startswith(prefix.casefold()) for prefix in FOOTNOTE_PREFIXES):
        return True
    if any(marker in folded for marker in LEGEND_MARKERS):
        return True
    return stripped.endswith(("：", ":")) and len(stripped) <= COMPANION_LEAD_IN_LIMIT


def _note_table_targets(
    nodes: list[dict[str, object]], language: str
) -> dict[int, int]:
    """为每个“表格注解”段落找到它紧邻的变更表（返回 节点位置 → 表序号）。

    判定顺序（先看下一张表，再看上一张表），与人在文档里的读法一致：

    1. 向下找：跳过空段落、其它注解、非变更表；遇到变更表即认定它是引导句；
       遇到正文段落或标题则停止。
    2. 找不到再向上找：同样跳过空段落、其它注解、非变更表；遇到变更表即认定它
       是注脚/图例；遇到正文段落或标题则停止。
    3. 两侧都没有变更表 → 不并入任何条目（该行仍按原有方式单独成条）。

    只并入紧邻的那张表，不用整章的表去套：1.14.80 英文文档里
    “V10/V6/V5 Probes change list：”三句引导语分别属于三张表，
    若统一并入本章全部条目，每条都会挂上另外两张表的引导语。
    """
    def is_table(position: int) -> bool:
        return nodes[position]["kind"] == "table"

    def is_change_table(position: int) -> bool:
        return is_table(position) and (
            _table_change_classification(nodes[position].get("payload"), language)
            is not None
        )

    def is_skippable(position: int) -> bool:
        if nodes[position]["kind"] == "table":
            return not is_change_table(position)
        paragraph = nodes[position]["paragraph"]
        text = paragraph.text.strip()
        if not text:
            return True
        return _is_table_companion(text)

    targets: dict[int, int] = {}
    for position, node in enumerate(nodes):
        if node["kind"] != "paragraph":
            continue
        text = node["paragraph"].text.strip()
        if not text or not _is_table_companion(text):
            continue
        target: int | None = None
        for direction in (1, -1):
            candidate = position + direction
            while 0 <= candidate < len(nodes):
                if is_change_table(candidate):
                    target = int(nodes[candidate]["index"])
                    break
                if not is_skippable(candidate):
                    break
                candidate += direction
            if target is not None:
                break
        if target is not None:
            targets[position] = target
    return targets


def extract_docx_tables(path: str | Path) -> list[dict[str, object]]:
    """Preserve Word tables as row/column data instead of flattening them into text."""
    from docx import Document

    document = Document(str(path))
    extracted: list[dict[str, object]] = []
    for table_index, table in enumerate(document.tables):
        payload = _table_payload(table, table_index)
        if payload is not None:
            extracted.append(payload)
    return extracted


def _normalized_table_header(value: str) -> str:
    return re.sub(r"[\s/_&（）()]+", "", value).casefold()


def _stable_item_key(item_name: str, item_code: str = "") -> str:
    if item_code:
        return item_code.upper()
    match = VCODE_PATTERN.search(item_name)
    if match:
        return match.group(0).upper()
    return re.sub(r"[\s:：+＋（）()/_-]+", "", item_name).casefold()


# 变更表里“条目名”列的常见表头。各版本文档写法不一：功能/探头、探头/功能、
# Function / Probe、Feature、Probe、探头（配合“产品系列”列）等，都是型号/功能名称。
# 识别不到型号列会让条目只剩一个 V 代码，等于把要审的核心内容丢掉。
ITEM_NAME_HEADERS = (
    "功能/探头",
    "Function/Probe",
    "Function/Probe/Feature",
    "探头/功能",
    "Probe/Function",
    "物料型号",
    "型号",
    "Model",
    "功能",
    "Function",
    "Functionality",
    "Feature",
    "Features",
    "探头",
    "Probe",
    "Probes",
    "名称",
    "Name",
    "Item",
)
ITEM_CODE_HEADERS = ("V代码", "Vcode", "V Code", "VCODE")


def _change_kind(text: str, default: str = "modified") -> str:
    folded = text.casefold()
    if any(marker in folded for marker in ("下架", "删除", "取消", "removed", "discontinued")):
        return "removed"
    if any(marker in folded for marker in ("新增", "补充", "added", "new")):
        return "added"
    return default


def classify_release_table(table: dict[str, object], language: str) -> dict[str, object]:
    """Classify one raw Word table and derive searchable, versioned records."""
    headers = [str(value).strip() for value in table.get("headers", [])]
    raw_rows = [[str(value).strip() for value in row] for row in table.get("rows", [])]
    normalized_headers = [_normalized_table_header(value) for value in headers]
    header_text = "|".join(normalized_headers)
    has_old_new = (
        any(value in {"旧", "old", "旧平台图像"} for value in normalized_headers)
        and any(value in {"新", "new", "新平台图像"} for value in normalized_headers)
    )
    if len(headers) == 2 and (
        "支持探头" in header_text or "supportedprobes" in header_text
    ):
        table_type = "support_scope"
        snapshot_mode = "full_snapshot"
    elif "ipn" in normalized_headers or "变更说明" in normalized_headers or "变更类型" in normalized_headers:
        table_type = "material_change"
        snapshot_mode = "delta"
    elif has_old_new and ("图像" in header_text or (normalized_headers and normalized_headers[0] == "探头")):
        table_type = "image_comparison"
        snapshot_mode = "comparison"
    elif has_old_new:
        table_type = "ui_comparison"
        snapshot_mode = "comparison"
    elif any(value in {"v代码", "vcode"} for value in normalized_headers) and len(headers) >= 3:
        table_type = "configuration_matrix"
        snapshot_mode = "full_snapshot" if len(raw_rows) >= 50 else "partial_update"
    else:
        table_type = "other"
        snapshot_mode = "reference"

    def index_for(*names: str) -> int | None:
        for name in names:
            normalized = _normalized_table_header(name)
            if normalized in normalized_headers:
                return normalized_headers.index(normalized)
        return None

    records: list[dict[str, object]] = []
    for row_index, source_row in enumerate(raw_rows):
        row = [*source_row, *([""] * max(0, len(headers) - len(source_row)))]
        if not any(row):
            continue
        if table_type == "configuration_matrix":
            code_index = index_for(*ITEM_CODE_HEADERS)
            name_index = index_for(*ITEM_NAME_HEADERS)
            item_code = row[code_index] if code_index is not None else ""
            item_name = row[name_index] if name_index is not None else ""
            data = {
                header: row[column]
                for column, header in enumerate(headers)
                if column not in {code_index, name_index} and row[column]
            }
            if not item_name and not item_code:
                continue
            change_kind = "modified"
        elif table_type == "support_scope":
            item_name = row[0]
            item_code = ""
            data = {"supported_scope": row[1] if len(row) > 1 else ""}
            change_kind = "snapshot"
        elif table_type == "material_change":
            name_index = index_for(*ITEM_NAME_HEADERS)
            code_index = index_for(*ITEM_CODE_HEADERS)
            item_name = row[name_index or 0]
            item_code = row[code_index] if code_index is not None else ""
            data = {
                header: row[column]
                for column, header in enumerate(headers)
                if column not in {name_index, code_index} and row[column]
            }
            evidence = " ".join(data.values())
            change_kind = _change_kind(evidence)
        elif table_type in {"ui_comparison", "image_comparison"}:
            item_name = row[0]
            code_match = VCODE_PATTERN.search(item_name)
            item_code = code_match.group(0).upper() if code_match else ""
            data = {"old": row[1] if len(row) > 1 else "", "new": row[2] if len(row) > 2 else ""}
            change_kind = "modified"
        else:
            item_name = row[0]
            item_code = ""
            data = {header: row[column] for column, header in enumerate(headers[1:], 1) if row[column]}
            change_kind = "reference"
        if not item_name and not item_code:
            continue
        summary = " | ".join(value for value in row if value)
        record = {
            "row_index": row_index,
            "stable_key": _stable_item_key(item_name, item_code),
            "item_code": item_code,
            "item_name": item_name,
            "change_kind": change_kind,
            "summary": summary or item_name,
            "data": data,
            "language": language,
        }
        if table_type in {"ui_comparison", "image_comparison"} and records:
            previous = records[-1]
            if previous["stable_key"] == record["stable_key"]:
                previous_score = sum(bool(value) for value in previous["data"].values())
                current_score = sum(bool(value) for value in data.values())
                if current_score >= previous_score:
                    records[-1] = record
                continue
        records.append(record)
    return {
        "index": int(table.get("index", 0)),
        "table_type": table_type,
        "snapshot_mode": snapshot_mode,
        "headers": headers,
        "rows": raw_rows,
        "records": records,
    }


def extract_release_note_candidates(
    path: str | Path, language: str
) -> list[ReleaseNoteCandidate]:
    """Extract release items using Word section headings, hierarchy and list levels.

    除段落外，**变更清单表**也逐行生成条目：配置变更章节的核心内容通常在表格里，
    只看段落会只剩“注：……”或“各功能支持的探头/应用如下：”这类注解，真正要审的
    型号反而被漏掉。表格行生成条目时，紧邻该表的图例、引导句、注脚作为说明行保留。
    """
    from docx import Document

    document = Document(str(path))
    nodes = _document_nodes(document)
    note_targets = _note_table_targets(nodes, language)
    category_scopes: dict[int, str | None] = {}
    basis_scopes: dict[int, str] = {}
    inline_category: str | None = None
    candidates: list[ReleaseNoteCandidate] = []
    group: dict[str, object] | None = None
    # 表序号 → 该表行条目在 candidates 中的位置
    table_positions: dict[int, list[int]] = {}
    # 目标表尚未处理到的注解（表格处理时归位）
    pending_notes: list[dict[str, object]] = []

    def active_category() -> str | None:
        if inline_category is not None:
            return inline_category
        if not category_scopes:
            return None
        return category_scopes[max(category_scopes)]

    def active_basis() -> str:
        if inline_category is not None:
            return BASIS_MAPPING
        if not basis_scopes:
            return BASIS_UNCLASSIFIED
        return basis_scopes[max(basis_scopes)]

    def add_flat_item(
        category: str,
        text: str,
        index: int,
        list_level: int | None,
        basis: str = BASIS_CARRIED,
    ) -> None:
        if _is_placeholder(text) or _is_operation_marker(text):
            return
        # “适用于非URM机型（model type不等于0或15）”这类兼容性/适用性声明默认归
        # 配置/兼容性说明，而不是跟着所在章节（升级注意事项→备注）走。
        if _is_compatibility_statement(text):
            category = CONFIG_NOTE
        if list_level is not None and list_level > 0 and candidates:
            previous = candidates[-1]
            if previous.category == category and previous.language == language:
                candidates[-1] = replace(previous, text=f"{previous.text}\n{text}")
                return
        candidates.append(
            ReleaseNoteCandidate(
                category=category,
                language=language,
                title=text,
                text=text,
                location=f"paragraph:{index}",
                basis=basis,
            )
        )

    def flush_group(next_heading_level: int | None = None) -> None:
        nonlocal group
        if group is None:
            return
        title = str(group["title"])
        body = list(group["body"])
        level = int(group["level"])
        if not body and next_heading_level is not None and next_heading_level > level:
            group = None
            return
        if _is_container_heading(title):
            for body_text, body_index, body_level in body:
                add_flat_item(
                    str(group["category"]),
                    str(body_text),
                    int(body_index),
                    body_level,
                    str(group.get("basis", BASIS_CARRIED)),
                )
            group = None
            return
        if not _is_placeholder(title):
            details = [str(item[0]) for item in body if not _is_placeholder(str(item[0]))]
            candidates.append(
                ReleaseNoteCandidate(
                    category=str(group["category"]),
                    language=language,
                    title=title,
                    text="\n".join([title, *details]),
                    location=f"paragraph:{group['index']}",
                    basis=str(group.get("basis", BASIS_CARRIED)),
                )
            )
        group = None

    def attach_notes(positions: list[int], notes: list[dict[str, object]]) -> None:
        """把注解文字作为说明行并入指定条目（同一行只出现一次）。"""
        lines: list[str] = []
        for note in notes:
            line = str(note["text"])
            if line not in lines:
                lines.append(line)
        for position in positions:
            candidate = candidates[position]
            existing = candidate.text.split("\n")
            additions = [line for line in lines if line not in existing]
            if additions:
                candidates[position] = replace(
                    candidate, text="\n".join([candidate.text, *additions])
                )

    def add_note(note: dict[str, object]) -> None:
        """注解归位：目标表已处理则立即并入，否则等该表处理；始终归不了再单独成条。"""
        positions = table_positions.get(int(note["target"]))
        if positions:
            attach_notes(positions, [note])
            return
        pending_notes.append(note)

    def emit_note_as_item(note: dict[str, object]) -> None:
        """归不了表时按改动前的方式处理：组内正文或独立条目。"""
        target = note.get("group")
        if target is not None and target is group:
            target["body"].append((note["text"], note["index"], note["list_level"]))
            return
        add_flat_item(
            str(note["category"]),
            str(note["text"]),
            int(note["index"]),
            note["list_level"],
            str(note["basis"]),
        )

    for position, node in enumerate(nodes):
        if node["kind"] == "table":
            classified = _table_change_classification(node["payload"], language)
            if classified is None:
                continue
            category = active_category()
            if category is None:
                continue
            records = list(classified["records"])
            if not records:
                continue
            for record in records:
                candidates.append(
                    _table_candidate(
                        classified, record, category, language, int(node["index"])
                    )
                )
            table_index = int(node["index"])
            positions = list(range(len(candidates) - len(records), len(candidates)))
            table_positions[table_index] = positions
            waiting = [
                note for note in pending_notes if int(note["target"]) == table_index
            ]
            if waiting:
                pending_notes = [
                    note for note in pending_notes if int(note["target"]) != table_index
                ]
                attach_notes(positions, waiting)
            continue
        paragraph = node["paragraph"]
        index = int(node["index"])
        text = paragraph.text.strip()
        if not text:
            continue
        heading_level = _heading_level(paragraph)
        if heading_level is not None:
            flush_group(heading_level)
            inline_category = None
            category_scopes = {
                level: category
                for level, category in category_scopes.items()
                if level < heading_level
            }
            basis_scopes = {
                level: basis for level, basis in basis_scopes.items() if level < heading_level
            }
            decision, decision_basis = _heading_decision(text, heading_level)
            if decision_basis == BASIS_IGNORED:
                # 前言/概述/目录：有意跳过，不产生条目，也不视为内容丢失。
                category_scopes[heading_level] = None
                basis_scopes[heading_level] = BASIS_IGNORED
                continue
            if decision_basis in (BASIS_MAPPING, BASIS_KEYWORD):
                category_scopes[heading_level] = decision
                basis_scopes[heading_level] = decision_basis
                continue
            if heading_level == 1:
                # 一级章节无法按标题判定：保留内容为待确认，绝不静默丢弃。
                category_scopes[1] = UNCLASSIFIED
                basis_scopes[1] = BASIS_UNCLASSIFIED
                continue
            category = active_category()
            if category is None:
                continue
            item_category = _item_category(text)
            if item_category is None and _is_compatibility_statement(text):
                # 兼容性/适用性声明作为小标题出现时，同样归配置/兼容性说明。
                item_category = CONFIG_NOTE
            group = {
                "category": item_category or category,
                "basis": BASIS_ITEM if item_category else active_basis(),
                "title": text,
                "index": index,
                "level": heading_level,
                "body": [],
                "skip_details": False,
            }
            continue
        heading_category = _section_category(text)
        if heading_category is not None:
            flush_group()
            inline_category = heading_category
            continue
        category = active_category()
        if category is None:
            continue
        if _is_placeholder(text):
            continue
        # 图例/引导句/注脚：并入紧邻的变更表条目，而不是自己占一条待确认。
        note_target = note_targets.get(position)
        if group is not None:
            if _is_operation_marker(text):
                group["skip_details"] = True
                continue
            if group["skip_details"]:
                continue
            if note_target is not None:
                add_note(
                    {
                        "text": text,
                        "index": index,
                        "list_level": _list_level(paragraph),
                        "category": group["category"],
                        "basis": group.get("basis", BASIS_CARRIED),
                        "group": group,
                        "target": note_target,
                    }
                )
                continue
            group["body"].append((text, index, _list_level(paragraph)))
            continue
        if note_target is not None:
            add_note(
                {
                    "text": text,
                    "index": index,
                    "list_level": _list_level(paragraph),
                    "category": category,
                    "basis": active_basis(),
                    "group": None,
                    "target": note_target,
                }
            )
            continue
        add_flat_item(category, text, index, _list_level(paragraph), active_basis())
    flush_group()
    # 目标表没生成任何条目（例如该章节无法判定分类）时，注解按原有方式单独成条，
    # 不做静默丢弃。
    for note in pending_notes:
        emit_note_as_item(note)
    return candidates

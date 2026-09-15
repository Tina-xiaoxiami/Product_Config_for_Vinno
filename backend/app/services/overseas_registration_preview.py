"""Read-only preview parsing for overseas registration tracking workbooks."""

from __future__ import annotations

from collections import Counter
import csv
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile

from openpyxl import load_workbook

from app.services.registration_rules import normalize_business_name


_SHEET_DEFAULTS = {
    "已完成注册": ("completed", "unspecified"),
    "进行中-暂未收到销售反馈": ("in_progress", "unspecified"),
    "新地址注册": ("new_address_scope", "new"),
}

_JURISDICTIONS = {
    "阿根廷": "AR",
    "埃及": "EG",
    "澳洲": "AU",
    "澳大利亚": "AU",
    "巴西": "BR",
    "白俄罗斯": "BY",
    "俄罗斯": "RU",
    "菲律宾": "PH",
    "哥伦比亚": "CO",
    "秘鲁": "PE",
    "缅甸": "MM",
    "泰国": "TH",
    "乌克兰": "UA",
    "乌兹别克斯坦": "UZ",
    "印尼": "ID",
    "印度尼西亚": "ID",
    "萨尔瓦多": "SV",
    "哈萨克斯坦": "KZ",
    "埃塞俄比亚": "ET",
    "埃塞": "ET",
    "阿尔及利亚": "DZ",
    "FDA": "US",
    "美国": "US",
    "以色列": "IL",
    "墨西哥": "MX",
    "印度": "IN",
    "波黑": "BA",
    "越南": "VN",
    "台湾": "TW",
    "沙特": "SA",
    "马来西亚": "MY",
    "巴拉圭": "PY",
    "吉尔吉斯斯坦": "KG",
    "孟加拉": "BD",
    "香港": "HK",
    "韩国": "KR",
    "乌拉圭": "UY",
    "厄瓜多尔": "EC",
    "伊拉克": "IQ",
    "尼加拉瓜": "NI",
    "哥斯达黎加": "CR",
    "利比亚": "LY",
    "坦桑尼亚": "TZ",
    "摩洛哥": "MA",
    "塞尔维亚": "RS",
    "巴拿马": "PA",
    "委内瑞拉": "VE",
}

_MODEL_SPLIT = re.compile(r"[，、,;；\n]+")
_PROBE_SPLIT = re.compile(r"[，、,;；\n]+")
_MODEL_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 +._-]*$")
_PROBE_TOKEN = re.compile(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+$")


@dataclass(frozen=True)
class OverseasRegistrationRecord:
    sheet_name: str
    source_row: int
    source_ref: str
    jurisdiction_raw: str
    jurisdiction_name: str | None
    jurisdiction_code: str | None
    authority: str | None
    registration_status: str
    address_version: str
    model_raw: str
    probe_raw: str
    models: tuple[str, ...]
    probes: tuple[str, ...]
    ready_for_import: bool
    issue_codes: tuple[str, ...]
    # 清洗/展开后的文本与「机型 → 探头」对应关系；原始文本仍是证据。
    model_text: str = ""
    probe_text: str = ""
    model_probes: tuple[tuple[str, tuple[str, ...]], ...] = ()
    applied_rules: tuple[str, ...] = ()
    unresolved_rules: tuple[str, ...] = ()


@dataclass(frozen=True)
class OverseasRegistrationRelation:
    jurisdiction_code: str
    model_name: str
    probe_model: str
    registration_status: str
    address_version: str
    source_ref: str


@dataclass(frozen=True)
class OverseasRegistrationPreview:
    source_file: str
    source_sha256: str
    snapshot_date: str | None
    records: tuple[OverseasRegistrationRecord, ...]
    relations: tuple[OverseasRegistrationRelation, ...]
    summary: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class MasterDataMatch:
    source_name: str
    match_status: str
    candidate_names: tuple[str, ...] = ()
    candidate_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class OverseasMasterDataMatchPreview:
    models: tuple[MasterDataMatch, ...]
    probes: tuple[MasterDataMatch, ...]
    summary: dict[str, dict[str, int]]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_date(path: Path) -> str | None:
    match = re.search(r"(?<!\d)(20\d{6})(?!\d)", path.stem)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def _xlrd_cell_value(cell, book):
    """把 xlrd 单元格还原成 openpyxl 写入时合适的 Python 值。"""

    import xlrd

    value = cell.value
    if value in ("", None):
        return None
    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            return xlrd.xldate.xldate_as_datetime(float(value), book.datemode)
        except (ValueError, TypeError):
            return value
    if cell.ctype == xlrd.XL_CELL_NUMBER and float(value).is_integer():
        return int(value)
    return value


_ILLEGAL_SHEET_TITLE = re.compile(r"[\[\]:*?/\\]")


def _safe_sheet_title(name: str, index: int) -> str:
    """把 .xls 的工作表名收敛成 openpyxl 能接受的名字。

    .xls 允许的字符比 .xlsx 多，名字里的 ``[]:*?/\\`` 会让 openpyxl 直接报错，
    这里替换掉；重名和超长交给 openpyxl 自己处理。
    """

    cleaned = _ILLEGAL_SHEET_TITLE.sub("_", name).strip().strip("'")[:31]
    return cleaned or f"Sheet{index + 1}"


def _convert_legacy_xls_with_xlrd(path: Path, directory: Path) -> Path:
    """用 xlrd 读旧版 .xls 并另存成 .xlsx（xlrd 只能读，写由 openpyxl 负责）。"""

    import xlrd
    from openpyxl import Workbook

    book = xlrd.open_workbook(str(path))
    workbook = Workbook()
    workbook.remove(workbook.active)
    for index, sheet in enumerate(book.sheets()):
        target = workbook.create_sheet(title=_safe_sheet_title(sheet.name, index))
        for row_index in range(sheet.nrows):
            for column_index in range(sheet.ncols):
                value = _xlrd_cell_value(
                    sheet.cell(row_index, column_index), book
                )
                if value is not None:
                    target.cell(
                        row=row_index + 1, column=column_index + 1, value=value
                    )
    converted = directory / f"{path.stem}.xlsx"
    workbook.save(converted)
    return converted


def _resolve_parseable_workbook(path: Path, directory: Path) -> Path:
    """返回 openpyxl 能读的工作簿路径。

    ``.xlsx`` 原样返回；``.xls`` 按「xlrd → LibreOffice」的顺序转换到临时目录。
    首选 xlrd：它是几十 KB 的纯 Python 包，不会像 700MB 的桌面套件那样
    「装过又不在 PATH 上」导致整条导入链悄悄断掉。
    """

    if path.suffix.casefold() != ".xls":
        return path
    reasons: list[str] = []
    try:
        return _convert_legacy_xls_with_xlrd(path, directory)
    except ImportError as exc:
        reasons.append(f"xlrd 未安装（{exc}）")
    except Exception as exc:  # 损坏文件等：明确记下来再试下一条路
        reasons.append(f"xlrd 读取失败（{exc}）")
    try:
        return _convert_legacy_xls(path, directory)
    except ValueError as exc:
        reasons.append(str(exc))
    raise ValueError(
        "无法读取 .xls：" + "；".join(reasons)
        + "。请安装 xlrd（推荐：pip install xlrd）或 LibreOffice"
    )


def _convert_legacy_xls(path: Path, directory: Path) -> Path:
    executable = shutil.which("soffice") or shutil.which("libreoffice")
    if executable is None:
        raise ValueError("读取 .xls 需要 LibreOffice/soffice 转换组件")
    result = subprocess.run(
        [
            executable,
            "--headless",
            "--convert-to",
            "xlsx",
            "--outdir",
            str(directory),
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    converted = directory / f"{path.stem}.xlsx"
    if result.returncode != 0 or not converted.is_file():
        message = (result.stderr or result.stdout or "转换失败").strip()
        raise ValueError(f"无法读取旧版 Excel：{message}")
    return converted


def _jurisdiction(value: str) -> tuple[str | None, str | None, str | None]:
    compact = normalize_business_name(value)
    for name in sorted(_JURISDICTIONS, key=len, reverse=True):
        if compact.startswith(name):
            authority = "FDA" if name == "FDA" else None
            display = "美国" if name == "FDA" else name
            return display, _JURISDICTIONS[name], authority
    return None, None, None


def _status(default_status: str, text: str) -> str:
    if re.search(r"不需要注册|不需注册|不注册", text):
        return "not_required"
    if re.search(r"未注册成功|没有注册成功|未注册", text):
        return "failed"
    if re.search(r"暂停注册|停止注册", text):
        return "suspended"
    return default_status


_MODEL_VARIANT_SUFFIXES = {
    "SUPER",
    "ELITE",
    "PRO",
    "PLUS",
    "MAX",
    "EXPERT",
    "PREMIUM",
    "FLAGSHIP",
}


def _split_model_token(part: str) -> tuple[str, ...]:
    """把空格分隔的型号清单再切一刀：``A3 A5 A6`` → 三个型号。

    判据刻意保守，只有同时满足下列条件才切，避免切坏带空格的真实型号名：

    - 至少两段；
    - **每段都含数字** —— 品牌词（``VINNO``、``ULTIMUS``、拼错的 ``Utimus``）没有数字，
      ``VINNO S300`` / ``ULTIMUS 9E`` 因此保持整体；
    - 没有版本后缀词 —— 挡住 ``V10 Super`` 这类；
    - 每段都是合法型号写法 —— 挡住 ``Sg12--- S300:OEM`` 这类混乱单元格。
    """

    parts = [piece for piece in part.split() if piece]
    if len(parts) < 2:
        return (part,)
    if any(not any(character.isdigit() for character in piece) for piece in parts):
        return (part,)
    if any(piece.isdigit() for piece in parts):
        # 段里出现裸数字（如 ``9URM-Ultimus 9``）说明整串是一条乱写记录而不是清单，
        # 宁可不切，留给人工确认。
        return (part,)
    if any(piece.upper() in _MODEL_VARIANT_SUFFIXES for piece in parts):
        return (part,)
    if any(_MODEL_TOKEN.fullmatch(piece) is None for piece in parts):
        return (part,)
    return tuple(parts)


def _split_models(value: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for part in _MODEL_SPLIT.split(value):
        cleaned = part.strip()
        if cleaned:
            tokens.extend(_split_model_token(cleaned))
    return tuple(tokens)


def _split_probes(value: str) -> tuple[str, ...]:
    if value.strip() == "/":
        return ()
    return tuple(part.strip() for part in _PROBE_SPLIT.split(value) if part.strip())


def _has_abbreviated_model_tokens(models: tuple[str, ...]) -> bool:
    if any(model.isdigit() for model in models):
        return True
    if len(models) < 2:
        return False
    first_has_prefix = " " in models[0]
    return first_has_prefix and any(
        re.fullmatch(r"\d+[A-Za-z]?", model) is not None
        for model in models[1:]
    )


def _identity(value: str) -> str:
    return normalize_business_name(value).casefold()


def _model_alias_identity(value: str) -> str:
    compact = re.sub(r"[^A-Z0-9]+", "", normalize_business_name(value).upper())
    if compact.startswith("VINNO"):
        compact = compact[5:]
    if re.fullmatch(r"V\d+[A-Z]?", compact):
        compact = compact[1:]
    return compact


def _edit_distance_at_most_one(left: str, right: str) -> bool:
    left = left.upper()
    right = right.upper()
    if not left or not right or left[0] != right[0]:
        return False
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) == 1
    if len(left) > len(right):
        left, right = right, left
    index_left = index_right = differences = 0
    while index_left < len(left) and index_right < len(right):
        if left[index_left] == right[index_right]:
            index_left += 1
            index_right += 1
            continue
        differences += 1
        if differences > 1:
            return False
        index_right += 1
    return True


_SERIES_PATTERN = re.compile(r"(?i)\bseries\b|系列|全系列")
# 表格自己的注解：与工作表名同源（「新地址注册」）、渠道与认证标记。
_ANNOTATIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[-—–_/]?\s*新地址\s*$"), "新地址"),
    (re.compile(r"[:：]\s*OEM\s*$", re.IGNORECASE), "OEM"),
    (re.compile(r"[-—–_/]?\s*OEM\s*$", re.IGNORECASE), "OEM"),
    (re.compile(r"\+\s*无线认证\s*$"), "无线认证"),
    (re.compile(r"[（(]\s*补充注册\s*[）)]\s*$"), "补充注册"),
)
# 探头列的「/」= 不适用（同一写法里作者自己写了「P:/」），不是"忘了填"。
_PROBE_NONE = {"/", "／"}
_SERIES_BRACKET = re.compile(r"^(?P<name>.+?)\s*[（(](?P<list>[^（()）]*)[)）]\s*$")
_NOTATION_MARKER = re.compile(r"[^\s,、;；/]+")


def series_key(value: object) -> str:
    """系列名的比较键：大小写、空格与全角空格都不算差异。"""

    return re.sub(r"\s+", "", normalize_business_name(value)).casefold()


@dataclass(frozen=True)
class ResolvedRowCells:
    """一行单元格按口径处理之后的结果。

    ``model_text`` / ``probe_text`` 是清洗后的文本（原始文本仍留在记录里作证据）；
    ``applied_rules`` 记录用过哪些口径，``unresolved_rules`` 记录还没解决的部分，
    两者都会写进审核条目，让人看得出系统做了什么、还剩什么。
    """

    model_text: str
    probe_text: str
    models: tuple[str, ...]
    probes: tuple[str, ...]
    model_probes: tuple[tuple[str, tuple[str, ...]], ...]
    applied_rules: tuple[str, ...] = ()
    unresolved_rules: tuple[str, ...] = ()


def _strip_annotations(value: str) -> tuple[str, tuple[str, ...]]:
    text = str(value or "").strip()
    applied: list[str] = []
    changed = True
    while changed:
        changed = False
        for pattern, name in _ANNOTATIONS:
            updated = pattern.sub("", text).strip()
            if updated != text:
                text = updated.rstrip(" ,，、;；-—–_/").strip()
                if name not in applied:
                    applied.append(name)
                changed = True
    return text, tuple(applied)


def _split_model_parts(text: str) -> tuple[str, ...]:
    """按分隔符切开机型写法；括号里的内容算一个整体。

    ``Q series(Q5-2P,Q5-3C,Q5-7L)`` 的括号是表格自己写的展开清单，
    括号里的逗号不能当分隔符，否则这份清单会被切碎。
    """

    guarded = re.sub(
        r"[（(][^（()）]*[)）]",
        lambda match: re.sub(r"[,，、;；]", "\x00", match.group(0)),
        str(text or ""),
    )
    return tuple(
        part.replace("\x00", ",").strip()
        for part in _MODEL_SPLIT.split(guarded)
        if part.strip()
    )


def _expand_model_series(
    model_text: str, series_index: dict[str, tuple[str, ...]]
) -> tuple[
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    dict[str, tuple[str, ...]],
]:
    """把系列写法换成一串机型；返回机型、未展开的原写法、套用/未解决的规则、系列名索引。"""

    models: list[str] = []
    unresolved_parts: list[str] = []
    applied: list[str] = []
    unresolved: list[str] = []
    by_name: dict[str, tuple[str, ...]] = {}
    for part in _split_model_parts(model_text):
        bracket = _SERIES_BRACKET.match(part)
        if bracket is not None and _SERIES_PATTERN.search(bracket.group("name")):
            listed = _split_model_parts(bracket.group("list"))
            if listed:
                name = bracket.group("name").strip()
                models.extend(listed)
                by_name[series_key(name)] = listed
                applied.append(f"series:{name}")
                continue
        if _SERIES_PATTERN.search(part):
            target = series_index.get(series_key(part))
            if target:
                models.extend(target)
                by_name[series_key(part)] = target
                nickname = _SERIES_PATTERN.sub("", part).strip(" -—–_/")
                if nickname:
                    by_name[series_key(nickname)] = target
                applied.append(f"series:{part}")
            else:
                unresolved.append("series")
                # 没展开的原写法照原样留着：界面要让人看见「R series 还没展开」。
                unresolved_parts.append(part)
            continue
        models.extend(_split_models(part))
    return (
        tuple(dict.fromkeys(models)),
        tuple(dict.fromkeys(unresolved_parts)),
        tuple(dict.fromkeys(applied)),
        tuple(dict.fromkeys(unresolved)),
        by_name,
    )


def _notation_groups(
    probe_text: str,
    model_lookup: dict[str, str],
    alias_lookup: dict[str, str],
    series_models: dict[str, tuple[str, ...]],
) -> dict[str, list[str]] | None:
    """解析「机型:探头列表」写法；标记可以是精确机型、别名，或本行出现的系列名。"""

    spans: list[tuple[int, int, tuple[str, ...]]] = []
    for hit in re.finditer(r"[:：]", probe_text):
        head = probe_text[: hit.start()]
        picked: list[tuple[str, int]] = []
        for token in reversed(list(re.finditer(_NOTATION_MARKER, head))):
            value = token.group(0)
            # 精确 → 别名（``E20`` ↔ ``VINNO E20``）→ 本行的系列写法
            canonical = model_lookup.get(value.casefold()) or alias_lookup.get(
                _model_alias_identity(value)
            )
            if canonical is not None:
                picked.insert(0, (canonical, token.start()))
                continue
            series = series_models.get(series_key(value))
            if series is not None:
                picked = [
                    (name, token.start()) for name in series
                ] + picked
                break
            break
        if picked:
            spans.append((picked[0][1], hit.end(), tuple(name for name, _ in picked)))
    if not spans or len(spans) != len(re.findall(r"[:：]", probe_text)):
        # 有冒号没能认出机型（例如机型列写 X2、探头列却写 A5/A6:…）：留给人。
        return None
    groups: dict[str, list[str]] = {}
    for index, (_, end, models) in enumerate(spans):
        stop = spans[index + 1][0] if index + 1 < len(spans) else len(probe_text)
        body = re.split(r"[，、,;；/\s]+", probe_text[end:stop])
        probes = [token for token in body if token]
        for model in models:
            groups.setdefault(model, []).extend(probes)
    return groups


def resolve_overseas_row_cells(
    model_raw: str,
    probe_raw: str,
    *,
    series_mappings: dict[str, tuple[str, ...]] | None = None,
) -> ResolvedRowCells:
    """按确认过的口径处理一行的机型/探头单元格。

    顺序：清洗表内注解 → 展开系列写法 → 解析「机型:探头」→ 处理探头列的「/」。
    处理不了的部分留在 ``unresolved_rules``，由调用方继续标成待确认。
    """

    series_index = {
        series_key(key): tuple(value) for key, value in (series_mappings or {}).items()
    }
    model_text, annotation_rules = _strip_annotations(model_raw)
    probe_text = str(probe_raw or "").strip()
    applied = [f"annotation:{name}" for name in annotation_rules]
    unresolved: list[str] = []

    models, unresolved_parts, series_rules, series_unresolved, series_models = (
        _expand_model_series(model_text, series_index)
    )
    applied.extend(series_rules)
    unresolved.extend(series_unresolved)

    probe_none = probe_text in _PROBE_NONE
    if probe_none:
        applied.append("probe:none")
        probes: tuple[str, ...] = ()
        groups: dict[str, list[str]] | None = None
    elif not probe_text:
        probes = ()
        groups = None
        unresolved.append("probe_blank")
    else:
        probes = _split_probes(probe_text)
        groups = None
        if re.search(r"[:：]", probe_text):
            lookup = {model.casefold(): model for model in models}
            # 别名只收唯一候选：``E20`` 对上 ``VINNO E20`` 是确定的，
            # 一对多就是猜，仍旧交给人。
            candidates: dict[str, list[str]] = {}
            for model in models:
                candidates.setdefault(_model_alias_identity(model), []).append(model)
            aliases = {
                identity: names[0]
                for identity, names in candidates.items()
                if len(names) == 1
            }
            candidate = _notation_groups(probe_text, lookup, aliases, series_models)
            if candidate is None or set(candidate) != set(models):
                unresolved.append("notation")
            else:
                groups = candidate
                applied.append("notation:model_probe")
                flattened = [probe for values in groups.values() for probe in values]
                probes = tuple(dict.fromkeys(flattened))
                if any(not _PROBE_TOKEN.fullmatch(probe) for probe in probes):
                    groups = None
                    unresolved.append("notation")

    if any(not _MODEL_TOKEN.fullmatch(model) for model in models) or (
        models and _has_abbreviated_model_tokens(models)
    ):
        unresolved.append("model")
    # 连写的短横线（``Sg12--- S300``）是把两个东西粘在一起，拆开就是猜，交给人。
    if re.search(r"[-—–]{2,}", model_text):
        unresolved.append("model")
    if probes and any(not _PROBE_TOKEN.fullmatch(probe) for probe in probes):
        unresolved.append("probe")

    if groups is not None:
        model_probes = tuple(
            (model, tuple(dict.fromkeys(groups.get(model, ())))) for model in models
        )
    elif probe_none:
        model_probes = tuple((model, ()) for model in models)
    else:
        model_probes = tuple((model, probes) for model in models)

    return ResolvedRowCells(
        model_text=model_text,
        probe_text=probe_text if not probe_none else "/",
        # 没展开的原写法附在后面：既不静默丢掉，也不会生成关系（有未解决项的行不生成）。
        models=tuple(dict.fromkeys(models + unresolved_parts)),
        probes=probes,
        model_probes=model_probes,
        applied_rules=tuple(applied),
        unresolved_rules=tuple(dict.fromkeys(unresolved)),
    )


def evaluate_overseas_row_issues(
    *,
    jurisdiction_code: str | None,
    status: str,
    model_raw: str,
    probe_raw: str,
    models: tuple[str, ...],
    probes: tuple[str, ...],
    unresolved_rules: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """判定一行是否还需要人工确认。

    ``model_raw`` / ``probe_raw`` 传清洗展开后的文本：注解和系列都已经处理掉的
    行不该再因为"写法"被拦下；``unresolved_rules`` 说明还有哪些写法没解决。
    """

    issues: list[str] = []
    combined = f"{model_raw} {probe_raw}"
    if jurisdiction_code is None:
        issues.append("jurisdiction_requires_mapping")
    if status != "completed":
        issues.append("non_final_status")
    if re.search(r"销售反馈|证书|可直接销售|不需要注册|不需注册", combined):
        issues.append("narrative_rule_requires_review")
    if "series" in unresolved_rules:
        issues.append("model_scope_requires_expansion")
    if "notation" in unresolved_rules:
        issues.append("complex_probe_mapping")
    if "probe_blank" in unresolved_rules:
        issues.append("probe_scope_not_explicit")
    if model_raw and (
        not models
        or "model" in unresolved_rules
        or any(not _MODEL_TOKEN.fullmatch(model) for model in models)
        or _has_abbreviated_model_tokens(models)
        or re.search(r"(?i)VINNNO|\bsere?is\b|\bsries\b", model_raw)
    ):
        issues.append("model_name_requires_review")
    if probes and (
        "probe" in unresolved_rules
        or any(not _PROBE_TOKEN.fullmatch(probe) for probe in probes)
    ):
        issues.append("probe_name_requires_review")
    return tuple(dict.fromkeys(issues))


def _parse_workbook(
    path: Path,
    *,
    series_mappings: dict[str, tuple[str, ...]] | None = None,
) -> tuple[tuple[OverseasRegistrationRecord, ...], tuple[OverseasRegistrationRelation, ...]]:
    workbook = load_workbook(path, read_only=False, data_only=True)
    try:
        available = [name for name in _SHEET_DEFAULTS if name in workbook.sheetnames]
        if not available:
            raise ValueError("未找到海外注册跟踪工作表")

        records: list[OverseasRegistrationRecord] = []
        relations: list[OverseasRegistrationRelation] = []
        for sheet_name in available:
            sheet = workbook[sheet_name]
            default_status, default_address_version = _SHEET_DEFAULTS[sheet_name]
            jurisdiction_raw = ""
            for row in range(2, sheet.max_row + 1):
                country_value = normalize_business_name(sheet.cell(row, 1).value)
                model_raw = normalize_business_name(sheet.cell(row, 2).value)
                probe_raw = normalize_business_name(sheet.cell(row, 3).value)
                if country_value:
                    jurisdiction_raw = country_value
                if not model_raw and not probe_raw:
                    continue
                if not jurisdiction_raw:
                    jurisdiction_raw = country_value

                jurisdiction_name, jurisdiction_code, authority = _jurisdiction(
                    jurisdiction_raw
                )
                row_text = " ".join(
                    value for value in (jurisdiction_raw, model_raw, probe_raw) if value
                )
                registration_status = _status(default_status, row_text)
                address_version = (
                    "new"
                    if sheet_name == "新地址注册" or "新地址" in row_text
                    else default_address_version
                )
                resolved = resolve_overseas_row_cells(
                    model_raw, probe_raw, series_mappings=series_mappings
                )
                models = resolved.models
                probes = resolved.probes
                issue_codes = evaluate_overseas_row_issues(
                    jurisdiction_code=jurisdiction_code,
                    status=registration_status,
                    model_raw=resolved.model_text,
                    probe_raw=resolved.probe_text,
                    models=models,
                    probes=probes,
                    unresolved_rules=resolved.unresolved_rules,
                )
                ready = not issue_codes
                source_ref = f"{sheet_name}!A{row}:C{row}"
                record = OverseasRegistrationRecord(
                    sheet_name=sheet_name,
                    source_row=row,
                    source_ref=source_ref,
                    jurisdiction_raw=jurisdiction_raw,
                    jurisdiction_name=jurisdiction_name,
                    jurisdiction_code=jurisdiction_code,
                    authority=authority,
                    registration_status=registration_status,
                    address_version=address_version,
                    model_raw=model_raw,
                    probe_raw=probe_raw,
                    models=models,
                    probes=probes,
                    ready_for_import=ready,
                    issue_codes=issue_codes,
                    model_text=resolved.model_text,
                    probe_text=resolved.probe_text,
                    model_probes=resolved.model_probes,
                    applied_rules=resolved.applied_rules,
                    unresolved_rules=resolved.unresolved_rules,
                )
                records.append(record)
        return tuple(records), build_overseas_relations(records)
    finally:
        workbook.close()


def build_overseas_relations(
    records,
) -> tuple[OverseasRegistrationRelation, ...]:
    """从已定稿的记录构建「国家－型号－探头」关系。

    只有 ``ready_for_import`` 的记录才生成关系；重复由暂存阶段的唯一约束收敛。
    「机型:探头」写法按每个机型各自的探头清单生成，探头列为「/」的行不生成关系。
    """

    relations: list[OverseasRegistrationRelation] = []
    for record in records:
        if not record.ready_for_import or record.jurisdiction_code is None:
            continue
        if record.model_probes:
            pairs = (
                (model, probe)
                for model, probes in record.model_probes
                for probe in probes
            )
        else:
            pairs = (
                (model, probe) for model in record.models for probe in record.probes
            )
        for model, probe in pairs:
            relations.append(
                OverseasRegistrationRelation(
                    jurisdiction_code=record.jurisdiction_code,
                    model_name=model,
                    probe_model=probe,
                    registration_status=record.registration_status,
                    address_version=record.address_version,
                    source_ref=record.source_ref,
                )
            )
    return tuple(relations)


def build_overseas_registration_preview(
    workbook_path: str | Path,
    *,
    series_mappings: dict[str, tuple[str, ...]] | None = None,
) -> OverseasRegistrationPreview:
    """Parse an overseas tracking workbook without writing registration tables.

    ``series_mappings`` 是人工确认过的「系列 → 机型清单」；不传就按未展开处理，
    这些行会继续留在待确认里。
    """

    source = Path(workbook_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)

    with tempfile.TemporaryDirectory(prefix="overseas-registration-preview-") as temp:
        parse_path = source
        if source.suffix.casefold() == ".xls":
            parse_path = _resolve_parseable_workbook(source, Path(temp))
        records, relations = _parse_workbook(
            parse_path, series_mappings=series_mappings
        )

    status_counts = Counter(record.registration_status for record in records)
    issue_counts = Counter(
        issue for record in records for issue in record.issue_codes
    )
    summary: dict[str, object] = {
        "source_rows": len(records),
        "ready_rows": sum(record.ready_for_import for record in records),
        "review_rows": sum(not record.ready_for_import for record in records),
        "normalized_relations": len(relations),
        "status_counts": dict(sorted(status_counts.items())),
        "issue_counts": dict(sorted(issue_counts.items())),
    }
    return OverseasRegistrationPreview(
        source_file=str(source),
        source_sha256=_sha256(source),
        snapshot_date=_snapshot_date(source),
        records=records,
        relations=relations,
        summary=summary,
    )


def _master_catalog(database_path: str | Path) -> tuple[list, list]:
    """只读读取海外系列机型与探头主数据。"""

    connection = sqlite3.connect(Path(database_path).expanduser().resolve())
    try:
        connection.execute("PRAGMA query_only = ON")
        product_rows = connection.execute(
            """
            SELECT product.id, product.name, product.config_group
            FROM product_models product
            JOIN product_series series ON series.id = product.series_id
            WHERE LOWER(series.name) LIKE '%oversea%'
            ORDER BY product.id
            """
        ).fetchall()
        probe_rows = connection.execute(
            "SELECT id, model_number FROM probe_models ORDER BY id"
        ).fetchall()
    finally:
        connection.close()
    return product_rows, probe_rows


def overseas_master_names(
    database_path: str | Path,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """（海外系列机型名, 探头型号名），供名称纠正判断「系统里已有」用。"""

    product_rows, probe_rows = _master_catalog(database_path)
    return (
        tuple(str(row[1]) for row in product_rows),
        tuple(str(row[1]) for row in probe_rows),
    )


def match_overseas_registration_master_data(
    preview: OverseasRegistrationPreview,
    database_path: str | Path,
) -> OverseasMasterDataMatchPreview:
    """Compare preview names with overseas master data without changing the DB."""

    product_rows, probe_rows = _master_catalog(database_path)

    products_by_name: dict[str, list[tuple[int, str]]] = {}
    products_by_group: dict[str, list[tuple[int, str]]] = {}
    products_by_alias: dict[str, list[tuple[int, str]]] = {}
    for product_id, product_name, config_group in product_rows:
        item = (int(product_id), str(product_name))
        products_by_name.setdefault(_identity(str(product_name)), []).append(item)
        products_by_alias.setdefault(
            _model_alias_identity(str(product_name)), []
        ).append(item)
        if config_group and normalize_business_name(config_group):
            products_by_group.setdefault(_identity(str(config_group)), []).append(item)

    model_issue_codes = {
        "model_name_requires_review",
        "model_scope_requires_expansion",
        "narrative_rule_requires_review",
    }
    model_review_names = {
        model
        for record in preview.records
        if model_issue_codes & set(record.issue_codes)
        for model in record.models
    }
    clean_model_names = {
        model
        for record in preview.records
        if not model_issue_codes & set(record.issue_codes)
        for model in record.models
    }
    model_review_names -= clean_model_names
    source_models = sorted(
        {model for record in preview.records for model in record.models},
        key=str.casefold,
    )
    model_matches: list[MasterDataMatch] = []
    for source_name in source_models:
        identity = _identity(source_name)
        candidates = products_by_name.get(identity, [])
        status = "direct"
        if not candidates:
            candidates = products_by_group.get(identity, [])
            status = "config_group"
        if not candidates:
            candidates = products_by_alias.get(_model_alias_identity(source_name), [])
            status = "alias_candidate"
        if source_name in model_review_names:
            status = "source_review_required"
            candidates = []
        elif not candidates:
            status = "registration_only_candidate"
        model_matches.append(
            MasterDataMatch(
                source_name=source_name,
                match_status=status,
                candidate_names=tuple(item[1] for item in candidates),
                candidate_ids=tuple(item[0] for item in candidates),
            )
        )

    probes_by_name = {
        _identity(str(model_number)): (int(probe_id), str(model_number))
        for probe_id, model_number in probe_rows
    }
    probe_issue_codes = {"complex_probe_mapping", "probe_name_requires_review"}
    probe_review_names = {
        probe
        for record in preview.records
        if probe_issue_codes & set(record.issue_codes)
        for probe in record.probes
    }
    clean_probe_names = {
        probe
        for record in preview.records
        if not probe_issue_codes & set(record.issue_codes)
        for probe in record.probes
    }
    probe_review_names -= clean_probe_names
    source_probes = sorted(
        {probe for record in preview.records for probe in record.probes},
        key=str.casefold,
    )
    probe_matches: list[MasterDataMatch] = []
    for source_name in source_probes:
        direct = probes_by_name.get(_identity(source_name))
        if direct is not None:
            status = "direct"
            candidates = [direct]
        else:
            typo_candidates = [
                item
                for item in probes_by_name.values()
                if _edit_distance_at_most_one(source_name, item[1])
            ]
            if len(typo_candidates) == 1:
                status = "similarity_candidate"
                candidates = typo_candidates
            elif source_name in probe_review_names:
                status = "source_review_required"
                candidates = typo_candidates
            else:
                status = "registration_only_candidate"
                candidates = []
        probe_matches.append(
            MasterDataMatch(
                source_name=source_name,
                match_status=status,
                candidate_names=tuple(item[1] for item in candidates),
                candidate_ids=tuple(item[0] for item in candidates),
            )
        )

    model_counts = Counter(item.match_status for item in model_matches)
    probe_counts = Counter(item.match_status for item in probe_matches)
    return OverseasMasterDataMatchPreview(
        models=tuple(model_matches),
        probes=tuple(probe_matches),
        summary={
            "models": dict(sorted(model_counts.items())),
            "probes": dict(sorted(probe_counts.items())),
        },
    )


def write_overseas_registration_preview(
    preview: OverseasRegistrationPreview,
    output_directory: str | Path,
) -> dict[str, Path]:
    """Write review artifacts only; this function never opens the product database."""

    directory = Path(output_directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    suffix = preview.snapshot_date or "undated"
    json_path = directory / f"overseas-registration-preview-{suffix}.json"
    review_path = directory / f"overseas-registration-review-{suffix}.csv"

    json_path.write_text(preview.to_json() + "\n", encoding="utf-8")
    with review_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "source_ref",
                "jurisdiction_raw",
                "jurisdiction_code",
                "registration_status",
                "address_version",
                "model_raw",
                "probe_raw",
                "issue_codes",
            ]
        )
        for record in preview.records:
            if record.ready_for_import:
                continue
            writer.writerow(
                [
                    record.source_ref,
                    record.jurisdiction_raw,
                    record.jurisdiction_code or "",
                    record.registration_status,
                    record.address_version,
                    record.model_raw,
                    record.probe_raw,
                    ";".join(record.issue_codes),
                ]
            )
    return {"json": json_path, "review_csv": review_path}


def write_overseas_master_data_match_preview(
    matches: OverseasMasterDataMatchPreview,
    output_directory: str | Path,
    *,
    snapshot_date: str | None = None,
) -> Path:
    """Write a compact mapping review sheet without changing master data."""

    directory = Path(output_directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    suffix = snapshot_date or "undated"
    target = directory / f"overseas-registration-master-match-{suffix}.csv"
    with target.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "entity_type",
                "source_name",
                "match_status",
                "candidate_names",
                "candidate_ids",
            ]
        )
        for entity_type, items in (("model", matches.models), ("probe", matches.probes)):
            for item in items:
                writer.writerow(
                    [
                        entity_type,
                        item.source_name,
                        item.match_status,
                        ";".join(item.candidate_names),
                        ";".join(str(value) for value in item.candidate_ids),
                    ]
                )
    return target


_CORRECTED_FILL = "FFF2CC"


def write_overseas_corrected_copy(
    source_path: str | Path,
    *,
    corrections,
    output_directory: str | Path,
    snapshot_date: str | None = None,
) -> Path:
    """另存一份「已标注修改」的副本，**绝不改写受控原件**。

    按名称映射替换单元格文本，改动过的单元格填浅黄并在批注里写明原值，
    便于把修好的表格回流给业务方；原件的 sha256 因此保持有效。
    """

    from openpyxl.comments import Comment
    from openpyxl.styles import PatternFill

    rename = {
        str(item.source_name): str(item.target_name)
        for item in corrections
        if str(item.source_name) != str(item.target_name)
    }
    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    directory = Path(output_directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="overseas-corrected-") as temp:
        parse_path = source
        if source.suffix.casefold() == ".xls":
            parse_path = _resolve_parseable_workbook(source, Path(temp))
        workbook = load_workbook(parse_path)
        try:
            fill = PatternFill("solid", fgColor=_CORRECTED_FILL) if rename else None
            for sheet in workbook.worksheets:
                for row in sheet.iter_rows():
                    for cell in row:
                        value = cell.value
                        if not isinstance(value, str) or not value.strip():
                            continue
                        updated = value
                        for old, new in rename.items():
                            # 词边界：X4-12 → X4-12L，但不会误伤本已正确的 X4-12L
                            updated = re.sub(
                                rf"(?<![0-9A-Za-z]){re.escape(old)}(?![0-9A-Za-z])",
                                new,
                                updated,
                            )
                        if updated == value:
                            continue
                        cell.comment = Comment(f"原值：{value}", "产品配置管理系统")
                        cell.value = updated
                        if fill is not None:
                            cell.fill = fill
            suffix = snapshot_date or datetime.now().strftime("%Y-%m-%d")
            target = directory / f"overseas-registration-corrected-{suffix}.xlsx"
            workbook.save(target)
        finally:
            workbook.close()
    return target

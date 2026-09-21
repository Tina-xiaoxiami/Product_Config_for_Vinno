"""白皮书正文功能名称核对。

白皮书正文里的功能写法通常是「英文缩写 + 中文说法」（如 `VSpeckle 斑点噪声抑制技术`），
还可能带选配标记（如 `集成式小键盘(选配)`）。这里把正文中实际使用的功能写法抽出来，
分别与两个基准比对：功能名称标准表、配置管理中的中文描述/英文描述，任一不一致单独提醒。

写法来源：
- 精确命中：正文里出现某个已知写法（标准名称、功能主数据主名或曾用名、配置管理描述）；
- 上下文命中：英文缩写后面紧跟的中文说法（与任一基准有共同词素时才记录），
  这样「VSpeckle 斑点噪声抑制技术」这类白皮书措辞也能与两个基准比对。

只做提示，不改写白皮书或正式数据。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.feature_name_standards import (
    _classify,
    _load_feature_index,
    audit_feature_names,
    strip_name_markers,
)

MIN_VARIANT_LENGTH = 2
SNIPPET_RADIUS = 40
MAX_SNIPPETS_PER_FEATURE = 2
MAX_CONTEXT_PHRASE_LENGTH = 20
MIN_SHARED_BIGRAMS = 2

SEVERITY_RANK = {"ok": 0, "style": 1, "differs": 2}
_STATUS_SEVERITY = {
    "ok": "ok",
    "undefined": "ok",
    "style": "style",
    "contains": "differs",
    "contained": "differs",
    "differs": "differs",
    "empty": "differs",
}

_CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")
_CJK_RUN_PATTERN = re.compile(r"[\u3400-\u9fff]+")
_LATIN_ONLY_PATTERN = re.compile(r"^[A-Za-z0-9+\-.\s]+$")
_WHITESPACE_PATTERN = re.compile(r"\s+")
# 中文说法后面紧跟的短后缀（3D/4D/2D 这类），用于还原「自由臂 3D」=「自由臂3D」
_SUFFIX_PATTERN = re.compile(r"\s*([A-Za-z0-9]{1,3})(?![A-Za-z0-9])")


@dataclass
class NameVariant:
    """一个可用于在正文里检索的名称写法。"""

    text: str
    feature_id: int
    source: str  # standard / feature / config
    language: str  # cn / en


def _add_variant(bucket: dict[tuple[int, str, str], NameVariant], variant: NameVariant) -> None:
    cleaned = strip_name_markers(variant.text).strip()
    if _CJK_PATTERN.search(cleaned) and _CJK_RUN_PATTERN.fullmatch(cleaned) is None:
        # 历史名称里可能并列多种写法（穿刺引导&穿刺增强），每种都单独作为候选
        for run in _CJK_RUN_PATTERN.findall(cleaned):
            if len(run) >= MIN_VARIANT_LENGTH:
                _add_variant(bucket, NameVariant(run, variant.feature_id, variant.source, "cn"))
        return
    if len(cleaned) < MIN_VARIANT_LENGTH:
        return
    if not _CJK_PATTERN.search(cleaned) and not _LATIN_ONLY_PATTERN.match(cleaned):
        return
    key = (variant.feature_id, variant.source, cleaned.casefold())
    bucket.setdefault(
        key,
        NameVariant(
            text=cleaned,
            feature_id=variant.feature_id,
            source=variant.source,
            language="cn" if _CJK_PATTERN.search(cleaned) else "en",
        ),
    )


def build_name_variants(
    features: dict[int, dict], standard_entry_by_feature: dict[int, dict]
) -> list[NameVariant]:
    """收集所有可以代表某个功能出现在正文里的名称写法。"""

    bucket: dict[tuple[int, str, str], NameVariant] = {}
    for feature_id, feature in features.items():
        for value in (feature["cn_name"], feature["legacy_name"], *feature["names_cn"]):
            if value:
                _add_variant(bucket, NameVariant(value, feature_id, "feature", "cn"))
        for value in (feature["en_name"], *feature["names_en"]):
            if value:
                _add_variant(bucket, NameVariant(value, feature_id, "feature", "en"))
        if feature["config_cn_desc"]:
            _add_variant(bucket, NameVariant(feature["config_cn_desc"], feature_id, "config", "cn"))
        if feature["config_en_desc"]:
            _add_variant(bucket, NameVariant(feature["config_en_desc"], feature_id, "config", "en"))
        entry = standard_entry_by_feature.get(feature_id)
        if entry:
            if entry["cn_name"]:
                _add_variant(bucket, NameVariant(entry["cn_name"], feature_id, "standard", "cn"))
            for value in (entry["en_name"], entry["short_en"]):
                if value:
                    _add_variant(bucket, NameVariant(value, feature_id, "standard", "en"))
    return list(bucket.values())


def _compile_patterns(variants: list[NameVariant]) -> tuple[re.Pattern | None, re.Pattern | None]:
    def _alternation(values: list[str]) -> str:
        escaped = sorted({re.escape(value) for value in values}, key=len, reverse=True)
        return "|".join(escaped)

    latin = [variant.text for variant in variants if variant.language == "en"]
    cjk = [variant.text for variant in variants if variant.language == "cn"]
    latin_pattern = (
        re.compile(rf"(?<![A-Za-z0-9])({_alternation(latin)})(?![A-Za-z0-9])", re.IGNORECASE)
        if latin
        else None
    )
    cjk_pattern = re.compile(_alternation(cjk)) if cjk else None
    return latin_pattern, cjk_pattern


def _snippet(text_value: str, start: int, end: int) -> str:
    left = max(0, start - SNIPPET_RADIUS)
    right = min(len(text_value), end + SNIPPET_RADIUS)
    return _WHITESPACE_PATTERN.sub(" ", text_value[left:right]).strip()


def _with_trailing_suffix(text_value: str, position: int, base: str) -> str:
    """把名称后面紧跟的短后缀（含数字，如 3D）并入名称，空格不影响比对。"""

    match = _SUFFIX_PATTERN.match(text_value[position : position + 4])
    if match and any(character.isdigit() for character in match.group(1)):
        return f"{base}{match.group(1)}"
    return base


def _bigrams(value: str) -> set[str]:
    return {value[index : index + 2] for index in range(len(value) - 1)}


def _context_phrase(text_value: str, position: int, baselines: list[str]) -> str:
    """取英文缩写后面紧跟的中文说法，只在它与某个基准有共同词素时返回。"""

    tail = text_value[position : position + MAX_CONTEXT_PHRASE_LENGTH + 4]
    match = _CJK_RUN_PATTERN.search(tail.lstrip(" \t:：,，、-—"))
    if match is None:
        return ""
    phrase = match.group(0)[:MAX_CONTEXT_PHRASE_LENGTH]
    phrase = _with_trailing_suffix(tail, match.end(), phrase)
    if len(phrase) < MIN_VARIANT_LENGTH:
        return ""
    phrase_bigrams = _bigrams(phrase)
    for baseline in baselines:
        if not baseline:
            continue
        if phrase == baseline:
            return phrase
        if len(phrase_bigrams & _bigrams(baseline)) >= MIN_SHARED_BIGRAMS:
            return phrase
    return ""


async def _load_whitepaper_texts(
    session: AsyncSession, document_id: int | None = None
) -> list[dict]:
    document_filter = " AND d.id = :document_id" if document_id is not None else ""
    chunk_filter = " AND c.document_id = :document_id" if document_id is not None else ""
    params: dict = {"document_id": document_id} if document_id is not None else {}
    documents = (
        await session.execute(
            text(
                f"""
                SELECT d.id, d.title, COALESCE(d.version, '') AS version, d.file_name
                FROM knowledge_documents d
                WHERE d.document_type = 'whitepaper'{document_filter}
                ORDER BY d.id
                """
            ),
            params,
        )
    ).all()
    if not documents:
        return []

    chunk_rows = (
        await session.execute(
            text(
                f"""
                SELECT c.document_id, c.content
                FROM knowledge_document_chunks c
                JOIN knowledge_documents d ON d.id = c.document_id
                WHERE d.document_type = 'whitepaper'{chunk_filter}
                ORDER BY c.document_id, c.chunk_index
                """
            ),
            params,
        )
    ).all()
    texts: dict[int, list[str]] = {}
    for row in chunk_rows:
        texts.setdefault(int(row.document_id), []).append(row.content or "")

    return [
        {
            "id": int(row.id),
            "title": row.title,
            "version": row.version,
            "file_name": row.file_name,
            "text": "\n".join(texts.get(int(row.id), [])),
        }
        for row in documents
    ]


def _verdict(used_values: list[str], baseline_value: str, label: str) -> dict | None:
    """把正文里用到的写法与该基准比对，取差异最大的一种写法作为结论。"""

    baseline_value = strip_name_markers(baseline_value)
    if not baseline_value or not used_values:
        return None
    best: dict | None = None
    for used in used_values:
        severity = _STATUS_SEVERITY.get(_classify(used, baseline_value), "differs")
        candidate = {"severity": severity, "used": used, "baseline": baseline_value}
        if best is None or SEVERITY_RANK[severity] > SEVERITY_RANK[best["severity"]]:
            best = candidate
    if best["severity"] == "ok":
        best["message"] = f"白皮书用词与{label}一致"
    elif best["severity"] == "style":
        best["message"] = (
            f"白皮书用「{best['used']}」与{label}「{best['baseline']}」仅大小写、空格或符号不同"
        )
    else:
        best["message"] = f"白皮书用「{best['used']}」，{label}是「{best['baseline']}」"
    best["label"] = label
    return best


def _combine(verdicts: list[dict], label: str) -> dict | None:
    if not verdicts:
        return None
    worst = max(verdicts, key=lambda value: SEVERITY_RANK[value["severity"]])
    messages = [verdict["message"] for verdict in verdicts if verdict["severity"] != "ok"]
    return {
        "label": label,
        "severity": worst["severity"],
        "message": "；".join(messages) or f"白皮书用词与{label}一致",
        "verdicts": verdicts,
    }


async def audit_whitepaper_names(
    session: AsyncSession,
    *,
    document_id: int | None = None,
    include_matched: bool = False,
    limit: int = 400,
) -> dict:
    """扫描白皮书正文中的功能名称，分别与标准表和配置管理描述比对。"""

    audit = await audit_feature_names(session)
    index = await _load_feature_index(session)
    features = index["features"]
    standard_entry_by_feature = {
        entry["feature_id"]: entry
        for entry in audit["standards"]
        if entry["feature_id"] is not None and entry["severity"] != "ambiguous"
    }
    variants = build_name_variants(features, standard_entry_by_feature)
    latin_pattern, cjk_pattern = _compile_patterns(variants)
    variant_by_text = {variant.text.casefold(): variant for variant in variants}

    entries: list[dict] = []
    document_summaries: list[dict] = []

    for document in await _load_whitepaper_texts(session, document_id):
        text_value = document["text"]
        found: dict[int, list[dict]] = {}

        for pattern in (latin_pattern, cjk_pattern):
            if pattern is None:
                continue
            for match in pattern.finditer(text_value):
                matched_text = match.group(0)
                variant = variant_by_text.get(matched_text.casefold())
                if variant is None:
                    continue
                if variant.language == "cn":
                    matched_text = _with_trailing_suffix(text_value, match.end(), matched_text)
                found.setdefault(variant.feature_id, []).append(
                    {
                        "text": matched_text,
                        "language": variant.language,
                        "snippet": _snippet(text_value, match.start(), match.end()),
                    }
                )

        # 英文缩写后面紧跟的中文说法（白皮书常见写法），与任一基准相关时记录
        if latin_pattern is not None:
            for match in latin_pattern.finditer(text_value):
                variant = variant_by_text.get(match.group(0).casefold())
                if variant is None:
                    continue
                feature = features.get(variant.feature_id)
                if feature is None:
                    continue
                entry = standard_entry_by_feature.get(variant.feature_id)
                phrase = _context_phrase(
                    text_value,
                    match.end(),
                    [
                        feature["cn_name"],
                        strip_name_markers(feature["config_cn_desc"]),
                        strip_name_markers(entry["cn_name"]) if entry else "",
                    ],
                )
                if phrase:
                    found.setdefault(variant.feature_id, []).append(
                        {
                            "text": phrase,
                            "language": "cn",
                            "snippet": _snippet(
                                text_value, match.start(), match.end() + len(phrase)
                            ),
                        }
                    )

        document_differs = 0
        for feature_id, matches in found.items():
            feature = features.get(feature_id)
            if feature is None:
                continue
            used_cn = sorted({match["text"] for match in matches if match["language"] == "cn"})
            used_en = sorted({match["text"] for match in matches if match["language"] == "en"})
            entry = standard_entry_by_feature.get(feature_id)
            standard_cn = strip_name_markers(entry["cn_name"]) if entry else ""
            standard_en = (entry["en_name"] or entry["short_en"]) if entry else ""

            standard_result = _combine(
                [
                    verdict
                    for verdict in (
                        _verdict(used_cn, standard_cn, "功能名称标准表中文名称"),
                        _verdict(used_en, standard_en, "功能名称标准表英文名称"),
                    )
                    if verdict is not None
                ],
                "功能名称标准表",
            )
            config_result = _combine(
                [
                    verdict
                    for verdict in (
                        _verdict(used_cn, feature["config_cn_desc"], "配置管理中文描述"),
                        _verdict(used_en, feature["config_en_desc"], "配置管理英文描述"),
                    )
                    if verdict is not None
                ],
                "配置管理描述",
            )
            severities = [
                result["severity"]
                for result in (standard_result, config_result)
                if result is not None
            ]
            severity = (
                max(severities, key=lambda value: SEVERITY_RANK[value]) if severities else "ok"
            )
            if severity != "ok":
                document_differs += 1
            if severity == "ok" and not include_matched:
                continue
            entries.append(
                {
                    "document_id": document["id"],
                    "document_title": document["title"],
                    "document_version": document["version"],
                    "feature_id": feature_id,
                    "feature_cn_name": feature["cn_name"] or feature["legacy_name"],
                    "feature_en_name": feature["en_name"],
                    "group_name": feature["group_name"],
                    "ipn": feature["config_ipn"],
                    "used_names": sorted({match["text"] for match in matches}),
                    "used_cn": used_cn,
                    "used_en": used_en,
                    "standard": standard_result,
                    "config": config_result,
                    "severity": severity,
                    "snippets": [match["snippet"] for match in matches[:MAX_SNIPPETS_PER_FEATURE]],
                }
            )

        document_summaries.append(
            {
                "document_id": document["id"],
                "document_title": document["title"],
                "document_version": document["version"],
                "mentioned_features": len(found),
                "mismatched_features": document_differs,
            }
        )

    entries.sort(key=lambda item: (item["document_id"], item["feature_id"]))
    # 汇总按全部差异统计，明细按 limit 截断，避免概览数字随分页变化
    summary = {
        "entries": len(entries),
        "standard_differs": sum(
            1
            for entry in entries
            if entry["standard"] and entry["standard"]["severity"] != "ok"
        ),
        "config_differs": sum(
            1 for entry in entries if entry["config"] and entry["config"]["severity"] != "ok"
        ),
        "variants": len(variants),
    }
    entries = entries[:limit]
    return {
        "documents": len(document_summaries),
        "document_summaries": document_summaries,
        "summary": {**summary, "returned": len(entries)},
        "entries": entries,
    }


async def list_whitepaper_documents(session: AsyncSession) -> list[dict]:
    """白皮书清单，供前端选择核对范围。"""

    rows = (
        await session.execute(
            text(
                """
                SELECT d.id, d.title, COALESCE(d.version, '') AS version,
                       (SELECT COUNT(*) FROM knowledge_document_chunks c WHERE c.document_id = d.id) AS chunks
                FROM knowledge_documents d
                WHERE d.document_type = 'whitepaper'
                ORDER BY d.id
                """
            )
        )
    ).all()
    return [
        {
            "id": int(row.id),
            "title": row.title,
            "version": row.version,
            "chunks": int(row.chunks or 0),
        }
        for row in rows
    ]

from __future__ import annotations

import re
from pathlib import Path

from tracker.database import Database
from tracker.domain import canonical_key, excerpt, pair_single_language_items
from tracker.importers.history_excel import read_history_workbook
from tracker.importers.release_notes import (
    ReleaseNoteCandidate,
    classify_release_table,
    extract_docx_fragments,
    extract_docx_tables,
    extract_release_note_candidates,
    file_sha256,
    scan_release_note_directory,
)


LATIN_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+(?:[-/+][A-Za-z0-9]+)*")
GENERIC_ENGLISH_TOKENS = {
    "a",
    "added",
    "and",
    "feature",
    "for",
    "in",
    "new",
    "of",
    "support",
    "supports",
    "the",
    "to",
    "with",
}
LOW_INFORMATION_SHARED_TOKENS = {
    "analysis",
    "auto",
    "data",
    "function",
    "image",
    "mode",
    "optimization",
    "roi",
    "ui",
    "urm",
    "vaid",
    "vaim",
}
SEMANTIC_HINTS = (
    ("剪切波", ("shear wave", "vshear", "pvshear"), 4.0),
    ("校验", ("validate", "validation"), 2.0),
    ("配置", ("config", "configuration"), 2.0),
    ("修复", ("fixed", "fix", "fixed"), 1.5),
    ("冻结", ("freeze", "frozen"), 2.0),
    ("胃排空", ("gastric emptying",), 3.0),
    ("曲线", ("curve",), 1.5),
    ("复核", ("review",), 1.5),
    ("新增功能", ("added feature",), 3.0),
    ("超分辨显微成像", ("urm",), 3.5),
    ("报告", ("report",), 1.5),
    ("记忆", ("memoriz", "remember"), 1.5),
    ("探头", ("probe",), 1.0),
    ("密度", ("density",), 1.5),
    ("速度", ("velocity",), 1.5),
    ("测量", ("measure",), 1.0),
    ("参数", ("parameter",), 1.0),
    ("调节", ("adjust",), 1.0),
    ("甲状腺", ("thyroid",), 3.0),
    ("胆囊", ("gallbladder", "gb"), 3.0),
    ("运动补偿", ("motion compensation",), 3.0),
    ("心电", ("ecg",), 3.0),
    ("快捷键", ("shortcut",), 2.0),
    ("采集", ("acquisition", "capture"), 2.0),
    ("导出", ("export",), 2.0),
    ("图标", ("icon",), 2.0),
)
MINIMUM_VERIFIED_PAIR_SCORE = 3.0


def _semantic_pair_score(cn_text: str, en_text: str) -> float:
    cn_folded = cn_text.casefold()
    en_folded = en_text.casefold()
    cn_tokens = {
        token.casefold()
        for token in LATIN_TOKEN_PATTERN.findall(cn_text)
        if token.casefold() not in GENERIC_ENGLISH_TOKENS
    }
    en_tokens = {
        token.casefold()
        for token in LATIN_TOKEN_PATTERN.findall(en_text)
        if token.casefold() not in GENERIC_ENGLISH_TOKENS
    }
    score = 0.0
    for token in cn_tokens & en_tokens:
        if token in LOW_INFORMATION_SHARED_TOKENS:
            score += 0.5
        else:
            score += 5.0 if any(character.isdigit() for character in token) else 3.5
    for chinese_hint, english_hints, weight in SEMANTIC_HINTS:
        if chinese_hint in cn_folded and any(hint in en_folded for hint in english_hints):
            score += weight
    return score


def _alignment_confidence(cn_text: str, en_text: str, score: float) -> float:
    if not cn_text or not en_text:
        return 0.5
    if score >= 7:
        return 0.95
    if score >= 3:
        return 0.85
    if score > 0:
        return 0.75
    return 0.6


def align_bilingual_texts(
    chinese: list[str], english: list[str]
) -> list[tuple[str, str, float]]:
    """Globally align bilingual items using semantic anchors while preserving order."""
    cn_count, en_count = len(chinese), len(english)
    gap_penalty = 2.0
    scores = [[0.0] * (en_count + 1) for _ in range(cn_count + 1)]
    operations = [[""] * (en_count + 1) for _ in range(cn_count + 1)]
    for cn_index in range(1, cn_count + 1):
        scores[cn_index][0] = scores[cn_index - 1][0] - gap_penalty
        operations[cn_index][0] = "skip_cn"
    for en_index in range(1, en_count + 1):
        scores[0][en_index] = scores[0][en_index - 1] - gap_penalty
        operations[0][en_index] = "skip_en"

    for cn_index in range(1, cn_count + 1):
        for en_index in range(1, en_count + 1):
            pair_score = _semantic_pair_score(
                chinese[cn_index - 1], english[en_index - 1]
            )
            order_penalty = 0.01 * abs(cn_index - en_index)
            options = (
                (
                    scores[cn_index - 1][en_index - 1] + pair_score - order_penalty
                    if pair_score >= MINIMUM_VERIFIED_PAIR_SCORE
                    else float("-inf"),
                    "match",
                ),
                (scores[cn_index][en_index - 1] - gap_penalty, "skip_en"),
                (scores[cn_index - 1][en_index] - gap_penalty, "skip_cn"),
            )
            scores[cn_index][en_index], operations[cn_index][en_index] = max(
                options, key=lambda option: option[0]
            )

    aligned: list[tuple[str, str, float]] = []
    cn_index, en_index = cn_count, en_count
    while cn_index or en_index:
        operation = operations[cn_index][en_index]
        if operation == "match":
            cn_text = chinese[cn_index - 1]
            en_text = english[en_index - 1]
            pair_score = _semantic_pair_score(cn_text, en_text)
            aligned.append(
                (cn_text, en_text, _alignment_confidence(cn_text, en_text, pair_score))
            )
            cn_index -= 1
            en_index -= 1
        elif operation == "skip_cn":
            aligned.append((chinese[cn_index - 1], "", 0.5))
            cn_index -= 1
        else:
            aligned.append(("", english[en_index - 1], 0.5))
            en_index -= 1
    aligned.reverse()
    return aligned


def import_history_releases(database: Database, path: str | Path) -> dict[str, int]:
    """Import the curated legacy workbook without modifying or duplicating it."""
    imported_releases = 0
    imported_changes = 0
    known_versions = {release["version"] for release in database.list_releases()}
    for historical in read_history_workbook(path):
        if historical.version not in known_versions:
            imported_releases += 1
            known_versions.add(historical.version)
        release_id = database.upsert_release(
            historical.version,
            domestic_release_date=historical.release_date,
            notes="历史版本发布记录.xls 导入",
        )
        for category, texts in historical.changes.items():
            for text in texts:
                identity = canonical_key(category, text)
                if database.has_change(release_id, category, identity):
                    continue
                database.add_change(
                    release_id=release_id,
                    category=category,
                    title_cn=text,
                    canonical_key=identity,
                    review_status="approved",
                    confidence=1.0,
                )
                imported_changes += 1
    return {"releases": imported_releases, "changes": imported_changes}


def _by_category(candidates: list[ReleaseNoteCandidate]) -> dict[str, list[ReleaseNoteCandidate]]:
    result: dict[str, list[ReleaseNoteCandidate]] = {}
    for candidate in candidates:
        result.setdefault(candidate.category, []).append(candidate)
    return result


def _category_evidence(
    extracted: dict[str, list[ReleaseNoteCandidate]],
) -> dict[str, set[str]]:
    evidence: dict[str, set[str]] = {}
    for candidates in extracted.values():
        for candidate in candidates:
            evidence.setdefault(candidate.text, set()).add(candidate.category)
    return evidence


def _pairing_key(item: ReleaseNoteCandidate) -> str:
    """中英配对使用的文本。

    配置表行按「型号（V代码）」配对：适用性符号（X/O/△）与图例在两侧几乎相同，
    若用整段说明参与配对，会把不相干的两行配成一对。
    """
    return item.pair_text or item.text


def _items_by_pairing_key(
    items: list[ReleaseNoteCandidate],
) -> dict[str, list[ReleaseNoteCandidate]]:
    grouped: dict[str, list[ReleaseNoteCandidate]] = {}
    for item in items:
        grouped.setdefault(_pairing_key(item), []).append(item)
    return grouped


def _cross_language_duplicate_issues(
    category: str, aligned: list[tuple[str, str, float]]
) -> list[str]:
    """列出疑似同一变更的中英两条，供人工一次判定是否合并。

    为什么不自动合并：合并一旦配错，代价是**静默丢失内容**；而分开保留的代价只是
    审核时多看到一条。因此这里只把疑似配对讲清楚，不改变候选生成结果。

    配对规则来自 `domain.pair_single_language_items`（唯一实现）：同一分类下中英两侧
    **未配对数量相等**时按文档顺序 1:1 列出，数量不等则不做任何推测。审核界面上的
    「确认合并」按钮用同一规则重算剩余组，所以合并一组之后提醒就会少一组。
    """
    cn_only = [cn for cn, en, _ in aligned if cn and not en]
    en_only = [en for cn, en, _ in aligned if en and not cn]
    return [
        f"{category} 分类疑似同一变更（中英各一条，请确认是否合并为一条）："
        f"{excerpt(cn_text)} ↔ {excerpt(en_text)}"
        for cn_text, en_text in pair_single_language_items(cn_only, en_only)
    ]


def _missing_language(extracted: dict[str, list[ReleaseNoteCandidate]]) -> str | None:
    """整个版本只导入了一门语言时返回缺少的那一门（否则 None）。

    这跟「双语都在、只是某几条配不上」是两回事：1.51.90 就只导入了中文册，
    英文册在整个资料目录里不存在。此时按分类逐条报「未能证实为同义」会把
    「缺一整本册子」说成「有 96 条配不上」，既看不懂也没法处理。
    """

    for language in ("cn", "en"):
        if not extracted.get(language):
            return language
    return None


def _single_language_issue(
    missing: str, staged: list[dict[str, object]]
) -> list[str]:
    """把「缺一门语言」写成一条可行动的提示，而不是几十条无法处理的条目。"""

    present = "中文" if missing == "en" else "英文"
    absent = "英文" if missing == "en" else "中文"
    single = [
        item
        for item in staged
        if (item["title_cn"] and not item["title_en"])
        or (item["title_en"] and not item["title_cn"])
    ]
    if not single:
        return []
    return [
        f"本版本只导入了{present} Release Note，没有{absent}册："
        f"抽取到的 {len(single)} 条记录只有{present}，不会自动补{absent}。"
        f"要么补导入{absent}最终版 Release Note 后重新导入，"
        f"要么先把这些条目按推荐处置记入版本变更。"
    ]


def _build_staged_candidates(
    extracted: dict[str, list[ReleaseNoteCandidate]],
) -> tuple[list[dict[str, object]], list[str]]:
    cn_by_category = _by_category(extracted["cn"])
    en_by_category = _by_category(extracted["en"])
    missing_language = _missing_language(extracted)
    staged_candidates: list[dict[str, object]] = []
    issues: list[str] = []
    for category in sorted(set(cn_by_category) | set(en_by_category)):
        cn_items = cn_by_category.get(category, [])
        en_items = en_by_category.get(category, [])
        cn_lookup = _items_by_pairing_key(cn_items)
        en_lookup = _items_by_pairing_key(en_items)
        aligned = align_bilingual_texts(
            [_pairing_key(item) for item in cn_items],
            [_pairing_key(item) for item in en_items],
        )
        unverified_count = sum(1 for cn_text, en_text, _ in aligned if not cn_text or not en_text)
        # 缺整册时不报「配不上」：那不是配对问题，报出来只会变成噪音。
        if unverified_count and missing_language is None:
            issues.append(
                f"{category} 分类有 {unverified_count} 条中英文原文未能证实为同义，已分开保留。"
            )
        issues.extend(_cross_language_duplicate_issues(category, aligned))
        for cn_key, en_key, confidence in aligned:
            cn_item = cn_lookup[cn_key].pop(0) if cn_key else None
            en_item = en_lookup[en_key].pop(0) if en_key else None
            staged_candidates.append(
                {
                    "category": category,
                    "title_cn": cn_item.title if cn_item else "",
                    "title_en": en_item.title if en_item else "",
                    # 原文保存完整证据（含表格行的适用配置与说明行），不因配对键而截断。
                    "raw_cn": cn_item.text if cn_item else "",
                    "raw_en": en_item.text if en_item else "",
                    "confidence": confidence,
                }
            )
    if missing_language is not None:
        issues.extend(_single_language_issue(missing_language, staged_candidates))
    return staged_candidates, issues


def _repair_pending_alignment(database: Database, release_id: int) -> None:
    pending = database.list_pending_candidates_for_release(release_id)
    by_category: dict[str, list[dict[str, object]]] = {}
    for candidate in pending:
        by_category.setdefault(str(candidate["category"]), []).append(candidate)
    for candidates in by_category.values():
        if any(
            candidate["manually_edited"]
            or candidate["title_cn"] != candidate["raw_cn"]
            or candidate["title_en"] != candidate["raw_en"]
            for candidate in candidates
        ):
            continue
        chinese = [str(item["raw_cn"]) for item in candidates if item["raw_cn"]]
        english = [str(item["raw_en"]) for item in candidates if item["raw_en"]]
        aligned = align_bilingual_texts(chinese, english)
        old_pairs = [(item["raw_cn"], item["raw_en"]) for item in candidates]
        new_pairs = [(cn_text, en_text) for cn_text, en_text, _confidence in aligned]
        if old_pairs == new_pairs:
            continue
        old_score = sum(_semantic_pair_score(cn_text, en_text) for cn_text, en_text in old_pairs)
        new_score = sum(_semantic_pair_score(cn_text, en_text) for cn_text, en_text in new_pairs)
        old_has_unverified_pair = any(
            cn_text and en_text and _semantic_pair_score(cn_text, en_text) < MINIMUM_VERIFIED_PAIR_SCORE
            for cn_text, en_text in old_pairs
        )
        if not old_has_unverified_pair and new_score < old_score + 6:
            continue
        database.replace_pending_candidate_alignment(candidates, aligned)


def preview_release_notes(
    root: str | Path, file_keywords: list[str] | None = None
) -> dict[str, object]:
    pairs = scan_release_note_directory(root, file_keywords=file_keywords)
    return {
        "versions_found": len(pairs),
        "ready_pairs": sum(pair.status == "ready" for pair in pairs),
        "needs_review": sum(pair.status != "ready" for pair in pairs),
        "versions": [
            {
                "version": pair.version,
                "status": pair.status,
                "chinese_file": pair.chinese_path.name if pair.chinese_path else None,
                "english_file": pair.english_path.name if pair.english_path else None,
                "issues": list(pair.issues),
                "warnings": list(pair.warnings),
            }
            for pair in pairs
        ],
    }


def stage_release_notes(
    database: Database,
    root: str | Path,
    project_id: int | None = None,
    file_keywords: list[str] | None = None,
    ready_only: bool = False,
    versions: set[str] | None = None,
) -> dict[str, int]:
    """Create bilingual review candidates from configured final release notes.

    `versions` 只用于**限定的重扫**（例如规则修正后只重扫已在库版本）；默认 None
    表示不限制。全新版本目录是否入库属于业务决定，不应被一次规则重扫顺带带进来。
    """
    pairs = scan_release_note_directory(root, file_keywords=file_keywords)
    if versions is not None:
        pairs = [pair for pair in pairs if pair.version in versions]
    stats = {
        "versions_found": len(pairs),
        "ready_pairs": sum(pair.status == "ready" for pair in pairs),
        "needs_review": sum(pair.status != "ready" for pair in pairs),
        "candidates_created": 0,
        "auto_approved": 0,
        "categories_corrected": 0,
        "candidates_removed": 0,
        "versions_skipped_empty": 0,
        "review_decisions_recorded": 0,
        "review_decisions_unmatched": 0,
    }
    pairs_to_stage = (
        [pair for pair in pairs if pair.status == "ready"] if ready_only else pairs
    )
    for pair in pairs_to_stage:
        if pair.chinese_path is None and pair.english_path is None:
            # 该版本目录下没有可用的最终版文件（例如文件放在子目录、或只有非 Release
            # Note 文档）。此处**不建立空版本行**，避免污染版本列表；缺失情况由
            # pair.issues 与 stats 反映，供人工处理。
            stats["versions_skipped_empty"] += 1
            continue
        release_id = database.upsert_release(pair.version, project_id=project_id)
        language_inputs = (("cn", pair.chinese_path), ("en", pair.english_path))
        extracted: dict[str, list[ReleaseNoteCandidate]] = {"cn": [], "en": []}
        sources: list[dict[str, object]] = []
        any_new_source = False
        for language, path in language_inputs:
            if path is None:
                continue
            digest = file_sha256(path)
            content = "\n".join(
                str(fragment["text"]) for fragment in extract_docx_fragments(path)
            )
            tables = extract_docx_tables(path)
            sources.append(
                {
                    "path": str(path),
                    "language": language,
                    "sha256": digest,
                    "content": content,
                    "tables": tables,
                    "structured_tables": [
                        classify_release_table(table, language) for table in tables
                    ],
                }
            )
            any_new_source = any_new_source or not database.has_source_document(str(path), digest)
        for language, path in language_inputs:
            if path is not None:
                extracted[language] = extract_release_note_candidates(path, language)
        stats["categories_corrected"] += database.correct_pending_candidate_categories(
            release_id, _category_evidence(extracted)
        )
        staged_candidates, semantic_issues = _build_staged_candidates(extracted)
        database.stage_release_pair(release_id, sources, [*pair.issues, *semantic_issues], [])
        # 重扫会重建 pending 行与 approved bug 行。先按原文指纹存档已有审核结论，
        # 使结论不依赖候选行 ID 而存活（见 Database.record_review_decisions）。
        stats["review_decisions_recorded"] += database.record_review_decisions(
            release_id
        )["recorded"]
        synced = database.sync_word_candidates(release_id, staged_candidates)
        if any_new_source:
            stats["candidates_created"] += synced["pending"]
        stats["candidates_removed"] += synced["removed"]
        stats["auto_approved"] += synced["auto_approved"]
        # 重扫后按原文指纹核对：对不上当前候选的结论显式报告，供人工复核。
        stats["review_decisions_unmatched"] += len(
            database.unmatched_review_decisions(pair.version)
        )
    return stats


def review_import_candidate(
    database: Database,
    candidate_id: int,
    decision: str,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    if decision not in {"approve", "reject", "restore"}:
        raise ValueError(f"Unsupported decision: {decision}")
    candidate = database.get_import_candidate(candidate_id)
    if decision == "restore":
        if candidate["status"] == "rejected":
            database.set_import_candidate_status(candidate_id, "pending")
            return {"candidate_id": candidate_id, "status": "pending"}
        return {"candidate_id": candidate_id, "status": candidate["status"]}
    if candidate["status"] != "pending":
        return {"candidate_id": candidate_id, "status": candidate["status"]}
    if decision == "reject":
        database.set_import_candidate_status(candidate_id, "rejected")
        return {"candidate_id": candidate_id, "status": "rejected"}

    title = candidate["title_cn"] or candidate["title_en"]
    feature_data = payload if payload and payload.get("promote_to_feature") else None
    return database.approve_import_candidate(
        candidate_id,
        canonical_key(candidate["category"], title),
        feature_data=feature_data,
    )

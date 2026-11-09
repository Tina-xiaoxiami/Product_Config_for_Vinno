"""解析并导入已经由产品负责人确认的产品状态记录。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
import re
from typing import Any

from tracker.database import Database


EXPECTED_MODELS = (
    "VINNO 10E",
    "VINNO 10",
    "VINNO 10P",
    "VINNO 9E",
    "VINNO 9",
    "VINNO 9P",
    "VINNO 9 综合版",
)
RELEASE_STATUS_CODES = {"已发布": "released"}
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _stable_source_ref(path: Path) -> str:
    """返回可展示、可迁移且不包含用户目录的来源标识。"""
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return resolved.name


def _metadata(text: str, label: str) -> str:
    match = re.search(rf"^{re.escape(label)}：(.+)$", text, re.MULTILINE)
    if not match:
        raise ValueError(f"来源缺少{label}。")
    return match.group(1).strip()


def _date_metadata(text: str, label: str) -> str:
    value = _metadata(text, label)
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"来源中的{label}必须是 YYYY-MM-DD 日期。") from error
    return value


def parse_product_state_source(text: str, source_ref: str) -> list[dict[str, Any]]:
    """解析确认记录；缺字段、未确认或机型集合漂移时立即停止。"""
    if _metadata(text, "状态") != "已确认":
        raise ValueError("产品状态来源必须标记为已确认。")
    reviewed_by = _metadata(text, "确认人")
    reviewed_at = _date_metadata(text, "确认日期")
    market = _metadata(text, "适用市场")
    effective_at = _date_metadata(text, "正式发布日期/生效日期")
    if market != "中国国内版":
        raise ValueError(f"当前导入只接受中国国内版，收到：{market}")

    rows: list[tuple[str, str, str, str]] = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or cells[0] not in EXPECTED_MODELS:
            continue
        rows.append((cells[0], cells[1], cells[2], cells[3]))
    if tuple(row[0] for row in rows) != EXPECTED_MODELS:
        raise ValueError("确认记录必须完整包含约定的 7 个知识库机型，且顺序与来源表一致。")

    records: list[dict[str, Any]] = []
    for model, version, release_label, knowledge_status in rows:
        if knowledge_status != "已确认":
            raise ValueError(f"{model} 的知识状态不是已确认。")
        release_status = RELEASE_STATUS_CODES.get(release_label)
        if not release_status:
            raise ValueError(f"{model} 使用了未登记的发布状态：{release_label}")
        records.append(
            {
                "market_code": "CN",
                "model_name": model,
                "software_version": version,
                "release_status": release_status,
                "effective_date": effective_at,
                "source_ref": source_ref,
                "evidence_excerpt": (
                    f"{model} 当前正式软件版本为 {version}，当前发布状态为{release_label}。"
                ),
                "reviewed_by": reviewed_by,
                "reviewed_at": reviewed_at,
            }
        )
    return records


def import_product_state_source(
    database: Database, source: str | Path, *, apply: bool = False
) -> dict[str, Any]:
    path = Path(source)
    records = parse_product_state_source(
        path.read_text(encoding="utf-8"), _stable_source_ref(path)
    )
    result = {"found": len(records), "created": 0, "skipped": 0, "applied": apply}
    if not apply:
        return result

    existing = database.list_product_states()
    for record in records:
        duplicate = next(
            (
                row
                for row in existing
                if row["market_code"] == record["market_code"]
                and row["model_name"] == record["model_name"]
                and row["software_version"] == record["software_version"]
                and row["release_status"] == record["release_status"]
                and row["effective_date"] == record["effective_date"]
                and row["source_ref"] == record["source_ref"]
                and row["reviewed_at"] == record["reviewed_at"]
                and row["record_status"] in {"current", "superseded"}
            ),
            None,
        )
        if duplicate:
            result["skipped"] += 1
            continue
        state_id = database.propose_product_state(
            market_code=record["market_code"],
            model_name=record["model_name"],
            software_version=record["software_version"],
            release_status=record["release_status"],
            effective_date=record["effective_date"],
            source_ref=record["source_ref"],
            evidence_excerpt=record["evidence_excerpt"],
        )
        database.approve_product_state(
            state_id,
            reviewed_by=record["reviewed_by"],
            reviewed_at=record["reviewed_at"],
            review_note="按产品负责人确认记录导入历史基线",
        )
        result["created"] += 1
        existing = database.list_product_states()
    return result

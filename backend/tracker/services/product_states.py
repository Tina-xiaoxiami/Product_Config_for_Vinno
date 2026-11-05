"""产品状态只读查询：显式事实、核验时效与完整历史。"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from tracker.database import Database


MARKET_LABELS = {"CN": "中国国内版"}
RELEASE_STATUS_LABELS = {"released": "已发布"}
RECORD_STATUS_LABELS = {
    "pending": "待审核",
    "current": "当前有效",
    "superseded": "已被新状态替代",
    "invalidated": "已失效",
    "rejected": "已驳回",
}
FRESHNESS_LABELS = {
    "current": "当前已核验",
    "expired": "已过复核期限",
    "pending_review": "待审核",
    "historical": "历史记录",
    "invalidated": "已失效",
    "rejected": "已驳回",
}


def _checked_at() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _freshness(row: dict[str, Any], today: date) -> str:
    status = row["record_status"]
    if status == "pending":
        return "pending_review"
    if status == "invalidated":
        return "invalidated"
    if status == "rejected":
        return "rejected"
    if status == "superseded":
        return "historical"
    valid_until = row.get("valid_until")
    if valid_until and date.fromisoformat(valid_until) < today:
        return "expired"
    return "current"


def _present(row: dict[str, Any], today: date) -> dict[str, Any]:
    result = dict(row)
    result["release_status_label"] = RELEASE_STATUS_LABELS.get(
        row["release_status"], row["release_status"]
    )
    result["record_status_label"] = RECORD_STATUS_LABELS.get(
        row["record_status"], row["record_status"]
    )
    result["freshness"] = _freshness(row, today)
    result["freshness_label"] = FRESHNESS_LABELS[result["freshness"]]
    return result


def product_state_options(database: Database) -> dict[str, Any]:
    rows = database.list_product_states()
    market_codes = sorted({row["market_code"] for row in rows})
    return {
        "markets": [
            {"code": code, "label": MARKET_LABELS.get(code, code)} for code in market_codes
        ],
        "models": sorted({row["model_name"] for row in rows}),
    }


def product_states(
    database: Database,
    *,
    market_code: str = "CN",
    model_name: str = "",
    today: date | None = None,
) -> dict[str, Any]:
    """返回状态与历史；只读 `kh_product_states`，不查看 releases 最大版本。"""
    reference_date = today or date.today()
    market = str(market_code or "CN").strip() or "CN"
    model = str(model_name or "").strip()
    rows = database.list_product_states(market_code=market, model_name=model or None)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["model_name"]].append(_present(row, reference_date))

    models: list[dict[str, Any]] = []
    for name in sorted(grouped):
        history = grouped[name]
        pending = [row for row in history if row["record_status"] == "pending"]
        active = next((row for row in history if row["record_status"] == "current"), None)
        current = active if active and active["freshness"] == "current" else None
        latest = active or next(
            (row for row in history if row["record_status"] not in {"pending", "rejected"}),
            pending[0] if pending else None,
        )
        models.append(
            {
                "model_name": name,
                "current": current,
                "latest": latest,
                "pending": pending,
                "history": history,
            }
        )

    summary = {
        "models": len(models),
        "current": sum(item["current"] is not None for item in models),
        "expired": sum(
            item["latest"] is not None and item["latest"]["freshness"] == "expired"
            for item in models
        ),
        "pending_review": sum(len(item["pending"]) for item in models),
        "without_current": sum(item["current"] is None for item in models),
    }
    return {
        "scope": {
            "market_code": market,
            "market_label": MARKET_LABELS.get(market, market),
            "model": model,
        },
        "summary": summary,
        "models": models,
        "checked_at": _checked_at(),
        "empty_reason": (
            "尚未登记该范围的已审核产品状态；系统不会从最大版本号推断当前版本或发布状态。"
            if not models
            else ""
        ),
    }

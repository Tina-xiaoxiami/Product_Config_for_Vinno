from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Any


DOMESTIC_V10_SERIES = "R&V10 series-China"

_DERIVATIVE_MODEL_ALIASES = {
    "vinno 9_private": "VINNO 9 综合版",
    "vinno 9 综合版": "VINNO 9 综合版",
}
_DERIVATIVE_SOURCE_MODELS = {
    "VINNO 9 综合版": ("VINNO 9_Private", "VINNO 9 综合版"),
}
_REGISTRATION_BASE_MODELS = {
    "VINNO 9 综合版": "VINNO 9",
}
_STRATEGIES = {
    "X": ("standard", "标配"),
    "O": ("optional", "选配"),
    "Δ": ("tender_support", "招标支持"),
}
_UNDEFINED_VALUES = {"", "N/A", "未定义"}


class ProductStrategySourceUnavailable(RuntimeError):
    pass


def _checked_at() -> str:
    """本次只读读取的时间（带本地时区偏移），与快照的采集时间区分开。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _clean_config_value(value: Any) -> str:
    cleaned = str(value or "").strip()
    if cleaned == "∆":
        return "Δ"
    return cleaned


def _is_defined(value: str) -> bool:
    return value not in _UNDEFINED_VALUES


class ProductStrategyReader:
    """Read formal product strategies without modifying the source system."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        if not self.database_path.is_file():
            raise ProductStrategySourceUnavailable(
                "产品配置管理系统数据库未找到，请检查 PRODUCT_CONFIG_DATABASE。"
            )
        connection = sqlite3.connect(
            f"{self.database_path.resolve().as_uri()}?mode=ro",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection

    def query(
        self,
        *,
        market: str,
        model: str,
        query: str = "",
    ) -> dict[str, Any]:
        normalized_market = market.strip().casefold() or "domestic"
        if normalized_market != "domestic":
            raise ValueError("阶段0只开放国内版产品策略查询。")

        requested_model = model.strip()
        if not requested_model:
            raise ValueError("model is required")

        canonical_model = _DERIVATIVE_MODEL_ALIASES.get(
            requested_model.casefold(), requested_model
        )
        source_model_names = _DERIVATIVE_SOURCE_MODELS.get(
            canonical_model, (canonical_model,)
        )

        with closing(self._connect()) as connection:
            source_models = self._find_source_models(
                connection, source_model_names
            )
            if not source_models:
                raise ValueError(
                    f"国内 V10 配置中未找到机型：{requested_model}"
                )
            rows = self._query_values(
                connection,
                [item["id"] for item in source_models],
                query.strip(),
            )

        items = self._merge_items(rows)
        displayed_model = (
            canonical_model
            if canonical_model in _DERIVATIVE_SOURCE_MODELS
            else source_models[0]["name"]
        )
        return {
            "scope": {
                "market": "domestic",
                "market_label": "国内版",
                "series": DOMESTIC_V10_SERIES,
                "model": displayed_model,
                "registration_model": _REGISTRATION_BASE_MODELS.get(
                    displayed_model, displayed_model
                ),
                "source_models": source_models,
            },
            "items": items,
            "source": {
                "system": "产品配置管理系统",
                "mode": "read_only",
                "selection_field": "selection_config",
                "current_field": "current_config",
                "checked_at": _checked_at(),
            },
        }

    def list_models(self) -> dict[str, Any]:
        """列出国内 V10 可选机型，供查询页做机型下拉；只读直连，不读快照。"""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT m.id, m.name
                FROM product_models m
                JOIN product_series s ON s.id = m.series_id
                WHERE s.name = ?
                ORDER BY m.id
                """,
                (DOMESTIC_V10_SERIES,),
            ).fetchall()
        return {
            "market": "domestic",
            "market_label": "国内版",
            "series": DOMESTIC_V10_SERIES,
            "source": {
                "system": "产品配置管理系统",
                "mode": "read_only",
                "checked_at": _checked_at(),
            },
            "models": [{"id": row["id"], "name": row["name"]} for row in rows],
        }

    @staticmethod
    def _find_source_models(
        connection: sqlite3.Connection,
        model_names: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        placeholders = ", ".join("?" for _ in model_names)
        rows = connection.execute(
            f"""
            SELECT m.id, m.name
            FROM product_models m
            JOIN product_series s ON s.id = m.series_id
            WHERE s.name = ?
              AND m.name COLLATE NOCASE IN ({placeholders})
            ORDER BY m.id
            """,
            (DOMESTIC_V10_SERIES, *model_names),
        ).fetchall()
        return [{"id": row["id"], "name": row["name"]} for row in rows]

    @staticmethod
    def _query_values(
        connection: sqlite3.Connection,
        model_ids: list[int],
        query: str,
    ) -> list[sqlite3.Row]:
        placeholders = ", ".join("?" for _ in model_ids)
        parameters: list[Any] = [*model_ids]
        filter_sql = ""
        if query:
            like = f"%{query}%"
            filter_sql = """
              AND (
                    ci.rd_name LIKE ? COLLATE NOCASE
                 OR ci.v_code LIKE ? COLLATE NOCASE
                 OR ci.zh_desc LIKE ? COLLATE NOCASE
                 OR ci.en_desc LIKE ? COLLATE NOCASE
                 OR ci.category LIKE ? COLLATE NOCASE
              )
            """
            parameters.extend([like] * 5)
        return connection.execute(
            f"""
            SELECT
                ci.id AS item_id,
                ci.category,
                ci.rd_name,
                ci.v_code,
                ci.zh_desc,
                ci.en_desc,
                m.id AS model_id,
                m.name AS model_name,
                cv.current_config,
                cv.final_config,
                cv.selection_config,
                cv.rd_status
            FROM config_values cv
            JOIN config_items ci ON ci.id = cv.item_id
            JOIN product_models m ON m.id = cv.model_id
            WHERE cv.model_id IN ({placeholders})
            {filter_sql}
            ORDER BY ci.id, m.id
            """,
            parameters,
        ).fetchall()

    @classmethod
    def _merge_items(cls, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        grouped: dict[int, list[sqlite3.Row]] = defaultdict(list)
        for row in rows:
            grouped[row["item_id"]].append(row)
        return [cls._merge_item(grouped[item_id]) for item_id in sorted(grouped)]

    @staticmethod
    def _merge_item(rows: list[sqlite3.Row]) -> dict[str, Any]:
        first = rows[0]
        source_values = [
            {
                "model_id": row["model_id"],
                "model_name": row["model_name"],
                "selection_config": _clean_config_value(row["selection_config"]),
                "current_config": _clean_config_value(row["current_config"]),
                "final_config": _clean_config_value(row["final_config"]),
                "rd_status": str(row["rd_status"] or "").strip(),
            }
            for row in rows
        ]
        selection_configs = sorted(
            {
                value["selection_config"]
                for value in source_values
                if _is_defined(value["selection_config"])
            }
        )
        current_configs = sorted(
            {
                value["current_config"]
                for value in source_values
                if _is_defined(value["current_config"])
            }
        )
        current_config = current_configs[0] if len(current_configs) == 1 else None

        strategy_code: str | None = None
        strategy: str | None = None
        strategy_label = "待确认"
        knowledge_status = "pending_confirmation"
        registration_marker = False
        current_config_note: str | None = None

        if len(selection_configs) > 1:
            strategy_label = "资料冲突，待确认"
            knowledge_status = "conflict"
        elif selection_configs:
            selection_config = selection_configs[0]
            if selection_config in _STRATEGIES:
                strategy_code = selection_config
                strategy, strategy_label = _STRATEGIES[selection_config]
                knowledge_status = "published"
            elif selection_config == "#":
                strategy_label = "待注册资料核对"
                knowledge_status = "registration_check_required"
                registration_marker = True
        elif current_config is not None:
            current_config_note = "研发内部状态，仅供参考"

        return {
            "item_id": first["item_id"],
            "category": str(first["category"] or ""),
            "name": str(first["rd_name"] or ""),
            "code": str(first["v_code"] or ""),
            "zh_description": str(first["zh_desc"] or ""),
            "en_description": str(first["en_desc"] or ""),
            "strategy_code": strategy_code,
            "strategy": strategy,
            "strategy_label": strategy_label,
            "knowledge_status": knowledge_status,
            "current_config": current_config,
            "current_config_note": current_config_note,
            "registration_marker": registration_marker,
            "conflicting_selection_configs": (
                selection_configs if len(selection_configs) > 1 else []
            ),
            "source_values": source_values,
        }

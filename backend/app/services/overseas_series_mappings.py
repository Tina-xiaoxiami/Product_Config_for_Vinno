"""海外注册「系列 → 机型清单」映射：确认一次，之后每次导入自动展开。

跟踪表里大量行写的是系列（``R series``、``G86全系列``、``Q系列``），
而不是具体机型。逐行问人没有意义——同一个 ``R series`` 在四个国家各写一遍。
所以按和名称映射一样的做法：人工确认一次，写进映射表，导入时自动展开。

映射只影响系统内的解析结果与正式数据，**绝不改写受控原件**。
清单为空或展开后仍无法解析的行，继续按「待确认」留给人。
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.services.overseas_registration_history import (
    migrate_overseas_registration_history_schema,
)
from app.services.registration_rules import normalize_business_name


@dataclass(frozen=True)
class OverseasSeriesMapping:
    source_name: str
    target_models: tuple[str, ...]
    confirmed_by: str
    change_note: str | None = None


def series_key(value: object) -> str:
    """系列名的比较键：大小写、空格与全角空格都不算差异。"""

    return re.sub(r"\s+", "", normalize_business_name(value)).casefold()


def _clean_models(models) -> tuple[str, ...]:
    cleaned: list[str] = []
    for model in models:
        text = str(model or "").strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return tuple(cleaned)


def list_overseas_series_mappings(
    database_path: str | Path,
) -> tuple[OverseasSeriesMapping, ...]:
    database = Path(database_path).expanduser().resolve()
    migrate_overseas_registration_history_schema(database)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT source_name, target_models_json, confirmed_by, change_note
            FROM overseas_series_mappings
            ORDER BY source_name
            """
        ).fetchall()
    finally:
        connection.close()
    return tuple(
        OverseasSeriesMapping(
            source_name=str(row["source_name"]),
            target_models=tuple(json.loads(row["target_models_json"])),
            confirmed_by=str(row["confirmed_by"]),
            change_note=row["change_note"],
        )
        for row in rows
    )


def overseas_series_index(
    database_path: str | Path,
) -> dict[str, tuple[str, ...]]:
    """给解析器用的「系列键 → 机型清单」。"""

    return {
        series_key(item.source_name): item.target_models
        for item in list_overseas_series_mappings(database_path)
    }


def save_overseas_series_mapping(
    database_path: str | Path,
    *,
    source_name: object,
    target_models,
    confirmed_by: object,
    change_note: object = None,
) -> OverseasSeriesMapping:
    source = str(source_name or "").strip()
    if not source:
        raise ValueError("系列写法不能为空")
    models = _clean_models(target_models)
    if not models:
        raise ValueError("系列展开后的机型清单不能为空")
    actor = str(confirmed_by or "").strip()
    if not actor:
        raise ValueError("确认人不能为空")
    note = str(change_note or "").strip() or None

    database = Path(database_path).expanduser().resolve()
    migrate_overseas_registration_history_schema(database)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            INSERT INTO overseas_series_mappings (
                source_name, target_models_json, normalized_source,
                confirmed_by, change_note
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(normalized_source) DO UPDATE SET
                source_name = excluded.source_name,
                target_models_json = excluded.target_models_json,
                confirmed_by = excluded.confirmed_by,
                change_note = excluded.change_note,
                updated_at = CURRENT_TIMESTAMP
            """,
            (source, json.dumps(models, ensure_ascii=False), series_key(source), actor, note),
        )
        connection.commit()
    finally:
        connection.close()
    return OverseasSeriesMapping(
        source_name=source,
        target_models=models,
        confirmed_by=actor,
        change_note=note,
    )


def delete_overseas_series_mapping(
    database_path: str | Path,
    *,
    source_name: object,
) -> bool:
    database = Path(database_path).expanduser().resolve()
    migrate_overseas_registration_history_schema(database)
    connection = sqlite3.connect(database)
    try:
        cursor = connection.execute(
            "DELETE FROM overseas_series_mappings WHERE normalized_source = ?",
            (series_key(source_name),),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()

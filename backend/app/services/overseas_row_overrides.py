"""按受控文档补录某一行的探头清单。

跟踪表里偶尔会写「探头见某某文档」而不是列清单（沙特那行就写着
``DOC——Rev10中对应机型适配探头``）。这类数据不在原件里，改原件又是不允许的，
所以按「原件 sha + 来源行 + 机型」登记人工补录，依据写进 source_note：

- 键里带原件 sha：换一份跟踪表就不会误套用别的文件登记的清单；
- 每条都能查到依据和确认人，可以单独撤销；
- 补录过的行在 applied_rules 里留 ``override:<依据>`` 痕迹。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.services.overseas_registration_history import (
    migrate_overseas_registration_history_schema,
)


@dataclass(frozen=True)
class RowProbeOverride:
    document_sha256: str
    source_ref: str
    model_name: str
    probes: tuple[str, ...]
    source_note: str
    confirmed_by: str


def document_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean(values) -> tuple[str, ...]:
    cleaned: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return tuple(cleaned)


def list_row_probe_overrides(
    database_path: str | Path,
    *,
    document_sha256: str | None = None,
) -> tuple[RowProbeOverride, ...]:
    database = Path(database_path).expanduser().resolve()
    migrate_overseas_registration_history_schema(database)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        if document_sha256:
            rows = connection.execute(
                """
                SELECT document_sha256, source_ref, model_name, probes_json,
                       source_note, confirmed_by
                FROM overseas_row_probe_overrides
                WHERE document_sha256 = ?
                ORDER BY source_ref, model_name
                """,
                (document_sha256,),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT document_sha256, source_ref, model_name, probes_json,
                       source_note, confirmed_by
                FROM overseas_row_probe_overrides
                ORDER BY source_ref, model_name
                """
            ).fetchall()
    finally:
        connection.close()
    return tuple(
        RowProbeOverride(
            document_sha256=str(row["document_sha256"]),
            source_ref=str(row["source_ref"]),
            model_name=str(row["model_name"]),
            probes=tuple(json.loads(row["probes_json"])),
            source_note=str(row["source_note"]),
            confirmed_by=str(row["confirmed_by"]),
        )
        for row in rows
    )


def row_probe_overrides_by_source(
    database_path: str | Path, document_sha256: str
) -> dict[str, dict[str, tuple[str, ...]]]:
    """给解析器用的「来源行 → 机型 → 探头清单」。"""

    index: dict[str, dict[str, tuple[str, ...]]] = {}
    for item in list_row_probe_overrides(
        database_path, document_sha256=document_sha256
    ):
        index.setdefault(item.source_ref, {})[item.model_name] = item.probes
    return index


def save_row_probe_override(
    database_path: str | Path,
    *,
    document_sha256: str,
    source_ref: object,
    model_name: object,
    probes,
    source_note: object,
    confirmed_by: object,
) -> RowProbeOverride:
    digest = str(document_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("原件哈希必须是 sha256")
    reference = str(source_ref or "").strip()
    if not reference:
        raise ValueError("来源行不能为空")
    model = str(model_name or "").strip()
    if not model:
        raise ValueError("机型不能为空")
    cleaned = _clean(probes)
    note = str(source_note or "").strip()
    if not note:
        raise ValueError("必须写明依据（哪份文档、哪一页）")
    if not cleaned and not re.search(r"(?i)N/A|无探头", note):
        # 空清单只在文档明确写 N/A 时才允许，免得手滑把已有探头清空
        raise ValueError("探头清单不能为空；文档标注无探头时请在依据里写明 N/A")
    actor = str(confirmed_by or "").strip()
    if not actor:
        raise ValueError("确认人不能为空")

    database = Path(database_path).expanduser().resolve()
    migrate_overseas_registration_history_schema(database)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            INSERT INTO overseas_row_probe_overrides (
                document_sha256, source_ref, model_name, probes_json,
                source_note, confirmed_by
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_sha256, source_ref, model_name) DO UPDATE SET
                probes_json = excluded.probes_json,
                source_note = excluded.source_note,
                confirmed_by = excluded.confirmed_by,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                digest,
                reference,
                model,
                json.dumps(cleaned, ensure_ascii=False),
                note,
                actor,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return RowProbeOverride(
        document_sha256=digest,
        source_ref=reference,
        model_name=model,
        probes=cleaned,
        source_note=note,
        confirmed_by=actor,
    )


def delete_row_probe_override(
    database_path: str | Path,
    *,
    document_sha256: str,
    source_ref: object,
    model_name: object,
) -> bool:
    database = Path(database_path).expanduser().resolve()
    migrate_overseas_registration_history_schema(database)
    connection = sqlite3.connect(database)
    try:
        cursor = connection.execute(
            """
            DELETE FROM overseas_row_probe_overrides
            WHERE document_sha256 = ? AND source_ref = ? AND model_name = ?
            """,
            (
                str(document_sha256 or "").strip().lower(),
                str(source_ref or "").strip(),
                str(model_name or "").strip(),
            ),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()

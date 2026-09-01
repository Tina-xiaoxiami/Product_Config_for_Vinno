"""幂等导入国内注册型号与探头差异。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3

from app.services.registration_confirmations import confirmed_derived_model_bases
from app.services.registration_rules import (
    DomesticRegistrationWorkbook,
    normalize_business_name,
    parse_domestic_registration_workbook,
)


@dataclass(frozen=True)
class RegistrationImportReport:
    country_code: str
    model_count: int
    probe_count: int
    matrix_count: int
    direct_link_count: int
    derived_link_count: int
    unmatched_product_model_count: int
    new_snapshot: bool


def _normalized_identity(value: object) -> str:
    return normalize_business_name(value).casefold()


def _snapshot_payload(parsed: DomesticRegistrationWorkbook) -> dict:
    return {
        "models": [
            {
                "model_name": item.model_name,
                "channel_count": item.channel_count,
                "unsupported_probes": list(item.unsupported_probes),
            }
            for item in parsed.models
        ],
        "probes": [
            {"probe_model": item.model, "ipn": item.ipn}
            for item in parsed.probes
        ],
    }


def _source_metadata(
    connection: sqlite3.Connection,
    source_document_id: int | None,
) -> tuple[str | None, str | None]:
    if source_document_id is None:
        return None, None
    row = connection.execute(
        "SELECT sha256, version FROM knowledge_documents WHERE id = ?",
        (source_document_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"未找到注册来源资料：{source_document_id}")
    return row[0], row[1]


def _upsert_batch(
    connection: sqlite3.Connection,
    *,
    country_code: str,
    source_document_id: int | None,
    source_sha256: str | None,
    source_version: str | None,
    snapshot_json: str,
    snapshot_hash: str,
    model_count: int,
    probe_count: int,
    matrix_count: int,
) -> tuple[int, bool]:
    existing = connection.execute(
        """
        SELECT id FROM registration_import_batches
        WHERE country_code = ? AND snapshot_hash = ?
        """,
        (country_code, snapshot_hash),
    ).fetchone()
    if existing is not None:
        connection.execute(
            "UPDATE registration_import_batches SET status = 'superseded' WHERE country_code = ?",
            (country_code,),
        )
        connection.execute(
            "UPDATE registration_import_batches SET status = 'active' WHERE id = ?",
            (existing[0],),
        )
        return int(existing[0]), False

    connection.execute(
        "UPDATE registration_import_batches SET status = 'superseded' WHERE country_code = ?",
        (country_code,),
    )
    cursor = connection.execute(
        """
        INSERT INTO registration_import_batches (
            country_code, source_document_id, source_version, source_sha256,
            snapshot_hash, snapshot_json, model_count, probe_count,
            matrix_count, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
        """,
        (
            country_code,
            source_document_id,
            source_version,
            source_sha256,
            snapshot_hash,
            snapshot_json,
            model_count,
            probe_count,
            matrix_count,
        ),
    )
    return int(cursor.lastrowid), True


def import_domestic_registration_workbook(
    database_path: str | Path,
    workbook_path: str | Path,
    *,
    source_document_id: int | None = None,
    confirmed_base_by_product_model_name: dict[str, str] | None = None,
) -> RegistrationImportReport:
    parsed = parse_domestic_registration_workbook(workbook_path)
    country_code = "CN"
    snapshot_json = json.dumps(
        _snapshot_payload(parsed),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    snapshot_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
    matrix_count = len(parsed.models) * len(parsed.probes)
    confirmed_bases = (
        confirmed_derived_model_bases()
        if confirmed_base_by_product_model_name is None
        else dict(confirmed_base_by_product_model_name)
    )

    connection = sqlite3.connect(Path(database_path), isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        source_sha256, source_version = _source_metadata(connection, source_document_id)
        connection.execute("BEGIN IMMEDIATE")
        try:
            batch_id, new_snapshot = _upsert_batch(
                connection,
                country_code=country_code,
                source_document_id=source_document_id,
                source_sha256=source_sha256,
                source_version=source_version,
                snapshot_json=snapshot_json,
                snapshot_hash=snapshot_hash,
                model_count=len(parsed.models),
                probe_count=len(parsed.probes),
                matrix_count=matrix_count,
            )

            model_ids: dict[str, int] = {}
            for model in parsed.models:
                normalized = _normalized_identity(model.model_name)
                connection.execute(
                    """
                    INSERT INTO registration_models (
                        country_code, model_name, normalized_name, channel_count,
                        import_batch_id, source_document_id, source_ref, source_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
                    ON CONFLICT(country_code, normalized_name) DO UPDATE SET
                        model_name = excluded.model_name,
                        channel_count = excluded.channel_count,
                        import_batch_id = excluded.import_batch_id,
                        source_document_id = excluded.source_document_id,
                        source_ref = excluded.source_ref,
                        source_status = 'active'
                    """,
                    (
                        country_code,
                        model.model_name,
                        normalized,
                        model.channel_count,
                        batch_id,
                        source_document_id,
                        f"0729!{model.source_row}",
                    ),
                )
                model_ids[normalized] = int(
                    connection.execute(
                        """
                        SELECT id FROM registration_models
                        WHERE country_code = ? AND normalized_name = ?
                        """,
                        (country_code, normalized),
                    ).fetchone()[0]
                )

            probe_ids: dict[str, int] = {}
            for probe in parsed.probes:
                normalized = _normalized_identity(probe.model)
                connection.execute(
                    """
                    INSERT INTO registration_probes (
                        country_code, probe_model, normalized_model, ipn,
                        import_batch_id, source_document_id, source_ref, source_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
                    ON CONFLICT(country_code, normalized_model) DO UPDATE SET
                        probe_model = excluded.probe_model,
                        ipn = excluded.ipn,
                        import_batch_id = excluded.import_batch_id,
                        source_document_id = excluded.source_document_id,
                        source_ref = excluded.source_ref,
                        source_status = 'active'
                    """,
                    (
                        country_code,
                        probe.model,
                        normalized,
                        probe.ipn,
                        batch_id,
                        source_document_id,
                        f"Sheet1!{probe.source_row}",
                    ),
                )
                probe_ids[normalized] = int(
                    connection.execute(
                        """
                        SELECT id FROM registration_probes
                        WHERE country_code = ? AND normalized_model = ?
                        """,
                        (country_code, normalized),
                    ).fetchone()[0]
                )

            active_model_ids = tuple(model_ids.values())
            active_probe_ids = tuple(probe_ids.values())
            connection.execute(
                "UPDATE registration_models SET source_status = 'archived' WHERE country_code = ?",
                (country_code,),
            )
            connection.executemany(
                "UPDATE registration_models SET source_status = 'active' WHERE id = ?",
                ((item_id,) for item_id in active_model_ids),
            )
            connection.execute(
                "UPDATE registration_probes SET source_status = 'archived' WHERE country_code = ?",
                (country_code,),
            )
            connection.executemany(
                "UPDATE registration_probes SET source_status = 'active' WHERE id = ?",
                ((item_id,) for item_id in active_probe_ids),
            )

            connection.execute(
                "DELETE FROM registration_model_probes WHERE country_code = ?",
                (country_code,),
            )
            unsupported_by_model = {
                _normalized_identity(model.model_name): {
                    _normalized_identity(probe) for probe in model.unsupported_probes
                }
                for model in parsed.models
            }
            for model in parsed.models:
                model_identity = _normalized_identity(model.model_name)
                for probe in parsed.probes:
                    probe_identity = _normalized_identity(probe.model)
                    registration_status = (
                        "unregistered"
                        if probe_identity in unsupported_by_model[model_identity]
                        else "registered"
                    )
                    connection.execute(
                        """
                        INSERT INTO registration_model_probes (
                            country_code, registration_model_id,
                            registration_probe_id, registration_status,
                            import_batch_id, source_document_id, source_ref
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            country_code,
                            model_ids[model_identity],
                            probe_ids[probe_identity],
                            registration_status,
                            batch_id,
                            source_document_id,
                            f"0729!{model.source_row}",
                        ),
                    )

            connection.execute(
                """
                DELETE FROM product_registration_model_links
                WHERE registration_model_id IN (
                    SELECT id FROM registration_models WHERE country_code = ?
                )
                """,
                (country_code,),
            )
            direct_link_count = 0
            derived_link_count = 0
            unmatched_product_model_count = 0
            confirmed_normalized = {
                _normalized_identity(product): _normalized_identity(base)
                for product, base in confirmed_bases.items()
            }
            series_marker = "china" if country_code == "CN" else "oversea"
            product_rows = connection.execute(
                """
                SELECT product.id, product.name, product.config_group
                FROM product_models product
                JOIN product_series series ON series.id = product.series_id
                WHERE LOWER(series.name) LIKE ?
                ORDER BY product.id
                """,
                (f"%{series_marker}%",),
            ).fetchall()
            for product_id, product_name, config_group in product_rows:
                product_identity = _normalized_identity(product_name)
                mapping_type = "direct"
                target_identity = product_identity
                if target_identity not in model_ids:
                    group_identity = _normalized_identity(config_group)
                    if group_identity and group_identity in model_ids:
                        target_identity = group_identity
                        mapping_type = "config_group"
                    elif product_identity in confirmed_normalized:
                        target_identity = confirmed_normalized[product_identity]
                        mapping_type = "confirmed_derived"
                    else:
                        unmatched_product_model_count += 1
                        continue
                if target_identity not in model_ids:
                    raise ValueError(
                        f"产品型号 {product_name} 的注册基础型号不存在"
                    )
                connection.execute(
                    """
                    INSERT INTO product_registration_model_links (
                        product_model_id, registration_model_id, mapping_type,
                        source, review_status
                    ) VALUES (?, ?, ?, ?, 'approved')
                    """,
                    (
                        product_id,
                        model_ids[target_identity],
                        mapping_type,
                        "registration_import"
                        if mapping_type == "direct"
                        else "product_owner_confirmation",
                    ),
                )
                if mapping_type == "direct":
                    direct_link_count += 1
                else:
                    derived_link_count += 1

            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"注册导入引入外键异常：{violations}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    finally:
        connection.close()

    return RegistrationImportReport(
        country_code=country_code,
        model_count=len(parsed.models),
        probe_count=len(parsed.probes),
        matrix_count=matrix_count,
        direct_link_count=direct_link_count,
        derived_link_count=derived_link_count,
        unmatched_product_model_count=unmatched_product_model_count,
        new_snapshot=new_snapshot,
    )

"""成对管理注册证与注册差异表的不可变版本记录。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
from typing import Any
from uuid import uuid4

from app.services.registration_confirmations import confirmed_derived_model_bases
from app.services.registration_rules import (
    normalize_business_name,
    parse_domestic_registration_workbook,
)
from app.services.registration_migration import migrate_registration_schema


class RegistrationPackageError(ValueError):
    """资料无法组成受控注册包时抛出。"""


def _identity(value: object) -> str:
    return normalize_business_name(value).casefold()


def _snapshot_maps(snapshot_json: str) -> tuple[dict[str, dict], dict[str, dict]]:
    try:
        payload = json.loads(snapshot_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RegistrationPackageError("注册快照格式不正确") from exc
    models = {
        _identity(item.get("model_name")): item
        for item in payload.get("models", [])
        if _identity(item.get("model_name"))
    }
    probes = {
        _identity(item.get("probe_model")): item
        for item in payload.get("probes", [])
        if _identity(item.get("probe_model"))
    }
    return models, probes


def _display_names(items: dict[str, dict], field: str, identities: set[str]) -> list[str]:
    return sorted(str(items[key][field]) for key in identities)


def compute_registration_snapshot_diff(
    previous_snapshot_json: str | None,
    current_snapshot_json: str,
    *,
    previous_documents: dict[str, str] | None = None,
    current_documents: dict[str, str] | None = None,
) -> dict[str, Any]:
    current_models, current_probes = _snapshot_maps(current_snapshot_json)
    if previous_snapshot_json is None:
        return {
            "kind": "baseline",
            "summary": {
                "models": len(current_models),
                "probes": len(current_probes),
                "relations": len(current_models) * len(current_probes),
            },
            "models": {"added": [], "removed": []},
            "probes": {"added": [], "removed": [], "ipn_changed": []},
            "documents": {
                "certificate_changed": False,
                "difference_changed": False,
            },
            "registration_status_changes": [],
        }

    previous_models, previous_probes = _snapshot_maps(previous_snapshot_json)
    previous_model_keys = set(previous_models)
    current_model_keys = set(current_models)
    previous_probe_keys = set(previous_probes)
    current_probe_keys = set(current_probes)
    common_models = previous_model_keys & current_model_keys
    common_probes = previous_probe_keys & current_probe_keys

    models_added = current_model_keys - previous_model_keys
    models_removed = previous_model_keys - current_model_keys
    probes_added = current_probe_keys - previous_probe_keys
    probes_removed = previous_probe_keys - current_probe_keys
    channel_count_changed = []
    for model_key in sorted(common_models):
        old_count = previous_models[model_key].get("channel_count")
        new_count = current_models[model_key].get("channel_count")
        if old_count != new_count:
            channel_count_changed.append(
                {
                    "model": str(current_models[model_key]["model_name"]),
                    "from": old_count,
                    "to": new_count,
                }
            )
    ipn_changed = []
    for probe_key in sorted(common_probes):
        old_ipn = str(previous_probes[probe_key].get("ipn") or "")
        new_ipn = str(current_probes[probe_key].get("ipn") or "")
        if old_ipn != new_ipn:
            ipn_changed.append(
                {
                    "probe": str(current_probes[probe_key]["probe_model"]),
                    "from": old_ipn,
                    "to": new_ipn,
                }
            )

    status_changes = []
    for model_key in sorted(common_models):
        old_unsupported = {
            _identity(item)
            for item in previous_models[model_key].get("unsupported_probes", [])
        }
        new_unsupported = {
            _identity(item)
            for item in current_models[model_key].get("unsupported_probes", [])
        }
        for probe_key in sorted(common_probes):
            old_status = "unregistered" if probe_key in old_unsupported else "registered"
            new_status = "unregistered" if probe_key in new_unsupported else "registered"
            if old_status != new_status:
                status_changes.append(
                    {
                        "model": str(current_models[model_key]["model_name"]),
                        "probe": str(current_probes[probe_key]["probe_model"]),
                        "from": old_status,
                        "to": new_status,
                    }
                )

    return {
        "kind": "changes",
        "summary": {
            "models_added": len(models_added),
            "models_removed": len(models_removed),
            "probes_added": len(probes_added),
            "probes_removed": len(probes_removed),
            "probe_ipn_changed": len(ipn_changed),
            "model_channel_count_changed": len(channel_count_changed),
            "registration_status_changed": len(status_changes),
        },
        "models": {
            "added": _display_names(current_models, "model_name", models_added),
            "removed": _display_names(previous_models, "model_name", models_removed),
            "channel_count_changed": channel_count_changed,
        },
        "probes": {
            "added": _display_names(current_probes, "probe_model", probes_added),
            "removed": _display_names(previous_probes, "probe_model", probes_removed),
            "ipn_changed": ipn_changed,
        },
        "documents": {
            "certificate_changed": bool(
                previous_documents
                and current_documents
                and previous_documents.get("certificate_sha256")
                != current_documents.get("certificate_sha256")
            ),
            "difference_changed": bool(
                previous_documents
                and current_documents
                and previous_documents.get("difference_sha256")
                != current_documents.get("difference_sha256")
            ),
        },
        "registration_status_changes": status_changes,
    }


def _document(connection: sqlite3.Connection, document_id: int) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT id, document_type, version, country, product_series, sha256,
               source_status, file_name, file_path, mime_type
        FROM knowledge_documents WHERE id = ?
        """,
        (document_id,),
    ).fetchone()
    if row is None:
        raise RegistrationPackageError(f"注册资料不存在：{document_id}")
    return row


def _validate_pair(
    connection: sqlite3.Connection,
    *,
    country_code: str,
    product_series: str | None,
    certificate_document_id: int,
    difference_document_id: int,
    import_batch_id: int,
) -> tuple[sqlite3.Row, sqlite3.Row, sqlite3.Row]:
    certificate = _document(connection, certificate_document_id)
    difference = _document(connection, difference_document_id)
    if certificate["document_type"] != "registration_certificate":
        raise RegistrationPackageError("注册证资料类型不正确")
    if difference["document_type"] != "registration_difference":
        raise RegistrationPackageError("注册差异表资料类型不正确")
    if certificate["source_status"] != "active" or difference["source_status"] != "active":
        raise RegistrationPackageError("注册资料不是有效状态")
    if certificate["country"] != country_code or difference["country"] != country_code:
        raise RegistrationPackageError("注册资料国家与注册包不一致")
    material_series = {
        str(value).strip()
        for value in (certificate["product_series"], difference["product_series"])
        if value and str(value).strip()
    }
    if len(material_series) > 1 or (
        product_series and material_series and product_series not in material_series
    ):
        raise RegistrationPackageError("注册资料产品系列不一致")
    if not certificate["sha256"] or not difference["sha256"]:
        raise RegistrationPackageError("注册资料缺少文件哈希")

    batch = connection.execute(
        """
        SELECT id, country_code, source_document_id, snapshot_hash, snapshot_json,
               model_count, probe_count, matrix_count, status
        FROM registration_import_batches WHERE id = ?
        """,
        (import_batch_id,),
    ).fetchone()
    if batch is None:
        raise RegistrationPackageError(f"注册导入批次不存在：{import_batch_id}")
    if batch["source_document_id"] != difference_document_id:
        raise RegistrationPackageError("导入批次未关联所选差异表")
    if batch["country_code"] != country_code:
        raise RegistrationPackageError("导入批次国家与注册包不一致")
    if not batch["snapshot_hash"]:
        raise RegistrationPackageError("注册导入批次缺少快照哈希")
    return certificate, difference, batch


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reference_controlled_document(
    database_path: Path,
    *,
    country_code: str,
    registration_number: str,
    role: str,
    document: sqlite3.Row,
) -> tuple[str, str, str | None]:
    del database_path, country_code, registration_number
    source = Path(str(document["file_path"]))
    if not source.is_absolute() or not source.is_file():
        raise RegistrationPackageError(
            f"{role}原文件不存在或尚未同步，不能建立不可变历史"
        )
    expected_sha = str(document["sha256"])
    if _file_sha256(source) != expected_sha:
        raise RegistrationPackageError(f"{role}原文件内容与登记哈希不一致")
    return str(source.resolve()), str(document["file_name"]), document["mime_type"]


def _validate_active_projection(
    connection: sqlite3.Connection,
    *,
    country_code: str,
    batch: sqlite3.Row,
) -> None:
    if batch["status"] != "active":
        raise RegistrationPackageError("所选导入批次不是当前生效批次")
    expected = (
        int(batch["model_count"]),
        int(batch["probe_count"]),
        int(batch["matrix_count"]),
    )
    snapshot_models, snapshot_probes = _snapshot_maps(batch["snapshot_json"])
    if expected != (
        len(snapshot_models),
        len(snapshot_probes),
        len(snapshot_models) * len(snapshot_probes),
    ):
        raise RegistrationPackageError("导入批次数量与注册快照内容不一致")
    actual = (
        int(
            connection.execute(
                """
                SELECT COUNT(*) FROM registration_models
                WHERE country_code = ? AND source_status = 'active'
                  AND import_batch_id = ?
                """,
                (country_code, batch["id"]),
            ).fetchone()[0]
        ),
        int(
            connection.execute(
                """
                SELECT COUNT(*) FROM registration_probes
                WHERE country_code = ? AND source_status = 'active'
                  AND import_batch_id = ?
                """,
                (country_code, batch["id"]),
            ).fetchone()[0]
        ),
        int(
            connection.execute(
                """
                SELECT COUNT(*) FROM registration_model_probes
                WHERE country_code = ? AND import_batch_id = ?
                """,
                (country_code, batch["id"]),
            ).fetchone()[0]
        ),
    )
    country_totals = (
        int(
            connection.execute(
                """
                SELECT COUNT(*) FROM registration_models
                WHERE country_code = ? AND source_status = 'active'
                """,
                (country_code,),
            ).fetchone()[0]
        ),
        int(
            connection.execute(
                """
                SELECT COUNT(*) FROM registration_probes
                WHERE country_code = ? AND source_status = 'active'
                """,
                (country_code,),
            ).fetchone()[0]
        ),
        int(
            connection.execute(
                "SELECT COUNT(*) FROM registration_model_probes WHERE country_code = ?",
                (country_code,),
            ).fetchone()[0]
        ),
    )
    if actual != expected or country_totals != expected:
        raise RegistrationPackageError(
            "导入批次与当前注册结构化投影不一致，禁止建立生效基线"
        )

    projected_models = {
        str(row["normalized_name"]): {
            "model_name": row["model_name"],
            "channel_count": row["channel_count"],
        }
        for row in connection.execute(
            """
            SELECT normalized_name, model_name, channel_count
            FROM registration_models
            WHERE country_code = ? AND source_status = 'active'
            """,
            (country_code,),
        )
    }
    projected_probes = {
        str(row["normalized_model"]): {
            "probe_model": row["probe_model"],
            "ipn": row["ipn"],
        }
        for row in connection.execute(
            """
            SELECT normalized_model, probe_model, ipn
            FROM registration_probes
            WHERE country_code = ? AND source_status = 'active'
            """,
            (country_code,),
        )
    }
    expected_models = {
        key: {
            "model_name": item["model_name"],
            "channel_count": item.get("channel_count"),
        }
        for key, item in snapshot_models.items()
    }
    expected_probes = {
        key: {"probe_model": item["probe_model"], "ipn": item.get("ipn") or None}
        for key, item in snapshot_probes.items()
    }
    if projected_models != expected_models or projected_probes != expected_probes:
        raise RegistrationPackageError(
            "导入批次与当前注册结构化投影不一致，禁止建立生效基线"
        )

    projected_statuses = {
        (str(row["model_key"]), str(row["probe_key"])): row["registration_status"]
        for row in connection.execute(
            """
            SELECT model.normalized_name AS model_key,
                   probe.normalized_model AS probe_key,
                   matrix.registration_status
            FROM registration_model_probes matrix
            JOIN registration_models model ON model.id = matrix.registration_model_id
            JOIN registration_probes probe ON probe.id = matrix.registration_probe_id
            WHERE matrix.country_code = ?
            """,
            (country_code,),
        )
    }
    expected_statuses = {}
    for model_key, model in snapshot_models.items():
        unsupported = {_identity(item) for item in model.get("unsupported_probes", [])}
        for probe_key in snapshot_probes:
            expected_statuses[(model_key, probe_key)] = (
                "unregistered" if probe_key in unsupported else "registered"
            )
    if projected_statuses != expected_statuses:
        raise RegistrationPackageError(
            "导入批次与当前注册结构化投影不一致，禁止建立生效基线"
        )


def _materialize_version_snapshot(
    connection: sqlite3.Connection,
    *,
    version_id: int,
) -> None:
    existing = connection.execute(
        "SELECT COUNT(*) FROM registration_package_version_models WHERE version_id = ?",
        (version_id,),
    ).fetchone()[0]
    if existing:
        return
    version = connection.execute(
        """
        SELECT version.id, version.import_batch_id, version.difference_document_id,
               package.country_code, batch.snapshot_json
        FROM registration_package_versions version
        JOIN registration_packages package ON package.id = version.package_id
        JOIN registration_import_batches batch ON batch.id = version.import_batch_id
        WHERE version.id = ?
        """,
        (version_id,),
    ).fetchone()
    if version is None:
        raise RegistrationPackageError("注册资料包版本不存在")
    models, probes = _snapshot_maps(version["snapshot_json"])
    version_model_ids: dict[str, int] = {}
    version_probe_ids: dict[str, int] = {}

    for normalized, item in models.items():
        source_ref = str(item.get("source_ref") or "") or None
        connection.execute(
            """
            INSERT INTO registration_models (
                country_code, model_name, normalized_name, channel_count,
                import_batch_id, source_document_id, source_ref, source_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
            ON CONFLICT(country_code, normalized_name) DO UPDATE SET
                model_name = excluded.model_name,
                channel_count = excluded.channel_count
            """,
            (
                version["country_code"],
                item["model_name"],
                normalized,
                item.get("channel_count"),
                version["import_batch_id"],
                version["difference_document_id"],
                source_ref,
            ),
        )
        master_id = int(
            connection.execute(
                "SELECT id FROM registration_models WHERE country_code = ? AND normalized_name = ?",
                (version["country_code"], normalized),
            ).fetchone()[0]
        )
        cursor = connection.execute(
            """
            INSERT INTO registration_package_version_models (
                version_id, registration_model_id, model_name, normalized_name,
                channel_count, source_ref
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                version_id,
                master_id,
                item["model_name"],
                normalized,
                item.get("channel_count"),
                source_ref,
            ),
        )
        version_model_ids[normalized] = int(cursor.lastrowid)

    for normalized, item in probes.items():
        source_ref = str(item.get("source_ref") or "") or None
        connection.execute(
            """
            INSERT INTO registration_probes (
                country_code, probe_model, normalized_model, ipn,
                import_batch_id, source_document_id, source_ref, source_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
            ON CONFLICT(country_code, normalized_model) DO UPDATE SET
                probe_model = excluded.probe_model,
                ipn = excluded.ipn
            """,
            (
                version["country_code"],
                item["probe_model"],
                normalized,
                item.get("ipn") or None,
                version["import_batch_id"],
                version["difference_document_id"],
                source_ref,
            ),
        )
        master_id = int(
            connection.execute(
                "SELECT id FROM registration_probes WHERE country_code = ? AND normalized_model = ?",
                (version["country_code"], normalized),
            ).fetchone()[0]
        )
        cursor = connection.execute(
            """
            INSERT INTO registration_package_version_probes (
                version_id, registration_probe_id, probe_model, normalized_model,
                ipn, source_ref
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                version_id,
                master_id,
                item["probe_model"],
                normalized,
                item.get("ipn") or None,
                source_ref,
            ),
        )
        version_probe_ids[normalized] = int(cursor.lastrowid)

    for model_key, model in models.items():
        unsupported = {_identity(item) for item in model.get("unsupported_probes", [])}
        for probe_key in probes:
            connection.execute(
                """
                INSERT INTO registration_package_version_model_probes (
                    version_id, version_model_id, version_probe_id,
                    registration_status, source_ref
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    version_model_ids[model_key],
                    version_probe_ids[probe_key],
                    "unregistered" if probe_key in unsupported else "registered",
                    str(model.get("source_ref") or "") or None,
                ),
            )


def backfill_registration_package_version_snapshots(
    database_path: str | Path,
) -> int:
    """为既有资料包版本补齐版本内快照；可安全重复执行。"""

    migrate_registration_schema(database_path)
    connection = sqlite3.connect(Path(database_path), isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        before = int(
            connection.execute(
                "SELECT COUNT(DISTINCT version_id) FROM registration_package_version_models"
            ).fetchone()[0]
        )
        for row in connection.execute(
            "SELECT id FROM registration_package_versions ORDER BY id"
        ).fetchall():
            _materialize_version_snapshot(connection, version_id=int(row["id"]))
        after = int(
            connection.execute(
                "SELECT COUNT(DISTINCT version_id) FROM registration_package_version_models"
            ).fetchone()[0]
        )
        connection.commit()
        return after - before
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def _version_result(row: sqlite3.Row, *, reused: bool) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "package_id": int(row["package_id"]),
        "version_no": int(row["version_no"]),
        "previous_version_id": (
            int(row["previous_version_id"]) if row["previous_version_id"] else None
        ),
        "status": row["status"],
        "diff": json.loads(row["diff_json"]),
        "model_count": int(row["model_count"]),
        "probe_count": int(row["probe_count"]),
        "matrix_count": int(row["matrix_count"]),
        "reused": reused,
    }


def record_registration_package_version(
    database_path: str | Path,
    *,
    country_code: str,
    unit_code: str,
    display_name: str,
    product_series: str | None,
    certificate_document_id: int,
    difference_document_id: int,
    import_batch_id: int,
    registration_number: str | None = None,
    identity_source: str | None = None,
    confirmed_by: str | None = None,
    change_note: str | None = None,
    effective_date: str | None = None,
    _activate_baseline: bool = False,
) -> dict[str, Any]:
    """校验并记录一对注册资料；普通新增保持草稿，重复资料幂等复用。"""

    path = Path(database_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    cleaned_country = str(country_code or "").strip().upper()
    cleaned_unit = str(unit_code or "").strip()
    cleaned_name = str(display_name or "").strip()
    cleaned_registration_number = str(registration_number or "").strip()
    cleaned_identity_source = str(identity_source or "").strip()
    cleaned_confirmed_by = str(confirmed_by or "").strip()
    if len(cleaned_country) != 2 or not cleaned_unit or not cleaned_name:
        raise RegistrationPackageError("注册包国家、单元标识和名称不能为空")

    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        try:
            certificate, difference, batch = _validate_pair(
                connection,
                country_code=cleaned_country,
                product_series=product_series,
                certificate_document_id=certificate_document_id,
                difference_document_id=difference_document_id,
                import_batch_id=import_batch_id,
            )
            if (
                not cleaned_registration_number
                or not cleaned_identity_source
                or not cleaned_confirmed_by
            ):
                raise RegistrationPackageError(
                    "注册证号、身份来源和确认人不能为空"
                )
            if _activate_baseline:
                _validate_active_projection(
                    connection,
                    country_code=cleaned_country,
                    batch=batch,
                )

            certificate_artifact = _reference_controlled_document(
                path,
                country_code=cleaned_country,
                registration_number=cleaned_registration_number,
                role="certificate",
                document=certificate,
            )
            difference_artifact = _reference_controlled_document(
                path,
                country_code=cleaned_country,
                registration_number=cleaned_registration_number,
                role="difference",
                document=difference,
            )

            conflicting_identity = connection.execute(
                """
                SELECT id, unit_code FROM registration_packages
                WHERE country_code = ? AND registration_number = ?
                  AND unit_code <> ?
                """,
                (cleaned_country, cleaned_registration_number, cleaned_unit),
            ).fetchone()
            if conflicting_identity is not None:
                raise RegistrationPackageError(
                    "该注册证号已绑定其他注册单元："
                    f"{conflicting_identity['unit_code']}"
                )
            existing_package = connection.execute(
                """
                SELECT id, registration_number FROM registration_packages
                WHERE country_code = ? AND unit_code = ?
                """,
                (cleaned_country, cleaned_unit),
            ).fetchone()
            if (
                existing_package is not None
                and existing_package["registration_number"]
                and existing_package["registration_number"]
                != cleaned_registration_number
            ):
                raise RegistrationPackageError("注册单元与既有注册证号不一致")
            connection.execute(
                """
                INSERT INTO registration_packages (
                    country_code, unit_code, display_name, product_series,
                    registration_number, identity_source, confirmed_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(country_code, unit_code) DO UPDATE SET
                    display_name = excluded.display_name,
                    product_series = excluded.product_series,
                    registration_number = excluded.registration_number,
                    identity_source = excluded.identity_source,
                    confirmed_by = excluded.confirmed_by,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    cleaned_country,
                    cleaned_unit,
                    cleaned_name,
                    product_series,
                    cleaned_registration_number,
                    cleaned_identity_source,
                    cleaned_confirmed_by,
                ),
            )
            package = connection.execute(
                """
                SELECT id FROM registration_packages
                WHERE country_code = ? AND unit_code = ?
                """,
                (cleaned_country, cleaned_unit),
            ).fetchone()
            package_id = int(package["id"])
            if _activate_baseline:
                conflicting_links = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM product_registration_model_links link
                    JOIN registration_models registration
                      ON registration.id = link.registration_model_id
                    WHERE registration.import_batch_id = ?
                      AND link.registration_package_id IS NOT NULL
                      AND link.registration_package_id <> ?
                    """,
                    (batch["id"], package_id),
                ).fetchone()[0]
                if conflicting_links:
                    raise RegistrationPackageError(
                        "产品机型已绑定其他注册证，禁止自动改写映射"
                    )
                connection.execute(
                    """
                    UPDATE product_registration_model_links
                    SET registration_package_id = ?
                    WHERE registration_package_id IS NULL
                      AND registration_model_id IN (
                          SELECT id FROM registration_models
                          WHERE import_batch_id = ?
                      )
                    """,
                    (package_id, batch["id"]),
                )
            pair_payload = "|".join(
                (
                    cleaned_country,
                    cleaned_unit,
                    str(certificate["sha256"]),
                    str(difference["sha256"]),
                    str(batch["snapshot_hash"]),
                )
            )
            pair_hash = hashlib.sha256(pair_payload.encode("utf-8")).hexdigest()
            existing = connection.execute(
                """
                SELECT * FROM registration_package_versions
                WHERE package_id = ? AND pair_hash = ?
                """,
                (package_id, pair_hash),
            ).fetchone()
            if existing is not None:
                _materialize_version_snapshot(
                    connection,
                    version_id=int(existing["id"]),
                )
                connection.execute(
                    """
                    UPDATE registration_package_versions SET
                        certificate_artifact_path = ?,
                        certificate_file_name = ?,
                        certificate_mime_type = ?,
                        difference_artifact_path = ?,
                        difference_file_name = ?,
                        difference_mime_type = ?
                    WHERE id = ?
                    """,
                    (*certificate_artifact, *difference_artifact, existing["id"]),
                )
                existing = connection.execute(
                    "SELECT * FROM registration_package_versions WHERE id = ?",
                    (existing["id"],),
                ).fetchone()
                connection.commit()
                return _version_result(existing, reused=True)

            previous = connection.execute(
                """
                SELECT version.*, batch.snapshot_json
                FROM registration_package_versions version
                JOIN registration_import_batches batch
                  ON batch.id = version.import_batch_id
                WHERE version.package_id = ? AND version.status = 'active'
                """,
                (package_id,),
            ).fetchone()
            previous_documents = None
            if previous is not None:
                previous_documents = {
                    "certificate_sha256": previous["certificate_sha256"],
                    "difference_sha256": previous["difference_sha256"],
                }
            diff = compute_registration_snapshot_diff(
                previous["snapshot_json"] if previous else None,
                batch["snapshot_json"],
                previous_documents=previous_documents,
                current_documents={
                    "certificate_sha256": certificate["sha256"],
                    "difference_sha256": difference["sha256"],
                },
            )
            version_no = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(version_no), 0) + 1
                    FROM registration_package_versions WHERE package_id = ?
                    """,
                    (package_id,),
                ).fetchone()[0]
            )
            if _activate_baseline and previous is not None:
                raise RegistrationPackageError(
                    "生效基线已存在；后续版本必须经合并校验后发布"
                )
            status = "active" if _activate_baseline else "draft"
            cursor = connection.execute(
                """
                INSERT INTO registration_package_versions (
                    package_id, version_no, previous_version_id,
                    certificate_document_id, certificate_version, certificate_sha256,
                    difference_document_id, difference_version, difference_sha256,
                    certificate_artifact_path, certificate_file_name,
                    certificate_mime_type, difference_artifact_path,
                    difference_file_name, difference_mime_type,
                    import_batch_id, snapshot_hash, pair_hash, diff_json, status,
                    change_note, effective_date, model_count, probe_count, matrix_count,
                    published_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?,
                          CASE WHEN ? = 'active' THEN CURRENT_TIMESTAMP ELSE NULL END)
                """,
                (
                    package_id,
                    version_no,
                    previous["id"] if previous else None,
                    certificate_document_id,
                    certificate["version"],
                    certificate["sha256"],
                    difference_document_id,
                    difference["version"],
                    difference["sha256"],
                    *certificate_artifact,
                    *difference_artifact,
                    import_batch_id,
                    batch["snapshot_hash"],
                    pair_hash,
                    json.dumps(diff, ensure_ascii=False, sort_keys=True),
                    status,
                    str(change_note or "").strip() or None,
                    effective_date,
                    batch["model_count"],
                    batch["probe_count"],
                    batch["matrix_count"],
                    status,
                ),
            )
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"注册资料包引入外键异常：{violations}")
            row = connection.execute(
                "SELECT * FROM registration_package_versions WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            _materialize_version_snapshot(
                connection,
                version_id=int(row["id"]),
            )
            connection.commit()
            return _version_result(row, reused=False)
        except Exception:
            connection.rollback()
            raise
    finally:
        connection.close()


def migrate_existing_registration_package(
    database_path: str | Path,
    *,
    certificate_document_id: int,
    difference_document_id: int,
    import_batch_id: int,
    country_code: str,
    unit_code: str,
    display_name: str,
    product_series: str | None,
    registration_number: str,
    identity_source: str,
    confirmed_by: str,
    change_note: str = "现有注册数据基线迁移",
) -> dict[str, Any]:
    """幂等建立资料包结构并绑定既有投影，不重写注册主数据。"""

    migrate_registration_schema(database_path)
    return record_registration_package_version(
        database_path,
        country_code=country_code,
        unit_code=unit_code,
        display_name=display_name,
        product_series=product_series,
        certificate_document_id=certificate_document_id,
        difference_document_id=difference_document_id,
        import_batch_id=import_batch_id,
        registration_number=registration_number,
        identity_source=identity_source,
        confirmed_by=confirmed_by,
        change_note=change_note,
        _activate_baseline=True,
    )


def _managed_source_copy(
    database_path: Path,
    *,
    registration_number: str,
    role: str,
    source_path: Path,
) -> Path:
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    safe_identity = re.sub(r"[^0-9A-Za-z._-]+", "_", registration_number).strip("_")
    suffix = source_path.suffix.lower()
    target_dir = database_path.parent / "registration_sources" / (safe_identity or "unknown")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{role}-{uuid4().hex}{suffix}"
    shutil.copyfile(source_path, target)
    return target.resolve()


def _draft_snapshot(workbook_path: Path) -> tuple[str, int, int, int]:
    parsed = parse_domestic_registration_workbook(workbook_path)
    payload = {
        "models": [
            {
                "model_name": item.model_name,
                "channel_count": item.channel_count,
                "unsupported_probes": list(item.unsupported_probes),
                "source_ref": f"0729!{item.source_row}",
            }
            for item in parsed.models
        ],
        "probes": [
            {
                "probe_model": item.model,
                "ipn": item.ipn,
                "source_ref": f"Sheet1!{item.source_row}",
            }
            for item in parsed.probes
        ],
    }
    snapshot_json = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        snapshot_json,
        len(parsed.models),
        len(parsed.probes),
        len(parsed.models) * len(parsed.probes),
    )


def _mapping_type(product_name: str, config_group: str | None, model_name: str) -> str:
    if _identity(product_name) == _identity(model_name):
        return "direct"
    if config_group and _identity(config_group) == _identity(model_name):
        return "config_group"
    confirmed = {
        _identity(product): _identity(base)
        for product, base in confirmed_derived_model_bases().items()
    }
    if confirmed.get(_identity(product_name)) == _identity(model_name):
        return "confirmed_derived"
    return "manual"


def _replace_version_mappings(
    connection: sqlite3.Connection,
    *,
    version_id: int,
    product_model_mappings: dict[int, str],
    approved_product_model_ids: set[int] | None = None,
) -> int:
    approved_ids = approved_product_model_ids or set()
    connection.execute(
        "DELETE FROM registration_package_version_product_mappings WHERE version_id = ?",
        (version_id,),
    )
    version_models = {
        str(row["normalized_name"]): row
        for row in connection.execute(
            "SELECT id, model_name, normalized_name FROM registration_package_version_models WHERE version_id = ?",
            (version_id,),
        )
    }
    for product_model_id, model_name in product_model_mappings.items():
        product = connection.execute(
            "SELECT id, name, config_group FROM product_models WHERE id = ?",
            (int(product_model_id),),
        ).fetchone()
        if product is None:
            raise RegistrationPackageError(f"产品机型不存在：{product_model_id}")
        version_model = version_models.get(_identity(model_name))
        if version_model is None:
            raise RegistrationPackageError(f"注册资料中不存在型号：{model_name}")
        connection.execute(
            """
            INSERT INTO registration_package_version_product_mappings (
                version_id, product_model_id, version_model_id,
                mapping_type, review_status
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                version_id,
                int(product_model_id),
                int(version_model["id"]),
                _mapping_type(product["name"], product["config_group"], version_model["model_name"]),
                "approved" if int(product_model_id) in approved_ids else "pending",
            ),
        )
    return len(product_model_mappings)


def _auto_version_mappings(
    connection: sqlite3.Connection,
    *,
    version_id: int,
    country_code: str,
) -> tuple[dict[int, str], set[int]]:
    version_models = {
        str(row["normalized_name"]): str(row["model_name"])
        for row in connection.execute(
            "SELECT model_name, normalized_name FROM registration_package_version_models WHERE version_id = ?",
            (version_id,),
        )
    }
    version = connection.execute(
        "SELECT package_id FROM registration_package_versions WHERE id = ?",
        (version_id,),
    ).fetchone()
    if version is None:
        raise RegistrationPackageError("注册资料包版本不存在")
    mappings = {
        int(row["product_model_id"]): version_models[str(row["normalized_name"])]
        for row in connection.execute(
            """
            SELECT link.product_model_id, model.normalized_name
            FROM product_registration_model_links link
            JOIN registration_models model ON model.id = link.registration_model_id
            WHERE link.registration_package_id = ?
              AND link.review_status = 'approved'
            ORDER BY link.product_model_id
            """,
            (int(version["package_id"]),),
        )
        if str(row["normalized_name"]) in version_models
    }
    reused_product_model_ids = set(mappings)
    marker = "china" if country_code == "CN" else "oversea"
    confirmed = {
        _identity(product): _identity(base)
        for product, base in confirmed_derived_model_bases().items()
    }
    for row in connection.execute(
        """
        SELECT product.id, product.name, product.config_group
        FROM product_models product
        JOIN product_series series ON series.id = product.series_id
        WHERE LOWER(series.name) LIKE ?
        ORDER BY product.id
        """,
        (f"%{marker}%",),
    ):
        candidates = (
            _identity(row["name"]),
            _identity(row["config_group"]),
            confirmed.get(_identity(row["name"]), ""),
        )
        matched = next((version_models[key] for key in candidates if key in version_models), None)
        if matched and int(row["id"]) not in mappings:
            mappings[int(row["id"])] = matched
    return mappings, reused_product_model_ids


def _version_mapping_review(
    connection: sqlite3.Connection,
    *,
    version_id: int,
) -> dict[str, Any]:
    models = [
        {
            "id": int(row["id"]),
            "model_name": row["model_name"],
            "channel_count": row["channel_count"],
        }
        for row in connection.execute(
            "SELECT id, model_name, channel_count FROM registration_package_version_models "
            "WHERE version_id = ? ORDER BY id",
            (version_id,),
        )
    ]
    mappings = [
        {
            "product_model_id": int(row["product_model_id"]),
            "product_model_name": row["product_model_name"],
            "registration_model_name": row["registration_model_name"],
            "mapping_type": row["mapping_type"],
            "review_status": row["review_status"],
        }
        for row in connection.execute(
            """
            SELECT mapping.product_model_id,
                   product.name AS product_model_name,
                   version_model.model_name AS registration_model_name,
                   mapping.mapping_type, mapping.review_status
            FROM registration_package_version_product_mappings mapping
            JOIN product_models product ON product.id = mapping.product_model_id
            JOIN registration_package_version_models version_model
              ON version_model.id = mapping.version_model_id
            WHERE mapping.version_id = ?
            ORDER BY product.id
            """,
            (version_id,),
        )
    ]
    return {"registration_models": models, "mappings": mappings}


def get_registration_package_version_mapping_review(
    database_path: str | Path,
    *,
    version_id: int,
) -> dict[str, Any]:
    """读取可恢复的草稿映射确认信息。"""

    connection = sqlite3.connect(Path(database_path))
    connection.row_factory = sqlite3.Row
    try:
        version = connection.execute(
            """
            SELECT id, status, model_count, probe_count, matrix_count
            FROM registration_package_versions
            WHERE id = ?
            """,
            (version_id,),
        ).fetchone()
        if version is None:
            raise RegistrationPackageError("注册资料包版本不存在")
        if version["status"] != "draft":
            raise RegistrationPackageError("只有待确认草稿可以继续编辑机型映射")
        return {
            "id": int(version["id"]),
            "status": version["status"],
            "model_count": int(version["model_count"]),
            "probe_count": int(version["probe_count"]),
            "matrix_count": int(version["matrix_count"]),
            **_version_mapping_review(connection, version_id=version_id),
        }
    finally:
        connection.close()


def _cleanup_unreferenced_staged_ingest(
    database_path: Path,
    *,
    document_ids: list[int],
    batch_id: int,
    managed_paths: tuple[Path, ...],
) -> None:
    """清理幂等复用或登记失败后没有被版本引用的导入中间数据。"""

    connection = sqlite3.connect(database_path, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        referenced = connection.execute(
            "SELECT 1 FROM registration_package_versions WHERE import_batch_id = ?",
            (batch_id,),
        ).fetchone()
        if referenced is None:
            connection.execute(
                "DELETE FROM registration_import_batches WHERE id = ?", (batch_id,)
            )
            placeholders = ",".join("?" for _ in document_ids)
            connection.execute(
                f"DELETE FROM knowledge_documents WHERE id IN ({placeholders})",
                tuple(document_ids),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        return
    finally:
        connection.close()
    if referenced is None:
        for path in managed_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def update_registration_package_version_mappings(
    database_path: str | Path,
    *,
    version_id: int,
    product_model_mappings: dict[int, str],
) -> dict[str, Any]:
    connection = sqlite3.connect(Path(database_path), isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute(
            "SELECT status FROM registration_package_versions WHERE id = ?",
            (version_id,),
        ).fetchone()
        if version is None:
            raise RegistrationPackageError("注册资料包版本不存在")
        if version["status"] != "draft":
            raise RegistrationPackageError("只有待确认草稿可以修改机型映射")
        _replace_version_mappings(
            connection,
            version_id=version_id,
            product_model_mappings=product_model_mappings,
        )
        review = _version_mapping_review(connection, version_id=version_id)
        connection.commit()
        return review
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def set_registration_package_version_supporting_documents(
    database_path: str | Path,
    *,
    version_id: int,
    documents: list[tuple[int, str]],
) -> dict[str, Any]:
    """Replace the supporting registration documents attached to a draft version."""

    allowed_roles = {"original_certificate", "change_certificate"}
    migrate_registration_schema(database_path)
    connection = sqlite3.connect(Path(database_path), isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute(
            """
            SELECT version.id, version.status, version.certificate_document_id,
                   version.difference_document_id, package.country_code,
                   package.product_series
            FROM registration_package_versions version
            JOIN registration_packages package ON package.id = version.package_id
            WHERE version.id = ?
            """,
            (version_id,),
        ).fetchone()
        if version is None:
            raise RegistrationPackageError("注册资料包版本不存在")
        if version["status"] != "draft":
            raise RegistrationPackageError("只有待确认草稿可以修改关联注册文件")

        normalized: list[tuple[int, str]] = []
        seen_documents: set[int] = set()
        for document_id, role in documents:
            cleaned_role = str(role or "").strip()
            if cleaned_role not in allowed_roles:
                raise RegistrationPackageError(f"不支持的注册文件角色：{role}")
            if int(document_id) in seen_documents:
                raise RegistrationPackageError("关联注册文件不能重复")
            if int(document_id) in {
                int(version["certificate_document_id"]),
                int(version["difference_document_id"]),
            }:
                raise RegistrationPackageError("主注册文件无需重复关联")
            document = _document(connection, int(document_id))
            if (
                document["document_type"] != "registration_certificate"
                or document["source_status"] != "active"
                or document["country"] != version["country_code"]
            ):
                raise RegistrationPackageError("关联注册文件类型、国家或状态不正确")
            if (
                version["product_series"]
                and document["product_series"]
                and version["product_series"] != document["product_series"]
            ):
                raise RegistrationPackageError("关联注册文件产品系列不一致")
            _reference_controlled_document(
                Path(database_path),
                country_code=version["country_code"],
                registration_number="supporting",
                role=cleaned_role,
                document=document,
            )
            seen_documents.add(int(document_id))
            normalized.append((int(document_id), cleaned_role))

        connection.execute(
            "DELETE FROM registration_package_version_documents WHERE version_id = ?",
            (version_id,),
        )
        for sort_order, (document_id, role) in enumerate(normalized):
            connection.execute(
                """
                INSERT INTO registration_package_version_documents (
                    version_id, document_id, role, sort_order
                ) VALUES (?, ?, ?, ?)
                """,
                (version_id, document_id, role, sort_order),
            )
        connection.commit()
        return {"version_id": version_id, "document_count": len(normalized)}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def set_registration_package_enabled(
    database_path: str | Path,
    *,
    package_id: int,
    is_enabled: bool,
    updated_by: str,
) -> dict[str, Any]:
    """Enable or disable a valid registration package without changing its version."""

    actor = str(updated_by or "").strip()
    if not actor:
        raise RegistrationPackageError("启用状态变更人不能为空")
    connection = sqlite3.connect(Path(database_path), isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        package = connection.execute(
            "SELECT id FROM registration_packages WHERE id = ?",
            (package_id,),
        ).fetchone()
        if package is None:
            raise RegistrationPackageError("注册资料包不存在")
        connection.execute(
            """
            UPDATE registration_packages
            SET is_enabled = ?,
                enable_status_changed_at = CURRENT_TIMESTAMP,
                enable_status_changed_by = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(is_enabled), actor, package_id),
        )
        updated = connection.execute(
            """
            SELECT id, country_code, unit_code, display_name, product_series,
                   registration_number, identity_source, confirmed_by,
                   is_enabled, enable_status_changed_at, enable_status_changed_by
            FROM registration_packages WHERE id = ?
            """,
            (package_id,),
        ).fetchone()
        connection.commit()
        return {
            **dict(updated),
            "is_enabled": bool(updated["is_enabled"]),
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def stage_registration_package_draft(
    database_path: str | Path,
    *,
    country_code: str,
    unit_code: str,
    display_name: str,
    product_series: str | None,
    registration_number: str,
    certificate_path: str | Path,
    difference_path: str | Path,
    certificate_version: str | None,
    difference_version: str | None,
    confirmed_by: str,
    change_note: str | None = None,
    effective_date: str | None = None,
    product_model_mappings: dict[int, str] | None = None,
    store_sources: bool = True,
) -> dict[str, Any]:
    """成对登记原件、解析差异表，并生成待确认的独立资料包版本。

    ``store_sources=False`` 用于已位于受控目录的原件：数据库直接登记并
    引用其绝对路径，不再创建应用内来源副本或版本归档副本。
    """

    database = Path(database_path)
    certificate_source = Path(certificate_path)
    difference_source = Path(difference_path)
    if certificate_source.suffix.lower() != ".pdf":
        raise RegistrationPackageError("注册证文件必须为 PDF")
    if difference_source.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise RegistrationPackageError("注册差异表必须为 Excel 文件")
    snapshot_json, model_count, probe_count, matrix_count = _draft_snapshot(
        difference_source
    )
    migrate_registration_schema(database)
    if store_sources:
        managed_certificate = _managed_source_copy(
            database,
            registration_number=registration_number,
            role="certificate",
            source_path=certificate_source,
        )
        managed_difference = _managed_source_copy(
            database,
            registration_number=registration_number,
            role="difference",
            source_path=difference_source,
        )
        managed_paths = (managed_certificate, managed_difference)
    else:
        managed_certificate = certificate_source.resolve()
        managed_difference = difference_source.resolve()
        managed_paths = ()
    certificate_sha = _file_sha256(managed_certificate)
    difference_sha = _file_sha256(managed_difference)
    snapshot_hash = hashlib.sha256(
        f"{country_code}|{unit_code}|{difference_sha}|{snapshot_json}".encode("utf-8")
    ).hexdigest()
    connection = sqlite3.connect(database, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        document_ids = []
        inserted_document_ids = []
        for document_type, title, source, version, sha, mime_type in (
            (
                "registration_certificate",
                f"{display_name} 注册证",
                managed_certificate,
                certificate_version,
                certificate_sha,
                "application/pdf",
            ),
            (
                "registration_difference",
                f"{display_name} 注册差异表",
                managed_difference,
                difference_version,
                difference_sha,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        ):
            existing = connection.execute(
                """
                SELECT id, document_type, sha256, country, product_series, source_status
                FROM knowledge_documents WHERE file_path = ?
                """,
                (str(source),),
            ).fetchone()
            if existing is not None:
                if (
                    existing["document_type"] != document_type
                    or existing["sha256"] != sha
                    or existing["country"] != country_code
                    or existing["source_status"] != "active"
                    or (
                        product_series
                        and existing["product_series"]
                        and existing["product_series"] != product_series
                    )
                ):
                    raise RegistrationPackageError(
                        f"受控原件登记信息不一致：{source.name}"
                    )
                document_ids.append(int(existing["id"]))
                continue
            cursor = connection.execute(
                """
                INSERT INTO knowledge_documents (
                    document_type, title, file_name, file_path, version,
                    market, country, product_series, mime_type, sha256, source_status
                ) VALUES (?, ?, ?, ?, ?, 'domestic', ?, ?, ?, ?, 'active')
                """,
                (
                    document_type,
                    title,
                    source.name,
                    str(source),
                    version,
                    country_code,
                    product_series,
                    mime_type,
                    sha,
                ),
            )
            document_id = int(cursor.lastrowid)
            document_ids.append(document_id)
            inserted_document_ids.append(document_id)
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
                document_ids[1],
                difference_version,
                difference_sha,
                snapshot_hash,
                snapshot_json,
                model_count,
                probe_count,
                matrix_count,
            ),
        )
        batch_id = int(cursor.lastrowid)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    try:
        draft = record_registration_package_version(
            database,
            country_code=country_code,
            unit_code=unit_code,
            display_name=display_name,
            product_series=product_series,
            certificate_document_id=document_ids[0],
            difference_document_id=document_ids[1],
            import_batch_id=batch_id,
            registration_number=registration_number,
            identity_source=(
                "paired_upload" if store_sources else "controlled_material"
            ),
            confirmed_by=confirmed_by,
            change_note=change_note,
            effective_date=effective_date,
        )
    except Exception:
        _cleanup_unreferenced_staged_ingest(
            database,
            document_ids=inserted_document_ids,
            batch_id=batch_id,
            managed_paths=managed_paths,
        )
        raise
    if draft["reused"]:
        _cleanup_unreferenced_staged_ingest(
            database,
            document_ids=inserted_document_ids,
            batch_id=batch_id,
            managed_paths=managed_paths,
        )
        if draft["status"] != "draft":
            raise RegistrationPackageError("相同注册资料已发布，无需重复生成草稿")
    connection = sqlite3.connect(database, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        mappings = product_model_mappings
        approved_product_model_ids: set[int] = set()
        if mappings is None:
            mappings, approved_product_model_ids = _auto_version_mappings(
                connection,
                version_id=int(draft["id"]),
                country_code=country_code,
            )
        mapping_count = _replace_version_mappings(
            connection,
            version_id=int(draft["id"]),
            product_model_mappings=mappings,
            approved_product_model_ids=approved_product_model_ids,
        )
        review = _version_mapping_review(connection, version_id=int(draft["id"]))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {**draft, "mapping_count": mapping_count, **review}


def publish_registration_package_version(
    database_path: str | Path,
    *,
    version_id: int,
    confirmed_by: str,
) -> dict[str, Any]:
    """原子发布一个资料包草稿，只同步该注册证确认过的产品机型。"""

    connection = sqlite3.connect(Path(database_path), isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute(
            """
            SELECT version.*, package.country_code
            FROM registration_package_versions version
            JOIN registration_packages package ON package.id = version.package_id
            WHERE version.id = ?
            """,
            (version_id,),
        ).fetchone()
        if version is None:
            raise RegistrationPackageError("注册资料包版本不存在")
        if version["status"] != "draft":
            raise RegistrationPackageError("只有待确认草稿可以发布")
        mappings = connection.execute(
            """
            SELECT mapping.product_model_id, mapping.mapping_type,
                   version_model.registration_model_id
            FROM registration_package_version_product_mappings mapping
            JOIN registration_package_version_models version_model
              ON version_model.id = mapping.version_model_id
             AND version_model.version_id = mapping.version_id
            WHERE mapping.version_id = ? AND mapping.review_status <> 'rejected'
            ORDER BY mapping.product_model_id
            """,
            (version_id,),
        ).fetchall()
        if not mappings:
            raise RegistrationPackageError("发布前必须确认至少一个产品机型映射")
        connection.execute(
            "UPDATE registration_package_versions SET status = 'superseded' "
            "WHERE package_id = ? AND status = 'active'",
            (version["package_id"],),
        )
        connection.execute(
            "DELETE FROM product_registration_model_links WHERE registration_package_id = ?",
            (version["package_id"],),
        )
        for mapping in mappings:
            connection.execute(
                """
                INSERT INTO product_registration_model_links (
                    product_model_id, registration_model_id,
                    registration_package_id, mapping_type, source, review_status
                ) VALUES (?, ?, ?, ?, 'registration_package_publish', 'approved')
                """,
                (
                    mapping["product_model_id"],
                    mapping["registration_model_id"],
                    version["package_id"],
                    mapping["mapping_type"],
                ),
            )
        connection.execute(
            "UPDATE registration_package_version_product_mappings "
            "SET review_status = 'approved' WHERE version_id = ?",
            (version_id,),
        )
        connection.execute(
            """
            UPDATE registration_package_versions
            SET status = 'active', published_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (version_id,),
        )
        connection.execute(
            "UPDATE registration_packages SET confirmed_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (str(confirmed_by or "").strip(), version["package_id"]),
        )
        row = connection.execute(
            "SELECT * FROM registration_package_versions WHERE id = ?",
            (version_id,),
        ).fetchone()
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"注册资料包发布引入外键异常：{violations}")
        connection.commit()
        return _version_result(row, reused=False)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

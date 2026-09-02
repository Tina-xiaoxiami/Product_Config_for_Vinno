"""成对管理注册证与注册差异表的不可变版本记录。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from app.services.registration_rules import normalize_business_name
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
            "registration_status_changed": len(status_changes),
        },
        "models": {
            "added": _display_names(current_models, "model_name", models_added),
            "removed": _display_names(previous_models, "model_name", models_removed),
        },
        "probes": {
            "added": _display_names(current_probes, "probe_model", probes_added),
            "removed": _display_names(previous_probes, "probe_model", probes_removed),
            "ipn_changed": ipn_changed,
        },
        "registration_status_changes": status_changes,
    }


def _document(connection: sqlite3.Connection, document_id: int) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT id, document_type, version, country, product_series, sha256, source_status
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
               model_count, probe_count, matrix_count
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
    change_note: str | None = None,
    effective_date: str | None = None,
) -> dict[str, Any]:
    """校验、记录并激活一对注册资料；重复资料包幂等复用。"""

    path = Path(database_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    cleaned_country = str(country_code or "").strip().upper()
    cleaned_unit = str(unit_code or "").strip()
    cleaned_name = str(display_name or "").strip()
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
            connection.execute(
                """
                INSERT INTO registration_packages (
                    country_code, unit_code, display_name, product_series
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(country_code, unit_code) DO UPDATE SET
                    display_name = excluded.display_name,
                    product_series = excluded.product_series,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (cleaned_country, cleaned_unit, cleaned_name, product_series),
            )
            package = connection.execute(
                """
                SELECT id FROM registration_packages
                WHERE country_code = ? AND unit_code = ?
                """,
                (cleaned_country, cleaned_unit),
            ).fetchone()
            package_id = int(package["id"])
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
            diff = compute_registration_snapshot_diff(
                previous["snapshot_json"] if previous else None,
                batch["snapshot_json"],
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
            if previous is not None:
                connection.execute(
                    """
                    UPDATE registration_package_versions
                    SET status = 'superseded'
                    WHERE id = ?
                    """,
                    (previous["id"],),
                )
            cursor = connection.execute(
                """
                INSERT INTO registration_package_versions (
                    package_id, version_no, previous_version_id,
                    certificate_document_id, certificate_version, certificate_sha256,
                    difference_document_id, difference_version, difference_sha256,
                    import_batch_id, snapshot_hash, pair_hash, diff_json, status,
                    change_note, effective_date, model_count, probe_count, matrix_count,
                    published_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active',
                          ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
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
                    import_batch_id,
                    batch["snapshot_hash"],
                    pair_hash,
                    json.dumps(diff, ensure_ascii=False, sort_keys=True),
                    str(change_note or "").strip() or None,
                    effective_date,
                    batch["model_count"],
                    batch["probe_count"],
                    batch["matrix_count"],
                ),
            )
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"注册资料包引入外键异常：{violations}")
            row = connection.execute(
                "SELECT * FROM registration_package_versions WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
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
        change_note=change_note,
    )

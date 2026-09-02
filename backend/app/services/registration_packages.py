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


def _artifact_directory(
    database_path: Path,
    *,
    country_code: str,
    registration_number: str,
) -> Path:
    safe_number = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", registration_number)
    return database_path.parent / "registration_artifacts" / country_code / safe_number


def _archive_document(
    database_path: Path,
    *,
    country_code: str,
    registration_number: str,
    role: str,
    document: sqlite3.Row,
) -> tuple[str, str, str | None]:
    source = Path(str(document["file_path"]))
    if not source.is_absolute() or not source.is_file():
        raise RegistrationPackageError(
            f"{role}原文件不存在或尚未同步，不能建立不可变历史"
        )
    expected_sha = str(document["sha256"])
    if _file_sha256(source) != expected_sha:
        raise RegistrationPackageError(f"{role}原文件内容与登记哈希不一致")

    target_directory = _artifact_directory(
        database_path,
        country_code=country_code,
        registration_number=registration_number,
    )
    target_directory.mkdir(parents=True, exist_ok=True)
    suffix = Path(str(document["file_name"])).suffix.lower()
    target = target_directory / f"{role}-{expected_sha}{suffix}"
    if target.exists():
        if _file_sha256(target) != expected_sha:
            raise RegistrationPackageError(f"{role}归档副本哈希不一致")
    else:
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            shutil.copyfile(source, temporary)
            if _file_sha256(temporary) != expected_sha:
                raise RegistrationPackageError(f"{role}归档复制校验失败")
            temporary.replace(target)
        finally:
            if temporary.exists():
                temporary.unlink()
    return str(target.resolve()), str(document["file_name"]), document["mime_type"]


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
        key: {"probe_model": item["probe_model"], "ipn": str(item.get("ipn") or "")}
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

            certificate_artifact = _archive_document(
                path,
                country_code=cleaned_country,
                registration_number=cleaned_registration_number,
                role="certificate",
                document=certificate,
            )
            difference_artifact = _archive_document(
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

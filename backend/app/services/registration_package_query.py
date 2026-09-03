"""注册资料包及不可变版本的只读查询。"""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


_VERSION_SELECT = """
    SELECT version.id, version.package_id, version.version_no,
           version.previous_version_id, version.status, version.change_note,
           version.effective_date, version.model_count, version.probe_count,
           version.matrix_count, version.created_at, version.published_at,
           version.diff_json,
           version.certificate_document_id, version.certificate_version,
           version.certificate_sha256, certificate.title AS certificate_title,
           version.certificate_file_name, version.certificate_mime_type,
           version.difference_document_id, version.difference_version,
           version.difference_sha256, difference.title AS difference_title,
           version.difference_file_name, version.difference_mime_type
    FROM registration_package_versions version
    JOIN knowledge_documents certificate
      ON certificate.id = version.certificate_document_id
    JOIN knowledge_documents difference
      ON difference.id = version.difference_document_id
"""


def _version_item(row) -> dict:
    return {
        "id": int(row.id),
        "package_id": int(row.package_id),
        "version_no": int(row.version_no),
        "previous_version_id": (
            int(row.previous_version_id) if row.previous_version_id else None
        ),
        "status": row.status,
        "change_note": row.change_note,
        "effective_date": row.effective_date,
        "model_count": int(row.model_count),
        "probe_count": int(row.probe_count),
        "matrix_count": int(row.matrix_count),
        "created_at": row.created_at,
        "published_at": row.published_at,
        "diff": json.loads(row.diff_json),
        "certificate": {
            "document_id": int(row.certificate_document_id),
            "title": row.certificate_title,
            "version": row.certificate_version,
            "sha256": row.certificate_sha256,
            "preview_url": (
                f"/api/registrations/package-versions/{row.id}/artifacts/certificate"
            ),
        },
        "difference": {
            "document_id": int(row.difference_document_id),
            "title": row.difference_title,
            "version": row.difference_version,
            "sha256": row.difference_sha256,
            "preview_url": (
                f"/api/registrations/package-versions/{row.id}/artifacts/difference"
            ),
        },
        "supporting_documents": [],
    }


async def _add_supporting_documents(session: AsyncSession, item: dict) -> dict:
    result = await session.execute(
        text(
            """
            SELECT link.role, document.id, document.title, document.version,
                   document.sha256
            FROM registration_package_version_documents link
            JOIN knowledge_documents document ON document.id = link.document_id
            WHERE link.version_id = :version_id
            ORDER BY link.sort_order, link.id
            """
        ),
        {"version_id": item["id"]},
    )
    item["supporting_documents"] = [
        {
            "document_id": int(row.id),
            "title": row.title,
            "version": row.version,
            "sha256": row.sha256,
            "preview_url": f"/api/knowledge/documents/{row.id}/preview",
            "role": row.role,
        }
        for row in result
    ]
    return item


def _package_item(row) -> dict:
    return {
        "id": int(row.id),
        "country_code": row.country_code,
        "unit_code": row.unit_code,
        "display_name": row.display_name,
        "product_series": row.product_series,
        "registration_number": row.registration_number,
        "identity_source": row.identity_source,
        "confirmed_by": row.confirmed_by,
        "is_enabled": bool(row.is_enabled),
        "enable_status_changed_at": row.enable_status_changed_at,
        "enable_status_changed_by": row.enable_status_changed_by,
    }


async def list_registration_packages(
    session: AsyncSession,
    *,
    country_code: str,
) -> list[dict]:
    package_rows = await session.execute(
        text(
            """
            SELECT id, country_code, unit_code, display_name, product_series,
                   registration_number, identity_source, confirmed_by,
                   is_enabled, enable_status_changed_at, enable_status_changed_by
            FROM registration_packages
            WHERE country_code = :country_code
            ORDER BY display_name, id
            """
        ),
        {"country_code": country_code},
    )
    packages = [_package_item(row) for row in package_rows]
    if not packages:
        return []
    version_rows = await session.execute(
        text(
            _VERSION_SELECT
            + """
            WHERE version.status = 'active'
              AND version.package_id IN (
                  SELECT id FROM registration_packages
                  WHERE country_code = :country_code
              )
            """
        ),
        {"country_code": country_code},
    )
    current_by_package = {}
    for row in version_rows:
        item = await _add_supporting_documents(session, _version_item(row))
        current_by_package[int(row.package_id)] = item
    for package in packages:
        package["current_version"] = current_by_package.get(package["id"])
    return packages


async def list_registration_package_versions(
    session: AsyncSession,
    *,
    package_id: int,
) -> dict | None:
    package_result = await session.execute(
        text(
            """
            SELECT id, country_code, unit_code, display_name, product_series,
                   registration_number, identity_source, confirmed_by,
                   is_enabled, enable_status_changed_at, enable_status_changed_by
            FROM registration_packages WHERE id = :package_id
            """
        ),
        {"package_id": package_id},
    )
    package = package_result.one_or_none()
    if package is None:
        return None
    version_rows = await session.execute(
        text(
            _VERSION_SELECT
            + """
            WHERE version.package_id = :package_id
            ORDER BY version.version_no DESC
            """
        ),
        {"package_id": package_id},
    )
    items = [
        await _add_supporting_documents(session, _version_item(row))
        for row in version_rows
    ]
    return {
        "package": _package_item(package),
        "items": items,
    }


async def get_registration_package_version(
    session: AsyncSession,
    *,
    version_id: int,
) -> dict | None:
    result = await session.execute(
        text(
            _VERSION_SELECT
            + """
            WHERE version.id = :version_id
            """
        ),
        {"version_id": version_id},
    )
    row = result.one_or_none()
    if row is None:
        return None
    return await _add_supporting_documents(session, _version_item(row))


async def get_registration_package_artifact(
    session: AsyncSession,
    *,
    version_id: int,
    artifact_type: str,
) -> dict | None:
    if artifact_type not in {"certificate", "difference"}:
        return None
    result = await session.execute(
        text(
            f"""
            SELECT {artifact_type}_artifact_path AS file_path,
                   {artifact_type}_file_name AS file_name,
                   {artifact_type}_mime_type AS mime_type,
                   {artifact_type}_sha256 AS sha256
            FROM registration_package_versions
            WHERE id = :version_id
            """
        ),
        {"version_id": version_id},
    )
    row = result.one_or_none()
    if row is None:
        return None
    return {
        "file_path": row.file_path,
        "file_name": row.file_name,
        "mime_type": row.mime_type,
        "sha256": row.sha256,
    }

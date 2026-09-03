"""注册红线与选型配置的分层查询。"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.registration_rules import evaluate_probe_availability


async def list_configured_registration_models(
    session: AsyncSession,
    *,
    country_code: str,
    include_disabled: bool = False,
) -> list[dict]:
    result = await session.execute(
        text(
            """
            SELECT product.id AS product_model_id,
                   product.name AS product_model_name,
                   version_model.id AS registration_model_id,
                   version_model.model_name AS registration_model_name,
                   link.mapping_type,
                   version_model.channel_count,
                   package.id AS registration_package_id,
                   package.registration_number,
                   package.display_name AS registration_package_name
            FROM product_registration_model_links link
            JOIN product_models product ON product.id = link.product_model_id
            JOIN registration_packages package
              ON package.id = link.registration_package_id
            JOIN registration_package_versions package_version
              ON package_version.package_id = package.id
             AND package_version.status = 'active'
            JOIN registration_package_version_models version_model
              ON version_model.version_id = package_version.id
             AND version_model.registration_model_id = link.registration_model_id
            WHERE package.country_code = :country_code
              AND link.review_status = 'approved'
              AND (:include_disabled = 1 OR package.is_enabled = 1)
            ORDER BY product.id
            """
        ),
        {
            "country_code": country_code,
            "include_disabled": int(include_disabled),
        },
    )
    return [dict(row._mapping) for row in result]


async def list_registration_models(
    session: AsyncSession,
    *,
    country_code: str,
    query: str | None,
    skip: int,
    limit: int,
) -> tuple[list[dict], int]:
    cleaned_query = str(query or "").strip()
    params = {
        "country_code": country_code,
        "search_pattern": f"%{cleaned_query}%" if cleaned_query else None,
        "skip": skip,
        "limit": limit,
    }
    filters = """
        package.country_code = :country_code
        AND package_version.status = 'active'
        AND (
            :search_pattern IS NULL
            OR version_model.model_name LIKE :search_pattern
        )
    """
    total_result = await session.execute(
        text(
            f"""
            SELECT COUNT(*)
            FROM registration_package_version_models version_model
            JOIN registration_package_versions package_version
              ON package_version.id = version_model.version_id
            JOIN registration_packages package ON package.id = package_version.package_id
            WHERE {filters}
            """
        ),
        params,
    )
    result = await session.execute(
        text(
            f"""
            SELECT version_model.id,
                   package.country_code,
                   version_model.model_name,
                   version_model.channel_count,
                   package_version.difference_document_id AS source_document_id
            FROM registration_package_version_models version_model
            JOIN registration_package_versions package_version
              ON package_version.id = version_model.version_id
            JOIN registration_packages package ON package.id = package_version.package_id
            WHERE {filters}
            ORDER BY package.id, version_model.id
            LIMIT :limit OFFSET :skip
            """
        ),
        params,
    )
    return [dict(row._mapping) for row in result], int(total_result.scalar_one())


async def list_registration_model_probes(
    session: AsyncSession,
    *,
    registration_model_id: int,
) -> dict | None:
    model_result = await session.execute(
        text(
            """
            SELECT version_model.id,
                   package.country_code,
                   version_model.model_name,
                   package_version.difference_document_id AS source_document_id
            FROM registration_package_version_models version_model
            JOIN registration_package_versions package_version
              ON package_version.id = version_model.version_id
             AND package_version.status = 'active'
            JOIN registration_packages package ON package.id = package_version.package_id
            WHERE version_model.id = :registration_model_id
            """
        ),
        {"registration_model_id": registration_model_id},
    )
    model = model_result.one_or_none()
    if model is None:
        return None

    result = await session.execute(
        text(
            """
            SELECT matrix.id AS matrix_id,
                   probe.registration_probe_id AS probe_id,
                   probe.probe_model,
                   probe.ipn,
                   matrix.registration_status,
                   item.id AS config_item_id,
                   item.zh_desc AS config_name,
                   probe_master.id AS probe_master_id,
                   probe_master.model_number AS probe_master_model,
                   package_version.difference_document_id AS source_document_id,
                   matrix.source_ref
            FROM registration_package_version_model_probes matrix
            JOIN registration_package_version_probes probe
              ON probe.id = matrix.version_probe_id
            JOIN registration_package_versions package_version
              ON package_version.id = matrix.version_id
             AND package_version.status = 'active'
            LEFT JOIN config_items item
              ON item.ipn = probe.ipn AND item.category = 'Probes'
            LEFT JOIN probe_model_variants variant
              ON variant.id = (
                  SELECT MIN(candidate.id)
                  FROM probe_model_variants candidate
                  WHERE UPPER(TRIM(COALESCE(candidate.ipn, '')))
                      = UPPER(TRIM(COALESCE(probe.ipn, '')))
              )
            LEFT JOIN probe_models probe_master
              ON probe_master.id = variant.probe_model_id
            WHERE matrix.version_model_id = :registration_model_id
            ORDER BY probe.id
            """
        ),
        {"registration_model_id": registration_model_id},
    )
    items = [dict(row._mapping) for row in result]
    return {
        "registration_model_id": int(model.id),
        "country_code": model.country_code,
        "model_name": model.model_name,
        "source_document_id": (
            int(model.source_document_id) if model.source_document_id else None
        ),
        "items": items,
        "total": len(items),
    }


def _probe_summary(items: list[dict]) -> dict[str, int]:
    return {
        "registered": sum(item["registration_status"] == "registered" for item in items),
        "unregistered": sum(item["registration_status"] == "unregistered" for item in items),
        "standard": sum(item["effective_status"] == "X" for item in items),
        "optional": sum(item["effective_status"] == "O" for item in items),
        "tender": sum(item["effective_status"] == "Δ" for item in items),
        "undefined": sum(item["effective_status"] == "未定义" for item in items),
        "auxiliary": sum(item["status_source"] == "current_config_aux" for item in items),
        "conflicts": sum(bool(item["conflict"]) for item in items),
    }


async def list_product_registration_probes(
    session: AsyncSession,
    *,
    product_model_id: int,
    query: str | None,
    registration_status: str | None,
    effective_status: str | None,
    skip: int,
    limit: int,
    registration_package_id: int | None = None,
) -> dict | None:
    params = {
        "product_model_id": product_model_id,
        "registration_package_id": registration_package_id,
    }
    mapping_result = await session.execute(
        text(
            """
            SELECT product.id AS product_model_id,
                   product.name AS product_model_name,
                   version_model.id AS registration_model_id,
                   version_model.model_name AS registration_model_name,
                   package_version.difference_document_id AS source_document_id,
                   link.mapping_type,
                   package.id AS registration_package_id,
                   package.registration_number,
                   package.display_name AS registration_package_name,
                   package_version.id AS registration_package_version_id
            FROM product_registration_model_links link
            JOIN product_models product ON product.id = link.product_model_id
            JOIN registration_packages package
              ON package.id = link.registration_package_id
            JOIN registration_package_versions package_version
              ON package_version.package_id = package.id
             AND package_version.status = 'active'
            JOIN registration_package_version_models version_model
              ON version_model.version_id = package_version.id
             AND version_model.registration_model_id = link.registration_model_id
            WHERE product.id = :product_model_id
              AND link.review_status = 'approved'
              AND package.is_enabled = 1
              AND (
                  :registration_package_id IS NULL
                  OR package.id = :registration_package_id
              )
            ORDER BY package.id
            """
        ),
        params,
    )
    mappings = mapping_result.all()
    if not mappings:
        return None

    result = await session.execute(
        text(
            """
            SELECT package.id AS registration_package_id,
                   country_probe.id AS probe_id,
                   country_probe.probe_model, country_probe.ipn,
                   COALESCE(matrix.registration_status, 'unregistered')
                       AS registration_status,
                   value.selection_config, value.current_config,
                   item.id AS config_item_id, item.zh_desc AS config_name,
                   probe_master.id AS probe_master_id,
                   probe_master.model_number AS probe_master_model,
                   package_version.difference_document_id AS source_document_id
            FROM product_registration_model_links link
            JOIN registration_packages package
              ON package.id = link.registration_package_id
            JOIN registration_package_versions package_version
              ON package_version.package_id = package.id
             AND package_version.status = 'active'
            JOIN registration_package_version_models version_model
              ON version_model.version_id = package_version.id
             AND version_model.registration_model_id = link.registration_model_id
            JOIN registration_probes country_probe
              ON country_probe.country_code = package.country_code
             AND country_probe.source_status = 'active'
            LEFT JOIN registration_package_version_probes probe
              ON probe.version_id = package_version.id
             AND probe.normalized_model = country_probe.normalized_model
            LEFT JOIN registration_package_version_model_probes matrix
              ON matrix.version_model_id = version_model.id
             AND matrix.version_id = package_version.id
             AND matrix.version_probe_id = probe.id
            LEFT JOIN config_items item
              ON item.ipn = country_probe.ipn AND item.category = 'Probes'
            LEFT JOIN probe_model_variants variant
              ON variant.id = (
                  SELECT MIN(candidate.id)
                  FROM probe_model_variants candidate
                  WHERE UPPER(TRIM(COALESCE(candidate.ipn, '')))
                      = UPPER(TRIM(COALESCE(country_probe.ipn, '')))
              )
            LEFT JOIN probe_models probe_master
              ON probe_master.id = variant.probe_model_id
            LEFT JOIN config_values value
              ON value.item_id = item.id
             AND value.model_id = :product_model_id
            WHERE link.product_model_id = :product_model_id
              AND link.review_status = 'approved'
              AND package.is_enabled = 1
              AND (
                  :registration_package_id IS NULL
                  OR package.id = :registration_package_id
              )
            ORDER BY package.id, country_probe.id
            """
        ),
        params,
    )

    cleaned_query = str(query or "").strip().casefold()
    items_by_package: dict[int, list[dict]] = {
        int(mapping.registration_package_id): [] for mapping in mappings
    }
    for row in result:
        policy = evaluate_probe_availability(
            registered=row.registration_status == "registered",
            selection_config=row.selection_config,
            current_config=row.current_config,
        )
        item = {
            "probe_id": int(row.probe_id),
            "probe_model": row.probe_model,
            "ipn": row.ipn,
            "registration_status": row.registration_status,
            "registration_symbol": (
                "#" if row.registration_status == "unregistered" else "已注册"
            ),
            "selection_config": row.selection_config,
            "current_config": row.current_config,
            "effective_status": policy.effective_status,
            "status_source": policy.status_source,
            "strategy_is_formal": policy.is_formal,
            "conflict": policy.conflict,
            "config_item_id": int(row.config_item_id) if row.config_item_id else None,
            "config_name": row.config_name,
            "probe_master_id": (
                int(row.probe_master_id) if row.probe_master_id else None
            ),
            "probe_master_model": row.probe_master_model,
            "source_document_id": (
                int(row.source_document_id) if row.source_document_id else None
            ),
        }
        searchable = " ".join(
            str(value or "")
            for value in (item["probe_model"], item["ipn"], item["config_name"])
        ).casefold()
        if cleaned_query and cleaned_query not in searchable:
            continue
        if registration_status and item["registration_status"] != registration_status:
            continue
        if effective_status and item["effective_status"] != effective_status:
            continue
        items_by_package[int(row.registration_package_id)].append(item)

    registrations: list[dict] = []
    for mapping in mappings:
        items = items_by_package[int(mapping.registration_package_id)]
        registrations.append(
            {
                "registration_model_id": int(mapping.registration_model_id),
                "registration_model_name": mapping.registration_model_name,
                "source_document_id": (
                    int(mapping.source_document_id)
                    if mapping.source_document_id
                    else None
                ),
                "mapping_type": mapping.mapping_type,
                "registration_package_id": int(mapping.registration_package_id),
                "registration_number": mapping.registration_number,
                "registration_package_name": mapping.registration_package_name,
                "items": items[skip : skip + limit],
                "total": len(items),
                "skip": skip,
                "limit": limit,
                "summary": _probe_summary(items),
            }
        )

    return {
        "product_model_id": int(mappings[0].product_model_id),
        "product_model_name": mappings[0].product_model_name,
        "registrations": registrations,
        "total_registrations": len(registrations),
    }

"""Read-optimized queries for the product knowledge feature catalog."""

from __future__ import annotations

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.feature_identity import clean_feature_name


_FILTER_SQL = """
    (:identity_status IS NULL OR f.identity_status = :identity_status)
    AND (:missing_name IS NULL
         OR (:missing_name = 'cn' AND TRIM(COALESCE(f.primary_cn_name, ''), ' ' || CHAR(9) || CHAR(10) || CHAR(13) || CHAR(160) || '　') = '')
         OR (:missing_name = 'en' AND TRIM(COALESCE(f.primary_en_name, ''), ' ' || CHAR(9) || CHAR(10) || CHAR(13) || CHAR(160) || '　') = ''))
    AND (
        :search_pattern IS NULL
        OR f.name LIKE :search_pattern
        OR COALESCE(f.ipn, '') LIKE :search_pattern
        OR COALESCE(f.primary_cn_name, '') LIKE :search_pattern
        OR COALESCE(f.primary_en_name, '') LIKE :search_pattern
        OR EXISTS (
            SELECT 1 FROM feature_names search_name
            WHERE search_name.feature_id = f.id
              AND search_name.review_status = 'approved'
              AND search_name.name LIKE :search_pattern
        )
        OR EXISTS (
            SELECT 1
            FROM feature_config_item_links search_link
            JOIN config_items search_item
              ON search_item.id = search_link.config_item_id
            WHERE search_link.feature_id = f.id
              AND search_link.review_status = 'approved'
              AND (
                  search_item.ipn LIKE :search_pattern
                  OR COALESCE(search_item.rd_name, '') LIKE :search_pattern
                  OR COALESCE(search_item.zh_desc, '') LIKE :search_pattern
                  OR COALESCE(search_item.en_desc, '') LIKE :search_pattern
              )
        )
    )
"""


async def _hydrate_features(
    session: AsyncSession,
    feature_rows: list,
) -> list[dict]:
    if not feature_rows:
        return []

    feature_ids = [int(row.id) for row in feature_rows]
    names_query = text(
        """
        SELECT feature_id, language, name, name_type, source
        FROM feature_names
        WHERE feature_id IN :feature_ids AND review_status = 'approved'
        ORDER BY feature_id,
                 CASE name_type WHEN 'primary' THEN 0 ELSE 1 END,
                 id
        """
    ).bindparams(bindparam("feature_ids", expanding=True))
    link_query = text(
        """
        SELECT link.feature_id, item.ipn, link.relation_type,
               item.zh_desc, item.en_desc,
               (SELECT COUNT(*) FROM config_items duplicate WHERE TRIM(duplicate.ipn)=TRIM(item.ipn)) AS ipn_count
        FROM feature_config_item_links link
        JOIN config_items item ON item.id = link.config_item_id
        WHERE link.feature_id IN :feature_ids
          AND link.review_status = 'approved'
        ORDER BY link.feature_id, item.id
        """
    ).bindparams(bindparam("feature_ids", expanding=True))
    names_result = await session.execute(names_query, {"feature_ids": feature_ids})
    links_result = await session.execute(link_query, {"feature_ids": feature_ids})

    names_by_feature: dict[int, list[dict]] = {feature_id: [] for feature_id in feature_ids}
    for row in names_result:
        names_by_feature[int(row.feature_id)].append(
            {
                "language": row.language,
                "name": row.name,
                "name_type": row.name_type,
                "source": row.source,
            }
        )

    ipns_by_feature: dict[int, list[dict]] = {feature_id: [] for feature_id in feature_ids}
    primary_names: dict[int, list[tuple[str, str]]] = {}
    primary_counts: dict[int, int] = {}
    for row in links_result:
        if row.relation_type == "primary":
            primary_counts[int(row.feature_id)] = primary_counts.get(int(row.feature_id), 0) + 1
        if row.relation_type == "primary" and row.ipn_count == 1 and clean_feature_name(row.zh_desc):
            primary_names.setdefault(int(row.feature_id), []).append((str(row.ipn).strip(), clean_feature_name(row.zh_desc)))
        ipns_by_feature[int(row.feature_id)].append(
            {
                "ipn": row.ipn,
                "relation_type": row.relation_type,
                "zh_desc": row.zh_desc,
                "en_desc": row.en_desc,
            }
        )

    items = []
    for row in feature_rows:
        feature_id = int(row.id)
        primaries = primary_names.get(feature_id, [])
        display_cn_name = (primaries[0][1] if len(primaries) == 1 and primary_counts.get(feature_id) == 1
                           and primaries[0][0] == str(row.primary_ipn or '').strip() else None)
        names = names_by_feature[feature_id]
        if display_cn_name and row.primary_cn_name and display_cn_name != row.primary_cn_name:
            if not any(name['language'] == 'cn' and name['name_type'] == 'alias'
                       and name['name'] == row.primary_cn_name for name in names):
                names.append({'language': 'cn', 'name': row.primary_cn_name, 'name_type': 'alias',
                              'source': 'features.primary_cn_name'})
        items.append({
            'id': feature_id, 'legacy_name': row.legacy_name, 'group_name': row.group_name,
            'identity_status': row.identity_status, 'primary_cn_name': row.primary_cn_name,
            'display_cn_name': display_cn_name, 'primary_en_name': row.primary_en_name,
            'names': names, 'ipns': ipns_by_feature[feature_id],
        })
    return items



async def list_feature_knowledge(
    session: AsyncSession,
    *,
    query: str | None = None,
    identity_status: str | None = None,
    missing_name: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[dict], int]:
    cleaned_query = str(query or "").strip()
    params = {
        "identity_status": identity_status,
        "missing_name": missing_name,
        "search_pattern": f"%{cleaned_query}%" if cleaned_query else None,
        "skip": skip,
        "limit": limit,
    }
    total_result = await session.execute(
        text(f"SELECT COUNT(*) FROM features f WHERE {_FILTER_SQL}"),
        params,
    )
    feature_result = await session.execute(
        text(
            f"""
            SELECT f.id, f.name AS legacy_name, g.name AS group_name,
                   f.identity_status, f.primary_cn_name, f.primary_en_name, f.ipn AS primary_ipn
            FROM features f
            JOIN feature_groups g ON g.id = f.group_id
            WHERE {_FILTER_SQL}
            ORDER BY g.sort_order, f.sort_order, f.id
            LIMIT :limit OFFSET :skip
            """
        ),
        params,
    )
    rows = list(feature_result)
    return await _hydrate_features(session, rows), int(total_result.scalar_one())


async def get_feature_knowledge(
    session: AsyncSession,
    feature_id: int,
) -> dict | None:
    result = await session.execute(
        text(
            """
            SELECT f.id, f.name AS legacy_name, g.name AS group_name,
                   f.identity_status, f.primary_cn_name, f.primary_en_name, f.ipn AS primary_ipn
            FROM features f
            JOIN feature_groups g ON g.id = f.group_id
            WHERE f.id = :feature_id
            """
        ),
        {"feature_id": feature_id},
    )
    row = result.one_or_none()
    if row is None:
        return None
    return (await _hydrate_features(session, [row]))[0]


async def get_knowledge_stats(session: AsyncSession) -> dict[str, int]:
    result = await session.execute(
        text(
            """
            SELECT COUNT(*) AS total_features,
                   SUM(CASE WHEN identity_status = 'auto_matched' THEN 1 ELSE 0 END)
                       AS auto_matched,
                   SUM(CASE WHEN identity_status = 'confirmed' THEN 1 ELSE 0 END)
                       AS confirmed,
                   SUM(CASE WHEN identity_status = 'related' THEN 1 ELSE 0 END)
                       AS related,
                   SUM(CASE WHEN identity_status = 'pending' THEN 1 ELSE 0 END)
                       AS pending
            FROM features
            """
        )
    )
    row = result.one()
    return {
        "total_features": int(row.total_features or 0),
        "auto_matched": int(row.auto_matched or 0),
        "confirmed": int(row.confirmed or 0),
        "related": int(row.related or 0),
        "pending": int(row.pending or 0),
    }

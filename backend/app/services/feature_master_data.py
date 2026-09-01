"""Maintain the feature identity that is shared by base data and knowledge search."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.feature_identity import clean_feature_name


class FeatureMasterDataError(ValueError):
    """Raised when a feature master-data update is invalid."""


def _normalized(value: str) -> str:
    return clean_feature_name(value).casefold()


def _clean_aliases(values: list[str], primary: str) -> list[str]:
    primary_key = _normalized(primary)
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = clean_feature_name(value)
        key = _normalized(cleaned)
        if not key or key == primary_key or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


async def get_feature_master_data(
    session: AsyncSession,
    feature_id: int,
) -> dict | None:
    result = await session.execute(
        text(
            """
            SELECT f.id, f.group_id, g.name AS group_name,
                   COALESCE(f.primary_cn_name, '') AS primary_cn_name,
                   COALESCE(f.primary_en_name, '') AS primary_en_name
            FROM features f
            JOIN feature_groups g ON g.id = f.group_id
            WHERE f.id = :feature_id
            """
        ),
        {"feature_id": feature_id},
    )
    feature = result.one_or_none()
    if feature is None:
        return None

    names_result = await session.execute(
        text(
            """
            SELECT language, name
            FROM feature_names
            WHERE feature_id = :feature_id
              AND name_type = 'alias'
              AND review_status = 'approved'
            ORDER BY id
            """
        ),
        {"feature_id": feature_id},
    )
    links_result = await session.execute(
        text(
            """
            SELECT item.id AS config_item_id, item.ipn, link.relation_type,
                   item.zh_desc, item.en_desc
            FROM feature_config_item_links link
            JOIN config_items item ON item.id = link.config_item_id
            WHERE link.feature_id = :feature_id
              AND link.review_status = 'approved'
            ORDER BY CASE link.relation_type
                         WHEN 'primary' THEN 0
                         WHEN 'related' THEN 1
                         ELSE 2
                     END,
                     link.id
            """
        ),
        {"feature_id": feature_id},
    )
    aliases = list(names_result)
    return {
        "id": int(feature.id),
        "group_id": int(feature.group_id),
        "group_name": feature.group_name,
        "primary_cn_name": feature.primary_cn_name,
        "primary_en_name": feature.primary_en_name,
        "alias_cn_names": [row.name for row in aliases if row.language == "cn"],
        "alias_en_names": [row.name for row in aliases if row.language == "en"],
        "ipns": [dict(row._mapping) for row in links_result],
    }


async def _resolve_ipns(session: AsyncSession, requested: list[dict]) -> list[dict]:
    normalized_ipns: set[str] = set()
    primary_count = 0
    resolved: list[dict] = []
    for entry in requested:
        ipn = str(entry["ipn"] or "").strip().upper()
        relation_type = entry["relation_type"]
        if not ipn:
            raise FeatureMasterDataError("IPN不能为空")
        if ipn in normalized_ipns:
            raise FeatureMasterDataError(f"IPN重复：{ipn}")
        normalized_ipns.add(ipn)
        if relation_type == "primary":
            primary_count += 1
        result = await session.execute(
            text(
                """
                SELECT id, ipn, zh_desc, en_desc
                FROM config_items
                WHERE UPPER(TRIM(COALESCE(ipn, ''))) = :ipn
                ORDER BY id
                """
            ),
            {"ipn": ipn},
        )
        matches = list(result)
        if not matches:
            raise FeatureMasterDataError(f"未找到IPN对应的配置项：{ipn}")
        if len(matches) > 1:
            raise FeatureMasterDataError(f"IPN对应多个配置项，请先清理基础数据：{ipn}")
        row = matches[0]
        resolved.append(
            {
                "config_item_id": int(row.id),
                "ipn": row.ipn,
                "relation_type": relation_type,
                "zh_desc": row.zh_desc,
                "en_desc": row.en_desc,
            }
        )
    if primary_count > 1:
        raise FeatureMasterDataError("一个功能只能设置一个主IPN")
    return resolved


async def _ensure_group_exists(session: AsyncSession, group_id: int) -> None:
    result = await session.execute(
        text("SELECT id FROM feature_groups WHERE id = :group_id"),
        {"group_id": group_id},
    )
    if result.one_or_none() is None:
        raise FeatureMasterDataError("功能组不存在")


async def _replace_language_names(
    session: AsyncSession,
    *,
    feature_id: int,
    language: str,
    primary: str,
    aliases: list[str],
) -> None:
    rows_result = await session.execute(
        text(
            """
            SELECT id, name, normalized_name, name_type, source
            FROM feature_names
            WHERE feature_id = :feature_id AND language = :language
            ORDER BY id
            """
        ),
        {"feature_id": feature_id, "language": language},
    )
    rows = list(rows_result)
    primary_key = _normalized(primary)

    for row in rows:
        if row.name_type == "primary" and row.normalized_name != primary_key:
            source = (
                "feature_management.history"
                if row.source == "feature_management"
                else row.source
            )
            await session.execute(
                text(
                    """
                    UPDATE feature_names
                    SET name_type = 'alias', source = :source
                    WHERE id = :name_id
                    """
                ),
                {"name_id": row.id, "source": source},
            )

    existing_result = await session.execute(
        text(
            """
            SELECT id FROM feature_names
            WHERE feature_id = :feature_id
              AND language = :language
              AND normalized_name = :normalized_name
            """
        ),
        {
            "feature_id": feature_id,
            "language": language,
            "normalized_name": primary_key,
        },
    )
    existing_primary = existing_result.one_or_none()
    if existing_primary:
        await session.execute(
            text(
                """
                UPDATE feature_names
                SET name = :name, name_type = 'primary',
                    source = 'feature_management', review_status = 'approved'
                WHERE id = :name_id
                """
            ),
            {"name": primary, "name_id": existing_primary.id},
        )
    else:
        await session.execute(
            text(
                """
                INSERT INTO feature_names (
                    feature_id, language, name, normalized_name,
                    name_type, source, review_status
                ) VALUES (
                    :feature_id, :language, :name, :normalized_name,
                    'primary', 'feature_management', 'approved'
                )
                """
            ),
            {
                "feature_id": feature_id,
                "language": language,
                "name": primary,
                "normalized_name": primary_key,
            },
        )

    requested_alias_keys = {_normalized(alias) for alias in aliases}
    manual_result = await session.execute(
        text(
            """
            SELECT id, normalized_name
            FROM feature_names
            WHERE feature_id = :feature_id
              AND language = :language
              AND name_type = 'alias'
              AND source = 'feature_management'
            """
        ),
        {"feature_id": feature_id, "language": language},
    )
    for row in manual_result:
        if row.normalized_name not in requested_alias_keys:
            await session.execute(
                text("DELETE FROM feature_names WHERE id = :name_id"),
                {"name_id": row.id},
            )

    for alias in aliases:
        normalized_alias = _normalized(alias)
        existing_result = await session.execute(
            text(
                """
                SELECT id, name_type
                FROM feature_names
                WHERE feature_id = :feature_id
                  AND language = :language
                  AND normalized_name = :normalized_name
                """
            ),
            {
                "feature_id": feature_id,
                "language": language,
                "normalized_name": normalized_alias,
            },
        )
        existing = existing_result.one_or_none()
        if existing:
            if existing.name_type != "primary":
                await session.execute(
                    text(
                        """
                        UPDATE feature_names
                        SET name = :name, review_status = 'approved'
                        WHERE id = :name_id
                        """
                    ),
                    {"name": alias, "name_id": existing.id},
                )
            continue
        await session.execute(
            text(
                """
                INSERT INTO feature_names (
                    feature_id, language, name, normalized_name,
                    name_type, source, review_status
                ) VALUES (
                    :feature_id, :language, :name, :normalized_name,
                    'alias', 'feature_management', 'approved'
                )
                """
            ),
            {
                "feature_id": feature_id,
                "language": language,
                "name": alias,
                "normalized_name": normalized_alias,
            },
        )


async def update_feature_master_data(
    session: AsyncSession,
    *,
    feature_id: int,
    group_id: int | None = None,
    sort_order: int | None = None,
    primary_cn_name: str,
    primary_en_name: str,
    alias_cn_names: list[str],
    alias_en_names: list[str],
    ipns: list[dict],
) -> dict | None:
    existing = await get_feature_master_data(session, feature_id)
    if existing is None:
        return None

    primary_cn = clean_feature_name(primary_cn_name)
    primary_en = clean_feature_name(primary_en_name)
    if not primary_cn or not primary_en:
        raise FeatureMasterDataError("中文主名称和英文主名称不能为空")
    aliases_cn = _clean_aliases(alias_cn_names, primary_cn)
    aliases_en = _clean_aliases(alias_en_names, primary_en)
    resolved_ipns = await _resolve_ipns(session, ipns)
    if group_id is not None:
        await _ensure_group_exists(session, group_id)

    await _replace_language_names(
        session,
        feature_id=feature_id,
        language="cn",
        primary=primary_cn,
        aliases=aliases_cn,
    )
    await _replace_language_names(
        session,
        feature_id=feature_id,
        language="en",
        primary=primary_en,
        aliases=aliases_en,
    )

    primary_link = next(
        (entry for entry in resolved_ipns if entry["relation_type"] == "primary"),
        None,
    )
    await session.execute(
        text(
            """
            UPDATE features
            SET name = :display_name,
                group_id = COALESCE(:group_id, group_id),
                sort_order = COALESCE(:sort_order, sort_order),
                primary_cn_name = :primary_cn_name,
                primary_en_name = :primary_en_name,
                config_item_id = :config_item_id,
                ipn = :ipn,
                identity_status = 'confirmed'
            WHERE id = :feature_id
            """
        ),
        {
            "feature_id": feature_id,
            "display_name": primary_cn,
            "group_id": group_id,
            "sort_order": sort_order,
            "primary_cn_name": primary_cn,
            "primary_en_name": primary_en,
            "config_item_id": primary_link["config_item_id"] if primary_link else None,
            "ipn": primary_link["ipn"] if primary_link else None,
        },
    )
    await session.execute(
        text("DELETE FROM feature_config_item_links WHERE feature_id = :feature_id"),
        {"feature_id": feature_id},
    )
    for entry in resolved_ipns:
        await session.execute(
            text(
                """
                INSERT INTO feature_config_item_links (
                    feature_id, config_item_id, relation_type, source, review_status
                ) VALUES (
                    :feature_id, :config_item_id, :relation_type,
                    'feature_management', 'approved'
                )
                """
            ),
            {
                "feature_id": feature_id,
                "config_item_id": entry["config_item_id"],
                "relation_type": entry["relation_type"],
            },
        )
    await session.commit()
    return await get_feature_master_data(session, feature_id)


async def create_feature_master_data(
    session: AsyncSession,
    *,
    group_id: int,
    sort_order: int,
    primary_cn_name: str,
    primary_en_name: str,
    alias_cn_names: list[str],
    alias_en_names: list[str],
    ipns: list[dict],
) -> dict:
    primary_cn = clean_feature_name(primary_cn_name)
    primary_en = clean_feature_name(primary_en_name)
    if not primary_cn or not primary_en:
        raise FeatureMasterDataError("中文主名称和英文主名称不能为空")
    await _ensure_group_exists(session, group_id)
    resolved_ipns = await _resolve_ipns(session, ipns)
    primary_link = next(
        (entry for entry in resolved_ipns if entry["relation_type"] == "primary"),
        None,
    )
    result = await session.execute(
        text(
            """
            INSERT INTO features (
                group_id, name, ipn, sort_order, config_item_id,
                primary_cn_name, primary_en_name, identity_status
            ) VALUES (
                :group_id, :name, :ipn, :sort_order, :config_item_id,
                :primary_cn_name, :primary_en_name, 'confirmed'
            )
            RETURNING id
            """
        ),
        {
            "group_id": group_id,
            "name": primary_cn,
            "ipn": primary_link["ipn"] if primary_link else None,
            "sort_order": sort_order,
            "config_item_id": primary_link["config_item_id"] if primary_link else None,
            "primary_cn_name": primary_cn,
            "primary_en_name": primary_en,
        },
    )
    feature_id = int(result.scalar_one())
    await _replace_language_names(
        session,
        feature_id=feature_id,
        language="cn",
        primary=primary_cn,
        aliases=_clean_aliases(alias_cn_names, primary_cn),
    )
    await _replace_language_names(
        session,
        feature_id=feature_id,
        language="en",
        primary=primary_en,
        aliases=_clean_aliases(alias_en_names, primary_en),
    )
    for entry in resolved_ipns:
        await session.execute(
            text(
                """
                INSERT INTO feature_config_item_links (
                    feature_id, config_item_id, relation_type, source, review_status
                ) VALUES (
                    :feature_id, :config_item_id, :relation_type,
                    'feature_management', 'approved'
                )
                """
            ),
            {
                "feature_id": feature_id,
                "config_item_id": entry["config_item_id"],
                "relation_type": entry["relation_type"],
            },
        )
    await session.commit()
    return await get_feature_master_data(session, feature_id)

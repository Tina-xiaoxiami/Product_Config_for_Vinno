"""Shared duplicate-draft validation and explicit SQLite repair support."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from typing import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.draft import ConfigDraft, DRAFT_BUSINESS_KEY_INDEX


DRAFT_BUSINESS_KEY_INDEX_NAME = DRAFT_BUSINESS_KEY_INDEX.name


class DraftIntegrityError(ValueError):
    """Raised when one draft business key has ambiguous stored records."""


@dataclass(frozen=True)
class DraftDuplicateGroup:
    batch_id: str
    item_id: int | None
    model_id: int | None
    field_name: str | None
    draft_ids: tuple[int, ...]
    redundant_ids: tuple[int, ...]
    conflict: bool


@dataclass(frozen=True)
class DraftIntegrityReport:
    database: str
    applied: bool
    exact_groups: tuple[DraftDuplicateGroup, ...]
    conflict_groups: tuple[DraftDuplicateGroup, ...]
    deleted_ids: tuple[int, ...]
    batch_count_changes: dict[str, dict[str, dict[str, int]]]


def draft_business_key(draft) -> tuple[str, int | None, int | None, str | None]:
    return (draft.batch_id, draft.item_id, draft.model_id, draft.field_name)


def _draft_meaning(draft) -> tuple[int, str, str | None, str | None]:
    return (draft.series_id, draft.change_type, draft.old_value, draft.new_value)


def group_drafts_by_business_key(drafts: Iterable) -> dict[tuple, list]:
    groups: dict[tuple, list] = {}
    for draft in drafts:
        groups.setdefault(draft_business_key(draft), []).append(draft)
    return groups


def _duplicate_group(key: tuple, drafts: Sequence) -> DraftDuplicateGroup:
    ordered = sorted(drafts, key=lambda draft: draft.id)
    meanings = {_draft_meaning(draft) for draft in ordered}
    return DraftDuplicateGroup(
        batch_id=key[0],
        item_id=key[1],
        model_id=key[2],
        field_name=key[3],
        draft_ids=tuple(draft.id for draft in ordered),
        redundant_ids=tuple(draft.id for draft in ordered[1:]),
        conflict=len(meanings) != 1,
    )


def find_duplicate_draft_groups(drafts: Iterable) -> tuple[DraftDuplicateGroup, ...]:
    return tuple(
        _duplicate_group(key, group)
        for key, group in group_drafts_by_business_key(drafts).items()
        if len(group) > 1
    )


def _group_label(group: DraftDuplicateGroup) -> str:
    field = group.field_name if group.field_name is not None else "<结构草稿>"
    return (
        f"batch={group.batch_id}, item={group.item_id}, model={group.model_id}, "
        f"field={field}, ids={list(group.draft_ids)}"
    )


def ensure_no_duplicate_draft_keys(drafts: Iterable) -> None:
    duplicates = find_duplicate_draft_groups(drafts)
    if duplicates:
        details = "; ".join(_group_label(group) for group in duplicates)
        raise DraftIntegrityError(f"草稿存在重复业务键，请先清理后再发布：{details}")


def ensure_identical_draft_group(drafts: Sequence) -> None:
    if len(drafts) < 2:
        return
    group = _duplicate_group(draft_business_key(drafts[0]), drafts)
    if group.conflict:
        raise DraftIntegrityError(
            f"同一配置位置存在相互冲突的草稿，不能自动选择：{_group_label(group)}"
        )


async def drafts_for_business_key(
    db: AsyncSession,
    *,
    batch_id: str,
    item_id: int | None,
    model_id: int | None,
    field_name: str | None,
) -> list[ConfigDraft]:
    query = select(ConfigDraft).where(
        ConfigDraft.batch_id == batch_id,
        ConfigDraft.item_id == item_id,
        ConfigDraft.model_id == model_id,
    )
    query = query.where(
        ConfigDraft.field_name.is_(None)
        if field_name is None
        else ConfigDraft.field_name == field_name
    )
    result = await db.execute(query.order_by(ConfigDraft.id))
    return list(result.scalars().all())


async def consolidate_identical_drafts(
    db: AsyncSession, drafts: Sequence[ConfigDraft]
) -> list[ConfigDraft]:
    """Collapse exact duplicates only after every duplicate group is proven safe."""

    groups = group_drafts_by_business_key(drafts)
    duplicate_groups = [group for group in groups.values() if len(group) > 1]
    for group in duplicate_groups:
        ensure_identical_draft_group(group)
    redundant_ids = {
        draft.id
        for group in duplicate_groups
        for draft in sorted(group, key=lambda row: row.id)[1:]
    }
    for draft in drafts:
        if draft.id in redundant_ids:
            await db.delete(draft)
    return [draft for draft in drafts if draft.id not in redundant_ids]


def _sqlite_duplicate_groups(connection: sqlite3.Connection) -> tuple[DraftDuplicateGroup, ...]:
    rows = connection.execute(
        """
        SELECT id, series_id, batch_id, change_type, item_id, model_id,
               field_name, old_value, new_value
        FROM config_drafts
        ORDER BY id
        """
    ).fetchall()
    return find_duplicate_draft_groups(
        SimpleNamespace(**dict(row)) for row in rows
    )


def _counts(connection: sqlite3.Connection, batch_id: str) -> dict[str, int]:
    row = connection.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN change_type = 'create' THEN 1 ELSE 0 END) AS creates,
               SUM(CASE WHEN change_type = 'update' THEN 1 ELSE 0 END) AS updates,
               SUM(CASE WHEN change_type = 'delete' THEN 1 ELSE 0 END) AS deletes
        FROM config_drafts WHERE batch_id = ?
        """,
        (batch_id,),
    ).fetchone()
    return {
        "total": int(row[0] or 0),
        "create": int(row[1] or 0),
        "update": int(row[2] or 0),
        "delete": int(row[3] or 0),
    }


def migrate_sqlite_draft_integrity(
    database_path: str | Path, *, apply: bool = False
) -> DraftIntegrityReport:
    """Preflight duplicates, optionally repair exact copies, then add the index."""

    database = Path(database_path).expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    connection = sqlite3.connect(database, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        groups = _sqlite_duplicate_groups(connection)
        exact = tuple(group for group in groups if not group.conflict)
        conflicts = tuple(group for group in groups if group.conflict)
        if apply and conflicts:
            details = "; ".join(_group_label(group) for group in conflicts)
            raise DraftIntegrityError(f"草稿重复记录存在冲突，未执行任何修复：{details}")

        deleted_ids: tuple[int, ...] = ()
        count_changes: dict[str, dict[str, dict[str, int]]] = {}
        if apply:
            affected_batches = sorted({group.batch_id for group in exact})
            before = {batch_id: _counts(connection, batch_id) for batch_id in affected_batches}
            deleted_ids = tuple(
                draft_id for group in exact for draft_id in group.redundant_ids
            )
            if deleted_ids:
                placeholders = ",".join("?" for _ in deleted_ids)
                connection.execute(
                    f"DELETE FROM config_drafts WHERE id IN ({placeholders})",
                    deleted_ids,
                )
            for batch_id in affected_batches:
                after = _counts(connection, batch_id)
                connection.execute(
                    """
                    UPDATE draft_batches
                    SET total_count = ?, create_count = ?, update_count = ?, delete_count = ?
                    WHERE id = ?
                    """,
                    (
                        after["total"],
                        after["create"],
                        after["update"],
                        after["delete"],
                        batch_id,
                    ),
                )
                count_changes[batch_id] = {"before": before[batch_id], "after": after}
            connection.execute(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS {DRAFT_BUSINESS_KEY_INDEX_NAME}
                ON config_drafts (
                    batch_id, item_id, model_id, COALESCE(field_name, '')
                )
                """
            )
            connection.commit()
        else:
            connection.rollback()
        return DraftIntegrityReport(
            database=str(database),
            applied=apply,
            exact_groups=exact,
            conflict_groups=conflicts,
            deleted_ids=deleted_ids,
            batch_count_changes=count_changes,
        )
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

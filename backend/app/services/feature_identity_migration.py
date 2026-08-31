"""Transactionally add IPN feature identities to a SQLite database copy."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
import unicodedata

from app.services.feature_identity import (
    ConfigItemIdentity,
    LegacyFeature,
    build_feature_identity_preview,
)


@dataclass(frozen=True)
class FeatureIdentityMigrationReport:
    feature_count_before: int
    feature_count_after: int
    auto_matched_count: int
    confirmed_matched_count: int
    pending_count: int
    pending_names: tuple[str, ...]
    foreign_key_violation_count: int


def _normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    }


def _add_feature_identity_columns(connection: sqlite3.Connection) -> None:
    columns = _column_names(connection, "features")
    definitions = {
        "config_item_id": "INTEGER REFERENCES config_items(id)",
        "primary_cn_name": "TEXT",
        "primary_en_name": "TEXT",
        "identity_status": "TEXT NOT NULL DEFAULT 'pending'",
    }
    for column, definition in definitions.items():
        if column not in columns:
            connection.execute(f'ALTER TABLE features ADD COLUMN "{column}" {definition}')


def _create_identity_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS feature_names (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feature_id INTEGER NOT NULL REFERENCES features(id) ON DELETE CASCADE,
            language TEXT NOT NULL CHECK (language IN ('cn', 'en')),
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            name_type TEXT NOT NULL CHECK (name_type IN ('primary', 'alias')),
            source TEXT NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'approved'
                CHECK (review_status IN ('pending', 'approved', 'rejected')),
            UNIQUE (feature_id, language, normalized_name)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_feature_primary_name
        ON feature_names(feature_id, language)
        WHERE name_type = 'primary' AND review_status = 'approved';

        CREATE TABLE IF NOT EXISTS feature_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_feature_id INTEGER NOT NULL REFERENCES features(id) ON DELETE CASCADE,
            target_feature_id INTEGER NOT NULL REFERENCES features(id) ON DELETE CASCADE,
            relation_type TEXT NOT NULL CHECK (
                relation_type IN (
                    'parent', 'child', 'parameter', 'bundle',
                    'supersedes', 'equivalent'
                )
            ),
            source_reference TEXT,
            review_status TEXT NOT NULL DEFAULT 'pending'
                CHECK (review_status IN ('pending', 'approved', 'rejected')),
            UNIQUE (source_feature_id, target_feature_id, relation_type)
        );
        """
    )


def _load_source_data(connection: sqlite3.Connection):
    config_items = [
        ConfigItemIdentity(
            id=int(row[0]),
            ipn=str(row[1] or ""),
            rd_name=str(row[2] or ""),
            zh_desc=str(row[3] or ""),
            en_desc=str(row[4] or ""),
        )
        for row in connection.execute(
            "SELECT id, ipn, rd_name, zh_desc, en_desc FROM config_items ORDER BY id"
        )
    ]
    legacy_features = [
        LegacyFeature(
            id=int(row[0]),
            name=str(row[1] or ""),
            ipn=str(row[2] or ""),
        )
        for row in connection.execute(
            "SELECT id, name, ipn FROM features ORDER BY id"
        )
    ]
    return config_items, legacy_features


def migrate_feature_identity_database(
    database_path: str | Path,
    *,
    confirmed_ipn_by_legacy_feature_id: Mapping[int, str] | None = None,
) -> FeatureIdentityMigrationReport:
    """Migrate the explicitly supplied SQLite file in one atomic transaction.

    The caller is responsible for supplying a database copy. The function never
    discovers or opens the application's production database implicitly.
    """

    path = Path(database_path)
    if not path.is_file():
        raise FileNotFoundError(path)

    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        config_items, legacy_features = _load_source_data(connection)
        preview = build_feature_identity_preview(
            config_items=config_items,
            legacy_features=legacy_features,
            confirmed_ipn_by_legacy_feature_id=confirmed_ipn_by_legacy_feature_id,
        )
        feature_count_before = connection.execute(
            "SELECT COUNT(*) FROM features"
        ).fetchone()[0]

        connection.execute("BEGIN IMMEDIATE")
        try:
            _add_feature_identity_columns(connection)
            _create_identity_tables(connection)

            for identity in preview.identities:
                connection.execute(
                    """
                    UPDATE features
                    SET config_item_id = ?, ipn = ?, primary_cn_name = ?,
                        primary_en_name = ?, identity_status = ?
                    WHERE id = ?
                    """,
                    (
                        identity.config_item_id,
                        identity.ipn,
                        identity.primary_cn_name or None,
                        identity.primary_en_name or None,
                        identity.status,
                        identity.legacy_feature_id,
                    ),
                )
                for name in identity.names:
                    connection.execute(
                        """
                        INSERT INTO feature_names (
                            feature_id, language, name, normalized_name,
                            name_type, source, review_status
                        ) VALUES (?, ?, ?, ?, ?, ?, 'approved')
                        ON CONFLICT(feature_id, language, normalized_name)
                        DO UPDATE SET
                            name = excluded.name,
                            name_type = excluded.name_type,
                            source = excluded.source,
                            review_status = excluded.review_status
                        """,
                        (
                            identity.legacy_feature_id,
                            name.language,
                            name.name,
                            _normalize_name(name.name),
                            name.name_type,
                            name.source,
                        ),
                    )

            for pending in preview.pending:
                connection.execute(
                    "UPDATE features SET identity_status = 'pending' WHERE id = ?",
                    (pending.legacy_feature_id,),
                )

            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_features_normalized_ipn
                ON features(UPPER(TRIM(ipn)))
                WHERE TRIM(COALESCE(ipn, '')) <> ''
                """
            )

            feature_count_after = connection.execute(
                "SELECT COUNT(*) FROM features"
            ).fetchone()[0]
            foreign_key_violations = connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            if feature_count_after != feature_count_before:
                raise RuntimeError("Migration changed the number of feature records")
            if foreign_key_violations:
                raise RuntimeError(
                    "Migration introduced foreign key violations: "
                    f"{foreign_key_violations}"
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

        return FeatureIdentityMigrationReport(
            feature_count_before=int(feature_count_before),
            feature_count_after=int(feature_count_after),
            auto_matched_count=sum(
                identity.status == "auto_matched" for identity in preview.identities
            ),
            confirmed_matched_count=sum(
                identity.status == "confirmed" for identity in preview.identities
            ),
            pending_count=len(preview.pending),
            pending_names=tuple(item.legacy_name for item in preview.pending),
            foreign_key_violation_count=len(foreign_key_violations),
        )
    finally:
        connection.close()

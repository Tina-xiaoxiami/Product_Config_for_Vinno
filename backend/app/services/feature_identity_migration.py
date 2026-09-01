"""Transactionally add IPN feature identities to a SQLite database copy."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3

from app.services.feature_identity import (
    ConfigItemIdentity,
    LegacyFeature,
    build_feature_identity_preview,
    clean_feature_name,
)


@dataclass(frozen=True)
class FeatureIdentityMigrationReport:
    feature_count_before: int
    feature_count_after: int
    auto_matched_count: int
    confirmed_matched_count: int
    related_feature_count: int
    pending_count: int
    pending_names: tuple[str, ...]
    foreign_key_violation_count: int


def _normalize_name(value: str) -> str:
    return clean_feature_name(value).casefold()


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

        CREATE TABLE IF NOT EXISTS feature_config_item_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feature_id INTEGER NOT NULL REFERENCES features(id) ON DELETE CASCADE,
            config_item_id INTEGER NOT NULL REFERENCES config_items(id) ON DELETE CASCADE,
            relation_type TEXT NOT NULL CHECK (
                relation_type IN ('primary', 'related', 'version_variant')
            ),
            source TEXT NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'approved'
                CHECK (review_status IN ('pending', 'approved', 'rejected')),
            UNIQUE (feature_id, config_item_id, relation_type)
        );

        CREATE TABLE IF NOT EXISTS knowledge_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_type TEXT NOT NULL,
            title TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL UNIQUE,
            version TEXT,
            market TEXT NOT NULL DEFAULT 'domestic',
            country TEXT,
            product_series TEXT,
            mime_type TEXT,
            sha256 TEXT,
            source_status TEXT NOT NULL DEFAULT 'active'
                CHECK (source_status IN ('active', 'superseded', 'archived')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS ix_knowledge_documents_type
        ON knowledge_documents(document_type);

        CREATE INDEX IF NOT EXISTS ix_knowledge_documents_market
        ON knowledge_documents(market);

        CREATE TABLE IF NOT EXISTS knowledge_document_extractions (
            document_id INTEGER PRIMARY KEY
                REFERENCES knowledge_documents(id) ON DELETE CASCADE,
            extractor_version TEXT NOT NULL,
            source_sha256 TEXT,
            status TEXT NOT NULL,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            extracted_at TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS knowledge_document_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL
                REFERENCES knowledge_documents(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            page_number INTEGER,
            section_name TEXT,
            source_ref TEXT NOT NULL,
            content TEXT NOT NULL,
            normalized_content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(document_id, chunk_index)
        );

        CREATE INDEX IF NOT EXISTS ix_knowledge_document_chunks_document
        ON knowledge_document_chunks(document_id);

        CREATE INDEX IF NOT EXISTS ix_knowledge_document_chunks_hash
        ON knowledge_document_chunks(content_hash);
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
    confirmed_relations_by_legacy_feature_id: Mapping[
        int, tuple[str, tuple[str, ...]]
    ]
    | None = None,
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
        confirmed_relations = confirmed_relations_by_legacy_feature_id or {}
        config_items_by_ipn = {
            item.ipn.strip().upper(): item for item in config_items
        }
        legacy_features_by_id = {item.id: item for item in legacy_features}
        for legacy_feature_id, (relation_type, target_ipns) in confirmed_relations.items():
            if relation_type not in {"related", "version_variant"}:
                raise ValueError(f"未知功能关系：{relation_type}")
            if legacy_feature_id not in legacy_features_by_id:
                raise ValueError(f"确认关系指向未知功能：{legacy_feature_id}")
            for target_ipn in target_ipns:
                normalized_ipn = target_ipn.strip().upper()
                if normalized_ipn not in config_items_by_ipn:
                    raise ValueError(
                        f"功能 {legacy_feature_id} 的关系指向未知IPN：{normalized_ipn}"
                    )
        preview = build_feature_identity_preview(
            config_items=config_items,
            legacy_features=legacy_features,
            confirmed_ipn_by_legacy_feature_id=confirmed_ipn_by_legacy_feature_id,
        )
        identities = [
            identity
            for identity in preview.identities
            if identity.legacy_feature_id not in confirmed_relations
        ]
        feature_count_before = connection.execute(
            "SELECT COUNT(*) FROM features"
        ).fetchone()[0]

        connection.execute("BEGIN IMMEDIATE")
        try:
            _add_feature_identity_columns(connection)
            _create_identity_tables(connection)
            connection.execute(
                "DELETE FROM feature_names WHERE source = 'config_items.rd_name'"
            )

            for identity in identities:
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
                connection.execute(
                    """
                    INSERT INTO feature_config_item_links (
                        feature_id, config_item_id, relation_type,
                        source, review_status
                    ) VALUES (?, ?, 'primary', 'feature_identity_migration', 'approved')
                    ON CONFLICT(feature_id, config_item_id, relation_type)
                    DO UPDATE SET
                        source = excluded.source,
                        review_status = excluded.review_status
                    """,
                    (identity.legacy_feature_id, identity.config_item_id),
                )

            for legacy_feature_id, (relation_type, target_ipns) in confirmed_relations.items():
                connection.execute(
                    """
                    UPDATE features
                    SET config_item_id = NULL, ipn = '',
                        primary_cn_name = NULL, primary_en_name = NULL,
                        identity_status = 'related'
                    WHERE id = ?
                    """,
                    (legacy_feature_id,),
                )
                legacy_feature = legacy_features_by_id[legacy_feature_id]
                legacy_name_language = (
                    "cn"
                    if re.search(r"[\u3400-\u9fff]", legacy_feature.name)
                    else "en"
                )
                connection.execute(
                    """
                    INSERT INTO feature_names (
                        feature_id, language, name, normalized_name,
                        name_type, source, review_status
                    ) VALUES (?, ?, ?, ?, 'alias', 'legacy_features.name', 'approved')
                    ON CONFLICT(feature_id, language, normalized_name)
                    DO UPDATE SET
                        name = excluded.name,
                        name_type = excluded.name_type,
                        source = excluded.source,
                        review_status = excluded.review_status
                    """,
                    (
                        legacy_feature_id,
                        legacy_name_language,
                        legacy_feature.name,
                        _normalize_name(legacy_feature.name),
                    ),
                )
                for target_ipn in target_ipns:
                    target_item = config_items_by_ipn[target_ipn.strip().upper()]
                    connection.execute(
                        """
                        INSERT INTO feature_config_item_links (
                            feature_id, config_item_id, relation_type,
                            source, review_status
                        ) VALUES (?, ?, ?, 'product_owner_confirmation', 'approved')
                        ON CONFLICT(feature_id, config_item_id, relation_type)
                        DO UPDATE SET
                            source = excluded.source,
                            review_status = excluded.review_status
                        """,
                        (legacy_feature_id, target_item.id, relation_type),
                    )

            for pending in preview.pending:
                if pending.legacy_feature_id in confirmed_relations:
                    continue
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

        pending = [
            item
            for item in preview.pending
            if item.legacy_feature_id not in confirmed_relations
        ]
        return FeatureIdentityMigrationReport(
            feature_count_before=int(feature_count_before),
            feature_count_after=int(feature_count_after),
            auto_matched_count=sum(
                identity.status == "auto_matched" for identity in identities
            ),
            confirmed_matched_count=sum(
                identity.status == "confirmed" for identity in identities
            ),
            related_feature_count=len(confirmed_relations),
            pending_count=len(pending),
            pending_names=tuple(item.legacy_name for item in pending),
            foreign_key_violation_count=len(foreign_key_violations),
        )
    finally:
        connection.close()

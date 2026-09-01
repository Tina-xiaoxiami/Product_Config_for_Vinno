"""国家-型号-探头注册数据结构迁移。"""

from __future__ import annotations

from pathlib import Path
import sqlite3


def migrate_registration_schema(database_path: str | Path) -> None:
    path = Path(database_path)
    if not path.is_file():
        raise FileNotFoundError(path)

    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS registration_import_batches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    country_code TEXT NOT NULL,
                    source_document_id INTEGER REFERENCES knowledge_documents(id),
                    source_version TEXT,
                    source_sha256 TEXT,
                    snapshot_hash TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    model_count INTEGER NOT NULL,
                    probe_count INTEGER NOT NULL,
                    matrix_count INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'superseded')),
                    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (country_code, snapshot_hash)
                );

                CREATE TABLE IF NOT EXISTS registration_models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    country_code TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    channel_count INTEGER,
                    import_batch_id INTEGER NOT NULL
                        REFERENCES registration_import_batches(id),
                    source_document_id INTEGER REFERENCES knowledge_documents(id),
                    source_ref TEXT,
                    source_status TEXT NOT NULL DEFAULT 'active'
                        CHECK (source_status IN ('active', 'archived')),
                    UNIQUE (country_code, normalized_name)
                );

                CREATE TABLE IF NOT EXISTS registration_probes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    country_code TEXT NOT NULL,
                    probe_model TEXT NOT NULL,
                    normalized_model TEXT NOT NULL,
                    ipn TEXT NOT NULL,
                    import_batch_id INTEGER NOT NULL
                        REFERENCES registration_import_batches(id),
                    source_document_id INTEGER REFERENCES knowledge_documents(id),
                    source_ref TEXT,
                    source_status TEXT NOT NULL DEFAULT 'active'
                        CHECK (source_status IN ('active', 'archived')),
                    UNIQUE (country_code, normalized_model),
                    UNIQUE (country_code, ipn)
                );

                CREATE TABLE IF NOT EXISTS registration_model_probes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    country_code TEXT NOT NULL,
                    registration_model_id INTEGER NOT NULL
                        REFERENCES registration_models(id) ON DELETE CASCADE,
                    registration_probe_id INTEGER NOT NULL
                        REFERENCES registration_probes(id) ON DELETE CASCADE,
                    registration_status TEXT NOT NULL
                        CHECK (registration_status IN ('registered', 'unregistered')),
                    import_batch_id INTEGER NOT NULL
                        REFERENCES registration_import_batches(id),
                    source_document_id INTEGER REFERENCES knowledge_documents(id),
                    source_ref TEXT,
                    UNIQUE (registration_model_id, registration_probe_id)
                );

                CREATE TABLE IF NOT EXISTS product_registration_model_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_model_id INTEGER NOT NULL
                        REFERENCES product_models(id) ON DELETE CASCADE,
                    registration_model_id INTEGER NOT NULL
                        REFERENCES registration_models(id) ON DELETE CASCADE,
                    mapping_type TEXT NOT NULL
                        CHECK (mapping_type IN (
                            'direct', 'config_group', 'confirmed_derived', 'manual'
                        )),
                    source TEXT NOT NULL,
                    review_status TEXT NOT NULL DEFAULT 'approved'
                        CHECK (review_status IN ('pending', 'approved', 'rejected')),
                    UNIQUE (product_model_id, registration_model_id)
                );

                CREATE INDEX IF NOT EXISTS ix_registration_models_country
                ON registration_models(country_code, source_status);
                CREATE INDEX IF NOT EXISTS ix_registration_probes_country
                ON registration_probes(country_code, source_status);
                CREATE INDEX IF NOT EXISTS ix_registration_matrix_status
                ON registration_model_probes(country_code, registration_status);
                CREATE INDEX IF NOT EXISTS ix_product_registration_links_product
                ON product_registration_model_links(product_model_id);
                """
            )
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"注册结构迁移引入外键异常：{violations}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    finally:
        connection.close()


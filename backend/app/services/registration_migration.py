"""国家-型号-探头注册数据结构迁移。"""

from __future__ import annotations

from pathlib import Path
import sqlite3


def _import_batch_has_unique_constraint(connection: sqlite3.Connection) -> bool:
    for index in connection.execute("PRAGMA index_list(registration_package_versions)"):
        if not index[2]:
            continue
        index_name = str(index[1]).replace("'", "''")
        columns = [
            row[2]
            for row in connection.execute(
                f"PRAGMA index_info('{index_name}')"
            )
        ]
        if columns == ["import_batch_id"]:
            return True
    return False


def _rebuild_registration_package_versions(connection: sqlite3.Connection) -> None:
    connection.execute("DROP INDEX IF EXISTS uq_registration_package_active")
    connection.execute("DROP INDEX IF EXISTS ix_registration_package_versions_package")
    connection.execute("DROP TABLE IF EXISTS registration_package_versions_new")
    connection.execute(
        """
        CREATE TABLE registration_package_versions_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            package_id INTEGER NOT NULL
                REFERENCES registration_packages(id) ON DELETE CASCADE,
            version_no INTEGER NOT NULL,
            previous_version_id INTEGER
                REFERENCES registration_package_versions_new(id),
            certificate_document_id INTEGER NOT NULL
                REFERENCES knowledge_documents(id),
            certificate_version TEXT,
            certificate_sha256 TEXT NOT NULL,
            difference_document_id INTEGER NOT NULL
                REFERENCES knowledge_documents(id),
            difference_version TEXT,
            difference_sha256 TEXT NOT NULL,
            certificate_artifact_path TEXT,
            certificate_file_name TEXT,
            certificate_mime_type TEXT,
            difference_artifact_path TEXT,
            difference_file_name TEXT,
            difference_mime_type TEXT,
            import_batch_id INTEGER NOT NULL
                REFERENCES registration_import_batches(id),
            snapshot_hash TEXT NOT NULL,
            pair_hash TEXT NOT NULL,
            diff_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'active', 'superseded')),
            change_note TEXT,
            effective_date TEXT,
            model_count INTEGER NOT NULL,
            probe_count INTEGER NOT NULL,
            matrix_count INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            published_at TEXT,
            CHECK (certificate_document_id <> difference_document_id),
            UNIQUE (package_id, version_no),
            UNIQUE (package_id, pair_hash)
        )
        """
    )
    columns = (
        "id, package_id, version_no, previous_version_id, "
        "certificate_document_id, certificate_version, certificate_sha256, "
        "difference_document_id, difference_version, difference_sha256, "
        "certificate_artifact_path, certificate_file_name, certificate_mime_type, "
        "difference_artifact_path, difference_file_name, difference_mime_type, "
        "import_batch_id, snapshot_hash, pair_hash, diff_json, status, change_note, "
        "effective_date, model_count, probe_count, matrix_count, created_at, published_at"
    )
    connection.execute(
        f"""
        INSERT INTO registration_package_versions_new ({columns})
        SELECT {columns} FROM registration_package_versions
        """
    )
    connection.execute("DROP TABLE registration_package_versions")
    connection.execute(
        "ALTER TABLE registration_package_versions_new "
        "RENAME TO registration_package_versions"
    )
    connection.execute(
        """
        CREATE INDEX ix_registration_package_versions_package
        ON registration_package_versions(package_id, version_no DESC)
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX uq_registration_package_active
        ON registration_package_versions(package_id)
        WHERE status = 'active'
        """
    )


def migrate_registration_schema(database_path: str | Path) -> None:
    path = Path(database_path)
    if not path.is_file():
        raise FileNotFoundError(path)

    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.executescript(
                """
                BEGIN IMMEDIATE;

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

                CREATE TABLE IF NOT EXISTS registration_packages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    country_code TEXT NOT NULL,
                    unit_code TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    product_series TEXT,
                    registration_number TEXT,
                    identity_source TEXT,
                    confirmed_by TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (country_code, unit_code)
                );

                CREATE TABLE IF NOT EXISTS registration_package_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    package_id INTEGER NOT NULL
                        REFERENCES registration_packages(id) ON DELETE CASCADE,
                    version_no INTEGER NOT NULL,
                    previous_version_id INTEGER
                        REFERENCES registration_package_versions(id),
                    certificate_document_id INTEGER NOT NULL
                        REFERENCES knowledge_documents(id),
                    certificate_version TEXT,
                    certificate_sha256 TEXT NOT NULL,
                    difference_document_id INTEGER NOT NULL
                        REFERENCES knowledge_documents(id),
                    difference_version TEXT,
                    difference_sha256 TEXT NOT NULL,
                    certificate_artifact_path TEXT,
                    certificate_file_name TEXT,
                    certificate_mime_type TEXT,
                    difference_artifact_path TEXT,
                    difference_file_name TEXT,
                    difference_mime_type TEXT,
                    import_batch_id INTEGER NOT NULL
                        REFERENCES registration_import_batches(id),
                    snapshot_hash TEXT NOT NULL,
                    pair_hash TEXT NOT NULL,
                    diff_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'active', 'superseded')),
                    change_note TEXT,
                    effective_date TEXT,
                    model_count INTEGER NOT NULL,
                    probe_count INTEGER NOT NULL,
                    matrix_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    published_at TEXT,
                    CHECK (certificate_document_id <> difference_document_id),
                    UNIQUE (package_id, version_no),
                    UNIQUE (package_id, pair_hash)
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
                    registration_package_id INTEGER
                        REFERENCES registration_packages(id),
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
                CREATE INDEX IF NOT EXISTS ix_registration_packages_country
                ON registration_packages(country_code, unit_code);
                CREATE INDEX IF NOT EXISTS ix_registration_package_versions_package
                ON registration_package_versions(package_id, version_no DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS uq_registration_package_active
                ON registration_package_versions(package_id)
                WHERE status = 'active';
                """
            )
            package_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(registration_packages)")
            }
            for column_name in (
                "registration_number",
                "identity_source",
                "confirmed_by",
            ):
                if column_name not in package_columns:
                    connection.execute(
                        f"ALTER TABLE registration_packages ADD COLUMN {column_name} TEXT"
                    )

            version_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(registration_package_versions)"
                )
            }
            for column_name in (
                "certificate_artifact_path",
                "certificate_file_name",
                "certificate_mime_type",
                "difference_artifact_path",
                "difference_file_name",
                "difference_mime_type",
            ):
                if column_name not in version_columns:
                    connection.execute(
                        "ALTER TABLE registration_package_versions "
                        f"ADD COLUMN {column_name} TEXT"
                    )
            if _import_batch_has_unique_constraint(connection):
                _rebuild_registration_package_versions(connection)
            link_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(product_registration_model_links)"
                )
            }
            if "registration_package_id" not in link_columns:
                connection.execute(
                    "ALTER TABLE product_registration_model_links "
                    "ADD COLUMN registration_package_id INTEGER "
                    "REFERENCES registration_packages(id)"
                )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_product_registration_links_package
                ON product_registration_model_links(registration_package_id)
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_registration_package_number
                ON registration_packages(country_code, registration_number)
                WHERE registration_number IS NOT NULL
                  AND registration_number <> ''
                """
            )
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"注册结构迁移引入外键异常：{violations}")
            connection.commit()
            connection.execute("PRAGMA foreign_keys = ON")
        except Exception:
            connection.rollback()
            connection.execute("PRAGMA foreign_keys = ON")
            raise
    finally:
        connection.close()

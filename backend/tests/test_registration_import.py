import sqlite3

from openpyxl import Workbook

from app.services.registration_import import import_domestic_registration_workbook
from app.services.registration_migration import migrate_registration_schema


def _create_database(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE knowledge_documents (
            id INTEGER PRIMARY KEY,
            sha256 TEXT,
            version TEXT
        );
        INSERT INTO knowledge_documents VALUES (1, 'source-sha', '20250729');

        CREATE TABLE product_series (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        INSERT INTO product_series VALUES
            (1, 'R&V10 series-China'),
            (2, 'R&V10 series-Oversea');

        CREATE TABLE product_models (
            id INTEGER PRIMARY KEY,
            series_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            config_group TEXT,
            FOREIGN KEY(series_id) REFERENCES product_series(id)
        );
        INSERT INTO product_models VALUES
            (1, 1, 'VINNO 10', NULL),
            (2, 1, 'VINNO 10E', NULL),
            (3, 1, 'VINNO 9', NULL),
            (4, 1, 'VINNO 9_Private', 'VINNO 9'),
            (5, 1, 'VINNO 9 综合版', NULL),
            (6, 2, 'VINNO 10', NULL);

        CREATE TABLE config_items (
            id INTEGER PRIMARY KEY,
            ipn TEXT,
            category TEXT,
            zh_desc TEXT
        );
        INSERT INTO config_items VALUES
            (10, '1000530', 'Probes', 'F2-5C探头'),
            (11, '1000744', 'Probes', 'G1-4P探头'),
            (12, '1000784', 'Probes', 'F4-9E探头');

        CREATE TABLE probe_models (
            id INTEGER PRIMARY KEY,
            model_number TEXT NOT NULL
        );
        CREATE TABLE probe_model_variants (
            id INTEGER PRIMARY KEY,
            probe_model_id INTEGER NOT NULL,
            internal_model TEXT NOT NULL,
            ipn TEXT,
            FOREIGN KEY(probe_model_id) REFERENCES probe_models(id)
        );
        INSERT INTO probe_models VALUES
            (21, 'F2-5C'), (22, 'G1-4P'), (23, 'F4-9E');
        INSERT INTO probe_model_variants VALUES
            (31, 21, 'F2-5C-Internal', '1000530'),
            (32, 22, 'G1-4P-Internal', '1000744'),
            (33, 23, 'F4-9E-Internal', '1000784');

        CREATE TABLE config_values (
            id INTEGER PRIMARY KEY,
            item_id INTEGER NOT NULL,
            model_id INTEGER NOT NULL,
            selection_config TEXT,
            current_config TEXT,
            FOREIGN KEY(item_id) REFERENCES config_items(id),
            FOREIGN KEY(model_id) REFERENCES product_models(id)
        );
        INSERT INTO config_values VALUES
            (1, 10, 1, 'X', 'X'),
            (2, 10, 2, '未定义', 'X'),
            (3, 11, 3, 'O', 'X'),
            (4, 11, 4, 'O', 'O'),
            (5, 11, 5, '未定义', 'Δ');
        """
    )
    connection.commit()
    connection.close()


def _write_registration_workbook(path, *, vinno10_unsupported="探头全适用"):
    workbook = Workbook()
    matrix = workbook.active
    matrix.title = "0729"
    matrix["A2"] = "支持探头\n共3把"
    matrix["B2"] = "F2-5C，G1-4P，F4-9E"
    matrix.append(["序号", "型号", "不支持探头", "通道数"])
    matrix.append([1, "VINNO 10", vinno10_unsupported, 128])
    matrix.append([2, "VINNO 10E", "F2-5C", 128])
    matrix.append([3, "VINNO 9", "F4-9E、G1-4P", 128])
    probes = workbook.create_sheet("Sheet1")
    probes.append([None, None, None])
    probes.append(["F2-5C", 1000530, 1000530])
    probes.append(["G1-4P", 1000744, 1000744])
    probes.append(["F4-9E", 1000784, 1000784])
    workbook.save(path)


def test_registration_schema_and_import_materialize_country_model_probe_redlines(tmp_path):
    database_path = tmp_path / "product_config.db"
    workbook_path = tmp_path / "registration.xlsx"
    _create_database(database_path)
    _write_registration_workbook(workbook_path)

    migrate_registration_schema(database_path)
    first = import_domestic_registration_workbook(
        database_path,
        workbook_path,
        source_document_id=1,
    )
    repeated = import_domestic_registration_workbook(
        database_path,
        workbook_path,
        source_document_id=1,
    )
    _write_registration_workbook(workbook_path, vinno10_unsupported="F4-9E")
    changed = import_domestic_registration_workbook(
        database_path,
        workbook_path,
        source_document_id=1,
    )
    _write_registration_workbook(workbook_path)
    restored = import_domestic_registration_workbook(
        database_path,
        workbook_path,
        source_document_id=1,
    )

    assert first.model_count == 3
    assert first.probe_count == 3
    assert first.matrix_count == 9
    assert first.direct_link_count == 3
    assert first.derived_link_count == 2
    assert first.unmatched_product_model_count == 0
    assert first.new_snapshot is True
    assert repeated.new_snapshot is False
    assert changed.new_snapshot is True
    assert restored.new_snapshot is False

    connection = sqlite3.connect(database_path)
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert connection.execute("SELECT COUNT(*) FROM registration_models").fetchone()[0] == 3
    assert connection.execute("SELECT COUNT(*) FROM registration_probes").fetchone()[0] == 3
    assert connection.execute("SELECT COUNT(*) FROM registration_model_probes").fetchone()[0] == 9
    assert connection.execute("SELECT COUNT(*) FROM registration_import_batches").fetchone()[0] == 2
    assert connection.execute(
        "SELECT COUNT(*) FROM registration_import_batches WHERE status = 'active'"
    ).fetchone()[0] == 1

    redlines = connection.execute(
        """
        SELECT model.model_name, probe.probe_model, matrix.registration_status
        FROM registration_model_probes matrix
        JOIN registration_models model ON model.id = matrix.registration_model_id
        JOIN registration_probes probe ON probe.id = matrix.registration_probe_id
        WHERE matrix.registration_status = 'unregistered'
        ORDER BY model.model_name, probe.probe_model
        """
    ).fetchall()
    assert redlines == [
        ("VINNO 10E", "F2-5C", "unregistered"),
        ("VINNO 9", "F4-9E", "unregistered"),
        ("VINNO 9", "G1-4P", "unregistered"),
    ]

    links = connection.execute(
        """
        SELECT product.name, registration.model_name, link.mapping_type
        FROM product_registration_model_links link
        JOIN product_models product ON product.id = link.product_model_id
        JOIN registration_models registration ON registration.id = link.registration_model_id
        ORDER BY product.id
        """
    ).fetchall()
    assert links == [
        ("VINNO 10", "VINNO 10", "direct"),
        ("VINNO 10E", "VINNO 10E", "direct"),
        ("VINNO 9", "VINNO 9", "direct"),
        ("VINNO 9_Private", "VINNO 9", "config_group"),
        ("VINNO 9 综合版", "VINNO 9", "confirmed_derived"),
    ]
    connection.close()

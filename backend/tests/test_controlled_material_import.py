from __future__ import annotations

from pathlib import Path
import sqlite3

from app.services.controlled_material_import import (
    discover_controlled_product_materials,
    import_controlled_product_materials,
)


def _write(root: Path, relative_path: str, content: bytes = b"source") -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _create_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE knowledge_documents (
                id INTEGER PRIMARY KEY,
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
                source_status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()
    finally:
        connection.close()


def test_discovery_infers_controlled_material_metadata(tmp_path: Path) -> None:
    whitepaper = _write(
        tmp_path,
        "白皮书/7P全身应用版_白皮书 _1.51.80.pdf",
    )
    v10_release = _write(
        tmp_path,
        "发布记录/V10系列 Release Note_1.4.70.pdf",
    )
    ultimus_release = _write(
        tmp_path,
        "发布记录/ULTIMUS 系列 Release Note_1.51.80.pdf",
    )
    manual = _write(
        tmp_path,
        "说明书/IFU 8000118 VINNO 8_8EXP_8PRO_8L_8T "
        "Basic User Manual_ZH-CN R18.pdf",
    )
    _write(tmp_path, "白皮书/.DS_Store")
    _write(tmp_path, "发布记录/notes.txt")
    _write(tmp_path, "注册资料/CN/certificate.pdf")

    sources = discover_controlled_product_materials(tmp_path)
    by_path = {source.path: source for source in sources}

    assert set(by_path) == {
        whitepaper.resolve(),
        v10_release.resolve(),
        ultimus_release.resolve(),
        manual.resolve(),
    }
    assert by_path[whitepaper.resolve()].document_type == "whitepaper"
    assert by_path[whitepaper.resolve()].version == "1.51.80"
    assert by_path[whitepaper.resolve()].product_series == "ULTIMUS 7P 全身应用版"
    assert by_path[v10_release.resolve()].version == "1.14.70"
    assert by_path[v10_release.resolve()].product_series == "V10"
    assert by_path[ultimus_release.resolve()].product_series == "ULTIMUS Series"
    assert by_path[manual.resolve()].version == "R18"
    assert by_path[manual.resolve()].product_series == "VINNO 8/8EXP/8PRO/8L/8T"


def test_import_is_dry_run_by_default_and_idempotent_on_apply(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.db"
    root = tmp_path / "受控材料"
    source = _write(root, "白皮书/6S_白皮书 _1.51.80.pdf", b"whitepaper")
    _create_database(database)

    dry_run = import_controlled_product_materials(database, root)

    assert dry_run.counts == {
        "scanned": 1,
        "ready": 1,
        "inserted": 0,
    }
    assert dry_run.items[0].status == "ready"
    connection = sqlite3.connect(database)
    assert connection.execute("SELECT COUNT(*) FROM knowledge_documents").fetchone()[0] == 0
    connection.close()

    applied = import_controlled_product_materials(database, root, apply=True)
    repeated = import_controlled_product_materials(database, root, apply=True)

    assert applied.counts == {"scanned": 1, "ready": 1, "inserted": 1}
    assert applied.items[0].status == "inserted"
    assert repeated.counts == {
        "scanned": 1,
        "ready": 0,
        "inserted": 0,
        "unchanged": 1,
    }
    connection = sqlite3.connect(database)
    row = connection.execute(
        """
        SELECT document_type, file_name, file_path, version, market, country,
               product_series, source_status
        FROM knowledge_documents
        """
    ).fetchone()
    connection.close()
    assert row == (
        "whitepaper",
        source.name,
        str(source.resolve()),
        "1.51.80",
        "domestic",
        "CN",
        "ULTIMUS 6S",
        "active",
    )


def test_import_reports_changed_names_and_duplicate_content(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.db"
    root = tmp_path / "受控材料"
    changed = _write(root, "发布记录/V10ReleaseNote_1.14.20.pdf", b"new")
    duplicate = _write(root, "发布记录/V10系列ReleaseNote_1.14.21.pdf", b"same")
    _create_database(database)
    connection = sqlite3.connect(database)
    connection.execute(
        """
        INSERT INTO knowledge_documents (
            document_type, title, file_name, file_path, version, market,
            country, product_series, mime_type, sha256
        ) VALUES
            ('release_note', 'old', ?, '/old/changed.pdf', '1.14.20',
             'domestic', 'CN', 'V10', 'application/pdf', ?),
            ('release_note', 'same', 'other.pdf', '/old/other.pdf', '1.14.21',
             'domestic', 'CN', 'V10', 'application/pdf', ?)
        """,
        (
            changed.name,
            "11507a0e2f5e69d5dfa40a62a1bd7b6ee5d0f795cb554d6f0864d68749a7c935",
            "0967115f2813a3541eaef77de9d9d5773f1c0c04314b0bbfe4ff3b3b1c55b5d5",
        ),
    )
    connection.commit()
    connection.close()

    result = import_controlled_product_materials(database, root, apply=True)

    statuses = {item.path.name: item.status for item in result.items}
    assert statuses[changed.name] == "name_conflict"
    assert statuses[duplicate.name] == "duplicate_content"
    assert result.counts == {
        "scanned": 2,
        "ready": 0,
        "inserted": 0,
        "name_conflict": 1,
        "duplicate_content": 1,
    }
    connection = sqlite3.connect(database)
    assert connection.execute("SELECT COUNT(*) FROM knowledge_documents").fetchone()[0] == 2
    connection.close()

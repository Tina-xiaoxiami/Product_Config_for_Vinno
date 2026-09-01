import sqlite3

from app.services.feature_identity_migration import migrate_feature_identity_database
from app.services.knowledge_source_import import (
    discover_v10_knowledge_sources,
    import_knowledge_sources,
)
from test_feature_identity_migration import _create_legacy_database


def _write(root, relative_path, content=b"source"):
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_discovery_classifies_provided_v10_materials_without_manual_entry(tmp_path):
    registration = _write(
        tmp_path,
        "注册/国内/长沙变更/注册变更-20260615.pdf",
    )
    difference = _write(
        tmp_path,
        "注册/国内/长沙变更/V10系列国内注册变更型号差异20250729.xlsx",
    )
    manual = _write(
        tmp_path,
        "注册/国内/长沙变更/IFU 8000574 VINNO 9_9E_9P_10_10E_10P Basic User Manual_ZH-CN R10（CS）.pdf",
    )
    whitepaper = _write(
        tmp_path,
        "Datasheet/国内/1.14.80/去封面/1.14.80白皮书/VINNO 10白皮书_1.14.80.pdf",
    )
    release_pdf = _write(
        tmp_path,
        "release note/1.14.80/V series Release Note_1.14.80.pdf",
    )
    release_docx = _write(
        tmp_path,
        "release note/1.14.80/V series Release Note_1.4.80.docx",
    )
    _write(tmp_path, "release note/1.14.80/.DS_Store")

    sources = discover_v10_knowledge_sources(tmp_path)

    assert [(item.document_type, item.path) for item in sources] == [
        ("whitepaper", whitepaper),
        ("release_note", release_pdf),
        ("release_note", release_docx),
        ("manual", manual),
        ("registration_difference", difference),
        ("registration_certificate", registration),
    ]
    assert next(item for item in sources if item.path == whitepaper).product_series == "VINNO 10"
    assert next(item for item in sources if item.path == manual).version == "R10"
    release_source = next(item for item in sources if item.path == release_docx)
    assert release_source.version == "1.14.80"
    assert release_source.title == "V series Release Note_1.14.80"
    assert release_source.path.name == "V series Release Note_1.4.80.docx"


def test_source_import_is_idempotent_and_refreshes_changed_file_digest(tmp_path):
    document_root = tmp_path / "V10文档"
    registration = _write(
        document_root,
        "注册/国内/长沙变更/注册变更-20260615.pdf",
        b"version-one",
    )
    database_path = tmp_path / "product_config_copy.db"
    _create_legacy_database(database_path)
    migrate_feature_identity_database(database_path)

    first = import_knowledge_sources(database_path, document_root)
    unchanged = import_knowledge_sources(database_path, document_root)
    registration.write_bytes(b"version-two")
    updated = import_knowledge_sources(database_path, document_root)

    assert first == {"discovered": 1, "inserted": 1, "updated": 0, "unchanged": 0}
    assert unchanged == {"discovered": 1, "inserted": 0, "updated": 0, "unchanged": 1}
    assert updated == {"discovered": 1, "inserted": 0, "updated": 1, "unchanged": 0}
    connection = sqlite3.connect(database_path)
    row = connection.execute(
        "SELECT document_type, title, file_name, version, market, country, sha256 FROM knowledge_documents"
    ).fetchone()
    assert row[:6] == (
        "registration_certificate",
        "V10系列国内注册变更",
        registration.name,
        "20260615",
        "domestic",
        "CN",
    )
    assert len(row[6]) == 64
    assert connection.execute("SELECT COUNT(*) FROM knowledge_documents").fetchone()[0] == 1
    connection.close()

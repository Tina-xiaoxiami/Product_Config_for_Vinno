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
    connection = sqlite3.connect(database_path)
    connection.execute(
        "UPDATE knowledge_documents SET title = 'old title', version = '1.4.80'"
    )
    connection.commit()
    connection.close()
    metadata_refreshed = import_knowledge_sources(database_path, document_root)
    registration.write_bytes(b"version-two")
    updated = import_knowledge_sources(database_path, document_root)

    assert first == {"discovered": 1, "inserted": 1, "updated": 0, "unchanged": 0}
    assert unchanged == {"discovered": 1, "inserted": 0, "updated": 0, "unchanged": 1}
    assert metadata_refreshed == {
        "discovered": 1,
        "inserted": 0,
        "updated": 1,
        "unchanged": 0,
    }
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


def _seed_answer(connection, question_id, document_id):
    connection.execute(
        "INSERT INTO knowledge_questions (id, question_text, normalized_question, status) VALUES (?, ?, ?, 'answered')",
        (question_id, f'question {question_id}', f'question {question_id}'),
    )
    connection.execute(
        "INSERT INTO knowledge_answers (id, question_id, answer_text, change_note) VALUES (?, ?, 'original answer', 'original note')",
        (question_id, question_id),
    )
    connection.execute(
        "INSERT INTO knowledge_answer_citations (answer_id, document_id, source_ref, excerpt) VALUES (?, ?, 'page 1', 'original excerpt')",
        (question_id, document_id),
    )


def test_import_marks_only_changed_evidence_and_rolls_back_on_failure(tmp_path, monkeypatch):
    from dataclasses import replace
    from app.services import knowledge_source_import

    root = tmp_path / 'sources'
    source = _write(root, '注册/国内/长沙变更/注册变更-20260615.pdf', b'first')
    database = tmp_path / 'test.db'
    from test_knowledge_qa_api import _create_qa_database
    _create_qa_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM knowledge_documents")
    import_knowledge_sources(database, root)
    with sqlite3.connect(database) as connection:
        _seed_answer(connection, 1, 1)
        connection.execute("INSERT INTO knowledge_documents (id, document_type, title, file_name, file_path) VALUES (2, 'manual', 'other', 'other', '/other')")
        _seed_answer(connection, 2, 2)
        connection.execute("UPDATE knowledge_documents SET title = 'old title' WHERE id = 1")
    import_knowledge_sources(database, root)
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT review_status FROM knowledge_answers WHERE id = 1').fetchone()[0] == 'published'

    source.write_bytes(b'second')
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TRIGGER fail_review BEFORE UPDATE ON knowledge_answers BEGIN SELECT RAISE(ABORT, 'test rollback'); END")
    import pytest
    with pytest.raises(sqlite3.IntegrityError, match='test rollback'):
        import_knowledge_sources(database, root)
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT sha256 FROM knowledge_documents WHERE id = 1').fetchone()[0] != knowledge_source_import._sha256(source)
        assert connection.execute('SELECT review_status FROM knowledge_answers WHERE id = 1').fetchone()[0] == 'published'
        connection.execute('DROP TRIGGER fail_review')
    import_knowledge_sources(database, root)
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT status FROM knowledge_questions ORDER BY id').fetchall() == [('pending',), ('answered',)]
        assert connection.execute('SELECT review_status, answer_text, change_note FROM knowledge_answers ORDER BY id').fetchall() == [('source_changed', 'original answer', 'original note'), ('published', 'original answer', 'original note')]
        assert connection.execute('SELECT excerpt FROM knowledge_answer_citations WHERE answer_id = 1').fetchone()[0] == 'original excerpt'
        connection.execute("UPDATE knowledge_answers SET review_status = 'published' WHERE id = 1")
        connection.execute("UPDATE knowledge_questions SET status = 'answered' WHERE id = 1")
    import_knowledge_sources(database, root)
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT review_status FROM knowledge_answers WHERE id = 1').fetchone()[0] == 'published'

    discovered = discover_v10_knowledge_sources(root)
    monkeypatch.setattr(knowledge_source_import, 'discover_v10_knowledge_sources', lambda _: [replace(discovered[0], version='new version')])
    import_knowledge_sources(database, root)
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT review_status FROM knowledge_answers WHERE id = 1').fetchone()[0] == 'scope_changed'


def test_import_establishes_missing_hash_without_claiming_a_change(tmp_path):
    root = tmp_path / 'sources'
    _write(root, '注册/国内/长沙变更/注册变更-20260615.pdf')
    database = tmp_path / 'test.db'
    from test_knowledge_qa_api import _create_qa_database
    _create_qa_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM knowledge_documents")
    import_knowledge_sources(database, root)
    with sqlite3.connect(database) as connection:
        _seed_answer(connection, 1, 1)
        connection.execute('UPDATE knowledge_documents SET sha256 = NULL WHERE id = 1')
    import_knowledge_sources(database, root)
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT review_status FROM knowledge_answers').fetchone()[0] == 'published'
        assert connection.execute('SELECT sha256 FROM knowledge_documents').fetchone()[0]


def test_partial_review_schema_is_rejected_before_import(tmp_path):
    import pytest

    root = tmp_path / 'sources'
    _write(root, '注册/国内/长沙变更/注册变更-20260615.pdf')
    database = tmp_path / 'test.db'
    _create_legacy_database(database)
    migrate_feature_identity_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE knowledge_answers (id INTEGER PRIMARY KEY)')
    with pytest.raises(RuntimeError, match='不完整的知识复核数据库表'):
        import_knowledge_sources(database, root)
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT COUNT(*) FROM knowledge_documents').fetchone()[0] == 0

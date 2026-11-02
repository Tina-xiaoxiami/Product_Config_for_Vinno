"""Read-only baseline and evidence-gap contracts; all data is synthetic."""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from test_knowledge_qa_api import _create_qa_database
from app.services.knowledge_baseline import KnowledgeBaselineError, build_knowledge_baseline


@pytest.fixture
def knowledge_source(tmp_path):
    database = tmp_path / "knowledge ?#.db"
    _create_qa_database(database)
    original = tmp_path / "original.pdf"
    original.write_bytes(b"controlled original")
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "UPDATE knowledge_documents SET file_path=?, sha256=? WHERE id=1",
            (str(original), digest),
        )
        connection.execute(
            "INSERT INTO knowledge_documents (id, document_type, title, file_name, "
            "file_path, version, market, source_status) VALUES "
            "(2, 'whitepaper', 'Missing source', 'missing.pdf', ?, '1.14.81', 'domestic', 'active'),"
            "(3, 'manual', 'Archived', 'old.pdf', ?, 'R1', 'domestic', 'archived')",
            (str(tmp_path / "missing.pdf"), str(tmp_path / "old.pdf")),
        )
        connection.execute(
            "INSERT INTO knowledge_document_extractions "
            "(document_id, extractor_version, source_sha256, status, chunk_count) "
            "VALUES (1, 'test', 'old-digest', 'completed', 1)"
        )
        connection.execute(
            "INSERT INTO knowledge_document_chunks "
            "(document_id, chunk_index, source_ref, content, normalized_content, content_hash) "
            "VALUES (1, 0, 'p1', 'source', 'source', 'test')"
        )
        for number in range(1, 5):
            connection.execute(
                "INSERT INTO knowledge_questions "
                "(id, question_text, normalized_question, status) VALUES (?, ?, ?, ?)",
                (number, f"Synthetic question {number}", f"q{number}",
                 "pending" if number == 4 else "answered"),
            )
        for number in range(1, 4):
            connection.execute(
                "INSERT INTO knowledge_answers "
                "(id, question_id, answer_text, review_status) VALUES (?, ?, ?, ?)",
                (number, number, "Do not export answer text",
                 "draft" if number == 3 else "published"),
            )
        connection.execute(
            "INSERT INTO knowledge_answer_citations "
            "(answer_id, document_id, source_ref) VALUES (1, 1, 'p1')"
        )
    return database, original


def test_baseline_preserves_sources_and_distinguishes_evidence_from_business_review(knowledge_source):
    database, original = knowledge_source
    before = (database.read_bytes(), original.read_bytes())

    report = build_knowledge_baseline(database)
    repeated = build_knowledge_baseline(database)

    assert (database.read_bytes(), original.read_bytes()) == before
    assert report["sources"] == repeated["sources"]
    assert report["schema_version"] == 1
    assert report["checks"]["original_file_hashes"] == "not_requested"
    knowledge = report["sources"]["knowledge"]
    assert knowledge["counts"] == {
        "documents": 3, "active_documents": 2, "extracted_documents": 1,
        "chunks": 1, "questions": 4, "answers": 3, "published_answers": 2,
        "citations": 1, "published_answers_without_document_citation": 1,
        "active_documents_without_extraction": 1,
        "active_documents_with_stale_extraction": 1,
        "active_documents_unavailable": 1,
    }
    uncited = next(row for row in knowledge["answer_review_queue"] if row["answer_id"] == 2)
    assert uncited["question_id"] == 2
    assert uncited["reasons"] == ["no_document_citation"]
    assert uncited["decision"] == "needs_owner_review"
    assert all(row["answer_id"] != 3 for row in knowledge["answer_review_queue"])
    assert knowledge["whitepaper_versions"] == {"1.14.80": 1, "1.14.81": 1}
    assert knowledge["native_release_counts"] == {
        "feature_versions": None, "release_introductions": None,
    }
    assert knowledge["question_scope_columns"] == []
    encoded = json.dumps(report)
    assert str(database.parent) not in encoded
    assert "Do not export answer text" not in encoded
    codes = {item["code"] for item in knowledge["findings"]}
    assert {"structured_question_scope_missing", "extraction_stale", "file_unavailable"} <= codes


def test_source_digest_mismatch_is_not_treated_as_an_original_file_hash_check(knowledge_source):
    database, _ = knowledge_source
    report = build_knowledge_baseline(database)
    doc = report["sources"]["knowledge"]["documents"][0]
    assert doc["original_hash_status"] == "not_checked"
    assert doc["extraction_status"] == "stale"


def test_opt_in_hash_verification_detects_changed_bytes_without_registering_them(knowledge_source):
    database, original = knowledge_source
    matching = build_knowledge_baseline(database, verify_file_hashes=True)
    assert matching["sources"]["knowledge"]["documents"][0]["original_hash_status"] == "matches"
    original.write_bytes(b"changed bytes")
    before = database.read_bytes()
    changed = build_knowledge_baseline(database, verify_file_hashes=True)
    doc = changed["sources"]["knowledge"]["documents"][0]
    assert doc["original_hash_status"] == "mismatch"
    assert "original_hash_mismatch" in {i["code"] for i in changed["sources"]["knowledge"]["findings"]}
    assert database.read_bytes() == before


def test_missing_primary_database_is_not_created(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(KnowledgeBaselineError, match="数据库不存在"):
        build_knowledge_baseline(missing)
    assert not missing.exists()


def test_incomplete_primary_schema_fails_instead_of_reporting_healthy_zero_counts(tmp_path):
    database = tmp_path / "partial.db"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER)")
    with pytest.raises(KnowledgeBaselineError, match="缺少"):
        build_knowledge_baseline(database)


def test_unrequested_and_missing_optional_sources_are_distinct(knowledge_source, tmp_path):
    database, _ = knowledge_source
    default = build_knowledge_baseline(database)
    assert default["sources"]["release"]["state"] == "not_requested"
    missing = build_knowledge_baseline(
        database, release_database=tmp_path / "absent.db",
        feature_library=tmp_path / "absent.json",
        publication_root=tmp_path / "absent-folder",
    )
    for name in ["release", "feature_library", "publication_receipts"]:
        assert missing["sources"][name]["state"] == "unavailable"
        assert "counts" not in missing["sources"][name]
    assert not (tmp_path / "absent.db").exists()


def test_existing_release_records_are_not_confused_with_native_feature_versions(knowledge_source, tmp_path):
    database, _ = knowledge_source
    release = tmp_path / "release.db"
    with closing(sqlite3.connect(release)) as connection, connection:
        connection.executescript(
            "CREATE TABLE projects (id INTEGER); INSERT INTO projects VALUES (1);"
            "CREATE TABLE releases (id INTEGER); INSERT INTO releases VALUES (1), (2);"
            "CREATE TABLE source_documents (id INTEGER); INSERT INTO source_documents VALUES (1);"
        )
    before = release.read_bytes()
    report = build_knowledge_baseline(database, release_database=release)
    assert report["sources"]["release"]["counts"] == {
        "projects": 1, "releases": 2, "source_documents": 1,
    }
    assert release.read_bytes() == before


@pytest.mark.parametrize("payload", ["not JSON", "{}", '{"revision":1,"features":{}}',
                                  '{"revision":1,"features":[{"id":"a"},{"id":"a"}]}'])
def test_invalid_library_is_reported_as_invalid_not_empty(knowledge_source, tmp_path, payload):
    library = tmp_path / "library.json"
    library.write_text(payload)
    report = build_knowledge_baseline(knowledge_source[0], feature_library=library)
    assert report["sources"]["feature_library"]["state"] == "invalid"


def test_library_count_does_not_claim_body_completeness_or_approval(knowledge_source, tmp_path):
    library = tmp_path / "library.json"
    library.write_text(json.dumps({"revision": 7, "features": [{"id": "a"}, {"id": "b"}]}))
    report = build_knowledge_baseline(knowledge_source[0], feature_library=library)
    assert report["sources"]["feature_library"]["counts"] == {"cards": 2}
    assert report["sources"]["feature_library"]["revision"] == 7


def test_receipts_are_inventoried_without_promoting_them_to_current_publication(knowledge_source, tmp_path):
    root = tmp_path / "receipts"
    job = root / "job-a"
    job.mkdir(parents=True)
    (job / "controlled.json").write_text(json.dumps({
        "id": "receipt-a", "job_id": "job-a", "controlled": True,
        "artifacts": {"model-a": {"destinations": {str(tmp_path / "not-here.docx"): "hash"},
                                    "generation_id": "generation-a", "hashes": {"docx": "hash"}}},
    }))
    (job / "archived.json").write_text(json.dumps({
        "id": "receipt-b", "job_id": "job-a", "controlled": False,
        "artifacts": {"model-a": {"destinations": {}, "generation_id": "g", "hashes": {}}},
    }))
    (job / "broken.json").write_text("broken")
    report = build_knowledge_baseline(knowledge_source[0], publication_root=root)
    receipts = report["sources"]["publication_receipts"]
    assert receipts["state"] == "degraded"
    assert receipts["counts"] == {
        "receipts": 3, "controlled_unverified": 1, "archived_unverified": 1, "invalid": 1,
    }
    assert report["checks"]["publication_eligibility"] == "not_checked"
    assert str(tmp_path) not in json.dumps(receipts)


def test_cli_writes_a_local_report_and_refuses_to_overwrite_inputs_or_existing_files(knowledge_source, tmp_path):
    database, _ = knowledge_source
    script = Path(__file__).resolve().parents[1] / "scripts" / "audit_knowledge_baseline.py"
    output = tmp_path / "output" / "baseline.json"
    result = subprocess.run(
        [sys.executable, str(script), "--database", str(database), "--output", str(output)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())["schema_version"] == 1
    for target in [database, output]:
        before = target.read_bytes()
        failed = subprocess.run(
            [sys.executable, str(script), "--database", str(database), "--output", str(target)],
            capture_output=True, text=True,
        )
        assert failed.returncode == 1
        assert target.read_bytes() == before


@pytest.mark.parametrize("denied_directory", ["root", "job"])
def test_receipt_directory_permission_failures_do_not_look_like_healthy_zero_counts(
    knowledge_source, tmp_path, monkeypatch, denied_directory,
):
    root = tmp_path / "receipts"
    job = root / "blocked-job"
    job.mkdir(parents=True)
    denied = root if denied_directory == "root" else job
    # Exercise the OS failure regardless of Path traversal details or host OS.
    for name in ["scandir", "listdir"]:
        original = getattr(os, name)

        def failing_read(path, _original=original):
            if Path(path).resolve() == denied.resolve():
                raise PermissionError("synthetic denied directory")
            return _original(path)

        monkeypatch.setattr(os, name, failing_read)
    report = build_knowledge_baseline(knowledge_source[0], publication_root=root)
    receipts = report["sources"]["publication_receipts"]
    assert receipts["state"] == ("unavailable" if denied_directory == "root" else "degraded")
    assert receipts["findings"]


@pytest.mark.parametrize("destination", ["missing_input", "missing_original", "receipt_directory"])
def test_cli_cannot_create_a_report_in_an_unavailable_source_location(knowledge_source, tmp_path, destination):
    database, _ = knowledge_source
    library = tmp_path / "missing-library.json"
    receipts = tmp_path / "receipts"
    target = {
        "missing_input": library, "missing_original": tmp_path / "missing.pdf",
        "receipt_directory": receipts / "new-job" / "report.json",
    }[destination]
    script = Path(__file__).resolve().parents[1] / "scripts" / "audit_knowledge_baseline.py"
    result = subprocess.run(
        [sys.executable, str(script), "--database", str(database),
         "--feature-library", str(library), "--publication-root", str(receipts),
         "--output", str(target)], capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert not target.exists()


def test_cli_main_reports_success_and_actionable_errors_without_creating_sources(
    knowledge_source, tmp_path, monkeypatch, capsys,
):
    from scripts.audit_knowledge_baseline import main

    database, _ = knowledge_source
    output = tmp_path / "report.json"
    argv = ["audit", "--database", str(database), "--output", str(output)]
    monkeypatch.setattr(sys, "argv", argv)
    assert main() == 0
    assert "uncited_answers=1" in capsys.readouterr().out
    assert main() == 1
    assert "已存在" in capsys.readouterr().err
    output.unlink()
    monkeypatch.setattr(sys, "argv", [
        "audit", "--database", str(database), "--output", str(tmp_path / "missing.pdf"),
    ])
    assert main() == 1
    assert "登记原件" in capsys.readouterr().err
    assert not (tmp_path / "missing.pdf").exists()

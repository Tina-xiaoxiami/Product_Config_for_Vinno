from hashlib import sha256
import json

import pytest

from app.services.knowledge_whitepaper_publication import verified_publication


@pytest.fixture
def publication(tmp_path):
    root = tmp_path / "controlled"
    folder = root / "白皮书" / "1.0.0" / "去封面"
    files = {}
    for kind, suffix in (("pdf", ".pdf"), ("docx", ".docx")):
        path = folder / kind / f"Example{suffix}"
        path.parent.mkdir(parents=True)
        path.write_bytes(kind.encode())
        files[kind] = path
    digests = {kind: sha256(path.read_bytes()).hexdigest() for kind, path in files.items()}
    source = {"generation_id": "generation", "hashes": digests,
              "destinations": {str(path): digests[kind] for kind, path in files.items()}}
    receipt = {"id": "publication", "job_id": "job", "controlled": True, "artifacts": {"Example": source}}
    task = {
        "id": "task", "version_to": "1.0.0",
        "publishes": [{"id": "publication", "controlled": True, "round_id": "round",
                       "build_id": "build", "products": ["Example"], "artifacts": receipt["artifacts"]}],
        "rounds": [{"id": "round", "snapshot": {"changeset": {"config_versions": {"Example-China": "1.0.0"}}},
                    "builds": [{"id": "build", "job_id": "job", "status": "done", "products": {"Example": {
                        "version": "1.0.0", "generation_id": "generation", "artifact_hashes": digests,
                        "gate": "format gate: PASSED",
                    }}}]}],
    }
    receipt_path = tmp_path / "job" / "publication.json"
    receipt_path.parent.mkdir()
    task_path = tmp_path / "task.json"
    return root, task_path, receipt_path, task, receipt, files


@pytest.mark.parametrize("invalid", [None, "archive", "hash", "test_scope", "cover_only", "build"])
def test_verify_frozen_publication_pair(publication, invalid):
    root, task_path, receipt_path, task, receipt, files = publication
    if invalid == "archive":
        receipt["controlled"] = False
    if invalid == "hash":
        files["pdf"].write_bytes(b"changed")
    if invalid == "test_scope":
        task["rounds"][0]["snapshot"]["changeset"]["config_versions"]["Example-China"] = "1.0.0-test"
    if invalid == "cover_only":
        receipt["artifacts"]["Example"]["destinations"].pop(str(files["pdf"]))
    if invalid == "build":
        task["rounds"][0]["builds"][0]["status"] = "failed"
    task_path.write_text(json.dumps(task))
    receipt_path.write_text(json.dumps(receipt))

    if invalid:
        with pytest.raises(ValueError):
            verified_publication(root, task_path, receipt_path, "Example", "Example-China", "1.0.0")
    else:
        materials, provenance = verified_publication(
            root, task_path, receipt_path, "Example", "Example-China", "1.0.0"
        )
        assert {item.path for item in materials} == set(files.values())
        assert provenance["generation"] == "generation"


@pytest.mark.asyncio
async def test_sync_is_atomic_idempotent_and_pins_receipt(publication, tmp_path, monkeypatch):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services import knowledge_whitepaper_publication as service
    from app.services.knowledge_content import (
        ExtractedBlock, KnowledgeContentError, extract_registered_document,
    )
    from test_versions_api import _versions_harness

    root, task_path, receipt_path, task, receipt, files = publication
    task_path.write_text(json.dumps(task))
    receipt_path.write_text(json.dumps(receipt))
    _, _, engine = await _versions_harness(tmp_path)

    async def scope(*args):
        return {"country": "CN", "market": "domestic", "product_model_id": 1,
                "software_version": "1.0.0", "model_name": "Example", "series_name": "Example-China"}

    async def identity(*args):
        return True

    async def snapshot(*args, **kwargs):
        return {"id": 1}, {"models": [{"id": 1}]}

    fail_word = True

    def extract(path, mime):
        if path == files["docx"] and fail_word:
            raise KnowledgeContentError("bad Word")
        return [ExtractedBlock("原文证据片段", "第1页", 1)]

    monkeypatch.setattr(service, "resolve_query_scope", scope)
    monkeypatch.setattr(service, "document_model_identity_unique", identity)
    monkeypatch.setattr(service, "answer_snapshot", snapshot)
    monkeypatch.setattr("app.services.knowledge_content.extract_document_blocks", extract)
    try:
        async with AsyncSession(engine) as db:
            await db.execute(text("INSERT INTO product_series(id,name) VALUES(1,'Example-China')"))
            await db.execute(text("INSERT INTO product_models(id,name,series_id,is_enabled) VALUES(1,'Example',1,1)"))
            await db.commit()
            args = (db, root, task_path, receipt_path, "Example", {})
            preview = await service.sync_publication(*args)
            assert [item["status"] for item in preview["documents"]] == ["ready", "ready"]
            with pytest.raises(KnowledgeContentError, match="bad Word"):
                await service.sync_publication(*args, apply=True)
            assert await db.scalar(text("SELECT COUNT(*) FROM knowledge_documents")) == 0
            assert await db.scalar(text("SELECT COUNT(*) FROM knowledge_document_extractions")) == 0
            fail_word = False
            result = await service.sync_publication(*args, apply=True)
            assert [item["status"] for item in result["documents"]] == ["inserted", "inserted"]
            replay = await service.sync_publication(*args, apply=True)
            assert [item["reused"] for item in replay["documents"]] == [True, True]
            assert await db.scalar(text("SELECT COUNT(*) FROM knowledge_whitepaper_publication_sources")) == 2
            ident = result["documents"][0]["document_id"]
            files["pdf"].write_bytes(b"unpublished bytes")
            with pytest.raises(KnowledgeContentError, match="发布回执"):
                await extract_registered_document(db, ident, force=True)
    finally:
        await engine.dispose()

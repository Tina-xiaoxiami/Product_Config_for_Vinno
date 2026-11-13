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
        assert {item.path for item in verified_publication(
            root, task_path, receipt_path, "Example", "Example-China", "1.0.0"
        )} == set(files.values())

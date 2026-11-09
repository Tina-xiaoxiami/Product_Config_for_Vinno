"""Check reviewed file fingerprints inside explicitly configured source roots."""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any, Iterable

from tracker.services.search_index import FileSnapshot, _file_signature, file_snapshot

if TYPE_CHECKING:
    from tracker.database import Database


def latest_extraction_review_hashes(database: Database) -> dict[str, str]:
    """Use the newest review record, including an empty or malformed baseline."""
    latest: dict[str, dict[str, Any]] = {}
    for review in database.list_review_records():
        if review["subject_type"] != "document_version" or review["decision"] != "verified":
            continue
        version_id = str(review["subject_ref"])
        if version_id not in latest or review["id"] > latest[version_id]["id"]:
            latest[version_id] = review
    hashes = {}
    for version_id, review in latest.items():
        try:
            excerpt = json.loads(review["excerpt"] or "{}")
        except (TypeError, ValueError):
            continue
        digest = excerpt.get("extract_sha256") if isinstance(excerpt, dict) else None
        if isinstance(digest, str) and digest:
            hashes[version_id] = digest
    return hashes


class DocumentEvidencePolicy:
    """Cache stable snapshots; invalidate on size, mtime, ctime, or inode change."""

    def __init__(self, *, allowed_roots: Iterable[str | Path], extraction_roots: Iterable[str | Path] = ()) -> None:
        self.roots = self.normalized_roots(allowed_roots)
        self.extraction_roots = self.normalized_roots(extraction_roots)
        self._snapshots: dict[Path, FileSnapshot] = {}
        self._lock = RLock()

    @staticmethod
    def normalized_roots(roots: Iterable[str | Path]) -> tuple[Path, ...]:
        return tuple(dict.fromkeys(Path(root).expanduser().resolve() for root in roots if str(root).strip()))

    def _matches_file(self, raw_path: str | None, expected: str, *, extraction: bool = False) -> bool:
        if not raw_path or not expected:
            return False
        try:
            raw = Path(raw_path).expanduser()
            resolved = raw.resolve(strict=True)
            roots = (*self.roots, *self.extraction_roots) if extraction else self.roots
            if not any(root in resolved.parents for root in roots) or not resolved.is_file():
                return False
            with self._lock:
                snapshot = self._snapshots.get(resolved)
                if snapshot is None or snapshot.signature != _file_signature(resolved):
                    snapshot = file_snapshot(resolved)
                    self._snapshots[resolved] = snapshot
                return snapshot.digest == expected and raw.resolve(strict=True) == resolved
        except (OSError, ValueError, RuntimeError):
            return False

    def version_is_current(self, database: Database, version: dict[str, Any]) -> bool:
        if not self._matches_file(version.get("path_pdf"), version.get("sha256") or ""):
            return False
        if version.get("path_docx"):
            expected = latest_extraction_review_hashes(database).get(str(version["id"]), "")
            return self._matches_file(version["path_docx"], expected, extraction=True)
        return True

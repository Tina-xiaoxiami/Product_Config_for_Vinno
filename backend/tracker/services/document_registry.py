"""受控资料登记、版本追加和人工复核，沿用已有版本及审核记录。"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable

from tracker.database import Database
from tracker.services.document_scopes import DOCUMENT_CATEGORIES, MAX_MODEL_SCOPE_LENGTH, matches_model_scope, normalize_model_scope
from tracker.services.search_index import FORMAT_LABELS, file_sha256, format_info


EXCLUDED_DIRECTORIES = frozenset({"__pycache__", "backups", "backup", "备份", "索引"})


def _validate_model_scope(value: str) -> str:
    normalized = normalize_model_scope(value)
    if any(model in DOCUMENT_CATEGORIES for model in normalized.split("、")):
        raise ValueError("适用机型不能填写资料分类；无法确认时请留空。")
    if len(normalized) > MAX_MODEL_SCOPE_LENGTH:
        raise ValueError(f"机型范围不能超过 {MAX_MODEL_SCOPE_LENGTH} 字。")
    return normalized


class DocumentRegistry:
    """文件只来自启动时允许的资料根，网页通过不透明 token 选择。"""

    def __init__(
        self, database: Database, *, allowed_roots: Iterable[str | Path],
        extraction_roots: Iterable[str | Path] = (),
        configure_evidence_roots: bool = True,
    ) -> None:
        self.database = database
        self.roots = tuple(dict.fromkeys(Path(root).expanduser().resolve() for root in allowed_roots if str(root).strip()))
        self.extraction_roots = tuple(dict.fromkeys(Path(root).expanduser().resolve() for root in extraction_roots if str(root).strip()))
        self._file_tokens: dict[str, Path] = {}
        if configure_evidence_roots:
            self.database.configure_document_evidence_roots(allowed_roots=self.roots, extraction_roots=self.extraction_roots)

    def _allowed_file(self, path: Path, *, extract_source: bool = False) -> Path:
        try:
            resolved = path.expanduser().resolve(strict=True)
        except OSError as error:
            raise ValueError("所选资料不存在或暂时不可读取。") from error
        if not resolved.is_file() or resolved.suffix.casefold() not in FORMAT_LABELS:
            raise ValueError("请选择支持格式的现有资料文件。")
        roots = self.roots + self.extraction_roots if extract_source else self.roots
        if not any(root in resolved.parents for root in roots):
            raise ValueError("登记原件必须在受控目录内；独立抽取目录仅可选作抽取源。")
        return resolved

    def token_for_path(self, path: str | Path, *, extract_source: bool = False) -> str:
        """仅供本机导入复用，仍按相同允许根检查，返回值不含路径。"""
        resolved = self._allowed_file(Path(path), extract_source=extract_source)
        token = sha256(str(resolved).encode("utf-8")).hexdigest()
        self._file_tokens[token] = resolved
        return token

    def file_catalog(self) -> dict[str, Any]:
        versions = [
            version for document in self.database.list_documents()
            for version in self.database.list_document_versions(document["id"])
        ]
        registered_paths = {
            str(Path(version[field]).expanduser().resolve())
            for version in versions
            for field in ("path_pdf", "path_docx") if version.get(field)
        }
        files: list[dict[str, Any]] = []
        unavailable = 0
        seen: set[Path] = set()
        self._file_tokens = {}
        for number, root in enumerate(self.roots, start=1):
            if not root.is_dir():
                unavailable += 1
                continue
            try:
                for path in sorted(root.rglob("*")):
                    relative = path.relative_to(root)
                    if any(part.startswith(".") or part.startswith("~$") or part.casefold() in EXCLUDED_DIRECTORIES for part in relative.parts):
                        continue
                    if path.is_symlink() or not path.is_file() or path.suffix.casefold() not in FORMAT_LABELS:
                        continue
                    try:
                        resolved = self._allowed_file(path)
                    except ValueError:
                        continue
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    files.append({
                        "file_token": self.token_for_path(resolved),
                        "name": path.name,
                        "relative_name": relative.as_posix(),
                        "root_label": f"资料目录 {number}",
                        "role": "registered_file",
                        **(format_info(path) or {}),
                        "registered": str(resolved) in registered_paths,
                    })
            except OSError:
                unavailable += 1
        # 独立抽取目录不递归采集，仅列出已有资料明确登记的抽取源。
        for raw in dict.fromkeys(version["path_docx"] for version in versions if version.get("path_docx")):
            try:
                resolved = self._allowed_file(Path(raw), extract_source=True)
            except ValueError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append({
                "file_token": self.token_for_path(resolved, extract_source=True),
                "name": resolved.name,
                "root_label": "已登记抽取来源",
                "role": "extract_source",
                **(format_info(resolved) or {}),
                "registered": True,
            })
        unavailable += sum(not root.is_dir() for root in self.extraction_roots)
        return {"files": files, "total": len(files), "unavailable_roots": unavailable}

    def _resolve_token(self, token: str, *, extract_source: bool = False) -> Path:
        if not isinstance(token, str) or len(token) != 64:
            raise ValueError("请选择资料列表中的文件。")
        if token not in self._file_tokens:
            self.file_catalog()
        path = self._file_tokens.get(token)
        if path is None:
            raise ValueError("所选文件已不可用，请刷新资料列表后重选。")
        return self._allowed_file(path, extract_source=extract_source)

    def _selected_files(self, file_token: str, extract_source_token: str | None) -> tuple[Path, Path | None, str, str]:
        registered = self._resolve_token(file_token)
        extract = self._resolve_token(extract_source_token, extract_source=True) if extract_source_token else None
        try:
            digest = file_sha256(registered)
            extract_digest = file_sha256(extract) if extract else ""
        except OSError as error:
            raise ValueError("所选资料暂时不可读取，请稍后重试。") from error
        return registered, extract, digest, extract_digest

    def _document(self, document_id: int) -> dict[str, Any]:
        if not isinstance(document_id, int) or isinstance(document_id, bool):
            raise ValueError("请选择有效资料。")
        document = next((item for item in self.database.list_documents() if item["id"] == document_id), None)
        if document is None:
            raise ValueError("资料不存在。")
        return document

    def _duplicate(self, digest: str, document_id: int | None = None) -> dict[str, Any] | None:
        for document in self.database.list_documents():
            for version in self.database.list_document_versions(document["id"]):
                if version["sha256"] != digest:
                    continue
                if document_id is not None and document["id"] != document_id:
                    raise ValueError("该文件已登记到其他资料，请打开既有资料。")
                return {"document_id": document["id"], "version_id": version["id"], "duplicate": True, "is_current": version["id"] == document["current_version_id"]}
        return None

    def register_document(
        self, *, title: str, doc_type: str, model_scope: str, scope_market: str,
        file_token: str, extract_source_token: str | None = None,
        version_label: str = "", effective_date: str | None = None,
    ) -> dict[str, Any]:
        title = self.database._required_business_text(title, "资料名称")
        doc_type = self.database._required_business_text(doc_type, "资料类型")
        model_scope = _validate_model_scope(model_scope)
        if scope_market not in {"domestic", "overseas", ""}:
            raise ValueError("市场请选择国内、海外或未登记。")
        effective_date = self.database._business_date(effective_date, "生效日期", required=False)
        registered, extract, digest, extract_digest = self._selected_files(file_token, extract_source_token)
        with self.database.transaction():
            duplicate = self._duplicate(digest)
            if duplicate:
                return duplicate
            document_id = self.database.add_document(title, doc_type=doc_type, scope_market=scope_market, model_scope=model_scope)
            version_id = self.database.add_document_version(document_id, version_label=str(version_label or "").strip(), sha256=digest, path_pdf=str(registered), path_docx=str(extract) if extract else None, effective_date=effective_date)
            self.database.add_review_record("document", str(document_id), "registered", bucket=doc_type, excerpt=json.dumps({"version_id": version_id, "model_scope": model_scope, "scope_market": scope_market, "registered_sha256": digest, "extract_sha256": extract_digest, "verified": False}, ensure_ascii=False))
        return {"document_id": document_id, "version_id": version_id, "duplicate": False, "is_current": True}

    def append_version(
        self, document_id: int, *, file_token: str, version_label: str,
        extract_source_token: str | None = None, effective_date: str | None = None,
    ) -> dict[str, Any]:
        version_label = self.database._required_business_text(version_label, "版本标签")
        effective_date = self.database._business_date(effective_date, "生效日期", required=False)
        registered, extract, digest, extract_digest = self._selected_files(file_token, extract_source_token)
        with self.database.transaction():
            document = self._document(document_id)
            duplicate = self._duplicate(digest, document_id)
            if duplicate:
                return duplicate
            version_id = self.database.add_document_version(document_id, version_label=version_label, sha256=digest, path_pdf=str(registered), path_docx=str(extract) if extract else None, supersedes_version_id=document["current_version_id"], effective_date=effective_date)
            self.database.add_review_record("document", str(document_id), "version_added", bucket=document["doc_type"], excerpt=json.dumps({"version_id": version_id, "supersedes_version_id": document["current_version_id"], "version_label": version_label, "registered_sha256": digest, "extract_sha256": extract_digest, "verified": False}, ensure_ascii=False))
        return {"document_id": document_id, "version_id": version_id, "duplicate": False, "is_current": True}

    def review_version(
        self, document_id: int, version_id: int, *, reviewer: str,
        reviewed_at: str, basis: str, confirmed: bool, model_scope: str | None = None,
        scope_market: str | None = None,
    ) -> dict[str, Any]:
        if confirmed is not True:
            raise ValueError("请明确确认已核对资料原文及适用范围。")
        reviewer = self.database._required_business_text(reviewer, "复核人")
        reviewed_at = self.database._business_date(reviewed_at, "复核日期")
        basis = self.database._required_business_text(basis, "复核依据")
        normalized_scope = _validate_model_scope(model_scope) if model_scope is not None else None
        with self.database.transaction() as connection:
            document = self._document(document_id)
            version = next((item for item in self.database.list_document_versions(document_id) if item["id"] == version_id), None)
            if version is None or document["current_version_id"] != version_id:
                raise ValueError("请复核资料当前版本；旧版本不能设为当前已复核。")
            if not version.get("path_pdf"):
                raise ValueError("资料未登记受控文件，不能复核。")
            registered = self._allowed_file(Path(version["path_pdf"]))
            extract = self._allowed_file(Path(version["path_docx"]), extract_source=True) if version.get("path_docx") else None
            try:
                digest = file_sha256(registered)
                extract_digest = file_sha256(extract) if extract else ""
            except OSError as error:
                raise ValueError("所选资料暂时不可读取。") from error
            if not version["sha256"] or digest != version["sha256"]:
                raise ValueError("资料文件已变更，请先追加新版本再复核。")
            scope = normalized_scope if normalized_scope is not None else document["model_scope"]
            if not scope:
                raise ValueError("请先核对并登记适用机型后复核。")
            scope = _validate_model_scope(scope)
            market = scope_market if scope_market is not None else document["scope_market"]
            if market not in {"domestic", "overseas"}:
                raise ValueError("请先核对并登记适用市场后复核。")
            if scope != document["model_scope"] or market != document["scope_market"]:
                answers = connection.execute(
                    """SELECT a.id, a.structured_signature FROM kh_qa_answers a
                       JOIN kh_evidence e ON e.id=a.evidence_id
                       JOIN kh_document_versions v ON v.id=e.document_version_id
                       WHERE v.document_id=? AND a.status='published'""",
                    (document_id,),
                ).fetchall()
                for answer in answers:
                    self.database.mark_qa_for_structured_review(answer["id"], answer["structured_signature"])
            connection.execute("UPDATE kh_documents SET model_scope=?, scope_market=? WHERE id=?", (scope, market, document_id))
            connection.execute("UPDATE kh_document_versions SET verified_at=? WHERE id=?", (reviewed_at, version_id))
            self.database.add_review_record("document_version", str(version_id), "verified", bucket=document["doc_type"], reviewer=reviewer, decided_at=reviewed_at, excerpt=json.dumps({"basis": basis, "model_scope": scope, "scope_market": market, "registered_sha256": digest, "extract_sha256": extract_digest}, ensure_ascii=False))
        return {"document_id": document_id, "version_id": version_id, "verified": True, "verified_at": reviewed_at, "model_scope": scope, "scope_market": market}

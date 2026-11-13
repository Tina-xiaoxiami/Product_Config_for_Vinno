"""Verify a document-editor publication against its task and controlled originals."""
from __future__ import annotations

import asyncio
import json
import mimetypes
from pathlib import Path

from sqlalchemy import text

from app.services.controlled_material_import import (
    ControlledMaterial, _sha256, document_identity_indexes, match_document_identity,
)
from app.services.knowledge_content import extract_registered_document
from app.services.knowledge_parameters import answer_snapshot
from app.services.knowledge_scope import a_only_question, document_model_identity_unique, resolve_query_scope


def _one(records, key, value):
    found = [item for item in records if item.get(key) == value]
    if len(found) != 1:
        raise ValueError(f"发布记录无法唯一对应 {key}")
    return found[0]


def verified_publication(root, task_path, receipt_path, product, series, version):
    """Resolve the exact body PDF and Word from one controlled receipt."""
    root = (Path(root) / "白皮书").resolve()
    task_path, receipt_path = Path(task_path), Path(receipt_path)
    task = json.loads(task_path.read_text())
    receipt = json.loads(receipt_path.read_text())
    try:
        if (receipt["controlled"] is not True or receipt_path.stem != receipt["id"]
                or receipt_path.parent.name != receipt["job_id"] or task_path.stem != task["id"]):
            raise ValueError("回执须为正式受控发布且对应任务和发布批次")
        record = _one(task["publishes"], "id", receipt["id"])
        if (record["controlled"] is not True or record["artifacts"] != receipt["artifacts"]
                or product not in record["products"] or task["version_to"] != version):
            raise ValueError("回执与任务发布账本不一致")
        round_ = _one(task["rounds"], "id", record["round_id"])
        build = _one(round_["builds"], "id", record["build_id"])
        result = build["products"][product]
        saved = receipt["artifacts"][product]
        if (build["status"] != "done" or build["job_id"] != receipt["job_id"]
                or result.get("failed") or result.get("gate") != "format gate: PASSED"
                or not saved["generation_id"] or result["generation_id"] != saved["generation_id"]
                or result["artifact_hashes"] != saved["hashes"] or result["version"] != version
                or round_["snapshot"]["changeset"]["config_versions"][series] != version):
            raise ValueError("构建、原件或冻结配置版本与所选范围不一致")

        materials = []
        for kind, suffix in (("pdf", ".pdf"), ("docx", ".docx")):
            digest = saved["hashes"][kind]
            paths = []
            for location, expected in saved["destinations"].items():
                original = Path(location)
                path = original.resolve()
                if (original.is_absolute() and path.is_relative_to(root) and path.suffix.lower() == suffix
                        and "去封面" in path.relative_to(root).parts and expected == digest):
                    paths.append(path)
            if len(paths) != 1 or not paths[0].is_file() or _sha256(paths[0]) != digest:
                raise ValueError(f"回执缺少唯一且摘要一致的受控 {kind.upper()} 正文")
            path = paths[0]
            materials.append(ControlledMaterial("whitepaper", path.stem, path, version,
                                               "", None, None, mimetypes.guess_type(path.name)[0], digest))
        if materials[0].title != materials[1].title:
            raise ValueError("Word 和 PDF 正文名称不一致")
        return materials, {
            "task": task["id"], "job": receipt["job_id"], "round": round_["id"], "build": build["id"],
            "publication": receipt["id"], "generation": saved["generation_id"], "product": product,
        }
    except (KeyError, TypeError) as exc:
        raise ValueError("回执或任务缺少正式发布依据") from exc


async def sync_publication(db, root, task_path, receipt_path, product, supplied_scope, *, apply=False):
    """Preview, or commit the two document indexes and both extractions together."""
    if apply:
        await db.execute(text("BEGIN IMMEDIATE"))
    try:
        scope = await resolve_query_scope(db, supplied_scope)
        if (not scope or not scope["country"] or a_only_question(scope["model_name"])
                or a_only_question(product) or not await document_model_identity_unique(db, scope)):
            raise ValueError("请选择有明确国家、唯一完整型号的维护范围")
        # The source task product must identify the same full model, or its exact
        # short label without the manufacturer prefix (e.g. ULTIMUS 6S → 6S).
        model_name = scope["model_name"]
        labels = {model_name, model_name.removeprefix("ULTIMUS ")}
        if product not in labels:
            raise ValueError("回执产品与配置完整型号不一致")
        version = scope["software_version"]
        series_id = await db.scalar(text(
            "SELECT series_id FROM product_models WHERE id=:id AND is_enabled=1 AND COALESCE(status,'')<>'已合并'"
        ), {"id": scope["product_model_id"]})
        if series_id is None:
            raise ValueError("机型已停用或已合并")
        metadata, snapshot = await answer_snapshot(db, series_id, software_version=version)
        if not any(int(row["id"]) == scope["product_model_id"] for row in snapshot["models"]):
            raise ValueError("正式配置快照未包含该完整机型")
        materials, publication = await asyncio.to_thread(
            verified_publication, root, task_path, receipt_path, product, scope["series_name"], version,
        )
        rows = (await db.execute(text("SELECT * FROM knowledge_documents ORDER BY id"))).mappings().all()
        indexes = document_identity_indexes(rows)
        if apply:
            await db.execute(text("""
                CREATE TABLE IF NOT EXISTS knowledge_whitepaper_publication_sources (
                    document_id INTEGER PRIMARY KEY REFERENCES knowledge_documents(id) ON DELETE CASCADE,
                    sha256 TEXT NOT NULL, provenance TEXT NOT NULL
                )
            """))
        results = []
        for material in materials:
            identity, existing = match_document_identity(material.path, material.sha256, material.document_type, indexes)
            fields = {
                "document_type": material.document_type, "title": material.title, "file_name": material.path.name,
                "file_path": str(material.path), "version": version, "market": scope["market"],
                "country": scope["country"], "product_series": model_name,
                "mime_type": material.mime_type, "sha256": material.sha256,
            }
            if identity != "ready" and (identity != "same_path" or existing["source_status"] != "active"
                    or any(existing[key] != value for key, value in fields.items())):
                raise ValueError("原件、范围或名称与既有资料冲突，须先核对登记")
            ident = existing["id"] if existing else None
            outcome = {"status": "unchanged" if existing else "ready", "document_id": ident,
                       "file_path": fields["file_path"], "sha256": material.sha256}
            if apply:
                if ident is None:
                    ident = (await db.execute(text("""
                        INSERT INTO knowledge_documents(document_type,title,file_name,file_path,version,market,country,product_series,mime_type,sha256,source_status)
                        VALUES (:document_type,:title,:file_name,:file_path,:version,:market,:country,:product_series,:mime_type,:sha256,'active')
                        RETURNING id
                    """), fields)).scalar_one()
                    outcome.update(status="inserted", document_id=ident)
                await db.execute(text("""
                    INSERT INTO knowledge_whitepaper_publication_sources(document_id,sha256,provenance)
                    VALUES (:id,:sha256,:provenance) ON CONFLICT(document_id) DO NOTHING
                """), {"id": ident, "sha256": material.sha256, "provenance": json.dumps({
                    **publication, "configuration_version_id": metadata["id"], "scope": scope,
                }, ensure_ascii=False, sort_keys=True)})
                extracted = await extract_registered_document(db, ident, commit=False, expected_sha256=material.sha256)
                outcome.update(chunk_count=extracted["chunk_count"], reused=extracted["reused"])
            results.append(outcome)
        if apply:
            await db.commit()
        return {"publication": publication, "configuration_version_id": metadata["id"],
                "scope": scope, "documents": results}
    except Exception:
        if apply:
            await db.rollback()
        raise

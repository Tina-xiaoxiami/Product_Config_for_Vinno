"""Contract tests for the feature release (功能发布) API.

These tests pin the behaviour the release capability owes the rest of the system:

- 「某个功能在哪个版本发布」只由**已确认**的功能版本决定，待复核候选单独返回；
- 版本号按数字排序，"R10" 这类文本版本不会冒充首发版本；
- 覆盖边界（已纳管 Release Note 的最早版本）随结果一起返回；
- 发布介绍按四个字段保存、每次保存前留历史，附件有独立实体与路径校验；
- 候选回填默认只预览，只有显式 apply 才落库，且落库是 pending。
"""

import sqlite3

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import release
from app.database import Base, get_db
import app.models  # noqa: F401 - registers every model on Base.metadata
from app.services import feature_release_versions
from app.services.feature_release_versions import (
    FeatureReleaseAttachmentError,
    resolve_release_attachment_path,
)


CONFIG_CHUNK_114_40 = (
    "1\n"
    "1. 概述\n"
    "此次更新新增心脏教学。\n"
    "2. 配置变更\n"
    "探头/功能 V 代码 配置\n"
    "梯形成像 V30001 新增,V10 系列选配支持。\n"
    "3. 图像优化\n"
    "3.1 超微细血流成像优化\n"
    "提升灵敏度。"
)

# 目录行（点前导 + 页码）不是变更证据：它只说明文档后面有这一节。
TOC_CHUNK_114_30 = (
    "1\n"
    "1. 概述\n"
    "2. 配置变更\n"
    "2.1. 新增超微细血流成像 SMF 选配.......................... 4\n"
    "2.2. 新增梯形成像 V30001 支持............................ 9"
)

CONFIG_CHUNK_114_80 = (
    "1\n"
    "1. 概述\n"
    "此版本为 V 系列合并版本。\n"
    "2. 配置变更\n"
    "探头/功能 V 代码 配置\n"
    "超微细血流成像 V30012 新增,V10 系列选配支持。"
)


def _seed(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        f"""
        PRAGMA foreign_keys = ON;
        INSERT INTO feature_groups (id, name, sort_order) VALUES (1, '成像技术', 1);
        INSERT INTO features (
            id, group_id, name, ipn, sort_order, config_item_id,
            primary_cn_name, primary_en_name, identity_status
        ) VALUES
            (1, 1, 'TView', '6000017', 1, NULL, '梯形成像', 'TView', 'confirmed'),
            (7, 1, 'SMF', '6000273', 2, NULL, '超微细血流成像',
             'SMF(Super Micro Flow)', 'confirmed');
        INSERT INTO config_items (id, row_index, ipn, rd_name, v_code, zh_desc, en_desc)
        VALUES
            (1, 1, '6000017', 'TView', 'V30001', '梯形成像', 'TView'),
            (2, 2, '6000273', 'SupportHSF【启用】', 'V30012', '超微细血流成像',
             'SMF(Super Micro Flow)');
        INSERT INTO feature_config_item_links (
            feature_id, config_item_id, relation_type, source, review_status
        ) VALUES
            (1, 1, 'primary', 'test', 'approved'),
            (7, 2, 'primary', 'test', 'approved');
        INSERT INTO knowledge_documents (
            id, document_type, title, file_name, file_path, version, market,
            product_series, source_status
        ) VALUES
            (100, 'release_note', 'V10系列Release Note_1.14.40', 'a.pdf',
             '/tmp/a.pdf', '1.14.40', 'domestic', 'V10', 'active'),
            (101, 'release_note', 'V系列 Release Note_1.14.80', 'b.pdf',
             '/tmp/b.pdf', '1.14.80', 'domestic', 'V10', 'active'),
            (102, 'release_note', 'V10系列Release Note_1.14.30', 'c.pdf',
             '/tmp/c.pdf', '1.14.30', 'domestic', 'V10', 'active');
        INSERT INTO knowledge_document_extractions (
            document_id, extractor_version, status, chunk_count
        ) VALUES (100, '2', 'completed', 1), (101, '2', 'completed', 1),
                 (102, '2', 'completed', 1);
        INSERT INTO knowledge_document_chunks (
            document_id, chunk_index, page_number, source_ref, content,
            normalized_content, content_hash
        ) VALUES
            (100, 0, 3, '第3页', '{CONFIG_CHUNK_114_40}', '', 'h1'),
            (101, 0, 4, '第4页', '{CONFIG_CHUNK_114_80}', '', 'h2'),
            (102, 0, 2, '第2页', '{TOC_CHUNK_114_30}', '', 'h3');
        """
    )
    connection.commit()
    connection.close()


async def _client_for(database_path, monkeypatch=None, attachment_root=None):
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
    _seed(database_path)

    if monkeypatch is not None and attachment_root is not None:
        monkeypatch.setattr(
            feature_release_versions, "RELEASE_ATTACHMENT_ROOT", attachment_root
        )

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(release.router, prefix="/api/release")

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )
    return client, engine


async def _create_version(client, feature_id, **payload):
    body = {"software_version": "1.14.80", "review_status": "confirmed"}
    body.update(payload)
    return await client.post(f"/api/release/features/{feature_id}/versions", json=body)


@pytest.mark.asyncio
async def test_first_release_uses_only_confirmed_versions_and_reports_coverage(tmp_path):
    database_path = tmp_path / "release.db"
    client, engine = await _client_for(database_path)

    async with client:
        await _create_version(client, 1, software_version="1.14.80")
        await _create_version(client, 1, software_version="1.14.40")
        pending = await _create_version(
            client, 7, software_version="1.14.20", review_status="pending"
        )
        timeline = await client.get("/api/release/features/1/versions")
        pending_timeline = await client.get("/api/release/features/7/versions")
    await engine.dispose()

    assert pending.status_code == 200
    body = timeline.json()
    assert timeline.status_code == 200
    assert body["feature"]["primary_cn_name"] == "梯形成像"
    assert body["first_release"]["software_version"] == "1.14.40"
    assert body["first_release"]["review_status"] == "confirmed"
    assert [item["software_version"] for item in body["items"]] == ["1.14.40", "1.14.80"]
    assert body["confirmed_count"] == 2
    assert body["pending_count"] == 0
    # 已纳管资料的最早版本必须随结论返回，避免把「资料中最早出现」当成首发。
    assert body["earliest_ingested_version"] == "1.14.30"
    assert "已纳管 Release Note 最早版本为 1.14.30" in body["coverage_note"]

    pending_body = pending_timeline.json()
    assert pending_body["first_release"] is None
    assert pending_body["first_release_candidate"]["software_version"] == "1.14.20"
    assert pending_body["confirmed_count"] == 0
    assert pending_body["pending_count"] == 1


@pytest.mark.asyncio
async def test_text_versions_never_become_the_first_release_version(tmp_path):
    database_path = tmp_path / "release.db"
    client, engine = await _client_for(database_path)

    async with client:
        await _create_version(client, 1, software_version="R10")
        await _create_version(client, 1, software_version="1.14.100")
        timeline = await client.get("/api/release/features/1/versions")
    await engine.dispose()

    body = timeline.json()
    assert body["first_release"]["software_version"] == "1.14.100"
    assert [item["software_version"] for item in body["items"]] == ["1.14.100", "R10"]


@pytest.mark.asyncio
async def test_release_version_scope_is_unique_per_feature_version_and_series(tmp_path):
    database_path = tmp_path / "release.db"
    client, engine = await _client_for(database_path)

    async with client:
        first = await _create_version(client, 1, product_series="V10")
        duplicate = await _create_version(client, 1, product_series="V10")
        other_series = await _create_version(client, 1, product_series="ULTIMUS Series")
        missing_feature = await _create_version(client, 999)
    await engine.dispose()

    assert first.status_code == 200
    assert duplicate.status_code == 422
    assert duplicate.json()["detail"] == "该功能在此版本与系列下已有记录"
    assert other_series.status_code == 200
    assert missing_feature.status_code == 404
    assert missing_feature.json()["detail"] == "功能不存在"


@pytest.mark.asyncio
async def test_release_version_update_confirms_and_validates_dates(tmp_path):
    database_path = tmp_path / "release.db"
    client, engine = await _client_for(database_path)

    async with client:
        created = await _create_version(
            client, 1, review_status="pending", release_date=None
        )
        version_id = created.json()["id"]
        confirmed = await client.put(
            f"/api/release/versions/{version_id}",
            json={
                "review_status": "confirmed",
                "release_date": "2026-08-05",
                "lifecycle_status": "released",
            },
        )
        bad_date = await client.put(
            f"/api/release/versions/{version_id}", json={"release_date": "2026/08/05"}
        )
        bad_lifecycle = await client.put(
            f"/api/release/versions/{version_id}", json={"lifecycle_status": "shipped"}
        )
        missing = await client.get("/api/release/versions/99999")
    await engine.dispose()

    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["review_status"] == "confirmed"
    assert body["release_date"] == "2026-08-05"
    assert body["lifecycle_status"] == "released"
    assert bad_date.status_code == 422
    assert bad_date.json()["detail"] == "发布日期必须写成 YYYY-MM-DD"
    assert bad_lifecycle.status_code == 422
    assert bad_lifecycle.json()["detail"] == "生命周期状态 取值非法：shipped"
    assert missing.status_code == 404
    assert missing.json()["detail"] == "功能版本不存在"


@pytest.mark.asyncio
async def test_version_list_answers_what_a_release_shipped(tmp_path):
    database_path = tmp_path / "release.db"
    client, engine = await _client_for(database_path)

    async with client:
        await _create_version(client, 1, software_version="1.14.80", change_type="added")
        await _create_version(client, 7, software_version="1.14.80", change_type="added")
        await _create_version(client, 1, software_version="1.14.40", change_type="added")
        listing = await client.get(
            "/api/release/versions", params={"software_version": "1.14.80"}
        )
        searched = await client.get("/api/release/versions", params={"q": "SMF"})
        overview = await client.get("/api/release/overview")
    await engine.dispose()

    body = listing.json()
    assert body["total"] == 2
    assert body["skip"] == 0
    assert body["limit"] == 50
    assert {item["feature_primary_cn_name"] for item in body["items"]} == {
        "梯形成像",
        "超微细血流成像",
    }
    assert {item["software_version"] for item in body["items"]} == {"1.14.80"}

    assert searched.json()["total"] == 1
    assert searched.json()["items"][0]["feature_id"] == 7

    versions = {item["software_version"]: item for item in overview.json()["items"]}
    assert versions["1.14.80"]["total"] == 2
    assert versions["1.14.80"]["confirmed"] == 2
    assert versions["1.14.40"]["total"] == 1


@pytest.mark.asyncio
async def test_introduction_keeps_four_sections_and_snapshots_the_previous_version(tmp_path):
    database_path = tmp_path / "release.db"
    client, engine = await _client_for(database_path)

    async with client:
        created = await _create_version(client, 1)
        version_id = created.json()["id"]
        missing = await client.get(
            f"/api/release/versions/{version_id}/introduction"
        )
        first = await client.put(
            f"/api/release/versions/{version_id}/introduction",
            json={
                "summary": "宽景成像拼接。",
                "clinical_significance": "帮助观察大范围结构。",
                "workflow": "选择 PView 模式后扫描。",
                "applications": ["腹部", "产科"],
                "review_status": "published",
                "change_note": "首版",
            },
        )
        second = await client.put(
            f"/api/release/versions/{version_id}/introduction",
            json={"summary": "宽景成像拼接（修订）。", "applications": ["腹部"]},
        )
        history = await client.get(
            f"/api/release/versions/{version_id}/introduction/history"
        )
        empty = await client.put(
            f"/api/release/versions/{version_id}/introduction", json={}
        )
        blank = await _create_version(client, 7, software_version="1.14.40")
        blank_id = blank.json()["id"]
        all_blank = await client.put(
            f"/api/release/versions/{blank_id}/introduction",
            json={"summary": "", "applications": []},
        )
    await engine.dispose()

    assert missing.status_code == 404
    assert missing.json()["detail"] == "该功能版本还没有发布介绍"

    assert first.status_code == 200
    first_body = first.json()
    assert first_body["version"] == 1
    assert first_body["review_status"] == "published"
    assert first_body["applications"] == ["腹部", "产科"]
    assert first_body["clinical_significance"] == "帮助观察大范围结构。"

    # 第二次保存只传了两个字段：未传的字段保持原值，不整篇覆盖。
    second_body = second.json()
    assert second_body["version"] == 2
    assert second_body["summary"] == "宽景成像拼接（修订）。"
    assert second_body["clinical_significance"] == "帮助观察大范围结构。"
    assert second_body["applications"] == ["腹部"]

    items = history.json()["items"]
    assert [item["version"] for item in items] == [2, 1]
    assert items[0]["is_current"] is True
    assert items[1]["summary"] == "宽景成像拼接。"
    assert items[1]["applications"] == ["腹部", "产科"]
    assert items[1]["is_current"] is False

    assert empty.status_code == 422
    assert empty.json()["detail"] == "没有需要保存的发布介绍字段"
    assert all_blank.status_code == 422
    assert all_blank.json()["detail"] == "发布介绍内容不能全部为空"


@pytest.mark.asyncio
async def test_attachment_upload_stores_a_row_and_delete_reclaims_the_file(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "release.db"
    attachment_root = tmp_path / "release_attachments"
    client, engine = await _client_for(
        database_path, monkeypatch=monkeypatch, attachment_root=attachment_root
    )

    async with client:
        created = await _create_version(client, 1)
        version_id = created.json()["id"]
        await client.put(
            f"/api/release/versions/{version_id}/introduction",
            json={"summary": "带附件的介绍"},
        )
        uploaded = await client.post(
            f"/api/release/versions/{version_id}/introduction/attachments",
            files={"file": ("演示图.png", b"\x89PNG-bytes", "image/png")},
        )
        escaped = await client.post(
            f"/api/release/versions/{version_id}/introduction/attachments",
            files={"file": ("../evil.txt", b"x", "text/plain")},
        )
        attached = await client.get(
            f"/api/release/versions/{version_id}/introduction"
        )
        # 删除前先记录落盘状态：删除就是要回收物理文件。
        stored_files = list(attachment_root.iterdir())
        stored_name = stored_files[0].name if stored_files else ""
        stored_bytes = stored_files[0].read_bytes() if stored_files else b""
        attachment_id = attached.json()["attachments"][0]["id"]
        deleted = await client.delete(
            f"/api/release/introduction-attachments/{attachment_id}"
        )
    await engine.dispose()

    assert uploaded.status_code == 200
    body = uploaded.json()
    assert [item["file_name"] for item in body["attachments"]] == ["演示图.png"]
    # 磁盘名是 uuid + 后缀（避免 macOS NFD 归一化与重名），展示名留在 file_name 里。
    assert len(stored_files) == 1
    assert stored_name.endswith(".png")
    assert stored_name != "演示图.png"
    assert stored_bytes == b"\x89PNG-bytes"
    assert body["attachments"][0]["sha256"]
    assert body["attachments"][0]["file_path"].endswith(stored_name)

    assert escaped.status_code == 400
    assert escaped.json()["detail"] == "附件文件名不合法"
    assert not (tmp_path / "evil.txt").exists()

    assert deleted.status_code == 200
    assert deleted.json() == {
        "attachment_id": attachment_id,
        "status": "deleted",
        "removed_file": True,
    }
    assert list(attachment_root.iterdir()) == []


def test_attachment_paths_reject_traversal_variants(tmp_path, monkeypatch):
    monkeypatch.setattr(
        feature_release_versions, "RELEASE_ATTACHMENT_ROOT", tmp_path / "root"
    )
    for candidate in ("", ".", "..", "../x.png", "..\\x.png", "a/b.png", "a\\b.png", "x\x00.png"):
        with pytest.raises(FeatureReleaseAttachmentError):
            resolve_release_attachment_path(candidate)
    assert resolve_release_attachment_path("演示图.png").name == "演示图.png"


@pytest.mark.asyncio
async def test_backfill_previews_from_release_notes_without_writing(tmp_path):
    database_path = tmp_path / "release.db"
    client, engine = await _client_for(database_path)

    async with client:
        preview = await client.post("/api/release/backfill", json={})
        before = await client.get("/api/release/versions")
        applied = await client.post("/api/release/backfill", json={"apply": True})
        after = await client.get("/api/release/versions")
        again = await client.post("/api/release/backfill", json={"apply": True})
        timeline = await client.get("/api/release/features/1/versions")
    await engine.dispose()

    body = preview.json()
    assert preview.status_code == 200
    assert body["applied"] is False
    assert body["created"] == 0
    assert before.json()["total"] == 0

    by_scope = {
        (item["feature_id"], item["software_version"]): item for item in body["candidates"]
    }
    tview = by_scope[(1, "1.14.40")]
    assert tview["matched_by"] == "v_code"
    assert tview["change_type"] == "added"
    assert tview["evidence_kind"] == "configuration_change"
    assert tview["evidence_source_ref"] == "第3页"
    assert tview["evidence_document_id"] == 100
    assert tview["is_first_release_candidate"] is True
    assert "梯形成像" in tview["evidence_excerpt"]

    # 正文叙述段落只说明「该版本涉及该功能」，不能当成首发证据。
    narrative = by_scope[(7, "1.14.40")]
    assert narrative["evidence_kind"] == "narrative"
    assert narrative["change_type"] == "optimized"
    assert narrative["is_first_release_candidate"] is False

    smf = by_scope[(7, "1.14.80")]
    assert smf["evidence_kind"] == "configuration_change"
    assert smf["matched_by"] == "v_code"
    assert smf["is_first_release_candidate"] is True
    assert body["earliest_ingested_version"] == "1.14.30"
    assert "不能证明首发" in body["coverage_note"]
    assert body["applicable"] == len(body["candidates"])

    assert applied.status_code == 200
    applied_body = applied.json()
    assert applied_body["applied"] is True
    assert applied_body["created"] == len(body["candidates"])
    assert applied_body["applicable"] == 0
    assert applied_body["skipped"] == len(body["candidates"])

    # 落库的行是待复核候选，不是正式结论；重复 apply 不会重复写入。
    listed = after.json()
    assert listed["total"] == len(body["candidates"])
    assert {item["review_status"] for item in listed["items"]} == {"pending"}
    assert {item["source"] for item in listed["items"]} == {"release_note"}
    assert again.json()["created"] == 0

    timeline_body = timeline.json()
    assert timeline_body["first_release"] is None
    assert timeline_body["first_release_candidate"]["software_version"] == "1.14.40"
    assert timeline_body["earliest_ingested_version"] == "1.14.30"


@pytest.mark.asyncio
async def test_backfill_can_be_scoped_to_one_software_version(tmp_path):
    database_path = tmp_path / "release.db"
    client, engine = await _client_for(database_path)

    async with client:
        scoped = await client.post(
            "/api/release/backfill", json={"software_versions": ["1.14.80"]}
        )
        features_only = await client.post(
            "/api/release/backfill", json={"feature_ids": [1]}
        )
    await engine.dispose()

    assert {item["software_version"] for item in scoped.json()["candidates"]} == {
        "1.14.80"
    }
    assert {item["feature_id"] for item in features_only.json()["candidates"]} == {1}


@pytest.mark.asyncio
async def test_table_of_contents_lines_are_not_release_evidence(tmp_path):
    database_path = tmp_path / "release.db"
    client, engine = await _client_for(database_path)

    async with client:
        preview = await client.post("/api/release/backfill", json={})
    await engine.dispose()

    candidates = preview.json()["candidates"]
    # 1.14.30 只有目录行提到这两个功能，不应产生任何候选。
    assert [item for item in candidates if item["software_version"] == "1.14.30"] == []
    smf_versions = {
        item["software_version"] for item in candidates if item["feature_id"] == 7
    }
    assert smf_versions == {"1.14.40", "1.14.80"}
    first = [
        item
        for item in candidates
        if item["feature_id"] == 7 and item["is_first_release_candidate"]
    ]
    assert [item["software_version"] for item in first] == ["1.14.80"]

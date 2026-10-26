from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.integrations.release_workbench import (
    close_release_workbench,
    create_integrated_workbench,
    mount_release_workbench,
)


def _workbench(tmp_path: Path):
    canonical_database = tmp_path / "product_config.db"
    sqlite3.connect(canonical_database).close()
    return create_integrated_workbench(
        {
            "TESTING": True,
            "DATABASE_PATH": tmp_path / "release_workbench.db",
            "SEARCH_INDEX_PATH": tmp_path / "release_workbench.search-index.db",
            "PRODUCT_CONFIG_DATABASE": canonical_database,
            "RELEASE_NOTE_ROOT": None,
            "CONTROLLED_MATERIALS_ROOT": None,
            "TRAINING_ROOT": None,
            "SOURCE_ROOTS": [],
            "CONTROLLED_EXTRACTION_ROOTS": [],
            "WORKBENCH_HOME": False,
        }
    )


def _client(tmp_path: Path) -> tuple[TestClient, object]:
    host = FastAPI()
    workbench = _workbench(tmp_path)
    mount_release_workbench(host, workbench)
    return TestClient(host), workbench


def test_workbench_is_mounted_under_one_prefix_with_prefixed_assets(tmp_path: Path) -> None:
    client, workbench = _client(tmp_path)
    try:
        health = client.get("/release-workbench/api/v1/health")
        assert health.status_code == 200
        assert health.json()["data"]["service"] == "feature-release-tracker"

        page = client.get("/release-workbench/?embedded=1")
        assert page.status_code == 200
        assert 'class="workbench-embedded"' in page.text
        assert 'href="/release-workbench/static/styles.css' in page.text
        assert 'src="/release-workbench/static/app.js' in page.text
        assert '"basePath": "/release-workbench"' in page.text
    finally:
        close_release_workbench(workbench)


def test_static_client_routes_api_preview_and_download_through_mount_prefix(tmp_path: Path) -> None:
    client, workbench = _client(tmp_path)
    try:
        app_source = client.get("/release-workbench/static/app.js").text
        workspace_source = client.get("/release-workbench/static/workspace.js").text

        assert "function workbenchUrl" in app_source
        assert "fetch(workbenchUrl(path)" in app_source
        assert "workbenchUrl(`/api/v1/workbench/search-index/sources/" in app_source
        assert "workbenchUrl(`/api/v1/workbench/backups/" in workspace_source
        assert "workbenchUrl(`/api/v1/workbench/search-index/sources/" in workspace_source
    finally:
        close_release_workbench(workbench)


def test_prefixed_search_opens_the_matching_release_snapshot(tmp_path: Path) -> None:
    client, workbench = _client(tmp_path)
    database = workbench.extensions["tracker_database"]
    release_id = database.upsert_release("1.51.80")
    database.stage_release_pair(
        release_id,
        [
            {
                "path": "/readonly/release-note.docx",
                "language": "cn",
                "sha256": "snapshot",
                "content": "前言\n新增后台转换\n仍可继续操作",
            }
        ],
        [],
        [],
    )
    try:
        result = client.get(
            "/release-workbench/api/v1/workbench/search",
            params={"q": "后台转换", "sources": "release"},
        )
        assert result.status_code == 200
        hit = result.json()["data"]["results"][0]

        preview = client.get(
            f"/release-workbench/api/v1/workbench/search-index/sources/{hit['preview_id']}/preview",
            params={"locator": hit["locator"]},
        )

        assert preview.status_code == 200
        assert "后台转换" in preview.json()["data"]["chunks"][0]["text"]
        assert "/readonly" not in str(preview.json())
    finally:
        close_release_workbench(workbench)


def test_integrated_mode_allows_release_review_but_blocks_duplicate_business_writes(
    tmp_path: Path,
) -> None:
    client, workbench = _client(tmp_path)
    try:
        releases = client.get("/release-workbench/api/v1/releases")
        assert releases.status_code == 200

        blocked = [
            ("/release-workbench/api/v1/features", {"cn_name": "duplicate"}),
            ("/release-workbench/api/v1/categories", {"name": "duplicate"}),
            ("/release-workbench/api/v1/import-candidates/batch/promote", {"candidate_ids": []}),
            (
                "/release-workbench/api/v1/import-candidates/1/approve",
                {"promote_to_feature": True},
            ),
        ]
        for path, payload in blocked:
            response = client.post(path, json=payload)
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "integrated_mode_restricted"

        ordinary_review = client.post(
            "/release-workbench/api/v1/import-candidates/1/approve",
            json={},
        )
        assert ordinary_review.status_code == 404
        assert ordinary_review.json()["error"]["code"] == "not_found"
    finally:
        close_release_workbench(workbench)


def test_embedded_mode_exposes_only_integrated_views_and_parent_navigation(tmp_path: Path) -> None:
    client, workbench = _client(tmp_path)
    try:
        page = client.get("/release-workbench/?embedded=1").text
        assert 'data-view="search"' in page
        assert 'data-view="review"' in page
        assert 'data-view="releases"' in page
        assert 'data-view="compare"' in page
        assert 'data-view="features"' not in page

        app_source = client.get("/release-workbench/static/app.js").text
        assert "release-workbench:navigate" in app_source
        assert "window.parent.postMessage" in app_source
        assert "release-workspace:activate" in app_source
        assert "event.source !== window.parent" in app_source
        assert "state.activeView !== view" in app_source
        assert "const overrideField = integratedMode() ? ''" in app_source
        assert "const promoteAction = integratedMode() ? ''" in app_source
    finally:
        close_release_workbench(workbench)


def test_close_release_workbench_stops_search_maintenance(tmp_path: Path) -> None:
    workbench = _workbench(tmp_path)
    maintenance = workbench.extensions["search_maintenance"]
    maintenance.ensure_started()

    close_release_workbench(workbench)

    assert maintenance._closed is True


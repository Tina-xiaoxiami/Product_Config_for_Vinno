import csv
import io
import sqlite3

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import feature_standards, features, knowledge
from app.database import Base, get_db
from app.models import FeatureNameStandard  # noqa: F401  注册标准表模型
from test_knowledge_api import _create_knowledge_database


def _standard_table_bytes(rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="\t", lineterminator="\n")
    writer.writerow(["中文名称", "英文名称", "中文UI"])
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _upload(content, name="功能名称标准表.tsv"):
    return {"file": (name, content, "text/tab-separated-values")}


async def _client_for(database_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    # 正式库由 init_db() 建表，测试库在这里补建标准表。
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.tables["feature_name_standards"].create)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(features.router, prefix="/api/features")
    app.include_router(feature_standards.router, prefix="/api/features/standards")
    app.include_router(knowledge.router, prefix="/api/knowledge")

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )
    return client, engine


STANDARD_ROWS = [
    ("组织多普勒成像", "Tissue Doppler Imaging", "TDI"),
    ("超微细血流成像", "SMF", "SMF"),
    ("心电信号", "ECG", "ECG"),
]


@pytest.mark.asyncio
async def test_importing_standard_table_reports_name_differences(tmp_path):
    database_path = tmp_path / "knowledge.db"
    _create_knowledge_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        imported = await client.post(
            "/api/features/standards/import",
            files=_upload(_standard_table_bytes(STANDARD_ROWS)),
        )
        audit = await client.get("/api/features/standards")
    await engine.dispose()

    assert imported.status_code == 200
    assert imported.json()["imported"] == 3

    body = audit.json()
    assert body["standard_count"] == 3
    entries = {entry["cn_name"]: entry for entry in body["standards"]}

    # 精确命中：中英文都与标准一致
    matched = entries["组织多普勒成像"]
    assert matched["feature_id"] == 1
    assert matched["severity"] == "ok"
    assert matched["match_reason"] == "中文名称精确匹配"

    # 系统英文名是「SMF(Super Micro Flow)」，标准是「SMF」→ 系统名多了内容
    smf = entries["超微细血流成像"]
    assert smf["feature_id"] == 7
    assert smf["severity"] == "differs"
    assert smf["en_field"]["status"] == "contains"
    assert smf["en_field"]["standard_value"] == "SMF"

    # 标准表有、系统没有
    assert entries["心电信号"]["severity"] == "missing"
    assert entries["心电信号"]["feature_id"] is None
    assert body["summary"] == {
        "ok": 1,
        "style": 0,
        "differs": 1,
        "ambiguous": 0,
        "missing": 1,
        "uncovered": 1,
    }
    assert [item["feature_id"] for item in body["uncovered_features"]] == [31]


@pytest.mark.asyncio
async def test_flags_are_available_by_feature_id_and_by_name(tmp_path):
    database_path = tmp_path / "knowledge.db"
    _create_knowledge_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        await client.post(
            "/api/features/standards/import",
            files=_upload(_standard_table_bytes(STANDARD_ROWS)),
        )
        flags = await client.get("/api/features/standards/flags")
    await engine.dispose()

    body = flags.json()
    assert set(body["by_feature"]) == {"7", "31"}
    assert body["by_feature"]["7"]["severity"] == "differs"
    assert body["by_feature"]["7"]["standard_cn_name"] == "超微细血流成像"
    assert body["by_feature"]["7"]["standard_en_name"] == "SMF"
    assert "SMF(Super Micro Flow)" in body["by_feature"]["7"]["message"]
    assert body["by_feature"]["31"]["severity"] == "uncovered"

    # 前端按名称查提示：主名和曾用名都能命中
    assert body["by_name"]["smfsupermicroflow"]["severity"] == "differs"
    assert body["by_name"]["超微细血流成像"]["severity"] == "differs"
    assert body["by_name"]["smf"]["severity"] == "differs"


@pytest.mark.asyncio
async def test_style_only_difference_is_reported_as_style(tmp_path):
    database_path = tmp_path / "knowledge.db"
    _create_knowledge_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        await client.post(
            "/api/features/standards/import",
            files=_upload(
                _standard_table_bytes([("组织多普勒成像", "tissue doppler imaging", "TDI")])
            ),
        )
        audit = await client.get("/api/features/standards")
        flags = await client.get("/api/features/standards/flags")
    await engine.dispose()

    entry = audit.json()["standards"][0]
    assert entry["severity"] == "style"
    assert entry["en_field"]["status"] == "style"
    assert audit.json()["summary"]["style"] == 1
    assert flags.json()["by_feature"]["1"]["severity"] == "style"
    assert "仅大小写、空格或符号不同" in flags.json()["by_feature"]["1"]["message"]


@pytest.mark.asyncio
async def test_ambiguous_standard_rows_are_not_assigned_automatically(tmp_path):
    database_path = tmp_path / "knowledge.db"
    _create_knowledge_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        await client.post(
            "/api/features/standards/import",
            files=_upload(
                _standard_table_bytes(
                    [
                        ("组织多普勒成像", "Tissue Doppler Imaging", "TDI"),
                        ("组织多普勒成像", "TDI", "TDI"),
                    ]
                )
            ),
        )
        audit = await client.get("/api/features/standards")
        flags = await client.get("/api/features/standards/flags")
    await engine.dispose()

    body = audit.json()
    assert body["summary"]["ambiguous"] == 2
    assert all(entry["severity"] == "ambiguous" for entry in body["standards"])
    assert flags.json()["by_feature"]["1"]["severity"] == "ambiguous"
    assert "人工确认" in flags.json()["by_feature"]["1"]["message"]


@pytest.mark.asyncio
async def test_importing_again_replaces_the_whole_standard_table(tmp_path):
    database_path = tmp_path / "knowledge.db"
    _create_knowledge_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        await client.post(
            "/api/features/standards/import",
            files=_upload(_standard_table_bytes(STANDARD_ROWS)),
        )
        second = await client.post(
            "/api/features/standards/import",
            files=_upload(_standard_table_bytes([("组织多普勒成像", "Tissue Doppler Imaging", "TDI")])),
        )
        audit = await client.get("/api/features/standards")
    await engine.dispose()

    assert second.status_code == 200
    body = audit.json()
    assert body["standard_count"] == 1
    assert [entry["cn_name"] for entry in body["standards"]] == ["组织多普勒成像"]
    assert body["source_file"] == "功能名称标准表.tsv"
    assert body["last_imported_at"] is not None


@pytest.mark.asyncio
async def test_latin_parenthetical_in_standard_chinese_name_is_not_a_difference(tmp_path):
    """标准中文名里的英文括号补充（宽景成像（Pview））不算中文名不一致，英文大小写仍要提示。"""

    database_path = tmp_path / "knowledge.db"
    _create_knowledge_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        INSERT INTO features (id, group_id, name, ipn, sort_order, primary_cn_name, primary_en_name, identity_status)
        VALUES (40, 1, '宽景成像', '', 9, '宽景成像', 'Pview', 'confirmed')
        """
    )
    connection.executemany(
        """
        INSERT INTO feature_names (feature_id, language, name, normalized_name, name_type, source, review_status)
        VALUES (?, ?, ?, ?, 'primary', 'feature_management', 'approved')
        """,
        [(40, "cn", "宽景成像", "宽景成像"), (40, "en", "Pview", "pview")],
    )
    connection.commit()
    connection.close()
    client, engine = await _client_for(database_path)

    async with client:
        await client.post(
            "/api/features/standards/import",
            files=_upload(_standard_table_bytes([("宽景成像（Pview）", "", "PView")])),
        )
        audit = await client.get("/api/features/standards")
    await engine.dispose()

    entry = audit.json()["standards"][0]
    assert entry["feature_id"] == 40
    assert entry["match_reason"] == "中文名称匹配（忽略括号补充）"
    assert entry["cn_field"]["status"] == "ok"
    assert entry["en_field"]["status"] == "style"
    assert entry["severity"] == "style"
    # 提示和展示仍使用标准表原文
    assert entry["cn_field"]["standard_value"] == "宽景成像（Pview）"
    assert entry["en_field"]["standard_value"] == "PView"


@pytest.mark.asyncio
async def test_chinese_parenthetical_in_standard_name_is_still_compared(tmp_path):
    """括号里含中文时属于名称的一部分，仍按不一致处理。"""

    database_path = tmp_path / "knowledge.db"
    _create_knowledge_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        await client.post(
            "/api/features/standards/import",
            files=_upload(
                _standard_table_bytes([("组织多普勒成像（含能量图）", "Tissue Doppler Imaging", "TDI")])
            ),
        )
        audit = await client.get("/api/features/standards")
    await engine.dispose()

    entry = audit.json()["standards"][0]
    assert entry["feature_id"] == 1
    assert entry["cn_field"]["status"] == "contained"
    assert entry["cn_field"]["severity"] == "differs"
    assert entry["severity"] == "differs"


@pytest.mark.asyncio
async def test_standard_table_without_chinese_header_is_rejected(tmp_path):
    database_path = tmp_path / "knowledge.db"
    _create_knowledge_database(database_path)
    client, engine = await _client_for(database_path)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="\t", lineterminator="\n")
    writer.writerow(["名称", "English"])
    writer.writerow(["组织多普勒成像", "Tissue Doppler Imaging"])

    async with client:
        rejected = await client.post(
            "/api/features/standards/import",
            files=_upload(buffer.getvalue().encode("utf-8")),
        )
        empty = await client.post(
            "/api/features/standards/import",
            files={"file": ("空.tsv", b"", "text/plain")},
        )
    await engine.dispose()

    assert rejected.status_code == 400
    assert "中文名称" in rejected.json()["detail"]
    assert empty.status_code == 400
    assert empty.json()["detail"] == "上传的文件是空的"


@pytest.mark.asyncio
async def test_feature_with_multiple_names_matches_through_any_of_them(tmp_path):
    """系统功能用曾用名或研发名命中标准定义时，也应给出中英文差异。"""

    database_path = tmp_path / "knowledge.db"
    _create_knowledge_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        await client.post(
            "/api/features/standards/import",
            files=_upload(
                _standard_table_bytes([("超微细血流成像", "SMF(Super Micro Flow)", "SMF")])
            ),
        )
        audit = await client.get("/api/features/standards")
    await engine.dispose()

    entry = audit.json()["standards"][0]
    assert entry["feature_id"] == 7
    assert entry["severity"] == "ok"
    assert entry["cn_field"]["status"] == "ok"
    assert entry["en_field"]["status"] == "ok"

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

    # 系统英文名「SMF(Super Micro Flow)」的括号说明不算差异，与标准「SMF」一致
    smf = entries["超微细血流成像"]
    assert smf["feature_id"] == 7
    assert smf["severity"] == "ok"
    assert smf["en_field"]["status"] == "ok"
    assert smf["en_field"]["standard_value"] == "SMF"
    assert smf["en_field"]["system_value"] == "SMF(Super Micro Flow)"

    # 标准表有、系统没有
    assert entries["心电信号"]["severity"] == "missing"
    assert entries["心电信号"]["feature_id"] is None
    # 配置管理描述与标准名称也分别比对：SMF(Super Micro Flow) ≠ 标准 SMF
    assert body["summary"] == {
        "ok": 2,
        "config_differs": 0,
        "config_unlinked": 1,
        "style": 0,
        "differs": 0,
        "ambiguous": 0,
        "missing": 1,
        "uncovered": 1,
    }
    assert [item["feature_id"] for item in body["uncovered_features"]] == [31]


@pytest.mark.asyncio
async def test_flags_cover_uncovered_features_and_name_index(tmp_path):
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
    # 标准表里的两种写法与系统一致（英文括号说明不算差异），只剩标准表未收录的功能
    assert set(body["by_feature"]) == {"31"}
    flag = body["by_feature"]["31"]
    assert flag["severity"] == "uncovered"
    assert flag["standard_check"]["severity"] == "uncovered"
    assert "标准表未收录" in flag["standard_check"]["message"]
    assert flag["config_check"]["severity"] == "unlinked"
    assert [check["label"] for check in flag["checks"]] == ["功能名称标准表", "配置管理描述"]

    # 提示同时按名称建立索引，前端在任何位置按名称显示都能命中
    assert body["by_name"]["vmindob"]["feature_id"] == 31


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
    assert "仅大小写、空格或符号不同" in flags.json()["by_feature"]["1"]["standard_check"]["message"]


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
    assert "人工确认" in flags.json()["by_feature"]["1"]["standard_check"]["message"]


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
async def test_optional_configuration_marker_is_not_a_name_difference(tmp_path):
    """白皮书用（可选）(选配) 标注选配状态，不属于名称差异。"""

    database_path = tmp_path / "knowledge.db"
    _create_knowledge_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        await client.post(
            "/api/features/standards/import",
            files=_upload(
                _standard_table_bytes(
                    [
                        ("组织多普勒成像（可选）", "Tissue Doppler Imaging", "TDI"),
                        ("超微细血流成像(选配)", "SMF", "SMF"),
                    ]
                )
            ),
        )
        audit = await client.get("/api/features/standards")
        flags = await client.get("/api/features/standards/flags")
    await engine.dispose()

    entries = {entry["cn_name"]: entry for entry in audit.json()["standards"]}
    assert entries["组织多普勒成像（可选）"]["severity"] == "ok"
    assert entries["组织多普勒成像（可选）"]["cn_field"]["status"] == "ok"
    assert "1" not in flags.json()["by_feature"]


@pytest.mark.asyncio
async def test_config_description_baseline_is_prompted_separately(tmp_path):
    """功能主名与配置管理中文/英文描述不一致时，与标准表基准分开提醒。"""

    database_path = tmp_path / "knowledge.db"
    _create_knowledge_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.execute(
        "INSERT INTO config_items (id, ipn, rd_name, zh_desc, en_desc) VALUES (500, '6009000', 'Legacy', '旧中文描述', 'Old English')"
    )
    connection.execute(
        "UPDATE feature_config_item_links SET config_item_id = 500 WHERE feature_id = 1 AND relation_type = 'primary'"
    )
    connection.commit()
    connection.close()
    client, engine = await _client_for(database_path)

    async with client:
        await client.post(
            "/api/features/standards/import",
            files=_upload(_standard_table_bytes([("组织多普勒成像", "Tissue Doppler Imaging", "TDI")])),
        )
        audit = await client.get("/api/features/standards")
        flags = await client.get("/api/features/standards/flags")
    await engine.dispose()

    body = audit.json()
    # 标准表基准一致，配置管理描述基准不一致 → 只提醒配置管理这一侧
    assert body["standards"][0]["severity"] == "ok"
    assert body["summary"]["config_differs"] == 1

    flag = flags.json()["by_feature"]["1"]
    assert flag["severity"] == "differs"
    assert flag["standard_check"] is None
    config_check = flag["config_check"]
    assert config_check["severity"] == "differs"
    assert config_check["ipn"] == "6009000"
    assert config_check["feature_relation"]["severity"] == "differs"
    # 配置描述与标准名称同样不一致
    assert config_check["standard_relation"]["severity"] == "differs"
    assert "旧中文描述" in config_check["feature_relation"]["message"]
    assert "Old English" in config_check["feature_relation"]["message"]


def _create_whitepaper(database_path, document_id, title, chunks):
    """建一份带正文片段的白皮书，用于名称核对测试。"""

    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        INSERT INTO knowledge_documents (id, document_type, title, file_name, file_path, version, market)
        VALUES (?, 'whitepaper', ?, ?, ?, '1.0', 'domestic')
        """,
        (document_id, title, f"{title}.pdf", f"/tmp/{document_id}.pdf"),
    )
    connection.executemany(
        """
        INSERT INTO knowledge_document_chunks (
            document_id, chunk_index, source_ref, content, normalized_content, content_hash
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (document_id, index, f"p{index + 1}", content, content, f"hash-{document_id}-{index}")
            for index, content in enumerate(chunks)
        ],
    )
    connection.commit()
    connection.close()


@pytest.mark.asyncio
async def test_whitepaper_names_are_checked_against_both_baselines(tmp_path):
    """白皮书正文里的写法（英文缩写+中文说法）分别与标准表和配置管理描述比对。"""

    database_path = tmp_path / "knowledge.db"
    _create_knowledge_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.execute(
        "INSERT INTO config_items (id, ipn, rd_name, zh_desc, en_desc) VALUES (500, '6009500', 'PView', '宽景成像', 'Pview')"
    )
    connection.execute(
        """
        INSERT INTO features (id, group_id, name, ipn, sort_order, primary_cn_name, primary_en_name, identity_status)
        VALUES (50, 1, '宽景成像', '6009500', 9, '宽景成像', 'Pview', 'confirmed')
        """
    )
    connection.executemany(
        """
        INSERT INTO feature_names (feature_id, language, name, normalized_name, name_type, source, review_status)
        VALUES (50, ?, ?, ?, 'primary', 'feature_management', 'approved')
        """,
        [("cn", "宽景成像", "宽景成像"), ("en", "Pview", "pview")],
    )
    connection.execute(
        """
        INSERT INTO feature_config_item_links (feature_id, config_item_id, relation_type, source, review_status)
        VALUES (50, 500, 'primary', 'feature_management', 'approved')
        """
    )
    connection.commit()
    connection.close()
    _create_whitepaper(
        database_path,
        900,
        "测试白皮书",
        [
            "5.9 PView 宽景扩展成像 用于扩大扫查范围",
            "5.10 PView 宽景成像 实时扫描速度提示",
            "5.11 SMF 超微细血流成像(选配) 支持微小血管显示",
        ],
    )
    client, engine = await _client_for(database_path)

    async with client:
        await client.post(
            "/api/features/standards/import",
            files=_upload(
                _standard_table_bytes(
                    [("宽景成像", "PView", "PView"), ("超微细血流成像", "SMF", "SMF")]
                )
            ),
        )
        overview = await client.get("/api/features/standards/whitepaper-names")
        detail = await client.get(
            "/api/features/standards/whitepaper-names", params={"document_id": 900}
        )
        matched = await client.get(
            "/api/features/standards/whitepaper-names",
            params={"document_id": 900, "include_matched": True},
        )
        documents = await client.get("/api/features/standards/whitepaper-documents")
    await engine.dispose()

    assert overview.status_code == 200
    assert overview.json()["documents"] == 1
    assert overview.json()["entries"] == []
    assert [item["document_title"] for item in overview.json()["document_summaries"]] == ["测试白皮书"]
    assert overview.json()["document_summaries"][0]["mismatched_features"] == 1

    assert detail.status_code == 200
    entries = {entry["feature_id"]: entry for entry in detail.json()["entries"]}
    assert set(entries) == {50}

    # 白皮书的中文说法「宽景扩展成像」与标准中文名称、配置管理中文描述都不同
    panoramic = entries[50]
    assert "宽景扩展成像" in panoramic["used_cn"]
    assert panoramic["standard"]["severity"] == "differs"
    assert "宽景扩展成像" in panoramic["standard"]["message"]
    assert panoramic["config"]["severity"] == "differs"
    assert "宽景扩展成像" in panoramic["config"]["message"]
    assert panoramic["snippets"]

    # 只有选配标记和括号说明的行不会成为差异项：SMF 两个基准都一致
    all_entries = {entry["feature_id"]: entry for entry in matched.json()["entries"]}
    smf = all_entries[7]
    assert smf["used_cn"] == ["超微细血流成像"]
    assert not any("选配" in name or "可选" in name for name in smf["used_names"])
    assert smf["severity"] == "ok"
    assert smf["standard"]["severity"] == "ok"
    assert smf["config"]["severity"] == "ok"

    assert documents.json()["items"][0]["title"] == "测试白皮书"
    assert documents.json()["items"][0]["chunks"] == 3


@pytest.mark.asyncio
async def test_whitepaper_scan_ignores_optional_marker_and_matches_spacing(tmp_path):
    """（选配）标记和「自由臂 3D」这类空格写法都不算名称差异。"""

    database_path = tmp_path / "knowledge.db"
    _create_knowledge_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        INSERT INTO features (id, group_id, name, ipn, sort_order, primary_cn_name, primary_en_name, identity_status)
        VALUES (40, 1, '自由臂3D', '', 9, '自由臂3D', 'Free 3D', 'confirmed')
        """
    )
    connection.executemany(
        """
        INSERT INTO feature_names (feature_id, language, name, normalized_name, name_type, source, review_status)
        VALUES (40, ?, ?, ?, 'primary', 'feature_management', 'approved')
        """,
        [("cn", "自由臂3D", "自由臂3d"), ("en", "Free 3D", "free3d")],
    )
    connection.commit()
    connection.close()
    _create_whitepaper(database_path, 901, "空格白皮书", ["5.12 自由臂 3D 使用 2D 探针重建", "整机选配清单"])
    client, engine = await _client_for(database_path)

    async with client:
        await client.post(
            "/api/features/standards/import",
            files=_upload(_standard_table_bytes([("自由臂3D", "Free 3D", "Free 3D")])),
        )
        detail = await client.get(
            "/api/features/standards/whitepaper-names", params={"document_id": 901}
        )
    await engine.dispose()

    body = detail.json()
    assert body["summary"]["entries"] == 0
    assert body["entries"] == []


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

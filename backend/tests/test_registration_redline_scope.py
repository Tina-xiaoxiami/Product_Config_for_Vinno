"""国内注册红线只反映本注册证当前有效版本（不跨注册证汇总）。

``registration_probes`` / ``registration_models`` 是按国家共享的主数据行，
同一个探头型号在不同注册证下的 IPN 并不相同。红线的探头与 IPN 必须取自
``registration_package_version_probes``（本证版本自带的值），一旦回落到国家
共享行，别的注册证（甚至只是一份未发布的草稿）就会改掉本证的结论。
"""

import sqlite3

import pytest
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.registration_migration import migrate_registration_schema
from app.services.registration_packages import publish_registration_package_version
from app.services.registration_query import list_product_registration_probes
from test_registration_import import _create_database
from test_registration_package_workflow import _stage


def _write_workbook_with_probe_ipn(path, *, f2_5c_ipn):
    """与共享夹具同形，但允许指定 F2-5C 的 IPN（模拟不同注册证的不同 IPN）。"""

    workbook = Workbook()
    matrix = workbook.active
    matrix.title = "0729"
    matrix["A2"] = "支持探头\n共3把"
    matrix["B2"] = "F2-5C，G1-4P，F4-9E"
    matrix.append(["序号", "型号", "不支持探头", "通道数"])
    matrix.append([1, "VINNO 10", "探头全适用", 128])
    matrix.append([2, "VINNO 10E", "F2-5C", 128])
    matrix.append([3, "VINNO 9", "F4-9E、G1-4P", 128])
    probes = workbook.create_sheet("Sheet1")
    probes.append([None, None, None])
    probes.append(["F2-5C", f2_5c_ipn, f2_5c_ipn])
    probes.append(["G1-4P", 1000744, 1000744])
    probes.append(["F4-9E", 1000784, 1000784])
    workbook.save(path)


async def _redline(database_path, product_model_id):
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        result = await list_product_registration_probes(
            session,
            product_model_id=product_model_id,
            query=None,
            registration_status=None,
            effective_status=None,
            skip=0,
            limit=200,
        )
    await engine.dispose()
    return result


def _probe(result, registration_number, probe_model):
    for registration in result["registrations"]:
        if registration["registration_number"] != registration_number:
            continue
        for item in registration["items"]:
            if item["probe_model"] == probe_model:
                return item
    return None


@pytest.mark.asyncio
async def test_unpublished_draft_of_another_certificate_cannot_change_a_published_redline(
    tmp_path,
):
    """B 证只暂存草稿（未发布）时，A 证已发布的红线不得改变。"""

    database_path = tmp_path / "product_config.db"
    workbook_a = tmp_path / "registration-a.xlsx"
    workbook_b = tmp_path / "registration-b.xlsx"
    certificate_a = tmp_path / "certificate-a.pdf"
    certificate_b = tmp_path / "certificate-b.pdf"
    _create_database(database_path)
    _write_workbook_with_probe_ipn(workbook_a, f2_5c_ipn=1000530)
    _write_workbook_with_probe_ipn(workbook_b, f2_5c_ipn=9999999)
    certificate_a.write_bytes(b"%PDF-1.4 certificate A")
    certificate_b.write_bytes(b"%PDF-1.4 certificate B")
    migrate_registration_schema(database_path)

    draft_a = _stage(
        database_path,
        workbook_a,
        certificate_a,
        unit_code="V10-A",
        registration_number="TEST-CN-001",
        mappings={1: "VINNO 10"},
    )
    publish_registration_package_version(
        database_path, version_id=draft_a["id"], confirmed_by="product_owner"
    )

    before = await _redline(database_path, 1)
    item_before = _probe(before, "TEST-CN-001", "F2-5C")
    assert item_before is not None
    assert item_before["ipn"] == "1000530"
    assert item_before["effective_status"] == "X"

    # 只登记 B 的草稿，不发布
    draft_b = _stage(
        database_path,
        workbook_b,
        certificate_b,
        unit_code="V10-B",
        registration_number="TEST-CN-002",
        mappings={1: "VINNO 10"},
    )
    assert draft_b["status"] == "draft"

    connection = sqlite3.connect(database_path)
    # 国家共享主数据确实被这份草稿改写了 —— 这正是旧实现会串数据的机制
    assert connection.execute(
        "SELECT ipn FROM registration_probes WHERE country_code = 'CN' "
        "AND normalized_model = 'f2-5c'"
    ).fetchone()[0] == "9999999"
    connection.close()

    after = await _redline(database_path, 1)
    item_after = _probe(after, "TEST-CN-001", "F2-5C")
    assert item_after is not None
    assert item_after["ipn"] == "1000530", "A 证的 IPN 不能被 B 证的草稿改写"
    assert item_after["effective_status"] == "X"
    # 未发布的 B 证不应出现在查询结果里
    assert [
        registration["registration_number"] for registration in after["registrations"]
    ] == ["TEST-CN-001"]


@pytest.mark.asyncio
async def test_each_published_certificate_reports_its_own_probe_ipn(tmp_path):
    """两个已发布注册证对同一探头型号各有 IPN 时，各自显示自己的值。"""

    database_path = tmp_path / "product_config.db"
    workbook_a = tmp_path / "registration-a.xlsx"
    workbook_b = tmp_path / "registration-b.xlsx"
    certificate_a = tmp_path / "certificate-a.pdf"
    certificate_b = tmp_path / "certificate-b.pdf"
    _create_database(database_path)
    _write_workbook_with_probe_ipn(workbook_a, f2_5c_ipn=1000530)
    _write_workbook_with_probe_ipn(workbook_b, f2_5c_ipn=9999999)
    certificate_a.write_bytes(b"%PDF-1.4 certificate A")
    certificate_b.write_bytes(b"%PDF-1.4 certificate B")
    migrate_registration_schema(database_path)

    for workbook, certificate, unit_code, number in (
        (workbook_a, certificate_a, "V10-A", "TEST-CN-001"),
        (workbook_b, certificate_b, "V10-B", "TEST-CN-002"),
    ):
        draft = _stage(
            database_path,
            workbook,
            certificate,
            unit_code=unit_code,
            registration_number=number,
            mappings={1: "VINNO 10"},
        )
        publish_registration_package_version(
            database_path, version_id=draft["id"], confirmed_by="product_owner"
        )

    result = await _redline(database_path, 1)
    assert result is not None
    item_a = _probe(result, "TEST-CN-001", "F2-5C")
    item_b = _probe(result, "TEST-CN-002", "F2-5C")
    assert item_a is not None and item_b is not None
    assert item_a["ipn"] == "1000530"
    assert item_a["effective_status"] == "X"
    # B 的 IPN 在配置管理里没有对应配置项，选型结论应为未定义
    assert item_b["ipn"] == "9999999"
    assert item_b["registration_status"] == "registered"
    assert item_b["effective_status"] == "未定义"
    assert item_b["config_item_id"] is None


@pytest.mark.asyncio
async def test_redline_does_not_list_probes_of_other_certificates(tmp_path):
    """本证没有声明的探头不能出现在本证红线里。"""

    database_path = tmp_path / "product_config.db"
    workbook_path = tmp_path / "registration.xlsx"
    certificate_path = tmp_path / "certificate.pdf"
    _create_database(database_path)
    _write_workbook_with_probe_ipn(workbook_path, f2_5c_ipn=1000530)
    certificate_path.write_bytes(b"%PDF-1.4 certificate")
    migrate_registration_schema(database_path)

    draft = _stage(
        database_path,
        workbook_path,
        certificate_path,
        unit_code="V10-A",
        registration_number="TEST-CN-001",
        mappings={1: "VINNO 10"},
    )
    publish_registration_package_version(
        database_path, version_id=draft["id"], confirmed_by="product_owner"
    )

    connection = sqlite3.connect(database_path)
    import_batch_id = connection.execute(
        "SELECT import_batch_id FROM registration_package_versions WHERE id = ?",
        (draft["id"],),
    ).fetchone()[0]
    # 同一国家、另一个注册证才有的探头
    connection.execute(
        """
        INSERT INTO registration_probes (
            country_code, probe_model, normalized_model, ipn,
            import_batch_id, source_ref, source_status
        ) VALUES ('CN', 'OTHER-PROBE', 'other-probe', 'OTHER-IPN', ?,
                  '另一注册证', 'active')
        """,
        (import_batch_id,),
    )
    connection.commit()
    connection.close()

    result = await _redline(database_path, 1)
    models = [item["probe_model"] for item in result["registrations"][0]["items"]]
    assert "OTHER-PROBE" not in models
    assert set(models) <= {"F2-5C", "G1-4P", "F4-9E"}

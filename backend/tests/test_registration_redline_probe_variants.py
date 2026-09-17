"""国内注册红线的结论按「探头型号 → 该型号的全部变体 IPN → 配置管理选型类别」算。

规则（业务方确认）：
1. 只看**启用**的注册证，停用的证只供历史查询；
2. 从启用的证拿到**探头型号**清单；
3. 取该探头型号在探头基础数据里的**全部变体 IPN**；
4. 逐个去配置管理查选型类别，**只要有一个是正式类别（X/O/Δ）就算支持**，并取该类别。

关键点：注册资料里的 IPN 不参与判断 —— 注册证只有"探头型号"的概念。
"""

import sqlite3

import pytest
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.registration_migration import migrate_registration_schema
from app.services.registration_packages import (
    publish_registration_package_version,
    set_registration_package_enabled,
    stage_registration_package_draft,
)
from app.services.registration_query import list_product_registration_probes
from test_registration_import import _create_database


def _write_workbook(path, *, f2_5c_ipn):
    """差异表：只声明探头型号与一个参考 IPN。"""

    workbook = Workbook()
    matrix = workbook.active
    matrix.title = "0729"
    matrix["A2"] = "支持探头\n共3把"
    matrix["B2"] = "F2-5C，G1-4P，F4-9E"
    matrix.append(["序号", "型号", "不支持探头", "通道数"])
    matrix.append([1, "VINNO 10", "探头全适用", 128])
    probes = workbook.create_sheet("Sheet1")
    probes.append([None, None, None])
    probes.append(["F2-5C", f2_5c_ipn, f2_5c_ipn])
    probes.append(["G1-4P", 1000744, 1000744])
    probes.append(["F4-9E", 1000784, 1000784])
    workbook.save(path)


def _stage(database_path, workbook_path, certificate_path, *, unit_code, number):
    return stage_registration_package_draft(
        database_path,
        country_code="CN",
        unit_code=unit_code,
        display_name=f"{unit_code} 国内注册",
        product_series=unit_code,
        registration_number=number,
        certificate_path=certificate_path,
        difference_path=workbook_path,
        certificate_version="20260902",
        difference_version="20260902",
        confirmed_by="product_owner",
        change_note="新增注册证",
        product_model_mappings={1: "VINNO 10"},
    )


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


def _probe(result, probe_model):
    assert result is not None
    for item in result["registrations"][0]["items"]:
        if item["probe_model"] == probe_model:
            return item
    raise AssertionError(f"结果里没有探头 {probe_model}")


def _publish_enabled(database_path, workbook, certificate, *, unit_code, number):
    draft = _stage(database_path, workbook, certificate, unit_code=unit_code, number=number)
    publish_registration_package_version(
        database_path, version_id=draft["id"], confirmed_by="product_owner"
    )
    return draft


@pytest.mark.asyncio
async def test_verdict_comes_from_probe_model_variants_not_the_certificate_ipn(tmp_path):
    """结论按探头型号的变体算；证里写的 IPN 与结论无关。

    证里给 F2-5C 写了一个配置管理里根本不存在的 IPN，而探头基础数据里该型号的
    变体是 1000530（配置管理里机型1 的选型类别是 X）。
    """

    database_path = tmp_path / "product_config.db"
    workbook = tmp_path / "cert.xlsx"
    certificate = tmp_path / "cert.pdf"
    _create_database(database_path)
    _write_workbook(workbook, f2_5c_ipn=9999999)  # 证里写一个配置管理没有的 IPN
    certificate.write_bytes(b"%PDF-1.4 certificate")
    migrate_registration_schema(database_path)
    _publish_enabled(
        database_path, workbook, certificate, unit_code="V10-A", number="TEST-CN-001"
    )

    probe = _probe(await _redline(database_path, 1), "F2-5C")
    assert probe["effective_status"] == "X", "结论要按探头型号的变体算，不能看证里的 IPN"
    assert probe["config_item_id"] is not None


@pytest.mark.asyncio
async def test_any_supported_variant_makes_the_probe_supported(tmp_path):
    """一个探头型号有多个变体时，只要有一个变体是正式类别就算支持。

    F2-5C 型号下挂两个变体：1000177（本机型 N/A）和 1000530（本机型 X）
    —— 真实数据里就是这种形态（F2-5C【停用】 + F2-5CP【启用】）。
    """

    database_path = tmp_path / "product_config.db"
    workbook = tmp_path / "cert.xlsx"
    certificate = tmp_path / "cert.pdf"
    _create_database(database_path)
    connection = sqlite3.connect(database_path)
    # 给 F2-5C 型号再挂一个变体，其在机型1 的选型类别是 N/A（即不构成支持）
    connection.execute(
        "INSERT INTO config_items (id, ipn, category, zh_desc) VALUES (13, '1000177', 'Probes', 'F2-5C探头')"
    )
    connection.execute(
        "INSERT INTO config_values (id, item_id, model_id, selection_config, current_config) "
        "VALUES (9, 13, 1, 'N/A', 'X')"
    )
    connection.execute(
        "INSERT INTO probe_model_variants (id, probe_model_id, internal_model, ipn) "
        "VALUES (34, 21, 'F2-5C-Old', '1000177')"
    )
    connection.commit()
    connection.close()
    _write_workbook(workbook, f2_5c_ipn=1000177)
    certificate.write_bytes(b"%PDF-1.4 certificate")
    migrate_registration_schema(database_path)
    _publish_enabled(
        database_path, workbook, certificate, unit_code="V10-A", number="TEST-CN-001"
    )

    probe = _probe(await _redline(database_path, 1), "F2-5C")
    assert probe["effective_status"] == "X", "另一个变体（1000530）支持，就应判定支持"
    connection = sqlite3.connect(database_path)
    item = connection.execute(
        "SELECT ipn FROM config_items WHERE id = ?", (probe["config_item_id"],)
    ).fetchone()[0]
    connection.close()
    assert item == "1000530", "支持结论应来自那个正式类别的变体"


@pytest.mark.asyncio
async def test_disabled_certificate_is_excluded_and_verdict_still_follows_the_master(tmp_path):
    """停用的证只供历史查询：不出现在当前结果里；结论仍按探头基础数据算。"""

    database_path = tmp_path / "product_config.db"
    workbook_1 = tmp_path / "cert-1.xlsx"
    workbook_2 = tmp_path / "cert-2.xlsx"
    certificate_1 = tmp_path / "cert-1.pdf"
    certificate_2 = tmp_path / "cert-2.pdf"
    _create_database(database_path)
    connection = sqlite3.connect(database_path)
    # 夹具里 G1-4P 的变体是 1000744（配置项 11），但没有机型1 的选型类别；
    # 补一行 X，用它验证"结论来自探头基础数据"。
    connection.execute(
        "INSERT INTO config_values (id, item_id, model_id, selection_config, current_config) "
        "VALUES (10, 11, 1, 'X', 'X')"
    )
    connection.commit()
    connection.close()
    _write_workbook(workbook_1, f2_5c_ipn=1000530)
    _write_workbook(workbook_2, f2_5c_ipn=1000530)
    certificate_1.write_bytes(b"%PDF-1.4 certificate 1")
    certificate_2.write_bytes(b"%PDF-1.4 certificate 2")
    migrate_registration_schema(database_path)

    _publish_enabled(
        database_path, workbook_1, certificate_1, unit_code="V10-A", number="TEST-CN-001"
    )
    draft_2 = _publish_enabled(
        database_path, workbook_2, certificate_2, unit_code="V10-B", number="TEST-CN-002"
    )
    set_registration_package_enabled(
        database_path, package_id=draft_2["package_id"], is_enabled=False,
        updated_by="product_owner",
    )

    result = await _redline(database_path, 1)
    assert [r["registration_number"] for r in result["registrations"]] == ["TEST-CN-001"]
    probe = _probe(result, "G1-4P")
    assert probe["effective_status"] == "X"
    assert probe["ipn"] == "1000744"

"""国内注册红线：证上的探头型号按「配置管理里的英文描述」找到候选 IPN。

业务方确认的规则：
1. 只看**启用**的注册证，停用的证只供历史查询；
2. 从启用的证拿到**探头型号**；
3. 用该型号去**配置管理**里按**英文描述**找出全部候选 IPN
   （探头管理里不一定建过这个型号，所以不能拿它当匹配键）；
4. 逐个候选人查该机型的选型类别，**只要有一个是正式类别（X/O/Δ）就算支持**，并取该类别。

注册资料里的 IPN 不参与判定 —— 注册证只有"探头型号"的概念。
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


def _write_workbook(path, probes):
    """probes: [(探头型号, 参考IPN)]，矩阵页与探头页必须一致。"""

    workbook = Workbook()
    matrix = workbook.active
    matrix.title = "0729"
    matrix["A2"] = f"支持探头\n共{len(probes)}把"
    matrix["B2"] = "，".join(name for name, _ in probes)
    matrix.append(["序号", "型号", "不支持探头", "通道数"])
    matrix.append([1, "VINNO 10", "探头全适用", 128])
    sheet = workbook.create_sheet("Sheet1")
    sheet.append([None, None, None])
    for name, ipn in probes:
        sheet.append([name, ipn, ipn])
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


async def _redline(database_path, product_model_id=1):
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


def _publish(database_path, workbook, certificate, *, unit_code, number):
    draft = _stage(database_path, workbook, certificate, unit_code=unit_code, number=number)
    publish_registration_package_version(
        database_path, version_id=draft["id"], confirmed_by="product_owner"
    )
    return draft


@pytest.mark.asyncio
async def test_candidates_come_from_the_english_description_not_the_probe_master(tmp_path):
    """探头管理里没建过这个型号，但配置管理里按英文描述能找到 → 仍要判出类别。

    真实例子：F4-9E 在探头管理里没有型号，但配置管理里有三行英文描述是 F4-9E，
    其中 IPN 1000784（F4-9EV【启用】）在湘证的机型上是选型类别 X。
    """

    database_path = tmp_path / "product_config.db"
    workbook = tmp_path / "cert.xlsx"
    certificate = tmp_path / "cert.pdf"
    _create_database(database_path)
    connection = sqlite3.connect(database_path)
    # 配置管理里新增一行：英文描述就是"探头型号"，而探头管理里没有建过这个型号
    connection.execute(
        "INSERT INTO config_items (id, ipn, category, zh_desc, en_desc) "
        "VALUES (20, '1009999', 'Probes', 'NEW-9X探头', 'NEW-9X')"
    )
    connection.execute(
        "INSERT INTO config_values (id, item_id, model_id, selection_config, current_config) "
        "VALUES (20, 20, 1, 'X', 'X')"
    )
    connection.commit()
    connection.close()
    _write_workbook(workbook, [("NEW-9X", 1009999)])  # 探头管理里没有 NEW-9X 型号
    certificate.write_bytes(b"%PDF-1.4 certificate")
    migrate_registration_schema(database_path)
    _publish(database_path, workbook, certificate, unit_code="V10-A", number="TEST-CN-001")

    probe = _probe(await _redline(database_path), "NEW-9X")
    assert probe["effective_status"] == "X", "候选 IPN 要按配置管理的英文描述找"
    assert probe["ipn"] == "1009999"


@pytest.mark.asyncio
async def test_any_supported_candidate_makes_the_probe_supported(tmp_path):
    """同一探头型号有多个候选 IPN 时，只要有一个是正式类别就算支持。"""

    database_path = tmp_path / "product_config.db"
    workbook = tmp_path / "cert.xlsx"
    certificate = tmp_path / "cert.pdf"
    _create_database(database_path)
    connection = sqlite3.connect(database_path)
    # 夹具里 1000530 在机型1 是 X；再补一个同型号但 N/A 的候选（不构成支持）
    connection.execute(
        "INSERT INTO config_items (id, ipn, category, zh_desc, en_desc) "
        "VALUES (20, '1000177', 'Probes', 'F2-5C探头', 'F2-5C')"
    )
    connection.execute(
        "INSERT INTO config_values (id, item_id, model_id, selection_config, current_config) "
        "VALUES (20, 20, 1, 'N/A', 'X')"
    )
    connection.commit()
    connection.close()
    _write_workbook(workbook, [("F2-5C", 1000177)])
    certificate.write_bytes(b"%PDF-1.4 certificate")
    migrate_registration_schema(database_path)
    _publish(database_path, workbook, certificate, unit_code="V10-A", number="TEST-CN-001")

    probe = _probe(await _redline(database_path), "F2-5C")
    assert probe["effective_status"] == "X"
    assert probe["ipn"] == "1000530", "结论应来自那个正式类别的候选"


@pytest.mark.asyncio
async def test_description_with_a_trailing_parenthesis_still_matches(tmp_path):
    """英文描述带括号补充（如 X4-9E(Straight handle)）时仍要匹配到该型号。"""

    database_path = tmp_path / "product_config.db"
    workbook = tmp_path / "cert.xlsx"
    certificate = tmp_path / "cert.pdf"
    _create_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.execute(
        "INSERT INTO config_items (id, ipn, category, zh_desc, en_desc) "
        "VALUES (20, '1001388', 'Probes', 'X4-9E探头', 'X4-9E(Straight handle)')"
    )
    connection.execute(
        "INSERT INTO config_values (id, item_id, model_id, selection_config, current_config) "
        "VALUES (20, 20, 1, 'X', 'X')"
    )
    connection.commit()
    connection.close()
    _write_workbook(workbook, [("X4-9E", 1001388)])
    certificate.write_bytes(b"%PDF-1.4 certificate")
    migrate_registration_schema(database_path)
    _publish(database_path, workbook, certificate, unit_code="V10-A", number="TEST-CN-001")

    probe = _probe(await _redline(database_path), "X4-9E")
    assert probe["effective_status"] == "X"
    assert probe["ipn"] == "1001388"


@pytest.mark.asyncio
async def test_candidates_without_a_formal_category_keep_the_auxiliary_note(tmp_path):
    """没有正式类别时仍要把配置项名称与研发当前配置备注带出来（备注不参与判定）。"""

    database_path = tmp_path / "product_config.db"
    workbook = tmp_path / "cert.xlsx"
    certificate = tmp_path / "cert.pdf"
    _create_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.execute(
        "INSERT INTO config_values (id, item_id, model_id, selection_config, current_config) "
        "VALUES (20, 11, 1, 'N/A', 'Δ')"
    )
    connection.commit()
    connection.close()
    _write_workbook(workbook, [("G1-4P", 1000300)])
    certificate.write_bytes(b"%PDF-1.4 certificate")
    migrate_registration_schema(database_path)
    _publish(database_path, workbook, certificate, unit_code="V10-A", number="TEST-CN-001")

    probe = _probe(await _redline(database_path), "G1-4P")
    assert probe["effective_status"] == "未定义"
    assert probe["current_config"] == "Δ"
    assert probe["current_config_note"] == "研发当前配置为 Δ，仅作备注，不参与判定"
    assert probe["config_name"] == "G1-4P探头"

"""停用的注册证不能改写当前注册红线的结论。

同一个国家的两张注册证可以覆盖同一批机型，但只有一张是启用的。国家级的
``registration_probes`` 是全国共用的一行，谁最后上传资料就写成谁的值 —— 包括
已停用的证。红线的结论按「探头型号 → 配置管理的英文描述 → 候选 IPN 的选型类别」
算，不依赖注册资料里的 IPN，也不依赖那张共享行，因此停用证的数据改不动它。
（`test_registration_redline_probe_match.py` 覆盖匹配口径本身。）

同时保留原有设计：探头清单仍然列该国家的全部探头，本证之外的显示为未注册
（见 6ba0a54 fix: report probes outside a certificate as unregistered）。
"""

import hashlib
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


def _write_workbook(path, *, f2_5c_ipn, extra_probe=None):
    """差异表：探头页与矩阵页同形，F2-5C 的 IPN 可指定。"""

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
    if extra_probe:
        probes.append([extra_probe, 424242, 424242])
        matrix["B2"] = f"F2-5C，G1-4P，F4-9E，{extra_probe}"
    workbook.save(path)


def _stage(database_path, workbook_path, certificate_path, *, unit_code, number, mapping):
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
        product_model_mappings=mapping,
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


def _probes(result):
    """本机型对应的那个注册证的探头字典：{探头型号: item}"""

    assert result is not None
    return {item["probe_model"]: item for item in result["registrations"][0]["items"]}


@pytest.mark.asyncio
async def test_redline_uses_the_enabled_certificate_not_a_disabled_one(tmp_path):
    """证1（启用）与证2（停用）覆盖同一机型时，结论必须按证1算。"""

    database_path = tmp_path / "product_config.db"
    workbook_1 = tmp_path / "cert-1.xlsx"
    workbook_2 = tmp_path / "cert-2.xlsx"
    certificate_1 = tmp_path / "cert-1.pdf"
    certificate_2 = tmp_path / "cert-2.pdf"
    _create_database(database_path)
    # 证1：F2-5C = 1000530（配置管理里有这条，机型1 的选型类别是 X）
    _write_workbook(workbook_1, f2_5c_ipn=1000530)
    # 证2：同一个探头型号，IPN 不同（配置管理里没有这条）
    _write_workbook(workbook_2, f2_5c_ipn=9999999)
    certificate_1.write_bytes(b"%PDF-1.4 certificate 1")
    certificate_2.write_bytes(b"%PDF-1.4 certificate 2")
    migrate_registration_schema(database_path)

    draft_1 = _stage(
        database_path, workbook_1, certificate_1,
        unit_code="V10-A", number="TEST-CN-001", mapping={1: "VINNO 10"},
    )
    publish_registration_package_version(
        database_path, version_id=draft_1["id"], confirmed_by="product_owner"
    )
    # 证1 之后才上传证2：国家级共享行的值会被证2 覆盖
    draft_2 = _stage(
        database_path, workbook_2, certificate_2,
        unit_code="V10-B", number="TEST-CN-002", mapping={1: "VINNO 10"},
    )
    publish_registration_package_version(
        database_path, version_id=draft_2["id"], confirmed_by="product_owner"
    )
    set_registration_package_enabled(
        database_path, package_id=draft_2["package_id"], is_enabled=False,
        updated_by="product_owner",
    )

    connection = sqlite3.connect(database_path)
    # 前提确认：国家级共享行确实被停用证（证2）改写了，测试才有意义
    assert connection.execute(
        "SELECT ipn FROM registration_probes WHERE country_code = 'CN' "
        "AND normalized_model = 'f2-5c'"
    ).fetchone()[0] == "9999999"
    connection.close()

    probes = _probes(await _redline(database_path, 1))
    assert probes["F2-5C"]["ipn"] == "1000530", "不能被停用证2改写共享行而改变结论"
    assert probes["F2-5C"]["effective_status"] == "X"
    assert probes["F2-5C"]["config_item_id"] is not None


@pytest.mark.asyncio
async def test_redline_still_lists_probes_outside_the_certificate_as_unregistered(tmp_path):
    """保留原设计：本证没有声明的探头仍然列出，并标为未注册。"""

    database_path = tmp_path / "product_config.db"
    workbook_1 = tmp_path / "cert-1.xlsx"
    workbook_2 = tmp_path / "cert-2.xlsx"
    certificate_1 = tmp_path / "cert-1.pdf"
    certificate_2 = tmp_path / "cert-2.pdf"
    _create_database(database_path)
    _write_workbook(workbook_1, f2_5c_ipn=1000530)
    # 证2 多一个探头顶级型号 OTHER-PROBE，只有它声明
    _write_workbook(workbook_2, f2_5c_ipn=9999999, extra_probe="OTHER-PROBE")
    certificate_1.write_bytes(b"%PDF-1.4 certificate 1")
    certificate_2.write_bytes(b"%PDF-1.4 certificate 2")
    migrate_registration_schema(database_path)

    draft_1 = _stage(
        database_path, workbook_1, certificate_1,
        unit_code="V10-A", number="TEST-CN-001", mapping={1: "VINNO 10"},
    )
    publish_registration_package_version(
        database_path, version_id=draft_1["id"], confirmed_by="product_owner"
    )
    draft_2 = _stage(
        database_path, workbook_2, certificate_2,
        unit_code="V10-B", number="TEST-CN-002", mapping={1: "VINNO 10"},
    )
    publish_registration_package_version(
        database_path, version_id=draft_2["id"], confirmed_by="product_owner"
    )
    set_registration_package_enabled(
        database_path, package_id=draft_2["package_id"], is_enabled=False,
        updated_by="product_owner",
    )

    probes = _probes(await _redline(database_path, 1))
    # 证2 独有的探头顶级型号仍要列出来（国家级清单），但结论是未注册
    assert "OTHER-PROBE" in probes
    assert probes["OTHER-PROBE"]["registration_status"] == "unregistered"
    assert probes["OTHER-PROBE"]["effective_status"] == "#"
    # 证1 自己声明的探头取证1 的值
    assert probes["G1-4P"]["ipn"] == "1000744"
    assert probes["F4-9E"]["ipn"] == "1000784"

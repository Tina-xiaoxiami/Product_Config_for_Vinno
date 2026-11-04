"""Probe exclusions retain evidence and resolve only against the category catalog."""
import io
import json

from fastapi import HTTPException, UploadFile
from openpyxl import Workbook
import pytest
from sqlalchemy import func, select

from app.api.probe_import import fill_template_excludes, import_template
from app.models.probe import (
    Application, CategoryApplication, Feature, FeatureGroup, ProbeCategory,
    ProbeModel, TemplateFeature,
)
from test_draft_safety import _draft_harness


@pytest.mark.parametrize("name, applications, expected", [
    (r"早\中\晚孕", ["早孕", "中孕", "晚孕"], ["早孕", "中孕", "晚孕"]),
    (r"早\中晚孕", ["早孕", "中晚孕"], ["早孕", "中晚孕"]),
    ("上/下肢静脉", ["上肢静脉", "下肢静脉"], ["上肢静脉", "下肢静脉"]),
    (r"早\中晚孕", ["子宫", "直肠", "前列腺"], [r"早\中晚孕"]),
    (r"早\中晚孕", ["早孕", "早晚孕", "中晚孕"], [r"早\中晚孕"]),
    ("中晚孕", ["早孕", "中孕", "晚孕", "中晚孕"], ["中晚孕"]),
    ("早中晚孕", ["早孕", "中孕", "晚孕"], ["早中晚孕"]),
])
def test_abbreviations_require_a_unique_complete_catalog_match(name, applications, expected):
    from app.services.probe_exclusion_rules import expand_exclusion_name
    assert expand_exclusion_name(name, applications) == expected


def test_parser_retains_inner_parentheses_and_splits_only_outer_separators():
    from app.services.probe_exclusion_rules import parse_exclusions
    applications = ["FAST", "心包积液(穿刺)", "早孕", "中晚孕"]
    assert parse_exclusions(r"√(除FAST,心包积液(穿刺)、早\中晚孕)", applications) == applications
    assert parse_exclusions("√（除FAST，心包积液(穿刺)）", applications) == applications[:2]
    assert parse_exclusions("√(除心包积液(穿刺,引流),FAST)", ["心包积液(穿刺,引流)", "FAST"]) == ["心包积液(穿刺,引流)", "FAST"]
    assert parse_exclusions("√", applications) is None
    assert parse_exclusions("-", applications) is None


@pytest.mark.parametrize("text", ["√(除FAST", "√除FAST)", "√(除FAST))", "√（除FAST)", "√(除)"])
def test_damaged_exclusion_parentheses_never_become_unrestricted(text):
    from app.services.probe_exclusion_rules import parse_exclusions
    with pytest.raises(ValueError):
        parse_exclusions(text, ["FAST"])


def workbook(*, malformed=False, nested=False):
    book = Workbook()
    sheet = book.active
    sheet.title = "正式模板"
    sheet.merge_cells("E1:O1")
    sheet["E1"] = "成像"
    sheet["E2"] = "常规造影"
    sheet["O2"] = "VFlow"
    sheet["A8"] = "双平面"
    sheet["B8"] = "DP1"
    sheet["C8"] = "FAST,心包积液(穿刺)" if nested else "子宫,直肠,前列腺"
    sheet["D8"] = "同常规"
    sheet["E8"] = "√"
    sheet["O8"] = "√(除FAST,心包积液(穿刺))" if nested else r"√(除早\中晚孕)"
    if malformed:
        sheet["A9"] = "新类别"
        sheet["B9"] = "NEW1"
        sheet["C9"] = "FAST"
        sheet["O9"] = "√(除FAST"
    stream = io.BytesIO()
    book.save(stream)
    stream.seek(0)
    return UploadFile(filename="probe.xlsx", file=stream)


@pytest.mark.asyncio
async def test_import_preserves_conflicting_source_restriction_and_reports_full_context(tmp_path):
    client, sessions, engine = await _draft_harness(tmp_path)
    try:
        async with sessions() as db:
            result = await import_template(workbook(), db)
            config = await db.scalar(select(TemplateFeature).join(Feature).where(Feature.name == "VFlow"))
            assert json.loads(config.default_excludes) == [r"早\中晚孕"]
            assert result["unresolved_exclusions"] == [{
                "category": "双平面", "feature": "VFlow", "worksheet": "正式模板", "cell": "O8",
                "raw_text": r"√(除早\中晚孕)", "application_names": ["前列腺", "子宫", "直肠"],
                "unresolved_names": [r"早\中晚孕"],
                "reason": "限制名称无法唯一匹配该类别的已确认应用，已保留完整原文；请核对原件与类别应用范围",
            }]
            assert set((await db.scalars(select(Application.name))).all()) == {"子宫", "直肠", "前列腺"}
            assert await db.scalar(select(func.count()).select_from(CategoryApplication)) == 6
    finally:
        await client.aclose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_import_keeps_nested_exclusion_names_whole(tmp_path):
    client, sessions, engine = await _draft_harness(tmp_path)
    try:
        async with sessions() as db:
            result = await import_template(workbook(nested=True), db)
            config = await db.scalar(select(TemplateFeature).join(Feature).where(Feature.name == "VFlow"))
            assert json.loads(config.default_excludes) == ["FAST", "心包积液(穿刺)"]
            assert result["unresolved_exclusions"] == []
    finally:
        await client.aclose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_bad_cell_returns_422_with_source_and_rolls_back_whole_import(tmp_path):
    client, sessions, engine = await _draft_harness(tmp_path)
    try:
        async with sessions() as db:
            with pytest.raises(HTTPException) as error:
                await import_template(workbook(malformed=True), db)
            assert error.value.status_code == 422
            assert "正式模板!O9" in str(error.value.detail)
            for model in [FeatureGroup, Feature, ProbeCategory, ProbeModel, Application, CategoryApplication, TemplateFeature]:
                assert await db.scalar(select(func.count()).select_from(model)) == 0
    finally:
        await client.aclose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_bad_later_cell_restores_preexisting_template_values(tmp_path):
    client, sessions, engine = await _draft_harness(tmp_path)
    try:
        async with sessions() as db:
            await import_template(workbook(nested=True), db)
            before = (await db.execute(select(TemplateFeature.id, TemplateFeature.default_support, TemplateFeature.default_excludes))).all()
            with pytest.raises(HTTPException):
                await import_template(workbook(malformed=True), db)
            after = (await db.execute(select(TemplateFeature.id, TemplateFeature.default_support, TemplateFeature.default_excludes))).all()
            assert after == before
            assert await db.scalar(select(func.count()).select_from(ProbeCategory)) == 1
    finally:
        await client.aclose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_fill_reads_dictionary_exclusions_preserves_tender_and_uses_source_catalog(tmp_path):
    client, sessions, engine = await _draft_harness(tmp_path)
    try:
        async with sessions() as db:
            db.add_all([
                FeatureGroup(id=1, name="成像"), Feature(id=1, name="VFlow", group_id=1),
                ProbeCategory(id=1, name="源类别"), ProbeCategory(id=2, name="目标类别"),
                ProbeCategory(id=3, name="不匹配类别"),
                ProbeCategory(id=4, name="明确清空类别"),
                Application(id=1, name="早孕"), Application(id=2, name="中晚孕"),
                Application(id=3, name="excludes"), Application(id=4, name="tender"),
            ])
            await db.flush()
            db.add_all([
                CategoryApplication(category_id=category_id, application_id=application_id)
                for category_id, application_id in [(1, 1), (1, 2), (2, 1), (2, 2), (3, 3), (3, 4), (4, 1), (4, 2)]
            ])
            db.add_all([
                TemplateFeature(category_id=1, feature_id=1, default_support="conditional", default_excludes=json.dumps({"excludes": [r"早\中晚孕"], "tender": ["特殊应用"]})),
                TemplateFeature(category_id=2, feature_id=1, default_support="supported"),
                TemplateFeature(category_id=3, feature_id=1, default_support="supported"),
                TemplateFeature(category_id=4, feature_id=1, default_support="supported", default_excludes=json.dumps({"excludes": [], "tender": ["保留招标"]})),
            ])
            await db.commit()
            await fill_template_excludes(db)
            rows = {row.category_id: row for row in (await db.scalars(select(TemplateFeature))).all()}
            assert json.loads(rows[1].default_excludes)["tender"] == ["特殊应用"]
            assert json.loads(rows[2].default_excludes) == ["中晚孕", "早孕"]
            assert rows[3].default_excludes is None
            assert json.loads(rows[4].default_excludes) == {"excludes": [], "tender": ["保留招标"]}
    finally:
        await client.aclose()
        await engine.dispose()

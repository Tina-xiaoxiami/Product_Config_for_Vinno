"""Joint regression for one shared mapping, computed answers and two Cart markets."""

from hashlib import sha256
from io import BytesIO
import json
from zipfile import ZipFile

from openpyxl import Workbook
import pytest

from app.api import knowledge
from app.models import ConfigVersion, KnowledgeDocument, ProductModel, ProductSeries
from app.models.knowledge import KnowledgeConfigurationAnswerRevision
from app.services.knowledge_cart_facts import apply_cart_facts
from app.services.knowledge_configuration_answers import configuration_answer_history
from app.services.knowledge_runtime import BATTERY_TEST
from test_versions_api import _versions_harness


@pytest.mark.asyncio
async def test_one_shared_mapping_resolves_answer_and_both_cart_candidates(tmp_path, monkeypatch):
    fact_key = "component.battery:70001"
    root_key = "battery.example.identity"
    issue = {"root_key": root_key, "detail": "缺少部件身份映射", "kind": "owner_decision"}
    source = tmp_path / f"{BATTERY_TEST}.xlsx"
    workbook = Workbook()
    workbook.active.title = "实测"
    workbook.active.append(["机型", "模式", "探头", "电池", "放电时长", "功耗"])
    workbook.active.append(["V10", "B", "Example probe", "V8BAT", "45分钟", "40W"])
    workbook.save(source)

    template = BytesIO()
    with ZipFile(template, "w") as archive:
        archive.writestr("ppt/slides/slide7.xml", """<p:sld
          xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
          xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
          <p:sp><p:nvSpPr><p:cNvPr id="4"/></p:nvSpPr><p:txBody>
          <a:p><a:r><a:t>Confirm configured battery identity.</a:t></a:r></a:p>
          </p:txBody></p:sp></p:sld>""")
    client, sessions, engine = await _versions_harness(tmp_path)
    client._transport.app.include_router(knowledge.router, prefix="/api/knowledge")
    templates, markets = {}, ("domestic", "overseas")
    try:
        async with client:
            async with sessions() as db:
                for sid, market in enumerate(markets, 1):
                    name = f"Example-{'China' if sid == 1 else 'Oversea'}"
                    data = json.dumps({"models": [{"id": sid, "name": "VINNO 10"}], "items": [{
                        "ipn": "70001", "en_desc": "Example battery", "values": {str(sid): {"selection_config": "O"}},
                    }]})
                    db.add_all([
                        ProductSeries(id=sid, name=name), ProductModel(id=sid, series_id=sid, name="VINNO 10"),
                        ConfigVersion(id=sid, series_id=sid, version_number="1.0.0", snapshot_data=data),
                    ])
                    folder = tmp_path / ("国内" if sid == 1 else "海外")
                    folder.mkdir()
                    (folder / "example.pptx").write_bytes(template.getvalue())
                    templates[market] = {
                        "filename": "example.pptx", "sha256": sha256(template.getvalue()).hexdigest(),
                        "anchors": [{"series": name, "version": "1.0.0", "sha256": sha256(data.encode()).hexdigest()}],
                        "facts": [{"facts": {"battery": fact_key}, "original": "Confirm configured battery identity.",
                                   "replacement": "Battery {battery}.", "targets": [[7, "4"]]}],
                    }
                db.add(KnowledgeDocument(id=1, document_type="measurement", title="Example test",
                                         file_name=source.name, file_path=str(source), market="unspecified",
                                         sha256=sha256(source.read_bytes()).hexdigest()))
                await db.commit()
            manifest = tmp_path / "rules.json"
            manifest.write_text(json.dumps({"version": "example", "templates": templates}))
            monkeypatch.setenv("CART_RELEASE_RULES_FILE", str(manifest))
            monkeypatch.setenv("CART_RELEASE_TEMPLATE_ROOT", str(tmp_path))
            async with sessions() as db:
                missing = [{"key": fact_key, "market": market, "status": "missing", "issue": issue} for market in markets]
                outcome = await apply_cart_facts(db, missing)
                assert [item["status"] for item in outcome["cart_impacts"]] == ["pending", "pending"]
                db.add(KnowledgeConfigurationAnswerRevision(
                    recipe="runtime:v10", model_id=1, config_version_id=1,
                    payload_json=json.dumps({"recipe": "runtime:v10",
                                             "model": {"id": 1, "name": "VINNO 10", "market": "domestic"},
                                             "snapshot": {"id": 1}, "review_items": [issue]}),
                ))
                await db.commit()
            path = "/api/knowledge/questions/configuration-issues"
            merged = (await client.get(path)).json()["items"]
            assert len(merged) == 1 and merged[0]["root_key"] == root_key
            assert {impact["market"] for impact in merged[0]["cart_impacts"]} == set(markets)
            assert [impact["model_id"] for impact in merged[0]["answer_impacts"]] == [1]

            async with sessions() as db:
                confirmed = [{
                    "key": fact_key, "market": market, "status": "confirmed", "value": "V8BAT",
                    "sources": [{"file_name": "Parts.xlsx", "version_id": "a" * 64, "locator": "Parts!A1:C1"}],
                } for market in markets]
                outcome = await apply_cart_facts(db, confirmed)
                assert [item["status"] for item in outcome["cart_impacts"]] == ["generated", "generated"]
                assert all(item["affected_pages"] == [7] for item in outcome["cart_impacts"])
                history = await configuration_answer_history(db, "runtime:v10", 1)
                assert history[0]["rows"][0]["duration"] == "45分钟"
                assert await apply_cart_facts(db, confirmed) == {"changed_fact_keys": [], "cart_impacts": []}
                await db.commit()
            assert (await client.get(path)).json()["items"] == []
    finally:
        await engine.dispose()

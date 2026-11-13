import json
import sqlite3
from hashlib import sha256

import pytest
from openpyxl import Workbook
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeConfigurationAnswerRevision, KnowledgePublicFact
from app.services.config_publication import commit_configuration_publication
from app.services.knowledge_runtime import BATTERY_TEST
from test_knowledge_qa_api import _client_for, _create_qa_database


def _snapshot(*batteries):
    return json.dumps({"models": [{"id": 901, "name": "VINNO 10"}],
                       "items": [{"ipn": ipn, "zh_desc": name,
                                  "values": {"901": {"selection_config": selection}}}
                                 for ipn, name, selection in batteries]})


@pytest.mark.asyncio
async def test_runtime_tracks_config_publish_and_retains_previous_measurements(tmp_path):
    source = tmp_path / f"{BATTERY_TEST}.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "实测"
    sheet.append(["机型", "模式", "探头", "电池", "放电时长", "功耗"])
    sheet.append(["V10", "B", "S1-6PV", "V9BAT", "52分钟", "75W"])
    sheet.append([None, "B", "S1-6PV", "V9BAT", "60分钟", None])
    sheet.merge_cells("A2:A3")
    sheet.row_dimensions[3].hidden = True
    sheet.append(["V6", "B", "X4-12L", "V8BAT", "100分钟", None])
    workbook.save(source)
    path = tmp_path / "runtime.db"
    _create_qa_database(path)
    client, engine = await _client_for(path)
    try:
        with sqlite3.connect(path) as db:
            for column in ("is_enabled INTEGER NOT NULL DEFAULT 1", "description TEXT", "status TEXT",
                           "column_start INTEGER", "column_end INTEGER", "sort_order INTEGER", "config_group TEXT",
                           "created_at TEXT", "updated_at TEXT"):
                db.execute(f"ALTER TABLE product_models ADD COLUMN {column}")
            db.execute("CREATE TABLE config_versions(id INTEGER PRIMARY KEY, series_id INTEGER,version_number TEXT,snapshot_data TEXT)")
            db.execute("INSERT INTO config_versions VALUES (1,901,'1.14.80',?)", (_snapshot(
                ("1001036", "V9BAT", "X"), ("2000000", "V8BAT", "O"),
            ),))
            db.execute("UPDATE knowledge_documents SET file_name=?,file_path=?,sha256=?,mime_type=NULL WHERE id=1",
                       (source.name, str(source), sha256(source.read_bytes()).hexdigest()))
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: KnowledgeConfigurationAnswerRevision.__table__.create(sync))
        async with client:
            payload = {"question": "V10 的续航是多少？", "scope": {"market": "domestic"}}
            response = await client.post("/api/knowledge/questions/ask", json=payload)
            assert response.status_code == 200, response.text
            outcome = response.json()
            assert outcome["status"] == "configuration" and outcome["question_id"] is None
            result, = outcome["configuration_answers"]
            assert result["snapshot"]["version_number"] == "1.14.80"
            assert [(r.get("duration"), r.get("hidden"), r["condition"]) for r in result["rows"]] == [
                ("52分钟", False, "标配"), ("60分钟", True, "标配"), (None, None, "选配"),
            ]
            assert result["rows"][0]["row_number"] == 2 and "75W" in result["rows"][0]["conditions"]
            assert result["rows"][-1]["missing"]
            async with AsyncSession(engine) as db:
                await db.execute(text("INSERT INTO config_versions VALUES (2,901,'1.14.81',:data)"), {
                    "data": _snapshot(("1000349", "独立包装电池", "O"), ("1001036", "V9BAT", "")),
                })
                await commit_configuration_publication(db, {901})
            history = await client.get("/api/knowledge/questions/configuration-history", params={"recipe": "runtime:v10", "model_id": 901})
            assert history.status_code == 200, history.text
            latest, old = history.json()["items"]
            assert latest["snapshot"]["version_number"] == "1.14.81"
            assert latest["rows"][0]["missing"] == "配置项未标明电池型号"
            assert old["rows"][0]["duration"] == "52分钟"
            again = await client.post("/api/knowledge/questions/ask", json=payload)
            assert again.json()["configuration_answers"][0]["revision_id"] == latest["revision_id"]
            historical = await client.post("/api/knowledge/questions/ask", json={
                **payload, "scope": {"market": "domestic", "software_version": "1.14.80"},
            })
            assert historical.status_code == 200, historical.text
            earlier, = historical.json()["configuration_answers"]
            assert earlier["snapshot"]["id"] == 1
            assert earlier["rows"][0]["duration"] == "52分钟"
            unknown = await client.post("/api/knowledge/questions/ask", json={
                **payload, "scope": {"market": "domestic", "software_version": "1.14.70"},
            })
            no_match, = unknown.json()["configuration_answers"]
            assert no_match["snapshot"] is None and no_match["rows"] == []
            assert "1.14.70" in no_match["issues"][0]
            history = await client.get("/api/knowledge/questions/configuration-history", params={"recipe": "runtime:v10", "model_id": 901})
            assert [item["revision_id"] for item in history.json()["items"]] == [latest["revision_id"], old["revision_id"]]
            async with engine.begin() as connection:
                await connection.run_sync(KnowledgePublicFact.__table__.create)
            async with AsyncSession(engine) as db, db.begin():
                await db.execute(text("""
                    INSERT INTO knowledge_public_facts(fact_key,market,payload_json)
                    VALUES ('component.excluded:901:2000000','domestic',:payload)
                """), {"payload": json.dumps({"status": "confirmed", "display_value": "该机型不使用此电池"})})
            corrected = await client.post("/api/knowledge/questions/ask", json={
                **payload, "scope": {"market": "domestic", "software_version": "1.14.80"},
            })
            answer, = corrected.json()["configuration_answers"]
            assert {row["ipn"] for row in answer["rows"]} == {"1001036"}
            assert "该机型不使用此电池" in answer["scope_note"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_parameter_question_reuses_existing_specs_and_current_snapshot(tmp_path):
    from test_knowledge_parameter_query import _topics

    path = tmp_path / "parameter-current.db"
    _create_qa_database(path)
    _topics(path)
    client, engine = await _client_for(path)
    try:
        with sqlite3.connect(path) as db:
            for column in ("is_enabled INTEGER NOT NULL DEFAULT 1", "description TEXT", "status TEXT",
                           "column_start INTEGER", "column_end INTEGER", "sort_order INTEGER", "config_group TEXT",
                           "created_at TEXT", "updated_at TEXT"):
                db.execute(f"ALTER TABLE product_models ADD COLUMN {column}")
            db.execute("CREATE TABLE config_versions(id INTEGER PRIMARY KEY, series_id INTEGER,version_number TEXT,snapshot_data TEXT)")
            db.execute("INSERT INTO config_versions VALUES (1,901,'1.14.81',?)", (_snapshot(("1001036", "V9BAT", "X"),),))
            db.execute("CREATE TABLE config_items(ipn TEXT,zh_desc TEXT)")
            db.execute("INSERT INTO config_items VALUES ('1001036','V9 电池')")
            db.execute("UPDATE knowledge_parameter_topics SET fields_json=?", (
                json.dumps([{"key":"capacity","label":"容量","unit":"mAh","type":"number"}]),))
            db.executescript("""
                DROP TABLE knowledge_parameter_specs;
                CREATE TABLE knowledge_parameter_specs(
                    id INTEGER PRIMARY KEY,topic_id INTEGER,ipn TEXT,name TEXT,values_json TEXT,
                    evidence_reference TEXT,confirmed_by TEXT,revision INTEGER,is_active INTEGER);
                INSERT INTO knowledge_parameter_specs VALUES
                  (1,1,'1001036','V9BAT','{"capacity": 6700}','规格书第 2 页','审核人',1,1);
            """)
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: KnowledgeConfigurationAnswerRevision.__table__.create(sync))
        async with client:
            r = await client.post("/api/knowledge/questions/ask", json={"question":"各型号电池容量是多少？",
                                  "scope":{"market":"domestic","product_model_id":901,"software_version":"1.14.81"}})
            assert r.status_code == 200, r.text
            result, = r.json()["configuration_answers"]
            assert result["recipe"] == "parameter:1"
            assert result["snapshot"]["id"] == 1
            selected, = result["rows"][0]["matches"]
            assert selected["usable"] and selected["values"] == {"capacity":6700}
            assert selected["evidence_reference"] == "规格书第 2 页"
            async with engine.begin() as connection:
                await connection.run_sync(KnowledgePublicFact.__table__.create)
            async with AsyncSession(engine) as db, db.begin():
                await db.execute(text("""
                    INSERT INTO knowledge_public_facts(fact_key,market,payload_json)
                    VALUES ('component.excluded:901:1001036','domestic',:payload)
                """), {"payload": json.dumps({"status": "confirmed", "display_value": "该机型不使用此电池"})})
            corrected = await client.post("/api/knowledge/questions/ask", json={
                "question": "各型号电池容量是多少？",
                "scope": {"market": "domestic", "product_model_id": 901, "software_version": "1.14.81"},
            })
            answer, = corrected.json()["configuration_answers"]
            assert answer["rows"][0]["matches"] == []
            assert "该机型不使用此电池" in answer["answer_text"]
    finally:
        await engine.dispose()


def test_confirmed_parameter_identity_can_match_generic_battery_but_conflicts_remain_pending():
    from app.services.knowledge_runtime import battery_configuration

    snapshot = json.loads(_snapshot(("1000349", "独立包装电池", "O")))
    spec = {"ipn":"1000349","name":"V9BAT","evidence_reference":"已核对物料主数据"}
    battery, = battery_configuration(snapshot, 901, [spec])
    assert battery["battery"] == "V9BAT" and battery["identity_sources"] == ["已核对物料主数据"]
    conflict, = battery_configuration(snapshot, 901, [spec, {**spec, "name":"V8BAT"}])
    assert conflict["battery"] is None and conflict["identity_issue"]


@pytest.mark.asyncio
async def test_unified_query_resolves_reviewed_component_and_cart_source_gap(tmp_path):
    path = tmp_path / "reviewed-facts.db"
    _create_qa_database(path)
    client, engine = await _client_for(path)
    source = tmp_path / "configuration.xlsx"
    workbook = Workbook()
    workbook.active.title = "Sheet1"
    workbook.active.append(["V30148", "N/A", "范围外"])
    workbook.save(source)
    version = sha256(source.read_bytes()).hexdigest()
    citation = {"document_id": 1, "version_id": version, "title": "原始配置",
                "file_name": source.name, "locator": "Sheet1!A1:B1"}
    try:
        with sqlite3.connect(path) as db:
            for column in ("is_enabled INTEGER NOT NULL DEFAULT 1", "description TEXT", "status TEXT",
                           "column_start INTEGER", "column_end INTEGER", "sort_order INTEGER", "config_group TEXT",
                           "created_at TEXT", "updated_at TEXT"):
                db.execute(f"ALTER TABLE product_models ADD COLUMN {column}")
            db.execute("CREATE TABLE config_versions(id INTEGER PRIMARY KEY, series_id INTEGER,version_number TEXT,snapshot_data TEXT)")
            db.execute("UPDATE knowledge_documents SET file_name=?,file_path=?,sha256=? WHERE id=1",
                       (source.name, str(source), version))
            db.execute("INSERT INTO config_versions VALUES (1,901,'1.14.82',?)",
                       (_snapshot(("1000349", "独立包装电池", "N/A")),))
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: KnowledgePublicFact.__table__.create(sync))
            await connection.run_sync(KnowledgeConfigurationAnswerRevision.__table__.create)
        async with AsyncSession(engine) as db:
            db.add_all([
                KnowledgePublicFact(fact_key="component.excluded:901:1000349", market="domestic", payload_json=json.dumps({
                    "status": "confirmed", "value": "不适用", "display_value": "VINNO 10 不搭配 V8BAT",
                    "conditions": {"model_id": 901}, "sources": [citation], "issue": None,
                })),
                KnowledgePublicFact(fact_key="cart_f.battery_pack.runtime", market="overseas", payload_json=json.dumps({
                    "status": "missing", "value": None, "sources": [citation],
                    "issue": {"root_key": "cart_f.runtime.source", "detail": "缺少现行整车放电报告"},
                })),
            ])
            await db.commit()
        async with client:
            async def ask(question, scope=None):
                response = await client.post("/api/knowledge/questions/ask", json={
                    "question": question, "scope": scope, "unified": True,
                })
                assert response.status_code == 200, response.text
                return response.json()

            result, = (await ask("国内 VINNO 10 支持选配 V8BAT 吗？"))["configuration_answers"]
            assert result["answer_text"] == "VINNO 10 不搭配 V8BAT"
            assert result["snapshot"]["version_number"] == "1.14.82" and result["selection"] == "N/A"
            assert result["sources"][0]["locator"] == citation["locator"]
            link = result["sources"][0]["evidence_url"]
            assert link.endswith(version)
            evidence = await client.get(link)
            assert evidence.status_code == 200, evidence.text
            assert evidence.json()["excerpts"] == [{
                "locator": "Sheet1!A1:B1",
                "cells": [{"address": "A1", "text": "V30148"}, {"address": "B1", "text": "N/A"}],
            }]
            assert (await client.get(link.replace(version, "b" * 64))).status_code == 409
            for question in (
                "V10 使用 V8BAT 的续航是多少？",
                "国内 VINNO 10 搭配 V30148 的实测续航是多久？",
            ):
                runtime, = (await ask(question))["configuration_answers"]
                assert runtime["answer_text"] == result["answer_text"]
                assert runtime["selection"] == "N/A" and not runtime["rows"]
                assert runtime["sources"][0]["evidence_url"] == link
            general, = (await ask("国内 V10 的续航是多少？", {"software_version": "1.14.82"}))["configuration_answers"]
            assert result["answer_text"] in general["scope_note"]
            assert "当前配置未登记可用于续航匹配的电池" in general["issues"]
            assert (await ask("A3 使用 V9BAT 的续航是多少？"))["status"] == "outside_scope"
            assert (await ask("Cart-F 的整车续航是多少？"))["missing_fields"] == ["market"]
            cart, = (await ask("海外 Cart-F 的整车续航是多少？"))["configuration_answers"]
            assert cart["market"] == "overseas" and cart["answer_text"] == "缺少现行整车放电报告"
            assert cart["sources"][0]["locator"] == citation["locator"]
            assert (await ask("国内 Cart-F 的整车续航是多少？"))["configuration_answers"] == []
    finally:
        await engine.dispose()

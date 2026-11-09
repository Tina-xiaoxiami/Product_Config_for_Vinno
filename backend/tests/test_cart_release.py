"""Cart shipping reviews use immutable configuration and presentation evidence."""

from io import BytesIO
from zipfile import ZipFile

import pytest

from app.services.cart_release_diff import changes, snapshot_view
from app.services.cart_release_ppt import replace_tokens
from app.services.cart_release_rules import Rules, TokenRule


RULES = Rules(market_pages={"domestic": {"V70001": (3, 7)}})


def config(ipn="7000001-1", code="V70001", final="O", current="O", name="Example Cart"):
    return {
        "models": [{"id": 30, "name": "Example 10"}],
        "items": [{
            "id": 10, "ipn": ipn, "v_code": code, "en_desc": name,
            "values": {"30": {"final_config": final, "selection_config": final, "current_config": current}},
        }],
    }


def test_cart_uses_shipping_values_and_existing_empty_semantics():
    before = snapshot_view(config(final=None), RULES)
    after = snapshot_view(config(final="N/A", current="X"), RULES)
    assert changes(before, after, "domestic", RULES) == []
    difference, = changes(after, snapshot_view(config(final="O"), RULES), "domestic", RULES)
    assert difference["models"] == ["Example 10"]
    assert difference["before"]["values"] == []
    assert difference["after"]["values"][0]["final_config"] == "O"
    assert difference["pages"] == [3, 7]


def test_cart_changes_keep_unmapped_and_old_identity():
    before = snapshot_view(config(ipn=None, code=None, name="Cart custom assembly"), RULES)
    after = snapshot_view(config(ipn=None, code=None, name="Accessory assembly"), RULES)
    difference, = changes(before, after, "domestic", RULES)
    assert difference["before"]["en_desc"] == "Cart custom assembly"
    assert difference["after"]["en_desc"] == "Accessory assembly"
    assert difference["pages"] == []


def test_ppt_patch_preserves_run_boundaries_and_other_members():
    xml = b"""<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
      xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:sp><p:nvSpPr>
      <p:cNvPr id="5"/></p:nvSpPr><p:txBody><a:p><a:r><a:t>Port (V</a:t></a:r>
      <a:r><a:t>77006</a:t></a:r><a:r><a:t>)</a:t></a:r></a:p></p:txBody></p:sp></p:sld>"""
    source = BytesIO()
    with ZipFile(source, "w") as archive:
        archive.writestr("ppt/slides/slide3.xml", xml)
        archive.writestr("ppt/media/image.png", b"unchanged")
    rule = TokenRule(series=("series",), code="V77006", ipn="7000010", field="v_code", targets=((3, "5"),))
    output = replace_tokens(source.getvalue(), [(rule, "V77007")])
    with ZipFile(BytesIO(output)) as archive:
        assert archive.read("ppt/media/image.png") == b"unchanged"
        changed = archive.read("ppt/slides/slide3.xml")
        assert b">Port (V<" in changed
        assert b">77007<" in changed
    with pytest.raises(ValueError, match="定位"):
        replace_tokens(output, [(rule, "V77008")])


@pytest.mark.asyncio
async def test_version_check_cross_series_retry_rollback_and_history(tmp_path, monkeypatch):
    import asyncio
    from hashlib import sha256
    import json

    from sqlalchemy import func, select

    from app.models import CartReleaseArtifact, ConfigItem, ConfigValue, ConfigVersion, ProductModel, ProductSeries
    from test_versions_api import _versions_harness

    code = "V77006"
    replacement = "V77007"
    ipn = "7000010"
    source = BytesIO()
    with ZipFile(source, "w") as archive:
        archive.writestr("ppt/slides/slide3.xml", f"""<p:sld
          xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
          xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:sp><p:nvSpPr>
          <p:cNvPr id="5"/></p:nvSpPr><p:txBody><a:p><a:r><a:t>Port ({code})</a:t></a:r>
          </a:p></p:txBody></p:sp></p:sld>""")
    template = tmp_path / "海外" / "example.pptx"
    template.parent.mkdir()
    snapshot = config(ipn=ipn, code=code)
    snapshot_data = json.dumps(snapshot)
    names = ("Example A-Oversea", "Example B-Oversea")
    rules = Rules(version="example-1", templates={"overseas": {
        "filename": template.name, "sha256": sha256(source.getvalue()).hexdigest(),
        "anchors": [
            {"series": name, "version": "1.0.0", "sha256": sha256(snapshot_data.encode()).hexdigest()}
            for name in names
        ],
        "rules": [{"series": names, "code": code, "ipn": ipn, "field": "v_code", "targets": [(3, "5")]}],
    }})
    path = tmp_path / "rules.json"
    path.write_text(rules.model_dump_json())
    monkeypatch.setenv("CART_RELEASE_RULES_FILE", str(path))
    monkeypatch.setenv("CART_RELEASE_TEMPLATE_ROOT", str(tmp_path))
    client, session_factory, engine = await _versions_harness(tmp_path)
    try:
        async with client:
            async with session_factory() as db:
                db.add_all([ProductSeries(id=i, name=name) for i, name in enumerate(names, 1)])
                db.add_all([ProductModel(id=i, series_id=s, name="Example 10") for i, s in ((30, 1), (31, 2))])
                db.add(ConfigItem(id=10, row_index=1, ipn=ipn, v_code=replacement, en_desc="Example Cart"))
                db.add_all([ConfigValue(item_id=10, model_id=i, final_config="O", selection_config="O", current_config="O")
                            for i in (30, 31)])
                first = ConfigVersion(series_id=1, version_number="1.0.0", snapshot_data=snapshot_data)
                second_snapshot = config(ipn=ipn, code=code)
                second_snapshot["models"][0]["id"] = 31
                second_snapshot["items"][0]["values"]["31"] = second_snapshot["items"][0]["values"].pop("30")
                second_data = json.dumps(second_snapshot)
                db.add_all([first, ConfigVersion(series_id=2, version_number="1.0.0", snapshot_data=second_data)])
                await db.commit()
            revised = rules.model_dump()
            revised["templates"]["overseas"]["anchors"][1]["sha256"] = sha256(second_data.encode()).hexdigest()
            path.write_text(json.dumps(revised))

            history = await client.get("/api/versions/1/cart-release")
            assert history.json()["status"] == "not_checked"
            first_save = await client.post("/api/versions", json={"series_id": 1})
            assert first_save.status_code == 200, first_save.text
            first_id = first_save.json()["id"]
            first_check = (await client.get(f"/api/versions/{first_id}/cart-release")).json()
            assert first_check["status"] == "pending"
            assert "证据不一致" in first_check["reason"]

            second_save = await client.post("/api/versions", json={"series_id": 2})
            assert second_save.status_code == 200, second_save.text
            second_id = second_save.json()["id"]
            check_url = f"/api/versions/{second_id}/cart-release"
            pending = (await client.get(check_url)).json()
            assert pending["status"] == "pending"
            assert "原件不可用" in pending["reason"]
            template.write_bytes(b"wrong source")
            changed_source = (await client.post(check_url)).json()
            assert changed_source["status"] == "pending"
            assert "原件版本已变化" in changed_source["reason"]
            template.write_bytes(source.getvalue())
            retries = await asyncio.gather(client.post(check_url), client.post(check_url))
            assert retries[0].json() == retries[1].json()
            generated = retries[0].json()
            assert generated["status"] == "generated", generated
            assert len(generated["baseline_changes"]) == 2
            assert generated["updates"] == [{"before": code, "after": replacement, "pages": [3]}]
            assert (await client.post(check_url)).json() == generated
            assert (await client.post(f"/api/versions/{first_id}/cart-release")).json()["status"] == "pending"
            archive = f"/api/versions/cart-release/archive/{generated['version']['key']}"
            result = await client.get(f"{archive}/presentation")
            assert result.status_code == 200
            with ZipFile(BytesIO(result.content)) as ppt:
                assert replacement.encode() in ppt.read("ppt/slides/slide3.xml")
            async with session_factory() as db:
                assert await db.scalar(select(func.count()).select_from(CartReleaseArtifact)) == 1

            # Series rollback preserves globally managed part metadata.
            rollback = await client.post("/api/versions/2/rollback")
            assert rollback.status_code == 200, rollback.text
            rollback_url = f"/api/versions/{rollback.json()['new_version']['id']}/cart-release"
            rollback_check = (await client.get(rollback_url)).json()
            assert rollback_check["status"] == "checked"
            assert rollback_check["origin"] == "rollback"
            assert rollback_check["rollback_target"]["id"] == 2

            # Reverting the global code and saving both series restores the original deck.
            async with session_factory() as db:
                item = await db.get(ConfigItem, 10)
                item.v_code = code
                await db.commit()
            for series_id in (1, 2):
                reverted = await client.post("/api/versions", json={"series_id": series_id})
                assert reverted.status_code == 200, reverted.text
                reverted_id = reverted.json()["id"]
                reverted_check = (await client.get(f"/api/versions/{reverted_id}/cart-release")).json()
                assert reverted_check["status"] == ("pending" if series_id == 1 else "generated")
            assert reverted_check["updates"] == [{"before": replacement, "after": code, "pages": [3]}]
            assert (await client.get(f"/api/versions/{reverted_id}/cart-release/presentation")).content == source.getvalue()

            backfill = await client.post("/api/versions/cart-release/backfill", params={"series_id": 1, "limit": 1})
            assert backfill.status_code == 200, backfill.text
            assert backfill.json()["next_after_id"] == 1
            assert (await client.delete(f"/api/versions/{second_id}")).status_code == 200
            assert (await client.get(f"{archive}/presentation")).content == result.content
    finally:
        await engine.dispose()

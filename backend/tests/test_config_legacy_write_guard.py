"""Legacy routes must not bypass configuration drafts and published versions."""
from fastapi import FastAPI
import httpx
import pytest

from app.api import config
from app.database import get_db


@pytest.mark.asyncio
async def test_legacy_single_and_batch_updates_are_rejected_without_using_database():
    app = FastAPI()
    app.include_router(config.router, prefix="/api/config")

    async def database_must_remain_unused():
        yield object()  # Any old query/commit would fail this regression.

    app.dependency_overrides[get_db] = database_must_remain_unused
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        single = await client.put("/api/config/value/1", params={"current_config": "X"})
        batch = await client.post("/api/config/batch-update", json={
            "item_ids": [1], "model_ids": [1], "field_name": "current_config", "value": "X",
        })
    for response in (single, batch):
        assert response.status_code == 409
        assert "草稿" in response.json()["detail"]

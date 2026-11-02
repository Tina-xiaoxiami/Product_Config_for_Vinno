"""The server must expose the workspaces and create their new empty storage."""
import importlib
from pathlib import Path
import pytest
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_application_model_registry_initializes_workspace_storage(tmp_path):
    import app.models  # noqa: F401
    from app.database import Base
    expected = {'knowledge_release_bindings', 'knowledge_parameter_topics', 'knowledge_parameter_specs', 'knowledge_parameter_revisions'}
    assert expected <= set(Base.metadata.tables)
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "registry.db"}')
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        from sqlalchemy import text
        tables = set((await connection.execute(text("select name from sqlite_master where type='table'"))).scalars())
        assert expected <= tables
    await engine.dispose()


def test_application_mounts_workspace_api_routes():
    app = importlib.import_module('main').app
    paths = set(app.openapi()['paths'])
    assert '/api/knowledge/release-history/trace' in paths
    assert '/api/knowledge/parameter-topics' in paths
    assert '/api/knowledge/parameter-topics/{topic_id}/preview' in paths

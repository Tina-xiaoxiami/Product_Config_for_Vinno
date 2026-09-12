import hashlib
from pathlib import Path
import sqlite3

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import knowledge
from app.database import get_db
from app.services.data_review import (
    get_data_review_item_history,
    list_data_review_batches,
    list_data_review_items,
    migrate_data_review_schema,
    revise_data_review_item,
    stage_knowledge_document_review_items,
    stage_overseas_preview_review_items,
)
from app.services.overseas_registration_preview import (
    OverseasRegistrationPreview,
    OverseasRegistrationRecord,
)


def _create_database(path: Path, controlled_file: Path) -> None:
    digest = hashlib.sha256(controlled_file.read_bytes()).hexdigest()
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE knowledge_documents (
            id INTEGER PRIMARY KEY,
            document_type TEXT NOT NULL,
            title TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            sha256 TEXT,
            version TEXT,
            market TEXT NOT NULL,
            country TEXT,
            product_series TEXT,
            mime_type TEXT,
            source_status TEXT NOT NULL DEFAULT 'active'
        );
        CREATE TABLE overseas_registration_snapshots (
            id INTEGER PRIMARY KEY,
            source_document_id INTEGER NOT NULL REFERENCES knowledge_documents(id),
            source_file_name TEXT NOT NULL,
            source_sha256 TEXT NOT NULL UNIQUE,
            snapshot_date TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            relation_count INTEGER NOT NULL,
            country_count INTEGER NOT NULL,
            model_count INTEGER NOT NULL,
            probe_count INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            published_at TEXT,
            confirmed_by TEXT
        );
        CREATE TABLE knowledge_document_chunks (
            id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL REFERENCES knowledge_documents(id),
            chunk_index INTEGER NOT NULL,
            page_number INTEGER,
            section_name TEXT,
            source_ref TEXT NOT NULL,
            content TEXT NOT NULL,
            normalized_content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            UNIQUE(document_id, chunk_index)
        );
        """
    )
    connection.execute(
        """
        INSERT INTO knowledge_documents (
            id, document_type, title, file_path, file_name, sha256, market
        ) VALUES (1, 'registration_tracking', 'tracking', ?, ?, ?, 'overseas')
        """,
        (str(controlled_file), controlled_file.name, digest),
    )
    connection.execute(
        """
        INSERT INTO overseas_registration_snapshots (
            id, source_document_id, source_file_name, source_sha256, snapshot_date,
            status, relation_count, country_count, model_count, probe_count
        ) VALUES (7, 1, ?, ?, '2026-08-19', 'draft', 0, 0, 0, 0)
        """,
        (controlled_file.name, digest),
    )
    connection.commit()
    connection.close()


def test_document_text_chunks_can_be_corrected_without_losing_ocr_text(tmp_path):
    controlled_file = tmp_path / "manual.pdf"
    controlled_file.write_bytes(b"controlled")
    database_path = tmp_path / "product_config.db"
    _create_database(database_path, controlled_file)
    connection = sqlite3.connect(database_path)
    connection.execute(
        "UPDATE knowledge_documents SET document_type = 'manual', title = '产品说明书' WHERE id = 1"
    )
    connection.execute(
        """
        INSERT INTO knowledge_document_chunks (
            id, document_id, chunk_index, page_number, section_name,
            source_ref, content, normalized_content, content_hash
        ) VALUES (9, 1, 0, 12, '功能说明', '第12页', '支持 VINNNO 10',
                  '支持vinnno10', 'raw-hash')
        """
    )
    connection.commit()
    connection.close()

    migrate_data_review_schema(database_path)
    staged = stage_knowledge_document_review_items(database_path, document_id=1)
    assert staged == {"item_count": 1, "needs_review_count": 0}

    async def load_item():
        engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            items, _ = await list_data_review_items(
                session,
                data_type="knowledge_document_chunk",
                batch_id=1,
                review_status=None,
                query=None,
                skip=0,
                limit=10,
            )
        await engine.dispose()
        return items[0]

    import asyncio

    item = asyncio.run(load_item())
    revised = revise_data_review_item(
        database_path,
        item_id=item["id"],
        effective_payload={
            **item["effective_payload"],
            "content": "支持 VINNO 10",
        },
        review_status="corrected",
        changed_by="product_owner",
        change_note="修正 OCR 拼写",
    )

    assert revised["raw_payload"]["content"] == "支持 VINNNO 10"
    assert revised["effective_payload"]["content"] == "支持 VINNO 10"
    connection = sqlite3.connect(database_path)
    chunk = connection.execute(
        "SELECT content, normalized_content FROM knowledge_document_chunks WHERE id = 9"
    ).fetchone()
    connection.close()
    assert chunk == ("支持 VINNO 10", "支持vinno10")


def _preview(controlled_file: Path) -> OverseasRegistrationPreview:
    digest = hashlib.sha256(controlled_file.read_bytes()).hexdigest()
    records = (
        OverseasRegistrationRecord(
            sheet_name="已完成注册",
            source_row=2,
            source_ref="已完成注册!A2:C2",
            jurisdiction_raw="泰国",
            jurisdiction_name="泰国",
            jurisdiction_code="TH",
            authority=None,
            registration_status="completed",
            address_version="unspecified",
            model_raw="VINNO10",
            probe_raw="S2-9C",
            models=("VINNO10",),
            probes=("S2-9C",),
            ready_for_import=True,
            issue_codes=(),
        ),
        OverseasRegistrationRecord(
            sheet_name="已完成注册",
            source_row=3,
            source_ref="已完成注册!A3:C3",
            jurisdiction_raw="巴西",
            jurisdiction_name="巴西",
            jurisdiction_code="BR",
            authority=None,
            registration_status="completed",
            address_version="unspecified",
            model_raw="VINNNO 10",
            probe_raw="S2_9C",
            models=("VINNNO 10",),
            probes=("S2_9C",),
            ready_for_import=False,
            issue_codes=("model_name_requires_review", "probe_name_requires_review"),
        ),
    )
    return OverseasRegistrationPreview(
        source_file=str(controlled_file),
        source_sha256=digest,
        snapshot_date="2026-08-19",
        records=records,
        relations=(),
        summary={"source_rows": 2, "ready_rows": 1, "review_rows": 1},
    )


@pytest.mark.asyncio
async def test_review_center_preserves_raw_values_and_records_corrections(tmp_path):
    controlled_file = tmp_path / "tracking.xls"
    controlled_file.write_bytes(b"controlled")
    database_path = tmp_path / "product_config.db"
    _create_database(database_path, controlled_file)
    migrate_data_review_schema(database_path)
    staged = stage_overseas_preview_review_items(
        database_path,
        snapshot_id=7,
        source_document_id=1,
        preview=_preview(controlled_file),
    )

    assert staged == {"item_count": 2, "needs_review_count": 1}

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        batches = await list_data_review_batches(session)
        items, total = await list_data_review_items(
            session,
            data_type="overseas_registration_row",
            batch_id=7,
            review_status="needs_review",
            query=None,
            skip=0,
            limit=50,
        )
    await engine.dispose()

    assert batches[0]["data_type"] == "overseas_registration_row"
    assert batches[0]["total_count"] == 2
    assert total == 1
    item = items[0]
    assert item["raw_payload"]["model_raw"] == "VINNNO 10"

    revised = revise_data_review_item(
        database_path,
        item_id=item["id"],
        effective_payload={
            **item["effective_payload"],
            "model_raw": "VINNO 10",
            "probe_raw": "S2-9C",
        },
        review_status="corrected",
        changed_by="product_owner",
        change_note="修正原表不规范型号",
    )

    assert revised["raw_payload"]["model_raw"] == "VINNNO 10"
    assert revised["effective_payload"]["model_raw"] == "VINNO 10"
    history = get_data_review_item_history(database_path, item_id=item["id"])
    assert history[0]["revision_no"] == 1
    assert history[0]["before_payload"]["model_raw"] == "VINNNO 10"
    assert history[0]["after_payload"]["model_raw"] == "VINNO 10"


@pytest.mark.asyncio
async def test_review_center_api_lists_and_edits_one_source_row(tmp_path):
    controlled_file = tmp_path / "tracking.xls"
    controlled_file.write_bytes(b"controlled")
    database_path = tmp_path / "product_config.db"
    _create_database(database_path, controlled_file)
    migrate_data_review_schema(database_path)
    stage_overseas_preview_review_items(
        database_path,
        snapshot_id=7,
        source_document_id=1,
        preview=_preview(controlled_file),
    )

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(knowledge.router, prefix="/api/knowledge")

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        listed = await client.get(
            "/api/knowledge/review-items",
            params={"data_type": "overseas_registration_row", "batch_id": 7},
        )
        item = listed.json()["items"][1]
        updated = await client.put(
            f"/api/knowledge/review-items/{item['id']}",
            json={
                "effective_payload": {
                    **item["effective_payload"],
                    "model_raw": "VINNO 10",
                    "probe_raw": "S2-9C",
                },
                "review_status": "corrected",
                "changed_by": "product_owner",
                "change_note": "OCR 修正",
            },
        )
        history = await client.get(
            f"/api/knowledge/review-items/{item['id']}/history"
        )
    await engine.dispose()

    assert listed.status_code == 200
    assert listed.json()["total"] == 2
    assert updated.status_code == 200
    assert updated.json()["effective_payload"]["model_raw"] == "VINNO 10"
    assert history.json()["items"][0]["change_note"] == "OCR 修正"


def _status_preview(
    controlled_file: Path,
    *,
    status: str,
    ready: bool,
    codes: tuple[str, ...],
) -> OverseasRegistrationPreview:
    """构造一行指定注册状态的预览，用于验证审核口径。"""

    digest = hashlib.sha256(controlled_file.read_bytes()).hexdigest()
    return OverseasRegistrationPreview(
        source_file=str(controlled_file),
        source_sha256=digest,
        snapshot_date="2026-08-19",
        records=(
            OverseasRegistrationRecord(
                sheet_name="进行中-暂未收到销售反馈",
                source_row=2,
                source_ref="进行中-暂未收到销售反馈!A2:C2",
                jurisdiction_raw="泰国",
                jurisdiction_name="泰国",
                jurisdiction_code="TH",
                authority=None,
                registration_status=status,
                address_version="unspecified",
                model_raw="VINNO10",
                probe_raw="S2-9C",
                models=("VINNO10",),
                probes=("S2-9C",),
                ready_for_import=ready,
                issue_codes=codes,
            ),
        ),
        relations=(),
        summary={
            "source_rows": 1,
            "ready_rows": int(ready),
            "review_rows": int(not ready),
        },
    )


@pytest.mark.asyncio
async def test_non_completed_rows_are_kept_as_excluded_records(tmp_path):
    """注册状态非「已完成」的行只作记录保留：不进待确认队列，也不算可用数据。"""

    controlled_file = tmp_path / "tracking.xls"
    controlled_file.write_bytes(b"controlled")
    database_path = tmp_path / "product_config.db"
    _create_database(database_path, controlled_file)
    migrate_data_review_schema(database_path)

    staged = stage_overseas_preview_review_items(
        database_path,
        snapshot_id=7,
        source_document_id=1,
        preview=_status_preview(
            controlled_file,
            status="in_progress",
            ready=False,
            codes=("non_final_status",),
        ),
    )

    assert staged == {"item_count": 1, "needs_review_count": 0}

    connection = sqlite3.connect(database_path)
    row = connection.execute(
        """
        SELECT review_status, issue_codes_json, change_note
        FROM data_review_items WHERE batch_id = 7
        """
    ).fetchone()
    connection.close()

    assert row is not None
    assert row[0] == "excluded"
    assert "non_final_status" in row[1]
    # 自动排除必须写明原因，便于日后对账
    assert "自动排除" in (row[2] or "")
    assert "不作为正式数据" in (row[2] or "")


@pytest.mark.asyncio
async def test_completed_rows_with_writing_issues_still_need_review(tmp_path):
    """状态是已完成、但写法有疑问的行仍然必须进待确认队列。"""

    controlled_file = tmp_path / "tracking.xls"
    controlled_file.write_bytes(b"controlled")
    database_path = tmp_path / "product_config.db"
    _create_database(database_path, controlled_file)
    migrate_data_review_schema(database_path)

    staged = stage_overseas_preview_review_items(
        database_path,
        snapshot_id=7,
        source_document_id=1,
        preview=_status_preview(
            controlled_file,
            status="completed",
            ready=False,
            codes=("model_scope_requires_expansion",),
        ),
    )

    assert staged == {"item_count": 1, "needs_review_count": 1}

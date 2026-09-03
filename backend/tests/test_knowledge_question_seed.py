import sqlite3

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.knowledge_question_seed import (
    SeedQuestionSpec,
    seed_pending_questions,
)
from test_knowledge_qa_api import _create_qa_database


async def _session_for(database_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory


@pytest.mark.asyncio
async def test_seed_preview_is_read_only_and_apply_is_idempotent(tmp_path):
    database_path = tmp_path / "qa.db"
    _create_qa_database(database_path)
    engine, session_factory = await _session_for(database_path)
    specs = [
        SeedQuestionSpec(category="软件版本", question="V10当前软件版本是什么？"),
        SeedQuestionSpec(category="注册", question="VINNO 10E国内注册支持哪些探头？"),
    ]

    async with session_factory() as session:
        preview = await seed_pending_questions(session, specs, apply=False)
    connection = sqlite3.connect(database_path)
    preview_count = connection.execute(
        "SELECT COUNT(*) FROM knowledge_questions"
    ).fetchone()[0]
    connection.close()

    async with session_factory() as session:
        applied = await seed_pending_questions(session, specs, apply=True)
    async with session_factory() as session:
        repeated = await seed_pending_questions(session, specs, apply=True)
    await engine.dispose()

    connection = sqlite3.connect(database_path)
    rows = connection.execute(
        "SELECT question_text, status, asked_count FROM knowledge_questions ORDER BY id"
    ).fetchall()
    connection.close()

    assert preview["summary"] == {
        "total": 2,
        "would_insert": 2,
        "inserted": 0,
        "existing": 0,
        "covered": 0,
    }
    assert preview_count == 0
    assert applied["summary"]["inserted"] == 2
    assert repeated["summary"]["existing"] == 2
    assert len(rows) == 2
    assert all(status == "pending" and asked_count == 0 for _, status, asked_count in rows)


@pytest.mark.asyncio
async def test_seed_reuses_published_question_without_inflating_ask_count(tmp_path):
    database_path = tmp_path / "qa.db"
    _create_qa_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        INSERT INTO knowledge_questions (
            id, question_text, normalized_question, status, asked_count
        ) VALUES (
            1, 'V10系列可根据环境光线自动调节亮度吗？',
            'v10系列可根据环境光线自动调节亮度吗', 'answered', 7
        );
        INSERT INTO knowledge_answers (
            question_id, answer_text, review_status, version
        ) VALUES (1, '是，V10系列均支持。', 'published', 1);
        INSERT INTO knowledge_question_phrasings (
            question_id, phrasing_text, normalized_phrasing, phrasing_type
        ) VALUES (
            1, 'V10支持环境光自动调节亮度吗',
            'v10支持环境光自动调节亮度吗', 'alias'
        );
        """
    )
    connection.commit()
    connection.close()
    engine, session_factory = await _session_for(database_path)

    async with session_factory() as session:
        result = await seed_pending_questions(
            session,
            [
                SeedQuestionSpec(
                    category="功能事实",
                    question="V10支持环境光自动调节亮度吗？",
                )
            ],
            apply=True,
        )
    await engine.dispose()

    connection = sqlite3.connect(database_path)
    question_count = connection.execute(
        "SELECT COUNT(*) FROM knowledge_questions"
    ).fetchone()[0]
    asked_count = connection.execute(
        "SELECT asked_count FROM knowledge_questions WHERE id = 1"
    ).fetchone()[0]
    connection.close()

    assert result["summary"]["covered"] == 1
    assert result["items"][0]["action"] == "covered_by_published"
    assert result["items"][0]["question_id"] == 1
    assert question_count == 1
    assert asked_count == 7


@pytest.mark.asyncio
async def test_seed_rejects_duplicate_questions_within_one_batch(tmp_path):
    database_path = tmp_path / "qa.db"
    _create_qa_database(database_path)
    engine, session_factory = await _session_for(database_path)

    async with session_factory() as session:
        with pytest.raises(ValueError, match="批次内存在重复问题"):
            await seed_pending_questions(
                session,
                [
                    SeedQuestionSpec(category="配置", question="针增益调节是招标功能吗？"),
                    SeedQuestionSpec(category="配置", question="针增益调节是招标功能吗"),
                ],
                apply=False,
            )
    await engine.dispose()

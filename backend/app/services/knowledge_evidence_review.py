"""Shared SQL for marking answers affected by changed source evidence."""

# Named parameters work with both sqlite3 and SQLAlchemy. The caller owns the
# transaction, so document updates and review state cannot diverge on failure.
MARK_ANSWERS_SQL = """
UPDATE knowledge_answers
SET review_status = CASE
        WHEN review_status = 'evidence_changed' THEN 'evidence_changed'
        WHEN review_status = 'source_changed' AND :reason = 'scope_changed'
          OR review_status = 'scope_changed' AND :reason = 'source_changed'
          THEN 'evidence_changed'
        WHEN :reason = 'evidence_changed' THEN 'evidence_changed'
        ELSE :reason
    END,
    updated_at = CURRENT_TIMESTAMP
WHERE review_status IN ('published', 'source_changed', 'scope_changed', 'evidence_changed')
  AND id IN (SELECT answer_id FROM knowledge_answer_citations WHERE document_id = :document_id)
"""

MARK_QUESTIONS_SQL = """
UPDATE knowledge_questions
SET status = 'pending', updated_at = CURRENT_TIMESTAMP
WHERE id IN (
    SELECT answer.question_id FROM knowledge_answers answer
    JOIN knowledge_answer_citations citation ON citation.answer_id = answer.id
    WHERE citation.document_id = :document_id
      AND answer.review_status IN ('source_changed', 'scope_changed', 'evidence_changed')
)
"""


def change_reason(*, source_changed: bool, scope_changed: bool) -> str | None:
    if source_changed and scope_changed:
        return 'evidence_changed'
    if source_changed:
        return 'source_changed'
    if scope_changed:
        return 'scope_changed'
    return None


# A legacy database may have neither module. Partial installation is an error:
# silently skipping it could leave a confirmed conclusion based on stale evidence.
QA_TABLES = frozenset({'knowledge_questions', 'knowledge_answers', 'knowledge_answer_citations'})
RELEASE_TABLES = frozenset({'feature_versions', 'feature_version_revisions'})
TABLES_SQL = """SELECT name FROM sqlite_master WHERE type = 'table' AND name IN
('knowledge_questions', 'knowledge_answers', 'knowledge_answer_citations',
 'feature_versions', 'feature_version_revisions')"""


def installed_modules(names: set[str]) -> tuple[bool, bool]:
    for group in (QA_TABLES, RELEASE_TABLES):
        present = names & group
        if present and present != group:
            raise RuntimeError(f"不完整的知识复核数据库表：缺少 {', '.join(sorted(group - present))}")
    return QA_TABLES <= names, RELEASE_TABLES <= names


FEATURE_ROWS_SQL = "SELECT * FROM feature_versions WHERE evidence_document_id = :document_id AND review_status = 'confirmed'"
FEATURE_UPDATE_SQL = "UPDATE feature_versions SET review_status = 'pending', updated_at = CURRENT_TIMESTAMP WHERE id = :id AND review_status = 'confirmed'"
FEATURE_REVISION_SQL = """
INSERT INTO feature_version_revisions (
    feature_version_id, revision_no, action, before_json, after_json, change_note, changed_by
) VALUES (
    :id, (SELECT COALESCE(MAX(revision_no), 0) + 1 FROM feature_version_revisions WHERE feature_version_id = :id),
    'updated', :before_json, :after_json, :note, 'source_revalidation'
)
"""


def feature_revision_params(row: dict, reason: str) -> dict:
    from app.services.feature_release_versions import _audit_snapshot

    notes = {
        'source_changed': '引用原文已变化，请重新确认',
        'scope_changed': '引用资料适用范围已变化，请重新确认',
        'evidence_changed': '引用原文和适用范围已变化，请重新确认',
    }
    return {
        'id': row['id'],
        'before_json': _audit_snapshot(row),
        'after_json': _audit_snapshot({**row, 'review_status': 'pending'}),
        'note': notes[reason],
    }


def mark_changed_sqlite(connection, document_id: int, reason: str) -> None:
    qa, release = installed_modules({row[0] for row in connection.execute(TABLES_SQL)})
    params = {'document_id': document_id, 'reason': reason}
    if qa:
        connection.execute(MARK_ANSWERS_SQL, params)
        connection.execute(MARK_QUESTIONS_SQL, params)
    if release:
        cursor = connection.execute(FEATURE_ROWS_SQL, params)
        columns = [item[0] for item in cursor.description]
        for row in cursor.fetchall():
            revision = feature_revision_params(dict(zip(columns, row)), reason)
            connection.execute(FEATURE_UPDATE_SQL, revision)
            connection.execute(FEATURE_REVISION_SQL, revision)


async def mark_changed_async(session, document_id: int, reason: str) -> None:
    from sqlalchemy import text

    tables = await session.execute(text(TABLES_SQL))
    qa, release = installed_modules({row[0] for row in tables})
    params = {'document_id': document_id, 'reason': reason}
    if qa:
        await session.execute(text(MARK_ANSWERS_SQL), params)
        await session.execute(text(MARK_QUESTIONS_SQL), params)
    if release:
        rows = await session.execute(text(FEATURE_ROWS_SQL), params)
        for row in rows:
            revision = feature_revision_params(dict(row._mapping), reason)
            await session.execute(text(FEATURE_UPDATE_SQL), revision)
            await session.execute(text(FEATURE_REVISION_SQL), revision)

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterator

from tracker.domain import (
    CHANGE_CATEGORIES,
    CHANGE_CATEGORY_LABELS,
    canonical_key,
    description_is_title_only,
    excerpt,
    matching_excerpt,
    feature_description,
    pair_single_language_items,
    sort_versions,
    version_key,
)


# 分类词表以 CHANGE_CATEGORIES 为唯一来源：写死列表会在词表放宽后失配——
# 词表加上 config_note / probe 之后，这两个分类的「未能证实同义」提醒就再也不会
# 随待审核清零而消失，导入与审核页会一直挂着无处可处理的条目。
_SEMANTIC_REVIEW_ISSUE = re.compile(
    r"^("
    + "|".join(
        re.escape(category)
        for category in sorted(CHANGE_CATEGORIES, key=len, reverse=True)
    )
    + r")\s+分类有\s+(\d+)\s+条中英文原文"
)
MARKET_SPECIFIC_TABLE_TYPES = {"configuration_matrix", "support_scope"}

# Shared visibility rules for search hits and version coverage inventories.
_SEARCH_SOURCE_VISIBLE = "s.is_final = 1"
_SEARCH_CANDIDATE_VISIBLE = "c.status = 'pending'"
_SEARCH_TABLE_VISIBLE = "table_data.table_type != 'other'"




SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    code TEXT NOT NULL COLLATE NOCASE UNIQUE,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO projects(id, name, code, is_default)
VALUES (1, 'ULTIMUS G2', 'ULTIMUS-G2', 1);

CREATE TABLE IF NOT EXISTS project_sources (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    path TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL DEFAULT 'Release Note',
    file_keywords_json TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS terms (
    id INTEGER PRIMARY KEY,
    cn_name TEXT NOT NULL,
    en_name TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    parent_id INTEGER REFERENCES terms(id),
    needs_review INTEGER NOT NULL DEFAULT 0,
    entry_type TEXT NOT NULL DEFAULT 'term' CHECK(entry_type IN ('term', 'note')),
    UNIQUE(cn_name, en_name, parent_id)
);

CREATE TABLE IF NOT EXISTS product_categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS features (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id),
    term_id INTEGER REFERENCES terms(id),
    parent_feature_id INTEGER REFERENCES features(id),
    cn_name TEXT NOT NULL,
    en_name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    cn_description TEXT NOT NULL DEFAULT '',
    en_description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS feature_notes (
    id INTEGER PRIMARY KEY,
    feature_id INTEGER NOT NULL REFERENCES features(id) ON DELETE CASCADE,
    cn_content TEXT NOT NULL,
    en_content TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER IF NOT EXISTS prevent_duplicate_feature_names_on_insert
BEFORE INSERT ON features
WHEN EXISTS (
    SELECT 1 FROM features
    WHERE project_id = NEW.project_id
      AND (cn_name = NEW.cn_name COLLATE NOCASE
       OR en_name = NEW.en_name COLLATE NOCASE)
)
BEGIN
    SELECT RAISE(ABORT, 'duplicate feature name');
END;

CREATE TRIGGER IF NOT EXISTS prevent_duplicate_feature_names_on_update
BEFORE UPDATE OF cn_name, en_name ON features
WHEN EXISTS (
    SELECT 1 FROM features
    WHERE id != OLD.id AND project_id = NEW.project_id
      AND (cn_name = NEW.cn_name COLLATE NOCASE
           OR en_name = NEW.en_name COLLATE NOCASE)
)
BEGIN
    SELECT RAISE(ABORT, 'duplicate feature name');
END;

CREATE TABLE IF NOT EXISTS feature_revisions (
    id INTEGER PRIMARY KEY,
    feature_id INTEGER NOT NULL REFERENCES features(id) ON DELETE CASCADE,
    revision_number INTEGER NOT NULL,
    cn_description TEXT NOT NULL,
    en_description TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'approved',
    source_change_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(feature_id, revision_number)
);

CREATE TABLE IF NOT EXISTS releases (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id),
    version TEXT NOT NULL,
    product TEXT NOT NULL DEFAULT 'ULTIMUS G2',
    domestic_release_date TEXT,
    overseas_release_date TEXT,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, version)
);

CREATE TABLE IF NOT EXISTS feature_market_releases (
    id INTEGER PRIMARY KEY,
    feature_id INTEGER NOT NULL REFERENCES features(id) ON DELETE CASCADE,
    release_id INTEGER NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    market TEXT NOT NULL CHECK(market IN ('domestic', 'overseas')),
    UNIQUE(feature_id, release_id, market)
);

CREATE TABLE IF NOT EXISTS source_documents (
    id INTEGER PRIMARY KEY,
    release_id INTEGER REFERENCES releases(id) ON DELETE SET NULL,
    path TEXT NOT NULL,
    filename TEXT NOT NULL,
    language TEXT NOT NULL CHECK(language IN ('cn', 'en', 'unknown')),
    sha256 TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    tables_json TEXT NOT NULL DEFAULT '[]',
    is_final INTEGER NOT NULL DEFAULT 1,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(path, sha256)
);

CREATE TABLE IF NOT EXISTS release_tables (
    id INTEGER PRIMARY KEY,
    release_id INTEGER NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    source_document_id INTEGER NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
    table_index INTEGER NOT NULL,
    language TEXT NOT NULL CHECK(language IN ('cn', 'en', 'unknown')),
    table_type TEXT NOT NULL CHECK(table_type IN (
        'configuration_matrix', 'support_scope', 'material_change',
        'ui_comparison', 'image_comparison', 'other'
    )),
    snapshot_mode TEXT NOT NULL CHECK(snapshot_mode IN (
        'full_snapshot', 'partial_update', 'delta', 'comparison', 'reference'
    )),
    headers_json TEXT NOT NULL DEFAULT '[]',
    rows_json TEXT NOT NULL DEFAULT '[]',
    row_count INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL,
    UNIQUE(source_document_id, table_index)
);

CREATE TABLE IF NOT EXISTS release_table_rows (
    id INTEGER PRIMARY KEY,
    table_id INTEGER NOT NULL REFERENCES release_tables(id) ON DELETE CASCADE,
    release_id INTEGER NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    stable_key TEXT NOT NULL,
    item_code TEXT NOT NULL DEFAULT '',
    item_name TEXT NOT NULL DEFAULT '',
    change_kind TEXT NOT NULL CHECK(change_kind IN (
        'added', 'removed', 'modified', 'snapshot', 'reference'
    )),
    summary TEXT NOT NULL DEFAULT '',
    data_json TEXT NOT NULL DEFAULT '{}',
    language TEXT NOT NULL CHECK(language IN ('cn', 'en', 'unknown')),
    pair_status TEXT NOT NULL DEFAULT 'unpaired' CHECK(pair_status IN (
        'matched', 'conflict', 'unpaired', 'needs_review'
    )),
    counterpart_id INTEGER REFERENCES release_table_rows(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(table_id, row_index, stable_key)
);

CREATE INDEX IF NOT EXISTS release_tables_by_release_type
ON release_tables(release_id, table_type);

CREATE INDEX IF NOT EXISTS release_table_rows_by_release_key
ON release_table_rows(release_id, stable_key);

CREATE TABLE IF NOT EXISTS change_events (
    id INTEGER PRIMARY KEY,
    release_id INTEGER NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    -- 取值必须与 tracker.domain.CHANGE_CATEGORIES 一致（有测试守护）；新增分类需追加迁移。
    category TEXT NOT NULL CHECK(category IN ('function', 'image', 'bug', 'config', 'config_note', 'probe', 'remark', 'unclassified')),
    canonical_key TEXT NOT NULL DEFAULT '',
    title_cn TEXT NOT NULL DEFAULT '',
    title_en TEXT NOT NULL DEFAULT '',
    description_cn TEXT NOT NULL DEFAULT '',
    description_en TEXT NOT NULL DEFAULT '',
    feature_id INTEGER REFERENCES features(id) ON DELETE SET NULL,
    source_document_id INTEGER REFERENCES source_documents(id) ON DELETE SET NULL,
    review_status TEXT NOT NULL DEFAULT 'approved',
    confidence REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS change_event_identity
ON change_events(release_id, category, canonical_key);

CREATE TABLE IF NOT EXISTS import_candidates (
    id INTEGER PRIMARY KEY,
    release_id INTEGER REFERENCES releases(id) ON DELETE CASCADE,
    -- 取值必须与 tracker.domain.CHANGE_CATEGORIES 一致（有测试守护）。
    category TEXT NOT NULL CHECK(category IN ('function', 'image', 'bug', 'config', 'config_note', 'probe', 'remark', 'unclassified')),
    title_cn TEXT NOT NULL DEFAULT '',
    title_en TEXT NOT NULL DEFAULT '',
    raw_cn TEXT NOT NULL DEFAULT '',
    raw_en TEXT NOT NULL DEFAULT '',
    proposed_feature_id INTEGER REFERENCES features(id) ON DELETE SET NULL,
    confidence REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    manually_edited INTEGER NOT NULL DEFAULT 0,
    source_document_id INTEGER REFERENCES source_documents(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS review_issues (
    id INTEGER PRIMARY KEY,
    issue_type TEXT NOT NULL,
    message TEXT NOT NULL,
    release_id INTEGER REFERENCES releases(id) ON DELETE CASCADE,
    candidate_id INTEGER REFERENCES import_candidates(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'running' CHECK(status IN (
        'running', 'completed', 'undone', 'failed'
    )),
    ready_only INTEGER NOT NULL DEFAULT 0,
    source_summary TEXT NOT NULL DEFAULT '',
    stats_json TEXT NOT NULL DEFAULT '{}',
    undoable INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    undone_at TEXT
);

CREATE TABLE IF NOT EXISTS import_batch_releases (
    batch_id INTEGER NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
    release_id INTEGER REFERENCES releases(id) ON DELETE SET NULL,
    version TEXT NOT NULL,
    was_existing INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(batch_id, version)
);

CREATE INDEX IF NOT EXISTS import_batches_by_project
ON import_batches(project_id, id DESC);
"""

# 版本化迁移登记表：记录已应用的迁移编号，使重复启动不再改写 schema。
MIGRATIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


# 审核结论的稳定载体：以「原文指纹」为键，使结论不依赖候选行 ID。
#
# 为何需要：重扫时 sync_word_candidates 会重建 pending 行与 approved bug 行
# （已批准非 bug、已拒绝、人工编辑过的行受保护，会原样保留）。因此任何按候选 ID
# 记录的外部结论都会失效。本表让结论按原文存活，重扫后仍可核对与再应用。
REVIEW_DECISIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS review_decisions (
    fingerprint TEXT PRIMARY KEY,
    release_version TEXT NOT NULL,
    category TEXT NOT NULL,
    status TEXT NOT NULL,
    decision_source TEXT NOT NULL DEFAULT 'human',
    reviewer TEXT,
    decided_at TEXT,
    excerpt TEXT NOT NULL DEFAULT '',
    fingerprint_alt TEXT NOT NULL DEFAULT '',
    applied_candidate_id INTEGER,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

REVIEW_DECISIONS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS review_decisions_by_version
ON review_decisions(release_version, status);
"""


# 条目与证据的关联（迁移 007）。
#
# 正式答案必须能回到原文定位：答案 → 条目 → 证据（文档版本 + 页码/工作表/单元格
# + 原文摘录）。条目与证据是多对多，故单列关联表。
ITEM_EVIDENCE_SQL = """
CREATE TABLE IF NOT EXISTS kh_item_evidence (
    item_id INTEGER NOT NULL REFERENCES kh_items(id) ON DELETE CASCADE,
    evidence_id INTEGER NOT NULL REFERENCES kh_evidence(id) ON DELETE CASCADE,
    note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (item_id, evidence_id)
);
"""

# 机型映射（迁移 006）。
#
# 红线：注册资料只维护基础型号。查询衍生型号时先用**已确认映射**解析基础型号，
# 再按基础型号查注册证与差异表；**没有映射必须返回待确认，绝不能因为注册资料里
# 没有衍生型号名称就判定未注册**（A33/A34）。产品策略与发布状态仍用衍生型号自身。
MODEL_MAPPINGS_SQL = """
CREATE TABLE IF NOT EXISTS kh_model_mappings (
    derived_model TEXT PRIMARY KEY,
    base_model TEXT NOT NULL,
    mapping_source TEXT NOT NULL DEFAULT '',
    evidence_id INTEGER REFERENCES kh_evidence(id),
    verified_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

MODEL_SOURCE_LINKS_SQL = """
CREATE TABLE IF NOT EXISTS kh_model_source_links (
    source_system TEXT NOT NULL,
    source_model_name TEXT NOT NULL,
    knowledge_model TEXT NOT NULL,
    PRIMARY KEY (source_system, source_model_name)
);
"""

# 受控资料与证据（迁移 004）。
#
# 不变量：版本不可覆盖（只追加并用 supersedes 指向被替代版本）；同一
# kh_document_versions 行同时登记抽取源（docx）与受控发布版（PDF），
# **正式引用使用 PDF**（见 docs/handover/I01-建表与导入方案.md §1.3）。
DOCUMENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS kh_documents (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    doc_type TEXT NOT NULL DEFAULT '',
    scope_market TEXT NOT NULL DEFAULT 'domestic',
    model_scope TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '有效',
    current_version_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

DOCUMENT_VERSIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS kh_document_versions (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES kh_documents(id),
    version_label TEXT NOT NULL DEFAULT '',
    effective_date TEXT,
    sha256 TEXT NOT NULL DEFAULT '',
    path_docx TEXT,
    path_pdf TEXT,
    supersedes_version_id INTEGER REFERENCES kh_document_versions(id),
    status TEXT NOT NULL DEFAULT '有效',
    verified_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

EVIDENCE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS kh_evidence (
    id INTEGER PRIMARY KEY,
    document_version_id INTEGER NOT NULL REFERENCES kh_document_versions(id),
    page INTEGER,
    sheet TEXT,
    cell_range TEXT,
    excerpt TEXT NOT NULL DEFAULT '',
    extractor_version TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# 产品策略与注册（迁移 005）。
#
# 不变量：正式策略只读 selection_config；current_config 仅研发参考；
# final_config 不是正式依据；'#' 不是策略值。冲突与缺失分别标记，不擅自择一。
# 快照哈希取自**快照文件本身**，不沿用源主文件哈希（源库每次启动都会改写文件头）。
STRATEGY_SNAPSHOTS_SQL = """
CREATE TABLE IF NOT EXISTS kh_strategy_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    source_version TEXT NOT NULL DEFAULT '',
    collected_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

STRATEGY_VALUES_SQL = """
CREATE TABLE IF NOT EXISTS kh_strategy_values (
    snapshot_id TEXT NOT NULL REFERENCES kh_strategy_snapshots(snapshot_id),
    model_code TEXT NOT NULL,
    item_code TEXT NOT NULL,
    selection_config TEXT,
    current_config TEXT,
    final_config TEXT,
    source_values_json TEXT NOT NULL DEFAULT '[]',
    conflict_state TEXT NOT NULL DEFAULT 'none',
    PRIMARY KEY (snapshot_id, model_code, item_code)
);
"""

REGISTRATION_SCOPES_SQL = """
CREATE TABLE IF NOT EXISTS kh_registration_scopes (
    id INTEGER PRIMARY KEY,
    country_code TEXT NOT NULL,
    registration_base_model TEXT NOT NULL,
    probe_code TEXT NOT NULL,
    certificate_no TEXT NOT NULL DEFAULT '',
    effective_date TEXT,
    evidence_id INTEGER REFERENCES kh_evidence(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

REGISTRATION_EXCLUSIONS_SQL = """
CREATE TABLE IF NOT EXISTS kh_registration_exclusions (
    id INTEGER PRIMARY KEY,
    country_code TEXT NOT NULL,
    registration_base_model TEXT NOT NULL,
    probe_code TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    evidence_id INTEGER REFERENCES kh_evidence(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

REGISTRATION_RELATIONS_SQL = """
CREATE TABLE IF NOT EXISTS kh_registration_relations (
    id INTEGER PRIMARY KEY,
    country_code TEXT NOT NULL,
    certificate_no TEXT NOT NULL DEFAULT '',
    registration_base_model TEXT NOT NULL,
    probe_code TEXT NOT NULL,
    state TEXT NOT NULL,
    rule TEXT NOT NULL DEFAULT '',
    batch_id TEXT NOT NULL DEFAULT '',
    evidence_id INTEGER REFERENCES kh_evidence(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# 知识中枢基础结构（迁移 003）。
#
# 设计取舍：用「分类树 + 统一条目表 + 标签 + 探头关系」承载已确认的全部落点，
# 而不是为每类落点各建一张表。分类树支持多级；图像优化的三层标签由
# kh_item_tags.field 表达（probe / function / application）。
KNOWLEDGE_ITEMS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS kh_categories (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    parent_code TEXT REFERENCES kh_categories(code),
    level INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

KNOWLEDGE_ITEMS_SQL = """
CREATE TABLE IF NOT EXISTS kh_items (
    id INTEGER PRIMARY KEY,
    category_code TEXT NOT NULL REFERENCES kh_categories(code),
    code TEXT,
    name_cn TEXT NOT NULL DEFAULT '',
    name_en TEXT NOT NULL DEFAULT '',
    parent_item_id INTEGER REFERENCES kh_items(id),
    software_version TEXT,
    scope_market TEXT NOT NULL DEFAULT 'domestic',
    status TEXT NOT NULL DEFAULT 'active',
    source_kind TEXT NOT NULL DEFAULT 'release_note',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

KNOWLEDGE_TAGS_SQL = """
CREATE TABLE IF NOT EXISTS kh_item_tags (
    item_id INTEGER NOT NULL REFERENCES kh_items(id) ON DELETE CASCADE,
    field TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (item_id, field, value)
);
"""

PROBE_VERSIONS_SQL = """
CREATE TABLE IF NOT EXISTS kh_probe_versions (
    probe_code TEXT NOT NULL,
    probe_model TEXT NOT NULL DEFAULT '',
    series_code TEXT NOT NULL,
    software_version TEXT NOT NULL,
    state TEXT NOT NULL,
    replaces_probe_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (probe_code, series_code, software_version)
);
"""

KNOWLEDGE_REVIEW_RECORDS_SQL = """
CREATE TABLE IF NOT EXISTS kh_review_records (
    id INTEGER PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_ref TEXT NOT NULL,
    decision TEXT NOT NULL,
    bucket TEXT NOT NULL DEFAULT '',
    reviewer TEXT,
    decided_at TEXT,
    excerpt TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

KNOWLEDGE_ISSUES_SQL = """
CREATE TABLE IF NOT EXISTS kh_issues (
    id INTEGER PRIMARY KEY,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'medium',
    subject_type TEXT NOT NULL DEFAULT '',
    subject_ref TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# 产品状态（迁移 011）。
#
# 状态与版本是两项分别确认的业务事实，不能从 releases 最大版本号推断。新结论先进入
# pending；只有审核通过后才成为 current，并将旧 current 保留为 superseded 历史。
# 失效也只改变生命周期，不删除记录，以保留确认日期、来源和原因。
PRODUCT_STATES_SQL = """
CREATE TABLE IF NOT EXISTS kh_product_states (
    id INTEGER PRIMARY KEY,
    market_code TEXT NOT NULL,
    model_name TEXT NOT NULL,
    software_version TEXT NOT NULL,
    release_status TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    evidence_excerpt TEXT NOT NULL,
    record_status TEXT NOT NULL DEFAULT 'pending'
        CHECK(record_status IN ('pending', 'current', 'superseded', 'invalidated', 'rejected')),
    reviewed_by TEXT,
    reviewed_at TEXT,
    valid_until TEXT,
    review_note TEXT NOT NULL DEFAULT '',
    supersedes_state_id INTEGER REFERENCES kh_product_states(id),
    invalidated_at TEXT,
    invalidation_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

PRODUCT_STATES_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS kh_product_states_one_current
ON kh_product_states(market_code, model_name)
WHERE record_status = 'current';
"""

PRODUCT_STATES_LOOKUP_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS kh_product_states_lookup
ON kh_product_states(market_code, model_name, record_status, reviewed_at DESC, id DESC);
"""

QA_TABLES_SQL = (
    """CREATE TABLE IF NOT EXISTS kh_qa_questions (
        id INTEGER PRIMARY KEY,
        question TEXT NOT NULL,
        market_code TEXT NOT NULL,
        country_code TEXT NOT NULL,
        model_name TEXT NOT NULL,
        requester TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'answered')),
        answer_id INTEGER REFERENCES kh_qa_answers(id),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        answered_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS kh_qa_answers (
        id INTEGER PRIMARY KEY,
        standard_question TEXT NOT NULL,
        answer_text TEXT NOT NULL,
        market_code TEXT NOT NULL,
        country_code TEXT NOT NULL,
        model_name TEXT NOT NULL,
        registration_result TEXT NOT NULL,
        strategy_result TEXT NOT NULL,
        limitations TEXT NOT NULL,
        evidence_id INTEGER NOT NULL REFERENCES kh_evidence(id),
        status TEXT NOT NULL DEFAULT 'draft'
            CHECK(status IN ('draft', 'in_review', 'published', 'needs_review', 'retired')),
        reviewed_by TEXT,
        reviewed_at TEXT,
        verified_at TEXT,
        published_at TEXT,
        retirement_reason TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS kh_qa_phrases (
        answer_id INTEGER NOT NULL REFERENCES kh_qa_answers(id) ON DELETE CASCADE,
        phrase TEXT NOT NULL,
        normalized_phrase TEXT NOT NULL,
        PRIMARY KEY(answer_id, normalized_phrase)
    )""",
    """CREATE INDEX IF NOT EXISTS kh_qa_phrase_lookup
        ON kh_qa_phrases(normalized_phrase)""",
    """CREATE TABLE IF NOT EXISTS kh_qa_feedback (
        id INTEGER PRIMARY KEY,
        question_id INTEGER NOT NULL REFERENCES kh_qa_questions(id),
        helpful INTEGER NOT NULL CHECK(helpful IN (0, 1)),
        detail TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS kh_qa_notifications (
        id INTEGER PRIMARY KEY,
        question_id INTEGER NOT NULL REFERENCES kh_qa_questions(id),
        answer_id INTEGER NOT NULL REFERENCES kh_qa_answers(id),
        requester TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        read_at TEXT,
        UNIQUE(question_id, answer_id)
    )""",
)

# 分类树初值（多级）。编码稳定，名称按业务口径。
KNOWLEDGE_CATEGORY_SEED: tuple[tuple[str, str, str | None, int, int], ...] = (
    ("feature", "功能库", None, 1, 10),
    ("probe", "探头资料", None, 1, 20),
    ("registration", "注册资料", None, 1, 30),
    ("image_opt", "图像优化库", None, 1, 40),
    ("sw_func_opt", "软件功能优化", None, 1, 50),
    ("perf_ux", "性能/体验优化", None, 1, 60),
    ("i18n", "本地化/语言支持", None, 1, 70),
    ("config_note", "配置/兼容性说明", None, 1, 80),
    ("bug_fix", "Bug 修复记录", None, 1, 90),
    # 图像优化库的功能标签（第二级，取自产品负责人确认的 6 个枚举）
    ("image_opt.2d", "二维图像", "image_opt", 2, 10),
    ("image_opt.flow", "血流", "image_opt", 2, 20),
    ("image_opt.contrast", "造影", "image_opt", 2, 30),
    ("image_opt.elastography", "弹性成像", "image_opt", 2, 40),
    ("image_opt.3d4d", "三维四维", "image_opt", 2, 50),
    ("image_opt.probe_update", "探头更新", "image_opt", 2, 60),
    # 软件功能优化的子功能
    ("sw_func_opt.patient", "Patient", "sw_func_opt", 2, 10),
    ("sw_func_opt.comment", "Comment", "sw_func_opt", 2, 20),
    ("sw_func_opt.body_mark", "Body Mark", "sw_func_opt", 2, 30),
    ("sw_func_opt.measure", "Measure", "sw_func_opt", 2, 40),
    ("sw_func_opt.report", "Report", "sw_func_opt", 2, 50),
    ("sw_func_opt.other", "其他", "sw_func_opt", 2, 90),
)

_REVIEW_WHITESPACE = re.compile(r"[\s\u3000]+")


def review_fingerprints(
    version: str, raw_cn: str, raw_en: str
) -> tuple[str, str]:
    """返回 (主指纹, 备用指纹)；匹配时任一相等即视为同一变更。

    设计取舍（均由端到端实测得出）：

    1. **不包含分类**。分类是可随规则改进的派生属性；纳入指纹后一次分类修正
       （function/image → probe）会让 46/92 条既有结论失效。
    2. **中英双侧都登记，任一侧匹配即可**。抽取修复后中文侧会由空变为有值
       （实测 1.14.30/1.14.40 的 raw_cn 即如此），若只按双侧拼接取指纹，同一
       变更会被判成新内容而丢失结论。
    """
    normalized_version = str(version or "").strip()
    en = _REVIEW_WHITESPACE.sub("", str(raw_en or ""))
    cn = _REVIEW_WHITESPACE.sub("", str(raw_cn or ""))

    def digest(text: str) -> str:
        return hashlib.sha256(
            f"{normalized_version}\n{text}".encode("utf-8")
        ).hexdigest()

    return digest(en or cn), digest(cn or en)


def review_fingerprint(version: str, raw_cn: str, raw_en: str) -> str:
    """主指纹（英文侧优先，英文缺失时退回中文）。见 review_fingerprints。"""
    return review_fingerprints(version, raw_cn, raw_en)[0]


def _review_excerpt(raw_cn: str, raw_en: str, limit: int = 120) -> str:
    text = _REVIEW_WHITESPACE.sub(" ", str(raw_cn or raw_en or "")).strip()
    return text[:limit]


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._active_connection: ContextVar[sqlite3.Connection | None] = ContextVar(
            "database_active_connection", default=None
        )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        active = self._active_connection.get()
        if active is not None:
            yield active
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """在当前执行上下文中复用既有写入方法，一次提交或整体回滚。"""
        active = self._active_connection.get()
        if active is not None:
            yield active
            return
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            token = self._active_connection.set(connection)
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            finally:
                self._active_connection.reset(token)

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
        self._apply_migrations()
        with self.connect() as connection:
            self._deduplicate_terms(connection)
            self._flag_duplicate_features(connection)
        self.auto_approve_pending_bugs()

    def _migrations(self) -> tuple[tuple[int, str, Any], ...]:
        """迁移注册表：`(版本号, 名称, 迁移函数)`，按版本号升序执行。

        新增迁移在此追加；**不要修改已发布迁移的行为**，否则老库与克隆库会得到
        不同的结构。需要变更历史结构时追加一个新版本号。
        """
        return (
            (1, "legacy-schema-adoption", self._adopt_legacy_schema),
            (2, "review-decisions", self._add_review_decisions),
            (3, "knowledge-hub-core", self._add_knowledge_hub_core),
            (4, "controlled-documents", self._add_controlled_documents),
            (5, "strategy-and-registration", self._add_strategy_and_registration),
            (6, "model-mappings", self._add_model_mappings),
            (7, "item-evidence-links", self._add_item_evidence_links),
            (8, "registration-unit-dimension", self._add_registration_unit_dimension),
            (9, "item-source-traceability", self._add_item_source_traceability),
            (10, "change-event-categories", self._widen_change_event_categories),
            (11, "product-states", self._add_product_states),
            (12, "qa-loop", self._add_qa_loop),
            (13, "qa-uncovered-questions", self._add_qa_uncovered_questions),
            (14, "qa-structured-signature", self._add_qa_structured_signature),
        )

    def _apply_migrations(self) -> None:
        """按版本号执行迁移。

        每个迁移在其自身事务内执行：迁移体与版本登记在同一事务提交，因此失败时
        整体回滚且不登记版本，下次启动会重试。已登记的版本不再重复执行，从而避免
        每次启动都改写 schema（见 docs/handover/I00-备份恢复操作记录.md §6.2）。

        注意：`connect()` 使用 sqlite3 的默认隔离级别，此时只有 DML 会自动开启事务，
        **DDL 会被立即自动提交**。迁移体以 DDL 为主，因此这里显式 `BEGIN`，否则失败
        的迁移会留下已建好的表或已加的列。
        """
        with self.connect() as connection:
            connection.execute(MIGRATIONS_TABLE_SQL)
            applied = {
                row["version"]
                for row in connection.execute("SELECT version FROM schema_migrations")
            }
        for version, name, migrate in self._migrations():
            if version in applied:
                continue
            with self.connect() as connection:
                if not connection.in_transaction:
                    connection.execute("BEGIN")
                try:
                    migrate(connection)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                        (version, name),
                    )
                except Exception:
                    connection.rollback()
                    raise

    @staticmethod
    def _widen_change_event_categories(connection: sqlite3.Connection) -> None:
        """迁移 010：放宽 `change_events.category` 的取值约束。

        历史问题：约束只有 (function, image, bug, config, remark) 五个值，而抽取器还
        会产生 probe（探头更新/导入）与 unclassified（章节无法判定），现在再加
        config_note（配置/兼容性说明）。`import_candidates` 的分类约束早先已放宽，于是
        出现“候选能存、批准写入 change_events 时报 CHECK constraint failed”的缺陷：
        16 条 probe 候选在界面上点“仅入版本”必然失败。

        SQLite 不能修改 CHECK，只能重建表后回填。幂等：表定义里已含 config_note 则跳过。
        """
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'change_events'"
        ).fetchone()
        if row is None or "config_note" in (row["sql"] or ""):
            return
        allowed = ", ".join(f"'{category}'" for category in CHANGE_CATEGORIES)
        connection.commit()
        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.execute(
                f"""
                CREATE TABLE change_events_new (
                    id INTEGER PRIMARY KEY,
                    release_id INTEGER NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
                    category TEXT NOT NULL CHECK(category IN ({allowed})),
                    canonical_key TEXT NOT NULL DEFAULT '',
                    title_cn TEXT NOT NULL DEFAULT '',
                    title_en TEXT NOT NULL DEFAULT '',
                    description_cn TEXT NOT NULL DEFAULT '',
                    description_en TEXT NOT NULL DEFAULT '',
                    feature_id INTEGER REFERENCES features(id) ON DELETE SET NULL,
                    source_document_id INTEGER REFERENCES source_documents(id) ON DELETE SET NULL,
                    review_status TEXT NOT NULL DEFAULT 'approved',
                    confidence REAL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                INSERT INTO change_events_new(
                    id, release_id, category, canonical_key, title_cn, title_en,
                    description_cn, description_en, feature_id, source_document_id,
                    review_status, confidence, created_at
                )
                SELECT id, release_id, category, canonical_key, title_cn, title_en,
                       description_cn, description_en, feature_id, source_document_id,
                       review_status, confidence, created_at
                FROM change_events
                """
            )
            connection.execute("DROP TABLE change_events")
            connection.execute("ALTER TABLE change_events_new RENAME TO change_events")
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS change_event_identity
                ON change_events(release_id, category, canonical_key)
                """
            )
            connection.commit()
        finally:
            connection.execute("PRAGMA foreign_keys = ON")

    @staticmethod
    def _add_review_decisions(connection: sqlite3.Connection) -> None:
        """迁移 002：建立审核结论的稳定载体（见 REVIEW_DECISIONS_TABLE_SQL）。"""
        connection.execute(REVIEW_DECISIONS_TABLE_SQL)
        connection.execute(REVIEW_DECISIONS_INDEX_SQL)

    @staticmethod
    def _add_knowledge_hub_core(connection: sqlite3.Connection) -> None:
        """迁移 003：知识中枢基础结构（分类树、条目、标签、探头关系、审核留痕、问题单）。"""
        for statement in (
            KNOWLEDGE_ITEMS_TABLE_SQL,
            KNOWLEDGE_ITEMS_SQL,
            KNOWLEDGE_TAGS_SQL,
            PROBE_VERSIONS_SQL,
            KNOWLEDGE_REVIEW_RECORDS_SQL,
            KNOWLEDGE_ISSUES_SQL,
        ):
            connection.execute(statement)
        connection.executemany(
            """
            INSERT INTO kh_categories(code, name, parent_code, level, sort_order)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                name = excluded.name,
                parent_code = excluded.parent_code,
                level = excluded.level,
                sort_order = excluded.sort_order
            """,
            KNOWLEDGE_CATEGORY_SEED,
        )

    @staticmethod
    def _add_controlled_documents(connection: sqlite3.Connection) -> None:
        """迁移 004：受控资料、版本与证据。"""
        for statement in (
            DOCUMENTS_TABLE_SQL,
            DOCUMENT_VERSIONS_TABLE_SQL,
            EVIDENCE_TABLE_SQL,
        ):
            connection.execute(statement)

    @staticmethod
    def _add_strategy_and_registration(connection: sqlite3.Connection) -> None:
        """迁移 005：产品策略快照与注册全集/排除/派生。"""
        for statement in (
            STRATEGY_SNAPSHOTS_SQL,
            STRATEGY_VALUES_SQL,
            REGISTRATION_SCOPES_SQL,
            REGISTRATION_EXCLUSIONS_SQL,
            REGISTRATION_RELATIONS_SQL,
        ):
            connection.execute(statement)

    @staticmethod
    def _add_model_mappings(connection: sqlite3.Connection) -> None:
        """迁移 006：衍生型号 → 基础型号映射，以及源系统型号身份。"""
        connection.execute(MODEL_MAPPINGS_SQL)
        connection.execute(MODEL_SOURCE_LINKS_SQL)

    @staticmethod
    def _add_item_evidence_links(connection: sqlite3.Connection) -> None:
        """迁移 007：条目与证据的多对多关联（答案→条目→原文定位）。"""
        connection.execute(ITEM_EVIDENCE_SQL)

    @staticmethod
    def _add_registration_unit_dimension(connection: sqlite3.Connection) -> None:
        """迁移 008：派生关系带注册单元（证书号）。

        产品负责人 2026-09-14 裁定：**按注册单元分别呈现，不做并集** —— 同一机型可
        出现在多张注册证下（如 VINNO 10 同时在 苏械注准20232061322 与
        湘械注准20222062053），并集会把不同证书的适用范围混为一个数字。
        """
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(kh_registration_relations)")
        }
        if "certificate_no" not in columns:
            connection.execute(
                "ALTER TABLE kh_registration_relations "
                "ADD COLUMN certificate_no TEXT NOT NULL DEFAULT ''"
            )

    @staticmethod
    def _add_item_source_traceability(connection: sqlite3.Connection) -> None:
        """迁移 009：条目记录来源候选 id，使证据链可精确回溯。

        背景：条目原先只按名称匹配来源，而导入时条目名会被规范化（如
        `主推探头（4 型号）` → `主推探头`），导致 74 个条目只有 21 个能关联上证据。
        记录来源候选 id 后，可沿「条目 → 候选 → 来源文档版本 → 页码/条目」精确回溯。
        """
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(kh_items)")}
        if "source_candidate_id" not in columns:
            connection.execute(
                "ALTER TABLE kh_items ADD COLUMN source_candidate_id INTEGER"
            )

    @staticmethod
    def _add_product_states(connection: sqlite3.Connection) -> None:
        """迁移 011：显式产品状态、审核与失效历史。"""
        for statement in (
            PRODUCT_STATES_SQL,
            PRODUCT_STATES_INDEX_SQL,
            PRODUCT_STATES_LOOKUP_INDEX_SQL,
        ):
            connection.execute(statement)

    @staticmethod
    def _add_qa_loop(connection: sqlite3.Connection) -> None:
        for statement in QA_TABLES_SQL:
            connection.execute(statement)

    @staticmethod
    def _add_qa_uncovered_questions(connection: sqlite3.Connection) -> None:
        connection.execute("ALTER TABLE kh_qa_questions ADD COLUMN reason_code TEXT NOT NULL DEFAULT 'unanswered'")
        connection.execute("ALTER TABLE kh_qa_questions ADD COLUMN context_note TEXT NOT NULL DEFAULT ''")

    @staticmethod
    def _add_qa_structured_signature(connection: sqlite3.Connection) -> None:
        connection.execute("ALTER TABLE kh_qa_answers ADD COLUMN structured_signature TEXT")
        # Existing published answers have no structural baseline; require one review.
        connection.execute("UPDATE kh_qa_answers SET status = 'needs_review' WHERE status = 'published'")
        connection.execute(
            "UPDATE kh_qa_questions SET status = 'open', answer_id = NULL, answered_at = NULL WHERE answer_id IN (SELECT id FROM kh_qa_answers WHERE status = 'needs_review')"
        )

    @staticmethod
    def _adopt_legacy_schema(connection: sqlite3.Connection) -> None:
        release_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(releases)").fetchall()
        }
        if "project_id" not in release_columns:
            connection.commit()
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute(
                """
                CREATE TABLE releases_new (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id),
                    version TEXT NOT NULL,
                    product TEXT NOT NULL DEFAULT 'ULTIMUS G2',
                    domestic_release_date TEXT,
                    overseas_release_date TEXT,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(project_id, version)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO releases_new(
                    id, project_id, version, product, domestic_release_date,
                    overseas_release_date, notes, created_at
                )
                SELECT id, 1, version, product, domestic_release_date,
                       overseas_release_date, notes, created_at
                FROM releases
                """
            )
            connection.execute("DROP TABLE releases")
            connection.execute("ALTER TABLE releases_new RENAME TO releases")
            connection.commit()
            connection.execute("PRAGMA foreign_keys = ON")
        candidate_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(import_candidates)").fetchall()
        }
        if "manually_edited" not in candidate_columns:
            connection.execute(
                "ALTER TABLE import_candidates "
                "ADD COLUMN manually_edited INTEGER NOT NULL DEFAULT 0"
            )
        term_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(terms)").fetchall()
        }
        if "entry_type" not in term_columns:
            connection.execute(
                "ALTER TABLE terms ADD COLUMN entry_type TEXT NOT NULL DEFAULT 'term'"
            )
        feature_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(features)").fetchall()
        }
        if "parent_feature_id" not in feature_columns:
            connection.execute(
                "ALTER TABLE features ADD COLUMN parent_feature_id INTEGER REFERENCES features(id)"
            )
        if "category" not in feature_columns:
            connection.execute(
                "ALTER TABLE features ADD COLUMN category TEXT NOT NULL DEFAULT ''"
            )
        if "project_id" not in feature_columns:
            connection.execute(
                "ALTER TABLE features ADD COLUMN project_id INTEGER NOT NULL DEFAULT 1"
            )
        # 用 IF NOT EXISTS 取代每次 DROP+CREATE：触发器定义未变时不再产生 schema
        # 变更。迁移 001 只执行一次，因此重复启动不再重写数据库文件头。
        connection.execute(
            """
            CREATE TRIGGER IF NOT EXISTS prevent_duplicate_feature_names_on_insert
            BEFORE INSERT ON features
            WHEN EXISTS (
                SELECT 1 FROM features
                WHERE project_id = NEW.project_id
                  AND (cn_name = NEW.cn_name COLLATE NOCASE
                       OR en_name = NEW.en_name COLLATE NOCASE)
            )
            BEGIN
                SELECT RAISE(ABORT, 'duplicate feature name');
            END
            """
        )
        connection.execute(
            """
            CREATE TRIGGER IF NOT EXISTS prevent_duplicate_feature_names_on_update
            BEFORE UPDATE OF cn_name, en_name, project_id ON features
            WHEN EXISTS (
                SELECT 1 FROM features
                WHERE id != OLD.id AND project_id = NEW.project_id
                  AND (cn_name = NEW.cn_name COLLATE NOCASE
                       OR en_name = NEW.en_name COLLATE NOCASE)
            )
            BEGIN
                SELECT RAISE(ABORT, 'duplicate feature name');
            END
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO product_categories(name)
            SELECT category FROM terms WHERE TRIM(category) != ''
            UNION
            SELECT category FROM features WHERE TRIM(category) != ''
            """
        )
        source_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(source_documents)").fetchall()
        }
        if "content" not in source_columns:
            connection.execute(
                "ALTER TABLE source_documents ADD COLUMN content TEXT NOT NULL DEFAULT ''"
            )
        if "tables_json" not in source_columns:
            connection.execute(
                "ALTER TABLE source_documents ADD COLUMN tables_json TEXT NOT NULL DEFAULT '[]'"
            )

    @staticmethod
    def _flag_duplicate_features(connection: sqlite3.Connection) -> None:
        for language, column in (("中文", "cn_name"), ("英文", "en_name")):
            groups = connection.execute(
                f"""
                SELECT project_id, {column} AS name, GROUP_CONCAT(id) AS feature_ids
                FROM features
                GROUP BY project_id, {column} COLLATE NOCASE
                HAVING COUNT(*) > 1
                """
            ).fetchall()
            for group in groups:
                message = (
                    f"发现重复的{language}功能名称“{group['name']}”，功能 ID："
                    f"{group['feature_ids']}。建立功能时请明确选择具体档案，并安排合并旧档案。"
                )
                connection.execute(
                    """
                    INSERT INTO review_issues(issue_type, message)
                    SELECT 'duplicate_feature', ?
                    WHERE NOT EXISTS (
                        SELECT 1 FROM review_issues
                        WHERE issue_type = 'duplicate_feature' AND message = ? AND status = 'open'
                    )
                    """,
                    (message, message),
                )

    @staticmethod
    def _deduplicate_terms(connection: sqlite3.Connection) -> None:
        duplicate_groups = connection.execute(
            """
            SELECT cn_name, en_name, MIN(id) AS keeper_id
            FROM terms
            WHERE parent_id IS NULL
            GROUP BY cn_name, en_name
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        for group in duplicate_groups:
            duplicate_parents = connection.execute(
                """
                SELECT id FROM terms
                WHERE parent_id IS NULL AND cn_name = ? AND en_name = ? AND id != ?
                """,
                (group["cn_name"], group["en_name"], group["keeper_id"]),
            ).fetchall()
            for duplicate in duplicate_parents:
                children = connection.execute(
                    "SELECT * FROM terms WHERE parent_id = ?", (duplicate["id"],)
                ).fetchall()
                for child in children:
                    keeper_child = connection.execute(
                        """
                        SELECT id FROM terms
                        WHERE parent_id = ? AND cn_name = ? AND en_name = ?
                        """,
                        (group["keeper_id"], child["cn_name"], child["en_name"]),
                    ).fetchone()
                    if keeper_child:
                        connection.execute(
                            "UPDATE features SET term_id = ? WHERE term_id = ?",
                            (keeper_child["id"], child["id"]),
                        )
                        connection.execute("DELETE FROM terms WHERE id = ?", (child["id"],))
                    else:
                        connection.execute(
                            "UPDATE terms SET parent_id = ? WHERE id = ?",
                            (group["keeper_id"], child["id"]),
                        )
                connection.execute(
                    "UPDATE features SET term_id = ? WHERE term_id = ?",
                    (group["keeper_id"], duplicate["id"]),
                )
                connection.execute("DELETE FROM terms WHERE id = ?", (duplicate["id"],))

    def default_project_id(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id FROM projects ORDER BY is_default DESC, id LIMIT 1"
            ).fetchone()
            if row is None:
                raise KeyError("project")
            return int(row["id"])

    def list_projects(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            projects = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT project.*,
                           (SELECT COUNT(*) FROM releases WHERE project_id = project.id) AS release_count,
                           (SELECT COUNT(*) FROM features WHERE project_id = project.id) AS feature_count,
                           (SELECT COUNT(*) FROM import_candidates candidate
                            JOIN releases release ON release.id = candidate.release_id
                            WHERE release.project_id = project.id AND candidate.status = 'pending') AS review_count
                    FROM projects project
                    ORDER BY project.is_default DESC, project.name
                    """
                ).fetchall()
            ]
            for project in projects:
                project["sources"] = [
                    {
                        **dict(source),
                        "file_keywords": json.loads(source["file_keywords_json"]),
                    }
                    for source in connection.execute(
                        "SELECT * FROM project_sources WHERE project_id = ? ORDER BY id",
                        (project["id"],),
                    ).fetchall()
                ]
            return projects

    def get_project(self, project_id: int) -> dict[str, Any]:
        projects = {int(item["id"]): item for item in self.list_projects()}
        if project_id not in projects:
            raise KeyError(project_id)
        return projects[project_id]

    def create_project(
        self,
        name: str,
        code: str,
        source_root: str = "",
        file_keywords: list[str] | None = None,
    ) -> dict[str, Any]:
        normalized_name = name.strip()
        normalized_code = code.strip().upper()
        if not normalized_name or not normalized_code:
            raise ValueError("Project name and code are required")
        if source_root and not Path(source_root).expanduser().is_dir():
            raise ValueError("Release Note source directory does not exist")
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO projects(name, code) VALUES (?, ?)",
                (normalized_name, normalized_code),
            )
            project_id = int(cursor.lastrowid)
        if source_root:
            self.add_project_source(project_id, source_root, file_keywords=file_keywords)
        return self.get_project(project_id)

    def add_project_source(
        self,
        project_id: int,
        path: str,
        label: str = "Release Note",
        file_keywords: list[str] | None = None,
    ) -> dict[str, Any]:
        source_path = Path(path).expanduser()
        if not source_path.is_dir():
            raise ValueError("Release Note source directory does not exist")
        keywords = [str(keyword).strip() for keyword in (file_keywords or []) if str(keyword).strip()]
        with self.connect() as connection:
            if connection.execute(
                "SELECT 1 FROM projects WHERE id = ?", (project_id,)
            ).fetchone() is None:
                raise KeyError(project_id)
            connection.execute(
                """
                INSERT INTO project_sources(project_id, path, label, file_keywords_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    project_id = excluded.project_id,
                    label = excluded.label,
                    file_keywords_json = excluded.file_keywords_json,
                    enabled = 1
                """,
                (
                    project_id,
                    str(source_path),
                    label.strip() or "Release Note",
                    json.dumps(keywords, ensure_ascii=False),
                ),
            )
        return self.get_project(project_id)

    def create_feature(
        self,
        cn_name: str,
        en_name: str,
        cn_description: str,
        en_description: str,
        term_id: int | None = None,
        parent_feature_id: int | None = None,
        category: str = "",
        project_id: int | None = None,
    ) -> int:
        normalized_category = category.strip()
        selected_project_id = project_id or self.default_project_id()
        with self.connect() as connection:
            self._register_product_category(connection, normalized_category)
            cursor = connection.execute(
                """
                INSERT INTO features(
                    project_id, term_id, parent_feature_id, cn_name, en_name,
                    category, cn_description, en_description
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    selected_project_id,
                    term_id,
                    parent_feature_id,
                    cn_name.strip(),
                    en_name.strip(),
                    normalized_category,
                    cn_description.strip(),
                    en_description.strip(),
                ),
            )
            feature_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO feature_revisions(
                    feature_id, revision_number, cn_description, en_description, review_status
                ) VALUES (?, 1, ?, ?, 'approved')
                """,
                (feature_id, cn_description.strip(), en_description.strip()),
            )
            return feature_id

    def get_feature(self, feature_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM features WHERE id = ?", (feature_id,)).fetchone()
            if row is None:
                raise KeyError(feature_id)
            feature = dict(row)
            tracks = {"domestic": [], "overseas": []}
            track_rows = connection.execute(
                """
                SELECT fmr.market, r.version,
                       CASE fmr.market
                           WHEN 'domestic' THEN r.domestic_release_date
                           ELSE r.overseas_release_date
                       END AS release_date
                FROM feature_market_releases fmr
                JOIN releases r ON r.id = fmr.release_id
                WHERE fmr.feature_id = ?
                """,
                (feature_id,),
            ).fetchall()
            ordered = sorted(track_rows, key=lambda item: tuple(int(part) for part in item["version"].split(".")))
            for track in ordered:
                tracks[track["market"]].append(
                    {"version": track["version"], "release_date": track["release_date"]}
                )
            feature["market_releases"] = tracks
            feature["description_title_only"] = description_is_title_only(
                feature["cn_description"], feature["en_description"]
            )
            feature["revisions"] = [
                dict(revision)
                for revision in connection.execute(
                    """
                    SELECT id, revision_number, cn_description, en_description,
                           review_status, created_at
                    FROM feature_revisions
                    WHERE feature_id = ?
                    ORDER BY revision_number
                    """,
                    (feature_id,),
                ).fetchall()
            ]
            feature["children"] = [
                dict(child)
                for child in connection.execute(
                    """
                    SELECT * FROM features
                    WHERE parent_feature_id = ?
                    ORDER BY cn_name
                    """,
                    (feature_id,),
                ).fetchall()
            ]
            feature["notes"] = [
                dict(note)
                for note in connection.execute(
                    """
                    SELECT * FROM feature_notes
                    WHERE feature_id = ?
                    ORDER BY id
                    """,
                    (feature_id,),
                ).fetchall()
            ]
            return feature

    def get_feature_timeline(self, feature_id: int) -> dict[str, Any]:
        """Combine description revisions and linked release changes into one audit trail."""
        feature = self.get_feature(feature_id)
        with self.connect() as connection:
            revision_rows = connection.execute(
                """
                SELECT id, revision_number, cn_description, en_description,
                       review_status, created_at
                FROM feature_revisions
                WHERE feature_id = ?
                ORDER BY revision_number
                """,
                (feature_id,),
            ).fetchall()
            change_rows = connection.execute(
                """
                SELECT event.id, event.release_id, release.version,
                       event.title_cn, event.title_en,
                       event.description_cn, event.description_en,
                       event.review_status, event.created_at
                FROM change_events event
                JOIN releases release ON release.id = event.release_id
                WHERE event.feature_id = ?
                ORDER BY event.id
                """,
                (feature_id,),
            ).fetchall()
            market_rows = connection.execute(
                """
                SELECT release_id, market
                FROM feature_market_releases
                WHERE feature_id = ?
                ORDER BY CASE market WHEN 'domestic' THEN 0 ELSE 1 END
                """,
                (feature_id,),
            ).fetchall()
        markets_by_release: dict[int, list[str]] = {}
        for market in market_rows:
            markets_by_release.setdefault(int(market["release_id"]), []).append(market["market"])
        events: list[dict[str, Any]] = [
            {"kind": "revision", **dict(row)} for row in revision_rows
        ]
        events.extend(
            {
                "kind": "release",
                **dict(row),
                "markets": markets_by_release.get(int(row["release_id"]), []),
            }
            for row in change_rows
        )
        return {
            "feature": {
                "id": feature["id"],
                "cn_name": feature["cn_name"],
                "en_name": feature["en_name"],
                "category": feature["category"],
            },
            "events": events,
        }

    def create_child_feature(
        self,
        parent_feature_id: int,
        cn_name: str,
        en_name: str,
        cn_description: str = "",
        en_description: str = "",
        category: str = "",
    ) -> int:
        with self.connect() as connection:
            parent = connection.execute(
                "SELECT project_id FROM features WHERE id = ?", (parent_feature_id,)
            ).fetchone()
            if parent is None:
                raise KeyError(parent_feature_id)
        return self.create_feature(
            cn_name,
            en_name,
            cn_description,
            en_description,
            parent_feature_id=parent_feature_id,
            category=category,
            project_id=int(parent["project_id"]),
        )

    def add_feature_note(
        self,
        feature_id: int,
        cn_content: str,
        en_content: str = "",
    ) -> int:
        if not cn_content.strip():
            raise ValueError("Parent notes require Chinese content")
        with self.connect() as connection:
            if connection.execute(
                "SELECT 1 FROM features WHERE id = ?", (feature_id,)
            ).fetchone() is None:
                raise KeyError(feature_id)
            cursor = connection.execute(
                """
                INSERT INTO feature_notes(feature_id, cn_content, en_content)
                VALUES (?, ?, ?)
                """,
                (feature_id, cn_content.strip(), en_content.strip()),
            )
            return int(cursor.lastrowid)

    def update_feature(
        self,
        feature_id: int,
        cn_name: str,
        en_name: str,
        cn_description: str,
        en_description: str,
        category: str | None = None,
    ) -> dict[str, Any]:
        updated_cn = cn_name.strip()
        updated_en = en_name.strip()
        updated_cn_description = cn_description.strip()
        updated_en_description = en_description.strip()
        if not updated_cn or not updated_en:
            raise ValueError("Features require Chinese and English names")
        if bool(updated_cn_description) != bool(updated_en_description):
            raise ValueError("Feature descriptions must be bilingual when provided")
        with self.connect() as connection:
            current = connection.execute(
                "SELECT * FROM features WHERE id = ?", (feature_id,)
            ).fetchone()
            if current is None:
                raise KeyError(feature_id)
            updated_category = (
                current["category"] if category is None else category.strip()
            )
            self._register_product_category(connection, updated_category)
            description_changed = (
                current["cn_description"] != updated_cn_description
                or current["en_description"] != updated_en_description
            )
            connection.execute(
                """
                UPDATE features
                SET cn_name = ?, en_name = ?, category = ?,
                    cn_description = ?, en_description = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    updated_cn,
                    updated_en,
                    updated_category,
                    updated_cn_description,
                    updated_en_description,
                    feature_id,
                ),
            )
            if description_changed:
                revision_number = connection.execute(
                    """
                    SELECT COALESCE(MAX(revision_number), 0) + 1
                    FROM feature_revisions WHERE feature_id = ?
                    """,
                    (feature_id,),
                ).fetchone()[0]
                connection.execute(
                    """
                    INSERT INTO feature_revisions(
                        feature_id, revision_number, cn_description,
                        en_description, review_status
                    ) VALUES (?, ?, ?, ?, 'approved')
                    """,
                    (
                        feature_id,
                        revision_number,
                        updated_cn_description,
                        updated_en_description,
                    ),
                )
        return self.get_feature(feature_id)

    def add_feature_revision(
        self,
        feature_id: int,
        cn_description: str,
        en_description: str,
        review_status: str = "pending",
    ) -> int:
        if review_status not in {"pending", "approved", "rejected"}:
            raise ValueError(f"Unsupported review status: {review_status}")
        if review_status == "approved" and (not cn_description.strip() or not en_description.strip()):
            raise ValueError("Approved revisions require both language descriptions")
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(revision_number), 0) + 1 AS next_revision FROM feature_revisions WHERE feature_id = ?",
                (feature_id,),
            ).fetchone()
            revision_number = int(row["next_revision"])
            cursor = connection.execute(
                """
                INSERT INTO feature_revisions(
                    feature_id, revision_number, cn_description, en_description, review_status
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    feature_id,
                    revision_number,
                    cn_description.strip(),
                    en_description.strip(),
                    review_status,
                ),
            )
            if review_status == "approved":
                connection.execute(
                    """
                    UPDATE features
                    SET cn_description = ?, en_description = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (cn_description.strip(), en_description.strip(), feature_id),
                )
            return int(cursor.lastrowid)

    def list_features(
        self, query: str = "", project_id: int | None = None
    ) -> list[dict[str, Any]]:
        selected_project_id = project_id or self.default_project_id()
        sql = """SELECT feature.*, parent.cn_name AS parent_cn_name,
                        parent.en_name AS parent_en_name
                 FROM features AS feature
                 LEFT JOIN features AS parent ON parent.id = feature.parent_feature_id"""
        params: tuple[Any, ...] = (selected_project_id,)
        sql += " WHERE feature.project_id = ?"
        if query:
            sql += " AND (feature.cn_name LIKE ? OR feature.en_name LIKE ? OR feature.cn_description LIKE ? OR feature.en_description LIKE ?)"
            pattern = f"%{query}%"
            params = (selected_project_id, pattern, pattern, pattern, pattern)
        sql += " ORDER BY feature.parent_feature_id IS NOT NULL, feature.cn_name"
        with self.connect() as connection:
            return [
                self._with_description_flag(dict(row))
                for row in connection.execute(sql, params).fetchall()
            ]

    def search_feature_matches(
        self, query: str, limit: int = 10, project_id: int | None = None
    ) -> list[dict[str, Any]]:
        keyword = query.strip()
        if not keyword:
            return []
        pattern = f"%{keyword}%"
        selected_project_id = project_id or self.default_project_id()
        with self.connect() as connection:
            feature_rows = connection.execute(
                """
                SELECT feature.id, feature.cn_name, feature.en_name, feature.category,
                       CASE WHEN feature.cn_name = ? COLLATE NOCASE
                                  OR feature.en_name = ? COLLATE NOCASE
                            THEN 1 ELSE 0 END AS exact
                       ,CASE WHEN
                            (SELECT COUNT(*) FROM features AS duplicate
                             WHERE duplicate.project_id = feature.project_id
                               AND duplicate.cn_name = feature.cn_name COLLATE NOCASE) > 1
                            OR
                            (SELECT COUNT(*) FROM features AS duplicate
                             WHERE duplicate.project_id = feature.project_id
                               AND duplicate.en_name = feature.en_name COLLATE NOCASE) > 1
                            THEN 1 ELSE 0 END AS conflict
                FROM features AS feature
                WHERE feature.project_id = ?
                  AND (feature.cn_name LIKE ? COLLATE NOCASE
                   OR feature.en_name LIKE ? COLLATE NOCASE)
                ORDER BY exact DESC, cn_name
                LIMIT ?
                """,
                (keyword, keyword, selected_project_id, pattern, pattern, limit),
            ).fetchall()
            term_rows = connection.execute(
                """
                SELECT id, cn_name, en_name, category,
                       CASE WHEN cn_name = ? COLLATE NOCASE OR en_name = ? COLLATE NOCASE
                            THEN 1 ELSE 0 END AS exact
                FROM terms
                WHERE (cn_name LIKE ? COLLATE NOCASE OR en_name LIKE ? COLLATE NOCASE)
                  AND en_name NOT IN ('', '—')
                  AND needs_review = 0
                  AND entry_type = 'term'
                ORDER BY exact DESC, parent_id IS NOT NULL, id
                LIMIT ?
                """,
                (keyword, keyword, pattern, pattern, limit),
            ).fetchall()

        matches = [
            {
                "source": source,
                "id": int(row["id"]),
                "cn_name": row["cn_name"],
                "en_name": row["en_name"],
                "category": row["category"],
                "exact": bool(row["exact"]),
                "conflict": bool(row["conflict"]) if source == "feature" else False,
            }
            for source, rows in (("feature", feature_rows), ("term", term_rows))
            for row in rows
        ]
        return sorted(
            matches,
            key=lambda item: (
                0 if item["source"] == "feature" and item["exact"] else
                1 if item["source"] == "term" and item["exact"] else
                2 if item["source"] == "feature" else 3,
                item["cn_name"],
            ),
        )[:limit]

    def upsert_release(
        self,
        version: str,
        domestic_release_date: str | None = None,
        overseas_release_date: str | None = None,
        notes: str = "",
        project_id: int | None = None,
    ) -> int:
        selected_project_id = project_id or self.default_project_id()
        with self.connect() as connection:
            project = connection.execute(
                "SELECT name FROM projects WHERE id = ?", (selected_project_id,)
            ).fetchone()
            if project is None:
                raise KeyError(selected_project_id)
            connection.execute(
                """
                INSERT INTO releases(
                    project_id, version, product, domestic_release_date,
                    overseas_release_date, notes
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, version) DO UPDATE SET
                    domestic_release_date = COALESCE(excluded.domestic_release_date, releases.domestic_release_date),
                    overseas_release_date = COALESCE(excluded.overseas_release_date, releases.overseas_release_date),
                    notes = CASE WHEN excluded.notes = '' THEN releases.notes ELSE excluded.notes END
                """,
                (
                    selected_project_id,
                    version,
                    project["name"],
                    domestic_release_date,
                    overseas_release_date,
                    notes,
                ),
            )
            row = connection.execute(
                "SELECT id FROM releases WHERE project_id = ? AND version = ?",
                (selected_project_id, version),
            ).fetchone()
            return int(row["id"])

    def list_releases(self, project_id: int | None = None) -> list[dict[str, Any]]:
        selected_project_id = project_id or self.default_project_id()
        with self.connect() as connection:
            rows = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT release.*,
                           (
                               SELECT COUNT(*) FROM source_documents source
                               WHERE source.release_id = release.id
                                 AND source.tables_json != '[]'
                           ) AS configuration_table_count
                           ,(
                               SELECT COUNT(*) FROM release_tables table_data
                               WHERE table_data.release_id = release.id
                                 AND table_data.table_type != 'other'
                           ) AS structured_table_count
                           ,(
                               SELECT COUNT(*) FROM release_table_rows table_row
                               WHERE table_row.release_id = release.id
                                 AND table_row.pair_status = 'conflict'
                           ) AS structured_conflict_count
                    FROM releases release
                    WHERE release.project_id = ?
                    """,
                    (selected_project_id,),
                ).fetchall()
            ]
        by_version = {row["version"]: row for row in rows}
        return [by_version[version] for version in sort_versions(by_version, reverse=True)]

    def create_import_batch(
        self,
        project_id: int,
        ready_only: bool,
        source_summary: str,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO import_batches(project_id, ready_only, source_summary)
                VALUES (?, ?, ?)
                """,
                (project_id, int(ready_only), source_summary.strip()),
            )
            return int(cursor.lastrowid)

    def complete_import_batch(
        self,
        batch_id: int,
        versions: list[str],
        preexisting_versions: set[str],
        stats: dict[str, Any],
    ) -> dict[str, Any]:
        unique_versions = list(dict.fromkeys(versions))
        with self.connect() as connection:
            batch = connection.execute(
                "SELECT project_id FROM import_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            if batch is None:
                raise KeyError(batch_id)
            for version in unique_versions:
                release = connection.execute(
                    "SELECT id FROM releases WHERE project_id = ? AND version = ?",
                    (batch["project_id"], version),
                ).fetchone()
                if release is None:
                    continue
                connection.execute(
                    """
                    INSERT OR REPLACE INTO import_batch_releases(
                        batch_id, release_id, version, was_existing
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (batch_id, release["id"], version, int(version in preexisting_versions)),
                )
            undoable = bool(unique_versions) and not any(
                version in preexisting_versions for version in unique_versions
            )
            connection.execute(
                """
                UPDATE import_batches
                SET status = 'completed', stats_json = ?, undoable = ?,
                    completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (json.dumps(stats, ensure_ascii=False), int(undoable), batch_id),
            )
        return self.get_import_batch(batch_id)

    def fail_import_batch(self, batch_id: int, message: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE import_batches
                SET status = 'failed', stats_json = ?, completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (json.dumps({"error": message}, ensure_ascii=False), batch_id),
            )

    def get_import_batch(self, batch_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM import_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            if row is None:
                raise KeyError(batch_id)
            item = dict(row)
            item["versions"] = [
                release["version"]
                for release in connection.execute(
                    """
                    SELECT version FROM import_batch_releases
                    WHERE batch_id = ? ORDER BY version
                    """,
                    (batch_id,),
                ).fetchall()
            ]
        item["stats"] = json.loads(item.pop("stats_json") or "{}")
        item["ready_only"] = bool(item["ready_only"])
        item["undoable"] = bool(item["undoable"])
        return item

    def list_import_batches(self, project_id: int | None = None) -> list[dict[str, Any]]:
        selected_project_id = project_id or self.default_project_id()
        with self.connect() as connection:
            ids = [
                int(row["id"])
                for row in connection.execute(
                    "SELECT id FROM import_batches WHERE project_id = ? ORDER BY id DESC",
                    (selected_project_id,),
                ).fetchall()
            ]
        return [self.get_import_batch(batch_id) for batch_id in ids]

    def undo_import_batch(self, batch_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            batch = connection.execute(
                "SELECT * FROM import_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            if batch is None:
                raise KeyError(batch_id)
            if batch["status"] != "completed" or not batch["undoable"]:
                raise ValueError("该批次不可撤销：只有未修改过的全新版本批次可撤销。")
            release_ids = [
                int(row["release_id"])
                for row in connection.execute(
                    """
                    SELECT release_id FROM import_batch_releases
                    WHERE batch_id = ? AND release_id IS NOT NULL AND was_existing = 0
                    """,
                    (batch_id,),
                ).fetchall()
            ]
            if not release_ids:
                raise ValueError("该批次没有可撤销的新版本。")
            placeholders = ",".join("?" for _ in release_ids)
            reviewed = connection.execute(
                f"""
                SELECT 1 FROM import_candidates
                WHERE release_id IN ({placeholders})
                  AND (
                      manually_edited = 1 OR status = 'rejected'
                      OR (status = 'approved' AND category != 'bug')
                  )
                LIMIT 1
                """,
                release_ids,
            ).fetchone()
            linked = connection.execute(
                f"""
                SELECT 1 FROM feature_market_releases
                WHERE release_id IN ({placeholders}) LIMIT 1
                """,
                release_ids,
            ).fetchone()
            feature_change = connection.execute(
                f"""
                SELECT 1 FROM change_events
                WHERE release_id IN ({placeholders}) AND feature_id IS NOT NULL LIMIT 1
                """,
                release_ids,
            ).fetchone()
            if reviewed or linked or feature_change:
                raise ValueError("该批次已有人工审核或功能关联，为保护数据不能撤销。")
            connection.execute(
                f"DELETE FROM source_documents WHERE release_id IN ({placeholders})",
                release_ids,
            )
            connection.execute(
                f"DELETE FROM releases WHERE id IN ({placeholders})", release_ids
            )
            connection.execute(
                """
                UPDATE import_batches
                SET status = 'undone', undoable = 0, undone_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (batch_id,),
            )
        return {"batch_id": batch_id, "releases_removed": len(release_ids)}

    def link_feature_release(self, feature_id: int, release_id: int, market: str) -> None:
        if market not in {"domestic", "overseas"}:
            raise ValueError(f"Unsupported market: {market}")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO feature_market_releases(feature_id, release_id, market)
                VALUES (?, ?, ?)
                """,
                (feature_id, release_id, market),
            )

    def add_change(
        self,
        release_id: int,
        category: str,
        title_cn: str = "",
        title_en: str = "",
        description_cn: str = "",
        description_en: str = "",
        feature_id: int | None = None,
        canonical_key: str = "",
        review_status: str = "approved",
        confidence: float | None = None,
    ) -> int:
        if category not in CHANGE_CATEGORIES:
            raise ValueError(f"Unsupported change category: {category}")
        if category != "function" and feature_id is not None:
            raise ValueError("Only function changes may link to a feature")
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO change_events(
                    release_id, category, canonical_key, title_cn, title_en,
                    description_cn, description_en, feature_id, review_status, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    release_id,
                    category,
                    canonical_key,
                    title_cn,
                    title_en,
                    description_cn,
                    description_en,
                    feature_id,
                    review_status,
                    confidence,
                ),
            )
            return int(cursor.lastrowid)

    def list_changes(self, release_id: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM change_events"
        params: tuple[Any, ...] = ()
        if release_id is not None:
            sql += " WHERE release_id = ?"
            params = (release_id,)
        sql += " ORDER BY id"
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def release_search_coverage(self, project_id: int, *, all_projects: bool = False) -> list[dict[str, Any]]:
        """Count a version as covered only if the search adapters can read evidence."""
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(f'''
                SELECT r.version, (
                    EXISTS(SELECT 1 FROM source_documents s WHERE s.release_id=r.id
                        AND {_SEARCH_SOURCE_VISIBLE} AND trim(s.content)!='')
                    OR EXISTS(SELECT 1 FROM change_events c WHERE c.release_id=r.id
                        AND trim(c.title_cn || c.title_en || c.description_cn || c.description_en)!='')
                    OR EXISTS(SELECT 1 FROM import_candidates c WHERE c.release_id=r.id
                        AND {_SEARCH_CANDIDATE_VISIBLE} AND trim(c.title_cn || c.title_en || c.raw_cn || c.raw_en)!='')
                    OR EXISTS(SELECT 1 FROM release_table_rows t JOIN release_tables table_data ON table_data.id=t.table_id
                        WHERE t.release_id=r.id AND {_SEARCH_TABLE_VISIBLE})
                    OR EXISTS(SELECT 1 FROM feature_market_releases f WHERE f.release_id=r.id)
                ) AS has_evidence FROM releases r WHERE (? OR r.project_id=?)
            ''', (all_projects, project_id)).fetchall()]

    def search_release_history(
        self,
        query: str,
        project_id: int | None = None,
        all_projects: bool = False,
        result_type: str = "all",
    ) -> dict[str, Any]:
        normalized_query = query.strip()
        if not normalized_query:
            return {"first_version": None, "first_project_id": None, "results": []}
        pattern = f"%{normalized_query}%"
        selected_project_id = project_id or self.default_project_id()
        project_filter = "" if all_projects else " AND r.project_id = ?"

        def params(*values: Any) -> tuple[Any, ...]:
            return tuple(values) if all_projects else (*values, selected_project_id)

        def result_from_row(
            row: sqlite3.Row,
            status: str,
            searchable_details: tuple[tuple[str, str], ...] = (),
        ) -> dict[str, Any]:
            item = {
                "project_id": int(row["project_id"]),
                "project_name": row["project_name"],
                "version": row["version"],
                "category": row["category"],
                "title_cn": row["title_cn"],
                "title_en": row["title_en"],
                "status": status,
                "evidence_kind": ("current_description" if status == "功能档案" else
                                  "pending" if status == "待审核" else
                                  "bug_fix" if row["category"] == "bug" else "version_record"),
                "preview_id": f"release:{row['record_kind']}:{row['record_id']}",
                "locator": "中文记录" if normalized_query.casefold() in str(row["title_cn"]).casefold() else "English record",

            }
            title_matches = any(
                normalized_query.casefold() in str(row[column]).casefold()
                for column in ("title_cn", "title_en")
            )
            if not title_matches:
                for label, column in searchable_details:
                    text = str(row[column] or "")
                    if normalized_query.casefold() in text.casefold():
                        item["locator"] = "中文记录" if column.endswith("cn") or column.startswith("cn_") else "English record"
                        item["matched_field"] = label
                        item["matched_text"] = matching_excerpt(text, normalized_query)
                        break
            if row['record_kind'] == 'table':
                item['locator'] = '表格记录'
            return item

        with self.connect() as connection:
            released = [
                result_from_row(
                    row,
                    "已入版本",
                    (("版本描述", "description_cn"), ("版本描述", "description_en")),
                )
                for row in connection.execute(
                    """
                    SELECT e.id AS record_id, 'change' AS record_kind, r.project_id, project.name AS project_name,
                           r.version, e.category, e.title_cn, e.title_en,
                           e.description_cn, e.description_en
                    FROM change_events e
                    JOIN releases r ON r.id = e.release_id
                    JOIN projects project ON project.id = r.project_id
                    WHERE (e.title_cn LIKE ? OR e.title_en LIKE ?
                       OR e.description_cn LIKE ? OR e.description_en LIKE ?)
                    """ + project_filter,
                    params(pattern, pattern, pattern, pattern),
                ).fetchall()
            ]
            pending = [
                result_from_row(
                    row,
                    "待审核",
                    (("Release Note 原文", "raw_cn"), ("Release Note 原文", "raw_en")),
                )
                for row in connection.execute(
                    f"""
                    SELECT c.id AS record_id, 'candidate' AS record_kind, r.project_id, project.name AS project_name,
                           r.version, c.category, c.title_cn, c.title_en,
                           c.raw_cn, c.raw_en
                    FROM import_candidates c
                    JOIN releases r ON r.id = c.release_id
                    JOIN projects project ON project.id = r.project_id
                    WHERE {_SEARCH_CANDIDATE_VISIBLE}
                      AND (c.title_cn LIKE ? OR c.title_en LIKE ?
                           OR c.raw_cn LIKE ? OR c.raw_en LIKE ?)
                    """ + project_filter,
                    params(pattern, pattern, pattern, pattern),
                ).fetchall()
            ]
            feature_results = [
                result_from_row(
                    row,
                    "功能档案",
                    (("功能最终描述", "cn_description"), ("功能最终描述", "en_description")),
                )
                for row in connection.execute(
                    """
                    SELECT DISTINCT f.id AS record_id, 'feature' AS record_kind, r.project_id, project.name AS project_name,
                           r.version, 'function' AS category,
                           f.cn_name AS title_cn, f.en_name AS title_en,
                           f.cn_description, f.en_description
                    FROM features f
                    JOIN (
                        SELECT feature_id, release_id FROM feature_market_releases
                        UNION
                        SELECT feature_id, release_id FROM change_events
                        WHERE feature_id IS NOT NULL
                    ) linked ON linked.feature_id = f.id
                    JOIN releases r ON r.id = linked.release_id
                    JOIN projects project ON project.id = r.project_id
                    WHERE (f.cn_name LIKE ? OR f.en_name LIKE ?
                       OR f.cn_description LIKE ? OR f.en_description LIKE ?)
                    """ + project_filter,
                    params(pattern, pattern, pattern, pattern),
                ).fetchall()
            ]
            structured_results = [
                result_from_row(
                    row,
                    "结构化表格",
                    (("表格结构化行", "summary"), ("表格结构化行", "data_json")),
                )
                for row in connection.execute(
                    f"""
                    SELECT table_row.id AS record_id, 'table' AS record_kind, r.project_id, project.name AS project_name, r.version,
                           CASE table_data.table_type
                               WHEN 'image_comparison' THEN 'image'
                               WHEN 'ui_comparison' THEN 'function'
                               ELSE 'config'
                           END AS category,
                           CASE WHEN table_row.language = 'cn'
                                THEN table_row.item_name ELSE '' END AS title_cn,
                           CASE WHEN table_row.language = 'en'
                                THEN table_row.item_name ELSE '' END AS title_en,
                           table_row.summary, table_row.data_json
                    FROM release_table_rows table_row
                    JOIN release_tables table_data ON table_data.id = table_row.table_id
                    JOIN releases r ON r.id = table_row.release_id
                    JOIN projects project ON project.id = r.project_id
                    WHERE {_SEARCH_TABLE_VISIBLE}
                      AND (table_row.item_code LIKE ? OR table_row.item_name LIKE ?
                           OR table_row.summary LIKE ? OR table_row.data_json LIKE ?)
                    """ + project_filter,
                    params(pattern, pattern, pattern, pattern),
                ).fetchall()
            ]
            source_results = [
                {
                    "project_id": int(row["project_id"]),
                    "project_name": row["project_name"],
                    "version": row["version"],
                    "category": "source",
                    "title_cn": row["filename"] if row["language"] == "cn" else "",
                    "title_en": row["filename"] if row["language"] != "cn" else "",
                    "status": "Release Note原文",
                    "evidence_kind": "source_snapshot",
                    "preview_id": f"release:source:{row['source_id']}",
                    "locator": f"原文行 {next((n for n, line in enumerate(row['content'].splitlines(), 1) if normalized_query.casefold() in line.casefold()), 1)}",
                    "matched_field": "Release Note 原文",
                    "matched_text": matching_excerpt(row["content"], normalized_query),
                }
                for row in connection.execute(
                    f"""
                    SELECT s.id AS source_id, r.project_id, project.name AS project_name,
                           r.version, s.filename, s.language, s.content
                    FROM source_documents s
                    JOIN releases r ON r.id = s.release_id
                    JOIN projects project ON project.id = r.project_id
                    WHERE {_SEARCH_SOURCE_VISIBLE} AND s.content LIKE ?
                    """ + project_filter,
                    params(pattern),
                ).fetchall()
            ]
        results = sorted(
            structured_results + released + pending + feature_results + source_results,
            key=lambda item: (
                version_key(item["version"]),
                item["project_name"],
                {"结构化表格": 0, "已入版本": 1, "功能档案": 2, "待审核": 3}.get(
                    item["status"], 4
                ),
            ),
        )
        allowed_types = {"all", "source", "structured", *CHANGE_CATEGORIES}
        if result_type not in allowed_types:
            raise ValueError("不支持的搜索内容类型。")
        if result_type == "source":
            results = [item for item in results if item["status"] == "Release Note原文"]
        elif result_type == "structured":
            results = [item for item in results if item["status"] == "结构化表格"]
        elif result_type != "all":
            results = [item for item in results if item["category"] == result_type]
        # Current descriptions are not dated evidence. Bug fixes and unreviewed
        # candidates are useful leads, not a first-support assertion.
        dated = [item for item in results if item["evidence_kind"] not in
                 {"current_description", "bug_fix", "pending"}]
        first_project_id = dated[0]["project_id"] if dated else None
        if not all_projects:
            for item in results:
                item.pop("project_id", None)
                item.pop("project_name", None)
        response = {
            "first_version": dated[0]["version"] if dated else None,
            "results": results,
        }
        if all_projects:
            response["first_project_id"] = first_project_id
        return response

    def has_change(self, release_id: int, category: str, canonical_key: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM change_events
                WHERE release_id = ? AND category = ? AND canonical_key = ?
                """,
                (release_id, category, canonical_key),
            ).fetchone()
            return row is not None

    def seed_terms(self, terms: list[dict[str, Any]]) -> None:
        with self.connect() as connection:
            for term in terms:
                existing = connection.execute(
                    """
                    SELECT id FROM terms
                    WHERE cn_name = ? AND en_name = ? AND parent_id IS NULL
                    """,
                    (term["cn"], term.get("en", "")),
                ).fetchone()
                if existing:
                    parent_id = int(existing["id"])
                else:
                    cursor = connection.execute(
                        """
                        INSERT INTO terms(cn_name, en_name, category, needs_review)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            term["cn"],
                            term.get("en", ""),
                            term.get("category", ""),
                            int(term.get("needs_review", False)),
                        ),
                    )
                    parent_id = int(cursor.lastrowid)
                for child in term.get("children", []):
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO terms(cn_name, en_name, category, parent_id, needs_review)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            child["cn"],
                            child.get("en", ""),
                            term.get("category", ""),
                            parent_id,
                            int(not child.get("en") or child.get("en") == "—"),
                        ),
                    )
            connection.execute(
                """
                INSERT OR IGNORE INTO product_categories(name)
                SELECT DISTINCT category FROM terms WHERE TRIM(category) != ''
                """
            )

    def list_terms(self, query: str = "", top_level_only: bool = False) -> list[dict[str, Any]]:
        conditions = []
        params: list[Any] = []
        if query:
            conditions.append("(cn_name LIKE ? OR en_name LIKE ? OR category LIKE ?)")
            pattern = f"%{query}%"
            params.extend((pattern, pattern, pattern))
        if top_level_only:
            conditions.append("parent_id IS NULL")
        sql = "SELECT * FROM terms"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY id"
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def confirm_term(
        self,
        term_id: int,
        cn_name: str | None = None,
        en_name: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        with self.connect() as connection:
            current = connection.execute(
                "SELECT * FROM terms WHERE id = ?", (term_id,)
            ).fetchone()
            if current is None:
                raise KeyError(term_id)
            if current["entry_type"] == "note":
                raise ValueError("Parent notes cannot be confirmed as terms")
            confirmed_cn = current["cn_name"] if cn_name is None else cn_name.strip()
            confirmed_en = current["en_name"] if en_name is None else en_name.strip()
            confirmed_category = current["category"] if category is None else category.strip()
            self._register_product_category(connection, confirmed_category)
            if not confirmed_cn or not confirmed_en or confirmed_en == "—":
                raise ValueError("Confirmed terms require Chinese and English names")
            connection.execute(
                """
                UPDATE terms
                SET cn_name = ?, en_name = ?, category = ?, needs_review = 0
                WHERE id = ?
                """,
                (confirmed_cn, confirmed_en, confirmed_category, term_id),
            )
            term = connection.execute("SELECT * FROM terms WHERE id = ?", (term_id,)).fetchone()
            return dict(term)

    def update_term(
        self,
        term_id: int,
        cn_name: str,
        en_name: str,
        category: str = "",
    ) -> dict[str, Any]:
        with self.connect() as connection:
            normalized_category = category.strip()
            self._register_product_category(connection, normalized_category)
            current = connection.execute(
                "SELECT * FROM terms WHERE id = ?", (term_id,)
            ).fetchone()
            if current is None:
                raise KeyError(term_id)
            updated_cn = cn_name.strip()
            updated_en = en_name.strip()
            if not updated_cn:
                raise ValueError("Chinese content is required")
            if (
                current["entry_type"] == "term"
                and not current["needs_review"]
                and (not updated_en or updated_en == "—")
            ):
                raise ValueError("Confirmed terms require Chinese and English names")
            connection.execute(
                """
                UPDATE terms
                SET cn_name = ?, en_name = ?, category = ?
                WHERE id = ?
                """,
                (updated_cn, updated_en, normalized_category, term_id),
            )
            return dict(
                connection.execute("SELECT * FROM terms WHERE id = ?", (term_id,)).fetchone()
            )

    @staticmethod
    def _register_product_category(
        connection: sqlite3.Connection, name: str
    ) -> None:
        if name:
            connection.execute(
                "INSERT OR IGNORE INTO product_categories(name) VALUES (?)", (name,)
            )

    def list_product_categories(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT category.id, category.name, category.sort_order,
                           (SELECT COUNT(*) FROM terms
                            WHERE terms.category = category.name COLLATE NOCASE) AS term_count,
                           (SELECT COUNT(*) FROM features
                            WHERE features.category = category.name COLLATE NOCASE) AS feature_count
                    FROM product_categories AS category
                    ORDER BY category.sort_order, category.name COLLATE NOCASE
                    """
                ).fetchall()
            ]

    def create_product_category(self, name: str) -> dict[str, Any]:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("分类名称不能为空")
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO product_categories(name) VALUES (?)", (normalized_name,)
            )
            category_id = int(cursor.lastrowid)
        return next(
            category
            for category in self.list_product_categories()
            if category["id"] == category_id
        )

    def rename_product_category(self, category_id: int, name: str) -> dict[str, Any]:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("分类名称不能为空")
        with self.connect() as connection:
            current = connection.execute(
                "SELECT * FROM product_categories WHERE id = ?", (category_id,)
            ).fetchone()
            if current is None:
                raise KeyError(category_id)
            old_name = current["name"]
            connection.execute(
                "UPDATE product_categories SET name = ? WHERE id = ?",
                (normalized_name, category_id),
            )
            connection.execute(
                "UPDATE terms SET category = ? WHERE category = ? COLLATE NOCASE",
                (normalized_name, old_name),
            )
            connection.execute(
                "UPDATE features SET category = ? WHERE category = ? COLLATE NOCASE",
                (normalized_name, old_name),
            )
        return next(
            category
            for category in self.list_product_categories()
            if category["id"] == category_id
        )

    def set_term_entry_type(self, term_id: int, entry_type: str) -> dict[str, Any]:
        if entry_type not in {"term", "note"}:
            raise ValueError("Entry type must be term or note")
        with self.connect() as connection:
            current = connection.execute(
                "SELECT * FROM terms WHERE id = ?", (term_id,)
            ).fetchone()
            if current is None:
                raise KeyError(term_id)
            if entry_type == "note" and current["parent_id"] is None:
                raise ValueError("Only child entries can be parent notes")
            needs_review = 0 if entry_type == "note" else 1
            connection.execute(
                "UPDATE terms SET entry_type = ?, needs_review = ? WHERE id = ?",
                (entry_type, needs_review, term_id),
            )
            return dict(
                connection.execute("SELECT * FROM terms WHERE id = ?", (term_id,)).fetchone()
            )

    def counts(self, project_id: int | None = None) -> dict[str, int]:
        selected_project_id = project_id or self.default_project_id()
        with self.connect() as connection:
            actionable_issues = self._actionable_review_issues(connection, selected_project_id)
            standalone_issue_count = sum(
                issue["category"] == "" for issue in actionable_issues
            )
            return {
                "feature_count": connection.execute(
                    "SELECT COUNT(*) FROM features WHERE project_id = ?", (selected_project_id,)
                ).fetchone()[0],
                "release_count": connection.execute(
                    "SELECT COUNT(*) FROM releases WHERE project_id = ?", (selected_project_id,)
                ).fetchone()[0],
                "review_count": connection.execute(
                    """SELECT COUNT(*) FROM import_candidates candidate
                       JOIN releases release ON release.id = candidate.release_id
                       WHERE candidate.status = 'pending' AND release.project_id = ?""",
                    (selected_project_id,),
                ).fetchone()[0]
                + standalone_issue_count,
                "term_count": connection.execute(
                    "SELECT COUNT(*) FROM terms WHERE parent_id IS NULL"
                ).fetchone()[0],
            }

    def todo_counts(self, project_id: int | None = None) -> dict[str, int]:
        """未完成事项计数，供工作台首页使用。

        口径说明：`import_candidates` 与 `review_issues` 经版本表限定项目；
        `kh_issues` 目前没有项目维度，只能全局计数——三项口径不同，调用方需照实展示，
        不要把它们描述成同一范围。

        `review_issues_open` 与审核页同源：都走 `_actionable_review_issues`。此前它数的是
        `review_issues` 里全部 open 行，而审核页会把候选已全部处理完的分类提醒整条隐藏，
        于是首页写着 51 条、点进去只有 1 条（V10 甚至是 0 条），用户既处理不了也无法对账。
        """
        selected_project_id = project_id or self.default_project_id()
        with self.connect() as connection:
            return {
                "candidates_pending": connection.execute(
                    """SELECT COUNT(*) FROM import_candidates candidate
                       JOIN releases release ON release.id = candidate.release_id
                       WHERE candidate.status = 'pending' AND release.project_id = ?""",
                    (selected_project_id,),
                ).fetchone()[0],
                "review_issues_open": len(
                    self._actionable_review_issues(connection, selected_project_id)
                ),
                "knowledge_issues_open": connection.execute(
                    "SELECT COUNT(*) FROM kh_issues WHERE status = 'open'"
                ).fetchone()[0],
            }

    @staticmethod
    def _actionable_review_issues(
        connection: sqlite3.Connection,
        project_id: int | None = None,
    ) -> list[dict[str, Any]]:
        project_clause = " AND release.project_id = ?" if project_id is not None else ""
        issue_project_clause = (
            " AND (release.project_id = ? OR issue.release_id IS NULL)"
            if project_id is not None
            else ""
        )
        project_params: tuple[Any, ...] = (project_id,) if project_id is not None else ()
        pending_by_release_and_category = {
            (int(row["release_id"]), row["category"]): int(row["pending_count"])
            for row in connection.execute(
                """
                SELECT release_id, category, COUNT(*) AS pending_count
                FROM import_candidates candidate
                JOIN releases release ON release.id = candidate.release_id
                WHERE candidate.status = 'pending' AND (title_cn = '' OR title_en = '')
                """ + project_clause + """
                GROUP BY release_id, category
                """,
                project_params,
            ).fetchall()
        }
        issues: list[dict[str, Any]] = []
        rows = connection.execute(
            """
            SELECT issue.*, release.version
            FROM review_issues AS issue
            LEFT JOIN releases AS release ON release.id = issue.release_id
            WHERE issue.status = 'open'
            """ + issue_project_clause + """
            ORDER BY release.version, issue.id
            """,
            project_params,
        ).fetchall()
        for row in rows:
            issue = dict(row)
            semantic_match = _SEMANTIC_REVIEW_ISSUE.match(issue["message"])
            if semantic_match:
                category, original_count = semantic_match.groups()
                pending_count = pending_by_release_and_category.get(
                    (int(issue["release_id"]), category), 0
                )
                if pending_count == 0:
                    continue
                issue.update(
                    category=category,
                    unverified_count=int(original_count),
                    pending_count=pending_count,
                )
            else:
                issue.update(category="", unverified_count=None, pending_count=None)
            issues.append(issue)
        return issues

    def list_review_issues(self, project_id: int | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return self._actionable_review_issues(
                connection, project_id or self.default_project_id()
            )

    def register_source_document(
        self,
        release_id: int,
        path: str,
        language: str,
        sha256: str,
    ) -> tuple[int, bool]:
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM source_documents WHERE path = ? AND sha256 = ?",
                (path, sha256),
            ).fetchone()
            if existing:
                return int(existing["id"]), False
            cursor = connection.execute(
                """
                INSERT INTO source_documents(release_id, path, filename, language, sha256)
                VALUES (?, ?, ?, ?, ?)
                """,
                (release_id, path, Path(path).name, language, sha256),
            )
            return int(cursor.lastrowid), True

    @staticmethod
    def _replace_source_release_tables(
        connection: sqlite3.Connection,
        release_id: int,
        source_document_id: int,
        source: dict[str, Any],
    ) -> None:
        """Replace derived rows while leaving the immutable Word-table evidence intact."""
        connection.execute(
            "DELETE FROM release_tables WHERE source_document_id = ?",
            (source_document_id,),
        )
        for table in source.get("structured_tables", []):
            records = table.get("records", [])
            serialized = json.dumps(
                {
                    "headers": table.get("headers", []),
                    "rows": table.get("rows", []),
                    "records": records,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            cursor = connection.execute(
                """
                INSERT INTO release_tables(
                    release_id, source_document_id, table_index, language,
                    table_type, snapshot_mode, headers_json, rows_json,
                    row_count, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    release_id,
                    source_document_id,
                    int(table.get("index", 0)),
                    source["language"],
                    table["table_type"],
                    table["snapshot_mode"],
                    json.dumps(table.get("headers", []), ensure_ascii=False),
                    json.dumps(table.get("rows", []), ensure_ascii=False),
                    len(records),
                    hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
                ),
            )
            table_id = int(cursor.lastrowid)
            for record in records:
                connection.execute(
                    """
                    INSERT INTO release_table_rows(
                        table_id, release_id, row_index, stable_key, item_code,
                        item_name, change_kind, summary, data_json, language
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        table_id,
                        release_id,
                        int(record.get("row_index", 0)),
                        str(record.get("stable_key", "")),
                        str(record.get("item_code", "")),
                        str(record.get("item_name", "")),
                        str(record.get("change_kind", "reference")),
                        str(record.get("summary", "")),
                        json.dumps(record.get("data", {}), ensure_ascii=False, sort_keys=True),
                        str(record.get("language", source["language"])),
                    ),
                )

    @staticmethod
    def _pair_release_table_rows(
        connection: sqlite3.Connection, release_id: int
    ) -> None:
        def comparison_value(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    re.sub(r"\s+", "", str(key)).casefold(): comparison_value(item)
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [comparison_value(item) for item in value]
            if isinstance(value, str):
                compact = re.sub(r"\s+", "", value).replace("，", ",")
                return re.sub(r",+", ",", compact).strip(",").casefold()
            return value

        connection.execute(
            """
            UPDATE release_table_rows
            SET pair_status = 'unpaired', counterpart_id = NULL
            WHERE release_id = ?
            """,
            (release_id,),
        )
        rows = connection.execute(
            """
            SELECT row.*, table_data.table_type
            FROM release_table_rows row
            JOIN release_tables table_data ON table_data.id = row.table_id
            WHERE row.release_id = ?
            ORDER BY row.id
            """,
            (release_id,),
        ).fetchall()
        grouped: dict[tuple[str, str], dict[str, list[sqlite3.Row]]] = {}
        for row in rows:
            if (
                not row["stable_key"]
                or row["language"] not in {"cn", "en"}
                or row["table_type"] in MARKET_SPECIFIC_TABLE_TYPES
            ):
                continue
            grouped.setdefault(
                (row["table_type"], row["stable_key"].casefold()), {"cn": [], "en": []}
            )[row["language"]].append(row)
        for languages in grouped.values():
            if len(languages["cn"]) != 1 or len(languages["en"]) != 1:
                continue
            chinese, english = languages["cn"][0], languages["en"][0]
            status = (
                "matched"
                if comparison_value(json.loads(chinese["data_json"]))
                == comparison_value(json.loads(english["data_json"]))
                else "conflict"
            )
            connection.execute(
                """
                UPDATE release_table_rows
                SET pair_status = ?, counterpart_id = ?
                WHERE id = ?
                """,
                (status, int(english["id"]), int(chinese["id"])),
            )
            connection.execute(
                """
                UPDATE release_table_rows
                SET pair_status = ?, counterpart_id = ?
                WHERE id = ?
                """,
                (status, int(chinese["id"]), int(english["id"])),
            )

    def stage_release_pair(
        self,
        release_id: int,
        sources: list[dict[str, Any]],
        issues: list[str],
        candidates: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Persist one bilingual file pair and all derived rows atomically."""
        with self.connect() as connection:
            new_source_exists = any(
                connection.execute(
                    "SELECT 1 FROM source_documents WHERE path = ? AND sha256 = ?",
                    (source["path"], source["sha256"]),
                ).fetchone()
                is None
                for source in sources
            )
            current_issue_messages = set(issues)
            open_issues = connection.execute(
                """
                SELECT id, message FROM review_issues
                WHERE issue_type = 'source_pair' AND release_id = ? AND status = 'open'
                """,
                (release_id,),
            ).fetchall()
            existing_issue_messages = {
                row["message"] for row in open_issues if row["message"] in current_issue_messages
            }
            for obsolete in open_issues:
                if obsolete["message"] not in current_issue_messages:
                    connection.execute(
                        "UPDATE review_issues SET status = 'resolved' WHERE id = ?",
                        (obsolete["id"],),
                    )
            for issue in issues:
                if issue in existing_issue_messages:
                    continue
                connection.execute(
                    """
                    INSERT INTO review_issues(issue_type, message, release_id)
                    VALUES ('source_pair', ?, ?)
                    """,
                    (issue, release_id),
                )
            source_ids: dict[str, int] = {}
            for source in sources:
                existing_source = connection.execute(
                    "SELECT id FROM source_documents WHERE path = ? AND sha256 = ?",
                    (source["path"], source["sha256"]),
                ).fetchone()
                if existing_source:
                    source_id = int(existing_source["id"])
                    connection.execute(
                        """
                        UPDATE source_documents
                        SET release_id = ?, content = ?, tables_json = ?
                        WHERE id = ?
                        """,
                        (
                            release_id,
                            source.get("content", ""),
                            json.dumps(source.get("tables", []), ensure_ascii=False),
                            source_id,
                        ),
                    )
                else:
                    cursor = connection.execute(
                        """
                        INSERT INTO source_documents(
                            release_id, path, filename, language, sha256, content, tables_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            release_id,
                            source["path"],
                            Path(source["path"]).name,
                            source["language"],
                            source["sha256"],
                            source.get("content", ""),
                            json.dumps(source.get("tables", []), ensure_ascii=False),
                        ),
                    )
                    source_id = int(cursor.lastrowid)
                source_ids[source["language"]] = source_id
                self._replace_source_release_tables(
                    connection, release_id, source_id, source
                )
            self._pair_release_table_rows(connection, release_id)
            if not new_source_exists:
                return {"pending": 0, "auto_approved": 0}

            pending_created = 0
            auto_approved = 0
            evidence_source_id = source_ids.get("cn") or source_ids.get("en")
            for candidate in candidates:
                existing_candidate = connection.execute(
                    """
                    SELECT 1 FROM import_candidates
                    WHERE release_id = ? AND category = ? AND raw_cn = ? AND raw_en = ?
                    """,
                    (
                        release_id,
                        candidate["category"],
                        candidate["raw_cn"],
                        candidate["raw_en"],
                    ),
                ).fetchone()
                if existing_candidate:
                    continue
                is_bug = candidate["category"] == "bug"
                connection.execute(
                    """
                    INSERT INTO import_candidates(
                        release_id, category, title_cn, title_en, raw_cn, raw_en,
                        confidence, source_document_id, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        release_id,
                        candidate["category"],
                        candidate["title_cn"],
                        candidate["title_en"],
                        candidate["raw_cn"],
                        candidate["raw_en"],
                        candidate["confidence"],
                        evidence_source_id,
                        "approved" if is_bug else "pending",
                    ),
                )
                if not is_bug:
                    pending_created += 1
                    continue
                title = candidate["title_cn"] or candidate["title_en"]
                change_cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO change_events(
                        release_id, category, canonical_key, title_cn, title_en,
                        description_cn, description_en, review_status, confidence
                    ) VALUES (?, 'bug', ?, ?, ?, ?, ?, 'approved', ?)
                    """,
                    (
                        release_id,
                        canonical_key("bug", title),
                        candidate["title_cn"],
                        candidate["title_en"],
                        candidate["raw_cn"],
                        candidate["raw_en"],
                        candidate["confidence"],
                    ),
                )
                auto_approved += int(change_cursor.rowcount > 0)
            return {"pending": pending_created, "auto_approved": auto_approved}

    def link_item_evidence(self, item_id: int, evidence_id: int, note: str = "") -> None:
        """把条目关联到证据，使答案可回到原文定位。"""
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO kh_item_evidence(item_id, evidence_id, note)
                VALUES (?, ?, ?)
                ON CONFLICT(item_id, evidence_id) DO UPDATE SET note = excluded.note
                """,
                (item_id, evidence_id, note),
            )

    def list_item_evidence(self, item_id: int) -> list[dict[str, Any]]:
        """列出某条目的全部证据，含文档版本与定位字段。"""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT e.id AS evidence_id, e.page, e.sheet, e.cell_range, e.excerpt,
                       e.extractor_version, v.id AS document_version_id,
                       v.version_label, v.path_pdf, v.path_docx,
                       d.title AS document_title, l.note AS link_note
                FROM kh_item_evidence l
                JOIN kh_evidence e ON e.id = l.evidence_id
                JOIN kh_document_versions v ON v.id = e.document_version_id
                JOIN kh_documents d ON d.id = v.document_id
                WHERE l.item_id = ? ORDER BY e.id
                """,
                (item_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    # ---- 机型映射与注册查询（迁移 006） ----

    def add_model_mapping(
        self,
        derived_model: str,
        base_model: str,
        mapping_source: str = "",
        verified_at: str | None = None,
        evidence_id: int | None = None,
    ) -> None:
        """登记衍生型号 → 基础型号映射。`mapping_source` 为已确认依据，不代填。"""
        if derived_model == base_model:
            raise ValueError("衍生型号与基础型号相同，无需映射")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO kh_model_mappings(
                    derived_model, base_model, mapping_source, verified_at, evidence_id
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(derived_model) DO UPDATE SET
                    base_model = excluded.base_model,
                    mapping_source = excluded.mapping_source,
                    verified_at = excluded.verified_at,
                    evidence_id = excluded.evidence_id
                """,
                (derived_model, base_model, mapping_source, verified_at, evidence_id),
            )

    def add_model_source_link(
        self, source_system: str, source_model_name: str, knowledge_model: str
    ) -> None:
        """登记源系统型号身份，保留全部源记录以便审计（A38）。"""
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO kh_model_source_links(
                    source_system, source_model_name, knowledge_model
                ) VALUES (?, ?, ?)
                ON CONFLICT(source_system, source_model_name) DO UPDATE SET
                    knowledge_model = excluded.knowledge_model
                """,
                (source_system, source_model_name, knowledge_model),
            )

    def list_model_mappings(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM kh_model_mappings ORDER BY derived_model"
            ).fetchall()
            return [dict(row) for row in rows]

    def resolve_registration_model(self, model: str) -> dict[str, Any]:
        """把查询机型解析为**注册用基础型号**。

        返回 `state`：
        - `resolved`：机型本身是基础型号，或已确认映射到基础型号
        - `pending`：是衍生型号但**没有已确认映射** → 必须返回待确认

        **绝不能**因为注册资料里没有该衍生型号名称就判定未注册（A34）。
        """
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM kh_model_mappings WHERE derived_model = ?", (model,)
            ).fetchone()
            row = dict(row) if row else None
        if row:
            return {
                "state": "resolved",
                "queried_model": model,
                "registration_model": row["base_model"],
                "derived": True,
                "mapping_source": row["mapping_source"],
            }
        return {
            "state": "resolved",
            "queried_model": model,
            "registration_model": model,
            "derived": False,
            "mapping_source": "",
        }

    def query_registration(
        self, model: str, country_code: str = "CN"
    ) -> dict[str, Any]:
        """按机型查询注册探头，**按注册单元分别呈现，不做并集**。

        产品负责人 2026-09-14 裁定：同一机型可出现在多张注册证下（如 VINNO 10 同时在
        苏械注准20232061322 与 湘械注准20222062053），并集会把不同证书的适用范围混为
        一个数字。故按证书号分组返回，每组各自标注全集与排除。

        红线：
        - 衍生型号先用已确认映射解析基础型号（A33）；**无映射返回 pending**（A34）
        - 解析后查不到任何注册关系 → `not_found` 语义的 pending，**不判定未注册**（A06）
        """
        with self.connect() as connection:
            mapping = connection.execute(
                "SELECT * FROM kh_model_mappings WHERE derived_model = ?", (model,)
            ).fetchone()
        mapping = dict(mapping) if mapping else None
        lookup = mapping["base_model"] if mapping else model

        relations = self.list_registration_relations(country_code, lookup)
        if not relations:
            return {
                "state": "pending",
                "queried_model": model,
                "registration_model": lookup,
                "derived": bool(mapping),
                "units": [],
                "reason": "当前资料中未查询到该机型的注册记录，返回待确认",
            }

        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in relations:
            grouped.setdefault(row["certificate_no"] or "未标注证书", []).append(
                {
                    "probe_code": row["probe_code"],
                    "state": row["state"],
                    "rule": row["rule"],
                }
            )

        units = []
        for certificate_no, probes in sorted(grouped.items()):
            scopes = {
                row["probe_code"]
                for row in self.list_registration_scopes(certificate_no)
            }
            registered = sum(1 for probe in probes if probe["state"] == "已注册")
            units.append(
                {
                    "certificate_no": certificate_no,
                    "probe_total": len(probes),
                    "registered": registered,
                    "unregistered": len(probes) - registered,
                    "all_applicable": any(
                        "探头全适用" in probe["rule"] for probe in probes
                    ),
                    "scope_size": len(scopes),
                    "probes": probes,
                }
            )
        return {
            "state": "resolved",
            "queried_model": model,
            "registration_model": lookup,
            "derived": bool(mapping),
            "mapping_source": mapping["mapping_source"] if mapping else "",
            "unit_count": len(units),
            "units": units,
        }

    # ---- 受控资料与证据（迁移 004） ----

    def add_document(
        self,
        title: str,
        doc_type: str = "",
        scope_market: str = "domestic",
        model_scope: str = "",
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO kh_documents(title, doc_type, scope_market, model_scope)
                VALUES (?, ?, ?, ?)
                """,
                (title, doc_type, scope_market, model_scope),
            )
            return int(cursor.lastrowid)

    def add_document_version(
        self,
        document_id: int,
        version_label: str = "",
        sha256: str = "",
        path_docx: str | None = None,
        path_pdf: str | None = None,
        supersedes_version_id: int | None = None,
        effective_date: str | None = None,
        verified_at: str | None = None,
    ) -> int:
        """登记一个文档版本。

        `path_docx` 为抽取源，`path_pdf` 为受控发布版；**正式引用使用 PDF**。
        版本只追加不覆盖：新版本用 `supersedes_version_id` 指向被替代版本。
        """
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO kh_document_versions(
                    document_id, version_label, effective_date, sha256,
                    path_docx, path_pdf, supersedes_version_id, verified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    version_label,
                    effective_date,
                    sha256,
                    path_docx,
                    path_pdf,
                    supersedes_version_id,
                    verified_at,
                ),
            )
            version_id = int(cursor.lastrowid)
            connection.execute(
                """
                UPDATE kh_documents SET current_version_id = ? WHERE id = ?
                """,
                (version_id, document_id),
            )
            # 新受控版本与指向旧版本的正式答案在同一事务切换，避免继续命中旧结论。
            connection.execute(
                """
                UPDATE kh_qa_answers SET status = 'needs_review'
                WHERE status = 'published' AND evidence_id IN (
                    SELECT e.id FROM kh_evidence e
                    JOIN kh_document_versions v ON v.id = e.document_version_id
                    WHERE v.document_id = ? AND v.id != ?
                )
                """,
                (document_id, version_id),
            )
            connection.execute(
                """UPDATE kh_qa_questions SET status = 'open', answer_id = NULL, answered_at = NULL
                   WHERE status = 'answered' AND answer_id IN (
                     SELECT a.id FROM kh_qa_answers a
                     JOIN kh_evidence e ON e.id = a.evidence_id
                     JOIN kh_document_versions v ON v.id = e.document_version_id
                     WHERE a.status = 'needs_review' AND v.document_id = ?
                   )""",
                (document_id,),
            )
            return version_id

    def list_documents(self) -> list[dict[str, Any]]:
        """列出全部受控资料（只登记信息，不读文件内容）。"""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM kh_documents ORDER BY doc_type, title"
            ).fetchall()
            return [dict(row) for row in rows]

    def count_document_version_evidence(self) -> dict[int, int]:
        """每个文档版本的证据条数（一次查完，避免逐个版本查询）。"""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT document_version_id, COUNT(*) AS total FROM kh_evidence GROUP BY document_version_id"
            ).fetchall()
            return {row["document_version_id"]: row["total"] for row in rows}

    def list_document_versions(self, document_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM kh_document_versions
                WHERE document_id = ? ORDER BY id
                """,
                (document_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def add_evidence(
        self,
        document_version_id: int,
        excerpt: str,
        page: int | None = None,
        sheet: str | None = None,
        cell_range: str | None = None,
        extractor_version: str = "",
    ) -> int:
        """登记一条可定位证据。引用必须能定位，不能只有文件名。"""
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO kh_evidence(
                    document_version_id, page, sheet, cell_range, excerpt, extractor_version
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (document_version_id, page, sheet, cell_range, excerpt, extractor_version),
            )
            return int(cursor.lastrowid)

    def list_evidence(self, document_version_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM kh_evidence WHERE document_version_id = ? ORDER BY id",
                (document_version_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    # ---- 产品策略与注册（迁移 005） ----

    def latest_strategy_snapshot(self) -> dict[str, Any] | None:
        """最近一次配置库一致性快照的登记信息；没有登记过则返回 None。

        注意：这只说明"曾经采集过一致性快照"，不代表本次查询读的是快照——
        查询始终是只读直连。源库每次启动都会改写文件头，因此源主文件哈希与
        快照哈希不可比，这里只如实呈现快照自身的登记值。
        """
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT snapshot_id, source_path, source_sha256, source_version,
                       collected_at, created_at
                FROM kh_strategy_snapshots
                ORDER BY created_at DESC, snapshot_id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return {
            "snapshot_id": row["snapshot_id"],
            "source_path": row["source_path"],
            "source_sha256": row["source_sha256"],
            "source_version": row["source_version"],
            "collected_at": row["collected_at"],
            "created_at": row["created_at"],
        }

    def add_strategy_snapshot(
        self,
        snapshot_id: str,
        source_path: str,
        source_sha256: str,
        collected_at: str,
        source_version: str = "",
    ) -> None:
        """登记配置库一致性快照。`source_sha256` 必须是**快照文件本身**的哈希。"""
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO kh_strategy_snapshots(
                    snapshot_id, source_path, source_sha256, source_version, collected_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_id) DO NOTHING
                """,
                (snapshot_id, source_path, source_sha256, source_version, collected_at),
            )

    def add_strategy_value(
        self,
        snapshot_id: str,
        model_code: str,
        item_code: str,
        selection_config: str | None = None,
        current_config: str | None = None,
        final_config: str | None = None,
        conflict_state: str = "none",
        source_values_json: str = "[]",
    ) -> None:
        """写入一条策略值。正式结论只读 `selection_config`。"""
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO kh_strategy_values(
                    snapshot_id, model_code, item_code, selection_config,
                    current_config, final_config, conflict_state, source_values_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_id, model_code, item_code) DO UPDATE SET
                    selection_config = excluded.selection_config,
                    current_config = excluded.current_config,
                    final_config = excluded.final_config,
                    conflict_state = excluded.conflict_state,
                    source_values_json = excluded.source_values_json
                """,
                (
                    snapshot_id,
                    model_code,
                    item_code,
                    selection_config,
                    current_config,
                    final_config,
                    conflict_state,
                    source_values_json,
                ),
            )

    def list_strategy_values(
        self, snapshot_id: str, model_code: str | None = None
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            if model_code is None:
                rows = connection.execute(
                    "SELECT * FROM kh_strategy_values WHERE snapshot_id = ? ORDER BY item_code",
                    (snapshot_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM kh_strategy_values
                    WHERE snapshot_id = ? AND model_code = ? ORDER BY item_code
                    """,
                    (snapshot_id, model_code),
                ).fetchall()
            return [dict(row) for row in rows]

    def add_registration_scope(
        self, country_code: str, registration_base_model: str, probe_code: str, **extra: Any
    ) -> int:
        """登记注册全集中的一条（原始全集，不做任何推导）。"""
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO kh_registration_scopes(
                    country_code, registration_base_model, probe_code, certificate_no,
                    effective_date, evidence_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    country_code,
                    registration_base_model,
                    probe_code,
                    extra.get("certificate_no", ""),
                    extra.get("effective_date"),
                    extra.get("evidence_id"),
                ),
            )
            return int(cursor.lastrowid)

    def list_registration_scopes(
        self, certificate_no: str | None = None
    ) -> list[dict[str, Any]]:
        """列出注册全集（可按证书号过滤）。"""
        with self.connect() as connection:
            if certificate_no is None:
                rows = connection.execute(
                    "SELECT * FROM kh_registration_scopes ORDER BY id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM kh_registration_scopes WHERE certificate_no = ? ORDER BY id",
                    (certificate_no,),
                ).fetchall()
            return [dict(row) for row in rows]

    def list_registration_exclusions(
        self,
        country_code: str | None = None,
        registration_base_model: str | None = None,
    ) -> list[dict[str, Any]]:
        """列出型号排除项。

        注意：**没有排除项不等于差异表缺失**——"资料里写了该型号全适用"与"我们没拿到差异表"
        是两个事实，调用方不能用空列表推断后者。
        """
        clauses, params = [], []
        if country_code:
            clauses.append("country_code = ?")
            params.append(country_code)
        if registration_base_model:
            clauses.append("registration_base_model = ?")
            params.append(registration_base_model)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM kh_registration_exclusions {where} ORDER BY id", tuple(params)
            ).fetchall()
            return [dict(row) for row in rows]

    def describe_evidence(self, evidence_id: int | None) -> dict[str, Any] | None:
        """把证据展开成可定位的原文位置：文档 + 工作表/页码 + 单元格 + 摘录。"""
        if not evidence_id:
            return None
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT e.id, e.page, e.sheet, e.cell_range, e.excerpt, e.extractor_version,
                       v.version_label, v.path_pdf, v.path_docx, v.verified_at,
                       d.title AS document_title, d.doc_type
                FROM kh_evidence e
                LEFT JOIN kh_document_versions v ON v.id = e.document_version_id
                LEFT JOIN kh_documents d ON d.id = v.document_id
                WHERE e.id = ?
                """,
                (evidence_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_registration_models(self, country_code: str = "CN") -> dict[str, list[str]]:
        """可选机型：注册关系里的基础型号，以及已确认映射到基础型号的衍生型号。"""
        with self.connect() as connection:
            base_models = [
                row[0]
                for row in connection.execute(
                    """
                    SELECT DISTINCT registration_base_model FROM kh_registration_relations
                    WHERE country_code = ? ORDER BY registration_base_model
                    """,
                    (country_code,),
                )
            ]
            derived_models = [
                {"derived_model": row[0], "base_model": row[1], "mapping_source": row[2]}
                for row in connection.execute(
                    """
                    SELECT m.derived_model, m.base_model, m.mapping_source
                    FROM kh_model_mappings m
                    WHERE m.base_model IN (
                        SELECT DISTINCT registration_base_model FROM kh_registration_relations
                        WHERE country_code = ?
                    )
                    ORDER BY m.derived_model
                    """,
                    (country_code,),
                )
            ]
        return {"base_models": base_models, "derived_models": derived_models}

    def add_registration_exclusion(
        self, country_code: str, registration_base_model: str, probe_code: str, **extra: Any
    ) -> int:
        """登记型号排除项。缺差异表时**不得**当作空集合。"""
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO kh_registration_exclusions(
                    country_code, registration_base_model, probe_code, reason, evidence_id
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    country_code,
                    registration_base_model,
                    probe_code,
                    extra.get("reason", ""),
                    extra.get("evidence_id"),
                ),
            )
            return int(cursor.lastrowid)

    def add_registration_relation(
        self, country_code: str, registration_base_model: str, probe_code: str, **extra: Any
    ) -> int:
        """登记派生结果：有效探头 = 注册探头全集 − 机型排除项。"""
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO kh_registration_relations(
                    country_code, certificate_no, registration_base_model, probe_code,
                    state, rule, batch_id, evidence_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    country_code,
                    extra.get("certificate_no", ""),
                    registration_base_model,
                    probe_code,
                    extra.get("state", "待确认"),
                    extra.get("rule", ""),
                    extra.get("batch_id", ""),
                    extra.get("evidence_id"),
                ),
            )
            return int(cursor.lastrowid)

    def list_registration_relations(
        self,
        country_code: str | None = None,
        registration_base_model: str | None = None,
        certificate_no: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses, params = [], []
        if country_code:
            clauses.append("country_code = ?")
            params.append(country_code)
        if registration_base_model:
            clauses.append("registration_base_model = ?")
            params.append(registration_base_model)
        if certificate_no:
            clauses.append("certificate_no = ?")
            params.append(certificate_no)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM kh_registration_relations {where} ORDER BY id", tuple(params)
            ).fetchall()
            return [dict(row) for row in rows]

    # ---- 产品状态（迁移 011） ----

    @staticmethod
    def _required_business_text(value: Any, label: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{label}不能为空。")
        return normalized

    @staticmethod
    def _business_date(value: Any, label: str, *, required: bool = True) -> str | None:
        normalized = str(value or "").strip()
        if not normalized:
            if required:
                raise ValueError(f"{label}不能为空。")
            return None
        try:
            date.fromisoformat(normalized)
        except ValueError as error:
            raise ValueError(f"{label}必须是 YYYY-MM-DD 日期。") from error
        return normalized

    def propose_product_state(
        self,
        *,
        market_code: str,
        model_name: str,
        software_version: str,
        release_status: str,
        effective_date: str,
        source_ref: str,
        evidence_excerpt: str,
    ) -> int:
        """登记待审核产品状态，不影响已经审核通过的当前状态。"""
        values = {
            "market_code": self._required_business_text(market_code, "市场"),
            "model_name": self._required_business_text(model_name, "机型"),
            "software_version": self._required_business_text(software_version, "软件版本"),
            "release_status": self._required_business_text(release_status, "发布状态"),
            "effective_date": self._business_date(effective_date, "生效日期"),
            "source_ref": self._required_business_text(source_ref, "来源"),
            "evidence_excerpt": self._required_business_text(evidence_excerpt, "依据原文"),
        }
        with self.connect() as connection:
            existing = connection.execute(
                """
                SELECT id FROM kh_product_states
                WHERE market_code = :market_code
                  AND model_name = :model_name
                  AND software_version = :software_version
                  AND release_status = :release_status
                  AND effective_date = :effective_date
                  AND source_ref = :source_ref
                  AND evidence_excerpt = :evidence_excerpt
                  AND record_status IN ('pending', 'current')
                ORDER BY id DESC LIMIT 1
                """,
                values,
            ).fetchone()
            if existing is not None:
                return int(existing["id"])
            cursor = connection.execute(
                """
                INSERT INTO kh_product_states(
                    market_code, model_name, software_version, release_status,
                    effective_date, source_ref, evidence_excerpt, record_status
                ) VALUES (
                    :market_code, :model_name, :software_version, :release_status,
                    :effective_date, :source_ref, :evidence_excerpt, 'pending'
                )
                """,
                values,
            )
            return int(cursor.lastrowid)

    def approve_product_state(
        self,
        state_id: int,
        *,
        reviewed_by: str,
        reviewed_at: str,
        valid_until: str | None = None,
        review_note: str = "",
    ) -> None:
        """审核通过一个候选；同机型旧当前状态保留为历史。"""
        reviewer = self._required_business_text(reviewed_by, "审核人")
        review_date = self._business_date(reviewed_at, "审核日期")
        expiry = self._business_date(valid_until, "复核期限", required=False)
        if expiry and expiry < review_date:
            raise ValueError("复核期限不能早于审核日期。")
        with self.connect() as connection:
            candidate = connection.execute(
                "SELECT * FROM kh_product_states WHERE id = ?", (state_id,)
            ).fetchone()
            if candidate is None:
                raise ValueError("待审核产品状态不存在。")
            if candidate["record_status"] != "pending":
                raise ValueError("只有待审核产品状态可以审核通过。")
            current = connection.execute(
                """
                SELECT id FROM kh_product_states
                WHERE market_code = ? AND model_name = ? AND record_status = 'current'
                """,
                (candidate["market_code"], candidate["model_name"]),
            ).fetchone()
            previous_id = int(current["id"]) if current else None
            if previous_id is not None:
                connection.execute(
                    "UPDATE kh_product_states SET record_status = 'superseded' WHERE id = ?",
                    (previous_id,),
                )
            connection.execute(
                """
                UPDATE kh_product_states
                SET record_status = 'current', reviewed_by = ?, reviewed_at = ?,
                    valid_until = ?, review_note = ?, supersedes_state_id = ?
                WHERE id = ?
                """,
                (reviewer, review_date, expiry, str(review_note or "").strip(), previous_id, state_id),
            )

    def reject_product_state(
        self,
        state_id: int,
        *,
        reviewed_by: str,
        reviewed_at: str,
        review_note: str,
    ) -> None:
        """驳回候选且保留审核记录；必须说明原因。"""
        reviewer = self._required_business_text(reviewed_by, "审核人")
        review_date = self._business_date(reviewed_at, "审核日期")
        note = self._required_business_text(review_note, "驳回原因")
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE kh_product_states
                SET record_status = 'rejected', reviewed_by = ?, reviewed_at = ?, review_note = ?
                WHERE id = ? AND record_status = 'pending'
                """,
                (reviewer, review_date, note, state_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("只有待审核产品状态可以驳回。")

    def invalidate_product_state(
        self,
        state_id: int,
        *,
        invalidated_at: str,
        reason: str,
    ) -> None:
        """显式失效当前状态；不删除历史，也不自动选择替代记录。"""
        invalidation_date = self._business_date(invalidated_at, "失效日期")
        explanation = self._required_business_text(reason, "失效原因")
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE kh_product_states
                SET record_status = 'invalidated', invalidated_at = ?, invalidation_reason = ?
                WHERE id = ? AND record_status = 'current'
                """,
                (invalidation_date, explanation, state_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("只有当前产品状态可以失效。")

    def list_product_states(
        self,
        *,
        market_code: str | None = None,
        model_name: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if market_code:
            clauses.append("market_code = ?")
            parameters.append(str(market_code).strip())
        if model_name:
            clauses.append("model_name = ?")
            parameters.append(str(model_name).strip())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM kh_product_states
                {where}
                ORDER BY model_name COLLATE NOCASE,
                         CASE record_status
                           WHEN 'pending' THEN 0
                           WHEN 'current' THEN 1
                           WHEN 'superseded' THEN 2
                           WHEN 'invalidated' THEN 3
                           ELSE 4
                         END,
                         COALESCE(reviewed_at, created_at) DESC,
                         id DESC
                """,
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    # ---- 知识中枢（迁移 003） ----

    def list_knowledge_categories(
        self, parent_code: str | None = None
    ) -> list[dict[str, Any]]:
        """列出分类。parent_code 为 None 时返回全部，便于展示多级树。"""
        with self.connect() as connection:
            if parent_code is None:
                rows = connection.execute(
                    "SELECT * FROM kh_categories ORDER BY level, sort_order, code"
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM kh_categories
                    WHERE parent_code = ? ORDER BY sort_order, code
                    """,
                    (parent_code,),
                ).fetchall()
            return [dict(row) for row in rows]

    def add_knowledge_item(
        self,
        category_code: str,
        name_cn: str,
        name_en: str = "",
        code: str | None = None,
        parent_item_id: int | None = None,
        software_version: str | None = None,
        scope_market: str = "domestic",
        source_kind: str = "release_note",
        source_candidate_id: int | None = None,
    ) -> int:
        """新增知识条目。未分类或未知分类直接报错，不静默创建分类。

        `source_candidate_id` 为来源候选 id，用于建立可精确回溯的证据链。
        """
        with self.connect() as connection:
            known = connection.execute(
                "SELECT 1 FROM kh_categories WHERE code = ?", (category_code,)
            ).fetchone()
            if known is None:
                raise ValueError(f"未知分类：{category_code}（不得静默创建分类）")
            cursor = connection.execute(
                """
                INSERT INTO kh_items(
                    category_code, code, name_cn, name_en, parent_item_id,
                    software_version, scope_market, source_kind, source_candidate_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    category_code,
                    code,
                    name_cn,
                    name_en,
                    parent_item_id,
                    software_version,
                    scope_market,
                    source_kind,
                    source_candidate_id,
                ),
            )
            return int(cursor.lastrowid)

    def list_item_tags(self, item_id: int | None = None) -> list[dict[str, Any]]:
        """列出条目标签（三层：probe / function / application）；不传条目则返回全部。"""
        with self.connect() as connection:
            if item_id is None:
                rows = connection.execute(
                    "SELECT * FROM kh_item_tags ORDER BY item_id, field, value"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM kh_item_tags WHERE item_id = ? ORDER BY field, value",
                    (item_id,),
                ).fetchall()
            return [dict(row) for row in rows]

    def add_item_tag(self, item_id: int, field: str, value: str) -> None:
        """给条目打标签。field 只允许 probe / function / application（三层标签）。"""
        if field not in {"probe", "function", "application"}:
            raise ValueError(f"未知标签层：{field}")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO kh_item_tags(item_id, field, value) VALUES (?, ?, ?)
                ON CONFLICT(item_id, field, value) DO NOTHING
                """,
                (item_id, field, value),
            )

    def list_knowledge_items(
        self, category_code: str | None = None
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            if category_code is None:
                rows = connection.execute(
                    "SELECT * FROM kh_items ORDER BY category_code, id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM kh_items WHERE category_code = ? ORDER BY id",
                    (category_code,),
                ).fetchall()
            return [dict(row) for row in rows]

    def add_probe_version(
        self,
        probe_code: str,
        series_code: str,
        software_version: str,
        state: str,
        probe_model: str = "",
        replaces_probe_code: str | None = None,
    ) -> None:
        """写入探头-版本对应关系（探头 Vcode × 机型系列 × 软件版本 → 状态）。

        `probe_code` 是配置系统的 Vcode（如 V20131），**必须用它作身份**：
        同一型号名可以对应多个 Vcode（如 `F4-9E` 既有 V20131「Added, replaces
        V20064」又有 V20064「Discontinued」），用型号名作主键会把两条互相覆盖。
        `probe_model` 仅用于展示。
        """
        if state not in {"added", "updated", "discontinued"}:
            raise ValueError(f"未知探头状态：{state}")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO kh_probe_versions(
                    probe_code, probe_model, series_code, software_version,
                    state, replaces_probe_code
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(probe_code, series_code, software_version) DO UPDATE SET
                    probe_model = excluded.probe_model,
                    state = excluded.state,
                    replaces_probe_code = excluded.replaces_probe_code
                """,
                (
                    probe_code,
                    probe_model,
                    series_code,
                    software_version,
                    state,
                    replaces_probe_code,
                ),
            )

    def list_probe_versions(
        self,
        series_code: str | None = None,
        software_version: str | None = None,
        probe_code: str | None = None,
    ) -> list[dict[str, Any]]:
        """双向查询：按系列/版本查支持的探头，或按探头查引入/停用版本。"""
        clauses, params = [], []
        if series_code:
            clauses.append("series_code = ?")
            params.append(series_code)
        if software_version:
            clauses.append("software_version = ?")
            params.append(software_version)
        if probe_code:
            clauses.append("probe_code = ?")
            params.append(probe_code)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM kh_probe_versions {where}
                ORDER BY series_code, software_version, probe_code
                """,
                tuple(params),
            ).fetchall()
            return [dict(row) for row in rows]

    def add_review_record(
        self,
        subject_type: str,
        subject_ref: str,
        decision: str,
        bucket: str = "",
        reviewer: str | None = None,
        decided_at: str | None = None,
        excerpt: str = "",
    ) -> int:
        """记录一条业务审核结论。reviewer / decided_at 属业务事实，不代填。"""
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO kh_review_records(
                    subject_type, subject_ref, decision, bucket, reviewer, decided_at, excerpt
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (subject_type, subject_ref, decision, bucket, reviewer, decided_at, excerpt),
            )
            return int(cursor.lastrowid)

    def list_review_records(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM kh_review_records ORDER BY decided_at, id"
            ).fetchall()
            return [dict(row) for row in rows]

    def add_knowledge_issue(
        self,
        issue_type: str,
        detail: str,
        severity: str = "medium",
        subject_type: str = "",
        subject_ref: str = "",
    ) -> int:
        """登记待处理问题。"""
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO kh_issues(
                    issue_type, severity, subject_type, subject_ref, detail
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (issue_type, severity, subject_type, subject_ref, detail),
            )
            return int(cursor.lastrowid)

    def list_knowledge_issues(self, status: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            if status is None:
                rows = connection.execute(
                    "SELECT * FROM kh_issues ORDER BY id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM kh_issues WHERE status = ? ORDER BY id", (status,)
                ).fetchall()
            return [dict(row) for row in rows]

    def record_review_decisions(self, release_id: int) -> dict[str, int]:
        """把该版本上已有的审核结论按原文指纹存档（幂等）。

        必须在重扫重建候选行之前调用：sync_word_candidates 会重建 pending 行与
        approved bug 行，若结论只挂在候选行 ID 上，外部按 ID 记录的结论即失效。
        """
        with self.connect() as connection:
            release = connection.execute(
                "SELECT version FROM releases WHERE id = ?", (release_id,)
            ).fetchone()
            if release is None:
                return {"recorded": 0}
            version = str(release["version"])
            rows = connection.execute(
                """
                SELECT id, category, raw_cn, raw_en, status, manually_edited
                FROM import_candidates
                WHERE release_id = ? AND status IN ('approved', 'rejected')
                """,
                (release_id,),
            ).fetchall()
            recorded = 0
            for row in rows:
                is_auto_bug = (
                    row["status"] == "approved"
                    and row["category"] == "bug"
                    and not row["manually_edited"]
                )
                connection.execute(
                    """
                    INSERT INTO review_decisions(
                        fingerprint, fingerprint_alt, release_version, category,
                        status, decision_source, excerpt, applied_candidate_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(fingerprint) DO UPDATE SET
                        status = excluded.status,
                        decision_source = excluded.decision_source,
                        excerpt = excluded.excerpt,
                        applied_candidate_id = excluded.applied_candidate_id,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        *review_fingerprints(version, row["raw_cn"], row["raw_en"]),
                        version,
                        row["category"],
                        row["status"],
                        "auto_bug" if is_auto_bug else "human",
                        _review_excerpt(row["raw_cn"], row["raw_en"]),
                        int(row["id"]),
                    ),
                )
                recorded += 1
            return {"recorded": recorded}

    def import_review_decisions(
        self, decisions: list[dict[str, Any]]
    ) -> dict[str, int]:
        """导入外部审核结论（以原文指纹为键），使其跨重扫存活。

        每条须给出 version / category / raw_cn / raw_en / status；
        reviewer 与 decided_at 属业务事实，**必须由调用方提供，不得代填**。
        """
        with self.connect() as connection:
            imported = 0
            skipped = 0
            for decision in decisions:
                version = str(decision.get("version") or "").strip()
                category = str(decision.get("category") or "").strip()
                status = str(decision.get("status") or "").strip()
                if (
                    not version
                    or not category
                    or status not in {"approved", "rejected"}
                ):
                    skipped += 1
                    continue
                raw_cn = str(decision.get("raw_cn") or "")
                raw_en = str(decision.get("raw_en") or "")
                connection.execute(
                    """
                    INSERT INTO review_decisions(
                        fingerprint, fingerprint_alt, release_version, category,
                        status, decision_source, reviewer, decided_at, excerpt
                    ) VALUES (?, ?, ?, ?, ?, 'human', ?, ?, ?)
                    ON CONFLICT(fingerprint) DO UPDATE SET
                        status = excluded.status,
                        reviewer = excluded.reviewer,
                        decided_at = excluded.decided_at,
                        excerpt = excluded.excerpt,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        *review_fingerprints(version, raw_cn, raw_en),
                        version,
                        category,
                        status,
                        decision.get("reviewer"),
                        decision.get("decided_at"),
                        _review_excerpt(raw_cn, raw_en),
                    ),
                )
                imported += 1
            return {"imported": imported, "skipped": skipped}

    def list_review_decisions(self, version: str | None = None) -> list[dict[str, Any]]:
        """列出已存档的审核结论。"""
        with self.connect() as connection:
            sql = "SELECT * FROM review_decisions"
            params: tuple[Any, ...] = ()
            if version:
                sql += " WHERE release_version = ?"
                params = (version,)
            sql += " ORDER BY release_version, category, excerpt"
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def unmatched_review_decisions(
        self, version: str | None = None
    ) -> list[dict[str, Any]]:
        """列出对不上当前任何候选的结论——原文已变化，必须人工复核。

        与“静默丢弃”相对：这里显式报告，供产品负责人重新确认。
        """
        with self.connect() as connection:
            sql = "SELECT * FROM review_decisions"
            params: tuple[Any, ...] = ()
            if version:
                sql += " WHERE release_version = ?"
                params = (version,)
            decisions = connection.execute(sql, params).fetchall()
            if not decisions:
                return []
            versions = sorted({str(row["release_version"]) for row in decisions})
            placeholders = ",".join("?" for _ in versions)
            current = connection.execute(
                f"""
                SELECT rl.version AS version, c.category AS category,
                       c.raw_cn AS raw_cn, c.raw_en AS raw_en
                FROM import_candidates c
                JOIN releases rl ON rl.id = c.release_id
                WHERE rl.version IN ({placeholders})
                """,
                tuple(versions),
            ).fetchall()
        live: set[str] = set()
        for row in current:
            live.update(review_fingerprints(row["version"], row["raw_cn"], row["raw_en"]))
        return [
            dict(row)
            for row in decisions
            if row["fingerprint"] not in live and row["fingerprint_alt"] not in live
        ]

    def sync_word_candidates(
        self,
        release_id: int,
        candidates: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Synchronize derived Word rows while preserving every human decision."""

        def row_signature(row: sqlite3.Row | dict[str, Any]) -> tuple[Any, ...]:
            return (
                row["category"],
                row["title_cn"],
                row["title_en"],
                row["raw_cn"],
                row["raw_en"],
                round(float(row["confidence"]), 6),
            )

        def evidence_key(row: sqlite3.Row | dict[str, Any]) -> tuple[str, str, str]:
            return (str(row["category"]), str(row["raw_cn"]), str(row["raw_en"]))

        with self.connect() as connection:
            all_existing = connection.execute(
                "SELECT * FROM import_candidates WHERE release_id = ? ORDER BY id",
                (release_id,),
            ).fetchall()
            mutable = [
                row
                for row in all_existing
                if not row["manually_edited"]
                and row["source_document_id"] is not None
                and (row["status"] == "pending" or (row["status"] == "approved" and row["category"] == "bug"))
            ]
            mutable_ids = {int(row["id"]) for row in mutable}
            protected_keys = {
                evidence_key(row) for row in all_existing if int(row["id"]) not in mutable_ids
            }
            desired = [candidate for candidate in candidates if evidence_key(candidate) not in protected_keys]
            if sorted(row_signature(row) for row in mutable) == sorted(
                row_signature(candidate) for candidate in desired
            ):
                return {"pending": 0, "removed": 0, "auto_approved": 0}

            for row in mutable:
                if row["category"] == "bug" and row["status"] == "approved":
                    connection.execute(
                        """
                        DELETE FROM change_events
                        WHERE release_id = ? AND category = 'bug'
                          AND description_cn = ? AND description_en = ?
                        """,
                        (release_id, row["raw_cn"], row["raw_en"]),
                    )
                connection.execute("DELETE FROM import_candidates WHERE id = ?", (row["id"],))

            source = connection.execute(
                """
                SELECT id FROM source_documents
                WHERE release_id = ?
                ORDER BY imported_at DESC, id DESC LIMIT 1
                """,
                (release_id,),
            ).fetchone()
            source_document_id = int(source["id"]) if source else None
            pending_created = 0
            auto_approved = 0
            for candidate in desired:
                is_bug = candidate["category"] == "bug"
                connection.execute(
                    """
                    INSERT INTO import_candidates(
                        release_id, category, title_cn, title_en, raw_cn, raw_en,
                        confidence, source_document_id, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        release_id,
                        candidate["category"],
                        candidate["title_cn"],
                        candidate["title_en"],
                        candidate["raw_cn"],
                        candidate["raw_en"],
                        candidate["confidence"],
                        source_document_id,
                        "approved" if is_bug else "pending",
                    ),
                )
                if not is_bug:
                    pending_created += 1
                    continue
                title = candidate["title_cn"] or candidate["title_en"]
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO change_events(
                        release_id, category, canonical_key, title_cn, title_en,
                        description_cn, description_en, review_status, confidence
                    ) VALUES (?, 'bug', ?, ?, ?, ?, ?, 'approved', ?)
                    """,
                    (
                        release_id,
                        canonical_key("bug", title),
                        candidate["title_cn"],
                        candidate["title_en"],
                        candidate["raw_cn"],
                        candidate["raw_en"],
                        candidate["confidence"],
                    ),
                )
                auto_approved += int(cursor.rowcount > 0)
            return {
                "pending": pending_created,
                "removed": len(mutable),
                "auto_approved": auto_approved,
            }

    def auto_approve_pending_bugs(self) -> int:
        """Move legacy pending Bug candidates directly into their release records."""
        migrated = 0
        with self.connect() as connection:
            candidates = connection.execute(
                """
                SELECT * FROM import_candidates
                WHERE category = 'bug' AND status = 'pending'
                ORDER BY id
                """
            ).fetchall()
            for candidate in candidates:
                title = candidate["title_cn"] or candidate["title_en"]
                connection.execute(
                    """
                    INSERT OR IGNORE INTO change_events(
                        release_id, category, canonical_key, title_cn, title_en,
                        description_cn, description_en, review_status, confidence
                    ) VALUES (?, 'bug', ?, ?, ?, ?, ?, 'approved', ?)
                    """,
                    (
                        candidate["release_id"],
                        canonical_key("bug", title),
                        candidate["title_cn"],
                        candidate["title_en"],
                        candidate["raw_cn"],
                        candidate["raw_en"],
                        candidate["confidence"],
                    ),
                )
                connection.execute(
                    "UPDATE import_candidates SET status = 'approved' WHERE id = ?",
                    (candidate["id"],),
                )
                migrated += 1
        return migrated

    def has_source_document(self, path: str, sha256: str) -> bool:
        with self.connect() as connection:
            return connection.execute(
                "SELECT 1 FROM source_documents WHERE path = ? AND sha256 = ?",
                (path, sha256),
            ).fetchone() is not None

    def add_import_candidate(
        self,
        release_id: int,
        category: str,
        title_cn: str,
        title_en: str,
        raw_cn: str,
        raw_en: str,
        confidence: float,
        source_document_id: int | None,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO import_candidates(
                    release_id, category, title_cn, title_en, raw_cn, raw_en,
                    confidence, source_document_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    release_id,
                    category,
                    title_cn,
                    title_en,
                    raw_cn,
                    raw_en,
                    confidence,
                    source_document_id,
                ),
            )
            return int(cursor.lastrowid)

    def has_import_candidate(
        self,
        release_id: int,
        category: str,
        raw_cn: str,
        raw_en: str,
    ) -> bool:
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT 1 FROM import_candidates
                WHERE release_id = ? AND category = ? AND raw_cn = ? AND raw_en = ?
                """,
                (release_id, category, raw_cn, raw_en),
            ).fetchone() is not None

    def create_review_issue(self, issue_type: str, message: str, release_id: int) -> int:
        with self.connect() as connection:
            existing = connection.execute(
                """
                SELECT id FROM review_issues
                WHERE issue_type = ? AND message = ? AND release_id = ? AND status = 'open'
                """,
                (issue_type, message, release_id),
            ).fetchone()
            if existing:
                return int(existing["id"])
            cursor = connection.execute(
                """
                INSERT INTO review_issues(issue_type, message, release_id)
                VALUES (?, ?, ?)
                """,
                (issue_type, message, release_id),
            )
            return int(cursor.lastrowid)

    def list_import_candidates(
        self, status: str = "pending", project_id: int | None = None
    ) -> list[dict[str, Any]]:
        selected_project_id = project_id or self.default_project_id()
        with self.connect() as connection:
            candidates = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT c.*, r.version, r.project_id,
                           (
                               SELECT COUNT(*) FROM source_documents source
                               WHERE source.release_id = c.release_id
                                 AND source.tables_json != '[]'
                           ) AS configuration_table_count
                    FROM import_candidates c
                    LEFT JOIN releases r ON r.id = c.release_id
                    WHERE c.status = ? AND r.project_id = ?
                    ORDER BY c.id
                    """,
                    (status, selected_project_id),
                ).fetchall()
            ]
        for candidate in candidates:
            missing_languages = []
            if not str(candidate["title_cn"]).strip():
                missing_languages.append("缺少中文")
            if not str(candidate["title_en"]).strip():
                missing_languages.append("缺少英文")
            if missing_languages:
                candidate["review_bucket"] = "missing_language"
                candidate["risk_level"] = "high"
                candidate["risk_reasons"] = missing_languages
            elif float(candidate["confidence"]) < 0.8:
                candidate["review_bucket"] = "semantic_review"
                candidate["risk_level"] = "medium"
                candidate["risk_reasons"] = ["中英文语义匹配待确认"]
            else:
                candidate["review_bucket"] = "ready"
                candidate["risk_level"] = "low"
                candidate["risk_reasons"] = []
        priority = {"missing_language": 0, "semantic_review": 1, "ready": 2}
        return sorted(
            candidates,
            key=lambda candidate: (
                version_key(candidate["version"]),
                -1 if candidate["manually_edited"] else priority[candidate["review_bucket"]],
                candidate["id"],
            ),
        )

    def list_release_configuration_tables(self, release_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            release = connection.execute(
                "SELECT id FROM releases WHERE id = ?", (release_id,)
            ).fetchone()
            if release is None:
                raise KeyError("release")
            rows = connection.execute(
                """
                SELECT id, filename, language, tables_json
                FROM source_documents
                WHERE release_id = ? AND tables_json != '[]'
                ORDER BY CASE language WHEN 'cn' THEN 0 WHEN 'en' THEN 1 ELSE 2 END, id
                """,
                (release_id,),
            ).fetchall()
        return [
            {
                "source_document_id": int(row["id"]),
                "filename": row["filename"],
                "language": row["language"],
                "tables": json.loads(row["tables_json"]),
            }
            for row in rows
        ]

    def get_release_archive(self, release_id: int) -> dict[str, Any]:
        """Return the five structured table families with their original evidence."""
        with self.connect() as connection:
            release = connection.execute(
                "SELECT * FROM releases WHERE id = ?", (release_id,)
            ).fetchone()
            if release is None:
                raise KeyError("release")
            table_rows = connection.execute(
                """
                SELECT table_data.*, source.filename
                FROM release_tables table_data
                JOIN source_documents source ON source.id = table_data.source_document_id
                WHERE table_data.release_id = ? AND table_data.table_type != 'other'
                ORDER BY CASE table_data.language WHEN 'cn' THEN 0 WHEN 'en' THEN 1 ELSE 2 END,
                         table_data.table_index, table_data.id
                """,
                (release_id,),
            ).fetchall()
            tables: list[dict[str, Any]] = []
            type_summary: dict[str, dict[str, int]] = {}
            conflict_count = 0
            row_count = 0
            for table_row in table_rows:
                records = [
                    {
                        **dict(record),
                        "data": json.loads(record["data_json"]),
                    }
                    for record in connection.execute(
                        """
                        SELECT * FROM release_table_rows
                        WHERE table_id = ? ORDER BY row_index, id
                        """,
                        (table_row["id"],),
                    ).fetchall()
                ]
                for record in records:
                    record.pop("data_json", None)
                table_type = str(table_row["table_type"])
                row_total = len(records)
                row_count += row_total
                conflict_count += sum(
                    record["pair_status"] == "conflict" for record in records
                )
                totals = type_summary.setdefault(
                    table_type, {"table_count": 0, "row_count": 0}
                )
                totals["table_count"] += 1
                totals["row_count"] += row_total
                tables.append(
                    {
                        "id": int(table_row["id"]),
                        "source_document_id": int(table_row["source_document_id"]),
                        "filename": table_row["filename"],
                        "table_index": int(table_row["table_index"]),
                        "language": table_row["language"],
                        "market": (
                            "domestic"
                            if table_row["language"] == "cn"
                            else "overseas"
                            if table_row["language"] == "en"
                            else "unknown"
                        ),
                        "table_type": table_type,
                        "snapshot_mode": table_row["snapshot_mode"],
                        "headers": json.loads(table_row["headers_json"]),
                        "rows": json.loads(table_row["rows_json"]),
                        "records": records,
                    }
                )
        return {
            "release": dict(release),
            "summary": {
                "table_count": len(tables),
                "row_count": row_count,
                "conflict_count": conflict_count,
                "types": type_summary,
            },
            "tables": tables,
        }

    @staticmethod
    def _preferred_structured_rows(
        connection: sqlite3.Connection, release_id: int
    ) -> list[sqlite3.Row]:
        rows = connection.execute(
            """
            SELECT row.*, table_data.table_type, table_data.snapshot_mode
            FROM release_table_rows row
            JOIN release_tables table_data ON table_data.id = row.table_id
            WHERE row.release_id = ? AND table_data.table_type != 'other'
            ORDER BY table_data.id, row.row_index, row.id
            """,
            (release_id,),
        ).fetchall()
        preferred: dict[tuple[str, str], sqlite3.Row] = {}
        for row in rows:
            key = (str(row["table_type"]), str(row["stable_key"]).casefold())
            current = preferred.get(key)
            if current is None or (current["language"] != "cn" and row["language"] == "cn"):
                preferred[key] = row
        return list(preferred.values())

    def get_effective_configuration(self, release_id: int) -> dict[str, Any]:
        """Build separate domestic and overseas configuration histories."""
        with self.connect() as connection:
            target = connection.execute(
                "SELECT id, project_id, version FROM releases WHERE id = ?", (release_id,)
            ).fetchone()
            if target is None:
                raise KeyError("release")
            # 只累计**本项目**的版本：不同项目各自独立编号（G2 1.50/1.51 与 V10 1.14），
            # 此前取全表 releases 并按版本号排序，会把别的项目的配置矩阵算进本版本的
            # 「国内/海外配置（截至本版本）」——G2 1.50.11 显示的整份配置都来自 V10。
            releases = connection.execute(
                "SELECT id, version FROM releases WHERE project_id = ?",
                (int(target["project_id"]),),
            ).fetchall()
            ordered = sorted(
                (row for row in releases if version_key(row["version"]) <= version_key(target["version"])),
                key=lambda row: version_key(row["version"]),
            )
            markets: dict[str, dict[str, Any]] = {}
            for market, language, label in (
                ("domestic", "cn", "国内配置"),
                ("overseas", "en", "海外配置"),
            ):
                state: dict[str, dict[str, Any]] = {}
                for release in ordered:
                    rows = connection.execute(
                        """
                        SELECT row.*, table_data.snapshot_mode
                        FROM release_table_rows row
                        JOIN release_tables table_data ON table_data.id = row.table_id
                        WHERE row.release_id = ?
                          AND table_data.table_type = 'configuration_matrix'
                          AND row.language = ?
                        ORDER BY table_data.id, row.row_index, row.id
                        """,
                        (int(release["id"]), language),
                    ).fetchall()
                    if any(row["snapshot_mode"] == "full_snapshot" for row in rows):
                        state.clear()
                    for row in rows:
                        key = str(row["stable_key"])
                        current = state.setdefault(
                            key,
                            {
                                "stable_key": key,
                                "item_code": row["item_code"],
                                "item_name": row["item_name"],
                                "values": {},
                                "last_changed_version": release["version"],
                            },
                        )
                        if row["item_code"]:
                            current["item_code"] = row["item_code"]
                        if row["item_name"]:
                            current["item_name"] = row["item_name"]
                        current["values"].update(json.loads(row["data_json"]))
                        current["values"] = dict(sorted(current["values"].items()))
                        current["last_changed_version"] = release["version"]
                markets[market] = {
                    "label": label,
                    "source_language": language,
                    "records": sorted(state.values(), key=lambda item: item["stable_key"]),
                }
        return {
            "as_of_version": target["version"],
            "markets": markets,
        }

    def compare_release_structured(
        self, earlier_release_id: int, later_release_id: int
    ) -> dict[str, list[dict[str, Any]]]:
        effective_configurations = {
            earlier_release_id: self.get_effective_configuration(earlier_release_id),
            later_release_id: self.get_effective_configuration(later_release_id),
        }
        with self.connect() as connection:
            for release_id in (earlier_release_id, later_release_id):
                if connection.execute(
                    "SELECT 1 FROM releases WHERE id = ?", (release_id,)
                ).fetchone() is None:
                    raise KeyError("release")

            def snapshot(release_id: int) -> dict[tuple[str, str], dict[str, Any]]:
                result: dict[tuple[str, str], dict[str, Any]] = {}
                for row in self._preferred_structured_rows(connection, release_id):
                    if row["table_type"] == "configuration_matrix":
                        continue
                    item = dict(row)
                    item["data"] = json.loads(item.pop("data_json"))
                    result[(item["table_type"], item["stable_key"].casefold())] = item
                for market, market_data in effective_configurations[release_id]["markets"].items():
                    for record in market_data["records"]:
                        result[(f"configuration_matrix:{market}", record["stable_key"].casefold())] = {
                            "table_type": "configuration_matrix",
                            "market": market,
                            "stable_key": record["stable_key"],
                            "item_code": record["item_code"],
                            "item_name": record["item_name"],
                            "change_kind": "snapshot",
                            "data": record["values"],
                        }
                return result

            earlier = snapshot(earlier_release_id)
            later = snapshot(later_release_id)
        comparison: dict[str, list[dict[str, Any]]] = {
            "added": [], "removed": [], "modified": [], "unchanged": []
        }
        for key in sorted(set(earlier) | set(later)):
            old, new = earlier.get(key), later.get(key)
            source = new or old
            item = {
                "table_type": source["table_type"],
                "market": source.get("market"),
                "stable_key": source["stable_key"],
                "item_code": source["item_code"],
                "item_name": source["item_name"],
                "old_data": old["data"] if old else None,
                "new_data": new["data"] if new else None,
            }
            if old is None:
                bucket = "added"
            elif new is None:
                bucket = "removed"
            elif old["data"] != new["data"] or old["change_kind"] != new["change_kind"]:
                bucket = "modified"
            else:
                bucket = "unchanged"
            comparison[bucket].append(item)
        return comparison

    def approve_import_candidates(self, candidate_ids: list[int]) -> dict[str, Any]:
        """把候选批量记入版本变更。

        `merged_candidates` 列出被并入已有变更记录的候选：它们同样算已提交，
        但如实报告「本次没有新建记录」，避免批量结果看起来比实际写入的多。
        """

        unique_ids = list(dict.fromkeys(candidate_ids))
        if not unique_ids:
            raise ValueError("Choose at least one pending candidate")
        placeholders = ", ".join("?" for _ in unique_ids)
        with self.connect() as connection:
            candidates = connection.execute(
                f"SELECT * FROM import_candidates WHERE id IN ({placeholders}) ORDER BY id",
                unique_ids,
            ).fetchall()
            by_id = {int(candidate["id"]): candidate for candidate in candidates}
            if len(by_id) != len(unique_ids):
                raise KeyError("candidate")
            if any(by_id[candidate_id]["status"] != "pending" for candidate_id in unique_ids):
                raise ValueError("Only pending candidates can be approved")
            unsupported = sorted(
                {
                    str(by_id[candidate_id]["category"])
                    for candidate_id in unique_ids
                    if str(by_id[candidate_id]["category"]) not in CHANGE_CATEGORIES
                }
            )
            if unsupported:
                # 明确报出分类不在词表里，而不是让数据库 CHECK 抛一句看不懂的冲突。
                raise ValueError(
                    "以下分类不在变更分类词表中，无法入版本："
                    + "、".join(unsupported)
                    + "。请先修订候选分类。"
                )
            merged: list[dict[str, Any]] = []
            for candidate_id in unique_ids:
                candidate = by_id[candidate_id]
                title = candidate["title_cn"] or candidate["title_en"]
                key = canonical_key(candidate["category"], title)
                cursor = connection.execute(
                    """
                    INSERT INTO change_events(
                        release_id, category, canonical_key, title_cn, title_en,
                        description_cn, description_en, review_status, confidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'approved', ?)
                    ON CONFLICT(release_id, category, canonical_key) DO NOTHING
                    """,
                    (
                        candidate["release_id"],
                        candidate["category"],
                        key,
                        candidate["title_cn"],
                        candidate["title_en"],
                        candidate["raw_cn"],
                        candidate["raw_en"],
                        candidate["confidence"],
                    ),
                )
                if cursor.rowcount == 0:
                    # 同版本已有同分类同标题的变更记录（重扫产生的重复行、或中英文各成一行）。
                    # 这里合并而不是新建第二条：只补齐缺失的中/英文与描述，绝不覆盖已有内容；
                    # 早期实现直接 INSERT，一旦命中唯一索引就整批回滚，批量审核因此完全不可用。
                    merged.append(
                        self._merge_change_event(
                            connection,
                            release_id=int(candidate["release_id"]),
                            category=str(candidate["category"]),
                            key=key,
                            title_cn=candidate["title_cn"],
                            title_en=candidate["title_en"],
                            description_cn=candidate["raw_cn"],
                            description_en=candidate["raw_en"],
                            confidence=candidate["confidence"],
                        )
                        | {"candidate_id": candidate_id}
                    )
                connection.execute(
                    "UPDATE import_candidates SET status = 'approved' WHERE id = ?",
                    (candidate_id,),
                )
        return {"approved_candidate_ids": unique_ids, "merged_candidates": merged}

    @staticmethod
    def _merge_change_event(
        connection: sqlite3.Connection,
        *,
        release_id: int,
        category: str,
        key: str,
        title_cn: str,
        title_en: str,
        description_cn: str,
        description_en: str,
        confidence: float,
        feature_id: int | None = None,
    ) -> dict[str, Any]:
        """把重复候选并入同版本已有的变更记录，只填空白字段。

        重复来自两种情况：同一句话被抽了两遍（中英文各一行），或重扫后又被产出一遍。
        合并语义是「补齐」：已有内容一律保留，只把空的标题/描述补上、置信度取较高值。
        """

        row = connection.execute(
            """
            SELECT id FROM change_events
            WHERE release_id = ? AND category = ? AND canonical_key = ?
            """,
            (release_id, category, key),
        ).fetchone()
        connection.execute(
            """
            UPDATE change_events SET
                title_cn = CASE WHEN COALESCE(title_cn, '') = '' THEN ? ELSE title_cn END,
                title_en = CASE WHEN COALESCE(title_en, '') = '' THEN ? ELSE title_en END,
                description_cn = CASE WHEN COALESCE(description_cn, '') = '' THEN ? ELSE description_cn END,
                description_en = CASE WHEN COALESCE(description_en, '') = '' THEN ? ELSE description_en END,
                feature_id = CASE WHEN feature_id IS NULL THEN ? ELSE feature_id END,
                confidence = CASE
                    WHEN confidence IS NULL OR confidence < ? THEN ? ELSE confidence END
            WHERE release_id = ? AND category = ? AND canonical_key = ?
            """,
            (
                title_cn,
                title_en,
                description_cn,
                description_en,
                feature_id,
                confidence,
                confidence,
                release_id,
                category,
                key,
            ),
        )
        return {
            "change_event_id": int(row["id"]) if row else None,
            "category": category,
            "canonical_key": key,
            "reason": "同版本已有相同分类与标题的变更记录，已合并为一条并补齐缺失的中/英文",
        }

    @staticmethod
    def _name_is_present_in_text(name: str, text: str) -> bool:
        if not name or name == "—":
            return False
        if re.fullmatch(r"[A-Za-z0-9+/-]+", name):
            return re.search(
                rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])",
                text,
                re.IGNORECASE,
            ) is not None
        return name.casefold() in text.casefold()

    def _feature_match_candidates(
        self, connection: sqlite3.Connection, candidate: sqlite3.Row
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """返回 (命中的现有功能, 命中的已确认术语)。

        命中＝该名称出现在候选的对应语言标题里（中英都要命中），与既有建立功能的
        判定口径一致；调用方据此决定是“增强已有功能”还是“据术语新建”。
        """
        if not candidate["title_cn"] or not candidate["title_en"]:
            return [], []
        release = connection.execute(
            "SELECT project_id FROM releases WHERE id = ?", (candidate["release_id"],)
        ).fetchone()
        if release is None:
            raise KeyError("release")
        feature_matches = [
            dict(feature)
            for feature in connection.execute(
                """SELECT id, cn_name, en_name, category, NULL AS term_id
                   FROM features WHERE project_id = ?""",
                (release["project_id"],),
            ).fetchall()
            if self._name_is_present_in_text(feature["cn_name"], candidate["title_cn"])
            and self._name_is_present_in_text(feature["en_name"], candidate["title_en"])
        ]
        if feature_matches:
            return feature_matches, []
        term_matches = [
            dict(term)
            for term in connection.execute(
                """SELECT id, cn_name, en_name, category, id AS term_id FROM terms
                   WHERE needs_review = 0 AND entry_type = 'term'"""
            ).fetchall()
            if self._name_is_present_in_text(term["cn_name"], candidate["title_cn"])
            and self._name_is_present_in_text(term["en_name"], candidate["title_en"])
        ]
        return [], term_matches

    def _resolve_verified_feature_match(
        self, connection: sqlite3.Connection, candidate: sqlite3.Row
    ) -> dict[str, Any] | None:
        if not candidate["title_cn"] or not candidate["title_en"]:
            return None
        feature_matches, term_matches = self._feature_match_candidates(connection, candidate)
        if len(feature_matches) == 1:
            return {**feature_matches[0], "source": "feature"}
        if feature_matches:
            return None
        return {**term_matches[0], "source": "term"} if len(term_matches) == 1 else None

    def recommend_candidate_actions(self, candidate_ids: list[int]) -> list[dict[str, Any]]:
        """为待审候选生成**推荐处置**，供审核时一键确认。

        推荐只表达系统能证实的东西，不代替人做决定：

        - 非功能类（配置/兼容性说明/探头/图像/备注/待确认）→ `record_only`：记入版本变更；
        - 功能类且功能库**唯一**命中 → `enhance_feature`：增强已有功能（可给出 feature_id）；
        - 功能类且术语词典唯一命中 → `create_feature`：按词典标准双语名新建功能；
        - 其余（缺中/英、多个疑似同名、查不到匹配）→ `record_only`，并在 reason 里说明原因，
          而不是替人猜一个功能。
        """
        unique_ids = list(dict.fromkeys(int(value) for value in candidate_ids))
        if not unique_ids:
            return []
        placeholders = ", ".join("?" for _ in unique_ids)
        recommendations: list[dict[str, Any]] = []
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM import_candidates WHERE id IN ({placeholders}) ORDER BY id",
                unique_ids,
            ).fetchall()
            for row in rows:
                candidate = dict(row)
                label = CHANGE_CATEGORY_LABELS.get(str(candidate["category"]), candidate["category"])
                if candidate["category"] != "function":
                    recommendations.append(
                        {
                            "candidate_id": int(candidate["id"]),
                            "action": "record_only",
                            "label": "记入版本变更",
                            "reason": f"{label}类内容不进功能库，记入本版本变更记录即可",
                        }
                    )
                    continue
                feature_matches, term_matches = self._feature_match_candidates(connection, candidate)
                if len(feature_matches) == 1:
                    match = feature_matches[0]
                    recommendations.append(
                        {
                            "candidate_id": int(candidate["id"]),
                            "action": "enhance_feature",
                            "feature_id": int(match["id"]),
                            "cn_name": match["cn_name"],
                            "en_name": match["en_name"],
                            "label": f"增强已有功能《{match['cn_name']}》",
                            "reason": "功能库唯一命中，归入同一档案形成连续修订历史",
                        }
                    )
                    continue
                if feature_matches:
                    names = "、".join(str(item["cn_name"]) for item in feature_matches[:3])
                    recommendations.append(
                        {
                            "candidate_id": int(candidate["id"]),
                            "action": "record_only",
                            "label": "记入版本变更",
                            "reason": f"功能库有 {len(feature_matches)} 个疑似同名功能（{names}），需人工指定归入哪个",
                        }
                    )
                    continue
                if len(term_matches) == 1:
                    match = term_matches[0]
                    recommendations.append(
                        {
                            "candidate_id": int(candidate["id"]),
                            "action": "create_feature",
                            "cn_name": match["cn_name"],
                            "en_name": match["en_name"],
                            "category": match["category"],
                            "label": f"新建功能《{match['cn_name']}》",
                            "reason": "功能库无匹配，术语词典有唯一已确认词条，可据此建档",
                        }
                    )
                    continue
                if not candidate["title_cn"] or not candidate["title_en"]:
                    reason = "缺少中文或英文名称，先记入版本变更；补齐双语后可再建立功能"
                else:
                    reason = "功能库与术语词典都没有可确认的唯一匹配，先记入版本变更"
                recommendations.append(
                    {
                        "candidate_id": int(candidate["id"]),
                        "action": "record_only",
                        "label": "记入版本变更",
                        "reason": reason,
                    }
                )
        return recommendations

    def confirm_import_candidates(self, candidate_ids: list[int]) -> dict[str, Any]:
        """按推荐处置批量提交：能建立/关联功能的建立或关联，其余记入版本变更。"""
        unique_ids = list(dict.fromkeys(int(value) for value in candidate_ids))
        if not unique_ids:
            raise ValueError("Choose at least one pending candidate")
        recommendations = self.recommend_candidate_actions(unique_ids)
        if not recommendations:
            # 与其它批量接口一致：指定的候选不存在时按 404 处理，而不是静默成功。
            raise KeyError("candidate")
        promote_ids = [
            item["candidate_id"]
            for item in recommendations
            if item["action"] in {"create_feature", "enhance_feature"}
        ]
        record_ids = [
            item["candidate_id"] for item in recommendations if item["action"] == "record_only"
        ]
        submitted: list[int] = []
        skipped: list[dict[str, Any]] = []
        merged: list[dict[str, Any]] = []
        if record_ids:
            approved = self.approve_import_candidates(record_ids)
            submitted.extend(approved["approved_candidate_ids"])
            merged.extend(approved.get("merged_candidates", []))
        if promote_ids:
            promoted = self.promote_import_candidates(promote_ids)
            submitted.extend(promoted["approved_candidate_ids"])
            skipped.extend(promoted["skipped_candidates"])
            merged.extend(promoted.get("merged_candidates", []))
        return {
            "submitted_candidate_ids": submitted,
            "skipped_candidates": skipped,
            "merged_candidates": merged,
            "recommendations": recommendations,
        }

    @staticmethod
    def _with_description_flag(feature: dict[str, Any]) -> dict[str, Any]:
        """附上「只有标题」标记，供界面统一渲染「说明待完善」。

        判据只有 `domain.description_is_title_only` 一处实现：前端不再自己判断，
        否则补全后的正文（可能以「新增…」开头）会被界面规则误标。
        """
        feature["description_title_only"] = description_is_title_only(
            feature.get("cn_description", ""), feature.get("en_description", "")
        )
        return feature

    @staticmethod
    def _candidate_feature_description(candidate: Any) -> tuple[str, str]:
        """建立功能时写入的描述＝已批准原文的完整段落（见 `domain.feature_description`）。

        此前这里取的是 `title_cn/title_en`，即原文的首行变更说法，导致功能库只剩标题。
        """
        return feature_description(
            str(candidate["title_cn"] or ""),
            str(candidate["title_en"] or ""),
            str(candidate["raw_cn"] or ""),
            str(candidate["raw_en"] or ""),
        )

    def promote_import_candidates(self, candidate_ids: list[int]) -> dict[str, Any]:
        unique_ids = list(dict.fromkeys(candidate_ids))
        if not unique_ids:
            raise ValueError("Choose at least one pending candidate")
        placeholders = ", ".join("?" for _ in unique_ids)
        approved_candidate_ids: list[int] = []
        skipped_candidates: list[dict[str, Any]] = []
        merged_candidates: list[dict[str, Any]] = []
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM import_candidates WHERE id IN ({placeholders}) ORDER BY id",
                unique_ids,
            ).fetchall()
            by_id = {int(row["id"]): row for row in rows}
            if len(by_id) != len(unique_ids):
                raise KeyError("candidate")
            for candidate_id in unique_ids:
                candidate = by_id[candidate_id]
                if candidate["status"] != "pending":
                    skipped_candidates.append({"candidate_id": candidate_id, "reason": "记录不在待审核状态"})
                    continue
                if candidate["category"] != "function":
                    skipped_candidates.append({"candidate_id": candidate_id, "reason": "仅功能类记录可建立功能"})
                    continue
                match = self._resolve_verified_feature_match(connection, candidate)
                release = connection.execute(
                    "SELECT project_id FROM releases WHERE id = ?", (candidate["release_id"],)
                ).fetchone()
                if release is None:
                    raise KeyError("release")
                if match is None:
                    skipped_candidates.append(
                        {"candidate_id": candidate_id, "reason": "未找到唯一且已确认的中英文术语"}
                    )
                    continue
                if match["source"] == "feature":
                    feature_id = int(match["id"])
                    revision_number = int(
                        connection.execute(
                            "SELECT COALESCE(MAX(revision_number), 0) + 1 FROM feature_revisions WHERE feature_id = ?",
                            (feature_id,),
                        ).fetchone()[0]
                    )
                    description_cn, description_en = self._candidate_feature_description(
                        candidate
                    )
                    connection.execute(
                        """
                        INSERT INTO feature_revisions(feature_id, revision_number, cn_description, en_description, review_status)
                        VALUES (?, ?, ?, ?, 'approved')
                        """,
                        (feature_id, revision_number, description_cn, description_en),
                    )
                    connection.execute(
                        """
                        UPDATE features SET cn_description = ?, en_description = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (description_cn, description_en, feature_id),
                    )
                else:
                    description_cn, description_en = self._candidate_feature_description(
                        candidate
                    )
                    cursor = connection.execute(
                        """
                        INSERT INTO features(
                            project_id, term_id, cn_name, en_name, category,
                            cn_description, en_description
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            release["project_id"],
                            match["term_id"],
                            match["cn_name"],
                            match["en_name"],
                            match["category"],
                            description_cn,
                            description_en,
                        ),
                    )
                    feature_id = int(cursor.lastrowid)
                    connection.execute(
                        """
                        INSERT INTO feature_revisions(feature_id, revision_number, cn_description, en_description, review_status)
                        VALUES (?, 1, ?, ?, 'approved')
                        """,
                        (feature_id, description_cn, description_en),
                    )
                for market in ("domestic", "overseas"):
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO feature_market_releases(feature_id, release_id, market)
                        VALUES (?, ?, ?)
                        """,
                        (feature_id, candidate["release_id"], market),
                    )
                title = candidate["title_cn"] or candidate["title_en"]
                key = canonical_key(candidate["category"], title)
                cursor = connection.execute(
                    """
                    INSERT INTO change_events(
                        release_id, category, canonical_key, title_cn, title_en,
                        description_cn, description_en, feature_id, review_status, confidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?)
                    ON CONFLICT(release_id, category, canonical_key) DO NOTHING
                    """,
                    (
                        candidate["release_id"],
                        candidate["category"],
                        key,
                        candidate["title_cn"],
                        candidate["title_en"],
                        candidate["raw_cn"],
                        candidate["raw_en"],
                        feature_id,
                        candidate["confidence"],
                    ),
                )
                if cursor.rowcount == 0:
                    # 该功能在本版本已有同样的变更记录：补上 feature_id 即可，
                    # 不能因为唯一索引冲突让整批提交失败。
                    merged_candidates.append(
                        self._merge_change_event(
                            connection,
                            release_id=int(candidate["release_id"]),
                            category=str(candidate["category"]),
                            key=key,
                            title_cn=candidate["title_cn"],
                            title_en=candidate["title_en"],
                            description_cn=candidate["raw_cn"],
                            description_en=candidate["raw_en"],
                            confidence=candidate["confidence"],
                            feature_id=feature_id,
                        )
                        | {"candidate_id": candidate_id}
                    )
                connection.execute(
                    "UPDATE import_candidates SET status = 'approved', proposed_feature_id = ? WHERE id = ?",
                    (feature_id, candidate_id),
                )
                approved_candidate_ids.append(candidate_id)
        return {
            "approved_candidate_ids": approved_candidate_ids,
            "skipped_candidates": skipped_candidates,
            "merged_candidates": merged_candidates,
        }

    def list_pending_candidates_for_release(self, release_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT * FROM import_candidates
                    WHERE release_id = ? AND status = 'pending'
                    ORDER BY category, id
                    """,
                    (release_id,),
                ).fetchall()
            ]

    def correct_pending_candidate_categories(
        self,
        release_id: int,
        category_evidence: dict[str, set[str]],
    ) -> int:
        """Correct untouched Word candidates when a heading parser gains a missing alias."""
        corrected = 0
        with self.connect() as connection:
            candidates = connection.execute(
                """
                SELECT id, category, raw_cn, raw_en
                FROM import_candidates
                WHERE release_id = ? AND status = 'pending' AND manually_edited = 0
                  AND source_document_id IS NOT NULL
                """,
                (release_id,),
            ).fetchall()
            for candidate in candidates:
                supported_categories: set[str] = set()
                for text in (candidate["raw_cn"], candidate["raw_en"]):
                    if text:
                        supported_categories.update(category_evidence.get(text, set()))
                if len(supported_categories) != 1:
                    continue
                corrected_category = next(iter(supported_categories))
                if corrected_category == candidate["category"]:
                    continue
                connection.execute(
                    "UPDATE import_candidates SET category = ? WHERE id = ?",
                    (corrected_category, candidate["id"]),
                )
                corrected += 1
        return corrected

    def remove_excel_reference_content(self) -> dict[str, int]:
        """Keep only release content traceable to an imported Word source document."""
        with self.connect() as connection:
            removed_changes = connection.execute(
                """
                DELETE FROM change_events
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM import_candidates candidate
                    WHERE candidate.release_id = change_events.release_id
                      AND candidate.status = 'approved'
                      AND candidate.category = change_events.category
                      AND (
                        (candidate.raw_cn <> '' AND candidate.raw_cn = change_events.description_cn)
                        OR (candidate.raw_en <> '' AND candidate.raw_en = change_events.description_en)
                      )
                )
                """
            ).rowcount
            removed_releases = connection.execute(
                """
                DELETE FROM releases
                WHERE NOT EXISTS (
                    SELECT 1 FROM source_documents source
                    WHERE source.release_id = releases.id
                )
                """
            ).rowcount
        return {"changes": removed_changes, "releases": removed_releases}

    def update_pending_candidate_alignment(
        self,
        updates: list[dict[str, Any]],
    ) -> None:
        with self.connect() as connection:
            for update in updates:
                cursor = connection.execute(
                    """
                    UPDATE import_candidates
                    SET title_cn = ?, title_en = ?, raw_cn = ?, raw_en = ?, confidence = ?
                    WHERE id = ? AND status = 'pending' AND manually_edited = 0
                      AND category = ?
                      AND title_cn = ? AND title_en = ?
                      AND raw_cn = ? AND raw_en = ?
                    """,
                    (
                        update["cn_text"],
                        update["en_text"],
                        update["cn_text"],
                        update["en_text"],
                        update["confidence"],
                        update["candidate_id"],
                        update["expected_category"],
                        update["expected_title_cn"],
                        update["expected_title_en"],
                        update["expected_raw_cn"],
                        update["expected_raw_en"],
                    ),
                )
                if cursor.rowcount != 1:
                    raise sqlite3.IntegrityError(
                        "Candidate alignment changed during semantic repair"
                    )

    def replace_pending_candidate_alignment(
        self,
        candidates: list[dict[str, Any]],
        aligned: list[tuple[str, str, float]],
    ) -> None:
        """Safely replace an untouched pending group with stricter bilingual alignment."""
        if not candidates:
            return
        release_id = int(candidates[0]["release_id"])
        category = str(candidates[0]["category"])
        with self.connect() as connection:
            for candidate in candidates:
                current = connection.execute(
                    """
                    SELECT * FROM import_candidates
                    WHERE id = ? AND status = 'pending' AND manually_edited = 0
                    """,
                    (candidate["id"],),
                ).fetchone()
                if (
                    current is None
                    or current["release_id"] != candidate["release_id"]
                    or current["category"] != candidate["category"]
                    or current["title_cn"] != candidate["title_cn"]
                    or current["title_en"] != candidate["title_en"]
                    or current["raw_cn"] != candidate["raw_cn"]
                    or current["raw_en"] != candidate["raw_en"]
                ):
                    raise sqlite3.IntegrityError(
                        "Candidate alignment changed during semantic repair"
                    )
            shared = min(len(candidates), len(aligned))
            for candidate, (cn_text, en_text, confidence) in zip(candidates[:shared], aligned[:shared]):
                connection.execute(
                    """
                    UPDATE import_candidates
                    SET title_cn = ?, title_en = ?, raw_cn = ?, raw_en = ?, confidence = ?
                    WHERE id = ?
                    """,
                    (cn_text, en_text, cn_text, en_text, confidence, candidate["id"]),
                )
            source_document_id = candidates[0]["source_document_id"]
            for cn_text, en_text, confidence in aligned[shared:]:
                connection.execute(
                    """
                    INSERT INTO import_candidates(
                        release_id, category, title_cn, title_en, raw_cn, raw_en,
                        confidence, source_document_id, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        release_id,
                        category,
                        cn_text,
                        en_text,
                        cn_text,
                        en_text,
                        confidence,
                        source_document_id,
                    ),
                )
            for candidate in candidates[shared:]:
                connection.execute(
                    "DELETE FROM import_candidates WHERE id = ?", (candidate["id"],)
                )

    # 人工确认合并后的置信度：两侧语言都齐、且由人判定为同一条，属于「可快速确认」档，
    # 取与语义锚定同样的 0.85，避免落进 <0.8 的「语义待核对」桶。
    MERGED_PAIR_CONFIDENCE = 0.85

    @staticmethod
    def _single_language_pending_rows(
        connection: sqlite3.Connection, release_id: int, category: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """该版本该分类下「只有中文」「只有英文」的待审核行，按文档顺序（id）。"""

        rows = connection.execute(
            """
            SELECT * FROM import_candidates
            WHERE release_id = ? AND category = ? AND status = 'pending'
            ORDER BY id
            """,
            (release_id, category),
        ).fetchall()
        chinese = [
            dict(row)
            for row in rows
            if str(row["title_cn"]).strip() and not str(row["title_en"]).strip()
        ]
        english = [
            dict(row)
            for row in rows
            if str(row["title_en"]).strip() and not str(row["title_cn"]).strip()
        ]
        return chinese, english

    def list_suspected_candidate_pairs(
        self, project_id: int | None = None
    ) -> list[dict[str, Any]]:
        """列出「疑似同一变更」的中英配对，供人工一次确认合并。

        规则与扫描时生成提醒用的完全一致（`domain.pair_single_language_items`）：
        同版本同分类下中英两侧未配对条数相等时，按文档顺序 1:1 配对。数量不等不推测。
        """

        selected_project_id = project_id or self.default_project_id()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT candidate.release_id, candidate.category, release.version
                FROM import_candidates candidate
                JOIN releases release ON release.id = candidate.release_id
                WHERE candidate.status = 'pending' AND release.project_id = ?
                GROUP BY candidate.release_id, candidate.category, release.version
                ORDER BY release.version, candidate.category
                """,
                (selected_project_id,),
            ).fetchall()
            pairs: list[dict[str, Any]] = []
            for row in rows:
                chinese, english = self._single_language_pending_rows(
                    connection, int(row["release_id"]), str(row["category"])
                )
                for cn_row, en_row in pair_single_language_items(chinese, english):
                    pairs.append(
                        {
                            "release_id": int(row["release_id"]),
                            "version": row["version"],
                            "category": row["category"],
                            "cn_candidate_id": int(cn_row["id"]),
                            "en_candidate_id": int(en_row["id"]),
                            "cn_excerpt": excerpt(cn_row["title_cn"]),
                            "en_excerpt": excerpt(en_row["title_en"]),
                        }
                    )
            return pairs

    def merge_bilingual_candidates(
        self, cn_candidate_id: int, en_candidate_id: int
    ) -> dict[str, Any]:
        """人工确认「中英各一条其实是同一变更」后合并成一条，并重算该分类的疑似提醒。

        - 只接受仍在待审核、同版本同分类、且一侧只有中文另一侧只有英文的两条；
        - 合并保留两侧原文（title/raw 都留），因此**不会丢内容**；
        - 主行标记 `manually_edited`：重扫既不会把它拆回两条，也不会被规则覆盖；
        - 被并入的行置为 `rejected`，可在「已拒绝」里撤销恢复，所以这一步可回退；
        - 合并后按同一配对规则重算该分类的提醒，「疑似同一变更」不会残留已处理的对。
        """

        if int(cn_candidate_id) == int(en_candidate_id):
            raise ValueError("不能把一条记录与它自己合并")
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM import_candidates WHERE id IN (?, ?)",
                (cn_candidate_id, en_candidate_id),
            ).fetchall()
            by_id = {int(row["id"]): dict(row) for row in rows}
            if len(by_id) != 2:
                raise KeyError("candidate")
            chinese = by_id[int(cn_candidate_id)]
            english = by_id[int(en_candidate_id)]
            for label, row in (("中文", chinese), ("英文", english)):
                if row["status"] != "pending":
                    raise ValueError(f"{label}那条不在待审核状态，无法合并")
            if chinese["release_id"] != english["release_id"] or chinese["category"] != english["category"]:
                raise ValueError("只有同一版本、同一分类的中英两条才能合并")
            if not str(chinese["title_cn"]).strip() or str(chinese["title_en"]).strip():
                raise ValueError("第一条必须是一条只有中文的记录")
            if not str(english["title_en"]).strip() or str(english["title_cn"]).strip():
                raise ValueError("第二条必须是一条只有英文的记录")

            connection.execute(
                """
                UPDATE import_candidates
                SET title_en = ?, raw_en = ?, confidence = ?, manually_edited = 1
                WHERE id = ?
                """,
                (
                    english["title_en"],
                    english["raw_en"],
                    self.MERGED_PAIR_CONFIDENCE,
                    cn_candidate_id,
                ),
            )
            connection.execute(
                "UPDATE import_candidates SET status = 'rejected' WHERE id = ?",
                (en_candidate_id,),
            )
            remaining = self._refresh_cross_language_issues(
                connection, int(chinese["release_id"]), str(chinese["category"])
            )
            merged = connection.execute(
                "SELECT * FROM import_candidates WHERE id = ?", (cn_candidate_id,)
            ).fetchone()
            return {
                "candidate": dict(merged),
                "absorbed_candidate_id": int(en_candidate_id),
                "remaining_suspected_pairs": remaining,
            }

    def _refresh_cross_language_issues(
        self, connection: sqlite3.Connection, release_id: int, category: str
    ) -> int:
        """按当前待审核行重算该分类的「疑似同一变更」提醒，返回剩余组数。

        合并掉一组之后，旧的提醒必须消失：否则导入与审核页会一直挂着已经处理完的条目，
        用户看到「还有一组待确认」却找不到对应的两条记录。
        """

        connection.execute(
            """
            DELETE FROM review_issues
            WHERE release_id = ? AND status = 'open' AND message LIKE ?
            """,
            (release_id, f"{category} 分类疑似同一变更%"),
        )
        chinese, english = self._single_language_pending_rows(
            connection, release_id, category
        )
        pairs = pair_single_language_items(chinese, english)
        for cn_row, en_row in pairs:
            connection.execute(
                """
                INSERT INTO review_issues(issue_type, message, release_id, candidate_id)
                VALUES ('source_pair', ?, ?, ?)
                """,
                (
                    f"{category} 分类疑似同一变更（中英各一条，请确认是否合并为一条）："
                    f"{excerpt(cn_row['title_cn'])} ↔ {excerpt(en_row['title_en'])}",
                    release_id,
                    int(cn_row["id"]),
                ),
            )
        return len(pairs)

    def get_import_candidate(self, candidate_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM import_candidates WHERE id = ?", (candidate_id,)
            ).fetchone()
            if row is None:
                raise KeyError(candidate_id)
            return dict(row)

    def update_import_candidate(
        self,
        candidate_id: int,
        category: str,
        title_cn: str,
        title_en: str,
    ) -> dict[str, Any]:
        if category not in CHANGE_CATEGORIES:
            raise ValueError(f"Unsupported change category: {category}")
        with self.connect() as connection:
            candidate = connection.execute(
                "SELECT status FROM import_candidates WHERE id = ?", (candidate_id,)
            ).fetchone()
            if candidate is None:
                raise KeyError(candidate_id)
            if candidate["status"] != "pending":
                raise ValueError("Only pending candidates can be edited")
            connection.execute(
                """
                UPDATE import_candidates
                SET category = ?, title_cn = ?, title_en = ?, manually_edited = 1
                WHERE id = ?
                """,
                (category, title_cn.strip(), title_en.strip(), candidate_id),
            )
        return self.get_import_candidate(candidate_id)

    def set_import_candidate_status(self, candidate_id: int, status: str) -> None:
        if status not in {"pending", "approved", "rejected"}:
            raise ValueError(f"Unsupported candidate status: {status}")
        with self.connect() as connection:
            connection.execute(
                "UPDATE import_candidates SET status = ? WHERE id = ?",
                (status, candidate_id),
            )

    def approve_import_candidate(
        self,
        candidate_id: int,
        identity_key: str,
        feature_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Approve a candidate and optional feature promotion in one transaction."""
        with self.connect() as connection:
            candidate_row = connection.execute(
                "SELECT * FROM import_candidates WHERE id = ?", (candidate_id,)
            ).fetchone()
            if candidate_row is None:
                raise KeyError(candidate_id)
            candidate = dict(candidate_row)
            if candidate["status"] != "pending":
                return {"candidate_id": candidate_id, "status": candidate["status"]}
            if str(candidate["category"]) not in CHANGE_CATEGORIES:
                raise ValueError(
                    f"分类 {candidate['category']} 不在变更分类词表中，无法入版本。请先修订候选分类。"
                )
            release = connection.execute(
                "SELECT project_id FROM releases WHERE id = ?", (candidate["release_id"],)
            ).fetchone()
            if release is None:
                raise KeyError("release")
            project_id = int(release["project_id"])

            feature_id = candidate["proposed_feature_id"]
            if feature_data:
                if candidate["category"] != "function":
                    raise ValueError("Only function candidates can be promoted to the feature library")
                candidate_is_bilingual = bool(
                    candidate["title_cn"] and candidate["title_en"]
                )
                cn_name = str(feature_data.get("cn_name", "")).strip()
                en_name = str(feature_data.get("en_name", "")).strip()
                requested_category = str(feature_data.get("category", "")).strip()
                self._register_product_category(connection, requested_category)
                requested_feature_id = feature_data.get("feature_id")
                matched_term_id = None
                if not requested_feature_id and (cn_name or en_name):
                    cn_features = (
                        connection.execute(
                            """SELECT id, cn_name, en_name FROM features
                               WHERE project_id = ? AND cn_name = ? COLLATE NOCASE""",
                            (project_id, cn_name),
                        ).fetchall()
                        if cn_name
                        else []
                    )
                    en_features = (
                        connection.execute(
                            """SELECT id, cn_name, en_name FROM features
                               WHERE project_id = ? AND en_name = ? COLLATE NOCASE""",
                            (project_id, en_name),
                        ).fetchall()
                        if en_name
                        else []
                    )
                    existing_feature = None
                    if cn_features and en_features:
                        en_ids = {row["id"] for row in en_features}
                        shared = [row for row in cn_features if row["id"] in en_ids]
                        if len(shared) == 1:
                            existing_feature = shared[0]
                        else:
                            raise sqlite3.IntegrityError(
                                "Chinese and English names do not identify one feature"
                            )
                    else:
                        matched_features = cn_features or en_features
                        if len(matched_features) == 1:
                            existing_feature = matched_features[0]
                        elif len(matched_features) > 1:
                            raise sqlite3.IntegrityError(
                                "Feature name matches multiple existing features"
                            )
                    if cn_features and en_features and existing_feature is None:
                        raise sqlite3.IntegrityError(
                            "Chinese and English names refer to different features"
                        )
                    if existing_feature:
                        requested_feature_id = int(existing_feature["id"])
                        cn_name = existing_feature["cn_name"]
                        en_name = existing_feature["en_name"]
                if not requested_feature_id and (cn_name or en_name):
                    term_conditions = [
                        "en_name NOT IN ('', '—')",
                        "needs_review = 0",
                        "entry_type = 'term'",
                    ]
                    term_params: list[str] = []
                    if cn_name:
                        term_conditions.append("cn_name = ? COLLATE NOCASE")
                        term_params.append(cn_name)
                    if en_name:
                        term_conditions.append("en_name = ? COLLATE NOCASE")
                        term_params.append(en_name)
                    term = connection.execute(
                        f"""
                        SELECT id, cn_name, en_name, category FROM terms
                        WHERE {' AND '.join(term_conditions)}
                        ORDER BY parent_id IS NOT NULL, id LIMIT 1
                        """,
                        term_params,
                    ).fetchone()
                    if term:
                        matched_term_id = int(term["id"])
                        cn_name = term["cn_name"]
                        en_name = term["en_name"]
                        if not requested_category:
                            requested_category = term["category"]
                            self._register_product_category(
                                connection, requested_category
                            )
                if not requested_feature_id and (not cn_name or not en_name):
                    raise ValueError(
                        "Enter either an exact Chinese or English term, or choose a matched feature"
                    )
                if (
                    not candidate_is_bilingual
                    and not requested_feature_id
                    and matched_term_id is None
                ):
                    raise ValueError(
                        "Single-language changes must match a confirmed term or existing feature"
                    )
                if requested_feature_id:
                    feature_id = int(requested_feature_id)
                    if connection.execute(
                        "SELECT 1 FROM features WHERE id = ? AND project_id = ?",
                        (feature_id, project_id),
                    ).fetchone() is None:
                        raise KeyError(feature_id)
                    if candidate_is_bilingual:
                        description_cn, description_en = (
                            self._candidate_feature_description(candidate)
                        )
                        revision_number = int(
                            connection.execute(
                                "SELECT COALESCE(MAX(revision_number), 0) + 1 FROM feature_revisions WHERE feature_id = ?",
                                (feature_id,),
                            ).fetchone()[0]
                        )
                        connection.execute(
                            """
                            INSERT INTO feature_revisions(
                                feature_id, revision_number, cn_description,
                                en_description, review_status
                            ) VALUES (?, ?, ?, ?, 'approved')
                            """,
                            (
                                feature_id,
                                revision_number,
                                description_cn,
                                description_en,
                            ),
                        )
                        connection.execute(
                            """
                            UPDATE features
                            SET cn_description = ?, en_description = ?,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (
                                description_cn,
                                description_en,
                                feature_id,
                            ),
                        )
                    if requested_category:
                        connection.execute(
                            "UPDATE features SET category = ? WHERE id = ?",
                            (requested_category, feature_id),
                        )
                else:
                    description_cn, description_en = (
                        self._candidate_feature_description(candidate)
                        if candidate_is_bilingual
                        else ("", "")
                    )
                    feature_cursor = connection.execute(
                        """
                        INSERT INTO features(
                            project_id, term_id, cn_name, en_name, category,
                            cn_description, en_description
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            project_id,
                            matched_term_id,
                            cn_name,
                            en_name,
                            requested_category,
                            description_cn,
                            description_en,
                        ),
                    )
                    feature_id = int(feature_cursor.lastrowid)
                    connection.execute(
                        """
                        INSERT INTO feature_revisions(
                            feature_id, revision_number, cn_description, en_description,
                            review_status
                        ) VALUES (?, 1, ?, ?, 'approved')
                        """,
                        (
                            feature_id,
                            description_cn,
                            description_en,
                        ),
                    )
                markets = feature_data.get("markets", [])
                if not isinstance(markets, list) or any(
                    market not in {"domestic", "overseas"} for market in markets
                ):
                    raise ValueError("Markets must contain domestic and/or overseas")
                for market in markets:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO feature_market_releases(feature_id, release_id, market)
                        VALUES (?, ?, ?)
                        """,
                        (feature_id, candidate["release_id"], market),
                    )

            merged = None
            cursor = connection.execute(
                """
                INSERT INTO change_events(
                    release_id, category, canonical_key, title_cn, title_en,
                    description_cn, description_en, feature_id, review_status, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?)
                ON CONFLICT(release_id, category, canonical_key) DO NOTHING
                """,
                (
                    candidate["release_id"],
                    candidate["category"],
                    identity_key,
                    candidate["title_cn"],
                    candidate["title_en"],
                    candidate["raw_cn"],
                    candidate["raw_en"],
                    feature_id if candidate["category"] == "function" else None,
                    candidate["confidence"],
                ),
            )
            if cursor.rowcount == 0:
                # 单条确认同样可能撞上唯一索引（重复行、重扫后的同一条内容）。
                # 旧实现直接抛 IntegrityError，界面只看到一句“与现有数据冲突”；
                # 这里并入已有记录并如实返回 merged，保证单条与批量语义一致。
                merged = self._merge_change_event(
                    connection,
                    release_id=int(candidate["release_id"]),
                    category=str(candidate["category"]),
                    key=identity_key,
                    title_cn=candidate["title_cn"],
                    title_en=candidate["title_en"],
                    description_cn=candidate["raw_cn"],
                    description_en=candidate["raw_en"],
                    confidence=candidate["confidence"],
                    feature_id=feature_id if candidate["category"] == "function" else None,
                )
            connection.execute(
                "UPDATE import_candidates SET status = 'approved', proposed_feature_id = ? WHERE id = ?",
                (feature_id, candidate_id),
            )
            return {
                "candidate_id": candidate_id,
                "status": "approved",
                "feature_id": feature_id,
                "merged": merged is not None,
                "merged_into_change_event_id": (merged or {}).get("change_event_id"),
            }

    # ---- I06 问答闭环（迁移 012） ----

    @staticmethod
    def _qa_phrase(value: str) -> str:
        return re.sub(r"\s+", "", str(value or "").casefold())

    @staticmethod
    def _qa_evidence(connection: sqlite3.Connection, evidence_id: int) -> dict[str, Any] | None:
        row = connection.execute(
            """
            SELECT e.id, e.excerpt, e.page, e.sheet, e.cell_range,
                   v.id AS document_version_id, v.version_label, v.verified_at,
                   v.status AS version_status, d.title AS document_title,
                   d.status AS document_status, d.current_version_id
            FROM kh_evidence e
            JOIN kh_document_versions v ON v.id = e.document_version_id
            JOIN kh_documents d ON d.id = v.document_id
            WHERE e.id = ?
            """,
            (evidence_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _qa_metadata_current(evidence: dict[str, Any] | None) -> bool:
        return bool(
            evidence
            and evidence["document_version_id"] == evidence["current_version_id"]
            and evidence["document_status"] == "有效"
            and evidence["version_status"] == "有效"
            and evidence["verified_at"]
            and evidence["excerpt"].strip()
            and (evidence["page"] is not None or evidence["sheet"] or evidence["cell_range"])
        )

    def _qa_source_current(self, evidence: dict[str, Any] | None) -> bool:
        """One evidence gate for formal reads, publication, and notifications."""
        if not self._qa_metadata_current(evidence):
            return False
        with self.connect() as connection:
            version = connection.execute("SELECT * FROM kh_document_versions WHERE id = ?", (evidence["document_version_id"],)).fetchone()
        return bool(version and self.document_version_fingerprint_current(dict(version)))

    def configure_document_evidence_roots(self, *, allowed_roots=(), extraction_roots=()) -> None:
        """Bind an explicit file allowlist without scanning or exposing paths."""
        from tracker.services.document_evidence import DocumentEvidencePolicy

        roots = DocumentEvidencePolicy.normalized_roots(allowed_roots)
        extract_roots = DocumentEvidencePolicy.normalized_roots(extraction_roots)
        policy = getattr(self, "_document_evidence_policy", None)
        if policy is None or policy.roots != roots or policy.extraction_roots != extract_roots:
            self._document_evidence_policy = DocumentEvidencePolicy(allowed_roots=roots, extraction_roots=extract_roots)

    def document_version_fingerprint_current(self, version: dict[str, Any]) -> bool:
        """Legacy unhashed records retain their existing metadata policy."""
        if not str(version.get("sha256") or "").strip():
            return True
        policy = getattr(self, "_document_evidence_policy", None)
        return bool(policy and policy.version_is_current(self, version))

    def qa_evidence_is_current(self, evidence_id: int) -> bool:
        with self.connect() as connection:
            return self._qa_source_current(self._qa_evidence(connection, evidence_id))

    def create_qa_draft(
        self,
        *,
        standard_question: str,
        similar_questions: list[str],
        answer_text: str,
        market_code: str,
        country_code: str,
        model_name: str,
        registration_result: str,
        strategy_result: str,
        limitations: str,
        evidence_id: int,
    ) -> int:
        if not isinstance(similar_questions, list) or any(not isinstance(item, str) for item in similar_questions):
            raise ValueError("相似问法必须是文本列表。")
        if not isinstance(evidence_id, int) or isinstance(evidence_id, bool):
            raise ValueError("请选择引用证据。")
        values = [
            self._required_business_text(value, label)
            for value, label in (
                (standard_question, "标准问题"), (answer_text, "正式答案"),
                (market_code, "市场"), (country_code, "国家"), (model_name, "机型"),
                (registration_result, "注册检查结果"), (strategy_result, "产品策略结果"),
                (limitations, "限制条件"),
            )
        ]
        if values[2] != "domestic" or values[3] != "CN":
            raise ValueError("当前试点仅支持中国国内版问答。")
        phrases = {self._qa_phrase(text): str(text).strip() for text in [standard_question, *similar_questions] if str(text).strip()}
        if any(len(text) > 500 for text in phrases.values()):
            raise ValueError("问题不能超过 500 字。")
        with self.connect() as connection:
            if self._qa_evidence(connection, evidence_id) is None:
                raise ValueError("引用证据不存在。")
            cursor = connection.execute(
                """
                INSERT INTO kh_qa_answers(
                    standard_question, answer_text, market_code, country_code, model_name,
                    registration_result, strategy_result, limitations, evidence_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*values, evidence_id),
            )
            answer_id = int(cursor.lastrowid)
            connection.executemany(
                "INSERT INTO kh_qa_phrases(answer_id, phrase, normalized_phrase) VALUES (?, ?, ?)",
                [(answer_id, phrase, normalized) for normalized, phrase in phrases.items()],
            )
            return answer_id

    def submit_qa_for_review(self, answer_id: int) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE kh_qa_answers SET status = 'in_review' WHERE id = ? AND status = 'draft'",
                (answer_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("只有草稿可以提交审核。")

    def publish_qa_answer(self, answer_id: int, *, reviewer: str, verified_at: str, structured_signature: str | None = None) -> None:
        reviewer = self._required_business_text(reviewer, "审核人")
        verification_date = self._business_date(verified_at, "最后核验日期")
        with self.connect() as connection:
            answer = connection.execute("SELECT * FROM kh_qa_answers WHERE id = ?", (answer_id,)).fetchone()
            if answer is None or answer["status"] != "in_review":
                raise ValueError("只有待审核答案可以发布。")
            if not self._qa_source_current(self._qa_evidence(connection, answer["evidence_id"])):
                raise ValueError("引用必须是已复核、当前有效且可定位的受控资料。")
            # 同一问法与范围只能有一个正式答案；冲突时交给负责人处理，不任选一条。
            overlap = connection.execute(
                """
                SELECT old.id FROM kh_qa_answers old
                JOIN kh_qa_phrases old_phrase ON old_phrase.answer_id = old.id
                JOIN kh_qa_phrases new_phrase ON new_phrase.normalized_phrase = old_phrase.normalized_phrase
                WHERE new_phrase.answer_id = ? AND old.id != ? AND old.status = 'published'
                  AND old.market_code = ? AND old.country_code = ? AND old.model_name = ?
                LIMIT 1
                """,
                (answer_id, answer_id, answer["market_code"], answer["country_code"], answer["model_name"]),
            ).fetchone()
            if overlap:
                raise ValueError("同一问题与适用范围已有正式答案，请先复核并失效旧答案。")
            connection.execute(
                """
                UPDATE kh_qa_answers SET status = 'published', reviewed_by = ?,
                    reviewed_at = CURRENT_TIMESTAMP, verified_at = ?, published_at = CURRENT_TIMESTAMP,
                    structured_signature = ?
                WHERE id = ?
                """,
                (reviewer, verification_date, structured_signature, answer_id),
            )
            phrases = {
                row[0] for row in connection.execute(
                    "SELECT normalized_phrase FROM kh_qa_phrases WHERE answer_id = ?", (answer_id,)
                )
            }
            questions = connection.execute(
                """
                SELECT * FROM kh_qa_questions WHERE status = 'open'
                  AND market_code = ? AND country_code = ? AND model_name = ?
                """,
                (answer["market_code"], answer["country_code"], answer["model_name"]),
            ).fetchall()
            for question in questions:
                if self._qa_phrase(question["question"]) not in phrases:
                    continue
                connection.execute(
                    "UPDATE kh_qa_questions SET status = 'answered', answer_id = ?, answered_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (answer_id, question["id"]),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO kh_qa_notifications(question_id, answer_id, requester) VALUES (?, ?, ?)",
                    (question["id"], answer_id, question["requester"]),
                )

    def retire_qa_answer(self, answer_id: int, *, reason: str) -> None:
        explanation = self._required_business_text(reason, "失效原因")
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE kh_qa_answers SET status = 'retired', retirement_reason = ? WHERE id = ? AND status IN ('published', 'needs_review')",
                (explanation, answer_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("只有已发布或待复核答案可以失效。")
            connection.execute(
                "UPDATE kh_qa_questions SET status = 'open', answer_id = NULL, answered_at = NULL WHERE answer_id = ?",
                (answer_id,),
            )

    def mark_qa_for_structured_review(self, answer_id: int, expected_signature: str | None) -> bool:
        """Invalidate one answer atomically only if it still has the observed baseline."""
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE kh_qa_answers SET status = 'needs_review' WHERE id = ? AND status = 'published' AND structured_signature IS ?",
                (answer_id, expected_signature),
            )
            if cursor.rowcount:
                connection.execute(
                    "UPDATE kh_qa_questions SET status = 'open', answer_id = NULL, answered_at = NULL WHERE answer_id = ?",
                    (answer_id,),
                )
            return bool(cursor.rowcount)

    def list_qa_answers(self, status: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM kh_qa_answers WHERE (? IS NULL OR status = ?) ORDER BY id DESC",
                (status, status),
            ).fetchall()
            result = []
            for row in rows:
                answer = dict(row)
                answer["similar_questions"] = [
                    phrase[0] for phrase in connection.execute(
                        "SELECT phrase FROM kh_qa_phrases WHERE answer_id = ? AND phrase != ? ORDER BY phrase",
                        (row["id"], row["standard_question"]),
                    )
                ]
                answer["evidence"] = self._qa_evidence(connection, row["evidence_id"])
                result.append(answer)
            return result

    def get_qa_answer_scope(self, answer_id: int) -> dict[str, str]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT market_code, country_code, model_name FROM kh_qa_answers WHERE id = ?", (answer_id,)
            ).fetchone()
        if row is None:
            raise ValueError("答案不存在。")
        return dict(row)

    def list_current_qa_evidence(self, query: str = "") -> list[dict[str, Any]]:
        """只列可用于正式答案的受控证据，供负责人选择定位来源。"""
        needle = f"%{str(query or '').strip()}%"
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT e.id, e.excerpt, e.page, e.sheet, e.cell_range,
                       v.version_label, v.verified_at, d.title AS document_title
                FROM kh_evidence e
                JOIN kh_document_versions v ON v.id = e.document_version_id
                JOIN kh_documents d ON d.id = v.document_id
                WHERE d.current_version_id = v.id
                  AND d.status = '有效' AND v.status = '有效'
                  AND v.verified_at IS NOT NULL AND v.verified_at != ''
                  AND TRIM(e.excerpt) != ''
                  AND (e.page IS NOT NULL OR e.sheet IS NOT NULL OR e.cell_range IS NOT NULL)
                  AND (d.title LIKE ? OR e.excerpt LIKE ?)
                ORDER BY d.title, v.id DESC, e.id
                LIMIT 100
                """,
                (needle, needle),
            ).fetchall()
            return [dict(row) for row in rows]

    def search_published_qa(self, question: str, market: str, country: str, model: str) -> list[dict[str, Any]]:
        normalized = self._qa_phrase(question)
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT a.* FROM kh_qa_answers a
                JOIN kh_qa_phrases p ON p.answer_id = a.id
                WHERE p.normalized_phrase = ? AND a.status = 'published'
                  AND a.market_code = ? AND a.country_code = ? AND a.model_name = ?
                ORDER BY a.id DESC
                """,
                (normalized, market, country, model),
            ).fetchall()
            matches = []
            for row in rows:
                evidence = self._qa_evidence(connection, row["evidence_id"])
                if self._qa_source_current(evidence):
                    answer = dict(row)
                    answer["evidence"] = evidence
                    matches.append(answer)
            return matches

    def submit_qa_question(self, *, question: str, market_code: str, country_code: str, model_name: str, requester: str, reason_code: str = "unanswered", context_note: str = "") -> int:
        if reason_code not in {"unanswered", "material_gap"}:
            raise ValueError("未知的待处理原因。")
        values = [
            self._required_business_text(question, "问题"),
            str(market_code or "").strip(), str(country_code or "").strip().upper(),
            str(model_name or "").strip(), self._required_business_text(requester, "提问人"),
        ]
        if values[1] and values[1] not in {"domestic", "overseas"}:
            raise ValueError("未知市场。")
        if values[2] and not re.fullmatch(r"[A-Z]{2}", values[2]):
            raise ValueError("国家必须使用两位代码。")
        if reason_code != "material_gap" and not all(values[1:4]):
            raise ValueError("请先补充市场、国家和机型；材料未涉及的问题可先登记后补范围。")
        note = str(context_note or "").strip()
        if len(note) > 2000:
            raise ValueError("补充说明不能超过 2000 字。")
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO kh_qa_questions(question, market_code, country_code, model_name, requester, reason_code, context_note)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (*values, reason_code, note),
            )
            return int(cursor.lastrowid)

    def list_qa_questions(self, status: str | None = None, requester: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM kh_qa_questions
                   WHERE (? IS NULL OR status = ?) AND (? IS NULL OR requester = ?)
                   ORDER BY id DESC""", (status, status, requester, requester)
            ).fetchall()
            return [dict(row) for row in rows]

    def list_qa_notifications(self, requester: str, signature_for_answer: Callable[[str, str], str] | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT n.*, a.status AS answer_status, a.answer_text, a.evidence_id,
                          a.country_code, a.model_name, a.structured_signature
                   FROM kh_qa_notifications n JOIN kh_qa_answers a ON a.id = n.answer_id
                   WHERE n.requester = ? ORDER BY n.id DESC""", (requester,)
            ).fetchall()
            notifications = []
            for row in rows:
                item = dict(row)
                evidence = self._qa_evidence(connection, item.pop("evidence_id"))
                current = item.pop("answer_status") == "published" and self._qa_source_current(evidence)
                if current and signature_for_answer is not None:
                    current = item.pop("structured_signature") == signature_for_answer(item["country_code"], item["model_name"])
                else:
                    item.pop("structured_signature")
                item["answer_state"] = "current" if current else "withdrawn"
                if not current:
                    item["answer_text"] = None
                notifications.append(item)
            return notifications

    def add_qa_feedback(self, question_id: int, *, helpful: bool, detail: str = "") -> int:
        with self.connect() as connection:
            question = connection.execute("SELECT status, answer_id FROM kh_qa_questions WHERE id = ?", (question_id,)).fetchone()
            answer = connection.execute("SELECT status, evidence_id FROM kh_qa_answers WHERE id = ?", (question["answer_id"],)).fetchone() if question and question["answer_id"] else None
            if not question or question["status"] != "answered" or not answer or answer["status"] != "published" or not self._qa_source_current(self._qa_evidence(connection, answer["evidence_id"])):
                raise ValueError("只能对当前有效的正式答案提交反馈。")
            cursor = connection.execute(
                "INSERT INTO kh_qa_feedback(question_id, helpful, detail) VALUES (?, ?, ?)",
                (question_id, int(helpful), str(detail or "").strip()),
            )
            return int(cursor.lastrowid)

    def list_qa_feedback(self, question_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM kh_qa_feedback WHERE question_id = ? ORDER BY id", (question_id,)
            ).fetchall()
            return [dict(row) for row in rows]

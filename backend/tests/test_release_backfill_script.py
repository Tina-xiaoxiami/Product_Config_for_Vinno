"""Contract tests for the Release Note backfill script.

The script is the sanctioned way to write release rows in bulk, so the two
guarantees that matter are pinned here: it is a dry-run by default, and when it
does write, it writes pending candidates rather than confirmed conclusions.
"""

import sqlite3
import sys
from pathlib import Path

from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from app.database import Base  # noqa: E402
import app.models  # noqa: F401 - registers every model on Base.metadata
from backfill_feature_versions import main  # noqa: E402


def _create_database(path):
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()

    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        INSERT INTO feature_groups (id, name, sort_order) VALUES (1, '成像技术', 1);
        INSERT INTO features (
            id, group_id, name, ipn, sort_order, config_item_id,
            primary_cn_name, primary_en_name, identity_status
        ) VALUES (1, 1, 'TView', '6000017', 1, NULL, '梯形成像', 'TView', 'confirmed');
        INSERT INTO config_items (id, row_index, ipn, rd_name, v_code, zh_desc, en_desc)
        VALUES (1, 1, '6000017', 'TView', 'V30001', '梯形成像', 'TView');
        INSERT INTO feature_config_item_links (
            feature_id, config_item_id, relation_type, source, review_status
        ) VALUES (1, 1, 'primary', 'test', 'approved');
        INSERT INTO knowledge_documents (
            id, document_type, title, file_name, file_path, version, market,
            product_series, source_status
        ) VALUES (100, 'release_note', 'V10系列Release Note_1.14.40', 'a.pdf',
                  '/tmp/a.pdf', '1.14.40', 'domestic', 'V10', 'active');
        INSERT INTO knowledge_document_extractions (
            document_id, extractor_version, status, chunk_count
        ) VALUES (100, '2', 'completed', 1);
        INSERT INTO knowledge_document_chunks (
            document_id, chunk_index, page_number, source_ref, content,
            normalized_content, content_hash
        ) VALUES (100, 0, 3, '第3页',
                  '1
1. 概述
此次更新新增心脏教学。
2. 配置变更
探头/功能 V 代码 配置
梯形成像 V30001 新增,V10 系列选配支持。', '', 'h1');
        """
    )
    connection.commit()
    connection.close()


def _rows(path, sql):
    connection = sqlite3.connect(path)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def test_backfill_script_is_a_dry_run_until_apply_is_given(tmp_path, capsys):
    database_path = tmp_path / "copy.db"
    _create_database(database_path)

    assert main(["--database", str(database_path)]) == 0
    output = capsys.readouterr().out
    assert "dry-run：未写入任何数据" in output
    assert "首发候选" in output
    assert "已纳管 Release Note 最早版本为 1.14.40" in output
    assert _rows(database_path, "SELECT COUNT(*) FROM feature_versions") == [(0,)]

    assert main(["--database", str(database_path), "--apply"]) == 0
    applied_output = capsys.readouterr().out
    assert "已写入 1 条待复核候选" in applied_output
    assert _rows(
        database_path,
        "SELECT review_status, source, change_type, evidence_kind, software_version"
        " FROM feature_versions",
    ) == [("pending", "release_note", "added", "configuration_change", "1.14.40")]

    # 幂等：再跑一次不会重复写入。
    assert main(["--database", str(database_path), "--apply"]) == 0
    assert "已写入 0 条待复核候选" in capsys.readouterr().out
    assert _rows(database_path, "SELECT COUNT(*) FROM feature_versions") == [(1,)]


def test_backfill_script_reports_a_missing_database(tmp_path, capsys):
    missing = tmp_path / "nope.db"
    assert main(["--database", str(missing)]) == 2
    assert "数据库不存在" in capsys.readouterr().out


def test_coverage_report_tells_which_features_still_lack_a_first_release(tmp_path, capsys):
    database_path = tmp_path / "copy.db"
    _create_database(database_path)

    assert main(["--database", str(database_path), "--coverage"]) == 0
    empty_output = capsys.readouterr().out
    assert "覆盖：功能 1 个 | 有首发证据 0 | 仅其他证据 0 | 无任何候选 1" in empty_output
    assert "[无任何候选] #1 梯形成像 | 候选 0 条" in empty_output
    assert "多为尚未发布的功能" in empty_output

    assert main(["--database", str(database_path), "--apply"]) == 0
    capsys.readouterr()
    assert main(["--database", str(database_path), "--coverage"]) == 0
    output = capsys.readouterr().out
    assert "覆盖：功能 1 个 | 有首发证据 1 | 仅其他证据 0 | 无任何候选 0" in output
    assert "[有首发证据] #1 梯形成像 | 候选 1 条 | 首发证据 1.14.40" in output

"""Contract tests for the feature-release data model.

These tests pin the schema before the implementation exists: the release
capability must keep a feature's software version, its release date, the
evidence it came from, and its review state as first-class columns, so
"which release introduced this feature" stays answerable from the database
instead of being re-derived from PDF text every time.
"""

from sqlalchemy import create_engine, inspect

from app.database import Base
import app.models  # noqa: F401 - registers every model on Base.metadata
from app.models.release import (
    FEATURE_VERSION_CHANGE_TYPES,
    FEATURE_VERSION_EVIDENCE_KINDS,
    FEATURE_VERSION_LIFECYCLE_STATUSES,
    FEATURE_VERSION_REVIEW_STATUSES,
    RELEASE_INTRODUCTION_REVIEW_STATUSES,
)
from app.services.feature_release_versions import version_sort_key


def test_clean_database_schema_contains_feature_release_tables():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    assert {
        "feature_versions",
        "release_introductions",
        "release_introduction_revisions",
        "release_introduction_attachments",
    } <= set(inspector.get_table_names())

    version_columns = {column["name"] for column in inspector.get_columns("feature_versions")}
    assert {
        "feature_id",
        "software_version",
        "version_sort_key",
        "product_series",
        "market",
        "release_date",
        "change_type",
        "configuration_status",
        "lifecycle_status",
        "evidence_document_id",
        "evidence_source_ref",
        "evidence_excerpt",
        "source",
        "review_status",
        "change_note",
        "created_at",
        "updated_at",
    } <= version_columns

    introduction_columns = {
        column["name"] for column in inspector.get_columns("release_introductions")
    }
    assert {
        "feature_version_id",
        "summary",
        "clinical_significance",
        "workflow",
        "applications_json",
        "version",
        "review_status",
        "change_note",
        "created_at",
        "updated_at",
    } <= introduction_columns

    revision_columns = {
        column["name"] for column in inspector.get_columns("release_introduction_revisions")
    }
    assert {
        "introduction_id",
        "version",
        "summary",
        "clinical_significance",
        "workflow",
        "applications_json",
        "review_status",
        "change_note",
    } <= revision_columns

    attachment_columns = {
        column["name"] for column in inspector.get_columns("release_introduction_attachments")
    }
    assert {
        "introduction_id",
        "file_name",
        "file_path",
        "sha256",
        "mime_type",
        "file_size",
        "sort_order",
    } <= attachment_columns
    engine.dispose()


def test_feature_versions_keep_one_row_per_feature_version_scope():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    unique_column_sets = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("feature_versions")
    }
    assert (
        "feature_id",
        "software_version",
        "product_series",
        "market",
    ) in unique_column_sets

    # One introduction per feature version, and one revision per introduction version.
    introduction_unique = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("release_introductions")
    }
    assert ("feature_version_id",) in introduction_unique

    revision_unique = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("release_introduction_revisions")
    }
    assert ("introduction_id", "version") in revision_unique
    engine.dispose()


def test_release_rows_cascade_from_the_feature_and_the_feature_version():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    def ondelete(table, column):
        for foreign_key in inspector.get_foreign_keys(table):
            if foreign_key["constrained_columns"] == [column]:
                return foreign_key["options"].get("ondelete")
        return None

    assert ondelete("feature_versions", "feature_id") == "CASCADE"
    assert ondelete("release_introductions", "feature_version_id") == "CASCADE"
    assert ondelete("release_introduction_revisions", "introduction_id") == "CASCADE"
    assert ondelete("release_introduction_attachments", "introduction_id") == "CASCADE"
    # Evidence survives as a plain reference: archiving a document must not
    # silently delete the release row that cites it.
    assert ondelete("feature_versions", "evidence_document_id") in (None, "SET NULL")
    engine.dispose()


def test_version_sort_key_orders_software_versions_numerically():
    ordered = ["1.4.80", "1.14.20", "1.14.40", "1.14.80", "1.14.100", "1.51.30", "4.14.14.12"]
    keys = [version_sort_key(version) for version in ordered]
    assert keys == sorted(keys)
    assert version_sort_key("1.14.80") == version_sort_key("1.14.80 ")
    assert version_sort_key("1.4.80") < version_sort_key("1.14.20")


def test_version_sort_key_keeps_unparseable_versions_after_numeric_ones():
    numeric = version_sort_key("1.14.80")
    assert version_sort_key("R10") > numeric
    assert version_sort_key("") > numeric
    assert version_sort_key("") == version_sort_key("   ")


def test_release_vocabularies_keep_the_ported_and_evidence_vocabularies():
    """A side kept these as data; here they are code, so pin them."""

    # 生命周期沿用 A 侧 6 态（含中文名对应关系见 models/release.py 注释）。
    assert FEATURE_VERSION_LIFECYCLE_STATUSES == (
        "undefined",
        "developing",
        "pending",
        "released",
        "offline",
        "deprecated",
    )
    assert FEATURE_VERSION_REVIEW_STATUSES == ("pending", "confirmed", "rejected")
    assert RELEASE_INTRODUCTION_REVIEW_STATUSES == ("draft", "published")
    # 「配置变更表」证据与「正文叙述」证据必须可区分，否则会把优化写进首发版本。
    assert "configuration_change" in FEATURE_VERSION_EVIDENCE_KINDS
    assert "narrative" in FEATURE_VERSION_EVIDENCE_KINDS
    # 未定义的变更类型只用于兜底，不能用来判定「新增」。
    assert "added" in FEATURE_VERSION_CHANGE_TYPES
    assert "unknown" in FEATURE_VERSION_CHANGE_TYPES

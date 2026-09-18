"""功能发布：功能版本、发布日期与发布介绍。

设计依据（合并方案 C / 交接文档阶段 2）：

- 功能版本是「某个功能在某个软件版本里的变化」的一等实体，首发版本由它派生，
  不再每次从 Release Note 正文重新推导。
- `release_date` 与证据字段（来源资料、页码、原文摘录）随行保存：
  Release Note 只能证明「功能进入某版本」，日期与发布状态仍需可追溯来源。
- 候选行以 `review_status='pending'` 落库，人工确认后才成为正式结论，
  与知识库既有「候选内容不能直接作为正式结论」的约定一致。
- 发布介绍按 A 侧（feature-release-system）的既有口径拆成
  功能概述 / 临床意义 / 工作流程 / 适用范围四个字段，附件单独建表，
  不再像 A 那样把附件塞进正文 JSON。
"""

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)

from app.database import Base


# 变更类型：与 Release Note「配置变更」表的口径对齐。
FEATURE_VERSION_CHANGE_TYPES = (
    "added",  # 新增 / 上架
    "optimized",  # 优化
    "fixed",  # 修复
    "removed",  # 下架 / 移除
    "status_changed",  # 选配、标配、招标支持、未注册等状态变化
    "unknown",  # 原文无法判定
)

FEATURE_VERSION_REVIEW_STATUSES = ("pending", "confirmed", "rejected")

# 证据类型：配置变更表证明「功能进入该版本」，正文叙述只证明「该版本涉及该功能」。
FEATURE_VERSION_EVIDENCE_KINDS = ("configuration_change", "narrative", "manual")

# 生命周期：沿用 A 侧的 6 态口径，代码内收敛，不再放进可改的配置表。
FEATURE_VERSION_LIFECYCLE_STATUSES = (
    "undefined",  # 未定义
    "developing",  # 开发中
    "pending",  # 待确认
    "released",  # 已发布
    "offline",  # 已下线
    "deprecated",  # 已废弃
)

RELEASE_INTRODUCTION_REVIEW_STATUSES = ("draft", "published")


class FeatureVersion(Base):
    """一个功能在一个软件版本、一个产品系列范围里的变化记录。"""

    __tablename__ = "feature_versions"

    id = Column(Integer, primary_key=True)
    feature_id = Column(Integer, ForeignKey("features.id", ondelete="CASCADE"), nullable=False)
    software_version = Column(String(50), nullable=False)
    # 版本比较用的规范化键：SQL 里直接 ORDER BY / MIN 即可得到最早版本。
    version_sort_key = Column(String(80), nullable=False)
    product_series = Column(String(100), nullable=False, default="")
    market = Column(String(30), nullable=False, default="domestic")
    release_date = Column(String(20), nullable=True)
    change_type = Column(String(30), nullable=False, default="unknown")
    # Release Note 原文的配置口径（选配 / 标配 / 招标支持 / 未注册 等），保留原文措辞。
    configuration_status = Column(Text, nullable=True)
    lifecycle_status = Column(String(20), nullable=False, default="undefined")
    evidence_document_id = Column(
        Integer,
        ForeignKey("knowledge_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    evidence_source_ref = Column(Text, nullable=True)
    evidence_excerpt = Column(Text, nullable=True)
    evidence_kind = Column(String(30), nullable=False, default="manual")
    matched_by = Column(String(30), nullable=True)
    source = Column(String(30), nullable=False, default="manual")
    review_status = Column(String(20), nullable=False, default="pending")
    change_note = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        UniqueConstraint(
            "feature_id",
            "software_version",
            "product_series",
            "market",
            name="uq_feature_version_scope",
        ),
        Index("ix_feature_versions_feature", "feature_id"),
        Index("ix_feature_versions_version", "software_version"),
        Index("ix_feature_versions_sort", "version_sort_key"),
        Index("ix_feature_versions_review", "review_status"),
    )


class ReleaseIntroduction(Base):
    """一个功能版本的发布介绍（面向客户的介绍内容）。"""

    __tablename__ = "release_introductions"

    id = Column(Integer, primary_key=True)
    feature_version_id = Column(
        Integer,
        ForeignKey("feature_versions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    summary = Column(Text, nullable=True)
    clinical_significance = Column(Text, nullable=True)
    workflow = Column(Text, nullable=True)
    # 适用范围按行保存，读回时是字符串列表。
    applications_json = Column(Text, nullable=False, server_default=text("'[]'"))
    version = Column(Integer, nullable=False, default=1)
    review_status = Column(String(20), nullable=False, default="draft")
    change_note = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class ReleaseIntroductionRevision(Base):
    """发布介绍每次保存前的不可变快照。"""

    __tablename__ = "release_introduction_revisions"

    id = Column(Integer, primary_key=True)
    introduction_id = Column(
        Integer,
        ForeignKey("release_introductions.id", ondelete="CASCADE"),
        nullable=False,
    )
    version = Column(Integer, nullable=False)
    summary = Column(Text, nullable=True)
    clinical_significance = Column(Text, nullable=True)
    workflow = Column(Text, nullable=True)
    applications_json = Column(Text, nullable=False, server_default=text("'[]'"))
    review_status = Column(String(20), nullable=False)
    change_note = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        UniqueConstraint(
            "introduction_id",
            "version",
            name="uq_release_introduction_revision",
        ),
        Index("ix_release_introduction_revisions_intro", "introduction_id"),
    )


class ReleaseIntroductionAttachment(Base):
    """发布介绍的附件（自有产物，不进入受控原始材料库）。"""

    __tablename__ = "release_introduction_attachments"

    id = Column(Integer, primary_key=True)
    introduction_id = Column(
        Integer,
        ForeignKey("release_introductions.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_name = Column(Text, nullable=False)
    file_path = Column(Text, nullable=False, unique=True)
    sha256 = Column(String(64), nullable=True)
    mime_type = Column(String(200), nullable=True)
    file_size = Column(Integer, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("ix_release_introduction_attachments_intro", "introduction_id"),
    )

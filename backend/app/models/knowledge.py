"""产品知识库与统一功能身份模型。"""

from sqlalchemy import Column, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text

from app.database import Base


class FeatureName(Base):
    """功能的中英文主名和备用名。"""

    __tablename__ = "feature_names"

    id = Column(Integer, primary_key=True)
    feature_id = Column(Integer, ForeignKey("features.id", ondelete="CASCADE"), nullable=False)
    language = Column(String(10), nullable=False)
    name = Column(Text, nullable=False)
    normalized_name = Column(Text, nullable=False)
    name_type = Column(String(20), nullable=False)
    source = Column(Text, nullable=False)
    review_status = Column(String(20), nullable=False, default="approved")

    __table_args__ = (
        UniqueConstraint(
            "feature_id",
            "language",
            "normalized_name",
            name="uq_feature_name_identity",
        ),
    )


class FeatureRelation(Base):
    """功能之间的业务关系。"""

    __tablename__ = "feature_relations"

    id = Column(Integer, primary_key=True)
    source_feature_id = Column(
        Integer,
        ForeignKey("features.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_feature_id = Column(
        Integer,
        ForeignKey("features.id", ondelete="CASCADE"),
        nullable=False,
    )
    relation_type = Column(String(30), nullable=False)
    source_reference = Column(Text, nullable=True)
    review_status = Column(String(20), nullable=False, default="pending")

    __table_args__ = (
        UniqueConstraint(
            "source_feature_id",
            "target_feature_id",
            "relation_type",
            name="uq_feature_relation",
        ),
    )


class FeatureConfigItemLink(Base):
    """功能与主IPN、关联IPN或版本IPN的关系。"""

    __tablename__ = "feature_config_item_links"

    id = Column(Integer, primary_key=True)
    feature_id = Column(Integer, ForeignKey("features.id", ondelete="CASCADE"), nullable=False)
    config_item_id = Column(
        Integer,
        ForeignKey("config_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    relation_type = Column(String(30), nullable=False)
    source = Column(Text, nullable=False)
    review_status = Column(String(20), nullable=False, default="approved")

    __table_args__ = (
        UniqueConstraint(
            "feature_id",
            "config_item_id",
            "relation_type",
            name="uq_feature_config_item_link",
        ),
    )


class KnowledgeDocument(Base):
    """可预览原始资料的受控索引。"""

    __tablename__ = "knowledge_documents"

    id = Column(Integer, primary_key=True)
    document_type = Column(String(50), nullable=False)
    title = Column(Text, nullable=False)
    file_name = Column(Text, nullable=False)
    file_path = Column(Text, nullable=False, unique=True)
    version = Column(String(100), nullable=True)
    market = Column(String(30), nullable=False, default="domestic")
    country = Column(String(100), nullable=True)
    product_series = Column(String(100), nullable=True)
    mime_type = Column(String(200), nullable=True)
    sha256 = Column(String(64), nullable=True)
    source_status = Column(String(30), nullable=False, default="active")
    created_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("ix_knowledge_documents_type", "document_type"),
        Index("ix_knowledge_documents_market", "market"),
    )

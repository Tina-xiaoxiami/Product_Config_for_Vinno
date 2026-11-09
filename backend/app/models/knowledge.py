"""产品知识库与统一功能身份模型。"""

from sqlalchemy import Column, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, text

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


class KnowledgeQuestion(Base):
    """A downstream question, pending or backed by a confirmed answer."""

    __tablename__ = "knowledge_questions"

    id = Column(Integer, primary_key=True)
    question_text = Column(Text, nullable=False)
    normalized_question = Column(Text, nullable=False)
    scope_key = Column(Text, nullable=False, default="", server_default="")
    status = Column(String(20), nullable=False, default="pending")
    asked_count = Column(Integer, nullable=False, default=1)
    last_asked_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    created_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        UniqueConstraint("scope_key", "normalized_question", name="uq_knowledge_question_scope"),
        UniqueConstraint("id", "scope_key", name="uq_knowledge_question_id_scope"),
        Index("ix_knowledge_questions_status", "status"),
        Index("ix_knowledge_questions_last_asked", "last_asked_at"),
        {"sqlite_autoincrement": True},
    )


class KnowledgeQuestionPhrasing(Base):
    """A confirmed alias or observed wording for a canonical question."""

    __tablename__ = "knowledge_question_phrasings"

    id = Column(Integer, primary_key=True)
    question_id = Column(Integer, nullable=False)
    scope_key = Column(Text, nullable=False, default="", server_default="")
    phrasing_text = Column(Text, nullable=False)
    normalized_phrasing = Column(Text, nullable=False)
    phrasing_type = Column(String(20), nullable=False, default="alias")
    created_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        ForeignKeyConstraint(["question_id", "scope_key"], ["knowledge_questions.id", "knowledge_questions.scope_key"], ondelete="CASCADE"),
        UniqueConstraint("scope_key", "normalized_phrasing", name="uq_knowledge_phrasing_scope"),
        Index("ix_knowledge_question_phrasings_question", "question_id"),
    )


class KnowledgeAnswer(Base):
    """The current confirmed answer for one canonical question."""

    __tablename__ = "knowledge_answers"

    id = Column(Integer, primary_key=True)
    question_id = Column(
        Integer,
        ForeignKey("knowledge_questions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    answer_text = Column(Text, nullable=False)
    review_status = Column(String(20), nullable=False, default="published")
    version = Column(Integer, nullable=False, default=1)
    change_note = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class KnowledgeAnswerCitation(Base):
    """A controlled source reference supporting a confirmed answer."""

    __tablename__ = "knowledge_answer_citations"

    id = Column(Integer, primary_key=True)
    answer_id = Column(
        Integer,
        ForeignKey("knowledge_answers.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id = Column(Integer, ForeignKey("knowledge_documents.id"), nullable=False)
    source_ref = Column(Text, nullable=True)
    excerpt = Column(Text, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)

    __table_args__ = (Index("ix_knowledge_answer_citations_answer", "answer_id"),)


class KnowledgeAnswerRevision(Base):
    """Immutable snapshots of every published answer version."""

    __tablename__ = "knowledge_answer_revisions"

    id = Column(Integer, primary_key=True)
    answer_id = Column(
        Integer,
        ForeignKey("knowledge_answers.id", ondelete="CASCADE"),
        nullable=False,
    )
    version = Column(Integer, nullable=False)
    answer_text = Column(Text, nullable=False)
    review_status = Column(String(20), nullable=False)
    change_note = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        UniqueConstraint("answer_id", "version", name="uq_knowledge_answer_revision"),
        Index("ix_knowledge_answer_revisions_answer", "answer_id"),
    )


class KnowledgeAnswerReview(Base):
    """Append-only owner decisions about one exact answer/evidence revision."""

    __tablename__ = "knowledge_answer_reviews"
    id = Column(Integer, primary_key=True)
    answer_id = Column(Integer, ForeignKey("knowledge_answers.id", ondelete="CASCADE"), nullable=False)
    answer_version = Column(Integer, nullable=False)
    source_fingerprint = Column(String(64), nullable=False)
    review_revision = Column(Integer, nullable=False)
    action = Column(String(30), nullable=False)
    country = Column(String(10))
    market = Column(String(20))
    model_ids_json = Column(Text, nullable=False, server_default="[]")
    software_version = Column(String(80))
    version_applicability = Column(String(30), nullable=False)
    evidence_reference = Column(Text, nullable=False, server_default="")
    note = Column(Text, nullable=False, server_default="")
    confirmed_by = Column(Text, nullable=False)
    target_question_ids_json = Column(Text, nullable=False, server_default="[]")
    request_fingerprint = Column(String(64), nullable=False)
    reviewed_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    __table_args__ = (
        UniqueConstraint("answer_id", "review_revision", name="uq_knowledge_answer_review_revision"),
        Index("ix_knowledge_answer_reviews_answer", "answer_id"),
    )


class KnowledgeDocumentExtraction(Base):
    """Extraction status for one controlled source document."""

    __tablename__ = "knowledge_document_extractions"

    document_id = Column(
        Integer,
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    extractor_version = Column(String(50), nullable=False)
    source_sha256 = Column(String(64), nullable=True)
    status = Column(String(20), nullable=False)
    chunk_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    extracted_at = Column(Text, nullable=True)
    updated_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class KnowledgeDocumentChunk(Base):
    """A source-located excerpt available for candidate evidence search."""

    __tablename__ = "knowledge_document_chunks"

    id = Column(Integer, primary_key=True)
    document_id = Column(
        Integer,
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index = Column(Integer, nullable=False)
    page_number = Column(Integer, nullable=True)
    section_name = Column(Text, nullable=True)
    source_ref = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    normalized_content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    created_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_document_chunk"),
        Index("ix_knowledge_document_chunks_document", "document_id"),
        Index("ix_knowledge_document_chunks_hash", "content_hash"),
    )


class DataReviewItem(Base):
    """One source-located extraction row with immutable raw and editable values."""

    __tablename__ = "data_review_items"

    id = Column(Integer, primary_key=True)
    document_id = Column(
        Integer,
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    data_type = Column(String(80), nullable=False)
    batch_id = Column(Integer, nullable=False)
    source_record_key = Column(Text, nullable=False)
    source_ref = Column(Text, nullable=False)
    raw_payload_json = Column(Text, nullable=False)
    effective_payload_json = Column(Text, nullable=False)
    issue_codes_json = Column(Text, nullable=False, server_default=text("'[]'"))
    review_status = Column(String(30), nullable=False, server_default=text("'auto_ready'"))
    updated_by = Column(Text, nullable=True)
    change_note = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        UniqueConstraint(
            "data_type",
            "batch_id",
            "source_record_key",
            name="uq_data_review_source_record",
        ),
        Index("ix_data_review_batch", "data_type", "batch_id"),
        Index("ix_data_review_status", "review_status"),
        Index("ix_data_review_document", "document_id"),
    )


class DataReviewRevision(Base):
    """Append-only history for corrections made to one extraction row."""

    __tablename__ = "data_review_revisions"

    id = Column(Integer, primary_key=True)
    review_item_id = Column(
        Integer,
        ForeignKey("data_review_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision_no = Column(Integer, nullable=False)
    before_payload_json = Column(Text, nullable=False)
    after_payload_json = Column(Text, nullable=False)
    action = Column(String(30), nullable=False)
    change_note = Column(Text, nullable=True)
    changed_by = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        UniqueConstraint(
            "review_item_id",
            "revision_no",
            name="uq_data_review_revision",
        ),
        Index("ix_data_review_revisions_item", "review_item_id"),
    )


class KnowledgeConfigurationAnswerRevision(Base):
    """Immutable result of an explicitly resolved configuration-dependent question."""

    __tablename__ = "knowledge_configuration_answer_revisions"

    id = Column(Integer, primary_key=True)
    recipe = Column(String(100), nullable=False)
    model_id = Column(Integer, nullable=False)
    config_version_id = Column(Integer, nullable=True)
    payload_json = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (Index("ix_knowledge_configuration_answer_lookup", "recipe", "model_id", "id"),)

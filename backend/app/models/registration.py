"""国家-型号-探头注册主数据模型。"""

from sqlalchemy import Column, ForeignKey, Index, Integer, Text, UniqueConstraint, text

from app.database import Base


class RegistrationImportBatch(Base):
    __tablename__ = "registration_import_batches"

    id = Column(Integer, primary_key=True)
    country_code = Column(Text, nullable=False)
    source_document_id = Column(Integer, ForeignKey("knowledge_documents.id"))
    source_version = Column(Text)
    source_sha256 = Column(Text)
    snapshot_hash = Column(Text, nullable=False)
    snapshot_json = Column(Text, nullable=False)
    model_count = Column(Integer, nullable=False)
    probe_count = Column(Integer, nullable=False)
    matrix_count = Column(Integer, nullable=False)
    status = Column(Text, nullable=False, default="active")
    imported_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        UniqueConstraint(
            "country_code",
            "snapshot_hash",
            name="uq_registration_import_snapshot",
        ),
    )


class RegistrationModel(Base):
    __tablename__ = "registration_models"

    id = Column(Integer, primary_key=True)
    country_code = Column(Text, nullable=False)
    model_name = Column(Text, nullable=False)
    normalized_name = Column(Text, nullable=False)
    channel_count = Column(Integer)
    import_batch_id = Column(
        Integer,
        ForeignKey("registration_import_batches.id"),
        nullable=False,
    )
    source_document_id = Column(Integer, ForeignKey("knowledge_documents.id"))
    source_ref = Column(Text)
    source_status = Column(Text, nullable=False, default="active")

    __table_args__ = (
        UniqueConstraint(
            "country_code",
            "normalized_name",
            name="uq_registration_model_country_name",
        ),
        Index("ix_registration_models_country", "country_code", "source_status"),
    )


class RegistrationProbe(Base):
    __tablename__ = "registration_probes"

    id = Column(Integer, primary_key=True)
    country_code = Column(Text, nullable=False)
    probe_model = Column(Text, nullable=False)
    normalized_model = Column(Text, nullable=False)
    ipn = Column(Text, nullable=False)
    import_batch_id = Column(
        Integer,
        ForeignKey("registration_import_batches.id"),
        nullable=False,
    )
    source_document_id = Column(Integer, ForeignKey("knowledge_documents.id"))
    source_ref = Column(Text)
    source_status = Column(Text, nullable=False, default="active")

    __table_args__ = (
        UniqueConstraint(
            "country_code",
            "normalized_model",
            name="uq_registration_probe_country_model",
        ),
        UniqueConstraint(
            "country_code",
            "ipn",
            name="uq_registration_probe_country_ipn",
        ),
        Index("ix_registration_probes_country", "country_code", "source_status"),
    )


class RegistrationModelProbe(Base):
    __tablename__ = "registration_model_probes"

    id = Column(Integer, primary_key=True)
    country_code = Column(Text, nullable=False)
    registration_model_id = Column(
        Integer,
        ForeignKey("registration_models.id", ondelete="CASCADE"),
        nullable=False,
    )
    registration_probe_id = Column(
        Integer,
        ForeignKey("registration_probes.id", ondelete="CASCADE"),
        nullable=False,
    )
    registration_status = Column(Text, nullable=False)
    import_batch_id = Column(
        Integer,
        ForeignKey("registration_import_batches.id"),
        nullable=False,
    )
    source_document_id = Column(Integer, ForeignKey("knowledge_documents.id"))
    source_ref = Column(Text)

    __table_args__ = (
        UniqueConstraint(
            "registration_model_id",
            "registration_probe_id",
            name="uq_registration_model_probe",
        ),
        Index(
            "ix_registration_matrix_status",
            "country_code",
            "registration_status",
        ),
    )


class ProductRegistrationModelLink(Base):
    __tablename__ = "product_registration_model_links"

    id = Column(Integer, primary_key=True)
    product_model_id = Column(
        Integer,
        ForeignKey("product_models.id", ondelete="CASCADE"),
        nullable=False,
    )
    registration_model_id = Column(
        Integer,
        ForeignKey("registration_models.id", ondelete="CASCADE"),
        nullable=False,
    )
    mapping_type = Column(Text, nullable=False)
    source = Column(Text, nullable=False)
    review_status = Column(Text, nullable=False, default="approved")

    __table_args__ = (
        UniqueConstraint(
            "product_model_id",
            "registration_model_id",
            name="uq_product_registration_model_link",
        ),
        Index("ix_product_registration_links_product", "product_model_id"),
    )

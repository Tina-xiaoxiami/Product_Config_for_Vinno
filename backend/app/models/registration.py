"""国家-型号-探头注册主数据与成对资料版本模型。"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)

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


class RegistrationPackage(Base):
    __tablename__ = "registration_packages"

    id = Column(Integer, primary_key=True)
    country_code = Column(Text, nullable=False)
    unit_code = Column(Text, nullable=False)
    display_name = Column(Text, nullable=False)
    product_series = Column(Text)
    registration_number = Column(Text)
    identity_source = Column(Text)
    confirmed_by = Column(Text)
    created_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        UniqueConstraint(
            "country_code",
            "unit_code",
            name="uq_registration_package_country_unit",
        ),
        Index(
            "uq_registration_package_number",
            "country_code",
            "registration_number",
            unique=True,
            sqlite_where=text(
                "registration_number IS NOT NULL AND registration_number <> ''"
            ),
        ),
    )


class RegistrationPackageVersion(Base):
    __tablename__ = "registration_package_versions"

    id = Column(Integer, primary_key=True)
    package_id = Column(
        Integer,
        ForeignKey("registration_packages.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_no = Column(Integer, nullable=False)
    previous_version_id = Column(
        Integer,
        ForeignKey("registration_package_versions.id"),
    )
    certificate_document_id = Column(
        Integer,
        ForeignKey("knowledge_documents.id"),
        nullable=False,
    )
    certificate_version = Column(Text)
    certificate_sha256 = Column(Text, nullable=False)
    difference_document_id = Column(
        Integer,
        ForeignKey("knowledge_documents.id"),
        nullable=False,
    )
    difference_version = Column(Text)
    difference_sha256 = Column(Text, nullable=False)
    certificate_artifact_path = Column(Text)
    certificate_file_name = Column(Text)
    certificate_mime_type = Column(Text)
    difference_artifact_path = Column(Text)
    difference_file_name = Column(Text)
    difference_mime_type = Column(Text)
    import_batch_id = Column(
        Integer,
        ForeignKey("registration_import_batches.id"),
        nullable=False,
    )
    snapshot_hash = Column(Text, nullable=False)
    pair_hash = Column(Text, nullable=False)
    diff_json = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="draft")
    change_note = Column(Text)
    effective_date = Column(Text)
    model_count = Column(Integer, nullable=False)
    probe_count = Column(Integer, nullable=False)
    matrix_count = Column(Integer, nullable=False)
    created_at = Column(Text, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    published_at = Column(Text)

    __table_args__ = (
        UniqueConstraint(
            "package_id",
            "version_no",
            name="uq_registration_package_version_no",
        ),
        UniqueConstraint(
            "package_id",
            "pair_hash",
            name="uq_registration_package_pair_hash",
        ),
        CheckConstraint(
            "certificate_document_id <> difference_document_id",
            name="ck_registration_package_distinct_documents",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'superseded')",
            name="ck_registration_package_version_status",
        ),
        Index(
            "uq_registration_package_active",
            "package_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
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
    registration_package_id = Column(
        Integer,
        ForeignKey("registration_packages.id"),
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
        Index("ix_product_registration_links_package", "registration_package_id"),
    )


class RegistrationPackageVersionModel(Base):
    __tablename__ = "registration_package_version_models"

    id = Column(Integer, primary_key=True)
    version_id = Column(
        Integer,
        ForeignKey("registration_package_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    registration_model_id = Column(
        Integer,
        ForeignKey("registration_models.id"),
        nullable=False,
    )
    model_name = Column(Text, nullable=False)
    normalized_name = Column(Text, nullable=False)
    channel_count = Column(Integer)
    source_ref = Column(Text)

    __table_args__ = (
        UniqueConstraint("version_id", "normalized_name", name="uq_registration_version_model"),
        Index("ix_registration_version_models_version", "version_id"),
    )


class RegistrationPackageVersionProbe(Base):
    __tablename__ = "registration_package_version_probes"

    id = Column(Integer, primary_key=True)
    version_id = Column(
        Integer,
        ForeignKey("registration_package_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    registration_probe_id = Column(
        Integer,
        ForeignKey("registration_probes.id"),
        nullable=False,
    )
    probe_model = Column(Text, nullable=False)
    normalized_model = Column(Text, nullable=False)
    ipn = Column(Text, nullable=False)
    source_ref = Column(Text)

    __table_args__ = (
        UniqueConstraint("version_id", "normalized_model", name="uq_registration_version_probe"),
        UniqueConstraint("version_id", "ipn", name="uq_registration_version_probe_ipn"),
        Index("ix_registration_version_probes_version", "version_id"),
    )


class RegistrationPackageVersionModelProbe(Base):
    __tablename__ = "registration_package_version_model_probes"

    id = Column(Integer, primary_key=True)
    version_id = Column(
        Integer,
        ForeignKey("registration_package_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_model_id = Column(
        Integer,
        ForeignKey("registration_package_version_models.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_probe_id = Column(
        Integer,
        ForeignKey("registration_package_version_probes.id", ondelete="CASCADE"),
        nullable=False,
    )
    registration_status = Column(Text, nullable=False)
    source_ref = Column(Text)

    __table_args__ = (
        UniqueConstraint(
            "version_model_id",
            "version_probe_id",
            name="uq_registration_version_model_probe",
        ),
        Index("ix_registration_version_matrix_version", "version_id"),
    )


class RegistrationPackageVersionProductMapping(Base):
    __tablename__ = "registration_package_version_product_mappings"

    id = Column(Integer, primary_key=True)
    version_id = Column(
        Integer,
        ForeignKey("registration_package_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_model_id = Column(
        Integer,
        ForeignKey("product_models.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_model_id = Column(
        Integer,
        ForeignKey("registration_package_version_models.id", ondelete="CASCADE"),
        nullable=False,
    )
    mapping_type = Column(Text, nullable=False)
    review_status = Column(Text, nullable=False, default="pending")

    __table_args__ = (
        UniqueConstraint(
            "version_id",
            "product_model_id",
            name="uq_registration_version_product_mapping",
        ),
        Index("ix_registration_version_mappings_version", "version_id"),
    )

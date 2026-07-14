"""探头配置相关模型"""
from sqlalchemy import Column, Integer, String, Text, Boolean, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base


class ProbeCategory(Base):
    """探头类别（常规凸阵、微凸、线阵等）"""
    __tablename__ = "probe_categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), unique=True, nullable=False)
    sort_order = Column(Integer, default=0)
    # relationships
    models = relationship("ProbeModel", back_populates="category", cascade="all, delete-orphan")
    category_applications = relationship("CategoryApplication", back_populates="category", cascade="all, delete-orphan")
    template_features = relationship("TemplateFeature", back_populates="category", cascade="all, delete-orphan")


class ProbeModel(Base):
    """探头型号 - 对外型号（如 F2-5CP, X2-6C）"""
    __tablename__ = "probe_models"
    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("probe_categories.id", ondelete="CASCADE"), nullable=False)
    model_number = Column(String(200), nullable=False)  # 对外型号标识符
    sort_order = Column(Integer, default=0)
    # relationships
    category = relationship("ProbeCategory", back_populates="models")
    variants = relationship("ProbeModelVariant", back_populates="probe_model", cascade="all, delete-orphan")
    probe_model_apps = relationship("ProbeModelApp", back_populates="probe_model", cascade="all, delete-orphan")
    product_probe_models = relationship("ProductProbeModel", back_populates="probe_model", cascade="all, delete-orphan")
    product_configs = relationship("ProductProbeConfig", back_populates="probe_model", cascade="all, delete-orphan")


class ProbeModelVariant(Base):
    """探头内部型号变体 - 一个对外型号可有多个内部型号+IPN组合"""
    __tablename__ = "probe_model_variants"
    id = Column(Integer, primary_key=True, index=True)
    probe_model_id = Column(Integer, ForeignKey("probe_models.id", ondelete="CASCADE"), nullable=False)
    internal_model = Column(String(200), nullable=False)  # 内部型号
    ipn = Column(String(100), nullable=True)  # IPN号，关联ConfigItem
    notes = Column(String(500), nullable=True)  # 备注，说明差异
    sort_order = Column(Integer, default=0)
    # relationships
    probe_model = relationship("ProbeModel", back_populates="variants")


class Application(Base):
    """应用定义（腹部精细、心脏、血管等）"""
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), unique=True, nullable=False)
    en_name = Column(String(200), nullable=True)
    sort_order = Column(Integer, default=0)


class CategoryApplication(Base):
    """探头类别支持的应用（常规/POC）"""
    __tablename__ = "category_applications"
    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("probe_categories.id", ondelete="CASCADE"), nullable=False)
    application_id = Column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    probe_type = Column(Enum("regular", "poc", name="app_probe_type"), nullable=False, default="regular")
    # relationships
    category = relationship("ProbeCategory", back_populates="category_applications")
    application = relationship("Application")


class FeatureGroup(Base):
    """功能组（基础功能、穿刺、血流、造影成像等）"""
    __tablename__ = "feature_groups"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), unique=True, nullable=False)
    sort_order = Column(Integer, default=0)
    # relationships
    features = relationship("Feature", back_populates="group", cascade="all, delete-orphan")


class Feature(Base):
    """具体功能（TView, VFlow, 常规造影等）"""
    __tablename__ = "features"
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("feature_groups.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False)
    ipn = Column(String(100), nullable=True)  # IPN号，关联ConfigItem
    sort_order = Column(Integer, default=0)
    # relationships
    group = relationship("FeatureGroup", back_populates="features")
    template_features = relationship("TemplateFeature", back_populates="feature", cascade="all, delete-orphan")


class TemplateFeature(Base):
    """模板配置：探头类别 × 功能 的默认支持状态"""
    __tablename__ = "template_features"
    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("probe_categories.id", ondelete="CASCADE"), nullable=False)
    feature_id = Column(Integer, ForeignKey("features.id", ondelete="CASCADE"), nullable=False)
    default_support = Column(Enum("supported", "conditional", "unsupported", name="template_support_status"), nullable=False, default="unsupported")
    default_excludes = Column(Text, nullable=True)  # JSON: ["早孕","中孕","胎心"]
    # relationships
    category = relationship("ProbeCategory", back_populates="template_features")
    feature = relationship("Feature", back_populates="template_features")


class ProductProbeModel(Base):
    """产品型号 × 探头型号 关联（产品支持哪些探头）"""
    __tablename__ = "product_probe_models"
    id = Column(Integer, primary_key=True, index=True)
    product_model_id = Column(Integer, ForeignKey("product_models.id", ondelete="CASCADE"), nullable=False)
    probe_model_id = Column(Integer, ForeignKey("probe_models.id", ondelete="CASCADE"), nullable=False)
    priority = Column(Enum("标1", "标2", "标3", "新", "新(未优化)", "新(未发放)", name="probe_priority"), nullable=True)
    # relationships
    product_model = relationship("ProductModel")
    probe_model = relationship("ProbeModel", back_populates="product_probe_models")
    __table_args__ = (UniqueConstraint("product_model_id", "probe_model_id", name="uq_product_probe"),)


class ProbeModelApp(Base):
    """探头型号 × 应用 关联（探头支持哪些应用）"""
    __tablename__ = "probe_model_apps"
    id = Column(Integer, primary_key=True, index=True)
    probe_model_id = Column(Integer, ForeignKey("probe_models.id", ondelete="CASCADE"), nullable=False)
    application_id = Column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    # relationships
    probe_model = relationship("ProbeModel", back_populates="probe_model_apps")
    application = relationship("Application")
    __table_args__ = (UniqueConstraint("probe_model_id", "application_id", name="uq_probe_app"),)


class ProductProbeConfig(Base):
    """
    产品探头-功能配置（核心配置表）
    每个 (产品型号, 探头型号, 功能) 对应一条记录
    双状态：defined_status（定义值/规格）+ current_status（现状值/实际）
    """
    __tablename__ = "product_probe_configs"
    id = Column(Integer, primary_key=True, index=True)
    product_model_id = Column(Integer, ForeignKey("product_models.id", ondelete="CASCADE"), nullable=False)
    probe_model_id = Column(Integer, ForeignKey("probe_models.id", ondelete="CASCADE"), nullable=False)
    feature_id = Column(Integer, ForeignKey("features.id", ondelete="CASCADE"), nullable=False)

    defined_status = Column(
        Enum("supported", "conditional", "unsupported", name="defined_support_status"),
        nullable=False, default="unsupported"
    )
    current_status = Column(
        Enum("supported", "conditional", "unsupported", name="current_support_status"),
        nullable=False, default="unsupported"
    )
    defined_excludes = Column(Text, nullable=True)   # JSON
    current_excludes = Column(Text, nullable=True)   # JSON

    priority = Column(
        Enum("标1", "标2", "标3", "新", "新(未优化)", "新(未发放)", name="config_priority"),
        nullable=True
    )
    notes = Column(Text, nullable=True)
    is_overridden = Column(Boolean, default=False)  # 是否偏离模板

    # relationships
    product_model = relationship("ProductModel")
    probe_model = relationship("ProbeModel", back_populates="product_configs")
    feature = relationship("Feature")

    __table_args__ = (UniqueConstraint("product_model_id", "probe_model_id", "feature_id", name="uq_product_probe_feature"),)


class ProbeConfigDraft(Base):
    """探头配置草稿表"""
    __tablename__ = "probe_config_drafts"
    id = Column(Integer, primary_key=True, index=True)
    product_model_id = Column(Integer, ForeignKey("product_models.id", ondelete="CASCADE"), nullable=False)
    probe_model_id = Column(Integer, ForeignKey("probe_models.id", ondelete="CASCADE"), nullable=False)
    feature_id = Column(Integer, ForeignKey("features.id", ondelete="CASCADE"), nullable=False)
    change_type = Column(String(20), nullable=False)  # update/create/delete
    old_defined = Column(String(20))
    new_defined = Column(String(20))
    old_current = Column(String(20))
    new_current = Column(String(20))
    old_excludes = Column(Text)
    new_excludes = Column(Text)
    created_at = Column(String(30), default=lambda: __import__('datetime').datetime.utcnow().isoformat())


class ProbeConfigVersion(Base):
    """探头配置版本快照"""
    __tablename__ = "probe_config_versions"
    id = Column(Integer, primary_key=True, index=True)
    product_model_id = Column(Integer, ForeignKey("product_models.id", ondelete="CASCADE"), nullable=False)
    version_number = Column(String(50), nullable=False)
    snapshot_data = Column(Text, nullable=False)  # JSON: full config state
    description = Column(Text)
    created_at = Column(String(30), default=lambda: __import__('datetime').datetime.utcnow().isoformat())
    __table_args__ = (UniqueConstraint("product_model_id", "version_number", name="uq_probe_version"),)


class TemplateDraft(Base):
    """模板配置草稿"""
    __tablename__ = "template_drafts"
    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("probe_categories.id", ondelete="CASCADE"), nullable=False)
    feature_id = Column(Integer, ForeignKey("features.id", ondelete="CASCADE"), nullable=False)
    old_support = Column(String(20))
    new_support = Column(String(20))
    old_excludes = Column(Text)
    new_excludes = Column(Text)
    created_at = Column(String(30), default=lambda: __import__('datetime').datetime.utcnow().isoformat())


class TemplateVersion(Base):
    """模板版本快照"""
    __tablename__ = "template_versions"
    id = Column(Integer, primary_key=True, index=True)
    version_number = Column(String(50), nullable=False)
    snapshot_data = Column(Text, nullable=False)
    description = Column(Text)
    created_at = Column(String(30), default=lambda: __import__('datetime').datetime.utcnow().isoformat())


class ApplicationVersion(Base):
    """应用版本快照"""
    __tablename__ = "application_versions"
    id = Column(Integer, primary_key=True, index=True)
    version_number = Column(String(50), nullable=False)
    snapshot_data = Column(Text, nullable=False)  # JSON: category-application associations
    description = Column(Text)
    created_at = Column(String(30), default=lambda: __import__('datetime').datetime.utcnow().isoformat())


class SeriesProbeConfigVersion(Base):
    """系列级探头配置版本快照"""
    __tablename__ = "series_probe_config_versions"
    id = Column(Integer, primary_key=True, index=True)
    series_ids = Column(Text, nullable=False)  # JSON: [1, 2]
    model_ids = Column(Text, nullable=False)  # JSON: [1, 2, 3]
    version_number = Column(String(50), nullable=False)
    snapshot_data = Column(Text, nullable=False)  # JSON: full merged matrix
    description = Column(Text)
    created_at = Column(String(30), default=lambda: __import__('datetime').datetime.utcnow().isoformat())

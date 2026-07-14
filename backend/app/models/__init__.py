"""
数据模型初始化
"""
from app.models.series import ProductSeries
from app.models.product_model import ProductModel
from app.models.config import ConfigItem, ConfigValue
from app.models.version import ConfigVersion, ChangeLog
from app.models.draft import DraftBatch, ConfigDraft
from app.models.import_history import ImportHistory
from app.models.probe import (
    ProbeCategory, ProbeModel, ProbeModelVariant,
    Application, CategoryApplication,
    FeatureGroup, Feature, TemplateFeature,
    ProductProbeModel, ProbeModelApp, ProductProbeConfig,
    ProbeConfigDraft, ProbeConfigVersion,
)

__all__ = [
    "ProductSeries",
    "ProductModel",
    "ConfigItem",
    "ConfigValue",
    "ConfigVersion",
    "ChangeLog",
    "DraftBatch",
    "ConfigDraft",
    "ImportHistory",
    "ProbeCategory",
    "ProbeModel",
    "ProbeModelVariant",
    "Application",
    "CategoryApplication",
    "FeatureGroup",
    "Feature",
    "TemplateFeature",
    "ProductProbeModel",
    "ProbeModelApp",
    "ProductProbeConfig",
    "ProbeConfigDraft",
    "ProbeConfigVersion",
    "TemplateDraft",
    "TemplateVersion",
]
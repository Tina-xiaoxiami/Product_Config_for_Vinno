"""
数据模型初始化
"""
from app.models.series import ProductSeries
from app.models.product_model import ProductModel
from app.models.config import ConfigItem, ConfigValue
from app.models.version import ConfigVersion, ChangeLog
from app.models.draft import DraftBatch, ConfigDraft
from app.models.import_history import ImportHistory

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
]
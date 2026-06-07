"""
版本控制模型
"""
import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.database import Base


class ConfigVersion(Base):
    """配置版本表"""
    __tablename__ = "config_versions"

    id = Column(Integer, primary_key=True, index=True)
    series_id = Column(Integer, ForeignKey("product_series.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(String(20), nullable=False)  # v1.0.0
    version_name = Column(String(100))
    description = Column(Text)

    # 快照
    snapshot_data = Column(Text, nullable=False)  # JSON格式完整快照
    row_count = Column(Integer, default=0)
    changes_summary = Column(Text)  # JSON格式变更摘要

    published_by = Column(String(100))
    published_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    series = relationship("ProductSeries", back_populates="config_versions")
    change_logs = relationship("ChangeLog", back_populates="version", cascade="all, delete-orphan")

    # 复合唯一索引
    __table_args__ = (
        Index('ix_versions_number', 'series_id', 'version_number', unique=True),
    )

    def get_snapshot_data(self):
        """获取快照数据"""
        if self.snapshot_data:
            return json.loads(self.snapshot_data)
        return {}

    def get_changes_summary(self):
        """获取变更摘要"""
        if self.changes_summary:
            return json.loads(self.changes_summary)
        return {}


class ChangeLog(Base):
    """变更记录表"""
    __tablename__ = "change_logs"

    id = Column(Integer, primary_key=True, index=True)
    series_id = Column(Integer, ForeignKey("product_series.id", ondelete="CASCADE"), nullable=False, index=True)
    version_id = Column(Integer, ForeignKey("config_versions.id", ondelete="SET NULL"))
    change_type = Column(String(20), nullable=False)  # create/update/delete
    item_id = Column(Integer, ForeignKey("config_items.id", ondelete="SET NULL"))
    model_id = Column(Integer, ForeignKey("product_models.id", ondelete="SET NULL"))
    field_name = Column(String(50))  # current_config/final_config/selection_config/rd_status
    old_value = Column(Text)
    new_value = Column(Text)
    changed_by = Column(String(100))
    changed_at = Column(DateTime, default=datetime.utcnow, index=True)

    # 关系
    series = relationship("ProductSeries", back_populates="change_logs")
    version = relationship("ConfigVersion", back_populates="change_logs")
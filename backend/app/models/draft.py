"""
草稿模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.database import Base


class DraftBatch(Base):
    """草稿批次表"""
    __tablename__ = "draft_batches"

    id = Column(String(50), primary_key=True)  # UUID
    series_id = Column(Integer, ForeignKey("product_series.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255))
    status = Column(String(20), default="draft", nullable=False)  # draft/submitted/discarded

    # 统计
    total_count = Column(Integer, default=0)
    create_count = Column(Integer, default=0)
    update_count = Column(Integer, default=0)
    delete_count = Column(Integer, default=0)

    # 元数据
    created_by = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    submitted_at = Column(DateTime)
    submitted_by = Column(String(100))

    # 关系
    series = relationship("ProductSeries", back_populates="draft_batches")
    drafts = relationship("ConfigDraft", back_populates="batch", cascade="all, delete-orphan")


class ConfigDraft(Base):
    """配置草稿表"""
    __tablename__ = "config_drafts"

    id = Column(Integer, primary_key=True, index=True)
    series_id = Column(Integer, ForeignKey("product_series.id", ondelete="CASCADE"), nullable=False, index=True)
    batch_id = Column(String(50), ForeignKey("draft_batches.id", ondelete="CASCADE"), nullable=False, index=True)

    # 变更类型
    change_type = Column(String(20), nullable=False)  # create/update/delete

    # 关联配置项和型号
    item_id = Column(Integer, ForeignKey("config_items.id", ondelete="SET NULL"))
    model_id = Column(Integer, ForeignKey("product_models.id", ondelete="SET NULL"))

    # 变更内容
    field_name = Column(String(50))  # current_config/final_config/selection_config/rd_status
    new_value = Column(Text)
    old_value = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    series = relationship("ProductSeries", back_populates="config_drafts")
    batch = relationship("DraftBatch", back_populates="drafts")
    model = relationship("ProductModel", back_populates="config_drafts")
"""
产品型号模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship

from app.database import Base


class ProductModel(Base):
    """产品型号表"""
    __tablename__ = "product_models"

    id = Column(Integer, primary_key=True, index=True)
    series_id = Column(Integer, ForeignKey("product_series.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)  # 型号描述
    status = Column(String(50), default="生产中")  # 状态：生产中、停产、研发中
    column_start = Column(Integer)
    column_end = Column(Integer)
    sort_order = Column(Integer, default=0)
    config_group = Column(String(200), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    series = relationship("ProductSeries", back_populates="product_models")
    config_values = relationship("ConfigValue", back_populates="model", cascade="all, delete-orphan")
    config_drafts = relationship("ConfigDraft", back_populates="model")
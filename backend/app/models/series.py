"""
产品系列模型
"""
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utcnow


class ProductSeries(Base):
    """产品系列表"""
    __tablename__ = "product_series"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), unique=True, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # 关系
    product_models = relationship("ProductModel", back_populates="series", cascade="all, delete-orphan")
    config_versions = relationship("ConfigVersion", back_populates="series", cascade="all, delete-orphan")
    draft_batches = relationship("DraftBatch", back_populates="series", cascade="all, delete-orphan")
    config_drafts = relationship("ConfigDraft", back_populates="series", cascade="all, delete-orphan")
    change_logs = relationship("ChangeLog", back_populates="series", cascade="all, delete-orphan")
    import_histories = relationship("ImportHistory", back_populates="series", cascade="all, delete-orphan")

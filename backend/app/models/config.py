"""
配置项和配置值模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, Text, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class ConfigItem(Base):
    """配置项表（通用）"""
    __tablename__ = "config_items"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(100), index=True)  # Main Unit / Optional Features
    row_index = Column(Integer, nullable=False)
    rd_name = Column(String(500))
    v_code = Column(String(100))
    ipn = Column(String(100), index=True)
    zh_desc = Column(Text)
    en_desc = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    config_values = relationship("ConfigValue", back_populates="item", cascade="all, delete-orphan")


class ConfigValue(Base):
    """配置值表"""
    __tablename__ = "config_values"

    id = Column(Integer, primary_key=True, autoincrement=True)  # SQLite兼容
    item_id = Column(Integer, ForeignKey("config_items.id", ondelete="CASCADE"), nullable=False, index=True)
    model_id = Column(Integer, ForeignKey("product_models.id", ondelete="CASCADE"), nullable=False, index=True)
    current_config = Column(Text)      # 当前配置
    final_config = Column(Text)        # 最终配置
    selection_config = Column(Text)    # 选型配置
    rd_status = Column(Text)           # 研发状态
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    item = relationship("ConfigItem", back_populates="config_values")
    model = relationship("ProductModel", back_populates="config_values")

    # 唯一约束
    __table_args__ = (
        UniqueConstraint('item_id', 'model_id', name='uq_config_value'),
    )
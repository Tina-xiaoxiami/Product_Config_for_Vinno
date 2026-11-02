"""功能名称标准定义（完整功能名称表：中文名称 / 英文名称 / 中文UI）。

标准表是功能中英文名称的定义来源，存库后由名称核对服务与功能主数据比对，
应用只做提示，不自动改写正式数据。
"""

from sqlalchemy import Column, DateTime, Integer, String, Text, ForeignKey

from app.database import Base
from app.utils.time import utcnow


class FeatureNameStandard(Base):
    """一条功能名称标准定义。"""

    __tablename__ = "feature_name_standards"

    id = Column(Integer, primary_key=True, index=True)
    cn_name = Column(Text, nullable=False, default="")
    cn_detail = Column(Text, nullable=True)
    en_name = Column(Text, nullable=False, default="")
    ui_label = Column(Text, nullable=True)
    ui_detail = Column(Text, nullable=True)
    source_file = Column(String(255), nullable=True)
    sort_order = Column(Integer, default=0)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class FeatureNameReview(Base):
    """A reversible confirmation of one exact baseline comparison; names stay unchanged."""
    __tablename__ = 'feature_name_reviews'
    id = Column(Integer, primary_key=True)
    feature_id = Column(Integer, ForeignKey('features.id', ondelete='CASCADE'), nullable=False, index=True)
    baseline = Column(String(20), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    snapshot_data = Column(Text, nullable=False)
    note = Column(String(1000), nullable=False, default='')
    confirmed_by = Column(String(100), nullable=False, default='local_user')
    confirmed_at = Column(DateTime, nullable=False, default=utcnow)
    revoked_at = Column(DateTime, nullable=True)

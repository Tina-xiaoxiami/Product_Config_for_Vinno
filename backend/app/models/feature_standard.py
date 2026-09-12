"""功能名称标准定义（完整功能名称表：中文名称 / 英文名称 / 中文UI）。

标准表是功能中英文名称的定义来源，存库后由名称核对服务与功能主数据比对，
应用只做提示，不自动改写正式数据。
"""

from sqlalchemy import Column, DateTime, Integer, String, Text

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

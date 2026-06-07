"""
导入历史模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


class ImportHistory(Base):
    """导入历史表"""
    __tablename__ = "import_history"

    id = Column(Integer, primary_key=True, index=True)
    series_id = Column(Integer, ForeignKey("product_series.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String(255), nullable=False)
    records_count = Column(Integer, default=0)
    status = Column(String(20), default="pending")  # pending/success/conflict/failed
    conflict_details = Column(Text)  # JSON格式冲突详情
    imported_by = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    series = relationship("ProductSeries", back_populates="import_histories")
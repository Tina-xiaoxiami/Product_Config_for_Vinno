"""Versioned, source-preserving human measurement library."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint

from app.database import Base
from app.utils.time import utcnow


class MeasurementBatch(Base):
    __tablename__ = "measurement_batches"
    __table_args__ = (UniqueConstraint("sha256", "version", name="uq_measurement_batch_content_version"),)

    id = Column(Integer, primary_key=True)
    version = Column(String(80), nullable=False)
    source_file = Column(String(255), nullable=False)
    sha256 = Column(String(64), nullable=False)
    summary = Column(JSON, nullable=False)
    warnings = Column(JSON, nullable=False)
    imported_at = Column(DateTime, default=utcnow, nullable=False)


class MeasurementEntry(Base):
    __tablename__ = "measurement_entries"

    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey("measurement_batches.id"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)
    item_id = Column(Text, nullable=False)
    description = Column(Text, nullable=False, default="")
    cn_name = Column(Text, nullable=False, default="")
    mode = Column(String(100), nullable=False, default="")
    categories = Column(JSON, nullable=False, default=list)
    group = Column(String(100), nullable=False, default="")
    unit = Column(String(100), nullable=False, default="")
    enabled = Column(String(20), nullable=False, default="unknown")
    enabled_raw = Column(String(100), nullable=False, default="")
    source_sheet = Column(String(100), nullable=False)
    source_row = Column(Integer, nullable=False)

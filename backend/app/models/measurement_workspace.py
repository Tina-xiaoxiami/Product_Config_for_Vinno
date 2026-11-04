"""Managed measurement drafts and immutable releases, separate from source facts."""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from app.database import Base
from app.utils.time import utcnow


class MeasurementWorkspace(Base):
    __tablename__ = 'measurement_workspaces'
    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey('measurement_batches.id'), nullable=False, unique=True)
    revision = Column(Integer, nullable=False, default=1)
    published_data = Column(Text, nullable=False)
    draft_data = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class MeasurementWorkspaceVersion(Base):
    __tablename__ = 'measurement_workspace_versions'
    __table_args__ = (UniqueConstraint('workspace_id', 'version_number', name='uq_measurement_workspace_version'),)
    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey('measurement_workspaces.id'), nullable=False, index=True)
    version_number = Column(String(100), nullable=False)
    description = Column(Text, nullable=False, default='')
    snapshot_data = Column(Text, nullable=False)
    initial = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

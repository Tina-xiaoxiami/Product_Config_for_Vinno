"""Shared probe totals, isolated working drafts and immutable release batches."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from app.database import Base
from app.utils.time import utcnow


class ProbeWorkspace(Base):
    __tablename__ = 'probe_workspaces'
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    published_data = Column(Text, nullable=True)
    draft_data = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class ProbeWorkspaceRelease(Base):
    __tablename__ = 'probe_workspace_releases'
    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey('probe_workspaces.id'), nullable=False, index=True)
    version_number = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    snapshot_data = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint('workspace_id', 'version_number'),)


class ProbeWorkspaceMember(Base):
    """One authoritative total per model; overlapping selections cannot fork it."""
    __tablename__ = 'probe_workspace_members'
    model_id = Column(Integer, ForeignKey('product_models.id'), primary_key=True)
    workspace_id = Column(Integer, ForeignKey('probe_workspaces.id'), nullable=False, index=True)

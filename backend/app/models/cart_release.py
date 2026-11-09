"""Saved Cart checks and content-addressed candidate presentations."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, LargeBinary, String

from app.database import Base
from app.utils.time import utcnow


class CartReleaseArtifact(Base):
    __tablename__ = "cart_release_artifacts"

    sha256 = Column(String(64), primary_key=True)
    data = Column(LargeBinary, nullable=False)


class CartReleaseCheck(Base):
    __tablename__ = "cart_release_checks"

    # A configuration version can be deleted and its SQLite ID reused. The
    # immutable version fingerprint lets its evidence and files remain archived.
    version_key = Column(String(64), primary_key=True)
    version_id = Column(Integer, nullable=False, index=True)
    report = Column(JSON, nullable=False)
    artifact_sha256 = Column(String(64), ForeignKey("cart_release_artifacts.sha256"))
    checked_at = Column(DateTime, nullable=False, default=utcnow)

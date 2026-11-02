"""Explicit, auditable applicability of a controlled release note."""
from sqlalchemy import Column, ForeignKey, Index, Integer, String, Text, text
from app.database import Base


class KnowledgeReleaseBinding(Base):
    __tablename__ = 'knowledge_release_bindings'
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey('knowledge_documents.id'), nullable=False)
    product_model_id = Column(Integer, ForeignKey('product_models.id'), nullable=False)
    country = Column(String(2), nullable=False)
    market = Column(String(20), nullable=False)
    release_line = Column(String(100), nullable=False)
    conditions = Column(Text, nullable=False, default='', server_default='')
    evidence_reference = Column(Text, nullable=False)
    confirmed_by = Column(String(100), nullable=False)
    document_fingerprint = Column(String(64), nullable=False)
    model_name = Column(Text, nullable=False)
    series_name = Column(Text, nullable=False)
    is_active = Column(Integer, nullable=False, server_default='1')
    revision = Column(Integer, nullable=False, server_default='1')
    created_at = Column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    updated_at = Column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    __table_args__ = (Index('uq_knowledge_release_binding_active', 'document_id', 'product_model_id',
        'country', 'market', 'release_line', unique=True, sqlite_where=text('is_active = 1')),)

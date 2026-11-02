"""Controlled parameter records; configuration snapshots remain independent."""
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text, UniqueConstraint, text
from app.database import Base


class KnowledgeParameterTopic(Base):
    __tablename__ = 'knowledge_parameter_topics'
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    question = Column(Text, nullable=False)
    normalized_question = Column(Text, nullable=False, unique=True)
    aliases_json = Column(Text, nullable=False)
    fields_json = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class KnowledgeParameterSpec(Base):
    __tablename__ = 'knowledge_parameter_specs'
    id = Column(Integer, primary_key=True)
    topic_id = Column(Integer, ForeignKey('knowledge_parameter_topics.id'), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    ipn = Column(String(100), nullable=False)
    values_json = Column(Text, nullable=False)
    evidence_reference = Column(Text, nullable=False)
    confirmed_by = Column(String(100), nullable=False)
    revision = Column(Integer, nullable=False)
    is_active = Column(Boolean, nullable=False, server_default=text('1'))
    updated_at = Column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))


class KnowledgeParameterRevision(Base):
    __tablename__ = 'knowledge_parameter_revisions'
    id = Column(Integer, primary_key=True)
    spec_id = Column(Integer, ForeignKey('knowledge_parameter_specs.id'), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    payload_json = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    __table_args__ = (UniqueConstraint('spec_id', 'revision', name='uq_parameter_spec_revision'),)

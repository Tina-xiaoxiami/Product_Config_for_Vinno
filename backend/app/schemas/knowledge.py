"""Schemas for the unified product knowledge API."""

from pydantic import BaseModel, Field


class FeatureKnowledgeName(BaseModel):
    language: str
    name: str
    name_type: str
    source: str


class FeatureKnowledgeIpn(BaseModel):
    ipn: str
    relation_type: str
    zh_desc: str | None = None
    en_desc: str | None = None


class FeatureKnowledgeItem(BaseModel):
    id: int
    legacy_name: str
    group_name: str
    identity_status: str
    primary_cn_name: str | None = None
    primary_en_name: str | None = None
    names: list[FeatureKnowledgeName] = Field(default_factory=list)
    ipns: list[FeatureKnowledgeIpn] = Field(default_factory=list)


class FeatureKnowledgeList(BaseModel):
    items: list[FeatureKnowledgeItem]
    total: int
    skip: int
    limit: int


class KnowledgeStats(BaseModel):
    total_features: int
    auto_matched: int
    confirmed: int
    related: int
    pending: int


class KnowledgeDocumentItem(BaseModel):
    id: int
    document_type: str
    title: str
    file_name: str
    version: str | None = None
    market: str
    country: str | None = None
    product_series: str | None = None
    mime_type: str | None = None
    file_size: int
    available: bool
    preview_url: str


class KnowledgeDocumentList(BaseModel):
    items: list[KnowledgeDocumentItem]
    total: int
    skip: int
    limit: int

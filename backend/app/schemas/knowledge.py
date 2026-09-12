"""Schemas for the unified product knowledge API."""

from typing import Any

from pydantic import BaseModel, Field


class LocalFileOpenRequest(BaseModel):
    """在本机打开受控原件的方式。"""

    mode: str = Field(default="open", pattern="^(open|reveal)$")


class LocalFileOpenResult(BaseModel):
    file_name: str
    mode: str
    file_path: str


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
    extraction_status: str = "not_extracted"
    chunk_count: int = 0
    extracted_at: str | None = None


class KnowledgeDocumentList(BaseModel):
    items: list[KnowledgeDocumentItem]
    total: int
    skip: int
    limit: int


class KnowledgeQuestionAsk(BaseModel):
    question: str = Field(min_length=2, max_length=500)


class KnowledgeAnswerCitationInput(BaseModel):
    document_id: int
    source_ref: str | None = Field(default=None, max_length=500)
    excerpt: str | None = Field(default=None, max_length=4000)


class KnowledgeAnswerPublish(BaseModel):
    answer_text: str = Field(min_length=1, max_length=20000)
    alias_questions: list[str] = Field(default_factory=list, max_length=50)
    citations: list[KnowledgeAnswerCitationInput] = Field(default_factory=list, max_length=50)
    change_note: str | None = Field(default=None, max_length=1000)


class KnowledgeAnswerCitationItem(BaseModel):
    id: int
    document_id: int
    document_title: str
    source_ref: str | None = None
    excerpt: str | None = None
    preview_url: str


class KnowledgeAnswerItem(BaseModel):
    id: int
    answer_text: str
    review_status: str
    version: int
    change_note: str | None = None
    updated_at: str
    citations: list[KnowledgeAnswerCitationItem] = Field(default_factory=list)


class KnowledgeQuestionItem(BaseModel):
    id: int
    question_text: str
    status: str
    asked_count: int
    last_asked_at: str
    alias_questions: list[str] = Field(default_factory=list)
    answer: KnowledgeAnswerItem | None = None


class KnowledgeQuestionList(BaseModel):
    items: list[KnowledgeQuestionItem]
    total: int
    skip: int
    limit: int


class KnowledgeDocumentExtractionReview(BaseModel):
    item_count: int = 0
    needs_review_count: int = 0


class KnowledgeDocumentExtractionItem(BaseModel):
    document_id: int
    status: str
    chunk_count: int
    extracted_at: str | None = None
    extractor_version: str
    reused: bool = False
    review: KnowledgeDocumentExtractionReview | None = None


class KnowledgeCandidateEvidence(BaseModel):
    chunk_id: int
    document_id: int
    document_title: str
    document_type: str
    source_ref: str
    page_number: int | None = None
    excerpt: str
    score: float
    preview_url: str


class KnowledgeCandidateEvidenceList(BaseModel):
    items: list[KnowledgeCandidateEvidence]


class KnowledgeQuestionResult(BaseModel):
    status: str
    question_id: int
    question: str
    match_type: str
    similarity: float
    answer: KnowledgeAnswerItem | None = None
    candidates: list[KnowledgeCandidateEvidence] = Field(default_factory=list)


class KnowledgeAnswerRevisionItem(BaseModel):
    version: int
    answer_text: str
    review_status: str
    change_note: str | None = None
    created_at: str


class KnowledgeAnswerHistory(BaseModel):
    items: list[KnowledgeAnswerRevisionItem]


class DataReviewBatchItem(BaseModel):
    data_type: str
    batch_id: int
    document_id: int
    document_title: str
    document_type: str
    market: str
    batch_status: str | None = None
    snapshot_date: str | None = None
    total_count: int
    needs_review_count: int
    corrected_count: int
    excluded_count: int
    preview_url: str


class DataReviewBatchList(BaseModel):
    items: list[DataReviewBatchItem] = Field(default_factory=list)
    total: int


class DataReviewItem(BaseModel):
    id: int
    document_id: int
    document_title: str
    data_type: str
    batch_id: int
    source_record_key: str
    source_ref: str
    raw_payload: dict[str, Any]
    effective_payload: dict[str, Any]
    issue_codes: list[str] = Field(default_factory=list)
    review_status: str
    updated_by: str | None = None
    change_note: str | None = None
    created_at: str
    updated_at: str
    preview_url: str


class DataReviewItemList(BaseModel):
    items: list[DataReviewItem] = Field(default_factory=list)
    total: int
    skip: int
    limit: int


class DataReviewItemUpdate(BaseModel):
    effective_payload: dict[str, Any]
    review_status: str = Field(pattern="^(corrected|confirmed|excluded)$")
    changed_by: str = Field(min_length=1, max_length=100)
    change_note: str | None = Field(default=None, max_length=1000)


class DataReviewRevisionItem(BaseModel):
    revision_no: int
    before_payload: dict[str, Any]
    after_payload: dict[str, Any]
    action: str
    change_note: str | None = None
    changed_by: str
    created_at: str


class DataReviewRevisionList(BaseModel):
    items: list[DataReviewRevisionItem] = Field(default_factory=list)

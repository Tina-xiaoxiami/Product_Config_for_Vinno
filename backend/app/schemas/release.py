"""Schemas for the feature release (functional version + release introduction) API."""

from pydantic import BaseModel, Field


class ReleaseVersionCreate(BaseModel):
    """新建一条功能版本记录（默认作为待复核候选）。"""

    software_version: str = Field(min_length=1, max_length=50)
    product_series: str | None = Field(default=None, max_length=100)
    market: str | None = Field(default="domestic", max_length=30)
    release_date: str | None = Field(default=None, max_length=20)
    change_type: str | None = Field(default="unknown", max_length=30)
    configuration_status: str | None = None
    lifecycle_status: str | None = Field(default="undefined", max_length=20)
    evidence_document_id: int | None = None
    evidence_source_ref: str | None = None
    evidence_excerpt: str | None = None
    source: str | None = Field(default="manual", max_length=30)
    review_status: str | None = Field(default="pending", max_length=20)
    change_note: str | None = None


class ReleaseVersionUpdate(BaseModel):
    """修改一条功能版本记录；只有显式传入的字段会被更新。"""

    software_version: str | None = Field(default=None, max_length=50)
    product_series: str | None = Field(default=None, max_length=100)
    market: str | None = Field(default=None, max_length=30)
    release_date: str | None = Field(default=None, max_length=20)
    change_type: str | None = Field(default=None, max_length=30)
    configuration_status: str | None = None
    lifecycle_status: str | None = Field(default=None, max_length=20)
    review_status: str | None = Field(default=None, max_length=20)
    change_note: str | None = None


class ReleaseVersionItem(BaseModel):
    id: int
    feature_id: int
    software_version: str
    version_sort_key: str
    product_series: str = ""
    market: str
    release_date: str | None = None
    change_type: str
    configuration_status: str | None = None
    lifecycle_status: str = "undefined"
    evidence_document_id: int | None = None
    evidence_document_title: str | None = None
    evidence_document_version: str | None = None
    evidence_source_ref: str | None = None
    evidence_excerpt: str | None = None
    evidence_kind: str = "manual"
    matched_by: str | None = None
    source: str
    review_status: str
    change_note: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    introduction_id: int | None = None
    introduction_version: int | None = None
    introduction_review_status: str | None = None
    introduction_preview: str | None = None
    preview_url: str | None = None
    feature_name: str | None = None
    feature_primary_cn_name: str | None = None
    feature_primary_en_name: str | None = None
    feature_ipn: str | None = None


class ReleaseFeatureIdentity(BaseModel):
    id: int
    legacy_name: str
    ipn: str | None = None
    primary_cn_name: str | None = None
    primary_en_name: str | None = None
    identity_status: str | None = None


class FeatureReleaseTimeline(BaseModel):
    """某个功能的发布版本时间线，含首发版本与覆盖边界提示。"""

    feature: ReleaseFeatureIdentity
    first_release: ReleaseVersionItem | None = None
    first_release_candidate: ReleaseVersionItem | None = None
    earliest_ingested_version: str | None = None
    coverage_note: str = ""
    confirmed_count: int = 0
    pending_count: int = 0
    items: list[ReleaseVersionItem] = Field(default_factory=list)


class ReleaseVersionList(BaseModel):
    items: list[ReleaseVersionItem]
    total: int
    skip: int
    limit: int


class ReleaseVersionOverviewItem(BaseModel):
    software_version: str
    version_sort_key: str
    total: int
    confirmed: int
    pending: int
    release_date: str | None = None


class ReleaseVersionOverviewList(BaseModel):
    items: list[ReleaseVersionOverviewItem]


class ReleaseIntroductionSave(BaseModel):
    """保存发布介绍内容；保存前会把上一版快照进历史表。"""

    summary: str | None = None
    clinical_significance: str | None = None
    workflow: str | None = None
    applications: list[str] | None = None
    review_status: str | None = Field(default="draft", max_length=20)
    change_note: str | None = None


class ReleaseAttachmentItem(BaseModel):
    id: int
    file_name: str
    file_path: str
    sha256: str | None = None
    mime_type: str | None = None
    file_size: int = 0
    sort_order: int = 0


class ReleaseIntroductionItem(BaseModel):
    id: int
    feature_version_id: int
    summary: str | None = None
    clinical_significance: str | None = None
    workflow: str | None = None
    applications: list[str] = Field(default_factory=list)
    version: int
    review_status: str
    change_note: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    attachments: list[ReleaseAttachmentItem] = Field(default_factory=list)


class ReleaseIntroductionRevisionItem(BaseModel):
    version: int
    summary: str | None = None
    clinical_significance: str | None = None
    workflow: str | None = None
    applications: list[str] = Field(default_factory=list)
    review_status: str
    change_note: str | None = None
    created_at: str | None = None
    is_current: bool = False


class ReleaseIntroductionHistory(BaseModel):
    items: list[ReleaseIntroductionRevisionItem]


class ReleaseEvidenceDocumentItem(BaseModel):
    id: int
    title: str
    version: str | None = None
    product_series: str | None = None
    market: str | None = None
    preview_url: str


class ReleaseEvidenceDocumentList(BaseModel):
    items: list[ReleaseEvidenceDocumentItem]


class ReleaseBackfillCandidate(BaseModel):
    """待复核候选：来自 Release Note 原文，尚未成为正式结论。"""

    feature_id: int
    feature_name: str
    feature_primary_cn_name: str | None = None
    feature_ipn: str | None = None
    software_version: str
    product_series: str = ""
    market: str = "domestic"
    change_type: str
    configuration_status: str | None = None
    matched_by: str
    evidence_kind: str = "narrative"
    evidence_document_id: int | None = None
    evidence_document_title: str | None = None
    evidence_source_ref: str | None = None
    evidence_excerpt: str | None = None
    is_first_release_candidate: bool = False
    existing_version_id: int | None = None
    skip_reason: str | None = None


class ReleaseBackfillPreview(BaseModel):
    candidates: list[ReleaseBackfillCandidate]
    total: int
    scanned_total: int = 0
    applicable: int
    skipped: int
    earliest_ingested_version: str | None = None
    coverage_note: str = ""
    applied: bool = False
    created: int = 0


class ReleaseBackfillRequest(BaseModel):
    product_series: str | None = Field(default=None, max_length=100)
    software_versions: list[str] | None = None
    feature_ids: list[int] | None = None
    limit: int | None = Field(default=None, ge=1, le=2000)
    apply: bool = False


class ReleaseAttachmentDeleteResult(BaseModel):
    attachment_id: int
    status: str
    removed_file: bool = False

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
    # 留痕的操作人：不传也能改，但留痕里会记成未署名，便于事后区分。
    changed_by: str | None = Field(default=None, max_length=100)


class ReleaseBatchReviewRequest(BaseModel):
    """批量复核待确认的功能版本；默认只预览，显式落库才写。

    范围可以用版本 / 系列 / 变更类型 / 证据类型组合，也可以直接用
    `first_candidate_only` 只处理每个功能的首发候选；`version_ids` 用于
    界面勾选后的精确提交。预览（`dry_run=True`）不要求填修改人，落库时必填。
    """

    review_status: str = Field(pattern="^(confirmed|rejected)$")
    changed_by: str | None = Field(default=None, max_length=100)
    change_note: str | None = Field(default=None, max_length=1000)
    feature_id: int | None = None
    software_version: str | None = Field(default=None, max_length=50)
    product_series: str | None = Field(default=None, max_length=100)
    market: str | None = Field(default=None, max_length=30)
    change_type: str | None = Field(default=None, max_length=30)
    evidence_kind: str | None = Field(default=None, max_length=30)
    first_candidate_only: bool = False
    version_ids: list[int] | None = None
    # 命中超过 batch_review_limit 时必须回传相同数字才能执行。
    confirm_count: int | None = Field(default=None, ge=0)
    dry_run: bool = True


class ReleaseBatchReviewChangeTypeGroup(BaseModel):
    """按变更类型的命中分布。"""

    change_type: str
    matched: int


class ReleaseBatchReviewVersionGroup(BaseModel):
    """按软件版本的命中分布。"""

    software_version: str
    matched: int


class ReleaseVersionRevisionItem(BaseModel):
    revision_no: int
    action: str
    before: dict = Field(default_factory=dict)
    after: dict = Field(default_factory=dict)
    change_note: str | None = None
    changed_by: str | None = None
    created_at: str


class ReleaseVersionRevisionList(BaseModel):
    items: list[ReleaseVersionRevisionItem] = Field(default_factory=list)


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


class ReleaseBatchReviewItem(ReleaseVersionItem):
    """批量复核的明细行，额外标出它是否属于首发候选。"""

    is_first_release_candidate: bool = False


class ReleaseBatchReviewResult(BaseModel):
    """批量复核的结果：先预览（dry_run），再落库。

    `applied=False` 表示这次只做了预览；`limit` 与 `requires_confirm_count`
    告诉界面「命中条数超过阈值时必须回传确认条数」。
    """

    applied: bool
    dry_run: bool
    review_status: str
    action: str
    change_note: str
    matched: int
    limit: int
    requires_confirm_count: bool
    by_change_type: list[ReleaseBatchReviewChangeTypeGroup] = Field(default_factory=list)
    by_software_version: list[ReleaseBatchReviewVersionGroup] = Field(
        default_factory=list
    )
    items: list[ReleaseBatchReviewItem] = Field(default_factory=list)


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


class ReleaseTemplateItem(BaseModel):
    """发布介绍 Word 导出模板：`sections` 决定章节，`variables` 决定变量白名单。"""

    id: int | None = None
    code: str
    name: str
    description: str | None = None
    sections: list[str] = Field(default_factory=list)
    variables: list[str] = Field(default_factory=list)
    active: bool = True
    is_system: bool = False


class ReleaseTemplateList(BaseModel):
    items: list[ReleaseTemplateItem]


class ReleaseTemplateCreate(BaseModel):
    code: str = Field(min_length=3, max_length=80)
    name: str = Field(min_length=1)
    description: str | None = None
    sections: list[str] | None = None
    variables: list[str] | None = None
    active: bool = True


class ReleaseTemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    sections: list[str] | None = None
    variables: list[str] | None = None
    active: bool | None = None

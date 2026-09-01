"""探头配置 Pydantic Schemas"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ========== ProbeCategory ==========
class ProbeCategoryBase(BaseModel):
    name: str
    sort_order: int = 0

class ProbeCategoryCreate(ProbeCategoryBase):
    pass

class ProbeCategoryUpdate(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None

class ProbeCategoryResponse(ProbeCategoryBase):
    id: int
    model_config = {"from_attributes": True}

class ProbeCategoryListResponse(BaseModel):
    items: List[ProbeCategoryResponse]
    total: int


# ========== ProbeModel ==========
class ProbeModelVariantBase(BaseModel):
    probe_model_id: int
    internal_model: str
    ipn: Optional[str] = None
    sort_order: int = 0

class ProbeModelVariantResponse(ProbeModelVariantBase):
    id: int
    model_config = {"from_attributes": True}

class ProbeModelBase(BaseModel):
    category_id: int
    model_number: str
    sort_order: int = 0

class ProbeModelCreate(ProbeModelBase):
    pass

class ProbeModelUpdate(BaseModel):
    category_id: Optional[int] = None
    model_number: Optional[str] = None
    sort_order: Optional[int] = None

class ProbeModelResponse(ProbeModelBase):
    id: int
    model_config = {"from_attributes": True}

class ProbeModelListResponse(BaseModel):
    items: List[ProbeModelResponse]
    total: int


# ========== Application ==========
class ApplicationBase(BaseModel):
    name: str
    en_name: Optional[str] = None
    sort_order: int = 0

class ApplicationCreate(ApplicationBase):
    pass

class ApplicationUpdate(BaseModel):
    name: Optional[str] = None
    en_name: Optional[str] = None
    sort_order: Optional[int] = None

class ApplicationResponse(ApplicationBase):
    id: int
    usage_count: int = 0
    probe_types: list[str] = []
    model_config = {"from_attributes": True}

class ApplicationListResponse(BaseModel):
    items: List[ApplicationResponse]
    total: int


# ========== FeatureGroup ==========
class FeatureGroupBase(BaseModel):
    name: str
    sort_order: int = 0

class FeatureGroupCreate(FeatureGroupBase):
    pass

class FeatureGroupUpdate(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None

class FeatureGroupResponse(FeatureGroupBase):
    id: int
    model_config = {"from_attributes": True}

class FeatureGroupListResponse(BaseModel):
    items: List[FeatureGroupResponse]
    total: int


# ========== Feature ==========
class FeatureBase(BaseModel):
    group_id: int
    name: str
    ipn: Optional[str] = None
    sort_order: int = 0

class FeatureCreate(FeatureBase):
    pass

class FeatureUpdate(BaseModel):
    group_id: Optional[int] = None
    name: Optional[str] = None
    ipn: Optional[str] = None
    sort_order: Optional[int] = None

class FeatureResponse(FeatureBase):
    id: int
    primary_cn_name: Optional[str] = None
    primary_en_name: Optional[str] = None
    identity_status: str = "pending"
    model_config = {"from_attributes": True}

class FeatureListResponse(BaseModel):
    items: List[FeatureResponse]
    total: int


class FeatureMasterIpnInput(BaseModel):
    ipn: str
    relation_type: str = Field(pattern="^(primary|related|version_variant)$")


class FeatureMasterIpn(FeatureMasterIpnInput):
    config_item_id: int
    zh_desc: Optional[str] = None
    en_desc: Optional[str] = None


class FeatureMasterDataUpdate(BaseModel):
    primary_cn_name: str
    primary_en_name: str
    alias_cn_names: List[str] = Field(default_factory=list)
    alias_en_names: List[str] = Field(default_factory=list)
    ipns: List[FeatureMasterIpnInput] = Field(default_factory=list)


class FeatureMasterDataResponse(BaseModel):
    id: int
    group_id: int
    group_name: str
    primary_cn_name: str
    primary_en_name: str
    alias_cn_names: List[str] = Field(default_factory=list)
    alias_en_names: List[str] = Field(default_factory=list)
    ipns: List[FeatureMasterIpn] = Field(default_factory=list)


# ========== TemplateFeature ==========
class TemplateFeatureBase(BaseModel):
    category_id: int
    feature_id: int
    default_support: str = "unsupported"  # "supported" | "unsupported"
    default_excludes: Optional[str] = None  # JSON

class TemplateFeatureCreate(TemplateFeatureBase):
    pass

class TemplateFeatureUpdate(BaseModel):
    default_support: Optional[str] = None
    default_excludes: Optional[str] = None

class TemplateFeatureResponse(TemplateFeatureBase):
    id: int
    model_config = {"from_attributes": True}


# ========== 产品探头配置 ==========
class ProductProbeConfigItem(BaseModel):
    """单个配置项"""
    id: Optional[int] = None
    probe_model_id: int
    probe_model_number: str = ""
    category_name: str = ""
    feature_id: int
    feature_name: str = ""
    group_name: str = ""
    defined_status: str = "unsupported"
    current_status: str = "unsupported"
    defined_excludes: Optional[str] = None
    current_excludes: Optional[str] = None
    priority: Optional[str] = None
    notes: Optional[str] = None
    is_overridden: bool = False
    template_support: str = "unsupported"


class ProductProbeConfigMatrix(BaseModel):
    """矩阵数据"""
    product_model_id: int
    product_model_name: str = ""
    features: List[dict] = []   # [{id, name, group_id, group_name}]
    probe_models: List[dict] = []  # [{id, model_number, category_id, category_name, priority}]
    applications: List[dict] = []  # [{id, name}]
    configs: dict = {}  # key: f"{probe_model_id}_{feature_id}" -> ProductProbeConfigItem


class UpdateProbeFeatureRequest(BaseModel):
    """更新 feature 支持状态请求"""
    probe_model_id: int
    feature_id: int
    defined_status: Optional[str] = None
    current_status: Optional[str] = None
    defined_excludes: Optional[str] = None
    current_excludes: Optional[str] = None
    priority: Optional[str] = None
    notes: Optional[str] = None


class ProductProbeInitRequest(BaseModel):
    """从模板初始化产品配置请求"""
    probe_model_ids: Optional[List[int]] = None  # 指定探头，空=全部

# ========== 版本管理 ==========
class ProbeDraftResponse(BaseModel):
    id: int; product_model_id: int; probe_model_id: int; feature_id: int
    change_type: str; old_defined: Optional[str]=None; new_defined: Optional[str]=None
    old_current: Optional[str]=None; new_current: Optional[str]=None
    created_at: Optional[str]=None
    model_config = {"from_attributes": True}

class ProbeVersionResponse(BaseModel):
    id: int; product_model_id: int; version_number: str
    description: Optional[str]=None; created_at: Optional[str]=None
    snapshot_data: Optional[str] = None
    model_config = {"from_attributes": True}

class ProbeDraftListResponse(BaseModel):
    drafts: list[ProbeDraftResponse] = []
    total: int = 0

class SubmitDraftRequest(BaseModel):
    version_number: Optional[str] = None
    description: Optional[str] = None


# ========== 系列探头查询 ==========
class SeriesProbeModelItem(BaseModel):
    id: int
    model_number: str
    category_id: int
    category_name: str
    source_product_models: list[str] = []

class SeriesProbeCategory(BaseModel):
    id: int
    name: str
    models: list[SeriesProbeModelItem] = []

class SeriesProbeSummary(BaseModel):
    product_model_names: list[str] = []
    total_models: int = 0
    total_probes: int = 0

class SeriesProbeResult(BaseModel):
    categories: list[SeriesProbeCategory] = []
    probe_ids: list[int] = []
    summary: SeriesProbeSummary = SeriesProbeSummary()
    empty_series: list[str] = []
    empty_probes: list[str] = []


# ========== 系列级聚合矩阵 ==========
class MergedConfigItem(BaseModel):
    defined_status: str = "unsupported"
    current_status: str = "unsupported"
    defined_excludes: Optional[str] = None
    current_excludes: Optional[str] = None
    template_support: str = "unsupported"
    template_excludes: Optional[str] = None
    priority: Optional[str] = None
    notes: Optional[str] = None
    is_overridden: bool = False
    per_model: dict = {}  # {model_id: {defined_status, current_status}}

class SeriesMatrixResponse(BaseModel):
    series_ids: list[int] = []
    product_models: list[dict] = []
    features: list[dict] = []
    probe_models: list[dict] = []
    applications: dict = {}
    configs: dict = {}  # {probe_model_id: {feature_id: MergedConfigItem}}

class SeriesFeatureUpdateRequest(BaseModel):
    probe_model_id: int
    feature_id: int
    defined_status: Optional[str] = None
    current_status: Optional[str] = None
    defined_excludes: Optional[str] = None
    current_excludes: Optional[str] = None
    priority: Optional[str] = None
    notes: Optional[str] = None
    target_model_ids: list[int]

class SeriesSubmitRequest(BaseModel):
    series_ids: list[int]
    model_ids: list[int]
    version_number: Optional[str] = None
    description: Optional[str] = None

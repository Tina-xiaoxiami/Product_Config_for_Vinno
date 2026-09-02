"""注册红线与产品策略查询结构。"""

from pydantic import BaseModel, Field


class ConfiguredRegistrationModel(BaseModel):
    product_model_id: int
    product_model_name: str
    registration_model_id: int
    registration_model_name: str
    mapping_type: str
    channel_count: int | None = None
    registration_package_id: int
    registration_number: str
    registration_package_name: str


class ConfiguredRegistrationModelList(BaseModel):
    items: list[ConfiguredRegistrationModel]
    total: int


class RegistrationModelItem(BaseModel):
    id: int
    country_code: str
    model_name: str
    channel_count: int | None = None
    source_document_id: int | None = None


class RegistrationModelList(BaseModel):
    items: list[RegistrationModelItem]
    total: int
    skip: int
    limit: int


class RegistrationMasterProbeItem(BaseModel):
    matrix_id: int
    probe_id: int
    probe_model: str
    ipn: str
    registration_status: str
    config_item_id: int | None = None
    config_name: str | None = None
    probe_master_id: int | None = None
    probe_master_model: str | None = None
    source_document_id: int | None = None
    source_ref: str | None = None


class RegistrationMasterProbeList(BaseModel):
    registration_model_id: int
    country_code: str
    model_name: str
    source_document_id: int | None = None
    items: list[RegistrationMasterProbeItem] = Field(default_factory=list)
    total: int


class RegistrationProbeStrategyItem(BaseModel):
    probe_id: int
    probe_model: str
    ipn: str
    registration_status: str
    registration_symbol: str
    selection_config: str | None = None
    current_config: str | None = None
    effective_status: str
    status_source: str
    strategy_is_formal: bool
    conflict: bool
    config_item_id: int | None = None
    config_name: str | None = None
    probe_master_id: int | None = None
    probe_master_model: str | None = None
    source_document_id: int | None = None


class RegistrationProbeSummary(BaseModel):
    registered: int = 0
    unregistered: int = 0
    standard: int = 0
    optional: int = 0
    tender: int = 0
    undefined: int = 0
    auxiliary: int = 0
    conflicts: int = 0


class RegistrationProbeStrategyList(BaseModel):
    items: list[RegistrationProbeStrategyItem] = Field(default_factory=list)
    total: int
    skip: int
    limit: int
    product_model_id: int
    product_model_name: str
    registration_model_id: int
    registration_model_name: str
    source_document_id: int | None = None
    mapping_type: str
    registration_package_id: int
    registration_number: str
    registration_package_name: str
    summary: RegistrationProbeSummary


class RegistrationMaterialReference(BaseModel):
    document_id: int
    title: str
    version: str | None = None
    sha256: str
    preview_url: str


class RegistrationPackageVersionItem(BaseModel):
    id: int
    package_id: int
    version_no: int
    previous_version_id: int | None = None
    status: str
    change_note: str | None = None
    effective_date: str | None = None
    model_count: int
    probe_count: int
    matrix_count: int
    created_at: str
    published_at: str | None = None
    diff: dict
    certificate: RegistrationMaterialReference
    difference: RegistrationMaterialReference


class RegistrationPackageBase(BaseModel):
    id: int
    country_code: str
    unit_code: str
    display_name: str
    product_series: str | None = None
    registration_number: str | None = None
    identity_source: str | None = None
    confirmed_by: str | None = None


class RegistrationPackageItem(RegistrationPackageBase):
    current_version: RegistrationPackageVersionItem | None = None


class RegistrationPackageList(BaseModel):
    items: list[RegistrationPackageItem] = Field(default_factory=list)
    total: int


class RegistrationPackageVersionList(BaseModel):
    package: RegistrationPackageBase
    items: list[RegistrationPackageVersionItem] = Field(default_factory=list)


class RegistrationPackageMappingUpdate(BaseModel):
    mappings: dict[int, str]


class RegistrationPackagePublishRequest(BaseModel):
    confirmed_by: str = Field(min_length=1, max_length=100)

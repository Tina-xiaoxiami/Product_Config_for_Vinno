"""注册红线与产品策略查询结构。"""

from pydantic import BaseModel, Field


class ConfiguredRegistrationModel(BaseModel):
    product_model_id: int
    product_model_name: str
    registration_model_id: int
    registration_model_name: str
    mapping_type: str
    channel_count: int | None = None


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
    summary: RegistrationProbeSummary

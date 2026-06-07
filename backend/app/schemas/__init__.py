"""
Pydantic schemas
"""
from app.schemas.series import ProductSeriesCreate, ProductSeriesResponse, ProductSeriesUpdate
from app.schemas.model import ProductModelCreate, ProductModelResponse
from app.schemas.config import ConfigItemResponse, ConfigValueResponse, ConfigRowResponse
from app.schemas.version import (
    ConfigVersionCreate, ConfigVersionResponse,
    VersionCompareRequest, VersionCompareResponse
)
from app.schemas.draft import (
    DraftBatchResponse, DraftSubmitRequest,
    ConfigDraftCreate, ConfigDraftResponse
)

__all__ = [
    "ProductSeriesCreate", "ProductSeriesResponse", "ProductSeriesUpdate",
    "ProductModelCreate", "ProductModelResponse",
    "ConfigItemResponse", "ConfigValueResponse", "ConfigRowResponse",
    "ConfigVersionCreate", "ConfigVersionResponse",
    "VersionCompareRequest", "VersionCompareResponse",
    "DraftBatchResponse", "DraftSubmitRequest",
    "ConfigDraftCreate", "ConfigDraftResponse",
]
"""Strict text-only research proposals. No expression evaluator is involved."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

Category = Literal['Common', 'ABD', 'CARD', 'GYN', 'OB', 'VAS']
Mode = Literal['Tissue', 'Flow', 'TissueTM', 'Doppler', 'EI', 'PWVTM', 'STRAINRATETM', 'VShear', 'pVShear', 'URM', 'VATT', 'SMF']


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Dependency(StrictModel):
    kind: Literal['measurement', 'calculation']
    item_id: StrictStr = Field(min_length=1)


class InputTerm(StrictModel):
    relation_kind: Literal['input', 'alternative', 'context', 'unresolved'] = 'input'
    term: StrictStr = Field(min_length=1)
    possible_dependencies: list[Dependency]
    uncertainty: StrictStr


class Source(StrictModel):
    url: StrictStr
    title: StrictStr = Field(min_length=1)
    publisher: StrictStr | None = None
    locator: StrictStr = Field(min_length=1)
    supports: list[StrictStr] = Field(min_length=1)

    @field_validator('url')
    @classmethod
    def http_url(cls, value):
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('来源必须为公开 HTTP(S) 地址')
        return value


class EnrichmentPayload(StrictModel):
    categories: list[Category]
    modes: list[Mode]
    input_terms: list[InputTerm]
    formula_reference: StrictStr
    sources: list[Source]
    uncertainties: list[StrictStr]
    research_status: Literal['proposed', 'unresolved']
    mapping_basis: StrictStr = Field(min_length=1)


class CandidateInput(StrictModel):
    item_id: StrictStr = Field(min_length=1)
    payload: EnrichmentPayload


class EnrichmentImport(StrictModel):
    batch_id: int = Field(ge=1)
    expected_sha256: StrictStr = Field(pattern=r'^[a-f0-9]{64}$')
    expected_version: StrictStr
    schema_version: Literal[1]
    candidates: list[CandidateInput] = Field(min_length=1, max_length=20000)


class EnrichmentReview(StrictModel):
    action: Literal['confirm', 'reject', 'defer', 'revoke']
    expected_candidate_fingerprint: StrictStr
    expected_source_fingerprint: StrictStr
    expected_review_revision: int = Field(ge=0)
    confirmed_by: StrictStr = Field(min_length=1)
    note: StrictStr = ''
    confirmed_payload: EnrichmentPayload | None = None

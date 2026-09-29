"""Application-side public mapped-background contract; no inventory data."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SHA256 = r'^[0-9a-f]{64}$'


class ProviderMappedBackgroundProcessPin(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    schema_version: Literal['provider.mapped-background-process-pin.v1'] = 'provider.mapped-background-process-pin.v1'
    consumer_exchange_id: str = Field(min_length=1, max_length=255)
    source_flow_namespace: str = Field(min_length=1)
    source_flow_uuid: str = Field(min_length=1)
    source_flow_version: str = Field(min_length=1)
    target_flow_uuid: str = Field(min_length=1)
    source_unit: str = Field(min_length=1)
    target_unit: str = Field(min_length=1)
    amount_factor: float = Field(gt=0, allow_inf_nan=False)
    mapping_level: Literal['L1', 'L2']
    mapping_status: Literal['auto', 'user_confirmed']
    mapping_rule_id: str = Field(min_length=1)
    mapping_package_id: str = Field(min_length=1)
    mapping_package_version: str = Field(min_length=1)
    mapping_package_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    database_release: str = Field(min_length=1)
    process_uuid: str = Field(min_length=1)
    expected_process_content_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    expected_vector_checksum: str = Field(pattern=r'^[0-9a-f]{64}$')
    claim_role: Literal['partial_background_leaf'] = 'partial_background_leaf'

    @model_validator(mode='after')
    def require_confirmation(self):
        if self.mapping_level == 'L2' and self.mapping_status != 'user_confirmed':
            raise ValueError('L2 mappings require explicit confirmation')
        return self


class ProviderNativeBackgroundClimateRequest(BaseModel):
    """One's copy of the engine's opt-in native background climate request.

    Mirrors `provider_schemas.ProviderNativeBackgroundClimateRequest` at the pinned source commit
    without adding constraints the engine does not impose, and is only ever filled from
    `resources/native_background_climate.json`.
    """

    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    schema_version: Literal['provider.native-background-climate-total.request.v1'] = (
        'provider.native-background-climate-total.request.v1'
    )
    database_release: Literal['ecoinvent_3.11']
    method_package_id: str = Field(min_length=1)
    method_package_version: str = Field(min_length=1)
    method_package_sha256: str = Field(pattern=SHA256)
    runtime_manifest_sha256: str = Field(pattern=SHA256)
    flow_snapshot_hash: str = Field(pattern=SHA256)
    reference_dependency_snapshot_hash: str = Field(pattern=SHA256)


class ProviderNativeBackgroundInventoryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal['provider.native-background-inventory.request.v1'] = 'provider.native-background-inventory.request.v1'
    database_release: Literal['ecoinvent_3.11']
    inventory_runtime_manifest_sha256: str = Field(pattern=SHA256)
    flow_snapshot_hash: str = Field(pattern=SHA256)
    reference_dependency_snapshot_hash: str = Field(pattern=SHA256)


class ProviderNativeClimateIndicator(BaseModel):
    method: Literal['EF v3.1']
    category: Literal['climate change']
    name: Literal['GWP100']
    unit: Literal['kg CO2-Eq']


class ProviderNativeClimateTerm(BaseModel):
    exchange_id: str
    process_uuid: str
    source_namespace: Literal['ecoinvent', 'tiangong_open_data']
    flow_uuid: str
    flow_version: str
    direction: Literal['input', 'output']
    compartment: str
    subcompartment: str | None = None
    amount: float
    amount_unit: str
    cf_presence: Literal['explicit_nonzero', 'explicit_zero', 'no_cf']
    cf_value: float | None = None
    cf_source: str
    cf_method: str
    cf_database_release: str
    method_package_sha256: str = Field(pattern=SHA256)
    contribution_value: float | None = None


class ProviderNativeClimateDomain(BaseModel):
    source_namespace: Literal['ecoinvent', 'tiangong_open_data']
    contribution_value: float
    indicator_unit: Literal['kg CO2-Eq']
    coverage: dict[str, int]
    negative_cf_exchange_count: int
    terms: list[ProviderNativeClimateTerm]


class ProviderNativeBackgroundClimateResponse(BaseModel):
    schema_version: Literal['provider.native-background-climate-total.response.v1']
    method_package_id: str
    method_package_version: str
    method_package_sha256: str = Field(pattern=SHA256)
    runtime_manifest_sha256: str = Field(pattern=SHA256)
    indicator: ProviderNativeClimateIndicator
    merge_status: Literal['merged', 'split_diagnostic']
    merge_blockers: list[dict[str, Any]]
    unified_climate_total: float | None = None
    domains: dict[str, ProviderNativeClimateDomain]
    provider_system_model_evidence: Literal['not_asserted_by_local_vector_metadata']
    carbon_storage_permanence: Literal['not_assessed']
    claim_limit: Literal['partial_background_leaf_only_not_complete_product_carbon_footprint']

    @model_validator(mode='after')
    def require_domain_and_total_consistency(self):
        if {'foreground', 'native_background'} - set(self.domains):
            raise ValueError('a native climate answer must report both the foreground and the native background domain')
        if self.merge_status == 'merged' and self.unified_climate_total is None:
            raise ValueError('a merged native climate answer must carry a unified total')
        if self.merge_status == 'split_diagnostic' and self.unified_climate_total is not None:
            raise ValueError('a split diagnostic must not carry a unified total')
        return self

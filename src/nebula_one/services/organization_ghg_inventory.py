from __future__ import annotations

from sqlalchemy import select

from ..analysis.dependency_gap import dependency_gap
from ..analysis.organization_ghg_inventory import (
    build_organization_ghg_inventory,
    validate_organization_ghg_inventory_method_package,
)
from ..analysis.organization_ghg_inventory_v1 import (
    build_organization_ghg_inventory_v1,
)
from ..analysis.organization_ghg_inventory_v1_visual import (
    render_organization_ghg_inventory_v1_svg,
)
from ..analysis.organization_ghg_inventory_visual import (
    render_organization_ghg_inventory_svg,
)
from ..database import Database
from ..errors import DomainError
from ..models import Application, SystemRevision
from ..runtime_models import SolvedSystemSnapshot, SystemBinding
from ..runtime_schemas import (
    CarbonManagementCreate,
    OrganizationGhgInventoryCreate,
    OrganizationGhgInventoryV1Create,
    ProductCarbonFootprintCreate,
)
from .carbon_management import CarbonManagementService
from .period_energy_total import PeriodEnergyTotalService
from .pcf import ProductCarbonFootprintService
from .province_electricity import ProvinceElectricityService
from .runtime_support import require_method_package


class OrganizationGhgInventoryService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.carbon_management = CarbonManagementService(database)
        self.province_electricity = ProvinceElectricityService(database)
        self.period_energy_totals = PeriodEnergyTotalService(database)
        self.product_carbon_footprints = ProductCarbonFootprintService(database)

    def aggregate(
        self, application_id: str, payload: OrganizationGhgInventoryV1Create
    ) -> dict:
        with self.database.session() as db:
            application = db.get(Application, application_id)
            if application is None:
                raise DomainError(
                    code="APPLICATION_NOT_FOUND",
                    message=f"application not found: {application_id}",
                    status_code=404,
                )
            bound_refs = set((application.context or {}).get("method_package_refs") or [])
            required_refs = {
                payload.method_package_ref,
                payload.pcf_method_package_ref,
            }
            if not required_refs.issubset(bound_refs):
                raise DomainError(
                    code="ORGANIZATION_GHG_METHOD_NOT_BOUND",
                    message="organization and PCF methods must be bound to this application",
                    status_code=409,
                    details={
                        "dependency_gap": dependency_gap(
                            code="ORGANIZATION_GHG_METHOD_NOT_BOUND",
                            kind="method_package_binding",
                            step="organization_ghg_inventory",
                            what_missing={
                                "unbound_refs": sorted(required_refs.difference(bound_refs)),
                                "required_identity": {"application_method_package_refs": sorted(required_refs)},
                                "observed_identity": {"bound_method_package_refs": sorted(bound_refs)},
                            },
                            affects={
                                "downstream_steps": [],
                                "scopes_affected": ["scope_1", "scope_2", "scope_3"],
                            },
                            how_to_resolve=[
                                {
                                    "action": "把清单方法包与 PCF 方法包写入该应用的 context.method_package_refs",
                                    "owner": "应用配置 / seed 自动加载",
                                    "precondition": "两个包已在注册表登记且哈希未漂移",
                                },
                            ],
                            evidence={"application_id": application_id},
                        ),
                    },
                )
            package = require_method_package(db, payload.method_package_ref)
            bindings = list(
                db.scalars(
                    select(SystemBinding).where(
                        SystemBinding.application_id == application_id,
                        SystemBinding.binding_id.in_(payload.binding_ids),
                    )
                )
            )
            by_id = {binding.binding_id: binding for binding in bindings}
            missing = sorted(set(payload.binding_ids).difference(by_id))
            if missing:
                raise DomainError(
                    code="ORGANIZATION_GHG_BINDING_NOT_FOUND",
                    message="one or more requested system bindings do not exist",
                    status_code=404,
                    details={"missing_binding_ids": missing},
                )
            sources = []
            for binding_id in payload.binding_ids:
                binding = by_id[binding_id]
                if binding.status != "active":
                    raise DomainError(
                        code="ORGANIZATION_GHG_BINDING_NOT_ACTIVE",
                        message="organization inventory requires active system bindings",
                        status_code=409,
                        details={"binding_id": binding_id},
                    )
                if "pcf.product.v1" not in binding.capabilities:
                    raise DomainError(
                        code="ORGANIZATION_GHG_BINDING_CAPABILITY_MISSING",
                        message="system binding does not declare pcf.product.v1",
                        status_code=422,
                        details={"binding_id": binding_id},
                    )
                revision = db.get(SystemRevision, binding.system_revision_id)
                snapshot = db.get(SolvedSystemSnapshot, binding.solved_snapshot_id)
                if (
                    revision is None
                    or revision.system_model_id != binding.system_model_id
                    or snapshot is None
                    or snapshot.application_id != application_id
                    or snapshot.system_revision_id != binding.system_revision_id
                ):
                    raise DomainError(
                        code="ORGANIZATION_GHG_BINDING_CHAIN_INVALID",
                        message="system binding model, revision and solved snapshot chain is invalid",
                        status_code=409,
                        details={"binding_id": binding_id},
                    )
                sources.append(
                    {
                        "binding": {
                            "binding_id": binding.binding_id,
                            "role": binding.role,
                            "system_model_id": binding.system_model_id,
                            "system_revision_id": binding.system_revision_id,
                            "solved_snapshot_id": binding.solved_snapshot_id,
                            "reporting_period_id": binding.reporting_period_id,
                            "organizational_boundary_id": binding.organizational_boundary_id,
                            "content_sha256": binding.content_sha256,
                        },
                        "snapshot_id": snapshot.id,
                    }
                )

        pcf_request = ProductCarbonFootprintCreate(
            method_package_ref=payload.pcf_method_package_ref
        )
        for source in sources:
            source["pcf"] = self.product_carbon_footprints.analyze(
                source.pop("snapshot_id"), pcf_request
            )
        return build_organization_ghg_inventory_v1(
            application_id=application_id,
            sources=sources,
            method_package_ref=payload.method_package_ref,
            method_package_sha256=package.content_sha256,
            method_package_kind=package.package_kind,
            manifest=package.manifest,
        )

    def analyze(
        self, application_id: str, payload: OrganizationGhgInventoryCreate
    ) -> dict:
        with self.database.session() as db:
            application = db.get(Application, application_id)
            if application is None:
                raise DomainError(
                    code="APPLICATION_NOT_FOUND",
                    message=f"application not found: {application_id}",
                    status_code=404,
                )
            bound_refs = set((application.context or {}).get("method_package_refs") or [])
            unbound_refs = sorted(
                {payload.method_package_ref, payload.carbon_method_package_ref}.difference(bound_refs)
            )
            if unbound_refs:
                raise DomainError(
                    code="GHG_INVENTORY_METHOD_NOT_BOUND",
                    message="organization GHG method is not bound to this application",
                    status_code=409,
                    details={
                        "dependency_gap": dependency_gap(
                            code="GHG_INVENTORY_METHOD_NOT_BOUND",
                            kind="method_package_binding",
                            step="organization_ghg_inventory",
                            what_missing={
                                "unbound_refs": unbound_refs,
                                "required_identity": {
                                    "application_method_package_refs": [
                                        payload.method_package_ref,
                                        payload.carbon_method_package_ref,
                                    ]
                                },
                                "observed_identity": {"bound_method_package_refs": sorted(bound_refs)},
                            },
                            affects={
                                "downstream_steps": [],
                                "scopes_affected": ["scope_1", "scope_2"],
                            },
                            how_to_resolve=[
                                {
                                    "action": "把清单方法包与直接贡献方法包写入该应用的 context.method_package_refs",
                                    "owner": "应用配置 / seed 自动加载",
                                    "precondition": "两个包已在注册表登记且哈希未漂移",
                                },
                            ],
                            evidence={"application_id": application_id},
                        ),
                    },
                )
            package = require_method_package(db, payload.method_package_ref)
            validate_organization_ghg_inventory_method_package(
                method_package_ref=payload.method_package_ref,
                method_package_kind=package.package_kind,
                manifest=package.manifest,
            )

        period_total = self.period_energy_totals.analyze(
            application_id, payload.province_electricity.period_energy_total
        )
        electricity = self.province_electricity.analyze(
            application_id, payload.province_electricity
        )
        activities = {
            item["period_id"]: item for item in period_total.get("activities") or []
        }
        scope_1_observations = []
        for observation in period_total.get("observations") or []:
            period_id = observation["period"]["id"]
            source = observation["source"]
            activity = activities.get(period_id)
            if activity is None:
                raise DomainError(
                    code="GHG_INVENTORY_SCOPE_1_PERIOD_SET_MISMATCH",
                    message="period total lacks production evidence for a Scope 1 period",
                    status_code=422,
                )
            snapshot_id = source["solved_snapshot_id"]
            with self.database.session() as db:
                snapshot = db.get(SolvedSystemSnapshot, snapshot_id)
                if snapshot is None or snapshot.application_id != application_id:
                    raise DomainError(
                        code="GHG_INVENTORY_SNAPSHOT_APPLICATION_MISMATCH",
                        message="a period solved snapshot is missing or belongs to another application",
                        status_code=409,
                    )
            carbon = self.carbon_management.analyze(
                snapshot_id,
                CarbonManagementCreate(
                    method_package_ref=payload.carbon_method_package_ref,
                    energy_carrier_result_id=source["energy_result_id"],
                ),
            )
            scope_1_observations.append(
                {
                    "period_id": period_id,
                    "carbon_management": carbon,
                    "activity": {
                        "scale_factor": activity["scale_factor"],
                        "source": source,
                        "production_evidence": {
                            "inventory_snapshot": activity["inventory_snapshot"],
                            "data_point": activity["data_point"],
                            "evidence": activity["evidence"],
                            "functional_output": activity["functional_output"],
                        },
                    },
                }
            )
        return build_organization_ghg_inventory(
            application_id=application_id,
            period_energy_total=period_total,
            scope_1_observations=scope_1_observations,
            province_electricity=electricity,
            scope_2_scenario_id=payload.scope_2_scenario_id,
            method_package_ref=payload.method_package_ref,
            method_package_sha256=package.content_sha256,
            method_package_kind=package.package_kind,
            manifest=package.manifest,
        )

    def chart_svg(
        self, application_id: str, payload: OrganizationGhgInventoryCreate
    ) -> str:
        return render_organization_ghg_inventory_svg(
            self.analyze(application_id, payload)
        )

    def aggregate_chart_svg(
        self, application_id: str, payload: OrganizationGhgInventoryV1Create
    ) -> str:
        return render_organization_ghg_inventory_v1_svg(
            self.aggregate(application_id, payload)
        )

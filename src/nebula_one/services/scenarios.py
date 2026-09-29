from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from ..database import Database
from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..runtime_models import (
    AnalysisPlan,
    BoundaryDefinition,
    Comparison,
    EntityModelBinding,
    InventorySnapshot,
    ParameterSet,
    Period,
    Scenario,
)
from ..runtime_schemas import AnalysisPlanCreate, ComparisonCreate, ScenarioCreate
from .analysis_runs import CAPABILITIES
from .runtime_support import (
    is_ancestor,
    require_application,
    require_method_package,
    require_revision,
)


class ScenarioService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self._capabilities = {item["key"] for item in CAPABILITIES}

    def create_scenario(
        self, application_id: str, payload: ScenarioCreate
    ) -> Scenario:
        with self.database.session() as db:
            require_application(db, application_id)
            base, base_model = require_revision(
                db, payload.base_revision_id, application_id
            )
            revision, revision_model = require_revision(
                db, payload.system_revision_id, application_id
            )
            if base_model.id != revision_model.id:
                raise DomainError(
                    code="SCENARIO_REVISION_MODEL_MISMATCH",
                    message="base and selected revisions must belong to the same system model",
                    status_code=409,
                )
            if not is_ancestor(db, base.id, revision):
                raise DomainError(
                    code="SCENARIO_BASE_NOT_ANCESTOR",
                    message="base revision must be an ancestor of the selected system revision",
                    status_code=409,
                )
            if payload.inventory_snapshot_id:
                inventory = db.get(InventorySnapshot, payload.inventory_snapshot_id)
                if inventory is None:
                    raise DomainError(
                        code="INVENTORY_SNAPSHOT_NOT_FOUND",
                        message=f"inventory snapshot not found: {payload.inventory_snapshot_id}",
                        status_code=404,
                    )
                if inventory.application_id != application_id:
                    raise DomainError(
                        code="INVENTORY_APPLICATION_MISMATCH",
                        message="inventory snapshot does not belong to the requested application",
                        status_code=409,
                    )
                inventory_revision, inventory_model = require_revision(
                    db, inventory.system_revision_id, application_id
                )
                if inventory_model.id != revision_model.id or not is_ancestor(
                    db, inventory_revision.id, revision
                ):
                    raise DomainError(
                        code="SCENARIO_INVENTORY_REVISION_MISMATCH",
                        message="inventory snapshot must bind to the same model and an ancestor revision",
                        status_code=409,
                    )
            if payload.parameter_set_id:
                parameter_set = db.get(ParameterSet, payload.parameter_set_id)
                if parameter_set is None:
                    raise DomainError(
                        code="PARAMETER_SET_NOT_FOUND",
                        message=f"parameter set not found: {payload.parameter_set_id}",
                        status_code=404,
                    )
                if parameter_set.application_id != application_id:
                    raise DomainError(
                        code="PARAMETER_SET_APPLICATION_MISMATCH",
                        message="parameter set does not belong to the requested application",
                        status_code=409,
                    )
            for reference in payload.method_package_refs:
                require_method_package(db, reference)
            record = Scenario(application_id=application_id, **payload.model_dump())
            db.add(record)
            db.commit()
            db.refresh(record)
            return record

    def list_scenarios(self, application_id: str) -> list[Scenario]:
        with self.database.session() as db:
            require_application(db, application_id)
            return list(
                db.scalars(
                    select(Scenario)
                    .where(Scenario.application_id == application_id)
                    .order_by(Scenario.created_at)
                )
            )

    def freeze_scenario(self, scenario_id: str) -> Scenario:
        with self.database.session() as db:
            scenario = db.get(Scenario, scenario_id)
            if scenario is None:
                raise DomainError(
                    code="SCENARIO_NOT_FOUND",
                    message=f"scenario not found: {scenario_id}",
                    status_code=404,
                )
            if scenario.status == "frozen":
                return scenario
            revision, system_model = require_revision(
                db, scenario.system_revision_id, scenario.application_id
            )
            inventory_hash = None
            if scenario.inventory_snapshot_id:
                inventory = db.get(InventorySnapshot, scenario.inventory_snapshot_id)
                assert inventory is not None
                if inventory.status != "frozen":
                    raise DomainError(
                        code="INVENTORY_SNAPSHOT_NOT_FROZEN",
                        message="scenario requires a frozen inventory snapshot",
                        status_code=409,
                    )
                inventory_hash = inventory.content_sha256
            parameter_hash = None
            if scenario.parameter_set_id:
                parameter_set = db.get(ParameterSet, scenario.parameter_set_id)
                assert parameter_set is not None
                if parameter_set.status != "frozen":
                    raise DomainError(
                        code="PARAMETER_SET_NOT_FROZEN",
                        message="scenario requires a frozen parameter set",
                        status_code=409,
                    )
                parameter_hash = parameter_set.content_sha256
            packages = [
                require_method_package(db, reference)
                for reference in scenario.method_package_refs
            ]
            content = {
                "base_revision_id": scenario.base_revision_id,
                "system_revision_id": scenario.system_revision_id,
                "system_revision_content_sha256": revision.content_sha256,
                "inventory_snapshot_id": scenario.inventory_snapshot_id,
                "inventory_snapshot_hash": inventory_hash,
                "parameter_set_id": scenario.parameter_set_id,
                "parameter_set_hash": parameter_hash,
                "method_packages": [
                    {
                        "reference": reference,
                        "content_sha256": package.content_sha256,
                    }
                    for reference, package in zip(
                        scenario.method_package_refs, packages, strict=True
                    )
                ],
                "model_pin": {
                    "provider": system_model.provider,
                    "project_id": system_model.upstream_project_id,
                    "version": system_model.upstream_version,
                    "base_graph_sha256": system_model.graph_sha256,
                },
                "assumptions": scenario.assumptions,
            }
            scenario.content_sha256 = canonical_json_sha256(content)
            scenario.status = "frozen"
            scenario.frozen_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(scenario)
            return scenario

    def create_plan(
        self, application_id: str, payload: AnalysisPlanCreate
    ) -> AnalysisPlan:
        unknown = sorted(set(payload.capability_keys).difference(self._capabilities))
        if unknown:
            raise DomainError(
                code="ANALYSIS_PLAN_CAPABILITY_UNKNOWN",
                message="analysis plan contains unregistered capabilities",
                status_code=422,
                details={"unknown_capabilities": unknown},
            )
        with self.database.session() as db:
            require_application(db, application_id)
            scenario = db.get(Scenario, payload.scenario_id)
            if scenario is None:
                raise DomainError(
                    code="SCENARIO_NOT_FOUND",
                    message=f"scenario not found: {payload.scenario_id}",
                    status_code=404,
                )
            if scenario.application_id != application_id:
                raise DomainError(
                    code="SCENARIO_APPLICATION_MISMATCH",
                    message="scenario does not belong to the requested application",
                    status_code=409,
                )
            record = AnalysisPlan(application_id=application_id, **payload.model_dump())
            db.add(record)
            db.commit()
            db.refresh(record)
            return record

    def list_plans(self, application_id: str) -> list[AnalysisPlan]:
        with self.database.session() as db:
            require_application(db, application_id)
            return list(
                db.scalars(
                    select(AnalysisPlan)
                    .where(AnalysisPlan.application_id == application_id)
                    .order_by(AnalysisPlan.created_at)
                )
            )

    def freeze_plan(self, plan_id: str) -> AnalysisPlan:
        with self.database.session() as db:
            plan = db.get(AnalysisPlan, plan_id)
            if plan is None:
                raise DomainError(
                    code="ANALYSIS_PLAN_NOT_FOUND",
                    message=f"analysis plan not found: {plan_id}",
                    status_code=404,
                )
            if plan.status == "frozen":
                return plan
            scenario = db.get(Scenario, plan.scenario_id)
            assert scenario is not None
            if scenario.status != "frozen":
                raise DomainError(
                    code="SCENARIO_NOT_FROZEN",
                    message="analysis plan requires a frozen scenario",
                    status_code=409,
                )
            plan.content_sha256 = canonical_json_sha256(
                {
                    "scenario_id": scenario.id,
                    "scenario_hash": scenario.content_sha256,
                    "capability_keys": plan.capability_keys,
                    "configuration": plan.configuration,
                }
            )
            plan.status = "frozen"
            plan.frozen_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(plan)
            return plan

    def create_comparison(
        self, application_id: str, payload: ComparisonCreate
    ) -> Comparison:
        with self.database.session() as db:
            require_application(db, application_id)
            scenarios: list[Scenario] = []
            signatures: list[dict] = []
            for scenario_id in payload.scenario_ids:
                scenario = db.get(Scenario, scenario_id)
                if scenario is None:
                    raise DomainError(
                        code="SCENARIO_NOT_FOUND",
                        message=f"scenario not found: {scenario_id}",
                        status_code=404,
                    )
                if scenario.application_id != application_id:
                    raise DomainError(
                        code="SCENARIO_APPLICATION_MISMATCH",
                        message="scenario does not belong to the requested application",
                        status_code=409,
                    )
                if scenario.status != "frozen":
                    raise DomainError(
                        code="SCENARIO_NOT_FROZEN",
                        message="comparison requires frozen scenarios",
                        status_code=409,
                        details={"scenario_id": scenario.id},
                    )
                scenarios.append(scenario)
                signatures.append(self._comparison_signature(db, scenario))

            dimensions = (
                "functional_unit",
                "boundary_hash",
                "period",
                "geography",
                "model_pin",
                "method_package_refs",
                "consolidation_policy",
                "allocation_rule_refs",
            )
            checks: dict[str, dict] = {}
            for dimension in dimensions:
                values = [signature[dimension] for signature in signatures]
                value_hashes = [canonical_json_sha256(value) for value in values]
                checks[dimension] = {
                    "compatible": len(set(value_hashes)) == 1,
                    "values": {
                        scenario.id: value
                        for scenario, value in zip(scenarios, values, strict=True)
                    },
                }
            incompatible = [
                dimension
                for dimension, check in checks.items()
                if not check["compatible"]
            ]
            comparability = {
                "compatible": not incompatible,
                "incompatible_dimensions": incompatible,
                "checks": checks,
                "informational_differences": {
                    "parameter_set_ids": {
                        scenario.id: scenario.parameter_set_id for scenario in scenarios
                    },
                    "system_revision_ids": {
                        scenario.id: scenario.system_revision_id for scenario in scenarios
                    },
                },
            }
            content = {
                "scenario_hashes": {
                    scenario.id: scenario.content_sha256 for scenario in scenarios
                },
                "comparability": comparability,
            }
            record = Comparison(
                application_id=application_id,
                name=payload.name,
                scenario_ids=payload.scenario_ids,
                comparability=comparability,
                content_sha256=canonical_json_sha256(content),
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record

    def list_comparisons(self, application_id: str) -> list[Comparison]:
        with self.database.session() as db:
            require_application(db, application_id)
            return list(
                db.scalars(
                    select(Comparison)
                    .where(Comparison.application_id == application_id)
                    .order_by(Comparison.created_at)
                )
            )

    @staticmethod
    def _comparison_signature(db, scenario: Scenario) -> dict:
        revision, system_model = require_revision(
            db, scenario.system_revision_id, scenario.application_id
        )
        inventory = (
            db.get(InventorySnapshot, scenario.inventory_snapshot_id)
            if scenario.inventory_snapshot_id
            else None
        )
        boundary = (
            db.get(BoundaryDefinition, inventory.boundary_id) if inventory else None
        )
        period = db.get(Period, inventory.period_id) if inventory else None
        allocation_rule_refs: list[str] = []
        if boundary and boundary.included_entity_ids:
            bindings = list(
                db.scalars(
                    select(EntityModelBinding).where(
                        EntityModelBinding.entity_id.in_(boundary.included_entity_ids)
                    )
                )
            )
            for binding in bindings:
                binding_revision, binding_model = require_revision(
                    db, binding.system_revision_id, scenario.application_id
                )
                if (
                    binding_model.id == system_model.id
                    and is_ancestor(db, binding_revision.id, revision)
                    and (binding.period_id is None or binding.period_id == inventory.period_id)
                    and binding.allocation_rule_ref
                ):
                    allocation_rule_refs.append(binding.allocation_rule_ref)
        return {
            "functional_unit": revision.graph_snapshot.get(
                "functionalUnit", revision.graph_snapshot.get("functional_unit")
            ),
            "boundary_hash": boundary.content_sha256 if boundary else None,
            "period": (
                {
                    "start_date": period.start_date.isoformat(),
                    "end_date": period.end_date.isoformat(),
                    "resolution": period.resolution,
                }
                if period
                else None
            ),
            "geography": boundary.geographic_scope if boundary else None,
            "model_pin": {
                "provider": system_model.provider,
                "project_id": system_model.upstream_project_id,
                "version": system_model.upstream_version,
                "source_policy": system_model.upstream_receipt.get("source_policy"),
                "allowed_lcia_scope": system_model.upstream_receipt.get(
                    "allowed_lcia_scope"
                ),
            },
            "method_package_refs": sorted(scenario.method_package_refs),
            "consolidation_policy": boundary.consolidation_policy if boundary else None,
            "allocation_rule_refs": sorted(set(allocation_rule_refs)),
        }

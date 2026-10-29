from __future__ import annotations

from ..analysis.pcf import build_product_pcf
from ..analysis.native_product_pcf import build_native_product_pcf
from ..analysis.pcf_visual import render_product_pcf_svg
from ..analysis.result_basis import project_result_basis
from ..database import Database
from ..errors import DomainError
from ..models import AnalysisRun, Application
from ..runtime_models import SolvedSystemSnapshot
from ..runtime_schemas import ProductCarbonFootprintCreate
from ..exports.pcf import build_pcf_html, build_pcf_xlsx
from .runtime_support import require_method_package
from .native_climate import NativeClimateArtifactService
from .climate_method_selection import method_resolution, resolve_frozen_pcf_method


class ProductCarbonFootprintService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def default_method(self, solved_snapshot_id: str) -> dict:
        with self.database.session() as db:
            snapshot = db.get(SolvedSystemSnapshot, solved_snapshot_id)
            if snapshot is None:
                raise DomainError(code="SOLVED_SYSTEM_SNAPSHOT_NOT_FOUND",
                                  message=f"solved system snapshot not found: {solved_snapshot_id}",
                                  status_code=404)
            application = db.get(Application, snapshot.application_id)
            bound = list((application.context or {}).get("method_package_refs") or []) if application else []
            return method_resolution(resolve_frozen_pcf_method(db, snapshot, bound))

    def analyze(
        self, solved_snapshot_id: str, payload: ProductCarbonFootprintCreate
    ) -> dict:
        with self.database.session() as db:
            snapshot = db.get(SolvedSystemSnapshot, solved_snapshot_id)
            if snapshot is None:
                raise DomainError(
                    code="SOLVED_SYSTEM_SNAPSHOT_NOT_FOUND",
                    message=f"solved system snapshot not found: {solved_snapshot_id}",
                    status_code=404,
                )
            if snapshot.provider != "nebula_lca":
                raise DomainError(
                    code="PCF_PROVIDER_UNSUPPORTED",
                    message="pcf.product.v1 currently requires a Nebula LCA snapshot",
                    status_code=422,
                    details={"provider": snapshot.provider},
                )
            package = require_method_package(db, payload.method_package_ref)
            analysis_run_id = str(
                (snapshot.provider_receipt or {}).get("analysis_run_id") or ""
            ).strip()
            run = db.get(AnalysisRun, analysis_run_id) if analysis_run_id else None
            if (
                run is None
                or run.capability_key != "solve.nebula.v1"
                or run.status != "succeeded"
            ):
                raise DomainError(
                    code="PCF_SOURCE_SOLVE_RUN_REQUIRED",
                    message="PCF requires the exact provider solve run behind the snapshot",
                    status_code=422,
                )
            if run.system_revision_id != snapshot.system_revision_id:
                raise DomainError(
                    code="PCF_SOURCE_REVISION_MISMATCH",
                    message="PCF snapshot and provider solve run bind different revisions",
                    status_code=409,
                )
            formula = package.manifest.get("formula_graph") or {}
            if formula.get("source_contract") == "provider.native-background-climate-total.response.v1":
                if package.package_kind != "product_carbon_footprint":
                    raise DomainError(code="PCF_METHOD_PACKAGE_KIND_MISMATCH", message="native product method must be a product_carbon_footprint package", status_code=422)
                _, _, answer, request = NativeClimateArtifactService(self.database)._frozen_answer(snapshot.id)
                return project_result_basis(
                    build_native_product_pcf(
                        snapshot_id=snapshot.id, snapshot_hash=snapshot.content_sha256,
                        revision_id=snapshot.system_revision_id, graph_hash=run.model_graph_sha256,
                        source_parameters=run.parameters, provider_receipt=snapshot.provider_receipt,
                        request=request, answer=answer, method_ref=payload.method_package_ref,
                        method_hash=package.content_sha256, manifest=package.manifest,
                    ),
                    basis=payload.result_basis, base_amount=payload.base_amount,
                    base_unit=payload.base_unit,
                    producing_outputs=snapshot.scaled_technosphere_exchanges)
            return project_result_basis(
                build_product_pcf(
                    solved_snapshot_id=snapshot.id,
                    solved_snapshot_sha256=snapshot.content_sha256,
                    lcia_results=snapshot.lcia_results,
                    provider_receipt=snapshot.provider_receipt,
                    source_run_parameters=run.parameters,
                    system_revision_id=snapshot.system_revision_id,
                    model_graph_sha256=run.model_graph_sha256,
                    scaled_elementary_exchanges=snapshot.scaled_elementary_exchanges,
                    method_package_ref=payload.method_package_ref,
                    method_package_sha256=package.content_sha256,
                    method_package_kind=package.package_kind,
                    manifest=package.manifest,
                ),
                basis=payload.result_basis, base_amount=payload.base_amount,
                base_unit=payload.base_unit,
                producing_outputs=snapshot.scaled_technosphere_exchanges)

    def export_xlsx(
        self, solved_snapshot_id: str, payload: ProductCarbonFootprintCreate
    ) -> tuple[bytes, dict]:
        result = self.analyze(solved_snapshot_id, payload)
        return build_pcf_xlsx(result), result

    def report_html(
        self, solved_snapshot_id: str, payload: ProductCarbonFootprintCreate
    ) -> tuple[str, dict]:
        result = self.analyze(solved_snapshot_id, payload)
        return build_pcf_html(result, render_product_pcf_svg(result)), result

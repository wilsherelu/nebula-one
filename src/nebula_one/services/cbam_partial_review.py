"""Recheck a frozen direct CBAM term against separately required steel components."""
from __future__ import annotations

from ..analysis.cbam_partial_review import build_cbam_partial_review
from ..database import Database
from ..errors import DomainError
from ..models import Application
from ..models import SystemRevision
from ..hashing import canonical_json_sha256
from ..runtime_models import SolvedSystemSnapshot
from ..runtime_schemas import CbamPartialReviewCreate, CbamTrialCreate
from .cbam_trial import CbamTrialService
from .official_product_method import official_template_profile
from .runtime_support import require_method_package
from .returned_cbam_binding import _identity_graph


class CbamPartialReviewService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.direct = CbamTrialService(database)

    def analyze(self, snapshot_id: str, payload: CbamPartialReviewCreate) -> dict:
        with self.database.session() as db:
            snapshot = db.get(SolvedSystemSnapshot, snapshot_id)
            if snapshot is None:
                raise DomainError(code="CBAM_PARTIAL_SNAPSHOT_NOT_FOUND", message="solved snapshot not found", status_code=404)
            application = db.get(Application, snapshot.application_id)
            if application is None or payload.method_package_ref not in ((application.context or {}).get("method_package_refs") or []):
                raise DomainError(code="CBAM_PARTIAL_METHOD_NOT_BOUND", message="partial method is not bound to the application", status_code=409)
            package = require_method_package(db, payload.method_package_ref)
            if package.package_kind != "cbam_partial_review":
                raise DomainError(code="CBAM_PARTIAL_METHOD_KIND_INVALID", message="method has another package kind", status_code=422)
            manifest = package.manifest
            profile = official_template_profile(application.context)
            if manifest.get("template_profile") != profile:
                raise DomainError(code="CBAM_PARTIAL_TEMPLATE_MISMATCH", message="partial method belongs to another template", status_code=409)
            reviewed_graph = manifest.get("reviewed_graph_identity_sha256")
            if reviewed_graph is not None:
                revision = db.get(SystemRevision, snapshot.system_revision_id)
                if revision is None or canonical_json_sha256(_identity_graph(revision.graph_snapshot)) != reviewed_graph:
                    raise DomainError(code="CBAM_PARTIAL_REVIEWED_GRAPH_MISMATCH", message="partial method belongs to another reviewed graph", status_code=409)
            source = (manifest.get("formula_graph") or {}).get("source_direct_method") or {}
            snapshot_data = {"id": snapshot.id, "content_sha256": snapshot.content_sha256,
                             "system_revision_id": snapshot.system_revision_id,
                             "scaled_technosphere_exchanges": snapshot.scaled_technosphere_exchanges,
                             "scaled_elementary_exchanges": snapshot.scaled_elementary_exchanges,
                             "provider_receipt": snapshot.provider_receipt}
            package_hash = package.content_sha256
            factor_package = None
            if payload.eligible_electricity_factor_ref:
                factor_package = require_method_package(db, payload.eligible_electricity_factor_ref)
                if factor_package.package_kind != "cbam_electricity_factor" or factor_package.jurisdiction != "EU":
                    raise DomainError(code="CBAM_ELECTRICITY_FACTOR_KIND_INVALID", message="factor must be a registered EU CBAM electricity package", status_code=422)
                factor_package = {"reference": payload.eligible_electricity_factor_ref,
                                  "content_sha256": factor_package.content_sha256,
                                  "valid_from": factor_package.valid_from.isoformat() if factor_package.valid_from else None,
                                  "valid_to": factor_package.valid_to.isoformat() if factor_package.valid_to else None,
                                  "manifest": factor_package.manifest}
        direct = self.direct.analyze(snapshot_id, CbamTrialCreate(
            method_package_ref=source.get("reference"),
            reporting_period_id=payload.reporting_period_id,
            boundary_definition_id=payload.boundary_definition_id,
        ))
        return build_cbam_partial_review(snapshot=snapshot_data, direct=direct,
                                         method_ref=payload.method_package_ref,
                                         method_hash=package_hash, manifest=manifest,
                                         factor_package=factor_package,
                                         condition_declarations=payload.condition_declarations)

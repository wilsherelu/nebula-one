"""Bind report data to exact persisted inputs and existing deterministic answers."""
from ..analysis.frozen_report import cbam_report, organization_report
from ..errors import DomainError
from ..models import SystemRevision
from ..runtime_models import SolvedSystemSnapshot
from ..runtime_schemas import SolvedSystemSnapshotOut
from .mfa_display_graph import MFADisplayGraph
from .runtime_support import require_method_package
from ..organization_lifecycle_display import organization_lifecycle_display
from .project_workspace import ProjectWorkspaceService


class FrozenReportService:
    def __init__(self, container):
        self.c = container

    def _source(self, snapshot_id, result, kind, lang):
        with self.c.database.session() as db:
            stored = db.get(SolvedSystemSnapshot, snapshot_id)
            if stored is None:
                raise DomainError(code="REPORT_SOURCE_NOT_FOUND", message="Frozen report source not found", status_code=404)
            snapshot = SolvedSystemSnapshotOut.model_validate(stored, from_attributes=True).model_dump(mode="json")
            revision = db.get(SystemRevision, stored.system_revision_id)
            graph = revision.graph_snapshot
            method_source = result["method_package"]
            method_ref = method_source.get("reference") or method_source["ref"]
            method = require_method_package(db, method_ref)
            if method.content_sha256 != method_source["content_sha256"]:
                raise DomainError(code="REPORT_METHOD_HASH_MISMATCH", message="Report method identity differs from the frozen answer", status_code=409)
            method_name = method.manifest.get("name") or method.manifest.get("title") or method.manifest.get("display_name")
            if isinstance(method_name, dict):
                method_name = method_name.get(lang)
        workspace = ProjectWorkspaceService(self.c).read(snapshot["application_id"], snapshot["system_revision_id"], lang)
        graph, names, issues = MFADisplayGraph(self.c.client).enrich(graph, snapshot["provider_receipt"].get("project_background_process_receipts") or [])
        return snapshot, graph, workspace, {"schema_version": "nebula_one.frozen-report.v1", "kind": kind,
            "language": lang,
            "title": "CBAM 试算报告" if kind == "cbam" else "组织生产模型碳核算报告",
            "snapshot_id": snapshot_id, "revision_id": snapshot["system_revision_id"],
            "method_name": method_name, "method_version": method_ref.rsplit("@", 1)[-1],
            "basis": result.get("activity_basis") or result.get("activity_level"),
            "reporting_period": result.get("reporting_period"),
            "inputs": workspace["fields"], "demand": snapshot["provider_receipt"].get("calculation_basis", {}).get("demand") or workspace["demand"],
            "sources": {"result": result, "workspace_identity": workspace.get("frozen_identity"),
                        "frozen_snapshot": snapshot,
                        "snapshot_hash": snapshot["content_sha256"], "provider_receipt": snapshot["provider_receipt"],
                        "display_name_sources": names, "display_name_issues": issues}}

    def cbam(self, snapshot_id, payload, lang="zh"):
        result = self.c.cbam_trials.analyze(snapshot_id, payload)
        if result["schema_version"] != "nebula_one.cbam.trial.v2":
            raise DomainError(code="CBAM_TRIAL_REPORT_SCHEMA_UNSUPPORTED", message="Complete report requires a frozen CBAM v2 boundary", status_code=422)
        _, graph, workspace, report = self._source(snapshot_id, result, "cbam", lang)
        report.update(cbam_report(result, graph, workspace))
        return report

    def organization(self, application_id, record_id, lang="zh"):
        record = self.c.organization_lifecycle.get(application_id, record_id)
        snapshot, graph, workspace, report = self._source(record["solved_snapshot_id"], record["result"], "organization", lang)
        report.update(organization_report(record["result"], snapshot, graph, workspace))
        if lang == "en":
            with self.c.database.session() as db:
                labels = organization_lifecycle_display(require_method_package(db, record["result"]["method_package"]["reference"]), lang)["labels"]
            report["status_labels"] = labels["group_status"]
            for key in ("gaps", "outside_boundary"):
                for row in report[key]:
                    category = row.get("identity", {}).get("category")
                    if category in labels["categories"]:
                        row["name"] = labels["categories"][category]
        report["record_id"] = record_id
        return report

"""Install a standard LCA seed into an engine through its public import API."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..adapters.nebula_lca import NebulaLCAClient, same_pinned_model
from ..database import Database
from ..errors import DomainError
from ..hashing import canonical_graph_sha256, canonical_json_sha256
from ..models import Application, SeedInstallation, SystemModel, SystemRevision
from ..runtime_models import BoundaryDefinition
from ..schemas import SystemModelCreate
from ..seeds import standard_seed_bundle
from .system_models import SystemModelService

STAGES = ("validated", "staged", "imported", "verified", "bound", "ready")

# the one boundary application whose ledger becomes a frozen BoundaryDefinition row
CBAM_BOUNDARY_APPLICATION = "cbam_trial"
MULTI_PROCESS_BOUNDARY_SCHEMA = "nebula_one.cbam.multi-process-boundary.v1"
DENOMINATOR_DISPOSITION = "reference_product_output_is_the_denominator"

# the engine fills these itself, so a seed row and a catalog row are not comparable on them
ENGINE_OWNED_COLUMNS = frozenset(
    {"allocation_properties", "source_updated_at", "flow_name", "flow_uuid"}
)

# the fields a pinned biosphere identity claims, re-checked against the provider resolver
ELEMENTARY_IDENTITY_FIELDS = (
    "source_namespace",
    "flow_uuid",
    "version",
    "flow_property_uuid",
    "flow_property_version",
    "unit_group_uuid",
    "unit_group_version",
    "unit",
    "direction",
    "compartment",
)

# provenance of the dataset version the resolver read, kept in the receipt for later replay
ELEMENTARY_PROVENANCE_FIELDS = (
    "content_hash",
    "content_hash_scope",
    "database_release",
    "flow_type",
    "name_en",
    "source_updated_at",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stage_index(status: str) -> int:
    return STAGES.index(status) if status in STAGES else -1


def _field(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return None


def _port_collection(node: dict[str, Any]) -> list[dict[str, Any]]:
    ports: list[dict[str, Any]] = []
    for group, direction in (("inputs", "input"), ("outputs", "output"), ("emissions", "output")):
        for port in node.get(group) or []:
            if isinstance(port, dict):
                enriched = dict(port)
                enriched["_group"] = group
                enriched.setdefault("direction", direction)
                ports.append(enriched)
    return ports


def _decimal_text(value: Any) -> str:
    if value is None:
        return ""
    return format(float(value), ".12g")


def _port_amount(port: dict[str, Any]) -> str:
    return (
        f'{_field(port, "flowUuid", "flow_uuid")}'
        f'::{_decimal_text(_field(port, "amount", "quantity"))}'
    )


class SeedInstallationService:
    """Drive one seed version from authored files to a bound, replayable engine object."""

    def __init__(
        self,
        database: Database,
        client: NebulaLCAClient,
        system_models: SystemModelService,
    ) -> None:
        self.database = database
        self.client = client
        self.system_models = system_models

    # ---------- validate only ----------

    def plan(self, seed_dir: Path) -> dict[str, Any]:
        build = self._run_build_gates(seed_dir)
        report = build.build()
        return {
            "schema_version": "nebula.seed-install.plan.v1",
            "seed_id": build.seed_id,
            "seed_version": build.version,
            "claim_level": build.manifest["claim_level"],
            "bundle_content_sha256": report["bundle_content_sha256"],
            "zip_path": report["zip_path"],
            "zip_sha256": report["zip_sha256"],
            "engine_project_id": build.identity["project_id"],
            "engine_model_version": build.version_row()["version"],
            "catalog_rows_added": [
                {
                    "flow_uuid": row["flow_uuid"],
                    "flow_name_en": row["flow_name_en"],
                    "default_unit": row["default_unit"],
                    "unit_group": row["unit_group"],
                }
                for row in build.owned_flows["rows"]
            ],
            "external_dependencies": [
                {
                    "role": row["role"],
                    "flow_uuid": row["flow_uuid"],
                    "declared": row["observed"],
                }
                for row in build.flow_dependencies["dependencies"]
                if row["disposition"] == "verify_present"
            ],
            "unit_groups": [
                {"name": group["name"], "declared": group["observed"]}
                for group in build.flow_dependencies["unit_groups"]
            ],
            "boundary_keys": dict(build.manifest["applications"]),
            "known_gaps": build.manifest["known_gaps"],
            "engine_calls": [],
        }

    def _run_build_gates(self, seed_dir: Path) -> standard_seed_bundle.SeedBuild:
        try:
            build = standard_seed_bundle.SeedBuild(seed_dir)
            build.validate()
        except standard_seed_bundle.BuildError as exc:
            raise DomainError(
                code="SEED_BUILD_REFUSED",
                message=f"the seed refused to build: {exc}",
                status_code=422,
                details={"seed_dir": standard_seed_bundle.relative_to_repo(seed_dir)},
            ) from exc
        return build

    # ---------- install ----------

    def find_installation(
        self, seed_id: str, seed_version: str
    ) -> SeedInstallation | None:
        """Whether a row for this seed version was already here, so a caller can tell a
        replay from a first run without reading the engine."""
        with self.database.session() as db:
            return db.scalar(
                select(SeedInstallation).where(
                    SeedInstallation.seed_id == seed_id,
                    SeedInstallation.seed_version == seed_version,
                )
            )

    def install(
        self,
        seed_dir: Path,
        *,
        application_id: str | None = None,
        boundary_key: str | None = None,
        declarations: dict[str, str] | None = None,
    ) -> SeedInstallation:
        build = self._run_build_gates(seed_dir)
        report = build.build()
        engine = self.client.engine_identity()
        engine_db_digest = _sha256_text(engine["database"])
        install_key = canonical_json_sha256(
            {
                "engine_db_digest": engine_db_digest,
                "openapi_version": engine["openapi_version"],
                "seed_id": build.seed_id,
                "seed_version": build.version,
                "bundle_content_sha256": report["bundle_content_sha256"],
            }
        )
        row = self._open_installation(build, report, engine, engine_db_digest, install_key)
        attempted = "validated"
        try:
            if _stage_index(row.status) < _stage_index("staged"):
                attempted = "staged"
                row = self._stage(row, report)
            if _stage_index(row.status) < _stage_index("imported"):
                attempted = "imported"
                row = self._import_bundle(row, build, report)
            attempted = "verified"
            row = self._verify(row, build, report)
            if application_id is not None:
                attempted = "bound"
                row = self._bind(
                    row,
                    build,
                    report,
                    application_id,
                    boundary_key,
                    declarations or {},
                )
        except DomainError as error:
            self._fail(row, error, attempted)
            raise
        return row

    def _open_installation(
        self,
        build: standard_seed_bundle.SeedBuild,
        report: dict[str, Any],
        engine: dict[str, str],
        engine_db_digest: str,
        install_key: str,
    ) -> SeedInstallation:
        with self.database.session() as db:
            decided = self._replay_or_conflict(
                db, install_key, build, report, engine, engine_db_digest
            )
            if decided is not None:
                return decided
            record = SeedInstallation(
                seed_id=build.seed_id,
                seed_version=build.version,
                install_key=install_key,
                bundle_content_sha256=report["bundle_content_sha256"],
                engine_base_url=self.client.base_url,
                engine_db_digest=engine_db_digest,
                engine_openapi_version=engine["openapi_version"],
                status="validated",
                stage_receipts={
                    "validated": {
                        "at": _now(),
                        "ok": True,
                        "engine_database": engine["database"],
                        "gates": "nebula_one.seeds.standard_seed_bundle",
                    }
                },
                engine_project_id=build.identity["project_id"],
                engine_model_version=build.version_row()["version"],
            )
            db.add(record)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                decided = self._replay_or_conflict(
                    db, install_key, build, report, engine, engine_db_digest
                )
                if decided is not None:
                    return decided
                raise
            db.refresh(record)
            return record

    def _replay_or_conflict(
        self,
        db: Session,
        install_key: str,
        build: standard_seed_bundle.SeedBuild,
        report: dict[str, Any],
        engine: dict[str, str],
        engine_db_digest: str,
    ) -> SeedInstallation | None:
        existing = db.scalar(
            select(SeedInstallation).where(
                SeedInstallation.install_key == install_key
            )
        )
        if existing is not None:
            return self._mark_replayed(existing, engine["openapi_version"])
        clash = db.scalar(
            select(SeedInstallation).where(
                SeedInstallation.seed_id == build.seed_id,
                SeedInstallation.seed_version == build.version,
                SeedInstallation.engine_db_digest == engine_db_digest,
            )
        )
        if clash is None:
            return None
        if clash.bundle_content_sha256 == report["bundle_content_sha256"]:
            # the engine's declared API version moved, the seed content did not
            return self._mark_replayed(clash, engine["openapi_version"])
        raise self._content_conflict(clash, report)

    def _content_conflict(
        self, clash: SeedInstallation, report: dict[str, Any]
    ) -> DomainError:
        return DomainError(
            code="SEED_VERSION_CONTENT_CONFLICT",
            message=(
                "this engine database already holds a different bundle for the same "
                "seed id and version"
            ),
            status_code=409,
            details={
                "installation_id": clash.id,
                "installed_bundle_content_sha256": clash.bundle_content_sha256,
                "refused_bundle_content_sha256": report["bundle_content_sha256"],
                "status": clash.status,
                "rule": "bump the seed version instead of replacing bytes under a shipped version",
            },
        )

    def _mark_replayed(
        self, row: SeedInstallation, observed_openapi_version: str | None = None
    ) -> SeedInstallation:
        def change(target: SeedInstallation) -> None:
            receipt: dict[str, Any] = {
                "at": _now(),
                "ok": True,
                "from_status": row.status,
                "install_key": row.install_key,
            }
            observed = observed_openapi_version or row.engine_openapi_version
            if observed != row.engine_openapi_version:
                receipt["installed_openapi_version"] = row.engine_openapi_version
                receipt["observed_openapi_version"] = observed
            target.stage_receipts = {
                **dict(target.stage_receipts),
                "replayed": receipt,
            }

        return self._mutate(row.id, change)

    def _mutate(
        self, installation_id: str, change: Callable[[SeedInstallation], None]
    ) -> SeedInstallation:
        with self.database.session() as db:
            target = db.get(SeedInstallation, installation_id)
            if target is None:
                raise DomainError(
                    code="SEED_INSTALLATION_LOST",
                    message=f"seed installation row disappeared: {installation_id}",
                    status_code=409,
                )
            change(target)
            db.commit()
            db.refresh(target)
            return target

    def _advance(
        self,
        row: SeedInstallation,
        stage: str,
        evidence: dict[str, Any],
        columns: dict[str, Any] | None = None,
    ) -> SeedInstallation:
        def change(target: SeedInstallation) -> None:
            for name, value in (columns or {}).items():
                setattr(target, name, value)
            # a replay re-runs the read-only stages, which must not unread an
            # installation that is already bound; the receipt still records the rerun
            if _stage_index(stage) >= _stage_index(target.status):
                target.status = stage
            target.stage_receipts = {
                **dict(target.stage_receipts),
                stage: {"at": _now(), "ok": True, **evidence},
            }
            target.failure = {}
            if stage == "verified":
                target.verified_at = datetime.now(timezone.utc)

        return self._mutate(row.id, change)

    def _fail(self, row: SeedInstallation, error: DomainError, stage: str) -> None:
        receipt = {
            "at": _now(),
            "ok": False,
            "code": error.code,
            "message": error.message,
            "details": error.details,
        }

        def change(target: SeedInstallation) -> None:
            target.failure = {
                "code": error.code,
                "message": error.message,
                "stage": stage,
                "details": error.details,
                "at": _now(),
            }
            # a refusal records its own key so the last passing receipt for that stage stays readable
            target.stage_receipts = {
                **dict(target.stage_receipts),
                f"{stage}:refused": receipt,
            }

        self._mutate(row.id, change)

    def _stage(
        self, row: SeedInstallation, report: dict[str, Any]
    ) -> SeedInstallation:
        return self._advance(
            row,
            "staged",
            {
                "zip_path": report["zip_path"],
                "zip_sha256": report["zip_sha256"],
                "zip_bytes": report["zip_bytes"],
                "bundle_content_sha256": report["bundle_content_sha256"],
                "counts": report["manifest"]["counts"],
            },
            columns={"zip_path": report["zip_path"], "zip_sha256": report["zip_sha256"]},
        )

    # ---------- the only engine write ----------

    def _import_bundle(
        self,
        row: SeedInstallation,
        build: standard_seed_bundle.SeedBuild,
        report: dict[str, Any],
    ) -> SeedInstallation:
        zip_path = Path(report["zip_path"])
        if not zip_path.is_absolute():
            zip_path = standard_seed_bundle.REPO_ROOT / zip_path
        pinned_project_id = build.identity["project_id"]
        filename = zip_path.name
        try:
            response = self.client.restore_native_bundle(
                filename=filename,
                payload=zip_path.read_bytes(),
                conflict_policy="fail",
            )
        except DomainError as error:
            if _is_identity_conflict(error):
                return self._adopt(row, build, report, error)
            raise
        payload = response.payload
        self._check_import_receipt(payload, pinned_project_id, report)
        row = self._mutate(
            row.id,
            lambda target: setattr(target, "import_receipt", dict(payload)),
        )
        return self._advance(
            row,
            "imported",
            {
                "endpoint": "/api/native-project-bundles/import?conflict_policy=fail",
                "project_id": payload["project_id"],
                "source_project_id": payload["source_project_id"],
                "issues": payload["issues"],
                "counts": payload["counts"],
            },
        )

    def _check_import_receipt(
        self,
        payload: dict[str, Any],
        pinned_project_id: str,
        report: dict[str, Any],
    ) -> None:
        failures: list[str] = []
        if payload.get("identity_remapped") is not False:
            failures.append("identity_remapped")
        if payload.get("graph_hashes_preserved") is not True:
            failures.append("graph_hashes_preserved")
        if payload.get("project_id") != pinned_project_id:
            failures.append("project_id")
        if payload.get("source_project_id") != pinned_project_id:
            failures.append("source_project_id")
        if failures:
            raise DomainError(
                code="SEED_IMPORT_RECEIPT_REFUSED",
                message="the engine import receipt does not confirm the pinned seed identity",
                status_code=502,
                details={
                    "failed_fields": failures,
                    "pinned_project_id": pinned_project_id,
                    "receipt": {
                        key: payload.get(key)
                        for key in (
                            "status",
                            "project_id",
                            "source_project_id",
                            "identity_remapped",
                            "graph_hashes_preserved",
                            "source_manifest_sha256",
                        )
                    },
                    "bundle_content_sha256": report["bundle_content_sha256"],
                },
            )

    def _adopt(
        self,
        row: SeedInstallation,
        build: standard_seed_bundle.SeedBuild,
        report: dict[str, Any],
        rejection: DomainError,
    ) -> SeedInstallation:
        """Take over a project the engine already holds instead of importing a second copy."""
        pinned_project_id = build.identity["project_id"]
        try:
            snapshot = self.client.get_provider_model_snapshot(
                pinned_project_id, build.version_row()["version"]
            )
        except DomainError as error:
            raise DomainError(
                code="SEED_IMPORT_REJECTED_OBJECT_ABSENT",
                message=(
                    "the engine refused the import but does not hold the pinned project, "
                    "so nothing can be adopted"
                ),
                status_code=502,
                details={
                    "import_rejection": {"code": rejection.code, **rejection.details},
                    "adopt_failure": {"code": error.code, **error.details},
                    "pinned_project_id": pinned_project_id,
                },
            ) from error
        mismatches = self._graph_mismatches(build, snapshot.payload["graph"])
        if mismatches:
            raise DomainError(
                code="SEED_ENGINE_OBJECT_MISMATCH",
                message=(
                    "the engine already holds this project id but its graph is not this seed, "
                    "so the install refuses rather than adopting an unrelated model"
                ),
                status_code=409,
                details={
                    "mismatches": mismatches,
                    "pinned_project_id": pinned_project_id,
                    "bundle_content_sha256": report["bundle_content_sha256"],
                    "import_rejection": {"code": rejection.code, **rejection.details},
                    "adopted_objects_are_never_deleted": True,
                },
            )
        row = self._mutate(
            row.id,
            lambda target: setattr(
                target,
                "import_receipt",
                {
                    "adopted": True,
                    "import_rejection": {
                        "code": rejection.code,
                        "message": rejection.message,
                        "details": rejection.details,
                    },
                    "snapshot_identity": {
                        "project_id": snapshot.payload["project_id"],
                        "version": snapshot.payload["version"],
                        "graph_hash": snapshot.payload["graph_hash"],
                    },
                },
            ),
        )
        return self._advance(
            row,
            "imported",
            {
                "adopted": True,
                "reason": "the engine reported the pinned project identity already exists",
                "project_id": snapshot.payload["project_id"],
                "import_rejection_status": rejection.details.get("upstream_status"),
            },
        )

    # ---------- read-only verification ----------

    def _verify(
        self,
        row: SeedInstallation,
        build: standard_seed_bundle.SeedBuild,
        report: dict[str, Any],
    ) -> SeedInstallation:
        project_id = row.engine_project_id or build.identity["project_id"]
        version = build.version_row()["version"]
        try:
            versions = self.client.list_project_versions(project_id)
            snapshot = self.client.get_provider_model_snapshot(project_id, version)
        except DomainError as error:
            if _is_absent(error) and row.import_receipt:
                raise DomainError(
                    code="SEED_ENGINE_OBJECT_MISSING",
                    message=(
                        "the install receipt names an engine object that the engine no longer returns; "
                        "the seed is not re-imported automatically"
                    ),
                    status_code=409,
                    details={
                        "project_id": project_id,
                        "version": version,
                        "probe_failure": {"code": error.code, **error.details},
                    },
                ) from error
            raise
        payload = snapshot.payload
        graph = payload["graph"]
        graph_hash = payload["graph_hash"]
        # `graph_hash` is Nebula LCA's own digest over its own serialization of the stored version,
        # and that serialization carries the flow display labels - `flow_name_en`, and the `name` /
        # `flowName` the engine's own POST /api/projects/{id}/sync-flow-names overwrites with its
        # catalogue labels once a later import matches more of its flows. Measured on the isolated
        # 8006 engine on 2026-09-21: that rewrite moves the engine-native hash, our digest over the
        # echo with `flow_name_en` removed, and the port labels, while leaving every amount, unit,
        # port id, flow uuid, direction and edge alone. No whole-graph digest of an engine echo can
        # therefore separate "the model moved" from "the engine relabelled it", so this service does
        # not try to: the gate is the authored-identity and authored-topology comparison below, which
        # reads the same fields the solver does, and both hashes stay recorded as upstream evidence.
        returned_versions = [item["version"] for item in versions]
        if version not in returned_versions:
            raise DomainError(
                code="SEED_ENGINE_OBJECT_MISSING",
                message="the engine does not list the model version this seed installed",
                status_code=409,
                details={
                    "project_id": project_id,
                    "required_version": version,
                    "returned_versions": returned_versions,
                },
            )
        observed_graph_pin = canonical_graph_sha256(
            self.client.get_model_version(project_id, version).payload["graph"]
        )
        engine_native_hash_changed = bool(
            row.engine_graph_hash and graph_hash != row.engine_graph_hash
        )
        mismatches = self._graph_mismatches(build, graph)
        if mismatches:
            raise DomainError(
                code="SEED_ENGINE_OBJECT_MISMATCH",
                message="the engine graph does not carry the identities this seed authored",
                status_code=409,
                details={
                    "mismatches": mismatches,
                    "project_id": project_id,
                    "version": version,
                    "receipt_graph_hash": row.engine_graph_hash,
                    "observed_graph_hash": graph_hash,
                    "observed_graph_pin": observed_graph_pin,
                },
            )
        catalog = self._verify_catalog(row, build)
        elementary = self._verify_elementary_identities(row, build)
        role_map = self._role_instance_map(build, graph)

        def record(target: SeedInstallation) -> None:
            target.engine_graph_hash = graph_hash
            target.role_instance_map = role_map
            target.verification = {
                "engine": {
                    "project_id": payload["project_id"],
                    "version": payload["version"],
                    "graph_hash": graph_hash,
                    "graph_pin": observed_graph_pin,
                    "engine_native_hash_changed_since_last_verification": (
                        engine_native_hash_changed
                    ),
                    "engine_build": payload.get("engine"),
                    "returned_versions": returned_versions,
                },
                "graph_identity": {
                    "process_uuids": sorted(
                        str(_field(node, "process_uuid", "processUuid") or "")
                        for node in graph.get("nodes") or []
                    ),
                    "ports": len(_graph_port_index(graph)),
                    "functional_unit": _functional_unit(graph),
                },
                "catalog": catalog,
                "elementary_identities": elementary,
                "bundle_content_sha256": report["bundle_content_sha256"],
                "verified_at": _now(),
            }

        row = self._mutate(row.id, record)
        return self._advance(
            row,
            "verified",
            {
                "graph_hash": graph_hash,
                "graph_pin": observed_graph_pin,
                "engine_native_hash_changed": engine_native_hash_changed,
                "version_rows_returned": len(versions),
                "catalog_checks": catalog["summary"],
                "elementary_identity_flows": len(elementary["flows"]),
            },
        )

    def _graph_mismatches(
        self,
        build: standard_seed_bundle.SeedBuild,
        graph: dict[str, Any],
    ) -> list[str]:
        mismatches: list[str] = []
        nodes = graph.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            return ["SNAPSHOT_NODES_MISSING"]
        authored_nodes = build.graph["nodes"]
        authored_processes = {node["process_uuid"] for node in authored_nodes}
        observed_processes = {
            str(_field(node, "process_uuid", "processUuid") or "") for node in nodes
        }
        if observed_processes != authored_processes:
            mismatches.append(
                "process_uuid set "
                f"authored={sorted(authored_processes)} observed={sorted(observed_processes)}"
            )
        authored_ports = _graph_port_index(build.graph)
        observed_ports = _graph_port_index(graph)
        for key in sorted(set(authored_ports) | set(observed_ports)):
            authored = authored_ports.get(key)
            observed = observed_ports.get(key)
            if authored is None or observed is None:
                mismatches.append(f"port {key} authored={authored is not None} observed={observed is not None}")
                continue
            if authored["flow_uuid"] != observed["flow_uuid"]:
                mismatches.append(f"port {key} flow_uuid differs")
            if authored["amount"] != observed["amount"]:
                mismatches.append(f"port {key} amount {authored['amount']} != {observed['amount']}")
            if authored["unit"] != observed["unit"]:
                mismatches.append(f"port {key} unit differs")
            if authored["direction"] != observed["direction"]:
                mismatches.append(f"port {key} direction differs")
        authored_edges = _graph_exchange_index(build.graph)
        observed_edges = _graph_exchange_index(graph)
        for key in sorted(set(authored_edges) | set(observed_edges)):
            authored = authored_edges.get(key)
            observed = observed_edges.get(key)
            if authored is None or observed is None:
                mismatches.append(
                    f"exchange {key} authored={authored is not None} observed={observed is not None}"
                )
                continue
            for name in ("flow_uuid", "amount", "unit", "from_node", "to_node"):
                if authored[name] != observed[name]:
                    mismatches.append(f"exchange {key} {name} differs")
        authored_fu = _functional_unit(build.graph)
        observed_fu = _functional_unit(graph)
        if authored_fu != observed_fu:
            mismatches.append(f"functional unit {authored_fu} != {observed_fu}")
        return mismatches

    def _verify_catalog(
        self, row: SeedInstallation, build: standard_seed_bundle.SeedBuild
    ) -> dict[str, Any]:
        readings: dict[str, Any] = {"declared": {}, "observed": {}}
        summary: list[dict[str, Any]] = []
        drift: list[dict[str, Any]] = []

        def check(
            kind: str,
            key: str,
            role: str | None,
            declared: dict[str, Any],
            observed: dict[str, Any] | None,
        ) -> None:
            readings["declared"][key] = declared
            if observed is None:
                readings["observed"][key] = None
                fields = {"<row>": "the engine returns no row for this identity"}
            else:
                readings["observed"][key] = {
                    name: observed.get(name) for name in declared
                }
                fields = {
                    name: {"declared": value, "observed": observed.get(name)}
                    for name, value in declared.items()
                    if name not in observed or observed[name] != value
                }
            summary.append({"kind": kind, "identity": key, "ok": not fields})
            if fields:
                drift.append(
                    {"kind": kind, "role": role, "identity": key, "fields": fields}
                )

        def flow_row_or_absent(flow_uuid: str) -> dict[str, Any] | None:
            try:
                return self.client.get_reference_flow(flow_uuid)
            except DomainError as error:
                if _is_absent(error):
                    return None
                raise

        for owned in build.owned_flows["rows"]:
            declared = {
                name: value
                for name, value in owned.items()
                if name not in ENGINE_OWNED_COLUMNS
            }
            check(
                "bundled_owned_flow",
                owned["flow_uuid"],
                None,
                declared,
                flow_row_or_absent(owned["flow_uuid"]),
            )

        for dependency in build.flow_dependencies["dependencies"]:
            if dependency["disposition"] != "verify_present":
                continue
            check(
                "verify_present_flow",
                dependency["flow_uuid"],
                dependency["role"],
                dict(dependency["observed"]),
                flow_row_or_absent(dependency["flow_uuid"]),
            )

        for group in build.flow_dependencies["unit_groups"]:
            declared = dict(group["observed"])
            units = self.client.list_reference_units(group["name"])
            names = sorted(str(_field(item, "unit_name", "name") or "") for item in units)
            anchor = units[0] if units else {}
            identity_keys = ("source_uuid", "source_version", "source_package_version")
            key = f"group:{group['name']}"
            check(
                "unit_group",
                key,
                None,
                {name: declared.get(name) for name in identity_keys},
                {name: anchor.get(name) for name in identity_keys},
            )
            readings["observed"][key]["units"] = names
            missing = [
                unit for unit in declared.get("contains", []) if unit not in names
            ]
            if missing:
                drift.append(
                    {
                        "kind": "unit_group",
                        "role": None,
                        "identity": key,
                        "fields": {
                            "contains": {
                                "declared": declared.get("contains"),
                                "observed": missing,
                            }
                        },
                    }
                )

        if drift:
            raise DomainError(
                code="SEED_VERIFY_PRESENT_OBSERVATION_DRIFT",
                message=(
                    "the engine catalog no longer matches the identities this seed declares, "
                    "so the install stops before any calculation pin is written"
                ),
                status_code=409,
                details={
                    "engine_db_digest": row.engine_db_digest,
                    "drift": drift,
                    "readings": readings,
                    "rule": "re-measure the probe, raise the seed version, or drop the dependency - never install against a row that moved",
                },
            )
        return {"summary": summary, "readings": readings}

    def _verify_elementary_identities(
        self, row: SeedInstallation, build: standard_seed_bundle.SeedBuild
    ) -> dict[str, Any]:
        """Re-read every pinned biosphere identity through the read-only provider resolver."""
        refs = (build.graph.get("metadata") or {}).get("elementary_flow_refs") or []
        declared: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for ref in refs:
            triple = (
                str(ref.get("source_namespace") or ""),
                str(ref.get("flow_uuid") or ""),
                str(ref.get("version") or ""),
            )
            declared.setdefault(triple, []).append(ref)
        if not declared:
            return {"endpoint": None, "flows": []}

        response = self.client.resolve_provider_catalog(
            {
                "schema_version": "provider.catalog.resolve.request.v1",
                "flows": [
                    {
                        "source_namespace": namespace,
                        "flow_uuid": flow_uuid,
                        "version": version,
                        "correlation_id": f"{flow_uuid}@{version}",
                    }
                    for (namespace, flow_uuid, version) in declared
                ],
            }
        )
        resolved: dict[tuple[str, str, str], dict[str, Any]] = {}
        for item in response.payload["items"]:
            if item.get("kind") != "flow":
                continue
            key = item.get("key") or {}
            resolved[
                tuple(
                    str(key.get(name) or "")
                    for name in ("source_namespace", "flow_uuid", "version")
                )
            ] = item

        flows: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        drift: list[dict[str, Any]] = []
        for triple, group in declared.items():
            identity = dict(
                zip(("source_namespace", "flow_uuid", "version"), triple)
            )
            exchange_ids = [str(ref.get("exchange_id") or "") for ref in group]
            item = resolved.get(triple)
            if item is None:
                unresolved.append(
                    {
                        **identity,
                        "exchange_ids": exchange_ids,
                        "status": None,
                        "reason": "the resolver returned no item for this exact identity",
                    }
                )
                continue
            if item.get("status") != "resolved":
                unresolved.append(
                    {
                        **identity,
                        "exchange_ids": exchange_ids,
                        "status": item.get("status"),
                        "code": item.get("code"),
                        "message": item.get("message"),
                    }
                )
                continue
            value = item.get("value") or {}
            moved = {
                name: {"declared": ref.get(name), "observed": value.get(name)}
                for ref in group
                for name in ELEMENTARY_IDENTITY_FIELDS
                if ref.get(name) != value.get(name)
            }
            if moved:
                drift.append(
                    {**identity, "exchange_ids": exchange_ids, "fields": moved}
                )
            flows.append(
                {
                    "identity": identity,
                    "exchange_ids": exchange_ids,
                    "declared": {name: group[0].get(name) for name in ELEMENTARY_IDENTITY_FIELDS},
                    "observed": {name: value.get(name) for name in ELEMENTARY_IDENTITY_FIELDS},
                    "provenance": {
                        name: value.get(name) for name in ELEMENTARY_PROVENANCE_FIELDS
                    },
                    "ok": not moved,
                }
            )

        def details(extra: dict[str, Any]) -> dict[str, Any]:
            return {
                "engine_db_digest": row.engine_db_digest,
                "seed": f"{build.seed_id} {build.version}",
                "declared_identities": sorted(str(key) for key in declared),
                "rule": "re-resolve the identity with POST /api/provider/v1/catalog/resolve, pin what the provider returns, and raise the seed version - never install against a biosphere dataset the engine cannot name",
                **extra,
            }

        if unresolved:
            raise DomainError(
                code="SEED_ELEMENTARY_IDENTITY_NOT_RESOLVED",
                message=(
                    "the engine does not resolve an elementary flow identity this seed pins, "
                    "so the install stops before any calculation pin is written"
                ),
                status_code=409,
                details=details({"unresolved": unresolved}),
            )
        if drift:
            raise DomainError(
                code="SEED_ELEMENTARY_IDENTITY_MISMATCH",
                message=(
                    "the engine resolves this elementary flow to a different dataset identity "
                    "than the seed pins, so the install stops before any calculation pin is written"
                ),
                status_code=409,
                details=details({"drift": drift}),
            )
        return {
            "endpoint": "POST /api/provider/v1/catalog/resolve",
            "flows": flows,
        }

    def _role_instance_map(
        self,
        build: standard_seed_bundle.SeedBuild,
        graph: dict[str, Any],
    ) -> list[dict[str, Any]]:
        nodes_by_process: dict[str, dict[str, Any]] = {}
        for node in graph.get("nodes") or []:
            process_uuid = str(_field(node, "process_uuid", "processUuid") or "")
            if process_uuid:
                nodes_by_process.setdefault(process_uuid, node)
        mapping: list[dict[str, Any]] = []
        for role in build.roles["roles"]:
            process_uuid = role["process_uuid"]
            node = nodes_by_process.get(str(process_uuid)) or {}
            ports = _port_collection(node) if node else []
            mapping.append(
                {
                    "role_id": role["role_id"],
                    "merged_sub_roles": [
                        item["sub_role_id"] for item in role.get("merged_sub_roles") or []
                    ],
                    "process_uuid": process_uuid,
                    "engine_node_id": _field(node, "id", "node_id"),
                    "engine_node_present": bool(node),
                    "inputs": sorted(_port_amount(port) for port in ports if port["direction"] == "input"),
                    "outputs": sorted(_port_amount(port) for port in ports if port["direction"] == "output"),
                }
            )
        return mapping

    # ---------- binding ----------

    def _bind(
        self,
        row: SeedInstallation,
        build: standard_seed_bundle.SeedBuild,
        report: dict[str, Any],
        application_id: str,
        boundary_key: str | None,
        declarations: dict[str, str] | None = None,
    ) -> SeedInstallation:
        # a row that already carries a successful `bound` receipt is a replay: the stage
        # pointer alone cannot tell, because every install re-verifies before it binds
        bound_receipt = row.stage_receipts.get("bound")
        if bound_receipt and row.system_model_id:
            self._check_replayed_binding(
                row, bound_receipt, application_id, boundary_key, declarations or {}
            )
            return row
        boundary_path = (
            build.manifest["applications"].get(boundary_key or "")
            if boundary_key
            else None
        )
        if not isinstance(boundary_path, str) or not boundary_path.startswith(
            "boundaries/"
        ):
            raise DomainError(
                code="SEED_BOUNDARY_NOT_AUTHORED",
                message=(
                    "this seed does not author a boundary file for that application key, "
                    "so no coverage claim can be bound"
                ),
                status_code=422,
                details={
                    "boundary_key": boundary_key,
                    "manifest_value": build.manifest["applications"].get(
                        boundary_key or ""
                    ),
                    "authored_keys": sorted(
                        key
                        for key, value in build.manifest["applications"].items()
                        if isinstance(value, str) and value.startswith("boundaries/")
                    ),
                    "rule": "an application must not borrow another application's boundary as a stand-in",
                },
            )
        boundary = build.read(boundary_path)
        undecided = boundary.get("undecided") or []
        declarations = self._resolve_declarations(boundary_key, boundary, declarations)
        with self.database.session() as db:
            application = db.get(Application, application_id)
            if application is None:
                raise DomainError(
                    code="APPLICATION_NOT_FOUND",
                    message=f"application not found: {application_id}",
                    status_code=404,
                )
        # the pin has to name the same graph representation `attach` persists as the
        # revision snapshot; the provider snapshot endpoint normalizes flow_name_en away
        # and hashes to a different value for the very same version
        upstream = self.client.get_model_version(
            row.engine_project_id or build.identity["project_id"],
            build.version_row()["version"],
        )
        echo_graph = upstream.payload["graph"]
        # A pin is written once. When this application already holds the model, the graph identity
        # the boundary ledger names is the one that first attach recorded: Nebula LCA rewrites the
        # flow display labels of a version it has already stored from its own catalogue, so
        # re-deriving the digest from today's answer would make a resumed install ask for a boundary
        # whose content differs from the frozen one and refuse its own model. Reusing the pin is
        # sound only because `_verify` has already compared every authored process identity, port
        # flow identity, amount, unit, direction, edge and the functional unit against this answer
        # in the same pass, and refuses before reaching here if any of them moved.
        attached = self._attached_revision(application_id, build, row, echo_graph)
        expected_graph_sha256 = (
            attached.graph_sha256
            if attached is not None
            else canonical_graph_sha256(echo_graph)
        )
        ledger: tuple[dict[str, Any], dict[str, Any]] | None = None
        if boundary.get("application") == CBAM_BOUNDARY_APPLICATION:
            ledger = self._cbam_boundary_ledger(
                build,
                boundary,
                declarations,
                boundary_path,
                report,
                expected_graph_sha256,
            )
        frozen = (
            self._freeze_boundary(application_id, ledger[0]) if ledger else None
        )
        model = self._attach(
            application_id,
            build,
            None if attached is not None else expected_graph_sha256,
            echo_graph,
            row,
        )
        revision_id = model.upstream_receipt.get("base_revision_id")

        def pin(target: SeedInstallation) -> None:
            target.application_id = application_id
            target.system_model_id = model.id
            target.system_revision_id = revision_id

        evidence = {
            "application_id": application_id,
            "application_type": application.application_type,
            "boundary_key": boundary_key,
            "system_model_id": model.id,
            "system_revision_id": revision_id,
            "expected_graph_sha256": expected_graph_sha256,
            "graph_pin_source": "stored_revision" if attached else "engine_echo",
            "declarations": [
                {"clause": clause, "declared": declarations[clause]}
                for clause in sorted(declarations)
            ],
        }
        if frozen is not None:
            evidence["boundary_definition_id"] = frozen[0]
            evidence["boundary_content_sha256"] = frozen[1]
        row = self._advance(self._mutate(row.id, pin), "bound", evidence)
        coverage = {
            "application": boundary.get("application"),
            "clause_refs": boundary.get("clause_refs"),
            "segments": len(boundary.get("segments") or []),
            "exclusions": len(boundary.get("exclusions") or []),
            "undecided": len(undecided),
            "applicability": [
                {
                    "clause": item.get("clause"),
                    "status": item.get("status"),
                }
                for item in boundary.get("applicability") or []
            ],
        }
        if ledger:
            coverage.update(ledger[1])
        return self._advance(row, "ready", {"boundary_coverage": coverage})

    @staticmethod
    def _check_replayed_binding(
        row: SeedInstallation,
        bound_receipt: dict[str, Any],
        application_id: str,
        boundary_key: str | None,
        declarations: dict[str, str],
    ) -> None:
        """A replay may not quietly rebind, or re-declare, what is already bound."""
        if (
            bound_receipt.get("application_id") != application_id
            or bound_receipt.get("boundary_key") != boundary_key
        ):
            raise DomainError(
                code="SEED_BOUNDARY_ALREADY_BOUND",
                message=(
                    "this verified seed is already bound to another application boundary, "
                    "so rebinding it here would silently move an existing result"
                ),
                status_code=409,
                details={
                    "installation_id": row.id,
                    "bound_application_id": bound_receipt.get("application_id"),
                    "bound_boundary_key": bound_receipt.get("boundary_key"),
                    "requested_application_id": application_id,
                    "requested_boundary_key": boundary_key,
                    "rule": "one installation keeps one binding; a second application attaches "
                    "to the verified system model, it does not rebind the installation",
                },
            )
        frozen_declarations = {
            str(item["clause"]): str(item["declared"])
            for item in bound_receipt.get("declarations") or []
        }
        if frozen_declarations != declarations:
            raise DomainError(
                code="SEED_BOUNDARY_DECLARATION_CONFLICT",
                message=(
                    "this installation is already bound under a different runtime declaration"
                ),
                status_code=409,
                details={
                    "installation_id": row.id,
                    "frozen": frozen_declarations,
                    "requested": declarations,
                    "rule": "a declaration is part of the bound boundary, not a per request option",
                },
            )

    @staticmethod
    def _resolve_declarations(
        boundary_key: str | None,
        boundary: dict[str, Any],
        declarations: dict[str, str] | None,
    ) -> dict[str, str]:
        """Return the clause-keyed runtime declarations a boundary still needs."""
        supplied = dict(declarations or {})
        undecided = boundary.get("undecided") or []
        if boundary.get("application") != CBAM_BOUNDARY_APPLICATION:
            if undecided or supplied:
                raise DomainError(
                    code="SEED_BOUNDARY_UNDECIDED_REFUSED",
                    message="the seed boundary still carries undecided emission candidates",
                    status_code=409,
                    details={
                        "boundary_key": boundary_key,
                        "undecided": undecided,
                        "given_declarations": sorted(supplied),
                        "rule": "an unclassified emission may not be silently excluded or included",
                    },
                )
            return {}
        # only the CBAM ledger may relax an undecided item, and only because the build gate
        # proves every port of this seed already carries exactly one disposition
        pending = [item for item in undecided if item.get("runtime_input_required")]
        clauses = [str(item.get("clause") or "") for item in pending]
        if len(set(clauses)) != len(clauses):
            raise DomainError(
                code="SEED_BOUNDARY_DECLARATION_KEY_AMBIGUOUS",
                message=(
                    "two undecided items that need a runtime declaration share one clause, "
                    "so a clause keyed declaration cannot name which one it answers"
                ),
                status_code=422,
                details={"boundary_key": boundary_key, "clauses": clauses},
            )
        missing = sorted(set(clauses) - set(supplied))
        unknown = sorted(set(supplied) - set(clauses))
        if missing:
            raise DomainError(
                code="SEED_BOUNDARY_UNDECIDED_REFUSED",
                message=(
                    "the seed boundary still carries undecided candidates that need a runtime "
                    "declaration, and none was given"
                ),
                status_code=409,
                details={
                    "boundary_key": boundary_key,
                    "undecided": undecided,
                    "missing_declarations": missing,
                    "rule": "an unclassified emission may not be silently excluded or included",
                },
            )
        if unknown:
            raise DomainError(
                code="SEED_BOUNDARY_DECLARATION_UNKNOWN",
                message="a declaration names no undecided item of this boundary",
                status_code=422,
                details={
                    "boundary_key": boundary_key,
                    "unknown_declarations": unknown,
                    "declinable_clauses": sorted(clauses),
                    "rule": "a declaration that answers no open question must not be filed silently",
                },
            )
        return supplied

    def _cbam_boundary_ledger(
        self,
        build: standard_seed_bundle.SeedBuild,
        boundary: dict[str, Any],
        declarations: dict[str, str],
        boundary_path: str,
        report: dict[str, Any],
        expected_graph_sha256: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Turn the authored CBAM ledger into the frozen boundary the trial reads."""
        processes = {
            str(role_id): str(uuid)
            for role_id, uuid in build.identity["process_uuids"].items()
        }

        def role_process(role_id: str) -> str:
            if role_id not in processes:
                raise DomainError(
                    code="SEED_BOUNDARY_PORT_UNKNOWN",
                    message=f"the CBAM ledger classifies a port of an unknown role: {role_id}",
                    status_code=409,
                    details={"role_id": role_id, "known_roles": sorted(processes)},
                )
            return processes[role_id]

        def process_uuid(exchange_id: str) -> str:
            return role_process(str(exchange_id).partition("::")[0])

        segments = [
            segment
            for segment in (boundary.get("segments") or {}).values()
            if isinstance(segment, dict)
        ]
        counted = [
            entry for segment in segments for entry in segment.get("included_exchanges") or []
        ]
        # one disposition per segment conclusion: a precursor port frozen as "counted" would be
        # demanded a CO2 receipt it cannot have, and an electricity port frozen as "counted" would
        # be added to the direct total
        dispositions = build.cbam_dispositions()
        excluded = [
            entry for segment in segments for entry in segment.get("excluded_exchanges") or []
        ]
        not_applicable = list(boundary.get("not_applicable") or [])
        counted_ids = {str(entry["exchange_id"]) for entry in counted}
        for entry in excluded:
            chosen = entry.get("counted_instead")
            if chosen and str(chosen) not in counted_ids:
                raise DomainError(
                    code="SEED_BOUNDARY_SOURCE_GROUP_NOT_COUNTED",
                    message=(
                        "an excluded exchange says another one carries its emission source, "
                        "but that one is not counted, so the source would go missing"
                    ),
                    status_code=409,
                    details={
                        "exchange_id": entry["exchange_id"],
                        "counted_instead": chosen,
                        "counted": sorted(counted_ids),
                    },
                )
        denominators = [
            entry
            for entry in not_applicable
            if entry.get("disposition") == DENOMINATOR_DISPOSITION
        ]
        if len(denominators) != 1:
            raise DomainError(
                code="SEED_BOUNDARY_REFERENCE_PROCESS_UNDECLARED",
                message=(
                    "exactly one port must be declared as the reference product output that "
                    "carries the functional unit"
                ),
                status_code=409,
                details={
                    "found": [entry.get("exchange_id") for entry in denominators],
                    "rule": "a multi process boundary without a denominator owner cannot be solved",
                },
            )
        classified = counted + excluded + not_applicable
        in_boundary = sorted(
            {role_process(str(entry["exchange_id"]).partition("::")[0]) for entry in classified}
        )

        def rule(entry: dict[str, Any]) -> dict[str, Any]:
            exchange_id = str(entry["exchange_id"])
            return {
                "exchange_id": exchange_id,
                "process_uuid": process_uuid(exchange_id),
                "clause": entry.get("clause"),
                "basis": entry.get("basis") or entry.get("reason"),
                "source_group": entry.get("same_source_group"),
                "counted_instead": entry.get("counted_instead"),
                "counterpart": entry.get("counterpart"),
            }

        pending = {
            str(item["clause"]): str(item["runtime_input_required"])
            for item in boundary.get("undecided") or []
            if item.get("runtime_input_required")
        }
        runtime_declarations = [
            {
                "clause": clause,
                "declared": declarations[clause],
                "runtime_input_required": pending[clause],
            }
            for clause in sorted(declarations)
        ]
        open_items = [
            {
                "clause": item.get("clause"),
                "item": item.get("item"),
                "effect": item.get("effect"),
                "gap_ref": item.get("gap_ref"),
                "state": "open_coverage_limitation",
            }
            for item in boundary.get("undecided") or []
            if not item.get("runtime_input_required")
        ]
        content = {
            "name": f"{build.seed_id}@{build.version} {boundary_path}",
            "boundary_type": CBAM_BOUNDARY_APPLICATION,
            "included_entity_ids": [],
            "included_process_ids": in_boundary,
            "included_flow_rules": [
                {
                    **rule(entry),
                    "disposition": dispositions[str(entry["exchange_id"])],
                    "emission_kind": entry.get("emission_kind"),
                    "parameter_refs": entry.get("parameter_refs") or [],
                }
                for entry in counted
            ],
            "excluded_items": [
                {
                    **rule(entry),
                    "disposition": "excluded_with_basis",
                }
                for entry in excluded
            ]
            + [
                {
                    **rule(entry),
                    "disposition": str(
                        entry.get("disposition") or "not_applicable_with_basis"
                    ),
                }
                for entry in not_applicable
            ],
            "consolidation_policy": {
                "schema": MULTI_PROCESS_BOUNDARY_SCHEMA,
                "reference_process_uuid": process_uuid(
                    str(denominators[0]["exchange_id"])
                ),
                "in_boundary_process_uuids": in_boundary,
                "clause": boundary["goods_identity"]["route_boundary_clause"],
                "runtime_declarations": runtime_declarations,
                "coverage_open_items": open_items,
            },
            "period_id": None,
            "geographic_scope": {
                "seed_id": build.seed_id,
                "seed_version": build.version,
                "bundle_content_sha256": report["bundle_content_sha256"],
                "boundary_path": boundary_path,
                "graph_sha256": expected_graph_sha256,
            },
            "method_package_ref": build.cbam_method_package_ref(),
        }
        coverage = {
            "universe": {
                "ports": len({str(entry["exchange_id"]) for entry in classified}),
                "counted": sum(
                    1
                    for entry in counted
                    if dispositions[str(entry["exchange_id"])]
                    == standard_seed_bundle.COUNTED_DISPOSITION
                ),
                "precursor_mass_counted": sum(
                    1
                    for entry in counted
                    if dispositions[str(entry["exchange_id"])]
                    == standard_seed_bundle.PRECURSOR_DISPOSITION
                ),
                "indirect_electricity_counted": sum(
                    1
                    for entry in counted
                    if dispositions[str(entry["exchange_id"])]
                    == standard_seed_bundle.INDIRECT_DISPOSITION
                ),
                "excluded_with_basis": len(excluded),
                "not_applicable": len(not_applicable),
            },
            "reference_exchange_id": str(denominators[0]["exchange_id"]),
            "in_boundary_process_uuids": in_boundary,
            "open_items": open_items,
            "declared": runtime_declarations,
        }
        return content, coverage

    def _freeze_boundary(
        self, application_id: str, content: dict[str, Any]
    ) -> tuple[str, str]:
        """Persist one immutable boundary row, or reuse the byte identical earlier one."""
        digest = canonical_json_sha256(content)
        with self.database.session() as db:
            existing = db.scalar(
                select(BoundaryDefinition).where(
                    BoundaryDefinition.application_id == application_id,
                    BoundaryDefinition.name == content["name"],
                )
            )
            if existing is not None:
                if (
                    existing.status != "frozen"
                    or existing.content_sha256 != digest
                ):
                    raise DomainError(
                        code="SEED_BOUNDARY_FROZEN_CONFLICT",
                        message=(
                            "a frozen boundary already exists for this application under that "
                            "name and its content differs, so rebinding would silently change "
                            "what an existing result means"
                        ),
                        status_code=409,
                        details={
                            "boundary_definition_id": existing.id,
                            "frozen_content_sha256": existing.content_sha256,
                            "requested_content_sha256": digest,
                            "rule": "a changed boundary is a new boundary, not an overwrite",
                        },
                    )
                return existing.id, digest
            record = BoundaryDefinition(
                application_id=application_id,
                **content,
                content_sha256=digest,
                status="frozen",
                frozen_at=datetime.now(timezone.utc),
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record.id, digest

    def _attached_revision(
        self,
        application_id: str,
        build: standard_seed_bundle.SeedBuild,
        row: SeedInstallation,
        echo_graph: dict[str, Any],
    ) -> SystemRevision | None:
        """The revision this application already pins, when today's engine answer is that same model.

        Returns None when nothing is attached yet, or when the stored snapshot and the answer are not
        one model: in both cases the caller derives the pin from the live answer and the guards in
        `attach` decide whether that is a new model or a mutated one.
        """
        project_id = row.engine_project_id or build.identity["project_id"]
        version = build.version_row()["version"]
        with self.database.session() as db:
            model = db.scalar(
                select(SystemModel).where(
                    SystemModel.application_id == application_id,
                    SystemModel.provider == "nebula_lca",
                    SystemModel.upstream_project_id == project_id,
                    SystemModel.upstream_version == version,
                )
            )
            if model is None:
                return None
            revision = db.scalar(
                select(SystemRevision)
                .where(SystemRevision.system_model_id == model.id)
                .order_by(SystemRevision.revision_number)
            )
        if revision is None or not same_pinned_model(revision.graph_snapshot or {}, echo_graph):
            return None
        return revision

    def _attach(
        self,
        application_id: str,
        build: standard_seed_bundle.SeedBuild,
        expected_graph_sha256: str | None,
        echo_graph: dict[str, Any],
        row: SeedInstallation,
    ) -> SystemModel:
        project_id = row.engine_project_id or build.identity["project_id"]
        version = build.version_row()["version"]
        try:
            return self.system_models.attach(
                application_id,
                SystemModelCreate(
                    name=f"{build.manifest['title']} ({build.seed_id} {build.version})",
                    upstream_project_id=project_id,
                    upstream_version=version,
                ),
                expected_graph_sha256=expected_graph_sha256,
            )
        except DomainError as error:
            if error.code != "SYSTEM_MODEL_PIN_ALREADY_ATTACHED":
                raise
            with self.database.session() as db:
                existing = db.scalar(
                    select(SystemModel).where(
                        SystemModel.application_id == application_id,
                        SystemModel.upstream_project_id == project_id,
                        SystemModel.upstream_version == version,
                    )
                )
            if existing is None or not same_pinned_model(
                existing.graph_snapshot or {}, echo_graph
            ):
                raise
            return existing


def _graph_port_index(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for node in graph.get("nodes") or []:
        node_id = str(_field(node, "id", "node_id") or "")
        for port in _port_collection(node):
            flow_uuid = str(_field(port, "flowUuid", "flow_uuid") or "")
            port_id = str(_field(port, "id", "exchange_id", "port_id") or "")
            direction = str(port.get("direction") or "")
            amount = _decimal_text(_field(port, "amount", "quantity"))
            key = f"{node_id}::{port_id}"
            index[key] = {
                "flow_uuid": flow_uuid,
                "amount": amount,
                "unit": str(_field(port, "unit", "unitName") or ""),
                "direction": direction,
            }
    return index


def _graph_exchange_index(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for exchange in graph.get("exchanges") or []:
        exchange_id = str(_field(exchange, "id", "exchange_id") or "")
        if not exchange_id:
            continue
        index[exchange_id] = {
            "flow_uuid": str(_field(exchange, "flowUuid", "flow_uuid") or ""),
            "amount": _decimal_text(_field(exchange, "amount", "quantity")),
            "unit": str(_field(exchange, "unit", "unitName") or ""),
            "from_node": str(_field(exchange, "fromNode", "from_node") or ""),
            "to_node": str(_field(exchange, "toNode", "to_node") or ""),
        }
    return index


def _functional_unit(graph: dict[str, Any]) -> tuple[str, str, str]:
    metadata = graph.get("metadata") or {}
    unit = metadata.get("functional_unit") or {}
    return (
        str(_field(unit, "flow_uuid", "flowUuid") or ""),
        str(unit.get("unit") or ""),
        _decimal_text(unit.get("amount")),
    )


def _is_identity_conflict(error: DomainError) -> bool:
    return error.code == "NEBULA_LCA_REJECTED" and error.details.get(
        "upstream_status"
    ) in (409, 422)


def _is_absent(error: DomainError) -> bool:
    return error.code == "NEBULA_LCA_REJECTED" and error.details.get(
        "upstream_status"
    ) == 404

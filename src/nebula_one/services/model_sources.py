from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import PurePosixPath
from typing import Any
from zipfile import BadZipFile, ZipFile

from sqlalchemy import select

from ..adapters.nebula_lca import NebulaLCAClient
from ..database import Database
from ..errors import DomainError
from ..hashing import canonical_graph_sha256, canonical_json_sha256
from ..models import Application, ModelSource, SystemModel, SystemRevision
from ..schemas import ModelSourceAttachCreate, NebulaProjectSourceCreate, SystemModelCreate
from .system_models import SystemModelService


MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_NATIVE_FILES = 32
NATIVE_SCHEMA = "nebula.project.bundle.v1"


def _file_sha256(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _clean_filename(filename: str | None) -> str:
    value = str(filename or "").strip()
    if not value or len(value) > 255 or PurePosixPath(value.replace("\\", "/")).name != value.replace("\\", "/"):
        raise DomainError(
            code="MODEL_SOURCE_FILENAME_INVALID",
            message="uploaded model package must have a plain file name",
            status_code=422,
        )
    return value


def _clean_name(name: str) -> str:
    value = name.strip()
    if not value or len(value) > 255:
        raise DomainError(
            code="MODEL_SOURCE_NAME_INVALID",
            message="model source name must contain 1 to 255 characters",
            status_code=422,
        )
    return value


def _validate_upload(filename: str | None, payload: bytes, *, native: bool) -> str:
    clean = _clean_filename(filename)
    suffix_valid = clean.lower().endswith(".nebula.zip" if native else ".zip")
    if not suffix_valid:
        raise DomainError(
            code="MODEL_SOURCE_FILE_TYPE_INVALID",
            message=(
                "native project backups must use the .nebula.zip suffix"
                if native
                else "TIDAS bundles must use the .zip suffix"
            ),
            status_code=422,
        )
    if not payload or len(payload) > MAX_BUNDLE_BYTES:
        raise DomainError(
            code="MODEL_SOURCE_FILE_SIZE_INVALID",
            message="model package must be non-empty and no larger than 64 MiB",
            status_code=413,
            details={"size_bytes": len(payload), "maximum_bytes": MAX_BUNDLE_BYTES},
        )
    if not payload.startswith(b"PK"):
        raise DomainError(
            code="MODEL_SOURCE_ARCHIVE_INVALID",
            message="model package is not a ZIP archive",
            status_code=422,
        )
    return clean


def inspect_native_bundle(filename: str | None, payload: bytes) -> dict[str, Any]:
    clean = _validate_upload(filename, payload, native=True)
    try:
        with ZipFile(BytesIO(payload)) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if len(infos) > MAX_NATIVE_FILES or sum(item.file_size for item in infos) > MAX_BUNDLE_BYTES:
                raise DomainError(
                    code="NATIVE_BUNDLE_EXPANSION_LIMIT_EXCEEDED",
                    message="native project backup expands beyond its safety limit",
                    status_code=422,
                )
            if len(names) != len(set(names)):
                raise DomainError(
                    code="NATIVE_BUNDLE_DUPLICATE_ENTRY",
                    message="native project backup contains duplicate entries",
                    status_code=422,
                )
            if any(
                name.startswith(("/", "\\"))
                or ".." in name.replace("\\", "/").split("/")
                for name in names
            ):
                raise DomainError(
                    code="NATIVE_BUNDLE_UNSAFE_PATH",
                    message="native project backup contains an unsafe path",
                    status_code=422,
                )
            if "manifest.json" not in names:
                raise DomainError(
                    code="NATIVE_BUNDLE_MANIFEST_MISSING",
                    message="native project backup has no manifest.json",
                    status_code=422,
                )
            manifest_raw = archive.read("manifest.json")
            manifest = json.loads(manifest_raw)
            if not isinstance(manifest, dict) or manifest.get("schema_version") != NATIVE_SCHEMA:
                raise DomainError(
                    code="NATIVE_BUNDLE_SCHEMA_UNSUPPORTED",
                    message="native project backup uses an unsupported schema",
                    status_code=422,
                    details={"schema_version": manifest.get("schema_version") if isinstance(manifest, dict) else None},
                )
            content = manifest.get("content")
            if not isinstance(content, dict) or not content:
                raise DomainError(
                    code="NATIVE_BUNDLE_MANIFEST_INVALID",
                    message="native project backup manifest has no content index",
                    status_code=422,
                )
            for name, metadata in content.items():
                if name not in names or not isinstance(metadata, dict):
                    raise DomainError(
                        code="NATIVE_BUNDLE_ENTRY_MISSING",
                        message="native project backup is missing a manifest entry",
                        status_code=422,
                        details={"entry": name},
                    )
                raw = archive.read(name)
                if sha256(raw).hexdigest() != metadata.get("sha256") or len(raw) != metadata.get("bytes"):
                    raise DomainError(
                        code="NATIVE_BUNDLE_HASH_MISMATCH",
                        message="native project backup entry does not match its manifest",
                        status_code=422,
                        details={"entry": name},
                    )
            dependencies: list[dict[str, Any]] = []
            if "dependencies.json" in content:
                candidate = json.loads(archive.read("dependencies.json"))
                if not isinstance(candidate, list) or any(not isinstance(item, dict) for item in candidate):
                    raise DomainError(
                        code="NATIVE_BUNDLE_DEPENDENCIES_INVALID",
                        message="native project backup dependencies are invalid",
                        status_code=422,
                    )
                dependencies = candidate
    except DomainError:
        raise
    except (BadZipFile, KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DomainError(
            code="NATIVE_BUNDLE_INVALID",
            message="native project backup cannot be read",
            status_code=422,
        ) from exc

    issues = [
        {"code": "EXTERNAL_DEPENDENCY_NOT_BUNDLED", **item}
        for item in dependencies
    ]
    summary = {
        "schema_version": manifest["schema_version"],
        "project_id": manifest.get("project_id"),
        "project_name": manifest.get("project_name"),
        "created_at": manifest.get("created_at"),
        "counts": manifest.get("counts") if isinstance(manifest.get("counts"), dict) else {},
        "manifest_sha256": sha256(manifest_raw).hexdigest(),
    }
    result = {
        "schema_version": "nebula_one.model-source-preview.v1",
        "source_type": "nebula_native_bundle",
        "file_name": clean,
        "file_sha256": _file_sha256(payload),
        "status": "ready",
        "summary": summary,
        "external_dependencies": dependencies,
        "issues": issues,
    }
    result["preview_sha256"] = canonical_json_sha256(result)
    return result


def _tidas_issues(report: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for message in report.get("errors") or []:
        issues.append({"code": "TIDAS_IMPORT_ERROR", "severity": "blocking", "message": str(message)})
    for item in report.get("unresolved_items") or []:
        issues.append({"code": "TIDAS_UNRESOLVED_REFERENCE", "severity": "blocking", "details": item})
    if int(report.get("model_topology_empty_count") or 0) > 0:
        issues.append({"code": "TIDAS_MODEL_TOPOLOGY_EMPTY", "severity": "blocking"})
    if int(report.get("filtered_exchange_count") or 0) > 0:
        issues.append(
            {
                "code": "TIDAS_EXCHANGES_FILTERED",
                "severity": "blocking",
                "count": int(report.get("filtered_exchange_count") or 0),
                "missing_flow_uuids": list(report.get("top_missing_flow_uuids") or []),
            }
        )
    for message in report.get("warnings") or []:
        issues.append({"code": "TIDAS_IMPORT_WARNING", "severity": "warning", "message": str(message)})
    return issues


def _stable_tidas_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in report.items()
        if key not in {"job_id", "created_at", "source_path"}
    }


class ModelSourceService:
    def __init__(
        self,
        database: Database,
        client: NebulaLCAClient,
        system_models: SystemModelService,
    ) -> None:
        self.database = database
        self.client = client
        self.system_models = system_models

    def _require_application(self, application_id: str) -> None:
        with self.database.session() as db:
            if db.get(Application, application_id) is None:
                raise DomainError(
                    code="APPLICATION_NOT_FOUND",
                    message=f"application not found: {application_id}",
                    status_code=404,
                )

    def preview_tidas(self, filename: str | None, payload: bytes) -> dict[str, Any]:
        clean = _validate_upload(filename, payload, native=False)
        receipt = self.client.import_tidas_bundle(
            filename=clean, payload=payload, dry_run=True
        ).payload
        issues = _tidas_issues(receipt)
        blocked = any(item.get("severity") == "blocking" for item in issues)
        result = {
            "schema_version": "nebula_one.model-source-preview.v1",
            "source_type": "tidas_bundle",
            "file_name": clean,
            "file_sha256": _file_sha256(payload),
            "status": "blocked" if blocked else "ready",
            "summary": receipt,
            "external_dependencies": [],
            "issues": issues,
        }
        result["preview_sha256"] = canonical_json_sha256(
            {
                "source_type": result["source_type"],
                "file_sha256": result["file_sha256"],
                "status": result["status"],
                "summary": _stable_tidas_report(receipt),
                "issues": issues,
            }
        )
        return result

    def inspect_native(self, filename: str | None, payload: bytes) -> dict[str, Any]:
        return inspect_native_bundle(filename, payload)

    def _candidates(self, project_ids: list[str]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for project_id in project_ids:
            for version in self.client.list_project_versions(project_id):
                candidates.append(
                    {
                        "project_id": project_id,
                        "version": version["version"],
                        "graph_hash": version.get("graph_hash"),
                        "created_at": version.get("created_at"),
                    }
                )
        return sorted(candidates, key=lambda item: (item["project_id"], item["version"]))

    def _persist_source(
        self,
        *,
        application_id: str,
        name: str,
        source_type: str,
        status: str,
        file_name: str | None,
        file_hash: str | None,
        upstream_project_id: str | None,
        upstream_version: int | None,
        graph_hash: str | None,
        receipt: dict[str, Any],
        candidates: list[dict[str, Any]],
        dependencies: list[dict[str, Any]],
        issues: list[dict[str, Any]],
    ) -> ModelSource:
        content = {
            "application_id": application_id,
            "name": name,
            "source_type": source_type,
            "provider": "nebula_lca",
            "provider_base_url": self.client.base_url,
            "status": status,
            "file_name": file_name,
            "file_sha256": file_hash,
            "upstream_project_id": upstream_project_id,
            "upstream_version": upstream_version,
            "graph_sha256": graph_hash,
            "import_receipt": receipt,
            "candidate_versions": candidates,
            "external_dependencies": dependencies,
            "issues": issues,
        }
        record = ModelSource(**content, content_sha256=canonical_json_sha256(content))
        with self.database.session() as db:
            db.add(record)
            db.commit()
            db.refresh(record)
            return record

    def connect_project(
        self, application_id: str, payload: NebulaProjectSourceCreate
    ) -> tuple[ModelSource, Any, SystemRevision]:
        self._require_application(application_id)
        snapshot = self.client.get_provider_model_snapshot(
            payload.upstream_project_id, payload.upstream_version
        ).payload
        snapshot_graph_hash = canonical_graph_sha256(snapshot["graph"])
        model = self.system_models.attach(
            application_id,
            SystemModelCreate(
                name=payload.name,
                upstream_project_id=payload.upstream_project_id,
                upstream_version=payload.upstream_version,
            ),
            expected_graph_sha256=snapshot_graph_hash,
        )
        snapshot_receipt = {
            key: value
            for key, value in snapshot.items()
            if key != "graph"
        }
        snapshot_receipt["hydrated_graph_sha256"] = snapshot_graph_hash
        source = self._persist_source(
            application_id=application_id,
            name=payload.name,
            source_type="nebula_project_version",
            status="attached",
            file_name=None,
            file_hash=None,
            upstream_project_id=payload.upstream_project_id,
            upstream_version=payload.upstream_version,
            graph_hash=model.graph_sha256,
            receipt={"provider_snapshot": snapshot_receipt},
            candidates=[{"project_id": payload.upstream_project_id, "version": payload.upstream_version, "graph_hash": model.graph_sha256}],
            dependencies=[],
            issues=list(snapshot.get("issues") or []),
        )
        return self._mark_attached(source.id, model.id)

    def import_tidas(
        self,
        application_id: str,
        *,
        name: str,
        filename: str | None,
        payload: bytes,
        confirmed: bool,
        expected_preview_sha256: str,
    ) -> ModelSource:
        self._require_application(application_id)
        if not confirmed:
            raise DomainError(
                code="MODEL_SOURCE_CONFIRMATION_REQUIRED",
                message="TIDAS import requires explicit confirmation",
                status_code=409,
            )
        preview = self.preview_tidas(filename, payload)
        if preview["preview_sha256"] != expected_preview_sha256:
            raise DomainError(
                code="MODEL_SOURCE_PREVIEW_MISMATCH",
                message="uploaded TIDAS bundle no longer matches the confirmed preview",
                status_code=409,
            )
        if preview["status"] != "ready":
            raise DomainError(
                code="TIDAS_IMPORT_PREVIEW_BLOCKED",
                message="TIDAS preview contains blocking issues",
                status_code=422,
                details={"issues": preview["issues"]},
            )
        clean = preview["file_name"]
        receipt = self.client.import_tidas_bundle(
            filename=clean, payload=payload, dry_run=False
        ).payload
        project_ids = [
            str(item.get("project_id"))
            for item in receipt.get("created_projects") or []
            if isinstance(item, dict) and item.get("project_id")
        ]
        candidates = self._candidates(project_ids)
        issues = _tidas_issues(receipt)
        status = "ready_to_attach" if candidates else "blocked"
        if not candidates:
            issues.append({"code": "TIDAS_IMPORT_CREATED_NO_MODEL_VERSION", "severity": "blocking"})
        return self._persist_source(
            application_id=application_id,
            name=_clean_name(name),
            source_type="tidas_bundle",
            status=status,
            file_name=clean,
            file_hash=preview["file_sha256"],
            upstream_project_id=None,
            upstream_version=None,
            graph_hash=None,
            receipt={"preview": preview, "import": receipt},
            candidates=candidates,
            dependencies=[],
            issues=issues,
        )

    def restore_native(
        self,
        application_id: str,
        *,
        name: str,
        filename: str | None,
        payload: bytes,
        confirmed: bool,
        expected_preview_sha256: str,
        conflict_policy: str,
    ) -> ModelSource:
        self._require_application(application_id)
        if not confirmed:
            raise DomainError(
                code="MODEL_SOURCE_CONFIRMATION_REQUIRED",
                message="native project restore requires explicit confirmation",
                status_code=409,
            )
        if conflict_policy not in {"rename", "fail"}:
            raise DomainError(
                code="MODEL_SOURCE_CONFLICT_POLICY_INVALID",
                message="conflict policy must be rename or fail",
                status_code=422,
            )
        preview = self.inspect_native(filename, payload)
        if preview["preview_sha256"] != expected_preview_sha256:
            raise DomainError(
                code="MODEL_SOURCE_PREVIEW_MISMATCH",
                message="uploaded native bundle no longer matches the confirmed preview",
                status_code=409,
            )
        receipt = self.client.restore_native_bundle(
            filename=preview["file_name"],
            payload=payload,
            conflict_policy=conflict_policy,
        ).payload
        project_id = str(receipt["project_id"])
        candidates = self._candidates([project_id])
        dependencies = list(preview["external_dependencies"])
        issues = list(receipt.get("issues") or [])
        if not candidates:
            issues.append({"code": "NATIVE_RESTORE_CREATED_NO_MODEL_VERSION", "severity": "blocking"})
        return self._persist_source(
            application_id=application_id,
            name=_clean_name(name),
            source_type="nebula_native_bundle",
            status="ready_to_attach" if candidates else "blocked",
            file_name=preview["file_name"],
            file_hash=preview["file_sha256"],
            upstream_project_id=project_id,
            upstream_version=None,
            graph_hash=None,
            receipt={"inspection": preview, "restore": receipt},
            candidates=candidates,
            dependencies=dependencies,
            issues=issues,
        )

    def attach(
        self, source_id: str, payload: ModelSourceAttachCreate
    ) -> tuple[ModelSource, Any, SystemRevision]:
        with self.database.session() as db:
            source = db.get(ModelSource, source_id)
            if source is None:
                raise DomainError(
                    code="MODEL_SOURCE_NOT_FOUND",
                    message=f"model source not found: {source_id}",
                    status_code=404,
                )
            if source.status != "ready_to_attach":
                raise DomainError(
                    code="MODEL_SOURCE_NOT_ATTACHABLE",
                    message="model source is not ready to attach",
                    status_code=409,
                    details={"status": source.status},
                )
            allowed = {
                (str(item.get("project_id")), item.get("version"))
                for item in source.candidate_versions
                if isinstance(item, dict)
            }
            if (payload.upstream_project_id, payload.upstream_version) not in allowed:
                raise DomainError(
                    code="MODEL_SOURCE_VERSION_NOT_OFFERED",
                    message="selected project version was not returned by the import or restore",
                    status_code=409,
                )
            application_id = source.application_id
            source_name = source.name
            dependencies = list(source.external_dependencies)
        model = self.system_models.attach(
            application_id,
            SystemModelCreate(
                name=source_name,
                upstream_project_id=payload.upstream_project_id,
                upstream_version=payload.upstream_version,
            ),
        )
        if dependencies:
            with self.database.session() as db:
                stored_model = db.get(type(model), model.id)
                receipt = dict(stored_model.upstream_receipt)
                receipt["model_source_id"] = source_id
                receipt["external_dependencies"] = dependencies
                receipt["solve_readiness"] = "blocked_missing_dependencies"
                stored_model.upstream_receipt = receipt
                db.commit()
                db.refresh(stored_model)
                model = stored_model
        return self._mark_attached(source_id, model.id)

    def _mark_attached(self, source_id: str, system_model_id: str):
        with self.database.session() as db:
            source = db.get(ModelSource, source_id)
            model = db.get(SystemModel, system_model_id)
            source.system_model_id = system_model_id
            source.status = "attached"
            source.upstream_project_id = model.upstream_project_id
            source.upstream_version = model.upstream_version
            source.graph_sha256 = model.graph_sha256
            source.attached_at = datetime.now(timezone.utc)
            content = {
                "application_id": source.application_id,
                "name": source.name,
                "source_type": source.source_type,
                "provider": source.provider,
                "provider_base_url": source.provider_base_url,
                "status": source.status,
                "file_name": source.file_name,
                "file_sha256": source.file_sha256,
                "upstream_project_id": source.upstream_project_id,
                "upstream_version": source.upstream_version,
                "graph_sha256": source.graph_sha256,
                "import_receipt": source.import_receipt,
                "candidate_versions": source.candidate_versions,
                "external_dependencies": source.external_dependencies,
                "issues": source.issues,
                "system_model_id": source.system_model_id,
            }
            source.content_sha256 = canonical_json_sha256(content)
            revision = db.scalar(
                select(SystemRevision).where(
                    SystemRevision.system_model_id == system_model_id,
                    SystemRevision.revision_number == 1,
                )
            )
            db.commit()
            db.refresh(source)
            return source, model, revision

    def list_for_application(self, application_id: str) -> list[ModelSource]:
        self._require_application(application_id)
        with self.database.session() as db:
            return list(
                db.scalars(
                    select(ModelSource)
                    .where(ModelSource.application_id == application_id)
                    .order_by(ModelSource.created_at.desc())
                )
            )

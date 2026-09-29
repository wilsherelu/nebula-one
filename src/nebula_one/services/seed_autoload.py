"""Declarative boot-time seed installation: run the CLI's existing steps from a pinned file.

The manifest is an ordered list of steps, not a dependency graph: the install gates already
refuse an out-of-order seed, so this layer must not invent a second ordering rule. See
docs/STANDARD_SEED_ENTERPRISE_PERIOD_AND_AUTOLOAD_V1.md section 3.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError

from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..runtime_schemas import MethodPackageCreate, PeriodCreate
from ..schemas import ApplicationCreate
from ..seeds import standard_seed_bundle
from ..seeds.prepare_open_supply_flow import ensure_open_supply_flow, open_flow_pins
from .applications import ApplicationService
from .registry import RegistryService
from .seed_installation import SeedInstallationService
from .public_supply_seed import ensure_public_supply_seed

logger = logging.getLogger(__name__)

AUTOLOAD_SCHEMA_VERSION = "nebula_one.seed_autoload.v1"
STEP_KINDS = ("register_method_package", "ensure_application", "ensure_period", "install_seed", "ensure_open_tiangong_flows", "ensure_public_supply", "ensure_template_editor_source", "ensure_demo_project")
# the same derivation the seed identity contract uses, so a concurrent boot collides on the
# primary key instead of creating a second application for the same key
APPLICATION_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://nebula-one.app/seed-autoload")
DEMO_DISPLAY_LANGUAGES = ("zh", "en")


def application_id_for(key: str) -> str:
    return str(uuid.uuid5(APPLICATION_NAMESPACE, f"application|{key}"))


def _file_invalid(message: str, **details: Any) -> DomainError:
    return DomainError(
        code="SEED_AUTOLOAD_FILE_INVALID",
        message=message,
        status_code=422,
        details=details,
    )


def _not_pinned(message: str, **details: Any) -> DomainError:
    return DomainError(
        code="SEED_AUTOLOAD_VERSION_NOT_PINNED",
        message=message,
        status_code=422,
        details=details,
    )


def _drift(code: str, message: str, status_code: int = 409, **details: Any) -> DomainError:
    return DomainError(code=code, message=message, status_code=status_code, details=details)


class SeedAutoloadService:
    def __init__(
        self,
        applications: ApplicationService,
        registry: RegistryService,
        seed_installation: SeedInstallationService,
        autoload_file: str | None,
    ) -> None:
        self.applications = applications
        self.registry = registry
        self.seed_installation = seed_installation
        self.autoload_file = autoload_file
        self.seed_projects = None

    def run(self) -> dict[str, Any]:
        if not self.autoload_file:
            return {"schema_version": AUTOLOAD_SCHEMA_VERSION, "result": "disabled", "steps": []}
        try:
            steps = self._read_steps(Path(self.autoload_file))
        except DomainError as error:
            logger.error("seed autoload manifest refused: %s %s", error.code, error.message)
            return {
                "schema_version": AUTOLOAD_SCHEMA_VERSION,
                "result": "refused",
                "file": self.autoload_file,
                "steps": [
                    {
                        "step_index": None,
                        "kind": "manifest",
                        "outcome": "refused",
                        "code": error.code,
                        "message": error.message,
                        "details": error.details,
                    }
                ],
            }
        return self._run_steps(steps)

    def _run_steps(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        result = "completed"
        for index, step in enumerate(steps):
            kind = str(step.get("kind"))
            try:
                outcome, identities = self._dispatch(kind, step)
            except DomainError as error:
                # the declared order is the dependency order, so continuing would build on a
                # reality this run did not create; the rest is skipped, never marked passed
                result = "refused"
                records.append(
                    {
                        "step_index": index,
                        "kind": kind,
                        "outcome": "refused",
                        "code": error.code,
                        "message": error.message,
                        "details": error.details,
                    }
                )
                for skipped in range(index + 1, len(steps)):
                    records.append(
                        {
                            "step_index": skipped,
                            "kind": str(steps[skipped].get("kind")),
                            "outcome": "not_attempted_after_failure",
                            "code": error.code,
                            "message": "an earlier step was refused, so this step never ran",
                        }
                    )
                logger.error(
                    "seed autoload step %d (%s) refused: %s %s", index, kind, error.code, error.message
                )
                break
            except Exception as error:  # boot must survive anything a step raises underneath
                result = "refused"
                records.append(
                    {
                        "step_index": index,
                        "kind": kind,
                        "outcome": "refused",
                        "code": "SEED_AUTOLOAD_STEP_ERROR",
                        "message": f"{type(error).__name__}: {error}",
                    }
                )
                for skipped in range(index + 1, len(steps)):
                    records.append(
                        {
                            "step_index": skipped,
                            "kind": str(steps[skipped].get("kind")),
                            "outcome": "not_attempted_after_failure",
                            "code": "SEED_AUTOLOAD_STEP_ERROR",
                            "message": "an earlier step failed, so this step never ran",
                        }
                    )
                logger.exception("seed autoload step %d (%s) failed", index, kind)
                break
            records.append(
                {
                    "step_index": index,
                    "kind": kind,
                    "outcome": outcome,
                    "identities": identities,
                }
            )
        return {
            "schema_version": AUTOLOAD_SCHEMA_VERSION,
            "result": result,
            "file": self.autoload_file,
            "steps": records,
        }

    def _dispatch(self, kind: str, step: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if kind == "ensure_open_tiangong_flows":
            if (self._required(step, "seed"), self._required(step, "version")) != (
                "nebula.iron-steel.bf-bof-crude-steel", "1.1.0"
            ):
                raise _file_invalid("open Flow step does not name the steel seed")
            if step.get("flows") != open_flow_pins():
                raise _file_invalid("steel open Flow declarations differ from pinned assets")
            flows = ensure_open_supply_flow(self.seed_installation.client)
            return ("executed" if flows["status"] == "imported" or flows["co2_flow"]["status"] == "imported" else "replayed"), flows
        if kind == "register_method_package":
            return self._register_method_package(step)
        if kind == "ensure_application":
            return self._ensure_application(step)
        if kind == "ensure_period":
            return self._ensure_period(step)
        if kind == "install_seed":
            return self._install_seed(step)
        if kind == "ensure_public_supply":
            return ensure_public_supply_seed(
                self.seed_installation.client,
                path=self._repo_path(self._required(step, "path")),
                declared_hash=self._required(step, "content_sha256"),
                seed_id=self._required(step, "seed_id"),
                seed_version=self._required(step, "version"),
            )
        if kind == "ensure_template_editor_source":
            seed = self._required(step, "seed")
            version = self._required(step, "version")
            declared_hash = self._required(step, "bundle_content_sha256")
            row = self.seed_installation.find_installation(seed, version)
            if row is None or row.status != "ready" or row.bundle_content_sha256 != declared_hash:
                raise _drift("SEED_TEMPLATE_SOURCE_UNAVAILABLE", "the exact installed seed is not ready",
                             seed=seed, version=version, bundle_content_sha256=declared_hash)
            if self.seed_projects is None:
                raise _drift("SEED_TEMPLATE_SOURCE_UNAVAILABLE", "template editor source service is unavailable")
            return self.seed_projects.ensure_editor_source(row.id)
        if kind == "ensure_demo_project":
            return self._ensure_demo_project(step)
        raise _file_invalid("unknown autoload step kind", kind=kind, allowed=list(STEP_KINDS))

    # ---------- manifest ----------

    def _read_steps(self, path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            raise _file_invalid("the autoload file does not exist", path=str(path))
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise _file_invalid(
                "the autoload file is not valid JSON", path=str(path), error=str(error)
            ) from error
        if not isinstance(document, dict):
            raise _file_invalid("the autoload file must hold a JSON object", path=str(path))
        if document.get("schema_version") != AUTOLOAD_SCHEMA_VERSION:
            raise _file_invalid(
                "the autoload schema_version is not the pinned one",
                path=str(path),
                expected=AUTOLOAD_SCHEMA_VERSION,
                found=document.get("schema_version"),
            )
        steps = document.get("steps")
        if not isinstance(steps, list) or not steps:
            raise _file_invalid("the autoload steps must be a non-empty list", path=str(path))
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise _file_invalid("an autoload step is not an object", step_index=index)
        return steps

    def _required(self, step: dict[str, Any], field: str) -> str:
        value = str(step.get(field) or "").strip()
        if not value:
            raise _not_pinned(
                "an autoload step is missing a required pinned value",
                kind=str(step.get("kind")),
                field=field,
            )
        if value.lower() in {"latest", "next", "*"}:
            raise _not_pinned(
                "an autoload step resolved to a moving reference",
                kind=str(step.get("kind")),
                field=field,
                found=value,
            )
        return value

    def _repo_path(self, relative: str) -> Path:
        candidate = Path(relative)
        return candidate if candidate.is_absolute() else standard_seed_bundle.REPO_ROOT / candidate

    # ---------- steps ----------

    def _ensure_demo_project(self, step: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        seed = self._required(step, "seed")
        version = self._required(step, "version")
        declared_hash = self._required(step, "bundle_content_sha256")
        key = self._required(step, "key")
        declared_names = step.get("display_name")
        if not isinstance(declared_names, dict) or set(declared_names) != set(DEMO_DISPLAY_LANGUAGES):
            raise _file_invalid(
                "a demo project step must declare exactly a zh and an en display name",
                key=key,
                found=sorted(declared_names) if isinstance(declared_names, dict) else type(declared_names).__name__,
            )
        display_name = {}
        for language in DEMO_DISPLAY_LANGUAGES:
            text = str(declared_names[language] or "").strip()
            if not text:
                raise _file_invalid("a demo project display name is blank", key=key, language=language)
            display_name[language] = text
        if self.seed_projects is None:
            raise _drift("SEED_TEMPLATE_SOURCE_UNAVAILABLE", "seed project service is unavailable")
        return self.seed_projects.ensure_demo_project(seed, version, declared_hash, key, display_name)

    def _register_method_package(self, step: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        declared_id = self._required(step, "package_id")
        declared_version = self._required(step, "version")
        declared_hash = self._required(step, "content_sha256")
        path = self._repo_path(self._required(step, "path"))
        if not path.is_file():
            raise _file_invalid("the declared method package file is absent", path=str(path))
        try:
            payload = MethodPackageCreate.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError) as error:
            raise _file_invalid(
                "the declared method package file does not validate",
                path=str(path),
                error=str(error),
            ) from error
        if (payload.package_id, payload.version) != (declared_id, declared_version):
            raise _file_invalid(
                "the autoload step and the package file disagree about the package identity",
                declared=f"{declared_id}@{declared_version}",
                found=f"{payload.package_id}@{payload.version}",
            )
        content = payload.model_dump(mode="json")
        actual_hash = canonical_json_sha256(content)
        if actual_hash != declared_hash:
            raise _drift(
                "SEED_AUTOLOAD_HASH_DRIFT",
                "the declared method package hash does not match the file on disk",
                package_id=declared_id,
                version=declared_version,
                declared_content_sha256=declared_hash,
                actual_content_sha256=actual_hash,
            )
        # the hash check above happens before anything is written anywhere
        existing = self.registry.find_method_package(declared_id, declared_version)
        if existing is not None:
            if existing.content_sha256 == actual_hash:
                return "replayed", {
                    "package_id": declared_id,
                    "version": declared_version,
                    "content_sha256": actual_hash,
                }
            raise _drift(
                "SEED_AUTOLOAD_PACKAGE_CONFLICT",
                "this package version is already registered with different bytes",
                package_id=declared_id,
                version=declared_version,
                declared_content_sha256=actual_hash,
                existing_content_sha256=existing.content_sha256,
            )
        try:
            self.registry.register_method_package(payload)
        except DomainError as error:
            if error.code != "METHOD_PACKAGE_VERSION_CONFLICT":
                raise
            # another boot inserted it in the meantime: same bytes replay, different bytes conflict
            recorded = self.registry.find_method_package(declared_id, declared_version)
            if recorded is not None and recorded.content_sha256 == actual_hash:
                return "replayed", {
                    "package_id": declared_id,
                    "version": declared_version,
                    "content_sha256": actual_hash,
                }
            raise _drift(
                "SEED_AUTOLOAD_PACKAGE_CONFLICT",
                "this package version was registered concurrently with different bytes",
                package_id=declared_id,
                version=declared_version,
                declared_content_sha256=actual_hash,
                existing_content_sha256=(recorded.content_sha256 if recorded else None),
            ) from error
        return "executed", {
            "package_id": declared_id,
            "version": declared_version,
            "content_sha256": actual_hash,
        }

    def _ensure_application(self, step: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        key = self._required(step, "key")
        application_id = application_id_for(key)
        payload = ApplicationCreate(
            name=self._required(step, "name"),
            application_type=self._required(step, "application_type"),
            description=step.get("description"),
            context={"method_package_refs": [str(ref) for ref in step.get("method_package_refs") or []]},
        )
        try:
            existing = self.applications.get(application_id)
        except DomainError as error:
            if error.code != "APPLICATION_NOT_FOUND":
                raise
            try:
                created = self.applications.create(payload, application_id=application_id)
            except IntegrityError:
                created = self.applications.get(application_id)
                self._compare_application(key, created, payload)
                return "replayed", {"application_key": key, "application_id": created.id}
            return "executed", {"application_key": key, "application_id": created.id}
        self._compare_application(key, existing, payload)
        return "replayed", {"application_key": key, "application_id": existing.id}

    def _compare_application(
        self, key: str, existing: Any, payload: ApplicationCreate
    ) -> None:
        declared_refs = list((payload.context or {}).get("method_package_refs") or [])
        bound_refs = list((existing.context or {}).get("method_package_refs") or [])
        if existing.application_type != payload.application_type or not set(
            declared_refs
        ).issubset(set(bound_refs)):
            raise _drift(
                "SEED_AUTOLOAD_APPLICATION_DRIFT",
                "an application already exists under this autoload key with different content",
                application_key=key,
                application_id=existing.id,
                declared_application_type=payload.application_type,
                found_application_type=existing.application_type,
                declared_method_package_refs=declared_refs,
                bound_method_package_refs=bound_refs,
            )

    def _ensure_period(self, step: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        application_key = self._required(step, "application_key")
        application_id = application_id_for(application_key)
        application = self.applications.get(application_id)
        period_key = self._required(step, "key")
        payload = PeriodCreate(
            key=period_key,
            name=self._required(step, "name"),
            start_date=self._required(step, "start_date"),
            end_date=self._required(step, "end_date"),
            resolution=self._required(step, "resolution"),
        )
        existing = self.registry.find_period(application.id, period_key)
        if existing is not None:
            self._compare_period(application_key, existing, payload)
            return "replayed", {
                "application_key": application_key,
                "period_key": period_key,
                "period_id": existing.id,
            }
        try:
            created = self.registry.create_period(application.id, payload)
        except DomainError as error:
            # create_period turns the unique-constraint hit into this code, so a concurrent boot
            # that won the race lands here rather than on a raw IntegrityError
            if error.code != "PERIOD_KEY_CONFLICT":
                raise
            recorded = self.registry.find_period(application.id, period_key)
            if recorded is None:
                raise
            self._compare_period(application_key, recorded, payload)
            return "replayed", {
                "application_key": application_key,
                "period_key": period_key,
                "period_id": recorded.id,
            }
        return "executed", {
            "application_key": application_key,
            "period_key": period_key,
            "period_id": created.id,
        }

    def _compare_period(self, application_key: str, existing: Any, payload: PeriodCreate) -> None:
        found = {
            "name": existing.name,
            "start_date": existing.start_date.isoformat(),
            "end_date": existing.end_date.isoformat(),
            "resolution": existing.resolution,
        }
        declared = {
            "name": payload.name,
            "start_date": payload.start_date.isoformat(),
            "end_date": payload.end_date.isoformat(),
            "resolution": payload.resolution,
        }
        if found != declared:
            raise _drift(
                "SEED_AUTOLOAD_PERIOD_DRIFT",
                "a period already exists under this key with different dates or resolution",
                application_key=application_key,
                period_key=payload.key,
                period_id=existing.id,
                declared=declared,
                found=found,
            )

    def _install_seed(self, step: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        seed = self._required(step, "seed")
        version = self._required(step, "version")
        declared_hash = self._required(step, "bundle_content_sha256")
        seed_dir = standard_seed_bundle.resolve_seed_directory(seed, None)
        application_id = application_id_for(self._required(step, "application_key"))
        boundary_key = self._required(step, "boundary_key")
        declarations = step.get("declarations") or {}
        if not isinstance(declarations, dict):
            raise _file_invalid(
                "the install_seed declarations must be an object",
                seed=seed,
                found=type(declarations).__name__,
            )
        # validate-only, so the pinned hash is proven before the engine sees a single byte
        planned = self.seed_installation.plan(seed_dir)
        if planned["seed_version"] != version or planned["bundle_content_sha256"] != declared_hash:
            raise _drift(
                "SEED_AUTOLOAD_HASH_DRIFT",
                "the declared seed version or bundle hash does not match the build gate",
                seed=seed,
                declared_version=version,
                built_version=planned["seed_version"],
                declared_bundle_content_sha256=declared_hash,
                built_bundle_content_sha256=planned["bundle_content_sha256"],
                engine_project_id=planned["engine_project_id"],
            )
        # a row that never reached its terminal stage still has work pending, so resuming it
        # is a real run and must not be reported as a replay
        pending = self.seed_installation.find_installation(planned["seed_id"], version)
        already_here = pending is not None and pending.status == "ready"
        row = self.seed_installation.install(
            seed_dir,
            application_id=application_id,
            boundary_key=boundary_key,
            declarations={str(k): str(v) for k, v in declarations.items()},
        )
        return ("replayed" if already_here else "executed"), {
            "seed_id": row.seed_id,
            "seed_version": row.seed_version,
            "installation_id": row.id,
            "application_id": application_id,
            "boundary_key": boundary_key,
            "engine_project_id": row.engine_project_id,
            "status": row.status,
        }

"""Exact accounting-library releases over an unchanged structural template profile."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..model_processing_contract import TemplateRef, PackageRef
from ..runtime_schemas import MethodPackageCreate

LIBRARY_ROOT = Path(__file__).resolve().parents[1] / "resources/template_method_libraries"
METHOD_ROOT = Path(__file__).resolve().parents[1] / "resources/official_methods"


class TaskDeclaration(BaseModel):
    """One reader-facing accounting task and the exact packages that realise it.

    A task names a single default preset plus any other 口径 that belong to the same task, so the
    template workspace shows one row per task instead of one card per internal package. Roles are a
    closed vocabulary; the refs must be drawn from this library's own pinned methods.
    """
    model_config = ConfigDict(extra="forbid")
    role: Literal["complete_model", "cbam", "scope_classification"]
    default_ref: str = Field(min_length=1)
    refs: list[str] = Field(min_length=1)


class TemplateMethodLibrary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["nebula_one.template-method-library.v1"]
    id: str = Field(min_length=1)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    template_profile: TemplateRef
    methods: list[PackageRef] = Field(min_length=1)
    # Optional so an archived release without a task declaration still validates; a new release that
    # omits it simply leaves the workspace on the flat per-package view.
    tasks: list[TaskDeclaration] | None = None

    @model_validator(mode="after")
    def _tasks_reference_own_methods(self) -> "TemplateMethodLibrary":
        if self.tasks is None:
            return self
        pinned = {f"{pin.package_id}@{pin.version}" for pin in self.methods}
        seen: set[str] = set()
        for task in self.tasks:
            if task.role in seen:
                raise ValueError(f"duplicate task role {task.role}")
            seen.add(task.role)
            if task.default_ref not in task.refs:
                raise ValueError(f"task {task.role} default_ref is not one of its refs")
            unknown = [ref for ref in task.refs if ref not in pinned]
            if unknown:
                raise ValueError(f"task {task.role} references unpinned methods {unknown}")
        return self


def load_template_method_library(profile: dict | None, *, library_root=None, method_root=None):
    """Read one explicit release; do not select method heads or mutate a stored project.

    A library version changes the reader-facing template release while its exact
    structural profile remains authoritative for graph derivation and old replay.
    Only a new template instance receives this library's declared method pins.
    Archived releases live below archive/ and are not default candidates; callers
    auditing an older release can pass that directory explicitly.
    """
    if not profile:
        return None
    matches = []
    for path in sorted(Path(library_root or LIBRARY_ROOT).glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            library = TemplateMethodLibrary.model_validate(raw)
        except (ValueError, ValidationError) as exc:
            raise DomainError(code="TEMPLATE_METHOD_LIBRARY_INVALID", message="核算方案集格式无效。",
                              status_code=409, details={"file": path.name}) from exc
        if library.template_profile.model_dump() == profile:
            matches.append((raw, library))
    if not matches:
        return None
    if len(matches) != 1:
        raise DomainError(code="TEMPLATE_METHOD_LIBRARY_AMBIGUOUS", message="同一模型模板存在多个默认核算方案集。", status_code=409)
    raw, library = matches[0]
    refs = [f"{pin.package_id}@{pin.version}" for pin in library.methods]
    if len(set(refs)) != len(refs):
        raise DomainError(code="TEMPLATE_METHOD_LIBRARY_DUPLICATE", message="核算方案集存在重复方法。", status_code=409)
    packages = []
    for pin in library.methods:
        matches = []
        for path in sorted(Path(method_root or METHOD_ROOT).glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if (data.get("package_id"), data.get("version")) == (pin.package_id, pin.version):
                matches.append(MethodPackageCreate.model_validate(data))
        if len(matches) != 1:
            raise DomainError(code="TEMPLATE_METHOD_LIBRARY_PACKAGE_UNRESOLVED", message="核算方案的精确方法版本不存在或不唯一。",
                              status_code=409, details={"package_id": pin.package_id, "version": pin.version})
        package = matches[0]
        digest = canonical_json_sha256(package.model_dump(mode="json"))
        if digest != pin.content_sha256 or package.manifest.get("template_profile") != profile:
            raise DomainError(code="TEMPLATE_METHOD_LIBRARY_PIN_MISMATCH", message="核算方案的方法内容或适用模型与声明不一致。",
                              status_code=409, details={"package_id": pin.package_id, "version": pin.version})
        packages.append((package, digest))
    return {"id": library.id, "version": library.version, "content_sha256": canonical_json_sha256(raw),
            "template_profile": profile, "methods": [pin.model_dump() for pin in library.methods],
            "tasks": [task.model_dump() for task in library.tasks] if library.tasks else None}, packages

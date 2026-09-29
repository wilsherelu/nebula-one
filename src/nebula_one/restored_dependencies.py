"""Register the superseded method packages that archived model-processing rules still cite.

A rule package stays loadable after it is superseded, because a project imported from the template
revision it was reviewed against must derive under the rules that revision was reviewed for. Those
rules cite method packages by exact content hash, so a citation this repository cannot hand back makes
that project's purpose uncomputable - not the newest one's, only that project's. The archive under
``cases/restored-dependencies`` holds the complete registration payload for such a package, and this
module is the gate that keeps the ledger and the tracked bytes saying the same thing.

Nothing here computes or interprets an emission. It reads a package, re-checks its identity and says
where the ledger claims it is cited from.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .errors import DomainError
from .hashing import canonical_json_sha256
from .model_processing_contract import RESOURCE_DIRECTORY
from .runtime_schemas import MethodPackageCreate

ARCHIVE_DIRECTORY = Path("cases/restored-dependencies")
LEDGER_FILE = "method-packages.json"
LEDGER_SCHEMA_VERSION = "nebula_one.restored-method-packages.v1"
_IDENTITY_FIELDS = ("package_id", "version", "package_kind", "jurisdiction")


def _refuse(code: str, message: str, **details: Any) -> None:
    raise DomainError(code=code, message=message, status_code=422, details=details)


@dataclass(frozen=True)
class RestoredMethodPackage:
    """One archived package this repository can hand back, with the identity it was verified to."""

    package_id: str
    version: str
    package_kind: str
    jurisdiction: str | None
    content_sha256: str
    path: Path
    payload: dict[str, Any]
    cited_by: tuple[dict[str, Any], ...]

    def autoload_step(self) -> dict[str, Any]:
        """The seed autoload step that registers this package on a fresh acceptance stack."""
        return {
            "kind": "register_method_package",
            "path": self.path.as_posix(),
            "package_id": self.package_id,
            "version": self.version,
            "package_kind": self.package_kind,
            "content_sha256": self.content_sha256,
        }


def _walk(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def rule_package_citations(*, repository_root: Path | None = None) -> list[tuple[str, dict]]:
    """Every method-package citation made by a tracked model-processing rule package.

    Returned as ``(rule file name, citation)`` pairs in load order, so a caller can ask which rule
    pins which package content without walking the resource directory itself.
    """
    directory = (repository_root or Path(".")) / Path("src") / "nebula_one" / RESOURCE_DIRECTORY
    citations: list[tuple[str, dict]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _refuse(
                "MODEL_PROCESSING_PACKAGE_UNREADABLE",
                f"cannot read the model processing package {path}: {exc}",
                path=str(path),
            )
            continue  # pragma: no cover - _refuse always raises
        for node in _walk(payload):
            if {"package_id", "version", "content_sha256"} <= set(node):
                citations.append((path.name, node))
    return citations


def load_restored_method_packages(
    *, archive_directory: Path = ARCHIVE_DIRECTORY
) -> list[RestoredMethodPackage]:
    """Every archived package the ledger declares, verified against the tracked bytes and rules."""
    ledger_path = archive_directory / LEDGER_FILE
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _refuse(
            "RESTORED_PACKAGE_LEDGER_UNREADABLE",
            f"the restored dependency ledger cannot be read: {exc}",
            path=str(ledger_path),
        )
        return []  # pragma: no cover - _refuse always raises
    if ledger.get("schema_version") != LEDGER_SCHEMA_VERSION:
        _refuse(
            "RESTORED_PACKAGE_LEDGER_UNSUPPORTED",
            f"the restored dependency ledger must declare {LEDGER_SCHEMA_VERSION}",
            schema_version=ledger.get("schema_version"),
        )
    if not str(ledger.get("license") or "").strip():
        _refuse(
            "RESTORED_PACKAGE_LICENSE_UNDISCLOSED",
            "a restored package is distributed with this repository, so the ledger must state its"
            " license",
            path=str(ledger_path),
        )
    entries = ledger.get("entries")
    if not isinstance(entries, list) or not entries:
        _refuse(
            "RESTORED_PACKAGE_LEDGER_EMPTY",
            "the restored dependency ledger declares no package",
            path=str(path),
        )
    citations = rule_package_citations()
    restored: list[RestoredMethodPackage] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        package = _verify_entry(entry, archive_directory, citations)
        key = (package.package_id, package.version)
        if key in seen:
            _refuse(
                "RESTORED_PACKAGE_DUPLICATE_IDENTITY",
                f"the ledger declares {key[0]}@{key[1]} twice",
                package_id=package.package_id,
                version=package.version,
            )
        seen.add(key)
        restored.append(package)
    return restored


def _verify_entry(
    entry: Any, archive_directory: Path, citations: list[tuple[str, dict]]
) -> RestoredMethodPackage:
    if not isinstance(entry, dict):
        _refuse("RESTORED_ENTRY_NOT_AN_OBJECT", "a restored dependency entry must be an object")
        return None  # pragma: no cover - _refuse always raises
    identity = {field: str(entry.get(field) or "") for field in _IDENTITY_FIELDS[:2]}
    label = f"{identity['package_id']}@{identity['version']}"
    declared = str(entry.get("content_sha256") or "")
    relative = str(entry.get("file") or "")
    path = archive_directory / relative
    if not relative or ".." in Path(relative).parts:
        _refuse(
            "RESTORED_ENTRY_PATH_INVALID",
            f"the restored dependency entry for {label} does not name a file inside the archive",
            file=relative,
        )
    if not path.is_file():
        _refuse(
            "RESTORED_ENTRY_FILE_ABSENT",
            f"the ledger names a restored package file that is not in this repository: {path}",
            package_id=identity["package_id"],
            version=identity["version"],
            path=str(path),
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        registered = MethodPackageCreate(**payload).model_dump(mode="json")
    except (json.JSONDecodeError, ValueError) as exc:
        _refuse(
            "RESTORED_ENTRY_UNREGISTERABLE",
            f"the restored package {label} does not validate as a registration payload: {exc}",
            path=str(path),
        )
        return None  # pragma: no cover - _refuse always raises
    # the registry hashes the create document, so a file carrying a field the model drops would give
    # this one package two identities
    if canonical_json_sha256(payload) != canonical_json_sha256(registered):
        _refuse(
            "RESTORED_ENTRY_IDENTITY_SPLIT",
            f"the restored package {label} carries fields the registry would drop",
            path=str(path),
        )
    content_sha256 = canonical_json_sha256(registered)
    if content_sha256 != declared:
        _refuse(
            "RESTORED_ENTRY_HASH_MISMATCH",
            f"the restored package {label} is not the content the ledger pins",
            path=str(path),
            declared_content_sha256=declared,
            actual_content_sha256=content_sha256,
        )
    for field in _IDENTITY_FIELDS:
        if entry.get(field) != registered[field]:
            _refuse(
                "RESTORED_ENTRY_IDENTITY_MISMATCH",
                f"the restored dependency ledger and the tracked bytes disagree about {field}",
                package_id=registered["package_id"],
                version=registered["version"],
                field=field,
                declared=entry.get(field),
                tracked=registered[field],
            )

    cited = [
        (source, node)
        for source, node in citations
        if (node["package_id"], node["version"]) == (registered["package_id"], registered["version"])
    ]
    if not cited:
        _refuse(
            "RESTORED_ENTRY_NOT_CITED",
            f"{label} is archived but no tracked model processing rule cites it; an archived"
            " package exists only to answer a citation",
            package_id=label,
        )
    if {node["content_sha256"] for _, node in cited} != {declared}:
        _refuse(
            "RESTORED_ENTRY_CITATION_DRIFT",
            f"a tracked rule cites {label} at a content hash the archived bytes do not reproduce",
            package_id=registered["package_id"],
            version=registered["version"],
            cited_hashes=sorted({node["content_sha256"] for _, node in cited}),
            archived_hash=declared,
        )
    declared_by = {
        str(Path(str(item.get("rules_file") or "")).name)
        for item in entry.get("cited_by") or []
    }
    if declared_by != {source for source, _ in cited}:
        _refuse(
            "RESTORED_ENTRY_CITATION_UNDISCLOSED",
            f"the ledger does not name every tracked rule package that cites {label}",
            declared=sorted(declared_by),
            found=sorted({source for source, _ in cited}),
        )
    return RestoredMethodPackage(
        package_id=registered["package_id"],
        version=registered["version"],
        package_kind=registered["package_kind"],
        jurisdiction=registered["jurisdiction"],
        content_sha256=content_sha256,
        path=path,
        payload=registered,
        cited_by=tuple(entry.get("cited_by") or ()),
    )

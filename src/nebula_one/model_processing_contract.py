"""Versioned model-processing rules: what each accounting purpose does to the model before solving.

Nebula LCA solves the graph it is handed, so "compute CBAM without the embedded supply chain" cannot
be a flag on a request or a branch inside a page - it has to be a reviewed, versioned statement about
which processes, background links and boundary exchanges a purpose keeps. This module loads and
validates those statements; `model_derivation.py` executes them. Neither computes an emission.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from copy import deepcopy
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .errors import DomainError
from .hashing import canonical_json_sha256
from .emission_selectors import selector_matches

MODEL_PROCESSING_SCHEMA_VERSION = "nebula_one.model-processing-rules.v1"
SHA256_HEX = re.compile(r"[0-9a-f]{64}")
# The resource directory is read with `Path.iterdir`, which importlib.resources only allows for a
# real filesystem package directory; a zipped install therefore falls back to the on-disk path.
RESOURCE_DIRECTORY = "resources/model_processing"


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _ref(value: str, subject: str) -> str:
    if not SHA256_HEX.fullmatch(value or ""):
        raise ValueError(f"{subject} must carry a sha256 content hash")
    return value


class PackageRef(_Frozen):
    package_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    content_sha256: str

    @field_validator("content_sha256")
    @classmethod
    def require_hash(cls, value: str) -> str:
        return _ref(value, "a bound method package")


class TemplateRef(_Frozen):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    content_sha256: str

    @field_validator("content_sha256")
    @classmethod
    def require_hash(cls, value: str) -> str:
        return _ref(value, "the bound project template")


class ProcessSelection(_Frozen):
    mode: Literal["all_model_processes", "method_package_boundary"]
    method_package: PackageRef | None = None
    process_uuids_path: str | None = None

    @model_validator(mode="after")
    def require_boundary_source(self) -> "ProcessSelection":
        if self.mode == "method_package_boundary" and not (
            self.method_package and self.process_uuids_path
        ):
            raise ValueError(
                "a method package boundary must name the package and the manifest path holding its process uuids"
            )
        if self.mode == "all_model_processes" and (
            self.method_package or self.process_uuids_path
        ):
            raise ValueError("all_model_processes must not carry a boundary source")
        return self


class BackgroundEvidence(_Frozen):
    method_package: PackageRef
    manifest_path: str = Field(min_length=1)
    required_value: bool
    clause: str = Field(min_length=1)


class BackgroundDisposition(_Frozen):
    mode: Literal[
        "retain_saved_pins", "unlink_all_background_links", "keep_declared_links_only"
    ]
    evidence: BackgroundEvidence | None = None
    retained_consumer_exchange_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_unlink_evidence(self) -> "BackgroundDisposition":
        if self.mode == "retain_saved_pins":
            if self.evidence is not None:
                raise ValueError("retaining saved pins must not cite method evidence")
            if self.retained_consumer_exchange_ids:
                raise ValueError("only keep_declared_links_only may list retained associations")
            return self
        if self.evidence is None:
            raise ValueError(
                f"{self.mode} must cite the method package declaration that justifies dropping links"
            )
        if self.mode == "keep_declared_links_only":
            if not self.retained_consumer_exchange_ids:
                raise ValueError(
                    "keep_declared_links_only must declare which background associations it retains"
                )
            if len(self.retained_consumer_exchange_ids) != len(
                set(self.retained_consumer_exchange_ids)
            ):
                raise ValueError("a retained background association is declared twice")
        elif self.retained_consumer_exchange_ids:
            raise ValueError("only keep_declared_links_only may list retained associations")
        return self


class BoundaryExchange(_Frozen):
    """A declared replacement for an edge that process selection would otherwise cut."""

    exchange_id: str = Field(min_length=1)
    disposition: Literal["keep_as_boundary_input"]
    amount_source: Literal["consumer_port_amount"]
    clause: str = Field(min_length=1)


class CrossBoundaryConnections(_Frozen):
    mode: Literal["keep_internal_edges", "reject_undeclared"]
    boundary_exchanges: list[BoundaryExchange] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_unique_exchanges(self) -> "CrossBoundaryConnections":
        keys = [item.exchange_id for item in self.boundary_exchanges]
        if len(keys) != len(set(keys)):
            raise ValueError("a boundary exchange declaration appears twice")
        if self.mode == "keep_internal_edges" and keys:
            raise ValueError(
                "keep_internal_edges does not cut edges, so it must not declare boundary exchanges"
            )
        return self


class ElementaryFlowEvidence(_Frozen):
    method_package: PackageRef
    manifest_path: str = Field(min_length=1)
    applicable_gases_path: str | None = None


class ExchangeClassification(_Frozen):
    """One reviewed decision about one emission exchange of one process instance.

    The key is the exchange, never the flow: the same standard flow leaving two instances is two
    decisions, and an emission the method does not count still has to be *said* not to be counted -
    `clause` is what separates a reviewed exclusion from an omission. Extra fields are ignored here
    because they carry the exact flow identity the deriver compares against the model, which this
    class deliberately does not restate: two spellings of an identity could disagree.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    exchange_id: str = Field(min_length=1)
    process_uuid: str = Field(min_length=1)
    disposition: Literal["include", "exclude"]
    clause: str = Field(min_length=1)


EXCHANGE_DISPOSITIONS = ("include", "exclude")


class ElementaryFlows(_Frozen):
    """Either the template's emission set already is the purpose's set, or a method classifies it."""

    mode: Literal["not_applicable", "template_prelimited", "explicit_flow_rules", "identity_selector_rules"]
    evidence: ElementaryFlowEvidence | None = None

    @model_validator(mode="after")
    def require_source(self) -> "ElementaryFlows":
        if self.mode in ("template_prelimited", "explicit_flow_rules", "identity_selector_rules") and self.evidence is None:
            raise ValueError(
                "an emission set a method package decides must cite that package and the manifest"
                " path holding its declarations"
            )
        if self.mode == "not_applicable" and self.evidence is not None:
            raise ValueError("not_applicable must not carry a flow source")
        return self


class Precursors(_Frozen):
    mode: Literal["not_applicable", "reference_only", "in_model_expansion"]


class PurposeRules(_Frozen):
    process_selection: ProcessSelection
    background_disposition: BackgroundDisposition
    cross_boundary_connections: CrossBoundaryConnections
    elementary_flows: ElementaryFlows
    precursors: Precursors


class ModelContent(_Frozen):
    applicable_template: TemplateRef
    purposes: dict[str, PurposeRules]
    reviewed_returned_graph: dict[str, Any] | None = None
    reviewed_returned_selector: dict[str, Any] | None = None
    reviewed_source_method_package: PackageRef | None = None
    # How this package may be chosen. `automatic` packages take part in the template auto-resolver;
    # `explicit_only` packages never do, so publishing one for a variant cannot change what an
    # unpinned official calculation resolves to - it is reachable only by exact reference or when a
    # user variant explicitly binds it. Old packages omit the field and keep their content hash.
    selection_mode: Literal["automatic", "explicit_only"] = "automatic"

    @model_validator(mode="after")
    def require_review_pair(self) -> "ModelContent":
        if self.reviewed_returned_graph is not None and self.reviewed_returned_selector is not None:
            raise ValueError("a returned model review must use one selection mode")
        if ((self.reviewed_returned_graph is not None or self.reviewed_returned_selector is not None)
                != (self.reviewed_source_method_package is not None)):
            raise ValueError("a returned graph review must pin its source method")
        if self.reviewed_returned_selector is not None:
            if self.reviewed_returned_selector.get("selector_manifest_path") != (
                    "classification_rules.additional_direct_emission_selectors"):
                raise ValueError("a returned selector must name its versioned method declaration")
            identity = self.reviewed_returned_selector.get("identity")
            boundary = self.reviewed_returned_selector.get("in_boundary_process_uuids")
            if not isinstance(identity, dict) or not isinstance(boundary, list) or not boundary:
                raise ValueError("a returned selector must declare its process and flow identity scope")
        if self.reviewed_returned_graph is not None:
            for key in ("source_graph_identity_sha256", "accepted_graph_identity_sha256"):
                _ref(self.reviewed_returned_graph.get(key, ""), key)
            if not self.reviewed_returned_graph.get("added_exchange_id"):
                raise ValueError("a returned graph review must name the added exchange")
            boundary_rule = self.reviewed_returned_graph.get("boundary_rule")
            if (not isinstance(boundary_rule, dict) or
                    boundary_rule.get("exchange_id") != self.reviewed_returned_graph["added_exchange_id"] or
                    boundary_rule.get("disposition") != "counted" or
                    not boundary_rule.get("process_uuid")):
                raise ValueError("a returned graph review must decide the added exchange exactly")
        return self

    @field_validator("purposes")
    @classmethod
    def require_purposes(cls, value: dict[str, PurposeRules]) -> dict[str, PurposeRules]:
        if not value or any(not key.strip() for key in value):
            raise ValueError("a model processing package must declare at least one purpose")
        return dict(sorted(value.items()))


class ModelProcessingRules:
    """One validated model-processing package, identified by its own content hash."""

    def __init__(self, payload: dict[str, Any], source: str) -> None:
        if payload.get("schema_version") != MODEL_PROCESSING_SCHEMA_VERSION:
            raise _invalid(
                "MODEL_PROCESSING_PACKAGE_SCHEMA_UNSUPPORTED",
                f"a model processing package must declare {MODEL_PROCESSING_SCHEMA_VERSION}",
                source=source,
            )
        content = payload.get("content")
        stated = payload.get("content_sha256")
        if not isinstance(content, dict) or canonical_json_sha256(content) != stated:
            raise _invalid(
                "MODEL_PROCESSING_PACKAGE_HASH_MISMATCH",
                "the model processing package content does not match the hash it publishes",
                source=source,
            )
        try:
            validated = ModelContent.model_validate(content)
        except Exception as exc:  # a broken rule package must never half-load
            raise _invalid(
                "MODEL_PROCESSING_PACKAGE_INVALID",
                f"the model processing package is not valid: {exc}",
                source=source,
            ) from exc
        self.source = source
        self.package_id = str(payload.get("package_id") or "").strip()
        self.version = str(payload.get("version") or "").strip()
        self.content_sha256 = str(stated)
        self.applicable_template = validated.applicable_template
        self.selection_mode = validated.selection_mode
        self._purposes = validated.purposes
        self.reviewed_returned_graph = validated.reviewed_returned_graph
        self.reviewed_returned_selector = validated.reviewed_returned_selector
        self.reviewed_source_method_package = validated.reviewed_source_method_package
        if not self.package_id or not self.version:
            raise _invalid(
                "MODEL_PROCESSING_PACKAGE_INVALID",
                "a model processing package needs a package id and a version",
                source=source,
            )

    @property
    def purposes(self) -> tuple[str, ...]:
        return tuple(self._purposes)

    def purpose(self, name: str) -> PurposeRules:
        try:
            return self._purposes[name]
        except KeyError:
            raise _invalid(
                "MODEL_PROCESSING_PURPOSE_UNDECLARED",
                f"the model processing package {self.package_id}@{self.version} declares no rules"
                f" for the accounting purpose '{name}'",
                purpose=name,
                declared=list(self._purposes),
            ) from None

    def reference(self) -> dict[str, Any]:
        """The package identity, in the shape a derivation receipt and solve pin record."""
        return {
            "package_id": self.package_id,
            "version": self.version,
            "content_sha256": self.content_sha256,
            "source": self.source,
        }


def _invalid(
    code: str, message: str, *, status_code: int = 422, **details: Any
) -> DomainError:
    return DomainError(code=code, message=message, status_code=status_code, details=details)


def _candidate_directories() -> list[Path]:
    try:
        base = Path(str(files("nebula_one").joinpath(RESOURCE_DIRECTORY)))
    except (FileNotFoundError, TypeError, OSError):
        return []
    return [base] if base.is_dir() else []


def _package_files(directories: list[Path]) -> list[Path]:
    return sorted(path for directory in directories for path in directory.glob("*.json"))


def _read_payload(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _invalid(
            "MODEL_PROCESSING_PACKAGE_UNREADABLE",
            f"cannot read the model processing package {path}: {exc}",
            path=str(path),
        ) from exc


def _version_key(version: str) -> tuple[tuple[int, ...], str]:
    """An ordering for published rule versions; a missing numeric segment sorts first.

    Only used to name the nearest reviewed binding inside a refusal message. It never selects the
    rules a calculation runs under - see `load_model_processing_rules_for_template`.
    """
    return (tuple(int(part) for part in re.findall(r"\d+", version)) or (0,), version)


def _as_template_ref(template: TemplateRef | Mapping[str, Any]) -> TemplateRef:
    if isinstance(template, TemplateRef):
        return template
    passed = dict(template) if isinstance(template, Mapping) else template
    try:
        if not isinstance(passed, dict):
            raise ValueError("a bare template id selects nothing; the full identity is required")
        return TemplateRef.model_validate(passed)
    except Exception as exc:  # pydantic reports every shape problem here
        raise _invalid(
            "MODEL_PROCESSING_TEMPLATE_IDENTITY_INCOMPLETE",
            "a model processing lookup must carry the project template's id, version and"
            " content hash, because rules are reviewed against one exact template content",
            status_code=409,
            template=passed,
            reason=str(exc),
        ) from exc


def load_model_processing_rules_for_template(
    template: TemplateRef | Mapping[str, Any],
    *,
    graph_identity_sha256: str | None = None,
    graph: dict[str, Any] | None = None,
    search_paths: list[Path] | None = None,
) -> ModelProcessingRules:
    """The package reviewed against exactly this project template identity.

    Superseded rule packages stay on disk so a saved calculation replays by its exact identity, so
    the newest version is not the answer: a project imported from an older template revision must
    get the rules that were reviewed against that revision, and a run of it is not a reason to
    reinterpret its model under a later review. Selection therefore filters on the full
    id/version/content hash and accepts only a single match; it never resolves several candidates by
    version number, because that is exactly the silent reinterpretation a pin exists to prevent.
    `explicit_only` packages are not candidates here at all: they are reachable only by exact
    reference or when a user variant binds them, so a variant's rule package can never change what an
    unpinned official calculation resolves to, and can never untie a real automatic ambiguity.
    """
    wanted = _as_template_ref(template)
    directories = search_paths if search_paths is not None else _candidate_directories()
    declared: list[ModelProcessingRules] = []
    exact: list[ModelProcessingRules] = []
    for path in _package_files(directories):
        payload = _read_payload(path)
        if not isinstance(payload, dict):
            continue
        rules = ModelProcessingRules(payload, str(path.name))
        if rules.selection_mode == "explicit_only":
            continue
        if rules.applicable_template.id != wanted.id:
            continue
        declared.append(rules)
        if (rules.applicable_template.version, rules.applicable_template.content_sha256) == (
            wanted.version,
            wanted.content_sha256,
        ):
            exact.append(rules)
    matching_graph = [item for item in exact if item.reviewed_returned_graph is not None
                      and item.reviewed_returned_graph["accepted_graph_identity_sha256"] == graph_identity_sha256]
    matching_selector = [item for item in exact if item.reviewed_returned_selector is not None
                         and graph is not None and (
                             any(selector_matches(item.reviewed_returned_selector["identity"], node, port)
                                 for node in graph.get("nodes", []) for port in node.get("outputs", []))
                             or any(node.get("process_uuid") not in item.reviewed_returned_selector["in_boundary_process_uuids"]
                                    for node in graph.get("nodes", [])))]
    selected = matching_graph or matching_selector or [item for item in exact if item.reviewed_returned_graph is None
                                                          and item.reviewed_returned_selector is None]
    if len(selected) == 1:
        return selected[0]
    if len(selected) > 1:
        raise _invalid(
            "MODEL_PROCESSING_PACKAGE_AMBIGUOUS",
            f"more than one model processing package declares the rules for template '{wanted.id}'"
            f" version '{wanted.version}' with this content",
            packages=sorted(f"{item.package_id}@{item.version}" for item in selected),
        )
    if declared:
        # Report against the binding that reviewed the closest thing to what was asked for: the same
        # template content under another version label wins, otherwise the most recent declaration.
        reviewed = next(
            (item for item in declared
             if item.applicable_template.content_sha256 == wanted.content_sha256),
            max(declared, key=lambda item: _version_key(item.version)),
        )
        binding = reviewed.applicable_template
        raise _invalid(
            "MODEL_PROCESSING_TEMPLATE_MISMATCH",
            "the model processing rules were reviewed against another version of this project"
            " template, so they cannot be applied to this model revision",
            status_code=409,
            template_id=wanted.id,
            mismatches={
                key: {"template": getattr(wanted, key), "rules": getattr(binding, key)}
                for key in ("version", "content_sha256")
                if getattr(binding, key) != getattr(wanted, key)
            },
            reviewed_by=[
                {
                    "package_id": item.package_id,
                    "version": item.version,
                    "template": item.applicable_template.model_dump(),
                }
                for item in sorted(declared, key=lambda item: _version_key(item.version))
            ],
        )
    raise _invalid(
        "MODEL_PROCESSING_PACKAGE_MISSING",
        f"no versioned model processing package declares how template '{wanted.id}'"
        " is turned into a calculation model",
        template_id=wanted.id,
    )


def list_model_processing_rules_for_template(
    template: TemplateRef | Mapping[str, Any], *, graph_identity_sha256: str,
    graph: dict[str, Any] | None = None,
    search_paths: list[Path] | None = None,
) -> list[ModelProcessingRules]:
    """List exact reviewed choices so a new revision or a user variant can bind one explicitly.

    This is the explicit-selection surface, so it offers every applicable package regardless of
    selection strategy - including `explicit_only` ones, which the automatic resolver hides.
    Applicability is enforced with the same deterministic predicate the auto-resolver uses: a
    returned-graph package must match this graph identity, and a returned-selector package must
    actually select against the supplied graph. A selector package is therefore never offered merely
    because a graph hash was passed without the graph to verify it against.
    """
    wanted = _as_template_ref(template)
    directories = search_paths if search_paths is not None else _candidate_directories()
    matches = []
    for path in _package_files(directories):
        payload = _read_payload(path)
        if not isinstance(payload, dict):
            continue
        rules = ModelProcessingRules(payload, str(path.name))
        if rules.applicable_template != wanted:
            continue
        if (rules.reviewed_returned_graph is not None and
                rules.reviewed_returned_graph["accepted_graph_identity_sha256"] != graph_identity_sha256):
            continue
        if rules.reviewed_returned_selector is not None:
            selector = rules.reviewed_returned_selector
            selects = graph is not None and (
                any(selector_matches(selector["identity"], node, port)
                    for node in graph.get("nodes", []) for port in node.get("outputs", []))
                or any(node.get("process_uuid") not in selector["in_boundary_process_uuids"]
                       for node in graph.get("nodes", [])))
            if not selects:
                continue
        matches.append(rules)
    return matches


def load_model_processing_rules_by_reference(
    package_id: str,
    version: str,
    content_sha256: str,
    *,
    search_paths: list[Path] | None = None,
) -> ModelProcessingRules:
    """The exact rule package a saved calculation was derived with.

    Replaying by template id alone would let a newly published version silently change what an
    already-frozen answer means, so an exact identity is required and anything else refuses.
    """
    directories = search_paths if search_paths is not None else _candidate_directories()
    available: list[dict[str, str]] = []
    for path in _package_files(directories):
        payload = _read_payload(path)
        if not isinstance(payload, dict):
            continue
        rules = ModelProcessingRules(payload, str(path.name))
        available.append(
            {
                "package_id": rules.package_id,
                "version": rules.version,
                "content_sha256": rules.content_sha256,
            }
        )
        if (rules.package_id, rules.version, rules.content_sha256) == (
            package_id,
            version,
            content_sha256,
        ):
            return rules
    raise _invalid(
        "MODEL_PROCESSING_RULES_VERSION_UNAVAILABLE",
        f"the saved calculation names model processing rules {package_id}@{version} whose content"
        " hash is no longer available; a frozen answer is never re-derived under other rules",
        requested={
            "package_id": package_id,
            "version": version,
            "content_sha256": content_sha256,
        },
        available=available,
    )


def load_bundled_model_processing_rules(
    package_file: str, *, override_directory: str | None = None
) -> ModelProcessingRules:
    """Load one package file by name, for callers that already pinned which package applies."""
    directory = (
        Path(override_directory)
        if override_directory
        else Path(str(files("nebula_one").joinpath(RESOURCE_DIRECTORY)))
    )
    path = directory / package_file
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _invalid(
            "MODEL_PROCESSING_PACKAGE_UNREADABLE",
            f"cannot read the model processing package {package_file}: {exc}",
            path=str(path),
        ) from exc
    return ModelProcessingRules(deepcopy(payload), str(path.name))

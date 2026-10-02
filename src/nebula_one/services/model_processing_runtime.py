"""Resolve one accounting purpose's calculation model, server-side, from verified packages.

A caller may name a purpose; it may not name the rules, the template identity or the method package
content that decide how the stored model becomes a calculation model. Those are read here from the
revision's own template binding and from stored method packages, so a frozen answer always records
the exact reviewed versions it was derived under and a replay cannot silently pick up a newer one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..model_derivation import DerivedCalculationModel, derive_calculation_model
from ..model_processing_contract import (
    ModelProcessingRules,
    PackageRef,
    TemplateRef,
    load_model_processing_rules_by_reference,
    load_model_processing_rules_for_template,
)
from ..models import Application, SystemRevision
from .runtime_support import require_method_package

DERIVATION_BASIS_SCHEMA_VERSION = "nebula_one.model-derivation-basis.v1"
FLOW_SELECTION_SCHEMA_VERSION = "nebula_one.model-flow-selection.v1"
_IDENTITY_KEYS = ("package_id", "version", "content_sha256")
_PROFILE_KEYS = ("id", "version", "content_sha256")
# The only two context keys that may state which reviewed template a model descends from, and the
# only code that writes them is the seed project instance and the modelling handoff confirmation.
TEMPLATE_PROFILE_SOURCES = ("seed_template", "modeling_template_binding")


@dataclass(frozen=True)
class PurposeDerivation:
    """One purpose's derived calculation model plus the identity it was derived under."""

    purpose: str
    derived: DerivedCalculationModel
    basis: dict[str, Any]
    basis_sha256: str


def _refuse(code: str, message: str, status_code: int = 422, **details: Any) -> None:
    raise DomainError(code=code, message=message, status_code=status_code, details=details)


def _template_profile_of(container: Any) -> dict[str, str] | None:
    for source in TEMPLATE_PROFILE_SOURCES:
        profile = ((container or {}).get(source) or {}).get("profile")
        if isinstance(profile, dict) and all(
            isinstance(profile.get(key), str) and profile[key].strip()
            for key in _PROFILE_KEYS
        ):
            return {key: profile[key] for key in _PROFILE_KEYS}
    return None


def reviewed_template_profile(
    application: Application | None, revision: SystemRevision | None = None
) -> dict[str, str] | None:
    """The reviewed template a stored model says it descends from, or None when it says nothing."""
    for container in (
        getattr(revision, "application_context", None),
        getattr(application, "context", None),
    ):
        profile = _template_profile_of(container)
        if profile is not None:
            return profile
    return None


def template_identity(
    revision: SystemRevision, application: Application | None
) -> dict[str, str]:
    """The template this revision was actually imported from, never a caller-supplied label."""
    containers: list[Any] = [getattr(revision, "application_context", None)]
    if application is not None:
        containers.append(getattr(application, "context", None))
    for container in containers:
        profile = _template_profile_of(container)
        if profile is not None:
            return profile
    _refuse(
        "MODEL_PROCESSING_TEMPLATE_UNBOUND",
        "this calculation names an accounting purpose, but the model revision does not record which"
        " reviewed project template it was imported from, so no rule package can be bound to it."
        " A project instance of an installed template and a model returned by professional modelling"
        " from such a project both record it; a model imported any other way does not",
        status_code=409,
        system_revision_id=revision.id,
    )
    raise AssertionError("unreachable")  # pragma: no cover


def _resolve_rules(
    template: dict[str, str], pinned: dict[str, Any] | None, graph_identity_sha256: str,
    graph: dict[str, Any] | None = None,
) -> ModelProcessingRules:
    if pinned is not None:
        requested = {key: str(pinned.get(key) or "") for key in _IDENTITY_KEYS}
        if any(not value for value in requested.values()):
            _refuse(
                "MODEL_PROCESSING_RULES_IDENTITY_INCOMPLETE",
                "a saved calculation basis must name the exact rule package it was derived with",
                pinned=pinned,
            )
        rules = load_model_processing_rules_by_reference(**requested)
        if rules.applicable_template != TemplateRef.model_validate(template):
            _refuse("MODEL_PROCESSING_TEMPLATE_MISMATCH", "the pinned rules belong to another project template", status_code=409)
        if (rules.reviewed_returned_graph is not None and
                rules.reviewed_returned_graph["accepted_graph_identity_sha256"] != graph_identity_sha256):
            _refuse("MODEL_PROCESSING_REVIEWED_GRAPH_MISMATCH", "the pinned returned-graph review belongs to another graph identity", status_code=409)
        return rules
    # The template identity is the whole selection key: a project keeps the rules that were reviewed
    # against the template revision it was imported from, not the newest published ones.
    return load_model_processing_rules_for_template(
        template, graph_identity_sha256=graph_identity_sha256, graph=graph)


def _cited_packages(intent: Any) -> list[PackageRef]:
    refs: list[PackageRef] = []
    candidates = [
        intent.process_selection.method_package,
        intent.background_disposition.evidence.method_package
        if intent.background_disposition.evidence is not None
        else None,
        intent.elementary_flows.evidence.method_package
        if intent.elementary_flows.evidence is not None
        else None,
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        if not any(
            (item.package_id, item.version) == (candidate.package_id, candidate.version)
            for item in refs
        ):
            refs.append(candidate)
    return refs


def _load_method_packages(db: Session, refs: list[PackageRef]) -> list[dict[str, Any]]:
    """Read each cited package through the verified loading path and re-check its content hash."""
    packages: list[dict[str, Any]] = []
    for ref in refs:
        record = require_method_package(db, f"{ref.package_id}@{ref.version}")
        if record.content_sha256 != ref.content_sha256:
            _refuse(
                "MODEL_PROCESSING_METHOD_PACKAGE_MISMATCH",
                f"the stored method package {ref.package_id}@{ref.version} is not the content the"
                " reviewed rules were bound to",
                status_code=409,
                package_id=ref.package_id,
                version=ref.version,
                expected_content_sha256=ref.content_sha256,
                stored_content_sha256=record.content_sha256,
            )
        packages.append(
            {
                "package_id": record.package_id,
                "version": record.version,
                "content_sha256": record.content_sha256,
                "manifest": record.manifest,
            }
        )
    return packages


def _sorted_pins(pins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(pins, key=lambda item: str(item.get("consumer_exchange_id") or ""))


def resolve_purpose_derivation(
    db: Session,
    *,
    revision: SystemRevision,
    application: Application | None,
    purpose: str,
    demand: list[dict[str, Any]],
    background_process_pins: list[dict[str, Any]],
    mapped_background_process_pins: list[dict[str, Any]],
    project_background_pins: list[dict[str, Any]] | None = None,
    lcia_methods: list[str] | None = None,
    pinned_basis: dict[str, Any] | None = None,
) -> PurposeDerivation:
    """Derive one purpose's calculation model and the identity that makes the answer replayable."""
    template = template_identity(revision, application)
    pinned = None
    if pinned_basis is not None:
        if not isinstance(pinned_basis, dict):
            _refuse(
                "MODEL_PROCESSING_BASIS_INVALID",
                "a saved calculation basis must be an object",
                pinned_basis=pinned_basis,
            )
        if pinned_basis.get("schema_version") != DERIVATION_BASIS_SCHEMA_VERSION:
            _refuse(
                "MODEL_PROCESSING_BASIS_UNSUPPORTED",
                f"a saved calculation basis must declare {DERIVATION_BASIS_SCHEMA_VERSION}",
                schema_version=pinned_basis.get("schema_version"),
            )
        pinned = pinned_basis.get("model_processing_rules")
        if not isinstance(pinned, dict):
            _refuse(
                "MODEL_PROCESSING_RULES_IDENTITY_INCOMPLETE",
                "a saved calculation basis must name the exact rule package it was derived with",
                pinned=pinned_basis.get("model_processing_rules"),
            )
        if str(pinned_basis.get("purpose") or "") != purpose:
            _refuse(
                "MODEL_PROCESSING_BASIS_MISMATCH",
                "the saved calculation basis was derived for another accounting purpose",
                status_code=409,
                expected_purpose=pinned_basis.get("purpose"),
                requested_purpose=purpose,
            )
        stored_template = pinned_basis.get("template")
        if stored_template != template:
            _refuse(
                "MODEL_PROCESSING_BASIS_MISMATCH",
                "the saved calculation basis was derived from another project template identity",
                status_code=409,
                expected_template=stored_template,
                actual_template=template,
            )
    from .returned_cbam_binding import _identity_graph
    if pinned is None:
        pinned = (revision.application_context or {}).get("project_inputs", {}).get("model_processing_rules_ref")
    rules = _resolve_rules(template, pinned,
                           canonical_json_sha256(_identity_graph(revision.graph_snapshot)),
                           revision.graph_snapshot)
    from .inventory_derivation import derive_inventory, recipe_of
    derive_inventory(revision.graph_snapshot, recipe_of(revision.application_context), validate_only=True)
    intent = rules.purpose(purpose)
    packages = _load_method_packages(db, _cited_packages(intent))
    derived = derive_calculation_model(
        graph=revision.graph_snapshot,
        demand=demand,
        rules=rules,
        purpose=purpose,
        method_packages=packages,
        background_process_pins=background_process_pins,
        mapped_background_process_pins=mapped_background_process_pins,
        project_background_pins=project_background_pins,
    )
    basis: dict[str, Any] = {
        "schema_version": DERIVATION_BASIS_SCHEMA_VERSION,
        "purpose": purpose,
        "template": template,
        "model_processing_rules": {
            key: rules.reference()[key] for key in _IDENTITY_KEYS
        },
        "method_packages": [
            {key: package[key] for key in _IDENTITY_KEYS} for package in packages
        ],
        "source_graph_sha256": derived.source_graph_sha256,
        "derived_graph_sha256": derived.derived_graph_sha256,
        "demand": demand,
        "lcia_methods": sorted(lcia_methods) if lcia_methods is not None else None,
        "effective_background_process_pins": _sorted_pins(
            derived.background_process_pins
        ),
        "effective_mapped_background_process_pins": _sorted_pins(
            derived.mapped_background_process_pins
        ),
    }
    if derived.project_background_pins:
        basis["effective_project_background_pins"] = _sorted_pins(derived.project_background_pins)
    basis_sha256 = canonical_json_sha256(basis)
    if pinned_basis is not None:
        pinned_without_hash = {
            key: value for key, value in pinned_basis.items() if key != "basis_sha256"
        }
        if (
            str(pinned_basis.get("basis_sha256") or "") != basis_sha256
            or canonical_json_sha256(pinned_without_hash) != basis_sha256
        ):
            _refuse(
                "MODEL_PROCESSING_BASIS_DRIFT",
                "re-deriving this calculation from the saved rule identity produced another"
                " calculation model, so the frozen answer cannot be reproduced",
                status_code=409,
                expected_basis_sha256=str(pinned_basis.get("basis_sha256") or ""),
                actual_basis_sha256=basis_sha256,
            )
    return PurposeDerivation(
        purpose=purpose, derived=derived, basis=basis, basis_sha256=basis_sha256
    )


def derivation_basis_from_receipt(provider_receipt: dict[str, Any] | None) -> dict[str, Any] | None:
    """The calculation basis a frozen snapshot recorded, if that solve named a purpose."""
    basis = ((provider_receipt or {}).get("calculation_basis") or {}).get(
        "model_derivation"
    )
    return basis if isinstance(basis, dict) else None


def flow_selection_of(derived: DerivedCalculationModel | None) -> dict[str, Any] | None:
    """The reviewed emission selection a derivation made, in the shape every consumer reads.

    One record, read by the solve receipt, the CBAM reading and the report, so a consumer cannot
    resolve its own list of counted exchanges from the method package after the calculation model has
    already decided them. A purpose whose template pre-limits its emissions records no selection:
    there the package's list *is* the whole set, and the deriver verifies it by exact identity.
    """
    if derived is None:
        return None
    action = next(
        (
            item
            for item in derived.actions
            if item.get("action") == "classify_elementary_flows"
        ),
        None,
    )
    if action is None:
        return None
    return {
        "schema_version": FLOW_SELECTION_SCHEMA_VERSION,
        "mode": action["mode"],
        "method_package": action["method_package"],
        "manifest_path": action["manifest_path"],
        "included_exchange_ids": list(action["included_exchange_ids"]),
        "excluded_exchange_ids": list(action["excluded_exchange_ids"]),
        "decisions": [
            {
                "exchange_id": item["exchange_id"],
                "process_uuid": item["process_uuid"],
                "state": item["state"],
                "clause": item["clause"],
                "greenhouse_gas": item["greenhouse_gas"],
            }
            for item in derived.flow_map
        ],
    }

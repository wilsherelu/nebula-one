from __future__ import annotations

from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..database import Database
from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..models import Application, utcnow
from ..runtime_models import (
    BoundaryDefinition,
    CalculationMethod,
    CalculationMethodVersion,
)
from ..runtime_schemas import (
    CalculationMethodClone,
    CalculationMethodCreate,
    CalculationMethodSave,
    ResultCategoryConversionCreate,
)
from ..analysis.classification_suggestion import (
    SUGGESTION_STRATEGY_VERSION,
    collect_energy_evidence,
    suggest_classifications,
)
from .template_accounting_methods import model_ports
from .runtime_support import (
    require_application,
    require_method_package,
    require_process_ids,
    require_revision,
)

# The GHG location role each Scope is declared against; a selected rule whose location
# contradicts its Scope is a structural problem, not a calculation the engine should guess.
_SCOPE_LOCATION = {
    "scope_1": {"onsite"},
    "scope_2": {"purchased_energy"},
    "scope_3": {"upstream_supply"},
}


# The explicit marker of a flow-tag scheme version lives with the grouping kernel it drives. It is
# a persisted semantic version, never guessed from ``purpose=custom`` or an empty field.
from ..analysis.tag_grouping import RESULT_CATEGORY_SEMANTICS, TAG_SEMANTICS  # noqa: E402


def version_content_sha256(
    purpose: str,
    cbam_boundary_ref: str | None,
    rules: list[dict],
    reporting_dimensions: list[dict] | None = None,
    model_processing_rules_ref: dict | None = None,
    semantics: str | None = None,
) -> str:
    payload = {
        "purpose": purpose,
        "cbam_boundary_ref": cbam_boundary_ref,
        "rules": rules,
    }
    # A version with no declared semantics is byte-for-byte the historical shape; only an explicit
    # marker folds into the identity, so every pre-existing hash still replays.
    if semantics:
        payload["semantics"] = semantics
    # A historical method declares no dimensions; leaving the key out keeps its stored hash
    # identical so a frozen v1 snapshot still replays. Only a version that declares its own
    # category tree folds those dimensions into its identity.
    if reporting_dimensions:
        payload["reporting_dimensions"] = reporting_dimensions
    # Likewise a version that binds no processing package is byte-for-byte unchanged; only a variant
    # that names one folds the exact reference into its identity, so its narrowing is replayed against
    # the same reviewed selection rather than a moved head.
    if model_processing_rules_ref:
        payload["model_processing_rules_ref"] = model_processing_rules_ref
    return canonical_json_sha256(payload)


# How a variant's bound package must treat emissions for its per-exchange include/exclude to be
# executable: an explicit, identity-driven decision set - never the template's prelimited emission
# set, which would ignore the user's narrowing entirely.
_VARIANT_EXPLICIT_FLOW_MODES = ("explicit_flow_rules", "identity_selector_rules")


def _variant_ref_identity(ref: dict) -> tuple[str, str, str]:
    package_id = str(ref.get("package_id") or "").strip()
    version = str(ref.get("version") or "").strip()
    content_sha256 = str(ref.get("content_sha256") or "").strip()
    if not (package_id and version and content_sha256):
        raise DomainError(
            code="CALCULATION_METHOD_PROCESSING_PACKAGE_IDENTITY_INCOMPLETE",
            message="a bound processing package must name its package id, version and content hash",
            status_code=422,
            details={"model_processing_rules_ref": ref},
        )
    return package_id, version, content_sha256


def _require_variant_ref_selectable(
    ref: dict, revision, application, purpose: str
) -> dict:
    """Prove the bound package is loadable by exact identity and applicable to this base and purpose.

    A variant reference is only meaningful if the very package it names can still be read by that
    hash and would be offered to a user choosing rules for this exact project template and graph. So
    this loads it by reference (which re-checks its own content hash), lists what is selectable for
    this revision, and refuses unless the named package is on that list. A CBAM variant must bind a
    package whose emission handling is per-exchange explicit, because otherwise the user's included
    and excluded exchanges have no effect on the derived model.
    """
    from ..model_processing_contract import (
        list_model_processing_rules_for_template,
        load_model_processing_rules_by_reference,
    )
    from .model_processing_runtime import template_identity
    from .returned_cbam_binding import _identity_graph

    package_id, version, content_sha256 = _variant_ref_identity(ref)
    rules = load_model_processing_rules_by_reference(
        package_id, version, content_sha256
    )
    identity = {"package_id": package_id, "version": version, "content_sha256": content_sha256}
    template = template_identity(revision, application)
    graph = revision.graph_snapshot
    graph_identity = canonical_json_sha256(_identity_graph(graph))
    selectable = list_model_processing_rules_for_template(
        template, graph_identity_sha256=graph_identity, graph=graph
    )
    if not any(
        (item.package_id, item.version, item.content_sha256)
        == (package_id, version, content_sha256)
        for item in selectable
    ):
        raise DomainError(
            code="CALCULATION_METHOD_PROCESSING_PACKAGE_NOT_SELECTABLE",
            message="the bound processing package is not one a user can select for this model"
            " revision's template and graph, so a variant cannot narrow against it",
            status_code=422,
            details={"model_processing_rules_ref": identity, "template": template},
        )
    if purpose not in rules.purposes:
        raise DomainError(
            code="CALCULATION_METHOD_PROCESSING_PACKAGE_PURPOSE_UNDECLARED",
            message="the bound processing package declares no rules for this method's purpose",
            status_code=422,
            details={
                "model_processing_rules_ref": identity,
                "purpose": purpose,
                "declared_purposes": list(rules.purposes),
            },
        )
    if purpose == "cbam":
        mode = rules.purpose("cbam").elementary_flows.mode
        if mode not in _VARIANT_EXPLICIT_FLOW_MODES:
            raise DomainError(
                code="CALCULATION_METHOD_PROCESSING_PACKAGE_NOT_EXPLICIT",
                message="a CBAM variant must bind a processing package that classifies emissions"
                " per exchange, not one that takes the template's emission set as already final",
                status_code=422,
                details={"model_processing_rules_ref": identity, "elementary_flows_mode": mode},
            )
    return identity


def _normalized_dimensions(dimension_dicts: list[dict]) -> dict:
    """Validate a declared dimension tree through the generic kernel's normalizer."""
    from ..analysis.method_grouping import normalize_dimensions

    return normalize_dimensions(dimension_dicts)


def _rule_identity(rule: dict) -> tuple:
    return (
        rule.get("process_instance_id"),
        rule.get("exchange_id"),
        rule.get("flow_uuid"),
        rule.get("direction"),
    )


def _find_duplicate_rule_identities(rules: list[dict]) -> list[tuple]:
    seen: set[tuple] = set()
    duplicates: list[tuple] = []
    for rule in rules:
        identity = _rule_identity(rule)
        if identity in seen and identity not in duplicates:
            duplicates.append(identity)
        seen.add(identity)
    return duplicates


def _compile_inclusion_toggle(rules: list[dict], purpose: str) -> list[dict]:
    """Compile the reader's single 是否计入 toggle onto the legacy CBAM relevance flag.

    The unified editor exposes one inclusion switch (``boundary_status``) and never a second
    ``cbam_relevant`` switch (§2.2), so the two legacy fields must not be synced by the client.
    For a CBAM-purpose method a contribution the reader counts must be CBAM-relevant — counting a
    flow the regulation does not reach is the one direction ``method_rule_adapter`` refuses — so a
    selected contribution is made relevant here. An excluded or pending contribution KEEPS the
    relevance it was sent with: a CBAM-relevant emission the method narrows OUT is a legal
    narrowing, not a de-regulation, so stripping the flag would erase the distinction the CBAM
    boundary is built on and leave a narrowing-only variant with no relevant rule at all.
    ``scope`` is written by the same edit and read back unchanged; only the CBAM flag is derived.
    Non-CBAM methods leave the flag as sent (it is inert there).
    """
    if purpose != "cbam":
        return rules
    for rule in rules:
        if rule.get("boundary_status") == "selected":
            rule["cbam_relevant"] = True
    return rules


def _require_unique_rule_identities(rules: list[dict]) -> None:
    duplicates = _find_duplicate_rule_identities(rules)
    if duplicates:
        raise DomainError(
            code="CALCULATION_METHOD_RULE_DUPLICATE",
            message="two rules share the same process/exchange/flow/direction identity",
            status_code=422,
            details={"duplicates": [list(item) for item in duplicates]},
        )


def _require_valid_dimensions(dimension_dicts: list[dict]) -> None:
    """Fail closed on a malformed declared dimension tree before it is ever persisted."""
    if not dimension_dicts:
        return
    try:
        _normalized_dimensions(dimension_dicts)
    except ValueError as exc:
        raise DomainError(
            code="CALCULATION_METHOD_DIMENSION_INVALID",
            message=str(exc),
            status_code=422,
        ) from exc


def _dimension_category_problems(dimensions: list[dict], rules: list[dict]) -> list[dict]:
    """Locate rule category assignments that name an undeclared dimension or a non-leaf category.

    A v1 rule that only carries the legacy ``scope`` field is not checked here: the adapter maps
    that onto the built-in LC-Scope dimension independently of the declared tree.
    """
    if not dimensions:
        return []
    try:
        normalized = _normalized_dimensions(dimensions)
    except ValueError:
        return []
    problems: list[dict] = []
    for index, rule in enumerate(rules):
        for dim_id, cat_id in (rule.get("categories") or {}).items():
            if not cat_id:
                continue
            dimension = normalized.get(str(dim_id))
            if dimension is None:
                problems.append(
                    {
                        "code": "CALCULATION_METHOD_CATEGORY_DIMENSION_UNKNOWN",
                        "message": f"rule assigns category {cat_id} to undeclared dimension {dim_id}",
                        "rule_index": index,
                        "process_instance_id": rule.get("process_instance_id"),
                        "exchange_id": rule.get("exchange_id"),
                    }
                )
                continue
            category = dimension["categories"].get(str(cat_id))
            if category is None:
                problems.append(
                    {
                        "code": "CALCULATION_METHOD_CATEGORY_UNKNOWN",
                        "message": f"dimension {dim_id} declares no category {cat_id}",
                        "rule_index": index,
                        "process_instance_id": rule.get("process_instance_id"),
                        "exchange_id": rule.get("exchange_id"),
                    }
                )
            elif not category["is_leaf"]:
                problems.append(
                    {
                        "code": "CALCULATION_METHOD_CATEGORY_NOT_LEAF",
                        "message": f"category {cat_id} is a parent; only leaves carry contributions",
                        "rule_index": index,
                        "process_instance_id": rule.get("process_instance_id"),
                        "exchange_id": rule.get("exchange_id"),
                    }
                )
    return problems


def _is_tag_scheme(semantics: str | None) -> bool:
    return semantics == TAG_SEMANTICS


def _is_result_category(semantics: str | None) -> bool:
    return semantics == RESULT_CATEGORY_SEMANTICS


def _is_caliber(semantics: str | None) -> bool:
    """A read-only grouping caliber, in either its historical or current semantic version."""
    return _is_tag_scheme(semantics) or _is_result_category(semantics)


def _is_legacy_ordinary(semantics: str | None, purpose: str) -> bool:
    """A pre-caliber custom method: its Scope/boundary rules are history, not an editable shape."""
    return semantics is None and purpose == "custom"


def _is_legacy_method(semantics: str | None, purpose: str) -> bool:
    return _is_tag_scheme(semantics) or _is_legacy_ordinary(semantics, purpose)


def _legacy_write_refusal(method_id: str, version: int, *, cloning: bool = False) -> DomainError:
    return DomainError(
        code="CALCULATION_METHOD_LEGACY_READ_ONLY",
        message=(
            "this legacy method is read-only; convert it to a result-category caliber"
            + (" instead of cloning it" if cloning else " to make further changes")
        ),
        status_code=409,
        details={"method_id": method_id, "version": version},
    )



def _category_leaves(dimension: dict) -> set[str]:
    categories = [c for c in dimension.get("categories") or [] if isinstance(c, dict)]
    parents = {str(c.get("parent_id")) for c in categories if c.get("parent_id")}
    return {
        str(c["id"])
        for c in categories
        if c.get("id") and str(c["id"]) not in parents and c.get("is_leaf") is not False
    }


def _result_category_problems(
    *,
    purpose: str,
    cbam_boundary_ref: str | None,
    variant_ref: dict | None,
    dimensions: list[dict],
    rules: list[dict],
) -> list[dict]:
    """Structural rules of a result-category caliber.

    Membership comes from one assigned leaf category, so a rule without one is a defect rather
    than an implicit inclusion. The legacy inclusion fields are derived by the adapter below and
    never chosen here; a boundary/Scope value would be a second meaning for the same flow.
    """
    problems: list[dict] = []

    def add(code: str, message: str, index: int | None = None, **extra) -> None:
        rule = rules[index] if index is not None else {}
        problems.append(
            {
                "code": code,
                "message": message,
                "rule_index": index,
                "process_instance_id": rule.get("process_instance_id"),
                "exchange_id": rule.get("exchange_id"),
                **extra,
            }
        )

    if purpose != "custom":
        add(
            "CALCULATION_METHOD_RESULT_CATEGORY_PURPOSE_INVALID",
            "a result-category caliber is an analysis view, not a regulatory purpose; use purpose=custom",
            purpose=purpose,
        )
    if cbam_boundary_ref:
        add(
            "CALCULATION_METHOD_RESULT_CATEGORY_BOUNDARY_REF_NOT_ALLOWED",
            "a result-category caliber carries no regulatory boundary reference",
        )
    if variant_ref:
        add(
            "CALCULATION_METHOD_RESULT_CATEGORY_PROCESSING_REF_NOT_ALLOWED",
            "a result-category caliber narrows nothing and never binds a processing package",
        )
    if len(dimensions) != 1:
        add(
            "CALCULATION_METHOD_RESULT_CATEGORY_DIMENSION_COUNT",
            "a result-category caliber declares exactly one category tree",
            dimension_count=len(dimensions),
        )
        return problems
    dimension = dimensions[0]
    dimension_id = str(dimension.get("id") or "")
    declared = {str(c.get("id")) for c in dimension.get("categories") or [] if isinstance(c, dict) and c.get("id")}
    leaves = _category_leaves(dimension)
    for index, rule in enumerate(rules):
        if not str(rule.get("exchange_id") or "").strip():
            add(
                "CALCULATION_METHOD_RESULT_CATEGORY_RULE_NEEDS_EXCHANGE",
                "a result-category assignment names one exact process exchange, not a whole process",
                index,
            )
        categories = rule.get("categories") or {}
        foreign = sorted(str(key) for key in categories if str(key) != dimension_id)
        if foreign:
            add(
                "CALCULATION_METHOD_RESULT_CATEGORY_CATEGORY_DIMENSION",
                "a rule may only assign a category of this caliber's own tree",
                index,
                dimensions=foreign,
            )
        category = categories.get(dimension_id)
        if not str(category or "").strip():
            add(
                "CALCULATION_METHOD_RESULT_CATEGORY_REQUIRED",
                "assign a leaf category; use an absent rule for “无” instead of an empty category",
                index,
            )
        elif str(category) not in declared:
            add(
                "CALCULATION_METHOD_RESULT_CATEGORY_UNKNOWN",
                f"this caliber declares no category {category}",
                index,
                category=category,
            )
        elif str(category) not in leaves:
            add(
                "CALCULATION_METHOD_RESULT_CATEGORY_NOT_LEAF",
                f"category {category} is a parent; only leaves carry contributions",
                index,
                category=category,
            )
        if rule.get("scope"):
            add(
                "CALCULATION_METHOD_RESULT_CATEGORY_SCOPE_NOT_ALLOWED",
                "a result-category caliber has no LC-Scope column; use its own categories",
                index,
                scope=rule.get("scope"),
            )
        if rule.get("boundary") in ("exclude", "pending"):
            add(
                "CALCULATION_METHOD_RESULT_CATEGORY_BOUNDARY_NOT_ALLOWED",
                "“无” is expressed by the absence of a relation, not by an exclude/pending boundary",
                index,
                boundary=rule.get("boundary"),
            )
    return problems


def _normalize_result_category_rules(rules: list[dict]) -> list[dict]:
    """Derive the legacy fields the shared execution machinery still reads.

    Presence in the caliber already means membership, so the stored rule carries
    ``selected`` only as an adapter fact (coverage-gap detection reads it). The reader never
    edits these fields; ``categories`` stays the single source of truth for grouping.
    """
    for rule in rules:
        rule["boundary_status"] = "selected"
        rule["boundary"] = None
        rule["cbam_relevant"] = False
        rule["classification_basis"] = "user"
    return rules


def _tag_scheme_problems(
    *,
    semantics: str | None,
    purpose: str,
    cbam_boundary_ref: str | None,
    variant_ref: dict | None,
    dimensions: list[dict],
    rules: list[dict],
) -> list[dict]:
    """Structural rules a flow-tag scheme obeys, located wherever possible.

    A tag scheme is one analysis caliber: exactly one category tree, one confirmed match per
    exchange, and no regulatory binding. Its flows are matched by presence, so an ``excluded``
    rule would be a second meaning for "not tagged" — the absence of a rule is the only one.
    """
    if semantics is None:
        return []
    if semantics == RESULT_CATEGORY_SEMANTICS:
        return _result_category_problems(
            purpose=purpose,
            cbam_boundary_ref=cbam_boundary_ref,
            variant_ref=variant_ref,
            dimensions=dimensions,
            rules=rules,
        )
    problems: list[dict] = []

    def add(code: str, message: str, index: int | None = None, **extra) -> None:
        rule = rules[index] if index is not None else {}
        problems.append(
            {
                "code": code,
                "message": message,
                "rule_index": index,
                "process_instance_id": rule.get("process_instance_id"),
                "exchange_id": rule.get("exchange_id"),
                **extra,
            }
        )

    if semantics != TAG_SEMANTICS:
        add("CALCULATION_METHOD_SEMANTICS_UNKNOWN", f"unknown method semantics {semantics!r}")
        return problems
    if purpose != "custom":
        add(
            "CALCULATION_METHOD_TAG_PURPOSE_INVALID",
            "a flow-tag scheme is an analysis caliber, not a regulatory purpose; use purpose=custom",
            purpose=purpose,
        )
    if cbam_boundary_ref:
        add(
            "CALCULATION_METHOD_TAG_BOUNDARY_REF_NOT_ALLOWED",
            "a flow-tag scheme carries no regulatory boundary reference",
        )
    if variant_ref:
        add(
            "CALCULATION_METHOD_TAG_PROCESSING_REF_NOT_ALLOWED",
            "a flow-tag scheme narrows nothing; it never binds a model-processing package",
        )
    if len(dimensions) != 1:
        add(
            "CALCULATION_METHOD_TAG_DIMENSION_COUNT",
            "a flow-tag scheme declares exactly one category tree",
            dimension_count=len(dimensions),
        )
        return problems
    dimension_id = str(dimensions[0].get("id") or "")
    for index, rule in enumerate(rules):
        if not str(rule.get("exchange_id") or "").strip():
            add(
                "CALCULATION_METHOD_TAG_RULE_NEEDS_EXCHANGE",
                "a tag match must name one exact process exchange, not a whole process",
                index,
            )
        status = rule.get("boundary_status")
        if status not in ("selected", "pending"):
            add(
                "CALCULATION_METHOD_TAG_BOUNDARY_INVALID",
                "a tag match is selected or pending; an excluded rule would redefine 'not tagged'",
                index,
                boundary_status=status,
            )
        foreign = sorted(
            key for key in (rule.get("categories") or {}) if str(key) != dimension_id
        )
        if foreign:
            add(
                "CALCULATION_METHOD_TAG_CATEGORY_DIMENSION",
                "a tag match may only assign a category of this scheme's own tree",
                index,
                dimensions=foreign,
            )
        if rule.get("scope"):
            add(
                "CALCULATION_METHOD_TAG_SCOPE_NOT_ALLOWED",
                "a flow-tag scheme has no LC-Scope column; use the scheme's own categories",
                index,
                scope=rule.get("scope"),
            )
    return problems


def _require_valid_tag_scheme(**kwargs) -> None:
    problems = _tag_scheme_problems(**kwargs)
    if problems:
        first = problems[0]
        raise DomainError(
            code=first["code"],
            message=first["message"],
            status_code=422,
            details={"problems": problems},
        )


def contribution_port_ids(graph: dict | None) -> set[str]:
    """The model ports the engine can characterize, used for a tag scheme's coverage claim.

    An emission or a biosphere input always contributes; a technosphere input contributes only
    when another modelled process does not feed it, because an internal transfer is not a
    purchased path and produces no second contribution.
    """
    if not isinstance(graph, dict):
        return set()
    edges = graph.get("exchanges") if isinstance(graph.get("exchanges"), list) else graph.get("edges")
    internal: set[str] = set()
    for edge in edges or []:
        if isinstance(edge, dict) and isinstance(edge.get("toNode"), str) and edge.get("targetPortId") is not None:
            internal.add(f"{edge['toNode']}::{edge['targetPortId']}")
    ids: set[str] = set()
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            continue
        for group in ("inputs", "outputs", "emissions"):
            for port in node.get(group) or []:
                if not isinstance(port, dict) or port.get("id") in (None, ""):
                    continue
                port_type = str(port.get("type") or "")
                elementary = port_type in ("biosphere", "elementary")
                exchange_id = f"{node['id']}::{port['id']}"
                if group == "emissions" or elementary and group in ("inputs", "outputs"):
                    ids.add(exchange_id)
                elif group == "inputs" and exchange_id not in internal:
                    ids.add(exchange_id)
    return ids


class CalculationMethodService:
    """Persists versioned user calculation methods bound to an exact model revision.

    One only records and validates the user's declared grouping; the emission and
    Scope numbers stay with Nebula LCA.
    """

    def __init__(self, database: Database) -> None:
        self.database = database

    def create_method(
        self, application_id: str, payload: CalculationMethodCreate
    ) -> CalculationMethod:
        rules = [rule.model_dump(mode="json") for rule in payload.rules]
        dimensions = [dim.model_dump(mode="json") for dim in payload.reporting_dimensions]
        _require_valid_dimensions(dimensions)
        _require_unique_rule_identities(rules)
        _require_valid_tag_scheme(
            semantics=payload.semantics,
            purpose=payload.purpose,
            cbam_boundary_ref=payload.cbam_boundary_ref,
            variant_ref=payload.model_processing_rules_ref.model_dump(mode="json")
            if payload.model_processing_rules_ref is not None
            else None,
            dimensions=dimensions,
            rules=rules,
        )
        if payload.semantics == RESULT_CATEGORY_SEMANTICS:
            _normalize_result_category_rules(rules)
        _compile_inclusion_toggle(rules, payload.purpose)
        with self.database.session() as db:
            require_application(db, application_id)
            revision, _model = require_revision(db, payload.model_revision_id, application_id)
            require_process_ids(revision, sorted({rule["process_instance_id"] for rule in rules}))
            variant_ref = None
            if payload.model_processing_rules_ref is not None:
                application = db.get(Application, application_id)
                variant_ref = _require_variant_ref_selectable(
                    payload.model_processing_rules_ref.model_dump(mode="json"),
                    revision,
                    application,
                    payload.purpose,
                )
            method = CalculationMethod(
                application_id=application_id,
                model_revision_id=payload.model_revision_id,
                purpose=payload.purpose,
                name=payload.name,
                description=payload.description,
                status="draft",
            )
            db.add(method)
            try:
                db.flush()
            except IntegrityError as exc:
                db.rollback()
                raise DomainError(
                    code="CALCULATION_METHOD_NAME_CONFLICT",
                    message="a method with this name already exists for this model revision",
                    status_code=409,
                    details={"name": payload.name},
                ) from exc
            version = CalculationMethodVersion(
                method_id=method.id,
                version=1,
                rules=rules,
                reporting_dimensions=dimensions,
                model_processing_rules_ref=variant_ref,
                semantics=payload.semantics,
                cbam_boundary_ref=payload.cbam_boundary_ref,
                content_sha256=version_content_sha256(
                    payload.purpose,
                    payload.cbam_boundary_ref,
                    rules,
                    dimensions,
                    variant_ref,
                    payload.semantics,
                ),
                status="draft",
            )
            db.add(version)
            db.commit()
            db.refresh(method)
            return method

    def save_method_version(
        self, method_id: str, base_version: int, payload: CalculationMethodSave
    ) -> CalculationMethod:
        """Replace the rule set as a new immutable version, guarded by the loaded content hash.

        A stale ``expected_content_sha256`` (or a base that is no longer the latest version) is a
        conflict: the user's edit is preserved client-side and the server keeps the existing chain.
        """
        rules = [rule.model_dump(mode="json") for rule in payload.rules]
        dimensions = [dim.model_dump(mode="json") for dim in payload.reporting_dimensions]
        _require_valid_dimensions(dimensions)
        _require_unique_rule_identities(rules)
        with self.database.session() as db:
            method = db.get(CalculationMethod, method_id)
            if method is None:
                raise DomainError(
                    code="CALCULATION_METHOD_NOT_FOUND",
                    message=f"calculation method not found: {method_id}",
                    status_code=404,
                )
            revision, _model = require_revision(db, method.model_revision_id, method.application_id)
            require_process_ids(
                revision, sorted({rule["process_instance_id"] for rule in rules})
            )
            base = db.scalar(
                select(CalculationMethodVersion).where(
                    CalculationMethodVersion.method_id == method_id,
                    CalculationMethodVersion.version == base_version,
                )
            )
            if base is None:
                raise DomainError(
                    code="CALCULATION_METHOD_VERSION_NOT_FOUND",
                    message=f"calculation method version not found: {method_id}@{base_version}",
                    status_code=404,
                )
            # An edit cannot silently drop the marker: omitting it keeps the base version's
            # semantics, while stating it explicitly converts (and is validated as) a new caliber.
            semantics = payload.semantics if payload.semantics is not None else base.semantics
            if _is_legacy_method(base.semantics, method.purpose):
                raise _legacy_write_refusal(method_id, base.version)
            _require_valid_tag_scheme(
                semantics=semantics,
                purpose=method.purpose,
                cbam_boundary_ref=payload.cbam_boundary_ref,
                variant_ref=payload.model_processing_rules_ref.model_dump(mode="json")
                if payload.model_processing_rules_ref is not None
                else None,
                dimensions=dimensions,
                rules=rules,
            )
            if semantics == RESULT_CATEGORY_SEMANTICS:
                _normalize_result_category_rules(rules)
            _compile_inclusion_toggle(rules, method.purpose)
            variant_ref = None
            if payload.model_processing_rules_ref is not None:
                application = db.get(Application, method.application_id)
                variant_ref = _require_variant_ref_selectable(
                    payload.model_processing_rules_ref.model_dump(mode="json"),
                    revision,
                    application,
                    method.purpose,
                )
            latest = db.scalar(
                select(CalculationMethodVersion)
                .where(CalculationMethodVersion.method_id == method_id)
                .order_by(CalculationMethodVersion.version.desc())
                .limit(1)
            )
            assert latest is not None
            new_hash = version_content_sha256(
                method.purpose,
                payload.cbam_boundary_ref,
                rules,
                dimensions,
                variant_ref,
                semantics,
            )
            meta_unchanged = (
                (payload.name is None or payload.name == method.name)
                and (payload.description is None or payload.description == method.description)
            )
            if meta_unchanged and latest.content_sha256 == new_hash:
                # An identical re-submit is a replay, not a second edit: return the current head
                # without creating a new version, so repeated PUTs are safe.
                return method
            if (
                base_version != latest.version
                or base.content_sha256 != payload.expected_content_sha256
            ):
                raise DomainError(
                    code="CALCULATION_METHOD_CONFLICT",
                    message="该计算方法已被更新，请重新加载后再保存。",
                    status_code=409,
                    details={
                        "expected_content_sha256": payload.expected_content_sha256,
                        "current_content_sha256": latest.content_sha256,
                        "current_version": latest.version,
                    },
                )
            if payload.name is not None and payload.name != method.name:
                method.name = payload.name
            if payload.description is not None:
                method.description = payload.description
            version = CalculationMethodVersion(
                method_id=method_id,
                version=latest.version + 1,
                rules=rules,
                reporting_dimensions=dimensions,
                model_processing_rules_ref=variant_ref,
                semantics=semantics,
                cbam_boundary_ref=payload.cbam_boundary_ref,
                content_sha256=new_hash,
                status="draft",
            )
            db.add(version)
            try:
                db.flush()
            except IntegrityError as exc:
                db.rollback()
                raise DomainError(
                    code="CALCULATION_METHOD_NAME_CONFLICT",
                    message="a method with this name already exists for this model revision",
                    status_code=409,
                    details={"name": method.name},
                ) from exc
            db.commit()
            db.refresh(method)
            return method

    def clone_method(
        self, method_id: str, source_version: int, payload: CalculationMethodClone
    ) -> CalculationMethod:
        """Copy the latest version's rules into a new method on an exact revision, keeping origin."""
        with self.database.session() as db:
            source = db.get(CalculationMethod, method_id)
            if source is None:
                raise DomainError(
                    code="CALCULATION_METHOD_NOT_FOUND",
                    message=f"calculation method not found: {method_id}",
                    status_code=404,
                )
            require_application(db, source.application_id)
            revision, _model = require_revision(db, payload.model_revision_id, source.application_id)
            source_ver = db.scalar(
                select(CalculationMethodVersion).where(
                    CalculationMethodVersion.method_id == method_id,
                    CalculationMethodVersion.version == source_version,
                )
            )
            if source_ver is None:
                raise DomainError(
                    code="CALCULATION_METHOD_VERSION_NOT_FOUND",
                    message=f"calculation method version not found: {method_id}@{source_version}",
                    status_code=404,
                )
            rules = [dict(rule) for rule in source_ver.rules]
            dimensions = [dict(dim) for dim in (source_ver.reporting_dimensions or [])]
            _require_valid_dimensions(dimensions)
            _require_unique_rule_identities(rules)
            if _is_legacy_method(source_ver.semantics, source.purpose):
                raise _legacy_write_refusal(method_id, source_ver.version, cloning=True)
            require_process_ids(
                revision, sorted({rule["process_instance_id"] for rule in rules})
            )
            semantics = payload.semantics if payload.semantics is not None else source_ver.semantics
            # A clone keeps the source's processing binding unless the caller re-binds it; either way
            # it is re-validated against the target revision, so a package not selectable there is
            # refused rather than carried over to a base it does not apply to.
            ref_input = (
                payload.model_processing_rules_ref.model_dump(mode="json")
                if payload.model_processing_rules_ref is not None
                else source_ver.model_processing_rules_ref
            )
            _require_valid_tag_scheme(
                semantics=semantics,
                purpose=payload.purpose,
                cbam_boundary_ref=source_ver.cbam_boundary_ref,
                variant_ref=ref_input,
                dimensions=dimensions,
                rules=rules,
            )
            if semantics == RESULT_CATEGORY_SEMANTICS:
                _normalize_result_category_rules(rules)
            variant_ref = None
            if ref_input:
                application = db.get(Application, source.application_id)
                variant_ref = _require_variant_ref_selectable(
                    ref_input, revision, application, payload.purpose
                )
            method = CalculationMethod(
                application_id=source.application_id,
                model_revision_id=payload.model_revision_id,
                purpose=payload.purpose,
                name=payload.name,
                description=source.description,
                origin_method_id=source.id,
                origin_method_version=source_ver.version,
                origin_content_sha256=source_ver.content_sha256,
                status="draft",
            )
            db.add(method)
            try:
                db.flush()
            except IntegrityError as exc:
                db.rollback()
                raise DomainError(
                    code="CALCULATION_METHOD_NAME_CONFLICT",
                    message="a method with this name already exists for this model revision",
                    status_code=409,
                    details={"name": payload.name},
                ) from exc
            version = CalculationMethodVersion(
                method_id=method.id,
                version=1,
                rules=rules,
                reporting_dimensions=dimensions,
                model_processing_rules_ref=variant_ref,
                semantics=semantics,
                cbam_boundary_ref=source_ver.cbam_boundary_ref,
                content_sha256=version_content_sha256(
                    payload.purpose,
                    source_ver.cbam_boundary_ref,
                    rules,
                    dimensions,
                    variant_ref,
                    semantics,
                ),
                status="draft",
            )
            db.add(version)
            db.commit()
            db.refresh(method)
            return method

    def validate_version(self, method_id: str, version: int) -> dict:
        """Re-check an exact version against its bound revision and persist the outcome.

        Unlike the create/save guards, validation never raises on a semantic problem: it
        collects every structural issue (uniqueness, process existence, Scope/location
        combinations, CBAM-vs-purpose matching, unclassified selections) into a located,
        structured report so the caller can block calculation and show per-rule reasons.
        Only a genuinely missing resource (method/version/revision) raises.
        """
        with self.database.session() as db:
            method = db.get(CalculationMethod, method_id)
            if method is None:
                raise DomainError(
                    code="CALCULATION_METHOD_NOT_FOUND",
                    message=f"calculation method not found: {method_id}",
                    status_code=404,
                )
            revision, _model = require_revision(
                db, method.model_revision_id, method.application_id
            )
            record = db.scalar(
                select(CalculationMethodVersion).where(
                    CalculationMethodVersion.method_id == method_id,
                    CalculationMethodVersion.version == version,
                )
            )
            if record is None:
                raise DomainError(
                    code="CALCULATION_METHOD_VERSION_NOT_FOUND",
                    message=f"calculation method version not found: {method_id}@{version}",
                    status_code=404,
                )
            rules = [dict(rule) for rule in record.rules]
            dimensions = [dict(dim) for dim in (record.reporting_dimensions or [])]
            graph_ids = {
                str(node.get("id") or "").strip()
                for node in revision.graph_snapshot.get("nodes") or []
                if isinstance(node, dict)
            }

            problems: list[dict] = []

            def add(code: str, message: str, index: int | None = None) -> None:
                rule = rules[index] if index is not None else {}
                problems.append(
                    {
                        "code": code,
                        "message": message,
                        "rule_index": index,
                        "process_instance_id": rule.get("process_instance_id"),
                        "exchange_id": rule.get("exchange_id"),
                    }
                )

            seen: set[tuple] = set()
            for index, rule in enumerate(rules):
                identity = _rule_identity(rule)
                if identity in seen:
                    add(
                        "CALCULATION_METHOD_RULE_DUPLICATE",
                        "another rule shares this process/exchange/flow/direction identity",
                        index,
                    )
                seen.add(identity)
            for index, rule in enumerate(rules):
                if rule["process_instance_id"] not in graph_ids:
                    add(
                        "BOUND_PROCESS_NOT_FOUND",
                        "the process is absent from the bound system revision",
                        index,
                    )

            tag_scheme = _is_tag_scheme(record.semantics)
            result_category = _is_result_category(record.semantics)
            if tag_scheme or result_category:
                prefix = (
                    "CALCULATION_METHOD_RESULT" if result_category else "CALCULATION_METHOD_TAG"
                )
                ports = {port["exchange_id"]: port for port in model_ports(revision.graph_snapshot)}
                seen_exchanges: set[str] = set()
                for index, rule in enumerate(rules):
                    exchange_id = str(rule.get("exchange_id") or "")
                    port = ports.get(exchange_id)
                    if port is None:
                        add(f"{prefix}_EXCHANGE_NOT_FOUND", "the assigned exchange is absent from this model revision", index)
                    elif (port["process_id"] != rule.get("process_instance_id")
                          or port["direction"] != rule.get("direction")
                          or rule.get("flow_uuid") and port.get("flow_uuid") != rule["flow_uuid"]):
                        add(f"{prefix}_IDENTITY_MISMATCH", "the assignment conflicts with the exact model exchange identity", index)
                    if exchange_id in seen_exchanges:
                        add(f"{prefix}_MATCH_DUPLICATE", "one exchange may appear only once in this caliber", index)
                    seen_exchanges.add(exchange_id)
                    if tag_scheme and rule.get("boundary_status") == "pending":
                        add("CALCULATION_METHOD_TAG_MATCH_PENDING", "confirm this proposed tag match before grouping", index)
                problems.extend(
                    _tag_scheme_problems(
                        semantics=record.semantics,
                        purpose=method.purpose,
                        cbam_boundary_ref=record.cbam_boundary_ref,
                        variant_ref=record.model_processing_rules_ref,
                        dimensions=dimensions,
                        rules=rules,
                    )
                )
                dimension = dimensions[0] if len(dimensions) == 1 else None
                if dimension and bool(dimension.get("requires_full_coverage")):
                    declared = contribution_port_ids(revision.graph_snapshot)
                    matched = {
                        str(rule.get("exchange_id"))
                        for rule in rules
                        if rule.get("exchange_id")
                        and (
                            result_category
                            or rule.get("boundary_status") in ("selected", "pending")
                        )
                    }
                    unmatched = sorted(declared.difference(matched))
                    if unmatched:
                        problems.append(
                            {
                                "code": "CALCULATION_METHOD_TAG_FLOW_UNMATCHED",
                                "message": "this scheme requires full coverage but some model flows are not tagged",
                                "rule_index": None,
                                "process_instance_id": None,
                                "exchange_id": None,
                                "unmatched_count": len(unmatched),
                                "exchange_ids": unmatched[:100],
                            }
                        )

            # A method that declares its own reporting dimensions groups contributions against
            # those categories, not the legacy Scope field; only a Scope-only (custom-empty)
            # method still owes every selected rule a Scope.
            custom_dimension_ids = {str(dim.get("id")) for dim in dimensions if dim.get("id")}
            requires_scope = method.purpose in ("cbam", "organization") and not custom_dimension_ids
            for index, rule in enumerate(rules):
                selected = rule.get("boundary_status") == "selected"
                scope = rule.get("scope")
                location = rule.get("location_role")
                if selected and rule.get("classification_basis") == "unclassified":
                    add(
                        "CALCULATION_METHOD_UNCLASSIFIED",
                        "a selected item is still unclassified",
                        index,
                    )
                if custom_dimension_ids and not (tag_scheme or result_category):
                    categorized = any(
                        rule.get("categories", {}).get(dim_id) for dim_id in custom_dimension_ids
                    )
                    if selected and not categorized and scope is None:
                        add(
                            "CALCULATION_METHOD_MISSING_CATEGORY",
                            "a selected item must be classified into a declared dimension category",
                            index,
                        )
                elif selected and scope is None and requires_scope:
                    add(
                        "CALCULATION_METHOD_MISSING_SCOPE",
                        "a selected item must declare a Scope for this purpose",
                        index,
                    )
                if scope is not None and rule.get("boundary_status") != "excluded":
                    allowed = _SCOPE_LOCATION.get(scope)
                    if allowed is not None and location not in allowed:
                        add(
                            "CALCULATION_METHOD_SCOPE_LOCATION_MISMATCH",
                            f"Scope {scope} does not match location role {location!r}",
                            index,
                        )

            if not result_category:
                problems.extend(_dimension_category_problems(dimensions, rules))

            boundary_ref = record.cbam_boundary_ref
            if method.purpose == "cbam":
                if not boundary_ref:
                    add(
                        "CALCULATION_METHOD_CBAM_BOUNDARY_REQUIRED",
                        "a CBAM-purpose method must reference a CBAM boundary definition",
                    )
                elif db.get(BoundaryDefinition, boundary_ref) is None:
                    add(
                        "CALCULATION_METHOD_CBAM_BOUNDARY_NOT_FOUND",
                        "the referenced CBAM boundary definition does not exist",
                    )
                if not any(rule.get("cbam_relevant") for rule in rules):
                    add(
                        "CALCULATION_METHOD_CBAM_NO_RELEVANT_RULE",
                        "no rule is flagged as CBAM-relevant for a CBAM-purpose method",
                    )
            elif boundary_ref:
                add(
                    "CALCULATION_METHOD_CBAM_BOUNDARY_NOT_ALLOWED",
                    "only a CBAM-purpose method may reference a CBAM boundary definition",
                )

            # A version that binds a processing package is only calculable while that exact package is
            # still loadable and selectable for this revision's template and graph; a drift here blocks
            # calculation instead of silently narrowing against something else.
            if record.model_processing_rules_ref:
                try:
                    _require_variant_ref_selectable(
                        dict(record.model_processing_rules_ref),
                        revision,
                        db.get(Application, method.application_id),
                        method.purpose,
                    )
                except DomainError as exc:
                    add(exc.code, exc.message)

            valid = not problems
            record.validated_at = utcnow()
            if valid and record.status == "draft":
                record.status = "ready"
            elif not valid and record.status == "ready":
                record.status = "draft"
            db.commit()
            db.refresh(record)
            return {
                "method_id": method.id,
                "version": record.version,
                "model_revision_id": method.model_revision_id,
                "content_sha256": record.content_sha256,
                "valid": valid,
                "status": record.status,
                "validated_at": record.validated_at,
                "problems": problems,
            }

    def classification_suggestions(self, method_id: str, version: int) -> dict:
        """Previewable classification suggestions for one exact version, from traceable evidence.

        Read-only: it derives a located suggestion per model port from the bound revision's graph,
        the rules this version already persists, and the purchased-energy exchanges the application's
        bound method packages declare. It never writes a rule and never guesses a factor; a port
        whose energy property cannot be evidenced stays pending. The reader confirms suggestions in
        the UI, which applies them to the draft without overriding a rule already decided by hand.
        """
        with self.database.session() as db:
            method = db.get(CalculationMethod, method_id)
            if method is None:
                raise DomainError(
                    code="CALCULATION_METHOD_NOT_FOUND",
                    message=f"calculation method not found: {method_id}",
                    status_code=404,
                )
            revision, _model = require_revision(
                db, method.model_revision_id, method.application_id
            )
            record = db.scalar(
                select(CalculationMethodVersion).where(
                    CalculationMethodVersion.method_id == method_id,
                    CalculationMethodVersion.version == version,
                )
            )
            if record is None:
                raise DomainError(
                    code="CALCULATION_METHOD_VERSION_NOT_FOUND",
                    message=f"calculation method version not found: {method_id}@{version}",
                    status_code=404,
                )
            application = require_application(db, method.application_id)
            graph = revision.graph_snapshot or {}
            ports = model_ports(graph)
            rules = [dict(rule) for rule in record.rules]

            manifests: list[tuple[dict, str, str, str]] = []
            for ref in sorted(set((application.context or {}).get("method_package_refs") or [])):
                try:
                    package = require_method_package(db, str(ref))
                except DomainError:
                    # A reference that no longer resolves is not evidence; skip it rather than fail
                    # the whole preview, and the affected ports simply stay pending.
                    continue
                manifests.append(
                    (package.manifest or {}, package.package_id, package.version, package.content_sha256)
                )
            energy_exchange_ids, energy_packages = collect_energy_evidence(manifests)

            return {
                "strategy_version": SUGGESTION_STRATEGY_VERSION,
                "method_id": method.id,
                "version": record.version,
                "model_revision_id": method.model_revision_id,
                "graph_content_sha256": canonical_json_sha256(graph),
                "energy_packages": energy_packages,
                "suggestions": suggest_classifications(
                    ports=ports,
                    rules=rules,
                    energy_exchange_ids=energy_exchange_ids,
                    energy_packages=energy_packages,
                ),
            }

    def list_methods(
        self, application_id: str, model_revision_id: str | None = None
    ) -> list[dict]:
        """List methods with the head version facts the list surface actually shows.

        Carrying ``semantics``, the head status and a tag scheme's category summary here keeps the
        list from issuing one detail request per row or from guessing a scheme's kind by its name.
        """
        with self.database.session() as db:
            require_application(db, application_id)
            query = select(CalculationMethod).where(
                CalculationMethod.application_id == application_id
            )
            if model_revision_id:
                query = query.where(CalculationMethod.model_revision_id == model_revision_id)
            methods = list(db.scalars(query.order_by(CalculationMethod.created_at)))
            heads: dict[str, CalculationMethodVersion] = {}
            if methods:
                versions = db.scalars(
                    select(CalculationMethodVersion)
                    .where(
                        CalculationMethodVersion.method_id.in_([method.id for method in methods])
                    )
                    .order_by(
                        CalculationMethodVersion.method_id,
                        CalculationMethodVersion.version.desc(),
                    )
                )
                for version in versions:
                    heads.setdefault(version.method_id, version)
            return [self._method_row(method, heads.get(method.id)) for method in methods]

    @staticmethod
    def _method_row(
        method: CalculationMethod, head: CalculationMethodVersion | None
    ) -> dict:
        summary: list[str] = []
        if head is not None and _is_caliber(head.semantics):
            dimensions = head.reporting_dimensions or []
            if len(dimensions) == 1:
                summary = [
                    str(category.get("name") or category.get("id"))
                    for category in dimensions[0].get("categories") or []
                    if category.get("is_leaf", category.get("parent_id") is None)
                ]
        return {
            "id": method.id,
            "application_id": method.application_id,
            "model_revision_id": method.model_revision_id,
            "purpose": method.purpose,
            "name": method.name,
            "description": method.description,
            "origin_method_id": method.origin_method_id,
            "origin_method_version": method.origin_method_version,
            "origin_content_sha256": method.origin_content_sha256,
            "status": method.status,
            "created_at": method.created_at,
            "updated_at": method.updated_at,
            "semantics": head.semantics if head is not None else None,
            "latest_version": head.version if head is not None else None,
            "latest_content_sha256": head.content_sha256 if head is not None else None,
            "latest_status": head.status if head is not None else None,
            "category_summary": summary,
        }

    def require_method(self, method_id: str) -> CalculationMethod:
        with self.database.session() as db:
            method = db.get(CalculationMethod, method_id)
            if method is None:
                raise DomainError(
                    code="CALCULATION_METHOD_NOT_FOUND",
                    message=f"calculation method not found: {method_id}",
                    status_code=404,
                )
            return method

    def list_versions(self, method_id: str) -> list[CalculationMethodVersion]:
        with self.database.session() as db:
            return list(
                db.scalars(
                    select(CalculationMethodVersion)
                    .where(CalculationMethodVersion.method_id == method_id)
                    .order_by(CalculationMethodVersion.version.desc())
                )
            )

    def get_version(self, method_id: str, version: int) -> CalculationMethodVersion | None:
        with self.database.session() as db:
            return db.scalar(
                select(CalculationMethodVersion).where(
                    CalculationMethodVersion.method_id == method_id,
                    CalculationMethodVersion.version == version,
                )
            )

    def build_detail(self, method: CalculationMethod) -> dict:
        versions = self.list_versions(method.id)
        return {
            "method": method,
            "latest_version": versions[0].version if versions else 0,
            "versions": versions,
        }

    def archive_method(self, method_id: str) -> CalculationMethod:
        """Stop a scheme from new use without deleting its history.

        Archiving is the only irreversible-ish action offered here: the method and every version stay
        readable, while the head version leaves ``ready`` so a citation can no longer group a result.
        Deletion is not offered - a historical result may still cite this identity.
        """
        with self.database.session() as db:
            method = db.get(CalculationMethod, method_id)
            if method is None:
                raise DomainError(
                    code="CALCULATION_METHOD_NOT_FOUND",
                    message=f"calculation method not found: {method_id}",
                    status_code=404,
                )
            latest = db.scalar(
                select(CalculationMethodVersion)
                .where(CalculationMethodVersion.method_id == method_id)
                .order_by(CalculationMethodVersion.version.desc())
                .limit(1)
            )
            method.status = "retired"
            if latest is not None and latest.status == "ready":
                latest.status = "retired"
            db.commit()
            db.refresh(method)
            return method

    def capabilities(self, method_id: str) -> dict:
        """Declare what this method can do, so a reader never triggers an unrelated guard.

        A tag scheme is an analysis caliber: it needs no processing package, no template binding
        and no regulatory boundary. A legacy method reports whether its own base can offer a
        selectable package and, when it cannot, the exact reason - a capability statement, not a
        swallowed error.
        """
        from .model_processing_runtime import template_identity

        with self.database.session() as db:
            method = db.get(CalculationMethod, method_id)
            if method is None:
                raise DomainError(
                    code="CALCULATION_METHOD_NOT_FOUND",
                    message=f"calculation method not found: {method_id}",
                    status_code=404,
                )
            latest = db.scalar(
                select(CalculationMethodVersion)
                .where(CalculationMethodVersion.method_id == method_id)
                .order_by(CalculationMethodVersion.version.desc())
                .limit(1)
            )
            semantics = latest.semantics if latest else None
            tag_scheme = _is_tag_scheme(semantics)
            result_category = _is_result_category(semantics)
            legacy_ordinary = _is_legacy_ordinary(semantics, method.purpose)
            legacy_method = tag_scheme or legacy_ordinary
            processing_selection = False
            reason: dict | None = None
            if tag_scheme:
                reason = {
                    "code": "CALCULATION_METHOD_TAG_NO_PROCESSING_PACKAGE",
                    "message": "a flow-tag scheme narrows nothing, so it never selects a processing package",
                }
            elif result_category:
                reason = {
                    "code": "CALCULATION_METHOD_RESULT_CATEGORY_NO_PROCESSING_PACKAGE",
                    "message": "a result-category caliber groups a frozen result and never selects a processing package",
                }
            elif legacy_ordinary:
                reason = {
                    "code": "CALCULATION_METHOD_LEGACY_METHOD_NO_PROCESSING_PACKAGE",
                    "message": "a legacy method is read-only; convert it to a result-category caliber before editing",
                }
            else:
                try:
                    revision, _model = require_revision(
                        db, method.model_revision_id, method.application_id
                    )
                    application = db.get(Application, method.application_id)
                    template_identity(revision, application)
                    processing_selection = True
                except DomainError as exc:
                    reason = {"code": exc.code, "message": exc.message}
            return {
                "method_id": method.id,
                "method_name": method.name,
                "semantics": semantics,
                "latest_version": latest.version if latest else None,
                "latest_status": latest.status if latest else None,
                "content_sha256": latest.content_sha256 if latest else None,
                "purpose": method.purpose,
                "tag_scheme": tag_scheme,
                "tag_grouping": tag_scheme or result_category,
                "result_category": result_category,
                "legacy_tag_scheme": tag_scheme,
                "legacy_method": legacy_method,
                "conversion_available": bool(
                    legacy_method and latest is not None and method.status != "retired"
                ),
                "dedicated_strategy": None,
                "processing_package_selection": processing_selection,
                "processing_package_reason": reason,
            }

    def conversion_preview(
        self, method_id: str, version: int, options: dict | None = None
    ) -> dict:
        """Count exactly what converting one legacy method version would carry over.

        The same mapping options are accepted here and by the apply, so a confirmed preview is the
        plan that actually runs; an unresolved invalid category blocks both.
        """
        with self.database.session() as db:
            method, record = self._conversion_source(db, method_id, version)
            preview, _rules, _dimension = self._conversion_plan(method, record, options)
            return preview

    def convert_to_result_category(
        self, method_id: str, version: int, payload: ResultCategoryConversionCreate
    ) -> CalculationMethod:
        """Copy the eligible relations into a new, independent result-category method.

        The source method keeps every version and its content hash; the copy is a new method with
        its own identity, so an old snapshot citing the legacy version never changes meaning.
        """
        options = {
            "source_dimension_id": payload.source_dimension_id,
            "target_dimension": payload.target_dimension.model_dump(mode="json")
            if payload.target_dimension is not None
            else None,
            "resolutions": [item.model_dump(mode="json") for item in payload.resolutions],
        }
        with self.database.session() as db:
            method, record = self._conversion_source(db, method_id, version)
            preview, source_rules, dimension = self._conversion_plan(method, record, options)
            if (
                payload.expected_mapping_sha256
                and payload.expected_mapping_sha256 != preview["mapping_sha256"]
            ):
                raise DomainError(
                    code="TAG_SCHEME_CONVERSION_MAPPING_CHANGED",
                    message="the confirmed mapping no longer matches this preview; preview again",
                    status_code=409,
                    details={
                        "expected_mapping_sha256": payload.expected_mapping_sha256,
                        "mapping_sha256": preview["mapping_sha256"],
                    },
                )
            if not preview["can_convert"]:
                reason = preview["reason"] or {}
                raise DomainError(
                    code=reason.get("code") or "TAG_SCHEME_CONVERSION_UNRESOLVED_MAPPING",
                    message=reason.get("message") or "this legacy method cannot be converted as mapped",
                    status_code=422,
                    details={"problems": preview["problems"]},
                )
            revision, _model = require_revision(
                db, method.model_revision_id, method.application_id
            )
            require_process_ids(
                revision,
                sorted({rule["process_instance_id"] for rule in source_rules}),
            )
            rules = [deepcopy(rule) for rule in source_rules]
            dimensions = [deepcopy(dimension)]
            _require_valid_dimensions(dimensions)
            _require_unique_rule_identities(rules)
            _require_valid_tag_scheme(
                semantics=RESULT_CATEGORY_SEMANTICS,
                purpose="custom",
                cbam_boundary_ref=None,
                variant_ref=None,
                dimensions=dimensions,
                rules=rules,
            )
            _normalize_result_category_rules(rules)
            created = CalculationMethod(
                application_id=method.application_id,
                model_revision_id=method.model_revision_id,
                purpose="custom",
                name=payload.name,
                description=method.description,
                origin_method_id=method.id,
                origin_method_version=record.version,
                origin_content_sha256=record.content_sha256,
                status="draft",
            )
            db.add(created)
            try:
                db.flush()
            except IntegrityError as exc:
                db.rollback()
                raise DomainError(
                    code="CALCULATION_METHOD_NAME_CONFLICT",
                    message="a method with this name already exists for this model revision",
                    status_code=409,
                    details={"name": payload.name},
                ) from exc
            db.add(
                CalculationMethodVersion(
                    method_id=created.id,
                    version=1,
                    rules=rules,
                    reporting_dimensions=dimensions,
                    model_processing_rules_ref=None,
                    cbam_boundary_ref=None,
                    semantics=RESULT_CATEGORY_SEMANTICS,
                    content_sha256=version_content_sha256(
                        "custom", None, rules, dimensions, None, RESULT_CATEGORY_SEMANTICS
                    ),
                    status="draft",
                )
            )
            db.commit()
            db.refresh(created)
            return created

    def _conversion_source(self, db, method_id: str, version: int):
        method = db.get(CalculationMethod, method_id)
        if method is None:
            raise DomainError(
                code="CALCULATION_METHOD_NOT_FOUND",
                message=f"calculation method not found: {method_id}",
                status_code=404,
            )
        record = db.scalar(
            select(CalculationMethodVersion).where(
                CalculationMethodVersion.method_id == method_id,
                CalculationMethodVersion.version == version,
            )
        )
        if record is None:
            raise DomainError(
                code="CALCULATION_METHOD_VERSION_NOT_FOUND",
                message=f"calculation method version not found: {method_id}@{version}",
                status_code=404,
            )
        if not _is_legacy_method(record.semantics, method.purpose):
            raise DomainError(
                code="TAG_SCHEME_CONVERSION_NOT_LEGACY",
                message="only a legacy method version can be converted into a result-category caliber",
                status_code=422,
                details={"method_id": method_id, "version": version},
            )
        digest = version_content_sha256(
            method.purpose,
            record.cbam_boundary_ref,
            record.rules,
            record.reporting_dimensions,
            record.model_processing_rules_ref,
            record.semantics,
        )
        if digest != record.content_sha256:
            raise DomainError(
                code="TAG_SCHEME_CONVERSION_SOURCE_CORRUPT",
                message="the legacy version content no longer matches its stored hash",
                status_code=409,
                details={"method_id": method_id, "version": version},
            )
        return method, record

    @staticmethod
    def _conversion_plan(
        method: CalculationMethod,
        record: CalculationMethodVersion,
        options: dict | None = None,
    ):
        """One mapping used by both the preview and the apply, so counts cannot drift.

        A legacy method may carry no category tree, several trees, or rules pointing outside the
        chosen tree. None of those is guessed: the caller chooses the source tree, supplies a
        target tree when the source has none, and resolves every invalid category to a declared
        leaf or explicitly to “无”.
        """
        options = options or {}
        source_dimension_id = options.get("source_dimension_id")
        supplied_target = options.get("target_dimension")
        target_dimension = deepcopy(supplied_target) if supplied_target else None
        resolution_input = options.get("resolutions") or []
        dimensions = [
            dict(item)
            for item in (record.reporting_dimensions or [])
            if isinstance(item, dict) and item.get("id")
        ]
        source_dimension = None
        reason: dict | None = None
        if source_dimension_id:
            source_dimension = next(
                (item for item in dimensions if str(item.get("id")) == source_dimension_id),
                None,
            )
            if source_dimension is None:
                reason = {
                    "code": "TAG_SCHEME_CONVERSION_UNKNOWN_DIMENSION",
                    "message": "the chosen category tree is absent from this legacy version",
                }
        elif len(dimensions) == 1:
            source_dimension = dimensions[0]
        elif len(dimensions) > 1:
            reason = {
                "code": "TAG_SCHEME_CONVERSION_DIMENSION_REQUIRED",
                "message": "this legacy version declares several category trees; choose the one to carry over",
            }
        if target_dimension is None:
            target_dimension = deepcopy(source_dimension)
        if target_dimension is None:
            if reason is None:
                reason = {
                    "code": "TAG_SCHEME_CONVERSION_TARGET_REQUIRED",
                    "message": "this legacy version declares no category tree; declare the target categories to map its flows",
                }
        else:
            try:
                _normalized_dimensions([target_dimension])
            except ValueError as exc:
                target_dimension = None
                reason = {
                    "code": "TAG_SCHEME_CONVERSION_TARGET_INVALID",
                    "message": f"the target category tree is not valid: {exc}",
                }
        dimension_id = str((source_dimension or {}).get("id") or "")
        target_id = str((target_dimension or {}).get("id") or "")
        leaves = _category_leaves(target_dimension) if target_dimension is not None else set()
        resolutions: dict[int, str | None] = {}
        for item in resolution_input:
            index = int(item.get("rule_index", -1))
            if index in resolutions:
                reason = reason or {
                    "code": "TAG_SCHEME_CONVERSION_RESOLUTION_DUPLICATE",
                    "message": "one rule has more than one mapping decision",
                }
            resolutions[index] = item.get("category")
        counts = {
            "total": len(record.rules),
            "assigned": 0,
            "selected_without_category": 0,
            "pending": 0,
            "excluded": 0,
            "invalid_category": 0,
            "unresolved_invalid": 0,
            "resolved_without_category": 0,
        }
        rows: list[dict] = []
        target: list[dict] = []
        problems: list[dict] = []
        seen: set[tuple] = set()
        for index, rule in enumerate(record.rules):
            categories = rule.get("categories") or {}
            old_category = (
                str(categories.get(dimension_id))
                if dimension_id and categories.get(dimension_id)
                else None
            )
            foreign = sorted(
                str(key) for key in categories if dimension_id and str(key) != dimension_id and categories.get(key)
            )
            status = rule.get("boundary_status")
            needs_resolution = False
            resolved = False
            new_category = None
            if status != "selected":
                outcome = "unassigned"
                counts["pending" if status == "pending" else "excluded"] += 1
            elif target_dimension is None:
                outcome = "invalid_category"
                counts["invalid_category"] += 1
                needs_resolution = True
            elif old_category and old_category in leaves:
                outcome = "assigned"
                new_category = old_category
            elif old_category:
                outcome = "invalid_category"
                counts["invalid_category"] += 1
                needs_resolution = True
            elif foreign:
                outcome = "invalid_category"
                counts["invalid_category"] += 1
                needs_resolution = True
            elif not dimension_id:
                outcome = "invalid_category"
                counts["invalid_category"] += 1
                needs_resolution = True
            else:
                outcome = "unassigned"
                counts["selected_without_category"] += 1
            if needs_resolution and index in resolutions:
                choice = resolutions.pop(index)
                if choice is None:
                    outcome, resolved = "unassigned", True
                    counts["resolved_without_category"] += 1
                elif str(choice) in leaves:
                    outcome, resolved, new_category = "assigned", True, str(choice)
                else:
                    problems.append(
                        {
                            "code": "TAG_SCHEME_CONVERSION_RESOLUTION_UNKNOWN",
                            "message": "the chosen category is not a leaf of the target tree",
                            "rule_index": index,
                            "exchange_id": rule.get("exchange_id"),
                            "category": choice,
                        }
                    )
            if outcome == "invalid_category":
                counts["unresolved_invalid"] += 1
                problems.append(
                    {
                        "code": (
                            "TAG_SCHEME_CONVERSION_CATEGORY_INVALID"
                            if old_category
                            else "TAG_SCHEME_CONVERSION_CATEGORY_OUTSIDE_DIMENSION"
                            if foreign
                            else "TAG_SCHEME_CONVERSION_CATEGORY_REQUIRED"
                        ),
                        "message": "choose a declared leaf for this flow, or explicitly choose “无”",
                        "rule_index": index,
                        "exchange_id": rule.get("exchange_id"),
                        "category": old_category,
                    }
                )
            elif outcome == "assigned":
                counts["assigned"] += 1
                identity = _rule_identity(rule)
                if identity in seen:
                    problems.append(
                        {
                            "code": "TAG_SCHEME_CONVERSION_DUPLICATE_RULE",
                            "message": "two legacy rules name the same exchange; the copy would not validate",
                            "rule_index": index,
                            "exchange_id": rule.get("exchange_id"),
                        }
                    )
                seen.add(identity)
                copied = deepcopy(rule)
                # The copy carries one meaning, the chosen category. Scope/boundary fields describe
                # the legacy editor and would be rejected by the result-category validator.
                copied["categories"] = {target_id: new_category}
                copied["boundary_status"] = "selected"
                copied["boundary"] = None
                copied["cbam_relevant"] = False
                copied["classification_basis"] = "user"
                copied["scope"] = None
                target.append(copied)
            rows.append(
                {
                    "rule_index": index,
                    "process_instance_id": rule.get("process_instance_id"),
                    "exchange_id": rule.get("exchange_id"),
                    "flow_uuid": rule.get("flow_uuid"),
                    "old_category": old_category,
                    "new_category": new_category if outcome == "assigned" else None,
                    "outcome": outcome,
                    "needs_resolution": needs_resolution and not resolved,
                    "resolved": resolved,
                }
            )
        for index in resolutions:
            problems.append(
                {
                    "code": "TAG_SCHEME_CONVERSION_RESOLUTION_NOT_APPLICABLE",
                    "message": "this rule needs no mapping decision",
                    "rule_index": index,
                }
            )
        if reason is None and problems:
            codes = {problem["code"] for problem in problems}
            if counts["unresolved_invalid"]:
                reason = {
                    "code": "TAG_SCHEME_CONVERSION_UNRESOLVED_MAPPING",
                    "message": "some selected flows still have no valid category; map each to a leaf or choose “无”",
                }
            elif "TAG_SCHEME_CONVERSION_DUPLICATE_RULE" in codes:
                reason = {
                    "code": "TAG_SCHEME_CONVERSION_DUPLICATE_RULE",
                    "message": "two selected legacy rules name the same exchange; the copy would not validate",
                }
            else:
                reason = {
                    "code": "TAG_SCHEME_CONVERSION_MAPPING_REJECTED",
                    "message": "the supplied mapping decisions do not match this legacy version",
                }
        can_convert = reason is None and not problems
        source_dimensions = [
            {
                "id": str(item.get("id")),
                "name": item.get("name"),
                "category_count": len(
                    [category for category in item.get("categories") or [] if isinstance(category, dict)]
                ),
                "rule_count": sum(
                    1
                    for rule in record.rules
                    if str((rule.get("categories") or {}).get(str(item.get("id"))) or "").strip()
                ),
            }
            for item in dimensions
        ]
        preview = {
            "source_method_id": method.id,
            "source_method_name": method.name,
            "source_version": record.version,
            "source_semantics": record.semantics,
            "source_content_sha256": record.content_sha256,
            "source_dimensions": source_dimensions,
            "source_dimension_id": dimension_id or None,
            "target_semantics": RESULT_CATEGORY_SEMANTICS,
            "target_dimension_id": target_id or None,
            "dimension": deepcopy(target_dimension) if target_dimension is not None else None,
            "counts": counts,
            "rules": rows,
            "problems": problems,
            "can_convert": can_convert,
            "reason": reason,
            "mapping_sha256": canonical_json_sha256({"dimension": target_dimension, "rules": rows}),
        }
        return preview, target, target_dimension

    def list_selectable_processing_packages(self, method_id: str) -> list[dict]:
        """Every processing package a user may bind to a variant of this method, with applicability.

        This is the selection surface, so it offers packages the automatic resolver hides
        (``explicit_only`` ones) and reports, for the method's own purpose, how each treats emissions -
        the fact that distinguishes a package a variant can narrow per-exchange from one that takes
        the template's emission set as already final. Selection is against the exact project template
        and graph the method's revision carries, never a moved head.
        """
        from ..model_processing_contract import list_model_processing_rules_for_template
        from .model_processing_runtime import template_identity
        from .returned_cbam_binding import _identity_graph

        with self.database.session() as db:
            method = db.get(CalculationMethod, method_id)
            if method is None:
                raise DomainError(
                    code="CALCULATION_METHOD_NOT_FOUND",
                    message=f"calculation method not found: {method_id}",
                    status_code=404,
                )
            latest = db.scalar(
                select(CalculationMethodVersion)
                .where(CalculationMethodVersion.method_id == method_id)
                .order_by(CalculationMethodVersion.version.desc())
                .limit(1)
            )
            if latest is not None and _is_tag_scheme(latest.semantics):
                raise DomainError(
                    code="CALCULATION_METHOD_TAG_NO_PROCESSING_PACKAGE",
                    message="a flow-tag scheme has no dedicated calculation strategy to narrow,"
                    " so there is no processing package to select",
                    status_code=422,
                )
            if latest is not None and _is_result_category(latest.semantics):
                raise DomainError(
                    code="CALCULATION_METHOD_RESULT_CATEGORY_NO_PROCESSING_PACKAGE",
                    message="a result-category caliber groups a frozen result and has no processing"
                    " package to select",
                    status_code=422,
                )
            revision, _model = require_revision(
                db, method.model_revision_id, method.application_id
            )
            application = db.get(Application, method.application_id)
            template = template_identity(revision, application)
            graph = revision.graph_snapshot
            graph_identity = canonical_json_sha256(_identity_graph(graph))
            selectable = list_model_processing_rules_for_template(
                template, graph_identity_sha256=graph_identity, graph=graph
            )
            options: list[dict] = []
            for rules in selectable:
                purpose_declared = method.purpose in rules.purposes
                flows_mode = (
                    rules.purpose(method.purpose).elementary_flows.mode
                    if purpose_declared
                    else None
                )
                options.append(
                    {
                        "package_id": rules.package_id,
                        "version": rules.version,
                        "content_sha256": rules.content_sha256,
                        "selection_mode": rules.selection_mode,
                        "purpose_declared": purpose_declared,
                        "elementary_flows_mode": flows_mode,
                    }
                )
            return options


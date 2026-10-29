"""One entry that resolves, validates and compiles a cited calculation method version.

Organization, PCF and CBAM all follow a user calculation method through this single
function so no service re-interprets the stored rules on its own. It proves the cited
version is still exact — application, bound model revision, purpose and content hash
all match the run, and the version passed validation against *this* content and
revision — then compiles the effective rules into an immutable execution plan and
freezes its hash, so a run can be replayed or recovered against exactly the grouping
it was accepted with, never a moved head.

The validation conclusion is bound to the content, not to a version pointer: every
``CalculationMethodVersion`` is an immutable, revision-bound row whose ``content_sha256``
is re-checked here, so a ``status == "ready"`` on a superseded history version describes
that version's own rules, and editing a newer version can never change what this plan
freezes. It never invents numbers — the plan records object selection, inheritance
source, contribution target, include/exclude boundary and per-dimension category only;
emission factors and weighted values stay with Nebula LCA.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from ..analysis.method_compile import compile_method_rules
from ..analysis.method_rule_adapter import adapt_rules
from ..analysis.tag_grouping import RESULT_CATEGORY_SEMANTICS, TAG_SEMANTICS
from ..errors import DomainError
from ..runtime_models import CalculationMethod, CalculationMethodVersion
from ..runtime_schemas import CalculationMethodRef

EXECUTION_PLAN_SCHEMA_VERSION = "nebula_one.method-execution-plan.v1"
# The compiler that produced the plan. R6 freezes this so a recovered run re-compiles
# with the same executor and can verify the plan hash rather than trust a stored shape.
EXECUTION_COMPILER_VERSION = "nebula_one.method-compiler.v1"

# The base method package every rule of a version builds its grouping on. Rules may
# each cite ``base_method_ref``; more than one distinct package in a single version is
# an ambiguous plan, so it fails closed instead of resolving by rule order.
def _base_package_refs(rules: list[dict[str, Any]]) -> list[str]:
    refs: set[str] = set()
    for rule in rules:
        ref = rule.get("base_method_ref")
        if ref:
            refs.add(str(ref))
    return sorted(refs)


def _declared_targets(
    exchange_rules: list[dict[str, Any]],
    process_defaults: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Turn each adapted rule into the concrete target the compiler resolves.

    An exchange rule already names one consumption path; a process default is recorded
    under an empty ``exchange_id`` so the compiler resolves it through the process layer
    and reports the inheritance source as ``process``. This freezes the method's *declared*
    plan, independent of any one solve's exchange list.
    """
    targets: list[dict[str, Any]] = []
    for rule in exchange_rules:
        targets.append(
            {
                "exchange_id": rule.get("exchange_id"),
                "process_instance_id": rule.get("process_instance_id"),
                "contribution_target": rule.get("contribution_target"),
            }
        )
    for rule in process_defaults:
        targets.append(
            {
                "exchange_id": "",
                "process_instance_id": rule.get("process_instance_id"),
                "contribution_target": rule.get("contribution_target"),
            }
        )
    return targets


def resolve_method_execution_plan(
    db,
    *,
    application_id: str,
    system_revision_id: str,
    purpose: str | None,
    ref: CalculationMethodRef | dict[str, Any] | None,
    require_ready: bool = True,
) -> dict[str, Any] | None:
    """Return the frozen execution plan for an exact cited version, or ``None``.

    ``purpose`` is the accounting purpose the run answers; when it is given it must
    match the method's declared purpose, so a method built for one purpose is never
    silently followed by a run of another. A plain solve/freeze carries no named
    purpose (``None``), and then the method's own purpose is authoritative.

    Raises a typed ``DomainError`` when the reference has drifted in any way that would
    make a frozen calculation ambiguous: unknown method/version, a different application
    or model revision, a purpose that does not match the run, a content hash that no
    longer matches, an unvalidated version, an ambiguous base method package, or rules
    that do not compile to a conflict-free plan.
    """
    if ref is None:
        return None

    if isinstance(ref, CalculationMethodRef):
        method_id, cited_version, cited_hash = (
            ref.method_id,
            ref.version,
            ref.content_sha256,
        )
    else:
        method_id = ref.get("method_id")
        cited_version = ref.get("version")
        cited_hash = ref.get("content_sha256")

    method = db.get(CalculationMethod, method_id)
    if method is None:
        raise DomainError(
            code="CALCULATION_METHOD_NOT_FOUND",
            message=f"calculation method not found: {method_id}",
            status_code=404,
        )
    if method.application_id != application_id:
        raise DomainError(
            code="CALCULATION_METHOD_APPLICATION_MISMATCH",
            message="calculation method does not belong to the requested application",
            status_code=409,
        )
    if method.model_revision_id != system_revision_id:
        raise DomainError(
            code="CALCULATION_METHOD_REVISION_MISMATCH",
            message="calculation method is bound to a different model revision than the one being solved",
            status_code=409,
            details={
                "method_revision_id": method.model_revision_id,
                "solve_revision_id": system_revision_id,
            },
        )
    if purpose is not None and method.purpose != purpose:
        raise DomainError(
            code="CALCULATION_METHOD_PURPOSE_MISMATCH",
            message="calculation method answers a different accounting purpose than this run",
            status_code=409,
            details={"method_purpose": method.purpose, "run_purpose": purpose},
        )

    record = db.scalar(
        select(CalculationMethodVersion).where(
            CalculationMethodVersion.method_id == method_id,
            CalculationMethodVersion.version == cited_version,
        )
    )
    if record is None:
        raise DomainError(
            code="CALCULATION_METHOD_VERSION_NOT_FOUND",
            message=f"calculation method version not found: {method_id}@{cited_version}",
            status_code=404,
        )
    if record.content_sha256 != cited_hash:
        raise DomainError(
            code="CALCULATION_METHOD_HASH_MISMATCH",
            message="the referenced method version content no longer matches the stored version",
            status_code=409,
            details={
                "referenced_content_sha256": cited_hash,
                "current_content_sha256": record.content_sha256,
            },
        )
    if require_ready and record.status != "ready":
        raise DomainError(
            code="CALCULATION_METHOD_NOT_VALIDATED",
            message="a calculation may only reference a validated (ready) method version",
            status_code=422,
            details={"status": record.status},
        )
    if record.semantics == RESULT_CATEGORY_SEMANTICS:
        # A result-category caliber only re-buckets a frozen pool. Executing it as an inclusion
        # method would give `categories` a second, contradictory meaning.
        raise DomainError(
            code="CALCULATION_METHOD_RESULT_CATEGORY_NOT_EXECUTABLE",
            message="a result-category caliber groups an existing result; it is not a solve method",
            status_code=422,
            details={"method_id": method_id, "version": record.version},
        )

    rules = [dict(rule) for rule in record.rules]
    base_refs = _base_package_refs(rules)
    if len(base_refs) > 1:
        raise DomainError(
            code="CALCULATION_METHOD_BASE_PACKAGE_AMBIGUOUS",
            message="one method version must build its grouping on a single base method package",
            status_code=422,
            details={"base_method_refs": base_refs},
        )

    dimensions = [dict(dim) for dim in (record.reporting_dimensions or [])]
    adapted = adapt_rules(
        rules,
        enforce_cbam_relevance=(method.purpose == "cbam"),
        dimensions=dimensions or None,
    )
    if adapted["conflicts"]:
        raise DomainError(
            code="CALCULATION_METHOD_PLAN_INVALID",
            message="the method rules do not resolve to a single conflict-free execution plan",
            status_code=422,
            details={"problems": adapted["conflicts"]},
        )
    exchange_targets = _declared_targets(
        adapted["exchange_rules"], adapted["process_defaults"]
    )
    # A declared dimension that requires full coverage makes its category mandatory on every
    # included contribution; the compiler fails closed rather than letting an override escape it.
    # A tag scheme reads ``requires_full_coverage`` as flow coverage (validated against the model's
    # own ports), not as a category mandate, so it never turns its dimension into a compiler gate.
    tag_scheme = record.semantics == TAG_SEMANTICS
    required_category_dimensions = (
        []
        if tag_scheme
        else [
            str(dim.get("id"))
            for dim in adapted["dimensions"]
            if dim.get("requires_full_coverage")
        ]
    )
    plan = compile_method_rules(
        dimensions=adapted["dimensions"],
        exchange_targets=exchange_targets,
        exchange_rules=adapted["exchange_rules"],
        process_defaults=adapted["process_defaults"],
        required_category_dimensions=required_category_dimensions,
    )
    if not plan["valid"]:
        raise DomainError(
            code="CALCULATION_METHOD_PLAN_INVALID",
            message="the method rules do not compile to a conflict-free execution plan",
            status_code=422,
            details={"problems": plan["problems"]},
        )

    return {
        "schema_version": EXECUTION_PLAN_SCHEMA_VERSION,
        "compiler_version": EXECUTION_COMPILER_VERSION,
        "method_id": method.id,
        "name": method.name,
        "purpose": method.purpose,
        "application_id": method.application_id,
        "model_revision_id": method.model_revision_id,
        "version": record.version,
        "content_sha256": record.content_sha256,
        # The version's explicit semantics travels with the frozen plan, so a run's result overlay
        # can tell a tag scheme from a boundary method without re-reading or guessing the method.
        "semantics": record.semantics,
        "cbam_boundary_ref": record.cbam_boundary_ref,
        # The exact processing package this variant version was bound to (None = automatic official
        # selection). It is part of the frozen plan so a run narrows against this reviewed selection
        # and a recovered run re-derives the same one, never a moved head.
        "model_processing_rules_ref": record.model_processing_rules_ref,
        "base_method_refs": base_refs,
        "rules": rules,
        "reporting_dimensions": dimensions,
        "validated_at": record.validated_at.isoformat() if record.validated_at else None,
        "execution_plan": {
            "dimensions": adapted["dimensions"],
            "resolved_targets": plan["resolved_targets"],
            "process_status": plan["process_status"],
        },
        "execution_plan_sha256": plan["execution_plan_sha256"],
    }


def recover_cbam_user_selection(
    db,
    *,
    application_id: str,
    system_revision_id: str,
    purpose: str | None,
    parameters: dict[str, Any],
) -> dict[str, Any] | None:
    """Rebuild the CBAM variant overlay an accepted run was derived under, or ``None``.

    A CBAM variant narrows a reviewed boundary, so the solve folds a ``user_calculation_method``
    identity into the frozen basis that both the worker recovery and the CBAM read-back must
    reproduce — otherwise re-deriving the narrowed model yields a different basis hash and the
    frozen answer refuses with a drift error. The overlay is rebuilt through this one shared
    execution contract the solve used: it resolves and recompiles the cited immutable version, so
    recovery recomputes the very ``execution_plan_sha256`` the run was accepted with rather than
    following a moved head. A non-CBAM purpose or a run that named no method version has no
    overlay. ``require_ready`` is not re-gated here because readiness was enforced when the run was
    accepted and every version row is immutable, so re-gating could only reject a still-exact
    history version.
    """
    if purpose != "cbam":
        return None
    ref = parameters.get("calculation_method_ref")
    if not isinstance(ref, dict):
        return None
    plan = resolve_method_execution_plan(
        db,
        application_id=application_id,
        system_revision_id=system_revision_id,
        purpose=purpose,
        ref=ref,
        require_ready=False,
    )
    return {
        "source": {
            "method_id": plan["method_id"],
            "version": plan["version"],
            "content_sha256": plan["content_sha256"],
        },
        "rules": plan["rules"],
        "execution_plan_sha256": plan["execution_plan_sha256"],
        "compiler_version": plan["compiler_version"],
    }

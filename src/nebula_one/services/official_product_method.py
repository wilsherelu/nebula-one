"""Install and bind a reviewed product method to its exact template descendant."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from sqlalchemy import select

from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..runtime_models import MethodPackage
from ..runtime_schemas import MethodPackageCreate


METHOD_ROOT = Path(__file__).resolve().parents[1] / "resources" / "official_methods"
METHOD_CAPABILITIES = {"product_carbon_footprint": "pcf.product.v1",
                       "organization_period_inventory": "organization.period.v1",
                       "cbam_partial_review": "cbam.partial-review.v1",
                       "organization_lifecycle_carbon": "organization.lifecycle-carbon.v1"}


def official_template_profile(context) -> dict | None:
    context = context or {}
    return (((context.get("modeling_template_binding") or {}).get("profile"))
            or ((context.get("seed_template") or {}).get("profile")))


def _bind(db, application, package_kind: str, *, revision=None) -> str | None:
    profile = official_template_profile(application.context)
    if not isinstance(profile, dict):
        return None
    graph_identity = None
    if revision is not None:
        from .returned_cbam_binding import _identity_graph
        graph_identity = canonical_json_sha256(_identity_graph(revision.graph_snapshot))
    matching = []
    library = ((application.context or {}).get('seed_template') or {}).get('accounting_library')
    frozen_pins = {(item['package_id'], item['version']): item['content_sha256']
                   for item in library['methods']} if library else None
    for path in METHOD_ROOT.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        payload = MethodPackageCreate.model_validate(data)
        if frozen_pins is not None:
            expected = frozen_pins.get((payload.package_id, payload.version))
            if expected is None:
                continue
            if canonical_json_sha256(payload.model_dump(mode='json')) != expected:
                raise DomainError(code='TEMPLATE_METHOD_LIBRARY_PIN_MISMATCH',
                                  message='核算方案集的固定方法内容已变化。', status_code=409)
        reviewed_graph = payload.manifest.get("reviewed_graph_identity_sha256")
        if (payload.package_kind == package_kind and payload.manifest.get("template_profile") == profile
                and (reviewed_graph is None or reviewed_graph == graph_identity)):
            matching.append(payload)
    if not matching:
        return None
    if matching:
        # The official packages use numeric release versions; retain older packages as exact
        # historical sources while binding only the newest reviewed release to new revisions.
        version_key = lambda payload: tuple(int(part) for part in payload.version.split("."))
        latest = max(version_key(payload) for payload in matching)
        matching = [payload for payload in matching if version_key(payload) == latest]
    if len(matching) != 1:
        raise DomainError(code="OFFICIAL_PRODUCT_METHOD_AMBIGUOUS", message="more than one product method matches this exact template profile", status_code=409)
    payload = matching[0]
    digest = canonical_json_sha256(payload.model_dump(mode="json"))
    existing = db.scalar(select(MethodPackage).where(MethodPackage.package_id == payload.package_id,
                                                    MethodPackage.version == payload.version))
    if existing is not None and existing.content_sha256 != digest:
        raise DomainError(code="OFFICIAL_PRODUCT_METHOD_CHANGED", message="registered product method differs from its versioned source", status_code=409)
    if existing is None:
        db.add(MethodPackage(package_id=payload.package_id, version=payload.version,
                             package_kind=payload.package_kind, jurisdiction=payload.jurisdiction,
                             valid_from=payload.valid_from, valid_to=payload.valid_to,
                             manifest=payload.manifest, content_sha256=digest, status="registered"))
    reference = f"{payload.package_id}@{payload.version}"
    context = deepcopy(application.context)
    refs = list(context.get("method_package_refs") or [])
    if reference not in refs:
        refs.append(reference)
        context["method_package_refs"] = refs
    capabilities = list(context.get("project_capabilities") or [])
    capability = METHOD_CAPABILITIES[package_kind]
    if capability not in capabilities:
        capabilities.append(capability)
        context["project_capabilities"] = capabilities
    if context != application.context:
        application.context = context
    db.flush()
    return reference


def bind_official_product_method(db, application) -> str | None:
    return _bind(db, application, "product_carbon_footprint")


def bind_official_organization_method(db, application) -> str | None:
    return _bind(db, application, "organization_period_inventory")


def bind_official_cbam_partial_method(db, application, *, revision=None) -> str | None:
    return _bind(db, application, "cbam_partial_review", revision=revision)


def bind_official_organization_lifecycle_method(db, application) -> str | None:
    return _bind(db, application, "organization_lifecycle_carbon")

"""Versioned climate method selection for new solves and frozen PCF views."""
from __future__ import annotations

import json
from functools import lru_cache
from math import isfinite
from importlib.resources import files

from sqlalchemy import select

from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..runtime_models import MethodPackage, SolvedSystemSnapshot
from ..runtime_schemas import MethodPackageCreate

_OFFICIAL_FILES = (
    "pcf-ef31-foreground-1.0.4.json",
    "pcf-ef31-native-model-boundary-1.0.0.json",
)
_NATIVE_RESPONSE = "provider.native-background-climate-total.response.v1"


@lru_cache(maxsize=1)
def _official_payloads() -> tuple[MethodPackageCreate, ...]:
    root = files("nebula_one").joinpath("resources/official_methods")
    return tuple(MethodPackageCreate.model_validate(json.loads(root.joinpath(name).read_text(encoding="utf-8")))
                 for name in _OFFICIAL_FILES)


def ensure_official_climate_methods(db) -> None:
    """Install authored method structures without changing a registered identity."""
    for payload in _official_payloads():
        digest = canonical_json_sha256(payload.model_dump(mode="json"))
        existing = db.scalar(select(MethodPackage).where(
            MethodPackage.package_id == payload.package_id,
            MethodPackage.version == payload.version,
        ))
        if existing is not None:
            if existing.content_sha256 != digest:
                raise DomainError(code="CLIMATE_METHOD_VERSION_CONFLICT",
                                  message="registered climate method differs from its versioned source",
                                  status_code=409, details={"reference": f"{payload.package_id}@{payload.version}"})
            continue
        db.add(MethodPackage(package_id=payload.package_id, version=payload.version,
                             package_kind=payload.package_kind, jurisdiction=payload.jurisdiction,
                             valid_from=payload.valid_from, valid_to=payload.valid_to,
                             manifest=payload.manifest, content_sha256=digest, status="registered"))
    db.flush()


def _reference(package: MethodPackage) -> str:
    return f"{package.package_id}@{package.version}"


def _official_refs() -> set[str]:
    return {f"{item.package_id}@{item.version}" for item in _official_payloads()}


def _candidates(db, bound_refs: list[str]) -> list[MethodPackage]:
    allowed = set(bound_refs) | _official_refs()
    return [item for item in db.scalars(select(MethodPackage).where(
        MethodPackage.package_kind == "product_carbon_footprint")).all()
            if _reference(item) in allowed]


def _choose(matches: list[MethodPackage], bound_refs: list[str]) -> MethodPackage | None:
    bound = [item for item in matches if _reference(item) in bound_refs]
    pool = bound or matches
    if len(pool) > 1:
        raise DomainError(code="CLIMATE_METHOD_AMBIGUOUS",
                          message="more than one exact climate method matches the frozen source",
                          status_code=409, details={"references": sorted(_reference(item) for item in pool)})
    return pool[0] if pool else None


def resolve_frozen_pcf_method(db, snapshot: SolvedSystemSnapshot, bound_refs: list[str]) -> MethodPackage | None:
    """Use the frozen answer; never infer a past method from catalog order."""
    frozen = ((snapshot.provider_receipt or {}).get("calculation_basis") or {}).get("calculation_method") or {}
    frozen_ref = frozen.get("reference")
    if frozen_ref:
        exact = [item for item in db.scalars(select(MethodPackage)).all()
                 if _reference(item) == frozen_ref and item.content_sha256 == frozen.get("content_sha256")]
        if len(exact) != 1:
            return None
        bound_refs = [frozen_ref]
    packages = _candidates(db, bound_refs)
    if frozen_ref:
        packages = [item for item in packages if _reference(item) == frozen_ref]
    envelope = snapshot.native_background_climate or {}
    answer = envelope.get("response") if isinstance(envelope, dict) else None
    if snapshot.native_background_climate is not None:
        request = envelope.get("request") if isinstance(envelope, dict) else None
        if (not isinstance(answer, dict) or not isinstance(request, dict)
                or request.get("schema_version") != "provider.native-background-climate-total.request.v1"
                or answer.get("merge_status") != "merged"
                or any(answer.get(key) != request.get(key) for key in (
                    "method_package_id", "method_package_version", "method_package_sha256",
                    "runtime_manifest_sha256",
                ))):
            return None
        native = []
        for item in packages:
            formula = item.manifest.get("formula_graph") or {}
            source = formula.get("source_method") or {}
            indicator = answer.get("indicator") or {}
            if (formula.get("source_contract") == _NATIVE_RESPONSE
                    and answer.get("schema_version") == _NATIVE_RESPONSE
                    and isinstance(answer.get("unified_climate_total"), (float, int))
                    and isfinite(answer["unified_climate_total"])
                    and source.get("id") == answer.get("method_package_id")
                    and source.get("version") == answer.get("method_package_version")
                    and source.get("content_sha256") == answer.get("method_package_sha256")
                    and formula.get("lcia_method") == indicator.get("method")
                    and formula.get("result_unit") == indicator.get("unit")):
                native.append(item)
        selected = _choose(native, bound_refs)
        return selected
    lcia = snapshot.lcia_results or {}
    rows = lcia.get("indicator_results") or []
    foreground = []
    for item in packages:
        formula = item.manifest.get("formula_graph") or {}
        key = formula.get("total_indicator_key")
        if (not formula.get("source_contract")
                and formula.get("source") in (None, "solved_system_snapshot.lcia_results")
                and formula.get("lcia_method") == lcia.get("method")
                and isinstance(rows, list) and isinstance(key, str)
                and len([row for row in rows if isinstance(row, dict)
                         and row.get("canonical_indicator_key") == key
                         and row.get("unit") == formula.get("result_unit")]) == 1):
            foreground.append(item)
    return _choose(foreground, bound_refs)


def resolve_new_climate_method(db, *, bound_refs: list[str], native: bool,
                               native_request: dict | None = None, preferred_ref: str | None = None) -> MethodPackage:
    """Pin one authored EF method before accepting a new climate solve."""
    default_formula = _official_payloads()[0].manifest["formula_graph"]
    matches = []
    for item in _candidates(db, bound_refs):
        formula = item.manifest.get("formula_graph") or {}
        if native:
            source = formula.get("source_method") or {}
            if (formula.get("source_contract") == _NATIVE_RESPONSE and native_request
                    and source.get("id") == native_request.get("method_package_id")
                    and source.get("version") == native_request.get("method_package_version")
                    and source.get("content_sha256") == native_request.get("method_package_sha256")
                    and formula.get("lcia_method") == default_formula["lcia_method"]
                    and formula.get("result_unit") == default_formula["result_unit"]):
                matches.append(item)
        elif (not formula.get("source_contract")
              and formula.get("source") == "solved_system_snapshot.lcia_results"
              and formula.get("lcia_method") == default_formula["lcia_method"]
              and formula.get("total_indicator_key") == default_formula["total_indicator_key"]
              and formula.get("result_unit") == default_formula["result_unit"]):
            matches.append(item)
    if preferred_ref is not None:
        matches = [item for item in matches if _reference(item) == preferred_ref]
    selected = _choose(matches, bound_refs)
    if selected is None:
        raise DomainError(code="CLIMATE_METHOD_UNAVAILABLE",
                          message="no versioned EF 3.1 climate method matches this calculation source",
                          status_code=422)
    return selected


def method_resolution(package: MethodPackage | None) -> dict:
    if package is None:
        return {"schema_version": "nebula_one.climate-method-resolution.v1",
                "status": "unavailable", "reference": None, "content_sha256": None,
                "reason_code": "CLIMATE_METHOD_UNAVAILABLE", "method": None}
    formula = package.manifest["formula_graph"]
    return {"schema_version": "nebula_one.climate-method-resolution.v1",
            "status": "ready", "reference": _reference(package),
            "content_sha256": package.content_sha256, "reason_code": None,
            "method": {"lcia_method": formula["lcia_method"],
                       "total_indicator_key": formula["total_indicator_key"],
                       "result_unit": formula["result_unit"],
                       "source_contract": formula.get("source_contract"),
                       "source_method": formula.get("source_method")}}

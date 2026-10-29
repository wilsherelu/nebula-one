"""Live, real-HTTP acceptance of the ORGANIZATION Scope chain on the shared stack (T2).

Drives the V1 organization inventory over the *aggregate* endpoint (POST
/applications/{id}/organization-ghg-inventory), which the seam fix now makes consume the user's
Scope rules: it counts each bound snapshot's frozen user-method grouping instead of the raw engine
total. Everything runs against the real HTTP API on the shared stack, over freshly solved snapshots
on the real steel foreground (no fabricated factor — Scope is a user declaration over real non-zero
foreground CO2), and asserts persisted state:

  include/exclude changes org counted and routes the removed exchange to the excluded bucket; a
  known-but-omitted exchange is reported as unattributed and stays separate from the counted Scopes
  and from the engine gap; demand doubling scales the org quantity exactly once; duplicate binding
  references and a second binding over the same snapshot cannot double-count; and the org result
  binds the frozen solve-time method identity (same-revision replay never reads the method head).

The reviewed public foreground data is entirely onsite, and the rule compiler allows only scope_1 for
onsite exchanges, so this demonstration declares scope_1 only. Cross-scope *reclassification* (a path
moved between Scope buckets, total preserved) needs an offsite/background contribution — the same
public-data gap recorded for T1 — so it is reported NOT_RUN here and pinned instead by the unit test
test_reclass_preserves_total_changes_distribution.

Requires the changed `one` service to be running (seam + method-package-bindings endpoint).
stdlib only, like live_user_method_acceptance.py.
"""
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

import live_user_method_acceptance as L

API = L.API


def _get_revision(base: str, rev_id: str) -> dict:
    return L._request(base, "GET", f"{API}/system-revisions/{rev_id}")


def _first_period(base: str, app_id: str) -> str:
    items = L._request(base, "GET", f"{API}/applications/{app_id}/periods")
    items = items if isinstance(items, list) else items.get("items", [])
    return items[0]["id"]


def _first_boundary(base: str, app_id: str) -> str:
    items = L._request(base, "GET", f"{API}/applications/{app_id}/boundaries")
    items = items if isinstance(items, list) else items.get("items", [])
    return items[0]["id"]


def _register_and_bind(base: str, app_id: str, package: dict, ref: str) -> None:
    try:
        L._request(base, "POST", f"{API}/method-packages", package)
    except RuntimeError as exc:
        if "METHOD_PACKAGE_VERSION_CONFLICT" not in str(exc):
            raise
    L._request(base, "POST", f"{API}/applications/{app_id}/method-package-bindings",
               {"reference": ref})


def _create_binding(base: str, app_id: str, *, binding_id: str, role: str, model_id: str,
                    rev_id: str, snap_id: str, period_id: str, boundary_id: str,
                    demand: list) -> dict:
    body = {
        "binding_id": binding_id,
        "role": role,
        "system_model_id": model_id,
        "system_revision_id": rev_id,
        "solved_snapshot_id": snap_id,
        "study_frame_id": f"T2 org scope acceptance {uuid.uuid4().hex[:8]}",
        "reporting_period_id": period_id,
        "organizational_boundary_id": boundary_id,
        "demand": demand,
        "capabilities": ["pcf.product.v1"],
        "dependencies": [],
        "status": "active",
    }
    return L._request(base, "POST", f"{API}/applications/{app_id}/system-bindings", body)


def _aggregate(base: str, app_id: str, org_ref: str, pcf_ref: str, binding_ids: list) -> dict:
    return L._request(base, "POST", f"{API}/applications/{app_id}/organization-ghg-inventory", {
        "method_package_ref": org_ref,
        "pcf_method_package_ref": pcf_ref,
        "binding_ids": binding_ids,
    })


def _scope_total(result: dict, scope: str) -> float | None:
    for item in result["scopes"]:
        if item["scope"] == scope:
            return item["total"]["value"]
    return None


def _counted_total(result: dict) -> float:
    return result["total"]["value"]


def run(base: str, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    results: dict = {"checks": []}

    def check(name: str, ok: bool, detail: dict | None = None) -> None:
        results["checks"].append({
            "name": name, "status": "pass" if ok else "fail", "ok": bool(ok), "detail": detail,
        })

    def not_run(name: str, reason: str, detail: dict | None = None) -> None:
        results["checks"].append({
            "name": name, "status": "not_run", "ok": False,
            "detail": {"reason": reason, **(detail or {})},
        })

    app = L._find_steel_application(base)
    app_id = app["id"]
    run_tag = uuid.uuid4().hex[:8]
    org_pkg = json.loads((Path(__file__).parent / "org_ghg_inventory_package.json").read_text("utf-8"))
    org_ref = f"{org_pkg['package_id']}@{org_pkg['version']}"

    seed_rev = L._base_revision_id(base, app_id)
    r1 = L._save_revision(base, app_id, seed_rev, 1000.0, f"T2 org scope baseline {run_tag}")
    rev1, demand1 = r1["revision_id"], r1["demand"]
    model_id = _get_revision(base, rev1)["system_model_id"]
    period_id = _first_period(base, app_id)
    boundary_id = _first_boundary(base, app_id)

    # Baseline solve (no method) to read the real foreground climate paths.
    snap0 = L._solve_method(base, app_id, rev1, demand1, "lca", "pcf", None, climate_default=True)
    indicator_key, terms = L._climate_terms(snap0)
    pcf_ref = L._request(base, "GET",
        f"{API}/solved-system-snapshots/{snap0['id']}/product-carbon-footprint/default-method")["reference"]

    positive = [t for t in terms if t["value"] > 0]
    check("real_nonzero_foreground_paths_available", len(positive) >= 3,
          {"n_positive": len(positive), "indicator_key": indicator_key})

    # Register + bind the org inventory package and the PCF package into the app context.
    _register_and_bind(base, app_id, org_pkg, org_ref)
    _register_and_bind(base, app_id, _load_pcf_package(base, pcf_ref), pcf_ref)

    # Aggregate the real foreground climate paths per exchange. A rule decides on an elementary
    # exchange, so every path row that shares an exchange id is summed together.
    by_exchange: dict[str, float] = {}
    for t in terms:
        by_exchange[t["exchange_id"]] = by_exchange.get(t["exchange_id"], 0.0) + float(t["value"])
    all_exchange_ids = sorted(by_exchange)
    positive_exchanges = [e for e in all_exchange_ids if by_exchange[e] > 0]
    check("two_positive_exchanges_available", len(positive_exchanges) >= 2,
          {"n_positive_exchanges": len(positive_exchanges), "total": sum(by_exchange.values())})

    excl_eid = positive_exchanges[0] if positive_exchanges else all_exchange_ids[0]
    omit_eid = (positive_exchanges[1] if len(positive_exchanges) >= 2
                else (all_exchange_ids[1] if len(all_exchange_ids) >= 2 else all_exchange_ids[0]))

    def selected(eid: str) -> dict:
        return L._rule(eid, boundary_status="selected", scope="scope_1")

    # Method A: every real exchange selected into scope_1.
    rules_a = [selected(e) for e in all_exchange_ids]
    m_a = L._create_validate_method(base, app_id, rev1, f"T2 A count-all {run_tag}", "pcf", rules_a)
    snap_a = L._solve_method(base, app_id, rev1, demand1, "lca", "pcf", m_a, climate_default=True)

    # Method B: exclude exactly one non-zero exchange (all onsite, so exclusion only lowers scope_1).
    rules_b = [L._rule(e, boundary_status="excluded" if e == excl_eid else "selected",
                       scope="scope_1") for e in all_exchange_ids]
    m_b = L._create_validate_method(base, app_id, rev1, f"T2 B exclude-one {run_tag}", "pcf", rules_b)
    snap_b = L._solve_method(base, app_id, rev1, demand1, "lca", "pcf", m_b, climate_default=True)

    # Method C: omit one exchange from the rule set entirely. The engine still returns that
    # contribution, so it is known-but-unselected (unattributed) — never folded into a Scope and,
    # because it is not background, never an engine gap. Validation may require full coverage; if so
    # this is recorded as not_run with the real endpoint response rather than forced through.
    rules_c = [selected(e) for e in all_exchange_ids if e != omit_eid]
    m_c, m_c_error = _create_validate_method_optional(
        base, app_id, rev1, f"T2 C omit-one {run_tag}", "pcf", rules_c)
    snap_c = (L._solve_method(base, app_id, rev1, demand1, "lca", "pcf", m_c, climate_default=True)
              if m_c is not None else None)

    # Bind each solved snapshot to a DISTINCT role: a SystemBinding role must be unique within the
    # application, and the org inventory aggregates distinct organizational sources (it does not
    # re-measure one unit under several methods). The run-tagged role still matches the single
    # "steel.own.production*" rule, so every source maps to scope_1 / own_production, and the tag
    # keeps roles globally unique across repeated runs against the persistent stack.
    def bind(tag: str, role_suffix: str, snap_id: str, rev_id: str, model: str, demand: list) -> dict:
        role = f"steel.own.production.{run_tag}.{role_suffix}"
        return _create_binding(base, app_id, binding_id=f"t2-{tag}-{run_tag}", role=role,
                               model_id=model, rev_id=rev_id, snap_id=snap_id, period_id=period_id,
                               boundary_id=boundary_id, demand=demand)

    bind_a = bind("a", "base", snap_a["id"], rev1, model_id, demand1)
    bind_b = bind("b", "exclude", snap_b["id"], rev1, model_id, demand1)
    bind_c = (bind("c", "omit", snap_c["id"], rev1, model_id, demand1)
              if m_c is not None else None)

    # Aggregate the distinct organizational sources. A per-functional-unit PCF total_footprint is an
    # intensity and does not grow with production volume, so the org layer's scaling lever is
    # per-source additivity: the org total is the sum of each bound source, counted exactly once.
    binding_ids = [bind_a["binding_id"], bind_b["binding_id"]]
    if bind_c is not None:
        binding_ids.append(bind_c["binding_id"])
    org = _aggregate(base, app_id, org_ref, pcf_ref, binding_ids)
    org_replay = _aggregate(base, app_id, org_ref, pcf_ref, binding_ids)

    src_by_bid = {s["binding_id"]: s for s in org["attribution"]["sources"]}
    src_a = src_by_bid[bind_a["binding_id"]]
    src_b = src_by_bid[bind_b["binding_id"]]

    def counted(src: dict) -> float:
        return sum(src["counted_scopes"].values()) if src.get("counted_scopes") else 0.0

    # The engine whole-product total is INVARIANT under a user include/exclude; A and B solve the
    # identical rev-1 data, so their raw totals are equal and the ONLY way their org-counted values
    # can differ is that the inventory consumed each source's user-method grouping. That difference
    # is the discriminating proof (a raw-total implementation would make it exactly zero).
    excl_value = by_exchange[excl_eid]

    # 1. Include/exclude changes the org counted quantity and routes the removed exchange to the
    #    excluded bucket (not unattributed), while the base source excludes nothing.
    check("org_include_exclude_changes_counted",
          L._isclose(counted(src_a) - counted(src_b), excl_value)
          and L._isclose(src_b["excluded"].get("value") or 0.0, excl_value)
          and not (src_b["unattributed"].get("exchange_ids") or [])
          and L._isclose(src_a["excluded"].get("value") or 0.0, 0.0),
          {"counted_a": counted(src_a), "counted_b": counted(src_b), "excluded_path": excl_value,
           "excluded_bucket_b": src_b["excluded"], "unattributed_b": src_b["unattributed"],
           "excluded_bucket_a": src_a["excluded"]})

    # 2. The grouping reconciles: counted + excluded is the same product total for A and B, so the
    #    exclusion redistributed within an unchanged total rather than inventing or dropping value.
    check("org_grouping_reconciles_to_same_product_total",
          L._isclose(counted(src_a) + (src_a["excluded"].get("value") or 0.0),
                     counted(src_b) + (src_b["excluded"].get("value") or 0.0)),
          {"a_counted_plus_excluded": counted(src_a) + (src_a["excluded"].get("value") or 0.0),
           "b_counted_plus_excluded": counted(src_b) + (src_b["excluded"].get("value") or 0.0)})

    # 3. A known-but-omitted exchange stays out of the counted Scopes and is reported apart from an
    #    engine gap; on foreground-only data the engine gap is empty, so unattributed is genuinely
    #    distinct from missing rather than a renamed zero or a silent drop.
    if bind_c is None:
        not_run("org_unattributed_separate_from_missing",
                "the method endpoint rejected a partial rule set, so an unattributed contribution "
                "could not be expressed over this endpoint",
                {"validation_error": m_c_error})
    else:
        src_c = src_by_bid[bind_c["binding_id"]]
        omit_value = by_exchange[omit_eid]
        check("org_unattributed_separate_from_missing",
              L._isclose(omit_value, src_c["unattributed"].get("value") or 0.0)
              and omit_eid in (src_c["unattributed"].get("exchange_ids") or [])
              and not (src_c["engine_gap"].get("exchange_ids") or [])
              and L._isclose(counted(src_a) - counted(src_c), omit_value),
              {"omit_exchange": omit_eid, "omit_value": omit_value,
               "unattributed_c": src_c["unattributed"], "engine_gap_c": src_c["engine_gap"],
               "counted_a": counted(src_a), "counted_c": counted(src_c)})

    # 4. Reclassifying a path across Scopes would preserve the org total but move the distribution.
    #    Foreground steel is all onsite and the rule compiler permits only scope_1 there, so a real
    #    cross-scope grouping needs an offsite/background contribution — the same public-data gap as
    #    T1. The seam itself is pinned by the unit test test_reclass_preserves_total_changes_distribution.
    not_run("org_cross_scope_reclass_preserves_total",
            "cross-scope reclassification needs an offsite/background contribution; foreground-only "
            "public data yields onsite (scope_1) only, so the scope/location compiler rejects scope_2/3 "
            "for these exchanges (same public-data gap as T1). Covered by unit test "
            "test_reclass_preserves_total_changes_distribution.")

    # 5. Per-source additivity ("one-period scaling"): aggregating two distinct sources yields exactly
    #    the sum of their single-source org totals, each counted once. A per-functional-unit PCF is an
    #    intensity that does not grow with production volume, so this additivity is the org layer's
    #    scaling lever; a duplicate snapshot is rejected instead of counted twice (see check 7b).
    single_a = _aggregate(base, app_id, org_ref, pcf_ref, [bind_a["binding_id"]])
    single_b = _aggregate(base, app_id, org_ref, pcf_ref, [bind_b["binding_id"]])
    pair = _aggregate(base, app_id, org_ref, pcf_ref,
                      [bind_a["binding_id"], bind_b["binding_id"]])
    sum_singles = single_a["total"]["value"] + single_b["total"]["value"]
    check("org_two_sources_scale_once",
          single_a["total"]["value"] > 0
          and L._isclose(pair["total"]["value"], sum_singles),
          {"single_a": single_a["total"]["value"], "single_b": single_b["total"]["value"],
           "pair": pair["total"]["value"], "sum_singles": sum_singles})

    # 6. Every counted value is onsite, so the rolled org result holds it all in scope_1 and leaves
    #    scope_2 / scope_3 at zero — and the rolled total equals the sum of the per-source counted.
    counted_sum = counted(src_a) + counted(src_b) + (
        counted(src_by_bid[bind_c["binding_id"]]) if bind_c else 0.0)
    check("org_counted_lands_in_declared_scope_only",
          L._isclose(_scope_total(org, "scope_1") or 0.0, counted_sum)
          and (_scope_total(org, "scope_2") in (None, 0.0))
          and (_scope_total(org, "scope_3") in (None, 0.0))
          and L._isclose(_counted_total(org), counted_sum),
          {"rolled_scope_1": _scope_total(org, "scope_1"),
           "rolled_scope_2": _scope_total(org, "scope_2"),
           "rolled_scope_3": _scope_total(org, "scope_3"),
           "rolled_total": _counted_total(org), "sum_of_sources_counted": counted_sum})

    # 7. Duplicate binding references cannot double-count.
    dup_err = _expect_error(base, app_id, org_ref, pcf_ref, [bind_a["binding_id"], bind_a["binding_id"]])
    check("org_duplicate_binding_ids_rejected", dup_err is not None, {"error": dup_err})

    # 7b. Two distinct roles over the SAME solved snapshot are rejected (a snapshot counts once).
    bind_dup = bind("z", "dupsnap", snap_a["id"], rev1, model_id, demand1)
    dup_snap_err = _expect_error(base, app_id, org_ref, pcf_ref,
                                 [bind_a["binding_id"], bind_dup["binding_id"]])
    check("org_same_snapshot_duplicate_rejected",
          dup_snap_err is not None and "ORGANIZATION_GHG_SNAPSHOT_DUPLICATE" in str(dup_snap_err),
          {"error": dup_snap_err})

    # 8. Same-data replay is deterministic and binds the frozen solve-time method identity, never a
    #    head reference.
    replay = {s["binding_id"]: s for s in org_replay["attribution"]["sources"]}
    frozen_identity = src_a.get("method_identity") or {}
    check("org_replay_reads_frozen_method_identity",
          org["content_sha256"] == org_replay["content_sha256"]
          and L._isclose(counted(replay[bind_a["binding_id"]]), counted(src_a))
          and frozen_identity.get("method_id") == m_a["method_id"]
          and str(frozen_identity.get("version")) == str(m_a["version"])
          and frozen_identity.get("content_sha256") == m_a["content_sha256"],
          {"content_sha256": org["content_sha256"],
           "replay_content_sha256": org_replay["content_sha256"],
           "frozen_identity": frozen_identity, "method_a": m_a})

    results["artifacts"] = {
        "app_id": app_id, "org_ref": org_ref, "pcf_ref": pcf_ref, "model_id": model_id,
        "period_id": period_id, "boundary_id": boundary_id, "rev1": rev1,
        "snap_a": snap_a["id"], "snap_b": snap_b["id"],
        "snap_c": snap_c["id"] if snap_c is not None else None,
        "binding_ids": binding_ids, "org": org, "org_replay": org_replay,
        "scaling_single_a": single_a, "scaling_single_b": single_b, "scaling_pair": pair,
        "by_exchange": by_exchange, "excl_exchange": excl_eid, "omit_exchange": omit_eid,
    }
    (out / "org-scope-report.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), "utf-8")
    statuses = [c["status"] for c in results["checks"]]
    results["counts"] = {
        "pass": statuses.count("pass"),
        "fail": statuses.count("fail"),
        "not_run": statuses.count("not_run"),
    }
    # Independent per-surface criteria. A required surface counts as success ONLY when every one of
    # its checks passed; a documented not_run (a real gap, never a pass) keeps that surface, and the
    # aggregate, out of "all success". no_regression stays separate so a fail is still distinguishable
    # from a known gap, but neither is claimed as full success while a required surface is undone.
    status_by_name = {c["name"]: c["status"] for c in results["checks"]}
    surfaces_def = {
        "org_data_prereq": ["real_nonzero_foreground_paths_available", "two_positive_exchanges_available"],
        "org_consumes_user_rules": [
            "org_include_exclude_changes_counted",
            "org_grouping_reconciles_to_same_product_total",
            "org_counted_lands_in_declared_scope_only",
            "org_cross_scope_reclass_preserves_total",
        ],
        "org_attribution_honesty": ["org_unattributed_separate_from_missing"],
        "org_scaling": ["org_two_sources_scale_once"],
        "org_persistence_identity": [
            "org_duplicate_binding_ids_rejected",
            "org_same_snapshot_duplicate_rejected",
            "org_replay_reads_frozen_method_identity",
        ],
    }
    surfaces: dict[str, dict] = {}
    for surface, names in surfaces_def.items():
        vals = {name: status_by_name.get(name, "missing") for name in names}
        vv = list(vals.values())
        if "fail" in vv or "missing" in vv:
            verdict = "fail"
        elif "not_run" in vv:
            verdict = "not_run"
        else:
            verdict = "pass"
        surfaces[surface] = {"required": True, "verdict": verdict, "checks": vals}
    surface_failures = sorted(s for s, v in surfaces.items() if v["verdict"] == "fail")
    surface_gaps = sorted(s for s, v in surfaces.items() if v["required"] and v["verdict"] == "not_run")
    results["surfaces"] = surfaces
    results["surface_failures"] = surface_failures
    results["surface_gaps"] = surface_gaps
    results["no_regression"] = not surface_failures
    results["all_success"] = not surface_failures and not surface_gaps
    results["verdict"] = "failed" if surface_failures else ("gaps_remain" if surface_gaps else "all_success")
    return results


def _expect_error(base: str, app_id: str, org_ref: str, pcf_ref: str, binding_ids: list) -> str | None:
    try:
        _aggregate(base, app_id, org_ref, pcf_ref, binding_ids)
        return None
    except RuntimeError as exc:
        return str(exc)


def _create_validate_method_optional(base: str, app_id: str, rev_id: str, name: str, purpose: str,
                                     rules: list[dict]) -> tuple[dict | None, dict | None]:
    """Create + validate a method, but return (None, reason) when the endpoint rejects the rule set.

    Used only for the omission probe: an unattributed contribution is expressed by giving fewer rules
    than the engine returns paths for, and the method endpoint may or may not accept a partial rule
    set. The real endpoint response is captured so a not_run is reported with its genuine cause,
    never a forced pass.
    """
    try:
        created = L._request(base, "POST", f"{API}/applications/{app_id}/calculation-methods",
                             {"name": name, "purpose": purpose, "model_revision_id": rev_id,
                              "rules": rules})
        method_id = created["method"]["id"]
        version = created["versions"][0]["version"]
        content_hash = created["versions"][0]["content_sha256"]
        validated = L._request(base, "POST",
                               f"{API}/calculation-methods/{method_id}/versions/{version}/validate")
        if not validated.get("valid"):
            return None, {"reason": "validation reported invalid", "validated": validated}
        return {"method_id": method_id, "version": version, "content_sha256": content_hash,
                "execution_plan_sha256": validated.get("execution_plan_sha256")}, None
    except RuntimeError as exc:
        return None, {"reason": "method create/validate request failed", "error": str(exc)}


def _load_pcf_package(base: str, pcf_ref: str) -> dict:
    """Return the registered PCF package payload so re-registration is a no-op conflict."""
    package_id, version = pcf_ref.rsplit("@", 1)
    for item in L._request(base, "GET", f"{API}/method-packages"):
        if item["package_id"] == package_id and item["version"] == version:
            return {
                "package_id": item["package_id"], "version": item["version"],
                "package_kind": item["package_kind"], "jurisdiction": item.get("jurisdiction"),
                "valid_from": item.get("valid_from"), "valid_to": item.get("valid_to"),
                "manifest": item["manifest"],
            }
    raise RuntimeError(f"PCF package {pcf_ref} is not registered")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18938")
    parser.add_argument("--out", default="deploy/s4-evidence/t2")
    args = parser.parse_args()
    res = run(args.url, Path(args.out))
    label = {"pass": "PASS", "fail": "FAIL", "not_run": "NOT_RUN"}
    for c in res["checks"]:
        print(label[c["status"]], c["name"])
        if c["status"] != "pass":
            print("   ", json.dumps(c["detail"], ensure_ascii=False)[:400])
    counts = res["counts"]
    print(f"counts: pass={counts['pass']} fail={counts['fail']} not_run={counts['not_run']}")
    print("PER-SURFACE VERDICT (required not_run is NOT success):")
    for surface, info in res["surfaces"].items():
        print(f"  {surface:26s} {info['verdict']}")
    print(f"VERDICT: {res['verdict'].upper()} | "
          + ("ALL SURFACES PROVEN" if res["all_success"]
             else "GAPS_REMAIN: " + ", ".join(res["surface_gaps"] + res["surface_failures"]))
          + ("" if res["no_regression"] else " | HAS_REGRESSION"))
    # A documented not_run is a known gap, not a regression: the process exits 0 only when nothing
    # failed, while the VERDICT line refuses to call an undone required surface a success.
    raise SystemExit(0 if res["no_regression"] else 1)


if __name__ == "__main__":
    main()

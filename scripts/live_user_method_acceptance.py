"""Live, real-HTTP acceptance of the user-defined calculation-method chain on the shared stack.

S4 evidence (see docs/QODER_USER_DEFINED_CALCULATION_METHODS_PLAN.md). This drives a REAL Nebula
LCA solve through the running One HTTP API on a *newly created, named* method/snapshot (it never
mutates the seeded model or existing snapshots), then asserts the whole success chain end to end:

  solve -> path_weighted_contribution_receipts -> persist -> execution-plan hash ->
  user-defined category grouping (org/PCF) -> counted A/B/C numerics ->
  history version replay -> demand-doubling scaling -> same-input dual-scenario comparison ->
  CBAM variant -> API/page/export bytes.

Modes:
  discover : additive baseline climate PCF solve + dumps the real response shapes (no asserts).
  full     : the complete numeric/chain assertion matrix, writes replayable artifacts + manifest.

Only Python stdlib (urllib) is used so it runs against the live entry without an extra venv.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

API = "/api/v1"
# This driver targets the explicitly selected local stack, bypassing inherited desktop proxies.
urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))


def _request(base: str, method: str, path: str, body: dict | None = None) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                raw = resp.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            error = json.loads(detail).get("error", {}) if detail.startswith("{") else {}
            if (attempt < 3 and method == "POST" and path.endswith("/solve")
                    and exc.code == 409 and error.get("code") == "ANALYSIS_RUN_IN_PROGRESS"):
                # Retry the IDENTICAL idempotent request; never change identity or erase its run.
                time.sleep(1)
                continue
            raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {detail[:800]}") from exc
    return json.loads(raw) if raw else {}


def _find_steel_application(base: str) -> dict:
    apps = _request(base, "GET", f"{API}/applications")
    items = apps if isinstance(apps, list) else apps.get("items", [])
    for app in items:
        name = (app.get("name") or "").lower()
        if "crude steel seed" in name or "bf-bof-crude-steel" in name:
            return app
    # A reviewed manifest names the seed application in Chinese, so the display name carries no
    # seed identity: fall back to the installed seed_template recorded on the application itself.
    # A project created from the template carries the same seed_id, so prefer the installed seed
    # modelling source (it has resource_purpose/display_name) over a derived project.
    candidates = []
    for app in items:
        detail = _request(base, "GET", f"{API}/applications/{app['id']}")
        seed = (detail.get("context") or {}).get("seed_template") or {}
        if str(seed.get("seed_id", "")).endswith("bf-bof-crude-steel"):
            candidates.append(detail)
    for detail in candidates:
        if (detail.get("context") or {}).get("resource_purpose"):
            return detail
    if candidates:
        return candidates[0]
    raise RuntimeError("no steel seed application found; is the steel catalog installed?")


def _base_revision_id(base: str, app_id: str) -> str:
    snapshots = _request(base, "GET", f"{API}/applications/{app_id}/solved-system-snapshots")
    items = snapshots if isinstance(snapshots, list) else snapshots.get("items", [])
    if not items:
        raise RuntimeError("steel application has no solved snapshot to derive a revision from")
    return items[0]["system_revision_id"]


def _fresh_revision(base: str, app_id: str, rev_id: str, amount: float) -> dict:
    """Save a new revision on a distinct matrix basis so the rebuilt engine's solve_hash cannot
    collide with a pre-rebuild cached snapshot, and never mutate the existing seed revision."""
    ws = _request(base, "GET", f"{API}/applications/{app_id}/workspace/{rev_id}")
    values = {f["key"]: f["value"] for f in (ws.get("fields") or [])}
    saved = _request(base, "POST", f"{API}/applications/{app_id}/workspace/inputs", {
        "revision_id": rev_id,
        "expected_content_sha256": ws["content_sha256"],
        "amounts": [amount],
        "demand_mode": "reference_output",
        "values": values,
        "source": "S4b live acceptance; isolated named scenario, not plant measurements",
    })
    return saved


def _solve(base: str, app_id: str, rev_id: str, *, method_ref: dict | None,
           purpose: str = "pcf", task: str = "pcf", demand: list[dict] | None = None) -> dict:
    body: dict = {
        "demand": demand,
        "idempotency_key": f"s4b-{task}-{purpose}-{uuid.uuid4().hex[:12]}",
        "analysis_task": task,
        "calculation_purpose": purpose,
        "climate_default": True,
    }
    if method_ref is not None:
        body["calculation_method_ref"] = method_ref
    return _request(base, "POST", f"{API}/applications/{app_id}/system-revisions/{rev_id}/solve", body)


def discover(base: str, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    app = _find_steel_application(base)
    app_id = app["id"]
    seed_rev = _base_revision_id(base, app_id)
    saved = _fresh_revision(base, app_id, seed_rev, amount=2.0)
    rev_id = saved["revision_id"]
    demand = saved.get("demand") or []
    snapshot = _solve(base, app_id, rev_id, method_ref=None, purpose="lca", demand=demand)
    snap_id = snapshot["id"]
    default_method = _request(base, "GET",
                              f"{API}/solved-system-snapshots/{snap_id}/product-carbon-footprint/default-method")
    method_ref = default_method.get("reference") or "pcf.iron-steel.native-model-boundary@1.0.3"
    pcf = _request(base, "POST",
                   f"{API}/solved-system-snapshots/{snap_id}/product-carbon-footprint",
                   {"method_package_ref": method_ref})
    dump = {
        "application_id": app_id,
        "seed_revision_id": seed_rev,
        "fresh_revision_id": rev_id,
        "baseline_snapshot_id": snap_id,
        "method_package_ref": method_ref,
        "default_method": default_method,
    }
    (out / "fresh-revision.json").write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "baseline-snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "baseline-pcf.json").write_text(json.dumps(pcf, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "discover.json").write_text(json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")

    def _has(o, needle):
        found = []
        stack = [(o, "")]
        while stack:
            cur, path = stack.pop()
            if isinstance(cur, dict):
                for k, v in cur.items():
                    p = f"{path}/{k}"
                    if needle in k:
                        found.append(p)
                    stack.append((v, p))
            elif isinstance(cur, list):
                for i, v in enumerate(cur[:5]):
                    stack.append((v, f"{path}[{i}]"))
        return found

    report = {
        "status": "discovered",
        "snapshot_id": snap_id,
        "snapshot_keys": sorted(snapshot.keys()),
        "n_scaled_technosphere": len(snapshot.get("scaled_technosphere_exchanges") or []),
        "n_scaled_elementary": len(snapshot.get("scaled_elementary_exchanges") or []),
        "path_weighted_in_snapshot": _has(snapshot, "path_weighted"),
        "pcf_keys": sorted(pcf.keys()),
        "pcf_contribution_keys": sorted((pcf.get("contribution_analysis") or {}).keys()),
        "grouping_in_pcf": _has(pcf, "grouping"),
        "method_grouping_mode": _has(pcf, "grouping_mode"),
        "total_footprint": pcf.get("total_footprint"),
    }
    (out / "discover-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _bytes(base: str, path: str) -> tuple[bytes, dict]:
    """GET a binary/text artifact, returning raw bytes and the lowercased response headers."""
    req = urllib.request.Request(base + path, method="GET", headers={"Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.read(), {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"GET {path} -> HTTP {exc.code}: {detail[:800]}") from exc


def _isclose(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def _final_output_field(ws: dict) -> dict:
    demand0 = (ws.get("demand") or [{}])[0]
    ref_flow = demand0.get("reference_flow_uuid")
    matches = [
        f for f in (ws.get("fields") or [])
        if f.get("group") == "outputs" and f.get("reference_product")
        and (ref_flow is None or f.get("flow_uuid") == ref_flow)
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one reference-product output field, got {len(matches)}")
    return matches[0]


def _save_revision(base: str, app_id: str, rev_id: str, output_amount: float, label: str) -> dict:
    """Save a new data version whose solve demand follows the edited reference-product output.

    ``amounts`` carries a placeholder so a green solve proves the demand tracked the edited
    final output rather than the batch field. The seed revision itself is never mutated.
    """
    ws = _request(base, "GET", f"{API}/applications/{app_id}/workspace/{rev_id}")
    values = {f["key"]: f["value"] for f in (ws.get("fields") or [])}
    values[_final_output_field(ws)["key"]] = output_amount
    saved = _request(base, "POST", f"{API}/applications/{app_id}/workspace/inputs", {
        "revision_id": rev_id,
        "expected_content_sha256": ws["content_sha256"],
        "amounts": [7],
        "demand_mode": "reference_output",
        "values": values,
        "source": label,
    })
    if not saved.get("saved"):
        raise RuntimeError(f"workspace save did not report saved: {saved}")
    return saved


def _rule(exchange_id: str, *, boundary_status: str, scope: str = "scope_1",
          cbam_relevant: bool = False, categories: dict | None = None,
          location_role: str = "onsite", direction: str = "emission") -> dict:
    # A custom-category rule omits Scope entirely (so the scope/location gate never fires) and
    # carries its classification in the method-declared reporting dimension via `categories`.
    # A background consumer-path rule instead binds to a purchasable input, so it overrides
    # location_role (scope_2 -> purchased_energy, scope_3 -> upstream_supply) and direction=input.
    return {
        "process_instance_id": exchange_id.split("::", 1)[0],
        "exchange_id": exchange_id,
        "flow_uuid": None,
        "direction": direction,
        "boundary_status": boundary_status,
        "location_role": location_role,
        "scope": None if boundary_status == "excluded" or categories else scope,
        "cbam_relevant": cbam_relevant,
        "classification_basis": "user",
        "schema_version": 2 if categories else 1,
        "contribution_target": "direct",
        "boundary": None,
        "categories": categories or {},
        "base_method_ref": None,
    }


def _create_validate_method(base: str, app_id: str, rev_id: str, name: str, purpose: str,
                            rules: list[dict], boundary_ref: str | None = None,
                            processing_ref: dict | None = None,
                            reporting_dimensions: list[dict] | None = None) -> dict:
    body: dict = {"name": name, "purpose": purpose, "model_revision_id": rev_id, "rules": rules}
    if boundary_ref is not None:
        body["cbam_boundary_ref"] = boundary_ref
    if processing_ref is not None:
        body["model_processing_rules_ref"] = processing_ref
    if reporting_dimensions is not None:
        body["reporting_dimensions"] = reporting_dimensions
    created = _request(base, "POST", f"{API}/applications/{app_id}/calculation-methods", body)
    method_id = created["method"]["id"]
    version = created["versions"][0]["version"]
    content_hash = created["versions"][0]["content_sha256"]
    validated = _request(base, "POST",
                         f"{API}/calculation-methods/{method_id}/versions/{version}/validate")
    if not validated.get("valid"):
        raise RuntimeError(f"method {name} failed validation: {validated}")
    return {"method_id": method_id, "version": version, "content_sha256": content_hash,
            "execution_plan_sha256": validated.get("execution_plan_sha256")}


def _solve_method(base: str, app_id: str, rev_id: str, demand: list, purpose: str,
                  task: str, ref: dict | None, *, climate_default: bool) -> dict:
    body: dict = {
        "demand": demand,
        "idempotency_key": f"s4b-{task}-{purpose}-{uuid.uuid4().hex[:12]}",
        "calculation_purpose": purpose,
        "analysis_task": task,
    }
    if climate_default:
        body["climate_default"] = True
    if ref is not None:
        body["calculation_method_ref"] = {
            "method_id": ref["method_id"], "version": ref["version"],
            "content_sha256": ref["content_sha256"],
        }
    return _request(base, "POST", f"{API}/applications/{app_id}/system-revisions/{rev_id}/solve", body)


def _pcf(base: str, snap_id: str, method_package_ref: str) -> dict:
    return _request(base, "POST",
                    f"{API}/solved-system-snapshots/{snap_id}/product-carbon-footprint",
                    {"method_package_ref": method_package_ref})


def _climate_terms(snapshot: dict) -> tuple[str, list[dict]]:
    receipts = (snapshot.get("lcia_results") or {}).get("path_weighted_contribution_receipts") or []
    for r in receipts:
        key = str(r.get("canonical_indicator_key") or "")
        if key.startswith("climate change|"):
            terms = [{"exchange_id": t["exchange_id"],
                      "value": float(t.get("path_contribution_value") or 0.0),
                      "attribution_basis": t.get("attribution_basis"),
                      "consumer_exchange_id": t.get("consumer_exchange_id"),
                      "path_share": t.get("path_share")} for t in (r.get("terms") or [])]
            return key, terms
    raise RuntimeError("engine returned no climate-change path-weighted receipt")


def _register_method_package(base: str, payload: dict) -> str:
    """Idempotently register a versioned method package; a re-run finds it already present."""
    body = {k: payload[k] for k in
            ("package_id", "version", "package_kind", "jurisdiction",
             "valid_from", "valid_to", "manifest") if k in payload}
    try:
        _request(base, "POST", f"{API}/method-packages", body)
        return "created"
    except RuntimeError as exc:
        if "-> HTTP 409" in str(exc):
            return "already-present"
        raise


def _register_and_bind(base: str, app_id: str, package: dict, ref: str) -> None:
    """Idempotently register a versioned package and bind it into the application context."""
    _register_method_package(base, package)
    _request(base, "POST", f"{API}/applications/{app_id}/method-package-bindings", {"reference": ref})


def _first_id(base: str, app_id: str, kind: str) -> str:
    items = _request(base, "GET", f"{API}/applications/{app_id}/{kind}")
    items = items if isinstance(items, list) else items.get("items", [])
    if not items:
        raise RuntimeError(f"application has no {kind}")
    return items[0]["id"]


def _load_registered_package(base: str, ref: str) -> dict:
    """Return an already-registered package's payload so a re-register is a no-op conflict."""
    package_id, version = ref.rsplit("@", 1)
    for item in _request(base, "GET", f"{API}/method-packages"):
        if item["package_id"] == package_id and item["version"] == version:
            return {k: item[k] for k in
                    ("package_id", "version", "package_kind", "jurisdiction",
                     "valid_from", "valid_to", "manifest") if k in item}
    raise RuntimeError(f"package {ref} is not registered")


def _dim_leaf_subtotals(pcf: dict, dim_id: str) -> tuple[dict, dict]:
    """Return (leaf_id -> subtotal, dim metadata) read from a PCF analysis custom-dimension grouping.

    None subtotal means the leaf carried no contribution (term_count 0), which is a real zero, so it
    is returned as 0.0 for arithmetic while the raw dict preserves the distinction.
    """
    ug = (pcf.get("contribution_analysis") or {}).get("user_method_grouping") or {}
    dg = ug.get("dimension_grouping") or {}
    grouping = dg.get("grouping") or {}
    dim = (grouping.get("dimensions") or {}).get(dim_id) or {}
    subtotals = {(c["id"]): (c.get("subtotal") if c.get("subtotal") is not None else 0.0)
                 for c in (dim.get("categories") or [])}
    return subtotals, {"dimension_grouping": dg, "known_total": grouping.get("known_total"),
                       "reconciled": dg.get("reconciled"), "dim_reconciled": dim.get("reconciled"),
                       "completeness": dim.get("completeness"), "unattributed": dim.get("unattributed"),
                       "grouping_mode": ug.get("grouping_mode")}


def _mpkg_version(snapshot: dict) -> str | None:
    return ((snapshot.get("provider_receipt") or {}).get("calculation_basis") or {}
            ).get("model_derivation", {}).get("model_processing_rules", {}).get("version")


def _ucm_ref(snapshot: dict):
    return ((snapshot.get("provider_receipt") or {}).get("user_calculation_method") or {}
            ).get("model_processing_rules_ref")


def _ucm_identity(snapshot: dict) -> dict:
    return (snapshot.get("provider_receipt") or {}).get("user_calculation_method") or {}


def _emis_ids(snapshot: dict) -> list[str]:
    return sorted({e["exchange_id"] for e in (snapshot.get("scaled_elementary_exchanges") or [])})


def full(base: str, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    run_tag = uuid.uuid4().hex[:8]
    # The baseline reference output stays the seed's integral 1000 kg. It is deliberately NOT a
    # per-run value: the final-output amount compiles into a set_exchange_amount graph operation, so
    # editing it to a fractional per-run number moves the revision's structural graph hash off the
    # seed graph (measured live: 1000.0 -> a263f2b0..., 1000.<frac> -> c75f7379...), and the frozen
    # cbam_trial boundary pins the seed graph - a moved graph makes CBAM_TRIAL_BOUNDARY_MISMATCH
    # refuse the whole CBAM surface. Per-run uniqueness that dodges the rebuild SOLVED_SNAPSHOT_-
    # CACHE_CONFLICT instead comes from the run_tag carried in each `source` label: source/demand
    # merge into application_context (content), never the graph, so content_sha256 - and therefore
    # solve_hash - is fresh each run while graph_sha256 stays pinned-compatible. discover() and the
    # background path already use this same label-scoped uniqueness.
    checks: list[dict] = []
    artifacts: dict[str, dict] = {}

    def check(name: str, ok: bool, detail: dict | None = None) -> None:
        checks.append({"name": name, "result": "pass" if ok else "fail", "detail": detail or {}})

    def not_run(name: str, reason: str) -> None:
        checks.append({"name": name, "result": "not_run", "detail": {"reason": reason}})

    def cap_limit(name: str, reason: str) -> None:
        # A documented interface capability limitation: the interface enforces a contract that makes
        # this reading impossible without a separate accounting/business decision. It is neither an
        # untested gap (not_run) nor a runtime failure (fail); it is a real, explained surface limit.
        checks.append({"name": name, "result": "capability_limitation", "detail": {"reason": reason}})

    def fail_all(names: list[str], reason: str) -> None:
        # A required-and-proven surface that errors at runtime is a FAILURE, never silently a gap.
        for name in names:
            if not any(item["name"] == name for item in checks):
                checks.append({"name": name, "result": "fail", "detail": {"reason": reason}})
        checks.append({"name": names[0] + "_runtime", "result": "fail", "detail": {"reason": reason}})

    app = _find_steel_application(base)
    app_id = app["id"]
    seed_rev = _base_revision_id(base, app_id)

    # 1. Fresh 1000 kg reference-output revision on the rebuilt engine.
    r1 = _save_revision(base, app_id, seed_rev, 1000.0,
                        f"S4b full A/B/replay baseline {run_tag} (named scenario, not plant data)")
    rev1, demand1 = r1["revision_id"], r1["demand"]
    artifacts["revision_r1"] = r1

    # 2. Baseline solve (no method) -> read the REAL climate receipt contribution paths.
    snap0 = _solve_method(base, app_id, rev1, demand1, "lca", "pcf", None, climate_default=True)
    indicator_key, terms = _climate_terms(snap0)
    total0 = sum(t["value"] for t in terms)
    artifacts["baseline_snapshot_r1"] = snap0
    check("engine_emits_nonempty_climate_path_receipt", len(terms) >= 2 and total0 > 0,
          {"indicator_key": indicator_key, "n_terms": len(terms), "total": total0,
           "all_attribution_bases": sorted({t["attribution_basis"] for t in terms})})

    default_method = _request(base, "GET",
        f"{API}/solved-system-snapshots/{snap0['id']}/product-carbon-footprint/default-method")
    pcf_ref = default_method.get("reference")
    artifacts["default_method"] = default_method

    # 3. Method A: every real contribution path counted into scope_1.
    rules_a = [_rule(t["exchange_id"], boundary_status="selected", scope="scope_1") for t in terms]
    m_a = _create_validate_method(base, app_id, rev1, f"S4b PCF A count-all {run_tag}", "pcf", rules_a)
    snap_a = _solve_method(base, app_id, rev1, demand1, "lca", "pcf", m_a, climate_default=True)
    pcf_a = _pcf(base, snap_a["id"], pcf_ref)
    ga = ((pcf_a.get("contribution_analysis") or {}).get("user_method_grouping") or {})
    arts = ga.get("grouping") or {}
    counted_a = sum((v.get("value") or 0.0) for v in (arts.get("scopes") or {}).values() if v.get("value"))
    artifacts["method_a"] = m_a
    artifacts["snapshot_a"] = snap_a
    artifacts["pcf_a"] = pcf_a
    check("pcf_grouping_mode_is_path_weighted", ga.get("grouping_mode") == "path_weighted",
          {"grouping_mode": ga.get("grouping_mode"), "reason": arts.get("reason"),
           "execution_status": ga.get("execution_status")})
    check("pcf_grouping_a_reconciled_and_fully_counted",
          arts.get("reconciled") is True
          and arts.get("excluded", {}).get("value") == 0.0
          and not arts.get("coverage_gaps")
          and not arts.get("unattributed", {}).get("exchange_ids")
          and _isclose(counted_a, pcf_a["total_footprint"]["value"]),
          {"reconciled": arts.get("reconciled"), "counted_a": counted_a,
           "total_footprint": pcf_a["total_footprint"]["value"],
           "coverage_gaps": arts.get("coverage_gaps"),
           "unattributed": arts.get("unattributed", {}).get("exchange_ids")})

    # 4. Method B: exclude exactly one real non-zero path; A - B must equal that path.
    excl = terms[0]
    rules_b = [
        _rule(t["exchange_id"],
              boundary_status="excluded" if t["exchange_id"] == excl["exchange_id"] else "selected",
              scope="scope_1") for t in terms
    ]
    m_b = _create_validate_method(base, app_id, rev1, f"S4b PCF B minus-one-path {run_tag}", "pcf", rules_b)
    snap_b = _solve_method(base, app_id, rev1, demand1, "lca", "pcf", m_b, climate_default=True)
    pcf_b = _pcf(base, snap_b["id"], pcf_ref)
    gb = ((pcf_b.get("contribution_analysis") or {}).get("user_method_grouping") or {})
    artn = gb.get("grouping") or {}
    counted_b = sum((v.get("value") or 0.0) for v in (artn.get("scopes") or {}).values() if v.get("value"))
    excluded_paths = [p for p in (artn.get("paths") or []) if p.get("decision") == "excluded"]
    artifacts["method_b"] = m_b
    artifacts["snapshot_b"] = snap_b
    artifacts["pcf_b"] = pcf_b
    check("pcf_ab_exclusion_removes_exactly_one_path",
          snap_b["id"] != snap_a["id"]
          and _isclose(counted_a - counted_b, excl["value"])
          and _isclose(artn.get("excluded", {}).get("value") or 0.0, excl["value"])
          and artn.get("reconciled") is True
          and [p["exchange_id"] for p in excluded_paths] == [excl["exchange_id"]],
          {"excluded_exchange_id": excl["exchange_id"], "excluded_value": excl["value"],
           "counted_a": counted_a, "counted_b": counted_b,
           "a_minus_b": counted_a - counted_b,
           "excluded_bucket_value": artn.get("excluded", {}).get("value"),
           "snapshot_a_id": snap_a["id"], "snapshot_b_id": snap_b["id"]})

    # 5. History version replay: same method version resolves to the identical frozen snapshot.
    replay = _solve_method(base, app_id, rev1, demand1, "lca", "pcf", m_a, climate_default=True)
    check("history_replay_cache_hits_same_frozen_snapshot",
          replay["id"] == snap_a["id"] and replay["content_sha256"] == snap_a["content_sha256"],
          {"replay_id": replay["id"], "snapshot_a_id": snap_a["id"]})
    # A newer head does not move the frozen v1 reference: save a content-changing edit (the first
    # selected rule moves to scope_2) so a real second immutable version is created, then re-solve
    # citing v1 — it must still resolve to the identical frozen snapshot, never the new head.
    edit_rules = [dict(r) for r in rules_a]
    edit_rules[0]["scope"] = "scope_2"
    put = _request(base, "PUT", f"{API}/calculation-methods/{m_a['method_id']}/versions/{m_a['version']}",
                   {"rules": edit_rules, "expected_content_sha256": m_a["content_sha256"]})
    new_head = max(v["version"] for v in put["versions"])
    frozen_v1 = _solve_method(base, app_id, rev1, demand1, "lca", "pcf", m_a, climate_default=True)
    check("edit_bumps_head_but_v1_ref_stays_frozen",
          new_head > m_a["version"] and frozen_v1["id"] == snap_a["id"],
          {"new_head": new_head, "v1_version": m_a["version"], "v1_snapshot_id": frozen_v1["id"]})

    # 6. Demand doubling: the save->demand seam and the reference-process activity each scale by
    #    exactly one factor of 2 (no hidden period/double-scaling), the frozen snapshot identity
    #    changes, and the per-functional-unit footprint is intensive — verified live to stay
    #    invariant, so it must NOT double.
    r2 = _save_revision(base, app_id, seed_rev, 2000.0,
                        f"S4b full scaling 2000 kg {run_tag} (named scenario)")
    rev2, demand2 = r2["revision_id"], r2["demand"]
    m_a2 = _create_validate_method(base, app_id, rev2, f"S4b PCF A count-all @2000 {run_tag}", "pcf", rules_a)
    snap_a2 = _solve_method(base, app_id, rev2, demand2, "lca", "pcf", m_a2, climate_default=True)
    pcf_a2 = _pcf(base, snap_a2["id"], pcf_ref)
    ga2 = ((pcf_a2.get("contribution_analysis") or {}).get("user_method_grouping") or {})
    counted_a2 = sum((v.get("value") or 0.0) for v in ((ga2.get("grouping") or {}).get("scopes") or {}).values()
                     if v.get("value"))
    act_a = {a["process_id"]: float(a.get("value") or 0.0) for a in (snap_a.get("activity_vector") or [])}
    act_a2 = {a["process_id"]: float(a.get("value") or 0.0) for a in (snap_a2.get("activity_vector") or [])}
    ref_pid = next((pid for pid, v in act_a.items()
                    if v > 0 and _isclose(v, float(demand1[0]["amount"]))), None)
    ref_a = act_a.get(ref_pid) if ref_pid else None
    ref_a2 = act_a2.get(ref_pid) if ref_pid else None
    demand_ratio = float(demand2[0]["amount"]) / float(demand1[0]["amount"])
    footprint_ratio = pcf_a2["total_footprint"]["value"] / pcf_a["total_footprint"]["value"]
    artifacts["revision_r2"] = r2
    artifacts["snapshot_a2"] = snap_a2
    artifacts["pcf_a2"] = pcf_a2
    check("demand_doubling_scales_activity_once_and_footprint_is_intensive",
          ref_pid is not None
          and _isclose(demand_ratio, 2.0)
          and ref_a2 is not None and _isclose(ref_a2, 2 * ref_a)
          and snap_a2["solve_hash"] != snap_a["solve_hash"]
          and snap_a2["id"] != snap_a["id"]
          and _isclose(footprint_ratio, 1.0)
          and _isclose(counted_a2, counted_a),
          {"reference_process_id": ref_pid, "activity_a": ref_a, "activity_a2": ref_a2,
           "demand_ratio": demand_ratio, "solve_hash_a": snap_a["solve_hash"],
           "solve_hash_a2": snap_a2["solve_hash"],
           "footprint_a": pcf_a["total_footprint"]["value"],
           "footprint_a2": pcf_a2["total_footprint"]["value"],
           "footprint_ratio": footprint_ratio,
           "counted_a": counted_a, "counted_a2": counted_a2})

    # 7. PCF export + report bytes carry the user-method grouping.
    xlsx, xh = _bytes(base, f"{API}/solved-system-snapshots/{snap_a['id']}/product-carbon-footprint/export.xlsx"
                            f"?method_package_ref={pcf_ref}")
    html, hh = _bytes(base, f"{API}/solved-system-snapshots/{snap_a['id']}/product-carbon-footprint/report.html"
                             f"?method_package_ref={pcf_ref}")
    html_text = html.decode("utf-8", "replace")
    check("pcf_export_xlsx_present",
          len(xlsx) > 1000 and bool(xh.get("x-nebula-result-sha256")),
          {"xlsx_bytes": len(xlsx), "etag": xh.get("etag")})
    check("pcf_report_html_present",
          len(html_text) > 1000 and "path_weighted" in html_text,
          {"html_bytes": len(html_text), "etag": hh.get("etag")})
    (out / "pcf-export-a.xlsx").write_bytes(xlsx)
    (out / "pcf-report-a.html").write_text(html_text, encoding="utf-8")

    # 8. S1 same-input dual-scenario comparison: two scenarios, each member keeps its own identity.
    try:
        s1 = _request(base, "POST", f"{API}/applications/{app_id}/scenarios",
                      {"name": f"S4b scenario 1 {run_tag}", "base_revision_id": rev1, "system_revision_id": rev1})
        s2 = _request(base, "POST", f"{API}/applications/{app_id}/scenarios",
                      {"name": f"S4b scenario 2 {run_tag}", "base_revision_id": rev1, "system_revision_id": rev1})
        _request(base, "POST", f"{API}/scenarios/{s1['id']}/freeze")
        _request(base, "POST", f"{API}/scenarios/{s2['id']}/freeze")
        cmp_ = _request(base, "POST", f"{API}/applications/{app_id}/comparisons",
                        {"name": f"S4b dual-scenario {run_tag}", "scenario_ids": [s1["id"], s2["id"]]})
        run = _request(base, "POST", f"{API}/comparisons/{cmp_['id']}/execute",
                       {"baseline_scenario_id": s1["id"], "demand": demand1,
                        "mapped_background_process_pins": []})
        results = run.get("scenario_results") or []
        result_ids = {r.get("scenario_id") for r in results}
        snapshot_ids = {r.get("solved_snapshot_id") for r in results}
        check("s1_same_input_dual_scenario_comparison",
              run.get("status") == "succeeded"
              and len(results) == 2
              and {s1["id"], s2["id"]}.issubset(result_ids)
              and all(r.get("solved_snapshot_id") and r.get("scenario_hash")
                      and r.get("system_revision_id") for r in results),
              {"comparison_id": cmp_["id"], "run_id": run.get("id"), "status": run.get("status"),
               "distinct_snapshot_ids": len(snapshot_ids),
               "members": [{"scenario_id": r.get("scenario_id"),
                            "scenario_hash": r.get("scenario_hash"),
                            "system_revision_id": r.get("system_revision_id"),
                            "solved_snapshot_id": r.get("solved_snapshot_id"),
                            "solve_hash": r.get("solve_hash")} for r in results]})
    except (RuntimeError, StopIteration) as exc:
        not_run("s1_same_input_dual_scenario_comparison", f"comparison execute unavailable: {exc}")

    # 9. CBAM exclusion narrowing AND numeric read-back, proven through the formal interfaces. The
    #    shipped steel reviewed basis is automatic (1.0.11): it counts a whole pre-limited emission set
    #    and declares no per-exchange decision, so a user exclusion on it must refuse closed rather than
    #    silently recount. The 1.0.12 explicit_only variant re-expresses that SAME reviewed counted set as
    #    per-exchange include decisions; binding it by exact reference is what lets One honour a user
    #    exclusion. Numerically the bound count-all is a FAITHFUL re-expression of the official trial
    #    (identical counted set, per-exchange amounts, counted total and SEE), reproducible on read-back
    #    and exportable. An arbitrary user exclusion, however, cannot be read back NUMERICALLY through
    #    the shipped fixed-universe trial package (recorded below as an interface capability limitation).
    cbam_structural_names = [
        "cbam_variant_selected_only_freezes_identity",
        "cbam_bound_package_selects_explicit_only_while_official_stays_automatic",
        "cbam_bound_count_all_reexpresses_official_universe",
        "cbam_exclusion_variant_actually_narrows",
    ]
    cbam_numeric_names = [
        "cbam_trial_official_analyzes_nonzero",
        "cbam_trial_bound_count_all_reexpresses_official_numerics",
        "cbam_trial_bound_readback_reproducible",
        "cbam_trial_bound_export_report_html",
    ]
    trial_ref = "cbam.eu.iron-steel.bf-bof-direct-trial@1.2.3"
    decisions_ref = "cbam.eu.iron-steel.bf-bof-direct-trial-boundary-decisions@1.2.6"
    ref_1012 = {"package_id": "steel-bf-bof.model-processing", "version": "1.0.12",
                "content_sha256": "e95a68b74a68bb60730d781fab7342789b3d9450a05e6f9a7937743a2a938415"}

    # Precondition (a fixture dependency of this scenario, not a runtime failure): the shipped frozen
    # cbam_trial boundary to analyze against and a reporting period. If absent the CBAM route is
    # untestable on this stack -> not_run for the whole CBAM surface (structural + numeric + the
    # excluded-variant limit), which is an untested gap rather than a runtime error.
    shipped = [b for b in _request(base, "GET", f"{API}/applications/{app_id}/boundaries")
               if b.get("boundary_type") == "cbam_trial" and b.get("status") == "frozen"]
    _periods = _request(base, "GET", f"{API}/applications/{app_id}/periods")
    period_items = _periods if isinstance(_periods, list) else _periods.get("items", [])
    if not shipped or not period_items:
        for name in cbam_structural_names + cbam_numeric_names:
            not_run(name, "shipped frozen cbam_trial boundary or reporting period absent on this stack")
        cap_limit("cbam_trial_excluded_variant_numeric_readback",
                  "not reached: shipped cbam_trial boundary or reporting period absent")
    else:
        bid3 = shipped[0]["id"]
        pid = period_items[0]["id"]
        try:
            # Register + bind the 1.2.6 decisions package and freeze a boundary twin citing it, so the
            # bound variant's trial read-back passes the package-identity gates the analyze endpoint
            # enforces (requested == app-bound == derivation == boundary == reviewed-selection).
            pkg_path = (Path(__file__).resolve().parent.parent
                        / "src/nebula_one/resources/official_methods"
                        / "cbam-steel-direct-boundary-decisions-1.2.6.json")
            artifacts["cbam_method_package_registration"] = {"result": _register_method_package(
                base, json.loads(pkg_path.read_text(encoding="utf-8")))}
            artifacts["cbam_method_package_binding"] = {"result": _request(
                base, "POST", f"{API}/applications/{app_id}/method-package-bindings",
                {"reference": decisions_ref})}
            twin = {k: shipped[0].get(k) for k in ("boundary_type", "included_entity_ids",
                    "included_process_ids", "included_flow_rules", "excluded_items",
                    "consolidation_policy", "geographic_scope")}
            twin.update(name=f"S4b cbam 1.2.6 twin {run_tag}", method_package_ref=decisions_ref)
            bid6 = _request(base, "POST", f"{API}/applications/{app_id}/boundaries", twin)["id"]
            _request(base, "POST", f"{API}/boundaries/{bid6}/freeze", {})

            boundary = _request(base, "POST", f"{API}/applications/{app_id}/boundaries",
                                {"name": f"S4b cbam boundary {run_tag}", "boundary_type": "cbam_production"})
            bid = boundary["id"]
            rules_count_all = [_rule(t["exchange_id"], boundary_status="selected", cbam_relevant=True)
                               for t in terms]
            m_off = _create_validate_method(base, app_id, rev1, f"S4b CBAM official unbound {run_tag}",
                                            "cbam", rules_count_all, boundary_ref=bid)
            m_bound = _create_validate_method(base, app_id, rev1, f"S4b CBAM bound count-all {run_tag}",
                                              "cbam", rules_count_all, boundary_ref=bid, processing_ref=ref_1012)
            snap_off = _solve_method(base, app_id, rev1, demand1, "cbam", "cbam", m_off, climate_default=False)
            snap_bound = _solve_method(base, app_id, rev1, demand1, "cbam", "cbam", m_bound, climate_default=False)
            artifacts["cbam_official"] = {"method": m_off, "snapshot_id": snap_off["id"]}
            artifacts["cbam_bound"] = {"method": m_bound, "snapshot_id": snap_bound["id"]}

            # The bound variant still freezes its exact identity on the snapshot.
            ucm_bound = _ucm_identity(snap_bound)
            check("cbam_variant_selected_only_freezes_identity",
                  ucm_bound.get("method_id") == m_bound["method_id"]
                  and ucm_bound.get("content_sha256") == m_bound["content_sha256"],
                  {"snapshot_id": snap_bound["id"], "frozen_method_id": ucm_bound.get("method_id")})

            # Binding 1.0.12 selects the explicit_only basis; leaving it unbound keeps the official 1.0.11,
            # and the exact ref is carried across the seam on the bound snapshot only.
            check("cbam_bound_package_selects_explicit_only_while_official_stays_automatic",
                  _mpkg_version(snap_bound) == "1.0.12" and _mpkg_version(snap_off) == "1.0.11"
                  and _ucm_ref(snap_bound) == ref_1012 and _ucm_ref(snap_off) is None,
                  {"bound_mpkg_version": _mpkg_version(snap_bound), "official_mpkg_version": _mpkg_version(snap_off),
                   "bound_ref": _ucm_ref(snap_bound), "official_ref": _ucm_ref(snap_off)})

            # The bound count-all is a faithful re-expression of the reviewed universe: the same six
            # emissions are counted, yet it is a distinct derivation identity (never a cache collision).
            e_bound, e_off = _emis_ids(snap_bound), _emis_ids(snap_off)
            check("cbam_bound_count_all_reexpresses_official_universe",
                  e_bound == e_off and snap_bound["solve_hash"] != snap_off["solve_hash"],
                  {"n_bound": len(e_bound), "n_official": len(e_off), "identical_set": e_bound == e_off,
                   "solve_hash_bound": snap_bound["solve_hash"], "solve_hash_official": snap_off["solve_hash"]})

            # C: bound minus-one. Narrowing is proven ONLY when the excluded emission actually leaves the
            # counted set - a solve that silently recounted would be the regression this check catches.
            excl = terms[0]
            rules_minus = [
                _rule(t["exchange_id"],
                      boundary_status="excluded" if t["exchange_id"] == excl["exchange_id"] else "selected",
                      cbam_relevant=True) for t in terms
            ]
            m_minus = _create_validate_method(base, app_id, rev1, f"S4b CBAM bound minus-one {run_tag}",
                                              "cbam", rules_minus, boundary_ref=bid, processing_ref=ref_1012)
            snap_minus = _solve_method(base, app_id, rev1, demand1, "cbam", "cbam", m_minus, climate_default=False)
            artifacts["cbam_minus_one"] = {"method": m_minus, "snapshot_id": snap_minus["id"]}
            e_minus = set(_emis_ids(snap_minus))
            dropped = sorted(set(e_bound) - e_minus)
            narrowed = (dropped == [excl["exchange_id"]] and excl["exchange_id"] not in e_minus
                        and _mpkg_version(snap_minus) == "1.0.12")
            check("cbam_exclusion_variant_actually_narrows", narrowed,
                  {"excluded_exchange_id": excl["exchange_id"], "dropped": dropped,
                   "still_present": excl["exchange_id"] in e_minus,
                   "n_bound": len(e_bound), "n_minus": len(e_minus),
                   "minus_mpkg_version": _mpkg_version(snap_minus), "snapshot_id": snap_minus["id"]})

            # --- numeric read-back through the formal cbam-trial analyze/GET/export interfaces ---
            def cbam_analyze(snap_id: str, pkg: str, boundary_id: str) -> dict:
                return _request(base, "POST",
                                f"{API}/solved-system-snapshots/{snap_id}/cbam-trial",
                                {"method_package_ref": pkg, "reporting_period_id": pid,
                                 "boundary_definition_id": boundary_id})

            def cbam_amounts(cb: dict) -> dict[str, float]:
                d = (cb.get("attributed_emissions") or {}).get("direct") or {}
                return {x["exchange_id"]: float(x["amount"]) for x in (d.get("exchanges") or [])}

            def cbam_total(cb: dict):
                return ((cb.get("coverage") or {}).get("totals") or {}).get("counted_kg_co2e")

            def cbam_see(cb: dict) -> dict:
                s = cb.get("specific_embedded_emissions") or {}
                return {"value": s.get("value"), "partial_value": s.get("partial_value"),
                        "unit": s.get("unit")}

            # A: official unbound trial, analyzed under 1.2.3 on the shipped boundary -> real nonzero.
            cb_off = cbam_analyze(snap_off["id"], trial_ref, bid3)
            amt_off, see_off, tot_off = cbam_amounts(cb_off), cbam_see(cb_off), cbam_total(cb_off)
            check("cbam_trial_official_analyzes_nonzero",
                  tot_off is not None and float(tot_off) > 0 and len(amt_off) == len(e_off),
                  {"counted_total": tot_off, "n_exchanges": len(amt_off), "see": see_off,
                   "snapshot_id": snap_off["id"]})

            # B: bound count-all cites 1.0.12 -> read back under 1.2.6 on the twin. It must re-express
            # the SAME reviewed universe NUMERICALLY (per-exchange amounts, counted total, SEE): a
            # faithful variant, not a recompute. The SEE is partial (direct-only trial omits indirect).
            cb_bound = cbam_analyze(snap_bound["id"], decisions_ref, bid6)
            amt_b, see_b, tot_b = cbam_amounts(cb_bound), cbam_see(cb_bound), cbam_total(cb_bound)
            per_exchange_equal = (set(amt_off) == set(amt_b)
                                  and all(_isclose(amt_off[k], amt_b[k]) for k in amt_off))
            check("cbam_trial_bound_count_all_reexpresses_official_numerics",
                  per_exchange_equal and tot_off is not None and tot_b is not None
                  and _isclose(float(tot_off), float(tot_b)) and see_off == see_b,
                  {"total_official": tot_off, "total_bound": tot_b,
                   "see_official": see_off, "see_bound": see_b,
                   "counted_official": sorted(amt_off), "counted_bound": sorted(amt_b),
                   "per_exchange_equal": per_exchange_equal})

            # Reproducibility: a second read-back of B resolves the identical frozen answer.
            cb_bound2 = cbam_analyze(snap_bound["id"], decisions_ref, bid6)
            check("cbam_trial_bound_readback_reproducible",
                  bool(cb_bound.get("content_sha256"))
                  and cb_bound["content_sha256"] == cb_bound2["content_sha256"],
                  {"content_sha256": cb_bound.get("content_sha256")})

            # Export: the bound variant produces a real report.html through the shipped artifact path.
            req_html = urllib.request.Request(
                f"{base}{API}/solved-system-snapshots/{snap_bound['id']}/cbam-trial/report.html",
                data=json.dumps({"method_package_ref": decisions_ref, "reporting_period_id": pid,
                                 "boundary_definition_id": bid6}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Accept": "text/html"}, method="POST")
            with urllib.request.urlopen(req_html, timeout=180) as resp_html:
                html_status, html_bytes = resp_html.status, resp_html.read()
            (out / "cbam-bound-report.html").write_bytes(html_bytes)
            check("cbam_trial_bound_export_report_html",
                  html_status == 200 and len(html_bytes) > 1000,
                  {"http_status": html_status, "bytes": len(html_bytes), "artifact": "cbam-bound-report.html"})

            cb_minus = cbam_analyze(snap_minus["id"], decisions_ref, bid6)
            amt_minus, tot_minus = cbam_amounts(cb_minus), cbam_total(cb_minus)
            user_ledger = cb_minus.get("user_declared_counted_ledger") or {}
            excluded_ledger = [r for r in user_ledger.get("entries", [])
                               if r.get("disposition") == "excluded_with_basis"]
            check("cbam_trial_excluded_variant_numeric_readback",
                  tot_b is not None and tot_minus is not None
                  and _isclose(float(tot_b) - float(tot_minus), amt_b[excl["exchange_id"]])
                  and set(amt_minus) == set(amt_b) - {excl["exchange_id"]}
                  and all(_isclose(amt_minus[k], amt_b[k]) for k in amt_minus)
                  and [r["exchange_id"] for r in excluded_ledger] == [excl["exchange_id"]]
                  and user_ledger.get("user_method", {}).get("content_sha256") == m_minus["content_sha256"]
                  and bool(user_ledger.get("content_sha256")),
                  {"counted_all": tot_b, "counted_minus": tot_minus,
                   "excluded_baseline_amount": amt_b[excl["exchange_id"]],
                   "ledger_sha256": user_ledger.get("content_sha256"), "excluded": excluded_ledger})
            cb_minus2 = cbam_analyze(snap_minus["id"], decisions_ref, bid6)
            check("cbam_excluded_variant_history_readback",
                  cb_minus2["content_sha256"] == cb_minus["content_sha256"],
                  {"content_sha256": cb_minus["content_sha256"]})
        except (RuntimeError, StopIteration) as exc:
            # The CBAM route is a REQUIRED-and-proven surface: a runtime error here is a FAILURE that
            # must surface (non-zero exit), never a silent not_run.
            fail_all(cbam_structural_names + cbam_numeric_names +
                     ["cbam_trial_excluded_variant_numeric_readback"],
                     f"cbam numeric/structural route runtime failure: {exc}")

    # 9b. Organization surface with its two endpoint families reported SEPARATELY (never one blanket
    #     verdict, and never an unconditional not_run that masks a real success):
    #   (a) user-defined CUSTOM-CATEGORY reassignment — an organization-purposed user method that
    #       declares its own reporting dimension (a non-Scope grouping) with two leaf categories,
    #       solved over the real non-zero foreground and read back through the analysis interface's
    #       dimension_grouping. Reassigning one path from leaf A to leaf B must leave the known total
    #       unchanged and equal to the product total while BOTH leaf subtotals move by exactly that
    #       path's value; both leaves stay non-zero before and after.
    #   (b) the organization-ghg-inventory AGGREGATE endpoint's Scope grouping — the persisted count-all
    #       PCF snapshot is bound to a reporting period + organizational boundary and aggregated; its
    #       rolled scope_1 total must equal the product total, sourced from user_method_grouping, with
    #       scope_2/scope_3 empty (the foreground is fully onsite).
    org_category_names = ["org_custom_category_reassignment_live",
                          "org_custom_category_reconciles_to_product_total"]
    org_ghg_names = ["org_ghg_inventory_scope_grouping_live"]
    # A leaf must set is_leaf explicitly: the method's dimension tree round-trips through JSON with
    # is_leaf=None present, and normalize_dimensions only infers leaf-ness when the key is ABSENT, so
    # an omitted flag collapses to bool(None)=False and the category is misread as a parent.
    org_dims = [{
        "id": "plant_split", "name": "Plant split", "source": "user",
        "mutually_exclusive": True, "requires_full_coverage": True,
        "categories": [{"id": "line_a", "name": "Line A", "is_leaf": True},
                       {"id": "line_b", "name": "Line B", "is_leaf": True}],
    }]
    try:
        if len(terms) < 3:
            for name in org_category_names:
                not_run(name, f"only {len(terms)} foreground contribution paths; a two-leaf custom "
                              "dimension needs >= 3 so both leaves stay non-zero after one path moves")
        else:
            # v1 puts paths 0 and 1 into line_a, the rest into line_b; v2 moves path 0 to line_b.
            moved = terms[0]["value"]
            rules_c1 = [_rule(t["exchange_id"], boundary_status="selected",
                              categories={"plant_split": "line_a" if i < 2 else "line_b"})
                        for i, t in enumerate(terms)]
            m_c1 = _create_validate_method(base, app_id, rev1, f"S4b org custom-cat v1 {run_tag}",
                                           "organization", rules_c1, reporting_dimensions=org_dims)
            snap_c1 = _solve_method(base, app_id, rev1, demand1, "lca", "organization", m_c1,
                                    climate_default=True)
            pcf_c1 = _pcf(base, snap_c1["id"], pcf_ref)
            s1, meta1 = _dim_leaf_subtotals(pcf_c1, "plant_split")
            rules_c2 = [_rule(t["exchange_id"], boundary_status="selected",
                              categories={"plant_split": "line_b" if i == 0 else
                                          ("line_a" if i == 1 else "line_b")})
                        for i, t in enumerate(terms)]
            m_c2 = _create_validate_method(base, app_id, rev1, f"S4b org custom-cat v2 {run_tag}",
                                           "organization", rules_c2, reporting_dimensions=org_dims)
            snap_c2 = _solve_method(base, app_id, rev1, demand1, "lca", "organization", m_c2,
                                    climate_default=True)
            pcf_c2 = _pcf(base, snap_c2["id"], pcf_ref)
            s2, meta2 = _dim_leaf_subtotals(pcf_c2, "plant_split")
            a1, b1 = s1.get("line_a", 0.0), s1.get("line_b", 0.0)
            a2, b2 = s2.get("line_a", 0.0), s2.get("line_b", 0.0)
            artifacts["org_custom_category"] = {
                "dimension": "plant_split", "moved_exchange_id": terms[0]["exchange_id"],
                "moved_value": moved, "v1_subtotals": s1, "v2_subtotals": s2,
                "v1_known_total": meta1["known_total"], "v2_known_total": meta2["known_total"],
                "v1_total_footprint": (pcf_c1.get("total_footprint") or {}).get("value"),
                "method_v1": m_c1, "method_v2": m_c2,
                "snapshot_v1_id": snap_c1["id"], "snapshot_v2_id": snap_c2["id"],
                "grouping_mode": meta1["grouping_mode"], "completeness": meta1["completeness"],
                "unattributed_v1": meta1["unattributed"], "unattributed_v2": meta2["unattributed"]}
            check("org_custom_category_reassignment_live",
                  meta1["grouping_mode"] == "path_weighted"
                  and min(a1, b1, a2, b2) > 0
                  and _isclose(a1 - a2, moved) and _isclose(b2 - b1, moved)
                  and meta1["dim_reconciled"] is True and meta2["dim_reconciled"] is True
                  and meta1["reconciled"] is True and meta2["reconciled"] is True,
                  {"moved_value": moved, "line_a_before": a1, "line_a_after": a2,
                   "line_b_before": b1, "line_b_after": b2,
                   "a_drop": a1 - a2, "b_rise": b2 - b1,
                   "grouping_mode": meta1["grouping_mode"], "completeness": meta1["completeness"],
                   "snapshot_v1_id": snap_c1["id"], "snapshot_v2_id": snap_c2["id"]})
            ft1 = (pcf_c1.get("total_footprint") or {}).get("value")
            check("org_custom_category_reconciles_to_product_total",
                  meta1["known_total"] is not None and meta2["known_total"] is not None
                  and _isclose(meta1["known_total"], meta2["known_total"])
                  and _isclose(meta1["known_total"], total0)
                  and _isclose(a1 + b1, total0) and _isclose(a2 + b2, total0)
                  and (meta1["unattributed"] or {}).get("subtotal") in (0.0, None)
                  and _isclose(ft1, total0),
                  {"known_total_v1": meta1["known_total"], "known_total_v2": meta2["known_total"],
                   "foreground_no_method_total": total0, "product_total_footprint": ft1,
                   "line_a_plus_b_v1": a1 + b1, "line_a_plus_b_v2": a2 + b2,
                   "unattributed_v1": meta1["unattributed"]})
    except (RuntimeError, StopIteration) as exc:
        fail_all(org_category_names, f"organization custom-category route runtime failure: {exc}")

    try:
        org_pkg = json.loads((Path(__file__).parent / "org_ghg_inventory_package.json").read_text("utf-8"))
        org_ref = f"{org_pkg['package_id']}@{org_pkg['version']}"
        _register_and_bind(base, app_id, org_pkg, org_ref)
        _register_and_bind(base, app_id, _load_registered_package(base, pcf_ref), pcf_ref)
        org_model_id = _request(base, "GET", f"{API}/system-revisions/{rev1}")["system_model_id"]
        org_period = _first_id(base, app_id, "periods")
        org_boundary = _first_id(base, app_id, "boundaries")
        org_bind = _request(base, "POST", f"{API}/applications/{app_id}/system-bindings", {
            "binding_id": f"s4b-ghg-{run_tag}", "role": f"steel.own.production.{run_tag}",
            "system_model_id": org_model_id, "system_revision_id": rev1,
            "solved_snapshot_id": snap_a["id"], "study_frame_id": f"S4b org ghg {run_tag}",
            "reporting_period_id": org_period, "organizational_boundary_id": org_boundary,
            "demand": demand1, "capabilities": ["pcf.product.v1"], "dependencies": [], "status": "active"})
        org_inv = _request(base, "POST", f"{API}/applications/{app_id}/organization-ghg-inventory", {
            "method_package_ref": org_ref, "pcf_method_package_ref": pcf_ref,
            "binding_ids": [org_bind["binding_id"]]})
        scope_vals = {s["scope"]: (s.get("total") or {}).get("value")
                      for s in (org_inv.get("scopes") or [])}
        sources = ((org_inv.get("attribution") or {}).get("sources") or [])
        src = sources[0] if sources else {}
        counted_from = (src.get("counted_scopes") or {}).get("scope_1")
        src_leaf = (src.get("counted_scopes") or {})
        # the counted_from label is carried on the leaf source row inside scopes -> categories ->
        # sources; pull it for the matching binding so the evidence names the real attribution lever.
        cf_label = None
        for scope in (org_inv.get("scopes") or []):
            for cat in (scope.get("categories") or []):
                for leaf in (cat.get("sources") or []):
                    if leaf.get("binding_id") == org_bind["binding_id"]:
                        cf_label = leaf.get("counted_from")
        artifacts["org_ghg_inventory"] = {
            "org_ref": org_ref, "binding_id": org_bind["binding_id"],
            "period_id": org_period, "boundary_id": org_boundary,
            "source_snapshot_id": snap_a["id"], "total": (org_inv.get("total") or {}).get("value"),
            "scope_vals": scope_vals, "counted_scopes": src_leaf,
            "counted_from_label": cf_label,
            "method_identity": src.get("method_identity")}
        check("org_ghg_inventory_scope_grouping_live",
              _isclose((org_inv.get("total") or {}).get("value") or 0.0, total0)
              and _isclose(scope_vals.get("scope_1") or 0.0, total0)
              and _isclose(counted_from or 0.0, total0)
              and cf_label == "user_method_grouping"
              and (scope_vals.get("scope_2") in (None, 0.0))
              and (scope_vals.get("scope_3") in (None, 0.0)),
              {"rolled_total": (org_inv.get("total") or {}).get("value"),
               "scope_1": scope_vals.get("scope_1"), "scope_2": scope_vals.get("scope_2"),
               "scope_3": scope_vals.get("scope_3"), "source_counted_scope_1": counted_from,
               "foreground_no_method_total": total0,
               "counted_from": cf_label})
    except (RuntimeError, StopIteration) as exc:
        fail_all(org_ghg_names, f"organization ghg-inventory route runtime failure: {exc}")


    # 10. Real background (Scope 2/3) association through the live HTTP interface, using a
    #     user-owned, locally-imported closed-leaf supply project pinned onto an exact-binding open
    #     inventory input. Proven numerically: a real, non-zero upstream contribution that reconciles
    #     against the foreground total (the foreground part is preserved exactly), with auditable
    #     provider provenance. Closed multi-node expansion is exercised independently by
    #     live_background_network_acceptance.py; a rejected open project is not evidence that
    #     all multi-node backgrounds are unsupported. Scope grouping uses the consumer input.
    bg_numeric_names = ["background_real_contribution_live", "background_readback_reproducible"]
    bg_limit_names = ["background_closed_network_live", "background_scope23_grouping_live"]
    not_run("background_closed_network_live", "run live_background_network_acceptance.py and retain its exact snapshot evidence")
    try:
        ws_bg = _request(base, "GET", f"{API}/applications/{app_id}/workspace/{rev1}")
        bg_ports = [p for p in (ws_bg.get("background_ports") or []) if p.get("exact_binding_supported")]
        if not bg_ports:
            for name in bg_numeric_names:
                not_run(name, "no exact-binding (tiangong_open_data) open inventory input on this stack")
            not_run("background_scope23_grouping_live", "no exact-binding input, so no background to group")
        else:
            port = bg_ports[0]["exchange_id"]
            projects = _request(base, "GET",
                                f"{API}/applications/{app_id}/workspace/{rev1}/background/user-projects")
            pitems = projects if isinstance(projects, list) else projects.get("items", [])
            leaf = None
            nonleaf_name = None
            for pr in pitems:
                vs = _request(base, "GET",
                              f"{API}/applications/{app_id}/workspace/{rev1}/background/user-projects/{pr['project_id']}/versions")
                vitems = (vs.get("items") or []) if isinstance(vs, dict) else (vs or [])
                if not vitems:
                    continue
                ver = vitems[0]["version"]
                try:
                    rr = _request(base, "POST",
                                  f"{API}/applications/{app_id}/workspace/{rev1}/background/user-project-resolve",
                                  {"consumer_exchange_id": port, "project_id": pr["project_id"], "version": ver})
                    if leaf is None and rr.get("pin"):
                        leaf = (pr["project_id"], ver, rr["pin"])
                except (RuntimeError, StopIteration) as exc:
                    if nonleaf_name is None and "PROJECT_BACKGROUND_NOT_CLOSED_LEAF" in str(exc):
                        nonleaf_name = pr.get("name") or pr["project_id"]
            if leaf is None:
                for name in bg_numeric_names + ["background_scope23_grouping_live"]:
                    not_run(name, "no user-imported closed-leaf provider project resolves on the exact-binding input")
            else:
                project_id, pver, pin = leaf
                vals = {f["key"]: f["value"] for f in (ws_bg.get("fields") or [])}
                saved_bg = _request(base, "POST", f"{API}/applications/{app_id}/workspace/inputs", {
                    "revision_id": rev1, "expected_content_sha256": ws_bg["content_sha256"], "amounts": [7],
                    "demand_mode": "reference_output", "values": vals,
                    "source": f"S4b background pin {project_id} {run_tag}", "project_background_pins": [pin]})
                bg_rev, bg_demand = saved_bg["revision_id"], saved_bg["demand"]

                def bg_solve():
                    return _request(base, "POST",
                                    f"{API}/applications/{app_id}/system-revisions/{bg_rev}/solve",
                                    {"demand": bg_demand, "idempotency_key": f"s4b-bg-{uuid.uuid4().hex[:10]}",
                                     "calculation_purpose": "lca", "analysis_task": "pcf",
                                     "climate_default": True, "project_background_pins": [pin]})

                snap_bg = bg_solve()
                _, terms_bg = _climate_terms(snap_bg)
                bg_terms = [t for t in terms_bg if t["exchange_id"].startswith("project-background")]
                fg_bg = [t for t in terms_bg if not t["exchange_id"].startswith("project-background")]
                bg_sum = sum(t["value"] for t in bg_terms)
                fg_sum = sum(t["value"] for t in fg_bg)
                prov_bg = (snap_bg.get("provider_receipt") or {}).get("project_background_process_receipts") or []
                artifacts["background_solve"] = {
                    "project_id": project_id, "version": pver, "consumer_port": port,
                    "expanded_exchange_ids": [t["exchange_id"] for t in bg_terms],
                    "background_sum": bg_sum, "provenance": prov_bg, "snapshot_id": snap_bg["id"]}
                check("background_real_contribution_live",
                      bg_sum > 0 and len(bg_terms) >= 1 and len(prov_bg) >= 1 and _isclose(fg_sum, total0),
                      {"background_sum": bg_sum, "n_background_terms": len(bg_terms),
                       "foreground_sum": fg_sum, "foreground_no_pin_total": total0,
                       "foreground_preserved": _isclose(fg_sum, total0), "provenance_entries": len(prov_bg),
                       "claim_limit": (prov_bg[0].get("claim_limit") if prov_bg else None),
                       "consumer_unit": (prov_bg[0].get("consumer_unit") if prov_bg else None),
                       "snapshot_id": snap_bg["id"]})
                snap_bg2 = bg_solve()
                check("background_readback_reproducible",
                      snap_bg2["content_sha256"] == snap_bg["content_sha256"],
                      {"content_sha256": snap_bg["content_sha256"]})
                # Scope 2/3 grouping reaches the engine-expanded background through the exact
                # consumer input it was pinned onto: LCA publishes the characterized background as a
                # background_consumer_path row keyed by consumer_exchange_id, and One groups it by
                # that selectable input (the expanded provider node stays out of the rule boundary).
                consumer_scopes: dict[str, str] = {}
                rules_bg = []
                for t in terms_bg:
                    if t["attribution_basis"] == "background_consumer_path" and t.get("consumer_exchange_id"):
                        # A purchased-energy leaf routes to Scope 2; any other background input to
                        # Scope 3 upstream supply. This grid-electricity leaf is purchased energy.
                        consumer_scopes.setdefault(t["consumer_exchange_id"], "scope_2")
                    else:
                        rules_bg.append(_rule(t["exchange_id"], boundary_status="selected", scope="scope_1"))
                for cid in sorted(consumer_scopes):
                    rules_bg.append(_rule(cid, boundary_status="selected", scope=consumer_scopes[cid],
                                          location_role="purchased_energy", direction="input"))
                m_bg = _create_validate_method(base, app_id, bg_rev,
                                               f"S4b background scope {run_tag}", "pcf", rules_bg)
                snap_grouped = _request(base, "POST",
                                        f"{API}/applications/{app_id}/system-revisions/{bg_rev}/solve",
                                        {"demand": bg_demand,
                                         "idempotency_key": f"s4b-bggrp-{uuid.uuid4().hex[:10]}",
                                         "calculation_purpose": "lca", "analysis_task": "pcf",
                                         "climate_default": True, "project_background_pins": [pin],
                                         "calculation_method_ref": {"method_id": m_bg["method_id"],
                                                                    "version": m_bg["version"],
                                                                    "content_sha256": m_bg["content_sha256"]}})
                pcf_bg = _pcf(base, snap_grouped["id"], pcf_ref)
                umg = (pcf_bg.get("contribution_analysis") or {}).get("user_method_grouping") or {}
                grp = umg.get("grouping") or {}
                sc = grp.get("scopes") or {}
                s1 = (sc.get("scope_1") or {}).get("value")
                s2 = (sc.get("scope_2") or {}).get("value")
                expected_s2 = sum(t["value"] for t in terms_bg
                                  if t["attribution_basis"] == "background_consumer_path")
                grouping_ok = (umg.get("grouping_mode") == "path_weighted"
                               and s2 is not None and _isclose(s2, expected_s2) and expected_s2 > 0
                               and s1 is not None and _isclose(s1, total0)
                               and grp.get("reconciled") is True)
                artifacts["background_grouping"] = {
                    "method_id": m_bg["method_id"], "snapshot_id": snap_grouped["id"],
                    "scope_1": s1, "scope_2": s2, "expected_scope_2": expected_s2,
                    "foreground_no_pin_total": total0, "reconciled": grp.get("reconciled"),
                    "consumer_inputs": sorted(consumer_scopes)}
                check("background_scope23_grouping_live", grouping_ok,
                      {"grouping_mode": umg.get("grouping_mode"), "scope_1": s1, "scope_2": s2,
                       "expected_scope_2": expected_s2, "foreground_no_pin_total": total0,
                       "reconciled": grp.get("reconciled"), "consumer_inputs": sorted(consumer_scopes)})
    except (RuntimeError, StopIteration) as exc:
        fail_all(bg_numeric_names + bg_limit_names, f"background route runtime failure: {exc}")

    # This HTTP driver does not inspect pixels. Record the independently operated browser run
    # with its actual viewport, interactions and screenshots instead of inferring its verdict.
    not_run("visible_browser_journey",
            "separate visible-browser evidence required; this CLI run does not measure browser visibility")

    failures = [c["name"] for c in checks if c["result"] == "fail"]

    # Independent per-surface criteria: a required surface counts as success ONLY when every one of
    # its checks passed. A not_run (a real gap, never a pass) or a fail keeps that surface out of
    # "all success", so a blocked CBAM/background/browser surface cannot hide behind the proven
    # foreground numerics.
    surfaces_def = {
        "foreground": [
            "engine_emits_nonempty_climate_path_receipt",
            "pcf_grouping_mode_is_path_weighted",
            "pcf_grouping_a_reconciled_and_fully_counted",
            "pcf_ab_exclusion_removes_exactly_one_path",
            "history_replay_cache_hits_same_frozen_snapshot",
            "edit_bumps_head_but_v1_ref_stays_frozen",
            "demand_doubling_scales_activity_once_and_footprint_is_intensive",
            "pcf_export_xlsx_present",
            "pcf_report_html_present",
        ],
        "dual_scenario": ["s1_same_input_dual_scenario_comparison"],
        "cbam": cbam_structural_names + cbam_numeric_names +
                ["cbam_trial_excluded_variant_numeric_readback"],
        "org": org_category_names + org_ghg_names,
        "background": bg_numeric_names + bg_limit_names,
        "visible_browser": ["visible_browser_journey"],
    }
    result_by_name = {c["name"]: c["result"] for c in checks}
    surfaces: dict[str, dict] = {}
    for surface, names in surfaces_def.items():
        results = {name: result_by_name.get(name, "missing") for name in names}
        verdict_values = list(results.values())
        if "fail" in verdict_values or "missing" in verdict_values:
            verdict = "fail"
        elif "not_run" in verdict_values:
            verdict = "not_run"
        elif "capability_limitation" in verdict_values:
            verdict = "capability_limitation"
        else:
            verdict = "pass"
        surfaces[surface] = {"required": True, "verdict": verdict, "checks": results}
    surface_failures = sorted(s for s, v in surfaces.items() if v["verdict"] == "fail")
    surface_gaps = sorted(s for s, v in surfaces.items()
                          if v["required"] and v["verdict"] == "not_run")
    # A capability limitation is a documented interface limit, not a runtime failure and not an
    # untested gap. It does not count toward "all success", but it is reported on its own axis so the
    # final hand-back can separate 运行失败 (fail) / 接口能力限制 (capability_limitation) /
    # 数据缺失或未测 (not_run).
    surface_capabilities = sorted(s for s, v in surfaces.items()
                                  if v["verdict"] == "capability_limitation")
    all_success = not failures and not surface_failures and not surface_gaps and not surface_capabilities
    overall_verdict = ("failed" if failures or surface_failures else
                       ("gaps_remain" if surface_gaps else
                        ("capability_limited" if surface_capabilities else "all_success")))
    report = {
        "status": ("failed" if failures else
                   ("gaps_remain" if surface_gaps else
                    ("capability_limited" if surface_capabilities else "ok"))),
        "verdict": overall_verdict,
        "all_success": all_success,
        "application_id": app_id,
        "seed_revision_id": seed_rev,
        "revision_r1": rev1, "revision_r2": rev2,
        "indicator_key": indicator_key,
        "contribution_paths": terms,
        "total_footprint_a": pcf_a["total_footprint"]["value"],
        "counted_a": counted_a, "counted_b": counted_b, "excluded_path": excl,
        "pcf_method_package_ref": pcf_ref,
        "execution_plan_sha_a": m_a.get("execution_plan_sha256"),
        "snapshot_ids": {"r1_baseline": snap0["id"], "a": snap_a["id"], "b": snap_b["id"],
                         "a2": snap_a2["id"]},
        "checks": checks,
        "failed": failures,
        "capability_limitations": [c["name"] for c in checks
                                   if c["result"] == "capability_limitation"],
        "surfaces": surfaces,
        "surface_failures": surface_failures,
        "surface_gaps": surface_gaps,
        "surface_capabilities": surface_capabilities,
    }
    (out / "full-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, payload in artifacts.items():
        (out / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_lines = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}"
        for p in sorted(out.iterdir()) if p.is_file() and p.name != "manifest.sha256"
    ]
    (out / "manifest.sha256").write_text("\n".join(manifest_lines) + "\n", encoding="ascii")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18938")
    parser.add_argument("--mode", choices=["discover", "full"], default="discover")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "discover":
        print(json.dumps(discover(args.url, args.output), ensure_ascii=False, indent=2))
    else:
        report = full(args.url, args.output)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        counts = {"pass": 0, "fail": 0, "not_run": 0, "capability_limitation": 0}
        for c in report["checks"]:
            counts[c["result"]] = counts.get(c["result"], 0) + 1
        print("\nPER-SURFACE VERDICT (required not_run is NOT success):")
        for surface, info in report["surfaces"].items():
            print(f"  {surface:16s} {info['verdict']}")
        open_axes = (report["surface_failures"] + report["surface_gaps"]
                     + report["surface_capabilities"])
        tail = "ALL SURFACES PROVEN" if report["all_success"] else "OPEN: " + ", ".join(open_axes)
        print(
            f"TOTAL: pass={counts['pass']} fail={counts['fail']} not_run={counts['not_run']} "
            f"capability_limitation={counts['capability_limitation']} | {report['verdict'].upper()} | {tail}"
        )
        if report["capability_limitations"]:
            print("INTERFACE CAPABILITY LIMITATIONS (documented, not failures, not untested):")
            for name in report["capability_limitations"]:
                print(f"  - {name}")
        # A runtime error on a required-and-proven surface is a FAIL: surface it with a non-zero exit
        # instead of silently passing. Documented gaps (not_run) and interface capability limitations
        # are reported but exit 0, so the run stays reproducible while the open axes stay visible.
        if report["surface_failures"] or report["failed"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()

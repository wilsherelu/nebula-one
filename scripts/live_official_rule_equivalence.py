"""Compare official organization calculation with its actual template rule copy.

Run only against an owned isolated instance. It creates named revisions/methods;
inventory/factors remain public seed data. Missing suppliers remain missing.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import uuid

import e3_packaged_runtime_verify as P
import live_user_method_acceptance as L


def run(base: str, engine: str, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    tag = uuid.uuid4().hex[:8]
    checks = []

    def check(name, condition, **details):
        checks.append(dict(name=name, status="pass" if condition else "fail", details=details))
        if not condition:
            raise AssertionError((name, details))

    templates = L._request(base, "GET", L.API + "/project-templates")["items"]
    candidates = [item for item in templates if item.get("seed_id") == "nebula.iron-steel.bf-bof-crude-steel"]
    if len(candidates) != 1:
        raise RuntimeError("acceptance needs one exact installed steel template")
    template = candidates[0]
    methods = L._request(base, "GET", f"{L.API}/project-templates/{template['id']}/accounting-methods")
    check("default_library_visible", template.get('version') == '1.1.6'
          and methods['template'].get('accounting_library') == template.get('accounting_library'))
    structural_profile = methods['template']['template_profile']
    check("structural_model_version_preserved", structural_profile['version'] == '1.1.4')
    declared_refs = {f"{m['base_method_ref']['package_id']}@{m['base_method_ref']['version']}"
                     for m in methods['methods'] if m.get('origin') == 'official_package'}
    project = L._request(base, 'POST', f"{L.API}/project-templates/{template['id']}/projects", dict(
        name='Library inheritance ' + tag, project_key=str(uuid.uuid4()),
        expected_template_sha256=template['template_sha256']))
    inherited = L._request(base, 'GET', f"{L.API}/system-revisions/{project['revision_id']}")['application_context']
    check('new_project_inherits_exact_method_set', set(inherited['method_package_refs']) == declared_refs,
          declared=sorted(declared_refs), inherited=sorted(inherited['method_package_refs']))
    check('new_project_freezes_library_and_model_identity',
          inherited['seed_template']['accounting_library'] == template['accounting_library']
          and inherited['seed_template']['profile'] == structural_profile)
    org = [m for m in methods["methods"] if m.get("purpose") == "organization_lifecycle_carbon"]
    if len(org) != 1:
        raise RuntimeError("template must bind one lifecycle organization package")
    copied = L._request(base, "POST", f"{L.API}/project-templates/{template['id']}/accounting-methods/copy",
                        dict(method_key=org[0]["method_key"], name="Official equivalence " + tag))
    app = copied["transcription"]["application_id"]
    revision = copied["transcription"]["model_revision_id"]
    prefix = f"{L.API}/applications/{app}"
    identities = P._discover(base, engine)
    pins = []
    for key in ("ore-sintering::grid-electricity-in", "continuous-casting::grid-electricity-in"):
        pin = L._request(base, "POST", f"{prefix}/workspace/{revision}/background/user-project-resolve",
            dict(consumer_exchange_id=key, project_id=identities["supply"]["supply_project"],
                 version=identities["supply"]["supply_version"]))["pin"]
        pins.append(pin)
    workspace = L._request(base, "GET", f"{prefix}/workspace/{revision}")
    saved = L._request(base, "POST", prefix + "/workspace/inputs", dict(revision_id=revision,
        expected_content_sha256=workspace["content_sha256"], amounts=[7], demand_mode="reference_output",
        values={f["key"]: f["value"] for f in workspace["fields"]}, source="Official equivalence " + tag,
        project_background_pins=pins))
    revision, demand = saved["revision_id"], saved["demand"]
    clone = L._request(base, "POST", f"{L.API}/calculation-methods/{copied['method']['method']['id']}/versions/1/clone",
        dict(name="Exact copied rules " + tag, purpose="organization", model_revision_id=revision))
    method_id = clone["method"]["id"]
    version = clone["versions"][0]
    validated = L._request(base, "POST", f"{L.API}/calculation-methods/{method_id}/versions/1/validate")
    check("copied_rules_validate", validated["valid"], problems=validated.get("problems"))
    ref = dict(method_id=method_id, version=1, content_sha256=version["content_sha256"])
    def solve(ref):
        payload = dict(demand=demand, calculation_purpose="lca", analysis_task="organization",
                       climate_default=True, project_background_pins=pins,
                       idempotency_key="equivalence-" + uuid.uuid4().hex)
        if ref is not None:
            payload["calculation_method_ref"] = ref
        return L._request(base, "POST", f"{prefix}/system-revisions/{revision}/solve", payload)

    baseline, overlay = solve(None), solve(ref)
    org_ref = org[0]["base_method_ref"]
    package_ref = f"{org_ref['package_id']}@{org_ref['version']}"

    def analyze(snapshot):
        return L._request(base, "POST", prefix + "/organization-lifecycle-inventories/current-model",
                         dict(solved_snapshot_id=snapshot["id"], method_package_ref=package_ref))

    old, new = analyze(baseline), analyze(overlay)
    old_result, new_result = old["result"], new["result"]
    for group in ("on_site_direct", "purchased_energy_lifecycle", "other_value_chain"):
        a, b = old_result["groups"][group]["value"], new_result["groups"][group]["value"]
        check("official_copy_" + group, a == b if a is None or b is None else math.isclose(a, b, rel_tol=1e-10),
              official=a, copied=b)
    check("same_period_basis", old_result["activity_basis"] == new_result["activity_basis"])
    check("missing_sources_not_zeroed", old_result["combined_total"] is None and new_result["combined_total"] is None)
    _, terms = L._climate_terms(overlay)
    direct = [t for t in terms if t["attribution_basis"] == "foreground_direct" and t["value"] != 0]
    excluded = direct[0]
    rules = deepcopy(version["rules"])
    rule = next(r for r in rules if r["exchange_id"] == excluded["exchange_id"])
    rule["boundary_status"] = "excluded"
    changed = L._request(base, "PUT", f"{L.API}/calculation-methods/{method_id}/versions/1",
        dict(name=clone["method"]["name"], expected_content_sha256=ref["content_sha256"],
             rules=rules, reporting_dimensions=version["reporting_dimensions"]))
    next_version = next(v for v in changed["versions"] if v["version"] == 2)
    check("edited_version_validates", L._request(base, "POST",
        f"{L.API}/calculation-methods/{method_id}/versions/2/validate")["valid"])
    changed_snapshot = solve(dict(method_id=method_id, version=2, content_sha256=next_version["content_sha256"]))
    changed_result = analyze(changed_snapshot)["result"]
    delta = new_result["groups"]["on_site_direct"]["value"] - changed_result["groups"]["on_site_direct"]["value"]
    check("exclude_exact_real_contribution", math.isclose(delta, excluded["value"], rel_tol=1e-10),
          delta=delta, engine_contribution=excluded["value"], exchange_id=excluded["exchange_id"])
    check("exclusion_detail_preserved", math.isclose(changed_result["user_method_grouping"]["grouping"]["excluded"]["value"], delta, rel_tol=1e-10))
    check("baseline_and_known_model_unchanged", changed_result["base_accounting"]["groups"] == old_result["groups"]
          and changed_result["known_model_total"] == new_result["known_model_total"])
    reread = L._request(base, "GET", prefix + f"/organization-lifecycle-inventories/{old['id']}")
    check("official_history_unchanged", reread["content_sha256"] == old["content_sha256"])
    ghg = next(m for m in methods['methods'] if m.get('purpose') == 'organization_period_inventory')
    ghg_copy = L._request(base, 'POST', f"{L.API}/project-templates/{template['id']}/accounting-methods/copy",
                         dict(method_key=ghg['method_key'], name='GHG factor boundary ' + tag))
    ghg_clone = L._request(base, 'POST',
        f"{L.API}/calculation-methods/{ghg_copy['method']['method']['id']}/versions/1/clone",
        dict(name='GHG exact revision ' + tag, purpose='organization', model_revision_id=revision))
    ghg_id = ghg_clone['method']['id']
    check('ghg_copy_covers_both_electricity_consumers',
          {r['exchange_id'] for r in ghg_clone['versions'][0]['rules'] if r.get('scope') == 'scope_2'}
          == {'ore-sintering::grid-electricity-in', 'continuous-casting::grid-electricity-in'})
    check('ghg_copy_validates', L._request(base, 'POST', f'{L.API}/calculation-methods/{ghg_id}/versions/1/validate')['valid'])
    ghg_snapshot = solve(dict(method_id=ghg_id, version=1, content_sha256=ghg_clone['versions'][0]['content_sha256']))
    rejected = None
    try:
        analyze(ghg_snapshot)
    except RuntimeError as error:
        rejected = str(error)
    check('ghg_generation_boundary_not_silently_replaced_by_lifecycle',
          rejected is not None and 'ORGANIZATION_USER_METHOD_BASE_MISMATCH' in rejected)
    paths = [Path(__file__).resolve().parents[1] / "src/nebula_one" / p for p in
             ("analysis/method_selectors.py", "services/template_accounting_methods.py",
              "services/seed_projects.py", "services/template_method_libraries.py",
              "services/official_product_method.py", "services/organization_lifecycle.py",
              "resources/template_method_libraries/steel-1.1.6.json",
              "resources/official_methods/ghg-organization-period-model-1.0.6.json")]
    report = dict(checks=checks, official=old, copied=new, excluded=changed_result,
                  one_commit=subprocess.check_output(["git", "rev-parse", "HEAD"],
                      cwd=Path(__file__).resolve().parents[1], text=True).strip(),
                  engine_health=L._request(engine, "GET", "/health"),
                  path_receipts=overlay["lcia_results"]["path_weighted_contribution_receipts"],
                  source_sha256={str(p.relative_to(paths[0].parents[2])): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                  application_id=app, revision_id=revision, method_ref=ref,
                  baseline_snapshot=baseline["id"], copied_snapshot=overlay["id"])
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return dict(passed=len(checks), failed=0, output=str(output / "summary.json"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--one", required=True)
    parser.add_argument("--lca", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.one, args.lca, args.output)))

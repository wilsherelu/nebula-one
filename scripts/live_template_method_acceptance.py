"""Exercise template defaults over the existing local HTTP stack, preserving user projects."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from urllib.request import ProxyHandler, Request, build_opener
from urllib.error import HTTPError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18938")
    parser.add_argument("--output", default=".local-evidence/template-method-live.json")
    parser.add_argument("--solve", action="store_true", help="Also solve the inherited method against the live engine")
    args = parser.parse_args()
    opener = build_opener(ProxyHandler({}))

    def request(path, data=None, verb=None):
        body = json.dumps(data).encode() if data is not None else None
        try:
            return json.load(opener.open(Request(args.base_url + "/api/v1" + path, data=body,
                headers={"Content-Type": "application/json"}, method=verb), timeout=60))
        except HTTPError as error:
            raise RuntimeError(f"{path}: {error.code} {error.read().decode('utf-8')}") from error

    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    source = next(item for item in request("/project-templates")["items"] if item.get("seed_id"))
    app_id, revision_id = source["source_application_id"], source["source_revision_id"]
    revision = request(f"/system-revisions/{revision_id}")
    node_id = revision["graph_snapshot"]["nodes"][0]["id"]
    method = request(f"/applications/{app_id}/calculation-methods", {
        "name": "Template-rule acceptance " + tag, "purpose": "pcf", "model_revision_id": revision_id,
        "rules": [{"process_instance_id": node_id, "direction": "emission",
            "boundary_status": "selected", "location_role": "onsite", "scope": "scope_1",
            "classification_basis": "user"}]})
    method_id = method["method"]["id"]
    version = method["versions"][0]
    assert request(f"/calculation-methods/{method_id}/versions/1/validate", {}, "POST")["valid"]
    template = request("/project-templates/authored", {
        "title": "Template-rule acceptance " + tag, "version": "1.0.0",
        "source_application_id": app_id, "source_model_id": source["source_model_id"],
        "source_revision_id": revision_id, "expected_revision_sha256": revision["content_sha256"],
        "methods": [], "user_methods": [{"method_id": method_id, "version": 1,
                                         "content_sha256": version["content_sha256"]}]})

    def create_copy():
        project = request(f"/project-templates/{template['id']}/projects", {
            "name": "Template-rule project " + tag, "project_key": str(uuid4()),
            "expected_template_sha256": template["template_sha256"]})
        methods = request(f"/applications/{project['application_id']}/calculation-methods")
        assert len(methods) == 1 and methods[0]["origin_method_id"] == method_id
        copy = request(f"/calculation-methods/{methods[0]['id']}")
        assert copy["method"]["model_revision_id"] == project["revision_id"]
        assert copy["versions"][0]["status"] == "draft"
        assert copy["versions"][0]["rules"] == version["rules"]
        workspace = request(f"/applications/{project['application_id']}/workspace/{project['revision_id']}")
        assert workspace["demand"]
        validated = request(f"/calculation-methods/{methods[0]['id']}/versions/1/validate", {}, "POST")
        assert validated["valid"], validated
        return project

    first = create_copy()
    request(f"/calculation-methods/{method_id}/versions/1", {
        "name": method["method"]["name"], "description": None,
        "expected_content_sha256": version["content_sha256"],
        "rules": [{**rule, "boundary_status": "excluded", "scope": None} for rule in version["rules"]]}, "PUT")
    second = create_copy()
    assert first["application_id"] != second["application_id"]
    evidence = {"passed": True, "template": template, "source_method_id": method_id,
        "first_project": first, "second_project": second,
        "checks": ["exact-template-freeze", "independent-project-copy", "validation-reset",
                   "project-validation", "workspace-readback", "source-edit-does-not-change-template"]}
    if args.solve:
        inherited = request(f"/applications/{first['application_id']}/calculation-methods")[0]
        inherited_version = request(f"/calculation-methods/{inherited['id']}")["versions"][0]
        workspace = request(f"/applications/{first['application_id']}/workspace/{first['revision_id']}")
        saved = request(f"/applications/{first['application_id']}/workspace/inputs", {
            "revision_id": workspace["revision_id"], "expected_content_sha256": workspace["content_sha256"],
            "amounts": [item["amount"] for item in workspace["demand"]], "demand_mode": "reference_output",
            "values": {field["key"]: field["value"] for field in workspace["fields"]},
            "source": "Template-rule acceptance " + tag})
        rebound = request(f"/calculation-methods/{inherited['id']}/versions/1/clone", {
            "name": inherited["name"], "purpose": inherited["purpose"],
            "model_revision_id": saved["revision_id"]})
        rebound_id = rebound["method"]["id"]
        assert request(f"/calculation-methods/{rebound_id}/versions/1/validate", {}, "POST")["valid"]
        ref = {"method_id": rebound_id, "version": 1,
               "content_sha256": rebound["versions"][0]["content_sha256"]}
        snapshot = request(f"/applications/{first['application_id']}/system-revisions/{saved['revision_id']}/solve", {
            "demand": saved["demand"], "analysis_task": "pcf", "climate_default": True,
            "calculation_purpose": "lca", "calculation_method_ref": ref,
            "idempotency_key": "template-method-" + tag})
        evidence["snapshot_id"] = snapshot["id"]
        evidence["checks"].append("inherited-method-live-solve")
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": True, "checks": len(evidence["checks"]), "evidence": str(destination)}))


if __name__ == "__main__":
    main()

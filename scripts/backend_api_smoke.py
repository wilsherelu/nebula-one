from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from urllib import error, request


def call_json(base_url: str, method: str, path: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    opener = request.build_opener(request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc
    if not isinstance(result, dict):
        raise RuntimeError(f"{method} {path} returned a non-object response")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Nebula One backend API smoke")
    parser.add_argument("--base-url", default="http://127.0.0.1:8088")
    parser.add_argument("--project-id")
    parser.add_argument("--version", type=int)
    parser.add_argument("--application-type", default="system_analysis")
    parser.add_argument("--run-lcia", action="store_true")
    args = parser.parse_args()

    health = call_json(args.base_url, "GET", "/health")
    capabilities = call_json(args.base_url, "GET", "/api/v1/capabilities")
    summary: dict = {
        "health": health.get("status"),
        "capabilities": {
            item["key"]: item["status"] for item in capabilities.get("items", [])
        },
    }
    if not args.project_id and args.version is None:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if not args.project_id or args.version is None:
        raise SystemExit("--project-id and --version must be supplied together")

    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    application = call_json(
        args.base_url,
        "POST",
        "/api/v1/applications",
        {
            "name": f"backend-smoke-{suffix}",
            "application_type": args.application_type,
            "description": "Tagged backend acceptance record",
            "context": {"acceptance_tag": suffix},
        },
    )
    model = call_json(
        args.base_url,
        "POST",
        f"/api/v1/applications/{application['id']}/system-models",
        {
            "name": "backend-smoke-model",
            "provider": "nebula_lca",
            "upstream_project_id": args.project_id,
            "upstream_version": args.version,
        },
    )
    base_revision = call_json(
        args.base_url,
        "GET",
        f"/api/v1/system-revisions/{model['upstream_receipt']['base_revision_id']}",
    )
    operation_batch = call_json(
        args.base_url,
        "POST",
        f"/api/v1/system-models/{model['id']}/operation-batches",
        {
            "parent_revision_id": base_revision["id"],
            "expected_parent_content_sha256": base_revision["content_sha256"],
            "idempotency_key": f"backend-smoke-{suffix}",
            "label": "Backend smoke revision",
            "operations": [
                {
                    "operation_type": "system.merge_context",
                    "payload": {"context": {"acceptance_tag": suffix}},
                }
            ],
        },
    )
    revision = operation_batch["revision"]
    mfa = call_json(
        args.base_url,
        "POST",
        f"/api/v1/system-models/{model['id']}/analysis-runs",
        {
            "capability_key": "mfa.declared.v1",
            "system_revision_id": revision["id"],
            "parameters": {},
        },
    )
    persisted = call_json(
        args.base_url, "GET", f"/api/v1/analysis-runs/{mfa['id']}"
    )
    if persisted.get("status") != "succeeded":
        raise RuntimeError(f"persisted MFA run did not succeed: {persisted}")
    summary.update(
        {
            "application_id": application["id"],
            "system_model_id": model["id"],
            "graph_sha256": model["graph_sha256"],
            "operation_batch_id": operation_batch["batch_id"],
            "system_revision_id": revision["id"],
            "mfa_run_id": mfa["id"],
            "mfa_series": len((mfa.get("result") or {}).get("series") or []),
        }
    )
    if args.run_lcia:
        lcia = call_json(
            args.base_url,
            "POST",
            f"/api/v1/system-models/{model['id']}/analysis-runs",
            {
                "capability_key": "lcia.nebula.v1",
                "parameters": {"lcia_methods": ["EF v3.1"]},
            },
        )
        summary["lcia_run_id"] = lcia["id"]
        summary["nebula_lca_run_id"] = lcia.get("provider_receipt", {}).get(
            "upstream_run_id"
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import httpx


REQUIRED_CONTRACTS = {
    "exact_model_version",
    "lcia_run",
    "provider_model_snapshot",
    "provider_solve",
    "provider_catalog_resolve",
    "tidas_bundle_import",
    "native_bundle_restore",
    "native_bundle_export",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-url", default="http://127.0.0.1:18088")
    parser.add_argument("--engine-url", default="http://127.0.0.1:18081")
    parser.add_argument("--editor-url", default="http://127.0.0.1:18082")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    with httpx.Client(timeout=30, trust_env=False) as client:
        app_health = client.get(f"{args.app_url}/health")
        app_health.raise_for_status()
        engine_health = client.get(f"{args.engine_url}/health")
        engine_health.raise_for_status()
        editor = client.get(f"{args.editor_url}/")
        editor.raise_for_status()
        editor_engine = client.get(f"{args.editor_url}/api/health")
        editor_engine.raise_for_status()
        modeling = client.get(f"{args.app_url}/api/v1/modeling/configuration")
        modeling.raise_for_status()
        engine = client.get(f"{args.app_url}/api/v1/engine")
        engine.raise_for_status()
        root = client.get(f"{args.app_url}/")
        root.raise_for_status()
        catalog = client.get(f"{args.app_url}/api/v1/casepacks")
        catalog.raise_for_status()
        templates = client.get(f"{args.app_url}/api/v1/project-templates")
        templates.raise_for_status()
        setup = client.get(f"{args.app_url}/api/v1/setup-status")
        setup.raise_for_status()

    engine_payload = engine.json()
    contracts = engine_payload.get("contracts", {})
    checks = {
        "nebula_one_health": app_health.json().get("status") == "ok",
        "nebula_lca_health": engine_health.json().get("status") == "ok",
        "editor_shell": "<div id=\"root\"" in editor.text,
        "editor_uses_same_engine": editor_engine.json().get("database") == engine_health.json().get("database"),
        "modeling_handoff_ready": modeling.json().get("available") is True,
        "provider_ready": engine_payload.get("status") == "ready",
        "required_contracts": all(contracts.get(key) is True for key in REQUIRED_CONTRACTS),
        "web_shell": "Nebula One" in root.text,
        "example_catalog": bool(catalog.json().get("items") or templates.json().get("items")),
        "setup_ready": setup.json().get("status") == "ready",
    }
    if not all(checks.values()):
        raise RuntimeError(f"deployment smoke failed: {checks}")
    receipt = {
        "schema_version": "nebula.one.deployment-smoke.v1",
        "status": "passed",
        "app_url": args.app_url,
        "engine_url": args.engine_url,
        "editor_url": args.editor_url,
        "checks": checks,
        "versions": {
            "nebula_one": app_health.json().get("version"),
            "nebula_lca": engine_health.json(),
        },
        "contracts": contracts,
    }
    encoded = (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    receipt["receipt_sha256"] = hashlib.sha256(encoded).hexdigest()
    output = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from pathlib import Path

import httpx


def _port(
    port_id: str,
    flow_uuid: str,
    name: str,
    amount: float,
    direction: str,
    exchange_type: str,
    *,
    product: bool = False,
) -> dict:
    return {
        "id": port_id,
        "flowUuid": flow_uuid,
        "flowSourceNamespace": "provider-smoke",
        "flowVersion": "1.0",
        "flowPropertyUuid": "fp-mass",
        "flowPropertyVersion": "1.0",
        "unitGroupUuid": "ug-mass",
        "unitGroupVersion": "1.0",
        "name": name,
        "unit": "kg",
        "unitGroup": "Mass",
        "amount": amount,
        "type": exchange_type,
        "direction": direction,
        "isProduct": product,
    }


def _graph() -> dict:
    return {
        "functionalUnit": "1 kg final product",
        "nodes": [
            {
                "id": "node-p1",
                "node_kind": "unit_process",
                "mode": "normalized",
                "process_uuid": "p1",
                "name": "Provider",
                "location": "CN",
                "reference_product": "Intermediate",
                "inputs": [
                    _port(
                        "in-feed",
                        "flow-feed",
                        "Feedstock",
                        4.0,
                        "input",
                        "technosphere",
                    )
                ],
                "outputs": [
                    _port(
                        "out-mid",
                        "flow-mid",
                        "Intermediate",
                        1.0,
                        "output",
                        "technosphere",
                        product=True,
                    ),
                    _port(
                        "out-co2",
                        "flow-co2",
                        "Carbon dioxide",
                        3.0,
                        "output",
                        "biosphere",
                    ),
                ],
            },
            {
                "id": "node-p2",
                "node_kind": "unit_process",
                "mode": "normalized",
                "process_uuid": "p2",
                "name": "Consumer",
                "location": "CN",
                "reference_product": "Final product",
                "inputs": [
                    _port(
                        "in-mid",
                        "flow-mid",
                        "Intermediate",
                        2.0,
                        "input",
                        "technosphere",
                    )
                ],
                "outputs": [
                    _port(
                        "out-final",
                        "flow-final",
                        "Final product",
                        1.0,
                        "output",
                        "technosphere",
                        product=True,
                    ),
                    _port(
                        "out-waste",
                        "flow-waste",
                        "Waste",
                        1.0,
                        "output",
                        "technosphere",
                    ),
                ],
            },
        ],
        "exchanges": [
            {
                "id": "edge-mid",
                "fromNode": "node-p1",
                "toNode": "node-p2",
                "sourceHandle": "out:out-mid",
                "targetHandle": "in:in-mid",
                "flowUuid": "flow-mid",
                "flowName": "Intermediate",
                "quantityMode": "single",
                "amount": 2.0,
                "unit": "kg",
                "type": "technosphere",
            }
        ],
        "metadata": {
            "database_release": "provider-smoke-release",
            "functional_unit": {
                "display_text": "1 kg final product",
                "amount": 1.0,
                "flow_uuid": "flow-final",
                "flow_source_namespace": "provider-smoke",
                "flow_version": "1.0",
                "unit": "kg",
                "unit_group_uuid": "ug-mass",
                "unit_group_version": "1.0",
            },
        },
    }


def _ok(response: httpx.Response) -> dict:
    if not response.is_success:
        raise RuntimeError(
            f"{response.request.method} {response.request.url} returned "
            f"HTTP {response.status_code}: {response.text}"
        )
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-url", default="http://127.0.0.1:8001")
    parser.add_argument("--app-url", default="http://127.0.0.1:8088")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    graph = _graph()
    suffix = uuid.uuid4().hex[:8]
    with httpx.Client(timeout=30, trust_env=False) as client:
        assert _ok(client.get(f"{args.engine_url}/health"))["status"] == "ok"
        assert _ok(client.get(f"{args.app_url}/health"))["status"] == "ok"

        project = _ok(
            client.post(
                f"{args.engine_url}/api/projects",
                json={
                    "name": f"Provider smoke {suffix}",
                    "reference_product": "Final product",
                    "functional_unit": graph["functionalUnit"],
                },
            )
        )
        project_id = project["project_id"]
        version = _ok(
            client.post(
                f"{args.engine_url}/api/projects/{project_id}/versions",
                json={"graph": graph},
            )
        )
        version_number = version["version"]

        application = _ok(
            client.post(
                f"{args.app_url}/api/v1/applications",
                json={
                    "name": f"Provider smoke {suffix}",
                    "application_type": "system_analysis",
                },
            )
        )
        system_model = _ok(
            client.post(
                f"{args.app_url}/api/v1/applications/{application['id']}/system-models",
                json={
                    "name": "Pinned provider smoke model",
                    "provider": "nebula_lca",
                    "upstream_project_id": project_id,
                    "upstream_version": version_number,
                },
            )
        )
        base_revision_id = system_model["upstream_receipt"]["base_revision_id"]
        snapshot = _ok(
            client.get(
                f"{args.app_url}/api/v1/provider/models/{project_id}/versions/{version_number}/snapshot"
            )
        )
        solved = _ok(
            client.post(
                f"{args.app_url}/api/v1/applications/{application['id']}/system-revisions/{base_revision_id}/solve",
                json={
                    "demand": [
                        {
                            "process_uuid": "p2",
                            "amount": 1.0,
                            "unit": "kg",
                            "unit_group_uuid": "ug-mass",
                            "unit_group_version": "1.0",
                        }
                    ]
                },
            )
        )
        mfa = _ok(
            client.get(
                f"{args.app_url}/api/v1/solved-system-snapshots/{solved['id']}/mfa"
            )
        )
        sankey_response = client.get(
            f"{args.app_url}/api/v1/solved-system-snapshots/{solved['id']}/mfa/sankey.svg"
        )
        if not sankey_response.is_success:
            raise RuntimeError(
                f"GET {sankey_response.request.url} returned "
                f"HTTP {sankey_response.status_code}: {sankey_response.text}"
            )
        sankey_svg = sankey_response.text

    activities = {
        item["process_id"]: item["value"] for item in solved["activity_vector"]
    }
    assert activities == {"p1": 2.0, "p2": 1.0}, activities
    assert solved["database_release"] == "provider-smoke-release"
    assert solved["provider_receipt"]["status"] == "completed"
    assert solved["contribution_graph"]["inventory_totals"]
    summary = {
        "status": "ok",
        "project_id": project_id,
        "version": version_number,
        "provider_graph_hash": snapshot["graph_hash"],
        "system_model_id": system_model["id"],
        "solved_snapshot_id": solved["id"],
        "solve_hash": solved["solve_hash"],
        "activities": activities,
        "scaled_technosphere_count": len(solved["scaled_technosphere_exchanges"]),
        "scaled_elementary_count": len(solved["scaled_elementary_exchanges"]),
        "mfa_audit_status": mfa["audit"]["status"],
        "mfa_series": [item["series_id"] for item in mfa["series"]],
    }
    if args.output_dir is not None:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        artifacts = {
            "case-input.json": {
                "schema_version": "nebula_one.case.v1",
                "feature": "mfa.solved.v1",
                "graph": graph,
                "demand": [
                    {
                        "process_uuid": "p2",
                        "amount": 1.0,
                        "unit": "kg",
                        "unit_group_uuid": "ug-mass",
                        "unit_group_version": "1.0",
                    }
                ],
            },
            "provider-snapshot.json": snapshot,
            "solved-system-snapshot.json": solved,
            "mfa-result.json": mfa,
            "audit.json": mfa["audit"],
            "run-summary.json": summary,
        }
        for filename, payload in artifacts.items():
            (args.output_dir / filename).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        (args.output_dir / "sankey.svg").write_text(sankey_svg, encoding="utf-8")
        evidence_files = sorted(
            path for path in args.output_dir.iterdir() if path.is_file()
        )
        manifest_lines = [
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
            for path in evidence_files
            if path.name != "manifest.sha256"
        ]
        (args.output_dir / "manifest.sha256").write_text(
            "\n".join(manifest_lines) + "\n", encoding="ascii"
        )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

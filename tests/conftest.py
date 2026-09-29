from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from nebula_one.config import Settings
from nebula_one.hashing import canonical_graph_sha256, canonical_json_sha256
from nebula_one.main import create_app
from nebula_one.mapped_background_schemas import ProviderMappedBackgroundProcessPin


@pytest.fixture()
def model_graph() -> dict:
    return {
        "functionalUnit": "8 kg product",
        "nodes": [
            {
                "id": "preparation",
                "node_kind": "unit_process",
                "mode": "normalized",
                "process_uuid": "process-preparation",
                "name": "Preparation",
                "location": "CN-SH",
                "reference_product": "material",
                "inputs": [
                    {
                        "id": "ore-in",
                        "flowUuid": "flow-ore",
                        "name": "ore",
                        "unit": "kg",
                        "unitGroup": "Units of mass",
                        "amount": 10.0,
                        "type": "technosphere",
                        "direction": "input",
                    }
                ],
                "outputs": [
                    {
                        "id": "material-out",
                        "flowUuid": "flow-material",
                        "name": "material",
                        "unit": "kg",
                        "unitGroup": "Units of mass",
                        "amount": 8.0,
                        "type": "technosphere",
                        "direction": "output",
                    },
                    {
                        "id": "waste-out",
                        "flowUuid": "flow-waste",
                        "name": "waste",
                        "unit": "kg",
                        "unitGroup": "Units of mass",
                        "amount": 2.0,
                        "type": "technosphere",
                        "direction": "output",
                    },
                ],
                "emissions": [],
            },
            {
                "id": "product",
                "node_kind": "unit_process",
                "mode": "normalized",
                "process_uuid": "process-product",
                "name": "Product",
                "location": "CN-SH",
                "reference_product": "product",
                "inputs": [
                    {
                        "id": "material-in",
                        "flowUuid": "flow-material",
                        "name": "material",
                        "unit": "kg",
                        "unitGroup": "Units of mass",
                        "amount": 8.0,
                        "type": "technosphere",
                        "direction": "input",
                    }
                ],
                "outputs": [
                    {
                        "id": "product-out",
                        "flowUuid": "flow-product",
                        "name": "product",
                        "unit": "kg",
                        "unitGroup": "Units of mass",
                        "amount": 8.0,
                        "type": "technosphere",
                        "direction": "output",
                    }
                ],
                "emissions": [],
            },
        ],
        "exchanges": [
            {
                "id": "edge-material",
                "fromNode": "preparation",
                "toNode": "product",
                "sourcePortId": "material-out",
                "targetPortId": "material-in",
                "flowUuid": "flow-material",
                "flowName": "material",
                "quantityMode": "single",
                "amount": 8.0,
                "providerAmount": 8.0,
                "consumerAmount": 8.0,
                "unit": "kg",
                "type": "technosphere",
            }
        ],
        "metadata": {},
    }


@pytest.fixture()
def upstream_requests() -> list[dict]:
    return []


SYNTHETIC_SHA256 = {
    "content": "c" * 64,
    "snapshot": "s" * 64,
    "property": "p" * 64,
    "group": "g" * 64,
    "unit": "u" * 64,
}


def _technosphere_flow_receipts(graph: dict) -> list[dict]:
    """Echo one receipt per graph technosphere port, exact TIDAS only where the port says so."""
    receipts = []
    for node in graph.get("nodes") or []:
        for group in ("inputs", "outputs"):
            for port in node.get(group) or []:
                if port.get("type") != "technosphere":
                    continue
                exact = port.get("flowSourceNamespace") == "tiangong_open_data"
                receipts.append(
                    {
                        "exchange_id": f"{node['id']}::{port['id']}",
                        "process_uuid": node.get("process_uuid"),
                        "source_namespace": port.get("flowSourceNamespace"),
                        "flow_uuid": port.get("flowUuid"),
                        "version": port.get("flowVersion"),
                        "flow_property_uuid": port.get("flowPropertyUuid"),
                        "flow_property_version": port.get("flowPropertyVersion"),
                        "unit_group_uuid": port.get("unitGroupUuid"),
                        "unit_group_version": port.get("unitGroupVersion"),
                        "unit": port.get("unit"),
                        "resolution": (
                            "tidas_exact_snapshot" if exact else "inline_custom"
                        ),
                        **(
                            {
                                "content_hash": SYNTHETIC_SHA256["content"],
                                "snapshot_hash": SYNTHETIC_SHA256["snapshot"],
                                "flow_property_content_hash": SYNTHETIC_SHA256["property"],
                                "unit_group_content_hash": SYNTHETIC_SHA256["group"],
                                "unit_content_hash": SYNTHETIC_SHA256["unit"],
                            }
                            if exact
                            else {}
                        ),
                    }
                )
    return receipts


def _mapped_background_receipts(pins: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return one activity-consistent receipt per pinned consumer, plus the provider's activity."""
    receipts = []
    activities = []
    for raw in pins:
        pin = ProviderMappedBackgroundProcessPin.model_validate(raw)
        receipt = pin.model_dump(mode="json")
        receipt.update(
            schema_version="provider.mapped-background-process-receipt.v1",
            process_content_hash=receipt.pop("expected_process_content_hash"),
            vector_checksum=receipt.pop("expected_vector_checksum"),
            claim_limit="partial_background_leaf_only_not_complete_cradle_to_gate",
            vector_nnz=1,
            quantitative_reference_amount=1.0,
            activity_amount=10.0,
            process_scale=10.0,
        )
        receipts.append(receipt)
        activities.append(
            {
                "process_uuid": pin.process_uuid,
                "activity_amount": 10.0,
                "reference_exchange_id": "synthetic-provider-out",
                "reference_flow_uuid": pin.target_flow_uuid,
                "unit": pin.target_unit,
            }
        )
    return receipts, activities


def _native_climate_answer(pin: dict) -> dict:
    """One synthetic EF v3.1 climate-total answer for the pinned method package.

    Amounts, flow identities and coverage counts are invented here; the numbers carry no meaning
    beyond the shape the contract requires, and no licensed factor appears in this file.
    """
    def term(**overrides) -> dict:
        return {
            "exchange_id": "synthetic::carbon-dioxide-out",
            "process_uuid": "synthetic-provider",
            "source_namespace": "ecoinvent",
            "flow_uuid": "08a91e70-3ddc-11dd-923d-0050c2490048",
            "flow_version": "3.11",
            "direction": "output",
            "compartment": "air, unspecified",
            "subcompartment": "air, unfinalised",
            "amount": 5.0,
            "amount_unit": "kg",
            "cf_presence": "explicit_nonzero",
            "cf_value": 1.0,
            "cf_source": "ecoinvent_3.11_native_EF_v3.1_climate_total",
            "cf_method": "EF v3.1",
            "cf_database_release": "ecoinvent_3.11",
            "method_package_sha256": pin["method_package_sha256"],
            "contribution_value": 5.0,
            **overrides,
        }

    return {
        "schema_version": "provider.native-background-climate-total.response.v1",
        "method_package_id": pin["method_package_id"],
        "method_package_version": pin["method_package_version"],
        "method_package_sha256": pin["method_package_sha256"],
        "runtime_manifest_sha256": pin["runtime_manifest_sha256"],
        "indicator": {
            "method": "EF v3.1",
            "category": "climate change",
            "name": "GWP100",
            "unit": "kg CO2-Eq",
        },
        "merge_status": "merged",
        "merge_blockers": [],
        "unified_climate_total": 5.5,
        "domains": {
            "foreground": {
                "source_namespace": "tiangong_open_data",
                "contribution_value": 4.0,
                "indicator_unit": "kg CO2-Eq",
                "coverage": {"explicit_nonzero": 3},
                "negative_cf_exchange_count": 0,
                "terms": [
                    term(
                        process_uuid="synthetic-steel",
                        source_namespace="tiangong_open_data",
                        flow_uuid="synthetic-carbon-dioxide",
                        flow_version="01.00.000",
                        compartment="air, unspecified",
                        subcompartment=None,
                        amount=4.0,
                        cf_value=1.0,
                        cf_source="tiangong_open_data_EF_v3.1_climate_total",
                        cf_database_release="EF v3.1",
                        contribution_value=4.0,
                    )
                ],
            },
            "native_background": {
                "source_namespace": "ecoinvent",
                "contribution_value": 1.5,
                "indicator_unit": "kg CO2-Eq",
                "coverage": {"explicit_nonzero": 83, "no_cf": 2654},
                "negative_cf_exchange_count": 1,
                "terms": [
                    term(amount=5.0, cf_value=1.0, contribution_value=5.0),
                    term(
                        exchange_id="synthetic::carbon-storage-in",
                        flow_uuid="99a91e70-3ddc-11dd-923d-0050c2490048",
                        amount=3.5,
                        cf_value=-1.0,
                        contribution_value=-3.5,
                    ),
                    term(
                        exchange_id="synthetic::uncharacterised-out",
                        flow_uuid="aaa91e70-3ddc-11dd-923d-0050c2490048",
                        amount=2.0,
                        cf_presence="no_cf",
                        cf_value=None,
                        contribution_value=None,
                    ),
                ],
            },
        },
        "provider_system_model_evidence": "not_asserted_by_local_vector_metadata",
        "carbon_storage_permanence": "not_assessed",
        "claim_limit": (
            "partial_background_leaf_only_not_complete_product_carbon_footprint"
        ),
        "next_contract_field": "preserved",
    }


def _with_background_evidence(body: dict, answer: dict) -> dict:
    """Attach the evidence One refuses to freeze a solve without, when the request asked for it.

    A projection solve keeps the minimal historical answer, and a request that pins a mapped
    background provider or opts into the native climate total gets its receipts and its climate
    answer, because both are refused as incomplete further down. An exact TIDAS port always gets
    its receipts whether or not anything was pinned, because the engine answers that way.
    """
    provenance = answer["provenance"]
    pins = body.get("mapped_background_process_pins") or []
    receipts = _technosphere_flow_receipts(
        (body.get("inline_snapshot") or {}).get("graph") or {}
    )
    if pins or any(item["resolution"] == "tidas_exact_snapshot" for item in receipts):
        answer["technosphere_flow_receipts"] = receipts
    if pins:
        mapped_receipts, activities = _mapped_background_receipts(pins)
        answer["activity_vector"] = [*answer["activity_vector"], *activities]
        answer["mapped_background_process_receipts"] = mapped_receipts
        provenance["mapped_background_process_pins_hash"] = canonical_json_sha256(
            [
                ProviderMappedBackgroundProcessPin.model_validate(item).model_dump(
                    mode="json"
                )
                for item in sorted(pins, key=lambda item: item["consumer_exchange_id"])
            ]
        )
    pin = body.get("native_background_climate")
    if isinstance(pin, dict):
        answer["native_background_climate"] = _native_climate_answer(pin)
        provenance["native_climate_method_package_sha256"] = pin["method_package_sha256"]
        provenance["native_climate_runtime_manifest_sha256"] = pin["runtime_manifest_sha256"]
    return answer


@pytest.fixture()
def engine_transport(model_graph, upstream_requests):
    """The synthetic Nebula LCA the shared client talks to, so a restart can reuse the same engine."""
    def handler(request: httpx.Request) -> httpx.Response:
        content_type = request.headers.get("content-type", "")
        upstream_requests.append(
            {
                "method": request.method,
                "path": request.url.path,
                "query": request.url.query.decode("utf-8"),
                "json": (
                    json.loads(request.content)
                    if request.content and "application/json" in content_type
                    else None
                ),
                "tidas_dry_run": (
                    b'name="dry_run"\r\n\r\ntrue' in request.content
                    if request.url.path == "/api/import/tidas/bundle"
                    else None
                ),
            }
        )
        if request.method == "GET" and request.url.path == "/api/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.method == "GET" and request.url.path == "/openapi.json":
            return httpx.Response(
                200,
                json={
                    "paths": {
                        "/api/projects/{project_id}/versions/{version}": {},
                        "/api/model/run": {},
                        "/api/provider/v1/models/{project_id}/versions/{version}/snapshot": {},
                        "/api/provider/v1/solve": {},
                        "/api/provider/v1/catalog/resolve": {},
                        "/api/import/tidas/bundle": {},
                        "/api/native-project-bundles/import": {},
                        "/api/native-project-bundles/projects/{project_id}": {},
                    }
                },
            )
        if (
            request.method == "GET"
            and request.url.path == "/api/projects/project-1/versions/3"
        ):
            return httpx.Response(
                200,
                headers={"ETag": '"graph-v3"'},
                json={
                    "project_id": "project-1",
                    "name": "Public model",
                    "version": 3,
                    "created_at": "2026-08-29T00:00:00Z",
                    "graph": model_graph,
                    "source_policy": "tidas_compliant",
                    "allowed_lcia_scope": "ef31_only",
                },
            )
        if request.method == "POST" and request.url.path == "/api/model/run":
            return httpx.Response(
                200,
                json={
                    "run_id": "nebula-run-1",
                    "status": "completed",
                    "summary": {"methods": ["EF v3.1"]},
                    "tiangong_like_input": {},
                    "lci_result": {"Climate change": 12.5},
                },
            )
        if request.method == "GET" and request.url.path in {
            "/api/projects/tidas-project/versions/1",
            "/api/projects/native-project/versions/1",
        }:
            project_id = request.url.path.split("/")[3]
            return httpx.Response(
                200,
                json={
                    "project_id": project_id,
                    "name": "Imported model",
                    "version": 1,
                    "created_at": "2026-09-02T00:00:00Z",
                    "graph": model_graph,
                    "source_policy": "tidas_compliant",
                    "allowed_lcia_scope": "ef31_only",
                },
            )
        if request.method == "GET" and request.url.path in {
            "/api/projects/tidas-project/versions",
            "/api/projects/native-project/versions",
        }:
            project_id = request.url.path.split("/")[3]
            return httpx.Response(
                200,
                json=[{
                    "project_id": project_id,
                    "version": 1,
                    "created_at": "2026-09-02T00:00:00Z",
                    "graph_hash": "b" * 64,
                }],
            )
        if request.method == "POST" and request.url.path == "/api/import/tidas/bundle":
            dry_run = b'name="dry_run"\r\n\r\ntrue' in request.content
            blocked = b'filename="blocked.zip"' in request.content
            return httpx.Response(
                200,
                json={
                    "job_id": "preview-job" if dry_run else "import-job",
                    "import_type": "bundle",
                    "source_path": "upload://fixture.zip",
                    "dry_run": dry_run,
                    "upsert_mode": "update",
                    "strict_mode": not dry_run,
                    "total_files": 3,
                    "total_records": 4,
                    "inserted": 1,
                    "updated": 0,
                    "skipped": 0,
                    "failed": 1 if blocked else 0,
                    "warnings": [],
                    "errors": ["missing Flow"] if blocked else [],
                    "imported_process_count": 1,
                    "imported_exchange_count": 2,
                    "filtered_exchange_count": 0,
                    "filtered_exchanges": [],
                    "top_missing_flow_uuids": [],
                    "imported_count": 1,
                    "filtered_count": 0,
                    "warning_count": 0,
                    "failed_count": 0,
                    "unresolved_count": 0,
                    "summary": {},
                    "unresolved": [],
                    "unresolved_items": [],
                    "model_topology_empty_count": 0,
                    "created_projects": [] if dry_run else [{"project_id": "tidas-project", "name": "TIDAS model"}],
                    "created_at": "2026-09-02T00:00:00Z",
                },
            )
        if request.method == "POST" and request.url.path == "/api/native-project-bundles/import":
            return httpx.Response(
                200,
                json={
                    "schema_version": "nebula.project.bundle.v1",
                    "status": "restored",
                    "source_project_id": "source-project",
                    "project_id": "native-project",
                    "identity_remapped": True,
                    "graph_hashes_preserved": True,
                    "counts": {"versions": 1},
                    "issues": [],
                    "source_manifest_sha256": "c" * 64,
                },
            )
        if (
            request.method == "GET"
            and request.url.path
            == "/api/provider/v1/models/project-1/versions/3/snapshot"
        ):
            return httpx.Response(
                200,
                json={
                    "schema_version": "provider.snapshot.v1",
                    "engine": {"version": "0.1.0", "commit": "62a51f3"},
                    "project_id": "project-1",
                    "version": 3,
                    "base_snapshot_ref": {
                        "project_id": "project-1",
                        "version": 3,
                        "graph_hash": canonical_graph_sha256(model_graph),
                    },
                    "graph_hash": canonical_graph_sha256(model_graph),
                    "functional_unit": {
                        "display_text": "8 kg product",
                        "amount": 8.0,
                        "flow_uuid": "flow-product",
                        "unit": "kg",
                    },
                    "graph": model_graph,
                    "issues": [],
                },
            )
        if request.method == "POST" and request.url.path == "/api/provider/v1/solve":
            body = json.loads(request.content)
            request_hash = "a" * 64
            return httpx.Response(
                200,
                json=_with_background_evidence(body, {
                    "schema_version": "nebula_lca.provider.solve.v1",
                    "run_id": "provider-run-1",
                    "status": "completed",
                    "idempotency_key": body.get("idempotency_key"),
                    "request_hash": request_hash,
                    "snapshot_ref": {
                        "project_id": "project-1",
                        "version": 3,
                        "graph_hash": body["inline_snapshot"]["graph_hash"],
                    },
                    "demand": body["demand"],
                    "activity_vector": [
                        {
                            "process_uuid": "product",
                            "activity_amount": 1.0,
                            "reference_exchange_id": "product-out",
                            "reference_flow_uuid": "flow-product",
                            "unit": "kg",
                        }
                    ],
                    "scaled_exchanges": [
                        {
                            "exchange_id": "preparation::ore-in",
                            "process_uuid": "process-preparation",
                            "flow_uuid": "flow-ore",
                            "unit_group_uuid": "Units of mass",
                            "unit": "kg",
                            "direction": "input",
                            "exchange_type": "technosphere",
                            "boundary_role": "boundary",
                            "scaled_amount": 10.0,
                        },
                        {
                            "exchange_id": "preparation::material-out",
                            "process_uuid": "process-preparation",
                            "flow_uuid": "flow-material",
                            "unit_group_uuid": "Units of mass",
                            "unit": "kg",
                            "direction": "output",
                            "exchange_type": "technosphere",
                            "boundary_role": "internal",
                            "scaled_amount": 8.0,
                        },
                        {
                            "exchange_id": "preparation::waste-out",
                            "process_uuid": "process-preparation",
                            "flow_uuid": "flow-waste",
                            "unit_group_uuid": "Units of mass",
                            "unit": "kg",
                            "direction": "output",
                            "exchange_type": "technosphere",
                            "boundary_role": "boundary",
                            "scaled_amount": 2.0,
                        },
                        {
                            "exchange_id": "product::material-in",
                            "process_uuid": "process-product",
                            "flow_uuid": "flow-material",
                            "unit_group_uuid": "Units of mass",
                            "unit": "kg",
                            "direction": "input",
                            "exchange_type": "technosphere",
                            "boundary_role": "internal",
                            "scaled_amount": 8.0,
                        },
                        {
                            "exchange_id": "product::product-out",
                            "process_uuid": "process-product",
                            "flow_uuid": "flow-product",
                            "unit_group_uuid": "Units of mass",
                            "unit": "kg",
                            "direction": "output",
                            "exchange_type": "technosphere",
                            "boundary_role": "boundary",
                            "scaled_amount": 8.0,
                        },
                    ],
                    "inventory_totals": [],
                    "lcia": {},
                    "issues": [],
                    "provenance": {
                        "engine_version": "0.1.0",
                        "engine_commit": "62a51f3",
                        "database_release": "fixture-release",
                        "solver_version": "nebula_hybrid_matrix_v1",
                        "idempotency_key": body.get("idempotency_key"),
                        "request_hash": request_hash,
                    },
                }),
            )
        if (
            request.method == "POST"
            and request.url.path == "/api/provider/v1/catalog/resolve"
        ):
            return httpx.Response(
                200,
                json={
                    "schema_version": "provider.catalog.resolve.response.v1",
                    "items": [],
                    "issues": [],
                },
            )
        if (
            request.method == "POST"
            and request.url.path == "/api/projects/project-1/versions"
        ):
            return httpx.Response(
                201,
                headers={"ETag": '"graph-v4"'},
                json={
                    "project_id": "project-1",
                    "version": 4,
                    "created_at": "2026-08-29T01:00:00Z",
                    "created_new_version": True,
                    "graph_hash": "nebula-internal-slim-graph-hash",
                    "graph_repair_count": 0,
                },
            )
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handler)


@pytest.fixture()
def client(tmp_path, engine_transport):
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'nebula-one.db').as_posix()}",
        nebula_lca_base_url="http://nebula-lca.test",
        nebula_lca_timeout_seconds=5,
    )
    app = create_app(settings, engine_transport=engine_transport)
    with TestClient(app) as test_client:
        yield test_client

from __future__ import annotations

import copy
import json

import httpx
import pytest

from nebula_one.adapters.nebula_lca import (
    NebulaLCAClient,
    same_pinned_model,
    without_flow_display_names,
)
from nebula_one.errors import UpstreamError
from nebula_one.hashing import canonical_graph_sha256


def _client(handler) -> NebulaLCAClient:
    return NebulaLCAClient(
        "http://nebula-lca.test",
        transport=httpx.MockTransport(handler),
    )


def test_probe_reports_provider_v1_contracts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/openapi.json":
            return httpx.Response(
                200,
                json={
                    "paths": {
                        "/api/projects/{project_id}/versions/{version}": {},
                        "/api/model/run": {},
                        "/api/provider/v1/models/{project_id}/versions/{version}/snapshot": {},
                        "/api/provider/v1/solve": {},
                        "/api/provider/v1/catalog/resolve": {},
                    }
                },
            )
        return httpx.Response(404)

    client = _client(handler)
    try:
        assert client.probe()["contracts"] == {
            "exact_model_version": True,
            "lcia_run": True,
            "provider_model_snapshot": True,
            "provider_solve": True,
            "provider_catalog_resolve": True,
            "tidas_bundle_import": False,
            "native_bundle_restore": False,
            "native_bundle_export": False,
        }
    finally:
        client.close()


def test_provider_snapshot_rejects_pin_mismatch() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "schema_version": "nebula_lca.provider.model_snapshot.v1",
                "engine": {"version": "0.1.0", "commit": "abc"},
                "project_id": "different-project",
                "version": 3,
                "graph_hash": "hash",
                "functional_unit": {"flow_uuid": "flow-1", "amount": 1, "unit": "kg"},
                "graph": {},
            },
        )

    client = _client(handler)
    try:
        with pytest.raises(UpstreamError) as captured:
            client.get_provider_model_snapshot("project-1", 3)
        assert captured.value.code == "NEBULA_LCA_MODEL_PIN_MISMATCH"
    finally:
        client.close()


def _engine_graph(names: str, port_amount: float = 1.0) -> dict:
    """One engine graph in the three shapes the engine and authored packs actually use.

    ``names`` is ``filled``, ``null``, or ``absent``: the engine backfills the display column of a
    flow it has already created, so a version can read back in the first two shapes, while an
    authored ``model/graph.json`` leaves the field out entirely.
    """

    def labelled(row: dict, flow: str) -> dict:
        if names == "absent":
            return row
        return {**row, "flow_name_en": flow if names == "filled" else None}

    return {
        "nodes": [
            {
                "id": "ammonia-synthesis",
                "inputs": [
                    labelled(
                        {"uuid": "flow-natural-gas", "amount": 1.0},
                        "Natural gas",
                    )
                ],
                "outputs": [
                    labelled(
                        {"uuid": "flow-ammonia", "amount": port_amount}, "Ammonia"
                    ),
                    labelled(
                        {"uuid": "flow-carbon-dioxide", "amount": 1.0},
                        "Carbon dioxide",
                    ),
                ],
            }
        ],
        "exchanges": [
            labelled(
                {
                    "producer_id": "ammonia-synthesis",
                    "consumer_id": None,
                    "flow_uuid": "flow-carbon-dioxide",
                    "amount": 1.0,
                },
                "Carbon dioxide",
            )
        ],
    }


def _version_handler(graph: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/projects/project-1/versions/1"
        return httpx.Response(
            200,
            json={"project_id": "project-1", "version": 1, "graph": graph},
        )

    return handler


def test_a_flow_display_name_the_engine_backfills_later_cannot_move_the_pin() -> None:
    """One immutable version must hash the same however the engine currently names its flows."""
    filled = _engine_graph("filled")
    nulled = _engine_graph("null")
    authored = _engine_graph("absent")
    assert len({canonical_graph_sha256(filled), canonical_graph_sha256(nulled)}) == 2

    client = _client(_version_handler(filled))
    try:
        returned = client.get_model_version("project-1", 1).payload["graph"]
    finally:
        client.close()

    assert returned == authored
    assert canonical_graph_sha256(returned) == canonical_graph_sha256(
        without_flow_display_names(nulled)
    )
    assert same_pinned_model(filled, returned)
    assert not same_pinned_model(
        _engine_graph("filled", port_amount=2.0), returned
    )
    # the engine's own name sync overwrites the port label and the exchange label too, which is
    # why the comparison cannot simply strip `flow_name_en`
    relabelled = copy.deepcopy(filled)
    for node in relabelled["nodes"]:
        for group in ("inputs", "outputs"):
            for port in node[group]:
                port["name"] = "电网电力（引擎目录标签）"
    for exchange in relabelled["exchanges"]:
        exchange["flowName"] = "二氧化碳（引擎目录标签）"
    assert canonical_graph_sha256(relabelled) != canonical_graph_sha256(filled)
    assert same_pinned_model(relabelled, filled)


def test_the_two_engine_read_shapes_of_one_version_converge_on_a_pin() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/snapshot"):
            return httpx.Response(
                200,
                json={
                    "schema_version": "nebula_lca.provider.model_snapshot.v1",
                    "engine": {"version": "0.1.0", "commit": "abc"},
                    "project_id": "project-1",
                    "version": 1,
                    "graph_hash": "engine-side-hash",
                    "functional_unit": {
                        "flow_uuid": "flow-ammonia",
                        "amount": 1.0,
                        "unit": "kg",
                    },
                    "graph": _engine_graph("filled"),
                },
            )
        return httpx.Response(
            200,
            json={
                "project_id": "project-1",
                "version": 1,
                "graph": _engine_graph("null"),
            },
        )

    client = _client(handler)
    try:
        version_pin = canonical_graph_sha256(
            client.get_model_version("project-1", 1).payload["graph"]
        )
        snapshot_pin = canonical_graph_sha256(
            client.get_provider_model_snapshot("project-1", 1).payload["graph"]
        )
    finally:
        client.close()

    assert version_pin == snapshot_pin == canonical_graph_sha256(_engine_graph("absent"))


def test_provider_solve_fails_closed_when_activity_vector_is_missing() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "schema_version": "nebula_lca.provider.solve.v1",
                "run_id": "run-1",
                "status": "completed",
                "snapshot_ref": {},
                "demand": [],
                "scaled_exchanges": [],
                "inventory_totals": [],
                "issues": [],
                "provenance": {},
            },
        )

    client = _client(handler)
    try:
        with pytest.raises(UpstreamError) as captured:
            client.solve_provider({"inline_snapshot": {}, "demand": []})
        assert captured.value.code == "NEBULA_LCA_PROVIDER_CONTRACT_INVALID"
        assert captured.value.details["missing"] == ["activity_vector"]
    finally:
        client.close()


def test_provider_solve_requires_matching_idempotency_receipt() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "schema_version": "nebula_lca.provider.solve.v1",
                "run_id": "run-1",
                "status": "completed",
                "snapshot_ref": {},
                "demand": [],
                "activity_vector": [],
                "scaled_exchanges": [],
                "inventory_totals": [],
                "issues": [],
                "idempotency_key": "different-key",
                "request_hash": "a" * 64,
                "provenance": {
                    "idempotency_key": "different-key",
                    "request_hash": "a" * 64,
                },
            },
        )

    client = _client(handler)
    try:
        with pytest.raises(UpstreamError) as captured:
            client.solve_provider(
                {
                    "inline_snapshot": {},
                    "demand": [],
                    "idempotency_key": "expected-key",
                }
            )
        assert (
            captured.value.code
            == "NEBULA_LCA_PROVIDER_IDEMPOTENCY_RECEIPT_INVALID"
        )
    finally:
        client.close()


def test_catalog_resolver_requires_explicit_item_and_issue_lists() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "schema_version": "nebula_lca.provider.catalog.v1",
                "items": {},
                "issues": [],
            },
        )

    client = _client(handler)
    try:
        with pytest.raises(UpstreamError) as captured:
            client.resolve_provider_catalog(
                {"schema_version": "provider.catalog.resolve.request.v1", "flows": []}
            )
        assert captured.value.code == "NEBULA_LCA_PROVIDER_CONTRACT_INVALID"
    finally:
        client.close()


def test_catalog_resolver_rejects_unknown_schema_version() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "schema_version": "provider.catalog.resolve.response.v2",
                "items": [],
                "issues": [],
            },
        )

    client = _client(handler)
    try:
        with pytest.raises(UpstreamError) as captured:
            client.resolve_provider_catalog(
                {"schema_version": "provider.catalog.resolve.request.v1"}
            )
        assert captured.value.code == "NEBULA_LCA_PROVIDER_CONTRACT_INVALID"
        assert captured.value.details["schema_version"].endswith(".v2")
    finally:
        client.close()


def _resolved_exact_elementary_flow_item() -> dict:
    key = {
        "source_namespace": "tiangong_open_data",
        "flow_uuid": "f79d0f8f-2b0e-49cb-bed0-b1ea0fbd8625",
        "version": "01.00.004",
        "correlation_id": "electricity-nox",
    }
    return {
        "kind": "flow",
        "key": key,
        "status": "resolved",
        "value": {
            "resolution_source": "tidas_exact_elementary_snapshot",
            "source_namespace": key["source_namespace"],
            "flow_uuid": key["flow_uuid"],
            "version": key["version"],
            "name": "Nitrogen oxides",
            "flow_type": "Elementary flow",
            "flow_property_uuid": "93a60a56-a3c8-11da-a746-0800200b9a66",
            "flow_property_version": "03.00.003",
            "unit_group_uuid": "93a60a57-a4c8-11da-a746-0800200c9a66",
            "unit_group_version": "03.00.003",
            "unit_group": "Units of mass",
            "unit": "kg",
            "default_unit": "kg",
            "direction": "output",
            "classification_path": ["Emissions", "Emissions to air, unspecified"],
            "compartment": "Emissions to air, unspecified",
            "database_release": "EF3.1",
            "content_hash": "1" * 64,
            "snapshot_hash": "2" * 64,
            "flow_property_content_hash": "3" * 64,
            "unit_group_content_hash": "4" * 64,
            "unit_content_hash": "5" * 64,
            "reference_dependency_resolution_source": "provider_reference_seed",
            "reference_dependency_snapshot_hash": None,
            "runtime_flow_index": 17,
            "factor_count": 185,
            "factor_hash": "6" * 64,
        },
        "code": None,
        "message": None,
    }


def _catalog_handler(item: dict):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "schema_version": "provider.catalog.resolve.response.v1",
                "items": [item],
                "issues": [],
            },
        )

    return httpx.MockTransport(handler)


@pytest.mark.parametrize("runtime_index", [None, 17])
def test_catalog_resolver_accepts_identity_with_explicit_empty_factor_evidence(runtime_index) -> None:
    from nebula_one.hashing import canonical_json_sha256
    item = _resolved_exact_elementary_flow_item()
    item["value"].update(runtime_flow_index=runtime_index, factor_count=0, factor_hash=canonical_json_sha256([]))
    client = NebulaLCAClient("http://nebula-lca.test", transport=_catalog_handler(item))
    try:
        value = client.resolve_provider_catalog({"flows": [item["key"]]}).payload["items"][0]["value"]
        assert value["factor_count"] == 0
        assert value["runtime_flow_index"] == runtime_index
    finally:
        client.close()


def test_catalog_resolver_accepts_exact_elementary_flow_receipt() -> None:
    item = _resolved_exact_elementary_flow_item()
    client = NebulaLCAClient("http://nebula-lca.test", transport=_catalog_handler(item))
    try:
        response = client.resolve_provider_catalog({"flows": [item["key"]]})
        value = response.payload["items"][0]["value"]
        assert value["version"] == "01.00.004"
        assert value["factor_count"] == 185
    finally:
        client.close()


@pytest.mark.parametrize(
    ("field", "value", "expected_error_field"),
    [
        ("version", "03.00.004", "version"),
        ("snapshot_hash", "not-a-hash", "snapshot_hash"),
        ("factor_count", -1, "factor_count"),
        ("runtime_flow_index", -1, "runtime_flow_index"),
        ("runtime_flow_index", None, "runtime_flow_index"),
        ("direction", "input", "classification_path"),
        (
            "compartment",
            "Emissions to water, unspecified",
            "classification_path",
        ),
    ],
)
def test_catalog_resolver_rejects_invalid_exact_elementary_flow_receipt(
    field: str,
    value,
    expected_error_field: str,
) -> None:
    item = copy.deepcopy(_resolved_exact_elementary_flow_item())
    item["value"][field] = value
    client = NebulaLCAClient("http://nebula-lca.test", transport=_catalog_handler(item))
    try:
        with pytest.raises(UpstreamError) as captured:
            client.resolve_provider_catalog({"flows": [item["key"]]})
        assert captured.value.code == "NEBULA_LCA_PROVIDER_CONTRACT_INVALID"
        assert captured.value.details["field"] == expected_error_field
    finally:
        client.close()


def _resolved_process_item() -> dict:
    exchange = {
        "exchange_internal_id": "4",
        "direction": "output",
        "amount": 1.0,
        "flow": {
            "source_namespace": "tiangong_open_data",
            "flow_uuid": "b7ce9d42-8843-4752-b408-040a32e6aa4e",
            "version": "01.01.000",
        },
        "flow_catalog_binding_status": "requires_exact_flow_resolution",
        "unit_identity_status": "requires_exact_flow_resolution",
    }
    input_exchange = {
        **exchange,
        "exchange_internal_id": "1",
        "direction": "input",
        "flow": {
            **exchange["flow"],
            "flow_uuid": "e8186909-07ca-41ef-9f5f-0ba05982720a",
            "version": "01.01.001",
        },
    }
    key = {
        "source_namespace": "tiangong_open_data",
        "process_uuid": "f784e009-504d-4422-9e7d-915394e5cdbd",
        "version": "01.01.000",
        "correlation_id": "candidate-delivery",
    }
    return {
        "kind": "process",
        "key": key,
        "status": "resolved",
        "value": {
            "resolution_source": "tidas_exact_process_snapshot",
            "source_namespace": key["source_namespace"],
            "process_uuid": key["process_uuid"],
            "version": key["version"],
            "content_hash": "1" * 64,
            "snapshot_hash": "2" * 64,
            "quantitative_reference": exchange,
            "exchanges": [input_exchange, exchange],
            "input_dependencies": [input_exchange],
            "other_outputs": [],
            "unresolved_exact_flow_refs": [input_exchange["flow"]],
            "dependency_closure_status": "unresolved",
            "background_solve_supported": False,
            "calculation_role": "catalog_only",
        },
        "code": None,
        "message": None,
    }


def test_catalog_resolver_accepts_exact_process_catalog_only_receipt() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "schema_version": "provider.catalog.resolve.response.v1",
                "items": [_resolved_process_item()],
                "issues": [],
            },
        )

    client = _client(handler)
    try:
        response = client.resolve_provider_catalog(
            {
                "schema_version": "provider.catalog.resolve.request.v1",
                "processes": [_resolved_process_item()["key"]],
            }
        )
        assert response.payload["items"][0]["value"]["calculation_role"] == "catalog_only"
    finally:
        client.close()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("background_solve_supported", True),
        ("dependency_closure_status", "resolved"),
        ("calculation_role", "background_provider"),
        ("snapshot_hash", "not-a-hash"),
    ],
)
def test_catalog_resolver_rejects_process_receipt_that_overstates_resolution(
    field: str,
    value,
) -> None:
    item = _resolved_process_item()
    item["value"][field] = value

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "schema_version": "provider.catalog.resolve.response.v1",
                "items": [item],
                "issues": [],
            },
        )

    client = _client(handler)
    try:
        with pytest.raises(UpstreamError) as captured:
            client.resolve_provider_catalog(
                {
                    "schema_version": "provider.catalog.resolve.request.v1",
                    "processes": [item["key"]],
                }
            )
        assert captured.value.code == "NEBULA_LCA_PROVIDER_CONTRACT_INVALID"
        assert captured.value.details["field"] == field
    finally:
        client.close()


def test_catalog_resolver_rejects_process_dependency_projection_drift() -> None:
    item = _resolved_process_item()
    item["value"]["unresolved_exact_flow_refs"] = []

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "schema_version": "provider.catalog.resolve.response.v1",
                "items": [item],
                "issues": [],
            },
        )

    client = _client(handler)
    try:
        with pytest.raises(UpstreamError) as captured:
            client.resolve_provider_catalog(
                {
                    "schema_version": "provider.catalog.resolve.request.v1",
                    "processes": [item["key"]],
                }
            )
        assert captured.value.details["field"] == "unresolved_exact_flow_refs"
    finally:
        client.close()


def _identity_handler(
    *,
    database="sqlite:///D:/isolated/lca_isolated.db",
    openapi_version="3.1.0",
):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/health":
            body = {"status": "ok", "desktop": False}
            if database is not None:
                body["database"] = database
            return httpx.Response(200, json=body)
        if request.url.path == "/openapi.json":
            info = {"title": "LCA Backend Demo"}
            if openapi_version is not None:
                info["version"] = openapi_version
            return httpx.Response(200, json={"info": info, "paths": {}})
        return httpx.Response(404)

    return handler


def test_engine_identity_reads_the_database_and_openapi_version() -> None:
    client = _client(_identity_handler())
    try:
        assert client.engine_identity() == {
            "database": "sqlite:///D:/isolated/lca_isolated.db",
            "openapi_version": "3.1.0",
        }
    finally:
        client.close()


@pytest.mark.parametrize(
    ("database", "openapi_version", "expected_code"),
    [
        (None, "3.1.0", "NEBULA_LCA_HEALTH_DATABASE_MISSING"),
        ("   ", "3.1.0", "NEBULA_LCA_HEALTH_DATABASE_MISSING"),
        ("sqlite:///x.db", None, "NEBULA_LCA_OPENAPI_VERSION_MISSING"),
        ("sqlite:///x.db", " ", "NEBULA_LCA_OPENAPI_VERSION_MISSING"),
    ],
)
def test_engine_identity_refuses_an_incomplete_identity(
    database,
    openapi_version,
    expected_code: str,
) -> None:
    client = _client(
        _identity_handler(database=database, openapi_version=openapi_version)
    )
    try:
        with pytest.raises(UpstreamError) as captured:
            client.engine_identity()
        assert captured.value.code == expected_code
    finally:
        client.close()


def _flow_row(**overrides) -> dict:
    row = {
        "flow_uuid": "8e1e39c0-11ef-4607-85f0-157ae68f6c63",
        "flow_name_en": "Hydrogen",
        "flow_type": "Product flow",
        "default_unit": "kg",
        "unit_group": "Units of mass",
    }
    row.update(overrides)
    return row


def _payload_handler(payload, status_code: int = 200):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload)

    return handler


def test_reference_flow_read_returns_the_exact_identity_row() -> None:
    row = _flow_row()
    client = _client(_payload_handler(row))
    try:
        assert client.get_reference_flow(row["flow_uuid"]) == row
    finally:
        client.close()


@pytest.mark.parametrize("field", ["flow_name_en", "flow_type", "default_unit", "unit_group"])
def test_reference_flow_read_refuses_a_row_without_an_identity_field(field: str) -> None:
    row = _flow_row()
    row.pop(field)
    client = _client(_payload_handler(row))
    try:
        with pytest.raises(UpstreamError) as captured:
            client.get_reference_flow(row["flow_uuid"])
        assert captured.value.code == "NEBULA_LCA_PROVIDER_CONTRACT_INVALID"
        assert captured.value.details["missing"] == [field]
    finally:
        client.close()


def test_reference_flow_read_refuses_a_row_for_a_different_uuid() -> None:
    client = _client(_payload_handler(_flow_row(flow_uuid="00000000-0000-0000-0000-000000000000")))
    try:
        with pytest.raises(UpstreamError) as captured:
            client.get_reference_flow("8e1e39c0-11ef-4607-85f0-157ae68f6c63")
        assert captured.value.code == "NEBULA_LCA_FLOW_IDENTITY_MISMATCH"
    finally:
        client.close()


def test_reference_flow_read_surfaces_a_missing_catalog_row_as_a_404_rejection() -> None:
    client = _client(_payload_handler({"detail": "Not Found"}, status_code=404))
    try:
        with pytest.raises(UpstreamError) as captured:
            client.get_reference_flow("325447e5-57f0-44b9-8cb8-c6fb4e131a15")
        assert captured.value.code == "NEBULA_LCA_REJECTED"
        assert captured.value.details["upstream_status"] == 404
    finally:
        client.close()


def test_structured_upstream_rejection_preserves_actionable_reason():
    detail = {'code': 'TIDAS_REFERENCE_DEPENDENCY_SNAPSHOT_REQUIRED',
              'message': 'Exact Flow Property needs its Unit Group snapshot.',
              'details': {'flow_uuid': 'exact-flow'}}
    client = _client(_payload_handler({'detail': detail}, status_code=422))
    try:
        with pytest.raises(UpstreamError) as captured:
            client.get_reference_flow('exact-flow')
        assert detail['code'] in captured.value.message
        assert detail['message'] in captured.value.message
        assert captured.value.details['upstream_detail'] == detail
        assert captured.value.code == 'NEBULA_LCA_REJECTED'
    finally:
        client.close()


def test_reference_units_query_uses_the_group_name() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("unit_group", ""))
        return httpx.Response(200, json=[{"unit_group": "Units of energy", "name": "MJ"}])

    client = _client(handler)
    try:
        assert client.list_reference_units("Units of energy") == [
            {"unit_group": "Units of energy", "name": "MJ"}
        ]
        assert seen == ["Units of energy"]
    finally:
        client.close()


@pytest.mark.parametrize(
    "payload",
    [
        {"unit_group": "Units of mass"},
        [{"unit_group": "Units of mass", "name": "kg"}, "not-an-object"],
    ],
)
def test_reference_units_read_refuses_a_malformed_payload(payload) -> None:
    client = _client(_payload_handler(payload))
    try:
        with pytest.raises(UpstreamError) as captured:
            client.list_reference_units("Units of energy")
        assert captured.value.code in {
            "NEBULA_LCA_INVALID_RESPONSE",
            "NEBULA_LCA_PROVIDER_CONTRACT_INVALID",
        }
    finally:
        client.close()


def test_reference_units_read_refuses_a_foreign_group_row() -> None:
    client = _client(_payload_handler([{"unit_group": "Units of mass", "name": "kg"}]))
    try:
        with pytest.raises(UpstreamError) as captured:
            client.list_reference_units("Units of energy")
        assert captured.value.code == "NEBULA_LCA_PROVIDER_CONTRACT_INVALID"
        assert captured.value.details["requested"] == "Units of energy"
    finally:
        client.close()


# Synthetic stand-ins for the pinned native climate contract: no licensed rows or factors.
_NATIVE_PIN = {
    "schema_version": "provider.native-background-climate-total.request.v1",
    "database_release": "ecoinvent_3.11",
    "method_package_id": "synthetic-ef31-climate-total",
    "method_package_version": "1.0.0",
    "method_package_sha256": "a" * 64,
    "runtime_manifest_sha256": "b" * 64,
    "flow_snapshot_hash": "c" * 64,
    "reference_dependency_snapshot_hash": "d" * 64,
}


def _native_term(**overrides) -> dict:
    term = {
        "exchange_id": "p-power::co2",
        "process_uuid": "0f0a1b2c-3d4e-5f60-7182-93a4b5c6d7e8",
        "source_namespace": "tiangong_open_data",
        "flow_uuid": "11111111-2222-3333-4444-555555555555",
        "flow_version": "01.00.000",
        "direction": "output",
        "compartment": "air, high indirect",
        "subcompartment": None,
        "amount": 1.5,
        "amount_unit": "kg",
        "cf_presence": "explicit_nonzero",
        "cf_value": 1.0,
        "cf_source": "synthetic_foreground",
        "cf_method": "EF v3.1",
        "cf_database_release": "EF v3.1",
        "method_package_sha256": "a" * 64,
        "contribution_value": 1.5,
    }
    term.update(overrides)
    return term


def _native_domain(*, namespace: str, contribution: float, coverage: dict) -> dict:
    return {
        "source_namespace": namespace,
        "contribution_value": contribution,
        "indicator_unit": "kg CO2-Eq",
        "coverage": coverage,
        "negative_cf_exchange_count": 0,
        "terms": [_native_term()],
    }


def _native_answer(**overrides) -> dict:
    answer = {
        "schema_version": "provider.native-background-climate-total.response.v1",
        "method_package_id": _NATIVE_PIN["method_package_id"],
        "method_package_version": _NATIVE_PIN["method_package_version"],
        "method_package_sha256": _NATIVE_PIN["method_package_sha256"],
        "runtime_manifest_sha256": _NATIVE_PIN["runtime_manifest_sha256"],
        "indicator": {
            "method": "EF v3.1",
            "category": "climate change",
            "name": "GWP100",
            "unit": "kg CO2-Eq",
        },
        "merge_status": "merged",
        "merge_blockers": [],
        "unified_climate_total": 3.5,
        "domains": {
            "foreground": _native_domain(
                namespace="tiangong_open_data",
                contribution=1.5,
                coverage={"explicit_nonzero": 1},
            ),
            "native_background": _native_domain(
                namespace="ecoinvent",
                contribution=2.0,
                coverage={"explicit_nonzero": 2, "no_cf": 3},
            ),
        },
        "provider_system_model_evidence": "not_asserted_by_local_vector_metadata",
        "carbon_storage_permanence": "not_assessed",
        "claim_limit": "partial_background_leaf_only_not_complete_product_carbon_footprint",
    }
    answer.update(overrides)
    return answer


def _native_solve_payload(*, answer: dict | None) -> dict:
    payload = {
        "schema_version": "nebula_lca.provider.solve.v1",
        "run_id": "run-native",
        "status": "completed",
        "snapshot_ref": {},
        "demand": [],
        "activity_vector": [],
        "scaled_exchanges": [],
        "inventory_totals": [],
        "issues": [],
        "provenance": {
            "database_release": "ecoinvent_3.11",
            "native_climate_method_package_sha256": _NATIVE_PIN["method_package_sha256"],
            "native_climate_runtime_manifest_sha256": _NATIVE_PIN["runtime_manifest_sha256"],
        },
    }
    if answer is not None:
        payload["native_background_climate"] = answer
    return payload


def _solve_handler(payload: dict):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return handler


def test_native_climate_answer_is_kept_verbatim_including_unknown_fields() -> None:
    answer = _native_answer(next_contract_field={"counts_toward_coverage": 3})
    client = _client(_solve_handler(_native_solve_payload(answer=answer)))
    try:
        response = client.solve_provider(
            {"inline_snapshot": {}, "demand": [], "native_background_climate": _NATIVE_PIN}
        )
    finally:
        client.close()
    echoed = response.payload["native_background_climate"]
    assert echoed["unified_climate_total"] == 3.5
    assert echoed["domains"]["native_background"]["coverage"]["no_cf"] == 3
    assert echoed["next_contract_field"] == {"counts_toward_coverage": 3}


def test_native_climate_split_diagnostic_is_accepted_without_a_unified_total() -> None:
    answer = _native_answer(
        merge_status="split_diagnostic",
        unified_climate_total=None,
        merge_blockers=[
            {"exchange_id": "p-power::co2", "flow_uuid": "1" * 32, "reason": "foreground_native_method_coefficient_differs"}
        ],
    )
    client = _client(_solve_handler(_native_solve_payload(answer=answer)))
    try:
        response = client.solve_provider(
            {"inline_snapshot": {}, "demand": [], "native_background_climate": _NATIVE_PIN}
        )
    finally:
        client.close()
    assert response.payload["native_background_climate"]["merge_status"] == "split_diagnostic"


@pytest.mark.parametrize(
    ("request_pin", "payload", "expected_reason"),
    [
        (None, _native_solve_payload(answer=_native_answer()), "unexpected_answer"),
        (_NATIVE_PIN, _native_solve_payload(answer=None), "missing_answer"),
        (
            {**_NATIVE_PIN, "method_package_sha256": "e" * 64},
            _native_solve_payload(answer=_native_answer()),
            "answer_identity_differs_from_request_pin",
        ),
        (
            _NATIVE_PIN,
            _native_solve_payload(
                answer=_native_answer(merge_status="split_diagnostic", unified_climate_total=3.5)
            ),
            "answer_shape_invalid",
        ),
        (
            _NATIVE_PIN,
            _native_solve_payload(
                answer=_native_answer(
                    indicator={"method": "EF v3.1", "category": "climate change", "name": "GWP100", "unit": "kg CO2"}
                )
            ),
            "answer_shape_invalid",
        ),
        (
            _NATIVE_PIN,
            {
                **_native_solve_payload(answer=_native_answer()),
                "provenance": {"database_release": "ecoinvent_3.11"},
            },
            "provenance_identity_differs_from_request_pin",
        ),
    ],
)
def test_native_climate_answer_refuses_anything_the_pinned_request_did_not_ask_for(
    request_pin, payload, expected_reason
) -> None:
    client = _client(_solve_handler(payload))
    request = {"inline_snapshot": {}, "demand": []}
    if request_pin is not None:
        request["native_background_climate"] = request_pin
    try:
        with pytest.raises(UpstreamError) as captured:
            client.solve_provider(request)
        assert captured.value.code == "NEBULA_LCA_NATIVE_CLIMATE_CONTRACT_INVALID"
        assert captured.value.details["reason"] == expected_reason
        # Failure details must survive the worker's JSON persistence, including model validators.
        json.dumps(captured.value.details, allow_nan=False)
    finally:
        client.close()


def test_projection_mode_solve_never_gains_a_native_climate_answer() -> None:
    client = _client(_solve_handler(_native_solve_payload(answer=_native_answer())))
    try:
        with pytest.raises(UpstreamError) as captured:
            client.solve_provider({"inline_snapshot": {}, "demand": []})
        assert captured.value.details["reason"] == "unexpected_answer"
    finally:
        client.close()

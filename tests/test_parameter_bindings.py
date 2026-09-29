from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from nebula_one.casepacks import (
    ParameterBindingDocument,
    ParameterBindingError,
    ParentRevisionSnapshot,
    canonical_contract_sha256,
    parse_parameter_binding,
    parse_parameter_set_snapshot,
    resolve_parameter_binding,
    to_operation_batch_create,
)
from nebula_one.hashing import canonical_json_sha256


def _unit(unit: str = "kg", group: str = "Units of mass") -> dict:
    return {
        "unit": unit,
        "unit_group": group,
        "unit_group_uuid": None,
        "unit_group_version": None,
    }


def _binding_payload(*, status: str = "frozen") -> dict:
    return {
        "schema_version": "nebula.parameter-binding.v1",
        "parameter_binding": {
            "id": "resource-efficiency-binding",
            "version": "0.1.0",
            "title": "Resource efficiency binding",
            "lifecycle_status": status,
        },
        "rule_version": "model-operation.v1",
        "bindings": [
            {
                "binding_id": "scale-waste",
                "order": 2,
                "operation": "scale_flow",
                "parameter_key": "waste_factor",
                "parameter_unit_identity": _unit("1", "Dimensionless"),
                "target": {
                    "flow_uuid": "flow-waste",
                    "unit_group": "Units of mass",
                    "unit_group_uuid": None,
                    "unit_group_version": None,
                },
            },
            {
                "binding_id": "set-ore-feed",
                "order": 1,
                "operation": "set_exchange_amount",
                "parameter_key": "ore_feed",
                "parameter_unit_identity": _unit(),
                "target": {
                    "process_id": "preparation",
                    "port_id": "ore-in",
                    "flow_uuid": "flow-ore",
                    "unit_identity": _unit(),
                },
            },
        ],
    }


def _parameter_snapshot_payload(values: dict | None = None) -> dict:
    active_values = values or {
        "ore_feed": {
            "value": 9.0,
            "quantity_kind": "amount",
            "unit_identity": _unit(),
        },
        "waste_factor": {
            "value": 0.5,
            "quantity_kind": "scale_factor",
            "unit_identity": _unit("1", "Dimensionless"),
        },
    }
    metadata = {"source": "test"}
    return {
        "schema_version": "nebula.parameter-set.snapshot.v1",
        "parameter_set_id": "parameter-set-1",
        "status": "frozen",
        "content_sha256": canonical_json_sha256(
            {"values": active_values, "metadata": metadata}
        ),
        "values": active_values,
        "metadata": metadata,
    }


def _resolve(model_graph: dict):
    binding = parse_parameter_binding(_binding_payload())
    parameters = parse_parameter_set_snapshot(_parameter_snapshot_payload())
    parent = ParentRevisionSnapshot(
        revision_id="revision-1",
        content_sha256="b" * 64,
        graph=model_graph,
    )
    return resolve_parameter_binding(binding, parameters, parent)


def test_binding_resolution_is_ordered_deterministic_and_batch_compatible(
    model_graph: dict,
) -> None:
    first = _resolve(model_graph)
    second = _resolve(copy.deepcopy(model_graph))

    assert first == second
    assert [item.binding_id for item in first.operations] == [
        "set-ore-feed",
        "scale-waste",
    ]
    assert first.operations[0].operation_type == "flow.update_port"
    assert first.operations[0].payload["changes"]["amount"] == 9.0
    assert first.operations[1].operation_type == "system.scale_flows"
    assert first.operations[1].payload["factor"] == 0.5
    assert first.idempotency_key == f"parameter-binding:{first.operation_set_sha256}"

    batch = to_operation_batch_create(first)
    assert batch.parent_revision_id == "revision-1"
    assert batch.idempotency_key == first.idempotency_key
    assert [item.operation_type for item in batch.operations] == [
        "flow.update_port",
        "system.scale_flows",
    ]


def test_binding_hash_is_independent_of_input_rule_order() -> None:
    payload = _binding_payload()
    reversed_payload = copy.deepcopy(payload)
    reversed_payload["bindings"].reverse()

    first = parse_parameter_binding(payload)
    second = parse_parameter_binding(reversed_payload)
    assert first == second
    assert canonical_contract_sha256(first) == canonical_contract_sha256(second)


def test_parameter_snapshot_hash_mismatch_fails_closed() -> None:
    payload = _parameter_snapshot_payload()
    payload["values"]["ore_feed"]["value"] = 99.0
    with pytest.raises(ParameterBindingError) as captured:
        parse_parameter_set_snapshot(payload)
    assert captured.value.code == "PARAMETER_SET_HASH_MISMATCH"


def test_binding_must_be_frozen(model_graph: dict) -> None:
    binding = parse_parameter_binding(_binding_payload(status="draft"))
    parameters = parse_parameter_set_snapshot(_parameter_snapshot_payload())
    parent = ParentRevisionSnapshot(
        revision_id="revision-1", content_sha256="b" * 64, graph=model_graph
    )
    with pytest.raises(ParameterBindingError) as captured:
        resolve_parameter_binding(binding, parameters, parent)
    assert captured.value.code == "PARAMETER_BINDING_NOT_FROZEN"


def test_missing_and_unused_parameters_fail_closed(model_graph: dict) -> None:
    missing_payload = _parameter_snapshot_payload()
    del missing_payload["values"]["waste_factor"]
    missing_payload["content_sha256"] = canonical_json_sha256(
        {
            "values": missing_payload["values"],
            "metadata": missing_payload["metadata"],
        }
    )
    binding = parse_parameter_binding(_binding_payload())
    parent = ParentRevisionSnapshot(
        revision_id="revision-1", content_sha256="b" * 64, graph=model_graph
    )
    with pytest.raises(ParameterBindingError) as missing:
        resolve_parameter_binding(
            binding, parse_parameter_set_snapshot(missing_payload), parent
        )
    assert missing.value.code == "PARAMETER_BINDING_PARAMETER_MISSING"

    unused_payload = _parameter_snapshot_payload()
    unused_payload["values"]["unused"] = {
        "value": 1.0,
        "quantity_kind": "scale_factor",
        "unit_identity": _unit("1", "Dimensionless"),
    }
    unused_payload["content_sha256"] = canonical_json_sha256(
        {
            "values": unused_payload["values"],
            "metadata": unused_payload["metadata"],
        }
    )
    with pytest.raises(ParameterBindingError) as unused:
        resolve_parameter_binding(
            binding, parse_parameter_set_snapshot(unused_payload), parent
        )
    assert unused.value.code == "PARAMETER_BINDING_PARAMETER_UNUSED"


def test_unit_mismatch_fails_closed(model_graph: dict) -> None:
    payload = _parameter_snapshot_payload()
    payload["values"]["ore_feed"]["unit_identity"] = _unit("t")
    payload["content_sha256"] = canonical_json_sha256(
        {"values": payload["values"], "metadata": payload["metadata"]}
    )
    with pytest.raises(ParameterBindingError) as captured:
        resolve_parameter_binding(
            parse_parameter_binding(_binding_payload()),
            parse_parameter_set_snapshot(payload),
            ParentRevisionSnapshot(
                revision_id="revision-1",
                content_sha256="b" * 64,
                graph=model_graph,
            ),
        )
    assert captured.value.code == "PARAMETER_BINDING_UNIT_MISMATCH"


def test_unknown_operation_and_expression_are_rejected() -> None:
    unknown = _binding_payload()
    unknown["bindings"][0]["operation"] = "evaluate_expression"
    with pytest.raises(ValidationError):
        ParameterBindingDocument.model_validate(unknown)

    expression = _parameter_snapshot_payload()
    expression["values"]["ore_feed"] = {
        "value": 1.0,
        "quantity_kind": "amount",
        "unit_identity": _unit(),
        "expression": "baseline * 0.9",
    }
    expression["content_sha256"] = canonical_json_sha256(
        {"values": expression["values"], "metadata": expression["metadata"]}
    )
    with pytest.raises(ParameterBindingError) as captured:
        parse_parameter_set_snapshot(expression)
    assert captured.value.code == "PARAMETER_SET_SNAPSHOT_INVALID"


def test_duplicate_and_overlapping_targets_are_rejected() -> None:
    duplicate = _binding_payload()
    duplicate["bindings"].append(copy.deepcopy(duplicate["bindings"][0]))
    duplicate["bindings"][-1]["binding_id"] = "duplicate-scale"
    duplicate["bindings"][-1]["order"] = 3
    with pytest.raises(ValidationError, match="binding targets must be unique"):
        parse_parameter_binding(duplicate)

    overlap = _binding_payload()
    overlap["bindings"][1]["target"]["flow_uuid"] = "flow-waste"
    with pytest.raises(
        ValidationError,
        match="set_exchange_amount and scale_flow targets overlap",
    ):
        parse_parameter_binding(overlap)


def _create_model_and_parameter_set(client, *, freeze: bool = True) -> tuple[dict, dict, dict]:
    application = client.post(
        "/api/v1/applications",
        json={
            "name": "Parameter binding workspace",
            "application_type": "system_analysis",
            "context": {},
        },
    ).json()
    model = client.post(
        f"/api/v1/applications/{application['id']}/system-models",
        json={
            "name": "Binding model",
            "provider": "nebula_lca",
            "upstream_project_id": "project-1",
            "upstream_version": 3,
        },
    ).json()
    parameter = client.post(
        f"/api/v1/applications/{application['id']}/parameter-sets",
        json={
            "name": "Resource efficiency parameters",
            "values": _parameter_snapshot_payload()["values"],
            "metadata": {"source": "test"},
        },
    ).json()
    if freeze:
        parameter = client.post(
            f"/api/v1/parameter-sets/{parameter['id']}/freeze"
        ).json()
    return application, model, parameter


def _apply_binding(
    client,
    model: dict,
    parameter: dict,
    binding: dict | None = None,
    expected_parent_content_sha256: str | None = None,
):
    base_id = model["upstream_receipt"]["base_revision_id"]
    base = client.get(f"/api/v1/system-revisions/{base_id}").json()
    return client.post(
        f"/api/v1/system-models/{model['id']}/parameter-bindings/apply",
        json={
            "parent_revision_id": base_id,
            "expected_parent_content_sha256": (
                expected_parent_content_sha256 or base["content_sha256"]
            ),
            "parameter_set_id": parameter["id"],
            "binding": binding or _binding_payload(),
            "label": "Resource efficiency",
        },
    )


def test_parameter_binding_http_flow_creates_one_idempotent_child_revision(client) -> None:
    _, model, parameter = _create_model_and_parameter_set(client)

    first = _apply_binding(client, model, parameter)
    assert first.status_code == 201, first.text
    first_payload = first.json()
    assert first_payload["operation_batch"]["idempotent_replay"] is False
    assert len(first_payload["operation_batch"]["operations"]) == 2
    child = first_payload["operation_batch"]["revision"]
    ore = child["graph_snapshot"]["nodes"][0]["inputs"][0]
    waste = child["graph_snapshot"]["nodes"][0]["outputs"][1]
    assert ore["amount"] == 9.0
    assert waste["amount"] == 1.0

    replay = _apply_binding(client, model, parameter)
    assert replay.status_code == 201, replay.text
    replay_payload = replay.json()
    assert replay_payload["operation_batch"]["idempotent_replay"] is True
    assert replay_payload["operation_batch"]["batch_id"] == first_payload[
        "operation_batch"
    ]["batch_id"]
    assert replay_payload["operation_batch"]["revision"]["id"] == child["id"]

    revisions = client.get(
        f"/api/v1/system-models/{model['id']}/revisions"
    ).json()
    assert len(revisions) == 2
    base_ore = revisions[0]["graph_snapshot"]["nodes"][0]["inputs"][0]
    assert base_ore["amount"] == 10.0


def test_parameter_binding_http_rejects_unfrozen_parameter_set(client) -> None:
    _, model, parameter = _create_model_and_parameter_set(client, freeze=False)
    response = _apply_binding(client, model, parameter)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PARAMETER_SET_NOT_FROZEN"


def test_parameter_binding_http_requires_exact_parent_hash(client) -> None:
    _, model, parameter = _create_model_and_parameter_set(client)
    response = _apply_binding(
        client,
        model,
        parameter,
        expected_parent_content_sha256="f" * 64,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == (
        "SYSTEM_REVISION_OPTIMISTIC_LOCK_FAILED"
    )


def test_parameter_binding_contract_is_discoverable(client) -> None:
    response = client.get("/api/v1/parameter-binding-contract")
    assert response.status_code == 200
    payload = response.json()
    assert payload["supported_binding_operations"] == [
        "scale_flow",
        "set_exchange_amount",
    ]
    assert payload["parameter_binding_schema"]["additionalProperties"] is False
    assert payload["resolved_operation_set_schema"]["additionalProperties"] is False

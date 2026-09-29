from __future__ import annotations


def _create_model(client) -> tuple[dict, dict]:
    application_response = client.post(
        "/api/v1/applications",
        json={
            "name": "Flow Process System workspace",
            "application_type": "system_analysis",
            "context": {"geography": "CN-SH", "study": "baseline"},
        },
    )
    assert application_response.status_code == 201, application_response.text
    application = application_response.json()
    model_response = client.post(
        f"/api/v1/applications/{application['id']}/system-models",
        json={
            "name": "Operation model",
            "provider": "nebula_lca",
            "upstream_project_id": "project-1",
            "upstream_version": 3,
        },
    )
    assert model_response.status_code == 201, model_response.text
    return application, model_response.json()


def _apply(client, model_id: str, parent_id: str, operation_type: str, payload: dict):
    return client.post(
        f"/api/v1/system-models/{model_id}/operations",
        json={
            "parent_revision_id": parent_id,
            "operation_type": operation_type,
            "payload": payload,
        },
    )


def test_attach_creates_immutable_base_revision(client):
    application, model = _create_model(client)
    base_revision_id = model["upstream_receipt"]["base_revision_id"]

    revisions = client.get(
        f"/api/v1/system-models/{model['id']}/revisions"
    ).json()
    assert len(revisions) == 1
    base = revisions[0]
    assert base["id"] == base_revision_id
    assert base["revision_number"] == 1
    assert base["revision_kind"] == "base"
    assert base["parent_revision_id"] is None
    assert base["graph_sha256"] == model["graph_sha256"]
    assert base["application_context"] == application["context"]
    assert len(base["content_sha256"]) == 64


def test_process_operation_creates_child_without_mutating_parent(client):
    _, model = _create_model(client)
    base_id = model["upstream_receipt"]["base_revision_id"]

    response = _apply(
        client,
        model["id"],
        base_id,
        "process.update",
        {"process_id": "product", "changes": {"name": "Finished product"}},
    )
    assert response.status_code == 201, response.text
    applied = response.json()
    child = applied["revision"]
    assert child["parent_revision_id"] == base_id
    assert child["revision_number"] == 2
    assert applied["operation"]["target_kind"] == "process"
    assert applied["operation"]["target_id"] == "product"
    assert applied["operation"]["before_content_sha256"] != applied["operation"]["after_content_sha256"]

    base = client.get(f"/api/v1/system-revisions/{base_id}").json()
    base_product = next(node for node in base["graph_snapshot"]["nodes"] if node["id"] == "product")
    child_product = next(node for node in child["graph_snapshot"]["nodes"] if node["id"] == "product")
    assert base_product["name"] == "Product"
    assert child_product["name"] == "Finished product"


def test_revision_branching_and_connected_removal_guard(client):
    _, model = _create_model(client)
    base_id = model["upstream_receipt"]["base_revision_id"]

    first = _apply(
        client,
        model["id"],
        base_id,
        "system.merge_context",
        {"context": {"scenario": "efficiency"}},
    )
    second = _apply(
        client,
        model["id"],
        base_id,
        "system.merge_context",
        {"context": {"scenario": "electrification"}},
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["revision"]["parent_revision_id"] == base_id
    assert second.json()["revision"]["parent_revision_id"] == base_id
    assert {
        first.json()["revision"]["revision_number"],
        second.json()["revision"]["revision_number"],
    } == {2, 3}

    guarded = _apply(
        client,
        model["id"],
        base_id,
        "process.remove",
        {"process_id": "product"},
    )
    assert guarded.status_code == 422
    assert guarded.json()["error"]["code"] == "PROCESS_HAS_CONNECTED_EXCHANGES"


def test_scaled_revision_drives_mfa_and_preserves_base(client):
    _, model = _create_model(client)
    base_id = model["upstream_receipt"]["base_revision_id"]
    scaled_response = _apply(
        client,
        model["id"],
        base_id,
        "system.scale_flows",
        {"factor": 2, "unit_groups": ["Units of mass"]},
    )
    assert scaled_response.status_code == 201, scaled_response.text
    scaled = scaled_response.json()["revision"]

    run_response = client.post(
        f"/api/v1/system-models/{model['id']}/analysis-runs",
        json={
            "capability_key": "mfa.declared.v1",
            "system_revision_id": scaled["id"],
            "parameters": {},
        },
    )
    assert run_response.status_code == 201, run_response.text
    run = run_response.json()
    assert run["system_revision_id"] == scaled["id"]
    assert run["model_graph_sha256"] == scaled["graph_sha256"]
    assert run["provider_receipt"]["system_revision_id"] == scaled["id"]
    assert run["result"]["series"][0]["totals"] == {
        "internal_flow": 16.0,
        "boundary_in": 20.0,
        "boundary_out": 20.0,
    }

    base_run = client.post(
        f"/api/v1/system-models/{model['id']}/analysis-runs",
        json={
            "capability_key": "mfa.declared.v1",
            "system_revision_id": base_id,
            "parameters": {},
        },
    ).json()
    assert base_run["result"]["series"][0]["totals"]["internal_flow"] == 8.0


def test_invalid_flow_identity_is_rejected_without_revision(client):
    _, model = _create_model(client)
    base_id = model["upstream_receipt"]["base_revision_id"]
    invalid = _apply(
        client,
        model["id"],
        base_id,
        "flow.update_port",
        {
            "process_id": "product",
            "port_id": "material-in",
            "changes": {"flowUuid": "different-flow"},
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "FLOW_EXCHANGE_IDENTITY_MISMATCH"
    revisions = client.get(f"/api/v1/system-models/{model['id']}/revisions").json()
    assert [item["revision_number"] for item in revisions] == [1]


def test_exact_electricity_input_is_added_only_to_child_revision(client):
    _, model = _create_model(client)
    base_id = model["upstream_receipt"]["base_revision_id"]
    port = {
        "id": "electricity-cn-2022-in",
        "flowUuid": "3d76981f-964a-4865-b588-0e067a2a1163",
        "flowSourceNamespace": "tiangong_open_data",
        "flowVersion": "01.01.003",
        "flowPropertyUuid": "93a60a56-a3c8-11da-a746-0800200c9a66",
        "flowPropertyVersion": "03.00.003",
        "unitGroupUuid": "93a60a57-a3c8-11da-a746-0800200c9a66",
        "unitGroupVersion": "03.00.003",
        "name": "Electricity, CN 1-35 kV consumption mix",
        "unit": "MJ",
        "unitGroup": "Units of energy",
        "amount": 3.6,
        "type": "technosphere",
    }
    response = _apply(
        client,
        model["id"],
        base_id,
        "flow.add_port",
        {
            "process_id": "product",
            "port_group": "inputs",
            "port": port,
        },
    )
    assert response.status_code == 201, response.text
    created = response.json()
    child = created["revision"]
    assert child["parent_revision_id"] == base_id
    assert created["operation"]["target_id"] == "product/electricity-cn-2022-in"
    child_product = next(
        node for node in child["graph_snapshot"]["nodes"] if node["id"] == "product"
    )
    added = next(item for item in child_product["inputs"] if item["id"] == port["id"])
    assert added == {**port, "direction": "input"}

    base = client.get(f"/api/v1/system-revisions/{base_id}").json()
    base_product = next(
        node for node in base["graph_snapshot"]["nodes"] if node["id"] == "product"
    )
    assert all(item["id"] != port["id"] for item in base_product["inputs"])

    duplicate = _apply(
        client,
        model["id"],
        child["id"],
        "flow.add_port",
        {
            "process_id": "product",
            "port_group": "inputs",
            "port": port,
        },
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["error"]["code"] == "FLOW_PORT_ID_DUPLICATE"


def test_flow_disconnect_and_reconnect_are_explicit_revisions(client):
    _, model = _create_model(client)
    base_id = model["upstream_receipt"]["base_revision_id"]
    disconnected_response = _apply(
        client,
        model["id"],
        base_id,
        "flow.disconnect",
        {"exchange_id": "edge-material"},
    )
    assert disconnected_response.status_code == 201, disconnected_response.text
    disconnected = disconnected_response.json()["revision"]
    assert disconnected["graph_snapshot"]["exchanges"] == []

    exchange = {
        "id": "edge-material-restored",
        "fromNode": "preparation",
        "toNode": "product",
        "sourcePortId": "material-out",
        "targetPortId": "material-in",
        "flowUuid": "flow-material",
        "flowName": "material",
        "quantityMode": "single",
        "amount": 8,
        "providerAmount": 8,
        "consumerAmount": 8,
        "unit": "kg",
        "type": "technosphere",
    }
    reconnected_response = _apply(
        client,
        model["id"],
        disconnected["id"],
        "flow.connect",
        {"exchange": exchange},
    )
    assert reconnected_response.status_code == 201, reconnected_response.text
    reconnected = reconnected_response.json()
    assert reconnected["operation"]["target_kind"] == "flow"
    assert reconnected["operation"]["target_id"] == "edge-material-restored"
    assert reconnected["revision"]["graph_snapshot"]["exchanges"] == [exchange]


def test_publish_requires_confirmation_and_sends_exact_revision_graph(
    client, upstream_requests
):
    _, model = _create_model(client)
    base_id = model["upstream_receipt"]["base_revision_id"]
    child = _apply(
        client,
        model["id"],
        base_id,
        "system.set_functional_unit",
        {"functional_unit": "1 t product"},
    ).json()["revision"]

    refused = client.post(
        f"/api/v1/system-revisions/{child['id']}/publish",
        json={"confirm_upstream_write": False},
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "UPSTREAM_WRITE_CONFIRMATION_REQUIRED"

    published = client.post(
        f"/api/v1/system-revisions/{child['id']}/publish",
        json={"confirm_upstream_write": True, "compile_pts_on_save": False},
    )
    assert published.status_code == 200, published.text
    receipt = published.json()["publish_receipt"]
    assert receipt["project_id"] == "project-1"
    assert receipt["version"] == 4
    assert receipt["graph_sha256"] == child["graph_sha256"]

    request = next(
        item
        for item in upstream_requests
        if item["path"] == "/api/projects/project-1/versions"
    )
    assert request["query"] == "compile_pts_on_save=false"
    assert request["json"]["graph"]["functionalUnit"] == "1 t product"


def test_product_blueprint_exposes_composition_mechanism(client):
    response = client.get("/api/v1/product-blueprint")
    assert response.status_code == 200
    blueprint = response.json()
    assert [item["key"] for item in blueprint["core_objects"]] == [
        "flow",
        "process",
        "system",
    ]
    assert "flow.connect" in blueprint["operation_contracts"]
    change_layer = next(
        item
        for item in blueprint["analysis_layers"]
        if item["key"] == "change_and_comparison"
    )
    assert "parameter_binding.v1" in change_layer["current"]
    assert {item["key"] for item in blueprint["application_compositions"]} >= {
        "industrial_ecology_research",
        "product_footprint",
        "park_and_region",
        "cbam_and_carbon_market",
    }

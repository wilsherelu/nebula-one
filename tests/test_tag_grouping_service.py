from __future__ import annotations
from nebula_one.hashing import canonical_json_sha256

from nebula_one.hashing import canonical_graph_sha256
from nebula_one.runtime_models import SolvedSystemSnapshot

TAG_DIMENSION = {
    "id": "tag",
    "name": "CBAM",
    "categories": [
        {"id": "direct", "name": "Direct", "is_leaf": True},
        {"id": "indirect", "name": "Indirect", "is_leaf": True},
    ],
}


def _create_application(client, name: str) -> dict:
    response = client.post(
        "/api/v1/applications",
        json={
            "name": name,
            "application_type": "zero_carbon_park",
            "description": "tag grouping acceptance",
            "context": {"geography": "CN-SH"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _attach_inline_model(client, application_id: str, graph: dict) -> dict:
    response = client.post(
        f"/api/v1/applications/{application_id}/system-models/inline",
        json={
            "name": "Inline model",
            "provider": "nebula_lca",
            "source_id": "casepack:petrochemical-refinery-reference",
            "source_version": 1,
            "expected_graph_sha256": canonical_graph_sha256(graph),
            "graph": graph,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _setup(client, model_graph):
    # The acceptance model must actually contain the exchanges the API validates.
    from copy import deepcopy
    model_graph = deepcopy(model_graph)
    model_graph["nodes"][0]["emissions"] = [
        {"id": key, "name": key, "flowUuid": f"flow-{key}", "type": "elementary", "unit": "kg", "amount": 1.0}
        for key in ("co2", "ch4", "loose")
    ]
    application = _create_application(client, "Tag grouping fixture")
    system_model = _attach_inline_model(client, application["id"], model_graph)
    revision_id = system_model["upstream_receipt"]["base_revision_id"]
    response = client.get(f"/api/v1/system-revisions/{revision_id}")
    assert response.status_code == 200, response.text
    node_id = response.json()["graph_snapshot"]["nodes"][0]["id"]
    return application, revision_id, node_id


def _tag_rule(node_id: str, port: str, *, category: str = "direct", status: str = "selected") -> dict:
    return {
        "process_instance_id": node_id,
        "exchange_id": f"{node_id}::{port}",
        "direction": "emission",
        "boundary_status": status,
        "location_role": "other",
        "categories": {"tag": category},
    }


def _create_tag_scheme(
    client, application_id: str, revision_id: str, name: str, rules: list[dict], *, validate: bool = True
) -> dict:
    response = client.post(
        f"/api/v1/applications/{application_id}/calculation-methods",
        json={
            "name": name,
            "purpose": "custom",
            "model_revision_id": revision_id,
            "semantics": "flow_tag.v1",
            "reporting_dimensions": [TAG_DIMENSION],
            "rules": rules,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    method_id = body["method"]["id"]
    version = body["versions"][0]
    assert version["semantics"] == "flow_tag.v1"
    if validate:
        checked = client.post(
            f"/api/v1/calculation-methods/{method_id}/versions/1/validate"
        )
        assert checked.status_code == 200, checked.text
        assert checked.json()["valid"] is True, checked.text
        assert checked.json()["status"] == "ready"
    return {
        "method_id": method_id,
        "ref": {
            "method_id": method_id,
            "version": 1,
            "content_sha256": version["content_sha256"],
        },
    }


def _insert_snapshot(
    client,
    application_id: str,
    revision_id: str,
    *,
    scaled: list[dict],
    terms: list[dict],
    solve_hash: str,
    indicator_key: str = "climate",
    unit: str = "kg CO2e",
) -> str:
    lcia_results = {
        "path_weighted_contribution_receipts": [
            {
                "canonical_indicator_key": indicator_key,
                "indicator_unit": unit,
                "terms": terms,
            }
        ]
    }
    receipt = lcia_results["path_weighted_contribution_receipts"][0]
    receipt["content_hash"] = canonical_json_sha256(receipt)
    database = client.app.state.container.database
    with database.session() as db:
        snapshot = SolvedSystemSnapshot(
            application_id=application_id,
            system_revision_id=revision_id,
            solve_hash=solve_hash,
            provider="nebula_lca",
            provider_receipt={},
            functional_unit={"amount": 1, "unit": "kg"},
            database_release="test-release",
            solver_version="test-solver",
            activity_vector=[],
            scaled_technosphere_exchanges=[],
            scaled_elementary_exchanges=scaled,
            internal_transfers=[],
            boundary_flows=[],
            process_balance_residuals=[],
            contribution_graph={},
            lcia_results=lcia_results,
            content_sha256="a" * 64,
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)
        return snapshot.id


def _group(client, application_id: str, body: dict) -> dict:
    response = client.post(
        f"/api/v1/applications/{application_id}/tag-grouping", json=body
    )
    assert response.status_code == 200, response.text
    return response.json()


def _no_term_snapshot(client, application_id: str, revision_id: str) -> str:
    database = client.app.state.container.database
    with database.session() as db:
        snapshot = SolvedSystemSnapshot(
            application_id=application_id,
            system_revision_id=revision_id,
            solve_hash="n" * 64,
            provider="nebula_lca",
            provider_receipt={},
            functional_unit={"amount": 1, "unit": "kg"},
            database_release="test-release",
            solver_version="test-solver",
            activity_vector=[],
            scaled_technosphere_exchanges=[],
            scaled_elementary_exchanges=[],
            internal_transfers=[],
            boundary_flows=[],
            process_balance_residuals=[],
            contribution_graph={},
            lcia_results={},
            content_sha256="b" * 64,
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)
        return snapshot.id


def test_tag_scheme_must_be_validated_before_it_can_group(client, model_graph):
    application, revision_id, node_id = _setup(client, model_graph)
    scheme = _create_tag_scheme(
        client,
        application["id"],
        revision_id,
        "CBAM draft",
        [_tag_rule(node_id, "co2")],
        validate=False,
    )
    snapshot_id = _insert_snapshot(
        client,
        application["id"],
        revision_id,
        scaled=[{"exchange_id": f"{node_id}::co2", "direction": "emission"}],
        terms=[{"exchange_id": f"{node_id}::co2", "path_contribution_value": 10.0}],
        solve_hash="c" * 64,
    )
    response = client.post(
        f"/api/v1/applications/{application['id']}/tag-grouping",
        json={
            "snapshot_id": snapshot_id,
            "indicator_key": "climate",
            "schemes": [scheme["ref"]],
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "TAG_SCHEME_NOT_VALIDATED"


def test_tag_grouping_reads_the_frozen_pool_and_separates_outcomes(client, model_graph):
    application, revision_id, node_id = _setup(client, model_graph)
    scheme = _create_tag_scheme(
        client,
        application["id"],
        revision_id,
        "CBAM",
        [
            _tag_rule(node_id, "co2", category="direct"),
            _tag_rule(node_id, "ch4", category="indirect"),
        ],
    )
    snapshot_id = _insert_snapshot(
        client,
        application["id"],
        revision_id,
        scaled=[
            {"exchange_id": f"{node_id}::co2", "direction": "emission"},
            {"exchange_id": f"{node_id}::ch4", "direction": "emission"},
            {"exchange_id": f"{node_id}::loose", "direction": "emission"},
        ],
        terms=[
            {"exchange_id": f"{node_id}::co2", "path_contribution_value": 100.0},
            {"exchange_id": f"{node_id}::loose", "path_contribution_value": 7.0},
        ],
        solve_hash="d" * 64,
    )

    body = _group(
        client,
        application["id"],
        {"snapshot_id": snapshot_id, "indicator_key": "climate", "schemes": [scheme["ref"]]},
    )
    assert body["available"] is True
    assert body["semantics"] == "flow_tag.v1"
    assert body["indicator_unit"] == "kg CO2e"
    assert body["snapshot_content_sha256"] == "a" * 64
    assert body["content_sha256"]

    scheme_out = body["schemes"][0]
    assert scheme_out["scheme"]["method_id"] == scheme["method_id"]
    assert scheme_out["tag_total"]["value"] == 100.0
    assert scheme_out["dimension"]["categories"][0]["subtotal"] == 100.0
    # The tagged path the engine returned no value for is a gap, not a zero.
    assert scheme_out["missing"]["exchange_ids"] == [f"{node_id}::ch4"]
    # The untagged known value stays outside the tag and is reported with its value.
    assert f"{node_id}::loose" in scheme_out["unmatched"]["exchange_ids"]
    assert scheme_out["unmatched"]["known_value"] == 7.0
    assert scheme_out["coverage"]["complete"] is False


def test_tag_grouping_rejects_hash_semantics_and_revision_drift(client, model_graph):
    application, revision_id, node_id = _setup(client, model_graph)
    scheme = _create_tag_scheme(
        client, application["id"], revision_id, "Scope tag", [_tag_rule(node_id, "co2")]
    )
    snapshot_id = _insert_snapshot(
        client,
        application["id"],
        revision_id,
        scaled=[{"exchange_id": f"{node_id}::co2", "direction": "emission"}],
        terms=[{"exchange_id": f"{node_id}::co2", "path_contribution_value": 1.0}],
        solve_hash="e" * 64,
    )

    wrong_hash = dict(scheme["ref"], content_sha256="f" * 64)
    response = client.post(
        f"/api/v1/applications/{application['id']}/tag-grouping",
        json={"snapshot_id": snapshot_id, "indicator_key": "climate", "schemes": [wrong_hash]},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "TAG_SCHEME_HASH_MISMATCH"

    legacy = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json={
            "name": "Legacy scope",
            "purpose": "custom",
            "model_revision_id": revision_id,
            "rules": [_tag_rule(node_id, "co2")],
        },
    )
    assert legacy.status_code == 201, legacy.text
    legacy_body = legacy.json()
    legacy_ref = {
        "method_id": legacy_body["method"]["id"],
        "version": 1,
        "content_sha256": legacy_body["versions"][0]["content_sha256"],
    }
    response = client.post(
        f"/api/v1/applications/{application['id']}/tag-grouping",
        json={"snapshot_id": snapshot_id, "indicator_key": "climate", "schemes": [legacy_ref]},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "TAG_SCHEME_SEMANTICS_MISMATCH"

    other_revision_snapshot = _insert_snapshot(
        client,
        application["id"],
        "some-other-revision",
        scaled=[],
        terms=[],
        solve_hash="g" * 64,
    )
    response = client.post(
        f"/api/v1/applications/{application['id']}/tag-grouping",
        json={
            "snapshot_id": other_revision_snapshot,
            "indicator_key": "climate",
            "schemes": [scheme["ref"]],
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "TAG_SCHEME_REVISION_MISMATCH"


def test_multi_scheme_union_and_intersection_never_double_count(client, model_graph):
    application, revision_id, node_id = _setup(client, model_graph)
    scheme_a = _create_tag_scheme(
        client,
        application["id"],
        revision_id,
        "Scheme A",
        [_tag_rule(node_id, "co2", category="direct"), _tag_rule(node_id, "ch4")],
    )
    scheme_b = _create_tag_scheme(
        client,
        application["id"],
        revision_id,
        "Scheme B",
        [_tag_rule(node_id, "co2", category="direct")],
    )
    snapshot_id = _insert_snapshot(
        client,
        application["id"],
        revision_id,
        scaled=[
            {"exchange_id": f"{node_id}::co2", "direction": "emission"},
            {"exchange_id": f"{node_id}::ch4", "direction": "emission"},
        ],
        terms=[
            {"exchange_id": f"{node_id}::co2", "path_contribution_value": 100.0},
            {"exchange_id": f"{node_id}::ch4", "path_contribution_value": 30.0},
        ],
        solve_hash="h" * 64,
    )
    schemes = [scheme_a["ref"], scheme_b["ref"]]

    union = _group(
        client,
        application["id"],
        {
            "snapshot_id": snapshot_id,
            "indicator_key": "climate",
            "schemes": schemes,
            "mode": "union",
        },
    )
    assert [item["tag_total"]["value"] for item in union["schemes"]] == [130.0, 100.0]
    assert union["union"]["value"] == 130.0
    assert union["overlap"]["multi_scheme_term_count"] == 1

    intersection = _group(
        client,
        application["id"],
        {
            "snapshot_id": snapshot_id,
            "indicator_key": "climate",
            "schemes": schemes,
            "mode": "intersection",
        },
    )
    assert intersection["intersection"]["value"] == 100.0
    assert intersection["intersection"]["exchange_ids"] == [f"{node_id}::co2"]

    separate = _group(
        client,
        application["id"],
        {"snapshot_id": snapshot_id, "indicator_key": "climate", "schemes": schemes},
    )
    assert separate["union"] is None and separate["intersection"] is None
    assert len(separate["schemes"]) == 2


def test_snapshot_without_path_receipt_is_unavailable_not_zero(client, model_graph):
    application, revision_id, node_id = _setup(client, model_graph)
    scheme = _create_tag_scheme(
        client, application["id"], revision_id, "No receipt", [_tag_rule(node_id, "co2")]
    )
    snapshot_id = _no_term_snapshot(client, application["id"], revision_id)
    body = _group(
        client,
        application["id"],
        {"snapshot_id": snapshot_id, "indicator_key": "climate", "schemes": [scheme["ref"]]},
    )
    assert body["available"] is False
    assert body["reason"] == "PATH_WEIGHTED_RECEIPT_MISSING"
    assert body["schemes"] == []
    assert body["content_sha256"]


def test_capabilities_declare_a_tag_scheme_needs_no_processing_package(client, model_graph):
    application, revision_id, node_id = _setup(client, model_graph)
    scheme = _create_tag_scheme(
        client, application["id"], revision_id, "CBAM", [_tag_rule(node_id, "co2")]
    )
    response = client.get(
        f"/api/v1/calculation-methods/{scheme['method_id']}/capabilities"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tag_scheme"] is True
    assert body["tag_grouping"] is True
    assert body["processing_package_selection"] is False
    assert body["processing_package_reason"]["code"] == "CALCULATION_METHOD_TAG_NO_PROCESSING_PACKAGE"

    packages = client.get(
        f"/api/v1/calculation-methods/{scheme['method_id']}/selectable-processing-packages"
    )
    assert packages.status_code == 422, packages.text
    assert packages.json()["error"]["code"] == "CALCULATION_METHOD_TAG_NO_PROCESSING_PACKAGE"


def test_capabilities_report_an_unbound_template_instead_of_raising(client, model_graph):
    application, revision_id, node_id = _setup(client, model_graph)
    boundary = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json={
            # A formal-purpose method (not a pre-caliber custom one) so the answer under test is the
            # missing template binding, not the legacy read-only capability.
            "name": "Unbound boundary",
            "purpose": "pcf",
            "model_revision_id": revision_id,
            "rules": [_tag_rule(node_id, "co2")],
        },
    )
    assert boundary.status_code == 201, boundary.text
    method_id = boundary.json()["method"]["id"]

    response = client.get(f"/api/v1/calculation-methods/{method_id}/capabilities")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tag_scheme"] is False
    assert body["processing_package_selection"] is False
    assert body["processing_package_reason"]["code"] == "MODEL_PROCESSING_TEMPLATE_UNBOUND"

    packages = client.get(
        f"/api/v1/calculation-methods/{method_id}/selectable-processing-packages"
    )
    assert packages.status_code == 409, packages.text
    assert packages.json()["error"]["code"] == "MODEL_PROCESSING_TEMPLATE_UNBOUND"


def test_archived_scheme_stops_grouping_new_results(client, model_graph):
    application, revision_id, node_id = _setup(client, model_graph)
    scheme = _create_tag_scheme(
        client, application["id"], revision_id, "Archived tag scheme", [_tag_rule(node_id, "co2")]
    )
    snapshot_id = _insert_snapshot(
        client,
        application["id"],
        revision_id,
        scaled=[{"exchange_id": f"{node_id}::co2", "direction": "emission"}],
        terms=[{"exchange_id": f"{node_id}::co2", "path_contribution_value": 12.0}],
        solve_hash="e" * 64,
    )

    archived = client.post(f"/api/v1/calculation-methods/{scheme['method_id']}/archive")
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "retired"

    refused = client.post(
        f"/api/v1/applications/{application['id']}/tag-grouping",
        json={"snapshot_id": snapshot_id, "indicator_key": "climate", "schemes": [scheme["ref"]]},
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "TAG_SCHEME_ARCHIVED"

    # Archiving never deletes the scheme: its versions remain readable for historical results.
    version = client.get(f"/api/v1/calculation-methods/{scheme['method_id']}/versions/1")
    assert version.status_code == 200
    assert version.json()["content_sha256"] == scheme["ref"]["content_sha256"]


def test_frozen_tag_result_survives_rename_archive_and_service_restart(client, model_graph):
    application, revision_id, node_id = _setup(client, model_graph)
    scheme = _create_tag_scheme(client, application["id"], revision_id, "Original tag", [_tag_rule(node_id, "co2")])
    snapshot_id = _insert_snapshot(client, application["id"], revision_id,
                                   scaled=[{"exchange_id": f"{node_id}::co2", "direction": "emission"}],
                                   terms=[{"exchange_id": f"{node_id}::co2", "path_contribution_value": 12.0}], solve_hash="z" * 64)
    payload = {"snapshot_id": snapshot_id, "indicator_key": "climate", "schemes": [scheme["ref"]]}
    first = _group(client, application["id"], payload)
    assert first["result_id"]
    assert _group(client, application["id"], payload) == first
    detail = client.get(f"/api/v1/calculation-methods/{scheme['method_id']}").json()
    saved = client.put(f"/api/v1/calculation-methods/{scheme['method_id']}/versions/1", json={
        "name": "Renamed tag", "rules": detail["versions"][0]["rules"],
        "reporting_dimensions": [TAG_DIMENSION], "expected_content_sha256": scheme["ref"]["content_sha256"],
    })
    # A legacy caliber is replay-only: its frozen result stays as-is, and edits go through conversion.
    assert saved.status_code == 409
    assert saved.json()["error"]["code"] == "CALCULATION_METHOD_LEGACY_READ_ONLY"
    preview = client.get(
        f"/api/v1/calculation-methods/{scheme['method_id']}/versions/1/conversion-preview"
    ).json()
    assert preview["can_convert"] is True
    assert preview["counts"]["assigned"] == 1
    converted = client.post(
        f"/api/v1/calculation-methods/{scheme['method_id']}/versions/1/convert",
        json={"name": "Converted tag"},
    )
    assert converted.status_code == 201, converted.text
    converted_method = converted.json()["method"]
    converted_version = converted.json()["versions"][0]
    assert converted_version["semantics"] == "result_category.v1"
    assert converted_method["id"] != scheme["method_id"]
    checked = client.post(
        f"/api/v1/calculation-methods/{converted_method['id']}/versions/1/validate"
    )
    assert checked.status_code == 200 and checked.json()["valid"] is True, checked.text
    saved = client.put(f"/api/v1/calculation-methods/{converted_method['id']}/versions/1", json={
        "name": "Renamed tag", "rules": converted_version["rules"],
        "reporting_dimensions": [TAG_DIMENSION], "expected_content_sha256": converted_version["content_sha256"],
    })
    assert saved.status_code == 200, saved.text
    assert client.post(f"/api/v1/calculation-methods/{scheme['method_id']}/archive").status_code == 200
    from nebula_one.services.tag_grouping import TagGroupingService
    client.app.state.container.tag_grouping = TagGroupingService(client.app.state.container.database)
    url = f"/api/v1/applications/{application['id']}/tag-grouping-results/{first['result_id']}"
    assert client.get(url).json() == first
    exported = client.get(url + "/export?format=json")
    assert exported.status_code == 200 and exported.json() == first
    html = client.get(url + "/export?format=html")
    assert html.status_code == 200 and "Original tag" in html.text and "Renamed tag" not in html.text
    other = _create_application(client, "Other account scope")
    assert client.get(url.replace(application["id"], other["id"])).status_code == 404
    assert client.get(f"/api/v1/applications/{application['id']}/tag-grouping-results", params={"snapshot_id": snapshot_id}).json() == [first]


def test_tag_validation_rejects_fabricated_exchange_and_pending_match(client, model_graph):
    application, revision_id, node_id = _setup(client, model_graph)
    for suffix, rule, code in [
        ("absent", _tag_rule(node_id, "imaginary"), "CALCULATION_METHOD_TAG_EXCHANGE_NOT_FOUND"),
        ("pending", _tag_rule(node_id, "co2", status="pending"), "CALCULATION_METHOD_TAG_MATCH_PENDING"),
        ("direction", dict(_tag_rule(node_id, "co2"), direction="input"), "CALCULATION_METHOD_TAG_IDENTITY_MISMATCH"),
    ]:
        scheme = _create_tag_scheme(client, application["id"], revision_id, suffix, [rule], validate=False)
        result = client.post(f"/api/v1/calculation-methods/{scheme['method_id']}/versions/1/validate").json()
        assert not result["valid"]
        assert code in {item["code"] for item in result["problems"]}


def test_grouping_rejects_stored_scheme_tampering(client, model_graph):
    application, revision_id, node_id = _setup(client, model_graph)
    scheme = _create_tag_scheme(client, application["id"], revision_id, "Pinned", [_tag_rule(node_id, "co2")])
    snapshot_id = _insert_snapshot(client, application["id"], revision_id, scaled=[], terms=[], solve_hash="t" * 64)
    from sqlalchemy import select
    from nebula_one.runtime_models import CalculationMethodVersion
    with client.app.state.container.database.session() as db:
        version = db.scalar(select(CalculationMethodVersion).where(CalculationMethodVersion.method_id == scheme["method_id"]))
        version.rules = []
        db.commit()
    response = client.post(f"/api/v1/applications/{application['id']}/tag-grouping", json={
        "snapshot_id": snapshot_id, "indicator_key": "climate", "schemes": [scheme["ref"]]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TAG_SCHEME_CONTENT_CORRUPT"


def test_full_coverage_includes_unlinked_purchased_inputs_but_not_internal_transfer(client, model_graph):
    application, revision_id, node_id = _setup(client, model_graph)
    response = client.post(f"/api/v1/applications/{application['id']}/calculation-methods", json={
        "name": "Full inventory", "purpose": "custom", "model_revision_id": revision_id,
        "semantics": "flow_tag.v1", "reporting_dimensions": [dict(TAG_DIMENSION, requires_full_coverage=True)],
        "rules": [_tag_rule(node_id, key) for key in ("co2", "ch4", "loose")],
    })
    assert response.status_code == 201, response.text
    method_id = response.json()["method"]["id"]
    checked = client.post(f"/api/v1/calculation-methods/{method_id}/versions/1/validate").json()
    assert checked["valid"] is False
    uncovered = next(row for row in checked["problems"] if row["code"] == "CALCULATION_METHOD_TAG_FLOW_UNMATCHED")
    assert f"{node_id}::ore-in" in uncovered["exchange_ids"]
    assert "product::material-in" not in uncovered["exchange_ids"]


def test_pre_result_category_frozen_record_keeps_its_shape_and_hash_on_every_api(client, model_graph):
    from copy import deepcopy
    from nebula_one.runtime_models import TagGroupingResult

    application, revision_id, node_id = _setup(client, model_graph)
    scheme = _create_tag_scheme(client, application["id"], revision_id, "Historical tag", [_tag_rule(node_id, "co2")])
    snapshot_id = _insert_snapshot(
        client, application["id"], revision_id,
        scaled=[{"exchange_id": f"{node_id}::co2", "direction": "emission"}],
        terms=[{"exchange_id": f"{node_id}::co2", "path_contribution_value": 12.0}],
        solve_hash="old-shape" * 8,
    )
    payload = {"snapshot_id": snapshot_id, "indicator_key": "climate", "schemes": [scheme["ref"]]}
    created = _group(client, application["id"], payload)
    database = client.app.state.container.database
    with database.session() as db:
        record = db.get(TagGroupingResult, created["result_id"])
        historical = deepcopy(record.result)
        for item in historical["schemes"]:
            # These fields did not exist in the public frozen shape before result_category.v1.
            item.pop("semantics")
            item.pop("populated")
        historical.pop("content_sha256")
        historical["content_sha256"] = canonical_json_sha256(historical)
        record.result = historical
        record.content_sha256 = historical["content_sha256"]
        db.commit()

    expected = {**historical, "result_id": created["result_id"], "created_at": created["created_at"]}
    base = f"/api/v1/applications/{application['id']}/tag-grouping-results"
    detail = client.get(f"{base}/{created['result_id']}")
    listed = client.get(base, params={"snapshot_id": snapshot_id})
    exported = client.get(f"{base}/{created['result_id']}/export?format=json")
    replayed = _group(client, application["id"], payload)
    assert detail.status_code == listed.status_code == exported.status_code == 200
    assert listed.json() == [expected]
    for result in (detail.json(), exported.json(), replayed):
        assert result == expected
        basis = {key: value for key, value in result.items()
                 if key not in {"result_id", "created_at", "content_sha256"}}
        assert canonical_json_sha256(basis) == historical["content_sha256"]
        assert "semantics" not in result["schemes"][0]
        assert "populated" not in result["schemes"][0]
    html = client.get(f"{base}/{created['result_id']}/export?format=html")
    assert html.status_code == 200
    assert "标签归集结果" in html.text and "已匹配贡献小计：12.0" in html.text
    with database.session() as db:
        assert db.get(TagGroupingResult, created["result_id"]).result == historical

from __future__ import annotations

from types import SimpleNamespace

from nebula_one.analysis.tag_grouping import (
    RESULT_CATEGORY_SEMANTICS,
    group_tag_scheme,
    group_tag_schemes,
)
from nebula_one.hashing import canonical_graph_sha256, canonical_json_sha256
from nebula_one.exports.tag_grouping import render_tag_grouping_html
from nebula_one.runtime_models import SolvedSystemSnapshot
from nebula_one.services.calculation_methods import CalculationMethodService

DIMENSION = {
    "id": "caliber",
    "name": "范围1–3",
    "categories": [
        {"id": "direct", "name": "直接排放", "parent_id": "all", "is_leaf": True},
        {"id": "indirect", "name": "间接排放", "parent_id": "all", "is_leaf": True},
        {"id": "all", "name": "全部", "is_leaf": False},
    ],
}


def _exchange(exchange_id: str, *, process_id: str) -> dict:
    return {
        "exchange_id": exchange_id,
        "process_id": process_id,
        "direction": "emission",
        "exchange_type": "elementary",
    }


def _rule(
    process_id: str,
    exchange_id: str,
    category: str | None,
    *,
    dimension: str = "caliber",
    location: str = "other",
) -> dict:
    return {
        "process_instance_id": process_id,
        "exchange_id": exchange_id,
        "direction": "emission",
        "location_role": location,
        "categories": {dimension: category} if category else {},
    }


def _create_application(client, name: str) -> dict:
    response = client.post(
        "/api/v1/applications",
        json={
            "name": name,
            "application_type": "zero_carbon_park",
            "description": "result category acceptance",
            "context": {"geography": "CN-SH"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _setup(client, model_graph):
    from copy import deepcopy

    graph = deepcopy(model_graph)
    graph["nodes"][0]["emissions"] = [
        {"id": key, "name": key, "flowUuid": f"flow-{key}", "type": "elementary", "unit": "kg", "amount": 1.0}
        for key in ("co2", "ch4")
    ]
    application = _create_application(client, f"Result category fixture {graph['nodes'][0]['id']}")
    created = client.post(
        f"/api/v1/applications/{application['id']}/system-models/inline",
        json={
            "name": "Inline model",
            "provider": "nebula_lca",
            "source_id": "casepack:petrochemical-refinery-reference",
            "source_version": 1,
            "expected_graph_sha256": canonical_graph_sha256(graph),
            "graph": graph,
        },
    )
    assert created.status_code == 201, created.text
    revision_id = created.json()["upstream_receipt"]["base_revision_id"]
    revision = client.get(f"/api/v1/system-revisions/{revision_id}").json()
    return application, revision_id, revision["graph_snapshot"]["nodes"][0]["id"]


def _create_caliber(client, application_id, revision_id, name, rules, *, semantics="result_category.v1", dimensions=None, validate=True):
    response = client.post(
        f"/api/v1/applications/{application_id}/calculation-methods",
        json={
            "name": name,
            "purpose": "custom",
            "model_revision_id": revision_id,
            "semantics": semantics,
            "reporting_dimensions": [DIMENSION] if dimensions is None else dimensions,
            "rules": rules,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    method_id = body["method"]["id"]
    version = body["versions"][0]
    assert version["semantics"] == semantics
    if validate:
        checked = client.post(f"/api/v1/calculation-methods/{method_id}/versions/1/validate")
        assert checked.status_code == 200, checked.text
        assert checked.json()["valid"] is True, checked.text
        assert checked.json()["status"] == "ready"
    return {
        "method_id": method_id,
        "ref": {"method_id": method_id, "version": 1, "content_sha256": version["content_sha256"]},
        "version": version,
    }


def _insert_snapshot(client, application_id, revision_id, *, scaled, terms, solve_hash):
    lcia_results = {
        "path_weighted_contribution_receipts": [
            {"canonical_indicator_key": "climate", "indicator_unit": "kg CO2e", "terms": terms}
        ]
    }
    receipt = lcia_results["path_weighted_contribution_receipts"][0]
    receipt["content_hash"] = canonical_json_sha256(receipt)
    with client.app.state.container.database.session() as db:
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


def _group(client, application_id, snapshot_id, refs, mode="separate"):
    response = client.post(
        f"/api/v1/applications/{application_id}/tag-grouping",
        json={"snapshot_id": snapshot_id, "indicator_key": "climate", "schemes": refs, "mode": mode},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_only_a_leaf_assignment_enters_the_caliber():
    scaled = [_exchange("p1::co2", process_id="p1"), _exchange("p1::ch4", process_id="p1")]
    terms = [
        {"exchange_id": "p1::co2", "contribution_value": 100.0},
        {"exchange_id": "p1::ch4", "contribution_value": 30.0},
    ]
    rules = [_rule("p1", "p1::co2", "direct")]
    grouped = group_tag_scheme(
        rules=rules,
        scaled_exchanges=scaled,
        weighted_terms=terms,
        dimension=DIMENSION,
        indicator_unit="kg CO2e",
        semantics=RESULT_CATEGORY_SEMANTICS,
    )
    assert grouped["semantics"] == RESULT_CATEGORY_SEMANTICS
    assert grouped["tag_total"]["value"] == 100.0
    assert grouped["unmatched"]["known_value"] == 30.0
    assert grouped["unmatched"]["term_count"] == 1
    assert grouped["pending"]["term_count"] == 0
    assert grouped["uncategorized"]["subtotal"] == 0.0
    assert grouped["populated"] is True
    assert {row["id"]: row["subtotal"] for row in grouped["dimension"]["categories"]}["all"] == 100.0

    rules.append(_rule("p1", "p1::ch4", "indirect"))
    grouped = group_tag_scheme(
        rules=rules,
        scaled_exchanges=scaled,
        weighted_terms=terms,
        dimension=DIMENSION,
        indicator_unit="kg CO2e",
        semantics=RESULT_CATEGORY_SEMANTICS,
    )
    # Parent rolls up its leaves once; the two leaves still total the same 130.
    assert grouped["tag_total"]["value"] == 130.0
    assert grouped["unmatched"]["known_value"] is None
    rows = {row["id"]: row for row in grouped["dimension"]["categories"]}
    assert rows["direct"]["subtotal"] == 100.0
    assert rows["indirect"]["subtotal"] == 30.0
    assert rows["all"]["subtotal"] == 130.0
    assert rows["all"]["is_leaf"] is False
    assert grouped["reconciled"] is True


def test_rule_without_a_leaf_is_a_problem_not_an_implicit_match():
    grouped = group_tag_scheme(
        rules=[_rule("p1", "p1::co2", None), _rule("p1", "p1::ch4", "all")],
        scaled_exchanges=[_exchange("p1::co2", process_id="p1"), _exchange("p1::ch4", process_id="p1")],
        weighted_terms=[
            {"exchange_id": "p1::co2", "contribution_value": 10.0},
            {"exchange_id": "p1::ch4", "contribution_value": 20.0},
        ],
        dimension=DIMENSION,
        indicator_unit="kg CO2e",
        semantics=RESULT_CATEGORY_SEMANTICS,
    )
    assert grouped["tag_total"]["value"] is None
    assert grouped["populated"] is False
    assert grouped["unmatched"]["known_value"] == 30.0
    assert {problem["code"] for problem in grouped["problems"]} == {"TAG_SCHEME_CATEGORY_INVALID"}
    assert grouped["reconciled"] is False


def test_caliber_api_groups_hundred_and_thirty_then_one_hundred_thirty(client, model_graph):
    application, revision_id, node = _setup(client, model_graph)
    first = _create_caliber(
        client, application["id"], revision_id, "范围1–3",
        [_rule(node, f"{node}::co2", "direct")],
    )
    snapshot_id = _insert_snapshot(
        client,
        application["id"],
        revision_id,
        scaled=[{"exchange_id": f"{node}::co2", "direction": "emission"},
                {"exchange_id": f"{node}::ch4", "direction": "emission"}],
        terms=[{"exchange_id": f"{node}::co2", "path_contribution_value": 100.0},
               {"exchange_id": f"{node}::ch4", "path_contribution_value": 30.0}],
        solve_hash="r" * 64,
    )
    grouped = _group(client, application["id"], snapshot_id, [first["ref"]])
    scheme = grouped["schemes"][0]
    assert grouped["semantics"] == RESULT_CATEGORY_SEMANTICS
    assert scheme["semantics"] == RESULT_CATEGORY_SEMANTICS
    assert scheme["tag_total"]["value"] == 100.0
    assert scheme["unmatched"]["known_value"] == 30.0
    assert scheme["populated"] is True

    detail = client.get(f"/api/v1/calculation-methods/{first['method_id']}").json()
    saved = client.put(
        f"/api/v1/calculation-methods/{first['method_id']}/versions/1",
        json={
            "name": "范围1–3",
            "rules": [
                _rule(node, f"{node}::co2", "direct"),
                _rule(node, f"{node}::ch4", "indirect"),
            ],
            "reporting_dimensions": [DIMENSION],
            "semantics": RESULT_CATEGORY_SEMANTICS,
            "expected_content_sha256": first["ref"]["content_sha256"],
        },
    )
    assert saved.status_code == 200, saved.text
    second_version = next(item for item in saved.json()["versions"] if item["version"] == 2)
    assert second_version["rules"][0]["boundary_status"] == "selected"
    checked = client.post(f"/api/v1/calculation-methods/{first['method_id']}/versions/2/validate")
    assert checked.json()["valid"] is True, checked.text
    ref2 = {"method_id": first["method_id"], "version": 2, "content_sha256": second_version["content_sha256"]}
    grouped = _group(client, application["id"], snapshot_id, [ref2])
    assert grouped["schemes"][0]["tag_total"]["value"] == 130.0
    assert grouped["schemes"][0]["dimension"]["categories"][-1]["subtotal"] == 130.0

    # The frozen v1 view is untouched by the later version.
    assert detail["versions"][0]["content_sha256"] == first["ref"]["content_sha256"]
    replay = _group(client, application["id"], snapshot_id, [first["ref"]])
    assert replay["schemes"][0]["tag_total"]["value"] == 100.0


def test_api_rejects_unclassified_parent_unknown_and_scope_assignments(client, model_graph):
    application, revision_id, node = _setup(client, model_graph)
    cases = [
        ([_rule(node, f"{node}::co2", None)], "CALCULATION_METHOD_RESULT_CATEGORY_REQUIRED"),
        ([_rule(node, f"{node}::co2", "all")], "CALCULATION_METHOD_RESULT_CATEGORY_NOT_LEAF"),
        ([_rule(node, f"{node}::co2", "ghost")], "CALCULATION_METHOD_RESULT_CATEGORY_UNKNOWN"),
        ([_rule(node, f"{node}::co2", "direct", dimension="other")], "CALCULATION_METHOD_RESULT_CATEGORY_CATEGORY_DIMENSION"),
        ([dict(_rule(node, f"{node}::co2", "direct"), scope="scope_1")], "CALCULATION_METHOD_RESULT_CATEGORY_SCOPE_NOT_ALLOWED"),
        ([dict(_rule(node, f"{node}::co2", "direct"), boundary="exclude")], "CALCULATION_METHOD_RESULT_CATEGORY_BOUNDARY_NOT_ALLOWED"),
    ]
    for index, (rules, code) in enumerate(cases):
        response = client.post(
            f"/api/v1/applications/{application['id']}/calculation-methods",
            json={
                "name": f"Invalid {index}",
                "purpose": "custom",
                "model_revision_id": revision_id,
                "semantics": RESULT_CATEGORY_SEMANTICS,
                "reporting_dimensions": [DIMENSION],
                "rules": rules,
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == code, response.text

    duplicate = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json={
            "name": "Duplicate",
            "purpose": "custom",
            "model_revision_id": revision_id,
            "semantics": RESULT_CATEGORY_SEMANTICS,
            "reporting_dimensions": [DIMENSION],
            "rules": [_rule(node, f"{node}::co2", "direct"), _rule(node, f"{node}::co2", "indirect")],
        },
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["error"]["code"] == "CALCULATION_METHOD_RULE_DUPLICATE"


def test_empty_caliber_is_not_a_zero_result(client, model_graph):
    application, revision_id, node = _setup(client, model_graph)
    empty_dimension = {"id": "caliber", "name": "碳市场", "categories": [{"id": "履约", "name": "履约", "is_leaf": True}]}
    scheme = _create_caliber(client, application["id"], revision_id, "碳市场", [], dimensions=[empty_dimension])
    snapshot_id = _insert_snapshot(
        client,
        application["id"],
        revision_id,
        scaled=[{"exchange_id": f"{node}::co2", "direction": "emission"}],
        terms=[{"exchange_id": f"{node}::co2", "path_contribution_value": 12.0}],
        solve_hash="e" * 64,
    )
    grouped = _group(client, application["id"], snapshot_id, [scheme["ref"]])
    body = grouped["schemes"][0]
    assert grouped["available"] is True
    assert body["populated"] is False
    assert body["tag_total"]["value"] is None
    assert body["unmatched"]["known_value"] == 12.0
    # Declared categories stay listed, but without a contribution they carry no zero subtotal.
    assert [(row["id"], row["subtotal"]) for row in body["dimension"]["categories"]] == [("履约", None)]
    assert body["matched"]["term_count"] == 0


def test_two_calibers_share_a_flow_without_double_counting(client, model_graph):
    application, revision_id, node = _setup(client, model_graph)
    cbam = _create_caliber(client, application["id"], revision_id, "CBAM", [_rule(node, f"{node}::co2", "direct")])
    scope = _create_caliber(
        client, application["id"], revision_id, "范围1–3",
        [_rule(node, f"{node}::co2", "direct"), _rule(node, f"{node}::ch4", "indirect")],
    )
    snapshot_id = _insert_snapshot(
        client,
        application["id"],
        revision_id,
        scaled=[{"exchange_id": f"{node}::co2", "direction": "emission"},
                {"exchange_id": f"{node}::ch4", "direction": "emission"}],
        terms=[{"exchange_id": f"{node}::co2", "path_contribution_value": 100.0},
               {"exchange_id": f"{node}::ch4", "path_contribution_value": 30.0}],
        solve_hash="u" * 64,
    )
    refs = [cbam["ref"], scope["ref"]]
    union = _group(client, application["id"], snapshot_id, refs, mode="union")
    assert union["schemes"][0]["tag_total"]["value"] == 100.0
    assert union["schemes"][1]["tag_total"]["value"] == 130.0
    assert union["union"]["value"] == 130.0
    assert union["union"]["value"] != 230.0
    intersection = _group(client, application["id"], snapshot_id, refs, mode="intersection")
    assert intersection["intersection"]["value"] == 100.0
    assert intersection["intersection"]["exchange_ids"] == [f"{node}::co2"]


def test_conversion_preview_maps_every_legacy_outcome():
    method = SimpleNamespace(id="m1", name="Legacy", purpose="custom")
    record = SimpleNamespace(
        version=3,
        semantics="flow_tag.v1",
        content_sha256="c" * 64,
        cbam_boundary_ref=None,
        model_processing_rules_ref=None,
        reporting_dimensions=[DIMENSION],
        rules=[
            dict(_rule("p1", "p1::co2", "direct"), boundary_status="selected"),
            dict(_rule("p1", "p1::ch4", None), boundary_status="selected"),
            dict(_rule("p1", "p1::n2o", "direct"), boundary_status="pending"),
            dict(_rule("p1", "p1::co", "direct"), boundary_status="excluded"),
            dict(_rule("p1", "p1::pm", "ghost"), boundary_status="selected"),
        ],
    )
    preview, target, dimension = CalculationMethodService._conversion_plan(method, record)
    # An invalid legacy category blocks the copy instead of silently becoming “无”.
    assert preview["can_convert"] is False
    assert preview["reason"]["code"] == "TAG_SCHEME_CONVERSION_UNRESOLVED_MAPPING"
    assert preview["counts"] == {
        "total": 5,
        "assigned": 1,
        "selected_without_category": 1,
        "pending": 1,
        "excluded": 1,
        "invalid_category": 1,
        "unresolved_invalid": 1,
        "resolved_without_category": 0,
    }
    outcomes = [row["outcome"] for row in preview["rules"]]
    assert outcomes == ["assigned", "unassigned", "unassigned", "unassigned", "invalid_category"]
    assert preview["rules"][1]["new_category"] is None
    assert preview["rules"][3]["old_category"] == "direct"
    assert preview["rules"][4]["needs_resolution"] is True
    assert preview["rules"][4]["resolved"] is False
    assert dimension["id"] == "caliber"
    assert [rule["exchange_id"] for rule in target] == ["p1::co2"]
    assert preview["mapping_sha256"]


def test_invalid_legacy_category_blocks_conversion_until_remapped(client, model_graph):
    application, revision_id, node = _setup(client, model_graph)
    legacy = _create_caliber(
        client, application["id"], revision_id, "Ghost tag",
        [dict(_rule(node, f"{node}::co2", "ghost"), boundary_status="selected")],
        semantics="flow_tag.v1", validate=False,
    )
    base = f"/api/v1/calculation-methods/{legacy['method_id']}/versions/1"
    blocked = client.post(f"{base}/convert", json={"name": "Ghost result"})
    assert blocked.status_code == 422, blocked.text
    assert blocked.json()["error"]["code"] == "TAG_SCHEME_CONVERSION_UNRESOLVED_MAPPING"

    preview = client.get(f"{base}/conversion-preview").json()
    assert preview["can_convert"] is False
    assert preview["counts"]["invalid_category"] == 1
    assert preview["counts"]["unresolved_invalid"] == 1

    # The reader may keep the flow out of the caliber, but only by choosing “无” explicitly.
    without = client.post(f"{base}/conversion-preview", json={
        "resolutions": [{"rule_index": 0, "category": None}],
    }).json()
    assert without["can_convert"] is True
    assert without["counts"]["resolved_without_category"] == 1
    assert without["counts"]["assigned"] == 0

    remapped = client.post(f"{base}/conversion-preview", json={
        "resolutions": [{"rule_index": 0, "category": "indirect"}],
    }).json()
    assert remapped["can_convert"] is True
    assert remapped["rules"][0]["new_category"] == "indirect"
    assert remapped["rules"][0]["resolved"] is True
    # The dialog keys its mapping decisions by rule_index, so the POST preview must keep it.
    assert [rule["rule_index"] for rule in remapped["rules"]] == [0]

    stale = client.post(f"{base}/convert", json={
        "name": "Ghost result",
        "resolutions": [{"rule_index": 0, "category": "indirect"}],
        "expected_mapping_sha256": "0" * 64,
    })
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "TAG_SCHEME_CONVERSION_MAPPING_CHANGED"

    converted = client.post(f"{base}/convert", json={
        "name": "Ghost result",
        "resolutions": [{"rule_index": 0, "category": "indirect"}],
        "expected_mapping_sha256": remapped["mapping_sha256"],
    })
    assert converted.status_code == 201, converted.text
    new_version = converted.json()["versions"][0]
    assert [rule["categories"] for rule in new_version["rules"]] == [{"caliber": "indirect"}]
    # The source keeps the invalid legacy category and its exact bytes.
    source = client.get(f"/api/v1/calculation-methods/{legacy['method_id']}").json()
    assert source["versions"][0]["content_sha256"] == legacy["ref"]["content_sha256"]
    assert source["versions"][0]["rules"][0]["categories"] == {"caliber": "ghost"}


def test_legacy_ordinary_method_is_read_only_and_convertible(client, model_graph):
    application, revision_id, node = _setup(client, model_graph)
    legacy = _create_caliber(
        client, application["id"], revision_id, "Old ordinary",
        [
            dict(_rule(node, f"{node}::co2", "direct", location="onsite"),
                 boundary_status="selected", scope="scope_1"),
            dict(_rule(node, f"{node}::ch4", "direct", location="onsite"),
                 boundary_status="selected", scope="scope_1"),
            dict(_rule(node, f"{node}::n2o", "direct", location="purchased_energy"),
                 boundary_status="excluded", scope="scope_2"),
        ],
        semantics=None,
    )
    capabilities = client.get(
        f"/api/v1/calculation-methods/{legacy['method_id']}/capabilities"
    ).json()
    assert capabilities["legacy_method"] is True
    assert capabilities["legacy_tag_scheme"] is False
    assert capabilities["result_category"] is False
    assert capabilities["conversion_available"] is True
    assert capabilities["processing_package_selection"] is False
    assert (
        capabilities["processing_package_reason"]["code"]
        == "CALCULATION_METHOD_LEGACY_METHOD_NO_PROCESSING_PACKAGE"
    )

    detail = client.get(f"/api/v1/calculation-methods/{legacy['method_id']}").json()
    saved = client.put(
        f"/api/v1/calculation-methods/{legacy['method_id']}/versions/1",
        json={
            "name": "Old ordinary renamed",
            "rules": detail["versions"][0]["rules"],
            "reporting_dimensions": [DIMENSION],
            "expected_content_sha256": legacy["ref"]["content_sha256"],
        },
    )
    assert saved.status_code == 409
    assert saved.json()["error"]["code"] == "CALCULATION_METHOD_LEGACY_READ_ONLY"
    cloned = client.post(
        f"/api/v1/calculation-methods/{legacy['method_id']}/versions/1/clone",
        json={"name": "Clone", "purpose": "custom", "model_revision_id": revision_id},
    )
    assert cloned.status_code == 409
    assert cloned.json()["error"]["code"] == "CALCULATION_METHOD_LEGACY_READ_ONLY"

    preview = client.get(
        f"/api/v1/calculation-methods/{legacy['method_id']}/versions/1/conversion-preview"
    ).json()
    assert preview["source_semantics"] is None
    assert preview["can_convert"] is True
    assert preview["counts"]["assigned"] == 2
    assert preview["counts"]["excluded"] == 1

    converted = client.post(
        f"/api/v1/calculation-methods/{legacy['method_id']}/versions/1/convert",
        json={"name": "Old ordinary result"},
    )
    assert converted.status_code == 201, converted.text
    new_version = converted.json()["versions"][0]
    assert new_version["semantics"] == RESULT_CATEGORY_SEMANTICS
    assert {rule["exchange_id"] for rule in new_version["rules"]} == {
        f"{node}::co2", f"{node}::ch4"
    }
    # The copy carries the chosen category only; the legacy Scope column is history.
    assert all(rule["scope"] is None for rule in new_version["rules"])
    assert all(rule["categories"] == {"caliber": "direct"} for rule in new_version["rules"])

    source = client.get(f"/api/v1/calculation-methods/{legacy['method_id']}").json()
    assert source["versions"][0]["content_sha256"] == legacy["ref"]["content_sha256"]
    assert source["versions"][0]["rules"][0]["scope"] == "scope_1"


def test_scope_only_legacy_requires_a_target_tree_and_explicit_mapping(client, model_graph):
    application, revision_id, node = _setup(client, model_graph)
    legacy = _create_caliber(
        client, application["id"], revision_id, "Scope only",
        [
            dict(_rule(node, f"{node}::co2", None, location="onsite"),
                 boundary_status="selected", scope="scope_1"),
            dict(_rule(node, f"{node}::ch4", None, location="onsite"),
                 boundary_status="pending", scope="scope_1"),
        ],
        semantics=None, dimensions=[],
    )
    base = f"/api/v1/calculation-methods/{legacy['method_id']}/versions/1"
    first = client.get(f"{base}/conversion-preview").json()
    assert first["can_convert"] is False
    assert first["reason"]["code"] == "TAG_SCHEME_CONVERSION_TARGET_REQUIRED"
    assert first["counts"]["invalid_category"] == 1
    assert first["counts"]["unresolved_invalid"] == 1
    assert first["counts"]["pending"] == 1

    target = {
        "id": "legacy_target",
        "name": "现场排放",
        "categories": [
            {"id": "onsite", "name": "现场", "is_leaf": True},
            {"id": "purchased", "name": "外购", "is_leaf": True},
        ],
    }
    unmapped = client.post(f"{base}/conversion-preview", json={"target_dimension": target}).json()
    assert unmapped["can_convert"] is False
    assert unmapped["rules"][0]["needs_resolution"] is True
    assert unmapped["problems"][0]["code"] == "TAG_SCHEME_CONVERSION_CATEGORY_REQUIRED"

    unknown = client.post(f"{base}/conversion-preview", json={
        "target_dimension": target,
        "resolutions": [{"rule_index": 0, "category": "missing"}],
    }).json()
    assert unknown["can_convert"] is False
    assert any(
        problem["code"] == "TAG_SCHEME_CONVERSION_RESOLUTION_UNKNOWN"
        for problem in unknown["problems"]
    )

    resolved = client.post(f"{base}/conversion-preview", json={
        "target_dimension": target,
        "resolutions": [{"rule_index": 0, "category": "onsite"}],
    }).json()
    assert resolved["can_convert"] is True
    assert resolved["counts"]["assigned"] == 1
    assert resolved["rules"][0]["resolved"] is True

    stale = client.post(f"{base}/convert", json={
        "name": "Scope only result",
        "target_dimension": target,
        "resolutions": [{"rule_index": 0, "category": "onsite"}],
        "expected_mapping_sha256": "0" * 64,
    })
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "TAG_SCHEME_CONVERSION_MAPPING_CHANGED"

    converted = client.post(f"{base}/convert", json={
        "name": "Scope only result",
        "target_dimension": target,
        "resolutions": [{"rule_index": 0, "category": "onsite"}],
        "expected_mapping_sha256": resolved["mapping_sha256"],
    })
    assert converted.status_code == 201, converted.text
    new_version = converted.json()["versions"][0]
    assert [dimension["id"] for dimension in new_version["reporting_dimensions"]] == ["legacy_target"]
    assert [rule["categories"] for rule in new_version["rules"]] == [{"legacy_target": "onsite"}]


def test_legacy_with_several_trees_requires_a_choice_and_resolution_for_foreign_rules():
    plant = {
        "id": "plant",
        "name": "工厂",
        "categories": [{"id": "onsite_plant", "name": "现场", "is_leaf": True}],
    }
    method = SimpleNamespace(id="m2", name="Multi tree", purpose="custom")
    record = SimpleNamespace(
        version=1,
        semantics=None,
        content_sha256="e" * 64,
        cbam_boundary_ref=None,
        model_processing_rules_ref=None,
        reporting_dimensions=[DIMENSION, plant],
        rules=[
            dict(_rule("p1", "p1::co2", "direct"), boundary_status="selected"),
            dict(_rule("p1", "p1::ch4", "onsite_plant", dimension="plant"), boundary_status="selected"),
            dict(_rule("p1", "p1::n2o", "indirect"), boundary_status="selected"),
        ],
    )
    undecided, _target, _dimension = CalculationMethodService._conversion_plan(method, record)
    assert undecided["can_convert"] is False
    assert undecided["reason"]["code"] == "TAG_SCHEME_CONVERSION_DIMENSION_REQUIRED"
    assert [item["id"] for item in undecided["source_dimensions"]] == ["caliber", "plant"]

    blocked, _target, _dimension = CalculationMethodService._conversion_plan(
        method, record, {"source_dimension_id": "caliber"}
    )
    assert blocked["can_convert"] is False
    assert blocked["counts"]["assigned"] == 2
    assert blocked["counts"]["unresolved_invalid"] == 1
    assert blocked["problems"][0]["code"] == "TAG_SCHEME_CONVERSION_CATEGORY_OUTSIDE_DIMENSION"

    decided, target, dimension = CalculationMethodService._conversion_plan(
        method, record, {
            "source_dimension_id": "caliber",
            "resolutions": [{"rule_index": 1, "category": None}],
        },
    )
    assert decided["can_convert"] is True
    assert decided["counts"]["resolved_without_category"] == 1
    assert dimension["id"] == "caliber"
    assert [rule["exchange_id"] for rule in target] == ["p1::co2", "p1::n2o"]

    redundant, _target, _dimension = CalculationMethodService._conversion_plan(
        method, record, {
            "source_dimension_id": "caliber",
            "resolutions": [{"rule_index": 0, "category": "direct"}],
        },
    )
    assert redundant["can_convert"] is False
    assert any(
        problem["code"] == "TAG_SCHEME_CONVERSION_RESOLUTION_NOT_APPLICABLE"
        for problem in redundant["problems"]
    )


def test_conversion_creates_an_independent_method_and_keeps_the_legacy_result(client, model_graph):
    application, revision_id, node = _setup(client, model_graph)
    legacy = _create_caliber(
        client, application["id"], revision_id, "Legacy tag",
        [
            dict(_rule(node, f"{node}::co2", "direct"), boundary_status="selected"),
            dict(_rule(node, f"{node}::ch4", None), boundary_status="selected"),
        ],
        semantics="flow_tag.v1",
    )
    snapshot_id = _insert_snapshot(
        client,
        application["id"],
        revision_id,
        scaled=[{"exchange_id": f"{node}::co2", "direction": "emission"},
                {"exchange_id": f"{node}::ch4", "direction": "emission"}],
        terms=[{"exchange_id": f"{node}::co2", "path_contribution_value": 100.0},
               {"exchange_id": f"{node}::ch4", "path_contribution_value": 30.0}],
        solve_hash="v" * 64,
    )
    before = _group(client, application["id"], snapshot_id, [legacy["ref"]])

    preview = client.get(
        f"/api/v1/calculation-methods/{legacy['method_id']}/versions/1/conversion-preview"
    ).json()
    assert preview["can_convert"] is True
    assert preview["counts"]["assigned"] == 1
    assert preview["counts"]["selected_without_category"] == 1

    converted = client.post(
        f"/api/v1/calculation-methods/{legacy['method_id']}/versions/1/convert",
        json={"name": "Legacy tag · 结果分类"},
    )
    assert converted.status_code == 201, converted.text
    new_method_id = converted.json()["method"]["id"]
    new_version = converted.json()["versions"][0]
    assert new_method_id != legacy["method_id"]
    assert new_version["semantics"] == RESULT_CATEGORY_SEMANTICS
    assert [rule["exchange_id"] for rule in new_version["rules"]] == [f"{node}::co2"]
    assert new_version["status"] == "draft"
    checked = client.post(f"/api/v1/calculation-methods/{new_method_id}/versions/1/validate")
    assert checked.json()["valid"] is True, checked.text

    # Legacy stays byte-identical and still replays its frozen result; the copy groups only co2.
    legacy_after = client.get(f"/api/v1/calculation-methods/{legacy['method_id']}").json()
    assert legacy_after["versions"][0]["content_sha256"] == legacy["ref"]["content_sha256"]
    assert legacy_after["versions"][0]["rules"][0]["boundary_status"] == "selected"
    assert _group(client, application["id"], snapshot_id, [legacy["ref"]]) == before
    after = _group(client, application["id"], snapshot_id, [{
        "method_id": new_method_id, "version": 1, "content_sha256": new_version["content_sha256"],
    }])
    assert after["schemes"][0]["tag_total"]["value"] == 100.0
    assert after["schemes"][0]["unmatched"]["known_value"] == 30.0


def test_legacy_save_and_clone_are_refused_but_conversion_is_offered(client, model_graph):
    application, revision_id, node = _setup(client, model_graph)
    legacy = _create_caliber(
        client, application["id"], revision_id, "Frozen tag",
        [dict(_rule(node, f"{node}::co2", "direct"), boundary_status="selected")],
        semantics="flow_tag.v1",
    )
    detail = client.get(f"/api/v1/calculation-methods/{legacy['method_id']}").json()
    saved = client.put(
        f"/api/v1/calculation-methods/{legacy['method_id']}/versions/1",
        json={
            "name": "Frozen tag renamed",
            "rules": detail["versions"][0]["rules"],
            "reporting_dimensions": [DIMENSION],
            "expected_content_sha256": legacy["ref"]["content_sha256"],
        },
    )
    assert saved.status_code == 409
    assert saved.json()["error"]["code"] == "CALCULATION_METHOD_LEGACY_READ_ONLY"
    cloned = client.post(
        f"/api/v1/calculation-methods/{legacy['method_id']}/versions/1/clone",
        json={"name": "Clone", "purpose": "custom", "model_revision_id": revision_id},
    )
    assert cloned.status_code == 409
    assert cloned.json()["error"]["code"] == "CALCULATION_METHOD_LEGACY_READ_ONLY"
    capabilities = client.get(f"/api/v1/calculation-methods/{legacy['method_id']}/capabilities").json()
    assert capabilities["legacy_tag_scheme"] is True
    assert capabilities["result_category"] is False
    assert capabilities["conversion_available"] is True
    assert capabilities["processing_package_selection"] is False
    assert capabilities["processing_package_reason"]["code"] == "CALCULATION_METHOD_TAG_NO_PROCESSING_PACKAGE"

    converted = client.post(
        f"/api/v1/calculation-methods/{legacy['method_id']}/versions/1/convert",
        json={"name": "Frozen tag result"},
    )
    assert converted.status_code == 201, converted.text
    new_id = converted.json()["method"]["id"]
    new_capabilities = client.get(f"/api/v1/calculation-methods/{new_id}/capabilities").json()
    assert new_capabilities["result_category"] is True
    assert new_capabilities["tag_grouping"] is True
    assert new_capabilities["legacy_tag_scheme"] is False
    assert new_capabilities["conversion_available"] is False
    assert new_capabilities["processing_package_selection"] is False
    assert new_capabilities["processing_package_reason"]["code"] == "CALCULATION_METHOD_RESULT_CATEGORY_NO_PROCESSING_PACKAGE"


def test_renaming_a_category_keeps_its_relations(client, model_graph):
    application, revision_id, node = _setup(client, model_graph)
    scheme = _create_caliber(client, application["id"], revision_id, "改名口径", [_rule(node, f"{node}::co2", "direct")])
    renamed = [DIMENSION | {"categories": [
        {"id": "direct", "name": "现场排放", "parent_id": "all", "is_leaf": True},
        {"id": "indirect", "name": "间接排放", "parent_id": "all", "is_leaf": True},
        {"id": "all", "name": "全部", "is_leaf": False},
    ]}]
    saved = client.put(
        f"/api/v1/calculation-methods/{scheme['method_id']}/versions/1",
        json={
            "name": "改名口径",
            "rules": [_rule(node, f"{node}::co2", "direct")],
            "reporting_dimensions": renamed,
            "expected_content_sha256": scheme["ref"]["content_sha256"],
        },
    )
    assert saved.status_code == 200, saved.text
    version_two = next(item for item in saved.json()["versions"] if item["version"] == 2)
    assert version_two["reporting_dimensions"][0]["categories"][0]["name"] == "现场排放"
    assert version_two["rules"][0]["categories"] == {"caliber": "direct"}
    snapshot_id = _insert_snapshot(
        client,
        application["id"],
        revision_id,
        scaled=[{"exchange_id": f"{node}::co2", "direction": "emission"}],
        terms=[{"exchange_id": f"{node}::co2", "path_contribution_value": 7.0}],
        solve_hash="w" * 64,
    )
    checked = client.post(f"/api/v1/calculation-methods/{scheme['method_id']}/versions/2/validate")
    assert checked.json()["valid"] is True, checked.text
    grouped = _group(client, application["id"], snapshot_id, [{
        "method_id": scheme["method_id"], "version": 2, "content_sha256": version_two["content_sha256"],
    }])
    assert grouped["schemes"][0]["dimension"]["categories"][0]["name"] == "现场排放"
    assert grouped["schemes"][0]["tag_total"]["value"] == 7.0


def test_exported_result_category_report_uses_category_wording_and_keeps_empty_as_unpopulated(
        client, model_graph):
    application, revision_id, node = _setup(client, model_graph)
    scheme = _create_caliber(
        client, application["id"], revision_id, "范围1–3",
        [_rule(node, f"{node}::co2", "direct")],
    )
    snapshot_id = _insert_snapshot(
        client,
        application["id"],
        revision_id,
        scaled=[{"exchange_id": f"{node}::co2", "direction": "emission"},
                {"exchange_id": f"{node}::ch4", "direction": "emission"}],
        terms=[{"exchange_id": f"{node}::co2", "path_contribution_value": 100.0},
               {"exchange_id": f"{node}::ch4", "path_contribution_value": 30.0}],
        solve_hash="x" * 64,
    )
    grouped = _group(client, application["id"], snapshot_id, [scheme["ref"]])
    report = client.get(
        f"/api/v1/applications/{application['id']}/tag-grouping-results/{grouped['result_id']}/export")
    assert report.status_code == 200, report.text
    assert "结果分类归集结果" in report.text
    assert "已分类贡献小计：100.0" in report.text
    # ch4 stays outside the caliber, and the declared-but-absent input port is listed, not zeroed.
    assert "无（未分类）：2" in report.text
    assert "未匹配：" not in report.text
    assert "待确认：" not in report.text
    assert "已匹配，未分类" not in report.text

    empty = _create_caliber(
        client, application["id"], revision_id, "碳市场", [],
        dimensions=[{"id": "caliber", "name": "碳市场",
                     "categories": [{"id": "履约", "name": "履约", "is_leaf": True}]}],
    )
    empty_grouped = _group(client, application["id"], snapshot_id, [empty["ref"]])
    empty_report = client.get(
        f"/api/v1/applications/{application['id']}/tag-grouping-results/{empty_grouped['result_id']}/export")
    assert empty_report.status_code == 200, empty_report.text
    assert "尚未给任何流选择结果分类" in empty_report.text
    assert "已分类贡献小计：—" in empty_report.text


def test_legacy_tag_report_wording_is_unchanged_by_the_result_category_branch():
    legacy = {
        "result_id": "r1", "created_at": "2026-10-28T00:00:00", "snapshot_id": "s1",
        "content_sha256": "c" * 64, "mode": "separate",
        "schemes": [{
            "scheme": {"name": "能源标签", "version": 1},
            "semantics": "flow_tag.v1",
            "dimension": {"categories": [
                {"id": "tag_category_1", "name": "购入能源", "subtotal": 100.0, "unit": "kg CO2e"},
            ]},
            "tag_total": {"value": 100.0, "unit": "kg CO2e"},
            "uncategorized": {"subtotal": 5.0, "unit": "kg CO2e", "term_count": 1},
            "matched": {"term_count": 1, "known_term_count": 1},
            "unmatched": {"term_count": 0},
            "pending": {"term_count": 0},
            "missing": {"term_count": 0},
            "real_zero": {"term_count": 0}, "coverage": {}, "reconciled": True,
        }],
    }
    report = render_tag_grouping_html(legacy)
    assert "标签归集结果" in report
    assert "已匹配贡献小计：100.0 kg CO2e" in report
    assert "未匹配：0" in report
    assert "待确认：0" in report
    assert "已匹配，未分类" in report
    assert "无（未分类）" not in report

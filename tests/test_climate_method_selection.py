"""HTTP and persisted identity checks for the authored EF climate default."""
from __future__ import annotations

from nebula_one.models import AnalysisRun
from nebula_one.models import Application
from nebula_one.runtime_models import SolvedSystemSnapshot
from nebula_one.services.climate_method_selection import ensure_official_climate_methods
from nebula_one.native_climate_contract import NativeClimateContract
from test_api_flow import _attach_model, _create_application


def test_new_solve_obeys_declared_library_default_without_guessing_between_bound_versions(client):
    import json
    from pathlib import Path
    payload = json.loads(Path('src/nebula_one/resources/official_methods/pcf-ef31-foreground-1.0.3.json').read_text(encoding='utf-8'))
    assert client.post('/api/v1/method-packages', json=payload).status_code == 201
    app = _create_application(client)
    model = _attach_model(client, app['id'])
    revision = model['upstream_receipt']['base_revision_id']
    preferred = 'pcf.product.ef31.foreground@1.0.4'
    with client.app.state.container.database.session() as db:
        row = db.get(Application, app['id'])
        row.context = {**row.context, 'method_package_refs': ['pcf.product.ef31.foreground@1.0.3', preferred],
            'seed_template': {'accounting_library': {'tasks': [{'role': 'complete_model', 'default_ref': preferred}]}}}
        db.commit()
    response = client.post(f'/api/v1/applications/{app["id"]}/system-revisions/{revision}/solve', json={
        'demand': [{'reference_flow_uuid': 'flow-product', 'amount': 8, 'unit': 'kg'}],
        'climate_default': True, 'idempotency_key': 'declared-default'})
    assert response.status_code == 201, response.text
    assert response.json()['provider_receipt']['calculation_basis']['calculation_method']['reference'] == preferred


def test_new_nonsteel_climate_solve_pins_the_registered_ef_method(client):
    app = _create_application(client)
    model = _attach_model(client, app["id"])
    revision_id = model["upstream_receipt"]["base_revision_id"]
    response = client.post(
        f"/api/v1/applications/{app['id']}/system-revisions/{revision_id}/solve",
        json={"demand": [{"reference_flow_uuid": "flow-product", "amount": 8, "unit": "kg"}],
              "climate_default": True, "idempotency_key": "nonsteel-default-ef31"},
    )
    assert response.status_code == 201, response.text
    snapshot = response.json()
    with client.app.state.container.database.session() as db:
        run = db.get(AnalysisRun, snapshot["provider_receipt"]["analysis_run_id"])
        assert run.parameters["calculation_method"]["lcia_method"] == "EF v3.1"
        assert run.parameters["calculation_method"]["reference"] == "pcf.product.ef31.foreground@1.0.4"
        assert len(run.parameters["calculation_method"]["content_sha256"]) == 64
        assert run.parameters["lcia_methods"] == ["EF v3.1"]
    resolved = client.get(
        f"/api/v1/solved-system-snapshots/{snapshot['id']}/product-carbon-footprint/default-method"
    )
    assert resolved.status_code == 200, resolved.text
    # The shared synthetic engine returns no characterization; a method pin is not a result.
    assert resolved.json()["status"] == "unavailable"


def test_climate_default_does_not_reuse_the_same_revisions_inventory_snapshot(client):
    app = _create_application(client)
    model = _attach_model(client, app["id"])
    revision_id = model["upstream_receipt"]["base_revision_id"]
    url = f"/api/v1/applications/{app['id']}/system-revisions/{revision_id}/solve"
    demand = [{"reference_flow_uuid": "flow-product", "amount": 8, "unit": "kg"}]
    inventory = client.post(url, json={"demand": demand, "idempotency_key": "inventory"})
    assert inventory.status_code == 201, inventory.text

    climate_request = {"demand": demand, "climate_default": True,
                       "idempotency_key": "climate-default"}
    climate = client.post(url, json=climate_request)
    assert climate.status_code == 201, climate.text
    assert climate.json()["id"] != inventory.json()["id"]
    assert climate.json()["solve_hash"] != inventory.json()["solve_hash"]
    basis = climate.json()["provider_receipt"]["calculation_basis"]
    assert basis["lcia_methods"] == ["EF v3.1"]
    assert basis["calculation_method"]["reference"] == "pcf.product.ef31.foreground@1.0.4"
    assert len(basis["calculation_method"]["content_sha256"]) == 64

    replay = client.post(url, json=climate_request)
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == climate.json()["id"]


def test_organization_solve_does_not_upgrade_the_projects_bound_grouping_method(client):
    app = _create_application(client)
    model = _attach_model(client, app["id"])
    revision_id = model["upstream_receipt"]["base_revision_id"]
    with client.app.state.container.database.session() as db:
        row = db.get(Application, app["id"])
        row.context = {**row.context, "method_package_refs": ["nebula.organization-lifecycle-carbon.steel-model@1.0.5"],
                       "modeling_template_binding": {"profile": {
                           "id": "steel-bf-bof-inventory", "version": "1.1.2",
                           "content_sha256": "df91eaf3c96638d1f20bbec40c544f046fe1107bb78282ba532da95fd2dbbe35"}}}
        db.commit()
    response = client.post(f"/api/v1/applications/{app['id']}/system-revisions/{revision_id}/solve", json={
        "demand": [{"reference_flow_uuid": "flow-product", "amount": 8, "unit": "kg"}],
        "climate_default": True, "analysis_task": "organization", "idempotency_key": "keep-organization-method"})
    assert response.status_code == 201, response.text
    with client.app.state.container.database.session() as db:
        assert db.get(Application, app["id"]).context["method_package_refs"] == [
            "nebula.organization-lifecycle-carbon.steel-model@1.0.5"]


def test_frozen_ef_answer_resolves_registered_method_without_project_name(client):
    app = _create_application(client)
    model = _attach_model(client, app["id"])
    with client.app.state.container.database.session() as db:
        ensure_official_climate_methods(db)
        db.add(SolvedSystemSnapshot(
            id="frozen-ef-default", application_id=app["id"],
            system_revision_id=model["upstream_receipt"]["base_revision_id"],
            solve_hash="a" * 64, provider="nebula_lca", provider_receipt={},
            functional_unit={"amount": 1, "unit": "kg"}, database_release="EF3.1",
            solver_version="fixture", activity_vector=[], scaled_technosphere_exchanges=[],
            scaled_elementary_exchanges=[], internal_transfers=[], boundary_flows=[],
            process_balance_residuals=[], contribution_graph={}, lcia_results={
                "method": "EF v3.1", "indicator_results": [{
                    "canonical_indicator_key": "climate change",
                    "unit": "kg CO2-Eq", "value": 3.0,
                }],
            }, content_sha256="b" * 64))
        db.commit()
    response = client.get(
        "/api/v1/solved-system-snapshots/frozen-ef-default/product-carbon-footprint/default-method"
    )
    assert response.status_code == 200, response.text
    assert response.json()["reference"] == "pcf.product.ef31.foreground@1.0.4"
    assert response.json()["method"]["lcia_method"] == "EF v3.1"
    assert response.json()["method"]["result_unit"] == "kg CO2-Eq"
    assert len(response.json()["content_sha256"]) == 64


def test_default_refuses_a_caller_selected_method(client):
    response = client.post(
        "/api/v1/applications/absent/system-revisions/absent/solve",
        json={"demand": [{"reference_flow_uuid": "flow-product", "amount": 1, "unit": "kg"}],
              "climate_default": True, "lcia_methods": ["other"]},
    )
    assert response.status_code == 422


def test_frozen_native_answer_uses_exact_source_pin_and_never_falls_back(client):
    app = _create_application(client)
    model = _attach_model(client, app["id"])
    pin = NativeClimateContract().request_payload()
    answer = {
        "schema_version": "provider.native-background-climate-total.response.v1",
        "method_package_id": pin["method_package_id"],
        "method_package_version": pin["method_package_version"],
        "method_package_sha256": pin["method_package_sha256"],
        "runtime_manifest_sha256": pin["runtime_manifest_sha256"],
        "merge_status": "merged", "unified_climate_total": 4.0,
        "indicator": {"method": "EF v3.1", "unit": "kg CO2-Eq"},
    }
    with client.app.state.container.database.session() as db:
        ensure_official_climate_methods(db)
        db.add(SolvedSystemSnapshot(
            id="frozen-native-default", application_id=app["id"],
            system_revision_id=model["upstream_receipt"]["base_revision_id"],
            solve_hash="c" * 64, provider="nebula_lca", provider_receipt={},
            functional_unit={"amount": 1, "unit": "kg"}, database_release="ecoinvent_3.11",
            solver_version="fixture", activity_vector=[], scaled_technosphere_exchanges=[],
            scaled_elementary_exchanges=[], internal_transfers=[], boundary_flows=[],
            process_balance_residuals=[], contribution_graph={}, lcia_results={},
            native_background_climate={"request": pin, "response": answer}, content_sha256="d" * 64))
        db.commit()
    url = "/api/v1/solved-system-snapshots/frozen-native-default/product-carbon-footprint/default-method"
    ready = client.get(url)
    assert ready.status_code == 200
    assert ready.json()["reference"] == "pcf.product.ef31.native-model-boundary@1.0.0"
    assert ready.json()["method"]["source_method"]["content_sha256"] == pin["method_package_sha256"]
    with client.app.state.container.database.session() as db:
        snapshot = db.get(SolvedSystemSnapshot, "frozen-native-default")
        snapshot.native_background_climate = {"request": pin, "response": {**answer, "merge_status": "split_diagnostic"}}
        db.commit()
    assert client.get(url).json()["status"] == "unavailable"

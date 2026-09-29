from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook

from nebula_one.hashing import canonical_json_sha256
from nebula_one.models import AnalysisRun


METHOD_PACKAGE = Path("examples/pcf-product-gold-standard/method-package.json")


def _indicator(key: str, value: float, unit: str = "kg CO2-Eq") -> dict:
    return {
        "method_en": "EF v3.1",
        "indicator_en": "Climate change - GWP100",
        "canonical_indicator_key": key,
        "value": value,
        "unit": unit,
        "indicator_unit": unit,
    }


def _prepare_snapshot(
    client,
    *,
    elementary_receipts=None,
    total_unit="kg CO2-Eq",
    include_contribution_receipts=False,
    mapped_receipts=None,
    provenance_extra=None,
):
    package_payload = json.loads(METHOD_PACKAGE.read_text(encoding="utf-8"))
    package = client.post("/api/v1/method-packages", json=package_payload)
    assert package.status_code == 201, package.text
    package = package.json()

    application = client.post(
        "/api/v1/applications",
        json={"name": "PCF gold standard", "application_type": "system_analysis"},
    ).json()
    model = client.post(
        f"/api/v1/applications/{application['id']}/system-models",
        json={
            "name": "PCF gold model",
            "provider": "nebula_lca",
            "upstream_project_id": "project-1",
            "upstream_version": 3,
        },
    ).json()
    revision_id = model["upstream_receipt"]["base_revision_id"]
    revision = client.get(f"/api/v1/system-revisions/{revision_id}").json()
    run = AnalysisRun(
        system_model_id=model["id"],
        system_revision_id=revision_id,
        capability_key="solve.nebula.v1",
        idempotency_key="pcf-gold-solve",
        request_sha256="a" * 64,
        parameters={
            "demand": [
                {
                    "reference_flow_uuid": "flow-product",
                    "amount": 1.0,
                    "unit": "kg",
                    "unit_group_uuid": "mass",
                    "unit_group_version": "1",
                }
            ],
            "lcia_methods": ["EF v3.1"],
        },
        status="succeeded",
        model_graph_sha256=model["graph_sha256"],
        provider_receipt={},
        result={},
    )
    with client.app.state.container.database.session() as db:
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    elementary_flow_receipts = (
        elementary_receipts
        if elementary_receipts is not None
        else [
            {
                "exchange_id": "process::co2-out",
                "source_namespace": "tiangong_open_data",
                "flow_uuid": "08a91e70-3ddc-11dd-923d-0050c2490048",
                "version": "03.00.004",
                "method": "EF v3.1",
                "factor_hash": "b" * 64,
            }
        ]
    )
    scaled_elementary_exchanges = [
        {
                "process_id": "process",
                "exchange_id": "process::co2-out",
                "flow_uuid": "08a91e70-3ddc-11dd-923d-0050c2490048",
                "amount": 2.0,
                "unit": "kg",
                "unit_group": "mass",
                "direction": "output",
                "exchange_type": "elementary",
            }
    ] if elementary_flow_receipts else []
    lcia_results = {
        "schema_version": "provider.lcia.response.v1",
        "method": "EF v3.1",
        "database_release": "EF3.1",
        "inventory_hash": "d" * 64,
        "indicator_results": [
            _indicator("climate change", 2.0, total_unit),
            _indicator("climate change: fossil", 2.0),
            _indicator("climate change: biogenic", 0.0),
            _indicator("climate change: land use and land use change", 0.0),
        ],
        "runtime_assets": [{"runtime_id": "ef31-gold"}],
    }
    if include_contribution_receipts:
        solve_hash = "e" * 64
        runtime_assets_hash = "f" * 64
        term = {
            "schema_version": "provider.lcia.contribution-term.v1",
            "exchange_id": "process::co2-out",
            "process_uuid": "process",
            "source_namespace": "tiangong_open_data",
            "flow_uuid": "08a91e70-3ddc-11dd-923d-0050c2490048",
            "flow_version": "03.00.004",
            "amount": 2.0,
            "amount_unit": "kg",
            "direction": "output",
            "contribution_value": 2.0,
            "contribution_unit": "kg CO2-Eq",
            "cf_method": "EF v3.1",
            "cf_database_release": "EF3.1",
            "cf_indicator_key": "climate change",
            "cf_runtime_assets_hash": runtime_assets_hash,
            "solve_hash": solve_hash,
            "cf_hash": "1" * 64,
        }
        receipt = {
            "schema_version": "provider.lcia.indicator-contribution-receipt.v1",
            "method": "EF v3.1",
            "database_release": "EF3.1",
            "canonical_indicator_key": "climate change",
            "indicator_unit": "kg CO2-Eq",
            "indicator_value": 2.0,
            "contribution_total": 2.0,
            "reconciliation_delta": 0.0,
            "terms": [term],
            "solve_hash": solve_hash,
            "provider_commit": "provider-test",
            "runtime_assets_hash": runtime_assets_hash,
        }
        receipt["content_hash"] = canonical_json_sha256(receipt)
        lcia_results.update(
            {
                "solve_hash": solve_hash,
                "provider_commit": "provider-test",
                "runtime_assets_hash": runtime_assets_hash,
                "indicator_contribution_receipts": [receipt],
            }
        )
        lcia_results["contribution_receipts_hash"] = canonical_json_sha256([receipt])
    snapshot_payload = {
        "system_revision_id": revision_id,
        "provider": "nebula_lca",
        "provider_receipt": {
            "endpoint": "/api/provider/v1/solve",
            "status": "completed",
            "upstream_run_id": "pcf-gold-provider-run",
            "system_revision_hash": revision["content_sha256"],
            "analysis_run_id": run_id,
            "database_release": "EF3.1",
            "solver_version": "gold-standard",
            "elementary_flow_receipts": elementary_flow_receipts,
            "background_process_receipts": [],
            "mapped_background_process_receipts": mapped_receipts or [],
            "provenance": {"request_hash": "c" * 64, **(provenance_extra or {})},
        },
        "functional_unit": revision["graph_snapshot"]["functionalUnit"],
        "database_release": "EF3.1",
        "solver_version": "gold-standard",
        "activity_vector": [],
        "scaled_technosphere_exchanges": [],
        "scaled_elementary_exchanges": scaled_elementary_exchanges,
        "internal_transfers": [],
        "boundary_flows": [],
        "process_balance_residuals": [],
        "contribution_graph": {},
        "lcia_results": lcia_results,
    }
    snapshot = client.post(
        f"/api/v1/applications/{application['id']}/solved-system-snapshots",
        json=snapshot_payload,
    )
    assert snapshot.status_code == 201, snapshot.text
    return snapshot.json(), f"{package['package_id']}@{package['version']}"


def test_mapped_background_is_partial_coverage_not_a_complete_declaration(client):
    snapshot, package_ref = _prepare_snapshot(client, mapped_receipts=[{
        "process_uuid": "synthetic-provider", "claim_role": "partial_background_leaf",
    }])
    response = client.post(
        f"/api/v1/solved-system-snapshots/{snapshot['id']}/product-carbon-footprint",
        json={"method_package_ref": package_ref},
    )
    assert response.status_code == 200, response.text
    claim = response.json()["boundary_claim"]
    assert claim["claim_scope"] == "model_defined_partial_background"
    assert claim["coverage"] == "foreground_with_pinned_background"
    assert claim["complete_product_declaration"] is False
    report = client.get(
        f"/api/v1/solved-system-snapshots/{snapshot['id']}/product-carbon-footprint/report.html",
        params={"method_package_ref": package_ref},
    )
    assert report.status_code == 200
    assert "model_defined_partial_background" in report.text


def test_product_pcf_gold_standard_is_deterministic(client) -> None:
    snapshot, package_ref = _prepare_snapshot(client)
    path = (
        f"/api/v1/solved-system-snapshots/{snapshot['id']}"
        "/product-carbon-footprint"
    )
    first = client.post(path, json={"method_package_ref": package_ref})
    replay = client.post(path, json={"method_package_ref": package_ref})

    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    result = first.json()
    assert result["total_footprint"] == {
        "value": 2.0,
        "unit": "kg CO2-Eq",
        "indicator_key": "climate change",
    }
    assert result["functional_unit"]["amount"] == 1.0
    assert result["boundary_claim"] == {
        "claim_scope": "foreground_boundary",
        "coverage": "foreground_only",
        "complete_product_declaration": False,
    }
    assert result["audit"]["status"] == "passed"
    assert result["contribution_analysis"]["status"] == "unavailable"
    content = dict(result)
    content.pop("content_sha256")
    assert result["content_sha256"] == canonical_json_sha256(content)
    chart = client.post(
        f"{path}/chart.svg", json={"method_package_ref": package_ref}
    )
    assert chart.status_code == 200
    assert chart.headers["content-type"].startswith("image/svg+xml")
    assert "Product carbon footprint" in chart.text
    assert "2 kg CO2-Eq" in chart.text
    chart_get = client.get(
        f"{path}/chart.svg", params={"method_package_ref": package_ref}
    )
    assert chart_get.status_code == 200
    assert chart_get.text == chart.text


def test_product_pcf_fails_closed_without_elementary_receipts(client) -> None:
    snapshot, package_ref = _prepare_snapshot(client, elementary_receipts=[])
    response = client.post(
        f"/api/v1/solved-system-snapshots/{snapshot['id']}/product-carbon-footprint",
        json={"method_package_ref": package_ref},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PCF_ELEMENTARY_FLOW_RECEIPTS_REQUIRED"


def test_product_pcf_fails_closed_on_impact_unit_mismatch(client) -> None:
    snapshot, package_ref = _prepare_snapshot(client, total_unit="kg")
    response = client.post(
        f"/api/v1/solved-system-snapshots/{snapshot['id']}/product-carbon-footprint",
        json={"method_package_ref": package_ref},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PCF_RESULT_UNIT_MISMATCH"


def test_product_pcf_consumes_exact_contribution_receipt(client) -> None:
    snapshot, package_ref = _prepare_snapshot(
        client, include_contribution_receipts=True
    )
    response = client.post(
        f"/api/v1/solved-system-snapshots/{snapshot['id']}/product-carbon-footprint",
        json={"method_package_ref": package_ref},
    )
    assert response.status_code == 200, response.text
    analysis = response.json()["contribution_analysis"]
    assert analysis["status"] == "available"
    assert analysis["coverage"] == "exact_exchange_contributions"
    assert analysis["hotspots"][0]["exchange_id"] == "process::co2-out"
    assert analysis["hotspots"][0]["share_of_total"] == 1.0


def test_product_pcf_exports_excel_and_printable_html(client) -> None:
    snapshot, package_ref = _prepare_snapshot(
        client, include_contribution_receipts=True
    )
    base = f"/api/v1/solved-system-snapshots/{snapshot['id']}/product-carbon-footprint"
    result = client.post(base, json={"method_package_ref": package_ref}).json()
    params = {"method_package_ref": package_ref}

    workbook_response = client.get(f"{base}/export.xlsx", params=params)
    assert workbook_response.status_code == 200
    assert workbook_response.headers["x-nebula-result-sha256"] == result["content_sha256"]
    workbook = load_workbook(BytesIO(workbook_response.content), read_only=True)
    assert workbook.sheetnames == ["核算摘要", "LCIA结果", "贡献热点", "审计与追溯"]
    assert workbook["核算摘要"]["B3"].value == result["content_sha256"]
    assert workbook["贡献热点"]["C2"].value == "process::co2-out"

    html_response = client.get(f"{base}/report.html", params=params)
    assert html_response.status_code == 200
    assert html_response.headers["x-nebula-result-sha256"] == result["content_sha256"]
    assert "产品碳足迹技术核算报告" in html_response.text
    assert "window.print()" in html_response.text
    assert result["content_sha256"] in html_response.text


MAPPING_DEPENDENCIES = [{
    "package_id": "synthetic-elementary-mapping-core", "package_version": "1.0.0",
    "package_hash": "9" * 64, "role": "certified_identity_adjudication",
}]


def test_elementary_mapping_dependencies_survive_freeze_read_and_export(client):
    snapshot, package_ref = _prepare_snapshot(
        client, provenance_extra={"elementary_mapping_dependencies": MAPPING_DEPENDENCIES}
    )
    base = f"/api/v1/solved-system-snapshots/{snapshot['id']}/product-carbon-footprint"
    params = {"method_package_ref": package_ref}
    result = client.post(base, json=params).json()
    assert result["provenance"]["elementary_mapping_dependencies"] == MAPPING_DEPENDENCIES

    workbook_response = client.get(f"{base}/export.xlsx", params=params)
    assert workbook_response.headers["x-nebula-result-sha256"] == result["content_sha256"]
    workbook = load_workbook(BytesIO(workbook_response.content), read_only=True)
    audit = {row[0].value: row[1].value for row in workbook["审计与追溯"].iter_rows(min_row=2, max_col=2)}
    assert json.loads(audit["Provider provenance"])["elementary_mapping_dependencies"] == MAPPING_DEPENDENCIES

    report = client.get(f"{base}/report.html", params=params)
    assert "基本流映射依赖包" in report.text
    assert "synthetic-elementary-mapping-core" in report.text


def test_snapshot_without_the_dependency_contract_gains_no_invented_record(client):
    snapshot, package_ref = _prepare_snapshot(client)
    base = f"/api/v1/solved-system-snapshots/{snapshot['id']}/product-carbon-footprint"
    params = {"method_package_ref": package_ref}
    result = client.post(base, json=params).json()
    assert "elementary_mapping_dependencies" not in result["provenance"]
    assert "基本流映射依赖包" not in client.get(f"{base}/report.html", params=params).text
    content = dict(result)
    content.pop("content_sha256")
    assert result["content_sha256"] == canonical_json_sha256(content)

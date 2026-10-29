"""One steel project, two accounting purposes: solve, recovery and freeze identity over real HTTP.

The engine answers here come from the shared synthetic transport, so no number in this file is a
live-engine result. What is real is the chain under test: one stored steel model, the reviewed
template binding it records, the versioned model processing package bound to that template, and the
method package those rules cite. The CBAM trial reading is exercised at the service seam because a
numeric v2 trial needs a frozen boundary ledger and a real solved inventory; that is R4-B scope.
"""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from nebula_one.config import Settings
from nebula_one.errors import DomainError
from nebula_one.hashing import canonical_json_sha256
from nebula_one.main import create_app
from nebula_one.mapped_background_schemas import ProviderMappedBackgroundProcessPin
from nebula_one.model_derivation import (
    _FLOW_IDENTITY_FIELDS,
    _REQUIRED_FLOW_IDENTITY,
    derive_calculation_model,
)
from nebula_one.model_processing_contract import (
    ModelProcessingRules,
    load_model_processing_rules_for_template,
)
from nebula_one.models import (
    AnalysisRun,
    Application,
    SeedInstallation,
    SystemModel,
    SystemRevision,
)
from nebula_one.runtime_models import MethodPackage, SolvedSystemSnapshot
from nebula_one.runtime_schemas import MethodPackageCreate, ProviderDemandItem
from nebula_one.services.model_processing_runtime import (
    derivation_basis_from_receipt,
    flow_selection_of,
    resolve_purpose_derivation,
)
from nebula_one.services.method_execution_contract import recover_cbam_user_selection
from nebula_one.services.analysis_runs import _provider_elementary_flow_refs
from nebula_one.services.project_mapped_background import ProjectMappedBackgroundService
from nebula_one.services.runtime_support import require_method_package
from test_api_flow import _attach_model
from test_steel_model_processing_assets import (
    _graph,
    _method_package,
    _template_identity,
    _template_profile,
)

SEED_DIR = Path("cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel")
SEED = json.loads((SEED_DIR / "seed.json").read_text(encoding="utf-8"))
METHOD_REF = SEED["method_package_refs"][0]
SOURCE_METHOD_PIN = f"{METHOD_REF['package_id']}@{METHOD_REF['version']}"
EFFECTIVE_PACKAGE = _method_package()
EFFECTIVE_METHOD_PIN = f"{EFFECTIVE_PACKAGE['package_id']}@{EFFECTIVE_PACKAGE['version']}"
RULES_IDENTITY = {
    key: load_model_processing_rules_for_template(_template_identity()).reference()[key]
    for key in ("package_id", "version", "content_sha256")
}
PROFILE, PROFILE_DIGEST, _ = _template_profile()
TEMPLATE_IDENTITY = {
    "id": PROFILE["id"],
    "version": PROFILE["version"],
    "content_sha256": PROFILE_DIGEST,
}


def _rules_binding_unavailable(*_args, **_kwargs):
    """Stand in for a template whose reviewed rule binding moved to a version this checkout lacks."""
    raise DomainError(
        code="MODEL_PROCESSING_RULES_VERSION_UNAVAILABLE",
        message="the rule package this template now binds is not available here",
        status_code=409,
    )


@pytest.fixture()
def model_graph():
    graph = _graph()
    # Match the shared synthetic provider's functional unit; never used as live evidence.
    graph["nodes"][-1]["outputs"][0]["flowUuid"] = "flow-product"
    return graph


@pytest.fixture()
def steel_project(client, model_graph, monkeypatch, upstream_requests, tmp_path):
    """One steel project created from the committed seed, with one mapped background link saved."""
    container = client.app.state.container
    source = client.post(
        "/api/v1/applications",
        json={
            "name": "Steel BF-BOF crude steel",
            "application_type": "project_carbon",
            "description": "Purpose derivation acceptance source",
            "context": {
                "geography": "CN-Hebei",
                "method_package_refs": [SOURCE_METHOD_PIN],
            },
        },
    )
    assert source.status_code == 201, source.text
    source_application = source.json()
    released = json.loads((SEED_DIR / METHOD_REF["path"]).read_text(encoding="utf-8"))
    with container.database.session() as db:
        db.add(
            MethodPackage(
                package_id=released["package_id"],
                version=released["version"],
                package_kind=released["package_kind"],
                jurisdiction=released.get("jurisdiction"),
                manifest=released["manifest"],
                content_sha256=METHOD_REF["content_sha256"],
                status="registered",
            )
        )
        db.commit()
    source_model = _attach_model(client, source_application["id"])
    with container.database.session() as db:
        db.add(
            SeedInstallation(
                id="steel-install",
                seed_id=SEED["seed_id"],
                seed_version=SEED["version"],
                install_key="a" * 64,
                bundle_content_sha256=SEED["content_pins"]["bundle_content_sha256"],
                engine_base_url=container.client.base_url,
                engine_db_digest="c" * 64,
                engine_openapi_version="3.1.0",
                status="ready",
                application_id=source_application["id"],
                system_model_id=source_model["id"],
            )
        )
        db.commit()

    template = client.get("/api/v1/project-templates").json()["items"][0]
    created = client.post(
        f"/api/v1/project-templates/{template['id']}/projects",
        json={
            "name": "Steel actual inventory",
            "project_key": str(uuid4()),
            "expected_template_sha256": template["template_sha256"],
        },
    )
    assert created.status_code == 200, created.text
    created = created.json()

    # The synthetic engine cannot verify an invented provider identity, so the save-time check is
    # stood down; every identity check inside the solve itself stays in force.
    monkeypatch.setattr(
        ProjectMappedBackgroundService, "validate", lambda self, graph, pins: None
    )
    workspace_path = f"/api/v1/applications/{created['application_id']}/workspace"
    original = client.get(f"{workspace_path}/{created['revision_id']}").json()
    assert original["capabilities"] and "cbam.trial.v2" in original["capabilities"]
    # The reviewed template identity revision rewrites both grid electricity inputs, so the link is
    # built from the identity the project actually holds, the way the workspace builds one.
    port = next(
        item
        for item in original["background_ports"]
        if item["exchange_id"] == "continuous-casting::grid-electricity-in"
    )
    pin = ProviderMappedBackgroundProcessPin(
        consumer_exchange_id=port["exchange_id"],
        source_flow_namespace=port["source_namespace"],
        source_flow_uuid=port["flow_uuid"],
        source_flow_version=port["version"],
        target_flow_uuid="22222222-2222-4222-8222-222222222222",
        source_unit=port["unit"],
        target_unit=port["unit"],
        amount_factor=1.0,
        mapping_level="L1",
        mapping_status="auto",
        mapping_rule_id="acceptance-grid-mapping",
        mapping_package_id="acceptance.mapping-package",
        mapping_package_version="1.0.0",
        mapping_package_hash="c" * 64,
        database_release="synthetic_release",
        process_uuid="33333333-3333-4333-8333-333333333333",
        expected_process_content_hash="d" * 64,
        expected_vector_checksum="e" * 64,
    ).model_dump(mode="json")
    saved = client.post(
        f"{workspace_path}/inputs",
        json={
            "revision_id": original["revision_id"],
            "expected_content_sha256": original["content_sha256"],
            "amounts": [1000],
            "values": {field["key"]: field["value"] for field in original["fields"]},
            "source": "Synthetic acceptance fixture",
            "mapped_background_process_pins": [pin],
        },
    )
    assert saved.status_code == 200, saved.text
    saved = saved.json()
    assert saved["saved"] and saved["mapped_background_process_pins"] == [pin]

    solve_url = (
        f"/api/v1/applications/{created['application_id']}/system-revisions"
        f"/{saved['revision_id']}/solve"
    )

    def body(purpose, extra):
        payload = {
            "demand": saved["demand"],
            "mapped_background_process_pins": saved["mapped_background_process_pins"],
            **extra,
        }
        if purpose is not None:
            payload["calculation_purpose"] = purpose
        return payload

    with container.database.session() as db:
        revision = db.get(SystemRevision, saved["revision_id"])
        stored_graph_sha256 = revision.graph_sha256

    return SimpleNamespace(
        container=container,
        database_url=f"sqlite:///{(tmp_path / 'nebula-one.db').as_posix()}",
        application_id=created["application_id"],
        system_model_id=created["system_model_id"],
        revision_id=saved["revision_id"],
        stored_graph_sha256=stored_graph_sha256,
        template=template,
        workspace=saved,
        mapped_pin=pin,
        solve=lambda purpose, **extra: client.post(
            solve_url, json=body(purpose, extra)
        ),
        queue=lambda purpose, **extra: client.post(
            f"{solve_url}/queue", json=body(purpose, extra)
        ),
        snapshots=lambda: client.get(
            f"/api/v1/applications/{created['application_id']}/solved-system-snapshots"
        ).json(),
        solve_requests=lambda: [
            request["json"]
            for request in upstream_requests
            if request["path"] == "/api/provider/v1/solve"
        ],
        run=lambda run_id: _read_run(container, run_id),
        mutate_run=lambda run_id, mutate: _mutate_run(container, run_id, mutate),
        mutate_revision=lambda mutate: _mutate_revision(container, saved["revision_id"], mutate),
    )


def _read_run(container, run_id):
    with container.database.session() as db:
        run = db.get(AnalysisRun, run_id)
        return SimpleNamespace(
            id=run.id,
            status=run.status,
            parameters=deepcopy(run.parameters),
            provider_receipt=deepcopy(run.provider_receipt),
            request_sha256=run.request_sha256,
        )


def _mutate_run(container, run_id, mutate):
    """Write to a persisted run the way a corrupted row would look, then re-read it."""
    with container.database.session() as db:
        run = db.get(AnalysisRun, run_id)
        mutate(run)
        db.commit()
    return _read_run(container, run_id)


def _mutate_revision(container, revision_id, mutate):
    """Write to a persisted revision the way a corrupted row would look."""
    with container.database.session() as db:
        mutate(db.get(SystemRevision, revision_id))
        db.commit()


def _basis(snapshot: dict) -> dict:
    return snapshot["provider_receipt"]["calculation_basis"]


def _derivation(snapshot: dict) -> dict:
    return _basis(snapshot)["model_derivation"]


def _final_output_key(workspace: dict) -> str:
    matches = [
        field
        for field in workspace["fields"]
        if field["group"] == "outputs"
        and field["reference_product"]
        and field["flow_uuid"] == workspace["demand"][0]["reference_flow_uuid"]
    ]
    assert len(matches) == 1, matches
    return matches[0]["key"]


def _save_reference_output(client, steel_project, output_amount: float):
    """Save a new data version whose solve demand is the declared reference-product output.

    ``amounts`` carries a non-matching placeholder so a green result proves the demand followed the
    edited final output, not the batch field, and was not multiplied by any other factor.
    """
    current = client.get(
        f"/api/v1/applications/{steel_project.application_id}/workspace"
        f"/{steel_project.revision_id}"
    ).json()
    key = _final_output_key(current)
    values = {field["key"]: field["value"] for field in current["fields"]}
    values[key] = output_amount
    response = client.post(
        f"/api/v1/applications/{steel_project.application_id}/workspace/inputs",
        json={
            "revision_id": current["revision_id"],
            "expected_content_sha256": current["content_sha256"],
            "values": values,
            "amounts": [7],
            "demand_mode": "reference_output",
            "source": "reference-output acceptance",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _solve_reference_output(client, steel_project, reference_output: dict, purpose: str):
    solve_url = (
        f"/api/v1/applications/{steel_project.application_id}/system-revisions"
        f"/{reference_output['revision_id']}/solve"
    )
    return client.post(
        solve_url,
        json={
            "demand": reference_output["demand"],
            "mapped_background_process_pins": reference_output["mapped_background_process_pins"],
            "calculation_purpose": purpose,
        },
    )


def _revision_node_ids(client, revision_id: str) -> list[str]:
    snapshot = client.get(f"/api/v1/system-revisions/{revision_id}").json()["graph_snapshot"]
    return [node["id"] for node in snapshot.get("nodes") or []]


def _ready_organization_method(client, application_id: str, revision_id: str):
    """Create and validate a ready user method on the exact revision, returning (id, hash, rule)."""
    node = _revision_node_ids(client, revision_id)[0]
    # The stored rule materializes every schema field, including the None-valued v1 identity
    # keys and the additive v2 core fields (which default onto the persisted JSON).
    rule = {
        "process_instance_id": node,
        "exchange_id": None,
        "flow_uuid": None,
        "direction": "emission",
        "boundary_status": "selected",
        "location_role": "onsite",
        "scope": "scope_1",
        "cbam_relevant": False,
        "classification_basis": "user",
        "schema_version": 1,
        "contribution_target": "direct",
        "boundary": None,
        "categories": {},
        "base_method_ref": None,
    }
    created = client.post(
        f"/api/v1/applications/{application_id}/calculation-methods",
        json={"name": "User grouping", "purpose": "organization", "model_revision_id": revision_id, "rules": [rule]},
    )
    assert created.status_code == 201, created.text
    method_id = created.json()["method"]["id"]
    content_hash = created.json()["versions"][0]["content_sha256"]
    validated = client.post(f"/api/v1/calculation-methods/{method_id}/versions/1/validate")
    assert validated.status_code == 200, validated.text
    assert validated.json()["valid"] is True, validated.text
    return method_id, content_hash, rule


def test_reference_output_demand_flows_verbatim_into_the_lca_and_cbam_purposes(
    client, steel_project
):
    """The §4 save-to-solve seam: a reference_output save becomes the exact solve demand.

    Two purposes (lca, cbam) are exercised here; the four task consumers are not run by this test.
    """
    single = _save_reference_output(client, steel_project, 1500)
    assert single["demand"][0]["amount"] == 1500
    assert single["demand"][0]["amount"] != 7

    # Doubling the declared batch output scales the demand exactly once — no hidden period factor.
    doubled = _save_reference_output(client, steel_project, 3000)
    assert doubled["demand"][0]["amount"] == 3000
    assert doubled["demand"][0]["amount"] == 2 * single["demand"][0]["amount"]

    # The reference-output revision is a fresh version; the earlier explicit version stays intact.
    assert doubled["revision_id"] != single["revision_id"]
    assert (
        client.get(
            f"/api/v1/applications/{steel_project.application_id}/workspace"
            f"/{single['revision_id']}"
        ).json()["demand"][0]["amount"]
        == 1500
    )

    application_id = steel_project.application_id
    for purpose in ("lca", "cbam"):
        solved = _solve_reference_output(client, steel_project, doubled, purpose)
        assert solved.status_code == 201, solved.text
        snapshot = solved.json()
        # Each purpose cites the one application and the exact reference-output revision, never latest.
        assert snapshot["system_revision_id"] == doubled["revision_id"]
        with steel_project.container.database.session() as db:
            row = db.get(SolvedSystemSnapshot, snapshot["id"])
            assert row.application_id == application_id
        # The frozen basis demand is the saved reference-output demand, item for item.
        assert _basis(snapshot)["demand"] == _derivation(snapshot)["demand"]
        assert _derivation(snapshot)["demand"] == [
            ProviderDemandItem.model_validate(item).model_dump(mode="json")
            for item in doubled["demand"]
        ]


def test_reference_output_revision_feeds_the_mfa_consumer_on_the_same_revision(
    client, steel_project
):
    """§4/§5.1 at the consumer seam: MFA reads the exact reference_output revision, not latest.

    The synthetic engine answers this steel topology with generic flows, so the mass-balance audit
    legitimately fails here — this test pins that it is *reported* failed rather than beautified into
    a pass (per §5.1), while proving MFA resolves to the same application and exact revision and is
    traceable to this solve. No number below is a live-engine conservation result.
    """
    ro = _save_reference_output(client, steel_project, 1500)
    solved = _solve_reference_output(client, steel_project, ro, "lca")
    assert solved.status_code == 201, solved.text
    snapshot = solved.json()

    mfa = client.get(f"/api/v1/solved-system-snapshots/{snapshot['id']}/mfa")
    assert mfa.status_code == 200, mfa.text
    mfa = mfa.json()

    # The reading is bound to this exact solve, not a fixed illustration or a re-derived latest.
    assert mfa["solved_snapshot_id"] == snapshot["id"]
    assert mfa["solve_hash"] == snapshot["solve_hash"]
    assert mfa["audit"]["provenance"]["solved_snapshot_content_sha256"] == snapshot["content_sha256"]
    with steel_project.container.database.session() as db:
        row = db.get(SolvedSystemSnapshot, snapshot["id"])
        assert row.application_id == steel_project.application_id
        # MFA points at the reference_output revision, distinct from the fixture's explicit version.
        assert row.system_revision_id == ro["revision_id"]
        assert ro["revision_id"] != steel_project.revision_id

    # A real derived graph was built (the sankey series carries nodes), and the mass-balance audit
    # walked this revision's steel topology rather than a fixed illustration.
    assert mfa["series"][0]["nodes"]
    assert mfa["audit"]["process_balances"]

    # Conservation stays honest on synthetic data: the audit reports the missing internal-transfer
    # evidence for a real steel edge (sinter -> blast furnace) instead of suppressing it, so a green
    # here would mean the guard was weakened (per §5.1, no beautifying the warning into a pass).
    issues = mfa["audit"]["issues"]
    assert mfa["audit"]["status"] == "failed"
    assert any(
        issue["code"] == "INTERNAL_TRANSFER_EVIDENCE_MISSING"
        and "sinter" in str(issue.get("source_exchange_id", ""))
        and "blast-furnace" in str(issue.get("target_exchange_id", ""))
        for issue in issues
    ), issues


def test_two_purposes_of_one_stored_model_never_share_one_frozen_answer(steel_project):
    lca = steel_project.solve("lca")
    assert lca.status_code == 201, lca.text
    cbam = steel_project.solve("cbam")
    assert cbam.status_code == 201, cbam.text
    lca, cbam = lca.json(), cbam.json()

    assert lca["id"] != cbam["id"]
    assert lca["solve_hash"] != cbam["solve_hash"]
    assert lca["system_revision_id"] == cbam["system_revision_id"] == steel_project.revision_id
    assert sorted(item["id"] for item in steel_project.snapshots()) == sorted(
        [lca["id"], cbam["id"]]
    )

    lca_basis, cbam_basis = _derivation(lca), _derivation(cbam)
    # Same stored model, same rule identity, two accounting purposes, two separate answers.
    assert lca_basis["source_graph_sha256"] == cbam_basis["source_graph_sha256"]
    assert lca_basis["source_graph_sha256"] == steel_project.stored_graph_sha256
    assert lca_basis["basis_sha256"] != cbam_basis["basis_sha256"]
    assert lca_basis["purpose"] == "lca" and cbam_basis["purpose"] == "cbam"
    assert lca_basis["template"] == cbam_basis["template"] == TEMPLATE_IDENTITY
    assert lca_basis["model_processing_rules"] == cbam_basis["model_processing_rules"]
    assert lca_basis["model_processing_rules"] == RULES_IDENTITY
    assert lca_basis["method_packages"] == []
    assert cbam_basis["method_packages"] == [
        {
            key: EFFECTIVE_PACKAGE[key]
            for key in ("package_id", "version", "content_sha256")
        }
    ]

    # The effective associations differ, and each answer keeps the request it came from.
    assert lca_basis["effective_mapped_background_process_pins"] == [steel_project.mapped_pin]
    assert cbam_basis["effective_mapped_background_process_pins"] == []
    assert cbam_basis["effective_background_process_pins"] == []
    # The basis records the demand this answer was actually calculated from: the saved workspace
    # demand as the request schema received it, so unset optional targets are explicit rather than
    # absent. Comparing the two shapes directly pins that nothing rewrote the activity data.
    assert _basis(lca)["demand"] == lca_basis["demand"]
    assert lca_basis["demand"] == [
        ProviderDemandItem.model_validate(item).model_dump(mode="json")
        for item in steel_project.workspace["demand"]
    ]
    assert [
        {key: value for key, value in item.items() if value is not None}
        for item in lca_basis["demand"]
    ] == steel_project.workspace["demand"]
    assert _basis(cbam)["source_model"] == {
        "graph_sha256": steel_project.stored_graph_sha256,
        "demand": steel_project.workspace["demand"],
        "background_process_pins": [],
        "mapped_background_process_pins": [steel_project.mapped_pin],
    }
    assert _basis(lca)["source_model"] == _basis(cbam)["source_model"]

    lca_run = steel_project.run(lca["provider_receipt"]["analysis_run_id"])
    cbam_run = steel_project.run(cbam["provider_receipt"]["analysis_run_id"])
    assert lca_run.id != cbam_run.id
    assert lca_run.request_sha256 != cbam_run.request_sha256
    assert lca_run.parameters["calculation_basis"] == lca_basis
    assert lca_run.provider_receipt["model_derivation"]["purpose"] == "lca"
    assert cbam_run.provider_receipt["model_derivation"]["purpose"] == "cbam"


def test_explicit_analysis_task_survives_the_frozen_http_solve(steel_project):
    legacy = steel_project.solve("lca")
    assert legacy.status_code == 201, legacy.text
    response = steel_project.solve("lca", analysis_task="mfa")
    assert response.status_code == 201, response.text
    frozen = response.json()
    assert frozen["id"] != legacy.json()["id"]
    assert frozen["solve_hash"] != legacy.json()["solve_hash"]
    assert frozen["provider_receipt"]["analysis_task"] == "mfa"
    run = steel_project.run(frozen["provider_receipt"]["analysis_run_id"])
    assert run.parameters["analysis_task"] == "mfa"


def test_an_identical_purpose_request_replays_the_frozen_answer_without_solving_again(
    steel_project,
):
    first = steel_project.solve("lca")
    assert first.status_code == 201, first.text
    first = first.json()
    solved = len(steel_project.solve_requests())

    again = steel_project.solve("lca")
    assert again.status_code == 201, again.text
    assert again.json() == first
    assert len(steel_project.solve_requests()) == solved
    assert [item["id"] for item in steel_project.snapshots()] == [first["id"]]

    other = steel_project.solve("cbam")
    assert other.status_code == 201, other.text
    assert other.json()["id"] != first["id"]
    assert len(steel_project.solve_requests()) == solved + 1


def test_the_cbam_purpose_sends_no_background_link_it_unbound(steel_project):
    assert steel_project.solve("lca").status_code == 201
    assert steel_project.solve("cbam").status_code == 201
    lca_request, cbam_request = steel_project.solve_requests()
    consumer = steel_project.mapped_pin["consumer_exchange_id"]

    assert lca_request["mapped_background_process_pins"] == [steel_project.mapped_pin]
    assert "mapped_background_process_pins" not in cbam_request
    assert "lcia_methods" not in cbam_request
    assert {item["exchange_id"] for item in cbam_request["elementary_flows"]} == {
        item["exchange_id"] for item in cbam_request["inline_snapshot"]["graph"]["metadata"]["elementary_flow_refs"]
    }
    assert lca_request["operation_hash"] != cbam_request["operation_hash"]

    # Both name the stored model they were derived from, and each sends its own derived graph.
    # The reviewed steel rule keeps every process, so these two hashes are equal by content; that
    # equality is not evidence of pruning. A pruned model is covered by
    # test_a_pruned_cbam_boundary_sends_a_smaller_derived_graph, on a labelled synthetic rule.
    assert lca_request["inline_snapshot"]["source_graph_hash"] == steel_project.stored_graph_sha256
    assert cbam_request["inline_snapshot"]["source_graph_hash"] == steel_project.stored_graph_sha256
    assert lca_request["inline_snapshot"]["graph_hash"] == cbam_request["inline_snapshot"]["graph_hash"]

    # Unbinding is not deleting: the input stays in the calculation model as a boundary input.
    node_id, port_id = consumer.split("::")
    sent_node = next(
        node for node in cbam_request["inline_snapshot"]["graph"]["nodes"] if node["id"] == node_id
    )
    assert any(port["id"] == port_id for port in sent_node["inputs"])
    assert not any(
        exchange.get("toNode") == node_id and exchange.get("targetPortId") == port_id
        for exchange in cbam_request["inline_snapshot"]["graph"]["exchanges"]
    )


def test_a_solve_without_a_purpose_freezes_the_basis_it_always_froze(steel_project):
    response = steel_project.solve(None)
    assert response.status_code == 201, response.text
    snapshot = response.json()
    assert _basis(snapshot) == {
        "schema_version": "nebula_one.provider-calculation-basis.v1",
        "demand": steel_project.workspace["demand"],
        "lcia_methods": None,
        "background_process_pins": [],
        "mapped_background_process_pins": [steel_project.mapped_pin],
    }
    run = steel_project.run(snapshot["provider_receipt"]["analysis_run_id"])
    assert "model_derivation" not in run.provider_receipt
    assert "calculation_basis" not in run.parameters
    # The whole stored model is sent, exactly as before purposes existed.
    sent = steel_project.solve_requests()[-1]
    assert "source_graph_hash" not in sent["inline_snapshot"]
    assert sent["inline_snapshot"]["graph_hash"] == steel_project.stored_graph_sha256
    assert sent["mapped_background_process_pins"] == [steel_project.mapped_pin]


def test_a_tampered_calculation_basis_refuses_the_recovered_run(steel_project):
    queued = steel_project.queue("lca")
    assert queued.status_code == 202, queued.text
    task = queued.json()["task"]
    run_id = queued.json()["run"]["id"]
    available = datetime.fromisoformat(task["available_at"].replace("Z", "+00:00"))

    def tamper(run):
        parameters = deepcopy(run.parameters)
        parameters["calculation_basis"]["demand"] = [
            {**parameters["calculation_basis"]["demand"][0], "amount": 1.0}
        ]
        run.parameters = parameters

    tampered = steel_project.mutate_run(run_id, tamper)
    assert tampered.parameters["calculation_basis"]["demand"][0]["amount"] == 1.0

    processed = steel_project.container.worker.process_one(
        worker_id="tamper-probe", lease_seconds=30, now=available + timedelta(seconds=1)
    )
    assert processed is not None and processed.id == task["id"]
    assert processed.status == "failed"
    assert processed.last_error["code"] == "MODEL_PROCESSING_BASIS_DRIFT"
    assert processed.last_error["details"]["expected_basis_sha256"] == tampered.parameters[
        "calculation_basis"
    ]["basis_sha256"]
    assert steel_project.snapshots() == []
    assert steel_project.solve_requests() == []


def test_a_tampered_engine_receipt_refuses_to_freeze_the_answer(steel_project):
    frozen = steel_project.solve("lca")
    assert frozen.status_code == 201, frozen.text
    frozen = frozen.json()
    run_id = frozen["provider_receipt"]["analysis_run_id"]

    def tamper(run):
        receipt = deepcopy(run.provider_receipt)
        receipt["model_derivation"]["basis"]["derived_graph_sha256"] = "0" * 64
        run.provider_receipt = receipt

    steel_project.mutate_run(run_id, tamper)
    refused = steel_project.solve("lca")
    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "PROVIDER_SOLVE_DERIVATION_MISMATCH"
    assert error["details"]["analysis_run_id"] == run_id
    assert error["details"]["executed_basis_sha256"] != error["details"]["expected_basis_sha256"]
    # The refusal freezes nothing new and leaves the answer that was frozen readable.
    assert [item["id"] for item in steel_project.snapshots()] == [frozen["id"]]
    assert len(steel_project.solve_requests()) == 1


def test_a_queued_run_recovers_after_a_restart_under_its_accepted_rule_identity(
    steel_project, engine_transport, monkeypatch
):
    queued = steel_project.queue("cbam")
    assert queued.status_code == 202, queued.text
    payload = queued.json()
    run_id, task = payload["run"]["id"], payload["task"]
    available = datetime.fromisoformat(task["available_at"].replace("Z", "+00:00"))
    accepted = steel_project.run(run_id).parameters["calculation_basis"]
    assert steel_project.solve_requests() == []

    # The reviewed binding moves on while the run is queued: recovery must not follow it.
    monkeypatch.setattr(
        "nebula_one.services.model_processing_runtime.load_model_processing_rules_for_template",
        _rules_binding_unavailable,
    )
    assert steel_project.solve("cbam").status_code == 409

    restarted = create_app(
        Settings(
            database_url=steel_project.database_url,
            nebula_lca_base_url="http://nebula-lca.test",
            nebula_lca_timeout_seconds=5,
        ),
        engine_transport=engine_transport,
    )
    with TestClient(restarted) as recovered_client:
        processed = recovered_client.app.state.container.worker.process_one(
            worker_id="worker-after-restart",
            lease_seconds=30,
            now=available + timedelta(seconds=1),
        )
        assert processed is not None and processed.id == task["id"]
        assert processed.status == "completed", processed.last_error
        frozen = recovered_client.get(
            f"/api/v1/applications/{steel_project.application_id}/solved-system-snapshots"
        ).json()

    assert len(frozen) == 1
    executed = _derivation(frozen[0])
    assert executed == accepted
    assert executed["model_processing_rules"] == RULES_IDENTITY
    assert executed["template"] == TEMPLATE_IDENTITY
    assert executed["purpose"] == "cbam"
    assert steel_project.run(run_id).provider_receipt["model_derivation"]["basis"] == accepted

    sent = steel_project.solve_requests()
    assert len(sent) == 1
    assert sent[0]["inline_snapshot"]["source_graph_hash"] == steel_project.stored_graph_sha256
    assert "mapped_background_process_pins" not in sent[0]


def test_a_native_climate_total_refuses_a_purpose_that_unbound_every_provider(steel_project):
    refused = steel_project.solve("cbam", native_background_climate=True)
    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "MODEL_DERIVATION_NATIVE_CLIMATE_UNLINKED"
    assert error["details"]["calculation_purpose"] == "cbam"
    assert error["details"]["unlinked_consumer_exchange_ids"] == [
        steel_project.mapped_pin["consumer_exchange_id"]
    ]
    assert "请改选保留背景关联的核算口径" in error["message"]
    # Nothing was accepted, solved or frozen for a request that could not be answered.
    assert steel_project.snapshots() == []
    assert steel_project.solve_requests() == []


def test_ef_default_uses_the_effective_cbam_source_after_reviewed_unlink(steel_project):
    frozen = steel_project.solve("cbam", climate_default=True)
    assert frozen.status_code == 201, frozen.text
    snapshot = frozen.json()
    run = steel_project.run(snapshot["provider_receipt"]["analysis_run_id"])
    assert run.parameters["calculation_method"]["reference"] == "pcf.iron-steel.ef31-model@1.0.0"
    assert run.parameters["lcia_methods"] == ["EF v3.1"]
    assert run.parameters["calculation_basis"]["effective_mapped_background_process_pins"] == []
    assert "mapped_background_process_pins" not in steel_project.solve_requests()[0]


def test_a_complete_model_solves_with_no_user_method_ref_yet_still_carries_the_base_characterization(steel_project):
    # P4 gate 无规则完整LCIA: a complete model is computed directly, without the operator having to
    # create or cite any calculation_method_ref, but the solve MUST still carry an applicable base
    # characterization method (a non-empty LCIA indicator + its registered package). It must never
    # fold in a user scheme it was not given, so nothing "last edited" can leak into the answer.
    frozen = steel_project.solve("lca", climate_default=True)
    assert frozen.status_code == 201, frozen.text
    snapshot = frozen.json()
    run = steel_project.run(snapshot["provider_receipt"]["analysis_run_id"])
    parameters = run.parameters
    # No user rule was required or cited.
    assert "calculation_method_ref" not in parameters
    # The base characterization method travels with the run: a registered package reference and a
    # non-empty indicator, resolved by the climate-default path rather than by any user scheme.
    assert parameters["calculation_method"]["reference"]
    assert parameters["lcia_methods"] == ["EF v3.1"]
    # The complete model did not read or misuse a user calculation method: none is frozen into the
    # receipt, because the user-method seam is only entered when a ref is present.
    assert run.provider_receipt.get("user_calculation_method") is None
    # The engine request itself carried the base indicator, so the characterization is real, not a
    # client-side label.
    sent = steel_project.solve_requests()[-1]
    assert sent["lcia_methods"] == ["EF v3.1"]


def test_a_new_rule_version_leaves_an_already_frozen_answer_alone(steel_project, monkeypatch):
    frozen = steel_project.solve("lca")
    assert frozen.status_code == 201, frozen.text
    frozen = frozen.json()

    monkeypatch.setattr(
        "nebula_one.services.model_processing_runtime.load_model_processing_rules_for_template",
        _rules_binding_unavailable,
    )
    reread = steel_project.snapshots()
    assert [item["id"] for item in reread] == [frozen["id"]]
    assert reread[0]["content_sha256"] == frozen["content_sha256"]
    assert _derivation(reread[0])["model_processing_rules"] == RULES_IDENTITY

    # A new request binds whatever the template binds now, and is refused rather than silently
    # reusing the answer that was calculated under the older reviewed rules.
    refused = steel_project.solve("lca")
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "MODEL_PROCESSING_RULES_VERSION_UNAVAILABLE"
    assert [item["id"] for item in steel_project.snapshots()] == [frozen["id"]]
    assert len(steel_project.solve_requests()) == 1


def test_a_cbam_trial_reads_the_purpose_it_was_derived_under_and_refuses_another(steel_project):
    lca = steel_project.solve("lca").json()
    cbam = steel_project.solve("cbam").json()
    service = steel_project.container.cbam_trials
    with steel_project.container.database.session() as db:
        package = require_method_package(db, EFFECTIVE_METHOD_PIN)
        cbam_row = db.get(SolvedSystemSnapshot, cbam["id"])
        derivation = service._derivation(db, cbam_row)
        assert derivation is not None and derivation.purpose == "cbam"
        assert derivation.basis_sha256 == _derivation(cbam)["basis_sha256"]
        assert derivation.basis == {
            key: value
            for key, value in _derivation(cbam).items()
            if key != "basis_sha256"
        }
        service._require_derivation_methods(derivation, package, cbam_row)
        # A CBAM answer reads the derived calculation model, not the whole stored model.
        assert service._frozen_graph(db, cbam_row, derivation) == derivation.derived.graph
        identity = service._revision_identity(db, cbam_row, derivation)
        assert identity["source_graph_sha256"] == steel_project.stored_graph_sha256
        assert identity["graph_sha256"] == derivation.derived.derived_graph_sha256
        assert identity["calculation_purpose"] == "cbam"
        assert identity["model_derivation_basis_sha256"] == derivation.basis_sha256

        lca_row = db.get(SolvedSystemSnapshot, lca["id"])
        lca_derivation = service._derivation(db, lca_row)
        assert lca_derivation is not None and lca_derivation.purpose == "lca"
        with pytest.raises(DomainError) as refused:
            service._require_derivation_methods(lca_derivation, package, lca_row)
        assert refused.value.code == "CBAM_TRIAL_DERIVATION_METHOD_MISMATCH"
        assert refused.value.status_code == 409
        assert refused.value.details["calculation_purpose"] == "lca"
        assert refused.value.details["requested_method_package"] == EFFECTIVE_METHOD_PIN
        assert refused.value.details["derivation_method_packages"] == []


def test_a_cbam_trial_refuses_a_frozen_answer_whose_basis_no_longer_reproduces(steel_project):
    cbam = steel_project.solve("cbam").json()
    run_id = cbam["provider_receipt"]["analysis_run_id"]
    service = steel_project.container.cbam_trials

    def tamper(run):
        parameters = deepcopy(run.parameters)
        parameters["calculation_basis"]["effective_mapped_background_process_pins"] = [
            steel_project.mapped_pin
        ]
        run.parameters = parameters

    steel_project.mutate_run(run_id, tamper)
    with steel_project.container.database.session() as db:
        row = db.get(SolvedSystemSnapshot, cbam["id"])
        with pytest.raises(DomainError) as refused:
            service._derivation(db, row)
    assert refused.value.code == "CBAM_TRIAL_DERIVATION_UNRESOLVED"
    assert refused.value.details["analysis_run_id"] == run_id


def test_a_cbam_trial_refuses_a_derivation_of_another_frozen_model(steel_project):
    """A purpose-specific read swaps in the derived graph, so the source hash is the only tie back.

    Nothing else would notice a basis derived from a model other than the revision this snapshot
    points at: the derived graph carries the purpose's edits, and its hashes are self-consistent.
    """
    cbam = steel_project.solve("cbam").json()
    service = steel_project.container.cbam_trials
    steel_project.mutate_revision(lambda revision: setattr(revision, "graph_sha256", "0" * 64))

    with steel_project.container.database.session() as db:
        row = db.get(SolvedSystemSnapshot, cbam["id"])
        derivation = service._derivation(db, row)
        assert derivation is not None
        with pytest.raises(DomainError) as refused:
            service._revision_identity(db, row, derivation)

    assert refused.value.code == "CBAM_TRIAL_DERIVATION_UNRESOLVED"
    assert refused.value.status_code == 409
    assert refused.value.details["solved_snapshot_id"] == cbam["id"]
    assert (
        refused.value.details["basis_source_graph_sha256"]
        == steel_project.stored_graph_sha256
    )
    assert refused.value.details["revision_graph_sha256"] == "0" * 64


def test_a_snapshot_without_a_purpose_keeps_the_identity_it_always_read(steel_project):
    legacy = steel_project.solve(None)
    assert legacy.status_code == 201, legacy.text
    legacy = legacy.json()
    service = steel_project.container.cbam_trials
    with steel_project.container.database.session() as db:
        row = db.get(SolvedSystemSnapshot, legacy["id"])
        derivation = service._derivation(db, row)
        assert derivation is None
        revision = db.get(SystemRevision, steel_project.revision_id)
        assert service._frozen_graph(db, row, derivation) == revision.graph_snapshot
        identity = service._revision_identity(db, row, derivation)
        assert identity["graph_sha256"] == steel_project.stored_graph_sha256
        assert "source_graph_sha256" not in identity
        assert "calculation_purpose" not in identity
        assert "model_derivation_basis_sha256" not in identity


PRUNED_PROCESS = "secondary-metallurgy-and-degassing"
PRUNED_CROSSING_EXCHANGE = "treated-steel-in"


def _synthetic_pruned_rules_and_package():
    """Build a labelled synthetic rule/method pair whose CBAM boundary excludes one in-model process.

    The reviewed steel rule keeps all five processes, so no shipped package can show the running
    solve actually shrinking the model. This is test scaffolding: it is not regulatory content, it is
    not published under ``cases/``, and nothing derived from it is acceptance evidence.
    """
    graph = _graph()
    dropped = next(
        node["process_uuid"] for node in graph["nodes"] if node["id"] == PRUNED_PROCESS
    )
    manifest = deepcopy(EFFECTIVE_PACKAGE["manifest"])
    boundary = manifest["boundary_schema"]["production_process_boundary"]
    assert dropped in boundary["in_boundary_process_uuids"]
    boundary["in_boundary_process_uuids"] = [
        uuid for uuid in boundary["in_boundary_process_uuids"] if uuid != dropped
    ]
    package = MethodPackageCreate.model_validate(
        {
            "package_id": "synthetic.steel-cbam-pruned-boundary",
            "version": "1.0.0",
            "package_kind": EFFECTIVE_PACKAGE["package_kind"],
            "jurisdiction": EFFECTIVE_PACKAGE.get("jurisdiction"),
            "manifest": manifest,
        }
    ).model_dump(mode="json")
    content = deepcopy(
        json.loads(
            Path(
                "src/nebula_one/resources/model_processing/steel-bf-bof-model-processing-1.0.11.json"
            ).read_text(encoding="utf-8")
        )["content"]
    )
    cbam = content["purposes"]["cbam"]
    cbam["process_selection"]["method_package"] = {
        key: package[key] for key in ("package_id", "version")
    } | {"content_sha256": canonical_json_sha256(package)}
    cbam["cross_boundary_connections"] = {
        "mode": "reject_undeclared",
        "boundary_exchanges": [
            {
                "exchange_id": f"continuous-casting::{PRUNED_CROSSING_EXCHANGE}",
                "disposition": "keep_as_boundary_input",
                "amount_source": "consumer_port_amount",
                "clause": "SYNTHETIC PRUNE: scaffolding only, not a reviewed clause",
            }
        ],
    }
    rules = ModelProcessingRules(
        {
            "schema_version": "nebula_one.model-processing-rules.v1",
            "package_id": "synthetic.steel-pruned.model-processing",
            "version": "1.0.0",
            "content": content,
            "content_sha256": canonical_json_sha256(content),
        },
        "synthetic-prune-test.json",
    )
    return rules, package


def test_a_pruned_cbam_boundary_sends_a_smaller_derived_graph(steel_project, monkeypatch):
    rules, package = _synthetic_pruned_rules_and_package()
    with steel_project.container.database.session() as db:
        db.add(
            MethodPackage(
                package_id=package["package_id"],
                version=package["version"],
                package_kind=package["package_kind"],
                jurisdiction=package.get("jurisdiction"),
                manifest=package["manifest"],
                content_sha256=canonical_json_sha256(package),
                status="registered",
            )
        )
        db.commit()
    monkeypatch.setattr(
        "nebula_one.services.model_processing_runtime.load_model_processing_rules_for_template",
        lambda _template_id, **_kwargs: rules,
    )
    # The worker re-derives under the identity the request was accepted with; a synthetic package
    # exists nowhere on disk, so that lookup is stood down to the same in-memory rules.
    monkeypatch.setattr(
        "nebula_one.services.model_processing_runtime.load_model_processing_rules_by_reference",
        lambda **reference: rules
        if reference == {key: getattr(rules, key) for key in
                         ("package_id", "version", "content_sha256")}
        else _rules_binding_unavailable(),
    )

    lca = steel_project.solve("lca")
    assert lca.status_code == 201, lca.text
    cbam = steel_project.solve("cbam")
    assert cbam.status_code == 201, cbam.text
    lca_request, cbam_request = steel_project.solve_requests()
    stored = steel_project.stored_graph_sha256
    stored_nodes = {node["id"] for node in _graph()["nodes"]}

    # The lifecycle purpose still sends the whole stored model.
    assert {
        node["id"] for node in lca_request["inline_snapshot"]["graph"]["nodes"]
    } == stored_nodes
    assert lca_request["inline_snapshot"]["graph_hash"] == stored

    # The pruned purpose sends a smaller calculation model that still names the model it came from.
    assert {
        node["id"] for node in cbam_request["inline_snapshot"]["graph"]["nodes"]
    } == stored_nodes - {PRUNED_PROCESS}
    assert cbam_request["inline_snapshot"]["source_graph_hash"] == stored
    assert cbam_request["inline_snapshot"]["graph_hash"] not in {
        stored,
        lca_request["inline_snapshot"]["graph_hash"],
    }

    frozen = _derivation(cbam.json())
    assert frozen["source_graph_sha256"] == stored
    assert frozen["derived_graph_sha256"] == cbam_request["inline_snapshot"]["graph_hash"]
    assert frozen["derived_graph_sha256"] != stored
    assert frozen["model_processing_rules"]["package_id"] == rules.package_id
    assert {item["package_id"] for item in frozen["method_packages"]} == {
        package["package_id"],
        EFFECTIVE_PACKAGE["package_id"],
    }

    # Cutting the supplier leaves the consumer port in place with its saved activity data, and the
    # edge that used to feed it is gone rather than silently rerouted.
    crossing = next(
        node
        for node in cbam_request["inline_snapshot"]["graph"]["nodes"]
        if node["id"] == "continuous-casting"
    )
    sent_port = next(p for p in crossing["inputs"] if p["id"] == PRUNED_CROSSING_EXCHANGE)
    stored_port = next(
        p
        for node in _graph()["nodes"]
        if node["id"] == "continuous-casting"
        for p in node["inputs"]
        if p["id"] == PRUNED_CROSSING_EXCHANGE
    )
    assert (sent_port["amount"], sent_port["unit"]) == (stored_port["amount"], stored_port["unit"])
    assert not any(
        exchange.get("toNode") == "continuous-casting"
        and exchange.get("targetPortId") == PRUNED_CROSSING_EXCHANGE
        for exchange in cbam_request["inline_snapshot"]["graph"]["exchanges"]
    )


SYNTHETIC_RULES_ID = "synthetic.steel-classified.model-processing"
SYNTHETIC_PACKAGE_ID = "synthetic.steel-cbam-one-emission-excluded"
# A blast-furnace raceway emission chosen because a sibling emission on the same process stays in, so
# the pair shows the decision is per exchange and not per process or per flow.
SYNTHETIC_EXCLUDED_EMISSION = "blast-furnace::co2-bf-raceway-out"
SYNTHETIC_KEPT_SIBLING = "blast-furnace::co2-bf-reduction-out"


def _emission_ports(graph):
    return {
        f"{node['id']}::{port['id']}": (node, port)
        for node in graph["nodes"]
        for side in ("inputs", "outputs")
        for port in node[side]
        if port.get("type") == "biosphere"
    }


def test_derived_elementary_refs_skip_only_reviewed_exclusions():
    graph = _graph()
    excluded = SYNTHETIC_EXCLUDED_EMISSION
    node_id, port_id = excluded.split("::")
    node = next(item for item in graph["nodes"] if item["id"] == node_id)
    node["outputs"] = [item for item in node["outputs"] if item["id"] != port_id]
    refs = _provider_elementary_flow_refs(
        graph, reviewed_excluded_exchange_ids={excluded}
    )
    assert excluded not in {item["exchange_id"] for item in refs}
    with pytest.raises(DomainError) as error:
        _provider_elementary_flow_refs(graph)
    assert error.value.code == "ELEMENTARY_FLOW_REFERENCE_UNKNOWN_EXCHANGE"
    graph["metadata"]["elementary_flow_refs"].append(
        {**graph["metadata"]["elementary_flow_refs"][0], "exchange_id": "unreviewed::unknown"}
    )
    with pytest.raises(DomainError) as error:
        _provider_elementary_flow_refs(graph, reviewed_excluded_exchange_ids={excluded})
    assert error.value.code == "ELEMENTARY_FLOW_REFERENCE_UNKNOWN_EXCHANGE"


def _synthetic_classifying_rules_and_package():
    """A labelled synthetic rule/method pair that counts every steel emission but one.

    The reviewed steel basis pre-limits its emissions, so no shipped package can show one reviewed
    emission selection travelling through a running solve. This is test scaffolding: it is not
    regulatory content, it is not published under ``cases/``, and no number computed from it is
    acceptance evidence. The identities each decision carries are read from the stored model itself,
    because a fixture that invented one would prove the gate by weakening it.
    """
    ports = _emission_ports(_graph())
    assert SYNTHETIC_EXCLUDED_EMISSION in ports and SYNTHETIC_KEPT_SIBLING in ports
    decisions = [
        {
            "exchange_id": exchange_id,
            "process_uuid": node["process_uuid"],
            "disposition": "exclude"
            if exchange_id == SYNTHETIC_EXCLUDED_EMISSION
            else "include",
            "clause": f"SYNTHETIC CLASSIFY {exchange_id}: scaffolding only, not a reviewed clause",
            "greenhouse_gas": "CO2",
            **{
                _FLOW_IDENTITY_FIELDS[port_key]: port[port_key]
                for port_key in _REQUIRED_FLOW_IDENTITY
            },
        }
        for exchange_id, (node, port) in sorted(ports.items())
    ]

    manifest = deepcopy(EFFECTIVE_PACKAGE["manifest"])
    manifest["classification_rules"]["exchange_decisions"] = decisions
    package = MethodPackageCreate.model_validate(
        {
            "package_id": SYNTHETIC_PACKAGE_ID,
            "version": "1.0.0",
            "package_kind": EFFECTIVE_PACKAGE["package_kind"],
            "jurisdiction": EFFECTIVE_PACKAGE.get("jurisdiction"),
            "manifest": manifest,
        }
    ).model_dump(mode="json")
    package_ref = {key: package[key] for key in ("package_id", "version")} | {
        "content_sha256": canonical_json_sha256(package)
    }

    content = deepcopy(
        json.loads(
            Path(
                "src/nebula_one/resources/model_processing/steel-bf-bof-model-processing-1.0.11.json"
            ).read_text(encoding="utf-8")
        )["content"]
    )
    cbam = content["purposes"]["cbam"]
    cbam["process_selection"]["method_package"] = package_ref
    cbam["elementary_flows"] = {
        "mode": "explicit_flow_rules",
        "evidence": {
            "method_package": package_ref,
            "manifest_path": "classification_rules.exchange_decisions",
        },
    }
    rules = ModelProcessingRules(
        {
            "schema_version": "nebula_one.model-processing-rules.v1",
            "package_id": SYNTHETIC_RULES_ID,
            "version": "1.0.0",
            "content": content,
            "content_sha256": canonical_json_sha256(content),
        },
        "synthetic-classify-test.json",
    )
    return rules, package


def _bind_synthetic_rules(steel_project, monkeypatch, rules, package):
    """Register a synthetic package and stand down only the on-disk lookups it cannot use."""
    with steel_project.container.database.session() as db:
        db.add(
            MethodPackage(
                package_id=package["package_id"],
                version=package["version"],
                package_kind=package["package_kind"],
                jurisdiction=package.get("jurisdiction"),
                manifest=package["manifest"],
                content_sha256=canonical_json_sha256(package),
                status="registered",
            )
        )
        db.commit()
    monkeypatch.setattr(
        "nebula_one.services.model_processing_runtime.load_model_processing_rules_for_template",
        lambda _template_id, **_kwargs: rules,
    )
    # The worker re-derives under the identity the request was accepted with; a synthetic package
    # exists nowhere on disk, so that lookup is stood down to the same in-memory rules.
    monkeypatch.setattr(
        "nebula_one.services.model_processing_runtime.load_model_processing_rules_by_reference",
        lambda **reference: rules
        if reference
        == {key: getattr(rules, key) for key in ("package_id", "version", "content_sha256")}
        else _rules_binding_unavailable(),
    )


def _sent_ports(request):
    graph = request["inline_snapshot"]["graph"]
    return {
        f"{node['id']}::{port['id']}"
        for node in graph["nodes"]
        for side in ("inputs", "outputs")
        for port in node[side]
    }


def test_one_reviewed_emission_selection_reaches_the_request_the_receipt_and_the_read(
    steel_project, monkeypatch
):
    rules, package = _synthetic_classifying_rules_and_package()
    _bind_synthetic_rules(steel_project, monkeypatch, rules, package)

    lca = steel_project.solve("lca")
    assert lca.status_code == 201, lca.text
    cbam = steel_project.solve("cbam")
    assert cbam.status_code == 201, cbam.text
    lca_request, cbam_request = steel_project.solve_requests()

    # The engine is handed the calculation model the reviewed selection cut, not the stored model: a
    # note in a receipt would not stop it characterising an emission nothing classified in.
    assert SYNTHETIC_EXCLUDED_EMISSION in _sent_ports(lca_request)
    assert SYNTHETIC_EXCLUDED_EMISSION not in _sent_ports(cbam_request)
    assert SYNTHETIC_KEPT_SIBLING in _sent_ports(cbam_request)

    stamp = steel_project.run(
        cbam.json()["provider_receipt"]["analysis_run_id"]
    ).provider_receipt["model_derivation"]
    selection = stamp["flow_selection"]
    assert selection["mode"] == "explicit_flow_rules"
    assert selection["excluded_exchange_ids"] == [SYNTHETIC_EXCLUDED_EMISSION]
    assert SYNTHETIC_KEPT_SIBLING in selection["included_exchange_ids"]
    assert selection["method_package"]["content_sha256"] == canonical_json_sha256(package)
    assert selection["manifest_path"] == "classification_rules.exchange_decisions"
    assert {item["state"] for item in selection["decisions"]} == {"included", "excluded"}

    # The graph the engine was given has exactly the reviewed selection's emissions left on it, so the
    # answer cannot be computed from a wider or narrower set than the one the receipt states.
    stored_emissions = set(_emission_ports(_graph()))
    assert stored_emissions & _sent_ports(cbam_request) == set(selection["included_exchange_ids"])
    assert stored_emissions & _sent_ports(lca_request) == stored_emissions

    # The lifecycle purpose decides nothing exchange by exchange, so it records no selection at all.
    lca_stamp = steel_project.run(
        lca.json()["provider_receipt"]["analysis_run_id"]
    ).provider_receipt["model_derivation"]
    assert lca_stamp["flow_selection"] is None

    service = steel_project.container.cbam_trials
    with steel_project.container.database.session() as db:
        row = db.get(SolvedSystemSnapshot, cbam.json()["id"])
        derivation = service._derivation(db, row)
        assert flow_selection_of(derivation.derived) == selection
        service._require_recorded_selection(db, row, selection)
        # A read that resolved a selection of its own has to say so, not quietly recount.
        with pytest.raises(DomainError) as refused:
            service._require_recorded_selection(db, row, None)
        assert refused.value.code == "CBAM_TRIAL_FLOW_SELECTION_UNRECORDED"
        assert refused.value.details["recorded_flow_selection"] == selection

    # And a receipt that carries no counted set is not a receipt that counted nothing: the reading
    # refuses rather than answering from whatever the whole stored model happens to hold.
    run_id = cbam.json()["provider_receipt"]["analysis_run_id"]

    def drop_selection(run):
        receipt = deepcopy(run.provider_receipt)
        del receipt["model_derivation"]["flow_selection"]
        run.provider_receipt = receipt

    steel_project.mutate_run(run_id, drop_selection)
    with steel_project.container.database.session() as fresh_db:
        fresh = fresh_db.get(SolvedSystemSnapshot, cbam.json()["id"])
        with pytest.raises(DomainError) as dropped:
            service._require_recorded_selection(fresh_db, fresh, selection)
        assert dropped.value.code == "CBAM_TRIAL_FLOW_SELECTION_UNRECORDED"
        assert dropped.value.details["recorded_flow_selection"] is None
        assert dropped.value.details["derived_flow_selection"] == selection


def test_a_receipt_that_rewrites_the_counted_set_refuses_the_freeze(
    steel_project, monkeypatch
):
    rules, package = _synthetic_classifying_rules_and_package()
    _bind_synthetic_rules(steel_project, monkeypatch, rules, package)
    frozen = steel_project.solve("cbam")
    assert frozen.status_code == 201, frozen.text
    frozen = frozen.json()
    run_id = frozen["provider_receipt"]["analysis_run_id"]

    def tamper(run):
        receipt = deepcopy(run.provider_receipt)
        counted = receipt["model_derivation"]["flow_selection"]
        counted["included_exchange_ids"] = sorted(
            {*counted["included_exchange_ids"], SYNTHETIC_EXCLUDED_EMISSION}
        )
        counted["excluded_exchange_ids"] = []
        run.provider_receipt = receipt

    steel_project.mutate_run(run_id, tamper)
    refused = steel_project.solve("cbam")
    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "PROVIDER_SOLVE_DERIVATION_MISMATCH"
    assert error["details"]["recorded_flow_selection"]["excluded_exchange_ids"] == []
    assert error["details"]["expected_flow_selection"]["excluded_exchange_ids"] == [
        SYNTHETIC_EXCLUDED_EMISSION
    ]
    # Nothing new froze, and the answer that was frozen is still listed.
    assert [item["id"] for item in steel_project.snapshots()] == [frozen["id"]]


def test_solve_freezes_referenced_user_method_and_older_records_stay_fixed(client, steel_project):
    """§3/§4/§5 at the calculation seam, over real HTTP against the synthetic transport.

    A validated method version is referenced by exact id + version + hash, its identity and
    immutable rule snapshot are frozen into the snapshot provenance, and a later new method
    version cannot rewrite that earlier record. No number here is a live-engine answer; what is
    real is the reference re-check, the persisted provenance and the frozen-record immutability.
    """
    ro = _save_reference_output(client, steel_project, 1500)
    application_id = steel_project.application_id
    method_id, content_hash, rule = _ready_organization_method(client, application_id, ro["revision_id"])

    solved = client.post(
        f"/api/v1/applications/{application_id}/system-revisions/{ro['revision_id']}/solve",
        json={
            "demand": ro["demand"],
            "mapped_background_process_pins": ro["mapped_background_process_pins"],
            "calculation_purpose": "lca",
            "calculation_method_ref": {"method_id": method_id, "version": 1, "content_sha256": content_hash},
        },
    )
    assert solved.status_code == 201, solved.text
    snapshot = solved.json()

    with steel_project.container.database.session() as db:
        row = db.get(SolvedSystemSnapshot, snapshot["id"])
        frozen_method = row.provider_receipt["user_calculation_method"]
    assert frozen_method["method_id"] == method_id
    assert frozen_method["version"] == 1
    assert frozen_method["content_sha256"] == content_hash
    assert frozen_method["model_revision_id"] == ro["revision_id"]
    assert frozen_method["rules"] == [rule]

    # The user then saves a new method version (head moves to v2), but the frozen record is fixed.
    moved = client.put(
        f"/api/v1/calculation-methods/{method_id}/versions/1",
        json={
            "rules": [{**rule, "location_role": "purchased_energy", "scope": "scope_2"}],
            "expected_content_sha256": content_hash,
        },
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["latest_version"] == 2

    with steel_project.container.database.session() as db:
        row = db.get(SolvedSystemSnapshot, snapshot["id"])
        still_frozen = row.provider_receipt["user_calculation_method"]
    assert still_frozen["version"] == 1
    assert still_frozen["content_sha256"] == content_hash
    assert still_frozen["rules"] == [rule]


def test_a_user_variant_narrows_the_reviewed_derivation_at_the_deriver_seam():
    """R4.2: a variant's exclusion drives the same formal pipeline a reviewed exclusion does.

    Not a test of the compiler (pure, covered in ``test_cbam_user_selection.py``): it is the
    wiring seam. The overlay is threaded through ``derive_calculation_model``, and the sibling
    emission leaves ``included_exchange_ids``, lands in ``excluded_exchange_ids`` with a clause
    naming the variant's exact source version, and is physically cut from the derived graph so
    what reaches the engine cannot count it. No HTTP, no synthetic transport, no numbers.
    """
    rules, package = _synthetic_classifying_rules_and_package()
    method = dict(package, content_sha256=canonical_json_sha256(package))
    packages = [dict(EFFECTIVE_PACKAGE), method]
    graph = _graph()
    blast = next(node for node in graph["nodes"] if node["id"] == "blast-furnace")
    demand = [{"process_uuid": blast["process_uuid"], "amount": 1, "unit": "kg"}]
    source = {"method_id": "user.variant.steel-bf-bof", "version": 3, "content_sha256": "a" * 64}
    overlay = {
        "source": source,
        "rules": [{
            "process_instance_id": "blast-furnace",
            "exchange_id": SYNTHETIC_KEPT_SIBLING,
            "boundary": "exclude",
            "cbam_relevant": True,
            "contribution_target": "direct",
        }],
    }

    base = derive_calculation_model(
        graph=deepcopy(graph), demand=demand, rules=rules, purpose="cbam", method_packages=packages
    )
    narrowed = derive_calculation_model(
        graph=deepcopy(graph), demand=demand, rules=rules, purpose="cbam",
        method_packages=packages, user_selection=overlay,
    )
    base_selection = flow_selection_of(base)
    selection = flow_selection_of(narrowed)

    # The overlay removes exactly one emission and leaves every other decision alone.
    assert selection["mode"] == "explicit_flow_rules"
    assert selection["excluded_exchange_ids"] == sorted(
        set(base_selection["excluded_exchange_ids"]) | {SYNTHETIC_KEPT_SIBLING}
    )
    assert SYNTHETIC_KEPT_SIBLING not in selection["included_exchange_ids"]
    assert set(selection["included_exchange_ids"]) == (
        set(base_selection["included_exchange_ids"]) - {SYNTHETIC_KEPT_SIBLING}
    )

    # The narrowed decision carries a clause naming the exact immutable source version, so the
    # frozen answer and the report can trace it back; the reviewed exclusions keep their own clause.
    decision = next(item for item in selection["decisions"] if item["exchange_id"] == SYNTHETIC_KEPT_SIBLING)
    assert decision["state"] == "excluded"
    assert decision["clause"] == (
        f"user-variant-exclusion@{source['method_id']}@{source['version']}#{source['content_sha256']}"
    )

    # The sibling port is physically gone from the derived graph, so the engine cannot compute a
    # value for an emission the operator excluded; every other emission the base kept is still on it.
    ports_after = set(_emission_ports(narrowed.graph))
    ports_base = set(_emission_ports(base.graph))
    assert ports_after == ports_base - {SYNTHETIC_KEPT_SIBLING}
    assert SYNTHETIC_EXCLUDED_EMISSION not in ports_after


def test_a_user_variant_on_the_shipped_prelimited_cbam_basis_refuses_closed():
    """Fail closed, do not silently ignore: the shipped basis counts a whole pre-limited set.

    The template the shipped steel CBAM package uses declares no per-exchange decision to narrow,
    so a variant that would take an emission out cannot express that through the reviewed machinery
    and the deriver refuses rather than answering with the whole regulated set as though the
    operator's boundary had been applied. A variant that narrows nothing still runs the reviewed
    package unchanged -- the overlay is only a refusal when it would actually take something out.
    """
    rules = load_model_processing_rules_for_template(_template_identity())
    graph = _graph()
    blast = next(node for node in graph["nodes"] if node["id"] == "blast-furnace")
    demand = [{"process_uuid": blast["process_uuid"], "amount": 1, "unit": "kg"}]
    overlay = {
        "source": {"method_id": "user.variant.steel-bf-bof", "version": 1, "content_sha256": "b" * 64},
        "rules": [{
            "process_instance_id": "blast-furnace",
            "exchange_id": SYNTHETIC_KEPT_SIBLING,
            "boundary": "exclude",
            "cbam_relevant": True,
        }],
    }

    with pytest.raises(DomainError) as refused:
        derive_calculation_model(
            graph=deepcopy(graph), demand=demand, rules=rules, purpose="cbam",
            method_packages=[dict(EFFECTIVE_PACKAGE)], user_selection=overlay,
        )
    assert refused.value.code == "MODEL_PROCESSING_USER_SELECTION_MODE_UNSUPPORTED"
    assert refused.value.details["mode"] == "template_prelimited"

    # A variant that excludes nothing still derives exactly the reviewed pre-limited set.
    empty_overlay = {"source": overlay["source"], "rules": []}
    derived = derive_calculation_model(
        graph=deepcopy(graph), demand=demand, rules=rules, purpose="cbam",
        method_packages=[dict(EFFECTIVE_PACKAGE)], user_selection=empty_overlay,
    )
    assert flow_selection_of(derived) is None
    plain = derive_calculation_model(
        graph=deepcopy(graph), demand=demand, rules=rules, purpose="cbam",
        method_packages=[dict(EFFECTIVE_PACKAGE)],
    )
    assert flow_selection_of(plain) is None
    assert derived.derived_graph_sha256 == plain.derived_graph_sha256


def _ready_cbam_variant(client, application_id, revision_id, excluded_exchange_id):
    """Create and validate a CBAM variant that excludes one emission exchange, return (id, v, hash).

    The variant is created directly (not cloned from a source) so it can be validated against
    synthetic rules that name one exchange and take it out; the exchange is CBAM-relevant, which
    R4.1 established is a legal narrowing rather than a conflict.
    """
    boundary = client.post(
        f"/api/v1/applications/{application_id}/boundaries",
        json={"name": "R4.3 variant boundary", "boundary_type": "cbam_production"},
    )
    assert boundary.status_code == 201, boundary.text
    boundary_id = boundary.json()["id"]
    node, _, _ = excluded_exchange_id.partition("::")
    created = client.post(
        f"/api/v1/applications/{application_id}/calculation-methods",
        json={
            "name": "Steel BF-BOF minus one emission",
            "purpose": "cbam",
            "model_revision_id": revision_id,
            "cbam_boundary_ref": boundary_id,
            "rules": [
                {
                    "process_instance_id": node,
                    "exchange_id": excluded_exchange_id,
                    "direction": "emission",
                    "boundary_status": "excluded",
                    "cbam_relevant": True,
                    "classification_basis": "user",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    method_id = created.json()["method"]["id"]
    content_hash = created.json()["versions"][0]["content_sha256"]
    validated = client.post(f"/api/v1/calculation-methods/{method_id}/versions/1/validate")
    assert validated.status_code == 200, validated.text
    assert validated.json()["valid"] is True, validated.text
    return method_id, 1, content_hash


def test_a_cbam_variant_excludes_one_port_from_the_solved_graph_and_freezes_its_identity(
    client, steel_project, monkeypatch
):
    """R4.3 end-to-end: a user CBAM variant actually takes an emission out of the calculation model.

    The variant is created against the same revision as the reviewed synthetic boundary with one
    exchange-level exclusion, and the solve is issued against that exact version + content hash
    so the frozen record traces to it. The sibling emission the reviewed boundary counted in
    leaves both the derived graph the engine sees AND the receipt's counted set, while the
    original LCA purpose still computes over the whole model. The build_cbam_trial_v2 counted-set
    equality guard runs unmodified against the regenerated ledger -- this is the same formal
    pipeline a reviewed exclusion goes through, not a relaxation of any check.
    """
    rules, package = _synthetic_classifying_rules_and_package()
    _bind_synthetic_rules(steel_project, monkeypatch, rules, package)

    # A baseline cbam solve, without a variant, proves the reviewed boundary is the reference.
    baseline = steel_project.solve("cbam")
    assert baseline.status_code == 201, baseline.text
    baseline_stamp = steel_project.run(
        baseline.json()["provider_receipt"]["analysis_run_id"]
    ).provider_receipt["model_derivation"]
    assert baseline_stamp["flow_selection"]["excluded_exchange_ids"] == [SYNTHETIC_EXCLUDED_EMISSION]
    assert SYNTHETIC_KEPT_SIBLING in baseline_stamp["flow_selection"]["included_exchange_ids"]

    method_id, version, content_hash = _ready_cbam_variant(
        client,
        steel_project.application_id,
        steel_project.revision_id,
        SYNTHETIC_KEPT_SIBLING,
    )
    solve_url = (
        f"/api/v1/applications/{steel_project.application_id}/system-revisions"
        f"/{steel_project.revision_id}/solve"
    )
    narrowed = client.post(
        solve_url,
        json={
            "demand": steel_project.workspace["demand"],
            "mapped_background_process_pins": steel_project.workspace["mapped_background_process_pins"],
            "calculation_purpose": "cbam",
            "calculation_method_ref": {
                "method_id": method_id,
                "version": version,
                "content_sha256": content_hash,
            },
        },
    )
    assert narrowed.status_code == 201, narrowed.text
    narrowed = narrowed.json()

    # The receipt's counted set actually took the sibling out, and the clause on the new
    # exclusion names the exact immutable variant version so the frozen answer traces back to it.
    stamp = steel_project.run(
        narrowed["provider_receipt"]["analysis_run_id"]
    ).provider_receipt["model_derivation"]
    selection = stamp["flow_selection"]
    assert selection["excluded_exchange_ids"] == sorted(
        [SYNTHETIC_EXCLUDED_EMISSION, SYNTHETIC_KEPT_SIBLING]
    )
    assert SYNTHETIC_KEPT_SIBLING not in selection["included_exchange_ids"]
    sibling_decision = next(
        item for item in selection["decisions"] if item["exchange_id"] == SYNTHETIC_KEPT_SIBLING
    )
    assert sibling_decision["state"] == "excluded"
    assert sibling_decision["clause"] == (
        f"user-variant-exclusion@{method_id}@{version}#{content_hash}"
    )

    # The engine was handed the narrowed graph, not the stored one: the sibling port is physically
    # gone from what was sent for CBAM, but still present for the LCA purpose that never classifies
    # exchange by exchange, so an operator exclusion cannot leak into a lifecycle answer.
    lca = steel_project.solve("lca")
    assert lca.status_code == 201, lca.text
    _baseline_cbam_request, narrowed_cbam_request, lca_request = steel_project.solve_requests()
    assert SYNTHETIC_KEPT_SIBLING in _sent_ports(lca_request)
    assert SYNTHETIC_KEPT_SIBLING in _sent_ports(_baseline_cbam_request)
    assert SYNTHETIC_KEPT_SIBLING not in _sent_ports(narrowed_cbam_request)
    assert SYNTHETIC_EXCLUDED_EMISSION not in _sent_ports(narrowed_cbam_request)

    # The frozen record carries the variant's exact identity, so a recovery re-checks against
    # that version and hash rather than the source method's current head.
    with steel_project.container.database.session() as db:
        row = db.get(SolvedSystemSnapshot, narrowed["id"])
        frozen = row.provider_receipt["user_calculation_method"]
    assert frozen["method_id"] == method_id
    assert frozen["version"] == version
    assert frozen["content_sha256"] == content_hash

    # The baseline record's own frozen flow_selection is untouched: only the variant narrowed
    # its graph, and no cache key or receipt was rewritten in place.
    baseline_run = steel_project.run(
        baseline.json()["provider_receipt"]["analysis_run_id"]
    )
    assert baseline_run.provider_receipt["model_derivation"]["flow_selection"][
        "excluded_exchange_ids"
    ] == [SYNTHETIC_EXCLUDED_EMISSION]


def test_a_cbam_variant_read_back_re_derives_under_its_own_overlay(
    client, steel_project, monkeypatch
):
    """Reading a bound variant's answer back must reproduce its narrowed basis, or CBAM refuses it.

    A CBAM run that cites a version folds a ``user_calculation_method`` identity into the frozen
    basis, so the trial's read-back re-derivation has to rebuild that very overlay through the shared
    execution contract. Deriving against the whole stored model instead produces a different basis
    hash and the read-back refuses with MODEL_PROCESSING_BASIS_DRIFT -- which is exactly what it did
    before the overlay was reconstructed here. This is the seam every CBAM numeric and product
    assertion in the acceptance depends on: no drift, and the re-derived counted set still excludes
    the sibling the operator took out.
    """
    rules, package = _synthetic_classifying_rules_and_package()
    _bind_synthetic_rules(steel_project, monkeypatch, rules, package)

    method_id, version, content_hash = _ready_cbam_variant(
        client,
        steel_project.application_id,
        steel_project.revision_id,
        SYNTHETIC_KEPT_SIBLING,
    )
    narrowed = client.post(
        f"/api/v1/applications/{steel_project.application_id}/system-revisions"
        f"/{steel_project.revision_id}/solve",
        json={
            "demand": steel_project.workspace["demand"],
            "mapped_background_process_pins": steel_project.workspace[
                "mapped_background_process_pins"
            ],
            "calculation_purpose": "cbam",
            "calculation_method_ref": {
                "method_id": method_id,
                "version": version,
                "content_sha256": content_hash,
            },
        },
    )
    assert narrowed.status_code == 201, narrowed.text
    narrowed = narrowed.json()

    service = steel_project.container.cbam_trials
    with steel_project.container.database.session() as db:
        row = db.get(SolvedSystemSnapshot, narrowed["id"])
        derivation = service._derivation(db, row)

    # The read-back reproduces the frozen, variant-narrowed basis exactly -- the same one the solve
    # accepted -- not the whole-model basis a bare re-derivation drifted to.
    assert derivation is not None
    assert derivation.basis_sha256 == _derivation(narrowed)["basis_sha256"]
    assert derivation.basis == {
        key: value
        for key, value in _derivation(narrowed).items()
        if key != "basis_sha256"
    }
    # And it reproduces the *narrowed* model, so the trial reads the answer under the operator's own
    # boundary rather than the whole regulated set.
    assert SYNTHETIC_KEPT_SIBLING not in flow_selection_of(derivation.derived)[
        "included_exchange_ids"
    ]

    # Negative control: derive against the same pinned basis WITHOUT the overlay -- exactly what the
    # read-back did before the reconstruction -- and the frozen answer refuses. The overlay is what
    # makes the read-back reproduce, so this guard is load-bearing rather than incidental.
    with steel_project.container.database.session() as db:
        row = db.get(SolvedSystemSnapshot, narrowed["id"])
        basis = derivation_basis_from_receipt(row.provider_receipt)
        parameters = db.get(
            AnalysisRun, row.provider_receipt["analysis_run_id"]
        ).parameters
        revision = db.get(SystemRevision, row.system_revision_id)
        model = db.get(SystemModel, revision.system_model_id)
        with pytest.raises(DomainError) as refused:
            resolve_purpose_derivation(
                db,
                revision=revision,
                application=db.get(Application, model.application_id),
                purpose="cbam",
                demand=parameters.get("demand") or [],
                background_process_pins=parameters.get("background_process_pins") or [],
                mapped_background_process_pins=parameters.get(
                    "mapped_background_process_pins"
                )
                or [],
                project_background_pins=parameters.get("project_background_pins") or [],
                lcia_methods=parameters.get("lcia_methods"),
                pinned_basis=basis,
                user_selection=None,
            )
        assert refused.value.code == "MODEL_PROCESSING_BASIS_DRIFT"
        # The shared contract rebuilds the very overlay the solve folded in.
        overlay = recover_cbam_user_selection(
            db,
            application_id=model.application_id,
            system_revision_id=revision.id,
            purpose="cbam",
            parameters=parameters,
        )
        assert overlay is not None and overlay["source"]["method_id"] == method_id


def test_a_user_variant_pinning_its_source_version_survives_a_later_source_edit(
    client, steel_project, monkeypatch
):
    """A variant's own identity is not the source head: the source moving forward changes nothing.

    After a variant is created from a source method, editing the source adds a version; the
    variant still names the exact source version and hash it was copied from, so a frozen CBAM
    ledger cannot silently drift as its source moves.
    """
    rules, package = _synthetic_classifying_rules_and_package()
    _bind_synthetic_rules(steel_project, monkeypatch, rules, package)

    # Create the source: a CBAM method with one CBAM-relevant selected rule for blast-furnace.
    boundary = client.post(
        f"/api/v1/applications/{steel_project.application_id}/boundaries",
        json={"name": "R4.3 source boundary", "boundary_type": "cbam_production"},
    )
    source_created = client.post(
        f"/api/v1/applications/{steel_project.application_id}/calculation-methods",
        json={
            "name": "Steel BF-BOF baseline",
            "purpose": "cbam",
            "model_revision_id": steel_project.revision_id,
            "cbam_boundary_ref": boundary.json()["id"],
            "rules": [
                {
                    "process_instance_id": "blast-furnace",
                    "direction": "emission",
                    "boundary_status": "selected",
                    "location_role": "onsite",
                    "scope": "scope_1",
                    "cbam_relevant": True,
                    "classification_basis": "user",
                }
            ],
        },
    )
    assert source_created.status_code == 201, source_created.text
    source_method = source_created.json()["method"]["id"]
    source_hash = source_created.json()["versions"][0]["content_sha256"]
    validated = client.post(
        f"/api/v1/calculation-methods/{source_method}/versions/1/validate"
    )
    assert validated.status_code == 200, validated.text
    assert validated.json()["status"] == "ready"

    # Clone to a variant on the same revision: the variant remembers the exact source version + hash.
    cloned = client.post(
        f"/api/v1/calculation-methods/{source_method}/versions/1/clone",
        json={
            "name": "Steel BF-BOF variant",
            "purpose": "cbam",
            "model_revision_id": steel_project.revision_id,
        },
    )
    assert cloned.status_code == 201, cloned.text
    variant = cloned.json()
    assert variant["method"]["origin_method_id"] == source_method
    assert variant["method"]["origin_method_version"] == 1
    assert variant["method"]["origin_content_sha256"] == source_hash
    # A clone is a fresh variant that has to earn its own compliance claim: the source's
    # validated status does not carry over, so it starts as a draft.
    assert variant["method"]["status"] == "draft"
    assert variant["versions"][0]["status"] == "draft"
    assert variant["versions"][0]["validated_at"] is None

    # Move the source head forward; the variant's pinned identity must not follow it.
    moved = client.put(
        f"/api/v1/calculation-methods/{source_method}/versions/1",
        json={
            "rules": [
                {
                    "process_instance_id": "blast-furnace",
                    "direction": "emission",
                    "boundary_status": "pending",
                    "location_role": "onsite",
                    "cbam_relevant": True,
                    "classification_basis": "user",
                }
            ],
            "expected_content_sha256": source_hash,
        },
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["latest_version"] == 2
    # Versions come back newest-first; versions[0] is the advanced head, versions[1] the pinned v1.
    moved_hash = moved.json()["versions"][0]["content_sha256"]
    assert moved_hash != source_hash
    assert moved.json()["versions"][1]["content_sha256"] == source_hash

    still_pinned = client.get(
        f"/api/v1/calculation-methods/{variant['method']['id']}"
    ).json()
    assert still_pinned["method"]["origin_method_version"] == 1
    assert still_pinned["method"]["origin_content_sha256"] == source_hash

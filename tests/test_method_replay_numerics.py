"""S3: versioned replay is proven against the counted numbers, not only the plan hash.

The R2 guarantee (``test_calculation_methods``) freezes and replays an exact method
version at the ``execution_plan_sha256`` level, while the A/B/C equalities
(``test_pcf_user_method_grouping``) live at the grouping-kernel level with hand-fed
rules. Neither alone shows that a run accepted against a historical version keeps its
*counted totals* unchanged once a newer version exists. This test closes that seam end to
end: create and validate a PCF method over HTTP, resolve its immutable execution plan,
feed the plan's own rules into the grouping kernel, then edit a v2 and re-resolve v1 —
v1's numeric grouping must be byte-identical, while v2 re-splits the same fixed engine
pool without moving the total.
"""

from __future__ import annotations

from test_calculation_methods import _graph_process_ids, _setup

from nebula_one.analysis.pcf import _attach_pcf_user_method_grouping
from nebula_one.services.method_execution_contract import resolve_method_execution_plan

INDICATOR = "GWP-fossil"
UNIT = "kg CO2e"

# The method rule binds by exchange id, and its process identity must equal the ``node::``
# prefix of the exchange it names (method_contribution_binding). The create endpoint further
# requires that process id to exist in the bound system revision, so the pool and the rules
# are both keyed on one real graph node id — and the counted total is always a re-bucketing
# of 130.0 across the node's two elementary paths (100 direct + 10/20 split background).
_PORT_A = "co2-a"
_PORT_B = "co2-b"


def _ids(node_id):
    return f"{node_id}::{_PORT_A}", f"{node_id}::{_PORT_B}"


def _pool(node_id):
    a, b = _ids(node_id)
    scaled = [
        {"exchange_id": a, "process_id": node_id, "flow_uuid": "flow-co2", "direction": "output"},
        {"exchange_id": b, "process_id": node_id, "flow_uuid": "flow-co2", "direction": "output"},
    ]
    terms = [
        {"exchange_id": a, "path_contribution_value": 100.0, "attribution_basis": "foreground_direct",
         "path_share": None, "consumer_exchange_id": None, "consumer_process_uuid": None,
         "provider_instance_id": a, "process_uuid": node_id},
        {"exchange_id": b, "path_contribution_value": 10.0, "attribution_basis": "background_consumer_path",
         "path_share": 1 / 3, "consumer_exchange_id": "consumer-a::in", "consumer_process_uuid": "consumer-a",
         "provider_instance_id": b, "process_uuid": node_id},
        {"exchange_id": b, "path_contribution_value": 20.0, "attribution_basis": "background_consumer_path",
         "path_share": 2 / 3, "consumer_exchange_id": "consumer-b::in", "consumer_process_uuid": "consumer-b",
         "provider_instance_id": b, "process_uuid": node_id},
    ]
    lcia = {"path_weighted_contribution_receipts": [{
        "canonical_indicator_key": INDICATOR, "indicator_unit": UNIT,
        "attribution_coverage": "complete", "terms": terms,
    }]}
    return scaled, lcia


def _rule(node_id, port, *, boundary_status="selected", scope="scope_1"):
    return {
        "process_instance_id": node_id,
        "exchange_id": f"{node_id}::{port}",
        "direction": "emission",
        "boundary_status": boundary_status,
        "location_role": "onsite",
        "scope": scope if boundary_status != "excluded" else None,
        "classification_basis": "user",
    }


def _plan_rules(node_id, bg_boundary="selected"):
    return [
        _rule(node_id, _PORT_A),
        _rule(node_id, _PORT_B, boundary_status=bg_boundary),
    ]


def _create_pcf_method(client, application, revision_id, node_id):
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json={
            "name": "Replayed PCF grouping",
            "purpose": "pcf",
            "model_revision_id": revision_id,
            "rules": _plan_rules(node_id),
        },
    )
    assert created.status_code == 201, created.text
    method_id = created.json()["method"]["id"]
    v1_hash = created.json()["versions"][0]["content_sha256"]
    validated = client.post(f"/api/v1/calculation-methods/{method_id}/versions/1/validate")
    assert validated.status_code == 200, validated.text
    assert validated.json()["valid"] is True, validated.text
    return method_id, v1_hash


def _resolve(client, application_id, revision_id, ref):
    container = client.app.state.container
    with container.database.session() as db:
        return resolve_method_execution_plan(
            db,
            application_id=application_id,
            system_revision_id=revision_id,
            purpose="pcf",
            ref=ref,
        )


def _grouping(plan, scaled, lcia):
    # The kernel consumes the plan's own frozen rules plus the plan identity it was accepted
    # with; it re-buckets the fixed pool and never re-solves, so totals can only redistribute.
    receipt = {
        "user_calculation_method": {
            "method_id": plan["method_id"],
            "version": plan["version"],
            "content_sha256": plan["content_sha256"],
            "model_revision_id": plan["model_revision_id"],
            "execution_plan_sha256": plan["execution_plan_sha256"],
            "compiler_version": plan["compiler_version"],
            "rules": plan["rules"],
        }
    }
    return _attach_pcf_user_method_grouping(
        contribution_analysis={"status": "available", "coverage": "exact_exchange_contributions", "hotspots": []},
        provider_receipt=receipt,
        scaled_elementary_exchanges=scaled,
        lcia_results=lcia,
        indicator_key=INDICATOR,
        indicator_unit=UNIT,
    )["user_method_grouping"]


def test_historical_version_replay_keeps_counted_totals_and_method_identity(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    scaled, lcia = _pool(node_id)
    method_id, v1_hash = _create_pcf_method(client, application, revision_id, node_id)

    plan_v1 = _resolve(client, application["id"], revision_id, {"method_id": method_id, "version": 1, "content_sha256": v1_hash})
    block_a = _grouping(plan_v1, scaled, lcia)

    # A: both selected paths count into scope_1; method identity is the exact frozen plan.
    assert block_a["grouping"]["scopes"]["scope_1"]["value"] == 130.0
    assert block_a["grouping"]["contribution_total"] == 130.0
    assert block_a["method"]["execution_plan_sha256"] == plan_v1["execution_plan_sha256"]

    # Edit into v2: the same background path is now excluded (leaving scope_1).
    saved = client.put(
        f"/api/v1/calculation-methods/{method_id}/versions/1",
        json={"rules": _plan_rules(node_id, bg_boundary="excluded"), "expected_content_sha256": v1_hash},
    )
    assert saved.status_code == 200, saved.text
    v2_hash = next(v["content_sha256"] for v in saved.json()["versions"] if v["version"] == 2)
    validated_v2 = client.post(f"/api/v1/calculation-methods/{method_id}/versions/2/validate")
    assert validated_v2.status_code == 200, validated_v2.text
    assert validated_v2.json()["valid"] is True, validated_v2.text

    # Replaying v1 after v2 exists must return the identical frozen plan AND identical numbers:
    # the historical counted total never moves under a newer version.
    replay_v1 = _resolve(client, application["id"], revision_id, {"method_id": method_id, "version": 1, "content_sha256": v1_hash})
    assert replay_v1["execution_plan_sha256"] == plan_v1["execution_plan_sha256"]
    replay_block = _grouping(replay_v1, scaled, lcia)
    assert replay_block == block_a

    plan_v2 = _resolve(client, application["id"], revision_id, {"method_id": method_id, "version": 2, "content_sha256": v2_hash})
    block_b = _grouping(plan_v2, scaled, lcia)
    assert plan_v2["execution_plan_sha256"] != plan_v1["execution_plan_sha256"]

    # B (v2) drops exactly the background path from the counted total; the excluded detail keeps it.
    assert block_b["grouping"]["scopes"]["scope_1"]["value"] == 100.0
    assert block_b["grouping"]["excluded"]["value"] == 30.0
    assert block_a["grouping"]["scopes"]["scope_1"]["value"] - block_b["grouping"]["scopes"]["scope_1"]["value"] == 30.0
    # A and B share one fixed engine pool: counted + excluded + unattributed stays 130.
    for block in (block_a, block_b):
        g = block["grouping"]
        assert g["contribution_total"] == 130.0
        assert g["scopes"]["scope_1"]["value"] + g["excluded"]["value"] + g["unattributed"]["value"] == 130.0

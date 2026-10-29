"""Synthetic regressions for the minimal model deriver: declared graph operations, nothing else.

The fixture is deliberately not the steel model - it shares the steel model's *shape* (three
production processes, one in-graph electricity supplier feeding all three, saved background pins on
two open inputs) so the deriver is proven to follow the rule package rather than a steel branch.
"""
from __future__ import annotations

import json
from copy import deepcopy

import pytest

from nebula_one.errors import DomainError
from nebula_one.hashing import canonical_graph_sha256, canonical_json_sha256
from nebula_one.model_derivation import DERIVATION_SCHEMA_VERSION, derive_calculation_model
from nebula_one.model_processing_contract import ModelProcessingRules
from nebula_one.services.model_processing_runtime import (
    FLOW_SELECTION_SCHEMA_VERSION,
    flow_selection_of,
)

SINTERING = "aaaaaaaa-0000-4000-8000-000000000001"
FURNACE = "aaaaaaaa-0000-4000-8000-000000000002"
CASTING = "aaaaaaaa-0000-4000-8000-000000000003"
GRID = "aaaaaaaa-0000-4000-8000-000000000009"

PACKAGE_ID = "cbam.test.direct-only"
PACKAGE_VERSION = "1.0.0"
PACKAGE_HASH = "1" * 64

ELECTRICITY_PORTS = [
    "sintering::grid-electricity-in",
    "furnace::grid-electricity-in",
    "casting::grid-electricity-in",
]


def _port(port_id, flow, unit, amount, kind, direction="output", namespace="nebula.test",
          version="1.0.0", name="test flow"):
    return {
        "id": port_id,
        "flowUuid": flow,
        "flowSourceNamespace": namespace,
        "flowVersion": version,
        "flowPropertyUuid": "fp-1",
        "flowPropertyVersion": "03.00.003",
        "unitGroupUuid": "ug-1",
        "unitGroupVersion": "03.00.003",
        "name": name,
        "unit": unit,
        "amount": amount,
        "type": kind,
        "direction": direction,
    }


def _emission(exchange_id, process_uuid, flow="co2-fossil", unit="kg", gas="CO2"):
    return {
        "exchange_id": exchange_id,
        "process_uuid": process_uuid,
        "direction": "output",
        "source_namespace": "tiangong_open_data",
        "flow_uuid": flow,
        "version": "03.00.004",
        "flow_property_uuid": "fp-1",
        "flow_property_version": "03.00.003",
        "unit_group_uuid": "ug-1",
        "unit_group_version": "03.00.003",
        "unit": unit,
        "greenhouse_gas": gas,
        "compartment": "Emissions to air, unspecified",
    }


def _decision(exchange_id, process_uuid, disposition, clause="TEST-CLASSIFY", **kwargs):
    """One reviewed include/exclude call, keyed by exchange rather than by flow."""
    return {
        **_emission(exchange_id, process_uuid, **kwargs),
        "disposition": disposition,
        "clause": clause,
    }


def _edge(edge_id, provider, source_port, consumer, target_port, flow, amount):
    return {
        "id": edge_id,
        "fromNode": provider,
        "toNode": consumer,
        "sourcePortId": source_port,
        "targetPortId": target_port,
        "flowUuid": flow,
        "flowName": "test flow",
        "quantityMode": "single",
        "amount": amount,
        "providerAmount": amount,
        "consumerAmount": amount,
        "unit": "kg" if flow != "grid-electricity" else "MJ",
        "type": "technosphere",
        "allocation": "none",
    }


def _graph():
    return {
        "schema_version": "test.graph.v1",
        "functionalUnit": "1 kg test product",
        "metadata": {
            "seed_id": "test.seed",
            "calculation_boundary": "cradle-to-gate",
            "reference_exchange_id": "casting::crude-steel-out",
        },
        "nodes": [
            {
                "id": "sintering",
                "node_kind": "unit_process",
                "mode": "normalized",
                "process_uuid": SINTERING,
                "name": "Sintering",
                "reference_product": "sinter-out",
                "inputs": [
                    _port("iron-ore-in", "iron-ore", "kg", 100.0, "technosphere", "input"),
                    _port("grid-electricity-in", "grid-electricity", "MJ", 600.0,
                          "technosphere", "input"),
                ],
                "outputs": [
                    _port("sinter-out", "sintered-ore", "kg", 50.0, "technosphere"),
                    _port("co2-sinter-out", "co2-fossil", "kg", 10.0, "biosphere",
                          namespace="tiangong_open_data", version="03.00.004",
                          name="Carbon dioxide (fossil), solid fuel"),
                ],
            },
            {
                "id": "furnace",
                "node_kind": "unit_process",
                "mode": "normalized",
                "process_uuid": FURNACE,
                "name": "Blast furnace",
                "reference_product": "hot-metal-out",
                "inputs": [
                    _port("sinter-in", "sintered-ore", "kg", 50.0, "technosphere", "input"),
                    _port("pci-coal-in", "pci-coal", "kg", 130.0, "technosphere", "input"),
                    _port("grid-electricity-in", "grid-electricity", "MJ", 200.0,
                          "technosphere", "input"),
                ],
                "outputs": [
                    _port("hot-metal-out", "hot-metal", "kg", 30.0, "technosphere"),
                    _port("co2-furnace-out", "co2-fossil", "kg", 40.0, "biosphere",
                          namespace="tiangong_open_data", version="03.00.004",
                          name="Carbon dioxide (fossil), raceway"),
                ],
            },
            {
                "id": "casting",
                "node_kind": "unit_process",
                "mode": "normalized",
                "process_uuid": CASTING,
                "name": "Casting",
                "reference_product": "crude-steel-out",
                "inputs": [
                    _port("hot-metal-in", "hot-metal", "kg", 30.0, "technosphere", "input"),
                    _port("grid-electricity-in", "grid-electricity", "MJ", 25.0,
                          "technosphere", "input"),
                ],
                "outputs": [_port("crude-steel-out", "test-product", "kg", 28.0, "technosphere")],
            },
            {
                "id": "electricity-grid",
                "node_kind": "unit_process",
                "mode": "normalized",
                "process_uuid": GRID,
                "name": "Grid electricity",
                "reference_product": "grid-electricity-out",
                "inputs": [
                    _port("primary-in", "primary-electricity", "MJ", 1000.0,
                          "technosphere", "input"),
                ],
                "outputs": [
                    _port("grid-electricity-out", "grid-electricity", "MJ", 1000.0, "technosphere"),
                ],
            },
        ],
        "exchanges": [
            _edge("edge-sinter", "sintering", "sinter-out", "furnace", "sinter-in",
                  "sintered-ore", 50.0),
            _edge("edge-hot-metal", "furnace", "hot-metal-out", "casting", "hot-metal-in",
                  "hot-metal", 30.0),
            _edge("edge-grid-sintering", "electricity-grid", "grid-electricity-out",
                  "sintering", "grid-electricity-in", "grid-electricity", 600.0),
            _edge("edge-grid-furnace", "electricity-grid", "grid-electricity-out",
                  "furnace", "grid-electricity-in", "grid-electricity", 200.0),
            _edge("edge-grid-casting", "electricity-grid", "grid-electricity-out",
                  "casting", "grid-electricity-in", "grid-electricity", 25.0),
        ],
    }


def _boundary_exchanges(port_ids):
    return [
        {
            "exchange_id": port_id,
            "disposition": "keep_as_boundary_input",
            "amount_source": "consumer_port_amount",
            "clause": "TEST-12",
        }
        for port_id in port_ids
    ]


def _manifest(boundary=None, emissions=None, annex_ii_direct_only=True, decisions=None):
    return {
        "boundary_schema": {
            "annex_ii_direct_only": annex_ii_direct_only,
            "greenhouse_gases": ["CO2"],
            "production_process_boundary": {
                "in_boundary_process_uuids": boundary or [SINTERING, FURNACE, CASTING],
                "clause": "TEST-ANNEX-II",
            },
        },
        "classification_rules": {
            "product": {"exchange_id": "casting::crude-steel-out"},
            "direct_emissions": emissions
            if emissions is not None
            else [
                _emission("sintering::co2-sinter-out", SINTERING),
                _emission("furnace::co2-furnace-out", FURNACE),
            ],
            "exchange_decisions": decisions,
        },
    }


def _explicit(manifest=None, **kwargs):
    """The same CBAM purpose, deciding its emission exchanges one by one instead of pre-limiting."""
    rules = _rules().purpose("cbam").model_dump()
    rules["elementary_flows"] = {
        "mode": "explicit_flow_rules",
        "evidence": {
            "method_package": {
                "package_id": PACKAGE_ID,
                "version": PACKAGE_VERSION,
                "content_sha256": PACKAGE_HASH,
            },
            "manifest_path": "classification_rules.exchange_decisions",
            "applicable_gases_path": "boundary_schema.greenhouse_gases",
        },
    }
    return _rules(cbam=rules), _method_package(
        manifest if manifest is not None else _manifest(**kwargs)
    )


def _plant():
    """The same plant with a furnace vent the reviewed boundary does not count."""
    graph = _graph()
    furnace = next(node for node in graph["nodes"] if node["id"] == "furnace")
    furnace["outputs"].append(
        _port(
            "ch4-furnace-out",
            "ch4-fossil",
            "kg",
            7.5,
            "biosphere",
            namespace="tiangong_open_data",
            version="03.00.004",
            name="Methane (fossil), furnace venting",
        )
    )
    return graph


def _whole_plant_decisions():
    return [
        _decision("sintering::co2-sinter-out", SINTERING, "include"),
        _decision("furnace::co2-furnace-out", FURNACE, "include"),
        _decision(
            "furnace::ch4-furnace-out", FURNACE, "exclude",
            flow="ch4-fossil", gas="CH4", clause="TEST-OUT-OF-SCOPE",
        ),
    ]


def _derive_explicit(purpose="cbam", *, graph=None, decisions=None, rules=None, packages=None):
    default_rules, default_package = _explicit(decisions=_whole_plant_decisions())
    background, mapped = _saved_pins()
    return derive_calculation_model(
        graph=graph if graph is not None else _plant(),
        demand=[{"process_uuid": CASTING, "amount": 1.0, "unit": "kg"}],
        rules=rules or default_rules,
        purpose=purpose,
        method_packages=packages if packages is not None else [default_package],
        background_process_pins=background,
        mapped_background_process_pins=mapped,
    )


def _method_package(manifest=None, **kwargs):
    return {
        "package_id": PACKAGE_ID,
        "version": PACKAGE_VERSION,
        "content_sha256": PACKAGE_HASH,
        "manifest": manifest if manifest is not None else _manifest(**kwargs),
    }


def _rules(cbam=None, lca=None):
    default_cbam = {
        "process_selection": {
            "mode": "method_package_boundary",
            "method_package": {
                "package_id": PACKAGE_ID,
                "version": PACKAGE_VERSION,
                "content_sha256": PACKAGE_HASH,
            },
            "process_uuids_path": "boundary_schema.production_process_boundary"
            ".in_boundary_process_uuids",
        },
        "background_disposition": {
            "mode": "unlink_all_background_links",
            "evidence": {
                "method_package": {
                    "package_id": PACKAGE_ID,
                    "version": PACKAGE_VERSION,
                    "content_sha256": PACKAGE_HASH,
                },
                "manifest_path": "boundary_schema.annex_ii_direct_only",
                "required_value": True,
                "clause": "TEST-ANNEX-II direct emissions only",
            },
        },
        "cross_boundary_connections": {
            "mode": "reject_undeclared",
            "boundary_exchanges": _boundary_exchanges(ELECTRICITY_PORTS),
        },
        "elementary_flows": {
            "mode": "template_prelimited",
            "evidence": {
                "method_package": {
                    "package_id": PACKAGE_ID,
                    "version": PACKAGE_VERSION,
                    "content_sha256": PACKAGE_HASH,
                },
                "manifest_path": "classification_rules.direct_emissions",
                "applicable_gases_path": "boundary_schema.greenhouse_gases",
            },
        },
        "precursors": {"mode": "reference_only"},
    }
    content = {
        "applicable_template": {
            "id": "test-template",
            "version": "1.0.0",
            "content_sha256": "2" * 64,
        },
        "purposes": {
            "lca": lca
            or {
                "process_selection": {"mode": "all_model_processes"},
                "background_disposition": {"mode": "retain_saved_pins"},
                "cross_boundary_connections": {
                    "mode": "keep_internal_edges",
                    "boundary_exchanges": [],
                },
                "elementary_flows": {"mode": "not_applicable"},
                "precursors": {"mode": "not_applicable"},
            },
            "cbam": cbam or default_cbam,
        },
    }
    return ModelProcessingRules(
        {
            "schema_version": "nebula_one.model-processing-rules.v1",
            "package_id": "test.model-processing",
            "version": "1.0.0",
            "content": content,
            "content_sha256": canonical_json_sha256(content),
        },
        "test.json",
    )


def _saved_pins():
    return (
        [
            {
                "schema_version": "provider.background-process-pin.v1",
                "consumer_exchange_id": "sintering::iron-ore-in",
                "source_namespace": "tiangong_open_data",
                "process_uuid": "bbbbbbbb-0000-4000-8000-000000000001",
                "version": "03.00.004",
                "expected_process_content_hash": "3" * 64,
                "expected_process_snapshot_hash": "4" * 64,
                "quantitative_reference_exchange_internal_id": "qref-1",
                "claim_role": "partial_background_leaf",
            }
        ],
        [
            {
                "schema_version": "provider.mapped-background-process-pin.v1",
                "consumer_exchange_id": "furnace::pci-coal-in",
                "source_flow_namespace": "nebula.test",
                "source_flow_uuid": "pci-coal",
                "source_flow_version": "1.0.0",
                "target_flow_uuid": "cccccccc-0000-4000-8000-000000000001",
                "source_unit": "kg",
                "target_unit": "kg",
                "amount_factor": 1.0,
                "mapping_level": "L1",
                "mapping_status": "auto",
                "mapping_rule_id": "rule-1",
                "mapping_package_id": "test.mapping",
                "mapping_package_version": "1.0.0",
                "mapping_package_hash": "5" * 64,
                "database_release": "test_release",
                "process_uuid": "bbbbbbbb-0000-4000-8000-000000000002",
                "expected_process_content_hash": "6" * 64,
                "expected_vector_checksum": "7" * 64,
                "claim_role": "partial_background_leaf",
            }
        ],
    )


def _derive(purpose="cbam", *, graph=None, rules=None, packages=None, demand=None, pins=True):
    background, mapped = _saved_pins() if pins else ([], [])
    return derive_calculation_model(
        graph=graph if graph is not None else _graph(),
        demand=demand if demand is not None else [
            {"process_uuid": CASTING, "amount": 1.0, "unit": "kg"}
        ],
        rules=rules or _rules(),
        purpose=purpose,
        method_packages=packages if packages is not None else [_method_package()],
        background_process_pins=background,
        mapped_background_process_pins=mapped,
    )


def _ports(graph):
    return {
        f"{node['id']}::{port['id']}": port
        for node in graph["nodes"]
        for port in [*node["inputs"], *node["outputs"]]
    }


def _codes(call):
    with pytest.raises(DomainError) as caught:
        call()
    return caught.value


# ---- the two purposes on one model ------------------------------------------------


def test_lca_purpose_derives_the_stored_model_unchanged_and_keeps_every_pin():
    source = _graph()
    frozen = deepcopy(source)
    derived = _derive("lca", graph=source)

    assert derived.derived_graph_sha256 == canonical_graph_sha256(frozen)
    assert source == frozen, "derivation must not touch the stored model"
    assert [node["process_uuid"] for node in derived.graph["nodes"]] == [
        SINTERING, FURNACE, CASTING, GRID
    ]
    assert len(derived.graph["exchanges"]) == 5
    background, mapped = _saved_pins()
    assert derived.background_process_pins == background
    assert derived.mapped_background_process_pins == mapped
    assert [action["action"] for action in derived.actions] == ["select_processes"]
    assert derived.method_package_references == []
    assert derived.record()["counts"]["derived_processes"] == 4


def test_cbam_purpose_drops_the_supplier_but_keeps_every_input_exchange():
    source = _graph()
    derived = _derive(graph=source)

    assert {node["process_uuid"] for node in derived.graph["nodes"]} == {
        SINTERING, FURNACE, CASTING
    }
    assert [edge["id"] for edge in derived.graph["exchanges"]] == [
        "edge-sinter", "edge-hot-metal"
    ]
    kept_ids = {node["id"] for node in derived.graph["nodes"]}
    assert all(
        edge["fromNode"] in kept_ids and edge["toNode"] in kept_ids
        for edge in derived.graph["exchanges"]
    ), "a derived model may never carry a dangling exchange"
    # Unlinking a supply link is not deleting the input exchange: quantity, unit and flow stay.
    ports = _ports(derived.graph)
    source_ports = _ports(source)
    for port_id in ELECTRICITY_PORTS:
        assert ports[port_id] == source_ports[port_id]
    assert ports["sintering::grid-electricity-in"]["amount"] == 600.0
    assert ports["furnace::grid-electricity-in"]["amount"] == 200.0
    assert derived.background_process_pins == []
    assert derived.mapped_background_process_pins == []
    assert derived.graph["functionalUnit"] == source["functionalUnit"]
    assert derived.graph["metadata"] == source["metadata"]


def test_cbam_derivation_refuses_a_shared_supplier_once_and_never_expands_it_again():
    derived = _derive()
    assert not any(
        node.get("process_uuid") == GRID for node in derived.graph["nodes"]
    )
    removed = [
        action for action in derived.actions if action["action"] == "keep_boundary_input"
    ]
    assert sorted(action["removed_exchange_id"] for action in removed) == [
        "edge-grid-casting", "edge-grid-furnace", "edge-grid-sintering"
    ]
    assert all(action["clause"] == "TEST-12" for action in removed)
    unlinked = [action for action in derived.actions if action["action"] == "unlink_background"]
    assert len(unlinked) == 2
    assert {action["clause"] for action in unlinked} == {"TEST-ANNEX-II direct emissions only"}
    assert {action["reason"] for action in unlinked} == {"unlink_all_background_links"}


def test_one_flow_uuid_in_three_processes_is_handled_per_instance():
    derived = _derive()
    ports = _ports(derived.graph)
    assert ports["casting::grid-electricity-in"]["amount"] == 25.0
    assert ports["sintering::grid-electricity-in"]["flowUuid"] == "grid-electricity"
    assert ports["furnace::grid-electricity-in"]["flowUuid"] == "grid-electricity"
    states = {item["consumer_exchange_id"]: item["state"] for item in derived.exchange_map}
    assert states["sintering::grid-electricity-in"] == "replaced_by_declared_boundary_input"
    assert states["casting::hot-metal-in"] == "kept"


def test_derivation_is_reproducible_and_the_record_carries_both_identities():
    first = _derive()
    second = _derive()
    assert first.derived_graph_sha256 == second.derived_graph_sha256
    record = first.record()
    assert record == second.record()
    assert record["schema_version"] == DERIVATION_SCHEMA_VERSION
    assert record["purpose"] == "cbam"
    assert record["model_processing_rules"]["package_id"] == "test.model-processing"
    assert record["method_packages"] == [
        {"package_id": PACKAGE_ID, "version": PACKAGE_VERSION, "content_sha256": PACKAGE_HASH}
    ]
    assert record["source_graph_sha256"] != record["derived_graph_sha256"]
    assert record["counts"] == {
        "source_processes": 4,
        "derived_processes": 3,
        "source_exchanges": 5,
        "removed_exchanges": 3,
        "boundary_inputs": 3,
        "unlinked_background_links": 2,
        "classified_emission_exchanges": 0,
        "excluded_emission_exchanges": 0,
    }


# ---- refusal instead of a silent guess -------------------------------------------


def test_cutting_an_undeclared_supply_exchange_refuses_rather_than_dropping_the_input():
    rules = _rules(
        cbam={
            **_rules().purpose("cbam").model_dump(),
            "cross_boundary_connections": {
                "mode": "reject_undeclared",
                "boundary_exchanges": _boundary_exchanges(ELECTRICITY_PORTS[:2]),
            },
        }
    )
    error = _codes(lambda: _derive(rules=rules))
    assert error.code == "MODEL_CROSS_BOUNDARY_UNDECLARED"
    assert error.details["consumer_exchange_ids"] == ["casting::grid-electricity-in"]
    assert error.details["exchange_ids"] == ["edge-grid-casting"]


def test_a_declaration_that_no_longer_cuts_anything_is_a_template_mismatch():
    rules = _rules(
        cbam={
            **_rules().purpose("cbam").model_dump(),
            "cross_boundary_connections": {
                "mode": "reject_undeclared",
                "boundary_exchanges": _boundary_exchanges([*ELECTRICITY_PORTS, "furnace::sinter-in"]),
            },
        }
    )
    error = _codes(lambda: _derive(rules=rules))
    assert error.code == "MODEL_CROSS_BOUNDARY_DECLARATION_UNUSED"
    assert error.details["consumer_exchange_ids"] == ["furnace::sinter-in"]


def test_cutting_a_link_whose_port_amount_differs_from_the_exchange_would_move_activity_data():
    graph = _graph()
    for node in graph["nodes"]:
        if node["id"] == "sintering":
            node["inputs"][1]["amount"] = 601.0
    error = _codes(lambda: _derive(graph=graph))
    assert error.code == "MODEL_CROSS_BOUNDARY_AMOUNT_CONFLICT"
    assert error.details == {
        "consumer_exchange_id": "sintering::grid-electricity-in",
        "port_amount": 601.0,
        "exchange_amount": 600.0,
    }


def test_the_same_process_uuid_on_two_instances_is_refused_not_renamed():
    graph = _graph()
    graph["nodes"].append(deepcopy(graph["nodes"][0]) | {"id": "sintering-copy"})
    error = _codes(lambda: _derive(graph=graph))
    assert error.code == "MODEL_DERIVATION_DUPLICATE_PROCESS_INSTANCE"
    assert error.details["process_uuids"] == [SINTERING]


def test_a_boundary_uuid_absent_from_the_model_is_reported_as_a_gap():
    manifest = _manifest(boundary=[SINTERING, FURNACE, CASTING, "no-such-process"])
    error = _codes(lambda: _derive(packages=[_method_package(manifest)]))
    assert error.code == "MODEL_DERIVATION_PROCESS_NOT_IN_MODEL"
    assert error.details["missing_process_uuids"] == ["no-such-process"]


def test_a_rule_pointing_at_an_absent_manifest_path_names_the_declaration():
    manifest = _manifest()
    del manifest["boundary_schema"]["production_process_boundary"]["in_boundary_process_uuids"]
    error = _codes(lambda: _derive(packages=[_method_package(manifest)]))
    assert error.code == "MODEL_PROCESSING_DECLARATION_UNREADABLE"
    assert error.details["declaration"] == "process_selection"


def test_a_package_that_no_longer_limits_itself_to_direct_emissions_keeps_the_background():
    manifest = _manifest(annex_ii_direct_only=False)
    error = _codes(lambda: _derive(packages=[_method_package(manifest)]))
    assert error.code == "MODEL_PROCESSING_EVIDENCE_NOT_DECLARED"
    assert error.details["found"] is False


@pytest.mark.parametrize(
    "packages, code",
    [
        ([], "MODEL_PROCESSING_METHOD_PACKAGE_UNBOUND"),
        ([{"package_id": PACKAGE_ID, "version": PACKAGE_VERSION, "content_sha256": "9" * 64,
           "manifest": _manifest()}], "MODEL_PROCESSING_METHOD_PACKAGE_MISMATCH"),
        ([{"package_id": PACKAGE_ID, "version": "1.0.1", "content_sha256": PACKAGE_HASH,
           "manifest": _manifest()}], "MODEL_PROCESSING_METHOD_PACKAGE_MISMATCH"),
        ([{"package_id": PACKAGE_ID, "version": PACKAGE_VERSION,
           "content_sha256": PACKAGE_HASH}], "MODEL_PROCESSING_METHOD_PACKAGE_UNBOUND"),
    ],
)
def test_method_package_identity_is_verified_before_any_link_is_dropped(packages, code):
    assert _codes(lambda: _derive(packages=packages)).code == code


def test_saved_demand_never_gets_rewritten_to_fit_the_derived_model():
    error = _codes(
        lambda: _derive(demand=[{"process_uuid": GRID, "amount": 1.0, "unit": "MJ"}])
    )
    assert error.code == "MODEL_DERIVATION_DEMAND_ORPHANED"
    assert error.details["process_uuid"] == GRID

    error = _codes(
        lambda: _derive(demand=[{"reference_exchange_id": "casting::missing-in",
                                 "amount": 1.0, "unit": "kg"}])
    )
    assert error.code == "MODEL_DERIVATION_DEMAND_ORPHANED"
    assert error.details["reference_exchange_id"] == "casting::missing-in"

    kept = _derive(demand=[{"reference_exchange_id": "casting::crude-steel-out",
                            "amount": 1.0, "unit": "kg"}])
    assert kept.demand == [{"reference_exchange_id": "casting::crude-steel-out",
                            "amount": 1.0, "unit": "kg"}]


def test_a_saved_pin_on_an_internally_supplied_port_is_a_stored_model_conflict():
    background, _ = _saved_pins()
    pin = dict(background[0], consumer_exchange_id="furnace::sinter-in")
    rules = _rules()
    with pytest.raises(DomainError) as caught:
        derive_calculation_model(
            graph=_graph(),
            demand=[{"process_uuid": CASTING, "amount": 1.0, "unit": "kg"}],
            rules=rules,
            purpose="lca",
            method_packages=[_method_package()],
            background_process_pins=[pin],
            mapped_background_process_pins=[],
        )
    assert caught.value.code == "MODEL_DERIVATION_PIN_CONFLICT"


def test_excluding_the_process_that_carries_the_reference_exchange_is_refused():
    cbam = _rules().purpose("cbam").model_dump()
    cbam["cross_boundary_connections"]["boundary_exchanges"] = _boundary_exchanges(
        ["sintering::grid-electricity-in", "furnace::grid-electricity-in"]
    )
    manifest = _manifest(
        boundary=[SINTERING, FURNACE],
        emissions=[_emission("sintering::co2-sinter-out", SINTERING),
                   _emission("furnace::co2-furnace-out", FURNACE)],
    )
    error = _codes(
        lambda: _derive(
            rules=_rules(cbam=cbam),
            packages=[_method_package(manifest)],
            demand=[{"process_uuid": FURNACE, "amount": 1.0, "unit": "kg"}],
        )
    )
    assert error.code == "MODEL_DERIVATION_REFERENCE_EXCHANGE_LOST"
    assert error.details["reference_exchange_id"] == "casting::crude-steel-out"


# ---- elementary flows: identity and version only, never a name match --------------


def test_a_pre_limited_template_is_checked_by_exact_identity_in_both_directions():
    derived = _derive()
    verification = [
        action for action in derived.actions if action["action"] == "verify_elementary_flows"
    ]
    assert len(verification) == 1
    assert verification[0]["verified_exchange_ids"] == [
        "furnace::co2-furnace-out", "sintering::co2-sinter-out"
    ]
    assert verification[0]["applicable_gases"] == ["CO2"]


def test_an_extra_emission_flow_is_a_template_mismatch_even_when_its_name_says_co2():
    graph = _graph()
    for node in graph["nodes"]:
        if node["id"] == "furnace":
            node["outputs"].append(
                _port("co2-biomass-out", "co2-biogenic", "kg", 3.0, "biosphere",
                      namespace="tiangong_open_data", version="03.00.004",
                      name="Carbon dioxide (biomass)")
            )
    error = _codes(lambda: _derive(graph=graph))
    assert error.code == "MODEL_ELEMENTARY_FLOW_TEMPLATE_MISMATCH"
    assert error.details["undeclared_in_method"] == ["furnace::co2-biomass-out"]
    assert error.details["missing_from_model"] == []


@pytest.mark.parametrize(
    ("mutate", "expected_field"),
    [
        (
            lambda rule: rule.update(version="03.00.005"),
            "flowVersion",
        ),
        (
            lambda rule: rule.update(flow_uuid="co2-some-other"),
            "flowUuid",
        ),
        (
            lambda rule: rule.update(process_uuid=CASTING),
            "process_uuid",
        ),
        (
            lambda rule: rule.update(greenhouse_gas="CH4"),
            "greenhouse_gas",
        ),
    ],
)
def test_a_single_identity_or_version_change_is_caught(mutate, expected_field):
    emissions = [_emission("sintering::co2-sinter-out", SINTERING)]
    mutate(emissions[0])
    emissions.append(_emission("furnace::co2-furnace-out", FURNACE))
    manifest = _manifest(emissions=emissions)
    error = _codes(lambda: _derive(packages=[_method_package(manifest)]))
    assert error.code == "MODEL_ELEMENTARY_FLOW_TEMPLATE_MISMATCH"
    drift = error.details["identity_drift"]
    assert [item["exchange_id"] for item in drift] == ["sintering::co2-sinter-out"]
    assert expected_field in drift[0]["fields"]


def test_a_declared_emission_flow_missing_from_the_selected_processes_is_reported():
    manifest = _manifest(
        emissions=[
            _emission("sintering::co2-sinter-out", SINTERING),
            _emission("furnace::co2-furnace-out", FURNACE),
            _emission("casting::co2-casting-out", CASTING),
        ]
    )
    error = _codes(lambda: _derive(packages=[_method_package(manifest)]))
    assert error.code == "MODEL_ELEMENTARY_FLOW_TEMPLATE_MISMATCH"
    assert error.details["missing_from_model"] == [
        {"exchange_id": "casting::co2-casting-out", "process_uuid": CASTING}
    ]


# ---- a pre-limited identity must actually be carried ------------------------------------


def _sintering_port(graph):
    return next(
        port
        for node in graph["nodes"]
        if node["id"] == "sintering"
        for port in node["outputs"]
        if port["id"] == "co2-sinter-out"
    )


@pytest.mark.parametrize(
    "port_key",
    [
        "flowSourceNamespace",
        "flowUuid",
        "flowVersion",
        "flowPropertyUuid",
        "flowPropertyVersion",
        "unitGroupUuid",
        "unitGroupVersion",
        "unit",
        "direction",
    ],
)
def test_a_model_port_missing_a_required_flow_identity_is_a_template_mismatch(port_key):
    # Absent is not "nothing to compare": a flow whose identity cannot be read cannot be confirmed
    # as one of the six flows the reviewed template pre-limits.
    graph = _graph()
    del _sintering_port(graph)[port_key]
    error = _codes(lambda: _derive(graph=graph))
    assert error.code == "MODEL_ELEMENTARY_FLOW_TEMPLATE_MISMATCH"
    drift = error.details["identity_drift"]
    assert [item["exchange_id"] for item in drift] == ["sintering::co2-sinter-out"]
    assert drift[0]["fields"][port_key]["absent_on"] == ["model"]


@pytest.mark.parametrize("empty", ["", "   ", None])
def test_an_empty_flow_identity_is_not_treated_as_absent_and_agreeing(empty):
    graph = _graph()
    _sintering_port(graph)["flowUuid"] = empty
    error = _codes(lambda: _derive(graph=graph))
    assert error.code == "MODEL_ELEMENTARY_FLOW_TEMPLATE_MISMATCH"
    assert error.details["identity_drift"][0]["fields"]["flowUuid"]["absent_on"] == ["model"]


def test_a_method_rule_that_stops_declaring_an_identity_is_also_a_mismatch():
    emissions = [_emission("sintering::co2-sinter-out", SINTERING)]
    del emissions[0]["flow_uuid"]
    emissions.append(_emission("furnace::co2-furnace-out", FURNACE))
    error = _codes(
        lambda: _derive(packages=[_method_package(_manifest(emissions=emissions))])
    )
    assert error.code == "MODEL_ELEMENTARY_FLOW_TEMPLATE_MISMATCH"
    assert error.details["identity_drift"][0]["fields"]["flowUuid"]["absent_on"] == ["method"]


def test_a_declared_emission_flow_without_any_exchange_identity_is_unreadable():
    emissions = [_emission("sintering::co2-sinter-out", SINTERING)]
    del emissions[0]["exchange_id"]
    emissions.append(_emission("furnace::co2-furnace-out", FURNACE))
    error = _codes(lambda: _derive(packages=[_method_package(_manifest(emissions=emissions))]))
    assert error.code == "MODEL_PROCESSING_DECLARATION_UNREADABLE"
    assert error.details["rule_indexes"] == [0]


def test_a_compartment_the_model_does_not_record_is_not_invented_to_break_the_template():
    # The stored port carries no compartment, so the method's compartment is not a claim the model
    # can be asked to confirm - requiring it would refuse the real steel asset.
    emissions = [_emission("sintering::co2-sinter-out", SINTERING)]
    emissions[0]["compartment"] = "Something else entirely"
    emissions.append(_emission("furnace::co2-furnace-out", FURNACE))
    derived = _derive(packages=[_method_package(_manifest(emissions=emissions))])
    assert [action["action"] for action in derived.actions].count("verify_elementary_flows") == 1


def test_a_compartment_both_sides_do_record_still_has_to_agree():
    graph = _graph()
    _sintering_port(graph)["compartment"] = "Emissions to water"
    error = _codes(lambda: _derive(graph=graph))
    assert error.code == "MODEL_ELEMENTARY_FLOW_TEMPLATE_MISMATCH"
    assert error.details["identity_drift"][0]["fields"]["compartment"] == {
        "model": "Emissions to water",
        "method": "Emissions to air, unspecified",
    }


# ---- the derived model never shares an object with the stored one -----------------------


def test_editing_a_kept_exchange_of_the_derived_model_leaves_the_stored_model_alone():
    graph = _graph()
    graph["exchanges"][0]["provenance"] = {"note": "as saved", "sources": ["a"]}
    stored_hash = canonical_graph_sha256(graph)
    derived = _derive("lca", graph=graph)
    kept = next(
        edge for edge in derived.graph["exchanges"] if edge["id"] == graph["exchanges"][0]["id"]
    )
    assert kept is not graph["exchanges"][0]
    kept["amount"] = 999
    kept["provenance"]["note"] = "rewritten"
    kept["provenance"]["sources"].append("b")
    assert canonical_graph_sha256(graph) == stored_hash
    assert graph["exchanges"][0]["amount"] != 999
    assert graph["exchanges"][0]["provenance"] == {"note": "as saved", "sources": ["a"]}


def test_editing_the_stored_model_after_derivation_leaves_the_derived_model_alone():
    graph = _graph()
    derived = _derive("lca", graph=graph)
    derived_hash = derived.derived_graph_sha256
    for edge in graph["exchanges"]:
        edge["amount"] = -1
    for node in graph["nodes"]:
        for port in [*node["inputs"], *node["outputs"]]:
            port["name"] = "rewritten label"
    assert canonical_graph_sha256(derived.graph) == derived_hash
    assert derived.graph["exchanges"][0]["amount"] != -1


def test_a_whole_plant_emission_the_method_excludes_never_reaches_the_calculation_model():
    source = _plant()
    frozen = deepcopy(source)
    derived = _derive_explicit(graph=source)
    assert source == frozen, "the stored model is never edited by a decision"
    ports = _ports(derived.graph)
    assert "furnace::ch4-furnace-out" not in ports
    assert {"sintering::co2-sinter-out", "furnace::co2-furnace-out"} <= set(ports)
    assert [(item["exchange_id"], item["state"]) for item in derived.flow_map] == [
        ("furnace::ch4-furnace-out", "excluded"),
        ("furnace::co2-furnace-out", "included"),
        ("sintering::co2-sinter-out", "included"),
    ]
    assert {item["clause"] for item in derived.flow_map} == {"TEST-CLASSIFY", "TEST-OUT-OF-SCOPE"}
    assert derived.record()["counts"]["excluded_emission_exchanges"] == 1
    action = next(
        item for item in derived.actions if item["action"] == "classify_elementary_flows"
    )
    assert action["excluded_exchange_ids"] == ["furnace::ch4-furnace-out"]
    assert action["method_package"]["package_id"] == PACKAGE_ID


def test_the_selection_record_is_exactly_what_the_deriver_decided():
    """The one record solve, freeze, CBAM reading and report share is built here, not downstream.

    A consumer may not resolve a counted list of its own from the method package once a calculation
    model has been derived, so this pins the whole shape: the package identity and manifest path the
    decisions were read from, the two id sets, and a per-exchange entry for every decision the model
    carries. It also has to survive the JSON round trip a receipt performs, because that is where the
    freeze compares it.
    """
    derived = _derive_explicit(graph=_plant())
    action = next(
        item for item in derived.actions if item["action"] == "classify_elementary_flows"
    )
    selection = flow_selection_of(derived)

    assert selection["schema_version"] == FLOW_SELECTION_SCHEMA_VERSION
    assert selection["mode"] == action["mode"] == "explicit_flow_rules"
    assert selection["method_package"] == action["method_package"]
    assert selection["manifest_path"] == action["manifest_path"]
    assert selection["included_exchange_ids"] == action["included_exchange_ids"]
    assert selection["excluded_exchange_ids"] == action["excluded_exchange_ids"]
    assert [(item["exchange_id"], item["state"], item["clause"]) for item in selection["decisions"]] == [
        (item["exchange_id"], item["state"], item["clause"]) for item in derived.flow_map
    ]
    assert all(
        set(item) == {"exchange_id", "process_uuid", "state", "clause", "greenhouse_gas"}
        for item in selection["decisions"]
    )
    assert json.loads(json.dumps(selection)) == selection
    assert canonical_json_sha256(selection) == canonical_json_sha256(
        json.loads(json.dumps(selection))
    )

    # A purpose whose template pre-limits its emissions decides nothing exchange by exchange, so the
    # package's declared list *is* the counted set and no selection is recorded on either side.
    assert flow_selection_of(_derive("lca", graph=_plant())) is None
    assert flow_selection_of(None) is None


def test_a_method_that_counts_every_emission_of_the_boundary_derives_one_same_model():
    """An all-include decision set and a pre-limited template must not be two different answers."""
    rules, package = _explicit(
        decisions=[
            _decision("sintering::co2-sinter-out", SINTERING, "include"),
            _decision("furnace::co2-furnace-out", FURNACE, "include"),
        ]
    )
    graph = _graph()
    assert (
        _derive_explicit(graph=graph, rules=rules, packages=[package]).derived_graph_sha256
        == _derive(graph=graph).derived_graph_sha256
    )


def test_a_process_outside_the_boundary_takes_its_emissions_without_a_decision():
    """An extension the method never selected must not make the calculation unanswerable."""
    graph = _plant()
    furnace = next(node for node in graph["nodes"] if node["id"] == "electricity-grid")
    furnace["outputs"].append(
        _port("co2-grid-out", "co2-fossil", "kg", 900.0, "biosphere",
              namespace="tiangong_open_data", version="03.00.004")
    )
    derived = _derive_explicit(graph=graph)
    assert all(item["process_uuid"] != GRID for item in derived.process_map if item["state"] == "kept")
    assert "electricity-grid::co2-grid-out" not in _ports(derived.graph)
    assert len(derived.flow_map) == 3


def test_the_other_purpose_still_sees_the_extension_the_boundary_excluded():
    """Classification is one purpose's decision; a whole-plant model stays whole for the others."""
    graph = _plant()
    derived = _derive("lca", graph=graph)
    assert "furnace::ch4-furnace-out" in _ports(derived.graph)
    assert derived.derived_graph_sha256 == canonical_graph_sha256(graph)
    assert derived.flow_map == []


def test_changing_an_included_emission_moves_the_selection_and_the_model():
    graph = _plant()
    _set_amount(graph, "furnace::co2-furnace-out", 44.0)
    changed = _derive_explicit(graph=graph)
    unchanged = _derive_explicit(graph=_plant())
    assert changed.derived_graph_sha256 != unchanged.derived_graph_sha256
    assert _flow_entry(changed, "furnace::co2-furnace-out")["amount"] == 44.0


def test_changing_an_excluded_emission_cannot_move_this_purpose_s_model():
    graph = _plant()
    _set_amount(graph, "furnace::ch4-furnace-out", 99.0)
    changed = _derive_explicit(graph=graph)
    unchanged = _derive_explicit(graph=_plant())
    assert changed.derived_graph_sha256 == unchanged.derived_graph_sha256
    assert _flow_entry(changed, "furnace::ch4-furnace-out")["amount"] == 99.0
    assert _flow_entry(unchanged, "furnace::ch4-furnace-out")["amount"] == 7.5


def _set_amount(graph, exchange_id, amount):
    node_id, port_id = exchange_id.split("::")
    node = next(item for item in graph["nodes"] if item["id"] == node_id)
    port = next(
        item for side in ("inputs", "outputs") for item in node[side] if item["id"] == port_id
    )
    port["amount"] = amount


def _flow_entry(derived, exchange_id):
    return next(item for item in derived.flow_map if item["exchange_id"] == exchange_id)


def _decisions_with(**overrides):
    decisions = _whole_plant_decisions()
    for exchange_id, change in overrides.items():
        rule = next(item for item in decisions if item["exchange_id"] == exchange_id)
        if change is None:
            decisions.remove(rule)
        else:
            rule.update(change)
    return decisions


def _derive_with(decisions):
    rules, package = _explicit(decisions=decisions)
    return _derive_explicit(rules=rules, packages=[package])


def test_an_emission_with_no_decision_refuses_rather_than_answering_from_the_rest():
    decisions = _decisions_with(**{"furnace::ch4-furnace-out": None})
    error = _codes(lambda: _derive_with(decisions))
    assert error.code == "MODEL_ELEMENTARY_FLOW_CLASSIFICATION_REQUIRED"
    assert error.details["exchange_ids"] == ["furnace::ch4-furnace-out"]


def test_an_exclusion_without_a_clause_is_not_a_reviewed_basis():
    decisions = _decisions_with(**{"furnace::ch4-furnace-out": {"clause": ""}})
    error = _codes(lambda: _derive_with(decisions))
    assert error.code == "MODEL_PROCESSING_DECLARATION_UNREADABLE"
    assert error.details["rule_index"] == 2


def test_a_decision_that_forgets_the_process_instance_cannot_be_matched():
    decisions = _decisions_with(**{"furnace::co2-furnace-out": {"process_uuid": ""}})
    error = _codes(lambda: _derive_with(decisions))
    assert error.code == "MODEL_PROCESSING_DECLARATION_UNREADABLE"
    assert error.details["rule_index"] == 1


def test_one_exchange_classified_both_ways_refuses_instead_of_choosing():
    decisions = _whole_plant_decisions() + [
        _decision("furnace::co2-furnace-out", FURNACE, "exclude", clause="TEST-OTHER")
    ]
    error = _codes(lambda: _derive_with(decisions))
    assert error.code == "MODEL_ELEMENTARY_FLOW_CLASSIFIED_TWICE"
    assert error.details["exchange_id"] == "furnace::co2-furnace-out"


def test_a_decision_about_a_technical_exchange_is_not_an_emission_decision():
    """The four things a rule may select stay four different things."""
    decisions = _whole_plant_decisions() + [
        _decision("furnace::pci-coal-in", FURNACE, "exclude", flow="pci-coal")
    ]
    error = _codes(lambda: _derive_with(decisions))
    assert error.code == "MODEL_ELEMENTARY_FLOW_DECISION_NOT_ELEMENTARY"
    assert error.details["exchange_type"] == "technosphere"


def test_a_decision_naming_an_exchange_this_model_does_not_have_is_a_drift():
    decisions = _whole_plant_decisions() + [
        _decision("sintering::co2-sinter-pile-out", SINTERING, "exclude")
    ]
    error = _codes(lambda: _derive_with(decisions))
    assert error.code == "MODEL_ELEMENTARY_FLOW_DECISION_NOT_IN_MODEL"
    assert error.details["exchange_id"] == "sintering::co2-sinter-pile-out"


def test_an_excluded_flow_still_has_to_match_the_model_identity_exactly():
    # A decision that removes a flow is not allowed a weaker proof than one that keeps it.
    decisions = _decisions_with(**{"furnace::ch4-furnace-out": {"version": "03.00.099"}})
    error = _codes(lambda: _derive_with(decisions))
    assert error.code == "MODEL_ELEMENTARY_FLOW_IDENTITY_MISMATCH"
    assert error.details["fields"]["flowVersion"] == {
        "model": "03.00.004",
        "method": "03.00.099",
    }


def test_an_included_gas_the_declared_boundary_does_not_accept_refuses():
    decisions = _decisions_with(
        **{"furnace::ch4-furnace-out": {"disposition": "include", "clause": "TEST-CLASSIFY"}}
    )
    error = _codes(lambda: _derive_with(decisions))
    assert error.code == "MODEL_ELEMENTARY_FLOW_GAS_NOT_APPLICABLE"
    assert error.details["applicable_gases"] == ["CO2"]


def test_excluding_an_emission_drops_its_elementary_flow_reference_too():
    """A narrowed emission must leave no elementary-flow reference behind, or the solver reports a
    reference to an exchange that is no longer in the inventory it was handed."""
    graph = _plant()
    graph["metadata"]["elementary_flow_refs"] = [
        {"exchange_id": "sintering::co2-sinter-out", "flow_uuid": "co2-fossil",
         "direction": "output", "compartment": "Emissions to air, unspecified"},
        {"exchange_id": "furnace::co2-furnace-out", "flow_uuid": "co2-fossil",
         "direction": "output", "compartment": "Emissions to air, unspecified"},
        {"exchange_id": "furnace::ch4-furnace-out", "flow_uuid": "ch4-fossil",
         "direction": "output", "compartment": "Emissions to air, unspecified"},
    ]
    rules, package = _explicit(decisions=_whole_plant_decisions())
    background, mapped = _saved_pins()
    excluded = "sintering::co2-sinter-out"
    user_selection = {
        "source": {"method_id": "m-variant", "version": 1, "content_sha256": "a" * 64},
        "rules": [
            {"process_instance_id": "sintering", "exchange_id": excluded, "flow_uuid": None,
             "direction": "emission", "boundary_status": "excluded", "location_role": "onsite",
             "scope": None, "cbam_relevant": True, "classification_basis": "user",
             "schema_version": 1, "contribution_target": "direct", "boundary": None,
             "categories": {}, "base_method_ref": None},
        ],
    }
    derived = derive_calculation_model(
        graph=graph,
        demand=[{"process_uuid": CASTING, "amount": 1.0, "unit": "kg"}],
        rules=rules,
        purpose="cbam",
        method_packages=[package],
        background_process_pins=background,
        mapped_background_process_pins=mapped,
        user_selection=user_selection,
    )
    refs = {ref["exchange_id"] for ref in derived.graph["metadata"]["elementary_flow_refs"]}
    assert excluded not in refs
    assert "furnace::co2-furnace-out" in refs
    # The port is gone from the graph too, and the retained emissions keep their references.
    assert excluded not in {
        f"{node['id']}::{port['id']}"
        for node in derived.graph["nodes"]
        for port in (node.get("outputs") or [])
    }


def test_a_model_port_missing_its_flow_identity_is_never_read_as_agreeing():
    graph = _plant()
    node = next(item for item in graph["nodes"] if item["id"] == "sintering")
    port = next(item for item in node["outputs"] if item["id"] == "co2-sinter-out")
    del port["flowVersion"]
    error = _codes(lambda: _derive_explicit(graph=graph))
    assert error.code == "MODEL_ELEMENTARY_FLOW_IDENTITY_MISMATCH"
    assert error.details["fields"]["flowVersion"]["absent_on"] == ["model"]


def test_rules_that_ask_for_in_model_precursor_expansion_report_the_gap():
    cbam = _rules().purpose("cbam").model_dump()
    cbam["precursors"] = {"mode": "in_model_expansion"}
    error = _codes(lambda: _derive(rules=_rules(cbam=cbam)))
    assert error.code == "MODEL_PRECURSOR_EXPANSION_UNSUPPORTED"


# ---- narrower selections ----------------------------------------------------------


def test_excluding_a_consumer_takes_its_edges_without_a_boundary_declaration():
    boundary = [SINTERING, FURNACE]
    cbam = _rules().purpose("cbam").model_dump()
    cbam["cross_boundary_connections"]["boundary_exchanges"] = _boundary_exchanges(
        ["sintering::grid-electricity-in", "furnace::grid-electricity-in"]
    )
    rules = _rules(cbam=cbam)
    manifest = _manifest(
        boundary=boundary,
        emissions=[
            _emission("sintering::co2-sinter-out", SINTERING),
            _emission("furnace::co2-furnace-out", FURNACE),
        ],
    )
    graph = _graph()
    # A narrower study also narrows what it reports a result for.
    graph["metadata"]["reference_exchange_id"] = "furnace::hot-metal-out"
    derived = _derive(
        graph=graph,
        rules=rules,
        packages=[_method_package(manifest)],
        demand=[{"process_uuid": FURNACE, "amount": 1.0, "unit": "kg"}],
    )
    states = {item["source_exchange_id"]: item["state"] for item in derived.exchange_map}
    assert states["edge-hot-metal"] == "removed_with_excluded_process"
    assert states["edge-grid-casting"] == "removed_with_excluded_process"
    assert states["edge-grid-sintering"] == "replaced_by_declared_boundary_input"
    assert states["edge-sinter"] == "kept"
    assert len(derived.graph["exchanges"]) == 1
    assert derived.record()["counts"]["boundary_inputs"] == 2
    assert derived.record()["counts"]["removed_exchanges"] == 4


def test_keep_declared_links_only_retains_exactly_the_declared_association():
    cbam = _rules().purpose("cbam").model_dump()
    cbam["background_disposition"] = {
        **cbam["background_disposition"],
        "mode": "keep_declared_links_only",
        "retained_consumer_exchange_ids": ["sintering::iron-ore-in"],
    }
    derived = _derive(
        rules=_rules(cbam=cbam),
        demand=[{"process_uuid": SINTERING, "amount": 1.0, "unit": "kg"}],
    )
    assert [pin["consumer_exchange_id"] for pin in derived.background_process_pins] == [
        "sintering::iron-ore-in"
    ]
    assert derived.mapped_background_process_pins == []
    unlinked = [
        action["consumer_exchange_id"]
        for action in derived.actions
        if action["action"] == "unlink_background"
    ]
    assert unlinked == ["furnace::pci-coal-in"]


def test_a_selective_retention_rule_must_declare_what_it_retains():
    cbam = _rules().purpose("cbam").model_dump()
    cbam["background_disposition"]["mode"] = "keep_declared_links_only"
    with pytest.raises(DomainError) as caught:
        _rules(cbam=cbam)
    assert caught.value.code == "MODEL_PROCESSING_PACKAGE_INVALID"
    assert "must declare which background associations it retains" in caught.value.message

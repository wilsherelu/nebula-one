"""The bundled steel rule package against the committed steel template, model and method package.

This is an asset-contract regression, not an engine acceptance test: it proves the reviewed rules
still bind the template and method package that ship in this repository, and that both accounting
purposes derive from the same stored model. No solve, no numbers.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from nebula_one.errors import DomainError
from nebula_one.hashing import canonical_graph_sha256, canonical_json_sha256
from nebula_one.mapped_background_schemas import ProviderMappedBackgroundProcessPin
from nebula_one.model_derivation import derive_calculation_model
from nebula_one.model_processing_contract import load_model_processing_rules_for_template
from nebula_one.runtime_schemas import ProviderBackgroundProcessPin
from nebula_one.services.project_template_profiles import load_profile
from nebula_one.services.model_processing_runtime import flow_selection_of
from nebula_one.services.returned_cbam_binding import _identity_graph
from nebula_one.runtime_schemas import MethodPackageCreate

SEED = Path("cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel")
TEMPLATE_ID = "steel-bf-bof-inventory"


def _template_profile():
    seed = json.loads((SEED / "seed.json").read_text(encoding="utf-8"))
    installation = SimpleNamespace(
        seed_id=seed["seed_id"],
        seed_version=seed["version"],
        bundle_content_sha256=seed["content_pins"]["bundle_content_sha256"],
    )
    return load_profile(["cases"], installation)


def _template_identity() -> dict[str, str]:
    """The full template identity a rule package must have been reviewed against."""
    profile, digest, _ = _template_profile()
    return {"id": profile["id"], "version": profile["version"], "content_sha256": digest}


def _graph() -> dict:
    stored = json.loads((SEED / "model" / "graph.json").read_text(encoding="utf-8"))
    return stored["graph"]


def test_versioned_identity_selector_uses_actual_returned_port_and_excludes_outside_process():
    graph = _graph()
    co2 = next(port for node in graph["nodes"] for port in node["outputs"]
               if port["id"] == "co2-sinter-breeze-out")
    secondary = next(node for node in graph["nodes"] if node["id"] == "secondary-metallurgy-and-degassing")
    secondary["outputs"].append({**deepcopy(co2), "id": "fresh_local_port", "amount": 1.0})
    outside = deepcopy(graph["nodes"][0])
    outside.update(id="external-process", process_uuid="outside-cbam-boundary")
    graph["nodes"].append(outside)
    path = Path("src/nebula_one/resources/official_methods/cbam-steel-direct-selector-1.2.4.json")
    package = MethodPackageCreate.model_validate(json.loads(path.read_text(encoding="utf-8")))
    method = package.model_dump(mode="json")
    method["content_sha256"] = canonical_json_sha256(method)
    rules = load_model_processing_rules_for_template(
        _template_identity(), graph_identity_sha256=canonical_json_sha256(_identity_graph(graph)),
        graph=graph)
    assert rules.version == "1.0.9"
    derived = derive_calculation_model(
        graph=graph, demand=[{"process_uuid": secondary["process_uuid"], "amount": 1, "unit": "kg"}],
        rules=rules, purpose="cbam", method_packages=[method])
    selection = flow_selection_of(derived)
    assert selection["mode"] == "identity_selector_rules"
    assert "secondary-metallurgy-and-degassing::fresh_local_port" in selection["included_exchange_ids"]
    assert len(selection["included_exchange_ids"]) == 7
    assert "external-process" not in {node["id"] for node in derived.graph["nodes"]}
    unknown = deepcopy(graph)
    secondary_unknown = next(node for node in unknown["nodes"] if node["id"] == secondary["id"])
    secondary_unknown["outputs"].append({**deepcopy(co2), "id": "unknown_port", "flowUuid": "unknown"})
    with pytest.raises(DomainError) as error:
        derive_calculation_model(
            graph=unknown, demand=[{"process_uuid": secondary["process_uuid"], "amount": 1, "unit": "kg"}],
            rules=rules, purpose="cbam", method_packages=[method])
    assert error.value.code == "MODEL_ELEMENTARY_FLOW_CLASSIFICATION_REQUIRED"
    assert error.value.details["exchange_ids"] == ["secondary-metallurgy-and-degassing::unknown_port"]
    lca = derive_calculation_model(
        graph=unknown, demand=[{"process_uuid": secondary["process_uuid"], "amount": 1, "unit": "kg"}],
        rules=rules, purpose="lca", method_packages=[])
    assert any(port["id"] == "fresh_local_port" for node in lca.graph["nodes"]
               for port in node["outputs"])


def _method_package() -> dict:
    """The template's effective CBAM package exactly as the profile resolves it, digest included."""
    _, _, replacements = _template_profile()
    _, package, digest = replacements[0]
    return dict(package.model_dump(mode="json"), content_sha256=digest)


def _open_input_ports(graph, port_id):
    return [
        (node, port)
        for node in graph["nodes"]
        for port in node["inputs"]
        if port["id"] == port_id
    ]


def _saved_associations(graph):
    """One native leaf pin and one mapped pin, on the two real open electricity inputs."""
    ports = _open_input_ports(graph, "grid-electricity-in")
    assert [node["id"] for node, _ in ports] == ["ore-sintering", "continuous-casting"]
    background = ProviderBackgroundProcessPin(
        consumer_exchange_id=f"{ports[0][0]['id']}::grid-electricity-in",
        process_uuid="11111111-1111-4111-8111-111111111111",
        version="03.00.004",
        expected_process_content_hash="a" * 64,
        expected_process_snapshot_hash="b" * 64,
        quantitative_reference_exchange_internal_id="qref-1",
    )
    _, port = ports[1]
    mapped = ProviderMappedBackgroundProcessPin(
        consumer_exchange_id=f"{ports[1][0]['id']}::grid-electricity-in",
        source_flow_namespace=port["flowSourceNamespace"],
        source_flow_uuid=port["flowUuid"],
        source_flow_version=port["flowVersion"],
        target_flow_uuid="22222222-2222-4222-8222-222222222222",
        source_unit=port["unit"],
        target_unit=port["unit"],
        amount_factor=1.0,
        mapping_level="L1",
        mapping_status="auto",
        mapping_rule_id="test-grid-mapping",
        mapping_package_id="test.mapping-package",
        mapping_package_version="1.0.0",
        mapping_package_hash="c" * 64,
        database_release="test_release",
        process_uuid="33333333-3333-4333-8333-333333333333",
        expected_process_content_hash="d" * 64,
        expected_vector_checksum="e" * 64,
    )
    return [background.model_dump(mode="json")], [mapped.model_dump(mode="json")]


def _derive(purpose, *, graph=None, background=None, mapped=None, packages=None):
    graph = graph if graph is not None else _graph()
    default_background, default_mapped = _saved_associations(graph)
    dumped = _method_package()
    return derive_calculation_model(
        graph=graph,
        demand=[
            {
                "process_uuid": "ea66dbd3-03e1-5ff8-a1d0-9662604392c0",
                "amount": 1000.0,
                "unit": "kg",
            }
        ],
        rules=load_model_processing_rules_for_template(_template_identity()),
        purpose=purpose,
        method_packages=packages if packages is not None else [dumped],
        background_process_pins=background if background is not None else default_background,
        mapped_background_process_pins=mapped if mapped is not None else default_mapped,
    )


def test_bundled_rules_bind_the_committed_template_and_method_package_identities():
    rules = load_model_processing_rules_for_template(_template_identity())
    profile, digest, _ = _template_profile()
    assert rules.applicable_template.id == profile["id"] == TEMPLATE_ID
    assert rules.applicable_template.version == profile["version"]
    assert rules.applicable_template.content_sha256 == digest

    package = _method_package()
    for ref in (
        rules.purpose("cbam").process_selection.method_package,
        rules.purpose("cbam").background_disposition.evidence.method_package,
        rules.purpose("cbam").elementary_flows.evidence.method_package,
    ):
        assert (ref.package_id, ref.version, ref.content_sha256) == (
            package["package_id"],
            package["version"],
            package["content_sha256"],
        )


def test_rules_never_repeat_a_process_or_exchange_identity_the_method_package_owns():
    rules_text = json.dumps(
        json.loads(
            Path("src/nebula_one/resources/model_processing/steel-bf-bof-model-processing-1.0.11.json").read_text(
                encoding="utf-8"
            )
        ),
        ensure_ascii=False,
    )
    graph = _graph()
    dumped = _method_package()
    emissions = dumped["manifest"]["classification_rules"]["direct_emissions"]
    assert len(emissions) == 6
    for rule in emissions:
        assert rule["exchange_id"] not in rules_text
    for node in graph["nodes"]:
        assert node["process_uuid"] not in rules_text


def test_lca_purpose_derives_the_stored_model_with_every_saved_association():
    graph = _graph()
    derived = _derive("lca", graph=graph)
    assert derived.derived_graph_sha256 == derived.source_graph_sha256
    assert derived.graph == graph
    assert len(derived.background_process_pins) == 1
    assert len(derived.mapped_background_process_pins) == 1
    assert [action["action"] for action in derived.actions] == ["select_processes"]


def test_cbam_purpose_unlinks_both_associations_and_keeps_both_input_exchanges():
    graph = _graph()
    derived = _derive("cbam", graph=graph)
    assert derived.graph == graph, (
        "the steel model carries no in-graph supplier, so unlinking must leave the stored graph"
        " byte-for-byte intact"
    )
    assert derived.background_process_pins == []
    assert derived.mapped_background_process_pins == []

    source_ports = {
        f"{node['id']}::{port['id']}": port
        for node, port in _open_input_ports(graph, "grid-electricity-in")
    }
    derived_ports = {
        f"{node['id']}::{port['id']}": port
        for node, port in _open_input_ports(derived.graph, "grid-electricity-in")
    }
    assert derived_ports == source_ports
    assert sorted(source_ports) == [
        "continuous-casting::grid-electricity-in",
        "ore-sintering::grid-electricity-in",
    ]
    assert {port["unit"] for port in derived_ports.values()} == {"MJ"}

    unlinked = {
        action["consumer_exchange_id"]: action
        for action in derived.actions
        if action["action"] == "unlink_background"
    }
    assert sorted(unlinked) == sorted(source_ports)
    assert {action["kind"] for action in unlinked.values()} == {"background", "mapped"}
    assert all(
        action["clause"].startswith("Selected direct component")
        for action in unlinked.values()
    )


def test_cbam_purpose_verifies_the_template_pre_limited_emission_set_by_identity():
    derived = _derive("cbam")
    verification = next(
        action for action in derived.actions if action["action"] == "verify_elementary_flows"
    )
    dumped = _method_package()
    assert verification["mode"] == "template_prelimited"
    assert verification["applicable_gases"] == ["CO2"]
    assert verification["verified_exchange_ids"] == sorted(
        rule["exchange_id"] for rule in dumped["manifest"]["classification_rules"]["direct_emissions"]
    )
    assert derived.record()["counts"] == {
        "source_processes": 5,
        "derived_processes": 5,
        "source_exchanges": 4,
        "removed_exchanges": 0,
        "boundary_inputs": 0,
        "unlinked_background_links": 2,
        "classified_emission_exchanges": 0,
        "excluded_emission_exchanges": 0,
    }


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
def test_a_real_steel_emission_flow_missing_any_required_identity_refuses(port_key):
    """The committed steel ports do carry every identity, so dropping one is a broken model."""
    graph = _graph()
    port = next(
        port
        for node in graph["nodes"]
        for port in node["outputs"]
        if port["id"] == "co2-sinter-breeze-out"
    )
    del port[port_key]
    with pytest.raises(DomainError) as caught:
        _derive("cbam", graph=graph)
    assert caught.value.code == "MODEL_ELEMENTARY_FLOW_TEMPLATE_MISMATCH"
    drift = caught.value.details["identity_drift"]
    assert [item["exchange_id"] for item in drift] == ["ore-sintering::co2-sinter-breeze-out"]
    assert drift[0]["fields"][port_key]["absent_on"] == ["model"]


def test_the_derived_steel_model_shares_no_exchange_object_with_the_stored_one():
    graph = _graph()
    stored_hash = canonical_graph_sha256(graph)
    derived = _derive("cbam", graph=graph)
    assert derived.graph["exchanges"], "the stored steel model does keep its internal exchanges"
    assert all(
        derived_edge is not stored_edge
        for derived_edge in derived.graph["exchanges"]
        for stored_edge in graph["exchanges"]
    )
    for edge in derived.graph["exchanges"]:
        edge["amount"] = 999
        edge["providerAmount"] = 999
    assert canonical_graph_sha256(graph) == stored_hash


def test_an_undeclared_emission_flow_in_the_steel_model_is_a_template_mismatch():
    graph = _graph()
    for node in graph["nodes"]:
        if node["id"] == "blast-furnace":
            node["outputs"].append(
                dict(node["outputs"][-1], id="ch4-bf-out", name="Methane (fossil)")
            )
    with pytest.raises(DomainError) as caught:
        _derive("cbam", graph=graph)
    assert caught.value.code == "MODEL_ELEMENTARY_FLOW_TEMPLATE_MISMATCH"
    assert caught.value.details["undeclared_in_method"] == ["blast-furnace::ch4-bf-out"]


def test_a_method_flow_version_drift_is_caught_against_the_real_graph():
    dumped = _method_package()
    manifest = json.loads(json.dumps(dumped["manifest"]))
    manifest["classification_rules"]["direct_emissions"][0]["version"] = "03.00.005"
    with pytest.raises(DomainError) as caught:
        _derive("cbam", packages=[dict(dumped, manifest=manifest)])
    assert caught.value.code == "MODEL_ELEMENTARY_FLOW_TEMPLATE_MISMATCH"
    drift = caught.value.details["identity_drift"]
    assert len(drift) == 1
    assert drift[0]["fields"]["flowVersion"]["method"] == "03.00.005"


def test_the_pre_limiting_evidence_is_read_from_the_package_rather_than_assumed():
    dumped = _method_package()
    manifest = json.loads(json.dumps(dumped["manifest"]))
    manifest["boundary_schema"]["annex_ii_direct_only"] = False
    with pytest.raises(DomainError) as caught:
        _derive("cbam", packages=[dict(dumped, manifest=manifest)])
    assert caught.value.code == "MODEL_PROCESSING_EVIDENCE_NOT_DECLARED"
    assert caught.value.details["found"] is False


def test_saved_associations_on_a_port_the_model_supplies_internally_are_refused():
    background, mapped = _saved_associations(_graph())
    background[0]["consumer_exchange_id"] = "blast-furnace::sinter-in"
    with pytest.raises(DomainError) as caught:
        _derive("lca", background=background, mapped=mapped)
    assert caught.value.code == "MODEL_DERIVATION_PIN_CONFLICT"

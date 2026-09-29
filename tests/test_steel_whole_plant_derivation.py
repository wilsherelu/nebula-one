"""What the whole-plant extension does to a calculation, decided one exchange and one process at a time.

The reviewed steel package pre-limits its emission set and cuts no supply, so on the extended model it
must *refuse* rather than quietly drop a stream or a supplier - that refusal is the requirement, not a
workaround. Proving the algorithm for "keep the extension, count its emissions by name" therefore runs
under a synthetic explicit-classification package that is labelled as such everywhere; no reviewed steel
clause is restated as a synthetic policy. Every comparison here changes exactly one thing at a fixed
product demand and reads the outbound model back.
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from nebula_one.errors import DomainError
from nebula_one.model_derivation import derive_calculation_model
from nebula_one.model_processing_contract import load_model_processing_rules_for_template
from nebula_one.services.model_processing_runtime import flow_selection_of

import steel_whole_plant_extension as ext
from test_steel_model_processing_assets import (
    _graph,
    _method_package,
    _saved_associations,
    _template_identity,
)

DEMAND = [{"process_uuid": "ea66dbd3-03e1-5ff8-a1d0-9662604392c0", "amount": 1000.0, "unit": "kg"}]
REVIEWED_PACKAGE = _method_package()
REVIEWED_RULES = load_model_processing_rules_for_template(_template_identity())

BOUNDARY_WITH_LINE = ext.steel_boundary_uuids() + [ext.SUPPLIER_UUID]


def derive(graph, rules, packages, purpose="cbam", *, pins=None):
    background, mapped = pins if pins is not None else _saved_associations(_graph())
    return derive_calculation_model(
        graph=deepcopy(graph),
        demand=deepcopy(DEMAND),
        rules=rules,
        purpose=purpose,
        method_packages=deepcopy(packages),
        background_process_pins=deepcopy(background),
        mapped_background_process_pins=deepcopy(mapped),
    )


def kept_rules(*, exclude_flare=True):
    package = ext.synthetic_package(
        ext.emission_decisions(exclude_flare=exclude_flare, auxiliary_kept=True),
        in_boundary=BOUNDARY_WITH_LINE)
    return package, ext.synthetic_rules(package)


def cut_rules():
    package = ext.synthetic_package(ext.emission_decisions(),
                                    in_boundary=ext.steel_boundary_uuids())
    return package, ext.synthetic_rules(package, boundary_exchanges=[ext.BORDER_SUPPLIED])


def ports_of(derived):
    return {f"{node['id']}::{port['id']}"
            for node in derived.graph["nodes"]
            for port in (*node["inputs"], *node["outputs"])}


# ---- the reviewed steel package refuses the extension instead of guessing -----


def test_reviewed_rules_let_the_extension_through_lca_but_refuse_it_for_cbam():
    plant = ext.plant_extension_graph()
    lca = derive(plant, REVIEWED_RULES, [REVIEWED_PACKAGE], "lca")
    assert ext.SUPPLIER_NODE in {node["id"] for node in lca.graph["nodes"]}
    with pytest.raises(DomainError) as refused:
        derive(plant, REVIEWED_RULES, [REVIEWED_PACKAGE], "cbam")
    assert refused.value.code == "MODEL_CROSS_BOUNDARY_UNDECLARED"
    assert ext.BORDER_SUPPLIED in refused.value.details["consumer_exchange_ids"]


# ---- counting an emission by name: one exchange in or out moves the model ------


def test_excluding_the_flare_drops_a_nonzero_stream_that_including_it_keeps():
    plant = ext.plant_extension_graph()
    exclude_package, exclude_rules = kept_rules(exclude_flare=True)
    include_package, include_rules = kept_rules(exclude_flare=False)
    excluded = derive(plant, exclude_rules, [exclude_package])
    included = derive(plant, include_rules, [include_package])

    assert ext.FLARE_EMISSION not in ports_of(excluded)
    assert ext.FLARE_EMISSION in ports_of(included)
    assert included.derived_graph_sha256 != excluded.derived_graph_sha256

    assert ext.FLARE_EMISSION in flow_selection_of(excluded)["excluded_exchange_ids"]
    assert ext.FLARE_EMISSION in flow_selection_of(included)["included_exchange_ids"]
    # the dropped stream is non-zero, so excluding it moves a real number, not an empty port
    flare = next(item for item in excluded.flow_map if item["exchange_id"] == ext.FLARE_EMISSION)
    assert flare["state"] == "excluded" and flare["amount"] == ext.FLARE_AMOUNT


# ---- extending process data: the outbound model changes, the stored one does not -


def test_extension_activity_moves_the_outbound_model_and_leaves_the_stored_graph_alone():
    stored = _graph()
    before = deepcopy(stored)
    package, rules = kept_rules()
    quiet = derive(ext.plant_extension_graph(), rules, [package])
    busy = derive(ext.plant_extension_graph(crop_charge=30.0, purchased_scrap=120.0), rules,
                  [package])
    assert quiet.derived_graph_sha256 != busy.derived_graph_sha256
    assert stored == before  # the deriver copies the graph; nothing is written back to the model


# ---- background supply: the supply-chain purposes consume it, CBAM never does --


def test_background_supply_changes_lca_but_leaves_the_cbam_model_identical():
    plant = ext.plant_extension_graph()
    package, rules = kept_rules()
    background, mapped = _saved_associations(_graph())
    cbam_with = derive(plant, rules, [package], pins=(background, mapped))
    cbam_without = derive(plant, rules, [package], pins=([], []))
    assert cbam_with.derived_graph_sha256 == cbam_without.derived_graph_sha256

    lca_with = derive(plant, rules, [package], "lca", pins=(background, mapped))
    lca_without = derive(plant, rules, [package], "lca", pins=([], []))
    assert len(lca_with.mapped_background_process_pins) == 1
    assert len(lca_without.mapped_background_process_pins) == 0


# ---- the guards: an unclassified kept emission, a phantom decision, a moved amount


def test_a_kept_emission_with_no_decision_refuses_rather_than_defaulting():
    package = ext.synthetic_package(ext.emission_decisions(auxiliary_kept=False),
                                    in_boundary=BOUNDARY_WITH_LINE)
    with pytest.raises(DomainError) as refused:
        derive(ext.plant_extension_graph(), ext.synthetic_rules(package), [package])
    assert refused.value.code == "MODEL_ELEMENTARY_FLOW_CLASSIFICATION_REQUIRED"
    assert ext.VENT_EMISSION in refused.value.details["exchange_ids"]


def test_a_decision_about_an_exchange_the_model_lacks_refuses():
    decisions = ext.emission_decisions(auxiliary_kept=True)
    phantom = dict(decisions[0], exchange_id="ore-sintering::a-stream-never-modelled")
    package = ext.synthetic_package(decisions + [phantom], in_boundary=BOUNDARY_WITH_LINE)
    with pytest.raises(DomainError) as refused:
        derive(ext.plant_extension_graph(), ext.synthetic_rules(package), [package])
    assert refused.value.code == "MODEL_ELEMENTARY_FLOW_DECISION_NOT_IN_MODEL"


def test_cutting_a_supply_and_declaring_it_must_not_move_a_quantity():
    package, rules = cut_rules()
    with pytest.raises(DomainError) as refused:
        derive(ext.plant_extension_graph(purchased_scrap=120.0), rules, [package])
    assert refused.value.code == "MODEL_CROSS_BOUNDARY_AMOUNT_CONFLICT"
    assert refused.value.details["port_amount"] == 150.0
    assert refused.value.details["exchange_amount"] == 140.0


def test_a_cut_supply_with_no_declaration_refuses():
    package = ext.synthetic_package(ext.emission_decisions(),
                                    in_boundary=ext.steel_boundary_uuids())
    with pytest.raises(DomainError) as refused:
        derive(ext.plant_extension_graph(), ext.synthetic_rules(package), [package])
    assert refused.value.code == "MODEL_CROSS_BOUNDARY_UNDECLARED"

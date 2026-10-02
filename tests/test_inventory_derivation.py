import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from nebula_one.errors import DomainError
from nebula_one.hashing import canonical_json_sha256
from nebula_one.services.inventory_derivation import derive_inventory

PROFILE = json.loads(Path('cases/project-templates/steel-bf-bof-inventory/template.json').read_text(encoding='utf-8'))
GRAPH = json.loads(Path('cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/model/graph.json').read_text(encoding='utf-8'))['graph']
RECIPE = PROFILE['inventory_derivation']


def port(graph, key):
    node_id, port_id = key.split('::')
    return next(p for n in graph['nodes'] if n['id'] == node_id for group in ('inputs','outputs') for p in n[group] if p['id'] == port_id)


def test_shared_methane_and_hot_metal_carbon_basis_and_rounding():
    result, values = derive_inventory(GRAPH, RECIPE)
    methane = Decimal(RECIPE['content']['compositions']['natural_gas'])
    assert methane == Decimal('12.011') / Decimal('16.043')
    assert values['basic-oxygen-converter::co2-converter-decarburisation-out'] == '152.562969'
    assert abs(sum(Decimal(v) for v in values.values()) - Decimal('1940.739734')) <= Decimal('.000002')
    derive_inventory(result, RECIPE, validate_only=True)


@pytest.mark.parametrize('key', ['blast-furnace::coke-in', 'blast-furnace::natural-gas-in', 'basic-oxygen-converter::scrap-in', 'ore-sintering::limestone-in'])
def test_input_changes_update_emissions_and_stale_editor_values_refuse(key):
    baseline, values = derive_inventory(GRAPH, RECIPE)
    changed = deepcopy(baseline)
    port(changed, key)['amount'] += 1
    with pytest.raises(DomainError) as error:
        derive_inventory(changed, RECIPE, validate_only=True)
    assert error.value.code == 'INVENTORY_DERIVATION_STALE'
    updated, new_values = derive_inventory(changed, RECIPE)
    assert sum(Decimal(v) for v in new_values.values()) > sum(Decimal(v) for v in values.values())
    derive_inventory(updated, RECIPE, validate_only=True)


@pytest.mark.parametrize('scale', ['0.001', '1', '2'])
def test_one_1000_and_2000_kg_quantities_scale_once(scale):
    graph = deepcopy(GRAPH)
    for node in graph['nodes']:
        for group in ('inputs','outputs'):
            for p in node[group]:
                p['amount'] = float(Decimal(str(p['amount'])) * Decimal(scale))
    result, values = derive_inventory(graph, RECIPE)
    product = Decimal(str(port(result, 'continuous-casting::crude-steel-slab-out')['amount']))
    intensity = sum(Decimal(v) for v in values.values()) / product
    assert abs(intensity - Decimal('1.940739734')) < Decimal('.000002')


def test_missing_dependency_is_not_zero_and_modified_recipe_fails_hash():
    graph = deepcopy(GRAPH)
    graph['nodes'][0]['inputs'] = [p for p in graph['nodes'][0]['inputs'] if p['id'] != 'coke-breeze-in']
    with pytest.raises(DomainError) as error:
        derive_inventory(graph, RECIPE)
    assert error.value.code == 'INVENTORY_DERIVATION_PORT_MISMATCH'
    recipe = deepcopy(RECIPE)
    recipe['content']['decimal_places'] = 2
    with pytest.raises(DomainError) as error:
        derive_inventory(GRAPH, recipe)
    assert error.value.code == 'INVENTORY_DERIVATION_INVALID'

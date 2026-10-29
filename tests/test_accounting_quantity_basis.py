from copy import deepcopy
from decimal import Decimal

import pytest

from nebula_one.analysis.accounting_quantity_basis import (
    climate_intensity_definition, evaluate_quantity_ratio, legacy_climate_intensity,
    per_reference_output, quantity_ratio_receipt)
from nebula_one.errors import DomainError


@pytest.mark.parametrize('amount,output', [('1940.739734', '1000'), ('0', '1000'),
                                        ('1.0000', '1000.0'), ('-10', '500')])
def test_definition_reproduces_legacy_decimal_values_and_string_representation(amount, output):
    definition = climate_intensity_definition()
    before = deepcopy(definition)
    answer = evaluate_quantity_ratio(definition, numerator=amount, denominator=output)
    old_numerator = Decimal(amount) / Decimal('1000')
    old_denominator = Decimal(output) / Decimal('1000')
    assert str(answer['numerator']) == str(old_numerator)
    assert str(answer['denominator']) == str(old_denominator)
    assert str(answer['value']) == str(old_numerator / old_denominator)
    assert definition == before


def test_exclusion_and_demand_double_once_preserve_intensity_and_physical_ledger():
    all_counted = legacy_climate_intensity({}, counted_kg='1940.739734', product_kg='1000')
    narrowed = legacy_climate_intensity({}, counted_kg='1747.280534', product_kg='1000')
    doubled = legacy_climate_intensity({}, counted_kg='3881.479468', product_kg='2000')
    assert all_counted['value'] - narrowed['value'] == Decimal('0.1934592')
    assert all_counted['value'] == doubled['value']
    assert doubled['numerator'] == 2 * all_counted['numerator']
    assert doubled['denominator'] == 2 * all_counted['denominator']


def test_missing_quantity_is_distinct_from_legal_zero():
    definition = climate_intensity_definition()
    missing = evaluate_quantity_ratio(definition, numerator=None, denominator=1000)
    assert missing['value'] is None and missing['missing'] == ['numerator']
    assert evaluate_quantity_ratio(definition, numerator=0, denominator=1000)['value'] == 0
    assert evaluate_quantity_ratio(definition, numerator=10, denominator=None)['value'] is None


@pytest.mark.parametrize('numerator,denominator', [('NaN', 1000), ('Infinity', 1000),
    (1, 0), (1, -1), (True, 1000), (1, False), ('factor missing', 1000), ('1e9999999999', 1000)])
def test_invalid_quantities_refuse(numerator, denominator):
    with pytest.raises(DomainError) as error:
        evaluate_quantity_ratio(climate_intensity_definition(), numerator=numerator, denominator=denominator)
    assert error.value.code == 'ACCOUNTING_QUANTITY_INVALID'


def test_no_arbitrary_expression_or_factor_injection_and_no_wrong_unit_contract():
    definition = climate_intensity_definition()
    for changed in (dict(definition, operation='eval'), dict(definition, expression='__import__("os")'),
                    dict(definition, schema_version='unknown')):
        with pytest.raises(DomainError) as error:
            evaluate_quantity_ratio(changed, numerator=10, denominator=1000)
        assert error.value.code == 'ACCOUNTING_QUANTITY_DEFINITION_INVALID'
    changed = deepcopy(definition)
    changed['numerator']['target_unit'] = 'kg'
    with pytest.raises(DomainError) as error:
        legacy_climate_intensity({'accounting_quantity_basis': changed}, counted_kg=10, product_kg=1000)
    assert error.value.code == 'ACCOUNTING_QUANTITY_RESULT_CONTRACT_MISMATCH'
    converted = evaluate_quantity_ratio(changed, numerator=10, denominator=1000)
    normal = evaluate_quantity_ratio(definition, numerator=10, denominator=1000)
    assert converted['definition_sha256'] != normal['definition_sha256']


def test_explicit_definition_serializes_a_replayable_receipt():
    definition = climate_intensity_definition()
    legacy = legacy_climate_intensity({}, counted_kg='12.98', product_kg='1')
    explicit = legacy_climate_intensity({'accounting_quantity_basis': definition}, counted_kg='12.98', product_kg='1')
    assert legacy == explicit
    receipt = quantity_ratio_receipt(explicit)
    assert receipt['value'] == '12.98'
    assert receipt['numerator'] == '0.01298' and receipt['denominator'] == '0.001'
    assert len(receipt['definition_sha256']) == 64 and receipt['definition'] == definition


def test_per_reference_output_matches_the_total_base_reference_arithmetic():
    # The plan's arithmetic case: total 2000 kg CO₂-eq for a 1000 kg reference output.
    per_kg = per_reference_output(total_kg='2000', reference_amount='1000', reference_unit='kg',
        base_amount='1', base_unit='kg')
    per_t = per_reference_output(total_kg='2000', reference_amount='1000', reference_unit='kg',
        base_amount='1', base_unit='t')
    assert per_kg['value'] == Decimal('2') and per_kg['unit'] == 'kg CO₂-eq/1 kg'
    assert per_t['value'] == Decimal('2000')
    # A reference output already expressed in tonnes converts to kg exactly once: 1 t == 1000 kg,
    # so the same total over a tonne reference equals the same total over a 1000 kg reference.
    from_tonnes = per_reference_output(total_kg='2000', reference_amount='1', reference_unit='t',
        base_amount='1', base_unit='kg')
    assert from_tonnes['value'] == Decimal('2') == per_kg['value']


def test_per_reference_output_demand_double_doubles_total_but_keeps_intensity():
    base = per_reference_output(total_kg='1940.739734', reference_amount='1000', reference_unit='kg',
        base_amount='1', base_unit='kg')
    doubled = per_reference_output(total_kg='3881.479468', reference_amount='2000', reference_unit='kg',
        base_amount='1', base_unit='kg')
    assert doubled['value'] == base['value']
    assert doubled['reference_kg'] == 2 * base['reference_kg']


def test_per_reference_output_negative_total_is_legal_but_missing_stays_a_gap():
    negative = per_reference_output(total_kg='-10', reference_amount='1000', reference_unit='kg',
        base_amount='1', base_unit='kg')
    assert negative['value'] == Decimal('-0.01')
    gap = per_reference_output(total_kg=None, reference_amount='1000', reference_unit='kg',
        base_amount='1', base_unit='kg')
    assert gap['value'] is None and gap['missing'] == ['total']


@pytest.mark.parametrize('total,ref_amount,ref_unit,base_amount,base_unit,code', [
    ('100', '0', 'kg', '1', 'kg', 'UNIT_PRODUCT_QUANTITY_INVALID'),
    ('100', '-5', 'kg', '1', 'kg', 'UNIT_PRODUCT_QUANTITY_INVALID'),
    ('100', 'NaN', 'kg', '1', 'kg', 'UNIT_PRODUCT_QUANTITY_INVALID'),
    ('100', 'Infinity', 'kg', '1', 'kg', 'UNIT_PRODUCT_QUANTITY_INVALID'),
    ('100', '1000', 'kWh', '1', 'kg', 'UNIT_PRODUCT_INCOMPATIBLE_DENOMINATOR'),
    ('100', '1000', 'kg', '1', 'MJ', 'UNIT_PRODUCT_INCOMPATIBLE_DENOMINATOR'),
    ('100', True, 'kg', '1', 'kg', 'UNIT_PRODUCT_QUANTITY_INVALID'),
    ('100', '1000', 'kg', '0', 'kg', 'UNIT_PRODUCT_QUANTITY_INVALID'),
    ('NaN', '1000', 'kg', '1', 'kg', 'UNIT_PRODUCT_QUANTITY_INVALID'),
])
def test_per_reference_output_refuses_illegal_denominator_base_or_unit(total, ref_amount, ref_unit,
        base_amount, base_unit, code):
    with pytest.raises(DomainError) as error:
        per_reference_output(total_kg=total, reference_amount=ref_amount, reference_unit=ref_unit,
            base_amount=base_amount, base_unit=base_unit)
    assert error.value.code == code


def test_per_reference_output_basis_freezes_only_the_conversion_not_the_snapshot():
    a = per_reference_output(total_kg='2000', reference_amount='1000', reference_unit='kg', base_amount='1', base_unit='kg')
    b = per_reference_output(total_kg='5000', reference_amount='1000', reference_unit='kg', base_amount='1', base_unit='kg')
    # Same denominator/base → same basis identity even though the solved total differs (display切换复用快照).
    assert a['basis_sha256'] == b['basis_sha256']
    c = per_reference_output(total_kg='2000', reference_amount='1000', reference_unit='kg', base_amount='1', base_unit='t')
    assert c['basis_sha256'] != a['basis_sha256']

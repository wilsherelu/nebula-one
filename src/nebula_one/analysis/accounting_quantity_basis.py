"""Typed quantity ratios for accounting results, without executable formulas or factors."""
from __future__ import annotations

from decimal import Decimal, DecimalException, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from ..errors import DomainError
from ..hashing import canonical_json_sha256

SCHEMA_VERSION = 'nebula_one.accounting-quantity-ratio.v1'
KG_PER_UNIT = {'kg': Decimal('1'), 't': Decimal('1000')}


class MassConversion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    dimension: Literal['climate_mass', 'product_mass']
    source_unit: Literal['kg', 't']
    target_unit: Literal['kg', 't']


class QuantityRatioDefinition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal['nebula_one.accounting-quantity-ratio.v1']
    operation: Literal['ratio']
    numerator: MassConversion
    denominator: MassConversion


def climate_intensity_definition() -> dict:
    """Compatibility adapter for the existing kg-based climate/product quantities."""
    return dict(schema_version=SCHEMA_VERSION, operation='ratio',
        numerator=dict(dimension='climate_mass', source_unit='kg', target_unit='t'),
        denominator=dict(dimension='product_mass', source_unit='kg', target_unit='t'))


def evaluate_quantity_ratio(definition: dict, *, numerator, denominator) -> dict:
    """Convert declared units once and divide; missing remains unknown and zero remains zero.

    Inputs are already counted physical/characterized quantities. This operation
    cannot supply CFs, select inventory, or decide regulatory applicability.
    """
    try:
        parsed = QuantityRatioDefinition.model_validate(definition)
    except ValidationError as exc:
        raise DomainError(code='ACCOUNTING_QUANTITY_DEFINITION_INVALID',
                          message='核算计量基准定义无效。', status_code=422) from exc

    def convert(value, conversion, positive=False):
        if value is None:
            return None
        try:
            if isinstance(value, bool):
                raise ValueError('boolean is not a quantity')
            number = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise DomainError(code='ACCOUNTING_QUANTITY_INVALID', message='核算量必须是有限数值。', status_code=422) from exc
        if not number.is_finite() or positive and number <= 0:
            raise DomainError(code='ACCOUNTING_QUANTITY_INVALID', message='核算量必须有限，分母必须大于零。', status_code=422)
        try:
            return number * KG_PER_UNIT[conversion.source_unit] / KG_PER_UNIT[conversion.target_unit]
        except DecimalException as exc:
            raise DomainError(code='ACCOUNTING_QUANTITY_INVALID', message='核算量超出支持的数值范围。', status_code=422) from exc

    converted_numerator = convert(numerator, parsed.numerator)
    converted_denominator = convert(denominator, parsed.denominator, positive=True)
    missing = [key for key, value in [('numerator', numerator), ('denominator', denominator)] if value is None]
    try:
        value = None if missing else converted_numerator / converted_denominator
    except DecimalException as exc:
        raise DomainError(code='ACCOUNTING_QUANTITY_INVALID', message='核算比值超出支持的数值范围。', status_code=422) from exc
    return dict(definition_sha256=canonical_json_sha256(parsed.model_dump()),
                numerator=converted_numerator, denominator=converted_denominator,
                value=value,
                missing=missing, definition=parsed.model_dump())


def legacy_climate_intensity(manifest: dict, *, counted_kg, product_kg) -> dict:
    """Adapt an existing method and enforce its existing t-CO2e/t-product result contract."""
    definition = manifest.get('accounting_quantity_basis', climate_intensity_definition())
    answer = evaluate_quantity_ratio(definition, numerator=counted_kg, denominator=product_kg)
    if answer['definition'] != climate_intensity_definition():
        raise DomainError(code='ACCOUNTING_QUANTITY_RESULT_CONTRACT_MISMATCH',
                          message='该方法输出要求吨二氧化碳当量/吨产品，输入必须保持原始千克口径。', status_code=422)
    return answer


def quantity_ratio_receipt(answer: dict) -> dict:
    return {**answer, **{key: str(answer[key]) if answer[key] is not None else None
                        for key in ('numerator', 'denominator', 'value')}}


# Units a per-reference-output denominator and display base may use. Anything else (e.g. kWh for a
# mass-based product) is an incompatible combination the server must refuse, never a silent fallback.
PRODUCT_MASS_UNITS = {'kg': Decimal('1'), 't': Decimal('1000')}


def _mass_in_kg(value, unit: str, *, field: str, positive: bool):
    if unit not in PRODUCT_MASS_UNITS:
        raise DomainError(code='UNIT_PRODUCT_INCOMPATIBLE_DENOMINATOR',
                          message=f'{field} 使用无法换算的质量单位，已拒绝单位产品结果。', status_code=422)
    try:
        if isinstance(value, bool):
            raise ValueError('boolean is not a quantity')
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DomainError(code='UNIT_PRODUCT_QUANTITY_INVALID',
                          message=f'{field} 必须是有限数值。', status_code=422) from exc
    if not number.is_finite() or (positive and number <= 0):
        raise DomainError(code='UNIT_PRODUCT_QUANTITY_INVALID',
                          message=f'{field} 必须有限且大于零。', status_code=422)
    return number * PRODUCT_MASS_UNITS[unit]


def per_reference_output(*, total_kg, reference_amount, reference_unit: str,
                         base_amount, base_unit: str) -> dict:
    """Convert one solved total to `total × base / reference`, dividing exactly once.

    The reference output (denominator) and the display base must both be a supported mass unit and
    strictly positive; a negative total contribution is legal and stays negative, an unknown total
    stays a gap and never becomes zero or a default denominator of one. The returned `basis_sha256`
    freezes only the denominator/base definition, so switching the display口径 is not a new solve.
    """
    reference_kg = _mass_in_kg(reference_amount, reference_unit, field='参考产出', positive=True)
    base_kg = _mass_in_kg(base_amount, base_unit, field='展示基准', positive=True)
    missing = ['total'] if total_kg is None else []
    if total_kg is None:
        converted_total = None
    else:
        try:
            if isinstance(total_kg, bool):
                raise ValueError('boolean is not a quantity')
            converted_total = Decimal(str(total_kg))
        except (InvalidOperation, ValueError) as exc:
            raise DomainError(code='UNIT_PRODUCT_QUANTITY_INVALID',
                              message='总量必须是有限数值。', status_code=422) from exc
        if not converted_total.is_finite():
            raise DomainError(code='UNIT_PRODUCT_QUANTITY_INVALID',
                              message='总量必须是有限数值。', status_code=422)
    try:
        value = None if missing else converted_total * base_kg / reference_kg
    except DecimalException as exc:
        raise DomainError(code='UNIT_PRODUCT_QUANTITY_INVALID',
                          message='单位产品结果超出支持的数值范围。', status_code=422) from exc
    basis = {'reference_amount': str(reference_amount), 'reference_unit': reference_unit,
             'base_amount': str(base_amount), 'base_unit': base_unit}
    return {'basis_sha256': canonical_json_sha256(basis),
            'reference_kg': reference_kg, 'base_kg': base_kg,
            'value': value, 'missing': missing, 'basis': basis,
            'unit': f'kg CO₂-eq/{base_amount} {base_unit}'}

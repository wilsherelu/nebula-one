"""Server-side result-basis projection over a frozen PCF solve, without re-solving.

The plan's唯一换算规则 makes the backend the sole place a total T and a reference output Q
are turned into a displayed result. ``total`` re-exports the frozen snapshot unchanged (the
raw total stays the single source and every existing byte/hash is preserved);
``per_reference_output`` rescales the total AND every component / hotspot line by the one
``per_reference_output`` primitive's ``base / reference`` ratio, so no line is left on a
different basis. The underlying ``source_snapshot.content_sha256`` (solve hash) never
changes: switching the display口径 is a read-side projection, not a new solve.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from ..errors import DomainError
from ..hashing import canonical_json_sha256
from .accounting_quantity_basis import per_reference_output

BASIS_SCHEMA = 'nebula_one.pcf-result-basis.v1'


# The three ways a reference output can be pinned, most-exact first: an output port/exchange, then
# a specific producing process, then the reference flow alone. A denominator is determinable only
# when the frozen demand binds EXACTLY ONE of these (the provider's require_one_selector) — a shared
# flow with several producers is disambiguated by the port/process, never by the flow uuid alone.
_REFERENCE_SELECTORS = ('reference_exchange_id', 'process_uuid', 'reference_flow_uuid')


def _reference_output_identity(functional_unit: dict, source_snapshot: dict,
                              producing_outputs: list | None = None) -> dict:
    """Bind the exact reference-output denominator identity, or refuse when it is not determinable.

    This is the read-side guard for the plan's rule that an ambiguous target must keep the total and
    disable the unit-product basis with a reason: the projection never guesses a denominator of one
    and never trusts a bare flow id when the frozen demand did not pin a unique output.

    Filling exactly one selector field is NOT the same as hitting exactly one output. When the
    frozen snapshot's scaled exchanges are supplied, the selected reference is resolved against the
    actual producing outputs, and only a single, unique producing exchange is accepted: a reference
    flow emitted by two processes (or by zero) is ambiguous and the unit-product conversion is
    refused. The unique hit's producing process and exchange identities are frozen into the result.
    """
    bound = {key: functional_unit.get(key) for key in _REFERENCE_SELECTORS}
    present = [key for key in _REFERENCE_SELECTORS if bound.get(key) not in (None, '')]
    if len(present) != 1:
        raise DomainError(code='UNIT_BASIS_REFERENCE_OUTPUT_AMBIGUOUS',
                          message='参考产出未绑定唯一输出，无法确定单位产品分母，请查看本次总量。',
                          status_code=422,
                          details={'bound': present})
    selector = present[0]
    value = bound[selector]
    identity = value
    producing: dict = {}
    if producing_outputs is not None:
        rows = [row for row in producing_outputs if isinstance(row, dict)]
        if selector == 'reference_flow_uuid':
            hits = [row for row in rows
                    if row.get('direction') == 'output' and str(row.get('flow_uuid') or '') == str(value)]
        elif selector == 'process_uuid':
            hits = [row for row in rows
                    if row.get('direction') == 'output' and str(row.get('process_id') or '') == str(value)]
        else:  # reference_exchange_id already names one exchange; confirm it is an output
            hits = [row for row in rows if str(row.get('exchange_id') or '') == str(value)]
        process_ids = sorted({str(row.get('process_id') or '') for row in hits})
        exchange_ids = sorted({str(row.get('exchange_id') or '') for row in hits})
        if len(hits) != 1 or len(process_ids) != 1 or len(exchange_ids) != 1:
            raise DomainError(code='UNIT_BASIS_REFERENCE_OUTPUT_AMBIGUOUS',
                              message='参考产出在冻结模型中命中多个或零个产出，无法确定单位产品分母，请查看本次总量。',
                              status_code=422,
                              details={'selector': selector, 'value': value,
                                       'match_count': len(hits), 'producing_process_uuids': process_ids})
        hit = hits[0]
        producing = {'producing_process_uuid': hit.get('process_id'),
                     'producing_exchange_id': hit.get('exchange_id')}
        identity = hit.get('exchange_id') or value
    amount = functional_unit.get('amount')
    unit = functional_unit.get('unit')
    return {
        'amount': amount, 'unit': unit,
        'source': 'frozen_functional_unit',
        'selector': selector,
        'value': value,
        'binding': bound,
        'model_version': {
            'system_revision_id': source_snapshot.get('system_revision_id'),
            'model_graph_sha256': source_snapshot.get('model_graph_sha256'),
        },
        **producing,
        'identity': identity,
    }


def _fmt_amount(value) -> str:
    """Render a base amount without a spurious decimal tail: 1.0 -> '1', 0.5 -> '0.5'."""
    try:
        number = Decimal(str(value))
    except Exception:  # noqa: BLE001
        return str(value)
    if number == number.to_integral_value():
        return str(number.to_integral_value())
    return str(number.normalize())


def _rescale(value, factor: Decimal):
    """Multiply one impact quantity by the frozen basis ratio, preserving unknown as a gap.

    A None/missing contribution stays None and never becomes zero; a negative value is a
    legal credit and keeps its sign. The result is a finite float on the intensity basis.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise DomainError(code='RESULT_BASIS_VALUE_INVALID',
                          message='结果值必须是有限数值。', status_code=422)
    try:
        number = Decimal(str(value))
    except Exception as exc:  # noqa: BLE001
        raise DomainError(code='RESULT_BASIS_VALUE_INVALID',
                          message='结果值必须是有限数值。', status_code=422) from exc
    return float(number * factor)


def project_result_basis(result: dict, *, basis: str, base_amount=None, base_unit=None,
                         producing_outputs: list | None = None) -> dict:
    """Return the PCF result re-expressed on the requested basis, or the same object for total.

    `total` is the identity: it returns ``result`` untouched so historical results, hashes and
    ETags stay byte-identical. `per_reference_output` divides exactly once (``T * b / Q``) and
    applies the same ratio to every line item.

    `producing_outputs` is the frozen snapshot's scaled exchange rows; when supplied the reference
    denominator is resolved against them so a shared reference flow that several processes emit is
    refused rather than silently converted (the plan's "one selector filled != unique output hit").
    """
    if basis in (None, '', 'total'):
        return result
    if basis != 'per_reference_output':
        raise DomainError(code='RESULT_BASIS_UNSUPPORTED',
                          message=f'不支持的结果口径：{basis}', status_code=422)

    functional_unit = result.get('functional_unit') or {}
    source_snapshot = result.get('source_snapshot') or {}
    # The denominator must be an unambiguous frozen reference output before any arithmetic.
    reference_identity = _reference_output_identity(functional_unit, source_snapshot, producing_outputs)
    reference_amount = reference_identity['amount']
    reference_unit = reference_identity['unit']

    # The primitive is the single converter: it validates the total (finite, negative legal),
    # the denominator and the base (positive, supported mass unit), converts kg/t once, and
    # freezes only the denominator/base definition (basis_sha256) so the toggle is not a solve.
    projected_total = per_reference_output(
        total_kg=(result.get('total_footprint') or {}).get('value'),
        reference_amount=reference_amount, reference_unit=reference_unit,
        base_amount=base_amount, base_unit=base_unit)
    factor = projected_total['base_kg'] / projected_total['reference_kg']
    base_label = _fmt_amount(base_amount)
    intensity_suffix = f"/{base_label} {base_unit}"

    projected = deepcopy(result)
    total = projected['total_footprint']
    total_value = projected_total['value']
    total['value'] = None if total_value is None else float(total_value)
    total['unit'] = f"{total.get('unit', '')}{intensity_suffix}"

    for component in projected.get('component_results') or []:
        component['value'] = _rescale(component.get('value'), factor)
        component['unit'] = f"{component.get('unit', '')}{intensity_suffix}"

    for hotspot in (projected.get('contribution_analysis') or {}).get('hotspots') or []:
        hotspot['contribution_value'] = _rescale(hotspot.get('contribution_value'), factor)
        if hotspot.get('contribution_unit') is not None:
            hotspot['contribution_unit'] = f"{hotspot['contribution_unit']}{intensity_suffix}"
        # share_of_total is a ratio and is scale-invariant; it is left untouched on purpose.

    method = projected.get('method_package') or {}
    projected['result_basis'] = {
        'schema_version': BASIS_SCHEMA,
        'basis': 'per_reference_output',
        'base_amount': base_label, 'base_unit': base_unit,
        'reference_output': reference_identity,
        'conversion_ratio_base_over_reference': str(factor),
        'basis_sha256': projected_total['basis_sha256'],
        'source': {
            'snapshot_id': (projected.get('source_snapshot') or {}).get('id'),
            'solve_hash': (projected.get('source_snapshot') or {}).get('content_sha256'),
            'lcia_method': method.get('lcia_method'),
            'indicator_key': (result.get('total_footprint') or {}).get('indicator_key'),
            'raw_total': {'value': (result.get('total_footprint') or {}).get('value'),
                          'unit': (result.get('total_footprint') or {}).get('unit')},
        },
    }
    # Re-hash the projected product (excluding the stale content_sha256) so page/API/XLSX/HTML
    # share one identical dict and ETag, while the solve hash above stays the frozen snapshot's.
    unsigned = {key: value for key, value in projected.items() if key != 'content_sha256'}
    projected['content_sha256'] = canonical_json_sha256(unsigned)
    return projected

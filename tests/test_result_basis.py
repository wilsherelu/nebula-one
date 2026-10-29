from __future__ import annotations

import pytest
from pydantic import ValidationError

from nebula_one.analysis.result_basis import project_result_basis, BASIS_SCHEMA
from nebula_one.errors import DomainError
from nebula_one.hashing import canonical_json_sha256
from nebula_one.runtime_schemas import ProductCarbonFootprintCreate


# The real recorded steel solve: total climate = 1940.739734 kg CO2-Eq over a 1000 kg reference output.
RAW_TOTAL = 1940.739734
REFERENCE_KG = 1000


def _result():
    total = {"indicator_key": "climate_change", "value": RAW_TOTAL, "unit": "kg CO2-Eq"}
    components = [
        {"indicator_key": "climate_change", "value": RAW_TOTAL, "unit": "kg CO2-Eq"},
        {"indicator_key": "other", "value": 7.5, "unit": "something"},
        {"indicator_key": "gap", "value": None, "unit": "kg CO2-Eq"},
    ]
    hotspots = [
        {"rank": 1, "contribution_value": 1500.0, "contribution_unit": "kg CO2-Eq",
         "share_of_total": 0.7729},
        {"rank": 2, "contribution_value": 440.739734, "contribution_unit": "kg CO2-Eq",
         "share_of_total": 0.2271},
    ]
    source = {"id": "snap-1", "content_sha256": "b" * 64, "model_graph_sha256": "c" * 64,
              "system_revision_id": "rev-1"}
    result = {
        "schema_version": "nebula_one.pcf.product.v1",
        "functional_unit": {"amount": REFERENCE_KG, "unit": "kg",
                            "reference_flow_uuid": "flow-product"},
        "total_footprint": total,
        "component_results": components,
        "contribution_analysis": {"hotspots": hotspots, "status": "available"},
        "source_snapshot": source,
        "method_package": {"lcia_method": "EF v3.1", "reference": "pkg",
                           "content_sha256": "d" * 64},
    }
    result["content_sha256"] = canonical_json_sha256(
        {key: value for key, value in result.items() if key != "content_sha256"})
    return result


def test_total_basis_is_the_byte_identity_and_keeps_every_hash():
    result = _result()
    projected = project_result_basis(result, basis="total")
    assert projected is result  # same object, not a copy
    assert "result_basis" not in projected  # no basis envelope is invented for the raw total
    assert projected["total_footprint"]["value"] == RAW_TOTAL
    # a caller passing no basis behaves the same as 'total'
    assert project_result_basis(result, basis=None) is result


def test_per_kilogram_intensity_divides_exactly_once():
    projected = project_result_basis(_result(), basis="per_reference_output",
                                     base_amount=1, base_unit="kg")
    total = projected["total_footprint"]
    assert abs(total["value"] - RAW_TOTAL / REFERENCE_KG) < 1e-9
    assert total["unit"] == "kg CO2-Eq/1 kg"


def test_per_tonne_intensity_uses_the_same_untouched_total():
    projected = project_result_basis(_result(), basis="per_reference_output",
                                     base_amount=1, base_unit="t")
    # base 1 t == 1000 kg == the reference output, so the per-tonne value equals the raw total
    assert abs(projected["total_footprint"]["value"] - RAW_TOTAL) < 1e-9
    assert projected["total_footprint"]["unit"] == "kg CO2-Eq/1 t"


def test_every_line_uses_the_same_basis_and_share_is_scale_invariant():
    projected = project_result_basis(_result(), basis="per_reference_output",
                                     base_amount=1, base_unit="kg")
    factor = 1 / REFERENCE_KG
    components = {item["indicator_key"]: item for item in projected["component_results"]}
    assert abs(components["climate_change"]["value"] - RAW_TOTAL * factor) < 1e-12
    assert abs(components["other"]["value"] - 7.5 * factor) < 1e-12
    assert components["gap"]["value"] is None  # an unknown stays a gap, never zero
    hotspots = projected["contribution_analysis"]["hotspots"]
    assert abs(hotspots[0]["contribution_value"] - 1500.0 * factor) < 1e-12
    assert hotspots[0]["share_of_total"] == 0.7729  # a ratio is left untouched
    assert hotspots[0]["contribution_unit"].endswith("/1 kg")


def test_projection_is_a_read_side_view_and_never_changes_the_solve_hash():
    original = _result()
    projected = project_result_basis(original, basis="per_reference_output",
                                     base_amount=1, base_unit="kg")
    assert projected["result_basis"]["source"]["solve_hash"] == original["source_snapshot"]["content_sha256"]
    assert projected["source_snapshot"]["content_sha256"] == original["source_snapshot"]["content_sha256"]
    # the projected product itself is re-hashed so page/API/XLSX/HTML share one identical dict
    unsigned = {key: value for key, value in projected.items() if key != "content_sha256"}
    assert projected["content_sha256"] == canonical_json_sha256(unsigned)
    assert projected["content_sha256"] != original["content_sha256"]


def test_basis_provenance_freezes_only_the_conversion():
    projected = project_result_basis(_result(), basis="per_reference_output",
                                     base_amount=1, base_unit="kg")
    basis = projected["result_basis"]
    assert basis["schema_version"] == BASIS_SCHEMA
    assert basis["basis"] == "per_reference_output"
    assert basis["reference_output"]["source"] == "frozen_functional_unit"
    assert basis["reference_output"]["identity"] == "flow-product"
    assert basis["source"]["raw_total"] == {"value": RAW_TOTAL, "unit": "kg CO2-Eq"}
    # switching only the display base changes the basis, not the underlying solve
    another = project_result_basis(_result(), basis="per_reference_output",
                                   base_amount=1, base_unit="t")
    assert basis["basis_sha256"] != another["result_basis"]["basis_sha256"]
    assert basis["source"]["solve_hash"] == another["result_basis"]["source"]["solve_hash"]


def test_bound_reference_output_records_the_selector_and_model_version():
    projected = project_result_basis(_result(), basis="per_reference_output",
                                     base_amount=1, base_unit="kg")
    reference = projected["result_basis"]["reference_output"]
    # the frozen demand pins the reference flow alone, and that selector is recorded verbatim
    assert reference["selector"] == "reference_flow_uuid"
    assert reference["value"] == "flow-product"
    assert reference["binding"] == {"reference_exchange_id": None, "process_uuid": None,
                                    "reference_flow_uuid": "flow-product"}
    # the denominator identity is bound to the exact frozen model, not a bare flow id
    assert reference["model_version"] == {"system_revision_id": "rev-1",
                                          "model_graph_sha256": "c" * 64}


@pytest.mark.parametrize("functional_unit", [
    # no selector bound at all -- nothing tells us which output is the denominator
    {"amount": REFERENCE_KG, "unit": "kg"},
    # a shared flow with several producers and no port/process to disambiguate it
    {"amount": REFERENCE_KG, "unit": "kg", "reference_flow_uuid": "flow", "process_uuid": "proc"},
], ids=["no-selector", "two-selectors"])
def test_an_ambiguous_reference_output_keeps_total_by_refusing_the_intensity_basis(functional_unit):
    result = _result()
    result["functional_unit"] = functional_unit
    # the projection never guesses a denominator of one; it refuses so the caller keeps the total
    with pytest.raises(DomainError) as error:
        project_result_basis(result, basis="per_reference_output", base_amount=1, base_unit="kg")
    assert error.value.code == "UNIT_BASIS_REFERENCE_OUTPUT_AMBIGUOUS"


def test_an_exact_output_port_or_process_is_a_determinable_denominator():
    result = _result()
    result["functional_unit"] = {"amount": REFERENCE_KG, "unit": "kg",
                                 "process_uuid": "producing-process"}
    projected = project_result_basis(result, basis="per_reference_output",
                                     base_amount=1, base_unit="kg")
    assert projected["result_basis"]["reference_output"]["selector"] == "process_uuid"


def _output(process_id: str, flow_uuid: str, exchange_id: str, direction: str = "output") -> dict:
    return {"process_id": process_id, "exchange_id": exchange_id, "flow_uuid": flow_uuid,
            "direction": direction, "amount": REFERENCE_KG, "unit": "kg",
            "unit_group": "mass", "exchange_type": "technosphere"}


def test_reference_flow_emitted_by_two_processes_refuses_the_intensity_basis():
    # Filling one selector field is NOT the same as hitting one output: the same reference flow
    # emitted by two distinct processes leaves the denominator undetermined, so the unit-product
    # conversion is refused and the total is kept rather than a guessed hit.
    rows = [_output("proc-a", "flow-product", "proc-a::product"),
            _output("proc-b", "flow-product", "proc-b::product")]
    with pytest.raises(DomainError) as error:
        project_result_basis(_result(), basis="per_reference_output", base_amount=1, base_unit="kg",
                             producing_outputs=rows)
    assert error.value.code == "UNIT_BASIS_REFERENCE_OUTPUT_AMBIGUOUS"
    assert error.value.details["match_count"] == 2
    assert error.value.details["producing_process_uuids"] == ["proc-a", "proc-b"]


def test_reference_flow_with_no_producing_output_in_the_frozen_model_refuses():
    # A bare flow id that the frozen snapshot never emits as an output (only consumes) cannot be a
    # denominator; the guard refuses instead of trusting the selector.
    rows = [_output("proc-a", "flow-product", "proc-a::consumed", direction="input")]
    with pytest.raises(DomainError) as error:
        project_result_basis(_result(), basis="per_reference_output", base_amount=1, base_unit="kg",
                             producing_outputs=rows)
    assert error.value.code == "UNIT_BASIS_REFERENCE_OUTPUT_AMBIGUOUS"
    assert error.value.details["match_count"] == 0


def test_reference_flow_emitted_twice_from_one_process_is_also_ambiguous():
    # Even a single process leaving the reference flow through two output ports does not pin which
    # one the demand means, so the denominator is still ambiguous.
    rows = [_output("proc-a", "flow-product", "proc-a::out-1"),
            _output("proc-a", "flow-product", "proc-a::out-2")]
    with pytest.raises(DomainError) as error:
        project_result_basis(_result(), basis="per_reference_output", base_amount=1, base_unit="kg",
                             producing_outputs=rows)
    assert error.value.code == "UNIT_BASIS_REFERENCE_OUTPUT_AMBIGUOUS"


def test_unique_producing_output_resolves_and_freezes_the_actual_hit():
    # Exactly one producing output for the reference flow: the projection resolves it against the
    # frozen model and freezes the ACTUAL hit (the producing process and exchange), not the bare
    # selector value, so the denominator identity is verifiable.
    rows = [_output("proc-a", "flow-product", "proc-a::product"),
            _output("proc-b", "flow-intermediate", "proc-b::other", direction="input")]
    projected = project_result_basis(_result(), basis="per_reference_output",
                                     base_amount=1, base_unit="kg", producing_outputs=rows)
    reference = projected["result_basis"]["reference_output"]
    assert reference["selector"] == "reference_flow_uuid"
    assert reference["value"] == "flow-product"  # the bound selector is still recorded verbatim
    assert reference["producing_process_uuid"] == "proc-a"
    assert reference["producing_exchange_id"] == "proc-a::product"
    assert reference["identity"] == "proc-a::product"  # the actual unique hit, not the bare flow id


def test_negative_total_contribution_stays_negative_on_the_intensity_basis():
    result = _result()
    result["contribution_analysis"]["hotspots"][1]["contribution_value"] = -440.739734
    projected = project_result_basis(result, basis="per_reference_output",
                                     base_amount=1, base_unit="kg")
    assert projected["contribution_analysis"]["hotspots"][1]["contribution_value"] < 0


@pytest.mark.parametrize("basis", ["unknown", "intensity", "per_unit"])
def test_unsupported_basis_is_refused(basis):
    with pytest.raises(DomainError) as error:
        project_result_basis(_result(), basis=basis, base_amount=1, base_unit="kg")
    assert error.value.code == "RESULT_BASIS_UNSUPPORTED"


def test_incompatible_base_unit_is_refused_by_the_converter():
    with pytest.raises(DomainError) as error:
        project_result_basis(_result(), basis="per_reference_output", base_amount=1, base_unit="kWh")
    assert error.value.code == "UNIT_PRODUCT_INCOMPATIBLE_DENOMINATOR"


def test_schema_defaults_to_total_and_requires_an_exact_base_for_intensity():
    plain = ProductCarbonFootprintCreate(method_package_ref="pkg-ref")
    assert plain.result_basis == "total" and plain.base_amount is None and plain.base_unit is None
    with pytest.raises(ValidationError):
        ProductCarbonFootprintCreate(method_package_ref="pkg-ref", result_basis="per_reference_output")
    with pytest.raises(ValidationError):
        ProductCarbonFootprintCreate(method_package_ref="pkg-ref", result_basis="per_reference_output",
                                     base_amount=1)  # missing base_unit
    valid = ProductCarbonFootprintCreate(method_package_ref="pkg-ref", result_basis="per_reference_output",
                                         base_amount=1, base_unit="t")
    assert valid.base_unit == "t"


@pytest.mark.parametrize("base_amount", [0, -1])
def test_schema_rejects_non_positive_base_amount(base_amount):
    with pytest.raises(ValidationError):
        ProductCarbonFootprintCreate(method_package_ref="pkg-ref", result_basis="per_reference_output",
                                     base_amount=base_amount, base_unit="kg")


def test_schema_rejects_unsupported_base_unit():
    with pytest.raises(ValidationError):
        ProductCarbonFootprintCreate(method_package_ref="pkg-ref", result_basis="per_reference_output",
                                     base_amount=1, base_unit="kWh")

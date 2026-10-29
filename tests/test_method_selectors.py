from copy import deepcopy

import pytest

from nebula_one.analysis.method_selectors import compile_accounting_selectors, SCHEMA_VERSION
from nebula_one.errors import DomainError
from nebula_one.runtime_schemas import CalculationMethodRule


PORTS = [dict(exchange_id="a::co2", process_id="a", flow_uuid="co2", direction="emission", internal=False),
         dict(exchange_id="a::ch4", process_id="a", flow_uuid="ch4", direction="emission", internal=False),
         dict(exchange_id="a::power", process_id="a", flow_uuid="power", direction="input", internal=False),
         dict(exchange_id="b::power", process_id="b", flow_uuid="power", direction="input", internal=True)]


def definition(*selectors):
    return dict(schema_version=SCHEMA_VERSION, selectors=list(selectors))


def selector(id="emissions", **match):
    return dict(id=id, match=match or dict(process_ids=["a"], directions=["emission"]),
                classification=dict(boundary_status="selected", location_role="onsite", scope="scope_1"))


def test_process_and_flow_selection_uses_exact_identity_and_existing_rule_contract():
    spec = definition(selector(process_ids=["a"], directions=["emission"], flow_uuids=["ch4"]))
    before = deepcopy(spec)
    result = compile_accounting_selectors(spec, PORTS, "official@1")
    assert [r["exchange_id"] for r in result["rules"]] == ["a::ch4"]
    assert CalculationMethodRule.model_validate(result["rules"][0]).scope == "scope_1"
    assert result["rule_sources"] == [dict(exchange_id="a::ch4", selector_ids=["emissions"])]
    assert len(result["definition_sha256"]) == 64 and spec == before
    renamed = [dict(port, name="电力 CO2 蒸汽 arbitrary") for port in reversed(PORTS)]
    assert compile_accounting_selectors(spec, renamed, "official@1") == result


def test_upstream_filter_does_not_classify_internal_transfer_as_purchased_power():
    item = selector(all_model_processes=True, directions=["input"], contribution_target="upstream")
    item["classification"].update(scope="scope_2", location_role="purchased_energy")
    rules = compile_accounting_selectors(definition(item), PORTS, "official@1")["rules"]
    assert [r["exchange_id"] for r in rules] == ["a::power"]
    assert rules[0]["contribution_target"] == "upstream"


@pytest.mark.parametrize("match,code", [
    (dict(exchange_ids=["missing::co2"], directions=["emission"]), "ACCOUNTING_SELECTOR_IDENTITY_ABSENT"),
    (dict(process_ids=["missing"], directions=["emission"]), "ACCOUNTING_SELECTOR_IDENTITY_ABSENT"),
    (dict(process_ids=["a"], directions=["emission"], flow_uuids=["co2", "missing"]), "ACCOUNTING_SELECTOR_TARGET_MISMATCH"),
    (dict(exchange_ids=["a::co2", "a::power"], directions=["emission"]), "ACCOUNTING_SELECTOR_TARGET_MISMATCH"),
    (dict(process_ids=["a"], directions=["resource"]), "ACCOUNTING_SELECTOR_MATCH_EMPTY"),
    (dict(process_ids=["a"], all_model_processes=True, directions=["emission"]), "ACCOUNTING_RULE_DEFINITION_INVALID"),
    (dict(process_name="a", directions=["emission"]), "ACCOUNTING_RULE_DEFINITION_INVALID"),
])
def test_invalid_or_stale_selector_never_partially_falls_back(match, code):
    with pytest.raises(DomainError) as error:
        compile_accounting_selectors(definition(selector(**match)), PORTS, "official@1")
    assert error.value.code == code


def test_unknown_version_and_conflicting_overlap_are_rejected():
    spec = definition(selector())
    spec["schema_version"] = "unknown.v2"
    with pytest.raises(DomainError) as error:
        compile_accounting_selectors(spec, PORTS, "official@1")
    assert error.value.code == "ACCOUNTING_RULE_DEFINITION_INVALID"
    first = selector()
    other = selector("override", exchange_ids=["a::co2"], directions=["emission"])
    other["classification"]["boundary_status"] = "excluded"
    with pytest.raises(DomainError) as error:
        compile_accounting_selectors(definition(first, other), PORTS, "official@1")
    assert error.value.code == "ACCOUNTING_SELECTOR_CONFLICT"
    assert error.value.details["exchange_id"] == "a::co2"


def test_same_decision_is_counted_once_and_changed_boundary_changes_definition_hash():
    first = selector()
    same = selector("same", exchange_ids=["a::co2"], directions=["emission"])
    result = compile_accounting_selectors(definition(first, same), PORTS, "official@1")
    assert len(result["rules"]) == 2
    assert result["rule_sources"][1 if result["rule_sources"][0]["exchange_id"] == "a::ch4" else 0]["selector_ids"] == ["emissions", "same"]
    first["classification"]["boundary_status"] = "excluded"
    excluded = compile_accounting_selectors(definition(first), PORTS, "official@1")
    assert result["definition_sha256"] != excluded["definition_sha256"]
    assert all(r["boundary_status"] == "excluded" for r in excluded["rules"])

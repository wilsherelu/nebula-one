from copy import deepcopy

import pytest

from nebula_one.analysis.cbam_variant_ledger import compile_variant_ledger
from nebula_one.errors import DomainError


def fixture():
    rules = [{"exchange_id": "node::a", "process_uuid": "process", "flow_uuid": "co2"},
             {"exchange_id": "node::b", "process_uuid": "process", "flow_uuid": "co2"}]
    ledger = {r["exchange_id"]: {"disposition": "counted", "clause": "base"} for r in rules}
    source = {"method_id": "user", "version": 2, "content_sha256": "b" * 64}
    selection = {"included_exchange_ids": ["node::a"], "excluded_exchange_ids": ["node::b"],
                 "decisions": [{"exchange_id": "node::a", "state": "included", "clause": "base"},
                               {"exchange_id": "node::b", "state": "excluded",
                                "clause": "user-variant-exclusion@user@2#" + "b" * 64}]}
    return dict(rules=rules, ledger=ledger, selection=selection, user_method=source,
                base_ref="base@1.0.0", base_hash="a" * 64)


def test_narrowed_ledger_is_content_addressed_preserves_base_and_replays():
    args = fixture()
    before = deepcopy(args)
    rules, ledger, artifact = compile_variant_ledger(**args)
    assert [r["exchange_id"] for r in rules] == ["node::a"]
    assert ledger["node::b"]["disposition"] == "excluded_with_basis"
    assert artifact["base_method_package_sha256"] == "a" * 64
    assert artifact["claim"] == "user_declared_variant_not_regulatory_baseline"
    assert compile_variant_ledger(**args)[2] == artifact
    assert args == before
    args["user_method"]["content_sha256"] = "c" * 64
    with pytest.raises(DomainError):
        compile_variant_ledger(**args)


def test_variant_refuses_boundary_mismatch_and_widening():
    args = fixture()
    args["ledger"]["node::a"]["disposition"] = "excluded_with_basis"
    with pytest.raises(DomainError):
        compile_variant_ledger(**args)
    args = fixture()
    args["selection"]["included_exchange_ids"].append("node::unknown")
    with pytest.raises(DomainError):
        compile_variant_ledger(**args)


def test_excluded_source_keeps_its_alternate_input_excluded_without_false_counted_backlink():
    args = fixture()
    args["ledger"]["node::fuel"] = {"disposition": "excluded_with_basis", "clause": "base",
        "basis": "counted_in_direct_emission", "source_group": "carbon", "counted_instead": "node::b"}
    _, ledger, artifact = compile_variant_ledger(**args)
    assert ledger["node::fuel"]["disposition"] == "excluded_with_basis"
    assert "counted_instead" not in ledger["node::fuel"]
    assert "source_group" not in ledger["node::fuel"]
    assert artifact["linked_source_exclusions"][0]["base_disposition"]["counted_instead"] == "node::b"

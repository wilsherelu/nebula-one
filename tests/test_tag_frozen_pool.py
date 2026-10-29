from types import SimpleNamespace

import pytest

from nebula_one.errors import DomainError
from nebula_one.hashing import canonical_json_sha256
from nebula_one.services.tag_grouping import frozen_tag_pool


def _receipt(terms, **extra):
    body = {"canonical_indicator_key": "climate", "indicator_unit": "kg CO2e", "terms": terms, **extra}
    return {**body, "content_hash": canonical_json_sha256(body)}


def test_background_gap_attaches_to_exact_consumer_and_keeps_known_subtotal():
    path = _receipt([
        {"exchange_id": "bg-a::co2", "process_uuid": "provider-instance-a", "consumer_exchange_id": "fg::power-a",
         "attribution_basis": "background_consumer_path", "path_contribution_value": 12.0},
        {"exchange_id": "bg-b::co2", "process_uuid": "provider-instance-b", "consumer_exchange_id": "fg::power-b",
         "attribution_basis": "background_consumer_path", "path_contribution_value": 8.0},
    ])
    flat = _receipt([
        {"exchange_id": "bg-a::co2", "contribution_value": 12.0},
        {"exchange_id": "bg-b::co2", "contribution_value": 8.0},
    ], characterization_coverage={"uncharacterized_exchanges": [
        {"exchange_id": "bg-a::gap", "process_uuid": "provider-instance-a"},
    ]})
    snapshot = SimpleNamespace(lcia_results={
        "path_weighted_contribution_receipts": [path], "indicator_contribution_receipts": [flat],
        "contribution_receipts_hash": canonical_json_sha256([flat]),
    }, scaled_elementary_exchanges=[{"exchange_id": key} for key in ("bg-a::co2", "bg-a::gap", "bg-b::co2")])
    terms, consumers, missing, unit = frozen_tag_pool(snapshot, "climate")
    assert terms == [
        {"exchange_id": "fg::power-a", "contribution_value": 12.0},
        {"exchange_id": "fg::power-b", "contribution_value": 8.0},
    ]
    assert missing == {"fg::power-a"}
    assert {row["exchange_id"] for row in consumers} == {"fg::power-a", "fg::power-b"}
    assert unit == "kg CO2e"


def test_flat_foreground_receipt_is_usable_and_tampering_is_rejected():
    flat = _receipt([{"exchange_id": "fg::co2", "contribution_value": 12.0}])
    snapshot = SimpleNamespace(lcia_results={
        "indicator_contribution_receipts": [flat],
        "contribution_receipts_hash": canonical_json_sha256([flat]),
    }, scaled_elementary_exchanges=[{"exchange_id": "fg::co2"}, {"exchange_id": "fg::gap"}])
    terms, consumers, missing, _ = frozen_tag_pool(snapshot, "climate")
    assert terms == [{"exchange_id": "fg::co2", "contribution_value": 12.0}]
    assert consumers == [] and missing == {"fg::gap"}
    flat["terms"][0]["contribution_value"] = 120.0
    with pytest.raises(DomainError) as caught:
        frozen_tag_pool(snapshot, "climate")
    assert caught.value.code == "TAG_RECEIPT_HASH_MISMATCH"


def test_duplicate_indicator_receipt_is_ambiguous_even_when_hashes_are_valid():
    receipt = _receipt([])
    snapshot = SimpleNamespace(lcia_results={"path_weighted_contribution_receipts": [receipt, receipt]},
                               scaled_elementary_exchanges=[])
    with pytest.raises(DomainError) as caught:
        frozen_tag_pool(snapshot, "climate")
    assert caught.value.code == "TAG_RECEIPT_AMBIGUOUS"


def test_partial_path_rows_preserve_the_known_part_of_one_consumer():
    receipt = _receipt([
        {"exchange_id": "bg::co2", "consumer_exchange_id": "fg::power", "attribution_basis": "background_consumer_path", "path_contribution_value": 10.0},
        {"exchange_id": "bg::gap", "consumer_exchange_id": "fg::power", "attribution_basis": "background_consumer_path", "path_contribution_value": None},
    ])
    snapshot = SimpleNamespace(lcia_results={"path_weighted_contribution_receipts": [receipt]},
                               scaled_elementary_exchanges=[{"exchange_id": "bg::co2"}, {"exchange_id": "bg::gap"}])
    terms, _, missing, _ = frozen_tag_pool(snapshot, "climate")
    assert terms == [{"exchange_id": "fg::power", "contribution_value": 10.0}]
    assert missing == {"fg::power"}

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from nebula_one.errors import DomainError
from nebula_one.hashing import canonical_json_sha256
from nebula_one.runtime_schemas import (
    ProviderBackgroundProcessPin,
    ProviderSolveAndFreezeCreate,
)
from nebula_one.services.provider_solve import (
    _validated_background_process_receipts,
)


PROCESS_UUID = "21084c23-87a9-4e84-af4e-d8b45550a1a2"
ELECTRICITY_UUID = "3d76981f-964a-4865-b588-0e067a2a1163"
CO2_UUID = "08a91e70-3ddc-11dd-923d-0050c2490048"
ENERGY_PROPERTY_UUID = "93a60a56-a3c8-11da-a746-0800200c9a66"
ENERGY_UNIT_GROUP_UUID = "93a60a57-a3c8-11da-a746-0800200c9a66"
MASS_PROPERTY_UUID = "93a60a56-a3c8-11da-a746-0800200b9a66"
MASS_UNIT_GROUP_UUID = "93a60a57-a4c8-11da-a746-0800200c9a66"
QREF_EXPANDED_ID = "provider-background-test::exchange-2"
CO2_EXPANDED_ID = "provider-background-test::exchange-1"


def _pin_payload() -> dict:
    return {
        "schema_version": "provider.background-process-pin.v1",
        "consumer_exchange_id": "consumer::electricity-in",
        "source_namespace": "tiangong_open_data",
        "process_uuid": PROCESS_UUID,
        "version": "01.01.013",
        "expected_process_content_hash": "1" * 64,
        "expected_process_snapshot_hash": "2" * 64,
        "quantitative_reference_exchange_internal_id": "2",
        "claim_role": "partial_background_leaf",
    }


def _graph() -> dict:
    return {
        "nodes": [
            {
                "id": "consumer",
                "process_uuid": "consumer-process",
                "inputs": [
                    {
                        "id": "electricity-in",
                        "flowSourceNamespace": "tiangong_open_data",
                        "flowUuid": ELECTRICITY_UUID,
                        "flowVersion": "01.01.003",
                        "flowPropertyUuid": ENERGY_PROPERTY_UUID,
                        "flowPropertyVersion": "03.00.003",
                        "unitGroupUuid": ENERGY_UNIT_GROUP_UUID,
                        "unitGroupVersion": "03.00.003",
                        "unit": "MJ",
                        "type": "technosphere",
                    }
                ],
                "outputs": [],
            }
        ],
        "exchanges": [],
    }


def _exchange_receipt(
    *,
    internal_id: str,
    expanded_id: str,
    role: str,
    flow_uuid: str,
    version: str,
    property_uuid: str,
    unit_group_uuid: str,
    unit: str,
    raw_amount: float,
    scaled_amount: float,
) -> dict:
    return {
        "exchange_internal_id": internal_id,
        "expanded_exchange_id": expanded_id,
        "role": role,
        "source_namespace": "tiangong_open_data",
        "flow_uuid": flow_uuid,
        "version": version,
        "flow_content_hash": "3" * 64,
        "flow_snapshot_hash": "4" * 64 if role == "quantitative_reference" else None,
        "flow_property_uuid": property_uuid,
        "flow_property_version": "03.00.003",
        "unit_group_uuid": unit_group_uuid,
        "unit_group_version": "03.00.003",
        "unit": unit,
        "direction": "output",
        "raw_amount": raw_amount,
        "scaled_amount": scaled_amount,
    }


def _result(pin: ProviderBackgroundProcessPin) -> dict:
    qref = _exchange_receipt(
        internal_id="2",
        expanded_id=QREF_EXPANDED_ID,
        role="quantitative_reference",
        flow_uuid=ELECTRICITY_UUID,
        version="01.01.003",
        property_uuid=ENERGY_PROPERTY_UUID,
        unit_group_uuid=ENERGY_UNIT_GROUP_UUID,
        unit="MJ",
        raw_amount=3.6,
        scaled_amount=3.6,
    )
    elementary = _exchange_receipt(
        internal_id="1",
        expanded_id=CO2_EXPANDED_ID,
        role="elementary",
        flow_uuid=CO2_UUID,
        version="03.00.004",
        property_uuid=MASS_PROPERTY_UUID,
        unit_group_uuid=MASS_UNIT_GROUP_UUID,
        unit="kg",
        raw_amount=0.568396722,
        scaled_amount=0.568396722,
    )
    receipt = {
        "schema_version": "provider.background-process-receipt.v1",
        "claim_role": "partial_background_leaf",
        "claim_limit": "partial_background_leaf_only_not_complete_cradle_to_gate",
        "consumer_exchange_id": pin.consumer_exchange_id,
        "source_namespace": pin.source_namespace,
        "process_uuid": pin.process_uuid,
        "version": pin.version,
        "process_type": "Partly terminated system",
        "process_content_hash": pin.expected_process_content_hash,
        "process_snapshot_hash": pin.expected_process_snapshot_hash,
        "quantitative_reference_exchange_internal_id": (
            pin.quantitative_reference_exchange_internal_id
        ),
        "quantitative_reference_flow_uuid": ELECTRICITY_UUID,
        "quantitative_reference_flow_version": "01.01.003",
        "quantitative_reference_amount": 3.6,
        "activity_amount": 3.6,
        "process_scale": 1.0,
        "exchanges": [elementary, qref],
    }
    scaled_exchanges = []
    for item in (elementary, qref):
        scaled_exchanges.append(
            {
                "exchange_id": item["expanded_exchange_id"],
                "process_uuid": pin.process_uuid,
                "flow_uuid": item["flow_uuid"],
                "flow_source_namespace": item["source_namespace"],
                "flow_version": item["version"],
                "flow_property_uuid": item["flow_property_uuid"],
                "flow_property_version": item["flow_property_version"],
                "unit_group_uuid": item["unit_group_uuid"],
                "unit_group_version": item["unit_group_version"],
                "unit": item["unit"],
                "direction": item["direction"],
                "exchange_type": (
                    "technosphere"
                    if item["role"] == "quantitative_reference"
                    else "elementary"
                ),
                "raw_amount": item["raw_amount"],
                "scaled_amount": item["scaled_amount"],
            }
        )
    scaled_exchanges.append(
        {
            "exchange_id": pin.consumer_exchange_id,
            "process_uuid": "consumer-process",
            "flow_uuid": ELECTRICITY_UUID,
            "flow_source_namespace": "tiangong_open_data",
            "flow_version": "01.01.003",
            "flow_property_uuid": ENERGY_PROPERTY_UUID,
            "flow_property_version": "03.00.003",
            "unit_group_uuid": ENERGY_UNIT_GROUP_UUID,
            "unit_group_version": "03.00.003",
            "unit": "MJ",
            "direction": "input",
            "exchange_type": "technosphere",
            "raw_amount": 3.6,
            "scaled_amount": 3.6,
        }
    )
    return {
        "background_process_receipts": [receipt],
        "scaled_exchanges": scaled_exchanges,
        "elementary_flow_receipts": [{"exchange_id": CO2_EXPANDED_ID}],
        "provenance": {
            "background_process_pins_hash": canonical_json_sha256(
                [pin.model_dump(mode="json")]
            ),
            "background_claim_scope": (
                "partial_background_leaf_only_not_complete_cradle_to_gate"
            ),
        },
    }


def test_exact_background_receipt_is_validated_and_returned() -> None:
    pin = ProviderBackgroundProcessPin.model_validate(_pin_payload())
    result = _result(pin)
    validated = _validated_background_process_receipts(
        result,
        [pin],
        _graph(),
        analysis_run_id="run-1",
    )
    assert validated == result["background_process_receipts"]


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("claim", "PROVIDER_BACKGROUND_RECEIPT_IDENTITY_MISMATCH"),
        ("scale", "PROVIDER_BACKGROUND_SCALE_MISMATCH"),
        ("scaled", "PROVIDER_BACKGROUND_SCALED_EXCHANGE_MISMATCH"),
        ("elementary_receipt", "PROVIDER_BACKGROUND_ELEMENTARY_RECEIPT_MISSING"),
        ("pins_hash", "PROVIDER_BACKGROUND_PROVENANCE_MISMATCH"),
        ("consumer_unit", "PROVIDER_BACKGROUND_CONSUMER_SCALED_EXCHANGE_MISMATCH"),
        ("qref_unit", "PROVIDER_BACKGROUND_QREF_IDENTITY_MISMATCH"),
    ],
)
def test_background_receipt_drift_fails_closed(
    mutation: str,
    expected_code: str,
) -> None:
    pin = ProviderBackgroundProcessPin.model_validate(_pin_payload())
    result = _result(pin)
    if mutation == "claim":
        result["background_process_receipts"][0]["claim_limit"] = "complete"
    elif mutation == "scale":
        result["background_process_receipts"][0]["process_scale"] = 2.0
    elif mutation == "scaled":
        result["background_process_receipts"][0]["exchanges"][0][
            "scaled_amount"
        ] = 9.0
    elif mutation == "elementary_receipt":
        result["elementary_flow_receipts"] = []
    elif mutation == "consumer_unit":
        result["scaled_exchanges"][-1]["unit"] = "kWh"
    elif mutation == "qref_unit":
        result["background_process_receipts"][0]["exchanges"][1]["unit"] = "kWh"
    else:
        result["provenance"]["background_process_pins_hash"] = "0" * 64
    with pytest.raises(DomainError) as captured:
        _validated_background_process_receipts(
            result,
            [pin],
            _graph(),
            analysis_run_id="run-1",
        )
    assert captured.value.code == expected_code


def test_unrequested_background_receipt_is_rejected() -> None:
    pin = ProviderBackgroundProcessPin.model_validate(_pin_payload())
    with pytest.raises(DomainError) as captured:
        _validated_background_process_receipts(
            _result(pin),
            [],
            _graph(),
            analysis_run_id="run-1",
        )
    assert captured.value.code == "PROVIDER_BACKGROUND_RECEIPT_UNREQUESTED"


def test_solve_request_rejects_duplicate_background_consumers() -> None:
    payload = {
        "demand": [{"process_uuid": "consumer-process", "amount": 1, "unit": "kg"}],
        "background_process_pins": [_pin_payload(), copy.deepcopy(_pin_payload())],
    }
    with pytest.raises(ValidationError, match="unique consumer exchanges"):
        ProviderSolveAndFreezeCreate.model_validate(payload)

"""Install the exact open TianGong Flow required by the public supply seed."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..errors import DomainError


RESOURCE_DIR = Path(__file__).resolve().parents[1] / "resources" / "public_supply"
PIN_PATH = RESOURCE_DIR / "tiangong-alternating-current-01.01.003.pin.json"
CO2_PIN_PATH = RESOURCE_DIR / "tiangong-carbon-dioxide-fossil-03.00.004.pin.json"
SUPPLY_PATH = RESOURCE_DIR / "tiangong-china-grid-2022.v1.json"


def open_flow_pins() -> list[dict[str, str]]:
    return [
        {key: pin[key] for key in ("flow_uuid", "source_namespace", "source_version", "asset_sha256")}
        for pin_path in (PIN_PATH, CO2_PIN_PATH)
        for pin in [json.loads(pin_path.read_text(encoding="utf-8"))]
    ]


def _identity_differences(observed: dict[str, Any], pin: dict[str, Any]) -> list[str]:
    fields = {
        "flow_uuid": "flow_uuid",
        "source_namespace": "source_namespace",
        "source_version": "source_version",
        "tidas_flow_property_uuid": "flow_property_uuid",
        "default_unit": "default_unit",
        "unit_group": "unit_group",
    }
    return [key for key, source in fields.items() if observed.get(key) != pin[source]]


def _ensure_pinned_open_flow(client: Any, pin_path: Path, port: dict[str, Any]) -> dict[str, str]:
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    if pin.get("schema_version") != "nebula_one.open-flow-import-pin.v1" or pin.get("source_namespace") != "tiangong_open_data":
        raise ValueError("public supply flow pin is not a TianGong open Flow")
    asset_path = RESOURCE_DIR / Path(pin["asset"]).name
    if asset_path.name != pin["asset"]:
        raise ValueError("public supply flow asset path is invalid")
    payload = asset_path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != pin["asset_sha256"]:
        raise ValueError("public supply flow import asset hash drifted")
    flow = json.loads(payload)
    ilcd = flow["flowDataSet"]
    source_hash = hashlib.sha256(json.dumps(
        {"flowDataSet": ilcd}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    if source_hash != pin["source_record_content_hash"]:
        raise ValueError("public supply Flow differs from the pinned TianGong source record")
    source_identity = ilcd["flowInformation"]["dataSetInformation"]["common:UUID"]
    property_ref = ilcd["flowProperties"]["flowProperty"]["referenceToFlowPropertyDataSet"]
    comparisons = (
        (source_identity, pin["flow_uuid"]),
        (flow["source"], pin["source_namespace"]),
        (flow["version"], pin["source_version"]),
        (flow["default_unit"], pin["default_unit"]),
        (flow["unit_group"], pin["unit_group"]),
        (flow["unit_group_uuid"], pin["unit_group_uuid"]),
        (flow["unit_group_version"], pin["unit_group_version"]),
        (property_ref["@refObjectId"], pin["flow_property_uuid"]),
        (property_ref["@version"], pin["flow_property_version"]),
        (port["flowUuid"], pin["flow_uuid"]),
        (port["flowSourceNamespace"], pin["source_namespace"]),
        (port["flowVersion"], pin["source_version"]),
        (port["flowPropertyUuid"], pin["flow_property_uuid"]),
        (port["unitGroupUuid"], pin["unit_group_uuid"]),
        (port["unitGroupVersion"], pin["unit_group_version"]),
    )
    if any(actual != expected for actual, expected in comparisons):
        raise ValueError("public supply seed and pinned TianGong Flow identities disagree")

    try:
        observed = client.get_reference_flow(pin["flow_uuid"])
    except DomainError as error:
        if error.details.get("upstream_status") != 404:
            raise
    else:
        differences = _identity_differences(observed, pin)
        if differences:
            raise ValueError("public supply Flow catalog identity drifted: " + ",".join(differences))
        return {"status": "present", "flow_uuid": pin["flow_uuid"], "source_version": pin["source_version"]}

    for dry_run in (True, False):
        receipt = client.import_tidas_flows(filename=asset_path.name, payload=payload, dry_run=dry_run).payload
        if receipt["inserted"] != 1 or receipt["failed"] != 0 or receipt["errors"] or receipt["warnings"]:
            raise ValueError("public supply TianGong Flow import did not verify cleanly")
    observed = client.get_reference_flow(pin["flow_uuid"])
    differences = _identity_differences(observed, pin)
    if differences:
        raise ValueError("imported public supply Flow identity drifted: " + ",".join(differences))
    return {"status": "imported", "flow_uuid": pin["flow_uuid"], "source_version": pin["source_version"]}


def ensure_open_supply_flow(client: Any) -> dict[str, Any]:
    supply = json.loads(SUPPLY_PATH.read_text(encoding="utf-8"))["graph"]["nodes"][0]
    ports = {port["flowUuid"]: port for port in supply["outputs"]}
    electricity = ports[json.loads(PIN_PATH.read_text(encoding="utf-8"))["flow_uuid"]]
    co2 = ports[json.loads(CO2_PIN_PATH.read_text(encoding="utf-8"))["flow_uuid"]]
    result = _ensure_pinned_open_flow(client, PIN_PATH, electricity)
    result["co2_flow"] = _ensure_versioned_open_flow(client, CO2_PIN_PATH, co2)
    return result


def _ensure_versioned_open_flow(client: Any, pin_path: Path, port: dict[str, Any]) -> dict[str, str]:
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    asset_path = RESOURCE_DIR / pin["asset"]
    payload = asset_path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != pin["asset_sha256"]:
        raise ValueError("open Flow import asset hash drifted")
    flow = json.loads(payload)
    source_hash = hashlib.sha256(json.dumps(
        {"flowDataSet": flow["flowDataSet"]}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    if source_hash != pin["source_record_content_hash"]:
        raise ValueError("open Flow differs from pinned TianGong source record")
    ilcd = flow["flowDataSet"]
    if (flow.get("source"), flow.get("version"),
        ilcd["flowInformation"]["dataSetInformation"].get("common:UUID"),
        ilcd["administrativeInformation"]["publicationAndOwnership"].get("common:dataSetVersion")) != (
        pin["source_namespace"], pin["source_version"], pin["flow_uuid"], pin["source_version"]
    ):
        raise ValueError("open Flow source identity differs from the steel pin")
    if (port.get("flowUuid"), port.get("flowSourceNamespace"), port.get("flowVersion"),
        port.get("flowPropertyUuid"), port.get("unitGroupUuid")) != (
        pin["flow_uuid"], pin["source_namespace"], pin["source_version"],
        pin["flow_property_uuid"], pin["unit_group_uuid"]):
        raise ValueError("public supply CO2 port differs from pinned TianGong Flow")

    def observed_version() -> dict[str, Any] | None:
        try:
            return client.get_flow_version(pin["source_namespace"], pin["flow_uuid"], pin["source_version"])
        except DomainError as error:
            if error.details.get("upstream_status") == 404:
                return None
            raise

    observed = observed_version()
    if observed is None:
        for dry_run in (True, False):
            receipt = client.import_tidas_flows(filename=asset_path.name, payload=payload, dry_run=dry_run).payload
            if receipt["failed"] or receipt["errors"] or receipt["total_records"] != 1:
                raise ValueError("open TianGong Flow import did not verify cleanly")
        observed = observed_version()
        if observed is None:
            raise ValueError("versioned TianGong Flow was not persisted")
        status = "imported"
    else:
        status = "present"
    expected = {
        "flow_id": pin["flow_uuid"], "source_namespace": pin["source_namespace"],
        "source_version": pin["source_version"], "unit": pin["default_unit"],
        "unit_group": pin["unit_group"], "tidas_flow_property_uuid": pin["flow_property_uuid"],
        "content_hash": pin["flow_snapshot_content_hash"],
    }
    differences = [key for key, value in expected.items() if observed.get(key) != value]
    if differences:
        raise ValueError("versioned TianGong Flow identity drifted: " + ",".join(differences))
    return {"status": status, "flow_uuid": pin["flow_uuid"], "source_version": pin["source_version"]}

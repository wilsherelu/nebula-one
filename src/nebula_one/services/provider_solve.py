from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from ..analysis.dependency_gap import dependency_gap
from ..database import Database
from ..errors import DomainError, UpstreamError
from ..hashing import canonical_json_sha256
from ..model_derivation import DerivedCalculationModel
from ..native_climate_contract import NativeClimateContract
from ..native_inventory_contract import NativeInventoryContract
from ..runtime_schemas import (
    ProviderBackgroundProcessPin,
    ProviderProjectBackgroundPin,
    ProviderDemandItem,
    ProviderSolveAndFreezeCreate,
    SolvedSystemSnapshotCreate,
)
from ..mapped_background_schemas import ProviderMappedBackgroundProcessPin
from ..models import AnalysisRun, Application, OutboxEvent, SystemModel
from ..runtime_models import Scenario
from ..schemas import AnalysisRunCreate
from .analysis_runs import ANALYSIS_EXECUTE_TOPIC, AnalysisRunService
from .model_processing_runtime import PurposeDerivation, flow_selection_of, resolve_purpose_derivation
from .results import ResultService
from .mapped_background_receipts import validate_mapped_receipts
from .runtime_support import require_revision
from .runtime_support import require_method_package
from .climate_method_selection import ensure_official_climate_methods, resolve_new_climate_method


SOLVE_AND_FREEZE_TOPIC = "solve.freeze.v1"

# Engine refusals that mean "the licensed background vector contains an emission flow whose exact
# identity is not covered by an accepted mapping". Retrying, renaming or dropping the row cannot
# fix them, and they are reported as one coverage gap instead of one row at a time.
BACKGROUND_ELEMENTARY_MAPPING_REFUSALS = frozenset({
    "MAPPED_BACKGROUND_ELEMENTARY_MAPPING_NOT_FOUND",
    "MAPPED_BACKGROUND_ELEMENTARY_MAPPING_AMBIGUOUS",
    "MAPPED_BACKGROUND_ELEMENTARY_STANDARD_NOT_FOUND",
})


def unverified_background_mapping(exc: DomainError) -> DomainError:
    """Restate an engine mapping-coverage refusal for the operator, keeping the upstream evidence.

    An idempotent replay of the failed run re-raises the stored failure as a plain DomainError, so
    the upstream code is read from the preserved detail rather than from the exception type.
    """
    detail = exc.details.get("upstream_detail")
    code = detail.get("code") if isinstance(detail, dict) else None
    if code not in BACKGROUND_ELEMENTARY_MAPPING_REFUSALS:
        return exc
    unresolved = detail.get("details") if isinstance(detail.get("details"), dict) else {}
    return UpstreamError(
        code="PROJECT_BACKGROUND_ELEMENTARY_MAPPING_UNVERIFIED",
        message="背景排放流映射待核实：所选背景过程仍有排放流没有已审定的身份映射，本次计算没有产生结果。",
        status_code=422,
        details={
            **exc.details,
            "upstream_code": code,
            "dependency_gap": dependency_gap(
                code=str(code),
                kind="background_elementary_mapping",
                step="provider_solve",
                what_missing={
                    "required_identity": "当前计算路径所需的背景排放流身份映射尚未通过核验",
                },
                affects={
                    "downstream_steps": ["mfa", "pcf", "cbam"],
                    "scopes_affected": ["所选背景过程的上游排放"],
                },
                how_to_resolve=[{
                    "action": "由 Nebula LCA 核实背景排放流的身份映射及所选方法的覆盖情况，再重算",
                    "owner": "Nebula LCA 来源侧",
                    "precondition": "身份映射通过当前路径校验；方法未收录、显式零因子与非零因子分别记录，不要求每条流都有非零因子",
                }],
                evidence={
                    "upstream_status": exc.details.get("upstream_status"),
                    "endpoint": exc.details.get("path"),
                    "unresolved_elementary_flows": dict(unresolved),
                },
            ),
        },
    )


@dataclass(frozen=True, slots=True)
class ProviderSolveContext:
    application_id: str
    system_revision_id: str
    system_model_id: str
    revision_hash: str
    functional_unit: Any
    scenario_hash: str | None
    graph_snapshot: dict[str, Any]
    analysis_request: AnalysisRunCreate
    native_background_climate: dict[str, Any] | None = None
    native_background_inventory: dict[str, Any] | None = None
    # The purpose's derivation basis, exactly as the worker will re-derive it: sent demand,
    # effective associations and the reviewed rule/method identities, plus the source model.
    calculation_basis: dict[str, Any] | None = None
    calculation_model: DerivedCalculationModel | None = None


def _required_text(item: dict[str, Any], key: str, *, context: str) -> str:
    value = str(item.get(key) or "").strip()
    if not value:
        raise DomainError(
            code="PROVIDER_SOLVE_RESULT_INVALID",
            message=f"provider solve result lacks {key} for {context}",
            status_code=502,
            details={"field": key, "context": context},
        )
    return value


def _map_activity(item: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "process_id": _required_text(item, "process_uuid", context=f"activity[{index}]"),
        "value": item.get("activity_amount"),
        "unit": _required_text(item, "unit", context=f"activity[{index}]"),
    }


def _map_exchange(item: dict[str, Any], index: int) -> dict[str, Any]:
    context = f"scaled_exchanges[{index}]"
    return {
        "exchange_id": _required_text(item, "exchange_id", context=context),
        "process_id": _required_text(item, "process_uuid", context=context),
        "counterparty_process_id": item.get("counterparty_process_uuid"),
        "flow_uuid": _required_text(item, "flow_uuid", context=context),
        "amount": item.get("scaled_amount"),
        "unit": _required_text(item, "unit", context=context),
        "unit_group": _required_text(item, "unit_group_uuid", context=context),
        "direction": _required_text(item, "direction", context=context),
        "exchange_type": _required_text(item, "exchange_type", context=context),
    }


def _graph_technosphere_exchanges(
    graph: dict[str, Any],
) -> dict[str, dict[str, str]]:
    expected: dict[str, dict[str, str]] = {}
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return expected
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "").strip()
        process_uuid = str(node.get("process_uuid") or "").strip()
        for collection in ("inputs", "outputs"):
            ports = node.get(collection)
            if not isinstance(ports, list):
                continue
            for port in ports:
                if not isinstance(port, dict) or port.get("type") != "technosphere":
                    continue
                port_id = str(port.get("id") or "").strip()
                exchange_id = f"{node_id}::{port_id}"
                expected[exchange_id] = {
                    "process_uuid": process_uuid,
                    "direction": "input" if collection == "inputs" else "output",
                    "source_namespace": str(
                        port.get("flowSourceNamespace")
                        or port.get("flow_source_namespace")
                        or ""
                    ).strip(),
                    "flow_uuid": str(port.get("flowUuid") or "").strip(),
                    "version": str(
                        port.get("flowVersion") or port.get("flow_version") or ""
                    ).strip(),
                    "flow_property_uuid": str(
                        port.get("flowPropertyUuid")
                        or port.get("flow_property_uuid")
                        or ""
                    ).strip(),
                    "flow_property_version": str(
                        port.get("flowPropertyVersion")
                        or port.get("flow_property_version")
                        or ""
                    ).strip(),
                    "unit_group_uuid": str(
                        port.get("unitGroupUuid")
                        or port.get("unit_group_uuid")
                        or ""
                    ).strip(),
                    "unit_group_version": str(
                        port.get("unitGroupVersion")
                        or port.get("unit_group_version")
                        or ""
                    ).strip(),
                    "unit": str(port.get("unit") or "").strip(),
                }
    return expected


def _validated_technosphere_receipts(
    result: dict[str, Any],
    graph: dict[str, Any],
    *,
    analysis_run_id: str,
) -> list[dict[str, Any]]:
    expected = _graph_technosphere_exchanges(graph)
    exact_tidas_ids = {
        exchange_id
        for exchange_id, identity in expected.items()
        if identity["source_namespace"] == "tiangong_open_data"
    }
    raw_receipts = result.get("technosphere_flow_receipts")
    if raw_receipts is None:
        if exact_tidas_ids:
            raise DomainError(
                code="PROVIDER_TIDAS_RECEIPT_MISSING",
                message="provider solve did not return exact TIDAS technosphere Flow receipts",
                status_code=502,
                details={
                    "analysis_run_id": analysis_run_id,
                    "exchange_ids": sorted(exact_tidas_ids),
                },
            )
        return []
    if not isinstance(raw_receipts, list) or any(
        not isinstance(item, dict) for item in raw_receipts
    ):
        raise DomainError(
            code="PROVIDER_TECHNOSPHERE_RECEIPT_INVALID",
            message="provider solve returned an invalid technosphere Flow receipt collection",
            status_code=502,
            details={"analysis_run_id": analysis_run_id},
        )
    by_exchange: dict[str, dict[str, Any]] = {}
    for index, receipt in enumerate(raw_receipts):
        exchange_id = _required_text(
            receipt, "exchange_id", context=f"technosphere_flow_receipts[{index}]"
        )
        if exchange_id in by_exchange:
            raise DomainError(
                code="PROVIDER_TECHNOSPHERE_RECEIPT_DUPLICATE",
                message="provider solve returned duplicate technosphere Flow receipts",
                status_code=502,
                details={"analysis_run_id": analysis_run_id, "exchange_id": exchange_id},
            )
        by_exchange[exchange_id] = receipt

    if set(by_exchange) != set(expected):
        raise DomainError(
            code="PROVIDER_TECHNOSPHERE_RECEIPT_SET_MISMATCH",
            message="provider technosphere Flow receipts do not match the solved graph exchanges",
            status_code=502,
            details={
                "analysis_run_id": analysis_run_id,
                "missing_exchange_ids": sorted(set(expected).difference(by_exchange)),
                "unexpected_exchange_ids": sorted(set(by_exchange).difference(expected)),
            },
        )

    identity_fields = (
        "process_uuid",
        "source_namespace",
        "flow_uuid",
        "version",
        "flow_property_uuid",
        "flow_property_version",
        "unit_group_uuid",
        "unit_group_version",
        "unit",
    )
    exact_hash_fields = (
        "content_hash",
        "snapshot_hash",
        "flow_property_content_hash",
        "unit_group_content_hash",
        "unit_content_hash",
    )
    for exchange_id, graph_identity in expected.items():
        receipt = by_exchange[exchange_id]
        mismatches = {
            field: {"graph": graph_identity[field], "receipt": receipt.get(field)}
            for field in identity_fields
            if str(receipt.get(field) or "").strip() != graph_identity[field]
        }
        if mismatches:
            raise DomainError(
                code="PROVIDER_TECHNOSPHERE_RECEIPT_IDENTITY_MISMATCH",
                message="provider technosphere Flow receipt does not match the solved graph identity",
                status_code=502,
                details={
                    "analysis_run_id": analysis_run_id,
                    "exchange_id": exchange_id,
                    "mismatches": mismatches,
                },
            )
        resolution = str(receipt.get("resolution") or "").strip()
        if exchange_id in exact_tidas_ids:
            missing_hashes = [
                field
                for field in exact_hash_fields
                if not str(receipt.get(field) or "").strip()
            ]
            if resolution != "tidas_exact_snapshot" or missing_hashes:
                raise DomainError(
                    code="PROVIDER_TIDAS_RECEIPT_INVALID",
                    message="provider did not prove the exact TIDAS Flow and dependency closure",
                    status_code=502,
                    details={
                        "analysis_run_id": analysis_run_id,
                        "exchange_id": exchange_id,
                        "resolution": resolution,
                        "missing_hash_fields": missing_hashes,
                    },
                )
        elif resolution != "inline_custom":
            raise DomainError(
                code="PROVIDER_CUSTOM_FLOW_CLASSIFICATION_INVALID",
                message="provider did not classify an inline custom technosphere Flow explicitly",
                status_code=502,
                details={
                    "analysis_run_id": analysis_run_id,
                    "exchange_id": exchange_id,
                    "resolution": resolution,
                },
            )
    return [by_exchange[exchange_id] for exchange_id in sorted(by_exchange)]


def _validated_background_process_receipts(
    result: dict[str, Any],
    pins: list[ProviderBackgroundProcessPin],
    graph: dict[str, Any],
    *,
    analysis_run_id: str,
) -> list[dict[str, Any]]:
    raw_receipts = result.get("background_process_receipts")
    if raw_receipts is None:
        raw_receipts = []
    if not isinstance(raw_receipts, list) or any(
        not isinstance(item, dict) for item in raw_receipts
    ):
        raise DomainError(
            code="PROVIDER_BACKGROUND_RECEIPT_INVALID",
            message="provider returned an invalid background Process receipt collection",
            status_code=502,
            details={"analysis_run_id": analysis_run_id},
        )
    if not pins and raw_receipts:
        raise DomainError(
            code="PROVIDER_BACKGROUND_RECEIPT_UNREQUESTED",
            message="provider returned background Process receipts without an explicit pin",
            status_code=502,
            details={"analysis_run_id": analysis_run_id},
        )
    expected_pins = {item.consumer_exchange_id: item for item in pins}
    by_consumer: dict[str, dict[str, Any]] = {}
    for index, receipt in enumerate(raw_receipts):
        consumer_id = _required_text(
            receipt,
            "consumer_exchange_id",
            context=f"background_process_receipts[{index}]",
        )
        if consumer_id in by_consumer:
            raise DomainError(
                code="PROVIDER_BACKGROUND_RECEIPT_DUPLICATE",
                message="provider returned duplicate background Process receipts",
                status_code=502,
                details={
                    "analysis_run_id": analysis_run_id,
                    "consumer_exchange_id": consumer_id,
                },
            )
        by_consumer[consumer_id] = receipt
    if set(by_consumer) != set(expected_pins):
        raise DomainError(
            code="PROVIDER_BACKGROUND_RECEIPT_SET_MISMATCH",
            message="provider background Process receipts do not match the requested pins",
            status_code=502,
            details={
                "analysis_run_id": analysis_run_id,
                "missing_consumer_exchange_ids": sorted(
                    set(expected_pins).difference(by_consumer)
                ),
                "unexpected_consumer_exchange_ids": sorted(
                    set(by_consumer).difference(expected_pins)
                ),
            },
        )
    if not pins:
        return []

    graph_exchanges = _graph_technosphere_exchanges(graph)
    scaled = result.get("scaled_exchanges")
    elementary_flow_receipts = result.get("elementary_flow_receipts")
    provenance = result.get("provenance")
    if (
        not isinstance(scaled, list)
        or any(not isinstance(item, dict) for item in scaled)
        or not isinstance(elementary_flow_receipts, list)
        or any(not isinstance(item, dict) for item in elementary_flow_receipts)
        or not isinstance(provenance, dict)
    ):
        raise DomainError(
            code="PROVIDER_BACKGROUND_RECEIPT_INVALID",
            message="provider background receipts lack solved exchange or provenance evidence",
            status_code=502,
            details={"analysis_run_id": analysis_run_id},
        )
    scaled_by_id = {
        str(item.get("exchange_id") or ""): item for item in scaled
    }
    if "" in scaled_by_id or len(scaled_by_id) != len(scaled):
        raise DomainError(
            code="PROVIDER_BACKGROUND_SCALED_EXCHANGE_INVALID",
            message="provider scaled exchange identities are missing or duplicated",
            status_code=502,
            details={"analysis_run_id": analysis_run_id},
        )
    elementary_receipt_ids = {
        str(item.get("exchange_id") or "") for item in elementary_flow_receipts
    }
    expected_pins_hash = canonical_json_sha256(
        [
            item.model_dump(mode="json")
            for item in sorted(pins, key=lambda pin: pin.consumer_exchange_id)
        ]
    )
    if (
        provenance.get("background_process_pins_hash") != expected_pins_hash
        or provenance.get("background_claim_scope")
        != "partial_background_leaf_only_not_complete_cradle_to_gate"
    ):
        raise DomainError(
            code="PROVIDER_BACKGROUND_PROVENANCE_MISMATCH",
            message="provider background provenance does not match the exact request pins",
            status_code=502,
            details={"analysis_run_id": analysis_run_id},
        )

    def require_sha256(value: Any, *, field: str, consumer_id: str) -> None:
        if re.fullmatch(r"[0-9a-f]{64}", str(value or "")) is None:
            raise DomainError(
                code="PROVIDER_BACKGROUND_RECEIPT_INVALID",
                message=f"provider background receipt has invalid {field}",
                status_code=502,
                details={
                    "analysis_run_id": analysis_run_id,
                    "consumer_exchange_id": consumer_id,
                    "field": field,
                },
            )

    def finite_number(value: Any, *, field: str, consumer_id: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            number = math.nan
        else:
            number = float(value)
        if not math.isfinite(number) or number < 0:
            raise DomainError(
                code="PROVIDER_BACKGROUND_RECEIPT_INVALID",
                message=f"provider background receipt has invalid {field}",
                status_code=502,
                details={
                    "analysis_run_id": analysis_run_id,
                    "consumer_exchange_id": consumer_id,
                    "field": field,
                },
            )
        return number

    for consumer_id, pin in expected_pins.items():
        receipt = by_consumer[consumer_id]
        graph_identity = graph_exchanges.get(consumer_id)
        if graph_identity is None or graph_identity["direction"] != "input":
            raise DomainError(
                code="PROVIDER_BACKGROUND_CONSUMER_MISMATCH",
                message="background pin does not target a graph input exchange",
                status_code=502,
                details={
                    "analysis_run_id": analysis_run_id,
                    "consumer_exchange_id": consumer_id,
                },
            )
        consumer_solved = scaled_by_id.get(consumer_id)
        expected_consumer_values = {
            "process_uuid": graph_identity["process_uuid"],
            "flow_uuid": graph_identity["flow_uuid"],
            "flow_source_namespace": graph_identity["source_namespace"],
            "flow_version": graph_identity["version"],
            "flow_property_uuid": graph_identity["flow_property_uuid"],
            "flow_property_version": graph_identity["flow_property_version"],
            "unit_group_uuid": graph_identity["unit_group_uuid"],
            "unit_group_version": graph_identity["unit_group_version"],
            "unit": graph_identity["unit"],
            "direction": "input",
            "exchange_type": "technosphere",
        }
        consumer_mismatches = {
            field: {"graph": expected, "scaled_exchange": (consumer_solved or {}).get(field)}
            for field, expected in expected_consumer_values.items()
            if (consumer_solved or {}).get(field) != expected
        }
        if consumer_solved is None or consumer_mismatches:
            raise DomainError(
                code="PROVIDER_BACKGROUND_CONSUMER_SCALED_EXCHANGE_MISMATCH",
                message="provider background consumer exchange differs from the frozen graph",
                status_code=502,
                details={
                    "analysis_run_id": analysis_run_id,
                    "consumer_exchange_id": consumer_id,
                    "mismatches": consumer_mismatches,
                },
            )
        expected_values = {
            "schema_version": "provider.background-process-receipt.v1",
            "claim_role": "partial_background_leaf",
            "claim_limit": "partial_background_leaf_only_not_complete_cradle_to_gate",
            "source_namespace": pin.source_namespace,
            "process_uuid": pin.process_uuid,
            "version": pin.version,
            "process_content_hash": pin.expected_process_content_hash,
            "process_snapshot_hash": pin.expected_process_snapshot_hash,
            "quantitative_reference_exchange_internal_id": (
                pin.quantitative_reference_exchange_internal_id
            ),
            "quantitative_reference_flow_uuid": graph_identity["flow_uuid"],
            "quantitative_reference_flow_version": graph_identity["version"],
        }
        mismatches = {
            field: {"expected": expected, "actual": receipt.get(field)}
            for field, expected in expected_values.items()
            if receipt.get(field) != expected
        }
        if mismatches:
            raise DomainError(
                code="PROVIDER_BACKGROUND_RECEIPT_IDENTITY_MISMATCH",
                message="provider background Process receipt does not match its exact pin",
                status_code=502,
                details={
                    "analysis_run_id": analysis_run_id,
                    "consumer_exchange_id": consumer_id,
                    "mismatches": mismatches,
                },
            )
        require_sha256(
            receipt.get("process_content_hash"),
            field="process_content_hash",
            consumer_id=consumer_id,
        )
        require_sha256(
            receipt.get("process_snapshot_hash"),
            field="process_snapshot_hash",
            consumer_id=consumer_id,
        )
        qref_amount = finite_number(
            receipt.get("quantitative_reference_amount"),
            field="quantitative_reference_amount",
            consumer_id=consumer_id,
        )
        activity_amount = finite_number(
            receipt.get("activity_amount"),
            field="activity_amount",
            consumer_id=consumer_id,
        )
        process_scale = finite_number(
            receipt.get("process_scale"),
            field="process_scale",
            consumer_id=consumer_id,
        )
        if qref_amount <= 0 or activity_amount <= 0 or process_scale <= 0 or not math.isclose(
            activity_amount,
            qref_amount * process_scale,
            rel_tol=1e-9,
            abs_tol=1e-12,
        ):
            raise DomainError(
                code="PROVIDER_BACKGROUND_SCALE_MISMATCH",
                message="provider background activity and Process scale are inconsistent",
                status_code=502,
                details={
                    "analysis_run_id": analysis_run_id,
                    "consumer_exchange_id": consumer_id,
                },
            )
        exchanges = receipt.get("exchanges")
        if not isinstance(exchanges, list) or not exchanges or any(
            not isinstance(item, dict) for item in exchanges
        ):
            raise DomainError(
                code="PROVIDER_BACKGROUND_EXCHANGE_RECEIPT_INVALID",
                message="provider background Process receipt has no exchange provenance",
                status_code=502,
                details={
                    "analysis_run_id": analysis_run_id,
                    "consumer_exchange_id": consumer_id,
                },
            )
        internal_ids = [str(item.get("exchange_internal_id") or "") for item in exchanges]
        expanded_ids = [str(item.get("expanded_exchange_id") or "") for item in exchanges]
        if (
            not all(internal_ids)
            or not all(expanded_ids)
            or len(internal_ids) != len(set(internal_ids))
            or len(expanded_ids) != len(set(expanded_ids))
        ):
            raise DomainError(
                code="PROVIDER_BACKGROUND_EXCHANGE_RECEIPT_INVALID",
                message="provider background exchange provenance identities are missing or duplicated",
                status_code=502,
                details={
                    "analysis_run_id": analysis_run_id,
                    "consumer_exchange_id": consumer_id,
                },
            )
        qref_rows = [item for item in exchanges if item.get("role") == "quantitative_reference"]
        elementary_rows = [item for item in exchanges if item.get("role") == "elementary"]
        if len(qref_rows) != 1 or len(qref_rows) + len(elementary_rows) != len(exchanges):
            raise DomainError(
                code="PROVIDER_BACKGROUND_EXCHANGE_ROLE_INVALID",
                message="provider background exchanges do not contain one qref and only elementary dependents",
                status_code=502,
                details={
                    "analysis_run_id": analysis_run_id,
                    "consumer_exchange_id": consumer_id,
                },
            )
        if qref_rows[0].get("exchange_internal_id") != pin.quantitative_reference_exchange_internal_id:
            raise DomainError(
                code="PROVIDER_BACKGROUND_QREF_RECEIPT_MISMATCH",
                message="provider background qref exchange does not match the exact pin",
                status_code=502,
                details={
                    "analysis_run_id": analysis_run_id,
                    "consumer_exchange_id": consumer_id,
                },
            )
        qref_identity = {
            "source_namespace": graph_identity["source_namespace"],
            "flow_uuid": graph_identity["flow_uuid"],
            "version": graph_identity["version"],
            "flow_property_uuid": graph_identity["flow_property_uuid"],
            "flow_property_version": graph_identity["flow_property_version"],
            "unit_group_uuid": graph_identity["unit_group_uuid"],
            "unit_group_version": graph_identity["unit_group_version"],
            "unit": graph_identity["unit"],
            "direction": "output",
        }
        qref_identity_mismatches = {
            field: {"graph": expected, "receipt": qref_rows[0].get(field)}
            for field, expected in qref_identity.items()
            if qref_rows[0].get(field) != expected
        }
        if qref_identity_mismatches:
            raise DomainError(
                code="PROVIDER_BACKGROUND_QREF_IDENTITY_MISMATCH",
                message="provider background qref identity differs from its consumer Flow",
                status_code=502,
                details={
                    "analysis_run_id": analysis_run_id,
                    "consumer_exchange_id": consumer_id,
                    "mismatches": qref_identity_mismatches,
                },
            )
        for exchange in exchanges:
            expanded_id = str(exchange["expanded_exchange_id"])
            solved = scaled_by_id.get(expanded_id)
            if solved is None:
                raise DomainError(
                    code="PROVIDER_BACKGROUND_SCALED_EXCHANGE_MISSING",
                    message="provider background provenance lacks its solved scaled exchange",
                    status_code=502,
                    details={
                        "analysis_run_id": analysis_run_id,
                        "consumer_exchange_id": consumer_id,
                        "expanded_exchange_id": expanded_id,
                    },
                )
            require_sha256(
                exchange.get("flow_content_hash"),
                field="flow_content_hash",
                consumer_id=consumer_id,
            )
            snapshot_hash = exchange.get("flow_snapshot_hash")
            if snapshot_hash is not None:
                require_sha256(
                    snapshot_hash,
                    field="flow_snapshot_hash",
                    consumer_id=consumer_id,
                )
            raw_amount = finite_number(
                exchange.get("raw_amount"),
                field="raw_amount",
                consumer_id=consumer_id,
            )
            scaled_amount = finite_number(
                exchange.get("scaled_amount"),
                field="scaled_amount",
                consumer_id=consumer_id,
            )
            solved_values = {
                "process_uuid": receipt["process_uuid"],
                "flow_uuid": exchange.get("flow_uuid"),
                "flow_source_namespace": exchange.get("source_namespace"),
                "flow_version": exchange.get("version"),
                "flow_property_uuid": exchange.get("flow_property_uuid"),
                "flow_property_version": exchange.get("flow_property_version"),
                "unit_group_uuid": exchange.get("unit_group_uuid"),
                "unit_group_version": exchange.get("unit_group_version"),
                "unit": exchange.get("unit"),
                "direction": exchange.get("direction"),
                "raw_amount": raw_amount,
                "scaled_amount": scaled_amount,
            }
            solved_mismatches = {
                field: {"receipt": expected, "scaled_exchange": solved.get(field)}
                for field, expected in solved_values.items()
                if solved.get(field) != expected
            }
            expected_exchange_type = (
                "technosphere"
                if exchange.get("role") == "quantitative_reference"
                else "elementary"
            )
            if solved.get("exchange_type") != expected_exchange_type:
                solved_mismatches["exchange_type"] = {
                    "receipt": expected_exchange_type,
                    "scaled_exchange": solved.get("exchange_type"),
                }
            if solved_mismatches:
                raise DomainError(
                    code="PROVIDER_BACKGROUND_SCALED_EXCHANGE_MISMATCH",
                    message="provider background receipt conflicts with solved scaled exchange",
                    status_code=502,
                    details={
                        "analysis_run_id": analysis_run_id,
                        "consumer_exchange_id": consumer_id,
                        "expanded_exchange_id": expanded_id,
                        "mismatches": solved_mismatches,
                    },
                )
            if exchange.get("role") == "elementary" and expanded_id not in elementary_receipt_ids:
                raise DomainError(
                    code="PROVIDER_BACKGROUND_ELEMENTARY_RECEIPT_MISSING",
                    message="provider background elementary exchange lacks an EF 3.1 receipt",
                    status_code=502,
                    details={
                        "analysis_run_id": analysis_run_id,
                        "consumer_exchange_id": consumer_id,
                        "expanded_exchange_id": expanded_id,
                    },
                )
        qref_scaled = float(qref_rows[0]["scaled_amount"])
        consumer_scaled = finite_number(
            consumer_solved.get("scaled_amount"),
            field="consumer_scaled_amount",
            consumer_id=consumer_id,
        )
        if (
            not math.isclose(qref_scaled, activity_amount, rel_tol=1e-9, abs_tol=1e-12)
            or not math.isclose(qref_scaled, consumer_scaled, rel_tol=1e-9, abs_tol=1e-12)
        ):
            raise DomainError(
                code="PROVIDER_BACKGROUND_QREF_SCALE_MISMATCH",
                message="provider background qref differs from activity or consumer amount",
                status_code=502,
                details={
                    "analysis_run_id": analysis_run_id,
                    "consumer_exchange_id": consumer_id,
                },
            )
    return [by_consumer[key] for key in sorted(by_consumer)]


def _validated_project_background_receipts(result: dict[str, Any], pins: list[ProviderProjectBackgroundPin]) -> list[dict[str, Any]]:
    raw = result.get("project_background_process_receipts") or []
    provenance = result.get("provenance") or {}
    expected = {pin.consumer_exchange_id: pin.model_dump(mode="json") for pin in pins}
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise DomainError(code="PROJECT_BACKGROUND_RECEIPT_INVALID", message="算法服务返回的自建供应回执无效。", status_code=502)
    actual = {str(item.get("pin", {}).get("consumer_exchange_id") or ""): item for item in raw}
    if len(actual) != len(raw) or set(actual) != set(expected):
        raise DomainError(code="PROJECT_BACKGROUND_RECEIPT_MISMATCH", message="自建供应回执与请求入口不一致。", status_code=502)
    if pins and provenance.get("project_background_pins_hash") != canonical_json_sha256(
        [expected[key] for key in sorted(expected)]
    ):
        raise DomainError(code="PROJECT_BACKGROUND_RECEIPT_MISMATCH", message="自建供应版本哈希回执不一致。", status_code=502)
    activities = {str(item.get("process_uuid")): item.get("activity_amount") for item in result.get("activity_vector") or []}
    for consumer_id, item in actual.items():
        pin = expected[consumer_id]
        if (item.get("pin") != pin or item.get("source_graph_hash") != pin["expected_graph_hash"]
                or item.get("claim_limit") != "user_declared_partial_background_leaf_only"
                or item.get("source_process_uuid") not in activities
                or item.get("activity_amount") != activities.get(item.get("source_process_uuid"))):
            raise DomainError(code="PROJECT_BACKGROUND_RECEIPT_MISMATCH", message="自建供应过程或求解活动回执不一致。", status_code=502)
    return [actual[key] for key in sorted(actual)]


class ProviderSolveService:
    def __init__(
        self,
        database: Database,
        analysis_runs: AnalysisRunService,
        results: ResultService,
        native_climate: NativeClimateContract,
        native_inventory: NativeInventoryContract | None = None,
    ) -> None:
        self.database = database
        self.analysis_runs = analysis_runs
        self.results = results
        self.native_climate = native_climate
        self.native_inventory = native_inventory or NativeInventoryContract(None)

    def _prepare(
        self,
        application_id: str,
        system_revision_id: str,
        payload: ProviderSolveAndFreezeCreate,
        *,
        accepted_basis: dict[str, Any] | None = None,
        accepted_climate_method: dict[str, Any] | None = None,
    ) -> ProviderSolveContext:
        with self.database.session() as db:
            revision, system_model = require_revision(
                db, system_revision_id, application_id
            )
            application = db.get(Application, application_id)
            if application and application.context.get("template_locked"):
                saved = revision.application_context.get("project_inputs")
                requested = [item.model_dump(mode="json", exclude_none=True) for item in payload.demand]
                expected = [ProviderDemandItem.model_validate(item).model_dump(mode="json", exclude_none=True) for item in saved["demand"]] if saved else None
                if not saved or canonical_json_sha256(requested) != canonical_json_sha256(expected):
                    raise DomainError(code="PROJECT_SAVED_INPUT_REQUIRED", message="请先保存生产数据，计算需求必须与选中数据版本一致。", status_code=409)
                expected_pins = saved.get('background_process_pins', [])
                requested_pins = [p.model_dump(mode='json') for p in payload.background_process_pins]
                if sorted(requested_pins, key=lambda p: p['consumer_exchange_id']) != sorted(expected_pins, key=lambda p: p['consumer_exchange_id']):
                    raise DomainError(code="PROJECT_BACKGROUND_NOT_APPROVED", message="此模板尚未声明可替换的背景数据，请先完成兼容性审查。", status_code=422)
                expected_mapped = saved.get('mapped_background_process_pins', [])
                requested_mapped = [p.model_dump(mode='json') for p in payload.mapped_background_process_pins]
                if sorted(expected_mapped, key=lambda p: p['consumer_exchange_id']) != sorted(requested_mapped, key=lambda p: p['consumer_exchange_id']):
                    raise DomainError(code='PROJECT_BACKGROUND_NOT_APPROVED', message='计算背景必须与所选数据版本保存的映射一致。', status_code=422)
                expected_project = saved.get("project_background_pins", [])
                requested_project = [p.model_dump(mode="json") for p in payload.project_background_pins]
                if sorted(expected_project, key=lambda p: p["consumer_exchange_id"]) != sorted(requested_project, key=lambda p: p["consumer_exchange_id"]):
                    raise DomainError(code="PROJECT_BACKGROUND_NOT_APPROVED", message="计算供应项目必须与所选数据版本一致。", status_code=422)
            if system_model.upstream_receipt.get("solve_readiness") == "blocked_missing_dependencies":
                raise DomainError(
                    code="MODEL_SOURCE_DEPENDENCIES_MISSING",
                    message="restored model can be browsed but cannot be solved until its external dependencies are available",
                    status_code=409,
                    details={
                        "system_model_id": system_model.id,
                        "external_dependencies": system_model.upstream_receipt.get(
                            "external_dependencies", []
                        ),
                    },
                )
            scenario_hash = None
            if payload.scenario_id is not None:
                scenario = db.get(Scenario, payload.scenario_id)
                if scenario is None:
                    raise DomainError(
                        code="SCENARIO_NOT_FOUND",
                        message=f"scenario not found: {payload.scenario_id}",
                        status_code=404,
                    )
                if scenario.application_id != application_id:
                    raise DomainError(
                        code="SCENARIO_APPLICATION_MISMATCH",
                        message="scenario does not belong to the requested application",
                        status_code=409,
                    )
                if scenario.status != "frozen":
                    raise DomainError(
                        code="SCENARIO_NOT_FROZEN",
                        message="provider solve requires a frozen scenario",
                        status_code=409,
                    )
                if scenario.system_revision_id != system_revision_id:
                    raise DomainError(
                        code="SCENARIO_REVISION_MISMATCH",
                        message="scenario does not bind to the requested system revision",
                        status_code=409,
                    )
                if scenario.inventory_snapshot_id or scenario.parameter_set_id:
                    raise DomainError(
                        code="SCENARIO_INPUT_BINDING_UNSUPPORTED",
                        message="provider solve cannot yet consume scenario inventory or parameter bindings",
                        status_code=422,
                        details={
                            "inventory_snapshot_id": scenario.inventory_snapshot_id,
                            "parameter_set_id": scenario.parameter_set_id,
                        },
                    )
                scenario_hash = scenario.content_sha256

            parameters: dict[str, Any] = {
                "demand": [item.model_dump(mode="json") for item in payload.demand]
            }
            preliminary_derivation = None
            effective_mapped_pins = [item.model_dump(mode="json") for item in payload.mapped_background_process_pins]
            effective_background_pins = [item.model_dump(mode="json") for item in payload.background_process_pins]
            if payload.climate_default:
                source_parameters = {
                    **parameters,
                    "lcia_methods": self.native_climate.solve_methods(),
                    "background_process_pins": [item.model_dump(mode="json") for item in payload.background_process_pins],
                    "mapped_background_process_pins": effective_mapped_pins,
                    "project_background_pins": [item.model_dump(mode="json") for item in payload.project_background_pins],
                }
                preliminary_derivation = self._derive_purpose(
                    db, revision=revision, application=application, payload=payload,
                    parameters=source_parameters, native_pin=None, accepted_basis=accepted_basis,
                )
                if preliminary_derivation is not None:
                    effective_mapped_pins = preliminary_derivation.derived.mapped_background_process_pins
                    effective_background_pins = preliminary_derivation.derived.background_process_pins
                if effective_mapped_pins and (effective_background_pins or payload.project_background_pins):
                    raise DomainError(
                        code="CLIMATE_DEFAULT_BACKGROUND_SOURCE_UNSUPPORTED",
                        message="native mapped providers cannot be mixed with other background sources in one climate solve",
                        status_code=422,
                    )
            use_native_climate = payload.native_background_climate or (
                payload.climate_default and bool(effective_mapped_pins)
            )
            if payload.climate_default and use_native_climate:
                providers = {item["process_uuid"] for item in effective_mapped_pins}
                if not providers or payload.scenario_id is not None:
                    raise DomainError(code="CLIMATE_DEFAULT_NATIVE_SCOPE_UNSUPPORTED",
                                      message="linked background requires a mapped provider for the pinned EF climate method",
                                      status_code=422)
            native_pin = (
                self.native_climate.request_payload()
                if use_native_climate
                else None
            )
            inventory_pin = None
            if payload.native_background_inventory:
                if self.native_inventory.request_pin is None:
                    raise DomainError(code="NATIVE_INVENTORY_CONTRACT_UNAVAILABLE",
                                      message="the native inventory source contract is not configured",
                                      status_code=422)
                inventory_pin = self.native_inventory.request_payload()
                parameters["native_background_inventory"] = inventory_pin
            if native_pin is not None:
                parameters["native_background_climate"] = native_pin
                # The contract's own method selection travels with the pin: the engine characterises
                # this solve under exactly one indicator, and a caller cannot widen it.
                parameters["lcia_methods"] = self.native_climate.solve_methods()
            if payload.scenario_id is not None:
                parameters["scenario_id"] = payload.scenario_id
            if payload.lcia_methods is not None:
                parameters["lcia_methods"] = payload.lcia_methods
            if payload.climate_default:
                ensure_official_climate_methods(db)
                db.commit()
                bound_refs = list((application.context or {}).get("method_package_refs") or []) if application else []
                if accepted_climate_method is None:
                    method = resolve_new_climate_method(db, bound_refs=bound_refs,
                                                       native=use_native_climate, native_request=native_pin)
                else:
                    method = require_method_package(db, accepted_climate_method["reference"])
                    if method.content_sha256 != accepted_climate_method["content_sha256"]:
                        raise DomainError(code="CLIMATE_METHOD_IDENTITY_MISMATCH",
                                          message="accepted climate method changed before solve recovery",
                                          status_code=409)
                formula = method.manifest["formula_graph"]
                if use_native_climate != bool(formula.get("source_contract")):
                    raise DomainError(code="CLIMATE_METHOD_SOURCE_MISMATCH",
                                      message="accepted climate method does not match the selected solve source",
                                      status_code=409)
                if native_pin is not None:
                    source = formula.get("source_method") or {}
                    if (source.get("id") != native_pin["method_package_id"]
                            or source.get("version") != native_pin["method_package_version"]
                            or source.get("content_sha256") != native_pin["method_package_sha256"]
                            or [formula.get("lcia_method")] != self.native_climate.solve_methods()):
                        raise DomainError(code="CLIMATE_METHOD_SOURCE_MISMATCH",
                                          message="native climate method differs from the pinned runtime source",
                                          status_code=409)
                if accepted_climate_method is not None and any(
                    accepted_climate_method.get(key) != value for key, value in {
                        "lcia_method": formula["lcia_method"],
                        "total_indicator_key": formula["total_indicator_key"],
                        "result_unit": formula["result_unit"],
                        "source_contract": formula.get("source_contract"),
                    }.items()
                ):
                    raise DomainError(code="CLIMATE_METHOD_IDENTITY_MISMATCH",
                                      message="accepted climate indicator differs from the registered method",
                                      status_code=409)
                parameters["lcia_methods"] = self.native_climate.solve_methods() if native_pin else [formula["lcia_method"]]
                parameters["climate_default"] = True
                parameters["calculation_method"] = {
                    "reference": f"{method.package_id}@{method.version}",
                    "content_sha256": method.content_sha256,
                    "lcia_method": formula["lcia_method"],
                    "total_indicator_key": formula["total_indicator_key"],
                    "result_unit": formula["result_unit"],
                    "source_contract": formula.get("source_contract"),
                }
            if payload.background_process_pins:
                parameters["background_process_pins"] = [
                    item.model_dump(mode="json")
                    for item in payload.background_process_pins
                ]
            if payload.mapped_background_process_pins:
                parameters['mapped_background_process_pins'] = [p.model_dump(mode='json') for p in payload.mapped_background_process_pins]
            if payload.project_background_pins:
                parameters["project_background_pins"] = [p.model_dump(mode="json") for p in payload.project_background_pins]
            derivation = self._derive_purpose(
                db,
                revision=revision,
                application=application,
                payload=payload,
                parameters=parameters,
                native_pin=native_pin,
                accepted_basis=accepted_basis,
            )
            if preliminary_derivation is not None and derivation is not None:
                if preliminary_derivation.basis_sha256 != derivation.basis_sha256:
                    raise DomainError(
                        code="CLIMATE_DEFAULT_SOURCE_DERIVATION_MISMATCH",
                        message="derived climate source changed between method selection and solve acceptance",
                        status_code=409,
                    )
            calculation_basis = (
                None
                if derivation is None
                else {**derivation.basis, "basis_sha256": derivation.basis_sha256}
            )
            if calculation_basis is not None:
                parameters["calculation_purpose"] = payload.calculation_purpose
                parameters["calculation_basis"] = calculation_basis
            if payload.analysis_task is not None:
                parameters["analysis_task"] = payload.analysis_task
            return ProviderSolveContext(
                application_id=application_id,
                system_revision_id=system_revision_id,
                system_model_id=system_model.id,
                revision_hash=revision.content_sha256,
                functional_unit=revision.graph_snapshot.get(
                    "functionalUnit",
                    revision.graph_snapshot.get("functional_unit"),
                ),
                scenario_hash=scenario_hash,
                graph_snapshot=revision.graph_snapshot,
                analysis_request=AnalysisRunCreate(
                    capability_key="solve.nebula.v1",
                    system_revision_id=system_revision_id,
                    idempotency_key=payload.idempotency_key,
                    parameters=parameters,
                ),
                native_background_climate=native_pin,
                native_background_inventory=inventory_pin,
                calculation_basis=calculation_basis,
                calculation_model=None if derivation is None else derivation.derived,
            )

    def _derive_purpose(
        self,
        db,
        *,
        revision,
        application: Application | None,
        payload: ProviderSolveAndFreezeCreate,
        parameters: dict[str, Any],
        native_pin: dict[str, Any] | None,
        accepted_basis: dict[str, Any] | None = None,
    ) -> PurposeDerivation | None:
        """Bind one accounting purpose to the reviewed rules, and record what will actually be sent.

        The caller names a purpose only. Which processes, associations and emissions that purpose
        keeps is decided by the versioned model processing package bound to this model's template,
        and the method content it cites is read back from the stored packages, so the basis stored
        here is the one the worker re-derives from and the frozen answer is identified by.

        A request that recovers an already-accepted run passes that run's basis, so recovery reads
        the rule identity the run was accepted with instead of whatever the template binds now; a
        newer reviewed rule version then cannot silently change a queued calculation.
        """
        if payload.calculation_purpose is None:
            return None
        derivation = resolve_purpose_derivation(
            db,
            revision=revision,
            application=application,
            purpose=payload.calculation_purpose,
            demand=parameters["demand"],
            background_process_pins=parameters.get("background_process_pins", []),
            mapped_background_process_pins=parameters.get(
                "mapped_background_process_pins", []
            ),
            project_background_pins=parameters.get("project_background_pins", []),
            lcia_methods=parameters.get("lcia_methods"),
            pinned_basis=accepted_basis,
        )
        if native_pin is not None and not derivation.derived.mapped_background_process_pins:
            raise DomainError(
                code="MODEL_DERIVATION_NATIVE_CLIMATE_UNLINKED",
                message=(
                    "此核算口径解除了全部背景关联，没有可刻画的供应过程，"
                    "不能计算原生背景气候总量；请改选保留背景关联的核算口径。"
                ),
                status_code=409,
                details={
                    "calculation_purpose": payload.calculation_purpose,
                    "unlinked_consumer_exchange_ids": [
                        action["consumer_exchange_id"]
                        for action in derivation.derived.actions
                        if action.get("action") == "unlink_background"
                    ],
                },
            )
        return derivation

    @staticmethod
    def _verify_derivation_stamp(run: AnalysisRun, context: ProviderSolveContext) -> None:
        """Freeze only a solve whose executed derivation is the one this request was accepted with.

        Three records have to agree: the basis this request derived, the basis the accepted run
        persisted, and the basis the worker stamped when it solved. Any one of them altered means
        the frozen number would no longer describe the calculation it claims to.
        """
        receipt = run.provider_receipt or {}
        stamp = receipt.get("model_derivation")
        if context.calculation_basis is None:
            if stamp is not None:
                raise DomainError(
                    code="PROVIDER_SOLVE_DERIVATION_MISMATCH",
                    message="求解回执记录了一个本次请求没有受理的派生计算依据，不能冻结结果。",
                    status_code=409,
                    details={"analysis_run_id": run.id},
                )
            return
        accepted = (run.parameters or {}).get("calculation_basis")
        executed = stamp.get("basis") if isinstance(stamp, dict) else None
        if executed != context.calculation_basis or accepted != context.calculation_basis:
            raise DomainError(
                code="PROVIDER_SOLVE_DERIVATION_MISMATCH",
                message="求解回执或已受理运行记录的计算依据与本次核算口径不一致，不能冻结结果。",
                status_code=409,
                details={
                    "analysis_run_id": run.id,
                    "expected_basis_sha256": context.calculation_basis.get("basis_sha256"),
                    "accepted_basis_sha256": (
                        canonical_json_sha256(accepted)
                        if isinstance(accepted, dict)
                        else None
                    ),
                    "executed_basis_sha256": (
                        canonical_json_sha256(executed)
                        if isinstance(executed, dict)
                        else None
                    ),
                },
            )
        # The counted emission set is a reviewed decision, so the solve has to record the one this
        # request derived: a receipt that quietly dropped it would freeze an answer whose counted
        # exchanges no reader could name.
        expected_selection = flow_selection_of(context.calculation_model)
        recorded_selection = stamp.get("flow_selection") if isinstance(stamp, dict) else None
        if recorded_selection != expected_selection:
            raise DomainError(
                code="PROVIDER_SOLVE_DERIVATION_MISMATCH",
                message="求解回执记录的排放选择与本次核算口径派生出的选择不一致，不能冻结结果。",
                status_code=409,
                details={
                    "analysis_run_id": run.id,
                    "expected_flow_selection": expected_selection,
                    "recorded_flow_selection": recorded_selection,
                },
            )

    @staticmethod
    def _freeze_calculation_basis(
        context: ProviderSolveContext,
        payload: ProviderSolveAndFreezeCreate,
        derived: DerivedCalculationModel | None,
        has_mapped_receipts: bool,
    ) -> dict[str, Any]:
        def by_consumer(pins) -> list[dict[str, Any]]:
            return sorted(
                (pin.model_dump(mode="json") for pin in pins),
                key=lambda pin: pin["consumer_exchange_id"],
            )

        requested: dict[str, Any] = {
            "schema_version": "nebula_one.provider-calculation-basis.v1",
            "demand": [d.model_dump(mode='json', exclude_none=True) for d in payload.demand],
            "lcia_methods": context.analysis_request.parameters.get("lcia_methods"),
            "background_process_pins": by_consumer(payload.background_process_pins),
        }
        calculation_method = context.analysis_request.parameters.get("calculation_method")
        if calculation_method is not None:
            requested["calculation_method"] = calculation_method
        if payload.project_background_pins:
            requested["project_background_pins"] = by_consumer(payload.project_background_pins)
        if has_mapped_receipts:
            requested["mapped_background_process_pins"] = by_consumer(
                payload.mapped_background_process_pins
            )
        if derived is None:
            return requested
        basis = context.calculation_basis or {}
        # The answer describes what was solved, so the derived demand and the effective associations
        # replace the request; the request and the source model stay alongside it as traceability
        # rather than as inputs this answer was calculated from.
        frozen = {
            **requested,
            "purpose": derived.purpose,
            "demand": derived.demand,
            "lcia_methods": basis.get("lcia_methods"),
            "background_process_pins": list(basis.get("effective_background_process_pins") or []),
            "mapped_background_process_pins": list(
                basis.get("effective_mapped_background_process_pins") or []
            ),
            "model_derivation": basis,
            "source_model": {
                "graph_sha256": derived.source_graph_sha256,
                "demand": requested["demand"],
                "background_process_pins": requested["background_process_pins"],
                "mapped_background_process_pins": by_consumer(
                    payload.mapped_background_process_pins
                ),
            },
        }
        if payload.project_background_pins:
            frozen["project_background_pins"] = list(basis.get("effective_project_background_pins") or [])
            frozen["source_model"]["project_background_pins"] = requested["project_background_pins"]
        return frozen

    def submit_solve_and_freeze(
        self,
        application_id: str,
        system_revision_id: str,
        payload: ProviderSolveAndFreezeCreate,
    ) -> tuple[AnalysisRun, OutboxEvent, bool]:
        context = self._prepare(application_id, system_revision_id, payload)
        return self.analysis_runs.submit(
            context.system_model_id,
            context.analysis_request,
            outbox_topic=SOLVE_AND_FREEZE_TOPIC,
        )

    def handle_outbox(self, payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) != {"run_id"} or not isinstance(payload.get("run_id"), str):
            raise DomainError(
                code="SOLVE_FREEZE_OUTBOX_PAYLOAD_INVALID",
                message="solve-and-freeze outbox payload must contain only run_id",
                status_code=422,
            )
        run = self.analysis_runs.execute_queued(payload["run_id"])
        with self.database.session() as db:
            system_model = db.get(SystemModel, run.system_model_id)
            if system_model is None or run.system_revision_id is None:
                raise DomainError(
                    code="SOLVE_FREEZE_RUN_CONTEXT_INVALID",
                    message="solve-and-freeze run lacks its application or revision context",
                    status_code=409,
                    details={"run_id": run.id},
                )
            application_id = system_model.application_id
            system_revision_id = run.system_revision_id
        try:
            native_run = run.parameters.get("native_background_climate") is not None
            inventory_run = run.parameters.get("native_background_inventory") is not None
            solve_payload = ProviderSolveAndFreezeCreate(
                demand=run.parameters.get("demand"),
                idempotency_key=run.idempotency_key,
                scenario_id=run.parameters.get("scenario_id"),
                # A native run's method selection is the contract's and _prepare re-derives it, so
                # the persisted copy stays evidence rather than a choice this rebuilt request may
                # re-make; passing it back would fail the scope guard of a run that was accepted.
                lcia_methods=None if native_run or run.parameters.get("climate_default") else run.parameters.get("lcia_methods"),
                background_process_pins=run.parameters.get(
                    "background_process_pins", []
                ),
                mapped_background_process_pins=run.parameters.get('mapped_background_process_pins', []),
                native_background_climate=native_run and not run.parameters.get("climate_default"),
                native_background_inventory=inventory_run,
                climate_default=bool(run.parameters.get("climate_default")),
                # The purpose is part of the accepted request, so recovery re-derives under the same
                # accounting scope instead of falling back to the whole stored model.
                calculation_purpose=run.parameters.get("calculation_purpose"),
                analysis_task=run.parameters.get("analysis_task"),
            )
        except ValidationError as exc:
            raise DomainError(
                code="SOLVE_FREEZE_RUN_CONTEXT_INVALID",
                message="persisted solve-and-freeze parameters are invalid",
                status_code=409,
                details={
                    "run_id": run.id,
                    # A validator's own context object is not JSON, and this detail is written to
                    # the failed task's persisted record, so keep the loc and message only.
                    "errors": [
                        {
                            "loc": list(error.get("loc") or []),
                            "type": error.get("type"),
                            "message": error.get("msg"),
                        }
                        for error in exc.errors(include_url=False)
                    ],
                },
            ) from exc
        snapshot = self.solve_and_freeze(
            application_id,
            system_revision_id,
            solve_payload,
            outbox_topic=SOLVE_AND_FREEZE_TOPIC,
            accepted_basis=run.parameters.get("calculation_basis"),
            accepted_climate_method=run.parameters.get("calculation_method"),
        )
        return {
            "resource_type": "SolvedSystemSnapshot",
            "id": snapshot.id,
            "content_sha256": snapshot.content_sha256,
        }

    def solve_and_freeze(
        self,
        application_id: str,
        system_revision_id: str,
        payload: ProviderSolveAndFreezeCreate,
        *,
        outbox_topic: str = ANALYSIS_EXECUTE_TOPIC,
        accepted_basis: dict[str, Any] | None = None,
        accepted_climate_method: dict[str, Any] | None = None,
    ):
        context = self._prepare(
            application_id,
            system_revision_id,
            payload,
            accepted_basis=accepted_basis,
            accepted_climate_method=accepted_climate_method,
        )
        try:
            run = self.analysis_runs.run(
                context.system_model_id,
                context.analysis_request,
                outbox_topic=outbox_topic,
            )
        except DomainError as exc:
            raise unverified_background_mapping(exc) from exc
        revision_hash = context.revision_hash
        functional_unit = context.functional_unit
        scenario_hash = context.scenario_hash
        derived = context.calculation_model
        # Everything below is checked against what was actually solved: for a purpose-derived
        # calculation model that is the derived graph and its effective associations, not the
        # stored model and the caller's request.
        sent_graph = context.graph_snapshot if derived is None else derived.graph
        sent_background_pins = (
            payload.background_process_pins
            if derived is None
            else [
                ProviderBackgroundProcessPin.model_validate(item)
                for item in derived.background_process_pins
            ]
        )
        sent_mapped_pins = (
            payload.mapped_background_process_pins
            if derived is None
            else [
                ProviderMappedBackgroundProcessPin.model_validate(item)
                for item in derived.mapped_background_process_pins
            ]
        )
        sent_project_pins = (
            payload.project_background_pins if derived is None else
            [ProviderProjectBackgroundPin.model_validate(item) for item in derived.project_background_pins]
        )
        self._verify_derivation_stamp(run, context)
        result = run.result or {}
        provenance = result.get("provenance")
        if not isinstance(provenance, dict):
            raise DomainError(
                code="PROVIDER_SOLVE_RESULT_INVALID",
                message="provider solve result has no provenance object",
                status_code=502,
                details={"analysis_run_id": run.id},
            )
        database_release = _required_text(
            provenance, "database_release", context="provenance"
        )
        solver_version = str(
            provenance.get("solver_version") or provenance.get("solver") or ""
        ).strip()
        if not solver_version:
            raise DomainError(
                code="PROVIDER_SOLVE_RESULT_INVALID",
                message="provider solve provenance has no solver version",
                status_code=502,
                details={"analysis_run_id": run.id},
            )

        raw_activities = result.get("activity_vector")
        raw_exchanges = result.get("scaled_exchanges")
        if not isinstance(raw_activities, list) or not isinstance(raw_exchanges, list):
            raise DomainError(
                code="PROVIDER_SOLVE_RESULT_INVALID",
                message="provider solve result lacks solved activity or exchange collections",
                status_code=502,
                details={"analysis_run_id": run.id},
            )
        activities = [
            _map_activity(item, index)
            for index, item in enumerate(raw_activities)
            if isinstance(item, dict)
        ]
        exchanges = [
            (_map_exchange(item, index), item)
            for index, item in enumerate(raw_exchanges)
            if isinstance(item, dict)
        ]
        technosphere_receipts = _validated_technosphere_receipts(
            result,
            sent_graph,
            analysis_run_id=run.id,
        )
        background_process_receipts = _validated_background_process_receipts(
            result,
            sent_background_pins,
            sent_graph,
            analysis_run_id=run.id,
        )
        mapped_receipts = validate_mapped_receipts(result, sent_mapped_pins, sent_graph)
        project_receipts = _validated_project_background_receipts(result, sent_project_pins)
        technosphere = [
            mapped for mapped, raw in exchanges if raw.get("exchange_type") == "technosphere"
        ]
        elementary = [
            mapped for mapped, raw in exchanges if raw.get("exchange_type") == "elementary"
        ]
        internal = [
            mapped for mapped, raw in exchanges if raw.get("boundary_role") == "internal"
        ]
        boundary = [
            mapped for mapped, raw in exchanges if raw.get("boundary_role") == "boundary"
        ]
        contribution_graph = {
            "provider_graph": result.get("contribution_graph") or {},
            "inventory_totals": result.get("inventory_totals") or [],
            "elementary_flow_receipts": result.get("elementary_flow_receipts") or [],
            "technosphere_flow_receipts": technosphere_receipts,
            "background_process_receipts": background_process_receipts,
            "project_background_process_receipts": project_receipts,
            "issues": result.get("issues") or [],
            "provenance": provenance,
            "analysis_run_id": run.id,
        }
        provider_receipt = {
            "endpoint": "/api/provider/v1/solve",
            "status": result.get("status"),
            "upstream_run_id": result.get("run_id"),
            "system_revision_hash": revision_hash,
            "inventory_snapshot_hash": None,
            "parameter_set_hash": None,
            "database_release": database_release,
            "solver_version": solver_version,
            "snapshot_ref": result.get("snapshot_ref"),
            "analysis_run_id": run.id,
            "scenario_id": payload.scenario_id,
            "scenario_hash": scenario_hash,
            "provenance": provenance,
            "elementary_flow_receipts": result.get("elementary_flow_receipts") or [],
            "technosphere_flow_receipts": technosphere_receipts,
            "background_process_receipts": background_process_receipts,
            "project_background_process_receipts": project_receipts,
            "calculation_basis": self._freeze_calculation_basis(
                context, payload, derived, bool(mapped_receipts)
            ),
        }
        if payload.analysis_task is not None:
            provider_receipt["analysis_task"] = payload.analysis_task
        if mapped_receipts:
            contribution_graph['mapped_background_process_receipts'] = mapped_receipts
            provider_receipt['mapped_background_process_receipts'] = mapped_receipts
        native_answer = result.get("native_background_climate")
        inventory_answer = result.get("native_background_inventory")
        if context.native_background_inventory is not None:
            if (not isinstance(inventory_answer, dict)
                    or inventory_answer.get("schema_version") != "provider.native-background-inventory.response.v1"
                    or inventory_answer.get("inventory_runtime_manifest_sha256")
                    != context.native_background_inventory["inventory_runtime_manifest_sha256"]
                    or result.get("lcia") is not None
                    or native_answer is not None):
                raise DomainError(code="PROVIDER_SOLVE_RESULT_INVALID",
                                  message="native inventory solve returned a mismatched identity or an LCIA answer",
                                  status_code=502, details={"analysis_run_id": run.id})
            provider_receipt["calculation_basis"]["native_background_inventory"] = context.native_background_inventory
            provider_receipt["native_background_inventory"] = inventory_answer
        native_envelope = None
        if context.native_background_climate is not None:
            if not isinstance(native_answer, dict):
                raise DomainError(
                    code="PROVIDER_SOLVE_RESULT_INVALID",
                    message="a native background climate solve returned no climate answer to freeze",
                    status_code=502,
                    details={
                        "analysis_run_id": run.id,
                        "field": "native_background_climate",
                    },
                )
            # The pin belongs to the solve basis so a mode or method change can never reuse the
            # projection-path snapshot of the same revision.
            provider_receipt["calculation_basis"]["native_background_climate"] = (
                context.native_background_climate
            )
            native_envelope = {
                "schema_version": "nebula_one.native-background-climate.v1",
                "source_contract": self.native_climate.source_contract,
                "request": context.native_background_climate,
                "response": native_answer,
            }
        snapshot = SolvedSystemSnapshotCreate(
            system_revision_id=system_revision_id,
            inventory_snapshot_id=None,
            parameter_set_id=None,
            provider="nebula_lca",
            provider_receipt=provider_receipt,
            functional_unit=functional_unit,
            database_release=database_release,
            solver_version=solver_version,
            activity_vector=activities,
            scaled_technosphere_exchanges=technosphere,
            scaled_elementary_exchanges=elementary,
            internal_transfers=internal,
            boundary_flows=boundary,
            process_balance_residuals=result.get("process_residuals") or [],
            contribution_graph=contribution_graph,
            lcia_results=result.get("lcia") or {},
            native_background_climate=native_envelope,
        )
        return self.results.import_solved_snapshot(application_id, snapshot)

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..analysis.method_grouping import path_rows_to_weighted_terms
from ..analysis.tag_grouping import (
    CALIBER_SEMANTICS,
    consumer_path_exchanges,
    group_tag_schemes,
    tag_dimension,
)
from ..database import Database
from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..runtime_models import CalculationMethod, CalculationMethodVersion, SolvedSystemSnapshot, TagGroupingResult
from ..models import SystemRevision
from ..runtime_schemas import TagGroupingOut, TagGroupingRequest, TagSchemeRef
from .calculation_methods import version_content_sha256
from .runtime_support import require_application
from .template_accounting_methods import model_ports
from .calculation_methods import contribution_port_ids


def frozen_tag_pool(snapshot, indicator_key: str):
    """Use exact provider receipts; keep known subtotals and missing paths independently."""
    lcia = snapshot.lcia_results or {}
    path_matches = [r for r in lcia.get("path_weighted_contribution_receipts", [])
                    if r.get("canonical_indicator_key") == indicator_key]
    flat_matches = [r for r in lcia.get("indicator_contribution_receipts", [])
                    if r.get("canonical_indicator_key") == indicator_key]
    if len(path_matches) > 1 or len(flat_matches) > 1:
        raise DomainError(code="TAG_RECEIPT_AMBIGUOUS", message="multiple receipts name this indicator", status_code=409)
    path = path_matches[0] if path_matches else None
    flat = flat_matches[0] if flat_matches else None
    receipt = path or flat
    if receipt is None:
        return None
    for item in [r for r in (path, flat) if r is not None]:
        basis = {key: value for key, value in item.items() if key != "content_hash"}
        if item.get("content_hash") != canonical_json_sha256(basis):
            raise DomainError(code="TAG_RECEIPT_HASH_MISMATCH", message="frozen contribution receipt hash is invalid", status_code=409)
    if flat is not None and lcia.get("contribution_receipts_hash") != canonical_json_sha256(lcia["indicator_contribution_receipts"]):
        raise DomainError(code="TAG_RECEIPT_HASH_MISMATCH", message="frozen contribution collection hash is invalid", status_code=409)
    if path and flat and path.get("indicator_unit") != flat.get("indicator_unit"):
        raise DomainError(code="TAG_RECEIPT_UNIT_MISMATCH", message="contribution receipts disagree on unit", status_code=409)
    invalid_path_ids: set[str] = set()
    known_path_rows = []
    for row in (path or {}).get("terms", []):
        try:
            finite = math.isfinite(float(row.get("path_contribution_value")))
        except (TypeError, ValueError):
            finite = False
        if finite:
            known_path_rows.append(row)
        else:
            key = row.get("consumer_exchange_id") if row.get("attribution_basis") == "background_consumer_path" else row.get("exchange_id")
            if key:
                invalid_path_ids.add(str(key))
    terms = path_rows_to_weighted_terms({"terms": known_path_rows}) if path is not None else [
        {"exchange_id": term["exchange_id"], "contribution_value": term["contribution_value"]}
        for term in flat.get("terms", [])]
    consumers = consumer_path_exchanges(path)
    represented = {str(row.get("exchange_id")) for row in (path or flat).get("terms", [])}
    missing = {str(row["exchange_id"]) for row in snapshot.scaled_elementary_exchanges
               if row.get("exchange_id") and row["exchange_id"] not in represented}
    missing.update(invalid_path_ids)
    # Missing elementary paths from an expanded provider inherit only the consumer attribution
    # explicitly recorded for that exact provider instance, never a global flow or supplier UUID.
    consumers_by_process: dict[str, set[str]] = {}
    for term in (path or {}).get("terms", []):
        if term.get("attribution_basis") == "background_consumer_path" and term.get("consumer_exchange_id"):
            consumers_by_process.setdefault(str(term.get("process_uuid")), set()).add(term["consumer_exchange_id"])
    for gap in (flat or {}).get("characterization_coverage", {}).get("uncharacterized_exchanges", []):
        mapped = consumers_by_process.get(str(gap.get("process_uuid")))
        if mapped:
            missing.discard(gap["exchange_id"])
            missing.update(mapped)
        else:
            missing.add(gap["exchange_id"])
    return terms, consumers, missing, str(receipt.get("indicator_unit") or "")


class TagGroupingService:
    """Re-bucket one frozen solve by exact tag-scheme versions, without re-solving.

    The snapshot already carries every contribution the engine characterized, so a tag view is a
    pure read over that frozen pool: no factor is computed and no model is rescaling. Each scheme
    is cited by ``method_id`` + version + content hash, verified against the stored version, and
    bound to the same model revision the solve used, so a renamed method or a newer version never
    quietly answers for the one the caller pinned.
    """

    def __init__(self, database: Database) -> None:
        self.database = database

    def group_for_snapshot(self, application_id: str, payload: TagGroupingRequest) -> dict:
        with self.database.session() as db:
            require_application(db, application_id)
            snapshot = db.get(SolvedSystemSnapshot, payload.snapshot_id)
            if snapshot is None or snapshot.application_id != application_id:
                raise DomainError(
                    code="TAG_GROUPING_SNAPSHOT_NOT_FOUND",
                    message=f"solved system snapshot not found: {payload.snapshot_id}",
                    status_code=404,
                )
            seen: set[str] = set()
            schemes: list[dict[str, Any]] = []
            for ref in payload.schemes:
                if ref.method_id in seen:
                    raise DomainError(
                        code="TAG_GROUPING_DUPLICATE_SCHEME",
                        message="a tag grouping cites each scheme at most once",
                        status_code=422,
                        details={"method_id": ref.method_id},
                    )
                seen.add(ref.method_id)
                schemes.append(self._load_scheme(db, application_id, snapshot, ref))
            semantics_values = sorted({str(item["semantics"]) for item in schemes})

            request_hash = canonical_json_sha256(payload.model_dump())
            previous = db.scalar(select(TagGroupingResult).where(
                TagGroupingResult.application_id == application_id,
                TagGroupingResult.request_sha256 == request_hash,
            ))
            if previous is not None:
                return self._result(previous)

            envelope: dict[str, Any] = {
                "application_id": application_id,
                "snapshot_id": snapshot.id,
                "snapshot_content_sha256": snapshot.content_sha256,
                "indicator_key": payload.indicator_key,
                "indicator_unit": None,
                "mode": payload.mode,
                "semantics": semantics_values[0] if len(semantics_values) == 1 else "mixed",
                "available": False,
                "reason": None,
                "schemes": [],
                "union": None,
                "intersection": None,
                "overlap": {},
                "reconciled": False,
                "problems": [],
            }
            pool = frozen_tag_pool(snapshot, payload.indicator_key)
            if pool is None:
                # No frozen provider contribution view exists to group.
                envelope["reason"] = "PATH_WEIGHTED_RECEIPT_MISSING"
                envelope["content_sha256"] = canonical_json_sha256(envelope)
                return envelope

            weighted_terms, consumers, missing, indicator_unit = pool
            revision = db.get(SystemRevision, snapshot.system_revision_id)
            if revision is not None:
                declared = contribution_port_ids(revision.graph_snapshot)
                existing = {row["exchange_id"] for row in snapshot.scaled_elementary_exchanges} | {row["exchange_id"] for row in consumers}
                for port in model_ports(revision.graph_snapshot):
                    if port["exchange_id"] in declared and port["exchange_id"] not in existing:
                        consumers.append({"exchange_id": port["exchange_id"], "process_id": port["process_id"],
                                          "direction": port["direction"], "exchange_type": "technosphere"})
                        missing.add(port["exchange_id"])
            grouped = group_tag_schemes(
                schemes=schemes,
                scaled_exchanges=snapshot.scaled_elementary_exchanges,
                weighted_terms=weighted_terms,
                indicator_unit=indicator_unit,
                mode=payload.mode,
                consumer_paths=consumers,
                missing_exchange_ids=missing,
            )
            envelope.update(
                indicator_unit=indicator_unit or None,
                available=True,
                schemes=grouped["schemes"],
                union=grouped["union"],
                intersection=grouped["intersection"],
                overlap=grouped["overlap"],
                reconciled=grouped["reconciled"],
                problems=grouped["problems"],
            )
            envelope["content_sha256"] = canonical_json_sha256(envelope)
            # Freeze the public response shape: exports and historical reads use these exact bytes,
            # never current scheme names or classification definitions.
            public = TagGroupingOut.model_validate(envelope).model_dump(mode="json", exclude={"result_id", "created_at", "content_sha256"})
            public["content_sha256"] = canonical_json_sha256(public)
            saved = TagGroupingResult(application_id=application_id, snapshot_id=snapshot.id,
                                      request_sha256=request_hash, result=public,
                                      content_sha256=public["content_sha256"])
            db.add(saved)
            try:
                db.commit()
                db.refresh(saved)
            except IntegrityError:
                db.rollback()
                saved = db.scalar(select(TagGroupingResult).where(
                    TagGroupingResult.application_id == application_id,
                    TagGroupingResult.request_sha256 == request_hash,
                ))
                if saved is None:
                    raise
            return self._result(saved)

    @staticmethod
    def _result(record: TagGroupingResult) -> dict:
        result = dict(record.result)
        stored_hash = result.pop("content_sha256", None)
        if stored_hash != record.content_sha256 or canonical_json_sha256(result) != stored_hash:
            raise DomainError(code="TAG_GROUPING_RESULT_HASH_MISMATCH", message="frozen tag result content has changed", status_code=409)
        return {**record.result, "result_id": record.id, "created_at": record.created_at}

    def read_result(self, application_id: str, result_id: str) -> dict:
        with self.database.session() as db:
            require_application(db, application_id)
            record = db.get(TagGroupingResult, result_id)
            if record is None or record.application_id != application_id:
                raise DomainError(code="TAG_GROUPING_RESULT_NOT_FOUND", message="tag result not found", status_code=404)
            return self._result(record)

    def list_results(self, application_id: str, snapshot_id: str | None = None) -> list[dict]:
        with self.database.session() as db:
            require_application(db, application_id)
            query = select(TagGroupingResult).where(TagGroupingResult.application_id == application_id)
            if snapshot_id is not None:
                query = query.where(TagGroupingResult.snapshot_id == snapshot_id)
            return [self._result(row) for row in db.scalars(query.order_by(TagGroupingResult.created_at.desc()).limit(100))]

    def _load_scheme(
        self,
        db: Any,
        application_id: str,
        snapshot: SolvedSystemSnapshot,
        ref: TagSchemeRef,
    ) -> dict[str, Any]:
        method = db.get(CalculationMethod, ref.method_id)
        if method is None:
            raise DomainError(
                code="CALCULATION_METHOD_NOT_FOUND",
                message=f"calculation method not found: {ref.method_id}",
                status_code=404,
            )
        if method.status == "retired":
            raise DomainError(
                code="TAG_SCHEME_ARCHIVED",
                message="this tag scheme is archived and no longer groups new results",
                status_code=409,
                details={"method_id": method.id},
            )
        if method.application_id != application_id:
            raise DomainError(
                code="TAG_SCHEME_APPLICATION_MISMATCH",
                message="tag scheme does not belong to the requested application",
                status_code=409,
                details={"method_id": method.id},
            )
        if method.model_revision_id != snapshot.system_revision_id:
            raise DomainError(
                code="TAG_SCHEME_REVISION_MISMATCH",
                message="tag scheme is bound to a different model revision than the snapshot",
                status_code=409,
                details={
                    "method_id": method.id,
                    "method_model_revision_id": method.model_revision_id,
                    "snapshot_system_revision_id": snapshot.system_revision_id,
                },
            )
        version = db.scalar(
            select(CalculationMethodVersion).where(
                CalculationMethodVersion.method_id == ref.method_id,
                CalculationMethodVersion.version == ref.version,
            )
        )
        if version is None:
            raise DomainError(
                code="CALCULATION_METHOD_VERSION_NOT_FOUND",
                message=f"calculation method version not found: {ref.method_id}@{ref.version}",
                status_code=404,
            )
        if version.semantics not in CALIBER_SEMANTICS:
            raise DomainError(
                code="TAG_SCHEME_SEMANTICS_MISMATCH",
                message="the cited version is neither a flow-tag nor a result-category caliber",
                status_code=409,
                details={"method_id": method.id, "version": version.version},
            )
        if version.content_sha256 != ref.content_sha256:
            raise DomainError(
                code="TAG_SCHEME_HASH_MISMATCH",
                message="the cited tag scheme content hash does not match the stored version",
                status_code=409,
                details={"method_id": method.id, "version": version.version},
            )
        if version.content_sha256 != version_content_sha256(
            method.purpose, version.cbam_boundary_ref, version.rules,
            version.reporting_dimensions, version.model_processing_rules_ref, version.semantics,
        ):
            raise DomainError(code="TAG_SCHEME_CONTENT_CORRUPT", message="stored tag scheme content differs from its frozen hash", status_code=409)
        if version.status != "ready":
            raise DomainError(
                code="TAG_SCHEME_NOT_VALIDATED",
                message="a tag scheme must be validated before it can group a result",
                status_code=409,
                details={"method_id": method.id, "version": version.version},
            )
        dimension = tag_dimension({"reporting_dimensions": version.reporting_dimensions})
        if dimension is None:
            raise DomainError(
                code="TAG_SCHEME_DIMENSION_INVALID",
                message="the cited version does not declare exactly one category tree",
                status_code=409,
                details={"method_id": method.id, "version": version.version},
            )
        return {
            "scheme": {
                "method_id": method.id,
                "version": version.version,
                "content_sha256": version.content_sha256,
                "name": method.name,
                "purpose": method.purpose,
                "model_revision_id": method.model_revision_id,
            },
            "rules": list(version.rules or []),
            "dimension": dimension,
            "semantics": version.semantics,
        }

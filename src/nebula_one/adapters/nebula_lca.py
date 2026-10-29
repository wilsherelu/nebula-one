from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass
from typing import Any, NoReturn
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from ..errors import UpstreamError
from ..hashing import canonical_json_sha256, graph_identity_sha256
from ..mapped_background_schemas import (
    ProviderNativeBackgroundClimateRequest,
    ProviderNativeBackgroundClimateResponse,
)

# the English display name Nebula LCA echoes onto a port or exchange is a column of its shared
# flow table, not a field of the model version: a later import of any bundle that references the
# flow rewrites what an already created version reads back.
FLOW_DISPLAY_NAME_FIELD = "flow_name_en"

_NATIVE_CLIMATE_IDENTITY_FIELDS = (
    "method_package_id",
    "method_package_version",
    "method_package_sha256",
    "runtime_manifest_sha256",
)


def native_climate_identity_mismatches(
    pin: ProviderNativeBackgroundClimateRequest,
    answer: ProviderNativeBackgroundClimateResponse,
) -> dict[str, dict[str, Any]]:
    """The fields a climate answer must echo back exactly, or the solve was not the pinned one."""
    return {
        field: {"expected": getattr(pin, field), "actual": getattr(answer, field)}
        for field in _NATIVE_CLIMATE_IDENTITY_FIELDS
        if getattr(pin, field) != getattr(answer, field)
    }


def _reject_native_climate(reason: str, **details: Any) -> NoReturn:
    raise UpstreamError(
        code="NEBULA_LCA_NATIVE_CLIMATE_CONTRACT_INVALID",
        message="Nebula LCA did not return the pinned native background climate answer",
        status_code=502,
        details={"reason": reason, **details},
    )


def validate_native_climate_answer(
    request_payload: dict[str, Any], payload: dict[str, Any], *, path: str
) -> None:
    """Accept only the climate answer the pinned request actually asked for.

    The opt-in mode reports a unified total only when the source merged both domains, and its
    method and runtime identity have to be the exact pins the request carried. A silent mode switch,
    a re-labelled package, a total on a split diagnostic, or an answer for a solve that never asked
    for one would otherwise be frozen as though it were citable.
    """
    requested = request_payload.get("native_background_climate")
    answer = payload.get("native_background_climate")
    if requested is None:
        if answer is not None:
            _reject_native_climate("unexpected_answer", path=path)
        return
    try:
        pin = ProviderNativeBackgroundClimateRequest.model_validate(requested)
    except ValidationError as exc:
        _reject_native_climate(
            "request_pin_invalid", path=path,
            errors=exc.errors(include_url=False, include_context=False, include_input=False),
        )
    if not isinstance(answer, dict):
        _reject_native_climate("missing_answer", path=path)
    try:
        native = ProviderNativeBackgroundClimateResponse.model_validate(answer)
    except ValidationError as exc:
        _reject_native_climate(
            "answer_shape_invalid", path=path,
            errors=exc.errors(include_url=False, include_context=False, include_input=False),
        )
    mismatches = native_climate_identity_mismatches(pin, native)
    if mismatches:
        _reject_native_climate(
            "answer_identity_differs_from_request_pin", path=path, mismatches=mismatches
        )
    raw_provenance = payload.get("provenance")
    provenance = raw_provenance if isinstance(raw_provenance, dict) else {}
    pinned_provenance = {
        "native_climate_method_package_sha256": pin.method_package_sha256,
        "native_climate_runtime_manifest_sha256": pin.runtime_manifest_sha256,
    }
    provenance_mismatches = {
        field: {"expected": expected, "actual": provenance.get(field)}
        for field, expected in pinned_provenance.items()
        if provenance.get(field) != expected
    }
    if provenance_mismatches:
        _reject_native_climate(
            "provenance_identity_differs_from_request_pin",
            path=path,
            mismatches=provenance_mismatches,
        )


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    payload: dict[str, Any]
    etag: str | None = None


def without_flow_display_names(graph: dict[str, Any]) -> dict[str, Any]:
    """Return one engine graph answer with the field the engine can rewrite later neutralised.

    Nebula LCA answers the same immutable model version through two endpoints whose serializations
    differ only by ``flow_name_en``, and its own flow-name sync fills that field after the version
    was created, so the raw answer is not a stable identity for a pinned model. Measured on the
    isolated 8004 engine with the ammonia seed 1.1.0 (2026-09-21): a second boot moved four
    ports and one exchange from null to a name, which shifted the canonical graph hash from
    ``f55a4513…`` to ``b633f50e…`` and made a resumed install refuse its own frozen boundary and
    an already imported project refuse the model-source connect. Stripping the field here is what
    makes both read shapes, and every later re-read, hash to one value.
    """
    stripped = copy.deepcopy(graph)
    for node in stripped.get("nodes") or []:
        for group in ("inputs", "outputs"):
            for port in node.get(group) or []:
                if isinstance(port, dict):
                    port.pop(FLOW_DISPLAY_NAME_FIELD, None)
    for exchange in stripped.get("exchanges") or []:
        if isinstance(exchange, dict):
            exchange.pop(FLOW_DISPLAY_NAME_FIELD, None)
    return stripped


def same_pinned_model(stored_graph: dict[str, Any], returned_graph: dict[str, Any]) -> bool:
    """True when a snapshot One already holds and a fresh engine answer describe one model.

    Comparing digests of the two answers directly would call a rewritten flow display name a mutated
    model version: Nebula LCA overwrites the display labels of a version it has already stored, from
    its own flow catalogue, long after that version was pinned. This compares the two graphs with
    exactly those labels removed, so every amount, unit, port, edge, flow identity and functional
    unit still has to agree while a relabelling cannot break a saved result.
    """
    return graph_identity_sha256(stored_graph) == graph_identity_sha256(returned_graph)


class NebulaLCAClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        normalized = base_url.strip().rstrip("/")
        if not normalized:
            raise ValueError("Nebula LCA base URL cannot be blank")
        self.base_url = normalized
        self.timeout_seconds = timeout_seconds
        if transport is None and normalized == "http://nebula-lca.desktop.invalid":
            import os
            from ..desktop_transport import DesktopEngineTransport
            transport = DesktopEngineTransport(os.environ.get("NEBULA_ONE_DESKTOP_ENGINE_ENDPOINT", ""))
        self._client = httpx.Client(
            base_url=normalized,
            timeout=timeout_seconds,
            transport=transport,
            trust_env=False,
            headers={"Accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise UpstreamError(
                code="NEBULA_LCA_TIMEOUT",
                message="Nebula LCA request timed out",
                status_code=504,
                details={"method": method, "path": path},
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamError(
                code="NEBULA_LCA_UNREACHABLE",
                message="Nebula LCA is unreachable",
                status_code=503,
                details={"method": method, "path": path, "reason": str(exc)},
            ) from exc
        if response.is_success:
            return response
        upstream_detail: Any = None
        try:
            body = response.json()
            upstream_detail = body.get("detail", body) if isinstance(body, dict) else body
        except ValueError:
            upstream_detail = response.text[:1000]
        message = f"Nebula LCA returned HTTP {response.status_code}"
        if isinstance(upstream_detail, dict):
            reason = upstream_detail.get('message')
            reason_code = upstream_detail.get('code')
            if isinstance(reason, str) and reason.strip():
                message = reason.strip()
                if isinstance(reason_code, str) and reason_code.strip():
                    message = f"{reason_code.strip()}: {message}"
        raise UpstreamError(
            code="NEBULA_LCA_REJECTED",
            message=message,
            status_code=502 if response.status_code >= 500 else 422,
            details={
                "method": method,
                "path": path,
                "upstream_status": response.status_code,
                "upstream_detail": upstream_detail,
            },
        )

    @staticmethod
    def _json_object(response: httpx.Response, *, path: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamError(
                code="NEBULA_LCA_INVALID_RESPONSE",
                message="Nebula LCA returned non-JSON content",
                status_code=502,
                details={"path": path},
            ) from exc
        if not isinstance(payload, dict):
            raise UpstreamError(
                code="NEBULA_LCA_INVALID_RESPONSE",
                message="Nebula LCA returned a non-object response",
                status_code=502,
                details={"path": path},
            )
        return payload

    def probe(self) -> dict[str, Any]:
        health_response = self._request("GET", "/api/health")
        health = self._json_object(health_response, path="/api/health")
        openapi_response = self._request("GET", "/openapi.json")
        openapi = self._json_object(openapi_response, path="/openapi.json")
        paths = openapi.get("paths") if isinstance(openapi.get("paths"), dict) else {}
        return {
            "provider": "nebula_lca",
            "base_url": self.base_url,
            "status": "ready" if health.get("status") == "ok" else "degraded",
            "contracts": {
                "exact_model_version": "/api/projects/{project_id}/versions/{version}" in paths,
                "lcia_run": "/api/model/run" in paths,
                "provider_model_snapshot": (
                    "/api/provider/v1/models/{project_id}/versions/{version}/snapshot"
                    in paths
                ),
                "provider_solve": "/api/provider/v1/solve" in paths,
                "provider_catalog_resolve": (
                    "/api/provider/v1/catalog/resolve" in paths
                ),
                "tidas_bundle_import": "/api/import/tidas/bundle" in paths,
                "native_bundle_restore": "/api/native-project-bundles/import" in paths,
                "native_bundle_export": (
                    "/api/native-project-bundles/projects/{project_id}" in paths
                ),
            },
        }

    def engine_identity(self) -> dict[str, str]:
        health = self._json_object(
            self._request("GET", "/api/health"), path="/api/health"
        )
        database = health.get("database")
        if not isinstance(database, str) or not database.strip():
            raise UpstreamError(
                code="NEBULA_LCA_HEALTH_DATABASE_MISSING",
                message="Nebula LCA health does not report its own database identity",
                status_code=502,
                details={"path": "/api/health"},
            )
        openapi = self._json_object(
            self._request("GET", "/openapi.json"), path="/openapi.json"
        )
        info = openapi.get("info") if isinstance(openapi.get("info"), dict) else {}
        version = info.get("version")
        if not isinstance(version, str) or not version.strip():
            raise UpstreamError(
                code="NEBULA_LCA_OPENAPI_VERSION_MISSING",
                message="Nebula LCA does not declare an OpenAPI version",
                status_code=502,
                details={"path": "/openapi.json"},
            )
        return {"database": database, "openapi_version": version}

    def get_reference_flow(self, flow_uuid: str) -> dict[str, Any]:
        path = f"/api/reference/flows/{flow_uuid}"
        payload = self._json_object(self._request("GET", path), path=path)
        self._require_fields(
            payload,
            path=path,
            fields=(
                "flow_uuid",
                "flow_name_en",
                "flow_type",
                "default_unit",
                "unit_group",
            ),
        )
        if str(payload["flow_uuid"]) != flow_uuid:
            raise UpstreamError(
                code="NEBULA_LCA_FLOW_IDENTITY_MISMATCH",
                message="Nebula LCA returned a catalog row for a different flow identity",
                status_code=502,
                details={
                    "requested": flow_uuid,
                    "returned": payload.get("flow_uuid"),
                },
            )
        return payload

    def get_flow_version(self, namespace: str, flow_uuid: str, version: str) -> dict[str, Any]:
        path = f"/api/flow-versions/{namespace}/{flow_uuid}/{version}"
        return self._json_object(self._request("GET", path), path=path)

    def import_tidas_flows(self, *, filename: str, payload: bytes, dry_run: bool) -> ProviderResponse:
        path = "/api/import/tidas/flows"
        response = self._request(
            "POST", path,
            files={"file": (filename, payload, "application/json")},
            data={"dry_run": str(dry_run).lower(), "strict_mode": "true", "upsert_mode": "skip"},
        )
        result = self._json_object(response, path=path)
        self._require_fields(result, path=path, fields=(
            "job_id", "import_type", "dry_run", "inserted", "failed", "errors", "warnings",
        ))
        if result["import_type"] != "flows" or result["dry_run"] is not dry_run:
            raise UpstreamError(
                code="NEBULA_LCA_PROVIDER_CONTRACT_INVALID",
                message="Nebula LCA returned a mismatched TIDAS flow import receipt",
                status_code=502, details={"path": path},
            )
        return ProviderResponse(payload=result, etag=response.headers.get("etag"))

    def list_reference_units(self, unit_group: str) -> list[dict[str, Any]]:
        path = "/api/reference/units"
        response = self._request("GET", path, params={"unit_group": unit_group})
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamError(
                code="NEBULA_LCA_INVALID_RESPONSE",
                message="Nebula LCA returned non-JSON content",
                status_code=502,
                details={"path": path},
            ) from exc
        if not isinstance(payload, list) or any(
            not isinstance(item, dict) for item in payload
        ):
            raise UpstreamError(
                code="NEBULA_LCA_PROVIDER_CONTRACT_INVALID",
                message="Nebula LCA unit listing is invalid",
                status_code=502,
                details={"path": path},
            )
        for item in payload:
            if item.get("unit_group") != unit_group:
                raise UpstreamError(
                    code="NEBULA_LCA_PROVIDER_CONTRACT_INVALID",
                    message="Nebula LCA returned units outside the requested group",
                    status_code=502,
                    details={"path": path, "requested": unit_group, "item": item},
                )
        return payload

    def list_project_versions(self, project_id: str) -> list[dict[str, Any]]:
        path = f"/api/projects/{project_id}/versions"
        response = self._request("GET", path)
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamError(
                code="NEBULA_LCA_INVALID_RESPONSE",
                message="Nebula LCA returned non-JSON content",
                status_code=502,
                details={"path": path},
            ) from exc
        if not isinstance(payload, list) or any(
            not isinstance(item, dict) for item in payload
        ):
            raise UpstreamError(
                code="NEBULA_LCA_MODEL_CONTRACT_INVALID",
                message="Nebula LCA project versions response is invalid",
                status_code=502,
                details={"path": path},
            )
        for item in payload:
            if str(item.get("project_id") or "") != project_id or not isinstance(
                item.get("version"), int
            ):
                raise UpstreamError(
                    code="NEBULA_LCA_MODEL_PIN_MISMATCH",
                    message="Nebula LCA returned an invalid project version identity",
                    status_code=502,
                    details={"path": path, "item": item},
                )
        return payload

    def import_tidas_bundle(
        self,
        *,
        filename: str,
        payload: bytes,
        dry_run: bool,
    ) -> ProviderResponse:
        path = "/api/import/tidas/bundle"
        response = self._request(
            "POST",
            path,
            files={"file": (filename, payload, "application/zip")},
            data={
                "dry_run": "true" if dry_run else "false",
                "strict_mode": "false" if dry_run else "true",
                "upsert_mode": "update",
                "display_lang": "zh",
                "allocation_policy": "quantity",
            },
        )
        result = self._json_object(response, path=path)
        self._require_fields(
            result,
            path=path,
            fields=(
                "job_id",
                "import_type",
                "dry_run",
                "failed",
                "errors",
                "warnings",
                "unresolved_count",
                "created_projects",
            ),
        )
        if result.get("import_type") != "bundle" or bool(result.get("dry_run")) != dry_run:
            raise UpstreamError(
                code="NEBULA_LCA_PROVIDER_CONTRACT_INVALID",
                message="Nebula LCA returned a mismatched TIDAS import receipt",
                status_code=502,
                details={"path": path},
            )
        return ProviderResponse(payload=result, etag=response.headers.get("etag"))

    def restore_native_bundle(
        self,
        *,
        filename: str,
        payload: bytes,
        conflict_policy: str,
    ) -> ProviderResponse:
        path = "/api/native-project-bundles/import"
        response = self._request(
            "POST",
            path,
            params={"conflict_policy": conflict_policy},
            files={"file": (filename, payload, "application/zip")},
        )
        result = self._json_object(response, path=path)
        self._require_fields(
            result,
            path=path,
            fields=(
                "schema_version",
                "status",
                "source_project_id",
                "project_id",
                "graph_hashes_preserved",
                "counts",
                "issues",
                "source_manifest_sha256",
            ),
        )
        if result.get("schema_version") != "nebula.project.bundle.v1":
            raise UpstreamError(
                code="NEBULA_LCA_PROVIDER_CONTRACT_INVALID",
                message="Nebula LCA restored an unsupported native bundle schema",
                status_code=502,
                details={"path": path, "schema_version": result.get("schema_version")},
            )
        return ProviderResponse(payload=result, etag=response.headers.get("etag"))

    def restore_native_catalog_flows(
        self, *, filename: str, payload: bytes, flow_uuids: list[str]
    ) -> ProviderResponse:
        path = "/api/native-project-bundles/import-catalog-flows"
        response = self._request(
            "POST", path,
            params=[("flow_uuid", value) for value in sorted(flow_uuids)],
            files={"file": (filename, payload, "application/zip")},
        )
        result = self._json_object(response, path=path)
        self._require_fields(result, path=path, fields=("source_project_id", "flow_uuids", "counts"))
        if result["flow_uuids"] != sorted(flow_uuids):
            raise UpstreamError(
                code="NEBULA_LCA_CATALOG_IMPORT_IDENTITY_MISMATCH",
                message="catalog import returned different Flow identities",
                status_code=502,
                details={"path": path},
            )
        return ProviderResponse(payload=result, etag=response.headers.get("etag"))

    @staticmethod
    def _require_fields(
        payload: dict[str, Any], *, path: str, fields: tuple[str, ...]
    ) -> None:
        missing = [field for field in fields if field not in payload]
        if missing:
            raise UpstreamError(
                code="NEBULA_LCA_PROVIDER_CONTRACT_INVALID",
                message="Nebula LCA provider response is missing required fields",
                status_code=502,
                details={"path": path, "missing": missing},
            )

    def get_provider_model_snapshot(
        self, project_id: str, version: int
    ) -> ProviderResponse:
        path = f"/api/provider/v1/models/{project_id}/versions/{version}/snapshot"
        response = self._request("GET", path)
        payload = self._json_object(response, path=path)
        self._require_fields(
            payload,
            path=path,
            fields=(
                "schema_version",
                "engine",
                "project_id",
                "version",
                "graph_hash",
                "functional_unit",
                "graph",
            ),
        )
        if str(payload["project_id"]) != project_id or payload["version"] != version:
            raise UpstreamError(
                code="NEBULA_LCA_MODEL_PIN_MISMATCH",
                message="Nebula LCA returned a different provider snapshot identity",
                status_code=502,
                details={
                    "requested_project_id": project_id,
                    "requested_version": version,
                    "returned_project_id": payload.get("project_id"),
                    "returned_version": payload.get("version"),
                },
            )
        if not isinstance(payload["graph"], dict):
            raise UpstreamError(
                code="NEBULA_LCA_PROVIDER_CONTRACT_INVALID",
                message="Nebula LCA provider snapshot graph is not an object",
                status_code=502,
                details={"path": path},
            )
        return ProviderResponse(
            payload={**payload, "graph": without_flow_display_names(payload["graph"])},
            etag=response.headers.get("etag"),
        )

    def solve_provider(self, request_payload: dict[str, Any]) -> ProviderResponse:
        path = "/api/provider/v1/solve"
        response = self._request("POST", path, json=request_payload)
        payload = self._json_object(response, path=path)
        self._require_fields(
            payload,
            path=path,
            fields=(
                "schema_version",
                "run_id",
                "status",
                "snapshot_ref",
                "demand",
                "activity_vector",
                "scaled_exchanges",
                "inventory_totals",
                "issues",
                "provenance",
            ),
        )
        for field in (
            "demand",
            "activity_vector",
            "scaled_exchanges",
            "inventory_totals",
            "issues",
        ):
            if not isinstance(payload[field], list):
                raise UpstreamError(
                    code="NEBULA_LCA_PROVIDER_CONTRACT_INVALID",
                    message=f"Nebula LCA provider solve field is not a list: {field}",
                    status_code=502,
                    details={"path": path, "field": field},
                )
        if not isinstance(payload["provenance"], dict):
            raise UpstreamError(
                code="NEBULA_LCA_PROVIDER_CONTRACT_INVALID",
                message="Nebula LCA provider solve provenance is not an object",
                status_code=502,
                details={"path": path},
            )
        requested_idempotency_key = request_payload.get("idempotency_key")
        if requested_idempotency_key is not None:
            request_hash = payload.get("request_hash")
            provenance = payload["provenance"]
            if (
                payload.get("idempotency_key") != requested_idempotency_key
                or provenance.get("idempotency_key") != requested_idempotency_key
                or re.fullmatch(r"[0-9a-f]{64}", str(request_hash or "")) is None
                or provenance.get("request_hash") != request_hash
            ):
                raise UpstreamError(
                    code="NEBULA_LCA_PROVIDER_IDEMPOTENCY_RECEIPT_INVALID",
                    message="Nebula LCA provider solve did not echo a valid idempotency receipt",
                    status_code=502,
                    details={"path": path},
                )
        background_receipts = payload.get("background_process_receipts", [])
        if not isinstance(background_receipts, list) or any(
            not isinstance(item, dict) for item in background_receipts
        ):
            raise UpstreamError(
                code="NEBULA_LCA_PROVIDER_CONTRACT_INVALID",
                message="Nebula LCA provider solve background receipts are invalid",
                status_code=502,
                details={"path": path, "field": "background_process_receipts"},
            )
        validate_native_climate_answer(request_payload, payload, path=path)
        return ProviderResponse(payload=payload, etag=response.headers.get("etag"))

    def convert_unit(self, *, from_unit: str, to_unit: str, unit_group: str | None) -> ProviderResponse:
        path = "/api/units/convert"
        response = self._request("POST", path, json={"value": 1.0, "from_unit": from_unit,
                                                       "to_unit": to_unit, "unit_group": unit_group})
        payload = self._json_object(response, path=path)
        self._require_fields(payload, path=path, fields=("converted_value", "from_unit", "to_unit", "unit_group"))
        return ProviderResponse(payload=payload, etag=response.headers.get("etag"))

    def list_provider_projects(self) -> list[dict[str, Any]]:
        path = "/api/projects"
        projects: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = self._json_object(self._request("GET", path, params={"page": page, "page_size": 100,
                                                                           "include_resources": True}), path=path)
            items = payload.get("items")
            total = payload.get("total")
            if not isinstance(items, list) or not isinstance(total, int) or total < 0 or any(
                not isinstance(item, dict) or not isinstance(item.get("project_id"), str) or
                not isinstance(item.get("name"), str) or
                not isinstance(item.get("latest_version"), (int, type(None))) for item in items
            ) or (not items and len(projects) < total):
                raise UpstreamError(code="NEBULA_LCA_PROJECT_LIST_INVALID", message="Nebula LCA returned an invalid project list", status_code=502)
            projects.extend({"project_id": item["project_id"], "name": item["name"],
                             "latest_version": item.get("latest_version")} for item in items)
            if len(projects) >= total:
                return projects
            page += 1

    def list_provider_project_versions(self, project_id: str) -> list[dict[str, Any]]:
        path = f"/api/projects/{quote(project_id, safe='')}/versions"
        payload = self._request("GET", path).json()
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise UpstreamError(code="NEBULA_LCA_PROJECT_VERSIONS_INVALID", message="Nebula LCA returned an invalid version list", status_code=502)
        if any(not isinstance(item.get("version"), int) or
                not isinstance(item.get("graph_hash"), str) or
                item.get("project_id") != project_id for item in payload):
            raise UpstreamError(code="NEBULA_LCA_PROJECT_VERSIONS_INVALID", message="Nebula LCA returned invalid version identities", status_code=502)
        return [{"version": item["version"], "created_at": item.get("created_at"),
                 "graph_hash": item.get("graph_hash")}
                for item in payload]

    def create_provider_project(self, project: dict[str, Any]) -> ProviderResponse:
        path = "/api/projects"
        response = self._request("POST", path, json=project)
        payload = self._json_object(response, path=path)
        self._require_fields(payload, path=path, fields=("project_id", "name"))
        return ProviderResponse(payload=payload, etag=response.headers.get("etag"))

    def get_provider_project(self, project_id: str) -> ProviderResponse:
        path = f"/api/projects/{quote(project_id, safe='')}"
        response = self._request("GET", path)
        payload = self._json_object(response, path=path)
        if payload.get("project_id") != project_id:
            raise UpstreamError(code="NEBULA_LCA_PROJECT_IDENTITY_MISMATCH",
                                message="Nebula LCA returned another project", status_code=502)
        return ProviderResponse(payload=payload, etag=response.headers.get("etag"))

    def mark_provider_supply_resource(self, project_id: str) -> ProviderResponse:
        path = f"/api/projects/{quote(project_id, safe='')}"
        response = self._request("PATCH", path, json={"status": "resource"})
        payload = self._json_object(response, path=path)
        if payload.get("project_id") != project_id or payload.get("status") != "resource":
            raise UpstreamError(code="NEBULA_LCA_RESOURCE_ROLE_MISMATCH",
                                message="Nebula LCA did not mark the exact background supply project as a resource",
                                status_code=502, details={"path": path})
        return ProviderResponse(payload=payload, etag=response.headers.get("etag"))

    def resolve_flow_mapping(self, request_payload: dict[str, Any]) -> ProviderResponse:
        path = '/api/intermediate-flow-links/resolve-batch'
        response = self._request('POST', path, json=request_payload)
        payload = self._json_object(response, path=path)
        self._require_fields(payload, path=path, fields=('package_id', 'package_version', 'package_hash', 'items'))
        return ProviderResponse(payload=payload, etag=response.headers.get('etag'))

    def mapped_provider_candidates(self, target_flow_uuid: str) -> ProviderResponse:
        path = '/api/intermediate-flow-links/providers'
        response = self._request('GET', path, params={'target_flow_uuid': target_flow_uuid})
        payload = self._json_object(response, path=path)
        self._require_fields(payload, path=path, fields=('target_flow_uuid', 'providers', 'auto_selected'))
        return ProviderResponse(payload=payload, etag=response.headers.get('etag'))

    def resolve_provider_catalog(
        self, request_payload: dict[str, Any]
    ) -> ProviderResponse:
        path = "/api/provider/v1/catalog/resolve"
        response = self._request("POST", path, json=request_payload)
        payload = self._json_object(response, path=path)
        self._require_fields(
            payload,
            path=path,
            fields=("schema_version", "items", "issues"),
        )
        if payload["schema_version"] != "provider.catalog.resolve.response.v1":
            raise UpstreamError(
                code="NEBULA_LCA_PROVIDER_CONTRACT_INVALID",
                message="Nebula LCA catalog resolver returned an unsupported schema version",
                status_code=502,
                details={
                    "path": path,
                    "schema_version": payload["schema_version"],
                },
            )
        if not isinstance(payload["items"], list) or not isinstance(
            payload["issues"], list
        ):
            raise UpstreamError(
                code="NEBULA_LCA_PROVIDER_CONTRACT_INVALID",
                message="Nebula LCA catalog resolver returned invalid collections",
                status_code=502,
                details={"path": path},
            )
        for index, item in enumerate(payload["items"]):
            if not isinstance(item, dict):
                self._raise_catalog_contract_error(
                    path=path,
                    index=index,
                    reason="catalog item is not an object",
                )
            if item.get("kind") == "process" and item.get("status") == "resolved":
                self._validate_exact_process_catalog_item(
                    item,
                    path=path,
                    index=index,
                )
            if (
                item.get("kind") == "flow"
                and item.get("status") == "resolved"
                and isinstance(item.get("value"), dict)
                and item["value"].get("resolution_source")
                == "tidas_exact_elementary_snapshot"
            ):
                self._validate_exact_elementary_catalog_item(
                    item,
                    path=path,
                    index=index,
                )
        return ProviderResponse(payload=payload, etag=response.headers.get("etag"))

    @staticmethod
    def _raise_catalog_contract_error(
        *, path: str, index: int, reason: str, field: str | None = None
    ) -> NoReturn:
        details: dict[str, Any] = {"path": path, "item_index": index}
        if field is not None:
            details["field"] = field
        raise UpstreamError(
            code="NEBULA_LCA_PROVIDER_CONTRACT_INVALID",
            message=f"Nebula LCA catalog resolver returned an invalid receipt: {reason}",
            status_code=502,
            details=details,
        )

    @classmethod
    def _validate_exact_elementary_catalog_item(
        cls,
        item: dict[str, Any],
        *,
        path: str,
        index: int,
    ) -> None:
        value = item.get("value")
        key = item.get("key")
        if not isinstance(value, dict) or not isinstance(key, dict):
            cls._raise_catalog_contract_error(
                path=path,
                index=index,
                reason="resolved elementary Flow receipt lacks key or value",
            )
        required_values = {
            "resolution_source": "tidas_exact_elementary_snapshot",
            "source_namespace": "tiangong_open_data",
            "flow_type": "Elementary flow",
        }
        for field, expected in required_values.items():
            if value.get(field) != expected:
                cls._raise_catalog_contract_error(
                    path=path,
                    index=index,
                    field=field,
                    reason=f"{field} does not preserve the exact elementary Flow boundary",
                )
        for field in ("source_namespace", "flow_uuid", "version"):
            if value.get(field) != key.get(field):
                cls._raise_catalog_contract_error(
                    path=path,
                    index=index,
                    field=field,
                    reason="resolved identity does not match the echoed exact request key",
                )
        for field in (
            "content_hash",
            "snapshot_hash",
            "flow_property_content_hash",
            "unit_group_content_hash",
            "unit_content_hash",
            "factor_hash",
        ):
            if re.fullmatch(r"[0-9a-f]{64}", str(value.get(field) or "")) is None:
                cls._raise_catalog_contract_error(
                    path=path,
                    index=index,
                    field=field,
                    reason=f"{field} is not a canonical SHA-256 hash",
                )
        classification_path = value.get("classification_path")
        if (
            not isinstance(classification_path, list)
            or not classification_path
            or any(not isinstance(part, str) or not part.strip() for part in classification_path)
        ):
            cls._raise_catalog_contract_error(
                path=path,
                index=index,
                field="classification_path",
                reason="elementary Flow classification is incomplete",
            )
        expected_direction = {
            "emissions": "output",
            "resources": "input",
        }.get(classification_path[0].casefold())
        if (
            expected_direction is None
            or value.get("direction") != expected_direction
            or value.get("compartment") != classification_path[-1]
        ):
            cls._raise_catalog_contract_error(
                path=path,
                index=index,
                field="classification_path",
                reason="classification, direction, and compartment are inconsistent",
            )
        for field in (
            "flow_property_uuid",
            "flow_property_version",
            "unit_group_uuid",
            "unit_group_version",
            "unit_group",
            "unit",
            "default_unit",
            "database_release",
        ):
            if not isinstance(value.get(field), str) or not value[field].strip():
                cls._raise_catalog_contract_error(
                    path=path,
                    index=index,
                    field=field,
                    reason=f"{field} is missing from the exact quantity identity",
                )
        if value["unit"] != value["default_unit"]:
            cls._raise_catalog_contract_error(
                path=path,
                index=index,
                field="default_unit",
                reason="default unit differs from the exact reference unit",
            )
        runtime_index = value.get("runtime_flow_index")
        factor_count = value.get("factor_count")
        if runtime_index is not None and (
            isinstance(runtime_index, bool)
            or not isinstance(runtime_index, int)
            or runtime_index < 0
        ):
            cls._raise_catalog_contract_error(
                path=path,
                index=index,
                field="runtime_flow_index",
                reason="EF 3.1 runtime Flow index is invalid",
            )
        if (
            isinstance(factor_count, bool)
            or not isinstance(factor_count, int)
            or factor_count < 0
        ):
            cls._raise_catalog_contract_error(
                path=path,
                index=index,
                field="factor_count",
                reason="elementary Flow factor count must be a non-negative integer",
            )
        if factor_count == 0 and value["factor_hash"] != canonical_json_sha256([]):
            cls._raise_catalog_contract_error(path=path, index=index, field="factor_hash",
                reason="missing factor coverage must carry the empty factor collection hash")
        if factor_count > 0 and runtime_index is None:
            cls._raise_catalog_contract_error(path=path, index=index, field="runtime_flow_index",
                reason="matched factors require a runtime Flow index")
        dependency_source = value.get("reference_dependency_resolution_source")
        dependency_hash = value.get("reference_dependency_snapshot_hash")
        if dependency_source not in {
            "provider_reference_seed",
            "tidas_exact_reference_snapshot",
        }:
            cls._raise_catalog_contract_error(
                path=path,
                index=index,
                field="reference_dependency_resolution_source",
                reason="reference dependency provenance is unsupported",
            )
        if dependency_source == "tidas_exact_reference_snapshot" and re.fullmatch(
            r"[0-9a-f]{64}", str(dependency_hash or "")
        ) is None:
            cls._raise_catalog_contract_error(
                path=path,
                index=index,
                field="reference_dependency_snapshot_hash",
                reason="exact reference dependency snapshot hash is missing",
            )

    @classmethod
    def _validate_exact_process_catalog_item(
        cls,
        item: dict[str, Any],
        *,
        path: str,
        index: int,
    ) -> None:
        value = item.get("value")
        key = item.get("key")
        if not isinstance(value, dict) or not isinstance(key, dict):
            cls._raise_catalog_contract_error(
                path=path,
                index=index,
                reason="resolved Process receipt lacks key or value",
            )
        required_values = {
            "resolution_source": "tidas_exact_process_snapshot",
            "source_namespace": "tiangong_open_data",
            "dependency_closure_status": "unresolved",
            "background_solve_supported": False,
            "calculation_role": "catalog_only",
        }
        for field, expected in required_values.items():
            if value.get(field) != expected:
                cls._raise_catalog_contract_error(
                    path=path,
                    index=index,
                    field=field,
                    reason=f"{field} does not preserve the catalog-only boundary",
                )
        for field in ("source_namespace", "process_uuid", "version"):
            if value.get(field) != key.get(field):
                cls._raise_catalog_contract_error(
                    path=path,
                    index=index,
                    field=field,
                    reason="resolved identity does not match the echoed exact request key",
                )
        for field in ("content_hash", "snapshot_hash"):
            if re.fullmatch(r"[0-9a-f]{64}", str(value.get(field) or "")) is None:
                cls._raise_catalog_contract_error(
                    path=path,
                    index=index,
                    field=field,
                    reason=f"{field} is not a canonical SHA-256 hash",
                )
        qref = value.get("quantitative_reference")
        if not isinstance(qref, dict) or qref.get("direction") != "output":
            cls._raise_catalog_contract_error(
                path=path,
                index=index,
                field="quantitative_reference",
                reason="quantitative reference is not an explicit output exchange",
            )
        amount = qref.get("amount")
        if (
            isinstance(amount, bool)
            or not isinstance(amount, (int, float))
            or not math.isfinite(float(amount))
            or float(amount) <= 0
        ):
            cls._raise_catalog_contract_error(
                path=path,
                index=index,
                field="quantitative_reference.amount",
                reason="quantitative reference amount is not finite and positive",
            )
        exchanges = value.get("exchanges")
        inputs = value.get("input_dependencies")
        outputs = value.get("other_outputs")
        unresolved = value.get("unresolved_exact_flow_refs")
        if (
            not isinstance(exchanges, list)
            or not exchanges
            or not isinstance(inputs, list)
            or not isinstance(outputs, list)
            or not isinstance(unresolved, list)
        ):
            cls._raise_catalog_contract_error(
                path=path,
                index=index,
                reason="Process exchanges or unresolved dependency collections are invalid",
            )
        for exchange_index, exchange in enumerate(exchanges):
            if not isinstance(exchange, dict):
                cls._raise_catalog_contract_error(
                    path=path,
                    index=index,
                    field=f"exchanges[{exchange_index}]",
                    reason="exchange receipt is not an object",
                )
            if (
                exchange.get("flow_catalog_binding_status")
                != "requires_exact_flow_resolution"
                or exchange.get("unit_identity_status")
                != "requires_exact_flow_resolution"
            ):
                cls._raise_catalog_contract_error(
                    path=path,
                    index=index,
                    field=f"exchanges[{exchange_index}]",
                    reason="exchange falsely claims resolved Flow or unit identity",
                )
            flow = exchange.get("flow")
            if (
                not isinstance(flow, dict)
                or flow.get("source_namespace") != "tiangong_open_data"
                or re.fullmatch(
                    r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",
                    str(flow.get("flow_uuid") or ""),
                )
                is None
                or re.fullmatch(
                    r"[0-9]{2}\.[0-9]{2}\.[0-9]{3}",
                    str(flow.get("version") or ""),
                )
                is None
            ):
                cls._raise_catalog_contract_error(
                    path=path,
                    index=index,
                    field=f"exchanges[{exchange_index}].flow",
                    reason="exchange does not preserve an exact TIDAS Flow identity",
                )
        if any(not isinstance(row, dict) for row in (*inputs, *outputs, *unresolved)):
            cls._raise_catalog_contract_error(
                path=path,
                index=index,
                reason="Process dependency collections contain non-object entries",
            )
        exchange_ids = [
            str(exchange.get("exchange_internal_id") or "")
            for exchange in exchanges
        ]
        if not all(exchange_ids) or len(exchange_ids) != len(set(exchange_ids)):
            cls._raise_catalog_contract_error(
                path=path,
                index=index,
                field="exchanges",
                reason="exchange internal IDs are missing or duplicated",
            )
        qref_id = str(qref.get("exchange_internal_id") or "")
        input_ids = [
            str(exchange.get("exchange_internal_id") or "")
            for exchange in exchanges
            if exchange.get("direction") == "input"
        ]
        other_output_ids = [
            str(exchange.get("exchange_internal_id") or "")
            for exchange in exchanges
            if exchange.get("direction") == "output"
            and str(exchange.get("exchange_internal_id") or "") != qref_id
        ]
        qref_exchange = next(
            (exchange for exchange in exchanges if exchange["exchange_internal_id"] == qref_id),
            None,
        )
        if qref_exchange is None or any(
            qref.get(field) != qref_exchange.get(field)
            for field in ("direction", "amount", "flow")
        ):
            cls._raise_catalog_contract_error(
                path=path,
                index=index,
                field="quantitative_reference",
                reason="quantitative reference does not match its exact exchange receipt",
            )
        if [row.get("exchange_internal_id") for row in inputs] != input_ids:
            cls._raise_catalog_contract_error(
                path=path,
                index=index,
                field="input_dependencies",
                reason="input dependencies do not match Process input exchanges",
            )
        if [row.get("exchange_internal_id") for row in outputs] != other_output_ids:
            cls._raise_catalog_contract_error(
                path=path,
                index=index,
                field="other_outputs",
                reason="other outputs do not match non-reference Process outputs",
            )
        unresolved_identities = [
            (
                row.get("source_namespace"),
                row.get("flow_uuid"),
                row.get("version"),
            )
            for row in unresolved
            if isinstance(row, dict)
        ]
        expected_unresolved = [
            (
                exchange["flow"].get("source_namespace"),
                exchange["flow"].get("flow_uuid"),
                exchange["flow"].get("version"),
            )
            for exchange in exchanges
            if exchange.get("direction") == "input"
        ]
        if unresolved_identities != expected_unresolved:
            cls._raise_catalog_contract_error(
                path=path,
                index=index,
                field="unresolved_exact_flow_refs",
                reason="unresolved Flow references do not match Process inputs",
            )

    def get_model_version(self, project_id: str, version: int) -> ProviderResponse:
        path = f"/api/projects/{project_id}/versions/{version}"
        response = self._request("GET", path)
        payload = self._json_object(response, path=path)
        graph = payload.get("graph")
        if not isinstance(graph, dict):
            raise UpstreamError(
                code="NEBULA_LCA_MODEL_CONTRACT_INVALID",
                message="Nebula LCA model-version response has no graph object",
                status_code=502,
                details={"path": path},
            )
        returned_project = str(payload.get("project_id") or "")
        returned_version = payload.get("version")
        if returned_project != project_id or returned_version != version:
            raise UpstreamError(
                code="NEBULA_LCA_MODEL_PIN_MISMATCH",
                message="Nebula LCA returned a different model identity",
                status_code=502,
                details={
                    "requested_project_id": project_id,
                    "requested_version": version,
                    "returned_project_id": returned_project,
                    "returned_version": returned_version,
                },
            )
        return ProviderResponse(
            payload={**payload, "graph": without_flow_display_names(graph)},
            etag=response.headers.get("etag"),
        )

    def run_lcia(
        self,
        *,
        graph: dict[str, Any],
        project_id: str,
        lcia_methods: list[str],
        force_recompile: bool = False,
    ) -> ProviderResponse:
        path = "/api/model/run"
        response = self._request(
            "POST",
            path,
            json={
                "graph": graph,
                "project_id": project_id,
                "force_recompile": force_recompile,
                "lcia_methods": lcia_methods,
            },
        )
        return ProviderResponse(
            payload=self._json_object(response, path=path),
            etag=response.headers.get("etag"),
        )

    def create_model_version(
        self,
        *,
        project_id: str,
        graph: dict[str, Any],
        compile_pts_on_save: bool,
    ) -> ProviderResponse:
        path = f"/api/projects/{project_id}/versions"
        response = self._request(
            "POST",
            path,
            params={
                "compile_pts_on_save": "true" if compile_pts_on_save else "false"
            },
            json={"graph": graph},
        )
        return ProviderResponse(
            payload=self._json_object(response, path=path),
            etag=response.headers.get("etag"),
        )

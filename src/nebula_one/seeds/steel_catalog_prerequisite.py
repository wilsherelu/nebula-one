"""Exact, public catalog rows required by the steel seed, without a second project."""
from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile


RESOURCE_DIR = Path(__file__).resolve().parents[1] / "resources" / "steel_catalog"
DESCRIPTOR = RESOURCE_DIR / "steel-flow-prerequisites.v1.json"


def load_steel_catalog_prerequisite() -> tuple[dict, bytes, list[dict]]:
    descriptor = json.loads(DESCRIPTOR.read_text(encoding="utf-8"))
    if descriptor.get("schema_version") != "nebula_one.steel-flow-prerequisites.v1":
        raise ValueError("steel catalog prerequisite descriptor schema changed")
    asset = RESOURCE_DIR / descriptor["asset"]
    if asset.parent != RESOURCE_DIR or asset.suffix != ".zip":
        raise ValueError("steel catalog prerequisite path is invalid")
    payload = asset.read_bytes()
    if hashlib.sha256(payload).hexdigest() != descriptor["asset_sha256"]:
        raise ValueError("steel catalog prerequisite asset hash drifted")
    with ZipFile(BytesIO(payload)) as archive:
        if set(archive.namelist()) != {"manifest.json", "catalog/flows.json"}:
            raise ValueError("steel catalog prerequisite contains unexpected entries")
        manifest = json.loads(archive.read("manifest.json"))
        flow_bytes = archive.read("catalog/flows.json")
        rows = json.loads(flow_bytes)
    flow_hash = hashlib.sha256(flow_bytes).hexdigest()
    if (manifest.get("schema_version") != "nebula.project.bundle.v1"
            or manifest.get("project_id") != descriptor["source_project_id"]
            or manifest.get("source_seed_id") != descriptor["source_seed_id"]
            or manifest.get("source_seed_version") != descriptor["source_seed_version"]
            or manifest.get("source_bundle_content_sha256") != descriptor["source_bundle_content_sha256"]
            or manifest.get("content") != {"catalog/flows.json": {"sha256": flow_hash, "bytes": len(flow_bytes)}}
            or flow_hash != descriptor["flows_sha256"]
            or sorted(row.get("flow_uuid") for row in rows) != descriptor["flow_uuids"]
            or len(rows) != len(descriptor["flow_uuids"])):
        raise ValueError("steel catalog prerequisite identity or contents drifted")
    return descriptor, payload, rows

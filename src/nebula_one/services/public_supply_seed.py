"""Install a pinned, editable single-process supply example through Nebula LCA's public API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..errors import DomainError
from ..hashing import canonical_json_sha256


def _refuse(code: str, message: str, **details: Any) -> None:
    raise DomainError(code=code, message=message, status_code=409, details=details)


def _contains(expected: Any, actual: Any) -> bool:
    """Ignore only fields added by Nebula LCA's graph schema and storage normalization."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _contains(value, actual[key]) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(
            _contains(left, right) for left, right in zip(expected, actual)
        )
    return expected == actual


def ensure_public_supply_seed(client: Any, *, path: Path, declared_hash: str,
                              seed_id: str, seed_version: str) -> tuple[str, dict[str, Any]]:
    if not path.is_file():
        _refuse("PUBLIC_SUPPLY_SEED_MISSING", "the declared public supply seed is absent", path=str(path))
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as error:
        _refuse("PUBLIC_SUPPLY_SEED_INVALID", "the public supply seed is not valid JSON", error=str(error))
    actual_hash = canonical_json_sha256(document)
    if actual_hash != declared_hash:
        _refuse("PUBLIC_SUPPLY_SEED_HASH_DRIFT", "the public supply seed content changed",
                declared_hash=declared_hash, actual_hash=actual_hash)
    if not isinstance(document, dict) or (document.get("schema_version"), document.get("seed_id"),
            document.get("seed_version")) != ("nebula_one.public-supply-seed.v1", seed_id, seed_version):
        _refuse("PUBLIC_SUPPLY_SEED_INVALID", "the public supply seed identity is invalid")
    name, project, graph, factor = (document.get(key) for key in
                                    ("project_name", "project", "graph", "factor"))
    source_process = document.get("source_process")
    if not isinstance(name, str) or not isinstance(project, dict) or not isinstance(graph, dict) or not (isinstance(factor, dict) or isinstance(source_process, dict)):
        _refuse("PUBLIC_SUPPLY_SEED_INVALID", "the public supply seed fields are invalid")
    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or len(nodes) != 1 or graph.get("exchanges") != []:
        _refuse("PUBLIC_SUPPLY_SEED_INVALID", "the supply graph must contain one closed process")
    outputs = nodes[0].get("outputs")
    if source_process is not None:
        from ..seeds.open_process_supply import ensure_open_process_supply_flows
        ensure_open_process_supply_flows(client, document, path)
    elif not isinstance(outputs, list) or len(outputs) != 2 or not any(
        port.get("type") == "biosphere" and port.get("amount") == factor.get("value")
        for port in outputs if isinstance(port, dict)
    ):
        _refuse("PUBLIC_SUPPLY_SEED_INVALID", "the declared factor and graph exchange disagree")

    matches = [item for item in client.list_provider_projects() if item["name"] == name]
    if len(matches) > 1:
        _refuse("PUBLIC_SUPPLY_SEED_PROJECT_CONFLICT", "multiple projects use the seed name")
    created = not matches
    if matches:
        project_id = matches[0]["project_id"]
    else:
        try:
            project_id = client.create_provider_project({"name": name, **project}).payload["project_id"]
        except DomainError as error:
            if error.details.get("upstream_status") != 409:
                raise
            matches = [item for item in client.list_provider_projects() if item["name"] == name]
            if len(matches) != 1:
                raise
            project_id = matches[0]["project_id"]
            created = False
    installed_project = client.get_provider_project(project_id).payload
    if any(installed_project.get(key) != value for key, value in {"name": name, **project}.items()):
        _refuse("PUBLIC_SUPPLY_SEED_PROJECT_CONFLICT", "the project metadata differs from the declared seed",
                project_id=project_id)
    versions = client.list_provider_project_versions(project_id)
    if not versions:
        response = client.create_model_version(project_id=project_id, graph=graph,
                                               compile_pts_on_save=False).payload
        if response.get("version") != 1:
            _refuse("PUBLIC_SUPPLY_SEED_VERSION_CONFLICT", "the first supply version was not version 1")
    elif not any(item["version"] == 1 for item in versions):
        _refuse("PUBLIC_SUPPLY_SEED_VERSION_CONFLICT", "the public supply seed has no initial version")
    snapshot = client.get_provider_model_snapshot(project_id, 1).payload
    if not _contains(graph, snapshot["graph"]) or snapshot.get("source_policy") != project.get("source_policy"):
        _refuse("PUBLIC_SUPPLY_SEED_VERSION_DRIFT", "the installed initial supply version differs from the declared seed",
                project_id=project_id, graph_hash=snapshot.get("graph_hash"))
    if installed_project.get("status") != "resource":
        client.mark_provider_supply_resource(project_id)
    return ("executed" if created or not versions else "replayed"), {
        "seed_id": seed_id, "seed_version": seed_version, "content_sha256": actual_hash,
        "project_id": project_id, "version": 1, "graph_hash": snapshot["graph_hash"],
    }

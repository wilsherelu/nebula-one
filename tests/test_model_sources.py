from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from zipfile import ZIP_DEFLATED, ZipFile


def _application(client) -> dict:
    response = client.post(
        "/api/v1/applications",
        json={
            "name": "Model source acceptance",
            "application_type": "system_analysis",
            "context": {},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _native_bundle(*, dependencies: list[dict] | None = None, corrupt_hash: bool = False) -> bytes:
    files = {
        "project.json": {"id": "source-project", "name": "Native project"},
        "versions.json": [{"id": "version-1", "model_id": "source-project", "version": 1}],
        "dependencies.json": dependencies or [],
    }
    encoded = {
        name: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        for name, value in files.items()
    }
    manifest = {
        "schema_version": "nebula.project.bundle.v1",
        "created_at": "2026-09-02T00:00:00Z",
        "project_id": "source-project",
        "project_name": "Native project",
        "content": {
            name: {"sha256": sha256(payload).hexdigest(), "bytes": len(payload)}
            for name, payload in sorted(encoded.items())
        },
        "counts": {"versions": 1, "runs": 0, "external_dependencies": len(dependencies or [])},
    }
    if corrupt_hash:
        manifest["content"]["project.json"]["sha256"] = "0" * 64
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        )
        for name, payload in encoded.items():
            archive.writestr(name, payload)
    return output.getvalue()


def test_connects_exact_nebula_project_and_records_model_source(client, upstream_requests):
    application = _application(client)
    response = client.post(
        f"/api/v1/applications/{application['id']}/model-sources/nebula-project",
        json={"name": "Existing exact model", "upstream_project_id": "project-1", "upstream_version": 3},
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["source"]["source_type"] == "nebula_project_version"
    assert result["source"]["status"] == "attached"
    assert result["source"]["system_model_id"] == result["system_model"]["id"]
    assert result["base_revision"]["revision_kind"] == "base"
    requested_paths = [item["path"] for item in upstream_requests]
    assert "/api/provider/v1/models/project-1/versions/3/snapshot" in requested_paths
    assert "/api/projects/project-1/versions/3" in requested_paths


def test_tidas_preview_import_and_exact_version_attach(client):
    application = _application(client)
    package = b"PK\x03\x04tidas-fixture"
    preview = client.post(
        "/api/v1/model-sources/tidas/preview",
        files={"file": ("refinery.zip", package, "application/zip")},
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["status"] == "ready"

    imported = client.post(
        f"/api/v1/applications/{application['id']}/model-sources/tidas/import",
        files={"file": ("refinery.zip", package, "application/zip")},
        data={
            "name": "Imported TIDAS refinery",
            "confirmed": "true",
            "expected_preview_sha256": preview_body["preview_sha256"],
        },
    )
    assert imported.status_code == 201, imported.text
    source = imported.json()
    assert source["status"] == "ready_to_attach"
    assert source["candidate_versions"][0]["project_id"] == "tidas-project"

    attached = client.post(
        f"/api/v1/model-sources/{source['id']}/attach",
        json={"upstream_project_id": "tidas-project", "upstream_version": 1},
    )
    assert attached.status_code == 200, attached.text
    assert attached.json()["source"]["status"] == "attached"


def test_tidas_import_rejects_unconfirmed_or_changed_preview(client):
    application = _application(client)
    package = b"PK\x03\x04tidas-fixture"
    response = client.post(
        f"/api/v1/applications/{application['id']}/model-sources/tidas/import",
        files={"file": ("refinery.zip", package, "application/zip")},
        data={"name": "TIDAS", "confirmed": "false", "expected_preview_sha256": "a" * 64},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODEL_SOURCE_CONFIRMATION_REQUIRED"

    response = client.post(
        f"/api/v1/applications/{application['id']}/model-sources/tidas/import",
        files={"file": ("refinery.zip", package, "application/zip")},
        data={"name": "TIDAS", "confirmed": "true", "expected_preview_sha256": "a" * 64},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODEL_SOURCE_PREVIEW_MISMATCH"


def test_tidas_blocking_preview_never_calls_formal_import(client, upstream_requests):
    application = _application(client)
    package = b"PK\x03\x04blocked-tidas"
    preview = client.post(
        "/api/v1/model-sources/tidas/preview",
        files={"file": ("blocked.zip", package, "application/zip")},
    )
    assert preview.status_code == 200
    assert preview.json()["status"] == "blocked"

    response = client.post(
        f"/api/v1/applications/{application['id']}/model-sources/tidas/import",
        files={"file": ("blocked.zip", package, "application/zip")},
        data={
            "name": "Blocked TIDAS",
            "confirmed": "true",
            "expected_preview_sha256": preview.json()["preview_sha256"],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TIDAS_IMPORT_PREVIEW_BLOCKED"
    calls = [item for item in upstream_requests if item["path"] == "/api/import/tidas/bundle"]
    assert len(calls) == 2
    assert all(item["tidas_dry_run"] is True for item in calls)


def test_native_inspect_restore_attach_and_missing_dependency_blocks_solve(client):
    application = _application(client)
    package = _native_bundle(
        dependencies=[{
            "kind": "flow",
            "flow_uuid": "licensed-flow",
            "source_namespace": "ecoinvent",
            "source_version": "3.11",
            "reason": "licensed_external",
        }]
    )
    inspected = client.post(
        "/api/v1/model-sources/native/inspect",
        files={"file": ("refinery.nebula.zip", package, "application/zip")},
    )
    assert inspected.status_code == 200, inspected.text
    inspection = inspected.json()
    assert inspection["summary"]["counts"]["versions"] == 1
    assert len(inspection["external_dependencies"]) == 1

    restored = client.post(
        f"/api/v1/applications/{application['id']}/model-sources/native/restore",
        files={"file": ("refinery.nebula.zip", package, "application/zip")},
        data={
            "name": "Restored refinery",
            "confirmed": "true",
            "expected_preview_sha256": inspection["preview_sha256"],
            "conflict_policy": "rename",
        },
    )
    assert restored.status_code == 201, restored.text
    source = restored.json()
    assert source["status"] == "ready_to_attach"
    assert source["candidate_versions"][0]["project_id"] == "native-project"

    attached = client.post(
        f"/api/v1/model-sources/{source['id']}/attach",
        json={"upstream_project_id": "native-project", "upstream_version": 1},
    )
    assert attached.status_code == 200, attached.text
    model = attached.json()["system_model"]
    revision = attached.json()["base_revision"]
    solve = client.post(
        f"/api/v1/applications/{application['id']}/system-revisions/{revision['id']}/solve",
        json={"demand": [{"reference_flow_uuid": "flow-product", "amount": 1, "unit": "kg"}]},
    )
    assert solve.status_code == 409
    assert solve.json()["error"]["code"] == "MODEL_SOURCE_DEPENDENCIES_MISSING"
    assert model["upstream_receipt"]["solve_readiness"] == "blocked_missing_dependencies"


def test_native_inspection_rejects_bad_hash_and_unsafe_path(client):
    package = _native_bundle(corrupt_hash=True)
    response = client.post(
        "/api/v1/model-sources/native/inspect",
        files={"file": ("broken.nebula.zip", package, "application/zip")},
    )
    assert response.status_code == 422

    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("../manifest.json", "{}")
    response = client.post(
        "/api/v1/model-sources/native/inspect",
        files={"file": ("unsafe.nebula.zip", output.getvalue(), "application/zip")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "NATIVE_BUNDLE_UNSAFE_PATH"

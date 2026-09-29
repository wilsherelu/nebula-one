from __future__ import annotations

import socket
import threading
import time

import httpx
import uvicorn

from nebula_one.config import Settings
from nebula_one.main import create_app


def test_real_http_and_sqlite_runtime_smoke(tmp_path, model_graph):
    def upstream_handler(request: httpx.Request) -> httpx.Response:
        if (
            request.method == "GET"
            and request.url.path == "/api/projects/project-http/versions/1"
        ):
            return httpx.Response(
                200,
                json={
                    "project_id": "project-http",
                    "version": 1,
                    "created_at": "2026-08-29T00:00:00Z",
                    "graph": model_graph,
                    "source_policy": "tidas_compliant",
                    "allowed_lcia_scope": "ef31_only",
                },
            )
        return httpx.Response(404, json={"detail": "not found"})

    app = create_app(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'http-smoke.db').as_posix()}",
            nebula_lca_base_url="http://nebula-lca-http-fixture.test",
            nebula_lca_timeout_seconds=5,
        ),
        engine_transport=httpx.MockTransport(upstream_handler),
    )
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    try:
        deadline = time.monotonic() + 10
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5
        ) as client:
            while True:
                try:
                    health = client.get("/health")
                    if health.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() >= deadline:
                    raise AssertionError("Nebula One HTTP smoke server did not start")
                time.sleep(0.05)

            assert health.json()["version"] == "1.0.0rc2"
            application = client.post(
                "/api/v1/applications",
                json={
                    "name": "HTTP acceptance workspace",
                    "application_type": "system_analysis",
                },
            )
            assert application.status_code == 201, application.text
            application_id = application.json()["id"]
            model = client.post(
                f"/api/v1/applications/{application_id}/system-models",
                json={
                    "name": "HTTP pinned model",
                    "provider": "nebula_lca",
                    "upstream_project_id": "project-http",
                    "upstream_version": 1,
                },
            )
            assert model.status_code == 201, model.text
            entity = client.post(
                f"/api/v1/applications/{application_id}/entities",
                json={"entity_type": "organization", "name": "HTTP entity"},
            )
            assert entity.status_code == 201, entity.text
            persisted = client.get(
                f"/api/v1/applications/{application_id}/entities"
            )
            assert persisted.status_code == 200
            assert [item["id"] for item in persisted.json()] == [entity.json()["id"]]
            revisions = client.get(
                f"/api/v1/system-models/{model.json()['id']}/revisions"
            )
            assert revisions.status_code == 200
            assert len(revisions.json()) == 1
            # A resource that declares no display names keeps the exact name its owner typed under any language.
            listed_en = client.get("/api/v1/applications", params={"lang": "en"})
            assert listed_en.status_code == 200
            shown = next(item for item in listed_en.json() if item["id"] == application_id)
            assert shown["name"] == "HTTP acceptance workspace"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        assert not thread.is_alive()

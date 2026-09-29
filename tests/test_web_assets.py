from __future__ import annotations

from fastapi.testclient import TestClient

from nebula_one.config import Settings
from nebula_one.main import create_app


def test_built_web_assets_and_spa_fallback(tmp_path):
    web_root = tmp_path / "web"
    web_root.mkdir()
    (web_root / "index.html").write_text(
        "<!doctype html><title>Nebula One packaged smoke</title>",
        encoding="utf-8",
    )
    (web_root / "asset.txt").write_text("asset-ok", encoding="utf-8")
    app = create_app(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'web.db').as_posix()}",
            nebula_lca_base_url="http://unused.test",
            web_root=str(web_root),
        )
    )

    with TestClient(app) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert root.headers["cache-control"] == "no-store"
        assert client.get("/asset.txt").text == "asset-ok"
        fallback = client.get("/applications/example/scenarios")
        assert fallback.status_code == 200
        assert fallback.headers["cache-control"] == "no-store"
        assert "Nebula One packaged smoke" in fallback.text
        assert client.get("/applications/example/scenarios", headers={"If-None-Match": fallback.headers["etag"]}).status_code == 200
        assert client.get("/health").json()["status"] == "ok"

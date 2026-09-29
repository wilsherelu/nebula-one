from __future__ import annotations

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles


class SpaStaticFiles(StaticFiles):
    """Serve built assets and fall back to index.html for client-side routes."""

    async def get_response(self, path: str, scope) -> Response:
        index = Path(self.directory) / "index.html"
        if path in {"", ".", "index.html"} and scope.get("method") in {"GET", "HEAD"}:
            return FileResponse(index, headers={"Cache-Control": "no-store"})
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or scope.get("method") not in {"GET", "HEAD"}:
                raise
            return FileResponse(index, headers={"Cache-Control": "no-store"})
        if response.status_code != 404 or scope.get("method") not in {"GET", "HEAD"}:
            return response
        return FileResponse(index, headers={"Cache-Control": "no-store"})


def usable_web_root(configured: str | None) -> Path | None:
    if not configured:
        return None
    root = Path(configured).expanduser().resolve()
    return root if root.is_dir() and (root / "index.html").is_file() else None

"""Stable desktop provider identity routed only to the owned loopback sidecar."""
from __future__ import annotations

import httpx

DESKTOP_PROVIDER_ORIGIN = "http://nebula-lca.desktop.invalid"


class DesktopEngineTransport(httpx.HTTPTransport):
    def __init__(self, endpoint: str):
        target = httpx.URL(endpoint)
        if (target.scheme != "http" or target.host != "127.0.0.1" or not target.port
                or target.path != "/" or target.query or target.fragment or target.userinfo):
            raise ValueError("desktop engine endpoint must be an exact loopback origin")
        self.target = target
        super().__init__(trust_env=False)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if str(request.url.copy_with(path="/", query=None)).rstrip("/") != DESKTOP_PROVIDER_ORIGIN:
            raise ValueError("desktop transport refuses an unrelated provider")
        request.url = request.url.copy_with(host=self.target.host, port=self.target.port)
        request.headers["host"] = self.target.netloc.decode("ascii")
        return super().handle_request(request)

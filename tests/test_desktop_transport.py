import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from nebula_one.desktop_transport import DESKTOP_PROVIDER_ORIGIN, DesktopEngineTransport


@pytest.mark.parametrize('endpoint', [
    'https://127.0.0.1:1234', 'http://localhost:1234', 'http://example.com:1234',
    'http://127.0.0.1:1234/path', 'http://user:secret@127.0.0.1:1234',
    'http://127.0.0.1:1234?x=1',
])
def test_desktop_transport_refuses_unowned_endpoint(endpoint):
    with pytest.raises(ValueError):
        DesktopEngineTransport(endpoint)


def test_desktop_transport_preserves_logical_identity_across_dynamic_ports():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers['Host']))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'owned-engine')

        def log_message(self, *_args):
            pass

    for _ in range(2):
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            endpoint = f'http://127.0.0.1:{server.server_port}'
            with httpx.Client(base_url=DESKTOP_PROVIDER_ORIGIN,
                              transport=DesktopEngineTransport(endpoint)) as client:
                assert str(client.base_url).rstrip('/') == DESKTOP_PROVIDER_ORIGIN
                assert client.get('/api/projects?version=7').text == 'owned-engine'
                with pytest.raises(ValueError):
                    client.get('http://other.invalid/api/health')
            assert seen[-1] == ('/api/projects?version=7', f'127.0.0.1:{server.server_port}')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

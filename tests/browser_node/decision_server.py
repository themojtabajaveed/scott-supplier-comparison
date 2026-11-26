"""Loopback helper for the Node port of test_network_integration: answers each routing decision with the
PRODUCT's Python network_allowed (scout/engine/browser.py), with the same test-only destination substitution as
the Python test. Binds 127.0.0.1 only; standard library only."""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scout.engine import browser as module  # noqa: E402

BASE = sys.argv[1]  # the fixture server's base URL
# identical to the Python test's monkeypatch: only the local fixture host:port, never a /cart path
module.safe_destination = lambda u, roots: urlparse(u).netloc == urlparse(BASE).netloc and not urlparse(u).path.startswith('/cart')


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        q = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        ok = module.network_allowed(q['method'], q['url'], q['resource_type'], q['roots'])
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({'allowed': ok}).encode())


s = HTTPServer(('127.0.0.1', 0), H)
print(s.server_port, flush=True)
s.serve_forever()

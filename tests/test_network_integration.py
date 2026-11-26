"""Actual local HTTP requests through Chromium routing. No external sites/API.
Local destinations are permitted only by a test-only predicate substitution.
Production keeps its private-address prohibition.
"""
import threading
from http.server import BaseHTTPRequestHandler,HTTPServer
from urllib.parse import urlparse
import pytest
from scout.engine import browser as module

class Handler(BaseHTTPRequestHandler):
 hits=[]
 def log_message(self,*a):pass
 def do_POST(self):
  self.hits.append(('POST',self.path));self.send_response(200);self.end_headers()
 def do_GET(self):
  self.hits.append(('GET',self.path))
  if self.path=='/redirect':
   self.send_response(302);self.send_header('Location','http://localhost:'+str(self.server.server_port)+'/target');self.end_headers();return
  self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(b'<html>fixture</html>')

def test_chromium_blocks_post_and_redirect_before_server_receives(monkeypatch):
 pytest.importorskip('playwright.sync_api')
 server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 base='http://127.0.0.1:'+str(server.server_port)
 # Only a local fixture GET on exact host:port; target hostname remains denied.
 monkeypatch.setattr(module,'safe_destination',lambda u,roots:urlparse(u).netloc==urlparse(base).netloc and not urlparse(u).path.startswith('/cart'))
 Handler.hits=[];b=None
 try:
  b=module.ReadOnlyBrowser();b.set_source(base);b.goto(base+'/page')
  b.page.evaluate("""async () => {try {await fetch('/cart/add', {method:'POST', body:'x'})}catch(e){} }""")
  with pytest.raises(Exception):b.goto(base+'/redirect')
  assert ('GET','/page') in Handler.hits and ('GET','/redirect') in Handler.hits
  assert not any(m=='POST' or p in ['/cart/add','/target'] for m,p in Handler.hits)
 finally:
  if b:b.close()
  server.shutdown();server.server_close();thread.join()

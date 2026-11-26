"""Page layout after the 2 November 2026 restructure: the recorded comparison is the home page, sample
questions live on /try, live-run details on /live, and each result page shows evidence before a folded
technical-details section. Offline: one local server on 127.0.0.1, labelled fixtures and saved files only.
"""
import http.client
import importlib.util
import re
import socket
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location('scout_ui_layout', ROOT / 'scripts' / 'scout_ui.py')
ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui)

RECORDED = all((ui.RECORDED_DIR / (s + '-result.json')).is_file() for s in ui.RECORDED_SITES)


class Layout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        real_connect = socket.socket.connect

        def guarded(sock, address):
            host = address[0] if isinstance(address, tuple) else address
            if host not in ('127.0.0.1', 'localhost', '::1'):
                raise OSError('test guard: non-loopback connection blocked')
            return real_connect(sock, address)
        cls.patches = [mock.patch.object(socket.socket, 'connect', guarded),
                       mock.patch.object(ui.Handler, 'log_message', lambda *a: None)]
        for p in cls.patches:
            p.start()
        cls.server = ui.make_server(0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        for p in reversed(cls.patches):
            p.stop()

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        headers = {'Content-Type': 'application/x-www-form-urlencoded'} if body else {}
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        text = resp.read().decode('utf-8')
        conn.close()
        return resp.status, text, resp.getheader('Location')

    def test_nav_names_the_four_pages(self):
        body = self.request('GET', '/about')[1]
        for href, label in ui.NAV:
            self.assertIn('<a href="%s">%s</a>' % (href, label), body)
        self.assertIn('<h1>How Scott works</h1>', body)
        for word in ('Quoted', 'Partly quoted', 'Not found', 'Values disagree', 'Needs review'):
            self.assertIn('<dt>%s</dt>' % word, body)

    def test_home_leads_with_the_comparison_and_keeps_live_details_off_it(self):
        # The home page renders the invented demo recordings, so the table checks below always run.
        sys.path.insert(0, str(ROOT / 'tests'))
        import demo_suppliers as demo
        old = self.server.recorded_dir
        self.server.recorded_dir = demo.FIXTURE_DIR
        try:
            with mock.patch.object(ui, 'RECORDED_SITES', [demo.ONE, demo.TWO, demo.THREE]), \
                    mock.patch.object(ui, 'SITE_LABELS', dict(demo.LABELS)):
                status, body, _ = self.request('GET', '/')
        finally:
            self.server.recorded_dir = old
        self.assertEqual(status, 200)
        self.assertNotIn('class="banner', body)
        for href in ('/try', '/live', '/about'):
            self.assertIn('href="%s"' % href, body)
        for detail in ('GEMINI_API_KEY', 'SCOUT_VERIFIED_FREE_PROJECT', 'live-ledger', 'owner decision'):
            self.assertNotIn(detail, body)
        self.assertNotIn('<form', body)  # questions are asked on /try
        self.assertIn('Live runs are switched off in this server instance.', body)
        self.assertIn('table class="cmp"', body)  # always exercised on the demo recordings
        self.assertLess(body.index('table class="cmp"'), body.index('id="live"'))

    def test_old_question_links_redirect_to_try_with_known_keys_only(self):
        status, _, location = self.request('GET', '/?example=supplier&evil=1')
        self.assertEqual((status, location), (303, '/try?example=supplier'))
        status, _, location = self.request('GET', '/?q=%3Cscript%3E%0D%0AX:1&domain=auto')
        self.assertEqual(status, 303)
        self.assertNotRegex(location, r'[\r\n<>]')
        self.assertTrue(location.startswith('/try?q='))
        status, body, _ = self.request('GET', '/try?example=provider')
        self.assertEqual(status, 200)
        self.assertIn('<form class="run"', body)
        self.assertIn(ui.EXAMPLES['provider'], body)
        self.assertIn('never runs it live', body)

    def test_live_page_when_switched_off_says_so(self):
        status, body, _ = self.request('GET', '/live')
        self.assertEqual(status, 200)
        self.assertIn('switched off in this server instance', body)
        self.assertNotIn('<form', body)

    def test_sample_result_shows_evidence_before_folded_technical_details(self):
        status, body, _ = self.request('POST', '/run', 'question=Compare+strong+white+bread+flour+16kg+delivery'
                                                         '&domain=auto')
        self.assertEqual(status, 200)
        summary, sources, tech = (body.index('<h2>Summary'), body.index('<h2>Sources</h2>'),
                                  body.index('<details class="tech">'))
        self.assertLess(summary, sources)
        self.assertLess(sources, tech)
        folded = body[tech:]
        for inner in ('<h2>Plan</h2>', '<h3>Budgets</h3>', '<h2>Engine report (sample data)</h2>',
                      '<h2>Trace (sample data run)</h2>', 'Full result object'):
            self.assertIn(inner, folded)
            self.assertNotIn(inner, body[:tech])
        self.assertIn('href="/try">Ask another question', body)

    def test_recorded_result_keeps_page_text_outside_the_folded_section(self):
        # Invented demo recording (tests/demo_suppliers.py) served by the same server; same assertions.
        sys.path.insert(0, str(ROOT / 'tests'))
        import demo_suppliers as demo
        old = self.server.recorded_dir
        self.server.recorded_dir = demo.FIXTURE_DIR
        try:
            with mock.patch.object(ui, 'RECORDED_SITES', [demo.ONE, demo.TWO, demo.THREE]), \
                    mock.patch.object(ui, 'SITE_LABELS', dict(demo.LABELS)):
                body = self.request('GET', '/recorded/' + demo.TWO)[1]
        finally:
            self.server.recorded_dir = old
        self.assertIn(ui.RECORDED_BANNER, body)
        tech = body.index('<details class="tech">')
        self.assertLess(body.index('<h2>Summary'), tech)
        self.assertLess(body.index('<h2>Page text Scott read</h2>'), tech)
        self.assertIn('an older engine version printed that date', body[tech:])

    def test_comparison_cells_carry_their_column_name_for_narrow_screens(self):
        rows = [{'site': 's', 'atomic_fields': {'product_price': {'status': 'incomplete', 'facts': {},
                                                                   'missing': ['amount']}}}]
        self.assertIn('<td data-label="Price (16kg sack)">', ui.comparison_table(rows))
        self.assertRegex(ui.CSS, re.compile(r'@media \(max-width:640px\)\{.*td::before\{content:attr\(data-label\)',
                                            re.S))


if __name__ == '__main__':
    unittest.main()

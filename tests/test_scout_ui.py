"""Hermetic tests for scripts/scout_ui.py. Standard library only.

The server runs in a thread on an ephemeral 127.0.0.1 port. A socket guard
fails the suite if anything tries to connect anywhere other than loopback.
"""
import ast
import importlib.util
import socket
import sys
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location('scout_ui', ROOT / 'scripts' / 'scout_ui.py')
ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui)

UNSUPPORTED = 'What is the weather in London tomorrow?'
UNSUPPORTED_GAP = 'Supported domains: 16kg flour supplier facts or named-model API token pricing'


class ScoutUITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Network guard: only loopback connections are allowed while the suite runs.
        cls.blocked = []

        cls._real_connect = socket.socket.connect
        real = cls._real_connect

        def guarded(sock, address):
            host = address[0] if isinstance(address, tuple) else address
            if host not in ('127.0.0.1', 'localhost', '::1'):
                cls.blocked.append(address)
                raise OSError('test guard: non-loopback connection blocked: %r' % (address,))
            return real(sock, address)
        socket.socket.connect = guarded

        # Count engine runs so the clarification path can prove nothing executed.
        cls.runs = []
        cls._real_execute = ui.execute_plan

        def counting(plan, browser, llm, **kwargs):
            cls.runs.append(plan.question)
            return cls._real_execute(plan, browser, llm, **kwargs)
        ui.execute_plan = counting

        cls._real_log = ui.Handler.log_message
        ui.Handler.log_message = lambda *args: None  # keep test output quiet
        cls.server = ui.make_server(0)
        # The recorded pages render the invented demo recordings (scout/demo_mode.py); the real 30 October
        # recordings are not included. Restored in tearDownClass.
        from unittest import mock as _mock
        sys.path.insert(0, str(ROOT / 'tests'))
        import demo_suppliers as _demo
        cls._demo_patches = [_mock.patch.object(ui, 'RECORDED_SITES', [_demo.ONE, _demo.TWO, _demo.THREE]),
                             _mock.patch.object(ui, 'SITE_LABELS', dict(_demo.LABELS))]
        for _p in cls._demo_patches:
            _p.start()
        cls.server.recorded_dir = _demo.FIXTURE_DIR
        cls.base = 'http://127.0.0.1:%d' % cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        for _p in getattr(cls, '_demo_patches', []):
            _p.stop()
        cls.server.shutdown()
        cls.server.server_close()
        ui.execute_plan = cls._real_execute

        ui.Handler.log_message = cls._real_log
        socket.socket.connect = cls._real_connect

    def setUp(self):
        self.runs.clear()

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=10) as resp:
                return resp.status, resp.read().decode('utf-8')
        except urllib.error.HTTPError as err:
            return err.code, err.read().decode('utf-8')

    def post(self, path, question, domain='auto'):
        data = urllib.parse.urlencode({'question': question, 'domain': domain}).encode('utf-8')
        req = urllib.request.Request(self.base + path, data=data, method='POST',
                                     headers={'Content-Type': 'application/x-www-form-urlencoded'})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read().decode('utf-8')
        except urllib.error.HTTPError as err:
            return err.code, err.read().decode('utf-8')

    # -- pages -------------------------------------------------------------
    def test_binds_loopback_only(self):
        self.assertEqual(self.server.server_address[0], '127.0.0.1')

    def test_try_page_names_supported_domains_and_config_entities(self):
        status, body = self.get('/try')
        self.assertEqual(status, 200)
        self.assertIn('Supplier', body)
        self.assertIn('API provider', body)

        self.assertIn('Run sample-data demo', body)
        for site in ui.supplier.WORKFLOW['sites']:
            self.assertIn(site['name'], body)
        self.assertIn(ui.supplier.WHOLEMEAL_SITE['name'], body)
        # One source of truth: every model the planner accepts is listed, including the demo's model.
        for model, _ in ui.provider.SUPPORTED_MODELS:
            self.assertIn(model, body)

    def test_about_page_states_limits(self):
        status, body = self.get('/about')
        self.assertEqual(status, 200)
        for text in ('The offline test suite covers', 'unreliable', 'ended incomplete',
                     'single runs cannot show reliability', 'Recorded live runs',
                     'Recordings of such runs are unavailable in this copy',
                     'cannot by themselves prove billing status', 'API pricing pages, which has not been tried with the current engine',
                     'a person must judge whether they mean the same thing',
                     'has not been tried with a live model',
                     'cheapest-buy or best-model verdicts', 'deliberate manual action',
                     'only a person replacing the ledger file with an empty one resets them', 'never typed into, shown on'):
            self.assertIn(text, body)
        # No historical account usage and no dated test count on the page.
        for text in ('input tokens and', 'output tokens, on a', 'free-tier project', '284 tests', 'counted 20 November'):
            self.assertNotIn(text, body)

    def test_examples_plan_to_ready(self):
        for domain, question in ui.EXAMPLES.items():
            plan = ui.plan_question(question)
            self.assertEqual((plan.state, plan.domain), ('ready', domain), plan.gaps)

    # -- demo runs ---------------------------------------------------------
    def test_supplier_demo_shows_banner_and_fixture_comparison(self):
        status, body = self.post('/run', ui.EXAMPLES['supplier'], 'supplier')
        self.assertEqual(status, 200)
        self.assertIn(ui.BANNER, body)
        self.assertIn('Engine report (sample data)', body)
        self.assertIn('£12.34', body)
        self.assertIn('demo-mill-one.sample.example', body)  # the invented page the sample read
        self.assertIn('Sample data invented for this demo', body)

        self.assertIn('demo_mill_one', body)  # invented sample source name
        self.assertIn('Trace (sample data run)', body)
        # execute_plan trace entries are {'step', 'tool', 'why', ...}; tool names must render.
        self.assertIn('<strong>navigate</strong>', body)
        self.assertIn('<strong>extract</strong>', body)
        self.assertIn('Show all', body)  # trace is collapsed behind a disclosure element
        self.assertEqual(len(self.runs), 1)

    def test_provider_demo_shows_fixture_prices(self):
        status, body = self.post('/run', ui.EXAMPLES['provider'], 'auto')
        self.assertEqual(status, 200)
        self.assertIn(ui.BANNER, body)
        self.assertIn('$1.23', body)
        self.assertIn('Ministral 3 8B', body)

    def test_unsupported_question_shows_clarification_and_runs_nothing(self):
        status, body = self.post('/run', UNSUPPORTED)
        self.assertEqual(status, 200)
        self.assertIn('Needs clarification', body)
        self.assertIn(UNSUPPORTED_GAP, body)
        self.assertIn(ui.BANNER, body)
        self.assertNotIn('Engine report (sample data)', body)
        self.assertEqual(self.runs, [])

    def test_domain_mismatch_is_not_silently_substituted(self):
        status, body = self.post('/run', ui.EXAMPLES['supplier'], 'provider')
        self.assertEqual(status, 200)
        self.assertIn('Needs clarification', body)
        self.assertIn('the selector cannot override it', body)
        self.assertEqual(self.runs, [])

    def test_user_text_is_escaped(self):

        status, body = self.post('/run', '<script>alert(1)</script> flour')
        self.assertEqual(status, 200)
        self.assertNotIn('<script>alert(1)', body)
        self.assertIn('&lt;script&gt;alert(1)', body)

    # -- routing -----------------------------------------------------------
    def test_post_to_any_other_path_is_404(self):
        for path in ('/', '/about', '/run/', '/runs', '/api/run'):
            status, _ = self.post(path, ui.EXAMPLES['supplier'])
            self.assertEqual(status, 404, path)
        self.assertEqual(self.runs, [])

    # -- recorded supplier comparison ---------------------------------------
    def test_comparison_page_renders_recorded_runs(self):
        status, body = self.get('/comparison')
        self.assertEqual(status, 200)
        self.assertIn('Supplier comparison', body)
        self.assertIn(ui.RECORDED_BANNER, body)
        self.assertIn('Demo Mill One (invented)', body)
        self.assertIn('Demo Mill Three (invented)', body)
        self.assertIn('Demo Mill Two (invented)', body)
        self.assertIn('30 October 2026', body)

    def test_comparison_page_shows_facts_with_quotes_and_sources(self):
        # Invented demo recordings (tests/demo_suppliers.py), same server; same assertions.
        from unittest import mock
        sys.path.insert(0, str(ROOT / 'tests'))
        import demo_suppliers as demo
        old = self.server.recorded_dir
        self.server.recorded_dir = demo.FIXTURE_DIR
        try:
            with mock.patch.object(ui, 'RECORDED_SITES', [demo.ONE, demo.TWO, demo.THREE]), \
                    mock.patch.object(ui, 'SITE_LABELS', dict(demo.LABELS)):
                status, body = self.get('/comparison')
        finally:
            self.server.recorded_dir = old
        self.assertEqual(status, 200)
        self.assertIn('£12.34', body)
        self.assertIn('&quot;£12.34&quot;', body)  # the exact words each fact came from
        self.assertIn('href="https://demo-mill-one.example/', body)  # recorded source, clickable
        self.assertIn('title="Supplier page as read 30 October 2026"', body)

    def test_comparison_page_marks_missing_and_status_in_plain_words(self):
        status, body = self.get('/comparison')
        self.assertEqual(status, 200)
        self.assertIn('Not found in this recorded run.', body)  # Shipton delivery charge cell
        self.assertIn('Not found (6)</summary>', body)  # missing inventory collapsed, still present
        self.assertIn('Amount, Basis, VAT, Zone, Packing, Surcharge', body)
        # offer-v1: the October prices were the only 'Found' cells; with no offer record they are not confirmed.
        self.assertNotIn('>Found<', body)
        self.assertIn('Price not confirmed', body)
        self.assertIn('Partly found', body)
        self.assertIn('Coverage:', body)

    def test_comparison_page_keeps_shipton_pack_size_unresolved(self):
        status, body = self.get('/comparison')
        self.assertEqual(status, 200)
        # The cell leads with the unresolved verdict, not a comparable price.
        self.assertIn('16kg price not confirmed', body)
        self.assertIn('Pack size: unresolved (16kg vs 1KG)', body)
        self.assertNotIn('<strong>£15.67</strong>', body)  # no bold price next to an unresolved pack size
        # The amount survives only inside the collapsed evidence, attached to its quotes.
        self.assertIn('Amount: £15.67 - &quot;', body)
        self.assertIn('not confirmed as the 16kg sack price', body)

    def test_comparison_page_has_supplier_cards_for_narrow_screens(self):
        status, body = self.get('/comparison')
        self.assertEqual(status, 200)
        self.assertIn('cmp-cards', body)
        self.assertEqual(body.count('class="card cmp-card"'), 3)  # one card per supplier
        self.assertIn('@media (max-width:56rem)', body)

    def test_comparison_page_marks_review_flags(self):
        status, body = self.get('/comparison')
        self.assertEqual(status, 200)
        self.assertIn('review required', body)
        self.assertIn('run stopped at page budget', body)

    def test_comparison_page_keeps_the_2_november_fixes(self):
        status, body = self.get('/comparison')
        self.assertEqual(status, 200)
        # A basis the engine reports missing (not quoted with the charge) is a quote, never a summary line.
        self.assertNotIn('<li>Basis: per parcel</li>', body)
        self.assertIn('Basis: per parcel - &quot;', body)
        # 'two' and '2' are one number: wording varies, not numbers; Shipton's pack sizes do differ in number.
        self.assertIn('Partly found - wording varies', body)
        self.assertIn('Needs review - numbers differ', body)  # offer-v1 word for Shipton's price cell
        # The 30 October store-data lines carry a £ that Scott added; the page says so.
        self.assertIn('the data itself states no currency', body)

    def test_home_links_to_comparison(self):
        status, body = self.get('/')
        self.assertEqual(status, 200)
        self.assertIn('href="/comparison"', body)
        self.assertEqual(self.runs, [])

    def test_unknown_get_is_404(self):
        self.assertEqual(self.get('/nope')[0], 404)

    # -- fixtures and network ----------------------------------------------
    def test_cli_and_ui_share_one_fixture_module(self):
        for script in ('scout_question.py', 'scout_ui.py'):
            tree = ast.parse((ROOT / 'scripts' / script).read_text(encoding='utf-8'))
            classes = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
            self.assertFalse(classes & {'DemoBrowser', 'DemoLLM'}, script)
            imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
            self.assertIn('scout.demo_fixtures', imports, script)

    def test_fixture_texts_are_labelled_and_contain_every_quote(self):
        from scout import demo_fixtures as fx
        for text in list(fx.PAGES.values()) + [fx.UNKNOWN_PAGE]:
            self.assertTrue(text.startswith('DEMO FIXTURE'), text)
        self.assertTrue(fx.RESPONSES)
        for (name, path), response in fx.RESPONSES.items():
            text = fx.PAGES[(name, '/pricing' if path.startswith('/pricing/') else path)]
            for field in response.values():
                for claim in field.values():
                    self.assertIn(claim['quote'], text)
                    self.assertIn(claim['value'], claim['quote'])

    def test_no_non_loopback_connection_attempted(self):
        self.post('/run', ui.EXAMPLES['provider'])
        self.assertEqual(self.blocked, [])


if __name__ == '__main__':
    unittest.main()

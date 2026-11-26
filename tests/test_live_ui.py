"""Offline tests for the private live-run path of scripts/scout_ui.py. No live call is ever made.

Standard library only. Every run uses a fake browser and a fake transport injected
into the real GeminiFree client, so the real planner, tool loop, budget checks
(BudgetExceeded) and ledger records all run, but nothing leaves this process.
A socket guard blocks every non-loopback connection and the urllib opener is
replaced so any outbound fetch attempt is recorded and refused. All files are
written under a temporary folder; the repository's eval-results is never touched.
The key below is a canary string, not a key.
"""
import builtins  # noqa: F401  (kept for parity with test_recorded_runs guards)
import http.client
import importlib.util
import itertools
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import types
import unittest
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


_spec = importlib.util.spec_from_file_location('scout_ui_live', ROOT / 'scripts' / 'scout_ui.py')
ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui)

try:
    from scout import live_run
except ImportError:  # turn-5 code has no live path; tests then fail on their assertions
    live_run = None

from scout.engine import llm as llm_module  # noqa: E402
from scout.workflows import supplier  # noqa: E402

CANARY = 'CANARY-not-a-real-key-7f3a9c41'
PROJECT = 'offline-test-project-placeholder'  # matches the placeholder project tests/conftest.py writes to the local config
ENV_OK = {'GEMINI_API_KEY': CANARY, 'SCOUT_VERIFIED_FREE_PROJECT': PROJECT}
SITES = {s['name']: s['url'] for s in supplier.WORKFLOW['sites']}
DELIVERY = {s['name']: s['delivery_page'] for s in supplier.WORKFLOW['sites']}
PAGE_TEXT = 'SYNTHETIC LIVE TEST PAGE: Demo strong flour 16kg £17.45.'
START = datetime(2026, 10, 30, 15, 0, 0, tzinfo=timezone.utc)
BANNER_DIV = re.compile(r'<div class="banner[^"]*" role="note">([^<]*)</div>')


class FakeBrowser:
    """Serves made-up text; records every URL it is asked to open."""

    def __init__(self, log, fail=False):
        self.log, self.fail = log, fail

    def goto(self, url):
        self.log.append(url)
        if self.fail:
            raise RuntimeError('synthetic page failure')

        self.url = url
        return url

    def text(self):
        return PAGE_TEXT

    def pick_evidence_link(self, missing, exclude):
        return None

    def try_select_variant(self, option):
        return False

    def close(self):
        self.log.append('closed')


class FakeTransport:
    """Stands in for the Gemini HTTP calls inside the real GeminiFree client."""

    def __init__(self):
        self.ops = []

    def __call__(self, op, body):
        self.ops.append(op)
        if op == 'countTokens':
            return {'totalTokens': 400}
        prompt = body['contents'][0]['parts'][0]['text']
        claims = ({'product_price': {'amount': {'value': '£17.45', 'quote': '16kg £17.45'}}}
                  if '16kg £17.45' in prompt else {})
        return {'candidates': [{'content': {'parts': [{'text': json.dumps(claims)}]}}],
                'usageMetadata': {'promptTokenCount': 380, 'candidatesTokenCount': 40}}



def reserved(n, input_tokens=1000, output_tokens=1024, released_input=100, released_output=900):
    """Ledger lines in the exact shape GeminiFree._record writes."""
    lines = []
    for i in range(n):
        lines.append({'ts': 0, 'model': 'm', 'kind': 'reserved', 'input_tokens': input_tokens,
                      'output_tokens': output_tokens, 'cumulative': {}, 'prompt_sha256': 'x' * 64})
        lines.append({'ts': 0, 'model': 'm', 'kind': 'reconciled', 'released_input': released_input,
                      'released_output': released_output, 'cumulative': {}})
    return ''.join(json.dumps(x) + '\n' for x in lines)


def banners(body):
    return BANNER_DIV.findall(body)


class LiveServer(unittest.TestCase):
    """One UI server per test, with its live path pointed at a temporary folder."""

    caps = {'calls': 30, 'input': 60000, 'output': 30000}
    env = ENV_OK
    browser_fails = False
    factory_error = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.results = self.base / 'eval-results'
        self.results.mkdir()
        self.ledger = self.results / 'live-ledger.jsonl'
        self.ledger.write_text('', encoding='utf-8')  # an empty ledger is a deliberate start; a missing one refuses
        self.recorded = self.base / 'recorded'
        self.recorded.mkdir()

        self.opened, self.transport, self.factory_calls = [], FakeTransport(), []
        self.outbound = []
        real_connect = socket.socket.connect

        def guarded(sock, address):
            host = address[0] if isinstance(address, tuple) else address
            if host not in ('127.0.0.1', 'localhost', '::1'):
                self.outbound.append(address)
                raise OSError('test guard: non-loopback connection blocked')
            return real_connect(sock, address)

        def no_fetch(opener, url, *a, **k):
            self.outbound.append(getattr(url, 'full_url', url))
            raise OSError('test guard: urllib fetch blocked')

        self.patches = [mock.patch.object(socket.socket, 'connect', guarded),
                        mock.patch.object(urllib.request.OpenerDirector, 'open', no_fetch),
                        mock.patch.object(ui.Handler, 'log_message', lambda *a: None)]
        for p in self.patches:
            p.start()
        self.clock_ticks = itertools.count()
        self.start_server()

    def factory(self):
        self.factory_calls.append(1)
        if self.factory_error:
            raise self.factory_error
        return FakeBrowser(self.opened, fail=self.browser_fails)

    def clock(self):
        return START + timedelta(seconds=next(self.clock_ticks))


    def live_config(self):
        return SimpleNamespace(env=dict(self.env), ledger_path=self.ledger, results_root=self.results,
                               caps=dict(self.caps), browser_factory=self.factory, transport=self.transport,
                               clock=self.clock)

    def start_server(self):
        self.server = ui.make_server(0, recorded_dir=self.recorded)
        self.server.live = self.live_config()  # attribute, so turn-5 code still starts (and ignores it)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()

    def tearDown(self):
        self.stop_server()
        for p in reversed(self.patches):
            p.stop()
        self.assertEqual(self.outbound, [])
        self.tmp.cleanup()

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        headers = {'Content-Type': 'application/x-www-form-urlencoded'} if body is not None else {}
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read().decode('utf-8')
        location = resp.getheader('Location')
        conn.close()
        return resp.status, data, location


    def start_run(self, site='wessex_mill', confirm=True, extra=''):
        body = 'site=' + site + ('&confirm=yes' if confirm else '') + extra
        return self.request('POST', '/live/run', body)

    def result_files(self):
        return sorted(self.results.glob('live-*/*-result.json'))

    def ledger_lines(self):
        if not self.ledger.exists():
            return []
        return [json.loads(x) for x in self.ledger.read_text(encoding='utf-8').splitlines() if x.strip()]


class ConfirmationAndRun(LiveServer):
    def test_confirmation_shows_only_configured_sites_and_correct_headroom(self):
        self.ledger.write_text(reserved(2), encoding='utf-8')  # 2 calls, 1,800 input, 248 output used
        self.server.live.caps = {'calls': 10, 'input': 20000, 'output': 12000}
        status, body, _ = self.request('GET', '/live')
        self.assertEqual(status, 200)
        for name, url in SITES.items():
            self.assertIn('value="%s"' % name, body)
            self.assertIn(url, body)
        self.assertNotIn('type="url"', body)
        self.assertNotIn('type="text"', body)  # no free URL (or key) input anywhere
        for text in ('<td>2</td><td>10</td><td>8</td>', '<td>1,800</td><td>20,000</td><td>18,200</td>',
                     '<td>248</td><td>12,000</td><td>11,752</td>', 'up to 6 model calls'):
            self.assertIn(text, body)
        self.assertIn('name="confirm"', body)
        self.assertEqual(banners(body), [])

    def test_post_without_confirmation_runs_nothing(self):

        status, body, _ = self.start_run(confirm=False)
        self.assertEqual(status, 400)
        self.assertIn('the confirmation box was not ticked', body)
        self.assertEqual((self.factory_calls, self.transport.ops, self.result_files(), self.ledger_lines()),
                         ([], [], [], []))

    def test_confirmed_run_calls_the_real_orchestration_with_real_config_and_fakes(self):
        self.assertIsNotNone(live_run, 'scout.live_run is missing')
        with mock.patch.object(live_run, 'run_live_site', wraps=live_run.run_live_site) as spy:
            status, body, location = self.start_run('wessex_mill')
        self.assertEqual(status, 303, body)
        spy.assert_called_once()
        self.assertEqual(spy.call_args.args[0], 'wessex_mill')
        # The configured page, then (no link on the fake page) the configured same-site delivery page.
        self.assertEqual(self.opened[:2], [SITES['wessex_mill'], DELIVERY['wessex_mill']])
        self.assertEqual(self.transport.ops, ['countTokens', 'generateContent'] * 2)
        files = self.result_files()
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].parent.name, 'live-20261030')
        self.assertTrue((files[0].parent / 'README.md').is_file())
        saved = json.loads(files[0].read_text(encoding='utf-8'))
        self.assertEqual(saved['plan']['workflow']['sites'][0]['url'], SITES['wessex_mill'])
        self.assertEqual(saved['live']['usage_before'], {'calls': 0, 'input': 0, 'output': 0})
        self.assertEqual(saved['live']['usage_after'], {'calls': 2, 'input': 760, 'output': 80})
        self.assertIn('snapshot, 30 October 2026.', saved['readable'])  # dated by the run's own clock
        self.assertNotIn('27 October 2026', saved['readable'])
        self.assertEqual([x['kind'] for x in self.ledger_lines()], ['reserved', 'response', 'reconciled'] * 2)
        self.assertIn('prompt_sha256', self.ledger_lines()[0])
        status, page, _ = self.request('GET', location)
        self.assertEqual(status, 200)
        self.assertIn('£17.45', page)

    def test_live_result_page_has_its_own_banner_and_is_listed_on_home(self):
        _, _, location = self.start_run('cotswold')
        status, page, _ = self.request('GET', location)

        self.assertEqual(status, 200)
        self.assertEqual(banners(page), ['Live run, 30 October 2026 - real public pages. Started 2026-10-30 15:00:00 UTC.'])
        self.assertIn('Engine report (live run)', page)
        self.assertIn('snapshot, 30 October 2026.', page)
        self.assertNotIn('older engine version', page)  # a new run's saved text is already dated correctly
        self.assertIn(PAGE_TEXT, page)  # page text Scott read, behind a disclosure
        listing = self.request('GET', '/live')[1]  # saved live runs are listed on the live-runs page
        self.assertIn('href="%s"' % location, listing[listing.index('Saved live runs'):])
        home = self.request('GET', '/')[1]
        self.assertIn('href="/live"', home[home.index('id="live"'):])
        self.assertEqual(banners(home), [])

    def test_one_run_at_a_time(self):
        self.assertTrue(ui.RUN_LOCK.acquire(blocking=False))
        try:
            status, body, _ = self.start_run()
        finally:
            ui.RUN_LOCK.release()
        self.assertEqual(status, 409)
        self.assertIn('Another run is in progress', body)
        self.assertEqual((self.factory_calls, self.transport.ops), ([], []))


class KeyAbsent(LiveServer):
    env = {'SCOUT_VERIFIED_FREE_PROJECT': PROJECT}

    def test_missing_key_disables_the_action_and_says_why(self):
        reason = 'No GEMINI_API_KEY is present in the server environment'
        home = self.request('GET', '/')[1]
        self.assertIn('Live runs are unavailable now.', home)
        self.assertNotIn('GEMINI_API_KEY', home)  # environment details stay on /live and in the docs
        status, body, _ = self.request('GET', '/live')
        self.assertIn(reason, body)
        self.assertRegex(body, r'<button type="submit" disabled>')
        status, body, _ = self.start_run(extra='&GEMINI_API_KEY=' + CANARY)  # a key from the browser is ignored

        self.assertEqual(status, 409)
        self.assertIn(reason, body)
        self.assertNotIn(CANARY, body)
        self.assertEqual((self.factory_calls, self.transport.ops, self.result_files()), ([], [], []))


class CapsExhausted(LiveServer):
    caps = {'calls': 1, 'input': 60000, 'output': 30000}  # below the per-run cap (6 before turn 7, 2 since)

    def test_cap_exhaustion_refuses_before_any_call(self):
        self.ledger.write_text(reserved(0), encoding='utf-8')
        status, body, _ = self.request('GET', '/live')
        self.assertIn('Not enough budget left', body)
        self.assertRegex(body, r'<button type="submit" disabled>')
        status, body, _ = self.start_run()
        self.assertEqual(status, 409)
        self.assertIn('Not enough budget left', body)
        self.assertIn('only a person replacing the ledger file with an empty one resets it', body)
        self.assertEqual((self.factory_calls, self.transport.ops, self.result_files()), ([], [], []))
        self.assertEqual(self.ledger.read_text(encoding='utf-8'), '')


class LedgerPersistence(LiveServer):
    def test_ledger_accumulates_across_runs_and_survives_a_restart(self):
        self.assertEqual(self.start_run('wessex_mill')[0], 303)
        self.assertEqual(self.start_run('shipton_mill')[0], 303)
        self.assertEqual([x['kind'] for x in self.ledger_lines()].count('reserved'), 4)  # 2 calls per run
        self.assertEqual(len(self.result_files()), 2)
        second = json.loads(next(p for p in self.result_files() if p.name.startswith('shipton_mill'))
                            .read_text(encoding='utf-8'))
        self.assertEqual(second['live']['usage_before']['calls'], 2)
        self.stop_server()

        self.start_server()  # a fresh server process state, same ledger file
        body = self.request('GET', '/live')[1]
        self.assertIn('<td>4</td><td>30</td><td>26</td>', body)

    def test_unreadable_ledger_refuses_and_is_left_alone(self):
        self.ledger.write_text('{"kind": "reserved", "input_tokens": 1}\nnot json\n', encoding='utf-8')
        before = self.ledger.read_bytes()
        body = self.request('GET', '/live')[1]
        self.assertIn('could not be read', body)
        status, body, _ = self.start_run()
        self.assertEqual(status, 409)
        self.assertIn('could not be read', body)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertEqual((self.factory_calls, self.transport.ops), ([], []))


class Failures(LiveServer):
    def test_failed_page_read_is_recorded_honestly_and_prior_results_stay(self):
        self.assertEqual(self.start_run('wessex_mill')[0], 303)
        first = self.result_files()[0]
        first_bytes = first.read_bytes()
        self.server.live.browser_factory = lambda: FakeBrowser(self.opened, fail=True)
        status, _, location = self.start_run('wessex_mill')
        self.assertEqual(status, 303)
        page = self.request('GET', location)[1]
        self.assertIn('source_or_extraction_error', page)
        self.assertIn('RuntimeError', page)
        self.assertEqual(first.read_bytes(), first_bytes)
        self.assertEqual(len(self.result_files()), 2)

    def test_browser_that_cannot_start_is_recorded_honestly(self):
        self.server.live.browser_factory = self.factory

        self.factory_error = ImportError('No module named playwright (key ' + CANARY + ')')
        status, _, location = self.start_run('wessex_mill')
        self.assertEqual(status, 303)
        page = self.request('GET', location)[1]
        self.assertIn('live_run_failed', page)
        self.assertIn('ImportError', page)
        self.assertIn('No module named playwright', page)
        self.assertNotIn(CANARY, page)
        saved = self.result_files()[0].read_text(encoding='utf-8')
        self.assertIn('[redacted]', saved)
        self.assertEqual(self.transport.ops, [])

    def test_missing_playwright_is_reported_in_plain_words(self):
        self.server.live.browser_factory = None
        real = importlib.util.find_spec
        with mock.patch.object(importlib.util, 'find_spec',
                               lambda name, *a: None if name == 'playwright' else real(name, *a)):
            body = self.request('GET', '/live')[1]
            status, refused, _ = self.start_run()
        self.assertIn('Playwright is not installed', body)
        self.assertEqual(status, 409)
        self.assertIn('Playwright is not installed', refused)


class Separation(LiveServer):
    def test_live_recorded_and_sample_banners_never_cooccur(self):
        stand_in = {'state': 'bounded_result_review_required', 'question': 'q', 'rows': [], 'trace': []}
        (self.recorded / 'wessex_mill-result.json').write_text(json.dumps(stand_in), encoding='utf-8')
        _, _, location = self.start_run('wessex_mill')
        pages = {
            'home': self.request('GET', '/')[1],
            'about': self.request('GET', '/about')[1],

            'confirm': self.request('GET', '/live')[1],
            'live': self.request('GET', location)[1],
            'recorded': self.request('GET', '/recorded/wessex_mill')[1],
            'sample': self.request('POST', '/run', 'question=' + ui.EXAMPLES['supplier'].replace(' ', '+')
                                   + '&domain=supplier')[1],
            'clarify': self.request('POST', '/run', 'question=weather&domain=auto')[1],
        }
        found = {k: banners(v) for k, v in pages.items()}
        self.assertEqual(found['home'], [])
        self.assertEqual(found['about'], [])
        self.assertEqual(found['confirm'], [])
        self.assertEqual(len(found['live']), 1)
        self.assertTrue(found['live'][0].startswith('Live run, '))
        self.assertEqual(found['recorded'], [ui.RECORDED_BANNER])
        self.assertEqual(found['sample'], [ui.BANNER])
        self.assertEqual(found['clarify'], [ui.BANNER])
        self.assertNotIn('sample data', pages['live'].lower())


class KeyIsolation(LiveServer):
    def test_canary_key_never_appears_in_pages_results_ledger_or_trace(self):
        with mock.patch.dict(os.environ, ENV_OK):
            self.server.live.env = os.environ  # exactly what the real server uses
            bodies = [self.start_run('wessex_mill')[1]]
            locations = [self.start_run('cotswold')[2]]
            self.server.live.browser_factory = lambda: FakeBrowser(self.opened, fail=True)
            locations.append(self.start_run('shipton_mill')[2])
            for path in ['/', '/about', '/live'] + locations:
                bodies.append(self.request('GET', path)[1])
        for body in bodies:
            self.assertNotIn(CANARY, body)
        written = [p for p in self.base.rglob('*') if p.is_file()]

        self.assertTrue(any(p.name == 'live-ledger.jsonl' for p in written))
        self.assertTrue(any(p.name == 'README.md' for p in written))
        for path in written:
            self.assertNotIn(CANARY, path.read_text(encoding='utf-8', errors='replace'), path)
        for path in self.result_files():
            self.assertIn('"trace"', path.read_text(encoding='utf-8'))


class LedgerFailsClosed(LiveServer):
    """A missing, unreadable or used-up ledger refuses every live run (20 November 2026). A fresh clone has
    no ledger, so counting a missing file as zero usage would silently reset the allowance."""

    caps = live_run.CUMULATIVE_CAPS if live_run else {}

    def assert_refused(self, reason, home_line='Live runs are unavailable now.'):
        self.assertIn(home_line, self.request('GET', '/')[1])
        body = self.request('GET', '/live')[1]
        self.assertIn(reason, body)
        self.assertRegex(body, r'<button type="submit" disabled>')
        status, body, _ = self.start_run()
        self.assertEqual(status, 409)
        self.assertIn(reason, body)
        self.assertEqual((self.factory_calls, self.transport.ops, self.result_files()), ([], [], []))

    def test_caps_and_run_cap_are_unchanged(self):
        self.assertEqual(live_run.CUMULATIVE_CAPS, {'calls': 8, 'input': 12000, 'output': 6000})
        self.assertEqual(live_run.UI_RUN_CALL_CAP, 2)

    def test_missing_ledger_refuses_and_is_not_created(self):
        self.ledger.unlink()
        with self.assertRaisesRegex(live_run.LedgerError, 'does not exist'):
            live_run.ledger_totals(self.ledger)
        self.assert_refused('a missing ledger is never counted as zero usage')
        self.assertFalse(self.ledger.exists())

    def test_ledger_that_cannot_be_read_as_text_refuses_and_is_left_alone(self):
        self.ledger.write_bytes(b'\xff\xfe not text \x00')
        before = self.ledger.read_bytes()
        self.assert_refused('could not be opened as text')
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_exhausted_allowance_at_the_real_caps_refuses(self):
        self.ledger.write_text(reserved(8), encoding='utf-8')  # every call under the cumulative call cap used
        self.assertEqual(live_run.ledger_totals(self.ledger)['calls'], 8)
        self.assert_refused('Not enough budget left',
                            home_line='Live runs are unavailable now. The shared budget has too few model calls '
                                      'left for one run.')
        self.assertEqual(self.ledger.read_text(encoding='utf-8'), reserved(8))

    def test_script_runner_refuses_a_missing_ledger_before_any_call(self):
        spec = importlib.util.spec_from_file_location('run_supplier_live_fc', ROOT / 'scripts' / 'run_supplier_live.py')
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        browser = types.ModuleType('scout.engine.browser')
        browser.ReadOnlyBrowser = lambda: SimpleNamespace(close=lambda: None)
        self.ledger.unlink()
        cwd = os.getcwd()
        os.chdir(self.base)
        try:
            with mock.patch.dict(sys.modules, {'scout.engine.browser': browser}), \
                    mock.patch.dict(os.environ, ENV_OK), \
                    mock.patch.object(live_run, 'LEDGER_PATH', self.ledger), \
                    mock.patch.object(llm_module.GeminiFree, '_post', lambda self, op, body: self.fail('model call')):
                with self.assertRaisesRegex(SystemExit, 'Usage ledger unreadable .*refusing to run'):
                    script.run_site('wessex_mill')
        finally:
            os.chdir(cwd)
        self.assertFalse(self.ledger.exists())
        self.assertEqual(self.transport.ops, [])


class SharedLedgerWithScript(unittest.TestCase):
    def test_run_supplier_live_counts_against_the_same_ledger(self):
        self.assertIsNotNone(live_run, 'scout.live_run is missing')
        spec = importlib.util.spec_from_file_location('run_supplier_live_t6', ROOT / 'scripts' / 'run_supplier_live.py')
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        agent = types.ModuleType('scout.engine.agent')

        def one_call(question, wf, llm, browser, trace):
            llm.generate_structured('synthetic prompt', {'type': 'object'})
            return [{'site': 'wessex_mill', 'atomic_fields': {}}]
        agent.run = one_call
        browser = types.ModuleType('scout.engine.browser')
        browser.ReadOnlyBrowser = lambda: SimpleNamespace(close=lambda: None)
        transport = FakeTransport()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / 'eval-results' / 'live-ledger.jsonl'
            ledger.parent.mkdir()
            ledger.write_text(reserved(1), encoding='utf-8')
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                with mock.patch.dict(sys.modules, {'scout.engine.agent': agent, 'scout.engine.browser': browser}), \
                        mock.patch.dict(os.environ, ENV_OK), \
                        mock.patch.object(live_run, 'LEDGER_PATH', ledger), \
                        mock.patch.object(llm_module.GeminiFree, '_post', lambda self, op, body: transport(op, body)), \
                        mock.patch('sys.stdout', new=__import__('io').StringIO()) as out:
                    script.run_site('wessex_mill')
            finally:
                os.chdir(cwd)
            kinds = [json.loads(x)['kind'] for x in ledger.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(kinds.count('reserved'), 2)  # the earlier UI-style call plus this script's call
            self.assertEqual(json.loads(out.getvalue())['llm_spent']['calls'], 2)
            self.assertFalse(any(Path(tmp, 'traces').glob('*.usage.jsonl')))  # no private per-run ledger


def invented_seed():
    """INVENTED ledger lines for budget tests: 6 calls of 1,000 input tokens each, 300 output tokens used per call
    (1,024 reserved, 724 released), totalling 6 calls, 6,000 input and 1,800 output tokens."""
    lines = []
    for _ in range(6):
        lines.append({'ts': 0, 'model': 'm', 'kind': 'reserved', 'input_tokens': 1000,
                      'output_tokens': 1024, 'cumulative': {}, 'prompt_sha256': 's' * 64})
        lines.append({'ts': 0, 'model': 'm', 'kind': 'reconciled', 'released_input': 0,
                      'released_output': 724, 'cumulative': {}})
    return ''.join(json.dumps(x) + '\n' for x in lines)


class LinkingBrowser(FakeBrowser):
    """Fake browser that offers one more same-site page and, optionally, a working pack selector."""

    def __init__(self, log, variant=False):
        super().__init__(log)
        self.variant = variant

    def pick_evidence_link(self, missing, exclude):
        link = self.url.split('#')[0].rstrip('/') + '/delivery-information/'
        return None if link in exclude or self.url.endswith('/delivery-information/') else link

    def try_select_variant(self, option):
        return self.variant


class OverrunOnSecondCall(FakeTransport):
    """Reports more input tokens than were reserved on the second generation, so GeminiFree raises BudgetExceeded."""

    def __call__(self, op, body):
        response = super().__call__(op, body)
        if op == 'generateContent' and self.ops.count('generateContent') == 2:

            response['usageMetadata'] = {'promptTokenCount': 5000, 'candidatesTokenCount': 40}
        return response


class EffectiveRunCap(LiveServer):
    """Turn 7: one UI run is capped at live_run.UI_RUN_CALL_CAP model calls."""

    def use_cumulative_caps(self, ledger_text):
        self.ledger.write_text(ledger_text, encoding='utf-8')
        self.server.live.caps = dict(live_run.CUMULATIVE_CAPS) if live_run else {'calls': 8, 'input': 12000,
                                                                                    'output': 6000}

    def test_confirmation_shows_the_effective_cap_and_the_engine_worst_case(self):
        self.use_cumulative_caps(invented_seed())
        status, body, _ = self.request('GET', '/live')
        self.assertEqual(status, 200)
        self.assertIn('capped at 2 model calls for this run', body)
        self.assertIn('the engine could use up to 6 model calls without the cap', body)
        # Used, cap, remaining, and "this run may use up to" (the effective cap, bounded by what remains).
        self.assertIn('<td>6</td><td>8</td><td>2</td><td>2</td>', body)
        self.assertIn('<td>6,000</td><td>12,000</td><td>6,000</td><td>6,000</td>', body)
        self.assertIn('<td>1,800</td><td>6,000</td><td>4,200</td><td>2,048</td>', body)
        self.assertNotRegex(body, r'<button type="submit" disabled>')

    def test_exhausted_budget_says_no_run_is_possible_without_a_per_run_column(self):
        self.use_cumulative_caps(invented_seed() + reserved(2))  # every call under the cumulative call cap used
        status, body, _ = self.request('GET', '/live')
        self.assertEqual(status, 200)
        self.assertIn('No live run is possible now: the shared budget has 0 model calls left, fewer than the 2 '
                      'one run needs', body)
        self.assertNotIn('This run may use up to', body)
        self.assertNotIn('capped at 2 model calls for this run;', body)
        self.assertIn('<td>8</td><td>8</td><td>0</td></tr>', body)
        self.assertRegex(body, r'<button type="submit" disabled>')

    def test_two_calls_remaining_permit_the_run(self):
        self.use_cumulative_caps(invented_seed())
        status, body, _ = self.start_run('wessex_mill')
        self.assertEqual(status, 303, body)
        self.assertEqual(self.transport.ops, ['countTokens', 'generateContent'] * 2)  # exactly the 2-call cap

    def test_one_call_remaining_refuses_before_any_call_and_says_why(self):
        self.use_cumulative_caps(invented_seed() + reserved(1))

        before = self.ledger.read_bytes()
        status, body, _ = self.start_run('wessex_mill')
        self.assertEqual(status, 409)
        self.assertIn("is below this run&#x27;s cap of 2 model calls", body)
        self.assertIn('1 model call,', body)
        self.assertEqual((self.factory_calls, self.transport.ops, self.result_files()), ([], [], []))
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_per_run_client_limit_equals_the_effective_cap(self):
        self.assertIsNotNone(live_run, 'scout.live_run is missing')
        self.assertEqual(live_run.UI_RUN_CALL_CAP, 2)
        clients, real = [], live_run.make_client

        def capture(*args, **kwargs):
            clients.append((kwargs, real(*args, **kwargs)))
            return clients[-1][1]
        with mock.patch.object(live_run, 'make_client', side_effect=capture):
            self.assertEqual(self.start_run('wessex_mill')[0], 303)
        kwargs, client = clients[0]
        self.assertEqual(kwargs['per_run']['calls'], 2)
        self.assertEqual(client.caps['calls'], 2)  # empty ledger, caps of 30: the per-run limit binds
        saved = json.loads(self.result_files()[0].read_text(encoding='utf-8'))
        self.assertEqual((saved['live']['run_call_cap'], saved['live']['planned_model_calls']), (2, 6))

    def test_run_hard_stops_at_the_cap_and_saves_an_honest_partial_result(self):
        self.server.live.browser_factory = lambda: LinkingBrowser(self.opened, variant=True)
        status, _, location = self.start_run('shipton_mill')
        self.assertEqual(status, 303)
        self.assertEqual(self.transport.ops.count('generateContent'), 2)  # a third call was wanted, never sent
        saved = json.loads(self.result_files()[0].read_text(encoding='utf-8'))
        row = saved['rows'][0]
        self.assertEqual(row['stop_reason'], 'provider_budget_stop')

        self.assertEqual(row['errors'][0]['type'], 'BudgetExceeded')
        self.assertEqual(len(row['pages_visited']), 2)
        self.assertEqual([x['kind'] for x in self.ledger_lines()].count('reserved'), 2)
        page = self.request('GET', location)[1]
        self.assertIn('Stopped by a budget check', page)

    def test_budget_exceeded_on_call_two_keeps_the_partial_result_and_ledger(self):
        self.server.live.browser_factory = lambda: LinkingBrowser(self.opened)
        self.server.live.transport = self.transport = OverrunOnSecondCall()
        status, body, location = self.start_run('wessex_mill')
        self.assertEqual(status, 303, body)
        saved = json.loads(self.result_files()[0].read_text(encoding='utf-8'))
        self.assertEqual(saved['state'], 'bounded_result_review_required')
        row = saved['rows'][0]
        self.assertEqual(row['stop_reason'], 'provider_budget_stop')
        self.assertEqual(row['errors'][0]['type'], 'BudgetExceeded')
        self.assertEqual([p['source_url'] for p in row['page_texts']], row['pages_visited'])
        self.assertEqual(len(row['pages_visited']), 2)
        self.assertEqual(row['atomic_fields']['product_price']['facts']['amount'][0]['value'], '£17.45')
        self.assertNotEqual(row['atomic_fields']['delivery_charge']['status'], 'literal_components_present')
        self.assertEqual([x['kind'] for x in self.ledger_lines()],
                         ['reserved', 'response', 'reconciled', 'reserved', 'response', 'failed'])
        self.assertEqual(saved['live']['usage_after'], {'calls': 2, 'input': 780, 'output': 1064})
        page = self.request('GET', location)[1]
        self.assertIn('Stopped by a budget check', page)
        self.assertIn('provider_budget_stop', page)

    def test_unknown_ledger_record_kind_fails_closed(self):
        self.ledger.write_text(json.dumps({'kind': 'seed', 'calls': 6}) + '\n', encoding='utf-8')
        body = self.request('GET', '/live')[1]
        self.assertIn('could not be read', body)
        self.assertIn('unknown record kind', body)



class StartHereMatchesConstants(unittest.TestCase):
    def test_start_here_live_section_points_to_the_limits_in_code(self):
        # The limits are read from the code (scout/live_run.py); the guide must name where they are set and must not
        # restate figures, which would go stale whenever the code changes.
        self.assertIsNotNone(live_run, 'scout.live_run is missing')
        caps, run_cap = live_run.CUMULATIVE_CAPS, live_run.UI_RUN_CALL_CAP
        self.assertEqual(set(caps), {'calls', 'input', 'output'})
        self.assertTrue(all(isinstance(v, int) and v > 0 for v in caps.values()), caps)
        self.assertTrue(isinstance(run_cap, int) and 0 < run_cap <= caps['calls'], run_cap)
        path = ROOT / 'START-HERE.md'
        if not path.is_file():
            self.skipTest('START-HERE.md not present')
        text = path.read_text(encoding='utf-8')
        start = text.index('## Local web UI')
        end = text.find('\n## ', start + 1)
        section = text[start:end if end != -1 else len(text)]
        for pointer in ('scout/live_run.py', 'UI_RUN_CALL_CAP', 'CUMULATIVE_CAPS', 'disabled by default',
                        'refused before any model call'):
            self.assertIn(pointer, section)
        for figure in ('%d model calls' % run_cap, '%d model calls' % caps['calls'], format(caps['input'], ','),
                       format(caps['output'], ','), str(caps['input']), str(caps['output']),
                       '60,000', '30 calls', 'Counting starts with this ledger'):
            self.assertNotIn(figure, section)


class StartsWithoutPlaywright(unittest.TestCase):
    def test_server_starts_under_dash_s_and_non_live_pages_work(self):
        env = {k: v for k, v in os.environ.items() if k not in ('GEMINI_API_KEY', 'SCOUT_VERIFIED_FREE_PROJECT')}
        proc = subprocess.Popen([sys.executable, '-S', str(ROOT / 'scripts' / 'scout_ui.py'), '--port', '0'],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, text=True)
        try:
            port = int(re.search(r'127\.0\.0\.1:(\d+)', proc.stdout.readline()).group(1))
            for path in ('/', '/about', '/live', '/scorecard'):
                conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
                conn.request('GET', path)
                resp = conn.getresponse()
                body = resp.read().decode('utf-8')
                conn.close()
                self.assertEqual(resp.status, 200, path)
                if path == '/':
                    self.assertIn('Live runs are unavailable now.', body)
                if path == '/live':
                    self.assertIn('Playwright is not installed', body)
                    self.assertIn('No GEMINI_API_KEY is present in the server environment', body)
        finally:
            proc.terminate()
            proc.wait(timeout=10)



if __name__ == '__main__':
    unittest.main()

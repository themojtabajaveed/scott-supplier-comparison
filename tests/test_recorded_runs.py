"""Offline tests for the recorded-live-run playback in scripts/scout_ui.py.

Standard library only. Most tests use synthetic stand-in result files that the
test itself writes to a temporary folder (made by running the real execute_plan
on made-up page text), so they never depend on the real bundled files. One test
checks the real eval-results/live-30oct files when they are present.

Requests are made with http.client to 127.0.0.1. A socket guard blocks every
non-loopback connection, and the urllib opener is replaced so any outbound
fetch attempt from a handler is recorded and refused.
"""
import builtins
import http.client
import importlib.util
import inspect
import io
import json
import socket
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location('scout_ui_recorded', ROOT / 'scripts' / 'scout_ui.py')
ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui)


from scout.engine import atomic_run  # noqa: E402

QUESTIONS = {
    'wessex_mill': 'Compare strong white bread flour 16kg delivery conditions from Wessex',
    'cotswold': 'Compare strong white bread flour 16kg delivery conditions from Cotswold',
    'shipton_mill': 'Compare strong white bread flour 16kg delivery conditions from Shipton',
}


def marker(site):
    return 'SYNTHETIC TEST PAGE TEXT for %s: Demo strong flour 16kg £17.45.' % site


class SyntheticBrowser:
    """Serves made-up text; never touches the network."""

    def __init__(self, site):
        self.site = site

    def goto(self, url):
        self.url = url
        return url

    def text(self):
        return marker(self.site)

    def pick_evidence_link(self, missing, exclude):
        return None

    def try_select_variant(self, option):
        return False



class SyntheticLLM:
    def generate_structured(self, prompt, schema):
        return {'product_price': {'amount': {'value': '£17.45', 'quote': '16kg £17.45'}}}


def write_stand_in_results(folder):
    for site, question in QUESTIONS.items():
        plan = ui.plan_question(question)
        assert plan.state == 'ready' and [s['name'] for s in plan.workflow['sites']] == [site], plan.gaps
        result = ui.execute_plan(plan, SyntheticBrowser(site), SyntheticLLM())
        (Path(folder) / (site + '-result.json')).write_text(json.dumps(result), encoding='utf-8')


class Guarded(unittest.TestCase):
    """Starts one UI server per recorded folder, with network guards in place."""

    @classmethod
    def start(cls, recorded_dir):
        cls.outbound = []
        real_connect = socket.socket.connect

        def guarded(sock, address):
            host = address[0] if isinstance(address, tuple) else address
            if host not in ('127.0.0.1', 'localhost', '::1'):
                cls.outbound.append(address)
                raise OSError('test guard: non-loopback connection blocked')
            return real_connect(sock, address)

        def no_fetch(opener, url, *args, **kwargs):
            cls.outbound.append(getattr(url, 'full_url', url))

            raise OSError('test guard: urllib fetch blocked')

        cls.patches = [mock.patch.object(socket.socket, 'connect', guarded),
                       mock.patch.object(urllib.request.OpenerDirector, 'open', no_fetch),
                       mock.patch.object(ui.Handler, 'log_message', lambda *a: None)]
        for p in cls.patches:
            p.start()
        cls.server = ui.make_server(0, recorded_dir=recorded_dir)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        for p in reversed(cls.patches):
            p.stop()

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        headers = {'Content-Type': 'application/x-www-form-urlencoded'} if body is not None else {}
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read().decode('utf-8')
        conn.close()
        return resp.status, data


class RecordedPlayback(Guarded):
    @classmethod
    def setUpClass(cls):

        cls.tmp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.tmp.name) / 'live-30oct'
        cls.folder.mkdir()
        write_stand_in_results(cls.folder)
        cls.start(cls.folder)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.tmp.cleanup()

    def test_home_lists_the_three_recorded_sites_apart_from_the_sample_demo(self):
        status, body = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn('Recorded live runs', body)
        self.assertIn('Real, not sample data.', body)
        for site in QUESTIONS:
            self.assertIn('/recorded/' + site, body)
        self.assertNotIn(ui.BANNER, body)
        self.assertNotIn(ui.RECORDED_BANNER, body)

    def test_each_site_plays_back_with_the_recorded_banner_only(self):
        for site in QUESTIONS:
            status, body = self.request('GET', '/recorded/' + site)
            self.assertEqual(status, 200, site)
            self.assertIn(ui.RECORDED_BANNER, body)
            self.assertNotIn(ui.BANNER, body)
            self.assertNotIn('sample data', body.lower())
            self.assertNotIn('DEMO FIXTURE', body)
            self.assertIn('Engine report (recorded live run)', body)
            self.assertIn('Show all', body)  # trace behind a disclosure
            self.assertIn('£17.45', body)

            # The page text, behind a disclosure, exactly as saved in the file.
            self.assertIn('<h2>Page text Scott read</h2>', body)
            self.assertIn('<details><summary>' + site, body)
            self.assertIn(marker(site), body)
            self.assertIn('snapshot, 30 October 2026.', body)  # rebuilt from the saved rows, dated when read
            self.assertNotIn('fixed date', body)

    def test_sample_pages_never_carry_the_recorded_banner(self):
        status, body = self.request('POST', '/run', 'question=' + ui.EXAMPLES['supplier'].replace(' ', '+')
                                    + '&domain=supplier')
        self.assertEqual(status, 200)
        self.assertIn(ui.BANNER, body)
        self.assertNotIn(ui.RECORDED_BANNER, body)
        status, body = self.request('POST', '/run', 'question=weather&domain=auto')
        self.assertIn(ui.BANNER, body)
        self.assertNotIn(ui.RECORDED_BANNER, body)
        for path in ('/', '/about'):
            body = self.request('GET', path)[1]
            self.assertNotIn(ui.RECORDED_BANNER, body)

    def test_page_text_is_read_from_the_file_at_request_time(self):
        path = self.folder / 'wessex_mill-result.json'
        original = path.read_text(encoding='utf-8')
        try:
            data = json.loads(original)
            for item in data['rows'][0]['page_texts']:  # every page this stand-in run read
                item['text'] = 'EDITED SYNTHETIC TEXT'
            path.write_text(json.dumps(data), encoding='utf-8')
            body = self.request('GET', '/recorded/wessex_mill')[1]
            self.assertIn('EDITED SYNTHETIC TEXT', body)
            self.assertNotIn(marker('wessex_mill'), body)
        finally:
            path.write_text(original, encoding='utf-8')


    def test_handlers_read_only_local_recorded_files_and_never_fetch(self):
        opened = []
        real_open = io.open
        real_path_open = Path.open

        def recording_open(file, *args, **kwargs):
            if not isinstance(file, int):
                opened.append(Path(file).resolve())
            return real_open(file, *args, **kwargs)

        def recording_path_open(file, *args, **kwargs):
            # pathlib 3.10 routes Path.open through the accessor's bound io.open,
            # so patching io.open alone never sees Path.read_text calls.
            opened.append(Path(file).resolve())
            return real_path_open(file, *args, **kwargs)

        with mock.patch.object(io, 'open', recording_open), \
             mock.patch.object(builtins, 'open', recording_open), \
             mock.patch.object(Path, 'open', recording_path_open):
            for path in ['/', '/about'] + ['/recorded/' + s for s in QUESTIONS]:
                self.assertEqual(self.request('GET', path)[0], 200, path)
        folder = self.folder.resolve()
        self.assertTrue(opened)
        self.assertTrue(all(folder in p.parents for p in opened), opened)
        self.assertEqual({p.name for p in opened}, {s + '-result.json' for s in QUESTIONS})
        self.assertEqual(self.outbound, [])

    def test_unknown_names_and_path_tricks_are_not_found(self):
        for path in ('/recorded/', '/recorded/evil', '/recorded/../../etc/passwd', '/recorded/%2e%2e%2fsecrets',
                     '/recorded/wessex_mill-result.json', '/recorded/wessex_wholemeal'):
            self.assertEqual(self.request('GET', path)[0], 404, path)
        self.assertEqual(self.request('POST', '/recorded/wessex_mill', 'x=1')[0], 404)

    def test_prompt_limit_stated_on_the_page_matches_the_extractor(self):
        self.assertIn('text[:%d]' % ui.PROMPT_TEXT_LIMIT, inspect.getsource(atomic_run.extract_page))


class NoRecordedRunsBundled(Guarded):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()

        cls.start(Path(cls.tmp.name) / 'absent-folder')

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.tmp.cleanup()

    def test_missing_folder_gives_an_honest_note_not_an_error(self):
        status, body = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn('No recorded runs are bundled with this copy.', body)
        status, body = self.request('GET', '/recorded/wessex_mill')
        self.assertEqual(status, 200)
        self.assertIn('is not bundled with this copy', body)
        self.assertNotIn(ui.RECORDED_BANNER, body)
        self.assertNotIn(ui.BANNER, body)


class UnreadableRecordedFile(Guarded):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        folder = Path(cls.tmp.name)
        (folder / 'wessex_mill-result.json').write_text('not json', encoding='utf-8')
        (folder / 'cotswold-result.json').write_text('[1, 2]', encoding='utf-8')
        cls.start(folder)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.tmp.cleanup()


    def test_unreadable_files_give_an_honest_note_not_an_error(self):
        for site in ('wessex_mill', 'cotswold'):
            status, body = self.request('GET', '/recorded/' + site)
            self.assertEqual(status, 200, site)
            self.assertIn('could not be read as a saved result', body)
            self.assertNotIn(ui.RECORDED_BANNER, body)
        body = self.request('GET', '/')[1]
        self.assertNotIn('/recorded/shipton_mill', body)  # absent file is not linked


class BundledRealRecordings(Guarded):
    # The bundled recordings are the invented demo recordings (tests/demo_suppliers.py), generated by the real
    # engine over invented pages.
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / 'tests'))
        import demo_suppliers as demo
        cls._patches = [mock.patch.object(ui, 'RECORDED_SITES', [demo.ONE, demo.TWO, demo.THREE]),
                        mock.patch.object(ui, 'SITE_LABELS', dict(demo.LABELS)),
                        mock.patch.object(ui, 'RECORDED_DIR', demo.FIXTURE_DIR)]
        for p in cls._patches:
            p.start()
        cls.sites = [demo.ONE, demo.TWO, demo.THREE]
        cls.start(ui.RECORDED_DIR)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        for p in cls._patches:
            p.stop()

    def test_real_recordings_play_back_with_their_saved_page_text(self):
        for site in self.sites:
            data = json.loads((ui.RECORDED_DIR / (site + '-result.json')).read_text(encoding='utf-8'))
            status, body = self.request('GET', '/recorded/' + site)
            self.assertEqual(status, 200, site)
            self.assertIn(ui.RECORDED_BANNER, body)
            self.assertNotIn(ui.BANNER, body)
            texts = [t for row in data['rows'] for t in row.get('page_texts') or []]
            self.assertTrue(texts, site)
            self.assertEqual(body.count('<details><summary>' + site + ': <code>'), len(texts), site)
            # The saved report text still carries the old fixed date; the page says so and dates the rebuild.
            self.assertIn('27 October 2026', data['readable'])
            self.assertIn('snapshot, 30 October 2026.', body)
            self.assertIn('an older engine version printed that date', body)
        self.assertEqual(self.outbound, [])

    def test_home_shows_the_recorded_comparison_and_compare_redirects_there(self):
        status, body = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn('Recorded live runs, 30 October 2026', body)
        self.assertIn('Real, not sample data.', body)
        self.assertIn('table class="cmp"', body)
        self.assertNotIn(ui.BANNER, body)
        self.assertNotIn(ui.RECORDED_BANNER, body)  # the section carries its own label; the page has no banner
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        conn.request('GET', '/compare')
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual((resp.status, resp.getheader('Location')), (303, '/'))
        self.assertEqual(self.outbound, [])


if __name__ == '__main__':
    unittest.main()

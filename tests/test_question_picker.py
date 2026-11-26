"""Question picker on /try (2 November 2026): choices build one fixed question per domain, and the planner
still decides. Offline: one local server on 127.0.0.1 and labelled sample fixtures only.
"""
import http.client
import importlib.util
import itertools
import socket
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location('scout_ui_picker', ROOT / 'scripts' / 'scout_ui.py')
ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui)


def form(**fields):
    """Form body with repeatable keys: lists become repeated fields."""
    pairs = [('form', 'picker')]
    for key, value in fields.items():
        pairs += [(key, v) for v in (value if isinstance(value, list) else [value])]
    return urlencode(pairs)


def every_selection():
    """All picker selections: (fields, expected site or model names)."""
    sites = list(ui.PICK_SITES)
    for k in range(1, len(sites) + 1):
        for combo in itertools.combinations(sites, k):
            yield {'domain': 'supplier', 'product': 'strong_white', 'site': list(combo)}, list(combo)
    yield {'domain': 'supplier', 'product': 'wholemeal', 'site': ['wessex_mill']}, ['wessex_wholemeal']
    for k in range(1, len(ui.PICK_MODELS) + 1):
        for combo in itertools.combinations(ui.PICK_MODELS, k):
            yield {'domain': 'provider', 'model': list(combo)}, list(combo)


class Picker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        real_connect = socket.socket.connect

        def guarded(sock, address):
            host = address[0] if isinstance(address, tuple) else address
            if host not in ('127.0.0.1', 'localhost', '::1'):
                raise OSError('test guard: non-loopback connection blocked')
            return real_connect(sock, address)
        cls.runs = []
        real_execute = ui.execute_plan

        def counting(plan, browser, llm, **kwargs):
            cls.runs.append(plan.question)
            return real_execute(plan, browser, llm, **kwargs)
        cls.patches = [mock.patch.object(socket.socket, 'connect', guarded),
                       mock.patch.object(ui, 'execute_plan', counting),
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

    def setUp(self):
        self.runs.clear()

    def post(self, body):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        conn.request('POST', '/run', body=body, headers={'Content-Type': 'application/x-www-form-urlencoded'})
        resp = conn.getresponse()
        text = resp.read().decode('utf-8')
        conn.close()
        return resp.status, text

    def test_every_selection_builds_a_question_the_planner_accepts_with_exactly_those_choices(self):
        count = 0
        for fields, expected in every_selection():
            question, domain, gaps = ui.picker_question({k: v if isinstance(v, list) else [v]
                                                         for k, v in fields.items()})
            plan = ui.plan_question(question)
            self.assertEqual((plan.state, plan.domain, gaps), ('ready', domain, []), question)
            got = (plan.entities['models'] if domain == 'provider'
                   else [s['name'] for s in plan.workflow['sites']])
            self.assertEqual(got, expected, question)
            count += 1
        self.assertEqual(count, 23)

    def test_order_sent_does_not_change_the_question(self):
        a = ui.picker_question({'domain': ['supplier'], 'product': ['strong_white'],
                                'site': ['shipton_mill', 'wessex_mill']})[0]
        b = ui.picker_question({'domain': ['supplier'], 'product': ['strong_white'],
                                'site': ['wessex_mill', 'shipton_mill']})[0]
        self.assertEqual(a, b)

    def test_tampered_values_are_refused_and_nothing_runs(self):
        for body in (form(domain='supplier', product='rye', site='wessex_mill'),
                     form(domain='supplier', product='strong_white', site='wessex_wholemeal'),
                     form(domain='supplier', product='strong_white', site=['wessex_mill', 'wessex_mill']),
                     form(domain='supplier', product=['strong_white', 'wholemeal'], site='wessex_mill'),
                     form(domain='provider', model='Ministral 3 8B Batch EUR'),
                     form(domain='weather', model='Ministral 3 8B'),
                     form(product='strong_white', site='wessex_mill')):
            status, text = self.post(body)
            self.assertEqual(status, 400, body)
            self.assertIn('nothing was planned or run', text)
        self.assertEqual(self.runs, [])

    def test_empty_selection_asks_for_a_choice_and_runs_nothing(self):
        for body, gap in ((form(domain='supplier', product='strong_white'), 'Pick at least one supplier.'),
                          (form(domain='provider'), 'Pick at least one model.')):
            status, text = self.post(body)
            self.assertEqual(status, 200)
            self.assertIn(gap, text)
            self.assertIn(ui.BANNER, text)
        self.assertEqual(self.runs, [])

    def test_wholemeal_with_another_supplier_shows_the_planner_refusal(self):
        status, text = self.post(form(domain='supplier', product='wholemeal', site=['wessex_mill', 'cotswold']))
        self.assertEqual(status, 200)
        self.assertIn('Needs clarification', text)
        self.assertIn('Wholemeal supported only on Wessex', text)
        self.assertIn('Question built from your choices', text)
        self.assertEqual(self.runs, [])

    def test_picker_run_is_a_labelled_sample_run_showing_the_built_question(self):
        status, text = self.post(form(domain='supplier', product='strong_white', site=['wessex_mill', 'cotswold']))
        self.assertEqual(status, 200)
        self.assertIn(ui.BANNER, text)
        self.assertIn('Question built from your choices', text)
        self.assertIn(ui.SUPPLIER_TEMPLATE % ('strong white bread flour', 'Wessex and Cotswold'), text)
        self.assertIn('demo-mill-one.sample.example', text)
        self.assertNotIn('demo-mill-three.sample.example', text)
        self.assertEqual(len(self.runs), 1)

    def test_try_page_has_both_pickers_and_the_folded_free_text_box(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        conn.request('GET', '/try')
        text = conn.getresponse().read().decode('utf-8')
        conn.close()
        self.assertEqual(text.count('<form class="card pick" method="post" action="/run">'), 2)
        for name in ui.PICK_SITES:
            self.assertIn('name="site" value="%s" checked' % name, text)
        for model in ui.PICK_MODELS:
            self.assertIn('name="model" value="%s"' % model, text)
        self.assertIn('<details class="own" id="own">', text)  # folded unless a question is prefilled
        self.assertIn(ui.REFUSED_EXAMPLE, text)
        self.assertLess(text.index('id="pick"'), text.index('id="own"'))


if __name__ == '__main__':
    unittest.main()

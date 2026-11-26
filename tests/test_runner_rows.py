"""Offline test for scripts/run_supplier_live.py result persistence. No live execution.

The engine pieces that touch the network or a browser (scout.engine.agent,
scout.engine.browser, scout.engine.llm) are replaced by in-memory fakes for the
duration of each test, and a socket guard fails the test on any connection.
The key and project values below are placeholders that only satisfy the
script's fail-closed environment checks; the fake LLM never sends anything.
Each run reads a temporary empty usage ledger (the sanctioned zero-usage state),
never the real eval-results/live-ledger.jsonl.
"""
import contextlib
import importlib.util
import io
import itertools
import json
import os
import socket
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location('run_supplier_live', ROOT / 'scripts' / 'run_supplier_live.py')
live = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(live)
from scout import live_run  # noqa: E402

ENV = {'GEMINI_API_KEY': 'offline-test-placeholder-not-a-key',
       'SCOUT_VERIFIED_FREE_PROJECT': 'offline-test-project-placeholder'}


class FakeBrowser:
    def close(self):
        self.closed = True


class FakeLLM:
    def __init__(self, *args, **kwargs):
        self.spent = {'calls': 0, 'note': 'offline fake, nothing sent'}


def fake_engine(rows):
    agent = types.ModuleType('scout.engine.agent')
    agent.run = lambda question, wf, llm, browser, trace: rows
    browser = types.ModuleType('scout.engine.browser')
    browser.ReadOnlyBrowser = FakeBrowser
    llm = types.ModuleType('scout.engine.llm')
    llm.GeminiFree = FakeLLM
    return {'scout.engine.agent': agent, 'scout.engine.browser': browser, 'scout.engine.llm': llm}


def no_network(*args, **kwargs):
    raise OSError('test guard: network blocked')


class LiveRunnerPersistence(unittest.TestCase):
    def run_site(self, rows):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                tempfile.TemporaryDirectory() as ledger_dir, \
                mock.patch.object(live_run, 'LEDGER_PATH', Path(ledger_dir) / 'live-ledger.jsonl'), \
                mock.patch.dict(sys.modules, fake_engine(rows)), \
                mock.patch.dict(os.environ, ENV), \
                mock.patch.object(socket.socket, 'connect', no_network), \
                mock.patch.object(live.time, 'time', side_effect=itertools.count(1000, 7)), \
                contextlib.redirect_stdout(out):
            live_run.LEDGER_PATH.write_text('', encoding='utf-8')
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                live.run_site('wessex_mill')
                summary = json.loads(out.getvalue())
                with open(summary['rows_file'], encoding='utf-8') as f:
                    saved = json.load(f)
                self.assertTrue(os.path.exists(summary['trace']))
                self.assertEqual(live_run.LEDGER_PATH.read_text(encoding='utf-8'), '')  # the fake LLM wrote nothing
            finally:
                os.chdir(cwd)
        return summary, saved

    def test_rows_with_page_texts_are_written_next_to_their_trace(self):
        rows = [{'site': 'wessex_mill', 'atomic_fields': {}, 'pages_visited': ['https://example.test/p'],
                 'page_texts': [{'source_url': 'https://example.test/p', 'text': 'Synthetic page text'}]}]
        summary, saved = self.run_site(rows)
        self.assertEqual(saved, rows)  # full rows, page_texts included
        trace, rows_file = Path(summary['trace']), Path(summary['rows_file'])
        self.assertEqual(trace.parent, rows_file.parent)
        # One timestamp: the clock advances on every call, so separate calls would differ.
        self.assertEqual(trace.name.split('-')[-1].split('.')[0], rows_file.name.split('-')[-1].split('.')[0])
        self.assertEqual(summary['sites'][0]['page_texts'], 1)

    def test_summary_shows_when_rows_carry_no_page_texts(self):
        summary, saved = self.run_site([{'site': 'wessex_mill', 'atomic_fields': {}}])
        self.assertEqual(summary['sites'][0]['page_texts'], 0)


if __name__ == '__main__':
    unittest.main()
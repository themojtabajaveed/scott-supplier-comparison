"""Synthetic regression tests for two code paths whose fixtures were real recordings, which are not included.
Invented data only; no real supplier name carries invented data.

1. scout/m1_view.py: a recorded scenario whose saved quotes are removal markers is labelled "N saved quotes; text
   removed in this sanitised copy"; any real quote among them keeps the "N exact quotes" label.
2. scripts/scout_ui.py later_runs_note: a later saved run whose price or delivery-charge amounts differ is reported
   as "did not quote the same price and delivery-charge amounts; compare them yourself".
"""
import copy
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import demo_suppliers as demo  # noqa: E402
from scout import m1_view  # noqa: E402
from scout.engine import supplier_comparison as sc  # noqa: E402
from scout.workflows import supplier  # noqa: E402

_spec = importlib.util.spec_from_file_location('scout_ui_uncovered', ROOT / 'scripts' / 'scout_ui.py')
ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui)

MARKER = '[removed for publication: third-party page text, 41 chars, sha256 0123456789ab]'  # invented marker


def _observation(quote):
    return {'field': 'delivery_time', 'key': 'dispatch', 'value': 'two working days', 'quote': quote,
            'source_url': 'https://demo-mill-one.example/delivery/', 'evidence_date': '2026-10-30',
            'provenance': 'invented test observation'}


def _stub_demo(monkeypatch, quotes):
    """The M1 view's recorded scenario, fed an invented assessment of demo site one (no structured offer)."""
    real = m1_view._demo()

    class Stub:
        def __getattr__(self, name):
            return getattr(real, name)

        @staticmethod
        def recorded_bundled():
            return True

        @staticmethod
        def recorded(order, read):
            a = sc.assess_supplier(demo.ONE, [], [_observation(q) for q in quotes], order,
                                   demo.SITE[demo.ONE]['offer_binding'], read)
            return [a], sc.compare([a], order, read)

        @staticmethod
        def recorded_observations(site):
            return [_observation(q) for q in quotes]
    monkeypatch.setattr(m1_view, '_demo', lambda: Stub())


def test_recorded_quotes_that_are_all_removal_markers_are_labelled_as_removed(monkeypatch):
    _stub_demo(monkeypatch, [MARKER, MARKER])
    html = m1_view.body('recorded')
    assert 'Evidence and details (2 saved quotes; text removed in this sanitised copy)' in html


def test_a_real_quote_among_the_markers_keeps_the_exact_quotes_label(monkeypatch):
    _stub_demo(monkeypatch, [MARKER, 'We dispatch within two working days (invented).'])
    html = m1_view.body('recorded')
    assert 'Evidence and details (2 exact quotes)' in html and 'text removed in this sanitised copy' not in html


def test_a_later_run_with_different_amounts_is_reported_as_different(tmp_path, monkeypatch):
    demo.use_demo_recordings(monkeypatch, ui)
    monkeypatch.setattr(supplier, 'WORKFLOW', dict(supplier.WORKFLOW, sites=demo.SITES))
    later = json.loads((demo.FIXTURE_DIR / (demo.ONE + '-result.json')).read_text(encoding='utf-8'))
    changed = copy.deepcopy(later)
    for claim in changed['rows'][0]['atomic_fields']['product_price']['facts']['amount']:
        claim['value'] = claim['quote'] = '£12.99'  # an invented later reading that differs from £12.34
    folder = tmp_path / 'live-20261031'
    folder.mkdir()
    (folder / (demo.ONE + '-20261031T120000Z-result.json')).write_text(json.dumps(changed), encoding='utf-8')
    rows, _ = ui.recorded_rows(ui.RECORDED_DIR)
    note = ui.later_runs_note(rows, tmp_path)
    assert 'did not quote the same price and delivery-charge amounts; compare them yourself' in note
    assert 'quoted the same price and delivery-charge amounts.' not in note
    # control: the unchanged copy is reported as the same
    (folder / (demo.ONE + '-20261031T120000Z-result.json')).write_text(json.dumps(later), encoding='utf-8')
    assert 'quoted the same price and delivery-charge amounts' in ui.later_runs_note(rows, tmp_path)

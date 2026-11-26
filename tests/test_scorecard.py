"""Scorecard of saved live runs against the supplier reference file (2 November 2026).
Offline: local files only. Tests that rebuild from the YAML reference skip without PyYAML.
"""
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scout.evals import scorecard as sc  # noqa: E402

_spec = importlib.util.spec_from_file_location('scout_ui_scorecard', ROOT / 'scripts' / 'scout_ui.py')
ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui)

DATA = ui.latest_scorecard()
needs_scorecard = pytest.mark.skipif(DATA is None, reason='no scorecard bundled')

REFERENCE = {'sites': {'mill': {'url': 'https://mill.example/p', 'fields': {
    'product_price': {'value': '£10.00', 'verified': True},
    'delivery_charge': {'value': '£5.00 standard', 'verified': True,
                        'quote_source': 'https://mill.example/shipping'},
    'delivery_time': {'value': None, 'verified': False},
    'free_delivery_threshold': {'value': '£50', 'verified': True},
}}}}
RUBRIC = [{'site': 'mill', 'field': 'product_price', 'components': {'GBP_10': '£\\s*10\\.00', 'pack': '16\\s*kg'}},
          {'site': 'mill', 'field': 'delivery_charge', 'components': {'GBP_5': '£\\s*5\\.00'}},
          {'site': 'mill', 'field': 'free_delivery_threshold', 'components': {'GBP_50': '£\\s*50'}}]


def row(pages, **fields):
    return {'site': 'mill', 'pages_visited': pages, 'atomic_fields': {
        f: {'facts': {'amount': [{'value': v, 'quote': q, 'source_url': pages[0]}]}} for f, (v, q) in fields.items()}}


def outcomes(r):
    return {c['field']: (c['outcome'], c['reason']) for c in sc.score_run([r], REFERENCE, RUBRIC)['cells']}


def test_each_outcome_and_miss_reason():
    got = outcomes(row(['https://mill.example/p'], product_price=('£10.00', '16kg £10.00'),
                       free_delivery_threshold=('£60', 'over £60'), delivery_time=('2 days', '2 days')))
    assert got['product_price'] == (sc.AGREES, None)
    assert got['free_delivery_threshold'] == (sc.DISAGREES, None)
    assert got['delivery_charge'] == (sc.MISSED, sc.PAGE_NOT_READ)
    assert got['delivery_time'] == (sc.NOT_IN_REFERENCE, 'quoted_but_unchecked')
    got = outcomes(row(['https://mill.example/p', 'https://mill.example/shipping/'],
                       product_price=('£10.00', '£10.00')))
    assert got['product_price'] == (sc.PARTLY, None)  # amount right, pack size part missing
    assert got['delivery_charge'] == (sc.MISSED, sc.READ_NOT_EXTRACTED)


def test_conflicting_reference_is_unresolved_and_names_the_matched_reading():
    rubric = [{'site': 'mill', 'field': 'product_price', 'conflict': True,
               'components': {'rendered_GBP_10': '£\\s*10\\.00', 'json_GBP_11': '£\\s*11'}}]
    cell = sc.score_run([row(['https://mill.example/p'], product_price=('£10.00', '£10.00'))],
                        REFERENCE, rubric)['cells'][0]
    assert (cell['outcome'], cell['reason']) == (sc.UNRESOLVED, 'matched_readings:rendered_GBP_10')


def test_sites_a_run_did_not_target_are_not_scored_as_missed():
    assert sc.score_run([], REFERENCE, RUBRIC) == {'cells': [], 'totals': {o: 0 for o in sc.OUTCOMES}}


# These three run on the invented demo scorecard (tests/demo_suppliers.py: invented truth file, rubric and
# recordings).
def _demo():
    sys.path.insert(0, str(ROOT / 'tests'))
    import demo_suppliers
    return demo_suppliers


def test_bundled_scorecard_is_current_and_matches_a_fresh_build(monkeypatch):
    pytest.importorskip('yaml')
    demo = _demo()
    data = demo.use_demo_scorecard(monkeypatch, ui)
    assert ui.scorecard_changed_inputs(data) == []
    build = demo.demo_scorecard_builder(monkeypatch)
    assert json.loads(json.dumps(build.build(), ensure_ascii=False)) == data


def test_recorded_runs_totals_and_why_cells_were_missed(monkeypatch):
    # The invented demo scorecard (6 cells).
    data = _demo().use_demo_scorecard(monkeypatch, ui)
    run = next(r for r in data['runs'] if r['id'] == 'recorded-30oct')
    totals = {k: v for k, v in run['totals'].items() if v}
    assert totals == {sc.AGREES: 5, sc.MISSED: 1} and sum(run['totals'].values()) == len(run['cells']) == 6
    missed = [c for c in run['cells'] if c['outcome'] == sc.MISSED]
    assert {c['reason'] for c in missed} == {sc.PAGE_NOT_READ}
    assert {c['site'] for c in missed} == {'demo_mill_two'}


def test_scorecard_page_shows_every_cell_dates_caveat_and_run_links(monkeypatch):
    data = _demo().use_demo_scorecard(monkeypatch, ui)
    page = ui.scorecard_body(data)
    cells = sum(len(r['cells']) for r in data['runs'])
    assert page.count('<tr><th scope="row">') == cells
    # the demo reference and run say what they are: invented, written 25 November 2026, not research
    assert 'recorded on 25 November 2026' in page
    assert 'Invented demo recordings (synthetic, not supplier facts), undated (invented)' in page
    assert 'not research' in page and 'not' in page and 'human verification' in page
    assert 'Seeded by agent research' not in page and 'Recorded live runs' not in page
    for site in ui.RECORDED_SITES:
        assert 'href="/recorded/%s"' % site in page
    assert 'Its page (/policies/shipping-policy) was not read in this run.' in page  # the invented policy page
    assert 'no longer matches' not in page


def test_changed_inputs_are_flagged_on_the_page(monkeypatch):
    stale = copy.deepcopy(_demo().use_demo_scorecard(monkeypatch, ui))
    stale['inputs'][0]['sha256'] = '0' * 64
    assert ui.scorecard_changed_inputs(stale) == [stale['inputs'][0]['path']]
    assert 'no longer matches the files it was built from' in ui.scorecard_body(stale)


def test_home_line_appears_only_next_to_the_bundled_recordings(tmp_path, monkeypatch):
    _demo().use_demo_scorecard(monkeypatch, ui)  # invented demo recordings and scorecard
    assert 'See the scorecard' in ui.recorded_section(ui.RECORDED_DIR)
    assert '0 disagree' in ui.recorded_section(ui.RECORDED_DIR)
    (tmp_path / 'demo_mill_one-result.json').write_text(json.dumps({'rows': []}), encoding='utf-8')
    assert 'scorecard' not in ui.recorded_section(tmp_path)


def test_build_script_never_replaces_an_existing_file(tmp_path, monkeypatch):
    pytest.importorskip('yaml')
    build = _demo().demo_scorecard_builder(monkeypatch)  # the real reference file is not included
    out = tmp_path / 'scorecard.json'
    assert build.main(['--output', str(out)]) == 0
    first = out.read_bytes()
    out.write_text('keep me', encoding='utf-8')
    assert build.main(['--output', str(out)]) == 1
    assert out.read_text(encoding='utf-8') == 'keep me'
    assert json.loads(first)['runs']

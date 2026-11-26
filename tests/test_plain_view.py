"""Plain-language status words, 'how it ended' sentences and the comparison table (2 November 2026).
Offline: saved result files, labelled sample fixtures and pure functions only.
"""
import html
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scout import plain  # noqa: E402
from scout.demo_fixtures import DemoBrowser, DemoLLM, sample_plan  # noqa: E402
from scout.engine.comparison import assess_comparable  # noqa: E402
from scout.engine.planner import plan_question  # noqa: E402
from scout.engine.tool_loop import execute_plan  # noqa: E402
from scout.workflows import provider, supplier  # noqa: E402

_spec = importlib.util.spec_from_file_location('scout_ui_plain', ROOT / 'scripts' / 'scout_ui.py')
ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui)

RECORDED = {s['name']: ROOT / 'eval-results' / 'live-30oct' / (s['name'] + '-result.json')
            for s in supplier.WORKFLOW['sites']}
LATER = sorted((ROOT / 'eval-results' / 'live-20261030').glob('*-result.json'))
SAVED = [p for p in list(RECORDED.values()) + LATER if p.is_file()]
# The real recordings are not included, so the saved-result parameters run on the invented demo recordings
# (never silently empty).
SAVED = SAVED or sorted((ROOT / 'demo' / 'recordings').glob('*-result.json'))
assert SAVED, 'no saved results to parametrise over'
needs_recordings = pytest.mark.skipif(not all(p.is_file() for p in RECORDED.values()),
                                      reason='recorded live results not bundled')


def fact(value, url='https://x.example/p'):
    return {'value': value, 'quote': value, 'source_url': url}


def rows_of(path):
    return [r for r in json.loads(path.read_text(encoding='utf-8'))['rows'] if isinstance(r, dict)]


def sample_rows(question):
    plan = sample_plan(plan_question(question))
    return execute_plan(plan, DemoBrowser(plan), DemoLLM(plan), sample=True)['rows']


# -- status words --------------------------------------------------------------
@pytest.mark.parametrize('field,word', [
    ({'status': 'literal_components_present', 'facts': {'amount': [fact('£1')]}, 'missing': []}, plain.QUOTED),
    ({'status': 'incomplete', 'facts': {'amount': [fact('£1')]}, 'missing': ['vat']}, plain.PARTLY),
    ({'status': 'incomplete', 'facts': {}, 'missing': ['amount']}, plain.NOT_FOUND),
    ({'status': 'possible_numeric_disagreement', 'facts': {'amount': [fact('£1'), fact('£2')]}}, plain.DISAGREE),
    ({'status': 'source_disagreement', 'facts': {'amount': [fact('£1'), fact('£2')]}}, plain.DISAGREE),
    ({'status': 'incomplete_literal_variation', 'facts': {'variant': [fact('1KG'), fact('16kg')]}}, plain.REVIEW),
    ({'status': 'brand_new_code', 'facts': {}}, plain.UNRECOGNISED),
])
def test_every_engine_status_has_a_plain_word_and_keeps_its_code(field, word):
    status = plain.field_status(field)
    assert status['word'] == word and status['code'] == field['status']


def test_number_words_count_as_the_same_number():
    field = {'status': 'incomplete_literal_variation', 'missing': [],
             'facts': {'dispatch': [fact('within two working days'), fact('within 2 working days')]}}
    status = plain.field_status(field)
    assert status['word'] == plain.QUOTED
    assert status['notes'] == ['wording differs for dispatch time']


def test_every_field_and_claim_key_has_a_readable_name():
    for module in (supplier, provider):
        for name, claims in module.ATOMIC_FIELDS.items():
            assert name in plain.FIELD_LABELS
            for key in claims:
                assert key in plain.CLAIM_LABELS, key


def test_every_stop_reason_the_engine_can_give_has_a_sentence():
    source = (ROOT / 'scout' / 'engine' / 'tool_loop.py').read_text(encoding='utf-8')
    reasons = set(re.findall(r"reason='([a-z_]+)'", source)) | set(re.findall(r"StopBudget\('([a-z_]+)'\)", source))
    reasons |= {'provider_budget_stop', 'source_or_extraction_error'}
    assert 'page_budget' in reasons and len(reasons) >= 10
    for reason in reasons - {'page_budget'}:
        assert reason in plain.STOP_SENTENCES, reason
    assert 'does not record' in plain.how_it_ended({'pages_visited': [], 'stop_reason': None})
    assert 'does not recognise' in plain.how_it_ended({'pages_visited': [], 'stop_reason': 'brand_new'})


# -- nothing is lost -------------------------------------------------------------
@pytest.mark.parametrize('rows', [pytest.param(lambda p=p: rows_of(p), id=p.name) for p in SAVED] + [
    pytest.param(lambda: sample_rows('Compare strong white bread flour 16kg delivery'), id='sample-suppliers'),
    pytest.param(lambda: sample_rows('Compare Ministral 3 8B and gpt-6.1-sol Standard USD input and output '
                                     'prices per million tokens'), id='sample-models')])
def test_comparison_table_lists_every_quote_and_source(rows):
    rows = rows()
    page = ui.comparison_table(rows)
    count = 0
    for row in rows:
        for field in row['atomic_fields'].values():
            for label, value, quote, url in plain.quotes(field):
                assert html.escape(quote, quote=True) in page and html.escape(url, quote=True) in page
                count += 1
            assert html.escape(field['status'], quote=True) in page  # the raw engine code stays visible
    assert count and page.count('<q>') == count
    assert 'How each run ended' in page


def test_unlinked_basis_is_kept_as_a_quote_but_not_shown_as_the_charge_basis():
    field = {'status': 'incomplete', 'missing': ['basis'], 'binding_warning': 'x',
             'facts': {'amount': [fact('£3.85')], 'basis': [fact('per parcel')]}}
    assert plain.cell_values('delivery_charge', field) == [('amount', ['£3.85'])]
    assert ('charge basis', 'per parcel', 'per parcel', 'https://x.example/p') in plain.quotes(field)
    assert any('not linked' in n for n in plain.field_status(field)['notes'])


# -- the recorded comparison -----------------------------------------------------
def test_recorded_comparison_reports_real_coverage_and_why_details_are_missing():
    # The invented demo recordings (demo_mill_two stands in for the page-quoted site, demo_mill_three for
    # the store-data site). The "no delivery page was read" ending is checked on a CONSTRUCTED copy of a demo row whose
    # delivery page is removed, because today's engine always reads the configured delivery page.
    sys.path.insert(0, str(ROOT / 'tests'))
    import copy
    import demo_suppliers as demo
    rows = [r for s in (demo.ONE, demo.TWO, demo.THREE) for r in rows_of(demo.FIXTURE_DIR / (s + '-result.json'))]
    cover = dict((label, n) for label, n, total in plain.coverage(rows, list(supplier.ATOMIC_FIELDS)))
    assert cover['Price (16kg sack)'] == 3 and cover['Delivery charge'] == 1
    by_site = {r['site']: r for r in rows}
    no_delivery = copy.deepcopy(by_site[demo.TWO])
    no_delivery['pages_visited'] = no_delivery['pages_visited'][:1]
    no_delivery['page_texts'] = no_delivery['page_texts'][:1]
    assert "product data file" in plain.how_it_ended(by_site[demo.THREE])
    assert 'no delivery or shipping page was read' in plain.how_it_ended(no_delivery)
    assert plain.field_status(by_site[demo.THREE]['atomic_fields']['product_price'])['word'] == plain.REVIEW


def test_recorded_section_is_playback_with_dates_links_and_the_later_run(monkeypatch):
    sys.path.insert(0, str(ROOT / 'tests'))
    import demo_suppliers as demo
    demo.use_demo_recordings(monkeypatch, ui)  # invented demo recordings; UI wording unchanged
    # an invented later run of demo site one (demo/later-runs), found by name as a saved UI live run would be
    monkeypatch.setattr(supplier, 'WORKFLOW', dict(supplier.WORKFLOW, sites=demo.SITES))
    page = ui.recorded_section(ui.RECORDED_DIR, ROOT / 'demo' / 'later-runs')
    assert 'Recorded live runs, 30 October 2026' in page
    assert 'Price (16kg sack) quoted: 3 of 3' in page and 'Delivery charge quoted: 1 of 3' in page
    for site in (demo.ONE, demo.TWO, demo.THREE):
        assert 'href="/recorded/%s"' % site in page
    assert 'Real, not sample data.' in page
    assert 'DEMO FIXTURE' not in page and '.sample.example' not in page
    assert 'quoted the same price and delivery-charge amounts' in page  # always exercised


def test_sample_summary_shows_found_missing_and_disagreeing_words():
    page = ui.comparison_table(sample_rows('Compare strong white bread flour 16kg delivery'))
    # offer-v1: sample pages carry no structured offer record, so an agreeing price reads as not confirmed;
    # a quote-level disagreement still reads as one.
    for word in (plain.PRICE_UNCONFIRMED, plain.NOT_FOUND, plain.DISAGREE):
        assert '>%s</span>' % word in page


# -- engine note -------------------------------------------------------------------
def test_amount_only_disagreement_gets_no_wording_note():
    schema = {'amount': 'a', 'variant': 'v'}
    out = assess_comparable({'amount': [fact('£1'), fact('£2')], 'variant': [fact('16kg')]}, schema)
    assert out['status'] == 'possible_numeric_disagreement' and 'variation_note' not in out
    out = assess_comparable({'amount': [fact('£1')], 'variant': [fact('16kg'), fact('16 kg')]}, schema)
    assert 'wording' in out['variation_note']

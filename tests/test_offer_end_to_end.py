"""Offer screen offer-v1 end to end, offline: the browser's capture data path (with a fake Playwright page),
execute_plan, scout.plain and the real UI cell functions. Development fixtures only (offer_fixtures.py);
no network, no model, no live DOM. Saved evidence files are hashed before and after rendering.
"""
import hashlib
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import demo_suppliers  # noqa: E402  (test-only invented demo config)

from offer_fixtures import DEMO_TWO_URL, DEMO_THREE_URL, DEMO_ONE_URL, demo_two_raw, demo_three_raw, demo_one_raw  # noqa: E402
from scout import plain  # noqa: E402
from scout.engine import offers  # noqa: E402
from scout.engine.browser import ReadOnlyBrowser  # noqa: E402
from demo_suppliers import plan_question  # noqa: E402  (test-only: invented demo sites)
from scout.engine.tool_loop import execute_plan  # noqa: E402

_spec = importlib.util.spec_from_file_location('scout_ui_offer', ROOT / 'scripts' / 'scout_ui.py')
ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui)

QUESTION = {'demo_mill_one': 'Compare Demo Mill One (invented) strong white bread flour 16kg delivery',
            'demo_mill_two': 'Compare Demo Mill Two (invented) strong white bread flour 16kg delivery',
            'demo_mill_three': 'Compare Demo Mill Three (invented) strong white bread flour 16kg delivery'}
RAW = {'demo_mill_one': (DEMO_ONE_URL, demo_one_raw), 'demo_mill_two': (DEMO_TWO_URL, demo_two_raw),
       'demo_mill_three': (DEMO_THREE_URL, demo_three_raw)}


@pytest.fixture(autouse=True)
def fixed_read_date(monkeypatch):
    monkeypatch.setattr(offers, 'today', lambda: date(2026, 11, 22))


class FakePage:
    """Stands in for a Playwright page: evaluate returns what the DOM query would, as plain data."""
    def __init__(self, url, raw, fail=False):
        self.url, self.raw, self.fail = url, raw, fail

    def evaluate(self, script):
        assert script == ReadOnlyBrowser.STRUCTURED_QUERY
        if self.fail:
            raise RuntimeError('page closed')
        return json.loads(json.dumps(self.raw))  # the JSON-serialisable shape a real evaluate hands back


def real_capture(url, raw, fail=False):
    """ReadOnlyBrowser.structured_offers with its page replaced; no Playwright is started."""
    b = object.__new__(ReadOnlyBrowser)
    b.page = FakePage(url, raw, fail)
    return b.structured_offers()


class FakeBrowser:
    def __init__(self, page_text, raw=None, url=None, capture=True):
        self.page_text, self.raw, self.url0, self.visited = page_text, raw, url, []
        if capture:
            self.structured_offers = lambda: real_capture(self.url0 or self.visited[0], self.raw or [])

    def goto(self, url):
        self.visited.append(url)
        return url

    def text(self):
        return self.page_text if len(self.visited) == 1 else 'Later page with no details.'

    def pick_evidence_link(self, missing, exclude):
        return None

    def try_select_variant(self, option):
        return False


class FakeLLM:
    def __init__(self, first_page_claims):
        self.calls, self.claims = 0, first_page_claims

    def generate_structured(self, prompt, schema):
        self.calls += 1
        return self.claims if self.calls == 1 else {}


def run(site, page_text, claims, raw=None, capture=True):
    url, maker = RAW[site]
    plan = plan_question(QUESTION[site])
    assert plan.state == 'ready', plan.gaps
    llm = FakeLLM(claims)
    r = execute_plan(plan, FakeBrowser(page_text, maker() if raw is None else raw, url, capture), llm)
    return r, r['rows'][0], llm


def price_cells(row):
    field = row['atomic_fields']['product_price']
    return field, ui.comparison_cell('product_price', field, row), ui._cmp_cell('product_price', field, row)


# -- browser capture data path -----------------------------------------------------------------
def test_browser_capture_path_returns_only_captures_and_fails_closed():
    caps = real_capture(DEMO_THREE_URL, demo_three_raw())
    assert caps and all(isinstance(c, offers.Capture) for c in caps)
    assert {c.origin for c in caps} == {'jsonld', 'inline_script', 'option'}
    assert real_capture(DEMO_THREE_URL, demo_three_raw(), fail=True) is None
    query = ReadOnlyBrowser.STRUCTURED_QUERY
    assert "application/ld+json" in query and "productVariants" in query and 'eval(' not in query


# -- positive offers drive both the headline and the word, with or without quotes ------------
def test_structured_offer_with_no_model_price_quotes_still_shows_and_reads_matched():
    r, row, llm = run('demo_mill_one', 'Demo Strong Flour 16kg', {})
    field, cell, (word, sheet) = price_cells(row)
    assert field['facts'] == {} and field['offer']['state'] == 'confirmed'
    assert plain.field_status(field, 'product_price')['word'] == plain.OFFER_OK
    assert plain.cell_values('product_price', field)[0] == ('price', ['GBP 33.92'])
    assert 'price: GBP 33.92' in cell and 'in stock at read time' in cell and 'VAT included' in cell
    assert word == plain.OFFER_OK and '<strong>GBP 33.92</strong>' in sheet and 'Not found' not in sheet
    assert plain.quoted(field)  # counted as covered by the record, not by quotes


def test_demo_two_out_of_stock_stays_visibly_unavailable():
    r, row, llm = run('demo_mill_two', 'Demo Premium Flour SOLD OUT', {})
    field, cell, (word, sheet) = price_cells(row)
    assert field['offer']['headline']['amount'] == '47.00'
    assert plain.field_status(field, 'product_price')['word'] == plain.OFFER_OUT == word
    assert 'out of stock at read time' in cell and 'out of stock at read time' in sheet


def test_demo_three_conflict_shows_both_values_and_no_headline():
    r, row, llm = run('demo_mill_three', 'Demo Canadian-style Flour', {})
    field, cell, (word, sheet) = price_cells(row)
    assert field['offer']['state'] == 'conflicting' and plain.price_headline(field) is None
    assert word == plain.DISAGREE and '<strong>GBP' not in sheet and 'price: GBP' not in cell
    for text in (cell, sheet):
        assert 'GBP 45.60' in text and 'GBP 38.00' in text


# -- text quotes never confirm, resolve or create a conflict ------------------------------------
SYNTHETIC = ('INVENTED PAGE. Everyday Flour 1kg £2.00. Demo Strong Flour 16kg. Add to basket.')
WRONG = {'product_price': {'amount': {'value': '£2.00', 'quote': '£2.00'}, 'currency': {'value': '£', 'quote': '£2.00'},
                           'variant': {'value': '16kg', 'quote': 'Demo Strong Flour 16kg'}}}


def test_wrong_1kg_amount_with_16kg_label_is_not_found_or_confirmed_without_a_record():
    r, row, llm = run('demo_mill_one', SYNTHETIC, WRONG, raw=[])
    field, cell, (word, sheet) = price_cells(row)
    assert field['status'] == 'literal_components_present'  # the engine's literal check still passes
    assert field['offer']['state'] == 'no_structured_offer'
    assert word == plain.PRICE_UNCONFIRMED != 'Found'
    assert '<strong>£2.00</strong>' not in sheet and 'amount: £2.00' not in cell
    assert '16kg price not confirmed' in cell and '16kg price not confirmed' in sheet
    assert '£2.00' in sheet  # the quote is kept as evidence


def test_a_16kg_text_quote_with_another_amount_is_only_a_note_beside_a_confirmed_offer():
    claims = {'product_price': {'amount': {'value': '£53.90', 'quote': 'Demo Six Seed Flour 16kg £53.90'},
                                'variant': {'value': '16kg', 'quote': 'Demo Six Seed Flour 16kg £53.90'}}}
    r, row, llm = run('demo_mill_one', 'Demo Strong Flour 16kg. Demo Six Seed Flour 16kg £53.90', claims)
    field, cell, (word, sheet) = price_cells(row)
    assert field['offer']['state'] == 'confirmed' and word == plain.OFFER_OK
    assert 'not tied to this offer' in sheet and '<strong>GBP 33.92</strong>' in sheet


def test_model_output_cannot_supply_an_offer():
    forged = dict(WRONG, product_price=dict(WRONG['product_price'], offer={'value': 'GBP 2.00', 'quote': '£2.00'}))
    r, row, llm = run('demo_mill_one', SYNTHETIC, forged, raw=[])
    field = row['atomic_fields']['product_price']
    assert field['offer']['state'] == 'no_structured_offer' and plain.price_headline(field) is None


# -- budgets and run behaviour unchanged -------------------------------------------------------------
def test_capture_adds_no_model_call_page_or_tool_step():
    with_cap = run('demo_mill_two', 'Demo Premium Flour', WRONG)
    without = run('demo_mill_two', 'Demo Premium Flour', WRONG, capture=False)
    assert with_cap[2].calls == without[2].calls
    assert with_cap[1]['pages_visited'] == without[1]['pages_visited']
    assert with_cap[0]['tool_steps'] == without[0]['tool_steps']
    assert with_cap[1]['stop_reason'] == without[1]['stop_reason']
    assert without[1]['atomic_fields']['product_price']['offer']['state'] == 'no_structured_offer'


# -- recorded runs: files unchanged, original status and the re-screen kept apart ----------------------
def _hashes():
    files = sorted(p for p in demo_suppliers.FIXTURE_DIR.rglob('*') if p.is_file())  # invented recordings
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def test_recorded_runs_are_rescreened_at_render_time_without_changing_their_files(monkeypatch):
    demo_suppliers.use_demo_recordings(monkeypatch, ui)
    before = _hashes()
    home = ui.recorded_section(ui.RECORDED_DIR)
    sheet = ui.comparison_body(ui.RECORDED_DIR)
    assert _hashes() == before
    for page in (home, sheet):
        assert 'As saved (read 30 October 2026): engine status literal_components_present.' in page
        assert 'by screen offer-v1 from this run&#x27;s text evidence only' in page
        assert '<strong>£39.90</strong>' not in page and '<strong>£47.00</strong>' not in page
    assert 'Price checked against structured offer records' not in home + sheet  # nothing new applied to October


def test_sample_rows_are_never_stamped_with_a_recorded_date():
    plan = plan_question('Compare strong white bread flour 16kg delivery')
    from scout.demo_fixtures import DemoBrowser, DemoLLM, sample_plan
    plan = sample_plan(plan)
    r = execute_plan(plan, DemoBrowser(plan), DemoLLM(plan), sample=True)
    page = ui.comparison_table(r['rows'], sample=True)
    assert 'sample data, not read from any website' in page and '30 October' not in page


# -- price cell presentation (UI clarity pass): one primary state first, evidence reachable first -----------
def _before_first_disclosure(html):
    return html[:html.index('<details')] if '<details' in html else html


def test_structured_only_price_leads_with_its_state_and_its_evidence_disclosure_links_the_page():
    r, row, llm = run('demo_mill_one', 'Demo Strong Flour 16kg', {})
    field, cell, (word, sheet) = price_cells(row)
    for html in (cell, sheet):
        top = _before_first_disclosure(html)
        assert 'Offer matched' in top and 'GBP 33.92' in top
        assert 'in stock at read time' in top and 'VAT included' in top  # stock and tax stay beside the price
        assert 'literal_components_present' not in top and 'incomplete' not in top and 'Not quoted' not in top
        first = html[html.index('<details'):]
        assert first.startswith('<details class="ev"><summary>Evidence: structured offer records (1)</summary>')
        assert 'href="%s"' % DEMO_ONE_URL in first.split('</details>')[0]


def test_structured_conflict_leads_with_disagreement_and_keeps_both_records_with_sources():
    r, row, llm = run('demo_mill_three', 'Demo Canadian-style Flour', {})
    field, cell, (word, sheet) = price_cells(row)
    for html in (cell, sheet):
        top = _before_first_disclosure(html)
        assert top.index('Price records disagree (amount): no price chosen') < top.index('GBP 45.60')
        assert 'GBP 38.00' in top and '<strong>GBP' not in top
        for absent in ('Missing', 'Not quoted', 'incomplete', 'Not found'):
            assert absent not in top
        evidence = html[html.index('<details class="ev">'):].split('</details>')[0]
        assert 'GBP 45.60; from structured product data (JSON-LD)' in evidence
        assert 'GBP 38.00; from page script product list' in evidence
        assert evidence.count('href="%s"' % DEMO_THREE_URL) == 2


def test_out_of_stock_price_shows_stock_before_any_disclosure():
    r, row, llm = run('demo_mill_two', 'Demo Premium Flour', {})
    field, cell, (word, sheet) = price_cells(row)
    for html in (cell, sheet):
        top = _before_first_disclosure(html)
        assert 'Out of stock' in top and 'out of stock at read time' in top and 'VAT basis not stated' in top


def test_evidence_links_only_web_addresses_and_escapes_everything():
    r, row, llm = run('demo_mill_one', 'x', {})
    field = json.loads(json.dumps(row['atomic_fields']['product_price']))
    field['offer']['records'][0]['page_url'] = 'javascript:alert(1)'
    field['offer']['records'].append(dict(field['offer']['records'][0], page_url='https://a.example/"><script>x</script>',
                                          label='<img src=x onerror=alert(1)>'))
    for html in (ui.comparison_cell('product_price', field, row), ui._cmp_cell('product_price', field, row)[1]):
        assert 'href="javascript' not in html and '<script>' not in html and '<img' not in html
        assert 'javascript:alert(1)</code> (not a web address, so not linked)' in html


def test_recorded_price_cells_show_one_state_and_keep_codes_and_rechecks_in_the_disclosure(monkeypatch):
    demo_suppliers.use_demo_recordings(monkeypatch, ui)
    rows, links = ui.recorded_rows(ui.RECORDED_DIR)
    for row in rows:
        field = row['atomic_fields']['product_price']
        for html in (ui.comparison_cell('product_price', field, row, home=True, read_on=ui.RECORDED_DATE),
                     ui._cmp_cell('product_price', field, row)[1]):
            top = _before_first_disclosure(html)
            assert top.count('16kg price not confirmed') == 1 and 'Read 30 October 2026.' in top
            assert 'literal_components_present' not in top and 'incomplete' not in top and 'offer-v1' not in top
            assert 'As saved (read 30 October 2026)' in html and 'How this was checked' in html


def test_phone_width_rules_keep_run_facts_and_codes_inside_the_page():
    css = ui.STYLE if hasattr(ui, 'STYLE') else (ROOT / 'scripts' / 'scout_ui.py').read_text(encoding='utf-8')
    assert 'grid-template-columns:max-content minmax(0,1fr)' in css and 'dd{margin:0;min-width:0;overflow-wrap:anywhere}' in css
    assert '@media (max-width:640px){\ndl{grid-template-columns:minmax(0,1fr)}' in css
    assert 'code{overflow-wrap:anywhere}' in css

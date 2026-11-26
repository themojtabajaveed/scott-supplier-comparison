"""Store product data read in code, fetched only when the price is missing, and counted apart from the page
limit; configured same-site delivery pages (2 November 2026). Offline: replays the saved 30 October page text
through the real loop with a fake browser and a fake model that returns that run's own page-1 claims.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scout import plain  # noqa: E402
from scout.engine import store_data  # noqa: E402
from scout.engine.planner import plan_question  # noqa: E402
from scout.engine.tool_loop import execute_plan  # noqa: E402
from scout.workflows import supplier  # noqa: E402

_spec = importlib.util.spec_from_file_location('scout_ui_store', ROOT / 'scripts' / 'scout_ui.py')
ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui)

SCHEMA = supplier.ATOMIC_FIELDS['product_price']
CONFIG = {s['name']: s for s in supplier.WORKFLOW['sites']}
RECORDED = ROOT / 'eval-results' / 'live-30oct'
SHIPTON_JSON = {'title': 'Demo Canadian-style Flour (112)', 'variants': [
    {'title': '1kg', 'price': 135, 'available': True}, {'title': '16kg', 'price': 1670, 'available': True},
    {'title': '25kg', 'price': 2580, 'available': True}]}


def test_store_data_keeps_the_stores_numbers_and_adds_no_currency():
    text = store_data.format_variants(SHIPTON_JSON)
    assert '£' not in text and store_data.NO_CURRENCY_NOTE in text
    assert '16kg | 16.70 | available=True' in text.splitlines()


def test_only_the_planned_pack_line_is_read_and_quoted_verbatim():
    text = store_data.format_variants({'title': 'x', 'variants': [
        {'title': '1kg', 'price': 135, 'available': True}, {'title': '160kg', 'price': 9900, 'available': True},
        {'title': '16kg Sack', 'price': 2130, 'available': False}]})
    found, notes = store_data.read_pack(text, '16kg', 'https://s.example/p.js', SCHEMA)
    assert [{k: v['value'] for k, v in f.items()} for f in found] == [{'amount': '21.30', 'variant': '16kg Sack'}]
    assert all(v['quote'] in text and v['value'] in v['quote'] for f in found for v in f.values())
    assert 'currency' not in found[0]
    assert notes == [{'source_url': 'https://s.example/p.js', 'pack': '16kg Sack', 'available': False,
                      'quote': '16kg Sack | 21.30 | available=False'}]


class ReplayBrowser:
    """Serves the saved page-1 text; any later page has no details. Records what was asked of it."""

    def __init__(self, first_text, data=None):
        self.first_text, self.data, self.visited, self.data_asked = first_text, data, [], 0

    def goto(self, url):
        self.url = url
        self.visited.append(url)
        return url

    def text(self):
        return self.first_text if len(self.visited) == 1 else 'Synthetic later page with no details.'

    def pick_evidence_link(self, missing, exclude):
        return None  # links were not saved with the run; the configured delivery page is the fallback

    def try_select_variant(self, option):
        return False

    def fetch_variant_data(self):
        self.data_asked += 1
        return (self.url.split('?')[0] + '.js', store_data.format_variants(self.data)) if self.data else None


class ReplayLLM:
    """Returns the recorded run's own accepted claims for page 1, and nothing for any other page."""

    def __init__(self, row, first_url):
        self.calls, self.raw = 0, {}
        for field, value in row['atomic_fields'].items():
            for key, claims in value['facts'].items():
                for c in claims:
                    if c['source_url'] == first_url:
                        self.raw.setdefault(field, {})[key] = {'value': c['value'], 'quote': c['quote']}

    def generate_structured(self, prompt, schema):
        self.calls += 1
        return self.raw if self.calls == 1 else {}


def replay(site, data=None):
    path = RECORDED / (site + '-result.json')
    if not path.is_file():
        pytest.skip('recorded live results not bundled')
    row = json.loads(path.read_text(encoding='utf-8'))['rows'][0]
    first = row['page_texts'][0]
    plan = plan_question('Compare the price and delivery conditions of one 16kg sack of strong white bread flour '
                         'from ' + {'cotswold': 'Cotswold', 'shipton_mill': 'Shipton'}[site])
    browser, llm = ReplayBrowser(first['text'], data), ReplayLLM(row, first['source_url'])
    return execute_plan(plan, browser, llm), browser, llm


# These two replays run on the invented demo recordings and demo sites (tests/demo_suppliers.py), with
# the planner's site list replaced for the test only; the real supplier config is untouched. Same assertions.
def replay_demo(site, data=None):
    sys.path.insert(0, str(ROOT / 'tests'))
    import demo_suppliers as demo
    row = json.loads((demo.FIXTURE_DIR / (site + '-result.json')).read_text(encoding='utf-8'))['rows'][0]
    first = row['page_texts'][0]
    plan = plan_question('Compare the price and delivery conditions of one 16kg sack of strong white bread flour '
                         'from Wessex')
    plan.workflow = dict(plan.workflow, sites=[demo.SITE[site]])
    browser, llm = ReplayBrowser(first['text'], data), ReplayLLM(row, first['source_url'])
    return execute_plan(plan, browser, llm), browser, llm, demo.SITE[site]


def test_cotswold_price_on_the_page_means_no_store_data_and_the_delivery_page_is_read_instead():
    r, browser, llm, cfg = replay_demo('demo_mill_two', data={'title': 'x', 'variants': []})
    row = r['rows'][0]
    assert browser.data_asked == 0  # the page already quoted £14.56 with its pack
    assert row['pages_visited'] == [cfg['url'], cfg['delivery_page']]
    assert llm.calls == 2 and row['stop_reason'] == 'page_budget'
    assert row['store_data'] == {'files': [], 'packs': []}


def test_shipton_reads_store_data_in_code_then_still_reaches_its_delivery_page():
    sys.path.insert(0, str(ROOT / 'tests'))
    import demo_suppliers as demo
    r, browser, llm, cfg = replay_demo('demo_mill_three', data=demo.THREE_DATA)
    row = r['rows'][0]
    data_url = cfg['url'] + '.js'
    assert row['pages_visited'] == [cfg['url'], data_url, cfg['delivery_page']]
    assert llm.calls == 2  # page 1 and the delivery page; the data file used no model call
    price = row['atomic_fields']['product_price']['facts']
    assert [c['value'] for c in price['amount']] == ['15.67']
    assert price['amount'][0]['quote'] == '16kg | 15.67 | available=True'
    assert [c['source_url'] for c in price['currency']] == [cfg['url']]  # from the page only
    assert row['store_data']['files'] == [data_url]
    assert row['store_data']['packs'][0]['available'] is True
    ended = plain.how_it_ended(row)
    assert ended.startswith('Read 2 pages:') and 'does not count toward the page limit' in ended


def test_store_data_is_fetched_at_most_once_and_never_counted_as_a_page():
    plan = plan_question('Compare Shipton strong white bread flour 16kg delivery')
    browser = ReplayBrowser('Demo Canadian-style Flour', SHIPTON_JSON)
    r = execute_plan(plan, browser, type('Nothing', (), {'generate_structured': lambda self, p, s: {}})())
    row = r['rows'][0]
    assert browser.data_asked == 1
    assert len([p for p in row['pages_visited'] if p not in row['store_data']['files']]) == 2


def test_comparison_cell_shows_availability_and_the_missing_currency():
    row = {'site': 'shipton_mill', 'atomic_fields': {'product_price': {'status': 'incomplete', 'missing': [],
                                                                       'facts': {}}},
           'store_data': {'files': ['https://x.example/p.js'],
                          'packs': [{'pack': '16kg', 'available': False, 'quote': 'q', 'source_url': 'u'}]}}
    page = ui.comparison_table([row])
    assert 'Store data: 16kg marked not available.' in page
    assert 'Prices from store data carry no currency' in page


def test_every_configured_delivery_page_is_on_its_suppliers_own_site():
    from scout.engine.browser import safe_destination
    for site in supplier.WORKFLOW['sites']:
        assert safe_destination(site['delivery_page'], [site['url']]), site['name']

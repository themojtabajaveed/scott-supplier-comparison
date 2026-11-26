"""Settled-price routing (offer-v1.3-routing), offline. When the structured offer decision is already 'confirmed'
(in or out of stock) or 'conflicting', the price stops steering recovery so the shared budget reaches the
requested delivery evidence. Every other state keeps today's recovery. Price facts, statuses, availability,
conflicts and binding are unchanged in the result; no limit is raised and no step is made free.

Development evidence only: the offer fixtures are invented derivatives (offer_fixtures.py) and the
delivery pages and claims below are entirely invented. Nothing here is supplier policy or live accuracy.
"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import offer_fixtures as fx  # noqa: E402
from scout import plain  # noqa: E402
from scout.engine import offers, store_data  # noqa: E402
from demo_suppliers import plan_question  # noqa: E402  (test-only: invented demo sites)
from scout.engine.tool_loop import execute_plan  # noqa: E402

ALL = 'Compare strong white bread flour 16kg delivery'
ONE = {'demo_mill_one': 'Compare Demo Mill One (invented) strong white bread flour 16kg delivery',
       'demo_mill_two': 'Compare Demo Mill Two (invented) strong white bread flour 16kg delivery',
       'demo_mill_three': 'Compare Demo Mill Three (invented) strong white bread flour 16kg delivery'}
HOSTS = {'demo_mill_one': 'https://demo-mill-one.example', 'demo_mill_two': 'https://demo-mill-two.example',
         'demo_mill_three': 'https://demo-mill-three.example'}
RAW = {'demo_mill_one': fx.demo_one_raw, 'demo_mill_two': fx.demo_two_raw, 'demo_mill_three': fx.demo_three_raw}
STORE = {'demo_mill_two': {'title': 'x', 'variants': [{'title': '16kg Sack', 'price': 4700, 'available': False}]},
         'demo_mill_three': {'title': 'x', 'variants': [{'title': '16kg', 'price': 3800, 'available': True}]}}

# Entirely invented delivery text and claims (one per requested delivery part).
S1 = ('Standard delivery £9.99 per parcel including VAT to UK mainland zone A, one sack per box, no surcharge, '
      'for orders under £150')
S2 = 'Free delivery over £150 after discounts, UK mainland zone A only, up to 30kg, excluding Highlands'
S3 = 'Dispatch in 2 working days; arrival in 3-5 working days'
S4 = 'We deliver to UK mainland; not to Channel Islands; Highlands surcharge £10'
S5 = 'Sack price shown on this page £38.00'
DELIVERY_TEXT = 'INVENTED DELIVERY PAGE. ' + '. '.join((S1, S2, S3, S4, S5)) + '.'
DELIVERY_CLAIMS = {
    'delivery_charge': {k: {'value': v, 'quote': S1} for k, v in dict(
        amount='£9.99', basis='per parcel', vat='including VAT', zone='UK mainland zone A', packing='one sack per box',
        surcharge='no surcharge', order_condition='orders under £150').items()},
    'free_delivery_threshold': {k: {'value': v, 'quote': S2} for k, v in dict(
        amount='£150', comparison='over', zone='UK mainland zone A only', weight_limit='up to 30kg',
        discount_condition='after discounts', exceptions='excluding Highlands').items()},
    'delivery_time': {'dispatch': {'value': '2 working days', 'quote': S3},
                      'arrival': {'value': '3-5 working days', 'quote': S3}},
    'delivery_geography': {'included': {'value': 'UK mainland', 'quote': S4},
                           'excluded': {'value': 'Channel Islands', 'quote': S4},
                           'surcharge': {'value': 'Highlands surcharge £10', 'quote': S4}},
}
PRODUCT_TEXT = 'Invented product page. Everyday Flour 1kg £3.60. Selected 16kg £38.00.'
DISAGREEING_PRICE = {'product_price': {'amount': {'value': '£3.60', 'quote': 'Everyday Flour 1kg £3.60'}}}


@pytest.fixture(autouse=True)
def fixed_read_date(monkeypatch):
    monkeypatch.setattr(offers, 'today', lambda: date(2026, 11, 22))


def is_delivery(url):
    return any(k in url for k in ('/delivery', '/policies/', '/pages/faq'))


class Browser:
    def __init__(self, capture='fixture', select_ok=False, store=True, raw=None):
        self.url, self.site, self.select_calls, self.data_calls = None, None, 0, 0
        self.select_ok, self.raw = select_ok, raw or {}
        if capture == 'fixture':
            self.structured_offers = lambda: offers.captures_from_raw(
                (self.raw.get(self.site) or RAW[self.site])(), self.url)
        elif capture == 'failed':
            self.structured_offers = lambda: None
        if store:
            self.fetch_variant_data = self._data

    def goto(self, url):
        self.url = url
        self.site = next(name for name, host in HOSTS.items() if url.startswith(host))
        return url

    def text(self):
        return DELIVERY_TEXT if is_delivery(self.url) else PRODUCT_TEXT

    def pick_evidence_link(self, missing, exclude):
        return None

    def try_select_variant(self, option):
        self.select_calls += 1
        return self.select_ok

    def _data(self):
        self.data_calls += 1
        return (self.url + '.js', store_data.format_variants(STORE[self.site])) if self.site in STORE else None


class LLM:
    def __init__(self, product_claims=None, delivery_price=False):
        self.calls, self.product_claims, self.delivery_price = 0, product_claims or {}, delivery_price

    def generate_structured(self, prompt, schema):
        self.calls += 1
        source = next(line[len('Source: '):] for line in prompt.splitlines() if line.startswith('Source: '))
        if not is_delivery(source):
            return json.loads(json.dumps(self.product_claims))
        claims = json.loads(json.dumps(DELIVERY_CLAIMS))
        if self.delivery_price:  # a second, different quoted price: a literal disagreement with page 1
            claims['product_price'] = {'amount': {'value': '£38.00', 'quote': S5}}
        return claims


def run(question=ALL, llm=None, **browser):
    plan = plan_question(question)
    assert plan.state == 'ready', plan.gaps
    b = Browser(**browser)
    r = execute_plan(plan, b, llm or LLM())
    return r, b, {row['site']: row for row in r['rows']}


def tools(r):
    return [e['tool'] for e in r['trace'] if e['tool'] not in ('checklist', 'report', 'structured_offers')]


def html_pages(row):
    return [p for p in row['pages_visited'] if p not in row['store_data']['files']]


DELIVERY_FIELDS = ('delivery_charge', 'free_delivery_threshold', 'delivery_time', 'delivery_geography')


# -- settled prices: delivery evidence is reached within the unchanged limits ----------------------------------
@pytest.mark.parametrize('select_ok', [False, True])
def test_settled_prices_leave_the_budget_for_all_three_delivery_pages(select_ok):
    r, b, rows = run(select_ok=select_ok)
    assert r['tool_steps'] == 24 and r['generation_calls'] == 6  # the default plan's limits, reached not raised
    assert r['plan']['budgets'] == {'pages_per_site': 2, 'store_data_files_per_site': 1, 'tool_steps': 24,
                                    'generation_calls': 6}
    assert {s: rows[s]['atomic_fields']['product_price']['offer']['state'] for s in rows} == {
        'demo_mill_one': 'confirmed', 'demo_mill_two': 'confirmed', 'demo_mill_three': 'conflicting'}
    for site, row in rows.items():
        assert len(html_pages(row)) == 2 and is_delivery(html_pages(row)[1]), site
        assert row['stop_reason'] == 'other_details_quoted_price_from_structured_records', site
        assert all(row['atomic_fields'][f]['status'] == 'literal_components_present' for f in DELIVERY_FIELDS)
        assert row['store_data']['files'] == []  # no price recovery for a settled price
    assert b.select_calls == 0 and b.data_calls == 0
    assert 'select_variant' not in tools(r) and 'variant_data' not in tools(r)
    skipped = [e for e in r['trace'] if e['tool'] == 'select_variant_skipped']
    assert len(skipped) == 1 and skipped[0]['offer_state'] == 'conflicting'  # Demo Mill Three (invented) is the only planned selection
    assert 'stay unknown' in skipped[0]['why']


def test_settled_result_keeps_price_facts_status_availability_and_conflicts():
    r, b, rows = run()
    demo_mill_two = rows['demo_mill_two']['atomic_fields']['product_price']
    assert demo_mill_two['offer']['availability'] == 'unavailable' and demo_mill_two['offer']['headline']['amount'] == '47.00'
    demo_three = rows['demo_mill_three']['atomic_fields']['product_price']
    assert demo_three['offer']['conflicts'] == ['amount'] and demo_three['offer']['headline'] is None
    assert sorted(x['amount'] for x in demo_three['offer']['records']) == ['38.00', '45.60']
    for row in rows.values():  # the literal price check is reported as it is, not converted
        price = row['atomic_fields']['product_price']
        assert price['status'] == 'incomplete' and price['facts'] == {}
    # the routing decision is the result's decision: recomputing from the same captures gives the same answer
    again = offers.bind_offer(offers.captures_from_raw(fx.demo_three_raw(), fx.DEMO_THREE_URL),
                              next(s for s in r['plan']['workflow']['sites'] if s['name'] == 'demo_mill_three')['offer_binding'],
                              '16kg', date(2026, 11, 22))
    assert again == demo_three['offer']


PAGE_ONE_PRICE = {'product_price': {'amount': {'value': '£3.60', 'quote': 'Everyday Flour 1kg £3.60'}}}


@pytest.mark.parametrize('settled', [True, False])
def test_a_quoted_price_disagreement_stops_routing_only_while_the_price_is_unsettled(settled):
    raw = {} if settled else {'demo_mill_three': lambda: [fx.ld(fx.DEMO_ONE_RECOMMENDED)]}  # other product only
    r, b, rows = run(ONE['demo_mill_three'], llm=LLM(PAGE_ONE_PRICE, delivery_price=True), store=False, raw=raw)
    row = rows['demo_mill_three']
    price = row['atomic_fields']['product_price']
    assert price['offer']['state'] == ('conflicting' if settled else 'not_confirmed')
    # the disagreement is kept in the result either way, never resolved
    assert price['status'] == 'possible_numeric_disagreement' and price['conflicts']
    assert sorted(c['value'] for c in price['facts']['amount']) == ['£3.60', '£38.00']
    assert is_delivery(html_pages(row)[-1])
    assert row['stop_reason'] == ('other_details_quoted_price_from_structured_records' if settled
                                  else 'possible_numeric_disagreement')


def test_an_unsettled_disagreement_on_the_product_page_still_stops_before_the_delivery_page():
    raw = {'demo_mill_three': lambda: [fx.ld(fx.DEMO_ONE_RECOMMENDED)]}  # records of another product only: not settled
    r, b, rows = run(ONE['demo_mill_three'], llm=LLM(PAGE_ONE_PRICE), raw=raw)
    row = rows['demo_mill_three']
    assert row['atomic_fields']['product_price']['offer']['state'] == 'not_confirmed'
    assert row['store_data']['files']  # store-data recovery still ran and added its 38.00 line
    assert row['stop_reason'] == 'possible_numeric_disagreement' and len(html_pages(row)) == 1


# -- unsettled states keep today's recovery exactly ------------------------------------------------------------
UNSETTLED = {
    'no structured capture': dict(capture=None),
    'capture failed': dict(capture='failed'),
    'not_confirmed (other product only)': dict(raw={'demo_mill_three': lambda: [fx.ld(fx.DEMO_ONE_RECOMMENDED)]}),
    'unsupported (known script channel missing)': dict(raw={'demo_mill_three': lambda: fx.demo_three_raw(with_script=False)}),
}


@pytest.mark.parametrize('name', sorted(UNSETTLED))
@pytest.mark.parametrize('select_ok', [False, True])
def test_unsettled_states_route_exactly_as_without_structured_capture(name, select_ok):
    base_r, base_b, base_rows = run(ONE['demo_mill_three'], capture=None, select_ok=select_ok)
    r, b, rows = run(ONE['demo_mill_three'], select_ok=select_ok, **UNSETTLED[name])
    assert rows['demo_mill_three']['atomic_fields']['product_price']['offer']['state'] in (
        'no_structured_offer', 'not_confirmed', 'unsupported')
    assert tools(r) == tools(base_r) and r['tool_steps'] == base_r['tool_steps']
    assert r['generation_calls'] == base_r['generation_calls'] and b.select_calls == base_b.select_calls == 1
    assert b.data_calls == base_b.data_calls == 1
    a, z = rows['demo_mill_three'], base_rows['demo_mill_three']
    assert (a['pages_visited'], a['stop_reason'], a['store_data']) == (z['pages_visited'], z['stop_reason'], z['store_data'])
    assert {f: v for f, v in a['atomic_fields'].items() if f != 'product_price'} == \
        {f: v for f, v in z['atomic_fields'].items() if f != 'product_price'}
    assert {k: v for k, v in a['atomic_fields']['product_price'].items() if k != 'offer'} == \
        {k: v for k, v in z['atomic_fields']['product_price'].items() if k != 'offer'}
    assert 'select_variant_skipped' not in [e['tool'] for e in r['trace']]


def test_unsettled_selection_still_costs_the_delivery_page_within_the_unchanged_call_limit():
    raw = {'demo_mill_three': lambda: fx.demo_three_raw(with_script=False)}  # unsupported: recovery kept
    r, b, rows = run(select_ok=True, raw=raw)
    assert r['tool_steps'] <= 24 and r['generation_calls'] <= 6
    assert rows['demo_mill_three']['atomic_fields']['product_price']['offer']['state'] == 'unsupported'
    assert b.select_calls == 1 and 'select_variant' in tools(r)


# -- limits and other domains ----------------------------------------------------------------------------------
@pytest.mark.parametrize('kw', [dict(), dict(select_ok=True), dict(capture=None, select_ok=True), dict(capture='failed')])
def test_no_limit_is_exceeded(kw):
    r, b, rows = run(**kw)
    assert r['tool_steps'] <= 24 and r['generation_calls'] <= 6
    assert all(len(html_pages(row)) <= 2 and len(row['store_data']['files']) <= 1 for row in rows.values())


def test_provider_plans_never_read_offers_or_skip_anything():
    plan = plan_question('Compare Ministral 3 8B Standard USD uncached input and output per million tokens')
    assert plan.state == 'ready' and plan.domain == 'provider'

    class ProviderBrowser:
        asked = 0

        def structured_offers(self):
            ProviderBrowser.asked += 1
            return []

        def goto(self, url):
            return url

        def text(self):
            return 'Invented provider page.'

        def pick_evidence_link(self, missing, exclude):
            return None

        def try_select_variant(self, option):
            return False

    r = execute_plan(plan, ProviderBrowser(), LLM())
    assert ProviderBrowser.asked == 0
    assert 'select_variant_skipped' not in [e['tool'] for e in r['trace']]
    assert all('offer' not in f for row in r['rows'] for f in row['atomic_fields'].values())


# -- wording ---------------------------------------------------------------------------------------------------
def test_the_new_stop_sentence_separates_structured_price_evidence_from_quoted_details():
    text = plain.how_it_ended({'pages_visited': ['https://a.example/p', 'https://a.example/delivery'],
                               'stop_reason': 'other_details_quoted_price_from_structured_records'})
    assert 'structured offer records' in text and 'every other requested detail was quoted' in text
    assert 'not checked as complete' in text and 'every requested detail was quoted' not in text

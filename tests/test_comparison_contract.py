"""Thin adapter: runs the comparison layer (scout/engine/supplier_comparison.py) over the 23 reviewed development
cases in comparison_expected.json, with inputs built from comparison_fixtures.py. Offline; fake data only.

Expected values are matched as written: dict keys present in the expectation must match exactly (extra keys in the
result are allowed), lists must match item by item, and *_must_show / claim strings are exact substrings / exact
equality. Interpretations the contract leaves open are stated beside the case builder that makes them.
"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import demo_suppliers  # noqa: E402  (test-only invented demo config)

import comparison_fixtures as cf  # noqa: E402
from offer_fixtures import DEMO_TWO_16, DEMO_TWO_URL, DEMO_THREE_16, ld  # noqa: E402
from scout.engine import offers  # noqa: E402
from scout.engine import supplier_comparison as sc  # noqa: E402
from scout.workflows import supplier  # noqa: E402

EXPECTED = json.loads((ROOT / 'tests' / 'comparison_expected.json').read_text(encoding='utf-8'))
CASES = {c['id']: c for c in EXPECTED['cases']}
BINDING = {s['name']: s['offer_binding'] for s in demo_suppliers.SITES}
URL = {'demo_mill_one': cf.DEMO_ONE_URL, 'demo_mill_two': cf.DEMO_TWO_URL, 'demo_mill_three': cf.DEMO_THREE_URL}
READ = date.fromisoformat(EXPECTED['read_date'])


# Interpretation (stated, not silently chosen): "X + DEMO_ONE_OBS (charge £9.90)" uses Demo Mill One (invented)'s charge and geography
# observations but not its real over-£100 threshold, which the constructed threshold replaces. Keeping the real rule
# would make C3 qualify through it at £150, contradicting the expected abstention.
DEMO_ONE_WITHOUT_THRESHOLD = [o for o in cf.DEMO_ONE_OBS if o['field'] != 'free_delivery_threshold']


def demo_two_with_eur_conflict():
    """As in tests/test_offers.py::test_currency_tax_and_availability_disagreements_are_conflicts."""
    return cf.demo_two_raw() + [ld({'@type': 'Product', 'url': DEMO_TWO_URL, 'sku': 'DM2-16', 'offers': {
        '@type': 'Offer', 'sku': 'DM2-16', 'price': '47.00', 'priceCurrency': 'EUR',
        'availability': 'https://schema.org/OutOfStock', 'url': DEMO_TWO_URL + '?variant=' + DEMO_TWO_16}})]


def demo_two_minor_unit_only():
    """As in tests/test_offers.py::test_minor_unit_store_record_alone_gives_no_currency_and_no_headline
    (its product-shaped record, which binds identity but states no currency)."""
    raw = [r for r in cf.demo_two_raw() if r['origin'] != 'jsonld']
    variant = json.loads(raw[0]['body'])
    product = {'handle': 'demo-premium-flour-16kg', 'variants': [variant]}
    return [{'origin': 'application_json', 'body': json.dumps(product)}] + raw[2:]


def run_supplier(name, raw, observations, order, order_value=None, read=READ):
    return sc.assess_supplier(name, offers.captures_from_raw(raw, URL[name]), observations, order, BINDING[name],
                              read, order_value)


def single(case_id):
    c = CASES[case_id]
    i = c['inputs']
    order = dict(getattr(cf, i['order']) if isinstance(i.get('order'), str) else (i.get('order') or {}))
    order.setdefault('pack', '16kg')
    order.setdefault('quantity', 1)
    if 'destination' in i:
        order['destination'] = i['destination']
    raw = {'demo_one_raw()': cf.demo_one_raw, 'demo_two_raw()': cf.demo_two_raw, 'demo_two_available()': cf.demo_two_available,
           }.get(i['offer'])
    if raw is None:
        raw = demo_two_with_eur_conflict if case_id == 'C4' else demo_two_minor_unit_only
    obs = {'DEMO_ONE_OBS': cf.DEMO_ONE_OBS, 'DEMO_TWO_OBS': cf.DEMO_TWO_OBS,
           'OBS_FROM_50 + DEMO_ONE_OBS (charge £9.90)': cf.OBS_FROM_50 + DEMO_ONE_WITHOUT_THRESHOLD,
           'OBS_PRE_VAT_WITH_RATE + DEMO_ONE_OBS (charge £9.90)': cf.OBS_PRE_VAT_WITH_RATE + DEMO_ONE_WITHOUT_THRESHOLD,
           'OBS_PRE_VAT_WITH_RATE + DEMO_ONE_OBS': cf.OBS_PRE_VAT_WITH_RATE + DEMO_ONE_WITHOUT_THRESHOLD,
           'OBS_PRE_VAT_NO_RATE + DEMO_ONE_OBS': cf.OBS_PRE_VAT_NO_RATE + DEMO_ONE_WITHOUT_THRESHOLD,
           'OBS_MIN_ORDER_20 + DEMO_ONE_OBS': cf.OBS_MIN_ORDER_20 + cf.DEMO_ONE_OBS}[i['observations']]
    return run_supplier(i['supplier'], raw(), obs, order, i.get('order_value'))


SUPPLIER_INPUTS = {'demo_one_raw()': cf.demo_one_raw, 'demo_two_raw()': cf.demo_two_raw,
                   'demo_two_available()': cf.demo_two_available, 'demo_three_raw()': cf.demo_three_raw,
                   "demo_three_agreeing('45.60')": lambda: cf.demo_three_agreeing('45.60'),
                   "demo_three_agreeing('33.92')": lambda: cf.demo_three_agreeing('33.92'),
                   "demo_three_agreeing('30.00')": lambda: cf.demo_three_agreeing('30.00')}


def multi(case_id, offer_override=None):
    c = CASES[case_id]
    i = c['inputs']
    order = dict(getattr(cf, i['order']))
    read = date.fromisoformat(i.get('read_date', EXPECTED['read_date']))
    assessments = []
    for name, s in i['suppliers'].items():
        raw = (offer_override or {}).get(name) or SUPPLIER_INPUTS[s['offer']]
        obs = getattr(cf, s['observations']) if s.get('observations') else []
        assessments.append(run_supplier(name, raw(), obs, order, read=read))
    return assessments, sc.compare(assessments, order, read)


def matches(expected, actual, path='$'):
    if isinstance(expected, dict):
        assert isinstance(actual, dict), '%s: expected an object, got %r' % (path, actual)
        for k, v in expected.items():
            assert k in actual, '%s.%s missing in %r' % (path, k, actual)
            matches(v, actual[k], path + '.' + k)
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), '%s: %r != %r' % (path, actual, expected)
        for n, (e, a) in enumerate(zip(expected, actual)):
            matches(e, a, '%s[%d]' % (path, n))
    else:
        assert actual == expected, '%s: %r != %r' % (path, actual, expected)


SINGLE = [c['id'] for c in EXPECTED['cases'] if not c['id'].startswith('D')]
MULTI = [c['id'] for c in EXPECTED['cases'] if c['id'].startswith('D')]


def test_the_reference_set_has_23_cases():
    assert len(EXPECTED['cases']) == 23 and len(SINGLE) + len(MULTI) == 23


@pytest.mark.parametrize('case_id', SINGLE)
def test_single_supplier_case(case_id):
    exp = CASES[case_id]['expected']
    a = single(case_id)
    for key in ('membership', 'eligibility', 'delivery', 'offer_state'):
        if key in exp:
            matches(exp[key], a[key], key)
    if 'delivered_total' in exp:
        if exp['delivered_total'] is None:
            assert a['delivered_total'] is None, a['delivered_total']
        else:
            matches(exp['delivered_total'], a['delivered_total'], 'delivered_total')
    if 'reasoning_must_show' in exp:
        assert exp['reasoning_must_show'] in ' | '.join(a['reasoning']), a['reasoning']
    if 'wording_must_say' in exp:
        assert exp['wording_must_say'] in a['summary'], a['summary']


@pytest.mark.parametrize('case_id', MULTI)
def test_cross_supplier_case(case_id):
    exp = CASES[case_id]['expected']
    assessments, result = multi(case_id)
    matches(exp['verdict'], result['verdict'], 'verdict')
    assert result['claim'] == exp['claim_licensed']
    if 'claim_forbidden' in exp:
        assert exp['claim_forbidden'] not in result['claim']
    for name, s in CASES[case_id]['inputs']['suppliers'].items():
        a = next(x for x in assessments if x['supplier'] == name)
        if 'total' in s:
            assert a['delivered_total']['amount'] == s['total']


# -- diagnostics for the D4/D6 fixture defect (adapter-local captures, clearly not the reference fixture) --------
def demo_three_truly_agreeing(price):
    """Both Demo Mill Three (invented) price channels at the same constructed price: the JSON-LD 16kg offer is set to it as well."""
    raw = cf.demo_three_raw(price_16=price)
    product = json.loads(raw[0]['body'])
    for offer in product['offers']:
        if offer['url'].endswith(DEMO_THREE_16):
            offer['price'] = price
    raw[0] = ld(product)
    return raw


@pytest.mark.parametrize('case_id,price', [('D4', '33.92'), ('D6', '30.00')])
def test_d4_d6_logic_with_a_truly_agreeing_capture(case_id, price):
    exp = CASES[case_id]['expected']
    assessments, result = multi(case_id, {'demo_mill_three': lambda: demo_three_truly_agreeing(price)})
    matches(exp['verdict'], result['verdict'], 'verdict')
    assert result['claim'] == exp['claim_licensed']
    assert exp.get('claim_forbidden', '\0') not in result['claim']


# Guards the fixture defect found and fixed on 25 Nov 2026: demo_three_agreeing(p) once changed only the page-script
# price, leaving the JSON-LD offer at 45.60 and producing a conflicting offer for p != 22.80. The reference fixture
# must now yield a confirmed Demo Mill Three (invented) offer at exactly the D4 and D6 case prices.
@pytest.mark.parametrize('case_id,price', [('D4', '33.92'), ('D6', '30.00')])
def test_d4_d6_reference_fixture_yields_a_confirmed_demo_three(case_id, price):
    assessments, result = multi(case_id)
    demo_three = next(a for a in assessments if a['supplier'] == 'demo_mill_three')
    assert demo_three['offer_state'] == 'confirmed'
    assert demo_three['offer']['headline']['amount'] == price and demo_three['offer']['headline']['currency'] == 'GBP'
    assert 'partial' not in result['verdict']

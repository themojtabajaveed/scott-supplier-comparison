"""Adversarial adapter for tests/adversarial_expected.json (blind-written held-out set). Offline; fake data only.

Inputs come from tests/comparison_fixtures.py; each case's constructed observations are defined below and labelled
constructed. Matching rules: keys present in an expectation must match; strings under the keys 'reason',
'membership_reason', 'label' and 'caveat' must appear as substrings of the layer's text (the layer may say more);
the flags free_claim_forbidden, double_count_forbidden, silent_total_forbidden,
applied_or_abstained_with_visible_assumption and no_upper_bound_claim are checked by their meaning, documented at
each check. In set m1-adversarial-v1, H1, H3 and H10 are report-only probes: they print actual behaviour (including a
crash) and never fail; every other case asserts.
"""
import json
import sys
import traceback
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import demo_suppliers  # noqa: E402  (test-only invented demo config)

import comparison_fixtures as cf  # noqa: E402
from comparison_fixtures import constructed  # noqa: E402
from scout.engine import offers  # noqa: E402
from scout.engine import supplier_comparison as sc  # noqa: E402
from scout.workflows import supplier  # noqa: E402

SET = json.loads((ROOT / 'tests' / 'adversarial_expected.json').read_text(encoding='utf-8'))
CASES = {c['id']: c for c in SET['cases']}
READ = date.fromisoformat(SET['read_date'])
BINDING = {s['name']: s['offer_binding'] for s in demo_suppliers.SITES}
URL = {'demo_mill_one': cf.DEMO_ONE_URL, 'demo_mill_two': cf.DEMO_TWO_URL, 'demo_mill_three': cf.DEMO_THREE_URL}
PROBES = {'H1', 'H3', 'H10'} if SET['set'] == 'm1-adversarial-v1' else set()

# -- constructed observations (invented for these cases; never captured evidence) ------------------------------
H3_EXCLUSION = [constructed('free_delivery_threshold', 'excludes', 'Northern Ireland',
                            'Free delivery offer excludes Northern Ireland', cf.DEMO_ONE_DELIVERY,
                            'H3 quoted exclusion naming the destination')]
H4_SECOND_STANDARD = [constructed('delivery_charge', 'amount', '£11.90', 'Standard delivery £11.90', cf.DEMO_ONE_DELIVERY,
                                  'H4 second, disagreeing standard charge')]
H5_THRESHOLD = [constructed('free_delivery_threshold', 'amount', '£100', 'Free delivery on orders over £100',
                            cf.DEMO_THREE_URL, 'H5 threshold for an unverified basket'),
                constructed('free_delivery_threshold', 'comparison', 'over', 'Free delivery on orders over £100',
                            cf.DEMO_THREE_URL, 'H5 threshold for an unverified basket')]
H9_AMOUNTLESS = [constructed('free_delivery_threshold', 'comparison', 'qualifying', 'Free delivery on qualifying orders',
                             cf.DEMO_ONE_DELIVERY, 'H9 threshold quote with no amount')]
# H9 keeps the real Demo Mill One (invented) charge and geography quotes ("standard £9.90 still applies from the real charge quote") and
# leaves out the real over-£100 rule, as the development adapter does for constructed thresholds.
DEMO_ONE_WITHOUT_THRESHOLD = [o for o in cf.DEMO_ONE_OBS if o['field'] != 'free_delivery_threshold']

INPUTS = {
    'H1': ('demo_mill_one', cf.demo_one_raw, cf.DEMO_ONE_OBS),
    'H2': ('demo_mill_two', cf.demo_two_available, cf.DEMO_TWO_OBS),
    'H3': ('demo_mill_one', cf.demo_one_raw, cf.DEMO_ONE_OBS + H3_EXCLUSION),
    'H4': ('demo_mill_one', cf.demo_one_raw, cf.DEMO_ONE_OBS + H4_SECOND_STANDARD),
    'H5': ('demo_mill_three', cf.demo_three_raw, H5_THRESHOLD),
    'H6': ('demo_mill_one', cf.demo_one_raw, cf.DEMO_ONE_OBS),
    'H7': ('demo_mill_one', cf.demo_one_raw, cf.DEMO_ONE_OBS),
    'H8': ('demo_mill_one', cf.demo_one_raw, cf.DEMO_ONE_OBS),
    'H9': ('demo_mill_one', cf.demo_one_raw, H9_AMOUNTLESS + DEMO_ONE_WITHOUT_THRESHOLD),
    'H10': ('demo_mill_one', cf.demo_one_raw, cf.DEMO_ONE_OBS),
}


def run(case_id):
    i = CASES[case_id]['inputs']
    name, raw, obs = INPUTS[case_id]
    order = i.get('order')
    order = dict(getattr(cf, order)) if isinstance(order, str) else dict(order or {})
    order.setdefault('pack', '16kg')
    order.setdefault('quantity', 1)
    if 'destination' in i:
        order['destination'] = i['destination']
    order.setdefault('destination', 'England mainland')
    return sc.assess_supplier(name, offers.captures_from_raw(raw(), URL[name]), obs, order, BINDING[name], READ,
                              i.get('order_value'))


TEXT_KEYS = ('reason', 'membership_reason', 'label', 'caveat')


def matches(expected, actual, path='$'):
    if isinstance(expected, dict):
        assert isinstance(actual, dict), '%s: expected an object, got %r' % (path, actual)
        for k, v in expected.items():
            assert k in actual, '%s.%s missing in %r' % (path, k, actual)
            if k in TEXT_KEYS and isinstance(v, str):
                assert v in str(actual[k]), '%s.%s: %r not in %r' % (path, k, v, actual[k])
            else:
                matches(v, actual[k], path + '.' + k)
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), '%s: %r != %r' % (path, actual, expected)
        for n, (e, a) in enumerate(zip(expected, actual)):
            matches(e, a, '%s[%d]' % (path, n))
    else:
        assert actual == expected, '%s: %r != %r' % (path, actual, expected)


def total_text(a):
    t = a.get('delivered_total') or {}
    return ' | '.join([str(t.get('caveat', ''))] + [str(x) for x in t.get('caveats', []) + t.get('basis_notes', [])])


def check(case_id, a):
    exp = dict(CASES[case_id]['expected'])
    delivery = a.get('delivery') or {}
    for key in ('offer_state', 'membership'):
        if key in exp:
            assert a.get(key) == exp[key], '%s: %r != %r' % (key, a.get(key), exp[key])
    if 'membership_reason' in exp:
        assert exp['membership_reason'] in str(a.get('membership_reason')), a.get('membership_reason')
    d = dict(exp.get('delivery') or {})
    if d.pop('free_claim_forbidden', False):
        # meaning: no applied free charge, no free-threshold kind, and the summary never claims free delivery
        applied = delivery.get('applied') or {}
        assert applied.get('amount') != '0.00' and applied.get('kind') != 'free_threshold', applied
        assert 'free' not in a.get('summary', '').lower(), a.get('summary')
    if d.pop('applied_or_abstained_with_visible_assumption', False):
        # meaning: either delivery abstains naming the parcel count, or it applies with a parcel assumption shown
        if delivery.get('applied'):
            assert any('parcel' in r and 'assum' in r for r in a.get('reasoning', [])), a.get('reasoning')
        else:
            assert 'parcel' in str((delivery.get('abstained') or {}).get('reason')), delivery.get('abstained')
    if d:
        matches(d, delivery, 'delivery')
    if exp.get('silent_total_forbidden'):
        # meaning: a total may exist only if a parcel assumption is shown next to it
        if a.get('delivered_total'):
            assert 'parcel' in total_text(a), total_text(a)
    if exp.get('unevaluable_rules_reported'):
        # meaning: every quoted threshold rule the layer could not evaluate is reported with its own quote and reason;
        # H9's amountless quote must be among them
        rules = a.get('unevaluable_rules') or []
        assert rules and all(r.get('quote') and r.get('reason') for r in rules), rules
        quotes = [o['quote'] for o in INPUTS[case_id][2] if o['field'] == 'free_delivery_threshold'
                  and str(o.get('provenance', '')).startswith('constructed')]
        assert all(q in [r['quote'] for r in rules] for q in quotes), (quotes, rules)
    if exp.get('no_upper_bound_claim'):
        assert not any('upper' in k or 'bound' in k for k in a), sorted(a)
    if 'delivered_total' in exp:
        t = exp['delivered_total']
        if t is None:
            assert a.get('delivered_total') is None, a.get('delivered_total')
        else:
            t = dict(t)
            caveat, forbidden = t.pop('caveat', None), t.pop('double_count_forbidden', None)
            matches(t, a.get('delivered_total'), 'delivered_total')
            if caveat:
                assert caveat in total_text(a), total_text(a)
            if forbidden:
                assert a['delivered_total']['amount'] != forbidden


def describe(a):
    keep = ('offer_state', 'eligibility', 'membership', 'membership_reason', 'delivery', 'delivered_total', 'summary')
    return json.dumps({k: a.get(k) for k in keep}, ensure_ascii=False, default=str)


@pytest.mark.parametrize('case_id', [c['id'] for c in SET['cases']])
def test_adversarial_case(case_id):
    if case_id in PROBES:
        try:
            a = run(case_id)
            print('\nPROBE %s (report only) actual: %s' % (case_id, describe(a)))
            try:
                check(case_id, a)
                print('PROBE %s would PASS the v1 expectation' % case_id)
            except AssertionError as e:
                print('PROBE %s would FAIL the v1 expectation: %s' % (case_id, str(e)[:300]))
        except Exception:  # noqa: BLE001 - a crash is the truth being reported
            print('\nPROBE %s (report only) CRASHED:\n%s' % (case_id, traceback.format_exc(limit=3)))
        return
    a = run(case_id)
    print('\n%s actual: %s' % (case_id, describe(a)))
    check(case_id, a)

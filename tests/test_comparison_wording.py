"""Regression tests for the comparison layer's user-facing wording (25 November 2026). Offline; fixture data only.

1. Report text never shows an internal state code (for example no_structured_offer); reasons are plain language.
2. With exactly one verified supplier the claim says there is no ranking and never says "cheapest".
"""
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import demo_suppliers  # noqa: E402  (test-only invented demo config)

import comparison_fixtures as cf  # noqa: E402
from scout.engine import offers  # noqa: E402
from scout.engine import supplier_comparison as sc  # noqa: E402
from scout.workflows import supplier  # noqa: E402

READ = date(2026, 11, 22)
BINDING = {s['name']: s['offer_binding'] for s in demo_suppliers.SITES}
URL = {'demo_mill_one': cf.DEMO_ONE_URL, 'demo_mill_two': cf.DEMO_TWO_URL, 'demo_mill_three': cf.DEMO_THREE_URL}
ORDER = cf.ORDER_1_SACK_ENGLAND
# internal codes that must never reach report text
CODES = re.compile(r'no_structured_offer|not_confirmed|unsupported|offer_state|free_threshold|\bNone\b')


def assess(name, raw, obs, binding=None):
    caps = offers.captures_from_raw(raw(), URL[name]) if raw else []
    return sc.assess_supplier(name, caps, obs, ORDER, BINDING[name] if binding is None else binding, READ)


def report_text(assessments, result):
    parts = [result['claim']]
    for a in assessments:
        parts += [a['summary'], str(a['eligibility'].get('reason')), str(a.get('membership_reason'))]
    return ' | '.join(parts)


def test_no_structured_offer_reads_as_plain_language():
    a = [assess(n, None, []) for n in ('demo_mill_one', 'demo_mill_two', 'demo_mill_three')]
    result = sc.compare(a, ORDER, READ)
    assert a[0]['summary'] == 'could not be verified: no structured offer record was captured'
    # revised 25 Nov 2026 (recorded-mode wording): no implied fresh verification attempt
    assert result['claim'] == ('No comparison: the records hold no structured price for Demo Mill One (invented), Demo Mill Two (invented) or '
                               'Demo Mill Three (invented), so no price can be confirmed from them.')
    assert 'current' not in result['claim']
    assert not CODES.search(report_text(a, result)), report_text(a, result)


def test_unconfigured_binding_reads_as_plain_language():
    a = assess('demo_mill_one', cf.demo_one_raw, cf.DEMO_ONE_OBS, binding={})
    assert a['offer_state'] == 'not_confirmed'  # the code stays in structured data ...
    assert not CODES.search(report_text([a], sc.compare([a], ORDER, READ)))  # ... never in report text
    assert 'no reviewed offer binding is configured' in a['summary'], a['summary']


def test_availability_codes_are_reworded():
    unknown = sc._offer_status({'state': 'confirmed', 'availability': 'unknown'}, '16kg')
    clash = sc._offer_status({'state': 'confirmed', 'availability': 'conflicting'}, '16kg')
    missing = sc._offer_status({'state': 'confirmed'}, '16kg')
    assert unknown[1] == missing[1] == 'availability not stated'
    assert clash[1] == 'availability signals disagree'


def test_one_verified_supplier_partial_says_no_ranking():
    a = [assess('demo_mill_one', cf.demo_one_raw, cf.DEMO_ONE_OBS), assess('demo_mill_three', cf.demo_three_raw, [])]
    claim = sc.compare(a, ORDER, READ)['claim']
    assert claim == ('Only one supplier could be verified, so there is no ranking: Demo Mill One (invented) £43.82 delivered. '
                     'Demo Mill Three (invented) could not be verified: its page shows conflicting prices.')
    assert 'cheapest' not in claim.lower()


def test_one_verified_supplier_with_exclusion_says_no_ranking():
    a = [assess('demo_mill_one', cf.demo_one_raw, cf.DEMO_ONE_OBS), assess('demo_mill_two', cf.demo_two_raw, cf.DEMO_TWO_OBS)]
    claim = sc.compare(a, ORDER, READ)['claim']
    assert claim == ('Only one supplier could be verified, so there is no ranking: Demo Mill One (invented) £43.82 delivered. '
                     'Demo Mill Two (invented) excluded: 16kg unavailable.')
    assert 'cheapest' not in claim.lower()


def test_lone_supplier_says_no_ranking():
    a = [assess('demo_mill_one', cf.demo_one_raw, cf.DEMO_ONE_OBS)]
    claim = sc.compare(a, ORDER, READ)['claim']
    assert claim.startswith('Only one supplier could be verified, so there is no ranking: Demo Mill One (invented) £43.82 delivered.')
    assert 'cheapest' not in claim.lower()

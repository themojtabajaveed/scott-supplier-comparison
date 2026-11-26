from scout.engine.atomic import validate_atoms

def test_existing_unsupported_box_count_is_rejected():
 text='Charge per box: £5.10 ex VAT (£6.12 inc. VAT)'
 raw={'box_count':{'value':'each box holds one 16kg sack','quote':text}}
 r=validate_atoms(raw,['amount','box_count'],text,'https://shop.example/shipping')
 assert r['facts']=={} and r['rejected']['box_count']=='value_not_explicitly_supported_by_quote'
 assert 'box_count' in r['missing']

def test_unknown_prose_cannot_expand_schema():
 r=validate_atoms({'recommendation':{'value':'buy','quote':'buy'}},['amount'],'buy','https://x.example')
 assert r['rejected']['recommendation']=='unknown_claim_key'

def test_literal_amount_does_not_fill_missing_conditions():
 r=validate_atoms({'amount':{'value':'£6.12','quote':'£6.12 inc. VAT'}},['amount','box_count','zone'],'£6.12 inc. VAT','https://x.example')
 assert list(r['facts'])==['amount'] and r['missing']==['box_count','zone']
 assert r['facts']['amount']['status']=='literal_evidence_only'

def test_bare_tokens_is_not_million_token_basis():
 from scout.engine.atomic import assess
 e={'unit':[{'value':'Tokens','quote':'Tokens','source_url':'https://fixture.example'}]}
 r=assess(e,{'unit':'million-token basis'},{'unit':r'/\s*M\b|MTok|million|1\s*M\b'})
 assert r['status']=='incomplete' and 'unit' in r['incomplete_components']
 assert r['facts']['unit'][0]['value']=='Tokens' # preserve evidence, not silently delete

def test_complete_unit_stays_literal_not_semantically_verified():
 from scout.engine.atomic import assess
 r=assess({'unit':[{'value':'/M Tokens'}]},{'unit':'basis'},{'unit':r'/\s*M\b|million'})
 assert r['status']=='literal_components_present' and r['review_required']


# -- quoted delivery passages (isolated candidate quoted-delivery-passages-v1) ------------------------------------------
# Fake model replies only: these check host bookkeeping, not real-model completeness, token fit or injection
# resistance. Expectations below are exposed development checks reconstructed from the saved live-30oct texts by the
# implementer; they are not independent human labels, held-out cases or current policy.
import hashlib as _hashlib
import json as _json
from pathlib import Path as _Path

import pytest as _pytest

from scout.engine import atomic_run as _ar
from scout.engine.llm import BudgetExceeded as _BudgetExceeded

_ROOT = _Path(__file__).resolve().parents[1]
import sys as _sys  # noqa: E402
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
import synthetic_pages as _sp  # noqa: E402  SYNTHETIC derivatives of real-record tests not included here

# The passages tests run on invented page bodies (tests/synthetic_pages.py). Each synthetic body keeps the
# structure the assertions need; no real supplier text is used. The pinned hash now pins the synthetic body.
_WESSEX_PRODUCT_BODY_SHA = _sp.PRODUCT_BODY_SHA
_SYNTHETIC = {('wessex_mill', 1): _sp.DELIVERY_BODY, ('shipton_mill', 0): _sp.DISPATCH_BODY}


def _saved_text(site, index):
    return _SYNTHETIC[(site, index)]


def _wessex_product_body():
    body = _sp.PRODUCT_BODY
    assert _hashlib.sha256(body.encode('utf-8')).hexdigest() == _WESSEX_PRODUCT_BODY_SHA
    return body


W1, W2, W3, W4, BANNER, W7 = _sp.P1, _sp.P2, _sp.P3, _sp.P4, _sp.BANNER, _sp.D7
WESSEX_SOURCE = {'source_url': _sp.PRODUCT_URL, 'result_file': 'tests/synthetic_pages.py', 'page_index': 0}
BASIS = 'original_body'  # synthetic bodies are originals, never "recovered from a saved semantic text"


class _Fake:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.prompts = reply, error, []

    def generate_structured(self, prompt, schema):
        self.prompts.append((prompt, schema))
        if self.error:
            raise self.error
        return self.reply


def _run(items, body=None, source=None, basis=BASIS):
    body = _wessex_product_body() if body is None else body
    return _ar.extract_shipping_statements(body, source or WESSEX_SOURCE,
                                           _Fake({'shipping_statements': items}), basis)


def _covers(record, expected):
    """Exposed check: each expected passage is inside some accepted statement that is not the entire body."""
    texts = [s['text'] for s in record['statements'] if not s['is_entire_body']]
    return all(any(e in t for t in texts) for e in expected)


def test_passages_wessex_useful_positive():
    r = _run([W1, W2, W3, W4])
    assert r['execution'] == 'ok' and (r['returned_count'], r['accepted_count'], r['rejected_count']) == (4, 4, 0)
    assert [s['text'] for s in r['statements']] == [W1, W2, W3, W4]  # W2 and W3 stay separate statements
    assert all(len(s['occurrences']) == 1 for s in r['statements'])
    for s in r['statements']:
        a, b = s['occurrences'][0]
        assert r['body'][a:b] == s['text']
    assert _covers(r, [W1, W2, W3, W4])
    assert 'add a surcharge as well' in W4 and 'Regional variations' in W4
    assert set(r) == {'contract', 'prompt_version', 'execution', 'reason', 'source', 'source_url_raw',
                      'document_address', 'fragment', 'source_identity', 'body_basis', 'body', 'body_sha256',
                      'raw_output', 'returned_count', 'accepted_count', 'rejected_count', 'statements', 'rejected'}
    assert set(r['statements'][0]) == {'output_indexes', 'text', 'occurrences', 'is_entire_body'}  # no roles/regions


def test_passages_gate_rejects_empty_whole_page_and_irrelevant_output():
    body = _wessex_product_body()
    assert _run([])['execution'] == 'parsed_empty' and not _covers(_run([]), [W1])
    whole = _run([body])
    assert whole['execution'] == 'ok' and whole['statements'][0]['is_entire_body'] and not _covers(whole, [W1])
    irrelevant = _run([_sp.IRRELEVANT])
    assert irrelevant['execution'] == 'ok' and not _covers(irrelevant, [W1, W2, W3, W4])


def test_passages_repeated_banner_and_duplicate_model_strings():
    r = _run([BANNER, BANNER])
    assert r['returned_count'] == 2 and r['accepted_count'] == 1
    assert r['statements'][0]['output_indexes'] == [0, 1] and len(r['statements'][0]['occurrences']) == 2


def test_passages_equal_amounts_in_distinct_quotes_stay_separate():
    r = _run([W1, W4, BANNER])
    assert r['accepted_count'] == 3 and all('£45' in s['text'] for s in r['statements'])


def test_passages_unicode_crlf_and_overlapping_spans():
    body = '🚚 Delivery £3.85\r\nabab ababa'
    r = _ar.extract_shipping_statements(body, {'source_url': 'https://lab.example/p'},
                                        _Fake({'shipping_statements': ['£3.85\r\n', 'aba']}), 'original_body')
    assert r['statements'][0]['occurrences'] == [[11, 18]] and body[11:18] == '£3.85\r\n'
    assert r['statements'][1]['occurrences'] == [[18, 21], [23, 26], [25, 28]]


def test_passages_modified_or_unlocated_quotes_are_rejected():
    r = _run(['standard delivery costs £3.80', W1 + ' extra'])
    assert r['execution'] == 'parsed_all_rejected' and r['accepted_count'] == 0
    assert [x['reason'] for x in r['rejected']] == ['not_located', 'not_located']
    mixed = _run([W1, 'standard delivery costs £3.80'])
    assert mixed['execution'] == 'ok' and (mixed['accepted_count'], mixed['rejected_count']) == (1, 1)


def test_passages_a_valid_substring_missing_its_qualifiers_is_located_but_incomplete():
    r = _run(['Standard delivery costs £3.80'])
    assert r['execution'] == 'ok' and r['accepted_count'] == 1
    assert not _covers(r, [W1])  # incomplete against the exposed expectation; the record makes no claim either way


def test_passages_operator_or_and_may_are_kept_and_changes_rejected():
    body = _saved_text('wessex_mill', 1)  # saved body-only text (no generated annotations)
    src = {'source_url': _sp.DELIVERY_URL}
    fake = lambda items: _Fake({'shipping_statements': items})  # noqa: E731
    ok = _ar.extract_shipping_statements(body, src, fake([W7]), 'saved_body')
    assert ok['accepted_count'] == 1 and ' or ' in ok['statements'][0]['text'] and ' may ' in ok['statements'][0]['text']
    for changed in (W7.replace('may be sent', 'will be sent'), W7.replace('item or weighing', 'item and weighing')):
        assert _ar.extract_shipping_statements(body, src, fake([changed]), 'saved_body')['execution'] == \
            'parsed_all_rejected'


def test_passages_dispatch_only_and_empty_are_not_charge_answers():
    body = _saved_text('shipton_mill', 0)
    src = {'source_url': _sp.DISPATCH_URL}
    r = _ar.extract_shipping_statements(body, src, _Fake({'shipping_statements': [_sp.DISPATCH]}),
                                        'saved_body')
    assert r['execution'] == 'ok' and 'arrive' not in r['statements'][0]['text']
    empty = _ar.extract_shipping_statements(body, src, _Fake({'shipping_statements': []}), 'saved_body')
    assert empty['execution'] == 'parsed_empty' and empty['statements'] == [] and 'charge' not in _json.dumps(
        {k: v for k, v in empty.items() if k != 'body'})


@_pytest.mark.parametrize('reply,error,state', [
    ({'shipping_statements': [W1], 'source_url': 'https://evil.example'}, None, 'schema_error'),
    ({'statements': [W1]}, None, 'schema_error'),
    ({}, None, 'schema_error'),
    ({'shipping_statements': W1}, None, 'schema_error'),
    ([W1], None, 'schema_error'),
    (None, None, 'schema_error'),
    ('{"shipping_statements": [', None, 'parse_failed'),
    (None, _json.JSONDecodeError('Expecting value', 'x', 0), 'parse_failed'),
    (None, RuntimeError('transport down'), 'call_failed'),
    (None, _BudgetExceeded('calls: 9 > cap 8'), 'call_failed'),
])
def test_passages_failure_states_stay_distinct(reply, error, state):
    r = _ar.extract_shipping_statements(_wessex_product_body(), WESSEX_SOURCE, _Fake(reply, error),
                                        BASIS)
    assert r['execution'] == state and r['statements'] == [] and r['reason']
    assert r['source'] == WESSEX_SOURCE  # host identity, never model-provided


def test_passages_non_string_empty_and_whitespace_items_are_rejected():
    r = _run([7, None, '', '   \n', W1])
    assert [x['reason'] for x in r['rejected']] == ['not_a_string', 'not_a_string', 'empty_or_whitespace',
                                                     'empty_or_whitespace']
    assert r['execution'] == 'ok' and r['accepted_count'] == 1 and r['returned_count'] == 5


def test_passages_not_run_is_distinct_from_attempted_states():
    body = _wessex_product_body()
    assert _ar.extract_shipping_statements(body, WESSEX_SOURCE, None, 'saved_body')['execution'] == 'not_run'
    assert _ar.extract_shipping_statements('', WESSEX_SOURCE, _Fake({}), 'saved_body')['execution'] == 'not_run'
    bad = _ar.extract_shipping_statements(body, WESSEX_SOURCE, _Fake({}), 'capture')
    assert bad['execution'] == 'not_run' and 'body_basis' in bad['reason']


@_pytest.mark.parametrize('url,identity', [(None, 'missing'), ('', 'missing'), ('   ', 'missing'),
                                           ('#frag', 'missing'), ('https://a.example/p?x=1#f', 'recorded')])
def test_passages_source_identity_is_host_supplied_and_explicit(url, identity):
    r = _ar.extract_shipping_statements('Delivery £3.85', {'source_url': url}, _Fake({'shipping_statements': []}),
                                        'original_body')
    assert r['source_identity'] == identity and r['source_url_raw'] == url
    if identity == 'recorded':
        assert (r['document_address'], r['fragment']) == ('https://a.example/p?x=1', 'f')


def test_passages_body_hash_basis_and_separate_attempts():
    body = _wessex_product_body()
    a, b = _run([W1]), _run([W1])
    assert a['body'] is body or a['body'] == body
    assert a['body_sha256'] == _WESSEX_PRODUCT_BODY_SHA and a['body_basis'] == BASIS
    assert a is not b and a['statements'] == b['statements']  # two attempts give two records; nothing is merged
    assert not any(k in a for k in ('captured_at', 'capture_sha256', 'read_date'))  # no capture provenance claimed


def test_passages_candidate_is_isolated_and_legacy_paths_unchanged():
    callers = [p for p in (_ROOT / 'scout').rglob('*.py') if 'extract_shipping_statements' in p.read_text(encoding='utf-8')]
    callers += [p for p in (_ROOT / 'scripts').rglob('*.py') if 'extract_shipping_statements' in p.read_text(encoding='utf-8')]
    assert [p.name for p in callers] == ['atomic_run.py']
    assert _ar.make_response_schema({'f': {'amount': 'x'}}) == {'type': 'object', 'properties': {'f': {
        'type': 'object', 'properties': {'amount': {'type': 'object', 'properties': {'value': {'type': 'string'},
                                                                                     'quote': {'type': 'string'}},
                                                    'required': ['value', 'quote'], 'additionalProperties': False}},
        'additionalProperties': False}}, 'additionalProperties': False}
    for site in ('demo_mill_one', 'demo_mill_two', 'demo_mill_three'):  # invented demo recordings
        row = _json.loads((_ROOT / ('demo/recordings/%s-result.json' % site)).read_text())['rows'][0]
        assert 'shipping_statements' not in row  # history records no attempt; absence is not "never attempted"


# -- v1.6.1 corrections --------------------------------------------------------------------------------------------
def test_passages_a_generic_client_value_error_is_a_call_failure_not_a_parse_failure():
    r = _ar.extract_shipping_statements(_wessex_product_body(), WESSEX_SOURCE, _Fake(error=ValueError('bad argument')),
                                        BASIS)
    assert r['execution'] == 'call_failed' and r['reason'].startswith('ValueError: bad argument')
    decode = _ar.extract_shipping_statements(_wessex_product_body(), WESSEX_SOURCE,
                                             _Fake(error=_json.JSONDecodeError('Expecting value', 'x', 0)),
                                             BASIS)
    assert decode['execution'] == 'parse_failed' and decode['reason'].startswith('JSONDecodeError')


def test_passages_mixed_type_unknown_keys_are_a_schema_error_without_raising():
    reply = {'shipping_statements': [W1], 1: 'x', 'zone': 'y'}
    r = _ar.extract_shipping_statements(_wessex_product_body(), WESSEX_SOURCE, _Fake(reply),
                                        BASIS)
    assert r['execution'] == 'schema_error' and r['statements'] == []
    assert '1' in r['reason'] and "'zone'" in r['reason']


def test_passages_root_string_replies_reviewer_expectation_corrected():
    # Not a product change: an unparseable string reply is parse_failed, a parsed JSON string is schema_error.
    run = lambda reply: _ar.extract_shipping_statements(_wessex_product_body(), WESSEX_SOURCE, _Fake(reply),  # noqa
                                                        BASIS)['execution']
    assert run('not json at all') == 'parse_failed'
    assert run('"a JSON string"') == 'schema_error'

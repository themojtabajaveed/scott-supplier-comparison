"""Structured offer screen offer-v1: normalisation and binding (pure, offline). Development cases only:
the three supplier fixtures are invented derivatives of development findings (see offer_fixtures.py), not held-out.
"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import demo_suppliers  # noqa: E402  (test-only invented demo config)

from offer_fixtures import (DEMO_TWO_16, DEMO_TWO_URL, DEMO_THREE_16, DEMO_THREE_URL, DEMO_ONE_PRODUCT,  # noqa: E402
                            DEMO_ONE_RECOMMENDED, DEMO_ONE_URL, demo_two_raw, ld, option, demo_three_raw, demo_one_raw)
from scout.engine import offers  # noqa: E402
from scout.workflows import supplier  # noqa: E402

BIND = {s['name']: s['offer_binding'] for s in demo_suppliers.SITES}
READ = date(2026, 11, 22)


def decide(raw, site, url, pack='16kg', read_date=READ, binding=None):
    return offers.bind_offer(offers.captures_from_raw(raw, url), binding or BIND[site], pack, read_date)


# -- positive supported offers --------------------------------------------------------------
def test_demo_one_single_offer_is_confirmed_with_vat_and_validity_and_ignores_the_recommended_16kg_product():
    d = decide(demo_one_raw(), 'demo_mill_one', DEMO_ONE_URL)
    assert d['state'] == 'confirmed', d['reasons']
    assert d['headline'] == {'amount': '33.92', 'currency': 'GBP', 'pack': '16kg', 'sku': 'DM1-16', 'variant_id': None}
    assert d['availability'] == 'available' and d['vat_included'] is True and d['valid_until'] == '2026-11-23'
    assert d['ignored'] == 1 and all(r['amount'] != '53.90' for r in d['records'])


def test_demo_two_is_confirmed_but_unavailable_with_three_agreeing_signals_and_one_deduplicated_copy():
    d = decide(demo_two_raw(), 'demo_mill_two', DEMO_TWO_URL)
    assert d['state'] == 'confirmed' and d['headline']['amount'] == '47.00' and d['headline']['currency'] == 'GBP'
    assert d['headline']['variant_id'] == DEMO_TWO_16
    assert d['availability'] == 'unavailable'
    assert sorted(s['origin'] for s in d['availability_signals']) == ['application_json', 'jsonld', 'option']
    assert sorted(r['origin'] for r in d['records']) == ['application_json', 'jsonld']  # quick-view copy is one
    store = next(r for r in d['records'] if r['origin'] == 'application_json')
    assert store['currency'] is None and store['minor_units'] is True  # corroborates, never supplies currency
    assert d['vat_included'] is None  # store 'taxable' is not read as a VAT basis


def test_availability_unknown_stays_unknown_on_a_confirmed_price():
    product = json.loads(json.dumps(DEMO_ONE_PRODUCT))
    del product['offers'][0]['availability']
    d = decide([ld(product)], 'demo_mill_one', DEMO_ONE_URL)
    assert d['state'] == 'confirmed' and d['availability'] == 'unknown'


# -- conflicts: no record wins ----------------------------------------------------------------
def test_demo_three_jsonld_and_page_script_disagree_so_there_is_no_headline():
    d = decide(demo_three_raw(), 'demo_mill_three', DEMO_THREE_URL)
    assert d['state'] == 'conflicting' and d['headline'] is None and d['conflicts'] == ['amount']
    assert sorted((r['origin'], r['amount']) for r in d['records']) == [('inline_script', '38.00'), ('jsonld', '45.60')]
    assert all(r['amount'] != '60.00' for r in d['records'])  # recommended product's 16kg variant ignored


def test_demo_three_without_its_known_script_channel_is_unsupported_not_22_80():
    d = decide(demo_three_raw(with_script=False), 'demo_mill_three', DEMO_THREE_URL)
    assert d['state'] == 'unsupported' and d['headline'] is None
    assert any('inline_script' in r for r in d['reasons'])


def test_demo_three_agreeing_channels_would_confirm():  # positive control for the variant-product path
    d = decide(demo_three_raw(price_16='45.60'), 'demo_mill_three', DEMO_THREE_URL)
    assert d['state'] == 'confirmed' and d['headline']['amount'] == '45.60' and d['headline']['variant_id'] == DEMO_THREE_16


def _demo_two_with(**changes):
    raw = demo_two_raw()
    product = json.loads(raw[0]['body'])
    product['offers'][0].update(changes)
    raw[0] = ld(product)
    return raw


def test_currency_tax_and_availability_disagreements_are_conflicts():
    raw = demo_two_raw() + [ld({'@type': 'Product', 'url': DEMO_TWO_URL, 'sku': 'DM2-16', 'offers': {
        '@type': 'Offer', 'sku': 'DM2-16', 'price': '47.00', 'priceCurrency': 'EUR',
        'availability': 'https://schema.org/OutOfStock', 'url': DEMO_TWO_URL + '?variant=' + DEMO_TWO_16}})]
    assert 'currency' in decide(raw, 'demo_mill_two', DEMO_TWO_URL)['conflicts']
    w1, w2 = json.loads(json.dumps(DEMO_ONE_PRODUCT)), json.loads(json.dumps(DEMO_ONE_PRODUCT))
    w2['offers'][0]['priceSpecification'][0]['valueAddedTaxIncluded'] = 'false'
    w2['offers'][0]['url'] = DEMO_ONE_URL  # same offer
    d = decide([ld(w1), ld(w2)], 'demo_mill_one', DEMO_ONE_URL)
    assert d['state'] == 'conflicting' and 'tax basis' in d['conflicts']
    d = decide(_demo_two_with(availability='https://schema.org/InStock'), 'demo_mill_two', DEMO_TWO_URL)
    assert d['state'] == 'conflicting' and d['conflicts'] == ['availability'] and d['headline'] is None


def test_was_and_now_prices_for_one_variant_are_a_conflict():
    raw = demo_two_raw() + [ld({'@type': 'Product', 'url': DEMO_TWO_URL, 'sku': 'DM2-16', 'offers': {
        '@type': 'Offer', 'sku': 'DM2-16', 'price': '25.00', 'priceCurrency': 'GBP',
        'availability': 'https://schema.org/OutOfStock', 'url': DEMO_TWO_URL + '?variant=' + DEMO_TWO_16}})]
    d = decide(raw, 'demo_mill_two', DEMO_TWO_URL)
    assert d['state'] == 'conflicting' and 'amount' in d['conflicts']


# -- identity and pack failures -----------------------------------------------------------------
def test_only_a_recommended_product_on_the_page_is_not_confirmed():
    assert decide([ld(DEMO_ONE_RECOMMENDED)], 'demo_mill_one', DEMO_ONE_URL)['state'] == 'not_confirmed'


def test_sku_or_path_mismatch_is_not_confirmed_and_titles_never_prove_identity():
    p = json.loads(json.dumps(DEMO_ONE_PRODUCT)); p['sku'] = 'DM1-1.5'
    assert decide([ld(p)], 'demo_mill_one', DEMO_ONE_URL)['state'] == 'not_confirmed'
    p = json.loads(json.dumps(DEMO_ONE_PRODUCT)); p['url'] = p['offers'][0]['url'] = 'https://demo-mill-one.example/product/other-16kg/'
    assert decide([ld(p)], 'demo_mill_one', DEMO_ONE_URL)['state'] == 'not_confirmed'
    p = json.loads(json.dumps(DEMO_ONE_PRODUCT)); del p['url']; del p['offers'][0]['url']
    p['name'] = 'Demo Strong Flour 16kg'  # exact-looking title, no path: still not identity
    assert decide([ld(p)], 'demo_mill_one', DEMO_ONE_URL)['state'] == 'not_confirmed'


def test_a_single_offer_product_listing_two_offers_is_not_confirmed():
    p = json.loads(json.dumps(DEMO_ONE_PRODUCT))
    p['offers'].append(dict(p['offers'][0], price='2.20', url=DEMO_ONE_URL + '?size=1kg'))
    d = decide([ld(p)], 'demo_mill_one', DEMO_ONE_URL)
    assert d['state'] == 'not_confirmed' and d['headline'] is None


def test_two_variant_ids_labelled_16kg_or_one_id_with_two_pack_labels_is_not_confirmed():
    raw = demo_two_raw() + [option('90000000000209', '16kg Sack (organic)')]
    product = json.loads(raw[0]['body'])
    product['offers'].append({'@type': 'Offer', 'sku': 'DM2-16', 'price': '27.00', 'priceCurrency': 'GBP',
                              'url': DEMO_TWO_URL + '?variant=90000000000209'})
    raw[0] = ld(product)
    assert decide(raw, 'demo_mill_two', DEMO_TWO_URL)['state'] == 'not_confirmed'
    raw = demo_two_raw() + [option(DEMO_TWO_16, '1 Bag - 1.5kg')]
    d = decide(raw, 'demo_mill_two', DEMO_TWO_URL)
    assert d['state'] == 'not_confirmed' and any('different pack' in r for r in d['reasons'])


def test_minor_unit_store_record_alone_gives_no_currency_and_no_headline():
    raw = [r for r in demo_two_raw() if r['origin'] != 'jsonld']
    d = decide(raw, 'demo_mill_two', DEMO_TWO_URL)  # a bare variant record states no product path: no identity
    assert d['state'] == 'not_confirmed' and d['records'] == []
    variant = json.loads(raw[0]['body'])
    product = {'handle': 'demo-premium-flour-16kg', 'variants': [variant]}
    raw = [{'origin': 'application_json', 'body': json.dumps(product)}] + raw[2:]
    d = decide(raw, 'demo_mill_two', DEMO_TWO_URL)  # product-shaped record with its handle: identity, but no currency
    assert d['state'] == 'not_confirmed' and d['headline'] is None and any('currency' in r for r in d['reasons'])


def test_unconfigured_source_or_other_pack_is_not_confirmed():
    assert decide(demo_one_raw(), 'demo_mill_one', DEMO_ONE_URL, pack='1.5kg')['state'] == 'not_confirmed'
    assert offers.bind_offer(offers.captures_from_raw(demo_one_raw(), DEMO_ONE_URL), None, '16kg', READ)['state'] == 'not_confirmed'


def test_expired_or_uncheckable_validity_blocks_the_headline():
    d = decide(demo_one_raw(), 'demo_mill_one', DEMO_ONE_URL, read_date=date(2026, 11, 24))
    assert d['state'] == 'not_confirmed' and d.get('expired') is True
    d = decide(demo_one_raw(), 'demo_mill_one', DEMO_ONE_URL, read_date=None)
    assert d['state'] == 'not_confirmed' and d['headline'] is None


# -- fail closed on capture limits and unreadable values ------------------------------------------
def test_capture_truncation_and_oversized_bodies_are_unsupported():
    filler = [option(str(i), 'x') for i in range(offers.MAX_CAPTURES)]
    d = decide(demo_one_raw() + filler, 'demo_mill_one', DEMO_ONE_URL)  # the matching offer is early; later ones dropped
    assert d['state'] == 'unsupported' and d['headline'] is None
    big = {'origin': 'inline_script', 'body': 'x' * (offers.MAX_BODY + 1)}
    assert decide(demo_one_raw() + [big], 'demo_mill_one', DEMO_ONE_URL)['state'] == 'unsupported'


def test_malformed_json_and_escaped_script_channels_are_unsupported():
    assert decide(demo_one_raw() + [{'origin': 'jsonld', 'body': '{"@type": "Product",'}],
                  'demo_mill_one', DEMO_ONE_URL)['state'] == 'unsupported'
    escaped = {'origin': 'inline_script', 'body': 'init("{\\"productVariants\\":[{\\"id\\":\\"1\\"}]}")'}
    assert decide(demo_three_raw() + [escaped], 'demo_mill_three', DEMO_THREE_URL)['state'] == 'unsupported'


def test_extreme_numbers_fail_safely():
    for bad in ('1e999999999', 'NaN', 'Infinity', '-1', '12abc', 10 ** 30, [1], {'a': 1}):
        p = json.loads(json.dumps(DEMO_ONE_PRODUCT))
        p['offers'][0]['price'] = bad
        d = decide([ld(p)], 'demo_mill_one', DEMO_ONE_URL)
        assert d['state'] == 'unsupported' and d['headline'] is None, bad
        json.dumps(d)  # the decision stays serialisable


# -- provenance ------------------------------------------------------------------------------------
def test_only_browser_built_captures_count():
    as_dicts = [dict(r, page_url=DEMO_ONE_URL) for r in demo_one_raw()]
    records, opts, problems = offers.normalise(as_dicts)  # plain dicts (e.g. from a saved file or model) ignored
    assert records == [] and opts == [] and problems == []
    looks_like = offers.Capture(origin='page_text', page_url=DEMO_ONE_URL, body=json.dumps(DEMO_ONE_PRODUCT))
    assert offers.normalise([looks_like]) == ([], [], [])
    assert offers.captures_from_raw([{'origin': 'model', 'body': json.dumps(DEMO_ONE_PRODUCT)}], DEMO_ONE_URL) == []


# -- parent/child SKU join (offer-v1.1). The conflict case below is the reviewer's withheld supplemental case
# that offer-v1 failed (7 of 8), reconstructed from the reviewer's description after it was exposed: it is a
# regression case now, never held-out evidence. Synthetic product; not a supplier quote. ----------------------
STONE_URL = 'https://shop.example/products/stonebread-16kg'
STONE_BIND = {'product_path': '/products/stonebread-16kg', 'sku': 'STONE', 'pack': '16kg'}


def stone_raw(variant_price=2915, variant_id='8112', variant_sku='STONE16', variant_path=None, offer_sku=None):
    offer = {'@type': 'Offer', 'price': '29.15', 'priceCurrency': 'GBP', 'availability': 'https://schema.org/InStock',
             'url': STONE_URL + '?variant=8112'}
    if offer_sku:
        offer['sku'] = offer_sku
    variant = {'id': int(variant_id), 'title': '16kg Sack', 'sku': variant_sku, 'price': variant_price,
               'available': True}
    body = ({'handle': variant_path, 'variants': [variant]} if variant_path else variant)
    return [ld({'@type': 'Product', 'name': 'Stonebread Flour', 'sku': 'STONE', 'url': STONE_URL, 'offers': offer}),
            option('8112', '16kg Sack'),
            {'origin': 'application_json', 'body': json.dumps(body)}]


def stone(raw):
    return offers.bind_offer(offers.captures_from_raw(raw, STONE_URL), STONE_BIND, '16kg', READ)


def test_exposed_case_same_variant_record_with_child_sku_and_other_price_is_a_conflict():
    d = stone(stone_raw(variant_price=2615))
    assert d['state'] == 'conflicting' and d['headline'] is None and d['conflicts'] == ['amount']
    assert sorted(r['amount'] for r in d['records']) == ['26.15', '29.15']


def test_counterpart_same_variant_record_with_child_sku_and_equal_price_stays_confirmed():
    d = stone(stone_raw(variant_price=2915))
    assert d['state'] == 'confirmed' and d['headline']['amount'] == '29.15' and d['headline']['variant_id'] == '8112'
    assert sorted(r['origin'] for r in d['records']) == ['application_json', 'jsonld']


def test_guard_another_variant_id_is_not_joined():
    d = stone(stone_raw(variant_price=2615, variant_id='9999'))  # same title and pack label, different variant
    assert d['state'] == 'confirmed' and d['headline']['amount'] == '29.15'
    assert all(r['variant_id'] == '8112' for r in d['records'])


def test_guard_another_product_path_is_not_joined_and_claiming_this_variant_is_a_conflict():
    d = stone(stone_raw(variant_price=2615, variant_id='9999', variant_path='other-flour-16kg'))
    assert d['state'] == 'confirmed' and d['headline']['amount'] == '29.15'  # other product, other variant: ignored
    d = stone(stone_raw(variant_price=2915, variant_path='other-flour-16kg'))
    assert d['state'] == 'conflicting' and 'product identity' in d['conflicts'] and d['headline'] is None


def test_guard_two_child_skus_for_one_variant_id_are_a_conflict():
    d = stone(stone_raw(variant_price=2915, offer_sku='STONE16', variant_sku='STONE17'))
    assert d['state'] == 'conflicting' and d['conflicts'] == ['variant SKU']


def test_guard_parent_sku_does_not_bind_other_packs_or_names():
    raw = stone_raw() + [option('8113', '1kg Bag'),
                         {'origin': 'application_json', 'body': json.dumps(
                             {'id': 8113, 'title': '1kg Bag', 'sku': 'STONE1', 'price': 315, 'available': True})},
                         ld({'@type': 'Product', 'name': 'Stonebread Flour 16kg', 'offers': {
                             '@type': 'Offer', 'price': '12.00', 'priceCurrency': 'GBP'}})]  # name only, no path
    d = stone(raw)
    assert d['state'] == 'confirmed' and d['headline']['amount'] == '29.15'
    assert {r['variant_id'] for r in d['records']} == {'8112'}

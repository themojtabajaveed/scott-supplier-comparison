"""Held-out comparability cases (25 November 2026). Offline; every input here is CONSTRUCTED (invented mills on
reserved .example addresses), never captured evidence.

Rule under test: a ranking among verified suppliers needs a known, normalised, same cost basis.
- The product-price VAT basis and the delivery-charge VAT basis must be known; a free delivery has none to know.
- A mix of inclusive and exclusive VAT may rank only when a rate is quoted, so that the conversion is grounded.
- The order need must be the same: equivalent pack (equivalent strings allowed), quantity, destination, and GBP.
Otherwise the claim must not rank, and each supplier's delivered total is listed with its basis labels.
"""
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scout.engine import offers  # noqa: E402
from scout.engine import supplier_comparison as sc  # noqa: E402

READ = date(2026, 11, 25)
ORDER = {'pack': '16kg', 'quantity': 4, 'destination': 'England mainland'}
RANK_KEYS = ('cheapest', 'tie')


def mill(name, price, vat=None, delivery='standard delivery £5.00 inc VAT', order=None, pack='16kg',
         currency='GBP', rate_quote=None):
    host = name.replace('_', '-') + '.example'
    url = 'https://%s/products/flour' % host
    offer = {'@type': 'Offer', 'price': price, 'priceCurrency': currency, 'url': url,
             'availability': 'https://schema.org/InStock'}
    if vat is not None:
        offer['priceSpecification'] = {'@type': 'PriceSpecification', 'valueAddedTaxIncluded': vat}
    raw = [{'origin': 'jsonld', 'body': json.dumps({'@type': 'Product', 'url': url, 'sku': 'T1', 'offers': offer})}]
    obs = []
    if delivery:
        amount = delivery.split('£')[1].split()[0]
        obs.append({'field': 'delivery_charge', 'key': 'amount', 'value': '£' + amount, 'quote': delivery,
                    'source_url': 'https://%s/delivery' % host, 'evidence_date': None,
                    'provenance': 'constructed: comparability case'})
    if rate_quote:
        rate = rate_quote.split('VAT at ')[1].split()[0].rstrip('.')
        obs.append({'field': 'price_vat', 'key': 'rate', 'value': rate, 'quote': rate_quote,
                    'source_url': 'https://%s/prices' % host, 'evidence_date': None,
                    'provenance': 'constructed: comparability case'})
    binding = {'product_path': '/products/flour', 'sku': 'T1', 'pack': pack, 'single_offer': True}
    return sc.assess_supplier(name, offers.captures_from_raw(raw, url), obs, dict(order or ORDER), binding, READ)


def ranks(result):
    v = result['verdict']
    return isinstance(v, dict) and (any(k in v for k in RANK_KEYS) or 'cheapest_among_verified' in v.get('partial', {}))


def assert_no_ranking(result, reason_words, assessments):
    assert not ranks(result), result['verdict']
    assert 'Lowest' not in result['claim'] and 'cheapest' not in result['claim'].lower(), result['claim']
    assert reason_words in result['claim'], (reason_words, result['claim'])
    for a in assessments:  # every delivered total is still listed per supplier
        if a['delivered_total']:
            assert '£%s' % a['delivered_total']['amount'] in result['claim'], result['claim']


# (a) both verified, same order need, product VAT basis unstated on both
def test_a_unstated_product_vat_on_both_refuses_ranking():
    a = [mill('mill_p', '16.00'), mill('mill_q', '17.00')]
    assert all(x['delivered_total'] for x in a)
    assert_no_ranking(sc.compare(a, ORDER, READ), 'VAT basis', a)


# (b) stated but different (one inclusive, one exclusive), no rate quoted
def test_b_mixed_vat_without_rate_refuses_ranking():
    a = [mill('mill_p', '16.00', vat=True), mill('mill_q', '14.00', vat=False, delivery='standard delivery £5.00 ex VAT')]
    assert_no_ranking(sc.compare(a, ORDER, READ), 'VAT', a)


# (c) both stated and equal; delivery VAT stated, or not applicable because delivery is free
def test_c_same_known_basis_ranks():
    a = [mill('mill_p', '16.00', vat=True), mill('mill_q', '17.00', vat=True)]
    result = sc.compare(a, ORDER, READ)
    assert ranks(result) and result['claim'].startswith('Lowest delivered among the 2 suppliers with verified prices: '
                                                         'mill_p £69.00'), result


def test_c_free_delivery_needs_no_delivery_vat_basis():
    free = [{'field': 'free_delivery_threshold', 'key': k, 'value': v, 'quote': 'free delivery on orders over £50',
             'source_url': 'https://mill-q.example/delivery', 'evidence_date': None,
             'provenance': 'constructed: comparability case'}
            for k, v in (('amount', '£50'), ('comparison', 'over'), ('zone', 'UK addresses'))]
    q = mill('mill_q', '17.00', vat=True, delivery=None)
    q = sc.assess_supplier('mill_q', q['offer'] and offers.captures_from_raw(
        [{'origin': 'jsonld', 'body': json.dumps({'@type': 'Product', 'url': 'https://mill-q.example/products/flour',
                                                  'sku': 'T1', 'offers': {
                                                      '@type': 'Offer', 'price': '17.00', 'priceCurrency': 'GBP',
                                                      'url': 'https://mill-q.example/products/flour',
                                                      'availability': 'https://schema.org/InStock',
                                                      'priceSpecification': {'valueAddedTaxIncluded': True}}})}],
        'https://mill-q.example/products/flour'), free, dict(ORDER),
        {'product_path': '/products/flour', 'sku': 'T1', 'pack': '16kg', 'single_offer': True}, READ)
    assert q['delivered_total'] and q['delivery']['applied']['kind'] == 'free_threshold'
    result = sc.compare([mill('mill_p', '16.00', vat=True), q], ORDER, READ)
    assert ranks(result), result


# (d) the order need differs: pack, quantity, destination, currency
def test_d_different_pack_refuses_ranking():
    a = [mill('mill_p', '16.00', vat=True), mill('mill_q', '20.00', vat=True, pack='25kg', order=dict(ORDER, pack='25kg'))]
    assert_no_ranking(sc.compare(a, ORDER, READ), 'pack', a)


def test_d_different_quantity_refuses_ranking():
    a = [mill('mill_p', '16.00', vat=True), mill('mill_q', '17.00', vat=True, order=dict(ORDER, quantity=2))]
    assert_no_ranking(sc.compare(a, ORDER, READ), 'quantity', a)


def test_d_different_destination_refuses_ranking():
    a = [mill('mill_p', '16.00', vat=True), mill('mill_q', '17.00', vat=True, order=dict(ORDER, destination='Wales'))]
    assert_no_ranking(sc.compare(a, ORDER, READ), 'destination', a)


def test_d_other_currency_is_never_ranked():
    eur = mill('mill_q', '15.00', vat=True, currency='EUR')
    result = sc.compare([mill('mill_p', '16.00', vat=True), eur, mill('mill_r', '17.00', vat=True)], ORDER, READ)
    assert eur['delivered_total'] is None
    assert 'mill_q' not in json.dumps(result['verdict'].get('cheapest', {})), result


# (e) the current synthetic demo shape, where both verified mills have an unknown VAT basis
def test_e_current_synthetic_demo_shape_refuses_ranking():
    spec = importlib.util.spec_from_file_location('compare_offline', ROOT / 'scripts' / 'compare_offline.py')
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    assessments, result = demo.synthetic_unknown_vat(dict(ORDER), READ) if hasattr(demo, 'synthetic_unknown_vat') \
        else demo.synthetic(dict(ORDER), READ)
    assert_no_ranking(result, 'VAT basis', assessments)


# refinements: mixed VAT with a quoted rate ranks; equivalent pack strings rank
def test_mixed_vat_with_quoted_rate_ranks_on_normalised_totals():
    p = mill('mill_p', '16.00', vat=True)  # 64.00 + 5.00 inc VAT = 69.00
    q = mill('mill_q', '13.00', vat=False, delivery='standard delivery £4.00 ex VAT',
             rate_quote='All prices exclude VAT at 20%.')  # (52.00 + 4.00) x 1.2 = 67.20 inc VAT
    result = sc.compare([p, q], ORDER, READ)
    assert ranks(result), result
    assert result['claim'].startswith('Lowest delivered among the 2 suppliers with verified prices: mill_q £67.20'), \
        result['claim']
    assert '20%' in result['claim'], result['claim']


def test_equivalent_pack_strings_rank():
    a = [mill('mill_p', '16.00', vat=True), mill('mill_q', '17.00', vat=True, pack='16 kg', order=dict(ORDER, pack='16 kg'))]
    assert ranks(sc.compare(a, ORDER, READ))

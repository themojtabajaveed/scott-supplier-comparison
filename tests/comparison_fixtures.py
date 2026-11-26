"""SYNTHETIC M1 reference-set fixtures: comparison layer (delivery membership, eligibility, totals,
verdicts).

Data only. Synthetic derivatives of real-record fixtures that are not included, documented in COMPARISON-DERIVATION.md:
- every supplier, label, address and SKU is INVENTED (tests/demo_suppliers.py);
- every GBP amount is the private value doubled, so sums, margins, ties, thresholds, minimum orders and VAT
  conversions keep their relations; rates, quantities, parcel counts, pack sizes and dates are unchanged;
- quotes are invented wording that keeps the tokens the engine reads (operator words such as "over"/"from",
  starred terms, "per parcel", "before VAT", "Most Of" wording, and the geography the area table knows).
Observations marked "derived" stand in for recorded ones; CONSTRUCTED inputs remain labelled constructed.
None of this is captured evidence or a supplier fact.
"""
from offer_fixtures import (DEMO_TWO_16, DEMO_TWO_URL, DEMO_THREE_16, DEMO_THREE_URL, DEMO_ONE_URL,
                            demo_two_raw, demo_three_raw, demo_one_raw)

# -- order contexts ---------------------------------------------------------
# A buyer basket: the comparison question is one product, one pack, a quantity and a destination.
# order_value is the goods value in GBP as the comparison layer would compute it from a confirmed
# headline; membership cases may set it directly when the boundary, not the basket, is what matters.

ORDER_1_SACK_ENGLAND = {'pack': '16kg', 'quantity': 1, 'destination': 'England mainland'}
ORDER_3_SACKS_ENGLAND = {'pack': '16kg', 'quantity': 3, 'destination': 'England mainland'}
# constructed order input: parcel count declared by the test, not derived from any supplier quote
ORDER_1_SACK_NI = {'pack': '16kg', 'quantity': 1, 'destination': 'Northern Ireland', 'parcel_count': 1}
ORDER_1_SACK_CHANNEL_ISLANDS = {'pack': '16kg', 'quantity': 1, 'destination': 'Channel Islands'}

# -- DERIVED delivery observations (synthetic): recorded live run, 30 Oct 2026 (verbatim quotes) ---------------

def obs(field, key, value, quote, url):
    return {'field': field, 'key': key, 'value': value, 'quote': quote, 'source_url': url,
            'evidence_date': '2026-10-30', 'provenance': 'derived from a recorded run (synthetic)'}


DEMO_ONE_PRODUCT = 'https://demo-mill-one.example/product/demo-strong-flour-16kg/'
DEMO_ONE_DELIVERY = 'https://demo-mill-one.example/delivery/'

DEMO_ONE_OBS = [
    obs('delivery_charge', 'amount', '£9.90', 'Standard delivery costs £9.90', DEMO_ONE_PRODUCT),
    obs('delivery_charge', 'amount', '£9.90', 'Standard delivery costs £9.90', DEMO_ONE_DELIVERY),
    obs('delivery_charge', 'basis', 'per parcel', '£13.40 per parcel to:', DEMO_ONE_PRODUCT),
    obs('delivery_charge', 'zone', 'United Kingdom', 'United Kingdom:', DEMO_ONE_PRODUCT),
    obs('free_delivery_threshold', 'amount', '£100', 'Orders over £100*', DEMO_ONE_PRODUCT),
    obs('free_delivery_threshold', 'amount', '£100', 'Free Standard UK carriage when orders total over £100*', DEMO_ONE_DELIVERY),
    obs('free_delivery_threshold', 'comparison', 'over', 'Orders over £100*', DEMO_ONE_PRODUCT),
    obs('free_delivery_threshold', 'comparison', 'over', 'Free Standard UK carriage when orders total over £100*', DEMO_ONE_DELIVERY),
    obs('free_delivery_threshold', 'zone', 'Standard UK', 'Free Standard UK carriage when orders total over £100*', DEMO_ONE_PRODUCT),
    obs('free_delivery_threshold', 'zone', 'UK', 'Free Standard UK carriage when orders total over £100*', DEMO_ONE_DELIVERY),
    obs('delivery_time', 'dispatch', 'within two working days',
        'Your order normally leaves us within two working days', DEMO_ONE_PRODUCT),
    obs('delivery_time', 'dispatch', 'within 2 working days',
        'All orders normally leave us within 2 working days', DEMO_ONE_DELIVERY),
    obs('delivery_time', 'arrival', '3-5 working days',
        'expect your parcel 3-5 working days after it leaves.', DEMO_ONE_PRODUCT),
    obs('delivery_time', 'arrival', '3-5 working days',
        'expect your parcel 3-5 working days after it leaves.', DEMO_ONE_DELIVERY),
    obs('delivery_geography', 'included', 'UK addresses',
        'Deliveries go to UK addresses only for now.', DEMO_ONE_PRODUCT),
    obs('delivery_geography', 'included', 'United Kingdom', 'United Kingdom', DEMO_ONE_DELIVERY),
    obs('delivery_geography', 'excluded', 'The Channel Islands\nForces mail addresses.',
        'The Channel Islands\nForces mail addresses.', DEMO_ONE_DELIVERY),
    obs('delivery_geography', 'surcharge', '£13.40 per parcel',
        '£13.40 per parcel\n\nNorth Coast Isles\nFar Valley District\nNorthern Ireland', DEMO_ONE_DELIVERY),
]

DEMO_TWO_OBS = [
    obs('free_delivery_threshold', 'amount', '£100',
        'Free carriage on orders Over £100 for Most Of UK Areas* - see terms', DEMO_TWO_URL),
    obs('free_delivery_threshold', 'comparison', 'Over',
        'Free carriage on orders Over £100 for Most Of UK Areas* - see terms', DEMO_TWO_URL),
    obs('free_delivery_threshold', 'zone', 'Most Of UK Areas*',
        'Free carriage on orders Over £100 for Most Of UK Areas* - see terms', DEMO_TWO_URL),
]

DEMO_THREE_OBS = [
    obs('delivery_time', 'dispatch', '3-5 working days', '- Orders leave the mill within 3-5 working days',
        DEMO_THREE_URL),
]

# -- CONSTRUCTED variants (invented; labelled per case in comparison_expected.json) --------------

def constructed(field, key, value, quote, url, note):
    o = obs(field, key, value, quote, url)
    o['evidence_date'] = None
    o['provenance'] = 'constructed: ' + note
    return o


# A1 wording variant: "from" instead of the real "over".
OBS_FROM_50 = [constructed('free_delivery_threshold', 'comparison', 'from',
                           'Free standard delivery on orders from £100', DEMO_ONE_DELIVERY,
                           'wording variant of the real over-£100 rule'),
               constructed('free_delivery_threshold', 'amount', '£100',
                           'Free standard delivery on orders from £100', DEMO_ONE_DELIVERY,
                           'wording variant of the real over-£100 rule'),
               # constructed zone metadata declared by the test author, not derived from any supplier quote
               constructed('free_delivery_threshold', 'zone', 'UK addresses',
                           'Free standard delivery on orders from £100', DEMO_ONE_DELIVERY,
                           'zone as structured metadata (not in the quote text)')]

# A4 / C2: pre-VAT threshold with the rate stated in the quote, so conversion is grounded.
OBS_PRE_VAT_WITH_RATE = [
    constructed('free_delivery_threshold', 'comparison', 'over',
                'Free delivery on orders over £120 before VAT (VAT at 20%)', DEMO_ONE_DELIVERY,
                'pre-VAT threshold, rate stated'),
    constructed('free_delivery_threshold', 'amount', '£120',
                'Free delivery on orders over £120 before VAT (VAT at 20%)', DEMO_ONE_DELIVERY,
                'pre-VAT threshold, rate stated'),
    constructed('free_delivery_threshold', 'vat_rate', '20%',
                'Free delivery on orders over £120 before VAT (VAT at 20%)', DEMO_ONE_DELIVERY,
                'pre-VAT threshold, rate stated'),
    # constructed zone metadata declared by the test author, not derived from any supplier quote
    constructed('free_delivery_threshold', 'zone', 'UK addresses',
                'Free delivery on orders over £120 before VAT (VAT at 20%)', DEMO_ONE_DELIVERY,
                'zone as structured metadata (not in the quote text)')]

# C3: pre-VAT threshold without any rate: membership must abstain.
OBS_PRE_VAT_NO_RATE = [
    constructed('free_delivery_threshold', 'comparison', 'over',
                'Free delivery on orders over £120 before VAT', DEMO_ONE_DELIVERY,
                'pre-VAT threshold, no rate quoted'),
    constructed('free_delivery_threshold', 'amount', '£120',
                'Free delivery on orders over £120 before VAT', DEMO_ONE_DELIVERY,
                'pre-VAT threshold, no rate quoted'),
    # constructed zone metadata declared by the test author, not derived from any supplier quote
    constructed('free_delivery_threshold', 'zone', 'UK addresses',
                'Free delivery on orders over £120 before VAT', DEMO_ONE_DELIVERY,
                'zone as structured metadata (not in the quote text)')]

# B1: minimum order value.
OBS_MIN_ORDER_20 = [constructed('order_eligibility', 'minimum_order', '£40',
                                'Minimum order value £40', DEMO_ONE_PRODUCT, 'minimum-order rule')]

# D1/D3/D6 constructed offers: agreeing Demo Mill Three (invented) channels at a chosen price, available Demo Mill Two (invented).
def demo_three_agreeing(price):
    """Demo Mill Three (invented) capture where both channels agree at the constructed 16kg price.

    Sets the price in the page script AND the JSON-LD offer: changing only one
    channel would produce a conflicting offer, not a confirmed one (defect found
    25 Nov 2026 by the M1 build session; fixed same day).
    """
    import json as _json
    raw = demo_three_raw(price_16=price)
    product = _json.loads(raw[0]['body'])
    for offer in product['offers']:
        if offer['url'].endswith('variant=' + DEMO_THREE_16):
            offer['price'] = price
    raw[0] = {'origin': 'jsonld', 'body': _json.dumps(product)}
    return raw

OBS_DEMO_THREE_DELIVERY_550 = [
    constructed('delivery_charge', 'amount', '£11.00', 'Standard delivery £11.00', DEMO_THREE_URL,
                'gives Demo Mill Three (invented) a verified total in D1 and D2'),
    constructed('delivery_charge', 'zone', 'UK', 'Standard delivery £11.00', DEMO_THREE_URL,
                'gives Demo Mill Three (invented) a verified total in D1 and D2')]

OBS_DEMO_THREE_DELIVERY_495 = [
    constructed('delivery_charge', 'amount', '£9.90', 'Standard delivery £9.90', DEMO_THREE_URL,
                'constructed tie with Demo Mill One (invented) in D4')]

OBS_DEMO_THREE_DELIVERY_900 = [
    constructed('delivery_charge', 'amount', '£18.00', 'Standard delivery £18.00', DEMO_THREE_URL,
                'product-cheapest but not delivered-cheapest in D6')]

OBS_DEMO_TWO_DELIVERY_695 = [
    constructed('delivery_charge', 'amount', '£13.90', 'Standard delivery £13.90', DEMO_TWO_URL,
                'gives an available Demo Mill Two (invented) a verified total in D1 and D3')]


def demo_two_available():
    """Demo Mill Two (invented) fixture with the 16kg offer marked InStock (constructed availability flip)."""
    import json as _json
    raw = demo_two_raw()
    product = _json.loads(raw[0]['body'])
    product['offers'][0]['availability'] = 'https://schema.org/InStock'
    raw[0] = {'origin': 'jsonld', 'body': _json.dumps(product)}
    variant = _json.loads(raw[1]['body'])
    variant['available'] = True
    raw[1] = {'origin': 'application_json', 'body': _json.dumps(variant),
              'attrs': {'resource': 'variant'}}
    raw[2] = dict(raw[1])
    raw[3] = {'origin': 'option', 'value': DEMO_TWO_16, 'text': '16kg Sack', 'disabled': False}
    return raw


# Offer captures reused per case (all from offer_fixtures):
#   demo_one_raw()                    confirmed £33.92, VAT included, valid until 2026-11-23
#   demo_two_raw()                  confirmed £47.00, unavailable
#   demo_two_available()            constructed: confirmed £47.00, available
#   demo_three_raw()                   conflicting: jsonld £45.60 vs page script £38.00
#   demo_three_agreeing('45.60')       confirmed £45.60 (positive control in the existing suite)
#   demo_three_agreeing(p)             confirmed at constructed price p


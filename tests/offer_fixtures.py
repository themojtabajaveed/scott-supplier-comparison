"""SYNTHETIC offer fixtures for the structured offer screen (offer-v1).

Synthetic derivatives of development transcriptions that are not included here: the same structure (JSON-LD Product/Offer
blocks, a store product record, a web-pixels "productVariants" list inside an ordinary script, pack options), but
every supplier, name, address, SKU and variant id is INVENTED (tests/demo_suppliers.py) and every GBP amount is the
private value doubled, which preserves every comparison and sum. Not a supplier fact; not proof of live capture.

Each fixture is the list the browser's DOM query (ReadOnlyBrowser.STRUCTURED_QUERY) returns.
"""
import json

DEMO_ONE_URL = 'https://demo-mill-one.example/product/demo-strong-flour-16kg/'
DEMO_TWO_URL = 'https://demo-mill-two.example/products/demo-premium-flour-16kg'
DEMO_THREE_URL = 'https://demo-mill-three.example/products/demo-canadian-flour'
DEMO_TWO_16 = '90000000000201'
DEMO_THREE_16 = '90000000000302'


def ld(obj):
    return {'origin': 'jsonld', 'body': json.dumps(obj)}


def option(value, text, disabled=False):
    return {'origin': 'option', 'value': value, 'text': text, 'disabled': disabled}


DEMO_ONE_PRODUCT = {
    '@type': 'Product', 'name': 'Demo Strong Flour 16kg - Bread Flour | Demo Mill One (invented)', 'sku': 'DM1-16',
    'url': DEMO_ONE_URL,
    'offers': [{'@type': 'Offer', 'price': '33.92', 'priceCurrency': 'GBP', 'priceValidUntil': '2026-11-23',
                'availability': 'http://schema.org/InStock', 'url': DEMO_ONE_URL,
                'priceSpecification': [{'@type': 'UnitPriceSpecification', 'price': '33.92',
                                        'priceCurrency': 'GBP', 'valueAddedTaxIncluded': 'true'}]}]}
# "You may also like": a different 16kg product under the correct page heading, with its own price
DEMO_ONE_RECOMMENDED = {
    '@type': 'Product', 'name': 'Demo Six Seed Flour 16kg', 'sku': 'DM1-SIX16',
    'url': 'https://demo-mill-one.example/product/demo-six-seed-flour-16kg/',
    'offers': {'@type': 'Offer', 'price': '53.90', 'priceCurrency': 'GBP', 'availability': 'https://schema.org/InStock'}}


def demo_one_raw():
    return [ld({'@context': 'https://schema.org/', '@graph': [DEMO_ONE_PRODUCT]}), ld(DEMO_ONE_RECOMMENDED)]


def demo_two_raw():
    variant = {'id': int(DEMO_TWO_16), 'title': '16kg Sack', 'sku': 'DM2-16', 'price': 4700, 'available': False,
               'taxable': False}
    product = {
        '@type': 'Product', 'name': 'Demo Premium Flour', 'sku': 'DM2-16',
        'url': DEMO_TWO_URL,
        'offers': [
            {'@type': 'Offer', 'sku': 'DM2-16', 'price': '47.00', 'priceCurrency': 'GBP',
             'availability': 'https://schema.org/OutOfStock', 'url': DEMO_TWO_URL + '?variant=' + DEMO_TWO_16},
            {'@type': 'Offer', 'sku': 'DM2-1.5', 'price': '5.90', 'priceCurrency': 'GBP',
             'availability': 'https://schema.org/InStock', 'url': DEMO_TWO_URL + '?variant=90000000000202'}]}
    store = {'origin': 'application_json', 'body': json.dumps(variant), 'attrs': {'resource': 'variant'}}
    return [ld(product), store, dict(store),  # main and quick-view copies of the same record
            option(DEMO_TWO_16, '16kg Sack - Sold out', disabled=True), option('90000000000202', '1 Bag - 1.5kg'),
            option('90000000000203', '5 Bags - 7.5kg')]


def _pixels(variants):
    return ('(function(){var w=window;w.webPixelsManagerAPI=w.webPixelsManagerAPI||{};'
            'webPixelsManagerAPI.init({"shopId":1,"storefrontBaseUrl":"https://demo-mill-three.example",'
            '"data":{"cart":null,"productVariants":' + json.dumps(variants) + '}});})();')


def demo_three_variants(price_16='38.0'):
    product = {'title': 'Demo Canadian-style Flour', 'url': '/products/demo-canadian-flour',
               'id': '7000000000001', 'vendor': 'Demo Mill Three (invented)'}
    return [{'price': {'amount': 3.6, 'currencyCode': 'GBP'}, 'product': product, 'id': '90000000000301',
             'sku': 'DM3-1', 'title': '1kg', 'untranslatedTitle': '1kg'},
            {'price': {'amount': float(price_16), 'currencyCode': 'GBP'}, 'product': product, 'id': DEMO_THREE_16,
             'sku': 'DM3-16', 'title': '16kg', 'untranslatedTitle': '16kg'}]


DEMO_THREE_RECOMMENDED_PIXELS = [{'price': {'amount': 60.0, 'currencyCode': 'GBP'},
                               'product': {'title': 'Demo Organic Flour', 'url': '/products/demo-organic-flour'},
                               'id': '49999999999999', 'sku': 'DM3-ORG16', 'title': '16kg', 'untranslatedTitle': '16kg'}]


def demo_three_raw(price_16='38.0', with_script=True):
    product = {
        '@type': 'Product', 'name': 'Demo Canadian-style Flour (112)', 'url': DEMO_THREE_URL,
        'offers': [
            {'@type': 'Offer', 'sku': 'DM3-1', 'price': '4.32', 'priceCurrency': 'GBP',
             'availability': 'https://schema.org/InStock', 'url': DEMO_THREE_URL + '?variant=90000000000301'},
            {'@type': 'Offer', 'sku': 'DM3-16', 'price': '45.60', 'priceCurrency': 'GBP',
             'availability': 'https://schema.org/InStock', 'url': DEMO_THREE_URL + '?variant=' + DEMO_THREE_16}]}
    raw = [ld(product)]
    if with_script:
        raw += [{'origin': 'inline_script', 'body': _pixels(demo_three_variants(price_16))},
                {'origin': 'inline_script', 'body': _pixels(DEMO_THREE_RECOMMENDED_PIXELS)}]
    return raw + [option('90000000000301', '1kg'), option(DEMO_THREE_16, '16kg'), option('90000000000303', '25kg')]

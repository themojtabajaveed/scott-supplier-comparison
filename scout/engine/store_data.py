"""Read a store's own product data (Shopify <product>.js) in code, without a model call.

browser.fetch_variant_data turns the JSON into plain lines, one per pack:
    <title>
    <pack> | <price as given by the store divided by 100> | available=<True|False>
plus a note line saying the data states no currency. This module picks the line for the planned
pack and returns literal claims quoted from that exact line. It never adds a currency: the store data
does not state one, so currency can only come from the product page's own text.
"""
import re

from .atomic import validate_atoms

NO_CURRENCY_NOTE = '(prices as given by the store divided by 100; this data does not state a currency)'
LINE = re.compile(r'^(?P<pack>[^|\n]+?) \| (?P<price>\d+(?:\.\d+)?) \| available=(?P<available>True|False|None)$',
                  re.M)


def format_variants(data):
    """Plain lines for a store product JSON object (as returned by <product>.js)."""
    lines = [str(data.get('title', '')), NO_CURRENCY_NOTE]
    for v in data.get('variants') or []:
        price = v.get('price')
        if isinstance(price, (int, float)) and not isinstance(price, bool):
            price = '%.2f' % (price / 100)
        lines.append('%s | %s | available=%s' % (v.get('title'), price, v.get('available')))
    return '\n'.join(lines)


def _pack_matches(label, pack):
    """'16kg Sack' and '16 KG' match pack '16kg'; '1kg' and '160kg' do not."""
    m = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*kg\s*', pack or '', re.I)
    if not m:
        return False
    return re.search(r'(?<![\d.])' + re.escape(m.group(1)) + r'\s*kg\b', label, re.I) is not None


def read_pack(text, pack, url, schema):
    """([accepted product_price claims per matching line], [availability notes]) for the planned pack.

    Claims go through the same literal validator as model output, so every value is a substring of its
    quote and every quote a substring of the data text. Several matching lines keep all their prices.
    """
    found, notes = [], []
    for m in LINE.finditer(text or ''):
        if not _pack_matches(m.group('pack'), pack):
            continue
        line = m.group(0)
        raw = {'amount': {'value': m.group('price'), 'quote': line},
               'variant': {'value': m.group('pack').strip(), 'quote': line}}
        checked = validate_atoms({k: v for k, v in raw.items() if k in schema}, schema, text, url)['facts']
        if checked:
            found.append(checked)
        available = {'True': True, 'False': False}.get(m.group('available'))
        notes.append({'source_url': url, 'pack': m.group('pack').strip(), 'available': available, 'quote': line})
    return found, notes

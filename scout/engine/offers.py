"""Structured offer screen (offer-v1): bind a price to the configured product and pack from records the
browser's own code read out of the page's markup, never from model output or visible page text.

Provenance. Only Capture objects count as evidence. The browser builds them in code from script
elements and form options (structured_offers); model replies, page text, saved result files and the store
data's plain-line text cannot become a Capture, and normalise() ignores anything else.

Channels read (no page JavaScript is executed; script bodies are only parsed as JSON):
  jsonld            <script type="application/ld+json">: Product with Offer(s)
  application_json  <script type="application/json">: a store product or variant object
  inline_script     an ordinary script, only at the known "productVariants": [ ... ] array
  option            <option>/<input type=radio>: value, visible text, disabled

Binding (configured per supplier in scout/workflows/supplier.py, reviewed by a person):
  identity  the record's product URL path (or its offer/variant URL path) equals the configured product
            path, and the SKU on the offer, or else on its parent product, equals the configured SKU.
            Titles are never identity proof.
  channels  a binding may list required_channels: record channels known (from reviewed snapshots) to carry a
            price for this product; if one is not captured, the result is unsupported.
  pack      variant products: the record's variant id has a same-page option or variant title that
            matches the planned pack, and no same-id label naming another pack; exactly one such id.
            single-offer products: the configured product+SKU+pack relationship, with one offer only.

Precedence: no record wins. Bound records that differ in amount, currency, tax basis or availability are a
conflict and get no headline. A record without a currency can corroborate an equal amount but never
supplies a currency. A known price channel that cannot be read makes the result unsupported. Text quotes
never confirm, resolve or create a conflict. A confirmed price is a price identity only: not product
suitability, substitutability, a delivered cost or buying advice.
"""
import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse, parse_qs

from .store_data import _pack_matches

SCREEN = 'offer-v1'
MAX_BODY = 2_000_000
MAX_CAPTURES = 400
KNOWN_CHANNEL = '"productVariants":'


@dataclass(frozen=True)
class Capture:
    """One raw piece of page markup, created only by browser code."""
    origin: str
    page_url: str
    body: str = ''
    value: str = ''
    text: str = ''
    disabled: bool = False
    attrs: dict = field(default_factory=dict)


def today():
    """Read date for validity checks; a function so tests can fix it."""
    return date.today()


def captures_from_raw(raw_items, page_url):
    """Capture objects from the plain list the browser's DOM query returned. Unknown shapes are dropped."""
    out = []
    items = raw_items if isinstance(raw_items, list) else []
    if len(items) > MAX_CAPTURES:  # fail closed: an omitted record could contradict a kept one
        out.append(Capture(origin='capture_limit', page_url=page_url,
                           text='more than %d markup records on the page; the rest were not read' % MAX_CAPTURES))
    for item in items[:MAX_CAPTURES]:
        if not isinstance(item, dict) or item.get('origin') not in ('jsonld', 'application_json', 'inline_script',
                                                                     'option'):
            continue
        body = item.get('body') if isinstance(item.get('body'), str) else ''
        if len(body) > MAX_BODY:
            out.append(Capture(origin='capture_limit', page_url=page_url,
                               text='a %s record was larger than the reading limit and was not read' % item['origin']))
            continue
        attrs = item.get('attrs') if isinstance(item.get('attrs'), dict) else {}
        out.append(Capture(origin=item['origin'], page_url=page_url, body=body,
                           value=str(item.get('value') or ''), text=' '.join(str(item.get('text') or '').split()),
                           disabled=item.get('disabled') is True,
                           attrs={str(k): str(v) for k, v in attrs.items()}))
    return out


# ---------- normalisation ----------

def _path(url, base=''):
    if not isinstance(url, str) or not url:
        return None
    p = urlparse(url)
    if p.netloc and base and urlparse(base).netloc and p.netloc.lower().removeprefix('www.') != \
            urlparse(base).netloc.lower().removeprefix('www.'):
        return ('other-site', p.netloc.lower())
    path = p.path or '/'
    return path.rstrip('/') or '/'


def _variant_from_url(url):
    if not isinstance(url, str):
        return None
    q = parse_qs(urlparse(url).query).get('variant')
    if q and q[0].isdigit():
        return q[0]
    m = re.search(r'/variants?/(\d+)', url)
    return m.group(1) if m else None


MAX_AMOUNT = Decimal('1000000')


def _decimal(value, minor_units=False, problems=None):
    """A price as a Decimal, or None when absent. A value that is present but unreadable (text, negative,
    not finite, absurdly large or precise) is reported as a problem, so the page fails closed."""
    if value is None or value == '':
        return None
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError
        d = Decimal(str(value).strip())
        if not d.is_finite() or d < 0:
            raise ValueError
        d = (d / 100) if minor_units else d
        if d >= MAX_AMOUNT:
            raise ValueError
        d.quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError, ArithmeticError):
        if problems is not None:
            problems.append('a price value could not be read')
        return None
    return d


def _availability(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.rsplit('/', 1)[-1].casefold()
        if v in ('instock', 'instoreonly', 'onlineonly', 'limitedavailability'):
            return True
        if v in ('outofstock', 'soldout', 'discontinued'):
            return False
    return None


def _vat(spec):
    specs = spec if isinstance(spec, list) else [spec]
    seen = {s.get('valueAddedTaxIncluded') for s in specs if isinstance(s, dict)}
    seen = {True if v in (True, 'true', 'True') else False if v in (False, 'false', 'False') else None for v in seen}
    seen.discard(None)
    return seen.pop() if len(seen) == 1 else (None if not seen else 'conflicting')


def _types(obj):
    t = obj.get('@type')
    return {str(x) for x in t} if isinstance(t, list) else {str(t)}


def _walk(obj):
    if isinstance(obj, list):
        for x in obj:
            yield from _walk(x)
    elif isinstance(obj, dict):
        yield obj
        for k in ('@graph', 'mainEntity', 'itemListElement', 'item'):
            if k in obj:
                yield from _walk(obj[k])


def _record(**kw):
    base = {'origin': None, 'page_url': None, 'product_path': None, 'product_sku': None, 'sku': None,
            'variant_id': None, 'label': None, 'amount': None, 'currency': None, 'vat_included': None,
            'availability': None, 'valid_until': None, 'name': None, 'minor_units': False}
    base.update(kw)
    return base


def _jsonld_records(cap, problems):
    try:
        data = json.loads(cap.body)
    except ValueError:
        problems.append('a JSON-LD block could not be parsed')
        return []
    out = []
    for obj in _walk(data):
        if 'Product' not in _types(obj):
            continue
        offers = obj.get('offers')
        offers = offers if isinstance(offers, list) else [offers]
        flat = []
        for o in offers:
            if isinstance(o, dict) and 'AggregateOffer' in _types(o) and isinstance(o.get('offers'), list):
                flat += [x for x in o['offers'] if isinstance(x, dict)]
            elif isinstance(o, dict):
                flat.append(o)
        product_path = _path(obj.get('url') or obj.get('@id'), cap.page_url)
        for o in flat:
            spec = o.get('priceSpecification')
            price = o.get('price')
            currency = o.get('priceCurrency')
            if price is None and isinstance(spec, dict):
                price, currency = spec.get('price'), currency or spec.get('priceCurrency')
            out.append(_record(
                origin='jsonld', page_url=cap.page_url, product_path=product_path,
                offer_path=_path(o.get('url'), cap.page_url), product_sku=obj.get('sku'), sku=o.get('sku'),
                variant_id=_variant_from_url(o.get('url')) or _variant_from_url(o.get('@id')),
                amount=_decimal(price, problems=problems), currency=currency if isinstance(currency, str) and currency else None,
                vat_included=_vat(spec) if spec is not None else None,
                availability=_availability(o.get('availability')),
                valid_until=o.get('priceValidUntil') if isinstance(o.get('priceValidUntil'), str) else None,
                name=obj.get('name')))
    return out


def _store_variant(v, cap, product_path, problems, product_sku=None):
    """A store variant object; integer prices in this shape are minor units with no currency."""
    price = v.get('price')
    minor = isinstance(price, int) and not isinstance(price, bool)
    return _record(origin=cap.origin, page_url=cap.page_url, product_path=product_path, product_sku=product_sku,
                   sku=v.get('sku'), variant_id=str(v['id']) if v.get('id') is not None else None,
                   label=v.get('title') or v.get('public_title') or v.get('name'),
                   amount=_decimal(price, minor_units=minor, problems=problems), currency=None, minor_units=minor,
                   availability=v.get('available') if isinstance(v.get('available'), bool) else None)


def _application_json_records(cap, problems):
    if not any(k in cap.body for k in ('"variants"', '"price"')):
        return []  # not a product-shaped record; nothing to read
    try:
        data = json.loads(cap.body)
    except ValueError:
        problems.append('a store product record could not be parsed')
        return []
    out = []
    for obj in _walk(data):
        if isinstance(obj.get('variants'), list):
            path = _path(obj.get('url') or ('/products/' + obj['handle'] if obj.get('handle') else None),
                         cap.page_url)
            out += [_store_variant(v, cap, path, problems) for v in obj['variants'] if isinstance(v, dict)]
        elif 'price' in obj and 'id' in obj and ('available' in obj or 'title' in obj or 'sku' in obj):
            out.append(_store_variant(obj, cap, None, problems))
    return out


def _inline_records(cap, problems):
    """Only the known "productVariants": [...] array is decoded; nothing in the script is run.
    A script that names productVariants in any other form (for example escaped inside a string) is
    reported as unreadable, so a known price channel is never skipped silently."""
    out, start = [], 0
    if cap.body.count('productVariants') > cap.body.count(KNOWN_CHANNEL):
        problems.append('a productVariants record in a page script is not in a readable form')
    while True:
        i = cap.body.find(KNOWN_CHANNEL, start)
        if i < 0:
            break
        start = i + len(KNOWN_CHANNEL)
        j = cap.body.find('[', start)
        try:
            arr, _ = json.JSONDecoder().raw_decode(cap.body[j:]) if j >= 0 else (None, 0)
        except ValueError:
            arr = None
        if not isinstance(arr, list):
            problems.append('a productVariants record in a page script could not be read')
            continue
        for v in arr:
            if not isinstance(v, dict):
                continue
            price = v.get('price') if isinstance(v.get('price'), dict) else {}
            product = v.get('product') if isinstance(v.get('product'), dict) else {}
            cur = price.get('currencyCode')
            out.append(_record(
                origin='inline_script', page_url=cap.page_url, product_path=_path(product.get('url'), cap.page_url),
                sku=v.get('sku'), variant_id=str(v['id']) if v.get('id') is not None else None,
                label=v.get('untranslatedTitle') or v.get('title'), amount=_decimal(price.get('amount'), problems=problems),
                currency=cur if isinstance(cur, str) and cur else None, name=product.get('title')))
    return out


def normalise(captures):
    """(price records, option records, problems) from Capture objects only."""
    records, options, problems = [], [], []
    for cap in captures or []:
        if not isinstance(cap, Capture):
            continue  # provenance: only browser-built captures count
        if cap.origin == 'capture_limit':
            problems.append(cap.text or 'the page capture hit a reading limit')
        elif cap.origin == 'jsonld':
            records += _jsonld_records(cap, problems)
        elif cap.origin == 'application_json':
            records += _application_json_records(cap, problems)
        elif cap.origin == 'inline_script':
            records += _inline_records(cap, problems)
        elif cap.origin == 'option' and cap.value:
            options.append({'variant_id': cap.value, 'label': cap.text, 'disabled': cap.disabled,
                            'page_url': cap.page_url})
    return records, options, problems


# ---------- binding ----------

def _norm_sku(s):
    return str(s).strip().casefold() if s not in (None, '') else None


def _public(rec):
    r = {k: v for k, v in rec.items()}
    r['amount'] = None if rec['amount'] is None else format(rec['amount'].quantize(Decimal('0.01')), 'f')
    r['product_path'] = rec['product_path'] if not isinstance(rec['product_path'], tuple) else 'other site'
    r.pop('offer_path', None)
    return r


def _paths(rec):
    return {p for p in (rec.get('product_path'), rec.get('offer_path')) if p}


def _skus(rec):
    """The record's SKUs at both levels: its own (offer or variant, the child) and its parent product's."""
    return {s for s in (_norm_sku(rec.get('sku')), _norm_sku(rec.get('product_sku'))) if s}


def _identity(rec, cfg_path, cfg_sku, matched_ids):
    paths = _paths(rec)
    if paths and paths != {cfg_path}:
        return False  # any stated path elsewhere (a recommended product, another site) is not this product
    if paths:
        return cfg_sku in _skus(rec) or rec.get('variant_id') in matched_ids
    # No path stated: only a same-page join by variant id to a path-and-SKU-anchored record. A child SKU here
    # is a variant-level fact: it is compared with the other records of the same variant id, never against a
    # configured parent-level SKU, so a contradicting record cannot be dropped for carrying it.
    return rec.get('variant_id') is not None and rec['variant_id'] in matched_ids


def bind_offer(captures, binding, pack, read_date=None):
    """Decision dict for the configured product and planned pack. States:
    confirmed | conflicting | not_confirmed | unsupported | no_structured_offer."""
    decision = {'screen': SCREEN, 'state': 'not_confirmed', 'reasons': [], 'records': [], 'ignored': 0,
                'headline': None, 'conflicts': [], 'availability': 'unknown', 'availability_signals': [],
                'vat_included': None, 'valid_until': None, 'read_date': read_date.isoformat() if read_date else None,
                'binding': dict(binding or {}), 'pack': pack}
    records, options, problems = normalise(captures)
    if not binding or not binding.get('product_path') or not binding.get('sku') or not binding.get('pack'):
        decision.update(state='not_confirmed', reasons=['no reviewed offer binding is configured for this source'])
        return decision
    if not pack or not _pack_matches(binding['pack'], pack):
        decision.update(reasons=['the planned pack is not the configured pack for this product'])
        return decision
    if not records and not problems:
        decision.update(state='no_structured_offer', reasons=['no structured offer record was captured'])
        return decision
    cfg_path, cfg_sku = binding['product_path'].rstrip('/') or '/', _norm_sku(binding['sku'])

    # 1. identity: path-and-SKU matches first, then same-page joins by variant id
    # the configured SKU may be the product's (parent) or the offer's/variant's (child)
    anchored = [r for r in records if _paths(r) == {cfg_path} and cfg_sku in _skus(r)]
    ids = {r['variant_id'] for r in anchored if r.get('variant_id')}
    matched = [r for r in records if _identity(r, cfg_path, cfg_sku, ids)]
    decision['ignored'] = len(records) - len(matched)

    # 2. pack
    labels = {}
    for o in options:
        labels.setdefault(o['variant_id'], set()).add(o['label'])
    for r in matched:
        if r.get('variant_id') and r.get('label'):
            labels.setdefault(r['variant_id'], set()).add(r['label'])
    if binding.get('single_offer'):
        bound = [r for r in matched if not any(not _pack_matches(lab, pack) for lab in labels.get(r.get('variant_id'), ()))]
        offers = {(r.get('variant_id'), r.get('offer_path'), r['amount'], r.get('currency'), r.get('availability'))
                  for r in bound if r['origin'] == 'jsonld'}  # identical copies are one offer
        if len(offers) > 1:
            decision.update(reasons=['more than one offer for the configured single-offer product'])
            bound = []
    else:
        def pack_state(vid):
            labs = [lab for lab in labels.get(vid, ()) if lab]
            if not labs:
                return 'unlabelled'
            ok = [_pack_matches(lab, pack) for lab in labs]
            return 'match' if all(ok) else ('contradicted' if any(ok) else 'other')
        states = {r.get('variant_id'): pack_state(r.get('variant_id')) for r in matched if r.get('variant_id')}
        if any(s == 'contradicted' for s in states.values()):
            decision['reasons'].append('a variant id carries labels for different pack sizes')
        pack_ids = {v for v, s in states.items() if s == 'match'}
        if len(pack_ids) > 1:
            decision['reasons'].append('more than one variant id matches the planned pack')
            pack_ids = set()
        bound = [r for r in matched if r.get('variant_id') in pack_ids]
    # identical duplicates (same origin and every compared detail) are one record
    seen, unique = set(), []
    for r in bound:
        key = (r['origin'], r.get('variant_id'), r.get('product_path'), r.get('offer_path'), r['amount'],
               r.get('currency'), r.get('vat_included'), r.get('availability'), _norm_sku(r.get('sku')))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    decision['records'] = [_public(r) for r in unique]
    if problems:
        decision.update(state='unsupported',
                        reasons=decision['reasons'] + ['a known price record on this page could not be read: '
                                                       + '; '.join(sorted(set(problems)))])
        return decision
    if not unique:
        decision['reasons'].append('no structured record binds a price to this product and pack')
        return decision
    missing_channels = [ch for ch in binding.get('required_channels') or [] if not any(r['origin'] == ch for r in unique)]
    if missing_channels:  # a reviewed source known to carry a price in this channel; never promote without it
        decision.update(state='unsupported', reasons=decision['reasons'] + [
            'the known %s price record for this product and pack was not captured, so a price from another '
            'record cannot be confirmed alone' % ', '.join(missing_channels)])
        return decision

    # 3. agreement on amount, currency, tax and availability (no winner is ever chosen)
    amounts = {r['amount'] for r in unique if r['amount'] is not None}
    currencies = {r['currency'] for r in unique if r.get('currency')}
    vats = {r['vat_included'] for r in unique if r.get('vat_included') is not None}
    signals = [(r['origin'], r['availability']) for r in unique if r.get('availability') is not None]
    pack_ids = {r.get('variant_id') for r in unique if r.get('variant_id')}
    signals += [('option', False) for o in options if o['variant_id'] in pack_ids and o['disabled']]
    decision['availability_signals'] = [{'origin': o, 'available': a} for o, a in signals]
    avail = {a for _, a in signals}
    decision['availability'] = ('conflicting' if len(avail) > 1 else
                                'available' if avail == {True} else 'unavailable' if avail == {False} else 'unknown')
    if len(amounts) > 1:
        decision['conflicts'].append('amount')
    if len(currencies) > 1:
        decision['conflicts'].append('currency')
    if len(vats) > 1 or 'conflicting' in vats:
        decision['conflicts'].append('tax basis')
    if decision['availability'] == 'conflicting':
        decision['conflicts'].append('availability')
    child_skus = {}
    for r in unique:
        if r.get('variant_id') and _norm_sku(r.get('sku')):
            child_skus.setdefault(r['variant_id'], set()).add(_norm_sku(r['sku']))
    if any(len(v) > 1 for v in child_skus.values()):
        decision['conflicts'].append('variant SKU')
    if any(_paths(r) and _paths(r) != {cfg_path} and r.get('variant_id') in pack_ids for r in records):
        decision['conflicts'].append('product identity')  # another product's record claims this variant id
    valid = sorted({r['valid_until'] for r in unique if r.get('valid_until')})
    decision['valid_until'] = valid[0] if valid else None
    decision['vat_included'] = next(iter(vats)) if len(vats) == 1 else None
    if decision['conflicts']:
        decision.update(state='conflicting', reasons=decision['reasons'] + [
            'structured records for this product and pack disagree on ' + ', '.join(decision['conflicts'])])
        return decision
    if not amounts:
        decision['reasons'].append('the bound record states no amount')
        return decision
    if not currencies:
        decision['reasons'].append('no bound record states a currency, so the amount is only a quoted number')
        return decision
    if decision['valid_until']:
        try:
            until = date.fromisoformat(decision['valid_until'][:10])
        except ValueError:
            until = None
        if until is None or read_date is None:
            decision['reasons'].append('the offer states a validity date that could not be checked against the '
                                       'read date')
            return decision
        if until < read_date:
            decision['reasons'].append('the offer\'s stated validity ended before the read date')
            decision['state'] = 'not_confirmed'
            decision['expired'] = True
            return decision
    amount = next(iter(amounts))
    decision.update(state='confirmed', headline={
        'amount': format(amount.quantize(Decimal('0.01')), 'f'), 'currency': next(iter(currencies)),
        'pack': binding['pack'], 'sku': binding['sku'], 'variant_id': next(iter(pack_ids), None)})
    return decision

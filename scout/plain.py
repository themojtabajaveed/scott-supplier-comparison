"""Plain-language reading of engine results for people. Standard library only.

Nothing here changes a result: every word is computed from the saved facts, statuses and
stop reasons, and the raw engine code is always returned alongside it so a page can show both.
A status word says only what was quoted, never that a value is correct.
"""
import re
from urllib.parse import urlparse

FIELD_LABELS = {
    'product_price': 'Price (16kg sack)',
    'delivery_charge': 'Delivery charge',
    'free_delivery_threshold': 'Free delivery over',
    'delivery_time': 'Dispatch / arrival',
    'delivery_geography': 'Delivery area',
    'model_price_input': 'Input price',
    'model_price_output': 'Output price',
}

CLAIM_LABELS = {
    'amount': 'amount', 'currency': 'currency', 'variant': 'pack size', 'basis': 'charge basis',
    'vat': 'VAT basis', 'zone': 'zone', 'packing': 'sacks per box', 'surcharge': 'surcharge',
    'order_condition': 'order condition', 'comparison': 'over or at the threshold',
    'weight_limit': 'weight limit', 'discount_condition': 'before or after discounts',
    'exceptions': 'exceptions', 'dispatch': 'dispatch time', 'arrival': 'arrival time',
    'included': 'areas served', 'excluded': 'areas excluded', 'model': 'model',
    'unit': 'token unit', 'processing': 'processing mode', 'region': 'regional or global inference',
}

# The claims a table cell shows first; every other quoted claim stays in the cell's quote list.
MAIN_CLAIMS = {
    'product_price': ['amount', 'variant'],
    'delivery_charge': ['amount', 'basis', 'zone'],
    'free_delivery_threshold': ['comparison', 'amount', 'zone'],
    'delivery_time': ['dispatch', 'arrival'],
    'delivery_geography': ['included', 'excluded'],
    'model_price_input': ['amount', 'model'],
    'model_price_output': ['amount', 'model'],
}

KNOWN_STATUSES = {'literal_components_present', 'incomplete', 'incomplete_literal_variation',
                  'possible_numeric_disagreement', 'source_disagreement'}

QUOTED, PARTLY, NOT_FOUND, DISAGREE, REVIEW, UNRECOGNISED = (
    'Quoted', 'Partly quoted', 'Not found', 'Values disagree', 'Needs review', 'Unrecognised')
# Price words from the structured offer screen (scout/engine/offers.py). Only a confirmed offer record gives a
# price headline; a confirmed price is a price identity, never suitability, substitutability or buying advice.
OFFER_OK, OFFER_OUT, PRICE_UNCONFIRMED = 'Offer matched', 'Out of stock', 'Price not confirmed'
OFFER_SCREEN = 'offer-v1'
ORIGIN_LABELS = {'jsonld': 'structured product data (JSON-LD)', 'application_json': 'store product record',
                 'inline_script': 'page script product list', 'option': 'pack option'}
AVAILABILITY_WORDS = {'available': 'in stock at read time', 'unavailable': 'out of stock at read time',
                      'unknown': 'availability not stated', 'conflicting': 'availability conflicting'}


def field_label(name):
    return FIELD_LABELS.get(name, name.replace('_', ' '))


def claim_label(key):
    return CLAIM_LABELS.get(key, key.replace('_', ' '))


NUMBER_WORDS = {w: str(i) for i, w in enumerate(
    'zero one two three four five six seven eight nine ten eleven twelve'.split())}


def _numbers(value):
    """Numbers in a value; whole number words up to twelve count as digits ('two' == '2')."""
    words = re.sub(r'[a-z]+', lambda m: NUMBER_WORDS.get(m.group(0), m.group(0)), value.casefold())
    return tuple(re.findall(r'\d+(?:\.\d+)?', words))


def _values(facts, key):
    return [c.get('value', '') for c in facts.get(key) or [] if isinstance(c, dict)]


# ---- delivery charge context (display only) ------------------------------------------------------------------
# A presentation check of each delivery qualifier claim against the charge amount shown. It reads saved claims and
# never changes a result, a status, a missing list or the research route. It says only whether a claim's own quote
# also contains the shown charge (co-quoted), contains other money amounts, or contains neither (stated separately).
# Words appearing together are not proof that a condition applies to the charge, and another amount in a quote is not
# proof of another rate or option. Equal amounts quoted in different places are not taken to be one delivery option.
DELIVERY_QUALIFIERS = ('basis', 'order_condition', 'vat', 'zone', 'packing', 'surcharge')
CONTEXT_SCREEN = 'delivery-context-v1'
_CURRENCY = {'£': 'GBP', 'GBP': 'GBP', '€': 'EUR', 'EUR': 'EUR', 'US$': 'USD', 'USD': 'USD', '$': '$'}
_MONEY = re.compile(
    r'(?<![\w.,$£€])(?:(?P<sym>US\$|£|€|\$)\s?(?P<n1>\d[\d,]*(?:\.\d+)?)'
    r'|(?P<code>GBP|EUR|USD)\s?(?P<n2>\d[\d,]*(?:\.\d+)?)'
    r'|(?P<n3>\d[\d,]*(?:\.\d+)?)\s?(?P<code2>GBP|EUR|USD|€)(?![A-Za-z]))(?![\d])(?![.,]\d)')
MONEY_FORMATS = '£ or GBP, € or EUR, $, US$ or USD'


def _money_value(number, currency):
    """Decimal for a recognised number, or None. Commas group thousands (1,250.00); a euro amount may use a
    decimal comma (4,95). Anything else (such as £4,95) is not recognised rather than guessed."""
    from decimal import Decimal, InvalidOperation
    if re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?', number):
        text = number.replace(',', '')
    elif currency == 'EUR' and re.fullmatch(r'\d+,\d{1,2}', number):
        text = number.replace(',', '.')
    else:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def money_amounts(text):
    """[(currency, Decimal, matched text)] for money written in a recognised form. A bare $ is kept as its own
    currency, never equated with USD; nothing is converted. Unrecognised forms are not returned."""
    out = []
    for m in _MONEY.finditer(text or ''):
        currency = _CURRENCY[m.group('sym') or m.group('code') or m.group('code2')]
        value = _money_value(m.group('n1') or m.group('n2') or m.group('n3'), currency)
        if value is not None:
            out.append((currency, value, m.group(0)))
    return out


def _doc(url):
    from urllib.parse import urldefrag
    return urldefrag(url or '')[0]


def _money_text(key):
    currency, value = key
    sign = {'GBP': '£', 'EUR': '€', 'USD': 'US$'}.get(currency)
    number = format(value, 'f')
    return (sign + number) if sign else ((currency + number) if currency == '$' else (number + ' ' + currency))


def delivery_context(field, row_fields=None):
    """Display assessment of each delivery qualifier claim. {'screen', 'checked', 'reason', 'claims', 'charges'}.

    Each claim gets one state, judged only from its own quote and document (a #fragment counts as the same
    document as its page), against charge amounts quoted in that same document:
      co_quoted          the quote also contains the shown charge, and no other amount that is not accounted for
      co_quoted_other    the quote also contains the shown charge and other amounts whose role was not extracted
      other_amount_only  the quote contains other amounts but not the shown charge
      separate           no shown charge was identified in the quote: it holds no amount that is not accounted for,
                         or the claim comes from a document where no charge was quoted (a page with a different
                         address or query string; a #fragment counts as the same page). Document separation comes
                         first, so a repeated equal amount on another page is never read as a second amount
      no_charge          no delivery charge amount was extracted, so nothing is shown as part of a charge
    An amount counts as accounted for when an extracted claim citing the same quote carries it. That only decides
    whether a note is shown; it does not check that claim's role.
    """
    field = field if isinstance(field, dict) else {}
    facts = field.get('facts') if isinstance(field.get('facts'), dict) else {}
    out = {'screen': CONTEXT_SCREEN, 'checked': False, 'reason': '', 'claims': [], 'charges': []}
    charges = []  # (document, (currency, value), quote) for each charge amount claim
    for claim in facts.get('amount') or []:
        if not isinstance(claim, dict):
            continue
        found = {(c, v) for c, v, _ in money_amounts(claim.get('value', ''))}
        if len(found) != 1:
            out['reason'] = ('the charge amount "%s" is not written in a recognised money format (%s), so its '
                             'quoted context was not checked' % (claim.get('value', ''), MONEY_FORMATS))
            return out
        charges.append((_doc(claim.get('source_url')), next(iter(found)), claim.get('quote', '')))
    if not charges:
        out['reason'] = 'no delivery charge amount was extracted'  # nothing is inferred from the detail quotes
    out['checked'] = True
    out['charges'] = sorted({k for _, k, _ in charges}, key=lambda k: (k[0], k[1]))
    accounted = {}
    sources = [field] + (list(row_fields.values()) if isinstance(row_fields, dict) else [])  # own claims always count
    for other in sources:
        for claims in ((other or {}).get('facts') or {}).values() if isinstance(other, dict) else []:
            for c in claims or []:
                if isinstance(c, dict):
                    accounted.setdefault((_doc(c.get('source_url')), c.get('quote', '')), set()).update(
                        (cur, v) for cur, v, _ in money_amounts(c.get('value', '')))
    for key in DELIVERY_QUALIFIERS:
        for c in facts.get(key) or []:
            if not isinstance(c, dict):
                continue
            doc, quote = _doc(c.get('source_url')), c.get('quote', '')
            in_quote = {(cur, v) for cur, v, _ in money_amounts(quote)}
            own = {(cur, v) for cur, v, _ in money_amounts(c.get('value', ''))}
            same_doc = {k for d, k, _ in charges if d == doc}
            named = in_quote & same_doc
            other = in_quote - named - own - accounted.get((doc, quote), set())
            if not charges:
                state, other = 'no_charge', set()
            elif not same_doc:  # a different document: separate, whatever amounts its quote repeats
                state, other = 'separate', set()
            elif named:
                state = 'co_quoted_other' if other else 'co_quoted'
            elif other:
                state = 'other_amount_only'
            else:
                state = 'separate'
            out['claims'].append({'key': key, 'value': c.get('value', ''), 'quote': quote,
                                  'source_url': c.get('source_url', ''), 'state': state,
                                  'with': sorted(named), 'other': sorted(other), 'charge_in_document': bool(same_doc)})
    return out


def delivery_context_lines(ctx):
    """Plain sentences for the default view: ('note', text) for ambiguity beside a shown claim, and
    ('separate', text) for each claim kept out of the headline. Every claim moved out of a headline gets a line."""
    if not ctx.get('checked'):
        return [('note', ctx['reason'][0].upper() + ctx['reason'][1:] + '.')] if ctx.get('reason') else []
    shown = ' or '.join(_money_text(k) for k in ctx['charges'])
    several = len(ctx['charges']) > 1
    lines = []
    for c in ctx['claims']:
        label = claim_label(c['key'])
        label = label[0].upper() + label[1:]
        value = ' '.join(str(c['value']).split())
        if c['state'] == 'no_charge':
            lines.append(('separate', '%s "%s": no delivery charge amount was extracted, so it is not shown as part '
                                      'of a charge.' % (label, value)))
        elif c['state'] == 'co_quoted':
            if several:
                lines.append(('note', '%s "%s" is quoted with %s only.' % (label, value,
                                                                         ' and '.join(_money_text(k) for k in c['with']))))
        elif c['state'] == 'co_quoted_other':
            lines.append(('note', '%s "%s": its quote also contains %s, whose role was not extracted; which amount '
                                  'this wording refers to was not checked.'
                          % (label, value, ', '.join(_money_text(k) for k in c['other']))))
        elif c['state'] == 'other_amount_only':
            lines.append(('separate', '%s "%s": its quote contains %s and does not contain the shown %s; how they '
                                      'relate was not checked.'
                          % (label, value, ', '.join(_money_text(k) for k in c['other']), shown)))
        elif c['charge_in_document']:
            lines.append(('separate', '%s "%s": no shown charge was identified in its quote (for example a heading, '
                                      'a site-wide statement or a standalone amount); whether it covers the shown %s '
                                      'was not checked.' % (label, value, shown)))
        else:
            lines.append(('separate', '%s "%s": stated on a different page (%s) from the charge quote; not checked '
                                      'against the shown %s.' % (label, value, host_and_path(c['source_url']), shown)))
    return lines


def host_and_path(url):
    """Host, path and query: a page with a different query string is a different source."""
    p = urlparse(url or '')
    return (p.netloc + p.path + ('?' + p.query if p.query else '')) if p.netloc else (url or 'source not recorded')


def headline_claim_shown(name, key, claim, ctx):
    """True when a claim may appear as a headline value beside the charge: always outside delivery qualifiers;
    for them, only when its own quote also contains the shown charge (or the context could not be checked)."""
    if name != 'delivery_charge' or key not in DELIVERY_QUALIFIERS or not ctx.get('checked'):
        return True
    for c in ctx['claims']:
        if c['key'] == key and c['value'] == claim.get('value', '') and c['quote'] == claim.get('quote', '') and \
                c['source_url'] == claim.get('source_url', ''):
            return c['state'] in ('co_quoted', 'co_quoted_other')
    return True


def repeated_amount_note(field):
    """A visible sentence when one shown amount comes from differently worded quotes: equal amounts are shown
    once, which does not mean they describe the same delivery option."""
    facts = (field or {}).get('facts') or {}
    by_value = {}
    for c in facts.get('amount') or []:
        if isinstance(c, dict):
            by_value.setdefault(' '.join(str(c.get('value', '')).split()), set()).add(' '.join(c.get('quote', '').split()))
    repeated = [v for v, quotes in by_value.items() if len(quotes) > 1]
    if not repeated:
        return ''
    return ('%s is quoted in more than one place with different wording; it is shown once here, which does not mean '
            'the quotes describe the same delivery option.' % ' and '.join(repeated))


def offer_decision(field):
    """The field's structured offer decision when it carries one from this screen version, else None."""
    offer = (field or {}).get('offer') if isinstance(field, dict) else None
    return offer if isinstance(offer, dict) and offer.get('screen') == OFFER_SCREEN else None


def price_headline(field):
    """The only source of a headline price: {'amount', 'currency', 'pack', 'availability', 'vat', 'valid_until'}
    from a confirmed offer record, or None. Text quotes, store-data lines and saved runs without an offer
    record never produce one."""
    offer = offer_decision(field)
    if not offer or offer.get('state') != 'confirmed' or not isinstance(offer.get('headline'), dict):
        return None
    h = offer['headline']
    if not h.get('amount') or not h.get('currency'):
        return None
    vat = offer.get('vat_included')
    return {'amount': h['amount'], 'currency': h['currency'], 'pack': h.get('pack'),
            'availability': offer.get('availability', 'unknown'),
            'vat': 'VAT included' if vat is True else ('VAT not included' if vat is False else 'VAT basis not stated'),
            'valid_until': offer.get('valid_until'), 'read_date': offer.get('read_date')}


def offer_notes(field):
    """Plain sentences on the offer screen for a price field: why no headline, or what the headline rests on."""
    offer = offer_decision(field)
    facts = (field or {}).get('facts') or {} if isinstance(field, dict) else {}
    if offer is None:
        return ['price not tied to a structured offer record for this product and pack, so no price is shown '
                'as confirmed; the quotes below are page text only']
    notes = []
    head = price_headline(field)
    if head is None:
        notes += [str(r) for r in offer.get('reasons') or []]
    for r in offer.get('records') or []:
        avail = {True: 'in stock', False: 'out of stock'}.get(r.get('availability'), 'availability not stated')
        notes.append('%s: %s %s for %s, %s' % (ORIGIN_LABELS.get(r.get('origin'), r.get('origin')),
                                               r.get('currency') or '(no currency)', r.get('amount'),
                                               r.get('label') or r.get('sku') or 'the configured product', avail))
    if head is not None:
        if head.get('valid_until'):
            notes.append('the offer states it is valid until %s' % head['valid_until'])
        other = {_numbers(v) for v in _values(facts, 'amount')} - {_numbers(head['amount'])}
        if any(other):
            notes.append('page text also quotes other amounts; they are not tied to this offer')
    return notes


def field_status(field, name=None, row_fields=None):
    """{'word', 'notes', 'missing', 'code'} for one engine field result.
    For the price field the word comes from the structured offer screen, never from quotes alone. For the delivery
    charge, a field that reads Quoted becomes Needs review when a qualifier's quote contains another amount and not
    the shown charge; every stronger or weaker existing word is kept as it is."""
    if name == 'product_price':
        return _price_status(field)
    if name == 'delivery_charge':
        status = field_status(field)
        ctx = delivery_context(field, row_fields)
        if status['word'] == QUOTED and any(c['state'] == 'other_amount_only' for c in ctx['claims']):
            status['word'] = REVIEW
            status['notes'].append('a detail shown with this charge is quoted with another amount, so it is listed '
                                   'separately for review')
        return status
    field = field if isinstance(field, dict) else {}
    facts = field.get('facts') if isinstance(field.get('facts'), dict) else {}
    code = field.get('status')
    missing = [claim_label(k) for k in field.get('missing') or []]
    notes = []
    if code not in KNOWN_STATUSES:
        return {'word': UNRECOGNISED, 'notes': ['status code not recognised; shown as recorded'],
                'missing': missing, 'code': code}
    amounts = {_numbers(v) for v in _values(facts, 'amount')}
    numbered = [k for k in facts if k != 'amount' and len({_numbers(v) for v in _values(facts, k)}) > 1]
    worded = [k for k in facts if k not in numbered and k != 'amount'
              and len({v.strip().casefold() for v in _values(facts, k)}) > 1]
    if len(amounts) > 1:
        word = DISAGREE
        notes.append('different amounts quoted; both kept, no winner chosen')
    elif numbered:
        word = REVIEW
        notes.append('different numbers quoted for ' + ', '.join(claim_label(k) for k in numbered)
                     + '; a person must judge whether they mean the same thing')
    elif not any(facts.get(k) for k in facts):
        word = NOT_FOUND
    elif missing or code == 'incomplete':
        word = PARTLY
    else:
        word = QUOTED
    if worded:
        notes.append('wording differs for ' + ', '.join(claim_label(k) for k in worded))
    if field.get('binding_warning'):
        notes.append('charge basis or order condition not quoted with the charge, so not linked to it')
    context = field.get('context_status')
    if isinstance(context, dict) and context.get('status') != 'scoped_components_present':
        notes.append('pricing context not confirmed from the page table')
    if field.get('incomplete_components'):
        notes.append('a quoted value lacks a required unit or condition')
    return {'word': word, 'notes': notes, 'missing': missing if word != NOT_FOUND else [], 'code': code}


def _price_status(field):
    base = field_status(field)  # the quote-level reading, kept for its missing list and code
    offer = offer_decision(field)
    head = price_headline(field)
    if head is not None:
        word = OFFER_OUT if head['availability'] == 'unavailable' else (
            REVIEW if head['availability'] == 'conflicting' else OFFER_OK)
    elif offer is not None and offer.get('state') == 'conflicting':
        word = DISAGREE
    elif base['word'] in (NOT_FOUND, DISAGREE, REVIEW, UNRECOGNISED) and (offer is None or offer.get('state') in (
            'no_structured_offer', 'not_confirmed')):
        word = base['word']  # quote-level disagreement or absence stays visible; there is still no headline
    else:
        word = PRICE_UNCONFIRMED
    return {'word': word, 'notes': offer_notes(field) + base['notes'], 'missing': base['missing'],
            'code': base['code']}


def cell_values(name, field, row_fields=None):
    """[(claim label, [values])] for the claims a table cell shows first. A delivery qualifier is a headline value
    only when its own quote also contains the shown charge; the others are listed by delivery_context_lines."""
    if name == 'product_price':
        head = price_headline(field)
        if head is None:
            return []  # no confirmed offer: no headline amount or pack; the quotes stay in the list
        return [('price', [head['currency'] + ' ' + head['amount']]), ('pack size', [head['pack'] or '']),
                ('availability', [AVAILABILITY_WORDS.get(head['availability'], head['availability'])]),
                ('tax', [head['vat']])]
    facts = (field or {}).get('facts') or {}
    # A claim the engine reports missing (such as a basis not quoted with its charge) is kept in the
    # quote list but never shown as a headline value, so it cannot read as applying to the charge.
    missing = set((field or {}).get('missing') or [])
    out = []
    ctx = delivery_context(field, row_fields) if name == 'delivery_charge' else {}
    for key in MAIN_CLAIMS.get(name, list(facts)):
        if key in missing:
            continue
        values = list(dict.fromkeys(' '.join(str(c.get('value', '')).split()) for c in facts.get(key) or []
                                    if isinstance(c, dict) and c.get('value', '')
                                    and headline_claim_shown(name, key, c, ctx)))
        if values:
            out.append((claim_label(key), values))
    return out


def quotes(field):
    """Every accepted claim in a field: (claim label, value, quote, source url). Nothing is dropped."""
    facts = (field or {}).get('facts') or {}
    return [(claim_label(key), c.get('value', ''), c.get('quote', ''), c.get('source_url', ''))
            for key, claims in facts.items() for c in claims or [] if isinstance(c, dict)]


def quoted(field):
    """True when the field has its headline claim (the amount, where the field has one) quoted."""
    if price_headline(field) is not None:
        return True  # a confirmed offer record counts even when the model quoted nothing
    facts = (field or {}).get('facts') or {}
    if 'amount' in facts or 'amount' in ((field or {}).get('missing') or []):
        return bool(facts.get('amount'))
    return any(facts.get(k) for k in facts)


def coverage(rows, fields):
    """[(field label, quoted count, row count)] across rows, in field order."""
    rows = [r for r in rows if isinstance(r, dict)]
    return [(field_label(f), sum(1 for r in rows if quoted((r.get('atomic_fields') or {}).get(f))), len(rows))
            for f in fields]


def page_kind(url, first):
    path = urlparse(url).path
    if path.endswith('.js') or path.endswith('.json'):
        return "the store's product data file"
    if url == first:
        return 'the starting page'
    return 'a linked page (%s)' % (path or '/')


STOP_SENTENCES = {
    'no_relevant_source': 'No link to a page with the missing details was found, so it stopped there.',
    'possible_numeric_disagreement': 'It stopped after finding two different values for the same detail; '
                                     'both are kept.',
    'source_disagreement': 'It stopped after finding two different values for the same detail; both are kept.',
    'literal_checklist_present_review_required': 'It stopped because every requested detail was quoted.',
    'other_details_quoted_price_from_structured_records': 'It stopped because every other requested detail was '
        'quoted on the pages it read. The price was not looked for again: the page\'s structured offer records had '
        'already set it (a matched price, or records that disagree with no price chosen). Quoted details are not '
        'checked as complete or as applying to every order.',
    'duplicate_source': 'It stopped because the next page was one it had already read.',
    'unsafe_destination': 'It stopped because the next page was outside the approved site, so it was not opened.',
    'unsafe_redirect': 'It stopped because the page redirected outside the approved site.',
    'unsafe_variant_source': "It stopped because the store's product data was outside the approved site.",
    'tool_budget': 'It stopped at its step limit; what was read before the stop is kept.',
    'generation_budget': 'It stopped at its model-call limit; what was read before the stop is kept.',
    'provider_budget_stop': 'It stopped at the shared model-usage limit; what was read before the stop is kept.',
    'source_or_extraction_error': 'The page could not be read or its text could not be checked; nothing was '
                                  'guessed.',
    'unknowns': 'It stopped with some details still unknown.',
}


def how_it_ended(row, page_limit=2):
    """One plain paragraph: which pages were read and why the run for this source stopped."""
    row = row if isinstance(row, dict) else {}
    every = [p for p in row.get('pages_visited') or [] if isinstance(p, str)]
    # Newer results list store data files separately: read in code and not counted toward the page limit.
    data = set((row.get('store_data') or {}).get('files') or []) if isinstance(row.get('store_data'), dict) else set()
    pages = [p for p in every if p not in data]
    first = pages[0] if pages else ''
    kinds = [page_kind(p, first) for p in pages]
    if not pages:
        read = 'No page was read.'
    else:
        read = 'Read %d page%s: %s.' % (len(pages), '' if len(pages) == 1 else 's', ' and '.join(kinds))
    if data:
        read += (" It also read the store's product data file in code, without a model call; that file does not "
                 "count toward the page limit.")
    reason = row.get('stop_reason')
    if reason == 'page_budget':
        fields = row.get('atomic_fields') or {}
        delivery_missing = any(not quoted(fields.get(f)) for f in ('delivery_charge', 'delivery_time')
                               if f in fields)
        linked = any(k.startswith('a linked page') for k in kinds)
        why = 'That is its page limit (%d)' % page_limit
        why += (', so no delivery or shipping page was read.' if delivery_missing and not linked else '.')
    elif reason is None:
        why = 'This older result does not record why it stopped.'
    else:
        why = STOP_SENTENCES.get(reason, 'It stopped for a reason this page does not recognise.')
    if row.get('errors'):
        why += ' An error was recorded; it is listed in the technical details.'
    return read + ' ' + why


def same_core_facts(row_a, row_b):
    """True when two runs of one source quoted the same price and delivery-charge amounts."""
    def core(row):
        fields = (row or {}).get('atomic_fields') or {}
        return tuple(frozenset(_values((fields.get(f) or {}).get('facts') or {}, 'amount'))
                     for f in ('product_price', 'delivery_charge'))
    a, b = core(row_a), core(row_b)
    return all(a) and a == b

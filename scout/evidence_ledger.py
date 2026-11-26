"""Evidence ledger (evidence-ledger-v1): make saved delivery evidence inspectable without asserting shipping rules.

Pure and deterministic. It reads entries and saved page texts that are passed in, and returns plain data. It makes
no network, model or browser call, writes nothing and imports nothing from the research runtime or the UI.

What it records
- One observation for every persisted claim entry, in input order, including identical duplicates. Entries that
  were collapsed or dropped before the result was saved cannot be recovered here.
- For each observation, the saved-text source candidates and every exact occurrence of its quote in each candidate:
  Python string offsets, i.e. Unicode code points, start inclusive and end exclusive. Saved text is never
  normalised, and no single occurrence is chosen when a quote repeats.
- same_quote_span groups: two or more observations whose quotes each have exactly one occurrence in exactly one
  source candidate, with the same candidate and the same start/end. This is evidence that the words were quoted
  from one place. It never establishes that the claims belong to one shipping rule.
- Money tokens with an explicit currency marker (see MONEY_COVERAGE) in each saved text, with exact spans and the
  enclosing line. No role, rate, option identity, conversion or completeness is implied.
- A SHA-256 of each saved text as UTF-8. That is a hash of the text as saved, not of the original capture.

What it never claims: see NOT_CLAIMED.
"""
import hashlib
import re
from urllib.parse import urldefrag

LEDGER = 'evidence-ledger-v1'
DELIVERY_FIELDS = ('delivery_charge', 'free_delivery_threshold', 'delivery_time', 'delivery_geography')
NOT_CLAIMED = ('rule membership', 'applicability', 'option identity', 'footnote coverage', 'source currentness',
               'completeness', 'net or gross tax/weight', 'free means zero total', 'eligibility', 'delivered totals',
               'ranking', 'buyer validation')
HASH_NOTE = 'SHA-256 of the saved text encoded as UTF-8; not a hash of the original capture'
AS_OF_LABEL = ('as_of as recorded in the result; not stated to be the date the source was read and not a '
               'capture time')

MONEY_COVERAGE = {
    'markers_before_number': ['£', '€', '$', 'US$', 'GBP', 'EUR', 'USD'],
    'markers_after_number': ['GBP', 'EUR', 'USD', '€'],
    'space_between_marker_and_number': 'none or one ordinary space',
    'number_forms': ['digits with an optional decimal point and digits (4.95, 50)',
                     'digit groups separated by commas, optionally with a decimal part (1,250.00)',
                     'digits with a decimal comma and one or two digits, only after or before a euro marker (4,95)'],
    'not_recognised': ['amounts without an explicit currency marker (4.95, 50p, "pounds")',
                       'a marker separated from its number by a line break or more than one space',
                       'other comma forms such as £4,95, and other currencies or symbols',
                       'ranges, words for numbers and amounts split across lines'],
    'reported': 'the exact token slice, its marker and number text as written; never a numeric value or currency '
                'conversion',
}
_NUM = r'\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?'
_EURO_COMMA = r'\d+,\d{1,2}'
_MONEY = re.compile(
    r'(?<![\w.,$£€])(?:'
    r'(?P<m1>US\$|£|\$|GBP|USD)\x20?(?P<n1>' + _NUM + r')'
    r'|(?P<m2>€|EUR)\x20?(?P<n2>' + _EURO_COMMA + r'|' + _NUM + r')'
    r'|(?P<n3>' + _NUM + r')\x20?(?P<m3>GBP|USD)(?![A-Za-z])'
    r'|(?P<n4>' + _EURO_COMMA + r'|' + _NUM + r')\x20?(?P<m4>EUR(?![A-Za-z])|€)'
    r')(?!\d)(?![.,]\d)')


def text_sha256(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def occurrences(text, quote):
    """Every exact occurrence of quote in text, overlapping ones included: [(start, end)] in code points."""
    if not quote:
        return []
    found, i = [], text.find(quote)
    while i >= 0:
        found.append((i, i + len(quote)))
        i = text.find(quote, i + 1)
    return found


def money_tokens(text):
    """Recognised money tokens with spans and the enclosing line (see MONEY_COVERAGE)."""
    out = []
    for m in _MONEY.finditer(text):
        marker = m.group('m1') or m.group('m2') or m.group('m3') or m.group('m4')
        number = m.group('n1') or m.group('n2') or m.group('n3') or m.group('n4')
        line_start = max(text.rfind('\n', 0, m.start()), text.rfind('\r', 0, m.start())) + 1
        ends = [i for i in (text.find('\n', m.end()), text.find('\r', m.end())) if i >= 0]
        line_end = min(ends) if ends else len(text)
        out.append({'start': m.start(), 'end': m.end(), 'text': m.group(0), 'marker': marker, 'number_text': number,
                    'line_start': line_start, 'line_end': line_end, 'line': text[line_start:line_end]})
    return out


def _identity(url):
    """(raw address, document address) when a source address was recorded, else None. Absent, null, empty,
    whitespace-only and fragment-only addresses identify no document, so they never match anything."""
    if not isinstance(url, str) or not url.strip():
        return None
    address = urldefrag(url)[0]
    return (url, address) if address.strip() else None


def _candidates(raw_url, sources):
    """(source indexes, match basis): exact address first; a fragmentless match only when it is unique.
    Saved texts without a recorded address are never candidates."""
    if _identity(raw_url) is None:
        return [], 'no_source_identity'
    sources = [s for s in sources if s['source_identity'] == 'recorded']
    exact = [s['source_index'] for s in sources if s['source_url'] == raw_url]
    if exact:
        return exact, ('exact_url' if len(exact) == 1 else 'exact_url_multiple')
    doc = urldefrag(raw_url or '')[0]
    loose = [s['source_index'] for s in sources if s['document_address'] == doc]
    if len(loose) == 1:
        return loose, 'fragmentless_unique'
    if loose:
        return loose, 'fragmentless_multiple'
    return [], 'no_saved_source'


def build_ledger(entries, sources):
    """entries: [{'field', 'key', 'value', 'quote', 'source_url'}] in persisted order.
    sources: [{'source_url', 'text'}] in saved order. Returns the ledger for one result row (plain dict)."""
    src = []
    for i, s in enumerate(sources):
        url, text = s.get('source_url'), s.get('text', '')
        address, fragment = urldefrag(url) if isinstance(url, str) else ('', '')
        src.append({'source_index': i, 'source_url': url, 'document_address': address, 'fragment': fragment,
                    'source_identity': 'recorded' if _identity(url) else 'missing',
                    'length_code_points': len(text), 'text_sha256': text_sha256(text), 'hash_note': HASH_NOTE,
                    'money_tokens': money_tokens(text), '_text': text})
    observations = []
    for n, e in enumerate(entries):
        raw = e.get('source_url')
        address, fragment = urldefrag(raw) if isinstance(raw, str) else ('', '')
        quote = e.get('quote')
        cands, basis = _candidates(raw, src)
        occ = [] if not isinstance(quote, str) else [
            {'source_index': i, 'start': a, 'end': b} for i in cands for a, b in occurrences(src[i]['_text'], quote)]
        if not isinstance(quote, str) or not quote:
            status = 'quote_empty'
        elif basis == 'no_source_identity':
            status = 'source_identity_missing'  # no address was recorded, so no saved text is assumed
        elif not cands:
            status = 'source_not_saved'
        elif len(cands) > 1:
            status = 'source_ambiguous'
        elif not occ:
            status = 'quote_not_located'
        else:
            status = 'located_unique' if len(occ) == 1 else 'located_repeated'
        observations.append({'observation_id': 'obs-%d' % n, 'input_position': n, 'field': e.get('field'),
                             'key': e.get('key'), 'index_in_key': e.get('index_in_key'), 'value': e.get('value'),
                             'quote': quote, 'source_url_raw': raw, 'document_address': address,
                             'fragment': fragment, 'source_match': basis, 'source_candidates': cands,
                             'location_status': status, 'occurrences': occ})
    spans = {}
    for o in observations:
        if o['location_status'] == 'located_unique':
            x = o['occurrences'][0]
            spans.setdefault((x['source_index'], x['start'], x['end']), []).append(o['observation_id'])
    groups = [{'group': 'same_quote_span', 'source_index': k[0], 'start': k[1], 'end': k[2], 'observations': ids,
               'meaning': 'quoted from one unique saved span; not evidence of one shipping rule'}
              for k, ids in sorted(spans.items()) if len(ids) > 1]
    for s in src:
        del s['_text']
    return {'sources': src, 'observations': observations, 'same_quote_span_groups': groups}


def entries_from_row(row, fields=DELIVERY_FIELDS):
    """Persisted claim entries of one saved result row, in saved order, for the delivery fields only."""
    out = []
    for field in fields:
        facts = ((row.get('atomic_fields') or {}).get(field) or {}).get('facts') or {}
        for key, claims in facts.items():
            for j, c in enumerate(claims or []):
                if isinstance(c, dict):
                    out.append({'field': field, 'key': key, 'index_in_key': j, 'value': c.get('value'),
                                'quote': c.get('quote'), 'source_url': c.get('source_url', '')})
    return out


def ledger_for_result(result):
    """Ledger for every row of a saved result object. A read date is reported only from an explicitly recorded
    read_date field (on the result or the row); another kind of date such as as_of is kept under its own label in
    recorded_metadata and never relabelled. Folder or file names are never treated as dates or capture times."""
    recorded = result.get('read_date') if isinstance(result, dict) else None
    metadata = {}
    if isinstance(result, dict) and result.get('as_of'):
        metadata['as_of'] = {'value': result['as_of'], 'label': AS_OF_LABEL}
    rows = []
    for row in (result.get('rows') or []) if isinstance(result, dict) else []:
        if not isinstance(row, dict):
            continue
        ledger = build_ledger(entries_from_row(row), [t for t in row.get('page_texts') or [] if isinstance(t, dict)])
        rows.append({'site': row.get('site'), 'read_date': row.get('read_date') or recorded or 'not_recorded',
                     **ledger})
    return {'ledger': LEDGER, 'fields': list(DELIVERY_FIELDS), 'money_coverage': MONEY_COVERAGE,
            'not_claimed': list(NOT_CLAIMED), 'recorded_metadata': metadata, 'rows': rows}

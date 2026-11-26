"""Score saved live runs (atomic rows) against the supplier reference file and strict rubric.

Standard library only: the caller loads the reference (YAML) and passes plain dicts. One cell per
reference site and detail, for the sites a run actually targeted. The outcome compares what the run
quoted with the reference value; it never re-reads a page and never fills a gap.

Outcomes:
  Agrees               every rubric part is present in the run's quoted values and quotes
  Partly agrees        the amount (or, without an amount, some part) is present; other parts are missing
  Disagrees            the run quoted something, but not the reference amount (or no rubric part at all)
  Missed               the run quoted nothing for this detail; the reason says whether its page was read
  Reference unresolved the reference itself holds conflicting readings; the cell notes which one matched
  Not in the reference the reference has no verified value; anything quoted is left for a person to check
  Not scored           the reference has a value but the rubric has no parts for this detail
"""
import re
from urllib.parse import urlparse

AGREES, PARTLY, DISAGREES, MISSED = 'Agrees', 'Partly agrees', 'Disagrees', 'Missed'
UNRESOLVED, NOT_IN_REFERENCE, NOT_SCORED = 'Reference unresolved', 'Not in the reference', 'Not scored'
OUTCOMES = [AGREES, PARTLY, DISAGREES, MISSED, UNRESOLVED, NOT_IN_REFERENCE, NOT_SCORED]

PAGE_NOT_READ, READ_NOT_EXTRACTED = 'page_not_read', 'read_not_extracted'


def _money(component):
    """Rubric parts that carry an amount, e.g. GBP_4_95 or rendered_GBP_23_50."""
    return component.startswith('GBP_') or '_GBP_' in component


def _page(url):
    p = urlparse(url or '')
    return (p.netloc.casefold(), p.path.rstrip('/'))


def _quoted(field):
    facts = (field or {}).get('facts') or {}
    return [{'claim': key, 'value': c.get('value', ''), 'quote': c.get('quote', ''),
             'source_url': c.get('source_url', '')}
            for key, claims in facts.items() for c in claims or [] if isinstance(c, dict)]


def score_cell(site, field, reference_site, row, rubric_cell):
    ref = reference_site['fields'][field]
    quoted = _quoted((row.get('atomic_fields') or {}).get(field))
    text = ' '.join(q['value'] + ' ' + q['quote'] for q in quoted)
    components = (rubric_cell or {}).get('components') or {}
    found = [name for name, pattern in components.items() if re.search(pattern, text, re.I)]
    missing = [name for name in components if name not in found]
    source = ref.get('quote_source') or reference_site.get('url')
    cell = {'site': site, 'field': field, 'reference_value': ref.get('value'), 'reference_source': source,
            'quoted': quoted, 'components_found': found, 'components_missing': missing,
            'outcome': None, 'reason': None}
    if not ref.get('verified') or ref.get('value') in (None, ''):
        cell['outcome'] = NOT_IN_REFERENCE
        cell['reason'] = 'quoted_but_unchecked' if quoted else None
    elif (rubric_cell or {}).get('conflict'):
        cell['outcome'] = UNRESOLVED
        cell['reason'] = 'matched_readings:' + ','.join(n for n in found if _money(n)) if quoted else None
    elif not quoted:
        cell['outcome'] = MISSED
        read = {_page(u) for u in row.get('pages_visited') or []}
        cell['reason'] = READ_NOT_EXTRACTED if _page(source) in read else PAGE_NOT_READ
    elif not components:
        cell['outcome'] = NOT_SCORED
    else:
        money = [n for n in components if _money(n)]
        if (money and not any(n in found for n in money)) or not found:
            cell['outcome'] = DISAGREES
        elif not missing:
            cell['outcome'] = AGREES
        else:
            cell['outcome'] = PARTLY
    return cell


def score_run(rows, reference, rubric):
    """Cells for every reference detail of each site the run has a row for, in reference order."""
    by_site = {r.get('site'): r for r in rows if isinstance(r, dict)}
    by_cell = {(c['site'], c['field']): c for c in rubric}
    cells = []
    for site, spec in reference['sites'].items():
        if site not in by_site:
            continue
        for field in spec['fields']:
            cells.append(score_cell(site, field, spec, by_site[site], by_cell.get((site, field))))
    totals = {o: sum(1 for c in cells if c['outcome'] == o) for o in OUTCOMES}
    return {'cells': cells, 'totals': totals}

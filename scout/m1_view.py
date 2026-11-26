"""Buyer-readable view of the M1 comparison layer for the local UI (page /m1). Offline: no network, no file writes.

Scenarios are fixed: the recorded runs of 30 October 2026, and five invented synthetic scenarios (S1-S5) built by
scripts/compare_offline.py. The order answered is fixed per scenario; there is no order form and no saved-run wiring.
The main view shows plain words only: no raw JSON and no internal state codes. Exact quotes sit behind a disclosure.
"""
import importlib.util
from datetime import date
from html import escape
from pathlib import Path

from scout.engine import supplier_comparison as sc

ROOT = Path(__file__).resolve().parents[1]
RECORDED_BANNER = 'Recorded: saved 30 Oct 2026 records, not live'
SYNTHETIC_BANNER = 'Synthetic: invented mills, not supplier facts'
RECORDED_ORDER = {'pack': '16kg', 'quantity': 1, 'destination': 'England mainland'}
RECORDED_READ = date(2026, 10, 30)
SYNTHETIC_READ = date(2026, 11, 25)
ELIGIBILITY_WORDS = {'eligible': 'Eligible', 'ineligible': 'Excluded', 'unverifiable': 'Could not be verified'}
MEMBERSHIP_WORDS = {'qualified': 'qualifies for free delivery', 'not_qualified': 'does not qualify for free delivery',
                    'abstained': 'free-delivery rule not evaluated'}
TAB_NAMES = {'s1': 'Delivery decides the winner', 's2': 'Mixed VAT, quoted rate', 's3': 'Same pack, written two ways',
             's4': 'Conflicting and excluded', 's5': 'VAT unknown: no ranking'}
KIND_WORDS = {'free_threshold': 'free delivery under the quoted threshold', 'standard': 'standard delivery charge',
              'regional': 'regional delivery charge'}


def _demo():
    spec = importlib.util.spec_from_file_location('compare_offline_for_m1_view', ROOT / 'scripts' / 'compare_offline.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def scenarios():
    """(key, short label, title) for the selector; keys are the only accepted ?s= values."""
    demo = _demo()
    out = [('recorded', 'Saved records, 30 Oct', 'Recorded runs of 30 October 2026')]
    for n, (title, _fn) in enumerate(demo.SYNTHETIC_SECTIONS, 1):
        out.append(('s%d' % n, TAB_NAMES.get('s%d' % n, 'S%d' % n), title.split('. ', 1)[1]))
    return out


def _invented_label(supplier):
    return 'Demo Mill %s (invented)' % supplier.rsplit('_', 1)[-1].upper()


def build(key):
    """Assessments, verdict/claim, order, banner and evidence date for one fixed scenario. Unknown keys: None."""
    demo = _demo()
    if key == 'recorded':
        assessments, result = demo.recorded(dict(RECORDED_ORDER), RECORDED_READ)
        if assessments:
            result = sc.compare(assessments, RECORDED_ORDER, RECORDED_READ)
        return {'assessments': assessments, 'result': result, 'order': RECORDED_ORDER, 'banner': RECORDED_BANNER,
                'recorded': True, 'evidence_date': ('30 October 2026 (saved records; nothing was re-checked)'
                                                    if demo.recorded_bundled() else
                                                    'none shown: the saved 30 October 2026 records are not included '
                                                    'in this copy')}
    keys = {'s%d' % n: fn for n, (_t, fn) in enumerate(demo.SYNTHETIC_SECTIONS, 1)}
    if key not in keys:
        return None
    order = dict(demo.SYN_ORDER)
    assessments, _ = keys[key](dict(order), SYNTHETIC_READ)
    for a in assessments:  # readable invented names; the comparison is re-run so its claim uses them
        a['label'] = _invented_label(a['supplier'])
    result = sc.compare(assessments, order, SYNTHETIC_READ)
    return {'assessments': assessments, 'result': result, 'order': order, 'banner': SYNTHETIC_BANNER,
            'recorded': False, 'evidence_date': 'undated invented quotes'}


def _quotes(a, recorded_quotes):
    """Exact quotes behind the supplier's row, each with what it was used for."""
    out = []
    d = a.get('delivery') or {}
    if d.get('applied'):
        out.append(('delivery rule applied', d['applied'].get('basis_quote'), d['applied'].get('source_url')))
    for c in d.get('components') or []:
        out.append((c.get('label', 'delivery charge'), c.get('quote'), c.get('source_url')))
    b = (a.get('delivered_total') or {}).get('cost_basis') or {}
    if b.get('vat_rate_quote'):
        out.append(('VAT rate quoted', b['vat_rate_quote'], None))
    if a['eligibility'].get('basis_quote'):
        out.append(('eligibility rule', a['eligibility']['basis_quote'], None))
    for r in a.get('unevaluable_rules') or []:
        out.append(('rule that could not be evaluated', r.get('quote'), r.get('source_url')))
    out += [('saved delivery quote (%s)' % o['field'].replace('_', ' '), o['quote'], o['source_url'])
            for o in recorded_quotes]
    return [q for q in out if q[1]]


def _inc_vat(t):
    """VAT-inclusive equivalent of a VAT-exclusive total, only with a quoted rate (same arithmetic as the engine)."""
    b = t.get('cost_basis') or {}
    if not b.get('vat_rate'):
        return None
    from decimal import Decimal, ROUND_HALF_UP
    r = Decimal(sc._RATE.search(b['vat_rate']).group(1)) / 100
    parts = [Decimal(b['goods']) * ((1 + r) if b['product_vat'] == 'ex' else 1),
             Decimal(b['delivery']) * ((1 + r) if b['delivery_vat'] == 'ex' else 1)]
    return str((parts[0] + parts[1]).quantize(Decimal('0.01'), ROUND_HALF_UP))


def _status(a):
    """(headline, reason in words or '')."""
    t = a.get('delivered_total')
    if t:
        b = t.get('cost_basis') or {}
        if b.get('product_vat') is None or b.get('delivery_vat') is None:
            return 'Quoted total £%s, VAT not confirmed' % t['amount'], ''
        if 'ex' in (b.get('product_vat'), b.get('delivery_vat')):
            norm = _inc_vat(t)
            if norm:  # the comparable, same-basis figure is primary; the original quote is secondary
                return ('£%s delivered, inc VAT' % norm,
                        'Converted from £%s ex VAT at the quoted %s' % (t['amount'], b['vat_rate']))
            return '£%s delivered, ex VAT' % t['amount'], ''
        return '£%s delivered, inc VAT' % t['amount'], ''
    s = a.get('summary') or ''
    head = {'ineligible': 'Excluded', 'unverifiable': 'Not verified'}.get(a['eligibility']['state'], 'No delivered total')
    for prefix in ('excluded: ', 'could not be verified: '):
        if s.startswith(prefix):
            s = s[len(prefix):]
    return head, s[:1].upper() + s[1:]


def _basis(a):
    t = a.get('delivered_total')
    lines = list(t['basis_notes']) if t else []
    d = a.get('delivery') or {}
    free = d.get('applied') and d['applied'].get('kind') == 'free_threshold'
    if d.get('applied') and d['applied'].get('kind') in KIND_WORDS and not free:  # the basis note already says free
        lines.insert(0, '%s: £%s' % (KIND_WORDS[d['applied']['kind']], d['applied']['amount']))
    if a.get('membership') in MEMBERSHIP_WORDS and a['eligibility']['state'] == 'eligible' and not free:
        lines.append(MEMBERSHIP_WORDS[a['membership']])
    return lines


def _short_claim(result):
    """The licensed claim, shortened only when no ranking was licensed for a comparability reason: the per-supplier
    cards carry each total and reason, and the full wording stays one click away."""
    v = result.get('verdict')
    nc = v.get('not_comparable') if isinstance(v, dict) else None
    if not nc:
        return result['claim']
    why = ('the VAT basis is not confirmed for every price and charge' if nc['reason'].startswith('VAT basis not stated')
           else nc['reason'])
    return 'No ranking: %s, so the %d quoted totals are not compared. Each card shows its total and reason.' % (
        why, len(nc['verified']))


def body(key):
    """HTML body for /m1?s=<key>. An unknown key falls back to the recorded scenario."""
    demo = _demo()
    data = build(key) or build('recorded')
    key = key if build(key) else 'recorded'
    o = data['order']
    tabs = ''.join('<a class="m1-tab%s" href="/m1?s=%s"%s>%s%s</a>' % (
        ' on' if k == key else '', k, ' aria-current="page"' if k == key else '', escape(lbl),
        ' <span class="m1-id">%s</span>' % k.upper() if k != 'recorded' else '')
        for k, lbl, _t in scenarios())
    title = next(t for k, _l, t in scenarios() if k == key)
    rows = []
    for a in data['assessments']:
        rec = demo.recorded_observations(a['supplier']) if data['recorded'] else []
        quotes = _quotes(a, rec)
        basis = _basis(a)
        head, reason = _status(a)
        removed = sum(1 for q in quotes if q[1].startswith('[removed for publication'))
        label = ('%d saved quote%s; text removed in this sanitised copy' % (len(quotes), '' if len(quotes) == 1 else 's')
                 if quotes and removed == len(quotes) else
                 '%d exact quote%s' % (len(quotes), '' if len(quotes) == 1 else 's'))
        rows.append(
            '<div class="card m1-row"><h3>%s</h3><p class="m1-total">%s</p>%s%s<p class="muted">%s</p>%s</div>' % (
                escape(a['label']), escape(head),
                '<p class="m1-reason">%s</p>' % escape(reason) if reason else '',
                ('<ul class="m1-basis">%s</ul>' % ''.join('<li>%s</li>' % escape(b) for b in basis)) if basis else '',
                escape(ELIGIBILITY_WORDS.get(a['eligibility']['state'], 'Not assessed')) if a['eligibility']['state'] == 'eligible' else '',
                ('<details class="ev"><summary>Evidence and details (%s)</summary><ul>%s</ul></details>'
                 % (label, ''.join(
                     '<li><span class="muted">%s:</span> &ldquo;%s&rdquo;%s</li>' % (
                         escape(use), escape(q.replace('\n', ' / ')),
                         ' <span class="muted">(%s)</span>' % escape(url) if url else '')
                     for use, q, url in quotes))) if quotes else
                '<p class="muted">No quotes were used for this supplier.</p>'))
    kind = 'Recorded evidence' if data['recorded'] else 'Invented demonstration'
    return ''.join([
        '<h1>M1 comparison</h1>',
        '<nav class="m1-tabs" aria-label="Scenario">', tabs, '</nav>',
        '<p class="m1-kind">%s: %s</p>' % (kind, escape(title)),
        '<div class="card m1-claim"><p class="m1-order"><strong>Order answered:</strong> %d &times; %s to %s</p>'
        % (o['quantity'], escape(o['pack']), escape(o['destination'])),
        '<p class="m1-sentence">%s</p>' % escape(_short_claim(data['result'])),
        ('<details class="how"><summary>Full claim wording</summary><p>%s</p></details>'
         % escape(data['result']['claim']) if _short_claim(data['result']) != data['result']['claim'] else ''),
        '<p class="muted"><strong>Evidence date:</strong> %s</p></div>' % escape(data['evidence_date']),
        '<div class="m1-rows">', ''.join(rows), '</div>',
        '<p class="muted">Prices count only when a structured offer record confirms them; page text is never read '
        'as a price. Suppliers are ranked only on the same order and a known, matching VAT basis. This page '
        'fetches nothing.</p>'])


def banner(key):
    data = build(key) or build('recorded')
    return data['banner']


CSS = """
.m1-tabs{display:flex;flex-wrap:wrap;gap:.4rem;margin:.6rem 0 1rem}
.m1-tab{padding:.35rem .8rem;border:1px solid var(--line);border-radius:999px;text-decoration:none;color:var(--fg)}
.m1-tab.on{background:var(--accent);color:var(--on-accent);border-color:var(--accent)}
.m1-kind{font-weight:600;margin:.2rem 0}.m1-sentence{font-size:1.12rem;line-height:1.5;margin:.5rem 0}
.m1-rows{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1rem}
.m1-row{margin:0}.m1-row h3{margin:.1rem 0 .3rem}.m1-total{font-size:1.25rem;font-weight:700;margin:.2rem 0}
.m1-id{font-size:.75em;opacity:.7;margin-left:.3rem}.m1-reason{margin:.2rem 0 .4rem}.m1-basis{margin:.3rem 0;padding-left:1.1rem;font-size:.92em}
"""

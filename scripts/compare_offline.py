"""Offline demo of the M1 comparison layer (scout/engine/supplier_comparison.py). Standard library only, no network.

    python3 -S scripts/compare_offline.py                 # recorded mode only (the default)
    python3 -S scripts/compare_offline.py --synthetic     # recorded mode, then a separate synthetic section

RECORDED mode uses only the recorded runs of 30 October 2026 in eval-results/live-30oct/: the delivery claims and
verbatim quotes those runs saved from the supplier pages. They are not a live capture. Those runs predate structured
offer capture, so they hold no offer records, and the comparison layer never takes a price from page text: every
supplier's price is unconfirmed and the honest result is a partial one with abstentions.

SYNTHETIC mode adds invented demonstration scenarios on reserved .example addresses that show how the flow decides.
Nothing in that section is a recorded quote or a supplier fact.

Writes comparison.md and result.json to a new folder under sample-runs/ (git-ignored); never overwrites.
"""
import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scout.engine import offers  # noqa: E402
from scout.engine import supplier_comparison as sc  # noqa: E402
from scout.workflows import supplier  # noqa: E402

RECORDED_DIR = ROOT / 'eval-results' / 'live-30oct'
RECORDED_LABEL = ('RECORDED EVIDENCE: delivery claims and verbatim quotes saved by the recorded runs of 30 October 2026 '
                  'from the suppliers\' public pages (eval-results/live-30oct). Not a live capture; prices and terms may '
                  'have changed since.')
SYNTHETIC_LABEL = ('SYNTHETIC DEMONSTRATION DATA: invented scenarios on reserved .example addresses. Not recorded quotes '
                   'and not supplier facts.')
# plain words for the offer screen's state codes; the codes stay in result.json, never in the readable report
OFFER_WORDS = {'confirmed': 'confirmed', 'conflicting': 'records conflict', 'not_confirmed': 'not confirmed',
               'no_structured_offer': 'no structured offer captured', 'unsupported': 'record could not be read'}
FIELDS = ('delivery_charge', 'free_delivery_threshold', 'delivery_time', 'delivery_geography')


def recorded_observations(site):
    """Delivery claims exactly as the recorded run saved them (field, key, value, verbatim quote, source URL)."""
    row = json.loads((RECORDED_DIR / ('%s-result.json' % site)).read_text(encoding='utf-8'))['rows'][0]
    out = []
    for field in FIELDS:
        for key, claims in ((row['atomic_fields'].get(field) or {}).get('facts') or {}).items():
            for c in claims:
                out.append({'field': field, 'key': key, 'value': c['value'], 'quote': c['quote'],
                            'source_url': c['source_url'], 'evidence_date': '2026-10-30',
                            'provenance': 'recorded live run 30 Oct 2026'})
    return out


NOT_BUNDLED = ('No recorded comparison: the saved 30 October 2026 records are not included in this copy (they are kept '
               'privately), so nothing from them is shown.')


def recorded_bundled():
    return all((RECORDED_DIR / ('%s-result.json' % s['name'])).is_file() for s in supplier.WORKFLOW['sites'])


def recorded(order, read):
    if not recorded_bundled():
        return [], {'verdict': 'none', 'claim': NOT_BUNDLED}
    bindings = {s['name']: s['offer_binding'] for s in supplier.WORKFLOW['sites']}
    sites = [s['name'] for s in supplier.WORKFLOW['sites']]
    # The recorded runs saved no structured offer captures, so each supplier is assessed with none.
    assessments = [sc.assess_supplier(s, [], recorded_observations(s), order, bindings[s], read) for s in sites]
    return assessments, sc.compare(assessments, order, read)


# -- synthetic scenarios (invented; never presented as recorded) ------------------------------------------------
SYN_ORDER = {'pack': '16kg', 'quantity': 4, 'destination': 'England mainland'}


def _syn_product(host, price, vat=None, pack='16kg'):
    """Invented JSON-LD offer. vat: True = stated VAT-inclusive, False = stated VAT-exclusive, None = not stated."""
    url = 'https://%s/products/demo-flour' % host
    offer = {'@type': 'Offer', 'price': price, 'priceCurrency': 'GBP', 'availability': 'https://schema.org/InStock',
             'url': url}
    if vat is not None:
        offer['priceSpecification'] = {'@type': 'PriceSpecification', 'valueAddedTaxIncluded': vat}
    return {'origin': 'jsonld', 'body': json.dumps({'@type': 'Product', 'name': 'Demo flour %s' % pack, 'url': url,
                                                    'sku': 'DEMO16', 'offers': offer})}


def _syn_obs(field, key, value, quote, host):
    return {'field': field, 'key': key, 'value': value, 'quote': 'SYNTHETIC: ' + quote,
            'source_url': 'https://%s/delivery' % host, 'evidence_date': None,
            'provenance': 'constructed: synthetic demonstration, invented'}


def _free_over_50(host):
    q = 'free delivery on orders over £50'
    return [_syn_obs('free_delivery_threshold', k, v, q, host)
            for k, v in (('amount', '£50'), ('comparison', 'over'), ('zone', 'UK addresses'))]


def _charge(host, amount, basis=None):
    q = 'standard delivery %s%s' % (amount, ' ' + basis if basis else '')
    return [_syn_obs('delivery_charge', 'amount', amount, q, host), _syn_obs('delivery_charge', 'zone', 'UK', q, host)]


def _run(scenarios, order, read):
    assessments = []
    for name, (raw, obs, pack) in scenarios.items():
        host = name.replace('demo_', '').replace('_', '-') + '.example'
        binding = {'product_path': '/products/demo-flour', 'sku': 'DEMO16', 'pack': pack, 'single_offer': True}
        caps = offers.captures_from_raw(raw, 'https://%s/products/demo-flour' % host)
        assessments.append(sc.assess_supplier(name, caps, obs, dict(order, pack=pack), binding, read))
    return assessments, sc.compare(assessments, order, read)


def synthetic_delivery_decides(order, read):
    """Known, consistent VAT (all VAT-inclusive). B has the lower product price; delivery makes A the lower total."""
    return _run({'demo_mill_a': ([_syn_product('mill-a.example', '16.00', vat=True)], _free_over_50('mill-a.example'), '16kg'),
                 'demo_mill_b': ([_syn_product('mill-b.example', '15.50', vat=True)],
                                 _charge('mill-b.example', '£5.95', 'inc VAT'), '16kg')}, order, read)


def synthetic_mixed_basis(order, read):
    """One mill quotes VAT-inclusive, the other VAT-exclusive WITH a quoted 20% rate: normalised, then ranked."""
    rate = _syn_obs('price_vat', 'rate', '20%', 'all prices exclude VAT at 20%', 'mill-f.example')
    return _run({'demo_mill_e': ([_syn_product('mill-e.example', '16.00', vat=True)],
                                 _charge('mill-e.example', '£5.00', 'inc VAT'), '16kg'),
                 'demo_mill_f': ([_syn_product('mill-f.example', '13.00', vat=False)],
                                 _charge('mill-f.example', '£4.00', 'ex VAT') + [rate], '16kg')}, order, read)


def synthetic_pack_normalised(order, read):
    """The same pack written two ways ('16kg' and '16 kg'): an equivalent pack, so the mills rank."""
    return _run({'demo_mill_g': ([_syn_product('mill-g.example', '16.50', vat=True)],
                                 _charge('mill-g.example', '£3.85', 'inc VAT'), '16kg'),
                 'demo_mill_h': ([_syn_product('mill-h.example', '16.75', vat=True, pack='16 kg')],
                                 _charge('mill-h.example', '£4.50', 'inc VAT'), '16 kg')}, order, read)


def synthetic_not_verified(order, read):
    """One verified mill, one with conflicting price records, one excluded: no ranking with one verified."""
    conflict = [_syn_product('mill-c.example', '14.00', vat=True),
                {'origin': 'application_json', 'body': json.dumps({'handle': 'demo-flour', 'variants': [
                    {'id': 1, 'title': '16kg', 'sku': 'DEMO16', 'price': 1550, 'available': True}]})}]
    return _run({'demo_mill_a': ([_syn_product('mill-a.example', '16.00', vat=True)], _free_over_50('mill-a.example'), '16kg'),
                 'demo_mill_c': (conflict, _charge('mill-c.example', '£3.95', 'inc VAT'), '16kg'),
                 'demo_mill_d': ([_syn_product('mill-d.example', '15.00', vat=True)],
                                 [_syn_obs('order_eligibility', 'minimum_order', '£100', 'minimum order value £100',
                                           'mill-d.example')] + _charge('mill-d.example', '£4.50', 'inc VAT'), '16kg')},
                order, read)


def synthetic_unknown_vat(order, read):
    """NEGATIVE: two verified mills whose VAT basis is never stated. The layer must refuse to rank."""
    return _run({'demo_mill_p': ([_syn_product('mill-p.example', '16.00')], _free_over_50('mill-p.example'), '16kg'),
                 'demo_mill_q': ([_syn_product('mill-q.example', '15.50')], _charge('mill-q.example', '£5.95'), '16kg')},
                order, read)


SYNTHETIC_SECTIONS = (
    ('S1. Ranking with known, consistent VAT: delivery decides the winner', synthetic_delivery_decides),
    ('S2. Mixed VAT basis with an explicitly quoted rate: normalised, then ranked', synthetic_mixed_basis),
    ('S3. Pack written two equivalent ways: ranked', synthetic_pack_normalised),
    ('S4. Conflicting and excluded mills beside one verified mill: no ranking', synthetic_not_verified),
    ('S5. NEGATIVE: VAT basis unknown on both verified mills: ranking refused', synthetic_unknown_vat),
)


def synthetic(order, read):
    """Backwards-compatible single section (S1)."""
    return synthetic_delivery_decides(order, read)


# -- rendering ----------------------------------------------------------------------------------------------------
def _supplier_lines(a, tag):
    lines = ['- **%s** [%s]: offer %s; eligibility `%s`%s' % (
        a['label'], tag, OFFER_WORDS.get(a['offer_state'], 'not confirmed'), a['eligibility']['state'],
        (' (%s)' % a['eligibility'].get('reason')) if a['eligibility'].get('reason') else '')]
    if a['membership'] is None:
        lines.append('  - membership: not applicable (no free-delivery rule quoted)')
    else:
        lines.append('  - membership: `%s`%s' % (a['membership'], (' (%s)' % a['membership_reason'])
                                                if a.get('membership_reason') else ''))
    d = a.get('delivery') or {}
    if d.get('applied'):
        lines.append('  - delivery applied: £%s (quote: "%s")' % (d['applied']['amount'], d['applied']['basis_quote']))
    if d.get('abstained'):
        lines.append('  - delivery abstained: %s' % d['abstained']['reason'])
    for c in d.get('components') or []:
        lines.append('  - component: £%s, %s (quote: "%s")' % (c['amount'], c['label'], c['quote']))
    t = a.get('delivered_total')
    lines.append('  - delivered total: %s' % (('£%s = %s; %s' % (t['amount'], t['arithmetic'], '; '.join(t['basis_notes'])))
                                             if t else 'none (%s)' % a['summary']))
    return lines


def _recorded_quotes(site):
    return ['  - [RECORDED 30 Oct 2026] %s.%s = "%s": "%s" (%s)' % (o['field'], o['key'], o['value'],
                                                                  o['quote'].replace('\n', ' / '), o['source_url'])
            for o in recorded_observations(site)]


def render(order, read, rec, syn):
    finding = ('Finding: the saved 30 October 2026 records are not included in this copy, so the recorded section '
               'shows no comparison.' if not rec[0] else None)
    out = ['# Scott M1 comparison layer: offline demo', '',
           'Order: %d x %s to %s. No network; standard library only.' % (order['quantity'], order['pack'], order['destination']), '',
           '## RECORDED (evidence)', '', RECORDED_LABEL if rec[0] else 'RECORDED EVIDENCE: not included in this copy.', '',
           finding or ('Finding: the saved 30 October 2026 records lack a structured price for every supplier (the runs '
                       'predate structured offer capture), and the layer never takes a price from page text. Nothing was '
                       're-checked today: "no comparison" is the honest result on these saved records, not a fresh '
                       'verification attempt.'), '',
           '**Verdict:** `%s`' % json.dumps(rec[1]['verdict'], ensure_ascii=False), '', '**Claim licensed:** %s' % rec[1]['claim'], '']
    for a in rec[0]:
        out += _supplier_lines(a, 'RECORDED')
        out += ['  - delivery quotes on record:'] + (_recorded_quotes(a['supplier']) or ['  - (none recorded)'])
    if syn:
        out += ['', '---', '', '## SYNTHETIC (demonstration only, not evidence)', '', SYNTHETIC_LABEL, '',
                'Synthetic order: %d x %s to %s (invented). Every mill below is invented, on a reserved .example '
                'address; every quote is prefixed SYNTHETIC.' % (SYN_ORDER['quantity'], SYN_ORDER['pack'],
                                                                 SYN_ORDER['destination']), '']
        for title, (assessments, result) in syn:
            out += ['### %s [SYNTHETIC]' % title, '',
                    '**Verdict:** `%s`' % json.dumps(result['verdict'], ensure_ascii=False), '',
                    '**Claim licensed (synthetic):** %s' % result['claim'], '']
            for a in assessments:
                out += _supplier_lines(a, 'SYNTHETIC')
            out += ['']
    return '\n'.join(out) + '\n'


def main(argv=None):
    p = argparse.ArgumentParser(description='Offline demo of the M1 comparison layer.')
    p.add_argument('--synthetic', action='store_true', help='add the separately labelled synthetic section')
    p.add_argument('--output-dir', default='sample-runs', help='parent folder (git-ignored sample-runs by default)')
    a = p.parse_args(argv)
    order = {'pack': '16kg', 'quantity': 1, 'destination': 'England mainland'}
    rec = recorded(order, date(2026, 10, 30))
    syn = [(t, f(dict(SYN_ORDER), date(2026, 11, 25))) for t, f in SYNTHETIC_SECTIONS] if a.synthetic else None
    target = Path(a.output_dir) / ('compare-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    target.mkdir(parents=True, exist_ok=False)
    md = render(order, date(2026, 10, 30), rec, syn)
    if syn:
        md = md.replace('Order: 1 x 16kg', 'Recorded order: 1 x 16kg', 1)
    result = {'recorded': {'label': RECORDED_LABEL, 'order': order, 'verdict': rec[1]['verdict'], 'claim': rec[1]['claim'],
                           'assessments': rec[0]}}
    if syn:
        result['synthetic'] = {'label': SYNTHETIC_LABEL, 'order': SYN_ORDER, 'sections': [
            {'title': t, 'verdict': r['verdict'], 'claim': r['claim'], 'assessments': a} for t, (a, r) in syn]}
    (target / 'comparison.md').write_text(md, encoding='utf-8')
    (target / 'result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + '\n', encoding='utf-8')
    sys.stdout.write(md)
    sys.stdout.write('\nsaved_to: %s\n' % target)
    return 0


if __name__ == '__main__':
    sys.exit(main())

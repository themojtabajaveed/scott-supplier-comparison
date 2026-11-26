"""Supplier comparison layer (comparison-contract-v0.1): eligibility, delivery-rule membership,
delivered totals and the cross-supplier verdict for one product, one pack, a quantity and a destination.

Composes the existing offer screen (offers.bind_offer) for every price decision; it never re-reads prices
from text. Every decision carries its reasons, every applied rule keeps its quote, and it fails closed:
- a threshold qualifies only by its quoted wording ("from"/"at least" include equality, "over"/"above"
  exclude it); anything else abstains;
- VAT is converted only with a quoted rate; an ungrounded comparison abstains;
- a missing delivery charge is never free, so there is then no delivered total;
- an unresolved free-delivery decision gives no total and no upper bound; applicable quoted charges are listed as
  labelled components instead; a per-parcel charge needs a stated parcel count, never the item quantity;
- zone and exclusions come from structured claims only; a zone-only fragment is context, never a rule;
- separate charge quotes are listed separately and never merged;
- a minor-unit store record never supplies a currency (the offer screen already refuses it);
- the verdict names a cheapest supplier only among verified totals, and says who was excluded or
  could not be verified.

Pure and offline: no network, model or browser calls. Development contract: the 23 reviewed cases in
tests/comparison_expected.json are exposed development cases, not held-out evidence.
"""
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urldefrag

from . import offers
from .store_data import _pack_matches

CONTRACT = 'comparison-contract-v0.1'
SUPPLIER_LABELS = {'wessex_mill': 'Wessex Mill', 'shipton_mill': 'Shipton Mill', 'cotswold': 'Cotswold'}
CENT = Decimal('0.01')

# Destinations this layer can place inside quoted areas. A destination or area outside this explicit table is
# never guessed: an unknown area is "not established", and an area with "most of" wording is ambiguous.
AREAS = {
    'england mainland': {'england mainland', 'england', 'great britain', 'mainland uk', 'uk mainland', 'uk',
                         'united kingdom', 'uk addresses', 'standard uk'},
    'northern ireland': {'northern ireland', 'uk', 'united kingdom', 'uk addresses'},
    'channel islands': {'channel islands'},
}
INCLUSIVE = ('from', 'at least', 'or more', 'and above', 'and over', 'minimum of')
STRICT = ('over', 'above', 'more than', 'exceeding', 'in excess of')
_GBP = re.compile(r'(?:£|GBP\s?)(\d+(?:,\d{3})*(?:\.\d+)?)')
_RATE = re.compile(r'(\d+(?:\.\d+)?)\s?%')


def _money(text):
    """Decimal for the single GBP amount in text, else None (never guessed)."""
    found = _GBP.findall(text or '')
    return Decimal(found[0].replace(',', '')) if len(found) == 1 else None


def _fmt(d):
    return format(Decimal(d).quantize(CENT, ROUND_HALF_UP), 'f')


def _day(iso):
    d = date.fromisoformat(iso[:10])
    return '%d %s %d' % (d.day, d.strftime('%b'), d.year)


def _norm_area(text):
    t = (text or '').strip().strip('*').strip().rstrip('.:').strip().lower()
    return t[4:] if t.startswith('the ') else t


def _in_area(destination, area):
    """True / False when the explicit table decides; None when the area wording is not specific."""
    a = _norm_area(area)
    if 'most of' in a:
        return None
    known = AREAS.get(_norm_area(destination))
    if known is None:
        return None
    return a in known


def _doc(url):
    return urldefrag(url or '')[0]


def _vat_basis(quote):
    q = (quote or '').lower()
    if any(w in q for w in ('before vat', 'ex vat', 'excluding vat', 'exc vat', 'exc. vat', '+ vat', 'plus vat')):
        return 'ex'
    if any(w in q for w in ('inc vat', 'inc. vat', 'including vat', 'incl vat', 'incl. vat')):
        return 'inc'
    return None


def _operator(word):
    w = (word or '').strip().lower()
    if w in INCLUSIVE or any(w == x or w.startswith(x + ' ') for x in INCLUSIVE):
        return 'inclusive'
    if w in STRICT or any(w == x or w.startswith(x + ' ') for x in STRICT):
        return 'strict'
    return None


# -- offer ------------------------------------------------------------------------------------------------------

def _offer_status(decision, pack):
    """(eligibility state or None, reason, evidence) from an offer decision; None means the price is usable."""
    state = decision.get('state')
    reasons = ' '.join(decision.get('reasons') or [])
    if state == 'not_confirmed' and 'planned pack is not the configured pack' in reasons:
        return 'ineligible', 'offer not confirmed for the requested pack', 'offer decision not_confirmed (unconfigured pack)'
    if state == 'conflicting':
        recs = decision.get('records') or []
        if 'amount' in (decision.get('conflicts') or []):
            label = {'inline_script': 'page', 'jsonld': 'structured data', 'application_json': 'store record'}
            parts = sorted(((label.get(r['origin'], r['origin']), r['amount']) for r in recs if r.get('amount')),
                           key=lambda p: (p[0] != 'page', p[0]))
            return 'unverifiable', 'conflicting prices: ' + ' vs '.join('%s £%s' % p for p in parts), None
        return 'unverifiable', 'conflicting ' + ', '.join(decision.get('conflicts') or []), None
    if state == 'confirmed':
        if decision.get('availability') == 'unavailable':
            signals = decision.get('availability_signals') or []
            words = {1: 'one', 2: 'two', 3: 'three', 4: 'four'}
            return ('ineligible', 'product unavailable',
                    "offer decision availability 'unavailable' from %s agreeing signals"
                    % words.get(len(signals), str(len(signals))))
        if decision.get('availability') != 'available':
            # plain words only: the decision's availability code is never shown in report text
            return ('unverifiable', {'conflicting': 'availability signals disagree'}.get(
                decision.get('availability'), 'availability not stated'), None)
        return None, None, None
    if decision.get('expired'):
        return 'unverifiable', 'quoted price expired %s' % _day(decision['valid_until']), None
    # the offer decision's reasons are plain sentences; its state code (e.g. no_structured_offer) is never shown
    return 'unverifiable', reasons or 'the offer could not be confirmed', None


# -- delivery-rule membership -------------------------------------------------------------------------------------

def _threshold_rules(observations):
    """(rules, exclusions, zone_context). Observations are grouped by (document, quote).
    - a group with an amount or comparison claim is a RULE; if either is missing or unreadable it is an
      unevaluable rule, reported with its quote, never dropped;
    - a group carrying only an 'excludes' claim is a quoted exclusion of the supplier's free-delivery offer and
      restricts every threshold rule of that supplier (the restrictive direction is the safe one);
    - a group carrying only zone information is zone CONTEXT for the supplier's rules, never a rule of its own.
    Zone and exclusions come from structured claims only; quote text is evidence, never parsed for areas."""
    groups = {}
    for o in observations:
        if o.get('field') == 'free_delivery_threshold':
            r = groups.setdefault((_doc(o['source_url']), o['quote']), {'quote': o['quote'], 'source_url': o['source_url'],
                                                                         'evidence_date': o.get('evidence_date'),
                                                                         'provenance': o.get('provenance')})
            r[o['key']] = o['value']
    rules, exclusions, zone_context = [], [], []
    for r in groups.values():
        keys = set(r) - {'quote', 'source_url', 'evidence_date', 'provenance'}
        if 'amount' in keys or 'comparison' in keys:
            rules.append(r)
        elif 'excludes' in keys:
            exclusions.append(r)
        elif 'zone' in keys:
            zone_context.append(r)
    return rules, exclusions, zone_context


def _zone_decision(rule, zone_context, destination):
    """(True / False / None, zone text, source). The rule's own structured zone first, else the supplier's zone
    context; disagreeing or unspecific context abstains; no zone at all is (None, None, None)."""
    if rule.get('zone') is not None:
        return _in_area(destination, rule['zone']), rule['zone'], 'rule'
    if not zone_context:
        return None, None, None
    decisions = {_in_area(destination, z['zone']) for z in zone_context}
    zones = ', '.join("'%s'" % z['zone'] for z in zone_context)
    if decisions == {True}:
        return True, zones, 'context'
    if decisions == {False}:
        return False, zones, 'context'
    return None, zones, 'context'


def _membership(observations, order_value, order_vat, destination):
    """(state or None, reasons, chosen rule, conversion text, unevaluable rules).
    States: qualified, not_qualified, abstained; None when no threshold rule was quoted."""
    rules, exclusions, zone_context = _threshold_rules(observations)
    if not rules:
        return None, ['no free-delivery threshold was quoted'], None, None, []
    reasons, qualified, abstained, excluded, unevaluable, conversion = [], [], [], [], [], None
    for r in rules:
        threshold, op, word = _money(r.get('amount')), _operator(r.get('comparison')), r.get('comparison')
        if threshold is None or op is None:
            why = ("a free-delivery rule is quoted but cannot be evaluated: '%s' has no readable %s"
                   % (r['quote'], 'amount' if threshold is None else 'comparison'))
            unevaluable.append({'quote': r['quote'], 'source_url': r['source_url'], 'reason': why,
                                'provenance': r.get('provenance')})
            abstained.append((r, why))
            continue
        basis, value, value_text = _vat_basis(r['quote']), order_value, None
        if basis and order_vat is None:
            abstained.append((r, 'the order value VAT basis is not known'))
            continue
        if basis == 'ex' and order_vat == 'inc' or basis == 'inc' and order_vat == 'ex':
            m = _RATE.search(r.get('vat_rate') or '') if r.get('vat_rate') and r['vat_rate'] in r['quote'] else None
            if not m:
                abstained.append((r, 'threshold is quoted %s VAT and no VAT rate is quoted; a VAT-%s order value '
                                     'cannot be compared' % ('before' if basis == 'ex' else 'including',
                                                             'inclusive' if order_vat == 'inc' else 'exclusive')))
                continue
            rate = Decimal(m.group(1)) / 100
            value = order_value / (1 + rate) if basis == 'ex' else order_value * (1 + rate)
            value_text = (order_value, value, r['vat_rate'])
        elif basis is None:
            reasons.append("the rule '%s' states no VAT basis; compared with the order value as given" % r['quote'])
        meets = value >= threshold if op == 'inclusive' else value > threshold
        if value == threshold:
            reasons.append("equality %s because the quoted rule says '%s'" % ('qualifies' if meets else 'does not qualify', word))
        if value_text:
            v, conv, rate_text = value_text
            if basis == 'ex':
                reasons.append('£%s including VAT is £%s excluding VAT at the quoted %s, which is %s%s %s'
                               % (_fmt(v), _fmt(conv), rate_text, '' if meets else 'not ', word, r['amount']))
                conversion = '£%s VAT-inclusive = £%s ex VAT at quoted %s, %s%s %s' % (
                    _fmt(v), _fmt(conv), rate_text, '' if meets else 'not ', word, r['amount'])
        if not meets:
            reasons.append("£%s does not meet the quoted rule '%s'" % (_fmt(value), r['quote']))
            continue
        hit = [x for x in exclusions + ([r] if r.get('excludes') else []) if _in_area(destination, x['excludes'])]
        if hit:
            excluded.append(r)
            reasons.append("the quoted exclusion '%s' names %s" % (hit[0]['quote'], destination))
            continue
        inside, zone, source = _zone_decision(r, zone_context, destination)
        if zone is None:
            abstained.append((r, "the rule '%s' states no zone, so whether it covers %s is not established"
                                 % (r['quote'], destination)))
            continue
        if inside is None:
            abstained.append((r, "the %s zone %s does not say whether %s is covered"
                                 % ("rule's" if source == 'rule' else "supplier's quoted", zone, destination)))
            continue
        if not inside:
            reasons.append("%s is outside the %s zone %s" % (destination, 'rule' if source == 'rule' else 'quoted', zone))
            continue
        if '*' in r['quote'] or 'terms apply' in r['quote'].lower() or "t&c" in r['quote'].lower():
            abstained.append((r, "the rule '%s' carries starred terms that were not captured" % r['quote']))
            continue
        qualified.append(r)
    if qualified:
        return 'qualified', reasons, qualified[0], conversion, unevaluable
    if abstained:
        return 'abstained', reasons + [abstained[0][1]], abstained[0][0], conversion, unevaluable
    if excluded:
        return 'not_qualified', reasons + ['destination excluded by the quoted rule'], None, conversion, unevaluable
    return 'not_qualified', reasons, None, conversion, unevaluable


# -- delivery charges ---------------------------------------------------------------------------------------------

def _charges(observations):
    standard, regional = {}, []
    zones = {(_doc(o['source_url']), o['quote']): o['value'] for o in observations
             if o.get('field') == 'delivery_charge' and o.get('key') == 'zone'}
    for o in observations:
        if o.get('field') == 'delivery_charge' and o.get('key') == 'amount':
            amount = _money(o['value'])
            if amount is None:
                continue
            c = standard.setdefault((amount, o['quote']), {'amount': amount, 'basis_quote': o['quote'], 'sources': [],
                                                          'evidence_date': o.get('evidence_date'),
                                                          'provenance': o.get('provenance'), 'zone': None})
            c['sources'].append(o['source_url'])
            c['zone'] = c['zone'] or zones.get((_doc(o['source_url']), o['quote']))
        if o.get('field') == 'delivery_geography' and o.get('key') == 'surcharge':
            amount = _money(o['value'])
            lines = [x.strip() for x in o['quote'].split('\n') if x.strip()]
            if amount is None or not lines:
                continue
            regional.append({'amount': amount, 'basis': 'per parcel' if 'per parcel' in o['value'] else None,
                             'zones': lines[1:], 'basis_quote': lines[0], 'source_url': o['source_url'],
                             'evidence_date': o.get('evidence_date'), 'provenance': o.get('provenance')})
    return list(standard.values()), regional


def _components(standard, inside, destination, order, unevaluable):
    """Quoted charges that could apply to this destination, listed beside an unresolved decision. Never a total and
    never an upper bound: each says what is still unknown."""
    if inside:
        out = []
        for c in inside:
            unknown_parcels = c['basis'] == 'per parcel' and order.get('parcel_count') is None
            out.append({'amount': _fmt(c['amount']), 'basis': c['basis'], 'quote': c['basis_quote'],
                        'label': 'quoted charge for this destination, parcel count not stated' if unknown_parcels
                        else 'quoted charge for this destination',
                        'unknown': ['parcel count'] if unknown_parcels else []})
        return out
    label = ('would apply if the unevaluable free-delivery rule does not qualify' if unevaluable
             else 'would apply if the free-delivery rule does not qualify')
    return [{'amount': _fmt(c['amount']), 'basis': None, 'quote': c['basis_quote'], 'label': label,
             'unknown': ['free-delivery membership']}
            for c in standard if c['zone'] is None or _in_area(destination, c['zone'])]


def _delivery(observations, membership, rule, order, unevaluable=()):
    destination = order['destination']
    standard, regional = _charges(observations)
    out = {'applied': None, 'also_listed': [], 'not_applied': [], 'abstained': None, 'components': [], 'reasoning': []}
    inside = [c for c in regional if any(_in_area(destination, z) for z in c['zones'])]
    for c in regional:
        if c not in inside:
            out['also_listed'].append({'amount': _fmt(c['amount']), 'basis': c['basis'], 'zones': ', '.join(c['zones']),
                                       'applied': False, 'basis_quote': c['basis_quote']})
            out['not_applied'].append({'amount': _fmt(c['amount']), 'reason': 'destination outside the quoted surcharge zones'})
    if regional and standard:
        out['reasoning'].append('the £%s per-parcel quote is a separate charge for named zones, not merged into or '
                                'replacing the standard charge' % _fmt(regional[0]['amount']))
    if membership == 'abstained':
        out['abstained'] = {'reason': None}
        out['components'] = _components(standard, inside, destination, order, unevaluable)
        return out
    if membership == 'qualified':
        if inside:
            out['abstained'] = {'reason': 'whether free delivery also removes the quoted per-parcel charge for this '
                                          'destination is not quoted'}
            out['components'] = _components(standard, inside, destination, order, unevaluable)
            return out
        out['applied'] = {'amount': '0.00', 'basis_quote': rule['quote'], 'kind': 'free_threshold',
                          'evidence_date': rule.get('evidence_date'), 'provenance': rule.get('provenance')}
        return out
    if inside:
        if len({c['amount'] for c in inside}) > 1:
            out['abstained'] = {'reason': 'more than one quoted surcharge covers the destination'}
            out['components'] = _components(standard, inside, destination, order, unevaluable)
            return out
        c = inside[0]
        if c['basis'] == 'per parcel' and order.get('parcel_count') is None:
            # Never inferred from the item quantity: a sack order may travel as one or several parcels.
            out['abstained'] = {'reason': 'parcel count not stated in the quotes'}
            out['components'] = _components(standard, inside, destination, order, unevaluable)
            return out
        n = int(order['parcel_count']) if c['basis'] == 'per parcel' else 1
        out['applied'] = {'amount': _fmt(c['amount'] * n), 'basis': c['basis'], 'basis_quote': c['basis_quote'],
                          'kind': 'regional', 'evidence_date': c['evidence_date'], 'provenance': c['provenance']}
        out['reasoning'].append('destination is inside the quoted surcharge zones; parcel count %d from the order' % n)
        out['not_applied'] += [{'amount': _fmt(s['amount']), 'reason': 'destination inside the quoted surcharge zones'}
                               for s in standard]
        return out
    usable = [c for c in standard if c['zone'] is None or _in_area(destination, c['zone'])]
    if not standard:
        out['abstained'] = {'reason': 'no delivery charge amount was quoted; absence of a charge quote is not free delivery'}
        return out
    if not usable:
        out['abstained'] = {'reason': 'no quoted delivery charge covers the destination'}
        return out
    if len({c['amount'] for c in usable}) > 1:
        out['abstained'] = {'reason': 'conflicting delivery charge quotes: ' +
                                      ', '.join('£%s' % _fmt(c['amount']) for c in usable)}
        out['conflicting_charges'] = [{'amount': _fmt(c['amount']), 'quote': c['basis_quote']} for c in usable]
        return out
    c = usable[0]
    out['applied'] = {'amount': _fmt(c['amount']), 'basis_quote': c['basis_quote'], 'kind': 'standard',
                      'evidence_date': c['evidence_date'], 'provenance': c['provenance']}
    return out


# -- per supplier -------------------------------------------------------------------------------------------------

def _geography(observations, destination):
    """(ineligible reason, basis quote) or (None, note)."""
    for o in observations:
        if o.get('field') == 'delivery_geography' and o.get('key') == 'excluded':
            for line in o['value'].split('\n'):
                if line.strip() and _norm_area(line) == _norm_area(destination):
                    return 'destination excluded by quoted delivery geography', line.strip()
    included = [o for o in observations if o.get('field') == 'delivery_geography' and o.get('key') == 'included']
    if included:
        decided = [_in_area(destination, o['value']) for o in included]
        if True in decided:
            return None, None
        if all(d is False for d in decided):
            return 'destination outside the quoted delivery geography', included[0]['quote']
        return None, 'whether the quoted delivery geography covers %s is not established' % destination
    return None, 'no delivery geography was quoted'


def _order_value(order_value):
    """(Decimal or None, problem or None). Accepts a plain amount (GBP, as the contract states) or
    {'amount': ..., 'currency': ...}. A non-GBP or unreadable value is a problem, never a crash or a conversion."""
    if order_value is None:
        return None, None
    if isinstance(order_value, dict):
        currency = str(order_value.get('currency') or '')
        if currency != 'GBP':
            return None, ('currency mismatch: order value in %s, quoted rules in GBP; no conversion is assumed'
                          % (currency or 'an unstated currency'))
        order_value = order_value.get('amount')
    try:
        value = Decimal(str(order_value).strip())
        if not value.is_finite():
            raise ValueError
        return value, None
    except Exception:  # noqa: BLE001 - an unreadable value abstains, never crashes
        return None, 'order value %r is not a readable GBP amount' % (order_value,)


def assess_supplier(supplier, captures, observations, order, binding, read_date, order_value=None):
    """Everything this layer decides for one supplier, with reasons.
    order: {'pack', 'quantity', 'destination'} and optionally 'parcel_count' (never inferred from quantity)."""
    decision = offers.bind_offer(captures, binding, order['pack'], read_date)
    out = {'contract': CONTRACT, 'supplier': supplier, 'label': SUPPLIER_LABELS.get(supplier, supplier),
           'offer_state': decision['state'], 'offer': decision, 'order': dict(order), 'read_date': read_date.isoformat(),
           'eligibility': {'state': 'eligible'}, 'membership': None, 'membership_reason': None, 'delivery': None,
           'delivered_total': None, 'goods_value': None, 'unevaluable_rules': [], 'reasoning': [],
           'constructed_inputs': sorted({o.get('provenance') for o in observations
                                         if str(o.get('provenance', '')).startswith('constructed')})}
    if decision['state'] != 'confirmed' and any(r.get('minor_units') for r in decision.get('records') or []) and \
            any('currency' in x for x in decision.get('reasons') or []):
        out['reasoning'].append('minor-unit record corroborates but never supplies currency')
    head = decision.get('headline') if decision['state'] == 'confirmed' else None
    value, value_problem = _order_value(order_value)
    if order_value is not None:
        goods = value
    elif head and head.get('currency') == 'GBP':
        goods = Decimal(head['amount']) * order.get('quantity', 1)
    else:
        goods = None
    out['goods_value'] = _fmt(goods) if goods is not None else None
    order_vat = {True: 'inc', False: 'ex'}.get(decision.get('vat_included'))
    state, reason, evidence = _offer_status(decision, order['pack'])
    if state:
        out['eligibility'] = {'state': state, 'reason': reason}
        if evidence:
            out['eligibility']['evidence'] = evidence
    if out['eligibility']['state'] == 'eligible':
        why, quote = _geography(observations, order['destination'])
        if why:
            out['eligibility'] = {'state': 'ineligible', 'reason': why, 'basis_quote': quote}
        elif quote:
            out['reasoning'].append(quote)
    if out['eligibility']['state'] == 'eligible' and goods is not None:
        for o in observations:
            if o.get('field') == 'order_eligibility' and o.get('key') == 'minimum_order':
                minimum = _money(o['value'])
                if minimum is not None and goods < minimum:
                    out['eligibility'] = {'state': 'ineligible', 'reason': 'minimum order value %s not met' % o['value'],
                                          'basis_quote': o['quote']}
    # Membership and delivery are computed only for an eligible supplier with a confirmed offer. Otherwise the
    # REPORTED membership is abstained with the reason; it is never qualified and never silently unset.
    if out['eligibility']['state'] != 'eligible' or decision['state'] != 'confirmed':
        out['membership'] = 'abstained'
        out['membership_reason'] = ('not evaluated: order value not verified (%s)' % out['eligibility'].get('reason')
                                    if out['eligibility']['state'] != 'ineligible'
                                    else 'not evaluated: supplier ineligible (%s)' % out['eligibility']['reason'])
        return _summarise(out)
    if value_problem or goods is None:
        out['membership'] = 'abstained'
        out['membership_reason'] = value_problem or 'order value not known in GBP'
        out['reasoning'].append(out['membership_reason'])
        return _summarise(out)
    membership, reasons, rule, conversion, unevaluable = _membership(observations, goods, order_vat, order['destination'])
    out['membership'] = membership
    out['unevaluable_rules'] = unevaluable
    out['reasoning'] += reasons
    if membership == 'abstained':
        out['membership_reason'] = reasons[-1]
    elif membership == 'not_qualified' and reasons and reasons[-1] == 'destination excluded by the quoted rule':
        out['membership_reason'] = reasons[-1]
    delivery = _delivery(observations, membership, rule, order, unevaluable)
    if membership == 'abstained':
        parts = [reasons[-1]]
        if any('parcel count' in u for c in delivery.get('components', []) for u in c.get('unknown', [])):
            parts.append('parcel count not stated in the quotes')
        delivery['abstained'] = {'reason': '; '.join(parts)}
    out['delivery'] = delivery
    out['reasoning'] += delivery.pop('reasoning')
    applied = delivery['applied']
    if applied:
        if applied['kind'] == 'regional':
            out['total_withheld'] = ('whether the regional per-parcel charge replaces or adds to the standard '
                                     'charge is not stated in the quotes')
        else:
            notes = [{True: 'product price quoted VAT-inclusive', False: 'product price quoted VAT-exclusive'}.get(
                decision.get('vat_included'), 'product price VAT basis not stated')]
            if applied['kind'] == 'free_threshold':
                notes.append('delivery free under the quoted threshold')
            else:
                vat = _vat_basis(applied['basis_quote'])
                notes.append({'inc': 'delivery charge quoted VAT-inclusive', 'ex': 'delivery charge quoted VAT-exclusive'}
                             .get(vat, 'delivery charge VAT basis not stated in the quotes'))
            total = goods + Decimal(applied['amount'])
            out['delivered_total'] = {'amount': _fmt(total), 'arithmetic': '%s + %s' % (_fmt(goods), applied['amount']),
                                      'basis_notes': notes, 'cost_basis': _cost_basis(decision, applied, goods,
                                                                                      observations)}
            if conversion and applied['kind'] == 'free_threshold':
                out['delivered_total']['conversion_shown'] = conversion
    return _summarise(out)


def _cost_basis(decision, applied, goods, observations):
    """What a cross-supplier ranking needs to know about one delivered total. VAT bases are 'inc', 'ex' or None
    (not stated); a free delivery has no charge whose basis matters ('n/a'). A VAT rate counts only when quoted."""
    rates = sorted({o['value'] for o in observations if o.get('field') == 'price_vat' and o.get('key') == 'rate'
                    and o.get('value') and o['value'] in o.get('quote', '') and _RATE.search(o['value'])})
    return {'product_vat': {True: 'inc', False: 'ex'}.get(decision.get('vat_included')),
            'delivery_vat': 'n/a' if applied['kind'] == 'free_threshold' else _vat_basis(applied['basis_quote']),
            'goods': _fmt(goods), 'delivery': applied['amount'],
            'vat_rate': rates[0] if len(rates) == 1 else None,
            'vat_rate_quote': next((o['quote'] for o in observations if o.get('field') == 'price_vat'
                                    and o.get('value') == rates[0]), None) if len(rates) == 1 else None}


def _comparability(ranked):
    """(reason or None, {supplier: normalised Decimal total} or None, conversions). A ranking needs the same order
    need (equivalent pack, quantity, destination) and a known, normalised, same VAT basis. Mixed inclusive and
    exclusive VAT is normalised to VAT-inclusive only with a quoted rate; a rate is never assumed."""
    first = ranked[0]['order']
    for a in ranked[1:]:
        o = a['order']
        if not _pack_matches(str(first.get('pack')), str(o.get('pack'))):
            return 'the pack sizes differ (%s vs %s)' % (first.get('pack'), o.get('pack')), None, []
        if Decimal(str(first.get('quantity', 1))) != Decimal(str(o.get('quantity', 1))):
            return 'the order quantity differs (%s vs %s)' % (first.get('quantity', 1), o.get('quantity', 1)), None, []
        if _norm_area(first.get('destination')) != _norm_area(o.get('destination')):
            return 'the destinations differ (%s vs %s)' % (first.get('destination'), o.get('destination')), None, []
    unknown = []
    for a in ranked:
        b = a['delivered_total'].get('cost_basis') or {}
        if b.get('product_vat') is None:
            unknown.append('%s product price' % a['label'])
        if b.get('delivery_vat') is None:
            unknown.append('%s delivery charge' % a['label'])
    if unknown:
        return 'VAT basis not stated for: %s' % ', '.join(unknown), None, []
    bases = {v for a in ranked for k, v in a['delivered_total']['cost_basis'].items()
             if k in ('product_vat', 'delivery_vat') and v != 'n/a'}
    if len(bases) <= 1:
        return None, None, []
    norm, conversions = {}, []
    for a in ranked:
        b = a['delivered_total']['cost_basis']
        if 'ex' not in (b['product_vat'], b['delivery_vat']):
            norm[a['supplier']] = Decimal(a['delivered_total']['amount'])
            continue
        if not b.get('vat_rate'):
            return ('VAT bases differ (inclusive and exclusive) and %s quotes no VAT rate' % a['label']), None, []
        r = Decimal(_RATE.search(b['vat_rate']).group(1)) / 100
        parts = [Decimal(b['goods']) * ((1 + r) if b['product_vat'] == 'ex' else 1),
                 Decimal(b['delivery']) * ((1 + r) if b['delivery_vat'] == 'ex' else 1)]
        norm[a['supplier']] = (parts[0] + parts[1]).quantize(Decimal('0.01'), ROUND_HALF_UP)
        conversions.append('%s £%s ex VAT is £%s inc VAT at the quoted %s ("%s")' % (
            a['label'], a['delivered_total']['amount'], _fmt(norm[a['supplier']]), b['vat_rate'], b['vat_rate_quote']))
    return None, norm, conversions


def _summarise(out):
    if out['delivered_total']:
        out['summary'] = 'delivered total £%s' % out['delivered_total']['amount']
    elif out['eligibility']['state'] == 'ineligible':
        out['summary'] = 'excluded: %s' % out['eligibility']['reason']
    elif out['eligibility']['state'] == 'unverifiable':
        out['summary'] = 'could not be verified: %s' % out['eligibility']['reason']
    elif out['delivery'] and out['delivery'].get('abstained'):
        out['summary'] = 'delivery charge unknown, so no delivered total'
    elif out.get('total_withheld'):
        out['summary'] = 'no delivered total: %s' % out['total_withheld']
    else:
        out['summary'] = 'no delivered total'
    return out


# -- verdict ------------------------------------------------------------------------------------------------------

def _excluded_phrase(a, pack):
    reason = a['eligibility']['reason']
    return '%s unavailable' % pack if reason == 'product unavailable' else reason


def _unverifiable_phrase(a):
    reason = a['eligibility'].get('reason') or a['summary']
    if reason.startswith('conflicting prices'):
        return 'its page shows conflicting prices'
    return reason


def compare(assessments, order, read_date):
    """Cross-supplier verdict and the one claim it licenses. Verdict kinds: cheapest, tie, partial, none."""
    verified = [a for a in assessments if a['delivered_total']]
    excluded = [a for a in assessments if a['eligibility']['state'] == 'ineligible']
    unverifiable = [a for a in assessments if a not in verified and a not in excluded]
    pack, qty = order['pack'], order.get('quantity', 1)
    name = lambda a: a['label']  # noqa: E731
    total = lambda a: Decimal(a['delivered_total']['amount'])  # noqa: E731
    if not verified:
        missing = 'no structured offer record was captured'
        if assessments and all(a['eligibility'].get('reason') == missing for a in assessments):
            # the records hold no structured price: say so, and do not imply a fresh verification attempt
            return {'verdict': 'none', 'claim': 'No comparison: the records hold no structured price for %s, so no '
                                                'price can be confirmed from them.'
                    % (', '.join(name(a) for a in assessments[:-1]) + ' or ' + name(assessments[-1])
                       if len(assessments) > 1 else name(assessments[0]))}
        phrases = []
        for a in assessments:
            reason = a['eligibility'].get('reason') or ''
            if reason.startswith('quoted price expired'):
                phrases.append("%s's quoted price expired %s" % (name(a), reason[len('quoted price expired '):]))
            elif reason == 'product unavailable':
                phrases.append('%s is unavailable' % name(a))
            elif reason.startswith('conflicting prices'):
                phrases.append('%s shows conflicting prices' % name(a))
            else:
                phrases.append('%s: %s' % (name(a), a['summary']))
        return {'verdict': 'none', 'claim': 'No comparison: no supplier has a verified current price. %s.'
                % '; '.join(phrases)}
    ranked = sorted(verified, key=total)
    best, rest = ranked[0], ranked[1:]
    others = ', '.join('%s £%s' % (name(a), a['delivered_total']['amount']) for a in rest)
    reason, norm, conversions = _comparability(ranked) if rest else (None, None, [])
    tail = ''.join(' %s could not be verified: %s.' % (name(a), _unverifiable_phrase(a)) for a in unverifiable) + \
        ''.join(' %s excluded: %s.' % (name(a), _excluded_phrase(a, pack)) for a in excluded)
    if reason:
        listed = '; '.join('%s £%s (%s)' % (name(a), a['delivered_total']['amount'],
                                            '; '.join(a['delivered_total']['basis_notes'])) for a in ranked)
        verdict = {'not_comparable': {'verified': [a['supplier'] for a in ranked], 'reason': reason,
                                      'totals': [{'supplier': a['supplier'], 'total': a['delivered_total']['amount'],
                                                  'basis_notes': a['delivered_total']['basis_notes']} for a in ranked]}}
        if unverifiable:
            verdict['not_comparable']['unverifiable'] = [{'supplier': a['supplier'], 'reason': a['eligibility'].get(
                'reason') or a['summary']} for a in unverifiable]
        if excluded:
            verdict['not_comparable']['excluded'] = [{'supplier': a['supplier'], 'reason': a['eligibility']['reason']}
                                                     for a in excluded]
        return {'verdict': verdict, 'claim': 'No ranking: the %d suppliers with verified prices are not on a comparable '
                                             'cost basis (%s). Delivered totals as quoted: %s.%s'
                                             % (len(ranked), reason, listed, tail)}
    if norm:
        ranked = sorted(ranked, key=lambda a: norm[a['supplier']])
        best, rest = ranked[0], ranked[1:]
        verdict = {'cheapest': {'supplier': best['supplier'], 'total_inc_vat': _fmt(norm[best['supplier']]),
                                'margin_over_next': _fmt(norm[rest[0]['supplier']] - norm[best['supplier']]),
                                'normalised': 'VAT-inclusive, quoted rate only', 'conversions': conversions}}
        claim = 'Lowest delivered among the %d suppliers with verified prices: %s £%s inc VAT%s.' % (
            len(ranked), name(best), _fmt(norm[best['supplier']]),
            ' (%s)' % ', '.join('%s £%s inc VAT' % (name(a), _fmt(norm[a['supplier']])) for a in rest))
        return {'verdict': verdict, 'claim': claim + ' Compared VAT-inclusive: ' + '; '.join(conversions) + '.' + tail}
    single = ('Only one supplier could be verified, so there is no ranking: %s £%s delivered.'
              % (name(best), best['delivered_total']['amount'])) if not rest else None
    lead = 'Lowest delivered among the %d suppliers with verified prices: %s £%s' % (
        len(ranked), name(best), best['delivered_total']['amount'])  # never a market-wide cheapest
    if unverifiable:
        claim = single or '%s%s.' % (lead, ' (%s)' % others if others else '')
        claim += ''.join(' %s could not be verified: %s.' % (name(a), _unverifiable_phrase(a)) for a in unverifiable)
        claim += ''.join(' %s excluded: %s.' % (name(a), _excluded_phrase(a, pack)) for a in excluded)
        verdict = {'partial': {'verified': [a['supplier'] for a in ranked], 'cheapest_among_verified': best['supplier'],
                               'unverifiable': [{'supplier': a['supplier'], 'reason': a['eligibility'].get('reason')
                                                 or a['summary']} for a in unverifiable]}}
        if excluded:
            verdict['partial']['excluded'] = [{'supplier': a['supplier'], 'reason': a['eligibility']['reason']}
                                              for a in excluded]
        return {'verdict': verdict, 'claim': claim}
    tied = [a for a in ranked if total(a) == total(best)]
    if len(tied) > 1:
        names = ', '.join(name(a) for a in tied[:-1]) + ' and ' + name(tied[-1])
        return {'verdict': {'tie': {'suppliers': [a['supplier'] for a in tied], 'total': best['delivered_total']['amount']}},
                'claim': 'Tie: %s %s £%s delivered. No cheapest.' % (names, 'both' if len(tied) == 2 else 'all',
                                                                     best['delivered_total']['amount'])}
    applied = best['delivery']['applied']
    kind = {'standard': 'standard delivery', 'free_threshold': 'free delivery'}.get(applied['kind'], applied['kind'])
    quoted = ('quoted %s' % _day(applied['evidence_date'])) if applied.get('evidence_date') else 'constructed, undated'
    cheapest = {'supplier': best['supplier'], 'total': best['delivered_total']['amount'],
                'margin_over_next': _fmt(total(rest[0]) - total(best)) if rest else None,
                'basis': '%d x %s, %s £%s (%s), price read %s' % (qty, pack, kind, applied['amount'], quoted,
                                                                  _day(read_date.isoformat()))}
    verdict = {'cheapest': cheapest}
    if excluded:
        verdict['excluded'] = [{'supplier': a['supplier'], 'reason': a['eligibility']['reason']} for a in excluded]
        claim = single or '%s%s.' % (lead, ' (%s)' % others if others else '')
        claim += ''.join(' %s excluded: %s.' % (name(a), _excluded_phrase(a, pack)) for a in excluded)
        return {'verdict': verdict, 'claim': claim}
    cheaper_goods = sorted((a for a in rest if Decimal(a['goods_value']) < Decimal(best['goods_value'])),
                           key=lambda a: Decimal(a['goods_value']))
    if cheaper_goods:
        a = cheaper_goods[0]
        return {'verdict': verdict, 'claim': '%s. %s has the lower product price (£%s) but costs more delivered (£%s).'
                                             % (lead, name(a), a['goods_value'], a['delivered_total']['amount'])}
    dates = sorted(a['delivery']['applied']['evidence_date'] for a in verified
                   if a['delivery']['applied'].get('evidence_date'))
    start = date.fromisoformat(dates[0]) if dates else read_date
    span = (_day(read_date.isoformat()) if start == read_date else  # one day, not "25 Nov-25 Nov"
            '%d %s-%s' % (start.day, start.strftime('%b'), _day(read_date.isoformat()))
            if start.year == read_date.year else '%s-%s' % (_day(start.isoformat()), _day(read_date.isoformat())))
    claim = single or '%s.' % lead
    if rest:
        claim += ' Next: %s £%s (£%s more)' % (name(rest[0]), rest[0]['delivered_total']['amount'],
                                               cheapest['margin_over_next'])
        claim += ''.join('; %s £%s' % (name(a), a['delivered_total']['amount']) for a in rest[1:]) + '.'
    claim += (' Prices and delivery quotes as recorded %s.' % span if dates else
              ' Prices read %s; delivery quotes undated.' % _day(read_date.isoformat()))
    return {'verdict': verdict, 'claim': claim}

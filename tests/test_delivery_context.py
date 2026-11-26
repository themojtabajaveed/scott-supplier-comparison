"""Delivery charge context (display only, delivery-context-v1). A delivery qualifier is shown beside the charge only
when its own quote also contains the shown charge; every other qualifier stays visible in a labelled default list
that says what its quote contains and what was not checked. Nothing here changes a result, status, missing list or
route. All pages, options and amounts are invented; the saved Wessex run is read, never written.
"""
import copy
import hashlib
import html as html_lib
import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scout import plain  # noqa: E402
from scout.engine.comparison import assess_comparable, bound_delivery_assessment  # noqa: E402
from scout.workflows import supplier  # noqa: E402

_spec = importlib.util.spec_from_file_location('scout_ui_ctx', ROOT / 'scripts' / 'scout_ui.py')
ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui)

U, U2 = 'https://shop.example/delivery', 'https://shop.example/product'
SCHEMA = supplier.ATOMIC_FIELDS['delivery_charge']
A = ('Standard UK mainland delivery is £3.85 per parcel including VAT, one sack per box, no surcharge, '
     'on orders under £50')
B = 'Highlands and Islands delivery is £12.50 per parcel excluding VAT, two sacks per box, £3 remote surcharge'


def c(value, quote, url=U):
    return {'value': value, 'quote': quote, 'source_url': url, 'status': 'literal_evidence_only'}


def complete(**over):
    """A delivery charge with every claim from option A, so the engine reads it as literal_components_present."""
    facts = {'amount': [c('£3.85', A)], 'basis': [c('per parcel', A)], 'vat': [c('including VAT', A)],
             'zone': [c('UK mainland', A)], 'packing': [c('one sack per box', A)], 'surcharge': [c('no surcharge', A)],
             'order_condition': [c('orders under £50', A)]}
    facts.update(over)
    field = assess_comparable({k: v for k, v in facts.items() if v}, SCHEMA)
    return bound_delivery_assessment(field)


def views(field, row_fields=None):
    row = {'atomic_fields': dict(row_fields or {}, delivery_charge=field)}
    status = plain.field_status(field, 'delivery_charge', row['atomic_fields'])
    headline = dict(plain.cell_values('delivery_charge', field, row['atomic_fields']))
    native = ui.comparison_cell('delivery_charge', field, row)
    word, sheet = ui._cmp_cell('delivery_charge', field, row)
    return status, headline, native, word, sheet


def default_view(html):
    return html_lib.unescape(html.split('<details')[0])  # what is visible before any disclosure is opened


def states(field, row_fields=None):
    return [(x['key'], x['state']) for x in plain.delivery_context(field, row_fields)['claims']]


# -- money recognition -------------------------------------------------------------------------------------------
def test_recognised_money_forms_and_boundaries():
    got = lambda t: [(cur, v) for cur, v, _ in plain.money_amounts(t)]  # noqa: E731
    assert got('£3.85') == got('GBP 3.85') == got('3.85 GBP') == got('GBP3.85') == [('GBP', Decimal('3.85'))]
    assert got('€3.85') == got('EUR 3.85') == got('€3,85') == got('3,85 €') == [('EUR', Decimal('3.85'))]
    assert got('US$3.85') == got('USD 3.85') == [('USD', Decimal('3.85'))]
    assert got('$3.85') == [('$', Decimal('3.85'))]  # a bare $ is kept apart from USD
    assert got('£1,250.00') == [('GBP', Decimal('1250.00'))]
    assert got('£14.95') == [('GBP', Decimal('14.95'))] and got('£4.9') == [('GBP', Decimal('4.9'))]
    assert got('£3,85') == [] and got('3.85') == [] and got('3.85 pounds') == []  # outside the recognised forms


def test_equal_digits_in_different_currencies_are_not_the_shown_charge():
    field = complete(amount=[c('GBP 3.85', A.replace('£3.85', 'GBP 3.85'))],
                     zone=[c('Eurozone', 'Eurozone delivery is EUR 3.85')])
    assert ('zone', 'other_amount_only') in states(field)


# -- positives stay useful ---------------------------------------------------------------------------------------
def test_compound_same_option_quote_with_its_threshold_extracted_stays_quoted_with_no_notes():
    threshold = {'facts': {'amount': [c('£50', A)]}}
    status, headline, native, word, sheet = views(complete(), {'free_delivery_threshold': threshold})
    assert status['word'] == plain.QUOTED and word == 'Found'
    assert headline == {'amount': ['£3.85'], 'charge basis': ['per parcel'], 'zone': ['UK mainland']}
    for html in (native, sheet):
        assert 'Stated separately' not in html and 'ctx-note' not in html


def test_unextracted_threshold_and_net_gross_prices_give_a_visible_note_not_a_review():
    # £50 is carried by the extracted order condition from the same quote, so only the unextracted amount is noted
    for quote, extra in ((A + ', free delivery over £75', '£75'),
                         ('Standard delivery £3.21 ex VAT (£3.85 inc VAT) per parcel, UK mainland, one sack per box, '
                          'no surcharge, orders under £50', '£3.21')):
        facts = {k: [c(v, quote)] for k, v in dict(basis='per parcel', zone='UK mainland', packing='one sack per box',
                                                   surcharge='no surcharge', order_condition='orders under £50').items()}
        field = complete(amount=[c('£3.85', quote)], vat=[c('VAT', quote)], **facts)
        status, headline, native, word, sheet = views(field)  # no threshold field, so £75 / £3.21 is not extracted
        others = [k for x in plain.delivery_context(field)['claims'] for k in x['other']]
        assert ('GBP', Decimal('50')) not in others and others  # £50 accounted for; the unextracted amount is not
        assert status['word'] == plain.QUOTED and word == 'Found'
        assert headline['zone'] == ['UK mainland']
        for html in (native, sheet):
            visible = default_view(html)
            assert 'its quote also contains %s, whose role was not extracted' % extra in visible
            assert 'was not checked' in visible


def test_repeated_amount_and_same_page_fragment_stay_co_quoted_without_claiming_one_option():
    field = complete(amount=[c('£3.85', A), c('£3.85', 'Delivery from £3.85', U2), c('£3.85', A, U + '#tab-delivery')],
                     vat=[c('including VAT', A, U + '#tab-delivery')])
    assert all(state.startswith('co_quoted') for _, state in states(field))
    status, headline, native, word, sheet = views(field)
    # the unchanged basis guard already lowers this field (its basis is not quoted with the second page's amount);
    # the context layer adds no review of its own and keeps that word
    assert status['word'] == plain.field_status(field)['word'] == plain.PARTLY and headline['amount'] == ['£3.85']
    assert 'context to check' not in sheet
    for html in (native, sheet):
        assert 'does not mean the quotes describe the same delivery option' in default_view(html)


# -- separately sourced context is not shown as a qualifier ------------------------------------------------------
@pytest.mark.parametrize('key,value', [('vat', 'excluding VAT'), ('zone', 'Highlands and Islands'),
                                       ('packing', 'two sacks per box'), ('surcharge', '£3 remote surcharge')])
def test_a_qualifier_from_the_other_option_moves_to_the_visible_list_and_asks_for_review(key, value):
    field = complete(**{key: [c(value, B)]})
    before = copy.deepcopy(field)
    status, headline, native, word, sheet = views(field)
    assert field == before  # display only: the result is not mutated
    assert (key, 'other_amount_only') in states(field)
    assert status['word'] == plain.REVIEW and word == 'Needs review'
    assert 'context to check' in sheet
    label = plain.claim_label(key)
    assert value not in headline.get(label, [])
    for html in (native, sheet):
        visible = default_view(html)
        assert 'Stated separately from the shown charge' in visible and value in visible
        assert 'does not contain the shown £3.85; how they relate was not checked' in visible
        assert 'another rate' not in visible and 'applies' not in visible
    assert field['missing'] == before['missing'] and field['status'] == before['status']


def test_heading_and_site_wide_statements_stay_visible_as_separate_context_not_missing():
    field = complete(zone=[c('United Kingdom', 'United Kingdom:')],
                     vat=[c('include VAT', 'All prices on this site include VAT')])
    status, headline, native, word, sheet = views(field)
    assert status['word'] == plain.QUOTED and 'zone' not in headline and field['missing'] == []
    for html in (native, sheet):
        visible = default_view(html)
        # v1.4.1 wording: says no shown charge was identified in the quote, not that it holds no money
        assert 'Zone "United Kingdom": no shown charge was identified in its quote' in visible
        assert 'VAT basis "include VAT": no shown charge was identified in its quote' in visible


def test_a_qualifier_on_another_page_is_labelled_with_that_page():
    field = complete(zone=[c('UK mainland', 'We deliver to UK mainland', U2)])
    status, headline, native, word, sheet = views(field)
    assert 'stated on a different page (shop.example/product)' in default_view(native)


def test_each_claim_is_checked_on_its_own():
    field = complete(zone=[c('UK mainland', A), c('Highlands and Islands', B)])
    status, headline, native, word, sheet = views(field)
    assert headline['zone'] == ['UK mainland']
    assert 'Zone "Highlands and Islands"' in default_view(native) and 'Zone "UK mainland"' not in default_view(native)


# -- precedence: stronger existing words stay ---------------------------------------------------------------------
def test_a_numeric_disagreement_keeps_its_word_and_says_which_amount_a_qualifier_is_quoted_with():
    field = complete(amount=[c('£3.85', A), c('£5.95', 'Standard delivery £5.95', U2)], zone=[c('Highlands', B)])
    status, headline, native, word, sheet = views(field)
    assert status['word'] == plain.DISAGREE and word == 'Needs review' and 'conflicting numbers' in sheet  # as before
    assert 'context to check' not in sheet
    assert 'is quoted with £3.85 only' in default_view(native)


def test_partly_quoted_stays_partly_quoted():
    field = complete(vat=None, zone=[c('Highlands and Islands', B)])
    status, headline, native, word, sheet = views(field)
    assert status['word'] == plain.PARTLY and word == 'Partly found'


def test_an_unrecognised_charge_format_is_reported_and_left_as_before():
    field = complete(amount=[c('3.85', A.replace('£3.85', '3.85'))])
    status, headline, native, word, sheet = views(field)
    assert headline['zone'] == ['UK mainland']  # not checked, so not moved
    assert 'is not written in a recognised money format' in default_view(native)


def test_claim_text_is_escaped():
    field = complete(zone=[c('<script>x</script>', 'Zone <script>x</script> list')])
    for html in views(field)[2:5:2]:
        assert '<script>' not in html


# -- saved evidence ------------------------------------------------------------------------------------------------
# Runs on the invented demo recordings (tests/demo_suppliers.py), with the invented amounts and zone.
def test_saved_wessex_charge_keeps_its_word_and_lists_its_basis_and_zone_separately(monkeypatch):
    sys.path.insert(0, str(ROOT / 'tests'))
    import demo_suppliers as demo
    folder = demo.use_demo_recordings(monkeypatch, ui)
    files = sorted(p for p in folder.rglob('*') if p.is_file())
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    rows, links = ui.recorded_rows(ui.RECORDED_DIR)
    row = next(r for r in rows if r['site'] == demo.ONE)
    field = row['atomic_fields']['delivery_charge']
    native = ui.comparison_cell('delivery_charge', field, row, home=True)
    word, sheet = ui._cmp_cell('delivery_charge', field, row)
    for html in (native, sheet):
        visible = default_view(html)
        assert 'Charge basis "per parcel": its quote contains £6.40 and does not contain the shown £3.80' in visible
        assert 'Zone "Mainland Demo Region": no shown charge was identified in its quote' in visible
    assert '<p class="cell-v">zone: Mainland Demo Region</p>' not in native and \
        '<li>Zone: Mainland Demo Region</li>' not in sheet
    assert word == 'Partly found'
    ui.recorded_section(ui.RECORDED_DIR)
    ui.comparison_body(ui.RECORDED_DIR)
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files} == before


# -- v1.4.1 corrections ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize('url,label', [(U2, 'shop.example/product'),
                                       (U + '?region=highlands', 'shop.example/delivery?region=highlands')])
def test_a_qualifier_from_another_document_stays_separate_even_when_its_quote_repeats_the_shown_amount(url, label):
    field = complete(zone=[c('UK mainland', 'UK mainland delivery is £3.85', url)])
    assert ('zone', 'separate') in states(field)
    status, headline, native, word, sheet = views(field)
    assert status['word'] == plain.field_status(field)['word'] and 'context to check' not in sheet  # not lowered
    assert 'UK mainland' not in headline.get('zone', [])
    for html in (native, sheet):
        visible = default_view(html)
        assert 'Zone "UK mainland": stated on a different page (%s) from the charge quote' % label in visible
        assert 'does not contain the shown' not in visible  # never claims the repeated amount is absent


def test_a_same_page_fragment_still_counts_as_the_same_document():
    field = complete(zone=[c('UK mainland', 'UK mainland delivery is £3.85', U + '#rates')])
    assert ('zone', 'co_quoted') in states(field)


def test_with_no_extracted_charge_every_detail_stays_visible_and_nothing_is_inferred():
    field = complete(amount=None)
    before = copy.deepcopy(field)
    status, headline, native, word, sheet = views(field)
    assert field == before and 'amount' in field['missing']  # stored field, status and missing list unchanged
    assert status['word'] == plain.field_status(field)['word']
    assert 'amount' not in headline and 'zone' not in headline and 'charge basis' not in headline  # no duplicates
    for html in (native, sheet):
        visible = default_view(html)
        assert 'Delivery details quoted, with no delivery charge amount extracted:' in visible
        for label, value in (('VAT basis', 'including VAT'), ('Zone', 'UK mainland'), ('Charge basis', 'per parcel'),
                             ('Surcharge', 'no surcharge'), ('Sacks per box', 'one sack per box')):
            assert '%s "%s": no delivery charge amount was extracted' % (label, value) in visible
        assert '£3.85' not in visible  # no amount is taken from the detail quotes
    assert 'Only details not linked to this field were quoted.' not in sheet
    assert 'Not found in this recorded run.' not in sheet  # v1.4.2: no whole-field not-found beside listed details


def test_a_genuinely_empty_delivery_field_keeps_its_not_found_message():
    field = bound_delivery_assessment(assess_comparable({}, SCHEMA))
    word, sheet = ui._cmp_cell('delivery_charge', field, {'atomic_fields': {'delivery_charge': field}})
    visible = default_view(sheet)
    assert 'Not found in this recorded run.' in visible and word == 'Not found'
    assert 'Delivery details quoted' not in visible and 'Stated separately' not in visible


@pytest.mark.parametrize('key,value,quote', [('surcharge', '£3 remote surcharge', 'A £3 remote surcharge applies'),
                                             ('order_condition', 'orders over £50', 'Free delivery on orders over £50')])
def test_a_standalone_or_accounted_amount_reads_as_no_shown_charge_in_that_quote(key, value, quote):
    field = complete(**{key: [c(value, quote)]})
    assert (key, 'separate') in states(field)
    visible = default_view(views(field)[2])
    label = plain.claim_label(key)
    assert '%s "%s": no shown charge was identified in its quote' % (label[0].upper() + label[1:], value) in visible
    assert 'any charge amount' not in visible

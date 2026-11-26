"""SYNTHETIC analogues of the live-run defect guards.

Every page text, quote, amount and address here is INVENTED (demo mill on a reserved .example address). The tests
mirror, one for one, a version that reproduces one real 27 October 2026 run from its preserved output and captured
excerpt; that version is not included here. The four guards covered:
  1. cross-rate binding (a basis quoted from another rate is not linked to the charge),
  2. excerpt conditions (conditions stated in the same sentence as the charge link; elsewhere they stay missing),
  3. same-document reread (fragments, redirects and variant data never re-read a visited document),
  4. wording variation (literal wording differences are variations; differing amounts are disagreements).
Hermetic: standard library only, no network, no API key, no live browser.
"""
import copy
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import demo_suppliers as demo  # noqa: E402
from scout.engine import atomic, tool_loop  # noqa: E402
from scout.engine.comparison import (  # noqa: E402
    assess_comparable, bound_delivery_assessment, render_comparison)
from scout.engine.planner import plan_question  # noqa: E402
from scout.workflows import supplier  # noqa: E402

QUESTION = 'Compare Demo Mill One demo strong flour 16kg delivery conditions (SYNTHETIC)'
ROOT_URL = demo.SITE[demo.ONE]['url']
TAB_URL = ROOT_URL + '#tab-delivery_tab'
SURCHARGE_QUOTE = '£6.40 per parcel to:\nNorth Coast Isles\nWestern Highlands Zone\nFar Valley District'
VARIATION_NOTE = 'Different wording/coverage retained; not a confirmed factual contradiction.'
BINDING_WARNING = 'Rate and charge basis are not linked in the same quoted evidence; do not combine.'
CONDITION_WARNING = 'Order condition and charge are not linked in the same quoted evidence; do not combine.'
CHARGE_SENTENCE = 'Standard delivery costs £3.80 but we offer\nFREE\nstandard delivery on Orders Above £45*'
THRESHOLD_EXCEPTION = 'Orders Above £45 will be free for the base rate but add a surcharge as well*'
# Invented excerpt: elided with '...', states no VAT or packing, and keeps the conditions apart from the charge.
EXCERPT = '\n'.join(['Demo Mill One', 'Delivery and returns', 'Mainland Demo Region:', CHARGE_SENTENCE,
                      SURCHARGE_QUOTE, '', '£8.20 per parcel to:\nHarbour Island\nOuter Reef Islands', '...',
                      'Regional variations apply:', THRESHOLD_EXCEPTION, 'Contact the mill with any questions.'])


def demo_plan():
    """A ready supplier plan whose site list is the invented demo site (test only; real config untouched)."""
    plan = plan_question('Compare Wessex strong white bread flour 16kg delivery conditions')
    site = dict(demo.SITE[demo.ONE])
    plan.question = QUESTION
    plan.workflow = dict(plan.workflow, sites=[site], question=QUESTION)
    return plan


def fact(value, quote, url):
    return {'value': value, 'quote': quote, 'source_url': url, 'status': 'literal_evidence_only'}


def both(value, quote, tab_quote=None, tab_value=None):
    return [fact(value, quote, ROOT_URL), fact(tab_value or value, tab_quote or quote, TAB_URL)]


def preserved_evidence():
    """Invented evidence with the structure of the private preserved run (root page, then delivery tab)."""
    return {
        'product_price': {
            'amount': both('£12.34', '£12.34'),
            'currency': both('£', '£12.34'),
            'variant': both('16kg', 'Demo Strong Flour 16kg'),
        },
        'delivery_charge': {
            'amount': both('£3.80', 'Standard delivery costs £3.80'),
            'basis': both('per parcel', '£6.40 per parcel to:', tab_value='parcel'),
            'zone': both('Mainland Demo Region', 'Mainland Demo Region:'),
            'surcharge': [fact('£6.40', SURCHARGE_QUOTE, TAB_URL)],
        },
        'free_delivery_threshold': {
            'amount': both('£45', 'Orders above £45*', tab_quote='Orders above £45'),
            'comparison': both('above', 'Orders above £45*', tab_quote='Orders above £45'),
            'zone': both('mainland', 'Free standard mainland delivery'),
        },
        'delivery_time': {
            'dispatch': both('within two working days', 'We dispatch your order within two working days'),
            'arrival': both('3-5 working days', 'please allow 3-5 working days for your parcel to arrive.',
                            tab_quote='please allow 3-5 working days for your parcel to arrive'),
        },
        'delivery_geography': {
            'included': both('mainland addresses', 'We deliver only to mainland addresses for now.'),
            'excluded': both('Harbour Island', 'Harbour Island',
                             tab_quote='Harbour Island\nForces mail addresses',
                             tab_value='Harbour Island\nForces mail addresses'),
        },
    }


def current_fields():
    """The same steps execute_plan applies to each field today."""
    ev = preserved_evidence()
    out = {f: assess_comparable(ev[f], schema) for f, schema in supplier.ATOMIC_FIELDS.items()}
    bound_delivery_assessment(out['delivery_charge'])
    return out


def readable(fields):
    return render_comparison([{'site': demo.ONE, 'input': QUESTION, 'atomic_fields': fields}],
                             'Scout planned research', as_of='27 October 2026')


def status_cell(text, field):
    row = next(line for line in text.splitlines() if line.startswith('| ' + field + ' |'))
    return row.rsplit(' | ', 1)[1].rstrip(' |')


CURRENT_STATUS = {
    'delivery_charge': 'incomplete_literal_variation; missing: vat, packing, order_condition, basis; '
                       + BINDING_WARNING + '; ' + VARIATION_NOTE,
    'delivery_geography': 'incomplete_literal_variation; missing: surcharge; ' + VARIATION_NOTE,
}


class PreservedOutputReproduction(unittest.TestCase):
    """Analogue: the private test compares today's render with one preserved real output (byte-for-byte copy of a
    recorded file); that comparison is recorded-specific. Public coverage is the same status cells on invented
    evidence, and that every other row carries no binding warning or variation note."""

    def test_current_code_sets_exactly_the_two_guarded_status_cells(self):
        text = readable(current_fields())
        for field, cell in CURRENT_STATUS.items():
            self.assertEqual(status_cell(text, field), cell)
        for line in text.splitlines():
            if line.startswith('| ') and not line.startswith(('| delivery_charge |', '| delivery_geography |')):
                self.assertNotIn(BINDING_WARNING, line)

    def test_question_still_plans_to_one_wessex_source(self):
        # Real planner configuration only (no page text): the named-supplier question plans to its one configured
        # source. The URL is read from the config, not written here.
        plan = plan_question('Compare Wessex strong white bread flour 16kg delivery conditions')
        self.assertEqual(plan.state, 'ready')
        wessex = next(s for s in supplier.WORKFLOW['sites'] if s['name'] == 'wessex_mill')
        self.assertEqual([s['url'] for s in plan.workflow['sites']], [wessex['url']])


class Defect1CrossRateBinding(unittest.TestCase):
    def test_validator_accepts_basis_quoted_from_another_rate(self):
        """Root cause: each atom only needs its own quote, so a basis from the £6.40 line is valid."""
        text = 'Mainland Demo Region:\nStandard delivery costs £3.80\n' + SURCHARGE_QUOTE
        raw = {'amount': {'value': '£3.80', 'quote': 'Standard delivery costs £3.80'},
               'basis': {'value': 'per parcel', 'quote': '£6.40 per parcel to:'}}
        result = atomic.validate_atoms(raw, supplier.ATOMIC_FIELDS['delivery_charge'], text, ROOT_URL)
        self.assertEqual(set(result['facts']), {'amount', 'basis'})

    def test_guard_flags_preserved_cross_rate_basis(self):
        field = current_fields()['delivery_charge']
        self.assertEqual(field['binding_warning'], BINDING_WARNING)
        self.assertNotEqual(field['status'], 'literal_components_present')

    def test_unlinked_basis_is_reported_missing_and_claims_are_kept(self):
        field = current_fields()['delivery_charge']
        self.assertIn('basis', field['missing'])
        self.assertEqual([b['value'] for b in field['facts']['basis']], ['per parcel', 'parcel'])

    def test_guard_does_not_link_on_a_longer_number(self):
        field = {'status': 'literal_components_present', 'facts': {
            'amount': [fact('£5', 'Standard delivery £5.', ROOT_URL)],
            'basis': [fact('per box', '£55 per box for Outer Reef Islands', ROOT_URL)]}}
        bound_delivery_assessment(field)
        self.assertEqual(field['binding_warning'], BINDING_WARNING)
        self.assertEqual(field['status'], 'incomplete')

    def test_guard_does_not_link_on_a_longer_decimal(self):
        field = {'status': 'literal_components_present', 'facts': {
            'amount': [fact('£5', 'Standard delivery £5.', ROOT_URL)],
            'basis': [fact('per box', '£5.50 per box for Outer Reef Islands', ROOT_URL)]}}
        bound_delivery_assessment(field)
        self.assertIn('binding_warning', field)

    def test_guard_still_links_a_genuinely_co_quoted_rate(self):
        """The boundary must not reject a real link, including one followed by a full stop."""
        for quote in ('Shipping £5 per order.', 'Shipping £5. Charged per order'):
            field = {'status': 'literal_components_present', 'missing': [], 'facts': {
                'amount': [fact('£5', quote, ROOT_URL)],
                'basis': [fact('per order', quote, ROOT_URL)]}}
            bound_delivery_assessment(field)
            self.assertNotIn('binding_warning', field, quote)
            self.assertEqual(field['status'], 'literal_components_present')
            self.assertEqual(field['missing'], [])


class Defect2CapturedExcerpt(unittest.TestCase):
    def setUp(self):
        self.page = EXCERPT  # invented excerpt with the same structure as the private captured excerpt

    def test_excerpt_states_no_vat_or_packing(self):
        """Supports 'missing: vat, packing' as schema-correct (absent stays unknown) for this excerpt."""
        self.assertIsNone(re.search(r'\bvat\b|pack', self.page, re.I))

    def test_excerpt_is_not_the_text_the_live_run_validated(self):
        """validate_atoms needs each quote verbatim in its source text. Three accepted live quotes are
        absent here, and the excerpt elides text with '...', so it cannot prove what the whole page omits."""
        self.assertIn('\n...\n', self.page)
        for absent in ('£12.34', 'Orders above £45*', 'Free standard mainland delivery'):
            self.assertNotIn(absent, self.page)
        for present in ('Standard delivery costs £3.80', SURCHARGE_QUOTE, 'Mainland Demo Region:'):
            self.assertIn(present, self.page)

    def test_excerpt_states_conditions_the_live_run_left_missing(self):
        """These explicit statements validate against the excerpt, so leaving them missing was an
        extraction miss (if, as is likely, the live text contained them), not a validator rejection."""
        cases = [
            ('free_delivery_threshold', 'exceptions', 'add a surcharge as well', THRESHOLD_EXCEPTION),
            ('delivery_geography', 'surcharge', '£8.20', '£8.20 per parcel to:\nHarbour Island\nOuter Reef Islands'),
            ('delivery_charge', 'order_condition', 'Orders Above £45', CHARGE_SENTENCE),
        ]
        for field, key, value, quote in cases:
            result = atomic.validate_atoms({key: {'value': value, 'quote': quote}},
                                           supplier.ATOMIC_FIELDS[field], self.page, ROOT_URL)
            self.assertIn(key, result['facts'], (field, key))

    def charge_field(self, raw):
        facts = atomic.validate_atoms(raw, supplier.ATOMIC_FIELDS['delivery_charge'], self.page, ROOT_URL)['facts']
        self.assertEqual(set(facts), set(raw))  # every claim is literally supported by the excerpt
        evidence = {k: [v] for k, v in facts.items()}
        return bound_delivery_assessment(assess_comparable(evidence, supplier.ATOMIC_FIELDS['delivery_charge']))

    def test_order_condition_in_the_charge_sentence_links_to_the_charge(self):
        field = self.charge_field({
            'amount': {'value': '£3.80', 'quote': 'Standard delivery costs £3.80'},
            'order_condition': {'value': 'Orders Above £45', 'quote': CHARGE_SENTENCE}})
        self.assertNotIn('order_condition', field['missing'])
        self.assertNotIn('binding_warning', field)

    def test_threshold_quoted_without_the_charge_stays_missing(self):
        field = self.charge_field({
            'amount': {'value': '£3.80', 'quote': 'Standard delivery costs £3.80'},
            'order_condition': {'value': 'Orders Above £45', 'quote': THRESHOLD_EXCEPTION}})
        self.assertIn('order_condition', field['missing'])
        self.assertEqual(field['binding_warning'], CONDITION_WARNING)
        self.assertEqual([c['value'] for c in field['facts']['order_condition']], ['Orders Above £45'])
        self.assertNotEqual(field['status'], 'literal_components_present')

    def test_unlinked_basis_and_condition_are_both_reported(self):
        field = self.charge_field({
            'amount': {'value': '£3.80', 'quote': 'Standard delivery costs £3.80'},
            'basis': {'value': 'per parcel', 'quote': '£6.40 per parcel to:'},
            'order_condition': {'value': 'Orders Above £45', 'quote': THRESHOLD_EXCEPTION}})
        self.assertIn('basis', field['missing'])
        self.assertIn('order_condition', field['missing'])
        self.assertEqual(field['binding_warning'], BINDING_WARNING + ' ' + CONDITION_WARNING)

    def test_standard_rate_line_carries_no_basis(self):
        """On the excerpt the £3.80 line states no per-parcel/order basis, so 'basis missing' is right."""
        line = next(x for x in self.page.splitlines() if '£3.80' in x)
        self.assertIsNone(re.search(r'\bper\b', line))


class ApprovedSchemaWording(unittest.TestCase):
    def test_extractor_prompt_carries_the_wording_and_the_charge_sentence(self):
        """Real extract_page puts json.dumps(schemas) in the prompt, so the description reaches the model."""
        from scout.engine.atomic_run import extract_page
        page = EXCERPT

        class CapturingLLM:
            def generate_structured(self, prompt, schema):
                self.prompt, self.schema = prompt, schema
                return {}
        llm = CapturingLLM()
        extract_page(QUESTION, {'delivery_charge': supplier.ATOMIC_FIELDS['delivery_charge']}, page, ROOT_URL, llm)
        self.assertIn('quoted in the same sentence as the charge', llm.prompt)
        self.assertIn(CHARGE_SENTENCE, llm.prompt.split('DATA:\n', 1)[1])
        self.assertIn('order_condition', llm.schema['properties']['delivery_charge']['properties'])

    def test_order_condition_wording_is_the_approved_text(self):
        self.assertEqual(supplier.ATOMIC_FIELDS['delivery_charge']['order_condition'],
                         'Order value or quantity condition under which this delivery charge applies, '
                         'quoted in the same sentence as the charge; absent stays unknown')


class Defect4WordingVariation(unittest.TestCase):
    def test_current_comparison_labels_wording_as_variation_not_conflict(self):
        fields = current_fields()
        geo = fields['delivery_geography']
        self.assertEqual(geo['status'], 'incomplete_literal_variation')
        self.assertEqual(geo['conflicts'], {})
        self.assertIn('excluded', geo['literal_variations'])
        self.assertEqual(fields['delivery_charge']['conflicts'], {})
        self.assertIn('basis', fields['delivery_charge']['literal_variations'])

    def test_readable_shows_variation_note_and_no_conflict_wording(self):
        text = readable(current_fields())
        self.assertNotIn('conflicting values retained', text)
        self.assertEqual(text.count(VARIATION_NOTE), 2)

    def test_delivery_guard_keeps_the_variation_status(self):
        self.assertEqual(current_fields()['delivery_charge']['status'], 'incomplete_literal_variation')

    def test_numeric_amount_disagreement_still_reported_as_conflict(self):
        ev = {'amount': both('£3.80', 'Standard delivery costs £3.80', tab_value='£4.20',
                             tab_quote='Standard delivery costs £4.20')}
        field = bound_delivery_assessment(assess_comparable(ev, supplier.ATOMIC_FIELDS['delivery_charge']))
        self.assertEqual(field['status'], 'possible_numeric_disagreement')
        self.assertIn('conflicting values retained', readable({'delivery_charge': field}))


NUMBERS_NOTE = ('Different numbers quoted for arrival; human review needed to judge whether the meanings match; '
                'not a confirmed contradiction.')


class Defect4cDifferingNumbersOutsideAmount(unittest.TestCase):
    """Design decision: keep both quotes, keep review required, stay a variation, never claim
    the two numbers agree or conflict, and say plainly that a human must judge."""

    def arrival(self, first, second):
        ev = {'arrival': [fact(first, 'please allow ' + first, ROOT_URL),
                          fact(second, 'please allow ' + second, ROOT_URL + 'delivery-information/')]}
        return assess_comparable(ev, supplier.ATOMIC_FIELDS['delivery_time'])

    def test_differing_numbers_keep_both_quotes_as_a_variation_with_review_note(self):
        field = self.arrival('3-5 working days', '5-7 working days')
        self.assertEqual(field['status'], 'incomplete_literal_variation')
        self.assertEqual(field['conflicts'], {})
        self.assertTrue(field['review_required'])
        self.assertEqual([f['value'] for f in field['facts']['arrival']], ['3-5 working days', '5-7 working days'])
        self.assertEqual(field['variation_note'], NUMBERS_NOTE)
        text = readable({'delivery_time': field})
        self.assertIn(NUMBERS_NOTE, text)
        self.assertNotIn('conflicting values retained', text)
        self.assertNotIn(VARIATION_NOTE, text)

    def test_number_against_no_number_also_needs_review(self):
        self.assertEqual(self.arrival('3-5 working days', 'next working day')['variation_note'], NUMBERS_NOTE)

    def test_same_numbers_keep_the_plain_variation_note(self):
        field = self.arrival('3-5 working days', '3 to 5 working days')
        self.assertEqual(field['status'], 'incomplete_literal_variation')
        self.assertEqual(field['variation_note'], VARIATION_NOTE)

    def test_run_continues_past_differing_non_amount_numbers(self):
        distinct = ROOT_URL + 'delivery-information/'
        browser = TextBrowser({ROOT_URL: ARRIVAL_PAGE_1, distinct: ARRIVAL_PAGE_2}, [distinct])
        r = run_loop(browser, llm=QuoteLLM(ARRIVAL_PATTERN, 'delivery_time', 'arrival'))
        row = r['rows'][0]
        self.assertEqual(row['stop_reason'], 'page_budget')  # not possible_numeric_disagreement
        self.assertEqual(row['pages_visited'], [ROOT_URL, distinct])
        field = row['atomic_fields']['delivery_time']
        self.assertEqual(field['status'], 'incomplete_literal_variation')
        self.assertEqual([f['value'] for f in field['facts']['arrival']], ['3-5 working days', '5-7 working days'])
        self.assertEqual(field['variation_note'], NUMBERS_NOTE)
        self.assertIn(NUMBERS_NOTE, r['readable'])
        self.assertEqual(r['state'], 'bounded_result_review_required')

    def test_differing_amounts_still_stop_the_site(self):
        distinct = ROOT_URL + 'delivery-information/'
        browser = TextBrowser({ROOT_URL: 'Standard delivery costs £3.80', distinct: 'Standard delivery costs £4.20'},
                              [distinct])
        r = run_loop(browser, llm=QuoteLLM(r'Standard delivery costs (£\d+\.\d+)', 'delivery_charge', 'amount'))
        self.assertEqual(r['rows'][0]['stop_reason'], 'possible_numeric_disagreement')


# --- Defect 3: same-document reread, exercised through the real tool loop -----------------
SOURCE_TEXT = ('Demo Strong Flour 16kg £12.34\nMainland Demo Region:\nStandard delivery costs £3.80\n'
               + SURCHARGE_QUOTE)  # invented


class OneDocBrowser:
    """Synthetic browser: every URL on the site serves the same reconstructed text."""

    def __init__(self, links, redirects=None):
        self.links, self.redirects, self.asked = links, redirects or {}, []

    def goto(self, u):
        self.url = self.redirects.get(u, u)
        return self.url

    def text(self):
        return SOURCE_TEXT

    def pick_evidence_link(self, missing, exclude):
        self.asked.append(list(exclude))
        return next((u for u in self.links if u not in exclude), None)

    def try_select_variant(self, x):
        return False


class VariantDataBrowser(OneDocBrowser):
    def fetch_variant_data(self):
        return ROOT_URL + '#variant-16kg', SOURCE_TEXT


class TextBrowser(OneDocBrowser):
    """Synthetic browser serving different made-up text per URL."""

    def __init__(self, pages, links):
        super().__init__(links)
        self.pages = pages

    def text(self):
        return self.pages[self.url]


ARRIVAL_PATTERN = r'please allow (\d-\d working days)'
ARRIVAL_PAGE_1 = 'Synthetic test page. please allow 3-5 working days for your parcel to arrive.'
ARRIVAL_PAGE_2 = 'Synthetic test page. please allow 5-7 working days for your parcel to arrive.'


class QuoteLLM:
    """Returns one claim whose value and quote are read literally from the page text."""

    def __init__(self, pattern, field, key):
        self.pattern, self.field, self.key = pattern, field, key

    def generate_structured(self, prompt, schema):
        m = re.search(self.pattern, prompt)
        return {self.field: {self.key: {'value': m.group(1), 'quote': m.group(0)}}} if m else {}


class OneDocLLM:
    def generate_structured(self, prompt, schema):
        return {'product_price': {'amount': {'value': '£12.34', 'quote': 'Demo Strong Flour 16kg £12.34'}},
                'delivery_charge': {'amount': {'value': '£3.80', 'quote': 'Standard delivery costs £3.80'}}}


def extract_with_validator(question, fields, text, url, llm, original_text=None, tables=None):
    raw = llm.generate_structured(text, fields)
    got = {}
    for f, keys in fields.items():
        if f in raw:
            facts = atomic.validate_atoms(raw[f], list(keys), text, url)['facts']
            if facts:
                got[f] = facts
    return got, {}


def same_host(url, roots):
    return all(urlparse(url).netloc == urlparse(r).netloc for r in roots)


def run_loop(browser, tool_steps=None, llm=None):
    plan = demo_plan()
    for site in plan.workflow['sites']:
        site.pop('delivery_page', None)  # these tests cover link handling; the configured page is tested elsewhere
    if tool_steps is not None:
        plan.budgets['tool_steps'] = tool_steps
    with mock.patch.object(tool_loop, 'extract_page', extract_with_validator), \
            mock.patch.object(tool_loop, 'safe_destination', same_host):
        return tool_loop.execute_plan(plan, browser, llm or OneDocLLM())


class Defect3SameDocumentReread(unittest.TestCase):
    """Runs the real execute_plan. Only the unseen extractor and destination policy are
    replaced (by a validate_atoms extractor and a same-host check), so these tests
    cover loop control flow, not live extraction."""

    def run_loop(self, browser, tool_steps=None):
        return run_loop(browser, tool_steps)

    def tools(self, r):
        return [e['tool'] for e in r['trace']]

    def test_canonical_source_ignores_fragment(self):
        self.assertEqual(tool_loop.canonical_source(TAB_URL), ROOT_URL)

    def test_preserved_anchor_link_is_not_reread(self):
        browser = OneDocBrowser([TAB_URL])
        r = self.run_loop(browser)
        row = r['rows'][0]
        self.assertEqual(row['pages_visited'], [ROOT_URL])
        self.assertEqual(row['stop_reason'], 'duplicate_source')
        self.assertEqual(r['generation_calls'], 1)
        # One bounded re-ask, with the duplicate excluded, before stopping.
        self.assertEqual(self.tools(r).count('evidence_link'), 2)
        self.assertEqual(browser.asked, [[ROOT_URL], [ROOT_URL, TAB_URL]])

    def test_anchor_duplicate_moves_on_to_a_distinct_source(self):
        distinct = ROOT_URL + 'delivery-information/'
        r = self.run_loop(OneDocBrowser([TAB_URL, distinct]))
        self.assertEqual(r['rows'][0]['pages_visited'], [ROOT_URL, distinct])
        self.assertEqual(r['generation_calls'], 2)

    def test_redirect_back_to_a_visited_document_is_not_reread(self):
        hop = ROOT_URL + 'delivery-information/'
        r = self.run_loop(OneDocBrowser([hop], redirects={hop: TAB_URL}))
        self.assertEqual(r['generation_calls'], 1)
        self.assertEqual(r['rows'][0]['stop_reason'], 'duplicate_source')
        self.assertEqual(r['rows'][0]['pages_visited'], [ROOT_URL])

    def test_variant_data_for_a_visited_document_is_not_reread(self):
        r = self.run_loop(VariantDataBrowser([]))
        self.assertEqual(r['rows'][0]['pages_visited'], [ROOT_URL])
        self.assertEqual(r['generation_calls'], 1)

    def test_reask_counts_against_the_tool_budget(self):
        # navigate, read, extract, evidence_link = 4; the re-ask would be step 5.
        r = self.run_loop(OneDocBrowser([TAB_URL, ROOT_URL + 'delivery-information/']), tool_steps=4)
        self.assertEqual(r['tool_steps'], 4)
        self.assertEqual(r['rows'][0]['stop_reason'], 'tool_budget')
        self.assertEqual(r['rows'][0]['pages_visited'], [ROOT_URL])


class PageTextRecording(unittest.TestCase):
    def test_each_read_page_text_is_kept_with_the_result(self):
        distinct = ROOT_URL + 'delivery-information/'
        r = run_loop(OneDocBrowser([distinct]))
        texts = r['rows'][0]['page_texts']
        self.assertEqual(texts, [{'source_url': ROOT_URL, 'text': SOURCE_TEXT},
                                 {'source_url': distinct, 'text': SOURCE_TEXT}])
        json.dumps(r)  # result stays serialisable for result.json

    def test_page_texts_do_not_change_the_readable_output(self):
        r = run_loop(OneDocBrowser([]))
        self.assertNotIn(SOURCE_TEXT, r['readable'])


if __name__ == '__main__':
    unittest.main()
"""TEST-ONLY invented demo suppliers and synthetic recordings for the public offline suite (25 November 2026).

This is a testing adapter, not product scope:
- the real supplier workflow config (scout/workflows/supplier.py) and the network-gated connectors are untouched;
- every name, address, page text, quote and amount below is INVENTED, on reserved .example addresses, and every
  supplier name says "(invented)";
- the recordings are produced by running the real engine (scout.engine.tool_loop.execute_plan) offline over these
  invented pages with a scripted model, so their shape is the engine's own, not hand-written JSON.

The three demo sites are synthetic structural analogues of three recorded runs that are not included here: a site
with a product page and a delivery page (one), a site whose store-data file lists the pack (two), and a site whose
page quotes another pack size so the 16kg pack stays unresolved (three). They are not rewrites of any real record.
"""
import json
from pathlib import Path

from scout.engine import store_data

FIXTURE_DIR = Path(__file__).resolve().parents[1] / 'demo' / 'recordings'  # invented demo data, outside tests
SYNTHETIC_DATE = '30 October 2026'  # the recorded-run date the UI labels; the content is invented

from scout.workflows.demo_supplier import LABELS, ONE, SITES, THREE, TWO  # noqa: E402,F401  separate demo config
SITE = {s['name']: s for s in SITES}
# Which invented site stands in for which configured site, by structural role only (one product page with a
# delivery page / a store-data site / a site with a known conflicting channel). Used to swap the planner's site list.
DEMO_FOR_CONFIG = {'wessex_mill': ONE, 'cotswold': TWO, 'shipton_mill': THREE}
# The planner resolves suppliers by their configured names; the invented label in a test question is translated to
# that name only to obtain a ready plan, whose sites are then replaced by the invented ones.
PLANNER_NAME = {'Demo Mill One (invented)': 'Wessex', 'Demo Mill Two (invented)': 'Cotswold',
                'Demo Mill Three (invented)': 'Shipton'}


def plan_question(question):
    """Test-only planner: the real planner, with the invented demo sites swapped in. Real config is untouched."""
    from scout.engine.planner import plan_question as real_plan_question
    planned = question
    for label, name in PLANNER_NAME.items():
        planned = planned.replace(label, name)
    plan = real_plan_question(planned)
    if plan.state == 'ready' and plan.domain == 'supplier':
        sites = [dict(SITE[DEMO_FOR_CONFIG[s['name']]]) for s in plan.workflow['sites'] if s['name'] in DEMO_FOR_CONFIG]
        plan.workflow = dict(plan.workflow, sites=sites, question=question)
    plan.question = question
    return plan

# -- invented page texts -------------------------------------------------------------------------------------------
BANNER = 'Free standard mainland delivery on Orders above £45*'
ONE_PRODUCT = '\n'.join([
    BANNER, 'Demo Mill One', 'Bread flour', 'Demo Strong Flour 16kg', '£12.34', 'Delivery and returns',
    'Standard delivery costs £3.80', '£6.40 per parcel to:', 'North Coast Isles', 'Far Valley District',
    'Mainland Demo Region:', 'We dispatch your order within two working days',
    'please allow 3-5 working days for your parcel to arrive.', 'We deliver only to mainland addresses for now.',
    BANNER])
ONE_DELIVERY = '\n'.join([
    BANNER, 'Delivery information', 'Mainland Demo Region', 'Standard delivery costs £3.80',
    'We dispatch all orders within 2 working days', 'please allow 3-5 working days for your parcel to arrive.',
    'We cannot deliver to:', 'Harbour Island\nForces mail addresses.',
    'Regional rates:', '£6.40 per parcel\n\nNorth Coast Isles\nWestern Highlands Zone\nFar Valley District',
    '£8.20 per parcel to Outer Reef Islands', BANNER])
TWO_PRODUCT = '\n'.join([
    'Demo Mill Two', 'Demo Premium Flour 16kg', 'Regular price\n£14.56', 'Pack size', '16kg Sack',
    'Free Delivery On Orders Above £40 For Most Demo Regions* - Terms Apply', 'Sold out'])
THREE_PRODUCT = '\n'.join([
    'Demo Mill Three', 'Demo Canadian-style Flour', 'From £1.23', 'Size', '1KG', 'Delivery',
    '- Orders leave the mill within 3-5 working days', 'Questions? Use the contact form.'])
TWO_DATA = {'title': 'Demo Premium Flour', 'variants': [{'title': '16kg Sack', 'price': 1456, 'available': False}]}
THREE_DATA = {'title': 'Demo Canadian-style Flour', 'variants': [
    {'title': '1kg', 'price': 123, 'available': True}, {'title': '16kg', 'price': 1567, 'available': True},
    {'title': '25kg', 'price': 2234, 'available': True}]}

PAGES = {SITE[ONE]['url']: ONE_PRODUCT, SITE[ONE]['delivery_page']: ONE_DELIVERY,
         SITE[TWO]['url']: TWO_PRODUCT, SITE[THREE]['url']: THREE_PRODUCT}
DATA = {TWO: TWO_DATA, THREE: THREE_DATA}


def _c(value, quote):
    return {'value': value, 'quote': quote}


# What the scripted model "extracts" from each invented page: every quote is a verbatim substring of that page.
CLAIMS = {
    SITE[ONE]['url']: {
        'product_price': {'amount': _c('£12.34', '£12.34'), 'currency': _c('£', '£12.34'),
                          'variant': _c('16kg', 'Demo Strong Flour 16kg')},
        'delivery_charge': {'amount': _c('£3.80', 'Standard delivery costs £3.80'),
                            'basis': _c('per parcel', '£6.40 per parcel to:'),
                            'zone': _c('Mainland Demo Region', 'Mainland Demo Region:')},
        'free_delivery_threshold': {'amount': _c('£45', 'Orders above £45*'),
                                    'comparison': _c('above', 'Orders above £45*'),
                                    'zone': _c('standard mainland', BANNER)},
        'delivery_time': {'dispatch': _c('within two working days', 'We dispatch your order within two working days'),
                          'arrival': _c('3-5 working days', 'please allow 3-5 working days for your parcel to arrive.')},
        'delivery_geography': {'included': _c('mainland addresses', 'We deliver only to mainland addresses for now.')}},
    SITE[ONE]['delivery_page']: {
        'delivery_charge': {'amount': _c('£3.80', 'Standard delivery costs £3.80')},
        'free_delivery_threshold': {'amount': _c('£45', BANNER), 'comparison': _c('above', BANNER),
                                    'zone': _c('mainland', BANNER)},
        'delivery_time': {'dispatch': _c('within 2 working days', 'We dispatch all orders within 2 working days'),
                          'arrival': _c('3-5 working days', 'please allow 3-5 working days for your parcel to arrive.')},
        'delivery_geography': {'included': _c('Mainland Demo Region', 'Mainland Demo Region'),
                               'excluded': _c('Harbour Island\nForces mail addresses.',
                                              'Harbour Island\nForces mail addresses.'),
                               'surcharge': _c('£6.40 per parcel',
                                               '£6.40 per parcel\n\nNorth Coast Isles\nWestern Highlands Zone\n'
                                               'Far Valley District')}},
    SITE[TWO]['url']: {
        'product_price': {'amount': _c('£14.56', 'Regular price\n£14.56'), 'currency': _c('£', '£14.56'),
                          'variant': _c('16kg Sack', '16kg Sack')},
        'free_delivery_threshold': {
            'amount': _c('£40', 'Free Delivery On Orders Above £40 For Most Demo Regions* - Terms Apply'),
            'comparison': _c('Above', 'Free Delivery On Orders Above £40 For Most Demo Regions* - Terms Apply'),
            'zone': _c('Most Demo Regions*', 'Free Delivery On Orders Above £40 For Most Demo Regions* - Terms Apply')}},
    SITE[THREE]['url']: {
        'product_price': {'currency': _c('£', '£1.23'), 'variant': _c('1KG', '1KG')},
        'delivery_time': {'dispatch': _c('3-5 working days', '- Orders leave the mill within 3-5 working days')}},
}


class DemoBrowser:
    """Serves the invented pages; a store-data file exists for demo sites two and three."""

    def __init__(self, site):
        self.site, self.visited, self.url = site, [], None

    def goto(self, url):
        self.url = url
        self.visited.append(url)
        return url

    def text(self):
        return PAGES.get(self.url, 'Synthetic page with no delivery details.')

    def pick_evidence_link(self, missing, exclude):
        return None  # the configured delivery page is the fallback, as in the recorded runs

    def try_select_variant(self, option):
        return False

    def fetch_variant_data(self):
        data = DATA.get(self.site)
        return (self.url.split('?')[0] + '.js', store_data.format_variants(data)) if data else None


class DemoLLM:
    """Scripted model: returns the invented claims for the page it is shown, identified by its address."""

    def __init__(self, browser):
        self.browser, self.calls = browser, 0

    def generate_structured(self, prompt, schema):
        self.calls += 1
        return json.loads(json.dumps(CLAIMS.get(self.browser.url, {})))


def make_recording(site):
    """Run the real engine offline over the invented pages for one demo site; returns the result dict."""
    from scout.engine.planner import plan_question
    from scout.engine.tool_loop import execute_plan
    plan = plan_question('Compare the price and delivery conditions of one 16kg sack of strong white bread flour '
                         'from Wessex')  # a ready supplier plan; its site list is replaced by the invented site
    plan.question = 'Compare %s demo flour 16kg delivery conditions (SYNTHETIC test recording)' % LABELS[site]
    plan.workflow = dict(plan.workflow, sites=[SITE[site]], question=plan.question)
    browser = DemoBrowser(site)
    result = execute_plan(plan, browser, DemoLLM(browser))
    # LEGACY FORMAT: the recordings these stand in for predate the offer screen (offer-v1), so they carry no offer
    # decision. Stripping it keeps the UI's re-screen path for old runs covered.
    for row in result['rows']:
        row.pop('offer_evidence', None)
        for field in row['atomic_fields'].values():
            field.pop('offer', None)
        # LEGACY FORMAT (runs saved before 2 November 2026): no store_data record, and store-data lines carried a
        # £ added by Scott's own formatting. Keeps the UI's legacy note ("the data itself states no currency") covered.
        if row.pop('store_data', None) is not None:
            import re as _re
            pound = lambda t: _re.sub(r'\| (\d+\.\d\d) \|', r'| £\1 |', t)  # noqa: E731
            for page in row.get('page_texts') or []:
                if page['source_url'].endswith('.js'):
                    page['text'] = pound(page['text'])
            for field in row['atomic_fields'].values():
                for claims in field['facts'].values():
                    for c in claims:
                        if c['source_url'].endswith('.js'):
                            c['quote'] = pound(c['quote'])
                            if _re.fullmatch(r'\d+\.\d\d', c['value']):
                                c['value'] = '£' + c['value']
    # A legacy-format header, so the UI path for old saved reports that printed a fixed date stays covered.
    result['readable'] = ('# Scout planned research\n\nRead-only evidence snapshot, 27 October 2026. SYNTHETIC test '
                          'recording of invented pages.\n\n' + result.get('readable', ''))
    return result


def write_recordings(folder=FIXTURE_DIR):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for site in (ONE, TWO, THREE):
        (folder / ('%s-result.json' % site)).write_text(
            json.dumps(make_recording(site), indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return folder


def use_demo_recordings(monkeypatch, ui, folder=FIXTURE_DIR):
    """Point a loaded scout_ui module at the invented recordings and names, for one test only."""
    monkeypatch.setattr(ui, 'RECORDED_DIR', Path(folder))
    monkeypatch.setattr(ui, 'RECORDED_SITES', [ONE, TWO, THREE])
    monkeypatch.setattr(ui, 'SITE_LABELS', dict(LABELS))
    return Path(folder)


# -- demo scorecard (invented truth file and rubric; tests only) ---------------------------------------------------
DEMO_EVALS = Path(__file__).resolve().parents[1] / 'demo' / 'evals'
DEMO_SCORECARD = DEMO_EVALS / 'scorecard-demo.json'


def demo_scorecard_builder(monkeypatch):
    """scripts/build_scorecard.py in demo mode (scout/demo_mode.py), for one test only."""
    import importlib.util
    from scout import demo_mode
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('build_scorecard_demo', root / 'scripts' / 'build_scorecard.py')
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    return demo_mode.apply_to_builder(build, monkeypatch.setattr)


def use_demo_scorecard(monkeypatch, ui):
    from scout import demo_mode
    return demo_mode.apply_to_ui(ui, monkeypatch.setattr)


def write_demo_scorecard():
    import importlib.util
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('build_demo_scorecard', root / 'scripts' / 'build_demo_scorecard.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = module.build()
    DEMO_SCORECARD.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return data

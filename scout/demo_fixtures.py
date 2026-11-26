"""Labelled synthetic demo fixtures, shared by scripts/scout_question.py --demo and scripts/scout_ui.py.

Every page text and every quote below is invented sample data marked 'DEMO FIXTURE'.
None of it is current web data. Sample runs never use a real supplier or provider address:
sample_plan() moves each planned source to a reserved .example address (RFC 2606), which can
never be a real website, and gives each source an INVENTED demo name (DEMO_NAMES), so a sample
output names no real supplier or provider and carries no real address. Prices are deliberately artificial (£12.34, $1.23) so they cannot be mistaken
for recorded real prices. Each source shows a different outcome: found, not found, two
disagreeing values, or only part of the context.
"""
from copy import deepcopy
from urllib.parse import urlparse

from scout.engine.store_data import NO_CURRENCY_NOTE

SAMPLE_SUFFIX = '.sample.example'
# Invented sample identities for the configured sources (the real configuration itself is unchanged).
DEMO_NAMES = {'wessex_mill': 'demo_mill_one', 'cotswold': 'demo_mill_two', 'shipton_mill': 'demo_mill_three',
              'wessex_wholemeal': 'demo_mill_one_wholemeal', 'mistral': 'demo_provider_one',
              'openai': 'demo_provider_two', 'anthropic': 'demo_provider_three'}


def _slug(text):
    return ''.join(c if c.isalnum() else '-' for c in text.casefold()).strip('-')


def sample_url(site):
    host = 'https://' + site['name'].replace('_', '-') + SAMPLE_SUFFIX
    return host + ('/pricing/' + _slug(site['model']) if site.get('model') else '/product')


def sample_plan(plan):
    """The same plan, with every source moved to its reserved sample address."""
    plan = deepcopy(plan)
    for site in plan.workflow.get('sites', []):
        site['name'] = DEMO_NAMES.get(site['name'], 'demo_source')  # invented identity, never the real name
        site['url'] = sample_url(site)
        site.pop('delivery_page', None)  # a real address; sample runs only follow invented links
        site.pop('offer_binding', None)  # real product paths and SKUs; sample runs capture no offers
    return plan


# Page texts, keyed by (source name, path). Quotes in RESPONSES are exact substrings of these.
PAGES = {
    ('demo_mill_one', '/product'): 'DEMO FIXTURE, invented sample text, not a real web page. '
                                 'Demo Strong Flour 16kg sack £12.34. See Delivery information.',
    ('demo_mill_one', '/delivery'): 'DEMO FIXTURE, invented sample text, not a real web page. '
                                  'Standard UK delivery is £5.67 per order. '
                                  'Free standard UK delivery on orders over £60.00.',
    ('demo_mill_two', '/product'): 'DEMO FIXTURE, invented sample text, not a real web page. '
                              'Demo Premium Flour 16kg sack £45.67. No delivery details on this page.',
    ('demo_mill_three', '/product'): 'DEMO FIXTURE, invented sample text, not a real web page. '
                                  'Demo Canadian-style Flour £23.45. Choose a pack size.',
    # Store product data in the browser's plain-line format; read in code, not by the model.
    ('demo_mill_three', '/product.js'): 'DEMO FIXTURE, invented sample data, not a real store feed.\n'
                                     + NO_CURRENCY_NOTE + '\n1kg | 3.21 | available=True'
                                     '\n16kg | 24.56 | available=False',
    ('demo_mill_one_wholemeal', '/product'): 'DEMO FIXTURE, invented sample text, not a real web page. '
                                      'Wholemeal Bread Flour 16kg sack £13.57.',
    ('demo_provider_one', '/pricing'): 'DEMO FIXTURE, invented sample text, not a real pricing page. '
                             'Ministral 3 8B: $1.23 input / $4.56 output, USD per million tokens, Standard. '
                             'Mistral Large 3: $2.34 input / $5.67 output.',
    ('demo_provider_two', '/pricing'): 'DEMO FIXTURE, invented sample text, not a real pricing page. '
                            'gpt-6.1-sol: $3.45 input / $6.78 output.',
    ('demo_provider_three', '/pricing'): 'DEMO FIXTURE, invented sample text, not a real pricing page. '
                               'Claude Sonnet 5.5: $7.89 input / $8.91 output.',
}
UNKNOWN_PAGE = 'DEMO FIXTURE, invented sample text, not a real web page. No details on this page.'


def _f(value, quote):
    return {'value': value, 'quote': quote}


def _price(amount, variant, quote):
    return {'product_price': {'amount': _f(amount, quote), 'currency': _f('£', quote), 'variant': _f(variant, quote)}}


def _model(model, line, input_price, output_price, full=False):
    out = {}
    for kind, amount in (('input', input_price), ('output', output_price)):
        claims = {'amount': _f(amount, line), 'model': _f(model, line)}
        if full:
            context = 'USD per million tokens, Standard'
            claims.update(currency=_f('USD', context), unit=_f('per million tokens', context),
                          processing=_f('Standard', context))
        out['model_price_' + kind] = claims
    return out


RESPONSES = {
    ('demo_mill_one', '/product'): _price('£12.34', '16kg', 'Demo Strong Flour 16kg sack £12.34'),
    ('demo_mill_one', '/delivery'): {
        'delivery_charge': {'amount': _f('£5.67', 'Standard UK delivery is £5.67 per order'),
                            'basis': _f('per order', 'Standard UK delivery is £5.67 per order'),
                            'zone': _f('UK', 'Standard UK delivery is £5.67 per order')},
        'free_delivery_threshold': {'amount': _f('£60.00', 'Free standard UK delivery on orders over £60.00'),
                                    'comparison': _f('over', 'Free standard UK delivery on orders over £60.00'),
                                    'zone': _f('UK', 'Free standard UK delivery on orders over £60.00')}},
    ('demo_mill_two', '/product'): _price('£45.67', '16kg', 'Demo Premium Flour 16kg sack £45.67'),
    # The page gives a price but no pack size, so the store data is read too; its 16kg price differs.
    ('demo_mill_three', '/product'): {'product_price': {
        'amount': _f('£23.45', 'Demo Canadian-style Flour £23.45'),
        'currency': _f('£', 'Demo Canadian-style Flour £23.45')}},
    ('demo_mill_one_wholemeal', '/product'): _price('£13.57', '16kg', 'Wholemeal Bread Flour 16kg sack £13.57'),
    ('demo_provider_one', '/pricing/ministral-3-8b'): _model('Ministral 3 8B', 'Ministral 3 8B: $1.23 input / $4.56 output',
                                                   '$1.23', '$4.56', full=True),
    ('demo_provider_one', '/pricing/mistral-large-3'): _model('Mistral Large 3', 'Mistral Large 3: $2.34 input / $5.67 output',
                                                    '$2.34', '$5.67'),
    ('demo_provider_two', '/pricing/gpt-6-1-sol'): _model('gpt-6.1-sol', 'gpt-6.1-sol: $3.45 input / $6.78 output',
                                               '$3.45', '$6.78'),
    ('demo_provider_three', '/pricing/claude-sonnet-5-5'): _model('Claude Sonnet 5.5',
                                                        'Claude Sonnet 5.5: $7.89 input / $8.91 output',
                                                        '$7.89', '$8.91'),
}


def _key(url):
    p = urlparse(url)
    host = p.hostname or ''
    name = host[:-len(SAMPLE_SUFFIX)].replace('-', '_') if host.endswith(SAMPLE_SUFFIX) else host
    return name, p.path


def _page_key(url):
    name, path = _key(url)
    return name, ('/pricing' if path.startswith('/pricing/') else path)


class DemoBrowser:
    def __init__(self, plan):
        self.plan = plan
        self.url = ''

    def goto(self, u):
        self.url = u
        return u

    def text(self):
        return PAGES.get(_page_key(self.url), UNKNOWN_PAGE)

    def pick_evidence_link(self, missing, exclude):
        name, path = _key(self.url)
        if name == 'demo_mill_one' and path == '/product':
            link = self.url.rsplit('/', 1)[0] + '/delivery'
            return None if link in exclude else link
        return None

    def fetch_variant_data(self):
        name, path = _key(self.url)
        if name == 'demo_mill_three' and path == '/product':
            u = self.url + '.js'
            return u, PAGES[(name, '/product.js')]
        return None

    def try_select_variant(self, x):
        return False


class DemoLLM:
    def __init__(self, plan):
        self.plan = plan

    def generate_structured(self, prompt, schema):
        # extract_page puts 'Source: <url>' in the prompt; answer for that sample page only.
        source = next((line[len('Source: '):] for line in prompt.splitlines() if line.startswith('Source: ')), '')
        return deepcopy(RESPONSES.get(_key(source), {}))

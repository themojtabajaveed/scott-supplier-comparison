"""Private local web UI for Scott's offline sample-data demo.

Python standard library only. Binds 127.0.0.1. Serves GET pages; the only
POST is /run, which plans the question and, when the plan is ready, runs the
bounded tool loop on the same labelled synthetic fixtures as
`scripts/scout_question.py --demo`. When saved live-run result files are present
(eval-results/live-30oct; not included in this copy), it replays them as read-only
playback, read from local files only. GET /comparison renders those recorded runs side by side as one supplier
comparison sheet: every fact sits next to its verbatim quote and source link,
and anything a run did not find is marked as not found. The one exception to "no network": a live run of one approved supplier page,
which happens only when the person running the server has a key in its environment
and ticks a confirmation box (POST /live/run); see scout/live_run.py. Playwright is
imported only inside that path. Otherwise no network calls, and no file writes
unless --output-dir names a folder under the current directory.
"""
import argparse
import hashlib
import html
import json
import os
import re
import secrets
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlencode, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scout.engine.planner import plan_question  # noqa: E402
from scout.engine.tool_loop import execute_plan  # noqa: E402
from scout.demo_fixtures import DemoBrowser, DemoLLM, sample_plan  # noqa: E402  (shared with the CLI demo)
from scout.engine.comparison import render_comparison  # noqa: E402
from scout import plain  # noqa: E402
from scout import m1_view  # noqa: E402  (standard library only; the M1 buyer-readable view)
from scout.evals import scorecard  # noqa: E402  (standard library only)
from scout import live_run  # noqa: E402  (standard library only at import time)

from scout.workflows import provider, supplier  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BANNER = 'Sample-data demonstration, not current prices or live data.'
RECORDED_BANNER = 'Recorded live run, 30 October 2026 - real public pages, read-only playback, not a fresh run.'
RECORDED_DATE = '30 October 2026'
RECORDED_HEADING = 'Recorded live runs, %s'  # demo mode (scout/demo_mode.py) replaces these two with invented wording
RECORDED_INTRO = ('<p><strong>Real, not sample data.</strong> On %s Scott read three public supplier pages, live and '
                  'read-only, one bounded run per supplier. They are replayed here side by side from saved files: '
                  'opening this page fetches nothing, and prices and terms are as read that day, not current.</p>')
RECORDED_DIR = ROOT / 'eval-results' / 'live-30oct'
RECORDED_SITES = [s['name'] for s in supplier.WORKFLOW['sites']]  # only these names map to files
SCORECARD_DIR = ROOT / 'eval-results'  # newest scorecard-<date>.json, built by scripts/build_scorecard.py
# Supplier comparison sheet (/comparison) only; the other pages use scout.plain's labels and words.
SITE_LABELS = {'wessex_mill': 'Wessex Mill', 'shipton_mill': 'Shipton Mill', 'cotswold': 'Cotswold Flour'}
FIELD_ORDER = ['product_price', 'delivery_charge', 'free_delivery_threshold', 'delivery_time', 'delivery_geography']
FIELD_LABELS = {'product_price': 'Product price (16kg sack)', 'delivery_charge': 'Delivery charge',
                'free_delivery_threshold': 'Free delivery threshold', 'delivery_time': 'Delivery time',
                'delivery_geography': 'Delivery area'}
CLAIM_LABELS = {'amount': 'Amount', 'currency': 'Currency', 'variant': 'Pack size', 'basis': 'Basis',
                'zone': 'Zone', 'comparison': 'Comparison', 'dispatch': 'Dispatch', 'arrival': 'Arrival',
                'included': 'Delivers to', 'excluded': 'Does not deliver to', 'surcharge': 'Surcharge',
                'weight_limit': 'Weight limit', 'discount_condition': 'Discount condition',
                'exceptions': 'Exceptions', 'vat': 'VAT', 'packing': 'Packing', 'order_condition': 'Order condition'}
STATUS_WORDS = {'literal_components_present': 'Found',
                'incomplete': 'Partly found',
                'incomplete_literal_variation': 'Partly found',
                'possible_numeric_disagreement': 'Needs review'}
PROMPT_TEXT_LIMIT = 18000  # extract_page sends text[:18000]; tests pin this to atomic_run
RUN_PATH = '/run'
LIVE_RUN_PATH = '/live/run'
LIVE_BANNER_PREFIX = 'Live run, '
MAX_BODY = 4096
MAX_QUESTION = 500
DOMAINS = {
    'auto': 'Auto (detect from the question)',
    'supplier': 'Supplier (16kg flour)',
    'provider': 'API provider (token pricing)',
}
EXAMPLES = {
    'supplier': 'Compare the price and delivery conditions of one 16kg sack '
                'of strong white bread flour from Wessex',
    'provider': 'Compare Ministral 3 8B Standard USD input and output prices '
                'per million tokens',
}
NAV = (('/', 'Comparison'), ('/comparison', 'Supplier comparison'), ('/m1', 'M1 comparison'), ('/try', 'Try it'), ('/live', 'Live runs'),
       ('/about', 'How it works'))
# Question picker: choices map to one fixed question template per domain, and the planner still decides.
PICK_SITES = {s['name']: s['name'].replace('_mill', '').replace('_', ' ').title() for s in supplier.WORKFLOW['sites']}
PICK_PRODUCTS = {'strong_white': 'strong white bread flour', 'wholemeal': 'wholemeal bread flour'}
PICK_MODELS = [m for m, _ in provider.SUPPORTED_MODELS]
SUPPLIER_TEMPLATE = 'Compare the price and delivery conditions of one 16kg sack of %s from %s'
PROVIDER_TEMPLATE = 'Compare %s Standard USD uncached input and output prices per million tokens'
REFUSED_EXAMPLE = 'Compare flour 25kg from Unknown Mill'
RUN_LOCK = threading.Lock()  # one demo run at a time; the engine is not audited for concurrency


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def esc(value):

    return html.escape(str(value), quote=True)


def as_json(value, indent=None):
    return json.dumps(value, ensure_ascii=False, default=str, indent=indent)


def host_of(url):
    return urlparse(url).netloc or url


_LINK = re.compile(r'\[([^\]]+)\]\(([^)\s]+)\)')


def _inline(text, cell=False):
    """Escape first, then turn [label](url) into plain, non-clickable text.

    Sample "sources" are invented pages on reserved .example addresses, and saved
    runs are playback only, so no source is rendered as a clickable link.
    """
    out = _LINK.sub(lambda m: '<span class="src">' + m.group(1) + ': <code>' + m.group(2) + '</code></span>',
                    esc(text))
    return out.replace('&lt;br&gt;', '<br>') if cell else out


def _table(rows):
    def cells(row):
        inner = row.strip()
        inner = inner[1:-1] if inner.endswith('|') and not inner.endswith('\\|') else inner[1:]
        return [c.strip().replace('\\|', '|') for c in re.split(r'(?<!\\)\|', inner)]
    body = [r for r in rows if not re.fullmatch(r'\|[\s:|-]+\|?', r.strip())]
    if not body:

        return ''
    head = ''.join('<th>' + _inline(c) + '</th>' for c in cells(body[0]))
    trs = ''.join('<tr>' + ''.join('<td>' + _inline(c, cell=True) + '</td>' for c in cells(r)) + '</tr>'
                  for r in body[1:])
    return '<div class="scroll"><table><thead><tr>' + head + '</tr></thead><tbody>' + trs + '</tbody></table></div>'


def render_markdown(md):
    """Just enough Markdown for render_comparison output: headings, tables, bullets, paragraphs."""
    out, para, lines, i = [], [], md.splitlines(), 0

    def flush():
        if para:
            out.append('<p>' + _inline(' '.join(para)) + '</p>')
            para.clear()

    while i < len(lines):
        s = lines[i].strip()
        heading = re.match(r'(#{1,3})\s+(.*)', s)
        if not s:
            flush()
            i += 1
        elif heading:
            flush()
            level = len(heading.group(1)) + 2  # page uses h1 and h2 already
            out.append('<h%d>%s</h%d>' % (level, _inline(heading.group(2)), level))
            i += 1
        elif s.startswith('|'):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                rows.append(lines[i])

                i += 1
            out.append(_table(rows))
        elif s.startswith('- '):
            flush()
            items = []
            while i < len(lines) and lines[i].strip().startswith('- '):
                items.append(lines[i].strip()[2:])
                i += 1
            out.append('<ul>' + ''.join('<li>' + _inline(x) + '</li>' for x in items) + '</ul>')
        else:
            para.append(s)
            i += 1
    flush()
    return '\n'.join(out)


ISSUE_KEYS = ('gaps', 'missing', 'unknowns', 'conflicts', 'literal_variations',
              'binding_warning', 'variation_note', 'warnings',
              'incomplete_components', 'context_status', 'errors')


def collect_issues(obj, path=''):
    """Walk the result object and list every non-empty gap/unknown/conflict-type entry."""
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not path and key in ('trace', 'readable'):
                continue
            here = path + '.' + str(key) if path else str(key)
            if key in ISSUE_KEYS:
                if key == 'context_status' and isinstance(value, dict) \
                        and value.get('status') == 'scoped_components_present':

                    continue
                if value not in (None, '', [], {}):
                    found.append((path or 'result', key, value))
            else:
                found.extend(collect_issues(value, here))
    elif isinstance(obj, list):
        for n, value in enumerate(obj):
            found.extend(collect_issues(value, '%s[%d]' % (path, n)))
    return found


def describe_plan(plan):
    bits = ['domain: ' + str(plan.domain), 'state: ' + plan.state]
    ent = plan.entities or {}
    if ent.get('models'):
        bits.append('models: ' + ', '.join(ent['models']))
    if ent.get('product'):
        bits.append('product: ' + str(ent['product']))
    if ent.get('pack'):
        bits.append('pack: ' + str(ent['pack']))
    sites = [s['name'] for s in plan.workflow.get('sites', [])]
    if sites:
        bits.append('sources: ' + ', '.join(sites))
    return '; '.join(bits)


# ---------------------------------------------------------------------------
# Page rendering
# ---------------------------------------------------------------------------
CSS = """
:root{--bg:#f6f5f1;--fg:#1c1c1a;--muted:#5c5a53;--line:#d8d4c8;--card:#fff;--accent:#1f4e79;--on-accent:#fff;
--warn-bg:#ffefb8;--warn-fg:#3f2d00;--gap:#8a1c1c;--rec-bg:#dcebfa;--rec-fg:#0b3a66;--live-bg:#dff3e4;--live-fg:#0f4d24}

@media (prefers-color-scheme:dark){:root{--bg:#151513;--fg:#ebeae4;--muted:#a8a59b;--line:#393832;--card:#1e1e1b;
--accent:#8dbbe8;--on-accent:#101010;--warn-bg:#4a3a06;--warn-fg:#ffe9a3;--gap:#f2a3a3;--rec-bg:#0f2f4d;--rec-fg:#bfdcfa;--live-bg:#123d22;--live-fg:#bfeccb}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
.banner{position:sticky;top:0;z-index:10;background:var(--warn-bg);color:var(--warn-fg);border-bottom:2px solid currentColor;
padding:.6rem 1rem;font-weight:700;text-align:center}
.banner.recorded{background:var(--rec-bg);color:var(--rec-fg)}
.card.recorded{border-left:5px solid var(--rec-fg)}
.banner.live{background:var(--live-bg);color:var(--live-fg)}
.card.live{border-left:5px solid var(--live-fg)}
.top{border-bottom:1px solid var(--line);background:var(--card)}
.top div{max-width:62rem;margin:0 auto;padding:.7rem 1rem;display:flex;gap:1.25rem;align-items:baseline;flex-wrap:wrap}
.top strong{font-size:1.1rem;letter-spacing:.02em}
a{color:var(--accent)}
main{max-width:62rem;margin:0 auto;padding:1.25rem 1rem 3rem}
h1{font-size:1.7rem;margin:.5rem 0 .4rem}
h2{font-size:1.25rem;margin:2rem 0 .5rem;padding-bottom:.25rem;border-bottom:1px solid var(--line)}
h3{font-size:1.1rem}h4{font-size:1rem}h5{font-size:.95rem}
.lead{font-size:1.1rem;max-width:46rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:1rem 1.2rem;margin:1rem 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(18rem,1fr));gap:1rem}
.grid .card{margin:0}
label{font-weight:600;display:block;margin:.4rem 0 .3rem}
textarea,select{width:100%;font:inherit;padding:.55rem;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
textarea{min-height:5.5rem;resize:vertical}
.row{display:flex;gap:1rem;align-items:end;flex-wrap:wrap;margin-top:.6rem}
.row>div{flex:1 1 16rem}
button{font:inherit;font-weight:700;padding:.65rem 1.2rem;border:0;border-radius:6px;background:var(--accent);color:var(--on-accent);cursor:pointer}
button[disabled]{opacity:.6;cursor:progress}
table{border-collapse:collapse;width:100%;font-size:.92rem}
th,td{border:1px solid var(--line);padding:.4rem .55rem;text-align:left;vertical-align:top}
th{background:var(--bg)}

.scroll{overflow-x:auto}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.86em}
pre{white-space:pre-wrap;word-break:break-word;background:var(--bg);border:1px solid var(--line);padding:.75rem;border-radius:6px}
.src{color:var(--muted);font-size:.9em}
.muted{color:var(--muted)}
.state{display:inline-block;padding:.05rem .5rem;border:1px solid currentColor;border-radius:4px;font-family:ui-monospace,Menlo,Consolas,monospace}
.gaps li{color:var(--gap);margin:.25rem 0}
ol.trace li{margin:.2rem 0}
details{margin:.8rem 0}summary{cursor:pointer;font-weight:600}
dl{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:.25rem 1rem;margin:.5rem 0}dt{font-weight:600}
dd{margin:0;min-width:0;overflow-wrap:anywhere}.state{max-width:100%;overflow-wrap:anywhere}
details.how,details.ev{margin:.3rem 0}.ctx-sep ul{margin:.2rem 0;padding-left:1.1rem;font-size:.88em}
.ctx-sep{margin:.25rem 0}details.how summary,details.ev summary{font-weight:400;font-size:.88em}
details.how summary{color:var(--muted)}details.ev ul{margin:.3rem 0;padding-left:1.1rem}code{overflow-wrap:anywhere}
details.how p{margin:.25rem 0;font-size:.9em}.cmp-ctx{color:var(--muted);font-size:.88em;margin:.2rem 0}
footer{max-width:62rem;margin:0 auto;padding:1rem;color:var(--muted);font-size:.9rem;border-top:1px solid var(--line)}
table.cmp td{min-width:9rem}table.cmp th[scope=row]{white-space:nowrap}
.st{font-weight:700}.st.no,.st.disagree,.st.unrec{color:var(--gap)}.st.part,.st.review{color:var(--warn-fg)}
.code{color:var(--muted);font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.78em}
.cell-v{margin:0 0 .2rem}.cell-n{color:var(--muted);font-size:.86em;margin:.15rem 0}
.coverage{font-weight:600}
fieldset{border:0;padding:0;margin:.6rem 0}legend{font-weight:700;padding:0;margin-bottom:.2rem}
label.opt{font-weight:400;margin:.25rem 0}label.opt input{margin-right:.4rem}
details.own{margin-top:1.5rem}details.own>summary{font-size:1.05rem}
details.tech{border-top:1px solid var(--line);margin-top:2rem;padding-top:.5rem}
details.tech>summary{font-size:1.1rem}
@media (max-width:640px){
dl{grid-template-columns:minmax(0,1fr)}dt{margin-top:.35rem}
table.cmp,table.cmp tbody,table.cmp tr,table.cmp th,table.cmp td{display:block;width:100%}
table.cmp thead{display:none}
table.cmp tr{border:1px solid var(--line);border-radius:6px;margin:.7rem 0;background:var(--card)}
table.cmp th[scope=row]{border:0;font-size:1.05rem}
table.cmp td{border:0;border-top:1px solid var(--line);min-width:0}
table.cmp td::before{content:attr(data-label);display:block;font-weight:700;margin-bottom:.2rem}
}
.cmp-claims{list-style:none;margin:0 0 .3rem;padding-left:0}
.cmp-claims li{margin:.12rem 0}
.cmp-ev{margin:.25rem 0}
.cmp-ev summary,.cmp-miss summary,.cmp-rev summary{font-weight:400;color:var(--muted);font-size:.88em}
.cmp-ev ul{margin:.3rem 0;padding-left:1.1rem}
.cmp-miss,.cmp-rev{margin:.2rem 0}
.cmp-miss p,.cmp-rev p{margin:.25rem 0;font-size:.92em;color:var(--muted)}
.cmp-warn strong{color:var(--gap)}
.cmp-cards{display:none}
.cmp-card h3 small{display:block;font-weight:400;color:var(--muted);font-size:.8rem}
.cmp-field{margin:.7rem 0}
.cmp-field h4{margin:.2rem 0;color:var(--muted)}
@media (max-width:56rem){.cmp-wrap{display:none}.cmp-cards{display:block}}
.cmp-status{font-weight:700;margin:.35rem 0 .1rem}
.cmp-none{color:var(--gap);font-weight:700;margin:.2rem 0}
.cmp-review{background:var(--warn-bg);color:var(--warn-fg);padding:.25rem .45rem;border-radius:4px;margin:.3rem 0}
.cmp th small{display:block;font-weight:400;color:var(--muted)}
.home-cmp table.cmp td{min-width:0}.home-cmp table.cmp th[scope=row]{white-space:normal}
.home-cmp .code{overflow-wrap:break-word}
@media (max-width:56rem){
.home-cmp table.cmp,.home-cmp table.cmp tbody,.home-cmp table.cmp tr,.home-cmp table.cmp th,
.home-cmp table.cmp td{display:block;width:100%}
.home-cmp table.cmp thead{display:none}
.home-cmp table.cmp tr{border:1px solid var(--line);border-radius:6px;margin:.7rem 0;background:var(--card)}
.home-cmp table.cmp th[scope=row]{border:0;font-size:1.05rem}
.home-cmp table.cmp td{border:0;border-top:1px solid var(--line)}
.home-cmp table.cmp td::before{content:attr(data-label);display:block;font-weight:700;margin-bottom:.2rem}
}
""" + m1_view.CSS

HOME_JS = """
document.querySelectorAll('a[data-example]').forEach(function(a){
 a.addEventListener('click',function(ev){ev.preventDefault();document.getElementById('own').open=true;
  var q=document.getElementById('question');q.value=a.getAttribute('data-example');
  document.getElementById('domain').value=a.getAttribute('data-domain');q.focus();});});
document.querySelectorAll('form.run,form.pick').forEach(function(form){
 var b=form.querySelector('button'),label=b.textContent;
 form.addEventListener('submit',function(){b.disabled=true;b.textContent='Running on sample data';});
 window.addEventListener('pageshow',function(){b.disabled=false;b.textContent=label;});});
// Wholemeal is configured for Wessex only: grey out the other suppliers (the planner still refuses if sent).
var wholemeal=document.querySelector('input[name=product][value=wholemeal]');
function only(){document.querySelectorAll('input[name=site]').forEach(function(c){
 var off=wholemeal.checked&&c.value!=='wessex_mill';c.disabled=off;if(off)c.checked=false;});}
document.querySelectorAll('input[name=product]').forEach(function(r){r.addEventListener('change',only);});
"""


def page(title, body, nonce, banner=None, script=''):
    return ''.join([
        '<!doctype html><html lang="en-GB"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>', esc(title), ' | Scott</title><style nonce="', nonce, '">', CSS, '</style></head><body>',
        ('<div class="banner%s" role="note">%s</div>'
         % (' recorded' if banner in (RECORDED_BANNER, m1_view.RECORDED_BANNER) else (' live' if banner.startswith(LIVE_BANNER_PREFIX) else ''),
            esc(banner)) if banner else ''),

        '<header class="top"><div><strong>Scott</strong>',
        ''.join('<a href="%s">%s</a>' % item for item in NAV),
        '<span class="muted">Private local prototype</span></div></header>',
        '<main>', body, '</main>',
        '<footer>Private, read-only research prototype. Apart from a live run you start and confirm yourself, this '
        'interface makes no network calls: demos use built-in fixtures and recorded runs are replayed from saved '
        'files. Nothing is bought, deployed or stored in an account.</footer>',
        '<script nonce="' + nonce + '">' + script + '</script>' if script else '',
        '</body></html>'])


def recorded_path(recorded_dir, name):
    """Only allow-listed site names map to files; nothing from the URL becomes a path."""
    if recorded_dir is None or name not in RECORDED_SITES:
        return None
    return Path(recorded_dir) / (name + '-result.json')


def load_recorded(recorded_dir, name):
    """Read one saved result from local disk. Returns (result or None, reason)."""
    path = recorded_path(recorded_dir, name)
    if path is None:
        return None, 'unknown'
    try:
        if not path.is_file():
            return None, 'missing'
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None, 'unreadable'
    if not isinstance(data, dict) or not isinstance(data.get('rows'), list):
        return None, 'unreadable'

    return data, 'ok'


def recorded_rows(recorded_dir):
    """Rows of the bundled recorded runs that load, and a link to each run's full page."""
    rows, links = [], {}
    for name in RECORDED_SITES:
        data, _ = load_recorded(recorded_dir, name)
        if data is None:
            continue
        for row in data['rows']:
            if isinstance(row, dict):
                rows.append(row)
                links[row.get('site')] = '/recorded/' + name
    return rows, links


def recorded_section(recorded_dir, results_root=None):
    """The recorded runs side by side. Carries its own label; the page itself has no banner."""
    head = ('<div class="card recorded" id="recorded"><h2>' + RECORDED_HEADING % esc(RECORDED_DATE) + '</h2>'
            + RECORDED_INTRO % esc(RECORDED_DATE))
    rows, links = recorded_rows(recorded_dir)
    if not rows:
        return head + '<p class="muted">No recorded runs are bundled with this copy.</p></div>'
    # The scorecard was built from the bundled recorded files, so it is only shown next to those.
    score = scorecard_line() if Path(recorded_dir).resolve() == RECORDED_DIR.resolve() else ''
    sheet = ('<p><a href="/comparison">Open the supplier comparison sheet</a>: the same three runs as short '
             'summaries, with each fact\'s quote and source folded under its cell.</p>')
    return (head + sheet + comparison_table(rows, links, home=True, read_on=RECORDED_DATE) + score + later_runs_note(rows, results_root)
            + '<p>Each supplier name opens that run in full: the page text it read, its plan, trace and saved '
              'result.</p></div>')


def usage_rows(caps, totals, run_calls=None):
    left = live_run.remaining(caps, totals)
    per_run = live_run.run_limits(caps, totals, run_calls) if run_calls else None
    names = (('calls', 'Model calls'), ('input', 'Input tokens'), ('output', 'Output tokens'))
    return ''.join('<tr><th>%s</th><td>%s</td><td>%s</td><td>%s</td>%s</tr>'
                   % (label, format(totals[k], ','), format(caps[k], ','), format(left[k], ','),
                      '<td>%s</td>' % format(per_run[k], ',') if per_run else '')
                   for k, label in names)


def live_overview(live):
    """What a live run is, and the live runs saved so far."""
    parts = ['<p><strong>Real public pages, read only when you confirm.</strong> Three kinds of evidence are kept '
             'apart in Scott: the <em>sample-data demo</em> uses invented pages; the <em>recorded live runs</em> are '
             'the saved runs of %s; a <em>live run you start yourself</em> reads one approved supplier page now, '
             'uses model calls from a shared, capped budget, and is saved under '
             '<code>eval-results/live-&lt;date&gt;/</code>.</p>' % esc(RECORDED_DATE)]
    runs = live_run.saved_runs(live.results_root)
    if runs:
        parts.append('<h2>Saved live runs</h2><p>Newest first.</p><ul>' + ''.join(
            '<li><a href="/live/%s/%s">%s, started %s</a></li>' % (esc(folder), esc(stem), esc(site), esc(stamp))
            for folder, stem, site, stamp in runs) + '</ul>')
    else:
        parts.append('<p class="muted">No live runs have been saved yet.</p>')
    return ''.join(parts)


def live_summary(live):
    """One line for the home page; the reasons, budget and environment details live on /live."""
    problems, totals = ([], None) if live is None else live_run.readiness(
        live.env, live.ledger_path, need_browser=live.browser_factory is None)
    if live is None:
        line = 'Live runs are switched off in this server instance.'
    # Too few calls left for one run is refused on /live before any call, so it is unavailable here too.
    elif totals is not None and live_run.remaining(live.caps, totals)['calls'] < live_run.UI_RUN_CALL_CAP:
        line = 'Live runs are unavailable now. The shared budget has too few model calls left for one run.'
    elif problems:
        line = 'Live runs are unavailable now.'
    else:
        line = 'A live run of one approved supplier page can be started by hand after review.'
    return ('<div class="card live" id="live"><h2>Live runs</h2><p>%s <a href="/live">See the status, the shared '
            'budget and saved live runs</a>.</p></div>' % esc(line))


def home_body(recorded_dir=None, live=None, results_root=None):
    return ''.join([
        '<h1>Scott</h1>',
        '<p class="lead">Scott reads a few approved supplier pages and reports only what it can quote. Every price '
        'and delivery term comes with the sentence it was read from and the page it came from; anything it could not '
        'find stays marked as not found, and it never picks a cheapest supplier.</p>',
        '<p><a href="/try"><strong>Try it on sample data</strong></a> · <a href="/about">How it works</a></p>',
        recorded_section(recorded_dir, results_root),
        live_summary(live),
    ])


class PickerRefused(ValueError):
    """A picker value outside the configured lists: the form was not sent by this page."""


def picker_question(form):
    """(question, domain, gaps) from picker choices. Unknown or repeated values raise PickerRefused."""
    def one(key):
        values = form.get(key, [])
        if len(values) != 1:
            raise PickerRefused(key)
        return values[0]

    def many(key, allowed):
        values = form.get(key, [])
        if any(v not in allowed for v in values) or len(set(values)) != len(values):
            raise PickerRefused(key)
        return [a for a in allowed if a in values]  # configuration order, whatever order was sent

    domain = one('domain')
    if domain == 'supplier':
        product = one('product')
        if product not in PICK_PRODUCTS:
            raise PickerRefused('product')
        sites = many('site', list(PICK_SITES))
        if not sites:
            return None, domain, ['Pick at least one supplier.']
        return SUPPLIER_TEMPLATE % (PICK_PRODUCTS[product], ' and '.join(PICK_SITES[x] for x in sites)), domain, []
    if domain == 'provider':
        models = many('model', PICK_MODELS)
        if not models:
            return None, domain, ['Pick at least one model.']
        return PROVIDER_TEMPLATE % ' and '.join(models), domain, []
    raise PickerRefused('domain')


def picker_forms():
    fields = ', '.join(plain.field_label(f).lower() for f in supplier.WORKFLOW['research_fields'])
    sites = ''.join(
        '<label class="opt"><input type="checkbox" name="site" value="%s" checked> %s <code>%s</code></label>'
        % (esc(s['name']), esc(PICK_SITES[s['name']]), esc(host_of(s['url']))) for s in supplier.WORKFLOW['sites'])
    models = ''.join(
        '<label class="opt"><input type="checkbox" name="model" value="%s"%s> %s</label>'
        % (esc(m), ' checked' if i == 0 else '', esc(m)) for i, m in enumerate(PICK_MODELS))
    return ''.join([
        '<div class="grid" id="pick">',
        '<form class="card pick" method="post" action="', RUN_PATH, '">',
        '<input type="hidden" name="form" value="picker"><input type="hidden" name="domain" value="supplier">',
        '<h2>Supplier: 16kg flour</h2>',
        '<fieldset><legend>Product</legend>',
        '<label class="opt"><input type="radio" name="product" value="strong_white" checked> Strong white bread '
        'flour, 16kg</label>',
        '<label class="opt"><input type="radio" name="product" value="wholemeal"> Wholemeal bread flour, 16kg '
        '(Wessex only)</label></fieldset>',
        '<fieldset><legend>Suppliers</legend>', sites, '</fieldset>',
        '<p class="muted">Details collected: ', esc(fields), '.</p>',
        '<button type="submit">Run on sample data</button></form>',
        '<form class="card pick" method="post" action="', RUN_PATH, '">',
        '<input type="hidden" name="form" value="picker"><input type="hidden" name="domain" value="provider">',
        '<h2>API pricing</h2>', PROVIDER_NOTE_HTML,
        '<fieldset><legend>Models</legend>', models, '</fieldset>',
        '<p class="muted">Pricing context: Standard, USD, uncached input and output, per million tokens.</p>',
        '<button type="submit">Run on sample data</button></form>',
        '</div>',
    ])


def try_body(prefill='', domain='auto'):
    def option(key):
        sel = ' selected' if key == domain else ''
        return '<option value="%s"%s>%s</option>' % (esc(key), sel, esc(DOMAINS[key]))

    examples = []
    for key, question in EXAMPLES.items():
        parsed = plan_question(question)
        examples.append(
            '<li><a href="/try?%s#ask" data-example="%s" data-domain="%s">Use %s example</a>: '
            '<q>%s</q><br><span class="muted">Planner reads it as: %s</span>%s</li>'
            % (esc(urlencode({'example': key})), esc(question), esc(key), esc(DOMAINS[key].split(' (')[0]),
               esc(question), esc(describe_plan(parsed)), PROVIDER_NOTE_HTML if key == 'provider' else ''))

    sw, pw = supplier.WORKFLOW, provider.WORKFLOW
    supplier_sites = ''.join(
        '<li><strong>%s</strong> <code>%s</code>%s</li>'
        % (esc(s['name']), esc(host_of(s['url'])),
           ' (pack option ' + esc(s['variant_option']) + ')' if s.get('variant_option') else '')
        for s in sw['sites'])
    wholemeal = supplier.WHOLEMEAL_SITE
    site_host = {s['name']: host_of(s['url']) for s in pw['sites']}
    provider_sites = ''.join(
        '<li><strong>%s</strong> from %s <code>%s</code></li>' % (esc(m), esc(name), esc(site_host[name]))
        for m, name in provider.SUPPORTED_MODELS)

    def required(wf):
        return ''.join('<li><code>%s</code>: %s</li>' % (esc(f), esc(wf['fields'][f])) for f in wf['required'])

    return ''.join([
        '<h1>Try Scott on sample data</h1>',
        '<p class="lead">Pick what to compare. Scott turns your choices into one narrow question, plans it, and runs '
        'it on invented sample pages: no website is contacted and no model is called.</p>',
        picker_forms(),
        '<details class="own" id="own"', ' open' if prefill else '', '>',
        '<summary>Type your own question (advanced)</summary>',
        '<p class="muted">Free text goes through the same planner. Anything outside the supported list below comes '
        'back for clarification instead of being guessed.</p>',
        '<div class="card" id="ask"><form class="run" method="post" action="', RUN_PATH, '">',
        '<label for="question">Your question</label>',
        '<textarea id="question" name="question" maxlength="', str(MAX_QUESTION), '" required>', esc(prefill),
        '</textarea><div class="row"><div><label for="domain">Domain</label>',
        '<select id="domain" name="domain">', ''.join(option(k) for k in DOMAINS), '</select></div>',
        '<div><button type="submit">Run sample-data demo</button></div></div>',
        '<p class="muted">This runs on built-in sample data only. No website is contacted. The domain selector '
        'is a cross-check: the planner decides from the question text, and a mismatch stops the run.</p>',
        '</form></div>',
        '<h3>Example questions</h3><ul>', ''.join(examples),
        '<li><a href="/try?%s#ask" data-example="%s" data-domain="auto">See a question Scott refuses</a>: <q>%s</q>'
        '</li>' % (esc(urlencode({'q': REFUSED_EXAMPLE})), esc(REFUSED_EXAMPLE), esc(REFUSED_EXAMPLE)),
        '</ul></details>',
        '<h2>Supported entities</h2>',
        '<p class="muted">Read from <code>scout/workflows/supplier.py</code> and '
        '<code>scout/workflows/provider.py</code>, the same lists the planner reads. Anything else in a question '
        'is sent back for clarification.</p>',
        '<div class="grid"><div class="card"><h3>Supplier: 16kg flour</h3>',
        '<p>Strong white bread flour, approved sources:</p><ul>', supplier_sites, '</ul>',
        '<p>Wholemeal bread flour, one approved source only:</p><ul><li><strong>', esc(wholemeal['name']),
        '</strong> <code>', esc(host_of(wholemeal['url'])), '</code></li></ul>',
        '<p>Required fields:</p><ul>', required(sw), '</ul></div>',
        '<div class="card"><h3>API provider: token pricing</h3>', PROVIDER_NOTE_HTML,
        '<p>Exact model names the planner accepts:</p><ul>',
        provider_sites, '</ul><p>Required fields:</p><ul>', required(pw), '</ul></div></div>',
        '<p><a href="/about">How Scott works, and what is and is not proven</a></p>',
    ])


PROVIDER_NOTE_HTML = ('<p class="muted">API pricing is sample data only here: this interface never runs it live. '
                      'Earlier provider runs from the command line were partial or failed; see How it works.</p>')


def about_body():
    return """
<h1>How Scott works</h1>
<p class="lead">Scott is a private research prototype. It answers a narrow kind of question by following a fixed
plan, quoting what it read, and leaving gaps visible. It does not buy anything, deploy anything or hold accounts.</p>

<h2>What it is for</h2>
<p>Comparing suppliers means reading several product and delivery pages and keeping track of which terms apply to
what. A search engine leaves that reading to you; a chatbot tends to answer whether or not it read the facts.
Scott sits in between: it reads only approved pages, keeps the exact sentence behind every value, and reports what
it could not find as not found. It is a bounded, checkable comparison, not a buying adviser.</p>

<h2>How a run works</h2>
<ol>
<li>A narrow question becomes a fixed plan: which approved pages, which details, and hard limits on pages, steps and
model calls. Anything outside the supported list stops here and asks for clarification.</li>
<li>A read-only browser opens the approved page and may read one more page on the same site: a delivery link it
finds, or else the supplier's configured delivery page. If the page does not give the price for the pack, the
store's own product data is read in code (no model call, and not counted as a page). That data states no currency,
so Scott adds none.</li>
<li>A model is asked for each detail with the exact quote it came from. A value is accepted only if its quote is
found word for word in the page text; anything else is rejected and recorded.</li>
<li>Details are checked: missing parts stay missing, different values are both kept, and a delivery basis or order
condition counts only when quoted together with its charge.</li>
<li>The result is a table of quoted values with their sources, plus why the run stopped where it did.</li>
</ol>

<h2>Safeguards</h2>
<ul>
<li>Only approved pages on approved sites; reading only (no forms, purchases, sign-ins or redirects off site).</li>
<li>Instructions written on a web page cannot add tools, sites or steps.</li>
<li>Every live model call is counted in a shared ledger with hard caps, checked before any call is sent.</li>
<li>Sample data, recorded runs and live runs are always labelled and never mixed on one page.</li>
</ul>

<h2>Status words in a comparison</h2>
<dl>
<dt>Quoted</dt><dd>Every requested detail was found word for word on the page read. It does not mean the value is
correct or current.</dd>
<dt>Partly quoted</dt><dd>Some details were quoted; the missing ones are listed.</dd>
<dt>Not found</dt><dd>Nothing for this detail was quoted. It stays unknown; nothing is guessed.</dd>
<dt>Values disagree</dt><dd>Two different amounts were quoted for the same thing. Both are kept; no winner is
chosen.</dd>
<dt>Needs review</dt><dd>The same detail was quoted with different numbers (such as two pack sizes). A person must
judge whether they mean the same thing.</dd>
<dt>Unrecognised</dt><dd>A status this page does not know, shown exactly as recorded.</dd>
</dl>
<p class="muted">Each word is shown next to the engine's own status code.</p>
<p>The <a href="/scorecard">scorecard</a> shows how the saved live runs compare with a reference file of supplier
facts: what agrees, what is partly there, and what was missed and why.</p>

<h2>What is proven, offline only</h2>

<ul>
<li>The offline test suite covers the engine's regression tests, this interface, and guards for the defects found
in the first real supplier run (27 October 2026). Run it with <code>python3 -m pytest -q</code>; this page does not
re-run any of it.</li>
<li>Two synthetic demos, one supplier question and one API pricing question, run end to end on labelled sample
data, with no API key and no network.</li>
<li>Four defects from that real run are reproduced offline from its preserved quotes, and guards for them now pass
those tests: a delivery rate is no longer matched to its basis inside a longer number; an unmatched basis is reported
missing; a page already read is not read again after a redirect, through variant data or through a repeated link; and
different wording of the same fact is labelled as variation, not as a conflict.</li>
<li>An order condition (such as a minimum order value) is accepted for a delivery charge only when it is quoted together
with that charge; otherwise it is reported missing. On the captured text of one supplier page, this links the
free-delivery threshold to the standard charge.</li>
<li>When the same detail is quoted twice with different numbers (for example two delivery times), Scott keeps both,
keeps the result marked for human review, and says that a person must judge whether they mean the same thing. It
does not claim they agree or that they conflict.</li>
</ul>

<h2>What is not proven</h2>
<ul>
<li>Live extraction from real websites is unreliable. Apart from a few single recorded runs and any live runs
started from this interface, none of the checks above has been used live,
and single runs cannot show reliability.</li>
<li>The first real supplier run, on 27 October 2026, ended incomplete.</li>
<li>Extraction can still take a delivery basis from the wrong line of a page. The guard now catches this and
reports the basis as missing; it does not make extraction right.</li>
<li>On the captured supplier page, some explicitly stated conditions (regional surcharges, the exception to free
delivery) were not extracted in the 27 October live run.</li>
<li>The clearer wording for order conditions has not been tried with a live model.</li>
<li>Scott makes no cheapest-buy or best-model verdicts. This is deliberate: it reports evidence, not a winner.</li>
</ul>

<h2>Recorded live runs</h2>

<p>Scott has been run live and read-only, one bounded run per configured supplier page, extracting evidence with a
quote and source for every accepted claim and keeping unknowns as unknowns.
Recordings of such runs are unavailable in this copy: when saved result files are present, the <a href="/#recorded">comparison page</a> replays them side by
side from files, together with the page text each run read, and opening them fetches nothing. Scott's own call caps
cannot by themselves prove billing status.</p>
<p>Still unproven: whether order conditions are extracted live; how complete the coverage of delivery conditions
is; and live extraction from API pricing pages, which has not been tried with the current engine or from this
interface (earlier v2/v3 provider runs were one known-row result plus partial or failed extractions). These are single runs, not evidence of
reliability. Scott makes no cheapest-buy or best-model verdicts.</p>

<h2>Live runs you start yourself</h2>
<p>This interface can start a live run of one approved supplier page, but only as a deliberate manual action by the
person running the server. The API key must be in the server's own environment (it is never typed into, shown on
or saved by any page), the free-project binding must be confirmed, Playwright must be installed, and you must tick a
confirmation box. Each run reads real public pages and uses model calls from one shared ledger,
<code>eval-results/live-ledger.jsonl</code>, which <code>scripts/run_supplier_live.py</code> also uses. The caps are
cumulative and never reset by themselves: only a person replacing the ledger file with an empty one resets them, and a missing ledger refuses every run. A run that would pass
them is refused before any call. Local caps cannot prove billing status. Results are saved under
<code>eval-results/live-&lt;date&gt;/</code>, with their own banner, and are never mixed with the sample demo or the
recorded runs. A single live run is not evidence of reliability, and Scott makes no cheapest-buy or best-model
verdicts.</p>
<p>Apart from a live run you start and confirm yourself, this interface makes no network calls: recorded runs are
replayed from saved files.</p>

<h2>How to read a result</h2>
<dl>
<dt>Plan</dt><dd>The fixed steps, sources and limits chosen before anything runs.</dd>
<dt>Summary</dt><dd>One row per source: values, status words, what is missing, and every quote with its
source.</dd>
<dt>Technical details</dt><dd>The plan, limits, the engine's own report, gaps, trace and the saved result, folded
away on each result page.</dd>
<dt>Unknown</dt><dd>A detail Scott did not find. It stays unknown; nothing is guessed.</dd>
<dt>Conflict</dt><dd>Two different amounts for the same thing. Both are kept; no winner is chosen.</dd>
<dt>Variation</dt><dd>The same detail quoted with different wording or coverage. Both are kept and labelled. If the
numbers differ, a person must judge whether they mean the same thing; Scott does not decide either way.</dd>

<dt>Trace</dt><dd>Every step the run took, in order.</dd>
<dt>Needs clarification</dt><dd>The question was outside what the planner supports, so nothing ran.</dd>
</dl>
<p class="muted">Every sample-data demo result in this interface is synthetic text labelled
"DEMO FIXTURE", read from invented pages on reserved <code>.example</code> addresses, with deliberately
artificial prices (such as £12.34). It is not current prices or live data, and no real supplier or provider
page is contacted. Recorded live runs and any live runs you start are labelled separately above.</p>
"""


def picker_gap_body(gaps):
    return ('<h1>Needs clarification</h1><p class="lead">Nothing was planned or run.</p><ul class="gaps">'
            + ''.join('<li>' + esc(g) + '</li>' for g in gaps) + '</ul><p><a href="/try">Back to Try it</a></p>')


def question_label(built):
    return 'Question built from your choices' if built else 'Your question'


def clarification_body(question, domain, plan, ui_gaps, built=False):
    planner_gaps = ''.join('<li>' + esc(g) + '</li>' for g in plan.gaps)
    body = [
        '<h1>Needs clarification</h1>',
        '<p class="lead">Nothing was run. The question could not be turned into a supported plan, so no sources '
        'were read and no default was substituted.</p>',
        '<div class="card"><dl><dt>', question_label(built), '</dt><dd>',
        esc(question) or '<span class="muted">(empty)</span>',
        '</dd><dt>Domain selector</dt><dd>', esc(DOMAINS[domain]), '</dd><dt>Planner read it as</dt><dd>',
        esc(describe_plan(plan)), '</dd></dl></div>',
        '<h2>Gaps from the plan</h2>',
    ]
    if plan.gaps:
        body += ['<ul class="gaps">', planner_gaps, '</ul>',
                 '<details><summary>As printed by the command-line tool</summary><pre>',
                 esc(json.dumps(plan.gaps, indent=2)), '</pre></details>']
    else:
        body.append('<p class="muted">The planner reported no gaps for this question.</p>')
    if ui_gaps:
        body += ['<h2>Gaps from this page</h2><ul class="gaps">',
                 ''.join('<li>' + esc(g) + '</li>' for g in ui_gaps), '</ul>']
    body += ['<p><a href="/try?', esc(urlencode({'q': question, 'domain': domain})),
             '#ask">Edit the question</a> or <a href="/try">try an example</a>.</p>']
    return ''.join(body)



def result_body(question, domain, plan, r, saved_to=None, recorded=False, live=None, built=False):
    label = 'live run' if live is not None else ('recorded live run' if recorded else 'sample data')
    replay = recorded or live is not None
    sites = plan.workflow.get('sites', [])
    if replay:
        site_head = '<th>Source</th><th>URL</th><th>Model or option</th>'
        site_rows = ''.join('<tr><td>%s</td><td><code>%s</code></td><td>%s</td></tr>'
                            % (esc(s.get('name')), esc(s.get('url')), esc(s.get('model') or s.get('variant_option') or ''))
                            for s in sites)
    else:
        site_head = '<th>Invented sample source</th><th>Sample address used</th><th>Model or option</th>'
        site_rows = ''.join('<tr><td>%s</td><td><code>%s</code></td><td>%s</td></tr>'
                            % (esc(s.get('name')), esc(s.get('url')), esc(s.get('model') or s.get('variant_option') or ''))
                            for s in sites)
    budgets = ''.join('<dt>%s</dt><dd>%s</dd>' % (esc(k.replace('_', ' ')), esc(v)) for k, v in plan.budgets.items())
    steps = ''.join('<li>' + esc(s) + '</li>' for s in plan.steps)
    entities = ''.join('<dt>%s</dt><dd>%s</dd>' % (esc(k), esc(', '.join(v) if isinstance(v, list) else v))
                       for k, v in plan.entities.items() if k != 'requested_context')

    readable = r.get('readable')
    stale_note = ''
    if readable and replay:
        read_on = live.get('date', '') if live is not None else RECORDED_DATE
        rebuilt = replay_readable(r, read_on)
        if rebuilt is not None:
            if OLD_FIXED_DATE in readable and read_on not in OLD_FIXED_DATE:
                stale_note = ('<p class="muted">The saved file is shown unchanged below. Its own report text says '
                              '"27 October 2026" because an older engine version printed that date on every '
                              'report; the pages were read on %s.</p>' % esc(read_on))
            readable = rebuilt
    if readable:
        comparison = render_markdown(readable) + (
            '<details><summary>Raw Markdown (%s)</summary><pre>%s</pre></details>' % (label, esc(readable)))
    else:
        comparison = '<p class="muted">The engine returned no readable comparison for this run.</p>'

    issues = []
    for g in plan.gaps:
        issues.append(('plan', 'gaps', g))
    issues += collect_issues(r)
    if issues:
        issue_html = ('<div class="scroll"><table><thead><tr><th>Where</th><th>Kind</th><th>Detail</th></tr></thead><tbody>'
                      + ''.join('<tr><td><code>%s</code></td><td>%s</td><td>%s</td></tr>'
                                % (esc(where), esc(kind.replace('_', ' ')), esc(v if isinstance(v, str) else as_json(v)))

                                for where, kind, v in issues)
                      + '</tbody></table></div>')
    else:
        issue_html = ('<p class="muted">No gap, unknown or conflict entries were recorded in the result object. '
                      'Check the status column of the comparison as well.</p>')

    trace_items = []
    for x in r.get('trace', []):
        if isinstance(x, dict) and 'tool' in x:  # execute_plan entries: {'step', 'tool', 'why', ...}
            rest = {k: v for k, v in x.items() if k not in ('step', 'tool')}
            trace_items.append('<li><strong>%s</strong> <code>%s</code></li>' % (esc(x['tool']), esc(as_json(rest))))
        else:
            trace_items.append('<li><code>%s</code></li>' % esc(x if isinstance(x, str) else str(x)))
    trace_html = ('<details><summary>Show all %d steps</summary><ol class="trace">%s</ol></details>'
                  % (len(trace_items), ''.join(trace_items))) if trace_items else \
        '<p class="muted">The trace is empty.</p>'

    if live is not None:
        rows = r.get('rows') or []
        error = r.get('error') if isinstance(r.get('error'), dict) else None
        head = ['<h1>Live run (started from this interface)</h1>',
                '<div class="card live"><dl><dt>Question</dt><dd>', esc(question), '</dd>',
                '<dt>Page</dt><dd>', esc(live.get('site')), ' <code>', esc(live.get('url')), '</code></dd>',
                '<dt>Started</dt><dd>', esc(live.get('started')), '</dd>',
                '<dt>Finished</dt><dd>', esc(live.get('finished')), '</dd>',
                '<dt>State</dt><dd><span class="state">', esc(r.get('state')), '</span> ',
                '<span class="muted">(as reported by the engine)</span></dd>',
                ('<dt>Error</dt><dd><code>%s: %s</code></dd>' % (esc(error.get('type')), esc(error.get('message')))
                 if error else ''),
                '<dt>Model calls</dt><dd>', esc(r.get('generation_calls', 'none recorded')), ' (capped at ',
                esc(live.get('run_call_cap', live.get('planned_model_calls'))), ' for this run; the engine could use up to ',
                esc(live.get('planned_model_calls')), ')</dd>',
                '<dt>Tool steps</dt><dd>', esc(r.get('tool_steps', 'none recorded')), '</dd>',
                ''.join('<dt>Stop reason (%s)</dt><dd><code>%s</code></dd>' % (esc(row.get('site')), esc(row.get('stop_reason')))
                        for row in rows if isinstance(row, dict)),
                ''.join('<dt>Error (%s)</dt><dd><code>%s</code></dd>' % (esc(row.get('site')), esc(as_json(row.get('errors'))))
                        for row in rows if isinstance(row, dict) and row.get('errors')),
                ''.join('<dt>Ended (%s)</dt><dd>Stopped by a budget check (<code>%s</code>). What was read before the '
                        'stop is kept below; everything not yet read stays unknown.</dd>'
                        % (esc(row.get('site')), esc(row.get('stop_reason')))
                        for row in rows if isinstance(row, dict)
                        and row.get('stop_reason') in ('provider_budget_stop', 'generation_budget', 'tool_budget')),
                '<dt>Shared usage before</dt><dd>', esc(as_json(live.get('usage_before'))), '</dd>',
                '<dt>Shared usage after</dt><dd>', esc(as_json(live.get('usage_after'))), '</dd>',
                '</dl></div>']
        sources_note = 'This is the approved public page this run was allowed to read. Viewing this page fetches nothing.'
    elif recorded:
        rows = r.get('rows') or []
        head = ['<h1>Recorded live run (read-only playback)</h1>',
                '<div class="card recorded"><dl><dt>Question</dt><dd>', esc(question), '</dd>',
                '<dt>Recorded</dt><dd>', esc(RECORDED_DATE), ': this run read public pages over the network</dd>',
                '<dt>This page</dt><dd>Replays the saved result from a local file; nothing is fetched</dd>',
                '<dt>State</dt><dd><span class="state">', esc(r.get('state')), '</span> ',
                '<span class="muted">(as reported by the engine)</span></dd>',
                '<dt>Model calls</dt><dd>', esc(r.get('generation_calls', 'not recorded')), '</dd>',
                '<dt>Tool steps</dt><dd>', esc(r.get('tool_steps', 'not recorded')), '</dd>',
                ''.join('<dt>Stop reason (%s)</dt><dd><code>%s</code></dd>' % (esc(row.get('site')), esc(row.get('stop_reason')))
                        for row in rows if isinstance(row, dict)),
                '</dl></div>']
        sources_note = ('These are the public pages this run was allowed to read. Opening this playback contacts '
                        'none of them.')
    else:
        head = ['<h1>Result (sample data)</h1>',
                '<div class="card"><dl><dt>', question_label(built), '</dt><dd>', esc(question), '</dd>',
                '<dt>Domain selector</dt><dd>', esc(DOMAINS[domain]), '</dd>',
                '<dt>State</dt><dd><span class="state">', esc(r.get('state')), '</span> ',
                '<span class="muted">(as reported by the engine)</span></dd>',
                '<dt>Network used</dt><dd>No</dd>',
                ('<dt>Saved to</dt><dd><code>' + esc(saved_to) + '</code></dd>') if saved_to else '',
                '</dl></div>']

        sources_note = ('Nothing real is contacted in this sample-data demo. Each source is replaced by an invented '
                        'page on a reserved <code>.example</code> address, which cannot be a real website. The '
                        'right-hand column lists the real page a live run would read instead.')

    rows = [x for x in r.get('rows') or [] if isinstance(x, dict)]
    table_date = live.get('date') if live is not None else (RECORDED_DATE if recorded else None)
    summary = (['<h2>Summary (%s)</h2>' % label,
                comparison_table(rows, read_on=table_date, sample=not replay)] if rows else [])
    # Evidence first (summary, sources, page text); the engine's internals are folded into one section.
    return ''.join(head + summary + [
        '<h2>Sources</h2><p class="muted">', sources_note, '</p>',
        '<div class="scroll"><table><thead><tr>', site_head, '</tr></thead><tbody>',
        site_rows, '</tbody></table></div>',
        page_texts_html(r) if replay else '',
        '<details class="tech"><summary>Technical details (plan, budgets, engine report, gaps, trace, raw result)'
        '</summary>',
        '<h2>Plan</h2>',
        '<dl><dt>domain</dt><dd>', esc(plan.domain), '</dd><dt>plan state</dt><dd>', esc(plan.state), '</dd>',
        entities, '</dl>',
        '<h3>Budgets</h3><dl>', budgets, '<dt>max pages</dt><dd>', esc(plan.workflow.get('max_pages')), '</dd></dl>',
        '<h3>Steps</h3><ol>', steps, '</ol>',
        '<h2>Engine report (%s)</h2>' % label, comparison,
        '<h2>Gaps, unknowns and conflicts (%s)</h2>' % (label if replay else 'sample data run'), issue_html,
        '<h2>Trace (%s)</h2>' % (label if replay else 'sample data run'), trace_html,
        stale_note,
        '<details><summary>Full result object (%s)</summary><pre>' % label, esc(as_json(r, indent=2)),
        '</pre></details>',
        '</details>',
        '<p><a href="/try">Ask another question</a> · <a href="/">Back to the comparison</a></p>',
    ])


def page_texts_html(r):
    """The text each recorded run actually read, exactly as saved in its result file."""
    blocks = []
    for row in r.get('rows') or []:
        if not isinstance(row, dict):
            continue
        for item in row.get('page_texts') or []:
            text = str(item.get('text', ''))
            blocks.append('<details><summary>%s: <code>%s</code> (%d characters)</summary><pre>%s</pre></details>'
                          % (esc(row.get('site')), esc(item.get('source_url')), len(text), esc(text)))

    if not blocks:
        return ('<h2>Page text Scott read</h2><p class="muted">This recorded result holds no saved page text.</p>')
    return ('<h2>Page text Scott read</h2><p class="muted">Saved with the run, shown unchanged. The model was sent at '
            'most the first %s characters of each text, and every accepted quote had to appear verbatim in the '
            'page text.</p>' % format(PROMPT_TEXT_LIMIT, ',') + ''.join(blocks))


def plan_view(r):
    plan = r.get('plan') if isinstance(r.get('plan'), dict) else {}
    return plan, SimpleNamespace(domain=plan.get('domain'), state=plan.get('state', ''), gaps=plan.get('gaps') or [],
                                 entities=plan.get('entities') or {}, workflow=plan.get('workflow') or {},
                                 steps=plan.get('steps') or [], budgets=plan.get('budgets') or {})


STATUS_CLASS = {plain.QUOTED: 'ok', plain.PARTLY: 'part', plain.NOT_FOUND: 'no', plain.DISAGREE: 'disagree',
                plain.REVIEW: 'review', plain.UNRECOGNISED: 'unrec', plain.OFFER_OK: 'ok', plain.OFFER_OUT: 'part',
                plain.PRICE_UNCONFIRMED: 'review'}


def offer_screen_line(field, read_on=None, sample=False):
    """Which screen the price result comes from, keeping the saved run's own date and status apart from any
    re-screen done now. A saved run without an offer record is re-screened from its text evidence only;
    today's structured records are never applied to it."""
    offer = plain.offer_decision(field)
    when = ('sample data, not read from any website' if sample else
            ('read %s' % read_on) if read_on else 'read date not recorded')
    if offer is not None and offer.get('state') == 'no_structured_offer':
        return ('No structured offer record was captured in this run (%s; %s), so the price is not confirmed '
                '(screen %s).' % ('; '.join(str(x) for x in offer.get('reasons') or []) or 'no reason recorded',
                                  when, offer.get('screen')))
    if offer is not None:
        return ('Price checked against structured offer records by screen %s when the page was read (%s).'
                % (offer.get('screen'), offer.get('read_date') or 'read date not recorded'))
    code = (field or {}).get('status') if isinstance(field, dict) else None
    return ('As saved (%s): engine status %s. Re-screened %s by screen %s from this run\'s text evidence only: no '
            'structured offer record was captured, so the price is not confirmed.'
            % (when, code or 'not recorded', datetime.now(timezone.utc).date().isoformat(), plain.OFFER_SCREEN))


def safe_source_link(url):
    """A link only for an http(s) address with a host; anything else is shown as escaped text, never a link."""
    text = str(url or '')
    parsed = urlparse(text)
    if parsed.scheme in ('http', 'https') and parsed.netloc:
        return ('<a class="src" href="%s" rel="noreferrer noopener">%s</a> <code>%s</code>'
                % (esc(text), esc(parsed.netloc), esc(text)))
    return '<code>%s</code> (not a web address, so not linked)' % esc(text or 'source not recorded')


def offer_evidence(field):
    """An evidence disclosure for the structured offer records behind a price (matched or disagreeing): each
    record's amount, currency, origin, availability, SKU and variant, with the page it was read from. Built
    from the saved decision only; opening it fetches nothing."""
    offer = plain.offer_decision(field)
    records = [r for r in (offer or {}).get('records') or [] if isinstance(r, dict)]
    if not records:
        return ''
    items = []
    for r in records:
        bits = ['%s %s' % (r.get('currency') or '(no currency)', r.get('amount')),
                'from ' + str(plain.ORIGIN_LABELS.get(r.get('origin'), r.get('origin'))),
                {True: 'in stock', False: 'out of stock'}.get(r.get('availability'), 'availability not stated')]
        bits += ['%s %s' % (k, r.get(key)) for k, key in (('pack label', 'label'), ('SKU', 'sku'),
                                                          ('variant', 'variant_id')) if r.get(key)]
        items.append('<li>%s<br><span class="src">read from: %s</span></li>'
                     % (esc('; '.join(str(b) for b in bits)), safe_source_link(r.get('page_url'))))
    return ('<details class="ev"><summary>Evidence: structured offer records (%d)</summary><ul>%s</ul>'
            '<p class="cell-n">Read from the page markup when the page was read; opening this fetches nothing.</p>'
            '</details>' % (len(records), ''.join(items)))


def price_view(field, read_on=None, sample=False, packs=None):
    """(status, primary state, visible lines, short context) for one price cell, in plain words.

    One primary state comes first: a matched offer (with stock and tax beside it), out of stock, a disagreement
    between price records (no price chosen, every amount listed), or a price that is not confirmed. Engine
    codes and the screen's own explanation belong in the cell's disclosure, not here."""
    status = plain.field_status(field, 'product_price')
    head = plain.price_headline(field)
    offer = plain.offer_decision(field)
    when = ('Sample data' if sample else 'Read %s' % (offer.get('read_date') if offer and offer.get('read_date')
                                                      else read_on or 'date not recorded'))
    if head is not None:
        lines = ['%s: %s' % (label, ' / '.join(v)) for label, v in plain.cell_values('product_price', field)]
        if head.get('valid_until'):
            lines.append('offer valid until: %s (as stated by the offer)' % head['valid_until'])
        return status, status['word'], lines, when + '.'
    if offer is not None and offer.get('state') == 'conflicting':
        what = ', '.join(offer.get('conflicts') or []) or 'price'
        lines = ['%s %s from %s, %s' % (r.get('currency') or '(no currency)', r.get('amount'),
                                        plain.ORIGIN_LABELS.get(r.get('origin'), r.get('origin')),
                                        {True: 'in stock', False: 'out of stock'}.get(r.get('availability'),
                                                                                      'availability not stated'))
                 for r in offer.get('records') or []]
        return status, 'Price records disagree (%s): no price chosen' % what, lines, when + '.'
    if not plain.quotes(field) and (offer is None or offer.get('state') == 'no_structured_offer'):
        return status, 'Not found', [], when + '. No price was quoted and no structured offer record was captured.'
    lines = ['Pack size: unresolved (%s)' % ' vs '.join(packs)] if packs else []
    if status['word'] == plain.DISAGREE:
        amounts = list(dict.fromkeys(' '.join(c.get('value', '').split())
                                     for c in ((field or {}).get('facts') or {}).get('amount') or []))
        lines.append('Quoted amounts differ (%s); none is chosen' % ' / '.join(amounts))
    if offer is None or offer.get('state') == 'no_structured_offer':
        context = when + '. No structured offer record in this run.'
    else:
        reasons = [str(r) for r in offer.get('reasons') or []]
        context = when + '. ' + ((reasons[-1][0].upper() + reasons[-1][1:] + '.') if reasons else '')
    return status, '16kg price not confirmed', lines, context.strip()


def store_data_notes(row):
    """Plain notes from a newer run's store product data: availability, and that it gives no currency."""
    store = row.get('store_data') if isinstance(row.get('store_data'), dict) else {}
    notes = []
    for item in store.get('packs') or []:
        state = {True: 'marked available', False: 'marked not available'}.get(item.get('available'),
                                                                             'availability not stated')
        notes.append('Store data: %s %s.' % (item.get('pack'), state))
    if store.get('files'):
        notes.append('Prices from store data carry no currency; any currency shown was quoted on the page.')
    return notes


def unresolved_pack(name, field):
    """Sorted pack sizes when a price field quotes more than one, as the comparison sheet treats them; else None."""
    if name != 'product_price':
        return None
    facts = (field or {}).get('facts') or {}
    packs = {str(c.get('value', '')) for c in facts.get('variant') or [] if isinstance(c, dict) and c.get('value')}
    return sorted(packs) if len(packs) > 1 else None


def price_cell(field, row=None, home=False, read_on=None, sample=False):
    """The price cell: primary state, the lines a reader needs beside it, one short date line, then the
    engine status, screen explanation and notes in a disclosure, then the quotes."""
    packs = unresolved_pack('product_price', field) if home else None
    status, primary, lines, context = price_view(field, read_on, sample, packs)
    warn_cls = '' if plain.price_headline(field) is not None else ' cmp-warn'
    parts = ['<p class="cell-v price-state%s"><strong>%s</strong></p>' % (warn_cls, esc(primary))]
    parts += ['<p class="cell-v">%s</p>' % esc(line) for line in lines]
    parts.append('<p class="cell-n">%s</p>' % esc(context))
    code = esc(status['code']).replace('_', '_<wbr>')
    how = ['<p><span class="st %s" title="Engine status: %s">%s</span> <span class="code">%s</span></p>'
           % (STATUS_CLASS[status['word']], esc(status['code']), esc(status['word']), code),
           '<p>%s</p>' % esc(offer_screen_line(field, read_on, sample))]
    if status['missing']:
        how.append('<p>Not quoted in page text: %s</p>' % esc(', '.join(status['missing'])))
    how += ['<p>%s</p>' % esc(n[0].upper() + n[1:]) for n in status['notes']]
    if row:
        how += ['<p>%s</p>' % esc(n) for n in store_data_notes(row)]
    parts.append(offer_evidence(field))  # supporting evidence first, then quotes, then how it was checked
    found = plain.quotes(field)
    if found:
        warn = ('<p class="cell-n">The run quoted more than one pack size (%s), so the amount below is not '
                'confirmed as the 16kg sack price.</p>' % esc(' vs '.join(packs))) if packs else ''
        parts.append('<details><summary>Quotes (%d)</summary>%s<ul>%s</ul></details>' % (len(found), warn, ''.join(
            '<li>%s: <q>%s</q><br><span class="src">source: <code>%s</code></span></li>'
            % (esc(label), esc(quote), esc(url)) for label, value, quote, url in found)))
    parts.append('<details class="how"><summary>How this was checked</summary>%s</details>' % ''.join(how))
    return '<td data-label="%s">' % esc(plain.field_label('product_price')) + ''.join(parts) + '</td>'


def delivery_context_html(field, row=None):
    """Visible by default: ambiguity notes beside the shown delivery claims, and every qualifier kept out of the
    headline under one labelled list. Built from saved claims only (plain.delivery_context); nothing is hidden in a
    closed disclosure and nothing is described as applying to the charge."""
    row_fields = (row or {}).get('atomic_fields') if isinstance(row, dict) else None
    ctx = plain.delivery_context(field, row_fields)
    lines = plain.delivery_context_lines(ctx)
    out = ['<p class="cell-n ctx-note">%s</p>' % esc(t) for kind, t in lines if kind == 'note']
    repeated = plain.repeated_amount_note(field)
    if repeated:
        out.append('<p class="cell-n ctx-note">%s</p>' % esc(repeated))
    separate = [t for kind, t in lines if kind == 'separate']
    if separate:
        heading = ('Stated separately from the shown charge (not shown as part of it):' if ctx.get('charges') else
                   'Delivery details quoted, with no delivery charge amount extracted:')
        out.append('<div class="ctx-sep"><p class="cell-n"><strong>%s</strong></p><ul>%s</ul></div>'
                   % (esc(heading), ''.join('<li>%s</li>' % esc(t) for t in separate)))
    return ''.join(out)


def comparison_cell(name, field, row=None, home=False, read_on=None, sample=False):
    if name == 'product_price':
        return price_cell(field, row, home, read_on, sample)
    row_fields = row.get('atomic_fields') if isinstance(row, dict) else None
    status = plain.field_status(field, name, row_fields)
    packs = unresolved_pack(name, field) if home else None
    shown = plain.cell_values(name, field, row_fields)
    parts = []
    if packs:  # an unresolved pack size gets no headline amount; the amount stays in the quotes below
        hidden = (plain.claim_label('amount'), plain.claim_label('variant'))
        shown = [(label, values) for label, values in shown if label not in hidden]
        parts += ['<p class="cell-v cmp-warn"><strong>16kg price not confirmed</strong></p>',
                  '<p class="cell-v">Pack size: unresolved (%s)</p>' % esc(' vs '.join(packs))]
    parts += ['<p class="cell-v">%s: %s</p>' % (esc(label), esc(' / '.join(values))) for label, values in shown]
    if name == 'delivery_charge':
        parts.append(delivery_context_html(field, row))
    code = esc(status['code']).replace('_', '_<wbr>') if home else esc(status['code'])  # home: break at '_'
    parts.append('<span class="st %s" title="Engine status: %s">%s</span> <span class="code">%s</span>'
                 % (STATUS_CLASS[status['word']], esc(status['code']), esc(status['word']), code))
    if status['missing']:
        parts.append('<p class="cell-n">Missing: %s</p>' % esc(', '.join(status['missing'])))
    parts += ['<p class="cell-n">%s</p>' % esc(n[0].upper() + n[1:]) for n in status['notes']]
    if name == 'product_price' and row:
        parts += ['<p class="cell-n">%s</p>' % esc(n) for n in store_data_notes(row)]
    found = plain.quotes(field)
    if found:
        warn = ('<p class="cell-n">The run quoted more than one pack size (%s), so the amount below is not '
                'confirmed as the 16kg sack price.</p>' % esc(' vs '.join(packs))) if packs else ''
        parts.append('<details><summary>Quotes (%d)</summary>%s<ul>%s</ul></details>' % (len(found), warn, ''.join(
            '<li>%s: <q>%s</q><br><span class="src">source: <code>%s</code></span></li>'
            % (esc(label), esc(quote), esc(url)) for label, value, quote, url in found)))
    return '<td data-label="%s">' % esc(plain.field_label(name)) + ''.join(parts) + '</td>'


def comparison_table(rows, site_links=None, home=False, read_on=None, sample=False):
    """One row per source, one column per field: values, a plain status word with its engine code,
    what is missing, and every quote with its source. Followed by how each source's run ended.

    home: the home page's recorded table. A price read with more than one pack size is worded as on the
    comparison sheet (not confirmed, amount kept in the quotes), and the table fits its card."""
    rows = [x for x in rows if isinstance(x, dict)]
    fields = list(dict.fromkeys(f for row in rows for f in row.get('atomic_fields') or {}))
    if not rows or not fields:
        return '<p class="muted">This result holds no source rows to compare.</p>'
    unconfirmed = sum(1 for row in rows if plain.quoted((row.get('atomic_fields') or {}).get('product_price'))
                      and plain.price_headline((row.get('atomic_fields') or {}).get('product_price')) is None)
    cover = ' · '.join('%s quoted: %d of %d' % c + (' (%d with the 16kg price not confirmed)' % unconfirmed
                                                    if unconfirmed and c[0] == plain.field_label('product_price')
                                                    else '') for c in plain.coverage(rows, fields))
    head = ''.join('<th>%s</th>' % esc(plain.field_label(f)) for f in fields)
    body = []
    for row in rows:
        site = str(row.get('site'))
        name = ('<a href="%s">%s</a>' % (esc(site_links[site]), esc(site))
                if site_links and site in site_links else esc(site))
        body.append('<tr><th scope="row">%s</th>%s</tr>' % (name, ''.join(
            comparison_cell(f, (row.get('atomic_fields') or {}).get(f), row, home, read_on, sample)
            for f in fields)))
    ended = ''.join('<li><strong>%s</strong>: %s</li>' % (esc(row.get('site')), esc(plain.how_it_ended(row)))
                    for row in rows)
    return ''.join([
        '<p class="coverage">', esc(cover), '</p>',
        '<div class="scroll%s"><table class="cmp"><thead><tr><th>Source</th>' % (' home-cmp' if home else ''),
        head, '</tr></thead><tbody>',
        ''.join(body), '</tbody></table></div>',
        '<p class="muted">"Quoted" means the words were found on the page that was read; it does not mean the '
        'value is correct or current. A price is shown as matched only when a structured offer record on the '
        'page ties it to the configured product, SKU and pack; that is not a judgement of suitability. Every '
        'quote and its source are listed in the cell. No cheapest-buy or best-model verdict is given.</p>',
        '<h3>How each run ended</h3><ul>', ended, '</ul>'])


def _cmp_price_cell(field, row=None):
    """(status word, html) for a recorded run's price on the comparison sheet: the primary state first, the
    lines a reader needs beside it, one short date line; status codes and review notes in one disclosure."""
    field = field if isinstance(field, dict) else {}
    facts = field.get('facts') if isinstance(field.get('facts'), dict) else {}
    variants = {str(c.get('value', '')) for c in facts.get('variant') or [] if isinstance(c, dict) and c.get('value')}
    packs = sorted(variants) if len(variants) > 1 else None
    status, primary, lines, context = price_view(field, RECORDED_DATE, packs=packs)
    head = plain.price_headline(field)
    word = status['word'] if (plain.quotes(field) or plain.offer_decision(field)) else 'Not found'
    flag = {plain.DISAGREE: ' - amounts differ', plain.REVIEW: ' - numbers differ'}.get(status['word'], '')
    if not flag and any(n.startswith('wording differs') for n in status['notes']):
        flag = ' - wording varies'
    items = []
    for i, line in enumerate(lines):
        if head is not None and i == 0:
            items.append('<li><strong>%s %s</strong></li>' % (esc(head['currency']), esc(head['amount'])))
        else:
            items.append('<li>%s</li>' % esc(line))
    parts = ['<p class="cmp-status cmp-primary%s"><strong>%s</strong></p>'
             % ('' if head is not None else ' cmp-warn', esc(primary))]
    if items:
        parts.append('<ul class="cmp-claims">' + ''.join(items) + '</ul>')
    parts.append('<p class="cmp-ctx">%s</p>' % esc(context))
    how = ['<p class="cmp-status">%s%s <span class="code">%s</span></p>'
           % (esc(word), esc(flag), esc(field.get('status') or 'not recorded')),
           '<p>%s</p>' % esc(offer_screen_line(field, RECORDED_DATE))]
    if field.get('missing'):
        how.append('<p>Not quoted in page text: %s</p>' % esc(', '.join(
            CLAIM_LABELS.get(m, m.replace('_', ' ')) for m in field['missing'])))
    how += ['<p>%s</p>' % esc(n[0].upper() + n[1:] + '.') for n in status['notes']]
    if row:
        how += ['<p>%s</p>' % esc(n) for n in store_data_notes(row)]
        if 'store_data' not in row and any(urlparse(c.get('source_url', '')).path.endswith(('.js', '.json'))
                                           for claims in facts.values() for c in claims or [] if isinstance(c, dict)):
            how.append("<p>Some quotes come from the store's product data file. In this run Scott's own formatting "
                       "added the £ to those lines; the data itself states no currency (fixed 2 November 2026).</p>")
    how_html = '<details class="cmp-rev"><summary>How this was checked</summary>%s</details>' % ''.join(how)
    parts.append(offer_evidence(field))  # supporting evidence first, then quotes, then how it was checked
    unique = list(dict.fromkeys((k, ' '.join(str(c.get('value', '')).split()), c.get('quote', ''), c.get('source_url', ''))
                                for k, claims in facts.items() for c in claims or [] if isinstance(c, dict)))
    if unique:
        warn = ('<p class="cmp-review">The run quoted more than one pack size (%s), so the amount below is not '
                'confirmed as the 16kg sack price.</p>' % esc(' vs '.join(packs))) if packs else ''
        ev = ''.join('<li>%s: %s - &quot;%s&quot;%s</li>' % (
            esc(CLAIM_LABELS.get(key, key)), esc(value), esc(quote),
            (' <a class="src" href="%s" title="Supplier page as read %s">%s</a>'
             % (esc(url), esc(RECORDED_DATE), esc(host_of(url)))) if url else '')
            for key, value, quote, url in unique)
        parts.append('<details class="cmp-ev"><summary>Quotes and sources (%d)</summary>%s<ul>%s</ul></details>'
                     % (len(unique), warn, ev))
    parts.append(how_html)
    return word, ''.join(parts)


def _cmp_cell(field_key, field, row=None):
    """(status word, html) for one supplier x field cell of the comparison sheet: short summary first;
    quotes, missing lists and review notes collapsed.

    Material uncertainty stays beside the value (status words, unresolved-pack-size headline); repetitive
    inventories and technical caveats sit behind disclosures with the full evidence. As in the plain view,
    a claim the engine lists as missing (such as a basis not quoted with its charge) is kept in the quotes
    but never made a summary line, and the flag and notes come from scout.plain ('two' and '2' are one number).
    """
    if field_key == 'product_price':
        return _cmp_price_cell(field, row)
    field = field if isinstance(field, dict) else {}
    facts = field.get('facts') if isinstance(field.get('facts'), dict) else {}
    missing = field.get('missing') or []
    row_fields = row.get('atomic_fields') if isinstance(row, dict) else None
    ctx = plain.delivery_context(field, row_fields) if field_key == 'delivery_charge' else {}
    groups, summary = {}, {}
    for key, claims in facts.items():
        label = CLAIM_LABELS.get(key, key.replace('_', ' '))
        for item in claims or []:
            if not isinstance(item, dict):
                continue
            value = str(item.get('value', ''))
            group = groups.setdefault((label, value), [label, value, []])
            sig = (item.get('quote', ''), item.get('source_url', ''))
            if sig not in group[2]:
                group[2].append(sig)
            # currency: the amounts already carry the symbol; it stays in the quotes
            if key != 'currency' and key not in missing and value.strip() and \
                    plain.headline_claim_shown(field_key, key, item, ctx):  # others are listed below, visibly
                values = summary.setdefault(label, [])
                if ' '.join(value.split()) not in values:
                    values.append(' '.join(value.split()))
    variants = {str(c.get('value', '')) for c in facts.get('variant') or [] if isinstance(c, dict) and c.get('value')}
    pack_unresolved = field_key == 'product_price' and len(variants) > 1
    head = plain.price_headline(field) if field_key == 'product_price' else None
    if field_key == 'product_price':  # only a confirmed offer record gives a bold price; quotes stay below
        summary.pop('Amount', None)
        summary.pop('Pack size', None)
        if head is not None:
            summary = {label: values for label, values in plain.cell_values('product_price', field)[1:]}
    amounts = ['<li><strong>%s</strong></li>' % esc(v) for v in summary.pop('Amount', [])]
    if head is not None:
        amounts = ['<li><strong>%s %s</strong></li>' % (esc(head['currency']), esc(head['amount']))]
    others = ['<li>%s: %s</li>' % (esc(label), esc(' / '.join(values))) for label, values in summary.items()]
    if pack_unresolved and head is None:
        amounts.insert(0, '<li class="cmp-warn"><strong>16kg price not confirmed</strong></li>'
                          '<li>Pack size: unresolved (%s)</li>' % esc(' vs '.join(sorted(variants))))
    elif field_key == 'product_price' and head is None and groups:
        amounts.insert(0, '<li class="cmp-warn"><strong>16kg price not confirmed</strong></li>')
    parts = []
    if amounts or others:
        parts.append('<ul class="cmp-claims">' + ''.join(amounts + others) + '</ul>')
    elif field_key == 'delivery_charge' and ctx.get('claims'):
        pass  # its quoted details are listed below under their own truthful heading
    elif groups:
        parts.append('<p class="cmp-none">Only details not linked to this field were quoted.</p>')
    else:
        parts.append('<p class="cmp-none">Not found in this recorded run.</p>')
    word = STATUS_WORDS.get(field.get('status', ''), (field.get('status') or 'unknown').replace('_', ' '))
    if not groups and word == 'Partly found':
        word = 'Not found'
    plain_status = plain.field_status(field, field_key, row_fields)
    if field_key == 'product_price' and (groups or plain.offer_decision(field) is not None):
        word = plain_status['word']  # the offer record decides, with or without quotes; quotes alone never read as Found
    context_review = (field_key == 'delivery_charge' and plain_status['word'] == plain.REVIEW
                      and plain.field_status(field)['word'] == plain.QUOTED)
    if context_review and word == 'Found':
        word = 'Needs review'  # only a Found field is lowered; every other word stays as it was
    flag = ''
    if context_review:
        flag = ' - context to check'
    elif field.get('status') == 'possible_numeric_disagreement':
        flag = ' - conflicting numbers'
    elif plain_status['word'] == plain.DISAGREE:
        flag = ' - amounts differ'
    elif plain_status['word'] == plain.REVIEW:
        flag = ' - numbers differ'
    elif any(n.startswith('wording differs') for n in plain_status['notes']):
        flag = ' - wording varies'
    parts.append('<p class="cmp-status">%s%s</p>' % (esc(word), esc(flag)))
    if field_key == 'delivery_charge':
        parts.append(delivery_context_html(field, row))
    if field_key == 'product_price':
        parts.append('<p class="cmp-review">%s</p>' % esc(offer_screen_line(field, RECORDED_DATE)))
    evidence = sum(len(ev) for _, _, ev in groups.values())
    if evidence:
        ev_lis = []
        for label, value, ev in groups.values():
            for quote, url in ev:
                link = (' <a class="src" href="%s" title="Supplier page as read %s">%s</a>'
                        % (esc(url), esc(RECORDED_DATE), esc(host_of(url)))) if url else ''
                ev_lis.append('<li>%s: %s - &quot;%s&quot;%s</li>' % (esc(label), esc(value), esc(quote), link))
        warn = ('<p class="cmp-review">The run quoted more than one pack size (%s), so the amount below is not '
                'confirmed as the 16kg sack price.</p>' % esc(' vs '.join(sorted(variants)))) if pack_unresolved else ''
        parts.append('<details class="cmp-ev"><summary>Quotes and sources (%d)</summary>%s<ul>' % (evidence, warn)
                     + ''.join(ev_lis) + '</ul></details>')
    if missing:  # beside a matched offer, missing page-text quotes are not a missing price
        parts.append('<details class="cmp-miss"><summary>%s (%d)</summary><p>%s</p></details>'
                     % ('Not quoted in page text' if head is not None else 'Not found', len(missing),
                        esc(', '.join(CLAIM_LABELS.get(m, m.replace('_', ' ')) for m in missing))))
    notes = [n[0].upper() + n[1:] + '.' for n in plain_status['notes']]
    if field_key == 'product_price' and row:
        notes += store_data_notes(row)
    # Runs saved before 2 November formatted store data with a £ of Scott's own; the data states no currency.
    if row is not None and 'store_data' not in row and any(
            urlparse(url).path.endswith(('.js', '.json')) for _, _, ev in groups.values() for _, url in ev):
        notes.append("Some quotes come from the store's product data file. In this run Scott's own formatting "
                     "added the £ to those lines; the data itself states no currency (fixed 2 November 2026).")
    if notes:
        parts.append('<details class="cmp-rev"><summary>Review notes (%d)</summary>' % len(notes)
                     + ''.join('<p>%s</p>' % esc(n) for n in notes) + '</details>')
    return word, ''.join(parts)


def comparison_body(recorded_dir):
    """Recorded supplier runs side by side: compact table on wide screens, supplier cards on narrow ones."""
    intro = ('<h1>Supplier comparison</h1><p class="lead">One bounded run per supplier page, recorded %s and '
             'replayed from saved files: opening this page fetches nothing, and the prices are as read that day, '
             'not current. Each cell is a short summary; the exact words, source links, missing items and review '
             'notes sit behind its disclosures. Anything a run did not find is marked, not filled in.</p>'
             % esc(RECORDED_DATE))
    loaded = [(name, *load_recorded(recorded_dir, name)) for name in RECORDED_SITES]
    available = [(name, data) for name, data, reason in loaded if data is not None]
    if not available:
        return (intro + '<p class="muted">No recorded runs are bundled with this copy, so there is nothing to '
                'compare yet.</p>')
    head = ''.join('<th>%s</th>' % esc(FIELD_LABELS.get(f, f.replace('_', ' '))) for f in FIELD_ORDER)
    rows_html, cards_html, counts = [], [], {'found': 0, 'partly': 0, 'none': 0}
    for name, data, reason in loaded:
        label = SITE_LABELS.get(name, name.replace('_', ' '))
        if data is None:
            rows_html.append('<tr><th>%s</th><td colspan="%d" class="muted">No recorded run for this supplier '
                             'is bundled with this copy.</td></tr>' % (esc(label), len(FIELD_ORDER)))
            cards_html.append('<div class="card cmp-card"><h3>%s</h3><p class="muted">No recorded run for this '
                              'supplier is bundled with this copy.</p></div>' % esc(label))
            continue
        row = next((r for r in data['rows'] if isinstance(r, dict)), {})
        atomic = row.get('atomic_fields') or {}
        cells = []
        for field_key in FIELD_ORDER:
            word, cell = _cmp_cell(field_key, atomic.get(field_key), row)
            counts['found' if word in ('Found', plain.OFFER_OK) else 'none' if word == 'Not found' else 'partly'] += 1
            cells.append((field_key, cell))
        notes = []
        if row.get('stop_reason'):
            notes.append('run stopped at %s' % str(row['stop_reason']).replace('_', ' '))
        if row.get('review_required'):
            notes.append('review required')
        visited = row.get('pages_visited') or []
        sub = '<small>%s%s</small>' % (esc(host_of(visited[0])) if visited else esc(name),
                                       ('; ' + esc('; '.join(notes))) if notes else '')
        rows_html.append('<tr><th>%s%s</th>%s</tr>'
                         % (esc(label), sub, ''.join('<td>%s</td>' % c for _, c in cells)))
        sections = ''.join('<div class="cmp-field"><h4>%s</h4>%s</div>'
                           % (esc(FIELD_LABELS.get(k, k.replace('_', ' '))), c) for k, c in cells)
        cards_html.append('<div class="card cmp-card"><h3>%s %s</h3>%s</div>' % (esc(label), sub, sections))
    total = sum(counts.values())
    coverage = ('<p>Coverage: %d of %d recorded supplier pages are bundled; across the %d cells '
                '(%d fields x %d runs): %d found, %d partly found, %d not found. Counts cover only these recorded '
                'runs, not the suppliers\' websites as a whole.</p>'
                % (len(available), len(RECORDED_SITES), total, len(FIELD_ORDER), len(available),
                   counts['found'], counts['partly'], counts['none']))
    foot = ('<p class="muted">Sources are the real supplier pages as read %s; follow a link to check the page '
            'today, which may have changed. Every run stayed within its budget and is marked review-required. '
            'What a run did not find is final output for that bounded run, not a promise of further research, '
            'and no cheapest or best-supplier verdict is made.</p>' % esc(RECORDED_DATE))
    table = ('<div class="scroll cmp-wrap"><table class="cmp"><thead><tr><th>Supplier</th>' + head +
             '</tr></thead><tbody>' + ''.join(rows_html) + '</tbody></table></div>')
    cards = '<div class="cmp-cards">' + ''.join(cards_html) + '</div>'
    return intro + coverage + table + cards + foot


def later_runs_note(rows, results_root):
    """Saved live runs of the same pages started later from this interface, and whether they agree.
    Without a results folder (live runs switched off) nothing is listed and no file is opened."""
    if results_root is None:
        return ''
    items = []
    by_site = {row.get('site'): row for row in rows}
    for folder, stem, site, stamp in live_run.saved_runs(results_root):
        if site not in by_site:
            continue
        try:
            data = json.loads((Path(results_root) / folder / (stem + '-result.json'))
                              .read_text(encoding='utf-8'))
            later = next(x for x in data['rows'] if isinstance(x, dict) and x.get('site') == site)
        except (OSError, ValueError, KeyError, TypeError, StopIteration):
            continue
        when = live_run.long_date(datetime.strptime(stamp, '%Y%m%dT%H%M%SZ'))
        verdict = ('quoted the same price and delivery-charge amounts' if plain.same_core_facts(by_site[site], later)
                   else 'did not quote the same price and delivery-charge amounts; compare them yourself')
        items.append('<li><a href="/live/%s/%s">%s, live run started %s UTC</a>: %s.</li>'
                     % (esc(folder), esc(stem), esc(site), esc(when), esc(verdict)))
    if not items:
        return ''
    return ('<h3>Later live runs of the same pages</h3><p class="muted">Started by hand from this interface. A '
            'matching re-run is a small consistency check, not evidence of reliability.</p><ul>'
            + ''.join(items) + '</ul>')


OUTCOME_CLASS = {scorecard.AGREES: 'ok', scorecard.PARTLY: 'part', scorecard.DISAGREES: 'disagree',
                 scorecard.MISSED: 'no', scorecard.UNRESOLVED: 'review', scorecard.NOT_IN_REFERENCE: 'review',
                 scorecard.NOT_SCORED: 'unrec'}


def latest_scorecard():
    """The newest scorecard-<date>.json, or None. Read from local disk only."""
    files = sorted(SCORECARD_DIR.glob('scorecard-*.json'))
    try:
        return json.loads(files[-1].read_text(encoding='utf-8')) if files else None
    except (OSError, ValueError):
        return None


def scorecard_changed_inputs(data):
    """Inputs whose bytes no longer match the hashes the scorecard was built from."""
    changed = []
    for item in data.get('inputs') or []:
        path = ROOT / item.get('path', '')
        try:
            if hashlib.sha256(path.read_bytes()).hexdigest() != item.get('sha256'):
                changed.append(item.get('path'))
        except OSError:
            changed.append(item.get('path'))
    return changed


def totals_text(totals):
    shown = [o for o in scorecard.OUTCOMES if totals.get(o) or o in (scorecard.DISAGREES, scorecard.MISSED)]
    words = {scorecard.AGREES: 'agree', scorecard.PARTLY: 'partly agree', scorecard.DISAGREES: 'disagree'}
    return ', '.join('%d %s' % (totals.get(o, 0), words.get(o, o.lower())) for o in shown)


def scorecard_line():
    data = latest_scorecard()
    run = next((r for r in (data or {}).get('runs') or [] if r.get('id') == 'recorded-30oct'), None)
    if run is None:
        return ''
    return ('<p class="coverage">Checked against reference facts recorded on %s: %s. '
            '<a href="/scorecard">See the scorecard</a>.</p>'
            % (esc(long_iso_date((data.get('reference') or {}).get('seeded_at'))), esc(totals_text(run['totals']))))


def long_iso_date(value):
    try:
        return live_run.long_date(datetime.strptime(str(value), '%Y-%m-%d'))
    except ValueError:
        return 'an unrecorded date'


def component_label(name):
    """Rubric part names in words: GBP_3_85 -> £3.85, rendered_GBP_21_30 -> rendered-page £21.30."""
    m = re.fullmatch(r'(?:(\w+?)_)?GBP_(\d+)(?:_(\d+))?', name)
    if m:
        amount = '£' + m.group(2) + ('.' + m.group(3) if m.group(3) else '')
        kind = {'rendered': 'rendered-page ', 'json': 'store-data '}.get(m.group(1) or '', '')
        return kind + amount
    return name.replace('_', ' ')


def scorecard_reason(cell):
    reason = cell.get('reason') or ''
    if reason == scorecard.PAGE_NOT_READ:
        return 'Its page (%s) was not read in this run.' % urlparse(cell.get('reference_source') or '').path
    if reason == scorecard.READ_NOT_EXTRACTED:
        return 'Its page was read, but nothing was quoted for it.'
    if reason == 'quoted_but_unchecked':
        return 'Scott quoted this, but the reference has no checked value; a person should check it.'
    if reason.startswith('matched_readings:'):
        readings = [component_label(n) for n in reason.split(':', 1)[1].split(',') if n]
        return ('The reference itself holds conflicting readings. Scott quoted the %s reading.'
                % ' and '.join(readings) if readings else 'The reference itself holds conflicting readings.')
    return ''


def scorecard_run_links(run):
    links = []
    for path in run.get('files') or []:
        parts = Path(path).parts
        stem = Path(path).name[:-len('-result.json')]
        if len(parts) >= 2 and parts[-2] == RECORDED_DIR.name and stem in RECORDED_SITES:
            links.append('<a href="/recorded/%s">%s</a>' % (esc(stem), esc(stem)))
        elif len(parts) >= 2:
            links.append('<a href="/live/%s/%s">%s</a>' % (esc(parts[-2]), esc(stem), esc(stem)))
    return ' · '.join(links)


def scorecard_body(data):
    if data is None:
        return ('<h1>Scorecard</h1><p class="lead">No scorecard is bundled with this copy. Build one offline with '
                '<code>python3 scripts/build_scorecard.py --output eval-results/scorecard-&lt;date&gt;.json</code>.'
                '</p>')
    ref = data.get('reference') or {}
    header = ' '.join(ref.get('header') or [])
    first = '.'.join(header.split('.')[:2]).strip() + '.' if header else ''
    changed = scorecard_changed_inputs(data)
    parts = [
        '<h1>Scorecard</h1>',
        '<p class="lead">How the saved live runs compare with a reference file of supplier facts. Built offline from '
        'local files by <code>scripts/build_scorecard.py</code>: nothing is fetched and no model is called.</p>',
        '<div class="card"><h2>About the reference</h2><p>The reference values were recorded on %s. The runs below '
        'read the pages later, so a difference could be a real change on the site rather than an error.</p>'
        % esc(long_iso_date(ref.get('seeded_at'))),
        ('<p>The reference file (<code>%s</code>) says of itself: <q>%s</q> It is a reference record, not '
         'independent human verification.</p>' % (esc(ref.get('path')), esc(first))) if first else '',
        '<p>Parts are the strict checklist in <code>%s</code>. Some parts, such as regional surcharges, are not in '
        'what Scott is asked to extract yet, so they cannot be found.</p></div>' % esc(data.get('rubric')),
    ]
    if changed:
        parts.append('<p>This scorecard no longer matches the files it was built from:</p><ul class="gaps">'
                     + ''.join('<li><code>%s</code></li>' % esc(c) for c in changed)
                     + '</ul><p class="muted">Rebuild it offline before relying on it.</p>')
    for run in data.get('runs') or []:
        rows = []
        for cell in run.get('cells') or []:
            outcome = cell.get('outcome')
            quoted = list(dict.fromkeys(' '.join(str(q.get('value', '')).split()) for q in cell.get('quoted') or []))
            notes = []
            if cell.get('components_missing') and outcome in (scorecard.PARTLY, scorecard.DISAGREES,
                                                              scorecard.UNRESOLVED):
                notes.append('Missing parts: ' + ', '.join(component_label(n) for n in cell['components_missing']))
            if scorecard_reason(cell):
                notes.append(scorecard_reason(cell))
            reference = (esc(cell.get('reference_value')) if cell.get('reference_value') not in (None, '')
                         else '<span class="muted">No checked value</span>')
            rows.append(''.join([
                '<tr><th scope="row">', esc(cell.get('site')), '</th>',
                '<td data-label="Detail">', esc(plain.field_label(cell.get('field', ''))), '</td>',
                '<td data-label="Outcome"><span class="st %s">%s</span></td>'
                % (OUTCOME_CLASS.get(outcome, 'unrec'), esc(outcome)),
                '<td data-label="Reference">', reference, '<br><span class="src">source: <code>',
                esc(cell.get('reference_source')), '</code></span></td>',
                '<td data-label="Scott quoted">', esc(' / '.join(quoted)) if quoted else
                '<span class="muted">Nothing</span>', '</td>',
                '<td data-label="Notes">', '<br>'.join(esc(n) for n in notes), '</td></tr>']))
        parts += [
            '<h2>%s, %s</h2>' % (esc(run.get('label')), esc(run.get('read_on'))),
            '<p class="coverage">', esc(totals_text(run.get('totals') or {})), '.</p>',
            '<div class="scroll"><table class="cmp"><thead><tr><th>Supplier</th><th>Detail</th><th>Outcome</th>'
            '<th>Reference</th><th>Scott quoted</th><th>Notes</th></tr></thead><tbody>', ''.join(rows),
            '</tbody></table></div>',
            '<p>Open the run: ', scorecard_run_links(run), '</p>',
        ]
    parts += [
        '<h2>How each cell is scored</h2><dl>',
        '<dt>Agrees</dt><dd>Every part of the checklist appears in what Scott quoted.</dd>',
        '<dt>Partly agrees</dt><dd>The amount (or, for wording-only details, some part) appears; other parts are '
        'missing.</dd>',
        '<dt>Disagrees</dt><dd>Scott quoted something, but not the reference amount.</dd>',
        '<dt>Missed</dt><dd>Scott quoted nothing for this detail. The note says whether the page holding it was '
        'read.</dd>',
        '<dt>Reference unresolved</dt><dd>The reference itself holds conflicting readings; the note says which one '
        'Scott quoted.</dd>',
        '<dt>Not in the reference</dt><dd>The reference has no checked value. Anything Scott quoted is left for a '
        'person to check.</dd></dl>',
        '<p class="muted">', esc(data.get('not_scored', '')), '</p>',
    ]
    return ''.join(parts)


OLD_FIXED_DATE = 'snapshot, 27 October 2026.'  # printed on every report before 2 November 2026


def replay_readable(r, read_on):
    """Rebuild a saved run's comparison from its saved rows, dated when its pages were read.
    The saved file is never changed. Returns None when the rows cannot be rendered."""
    try:
        return render_comparison(r['rows'], 'Scott planned research', as_of=read_on or None)
    except (KeyError, TypeError, AttributeError):
        return None


def recorded_page_body(r):
    plan, view = plan_view(r)
    return result_body(str(r.get('question', plan.get('question', ''))), 'auto', view, r, recorded=True)


def live_banner(meta):
    started = datetime.fromisoformat(meta['started'])
    return '%s%s - real public pages. Started %s UTC.' % (LIVE_BANNER_PREFIX, live_run.long_date(started),
                                                         started.strftime('%Y-%m-%d %H:%M:%S'))


def live_page_body(r):
    plan, view = plan_view(r)
    meta = dict(r['live'])
    meta['date'] = live_run.long_date(datetime.fromisoformat(meta['started']))
    return result_body(str(r.get('question', plan.get('question', ''))), 'auto', view, r, live=meta)



def live_confirm_body(live):
    problems, totals = live_run.readiness(live.env, live.ledger_path, need_browser=live.browser_factory is None)
    planned = None
    choices = []
    for i, site in enumerate(supplier.WORKFLOW['sites']):
        try:
            plan = live_run.plan_for(site['name'])
            planned = max(planned or 0, plan.budgets['generation_calls'])
        except live_run.RunRefused as exc:
            problems.append(str(exc))
        choices.append('<li><label><input type="radio" name="site" value="%s"%s> <strong>%s</strong> <code>%s</code>'
                       '</label></li>' % (esc(site['name']), ' checked' if i == 0 else '', esc(site['name']),
                                          esc(site['url'])))
    cap = live_run.run_call_cap(planned) if planned else None
    no_headroom = None
    if totals is not None and cap:
        no_headroom = live_run.headroom_problem(live.caps, totals, cap)
        if no_headroom:
            problems.append(no_headroom)
    # With too little budget left there is no run to describe, so the per-run column is left out.
    per_run = None if no_headroom else cap
    budget = ('<table><thead><tr><th></th><th>Used so far</th><th>Cumulative cap</th><th>Remaining</th>'
              + ('<th>This run may use up to</th>' if per_run else '') + '</tr></thead><tbody>'
              + usage_rows(live.caps, totals, per_run) + '</tbody></table>') if totals is not None else ''
    if no_headroom:
        cap_note = ('No live run is possible now: the shared budget has %s model call%s left, fewer than the %s one '
                    'run needs, so a run would be refused before any model call. Raising a cap is an owner decision.'
                    % (esc(live_run.remaining(live.caps, totals)['calls']),
                       '' if live_run.remaining(live.caps, totals)['calls'] == 1 else 's', esc(cap)))
    else:
        cap_note = ('This run is capped at %s model calls for this run; the engine could use up to %s model calls '
                    'without the cap. Raising the per-run cap is an owner decision.' % (esc(cap), esc(planned)))
    return ''.join([
        '<h2>Start a live run</h2>',
        '<p class="lead">A live run is a deliberate manual action. Scott opens one approved public supplier page in a '
        'read-only browser, may read at most one more page on the same site (a delivery link it finds, or the '
        "supplier's configured delivery page) and, if the price is missing, the store's product data in code, "
        'sends the page text to the model, '
        'and saves the result under <code>eval-results/live-&lt;date&gt;/</code>. Nothing runs until you confirm '
        'below.</p>',
        '<h2>Budget</h2>', '<p>', cap_note, '</p>', budget,
        '<p class="muted">Usage is read from the shared ledger <code>', esc(Path(live.ledger_path).name), '</code>. The '
        'caps are cumulative across every live run from this interface and from '

        '<code>scripts/run_supplier_live.py</code>. They never reset by themselves: only a person replacing the ledger '
        'file with an empty one resets them, and a missing ledger refuses every run. Unused output reservations '
        'are released after each call. Local caps cannot prove billing status.</p>',
        ('<h2>Not available now</h2><ul class="gaps">' + ''.join('<li>' + esc(p) + '</li>' for p in problems)
         + '</ul>') if problems else '',
        '<form method="post" action="', LIVE_RUN_PATH, '"><h2>Page to read</h2>',
        '<p>Only the approved supplier pages configured in <code>scout/workflows/supplier.py</code> can be read.</p>',
        '<ul>', ''.join(choices), '</ul>',
        '<p><label><input type="checkbox" name="confirm" value="yes" required> I am starting a live run. Scott will '
        'read the real public page selected above, capped at %s model calls for this run from the shared budget; '
        'the engine could use up to %s model calls without the cap.</label></p>' % (esc(cap), esc(planned)),
        '<p><button type="submit"%s>Start live run</button></p>' % (' disabled' if problems else ''),
        '<p class="muted">One run at a time. This page waits until the run ends: nothing runs in the background, '
        'nothing is retried, and the result is saved even if the run fails.</p></form>',
    ])


def live_body(live):
    return '<h1>Live runs</h1>' + live_overview(live) + live_confirm_body(live)


def live_notice_body(title, message):
    return ('<h1>%s</h1><p class="lead">%s</p><p><a href="/live">Back to the live-run page</a> or '
            '<a href="/#live">home</a>.</p>' % (esc(title), esc(message)))


def not_bundled_body(name, reason):
    why = ('could not be read as a saved result' if reason == 'unreadable' else 'is not bundled with this copy')
    return ('<h1>Recorded live run not available</h1><p class="lead">The recorded run for <code>%s</code> %s. '
            'Nothing was fetched instead.</p><p><a href="/#recorded">Back to recorded live runs</a></p>'
            % (esc(name), why))


def error_body(question, exc):
    return ('<h1>The sample-data run stopped</h1><p class="lead">The engine raised an error, so there is no '
            'result to show. Nothing was retried.</p><div class="card"><dl><dt>Your question</dt><dd>%s</dd>'
            '<dt>Error</dt><dd><code>%s: %s</code></dd></dl></div><p><a href="/try">Back</a></p>'
            % (esc(question), esc(type(exc).__name__), esc(exc)))



def write_run(out_dir, r):
    """Mirror the CLI's --output-dir files, one sub-folder per run."""
    d = out_dir / ('run-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    d.mkdir(parents=True, exist_ok=False)
    (d / 'result.json').write_text(json.dumps(r, indent=2, default=str), encoding='utf-8')
    (d / 'comparison.md').write_text('DEMO FIXTURES ONLY, not live facts.\n\n'
                                     + r.get('readable', 'Needs clarification: ' + str(r.get('gaps'))), encoding='utf-8')
    (d / 'trace.md').write_text('# Offline tool trace\n\n' + '\n'.join(str(x) for x in r['trace']), encoding='utf-8')
    return d


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = 'ScoutUI'
    sys_version = ''

    def _send(self, status, content, ctype='text/html; charset=utf-8', nonce=None, headers=()):
        data = content.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        src = "'nonce-%s'" % nonce if nonce else "'none'"
        self.send_header('Content-Security-Policy',
                         "default-src 'none'; style-src %s; script-src %s; form-action 'self'; "
                         "base-uri 'none'; frame-ancestors 'none'" % (src, src))
        for k, v in headers:

            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _page(self, status, title, body, banner=None, script=''):
        nonce = secrets.token_urlsafe(16)
        self._send(status, page(title, body, nonce, banner=banner, script=script), nonce=nonce)

    def _not_found(self):
        self._page(404, 'Not found', '<h1>Not found</h1><p><a href="/">Back to Scott</a></p>')

    def _host_ok(self):
        port = self.server.server_address[1]
        return self.headers.get('Host', '') in ('127.0.0.1:%d' % port, 'localhost:%d' % port)

    def do_GET(self):
        if not self._host_ok():
            return self._send(400, 'Bad Host header', 'text/plain; charset=utf-8')
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        if url.path == '/' and any(k in qs for k in ('example', 'q', 'domain')):
            # Older question links: rebuilt from known keys only, never echoed raw into the header.
            keep = {k: qs[k][0][:MAX_QUESTION] for k in ('example', 'q', 'domain') if k in qs}
            return self._send(303, 'See /try', 'text/plain; charset=utf-8',
                              headers=[('Location', '/try?' + urlencode(keep))])
        if url.path == '/':
            live = getattr(self.server, 'live', None)
            return self._page(200, 'Recorded comparison',
                              home_body(self.server.recorded_dir, live, live.results_root if live else None))
        if url.path == '/compare':
            return self._send(303, 'See /', 'text/plain; charset=utf-8', headers=[('Location', '/')])
        if url.path == '/try':
            example = qs.get('example', [''])[0]
            domain = qs.get('domain', ['auto'])[0]
            prefill = EXAMPLES.get(example, qs.get('q', [''])[0])[:MAX_QUESTION]
            domain = example if example in EXAMPLES else (domain if domain in DOMAINS else 'auto')
            return self._page(200, 'Try it', try_body(prefill, domain), script=HOME_JS)
        if url.path == '/scorecard':
            return self._page(200, 'Scorecard', scorecard_body(latest_scorecard()))
        if url.path == '/about':
            return self._page(200, 'How it works', about_body())
        if url.path == '/m1':
            key = qs.get('s', ['recorded'])[0]
            return self._page(200, 'M1 comparison', m1_view.body(key), banner=m1_view.banner(key))
        if url.path == '/comparison':
            return self._page(200, 'Supplier comparison', comparison_body(self.server.recorded_dir),
                              banner=RECORDED_BANNER)
        if url.path.startswith('/recorded/'):
            name = unquote(url.path[len('/recorded/'):])

            if name not in RECORDED_SITES:
                return self._not_found()
            data, reason = load_recorded(self.server.recorded_dir, name)
            if data is None:
                return self._page(200, 'Recorded live run not available', not_bundled_body(name, reason))
            return self._page(200, 'Recorded live run: ' + name, recorded_page_body(data), banner=RECORDED_BANNER)
        if url.path == '/live':
            live = getattr(self.server, 'live', None)
            if live is None:
                return self._page(200, 'Live runs', '<h1>Live runs</h1><p class="lead">Live runs are switched off in '
                                  'this server instance. Nothing can be started here.</p>')
            return self._page(200, 'Live runs', live_body(live))
        if url.path.startswith('/live/') and url.path != LIVE_RUN_PATH:
            return self._live_result(url.path)
        if url.path in (RUN_PATH, LIVE_RUN_PATH):
            return self._send(405, 'Use the form on the Try it page.', 'text/plain; charset=utf-8',
                              headers=[('Allow', 'POST')])
        return self._not_found()

    def _live_result(self, path):
        live = getattr(self.server, 'live', None)
        parts = path.split('/')
        if (live is None or len(parts) != 4 or not live_run.FOLDER_RE.fullmatch(parts[2])
                or not live_run.STEM_RE.fullmatch(parts[3])
                or live_run.STEM_RE.fullmatch(parts[3]).group(1) not in RECORDED_SITES):
            return self._not_found()
        file = Path(live.results_root) / parts[2] / (parts[3] + '-result.json')
        try:
            data = json.loads(file.read_text(encoding='utf-8')) if file.is_file() else None
            banner = live_banner(data['live']) if isinstance(data, dict) and isinstance(data.get('rows'), list) else None
        except (OSError, ValueError, KeyError, TypeError):
            banner = None
        if banner is None:
            return self._page(200, 'Live run not available', live_notice_body(
                'Live run not available', 'This saved live run is missing or could not be read. Nothing was fetched.'))
        return self._page(200, 'Live run: ' + parts[3], live_page_body(data), banner=banner)


    def _live_run(self, form):
        live = self.server.live
        if form.get('confirm', [''])[0] != 'yes':
            return self._page(400, 'Live run not started', live_notice_body(
                'Live run not started', 'Nothing was run: the confirmation box was not ticked, so no page was read '
                'and no model call was made.'))
        site = form.get('site', [''])[0]
        if site not in RECORDED_SITES:
            return self._page(400, 'Live run not started', live_notice_body(
                'Live run not started', 'Nothing was run: that is not one of the approved supplier pages.'))
        if not RUN_LOCK.acquire(blocking=False):
            return self._page(409, 'Live run not started', live_notice_body(
                'Live run not started', 'Another run is in progress. Nothing was started; try again when it has '
                'finished.'))
        try:
            _, saved = live_run.run_live_site(site, live.env, live.ledger_path, live.results_root, live.caps,
                                              live.browser_factory, live.transport, live.clock)
        except live_run.RunRefused as exc:
            return self._page(409, 'Live run not started', live_notice_body('Live run not started', str(exc)))
        except Exception as exc:  # never echo the message: it is not ours to trust
            self.log_error('live run could not be saved: %s', type(exc).__name__)
            return self._page(500, 'Live run not saved', live_notice_body(
                'Live run not saved', 'The run could not be saved (%s). No earlier result was changed.'
                % type(exc).__name__))
        finally:
            RUN_LOCK.release()
        return self._send(303, 'See the saved live run.', 'text/plain; charset=utf-8',
                          headers=[('Location', '/live/%s/%s' % (saved.parent.name, saved.name[:-len('-result.json')]))])

    def do_POST(self):
        path = urlparse(self.path).path

        if path != RUN_PATH and not (path == LIVE_RUN_PATH and getattr(self.server, 'live', None) is not None):
            return self._not_found()
        if not self._host_ok():
            return self._send(400, 'Bad Host header', 'text/plain; charset=utf-8')
        if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/x-www-form-urlencoded':
            return self._send(415, 'Expected a form submission.', 'text/plain; charset=utf-8')
        try:
            length = int(self.headers.get('Content-Length', ''))
        except ValueError:
            return self._send(411, 'Content-Length required.', 'text/plain; charset=utf-8')
        if length < 0 or length > MAX_BODY:
            return self._send(413, 'Form too large.', 'text/plain; charset=utf-8')
        try:
            form = parse_qs(self.rfile.read(length).decode('utf-8'), keep_blank_values=True)
        except UnicodeDecodeError:
            return self._send(400, 'Form must be UTF-8.', 'text/plain; charset=utf-8')
        if path == LIVE_RUN_PATH:
            return self._live_run(form)
        built = form.get('form', [''])[0] == 'picker'
        if built:
            try:
                question, domain, pick_gaps = picker_question(form)
            except PickerRefused:
                return self._send(400, 'Unknown picker value; nothing was planned or run.',
                                  'text/plain; charset=utf-8')
            if pick_gaps:
                return self._page(200, 'Needs clarification', picker_gap_body(pick_gaps), banner=BANNER)
        else:
            question = form.get('question', [''])[0].strip()
            domain = form.get('domain', ['auto'])[0]
        if domain not in DOMAINS:
            return self._send(400, 'Unknown domain value.', 'text/plain; charset=utf-8')
        if len(question) > MAX_QUESTION:
            return self._page(200, 'Needs clarification',
                              '<h1>Needs clarification</h1><ul class="gaps"><li>Question is longer than %d '
                              'characters; nothing was planned or run.</li></ul><p><a href="/try">Back</a></p>'
                              % MAX_QUESTION, banner=BANNER)

        plan = plan_question(question)
        ui_gaps = []
        if domain != 'auto' and plan.domain != domain:
            ui_gaps.append('Domain selector is set to "%s", but the planner read this question as "%s". The planner '

                           'decides from the question text alone; the selector cannot override it.'
                           % (DOMAINS[domain], DOMAINS.get(plan.domain, 'no supported domain')))
        if plan.state != 'ready' or ui_gaps:
            return self._page(200, 'Needs clarification', clarification_body(question, domain, plan, ui_gaps, built),
                              banner=BANNER)
        try:
            with RUN_LOCK:
                plan = sample_plan(plan)  # reserved .example addresses; real pages are only listed
                r = execute_plan(plan, DemoBrowser(plan), DemoLLM(plan), sample=True)
            r['demo_fixture_only'] = True
            r['network_used'] = False
        except Exception as exc:  # show the failure plainly; never fall back to another source
            self.log_error('demo run failed: %r', exc)
            return self._page(500, 'Run stopped', error_body(question, exc), banner=BANNER)
        saved = None
        out_dir = getattr(self.server, 'output_dir', None)
        if out_dir is not None:
            saved = write_run(out_dir, r).relative_to(Path.cwd().resolve())
        return self._page(200, 'Result (sample data)', result_body(question, domain, plan, r, saved, built=built),
                          banner=BANNER)


def make_server(port=8017, output_dir=None, recorded_dir=RECORDED_DIR, live=None):
    """Build the server bound to 127.0.0.1 only. port=0 picks a free port (used by tests).

    live=None switches live runs off; main() passes default_live_config().
    """
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.output_dir = output_dir
    server.recorded_dir = recorded_dir
    server.live = live
    return server



def default_live_config():
    """The real live wiring: key from this process's environment only, shared ledger, real browser and client."""
    return SimpleNamespace(env=os.environ, ledger_path=live_run.LEDGER_PATH, results_root=live_run.RESULTS_ROOT,
                           caps=live_run.CUMULATIVE_CAPS, browser_factory=None, transport=None, clock=None)


def resolve_output_dir(arg):
    if not arg:
        return None
    cwd = Path.cwd().resolve()
    target = (cwd / arg).resolve()
    if target != cwd and cwd not in target.parents:
        raise SystemExit('--output-dir must be inside the current directory: ' + str(cwd))
    return target


def main(argv=None):
    p = argparse.ArgumentParser(description='Private local web UI for the Scott sample-data demo.')
    p.add_argument('--port', type=int, default=8017)
    p.add_argument('--output-dir', help='optional folder under the current directory for per-run files')
    a = p.parse_args(argv)
    server = make_server(a.port, resolve_output_dir(a.output_dir), live=default_live_config())
    print('Scott sample-data UI on http://127.0.0.1:%d (Ctrl+C to stop)' % server.server_address[1], flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':

    main()

"""Shared live-run wiring for the private local UI and scripts/run_supplier_live.py.

A live run is a deliberate manual action by the person running the server. This
module:
- reads the API key from the process environment only, and never writes it;
- keeps the existing free-project binding gate (SCOUT_VERIFIED_FREE_PROJECT);
- counts model usage in one persistent ledger shared by both entry points, made
  of the records GeminiFree already writes before and after every call, and
  enforces cumulative caps through GeminiFree's own BudgetExceeded;
- saves each UI run under eval-results/live-<YYYYMMDD>/ beside a provenance README.
Playwright and the Gemini client are imported only when a run actually starts.
Local caps cannot prove billing status. A missing or unreadable ledger refuses every run; only a person replacing it with an empty file resets usage.
"""
import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from scout import local_config

ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = ROOT / 'eval-results'
LEDGER_PATH = RESULTS_ROOT / 'live-ledger.jsonl'
CUMULATIVE_CAPS = {'calls': 8, 'input': 12000, 'output': 6000}
MAX_OUTPUT_PER_CALL = 1024  # GeminiFree's default output reservation per call
PER_RUN_INPUT = 20000
UI_RUN_CALL_CAP = 2  # bounds one UI live run (one page needs 1, at most 2 calls); raising it is an owner decision
KNOWN_KINDS = ('reserved', 'response', 'reconciled', 'failed', 'preflight_error')  # what GeminiFree._record writes
FOLDER_RE = re.compile(r'live-\d{8}')
STEM_RE = re.compile(r'([a-z_]+)-(\d{8}T\d{6}Z)')
MONTHS = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
          'November', 'December')

PROVENANCE = """# Live runs started from the local Scott UI

Each *-result.json file in this folder is one live, read-only run that a person started by hand from the
private local UI (scripts/scout_ui.py) on {date} (UTC). Scott read one approved public supplier page from
scout/workflows/supplier.py, sent page text to the model, and saved the bounded result here unchanged.

- Real public pages, as read at the time in each file name: not current prices, not sample data, and not
  the recorded runs in eval-results/live-30oct.
- Model usage is counted in eval-results/{ledger}. The caps are cumulative across every live run and only
  a person replacing that file with an empty one resets them; a missing file refuses every run. Local caps cannot prove billing status.
- No API key is stored in these files.
- A single run is not evidence of reliability. Scott makes no cheapest-buy or best-model verdicts.

Runs:
"""


class LedgerError(RuntimeError):
    pass


class RunRefused(RuntimeError):
    pass


def long_date(moment):
    return '%d %s %d' % (moment.day, MONTHS[moment.month - 1], moment.year)


def key_from(env):
    return (env.get('GEMINI_API_KEY') or '').strip()



def binding_confirmed(env):
    """The run's SCOUT_VERIFIED_FREE_PROJECT matches the project in the local config (scott.local.json)."""
    expected = local_config.verified_project()
    return bool(expected) and env.get('SCOUT_VERIFIED_FREE_PROJECT') == expected


def browser_available():
    return importlib.util.find_spec('playwright') is not None


def ledger_totals(path=None):
    """Calls, input and output tokens used so far, summed from GeminiFree's ledger records.

    Each call writes one 'reserved' record (with the prompt hash) before anything is sent,
    then 'response' and 'reconciled', or 'failed'. A failed call keeps its reservation.
    A missing ledger is an error, never zero usage: a fresh clone or a deleted file must not reset the
    allowance. Starting from zero takes a person creating an empty ledger file on purpose.
    """
    path = Path(path or LEDGER_PATH)
    totals = {'calls': 0, 'input': 0, 'output': 0}
    if not path.is_file():
        raise LedgerError('the file does not exist; a missing ledger is never counted as zero usage')
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeDecodeError):
        raise LedgerError('the file could not be opened as text') from None
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            raise LedgerError('line %d is not valid JSON' % n) from None
        if not isinstance(record, dict):
            raise LedgerError('line %d is not a record' % n)

        if record.get('kind') not in KNOWN_KINDS:  # never count an unrecognised line as zero usage
            raise LedgerError('line %d has an unknown record kind' % n)
        try:
            if record.get('kind') == 'reserved':
                totals['calls'] += 1
                totals['input'] += int(record['input_tokens'])
                totals['output'] += int(record['output_tokens'])
            elif record.get('kind') == 'reconciled':
                totals['input'] -= int(record['released_input'])
                totals['output'] -= int(record['released_output'])
        except (KeyError, TypeError, ValueError):
            raise LedgerError('line %d is missing its token counts' % n) from None
    return totals


def remaining(caps, totals):
    return {k: caps[k] - totals[k] for k in caps}


def readiness(env, ledger_path=None, need_browser=True):
    """Plain-words reasons a live run cannot start now, plus the ledger totals (None if unreadable)."""
    problems = []
    if not key_from(env):
        problems.append('No GEMINI_API_KEY is present in the server environment, so live runs are unavailable.')
    if not binding_confirmed(env):
        problems.append('The free-project binding is not confirmed (SCOUT_VERIFIED_FREE_PROJECT does not match the '
                        'project in the local scott.local.json, or that file is missing), so no model call is '
                        'permitted.')
    if need_browser and not browser_available():
        problems.append('Playwright is not installed in the Python environment running this server, so the '
                        'read-only browser cannot start.')
    try:
        totals = ledger_totals(ledger_path)

    except LedgerError as exc:
        problems.append('The usage ledger (%s) could not be read: %s. Nothing will run until a person inspects it.'
                        % (Path(ledger_path or LEDGER_PATH).name, exc))
        totals = None
    return problems, totals


def configured_site(name):
    from scout.workflows import supplier
    for site in supplier.WORKFLOW['sites']:
        if site['name'] == name:
            return site
    raise RunRefused('That page is not one of the approved supplier pages; nothing was run.')


def plan_for(name):
    """Plan one configured site through the normal planner, and check it targets exactly that URL."""
    from scout.engine.planner import plan_question
    site = configured_site(name)
    plan = plan_question('Compare strong white bread flour 16kg delivery conditions from '
                         + site['name'].replace('_mill', '').replace('_', ' '))
    if plan.state != 'ready' or [s['url'] for s in plan.workflow['sites']] != [site['url']]:
        raise RunRefused('The planner did not produce a plan for exactly the approved page; nothing was run.')
    return plan


def run_call_cap(engine_calls):
    """The model calls one UI run may make: the engine's own budget, capped at UI_RUN_CALL_CAP."""
    return min(engine_calls, UI_RUN_CALL_CAP)


def run_limits(caps, totals, run_calls):

    """What this run may use: its own limits, bounded by what remains under the cumulative caps."""
    left = remaining(caps, totals)
    own = {'calls': run_calls, 'input': PER_RUN_INPUT, 'output': run_calls * MAX_OUTPUT_PER_CALL}
    return {k: max(0, min(left[k], own[k])) for k in own}


def headroom_problem(caps, totals, run_calls):
    """Refuse when the remaining budget is below this run's call cap (or its output reservation)."""
    left = remaining(caps, totals)
    if (left['calls'] < run_calls or left['output'] < run_calls * MAX_OUTPUT_PER_CALL
            or left['input'] <= 0):
        return ("Not enough budget left: the remaining budget (%s model call%s, %s input tokens, %s output tokens) "
                "is below this run's cap of %d model calls (%s output tokens reserved). The caps never reset by "
                "themselves; only a person replacing the ledger file with an empty one resets it."
                % (format(left['calls'], ','), '' if left['calls'] == 1 else 's', format(left['input'], ','),
                   format(left['output'], ','), run_calls, format(run_calls * MAX_OUTPUT_PER_CALL, ',')))
    return None


def make_client(key, ledger_path=None, caps=None, per_run=None, transport=None, totals=None):
    """The real GeminiFree client, writing to the shared ledger, with cumulative usage pre-loaded.

    GeminiFree's own _charge then raises BudgetExceeded before any call that would pass either the
    cumulative caps or this run's own limit. Callers must check binding_confirmed() first.
    """
    from scout.engine.llm import GeminiFree
    ledger_path = Path(ledger_path or LEDGER_PATH)
    caps = caps or CUMULATIVE_CAPS
    totals = ledger_totals(ledger_path) if totals is None else totals
    limit = {k: caps[k] if not per_run else min(caps[k], totals[k] + per_run[k]) for k in caps}
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    client = GeminiFree(key, max_calls=limit['calls'], max_input_tokens=limit['input'],

                        max_output_tokens=limit['output'], max_output_per_call=MAX_OUTPUT_PER_CALL,
                        transport=transport, ledger_path=str(ledger_path), free_project_verified=True)
    client.spent = dict(totals)
    return client


def _readonly_browser():
    from scout.engine.browser import ReadOnlyBrowser  # imports Playwright only here
    return ReadOnlyBrowser()


def _now():
    return datetime.now(timezone.utc)


def _scrub(text, key):
    return text.replace(key, '[redacted]') if key else text


def run_live_site(site_name, env, ledger_path=None, results_root=None, caps=None, browser_factory=None,
                  transport=None, clock=None):
    """One bounded live run of one approved supplier page. Returns (saved result, path).

    Raises RunRefused, before any browser or model call, when the run must not start.
    Any failure after that is saved as an honest result; earlier results are never touched.
    """
    from scout.engine.tool_loop import execute_plan
    ledger_path = Path(ledger_path or LEDGER_PATH)
    results_root = Path(results_root or RESULTS_ROOT)
    caps = caps or CUMULATIVE_CAPS
    clock = clock or _now
    problems, totals = readiness(env, ledger_path, need_browser=browser_factory is None)

    if problems:
        raise RunRefused(' '.join(problems))
    plan = plan_for(site_name)
    planned = plan.budgets['generation_calls']  # the engine's worst case for this plan
    cap = run_call_cap(planned)  # what this UI run is allowed to use
    problem = headroom_problem(caps, totals, cap)
    if problem:
        raise RunRefused(problem)
    key = key_from(env)
    started = clock()
    folder = results_root / ('live-' + started.strftime('%Y%m%d'))
    folder.mkdir(parents=True, exist_ok=True)
    readme = folder / 'README.md'
    if not readme.exists():
        readme.write_text(PROVENANCE.format(date=long_date(started), ledger=ledger_path.name), encoding='utf-8')
    path = folder / ('%s-%s-result.json' % (site_name, started.strftime('%Y%m%dT%H%M%SZ')))
    if path.exists():
        raise RunRefused('A result with this timestamp already exists; nothing was run or overwritten.')
    meta = {'kind': 'live_run', 'site': site_name, 'url': plan.workflow['sites'][0]['url'],
            'started': started.isoformat(), 'planned_model_calls': planned, 'run_call_cap': cap, 'caps': caps,
            'usage_before': totals, 'ledger': ledger_path.name, 'network_used': True}
    browser = None
    try:
        browser = (browser_factory or _readonly_browser)()
        llm = make_client(key, ledger_path, caps, transport=transport, totals=totals,
                          per_run={'calls': cap, 'input': PER_RUN_INPUT, 'output': cap * MAX_OUTPUT_PER_CALL})
        # A BudgetExceeded mid-run is caught by execute_plan, which stops the page with
        # stop_reason 'provider_budget_stop' and returns everything read so far.
        result = execute_plan(plan, browser, llm, as_of=long_date(started))
    except Exception as exc:  # record honestly; no retry
        result = {'state': 'live_run_failed', 'question': plan.question, 'plan': plan.to_dict(), 'rows': [],
                  'trace': [], 'error': {'type': type(exc).__name__, 'message': _scrub(str(exc), key)[:500]}}

    finally:
        if browser is not None and hasattr(browser, 'close'):
            try:
                browser.close()
            except Exception:
                pass
    meta['finished'] = clock().isoformat()
    try:
        meta['usage_after'] = ledger_totals(ledger_path)
    except LedgerError as exc:
        meta['usage_after'] = 'ledger unreadable after the run: %s' % exc
    result['live'] = meta
    text = _scrub(json.dumps(result, indent=1, ensure_ascii=False, default=str), key)
    with open(path, 'x', encoding='utf-8') as f:
        f.write(text)
    with open(readme, 'a', encoding='utf-8') as f:
        f.write('- %s: %s, state %s, file %s\n' % (meta['started'], site_name, result.get('state'), path.name))
    return json.loads(text), path


def saved_runs(results_root=None, limit=30):
    """(folder, stem, site, started-stamp) for saved UI live runs, newest first. Names only; nothing is opened."""
    from scout.workflows import supplier
    names = {s['name'] for s in supplier.WORKFLOW['sites']}
    root = Path(results_root or RESULTS_ROOT)
    found = []
    if root.is_dir():
        for folder in root.iterdir():
            if folder.is_dir() and FOLDER_RE.fullmatch(folder.name):
                for f in folder.glob('*-result.json'):
                    m = STEM_RE.fullmatch(f.name[:-len('-result.json')])
                    if m and m.group(1) in names:

                        found.append((folder.name, m.group(0), m.group(1), m.group(2)))
    return sorted(found, key=lambda x: x[3], reverse=True)[:limit]

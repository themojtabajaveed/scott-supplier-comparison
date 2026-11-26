"""Truth fixes, 2 November 2026: report dates, sample data that cannot pass for real evidence,
and demo output that never overwrites. Offline: fixtures and local files only.
"""
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scout.demo_fixtures import RESPONSES, DemoBrowser, DemoLLM, sample_plan  # noqa: E402
from scout.engine.comparison import evidence_line, render_comparison  # noqa: E402
from scout.engine.planner import plan_question  # noqa: E402
from scout.engine.tool_loop import execute_plan  # noqa: E402
from scout.workflows import provider, supplier  # noqa: E402

ALL_SUPPLIERS = 'Compare strong white bread flour 16kg delivery'
WHOLEMEAL = 'Compare Wessex wholemeal bread flour 16kg'
ALL_MODELS = ('Compare ' + ' and '.join(m for m, _ in provider.SUPPORTED_MODELS)
              + ' Standard USD input and output prices per million tokens')
RECORDED = [ROOT / 'eval-results' / 'live-30oct' / (s['name'] + '-result.json') for s in supplier.WORKFLOW['sites']]
RECORDED += sorted((ROOT / 'eval-results' / 'live-20261030').glob('*-result.json'))
REAL_HOSTS = {urlparse(s['url']).hostname for s in supplier.WORKFLOW['sites'] + provider.WORKFLOW['sites']}


def sample_run(question):
    plan = plan_question(question)
    assert plan.state == 'ready', plan.gaps
    plan = sample_plan(plan)
    return plan, execute_plan(plan, DemoBrowser(plan), DemoLLM(plan), sample=True)


def numbers(text):
    return {float(n) for n in re.findall(r'\d+(?:\.\d+)?', text)}


@pytest.mark.parametrize('question', [ALL_SUPPLIERS, WHOLEMEAL, ALL_MODELS])
def test_sample_runs_read_only_reserved_addresses_and_list_the_real_page(question):
    plan, r = sample_run(question)
    for site in plan.workflow['sites']:
        assert urlparse(site['url']).hostname.endswith('.sample.example')
        # A sample output carries no real address and no real source name at all
        assert 'live_url' not in site and site['name'].startswith('demo_')
    dumped = json.dumps({'plan': plan.to_dict(), 'result': r})
    assert not any(host in dumped for host in REAL_HOSTS), [h for h in REAL_HOSTS if h in dumped]
    for row in r['rows']:
        assert row['pages_visited']
        for url in row['pages_visited']:
            assert urlparse(url).hostname.endswith('.sample.example'), url
        for field in row['atomic_fields'].values():
            for claims in field['facts'].values():
                for claim in claims:
                    assert urlparse(claim['source_url']).hostname.endswith('.sample.example')
    assert r['readable'].split('\n')[2].startswith('Sample data invented for this demo')


# test_sample_amounts_never_equal_a_recorded_real_amount is not included: it compares the demo fixtures with real
# recorded amounts, which are not in this repository (see docs/TESTING.md, coverage limits).


def test_sample_sources_show_found_missing_and_disagreeing_outcomes():
    _, r = sample_run(ALL_SUPPLIERS)
    rows = {row['site']: row['atomic_fields'] for row in r['rows']}
    wessex = rows['demo_mill_one']['delivery_charge']
    assert wessex['facts']['amount'][0]['value'] == '£5.67' and 'binding_warning' not in wessex  # basis linked
    assert 'amount' in rows['demo_mill_two']['delivery_charge']['missing']  # not found
    assert rows['demo_mill_three']['product_price']['status'] == 'possible_numeric_disagreement'
    _, r = sample_run(ALL_MODELS)
    missing = {row['site'] + ':' + row['atomic_fields']['model_price_input']['facts']['model'][0]['value']:
               row['atomic_fields']['model_price_input']['missing'] for row in r['rows']}
    assert missing['demo_provider_one:Ministral 3 8B'] == ['region']
    assert 'unit' in missing['demo_provider_two:gpt-6.1-sol']  # partial context


def test_report_date_comes_from_the_caller_and_is_never_assumed():
    row = [{'site': 'x', 'atomic_fields': {}}]
    assert evidence_line(as_of='30 October 2026').startswith('Read-only evidence snapshot, 30 October 2026.')
    assert 'not recorded' in evidence_line()
    assert evidence_line(sample=True).startswith('Sample data invented for this demo')
    for kwargs in ({}, {'sample': True}, {'as_of': '2 November 2026'}):
        assert '27 October 2026' not in render_comparison(row, 'T', **kwargs)


def test_cli_demo_output_makes_a_new_folder_per_run_and_never_overwrites(tmp_path):
    out = tmp_path / 'sample-runs'
    out.mkdir()
    keep = out / 'result.json'
    keep.write_text('existing file', encoding='utf-8')
    cmd = [sys.executable, '-S', str(ROOT / 'scripts' / 'scout_question.py'), '--question', ALL_SUPPLIERS,
           '--demo', '--output-dir', str(out)]
    for _ in range(2):
        subprocess.run(cmd, check=True, capture_output=True, cwd=tmp_path, timeout=60)
    runs = sorted(p for p in out.iterdir() if p.is_dir())
    assert len(runs) == 2 and all(p.name.startswith('run-') for p in runs)
    assert keep.read_text(encoding='utf-8') == 'existing file'
    for run in runs:
        assert {p.name for p in run.iterdir()} == {'result.json', 'comparison.md', 'trace.md'}
        assert '£12.34' in (run / 'comparison.md').read_text(encoding='utf-8')

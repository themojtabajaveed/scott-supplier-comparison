"""Score the saved supplier live runs against scout/evals/supplier_truth.yaml and supplier_rubric.json.

Offline: reads local files only, no network and no model calls. Needs PyYAML (requirements.txt), so run it
with the project's virtual environment, not under -S:

    python3 scripts/build_scorecard.py                      # print the scorecard JSON
    python3 scripts/build_scorecard.py --output eval-results/scorecard-<YYYY-MM-DD>.json

--output writes a new file and refuses to replace an existing one. The JSON records a SHA-256 of every input
so the UI and the tests can tell when it no longer matches the files it was built from.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from scout import live_run  # noqa: E402  (standard library only at import time)
from scout.evals.scorecard import score_run  # noqa: E402
from scout.workflows import supplier  # noqa: E402

REFERENCE = ROOT / 'scout' / 'evals' / 'supplier_truth.yaml'
RUBRIC = ROOT / 'scout' / 'evals' / 'supplier_rubric.json'
RECORDED_DIR = ROOT / 'eval-results' / 'live-30oct'
RESULTS_ROOT = ROOT / 'eval-results'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rel(path):
    return Path(path).resolve().relative_to(ROOT).as_posix()


def runs_to_score():
    """(id, label, read_on, [result files]): the 30 Oct recorded runs, then each saved UI live run."""
    recorded = [RECORDED_DIR / (s['name'] + '-result.json') for s in supplier.WORKFLOW['sites']]
    out = [('recorded-30oct', 'Recorded live runs', '30 October 2026', [p for p in recorded if p.is_file()])]
    for folder, stem, site, stamp in sorted(live_run.saved_runs(RESULTS_ROOT), key=lambda x: x[3]):
        started = datetime.strptime(stamp, '%Y%m%dT%H%M%SZ')
        out.append(('live-' + stamp, 'Live run started from the UI, %s, %s UTC'
                    % (site, started.strftime('%H:%M')), live_run.long_date(started),
                    [RESULTS_ROOT / folder / (stem + '-result.json')]))
    return [r for r in out if r[3]]


def build():
    reference = yaml.safe_load(REFERENCE.read_text(encoding='utf-8'))
    rubric = json.loads(RUBRIC.read_text(encoding='utf-8'))
    header = [line[1:].strip() for line in REFERENCE.read_text(encoding='utf-8').splitlines()
              if line.startswith('#')]
    inputs = [REFERENCE, RUBRIC]
    runs = []
    for run_id, label, read_on, files in runs_to_score():
        rows = []
        for path in files:
            rows += [r for r in json.loads(path.read_text(encoding='utf-8'))['rows'] if isinstance(r, dict)]
            inputs.append(path)
        scored = score_run(rows, reference, rubric)
        runs.append({'id': run_id, 'label': label, 'read_on': read_on, 'files': [rel(p) for p in files],
                     **scored})
    return {
        'built_by': 'scripts/build_scorecard.py',
        'reference': {'path': rel(REFERENCE), 'seeded_at': reference.get('seeded_at'), 'header': header},
        'rubric': rel(RUBRIC),
        'inputs': [{'path': rel(p), 'sha256': sha256(p)} for p in inputs],
        'not_scored': 'API pricing: there is a provider reference file, but no live provider run from the current '
                      'engine to score.',
        'runs': runs,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--output', help='new file to write; an existing file is never replaced')
    a = p.parse_args(argv)
    text = json.dumps(build(), indent=2, ensure_ascii=False) + '\n'
    if not a.output:
        sys.stdout.write(text)
        return 0
    out = Path(a.output)
    try:
        with out.open('x', encoding='utf-8') as f:
            f.write(text)
    except FileExistsError:
        print('Refusing to replace %s; choose a new file name.' % out, file=sys.stderr)
        return 1
    print('Wrote %s' % out)
    return 0


if __name__ == '__main__':
    sys.exit(main())

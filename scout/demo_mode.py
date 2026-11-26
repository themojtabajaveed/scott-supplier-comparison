"""Explicit DEMO MODE: the local UI and the scorecard builder pointed at the invented demo suppliers
(scout/workflows/demo_supplier.py) and their invented recordings and reference under demo/.

Used only by the separate entry points scripts/scout_ui_demo.py and scripts/build_demo_scorecard.py, and by the
offline tests. The real supplier configuration and the network-gated connector are untouched; nothing selects
demo mode silently.
"""
import json
from pathlib import Path

from scout.workflows.demo_supplier import LABELS, SITES

ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = ROOT / 'demo' / 'recordings'
EVALS = ROOT / 'demo' / 'evals'
REFERENCE = EVALS / 'demo_supplier_truth.yaml'
RUBRIC = EVALS / 'demo_supplier_rubric.json'
SCORECARD = EVALS / 'scorecard-demo.json'
RUN_LABEL = 'Invented demo recordings (synthetic, not supplier facts)'
RUN_DATE = 'undated (invented)'
BANNER = 'Demo mode: invented demo suppliers and recordings, not real pages and not supplier facts.'


def apply_to_ui(ui, setattr_=setattr, banner=False):
    """Point a loaded scripts/scout_ui.py module at the demo data. setattr_ lets tests restore afterwards."""
    setattr_(ui, 'RECORDED_DIR', RECORDINGS)
    setattr_(ui, 'RECORDED_SITES', [s['name'] for s in SITES])
    setattr_(ui, 'SITE_LABELS', dict(LABELS))
    data = json.loads(SCORECARD.read_text(encoding='utf-8'))
    setattr_(ui, 'latest_scorecard', lambda: json.loads(json.dumps(data)))
    if banner:  # the demo entry point relabels the recorded-run banner and date; tests keep the UI's own labels
        setattr_(ui, 'RECORDED_BANNER', BANNER)
        setattr_(ui, 'RECORDED_DATE', RUN_DATE)
        setattr_(ui, 'RECORDED_HEADING', 'Invented demo recordings, %s')
        setattr_(ui, 'RECORDED_INTRO', '<p><strong>Invented demo data, not real.</strong> These recordings (%s) were '
                                       'produced offline by Scott\'s engine over invented pages for invented mills on '
                                       'reserved .example addresses. They are not supplier facts.</p>')
    return data


def apply_to_builder(build, setattr_=setattr):
    """Point a loaded scripts/build_scorecard.py module at the demo reference, rubric and recordings."""
    setattr_(build, 'REFERENCE', REFERENCE)
    setattr_(build, 'RUBRIC', RUBRIC)
    setattr_(build, 'RECORDED_DIR', RECORDINGS)
    setattr_(build, 'RESULTS_ROOT', EVALS)  # holds no saved UI live runs
    setattr_(build.supplier, 'WORKFLOW', dict(build.supplier.WORKFLOW, sites=SITES))
    original = build.runs_to_score

    def runs_to_score():
        # the scorecard keeps its internal run id; the visible label and date say what the data is
        return [(rid, RUN_LABEL, RUN_DATE, files) if rid == 'recorded-30oct' else (rid, label, on, files)
                for rid, label, on, files in original()]
    setattr_(build, 'runs_to_score', runs_to_score)
    return build

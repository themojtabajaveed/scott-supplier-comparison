"""Guards for the test-only demo-supplier adapter (tests/demo_suppliers.py): the committed synthetic recordings and
demo scorecard are exactly what the real engine produces over the invented pages, every name is invented, and the
real supplier workflow config is untouched by the adapter."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import demo_suppliers as demo  # noqa: E402
from scout.workflows import supplier  # noqa: E402

REAL = re.compile(r'wessex|cotswold|shipton', re.I)


def test_committed_recordings_are_regenerated_byte_for_byte_by_the_engine(tmp_path):
    folder = demo.write_recordings(tmp_path)
    for site in (demo.ONE, demo.TWO, demo.THREE):
        name = '%s-result.json' % site
        assert (folder / name).read_bytes() == (demo.FIXTURE_DIR / name).read_bytes(), name


def test_committed_demo_scorecard_matches_a_fresh_build(monkeypatch):
    build = demo.demo_scorecard_builder(monkeypatch)
    assert json.loads(json.dumps(build.build(), ensure_ascii=False)) == \
        json.loads(demo.DEMO_SCORECARD.read_text(encoding='utf-8'))


def test_every_demo_name_and_address_is_invented_and_no_real_name_appears_in_the_fixtures():
    assert all(label.endswith('(invented)') for label in demo.LABELS.values())
    assert all('.example/' in s['url'] and '.example/' in s['delivery_page'] for s in demo.SITES)
    for path in list(demo.FIXTURE_DIR.glob('*')) + list(demo.DEMO_EVALS.glob('*')):
        assert not REAL.search(path.read_text(encoding='utf-8')), path


def test_every_scripted_quote_is_verbatim_in_its_invented_page():
    for url, fields in demo.CLAIMS.items():
        for keys in fields.values():
            for claim in keys.values():
                assert claim['quote'] in demo.PAGES[url] and claim['value'] in claim['quote'], (url, claim)


def test_the_real_supplier_workflow_config_is_untouched_by_the_adapter():
    names = [s['name'] for s in supplier.WORKFLOW['sites']]
    assert not any(n.startswith('demo_mill') for n in names)
    assert all(not s['url'].endswith('.example/') for s in supplier.WORKFLOW['sites'])

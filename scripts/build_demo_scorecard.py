"""Build the INVENTED demo scorecard (demo/evals/scorecard-demo.json) from the invented reference, rubric and
recordings. Separate entry point; the real scorecard builder (scripts/build_scorecard.py) is unchanged.

    python3 scripts/build_demo_scorecard.py            # print
    python3 scripts/build_demo_scorecard.py --write    # replace demo/evals/scorecard-demo.json (demo data only)
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scout import demo_mode  # noqa: E402


def build():
    spec = importlib.util.spec_from_file_location('build_scorecard_for_demo', ROOT / 'scripts' / 'build_scorecard.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    undo = []

    def set_(obj, name, value):
        undo.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)
    try:
        return demo_mode.apply_to_builder(module, set_).build()
    finally:
        for obj, name, value in reversed(undo):
            setattr(obj, name, value)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--write', action='store_true')
    a = p.parse_args(argv)
    text = json.dumps(build(), indent=2, ensure_ascii=False) + '\n'
    if a.write:
        demo_mode.SCORECARD.write_text(text, encoding='utf-8')
    else:
        sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())

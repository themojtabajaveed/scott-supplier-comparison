"""Local UI in explicit DEMO MODE: invented demo suppliers, recordings and scorecard (demo/). Offline.
Separate entry point; scripts/scout_ui.py and the real supplier configuration are unchanged.

    python3 -S scripts/scout_ui_demo.py [--port 8017]
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scout import demo_mode  # noqa: E402

spec = importlib.util.spec_from_file_location('scout_ui', ROOT / 'scripts' / 'scout_ui.py')
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)
demo_mode.apply_to_ui(ui, banner=True)

if __name__ == '__main__':
    sys.exit(ui.main(sys.argv[1:]))

"""Every test reads a temporary local config holding a neutral placeholder project, never a local
scott.local.json, so no real project ID is needed or read while the offline suite runs."""
import json

import pytest

from scout import local_config

TEST_PROJECT = 'offline-test-project-placeholder'


@pytest.fixture(autouse=True)
def placeholder_local_config(tmp_path, monkeypatch):
    path = tmp_path / 'scott.local.json'
    path.write_text(json.dumps({'verified_free_project': TEST_PROJECT}), encoding='utf-8')
    monkeypatch.setattr(local_config, 'CONFIG_PATH', path)
    return path


# -- optional, visible deselection list (tests/STAGING-DESELECTED.json; currently empty) ---------------------------
_DESELECTED = {d['nodeid']: d['reason'] for d in json.load(
    open(__import__('pathlib').Path(__file__).with_name('STAGING-DESELECTED.json'), encoding='utf-8'))['deselected']}


def pytest_collection_modifyitems(config, items):
    drop = [i for i in items if i.nodeid in _DESELECTED]
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = [i for i in items if i.nodeid not in _DESELECTED]


# -- engine display labels for the invented demo suppliers (tests only) ---------------------------------
DEMO_LABELS = {'demo_mill_one': 'Demo Mill One (invented)', 'demo_mill_two': 'Demo Mill Two (invented)',
               'demo_mill_three': 'Demo Mill Three (invented)'}


@pytest.fixture(autouse=True)
def demo_supplier_labels(monkeypatch):
    from scout.engine import supplier_comparison
    for key, label in DEMO_LABELS.items():
        monkeypatch.setitem(supplier_comparison.SUPPLIER_LABELS, key, label)

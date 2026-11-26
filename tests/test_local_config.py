"""The verified project ID comes only from the local, uncommitted scott.local.json; anything else keeps
the live-run binding gate closed. Offline: temporary files only."""
import json

import pytest

from scout import live_run, local_config
from scout.engine.live_adapter import run_live_plan
from scout.engine.planner import plan_question
from tests.conftest import TEST_PROJECT
from tests.test_planner_loop import SUP


@pytest.mark.parametrize('content', [None, 'not json', '[]', '{}', '{"verified_free_project": ""}',
                                     json.dumps({'verified_free_project': local_config.PLACEHOLDER})])
def test_missing_or_placeholder_config_verifies_no_project(tmp_path, content):
    path = tmp_path / 'candidate.json'  # conftest already wrote scott.local.json here
    if content is not None:
        path.write_text(content, encoding='utf-8')
    assert local_config.verified_project(path) is None


def test_binding_needs_the_environment_to_match_the_local_config(tmp_path, monkeypatch):
    assert live_run.binding_confirmed({'SCOUT_VERIFIED_FREE_PROJECT': TEST_PROJECT})
    assert not live_run.binding_confirmed({'SCOUT_VERIFIED_FREE_PROJECT': 'some-other-project'})
    assert not live_run.binding_confirmed({})
    monkeypatch.setattr(local_config, 'CONFIG_PATH', tmp_path / 'absent.json')
    assert not live_run.binding_confirmed({'SCOUT_VERIFIED_FREE_PROJECT': TEST_PROJECT})


def test_adapter_refuses_without_a_local_config(tmp_path, monkeypatch):
    monkeypatch.setattr(local_config, 'CONFIG_PATH', tmp_path / 'absent.json')

    def forbidden(*a, **k):
        raise AssertionError('adapter constructed')
    with pytest.raises(RuntimeError, match='binding'):
        run_live_plan(plan_question(SUP), api_key='test-only', verified_free_project=TEST_PROJECT,
                      ledger_path='fixture', safety_reviewed=True, browser_factory=forbidden,
                      client_factory=forbidden)


def test_example_config_and_ignore_rules_keep_the_real_value_out():
    root = local_config.ROOT
    example = json.loads((root / 'scott.local.example.json').read_text(encoding='utf-8'))
    assert example == {'verified_free_project': local_config.PLACEHOLDER}
    ignored = (root / '.gitignore').read_text(encoding='utf-8').splitlines()
    assert 'scott.local.json' in ignored and 'eval-results/live-ledger.jsonl' in ignored

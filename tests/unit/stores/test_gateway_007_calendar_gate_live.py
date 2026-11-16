"""Gateway calendar declaration gate tests; no calendar or service I/O."""
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from tests.unit.stores.test_iter67_gateway_calendar_dry_run import synthetic_config

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / 'examples/live/007_ctp'


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _module('gateway_007_calendar_gate_runner', EXAMPLE / 'gateway_client_runner.py')
from calendar_gate import CalendarGateRefusal, check_gateway_calendar


@pytest.mark.parametrize('section', [
    {'root': 42}, {'root': False}, {'root': ''}, {'root': '  '},
    {'root': 'bad\0path'}, {'root': 'declared', 'unknown': 1},
    {'root': 'declared', 'review_mode': 'bad'}, [], 'invalid',
])
@pytest.mark.parametrize('dry_run', [False, True])
def test_invalid_declarations_refused_without_touching_files(tmp_path, section, dry_run):
    config = {'calendars': section}
    before = tuple(tmp_path.iterdir())
    with pytest.raises(CalendarGateRefusal) as exc:
        check_gateway_calendar(config, config_file=tmp_path / 'config.yaml', dry_run=dry_run)
    assert exc.value.code == 'CALENDAR_CONFIG_INVALID'
    assert tuple(tmp_path.iterdir()) == before


@pytest.mark.parametrize('section', [None, {}, {'root': None}])
def test_live_missing_root_retains_existing_finite_code(tmp_path, section):
    config = {} if section is None else {'calendars': section}
    if section is None:
        assert check_gateway_calendar(config, config_file=tmp_path / 'config.yaml', dry_run=False).code == 'calendar_root_unconfigured'
    else:
        with pytest.raises(CalendarGateRefusal) as exc:
            check_gateway_calendar(config, config_file=tmp_path / 'config.yaml', dry_run=False)
        assert exc.value.code == 'calendar_root_unconfigured'


@pytest.mark.parametrize('root,expected_kind', [('relative/calendar', 'directory'), ('package_seed', 'package_seed')])
def test_valid_live_and_dry_declarations_use_parser_without_filesystem_access(tmp_path, monkeypatch, root, expected_kind):
    import bt_api_py.trading_calendar_config as sdk
    original = sdk.parse_trading_calendar_config
    observed = []
    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        observed.append(result)
        return result
    monkeypatch.setattr(sdk, 'parse_trading_calendar_config', capture)
    config = {'calendars': {'root': root}}
    before = tuple(tmp_path.iterdir())
    assert check_gateway_calendar(config, config_file=tmp_path / 'public.yaml', dry_run=False).kind == 'declared'
    assert check_gateway_calendar(config, config_file=tmp_path / 'public.yaml', dry_run=True).kind == expected_kind
    assert all(value.root_kind == expected_kind for value in observed)
    if root != 'package_seed':
        assert all(value.root_path == tmp_path / root for value in observed)
    assert tuple(tmp_path.iterdir()) == before


@pytest.mark.parametrize('section', [{'root': 42}, {'root': ''}, {'root': 'good', 'unknown': 1}, {}])
def test_live_bad_declaration_rejected_before_provider(tmp_path, monkeypatch, capsys, section):
    config = synthetic_config()
    config['calendars'] = section
    path = tmp_path / 'public.yaml'
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    monkeypatch.setattr(runner, 'resolve_resources', lambda *args, **kwargs: pytest.fail('provider accessed'))
    monkeypatch.setattr(runner, 'configure_run_logging', lambda *args, **kwargs: pytest.fail('logging started'))
    assert runner.main(type('Strategy', (), {}), 'test', tmp_path, ['--config', str(path)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result['error_code'] == ('calendar_root_unconfigured' if section == {} else 'CALENDAR_CONFIG_INVALID')
    assert sorted(p.name for p in tmp_path.iterdir()) == ['public.yaml']

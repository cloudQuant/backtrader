"""Offline checks for unsupported 007 Gateway Execution configuration."""

import json
import runpy

import pytest
import yaml

from tests.unit.stores.test_iter67_gateway_calendar_dry_run import RUNNER, synthetic_config


@pytest.mark.parametrize("execution", [None, False, {}, {"enabled": True}, "SENTINEL"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_top_level_execution_is_rejected_before_resources(
    tmp_path, monkeypatch, capsys, execution, dry_run
):
    import bt_api_py.gateway_strategy_config as gateway_config

    main = runpy.run_path(str(RUNNER), run_name="execution_config_test")["main"]
    config = synthetic_config()
    config["gateway_resource_provider"] = "local_files"
    config["execution"] = execution
    path = tmp_path / "synthetic.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")

    def forbidden(*args, **kwargs):
        pytest.fail("configuration must be rejected before runtime setup")

    monkeypatch.setattr(gateway_config, "parse_gateway_strategy_config", forbidden)
    main.__globals__["configure_run_logging"] = forbidden
    main.__globals__["resolve_resources"] = forbidden
    args = ["--config", str(path)] + (["--dry-run"] if dry_run else [])
    assert main(type("Strategy", (), {}), "synthetic", tmp_path, args) == 2
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["status"] == "BLOCKED"
    assert report["error_code"] == "GATEWAY_TOP_LEVEL_EXECUTION_UNSUPPORTED"
    assert "execution" in report["message"]
    assert "SENTINEL" not in captured.out + captured.err
    assert list(tmp_path.iterdir()) == [path]

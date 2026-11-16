"""007 Gateway calendar configuration checks use synthetic offline input only."""

import json
import runpy
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from tests.unit.stores.test_iter67_calendar_config_wiring import offline_subprocess_environment

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = sorted((ROOT / "examples/live/007_ctp").glob("*_gateway/run.py"))
RUNNER = ROOT / "examples/live/007_ctp/gateway_client_runner.py"


def synthetic_config():
    instrument = {
        "provider": "ctp",
        "venue": "CFFEX",
        "environment": "simnow",
        "product_type": "future",
        "instrument_id": "IF2612",
        "native_symbol": "IF2612",
    }
    route_scope = {
        "execution_domain_ref": "domain",
        "account_ref": "account",
        "account_refs": [],
        "strategy_ref": "strategy",
        "run_id": "run",
        "manual_book_ref": None,
        "portfolio_ref": None,
        "group_id": None,
        "leg_id": None,
    }
    binding = {
        "mount": "broker.direct_write",
        "service_id": "gateway",
        "instance_id": "instance",
        "scope_ref": "scope",
        "account_ref": "account",
        "transport_ref": "transport",
    }
    market_binding = {key: value for key, value in binding.items() if key != "account_ref"}
    market_binding["mount"] = "store.market"
    gateway = {
        "schema_version": 1,
        "exchange_name": "CTP___FUTURE",
        "risk": "none",  # Explicit D64-01 selection for this offline fixture.
        "client_config": {
            "client_config_schema_version": 1,
            "process_role": "strategy_client",
            "registration": {"strategy_ref": "strategy"},
            "clients": {
                "gateway": {
                    "config_schema_version": 1,
                    "settings": {"bindings": [binding, market_binding]},
                }
            },
            "communication": {
                "config_schema_version": 1,
                "profiles": {
                    "transport": {
                        "backend": "zmq",
                        "config_schema_version": 1,
                        "endpoints": {
                            "rpc_connect": "tcp://127.0.0.1:12345",
                            "market_connect": "tcp://127.0.0.1:12346",
                        },
                        "security_profile_ref": "security",
                    }
                },
            },
        },
        "binding": {
            "journal_id": "journal",
            "account_scope": "account",
            "strategy_scope": "strategy",
            "principal": "principal",
        },
        "route": {
            "mount": "broker.direct_write",
            "service_id": "gateway",
            "instance_id": "instance",
            "scope_ref": "scope",
            "scope": route_scope,
            "identity": {
                "role": "strategy_client",
                "principal_ref": "principal",
                "actor_ref": "strategy",
                "delegate_ref": None,
            },
        },
        "peer": {
            "role": "service",
            "principal_ref": "service-principal",
            "actor_ref": "gateway",
            "delegate_ref": None,
        },
        "requested_operations": [
            "direct.reserve",
            "direct.release",
            "direct.dispatch",
            "direct.command_status",
            "direct.cancel",
            "direct.cancel_status",
            "direct.events.read_after",
            "direct.events.ack",
            "direct.events.progress",
        ],
        "execution_time_policy": {
            "route": "CTP___FUTURE",
            "timezone": "Asia/Shanghai",
            "format": "date_hms_seconds_v1",
            "schema_version": 1,
        },
        "instruments_by_ref": {"main": deepcopy(instrument)},
        "market_settings": {
            "subscriptions": {
                "main": {
                    "key": {
                        "source_ref": "ctp-source",
                        "entitlement_ref": "market-entitlement",
                        "instrument": instrument,
                        "channel": "tick",
                        "depth": None,
                        "timeframe": None,
                    },
                    "require_source_descriptor": True,
                }
            }
        },
    }
    return {
        "gateway_resource_provider": "synthetic",
        "symbols": ["IF2612"],
        "contracts": {
            "IF2612": {
                "exchange": "CFFEX",
                "quantity_unit": "contracts",
                "time_in_force": "GFD",
                "price_tick": 0.2,
            }
        },
        "gateway_strategy": gateway,
    }


def test_missing_risk_selection_is_rejected_before_calendar(tmp_path, capsys):
    main = runpy.run_path(str(RUNNER), run_name="calendar_runner_test")["main"]
    config = synthetic_config()
    del config["gateway_strategy"]["risk"]
    path = tmp_path / "synthetic.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")

    assert main(type("Strategy", (), {}), "synthetic", tmp_path, ["--config", str(path), "--dry-run"]) == 2
    assert json.loads(capsys.readouterr().out)["error_code"] == "GATEWAY_CONFIG_INVALID"


def test_simulation_calendar_opt_in_is_explicit_in_dry_run(tmp_path, capsys):
    main = runpy.run_path(str(RUNNER), run_name="calendar_runner_test")["main"]
    config = synthetic_config()
    gateway = config["gateway_strategy"]
    assert "calendar_settings" not in gateway
    bindings = gateway["client_config"]["clients"]["gateway"]["settings"]["bindings"]
    bindings.append({**bindings[0], "mount": "store.calendar"})
    gateway["calendar_settings"] = {
        "mode": "SIMULATION_ONLY",
        "scopes": [{"route": "CTP___FUTURE", "venue": "CFFEX", "kind": "future",
                    "product": "IF", "contract": "IF2612"}],
    }
    path = tmp_path / "synthetic.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    assert main(type("Strategy", (), {}), "synthetic", tmp_path, ["--config", str(path), "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["calendar"] == "calendar_root_unconfigured"


@pytest.mark.parametrize(
    "calendars,expected",
    [
        (None, "calendar_root_unconfigured"),
        ({"root": "中文 dir"}, "external_directory_configured_not_bound"),
        ({"root": "package_seed"}, "package_seed_declared_not_bound"),
    ],
)
def test_all_gateway_wrappers_dry_run_offline(tmp_path, calendars, expected):
    assert len(SCRIPTS) == 11
    config = synthetic_config()
    if calendars is not None:
        config["calendars"] = calendars
    path = tmp_path / "synthetic.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    environment = offline_subprocess_environment(tmp_path)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    before = {p.relative_to(tmp_path) for p in tmp_path.rglob("*")}
    for script in SCRIPTS:
        result = subprocess.run(
            [sys.executable, str(script), "--config", str(path), "--dry-run"],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (script.name, result.stdout, result.stderr)
        assert json.loads(result.stdout)["calendar"] == expected
        assert str(tmp_path) not in result.stdout + result.stderr
    assert {p.relative_to(tmp_path) for p in tmp_path.rglob("*")} == before


@pytest.mark.parametrize(
    "calendars,code",
    [
        ({}, "CALENDAR_CONFIG_INVALID"),
        ({"root": None}, "CALENDAR_CONFIG_INVALID"),
        ({"root": 3}, "CALENDAR_CONFIG_INVALID"),
        ({"root": "secret", "bad": "SENTINEL"}, "CALENDAR_CONFIG_INVALID"),
    ],
)
def test_invalid_sections_are_reported_without_runtime(
    tmp_path, monkeypatch, capsys, calendars, code
):
    namespace = runpy.run_path(str(RUNNER), run_name="calendar_runner_test")
    main = namespace["main"]
    path = tmp_path / "synthetic.yaml"
    path.write_text(
        yaml.safe_dump({**synthetic_config(), "calendars": calendars}), encoding="utf-8"
    )

    def forbidden(*args, **kwargs):
        pytest.fail("runtime resources were reached")

    main.__globals__["resolve_resources"] = forbidden
    main.__globals__["configure_run_logging"] = forbidden
    assert (
        main(type("Strategy", (), {}), "synthetic", tmp_path, ["--config", str(path), "--dry-run"])
        == 2
    )
    captured = capsys.readouterr()
    assert json.loads(captured.out)["error_code"] == code
    assert (
        "SENTINEL" not in captured.out + captured.err
        and str(tmp_path) not in captured.out + captured.err
    )
    assert not (tmp_path / "secret").exists()


@pytest.mark.parametrize("dry_run,kind", [(True, "package_seed"), (False, "declared")])
def test_package_seed_is_accepted_as_a_declaration_only(tmp_path, monkeypatch, dry_run, kind):
    """The Shared Gateway gate accepts the keyword; this process never reads it."""
    monkeypatch.syspath_prepend(str(RUNNER.parent))
    from calendar_gate import check_gateway_calendar

    path = tmp_path / "synthetic.yaml"
    config = {**synthetic_config(), "calendars": {"root": "package_seed"}}
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    gate = check_gateway_calendar(config, config_file=path, dry_run=dry_run)
    assert gate.code is None and gate.kind == kind
    assert not (tmp_path / "package_seed").exists()


def test_unknown_root_kind_still_exits_2(tmp_path, monkeypatch, capsys):
    """A future parser root kind is refused instead of being treated as a directory."""
    import bt_api_py.trading_calendar_config as calendar
    from bt_api_py.trading_calendar_config import CalendarConfigCandidate

    monkeypatch.syspath_prepend(str(RUNNER.parent))

    def candidate(*args, **kwargs):
        return CalendarConfigCandidate(
            "CONFIGURED", "committed_builtin", "committed_builtin", None, "auto", "default", None
        )

    monkeypatch.setattr(calendar, "parse_trading_calendar_config", candidate)
    main = runpy.run_path(str(RUNNER), run_name="calendar_runner_test")["main"]
    config = {**synthetic_config(), "calendars": {"root": "dir"}}
    path = tmp_path / "synthetic.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    assert (
        main(type("Strategy", (), {}), "synthetic", tmp_path, ["--config", str(path), "--dry-run"])
        == 2
    )
    assert json.loads(capsys.readouterr().out)["error_code"] == "CALENDAR_CONFIG_INVALID"


def test_live_start_rejects_invalid_calendar_before_resources(tmp_path, monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(RUNNER.parent))
    namespace = runpy.run_path(str(RUNNER), run_name="calendar_runner_test")
    main = namespace["main"]
    path = tmp_path / "synthetic.yaml"
    path.write_text(
        yaml.safe_dump({**synthetic_config(), "calendars": {"root": 3}}), encoding="utf-8"
    )

    def forbidden(*args, **kwargs):
        pytest.fail("invalid calendar must be rejected before resource access")

    main.__globals__["configure_run_logging"] = forbidden
    main.__globals__["resolve_resources"] = forbidden
    assert main(type("Strategy", (), {}), "synthetic", tmp_path, ["--config", str(path)]) == 2
    assert json.loads(capsys.readouterr().out)["error_code"] == "CALENDAR_CONFIG_INVALID"


def test_missing_calendar_dry_run_does_not_import_parser(tmp_path, monkeypatch, capsys):
    import builtins

    main = runpy.run_path(str(RUNNER), run_name="calendar_runner_test")["main"]
    path = tmp_path / "synthetic.yaml"
    path.write_text(yaml.safe_dump(synthetic_config()), encoding="utf-8")
    original = builtins.__import__

    def checked(name, *args, **kwargs):
        if name == "bt_api_py.trading_calendar_config":
            pytest.fail("unconfigured dry-run must not import calendar parser")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", checked)
    assert (
        main(type("Strategy", (), {}), "synthetic", tmp_path, ["--config", str(path), "--dry-run"])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["calendar"] == "calendar_root_unconfigured"


@pytest.mark.parametrize("root", ["~/中文 路径", "$HOME/calendars", "/tmp/中文 路径"])
def test_dry_run_uses_sdk_path_parsing_without_printing_or_creating(
    root, tmp_path, monkeypatch, capsys
):
    import bt_api_py.trading_calendar_config as calendar

    monkeypatch.setenv("HOME", str(tmp_path / "synthetic-home"))
    original, seen = calendar.parse_trading_calendar_config, []

    def inspect(*args, **kwargs):
        result = original(*args, **kwargs)
        seen.append(result.root_path)
        return result

    monkeypatch.setattr(calendar, "parse_trading_calendar_config", inspect)
    main = runpy.run_path(str(RUNNER), run_name="calendar_runner_test")["main"]
    path = tmp_path / "synthetic.yaml"
    path.write_text(
        yaml.safe_dump({**synthetic_config(), "calendars": {"root": root}}), encoding="utf-8"
    )
    assert (
        main(type("Strategy", (), {}), "synthetic", tmp_path, ["--config", str(path), "--dry-run"])
        == 0
    )
    captured = capsys.readouterr()
    assert json.loads(captured.out)["calendar"] == "external_directory_configured_not_bound"
    assert (
        str(tmp_path) not in captured.out + captured.err and root not in captured.out + captured.err
    )
    expected = (
        tmp_path / "synthetic-home/中文 路径"
        if root.startswith("~")
        else tmp_path / root
        if root.startswith("$")
        else Path(root)
    )
    assert seen == [expected]
    assert not (tmp_path / "synthetic-home").exists()

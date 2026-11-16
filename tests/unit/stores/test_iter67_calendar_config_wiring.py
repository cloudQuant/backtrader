"""Offline Store-local calendar observations; no runtime binding is claimed."""

import hashlib
import json
import os
import runpy
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import yaml
import backtrader
import bt_api_base
import bt_api_ctp
import bt_api_py

from backtrader.live_state.gateway_pending import GatewayPendingHost
from backtrader.service.trading_calendar_config import parse_direct_calendar_status
from backtrader.stores.btapistore import BtApiStore, BtApiStoreError
from bt_api_py.bt_api import BtApi
from bt_api_py.service_runtime import ClientCurveKeys
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_py.trading_calendar_store import (
    CurrentPrecondition, PolicyPublication, TradingCalendarStore, calendar_snapshot_digest,
)
from backtrader.stores import btapistore as store_module
from tests.unit.stores.test_iter67_trading_calendar_status import publish, observed_status
from tests.unit.live_state.conftest import state as state, strategy_dir as strategy_dir

ROUTE = "CTP___FUTURE"
OTHER = "OTHER___FUTURE"
ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = sorted((ROOT / "examples/live/007_ctp").glob("*_direct/run.py"))


def isolated_subprocess_environment():
    """Use these loaded source roots without inheriting credentials or cwd-relative paths."""
    modules = (backtrader, bt_api_py, bt_api_ctp, bt_api_base)
    roots = [str(Path(module.__file__).resolve().parent.parent) for module in modules]
    return {"PATH": os.defpath, "PYTHONPATH": os.pathsep.join(roots)}


def offline_subprocess_environment(tmp_path):
    """Block network calls in the synthetic CLI while retaining only source roots."""
    guard = tmp_path / "offline_guard"
    guard.mkdir(exist_ok=True)
    (guard / "sitecustomize.py").write_text(
        "import socket\n"
        "def blocked(*args, **kwargs):\n"
        "    raise OSError('network disabled in test')\n"
        "socket.socket.connect = blocked\n"
        "socket.socket.connect_ex = blocked\n"
        "socket.socket.sendto = blocked\n"
        "socket.create_connection = blocked\n"
        "socket.getaddrinfo = blocked\n",
        encoding="utf-8",
    )
    environment = isolated_subprocess_environment()
    environment["PYTHONPATH"] += os.pathsep + str(guard)
    return environment


def parse(tmp_path, root, routes=(ROUTE,), configured=(ROUTE,)):
    return parse_direct_calendar_status(
        {"calendars": {"root": root}}, config_file=tmp_path / "config.yaml",
        ctp_routes=routes, configured_routes=set(configured),
    )


@pytest.mark.parametrize("root", ["relative/../中文 日历", "/tmp/中文 日历", "$HOME/calendars"])
def test_path_resolution_is_sdk_parser_based(tmp_path, monkeypatch, root):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    candidate, roots = parse(tmp_path, root)
    expected = Path(os.path.normpath(root if root.startswith("/") else tmp_path / root))
    assert candidate.root_path == expected
    assert roots == {ROUTE: str(expected / "ctp")}


def test_home_expansion_and_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert parse(tmp_path, "~/calendars")[1][ROUTE] == str(tmp_path / "home/calendars/ctp")
    candidate, roots = parse_direct_calendar_status(
        {}, config_file=tmp_path / "config.yaml", ctp_routes=(ROUTE,), configured_routes={ROUTE}
    )
    assert candidate.reason == "calendar_root_unconfigured" and not roots


@pytest.mark.parametrize("value", [None, "", 1, {}, {"review_mode": "manual"},
                                   {"root": "x", "bad": 1}])
def test_invalid_sections_are_rejected(tmp_path, value):
    with pytest.raises(ValueError):
        parse_direct_calendar_status({"calendars": value}, config_file=tmp_path / "config.yaml",
                                     ctp_routes=(ROUTE,), configured_routes={ROUTE})


def test_seed_and_route_validation(tmp_path):
    with pytest.raises(ValueError, match="calendar_package_seed_unsupported"):
        parse(tmp_path, "package_seed")
    for routes in ((ROUTE, ROUTE), (OTHER,), (), ("bad route",)):
        with pytest.raises(ValueError, match="calendar_ctp_routes_invalid"):
            parse(tmp_path, "dir", routes=routes)
    assert parse(tmp_path, "dir", routes=(ROUTE, OTHER), configured=(ROUTE, OTHER))[1] == {
        route: str(tmp_path / "dir/ctp") for route in (ROUTE, OTHER)
    }


@pytest.mark.parametrize("section, message", [
    ({}, "calendar_configuration_invalid"),
    ({"review_mode": "manual"}, "calendar_configuration_invalid"),
])
def test_store_rejects_invalid_configuration(tmp_path, section, message):
    with pytest.raises(BtApiStoreError, match=message):
        BtApiStore(config={"exchange_kwargs": {ROUTE: {}}},
                   calendar_config_file=tmp_path / "config.yaml",
                   calendar_config={"calendars": section}, calendar_ctp_routes=(ROUTE,))


def test_store_missing_configuration_keeps_old_construction(monkeypatch):
    import builtins
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name == "bt_api_py.trading_calendar_config":
            pytest.fail("missing calendar section must not require the new SDK parser")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    store = BtApiStore(config={"exchange_kwargs": {ROUTE: {}}})
    assert store.sdk_api is None


def test_injected_api_is_not_reconfigured(monkeypatch, tmp_path):
    api = BtApi(debug=False)
    api.exchange_feeds[ROUTE] = object()
    def forbidden(**kwargs):
        pytest.fail("injected API must not be reconfigured")
    monkeypatch.setattr(api, "configure_trading_calendar_status", forbidden)
    BtApiStore(api=api, config={"exchange_kwargs": {ROUTE: {}}},
               calendar_config_file=tmp_path / "config.yaml",
               calendar_config={"calendars": {"root": "dir"}},
               calendar_ctp_routes=(ROUTE,))
    assert api.trading_calendar_status(ROUTE).reason == "ROUTE_UNCONFIGURED"


def test_local_reader_configuration_failure_is_sanitized(monkeypatch, tmp_path):
    from bt_api_py.trading_calendar_runtime_status import TradingCalendarStatusReader
    def fail(*args, **kwargs):
        raise OSError("/private/secret")
    monkeypatch.setattr(TradingCalendarStatusReader, "configure", fail)
    with pytest.raises(BtApiStoreError, match="calendar_status_configuration_failed") as exc:
        BtApiStore(config={"exchange_kwargs": {ROUTE: {}}},
                   calendar_config_file=tmp_path / "config.yaml",
                   calendar_config={"calendars": {"root": "dir"}},
                   calendar_ctp_routes=(ROUTE,))
    assert "/private/secret" not in str(exc.value)


def test_read_only_service_cannot_select_local_configuration(monkeypatch, tmp_path):
    monkeypatch.setattr(store_module, "_is_supported_api_facade", lambda _: (False, True))
    with pytest.raises(BtApiStoreError, match="calendar_configuration_requires_direct_sdk"):
        BtApiStore(api=object(), config={"exchange_kwargs": {ROUTE: {}}},
                   calendar_config_file=tmp_path / "config.yaml",
                   calendar_config={"calendars": {"root": "dir"}},
                   calendar_ctp_routes=(ROUTE,))


def test_gateway_cannot_select_local_configuration(state, tmp_path):
    example = (Path(bt_api_py.__file__).resolve().parent.parent / "examples/services"
               / "gateway-strategy-client.example.yaml")
    config = yaml.safe_load(example.read_text(encoding="utf-8"))
    binding = GatewayCommandBinding(**config["binding"])
    GatewayPendingHost.upgrade_for_gateway(state.strategy_dir, state.strategy_uuid, binding)
    GatewayPendingHost.upgrade_for_cancellation(state.strategy_dir, state.strategy_uuid, binding)
    GatewayPendingHost.upgrade_for_execution(
        state.strategy_dir, state.strategy_uuid, binding, consumer_ref="gexec:" + "a" * 64
    )
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    keys = {"security": ClientCurveKeys(b"a" * 40, b"b" * 40, b"c" * 40)}
    with pytest.raises(BtApiStoreError, match="calendar_configuration_requires_direct_sdk"):
        BtApiStore(config={"gateway_strategy": config}, gateway_host=host,
                   gateway_security_profiles=keys, calendar_config_file=tmp_path / "config.yaml",
                   calendar_config={"calendars": {"root": "dir"}}, calendar_ctp_routes=(ROUTE,))


def local_store(monkeypatch, base, *, api=None, routes=(ROUTE,), local_routes=(ROUTE,),
                custom_factory=False, owned=False):
    if api is None:
        api = BtApi(debug=False)
        api.exchange_feeds.update({route: object() for route in routes})
    options = {} if owned else ({"api_cls": lambda: api} if custom_factory else {"api": api})
    config_file = base / "config.yaml"
    config_file.write_text(yaml.safe_dump({"calendars": {"root": "calendars"}}), encoding="utf-8")
    store = BtApiStore(
        config={"exchange_kwargs": {route: {} for route in routes}},
        calendar_config_file=config_file,
        calendar_config=yaml.safe_load(config_file.read_text(encoding="utf-8")),
        calendar_ctp_routes=local_routes, **options,
    )
    def start(s, *_args, **_kwargs):
        s._api = api
        s._started = s._connected = s._sdk_configured = True
    monkeypatch.setattr(store_module, "_start_store", start)
    store.start()
    return store, api


@pytest.mark.parametrize("owned", [False, True])
def test_actual_sdk_local_reader_observes_published_ctp(monkeypatch, tmp_path, owned):
    root = tmp_path / "calendars/ctp"
    root.mkdir(parents=True)
    publish(root)
    store, api = local_store(monkeypatch, tmp_path, owned=owned)
    def forbidden(*args, **kwargs):
        pytest.fail("local status must not construct, configure or connect the facade")
    monkeypatch.setattr(store, "_ensure_api_ready", forbidden)
    monkeypatch.setattr(api, "configure_trading_calendar_status", forbidden)
    monkeypatch.setattr(api, "trading_calendar_status", forbidden)
    monkeypatch.setattr(api, "connect", forbidden, raising=False)
    result = store.trading_calendar_status()
    observed = result["routes"][ROUTE]
    assert result["status"] == "OBSERVED" and result["sources"] == {ROUTE: "LOCAL_CONFIG"}
    assert (observed.status, observed.published, observed.bound, observed.source_authentication) == (
        "OBSERVED_UNAUTHENTICATED", "CURRENT_OBSERVED", "NOT_BOUND", "NOT_PROVEN")
    assert str(tmp_path) not in repr(result)


def test_local_only_does_not_access_facade_status_property(monkeypatch, tmp_path):
    root = tmp_path / "calendars/ctp"
    root.mkdir(parents=True)
    publish(root)
    store, _ = local_store(monkeypatch, tmp_path)
    def forbidden(_self):
        pytest.fail("facade status property must not be accessed")
    monkeypatch.setattr(BtApi, "trading_calendar_status", property(forbidden))
    assert store.trading_calendar_status()["status"] == "OBSERVED"


def test_two_stores_share_facade_without_overwriting_each_other(monkeypatch, tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    (first / "calendars/ctp").mkdir(parents=True)
    (second / "calendars/ctp").mkdir(parents=True)
    publish(first / "calendars/ctp")
    api = BtApi(debug=False)
    api.exchange_feeds[ROUTE] = object()
    store_a, _ = local_store(monkeypatch, first, api=api)
    store_b, _ = local_store(monkeypatch, second, api=api)
    assert store_a.trading_calendar_status()["status"] == "OBSERVED"
    assert store_b.trading_calendar_status()["routes"][ROUTE].reason == "CURRENT_UNAVAILABLE"
    assert api.trading_calendar_status(ROUTE).reason == "ROUTE_UNCONFIGURED"
    repo = TradingCalendarStore(second / "calendars/ctp")
    policy = repo.initialize_review_policy(config_read_succeeded=True)
    content = {"sources": [{"source": 2}], "trading_days": [{"day": 2}],
               "trading_hours": [{"hours": 2}], "exceptions": []}
    difference = {}
    digest = hashlib.sha256(json.dumps(difference, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=False).encode()).hexdigest()
    claim = PolicyPublication(policy.directory_id, policy.revision, policy.mode,
                              calendar_snapshot_digest(content), difference, digest)
    result = repo.publish(content, publication_id="p2", version_id="v2",
                          expected_current=CurrentPrecondition.absent(), policy_publication=claim)
    assert result.visibility == "COMMITTED"
    assert store_b.trading_calendar_status()["routes"][ROUTE].publication_id == "p2"
    assert store_a.trading_calendar_status()["routes"][ROUTE].publication_id == "p1"
    assert api.trading_calendar_status(ROUTE).reason == "ROUTE_UNCONFIGURED"


def test_local_precedes_facade_and_failure_never_falls_back(monkeypatch, tmp_path):
    root = tmp_path / "calendars/ctp"
    root.mkdir(parents=True)
    publish(root)
    store, api = local_store(monkeypatch, tmp_path)
    facade_calls = []
    monkeypatch.setattr(api, "trading_calendar_status",
                        lambda route: (facade_calls.append(route), observed_status())[1])
    assert store.trading_calendar_status()["sources"] == {ROUTE: "LOCAL_CONFIG"}
    assert store.trading_calendar_status()["status"] == "OBSERVED"
    def failed(_route):
        raise RuntimeError("/private/secret")
    monkeypatch.setattr(store._calendar_local_reader, "status", failed)
    result = store.trading_calendar_status()
    assert result["status"] == "UNKNOWN" and result["routes"][ROUTE].reason == "READ_UNAVAILABLE"
    assert result["sources"] == {ROUTE: "LOCAL_CONFIG"} and not facade_calls
    assert "/private/secret" not in repr(result)


@pytest.mark.parametrize("facade_available", [True, False])
def test_mixed_routes_and_missing_facade_capability(monkeypatch, tmp_path, facade_available):
    root = tmp_path / "calendars/ctp"
    root.mkdir(parents=True)
    publish(root)
    store, api = local_store(monkeypatch, tmp_path, routes=(ROUTE, OTHER))
    monkeypatch.setattr(api, "trading_calendar_status",
                        (lambda _route: observed_status()) if facade_available else None)
    result = store.trading_calendar_status()
    assert result["sources"] == {ROUTE: "LOCAL_CONFIG", OTHER: "SDK_FACADE"}
    assert result["routes"][ROUTE].bound == "NOT_BOUND"
    if facade_available:
        assert result["status"] == "OBSERVED"
    else:
        assert result["status"] == "PARTIAL"
        assert result["routes"][OTHER].reason == "CAPABILITY_UNAVAILABLE"


def test_multiple_local_routes_have_independent_failures(monkeypatch, tmp_path):
    root = tmp_path / "calendars/ctp"
    root.mkdir(parents=True)
    publish(root)
    store, _ = local_store(monkeypatch, tmp_path, routes=(ROUTE, OTHER),
                           local_routes=(ROUTE, OTHER), custom_factory=True)
    original = store._calendar_local_reader.status
    def status(route):
        if route == OTHER:
            raise RuntimeError("private")
        return original(route)
    monkeypatch.setattr(store._calendar_local_reader, "status", status)
    result = store.trading_calendar_status()
    assert result["status"] == "PARTIAL"
    assert result["routes"][ROUTE].status == "OBSERVED_UNAUTHENTICATED"
    assert result["routes"][OTHER].reason == "READ_UNAVAILABLE"
    assert result["sources"] == {ROUTE: "LOCAL_CONFIG", OTHER: "LOCAL_CONFIG"}


@pytest.mark.parametrize("change, reason", [("stop", "STORE_CHANGED"),
                                            ("routes", "ROUTE_SET_CHANGED"),
                                            ("api", "STORE_CHANGED"),
                                            ("stream", "STORE_CHANGED")])
def test_local_observation_is_discarded_after_lifecycle_or_route_change(
        monkeypatch, tmp_path, change, reason):
    root = tmp_path / "calendars/ctp"
    root.mkdir(parents=True)
    publish(root)
    store, api = local_store(monkeypatch, tmp_path)
    original = store._calendar_local_reader.status
    def read(route):
        value = original(route)
        if change == "stop":
            monkeypatch.setattr(store_module, "_stop_store", lambda *_args, **_kwargs: None)
            store.stop()
        elif change == "routes":
            api.exchange_feeds[OTHER] = object()
        elif change == "api":
            store._api = object()
        else:
            store._stream_generation += 1
        return value
    monkeypatch.setattr(store._calendar_local_reader, "status", read)
    result = store.trading_calendar_status()
    assert (result["status"], result["reason"]) == ("UNKNOWN", reason)
    assert result["routes"][ROUTE].reason == reason


def test_inflight_local_read_is_discarded_after_stop(monkeypatch, tmp_path):
    root = tmp_path / "calendars/ctp"
    root.mkdir(parents=True)
    publish(root)
    store, _ = local_store(monkeypatch, tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = store._calendar_local_reader.status
    def read(route):
        value = original(route)
        entered.set()
        assert release.wait(5)
        return value
    monkeypatch.setattr(store._calendar_local_reader, "status", read)
    result = []
    thread = threading.Thread(target=lambda: result.append(store.trading_calendar_status()))
    thread.start()
    assert entered.wait(5)
    monkeypatch.setattr(store_module, "_stop_store", lambda *_args, **_kwargs: None)
    try:
        store.stop()
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert result[0]["status"] == "UNKNOWN" and result[0]["reason"] == "STORE_CHANGED"


def synthetic_config(tmp_path):
    return {"symbols": ["IF0000"], "contracts": {"IF0000": {
        "exchange": "CFFEX", "price_tick": 0.2, "multiplier": 300}},
        "logging": {"file": str(tmp_path / "private.log")}}


def test_subprocess_imports_loaded_source_roots_with_relative_parent_path(monkeypatch, tmp_path):
    monkeypatch.setenv("PYTHONPATH", ".")
    monkeypatch.setenv("SIMNOW_PASSWORD", "synthetic-secret")
    environment = offline_subprocess_environment(tmp_path)
    assert set(environment) == {"PATH", "PYTHONPATH"}
    roots = environment["PYTHONPATH"].split(os.pathsep)
    assert all(Path(root).is_absolute() for root in roots)
    command = [sys.executable, "-c", (
        "import json, pathlib, backtrader, bt_api_py, bt_api_ctp, bt_api_base; "
        "print(json.dumps([str(pathlib.Path(m.__file__).resolve().parent.parent) "
        "for m in (backtrader, bt_api_py, bt_api_ctp, bt_api_base)]))"
    )]
    result = subprocess.run(command, capture_output=True, text=True, cwd=tmp_path,
                            env=environment, timeout=30, check=True)
    assert json.loads(result.stdout) == roots[:4]
    command = [sys.executable, "-c", (
        "import socket\n"
        "try:\n"
        "    socket.socket().connect(('127.0.0.1', 1))\n"
        "except OSError as exc:\n"
        "    print(str(exc))\n"
    )]
    result = subprocess.run(command, capture_output=True, text=True, cwd=tmp_path,
                            env=environment, timeout=30, check=True)
    assert result.stdout.strip() == "network disabled in test"


def test_all_direct_dry_runs_are_offline(tmp_path):
    assert len(SCRIPTS) == 11
    config = synthetic_config(tmp_path)
    path = tmp_path / "synthetic.yaml"
    environment = offline_subprocess_environment(tmp_path)
    for calendars, expected, marker in [(None, 0, "unconfigured"),
                                        ({"root": "中文 path"}, 0, "local status only"),
                                        ({"root": "package_seed"}, 0, "in-package seed"),
                                        ({}, 2, "invalid"),
                                        ({"review_mode": "manual"}, 2, "invalid"),
                                        ({"root": 3}, 2, "invalid"),
                                        ({"root": "secret", "bad": "SENTINEL"}, 2, "invalid")]:
        config.pop("calendars", None)
        if calendars is not None:
            config["calendars"] = calendars
        path.write_text(yaml.safe_dump(config), encoding="utf-8")
        for script in SCRIPTS:
            result = subprocess.run([sys.executable, str(script), "--config", str(path),
                                     "--env-file", str(tmp_path / "must-not-read"), "--dry-run"],
                                    capture_output=True, text=True, cwd=tmp_path, env=environment,
                                    timeout=30)
            assert result.returncode == expected, (script.name, result.stdout, result.stderr)
            assert marker in result.stdout
            assert "SENTINEL" not in result.stdout + result.stderr
            assert str(tmp_path) not in result.stdout + result.stderr
            if expected == 0:
                assert "Strategy:" in result.stdout and "symbols: IF0000" in result.stdout
                assert "Feed IF0000:" in result.stdout and "Logging:" in result.stdout
                assert "to=configured file" in result.stdout and "State directory:" in result.stdout


def test_all_direct_bad_files_are_redacted_before_credentials(tmp_path, request):
    assert len(SCRIPTS) == 11
    cases = {
        "broken.yaml": "password: SENTINEL_CONFIG_SECRET\ncalendars: [\n  bad: value\n",
        "broken.json": '{"password": "SENTINEL_CONFIG_SECRET",',
        "null.yaml": "null\n",
        "null.json": "null\n",
        "invalid.yaml": "symbols: [SENTINEL_CONFIG_SECRET]\ncontracts: {}\n",
    }
    for name, contents in cases.items():
        (tmp_path / name).write_text(contents, encoding="utf-8")
    inaccessible = tmp_path / "SENTINEL_PRIVATE_DIRECTORY.yaml"
    inaccessible.mkdir()  # Opening a directory as a file fails on all supported systems.
    unreadable = tmp_path / "SENTINEL_PRIVATE_UNREADABLE.yaml"
    unreadable.write_text("secret: SENTINEL_CONFIG_SECRET\n", encoding="utf-8")
    unreadable.chmod(0)
    request.addfinalizer(lambda: unreadable.chmod(0o600))
    paths = [tmp_path / name for name in cases] + [inaccessible]
    if not os.access(unreadable, os.R_OK):
        paths.append(unreadable)
    environment = offline_subprocess_environment(tmp_path)
    for script in SCRIPTS:
        for config_path in paths:
            for dry_run in (False, True):
                command = [sys.executable, str(script), "--config", str(config_path),
                           "--env-file", str(tmp_path / "SENTINEL_MUST_NOT_READ")]
                if dry_run:
                    command.append("--dry-run")
                result = subprocess.run(command, capture_output=True, text=True,
                                        cwd=tmp_path, env=environment, timeout=30)
                assert result.returncode == 2, (script.name, config_path.name, dry_run)
                assert result.stdout == "Configuration invalid or unavailable\n"
                assert not result.stderr
                assert "SENTINEL" not in result.stdout + result.stderr
                assert str(tmp_path) not in result.stdout + result.stderr


@pytest.mark.parametrize("exception", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("function", ["load_config", "validate_live_config"])
def test_config_boundary_propagates_interrupts(monkeypatch, tmp_path, exception, function):
    config_path = tmp_path / "synthetic.yaml"
    config_path.write_text(yaml.safe_dump(synthetic_config(tmp_path)), encoding="utf-8")
    for script in SCRIPTS:
        monkeypatch.syspath_prepend(str(script.parent))
        namespace = runpy.run_path(str(script), run_name="calendar_runner_test")
        def interrupt(*args, **kwargs):
            raise exception()
        namespace["main"].__globals__[function] = interrupt
        with pytest.raises(exception):
            namespace["main"](["--config", str(config_path), "--dry-run"])


def test_live_explicit_configuration_stops_before_credentials(monkeypatch, tmp_path, capsys):
    assert len(SCRIPTS) == 11
    config = synthetic_config(tmp_path)
    path = tmp_path / "synthetic.yaml"
    for script in SCRIPTS:
        monkeypatch.syspath_prepend(str(script.parent))
        namespace = runpy.run_path(str(script), run_name="calendar_runner_test")
        function_globals = namespace["main"].__globals__
        def forbidden(*args, **kwargs):
            pytest.fail("credential or runtime construction was reached")
        function_globals["load_credentials"] = forbidden
        function_globals["create_store"] = forbidden
        function_globals["configure_run_logging"] = forbidden
        for section in ({}, {"review_mode": "manual"}, {"root": 3}):
            config["calendars"] = section
            path.write_text(yaml.safe_dump(config), encoding="utf-8")
            assert namespace["main"](["--config", str(path), "--env-file", "must-not-read"]) == 2
            out = capsys.readouterr().out
            assert "Calendar" in out and str(tmp_path) not in out


def test_live_valid_calendar_is_checked_before_credentials(monkeypatch, tmp_path, capsys):
    path = tmp_path / "synthetic.yaml"
    config = synthetic_config(tmp_path)
    config["calendars"] = {"root": "dir", "feed_scope": {
        "IF0000": {"route": "CTP___FUTURE", "venue": "CFFEX", "kind": "future",
                   "product": "IF", "contract": "IF0000"}}}
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    calls = []
    for script in SCRIPTS:
        monkeypatch.syspath_prepend(str(script.parent))
        namespace = runpy.run_path(str(script), run_name="calendar_runner_test")
        function_globals = namespace["main"].__globals__
        def credentials(_):
            calls.append(True)
            raise LookupError("not available")
        def forbidden(*args, **kwargs):
            pytest.fail("runtime construction was reached")
        function_globals["load_credentials"] = credentials
        function_globals["create_store"] = forbidden
        function_globals["configure_run_logging"] = lambda _: "test"
        assert namespace["main"](["--config", str(path)]) == 2
        capsys.readouterr()
    assert len(calls) == 11


def feed_scope(**overrides):
    scope = {"route": "CTP___FUTURE", "venue": "CFFEX", "kind": "future",
             "product": "IF", "contract": "IF0000"}
    scope.update(overrides)
    return {"IF0000": scope}


def test_package_seed_is_accepted_without_credentials_or_store(monkeypatch, tmp_path, capsys):
    """The keyword is accepted; only a Store may materialize it at live start."""
    config = synthetic_config(tmp_path)
    config["calendars"] = {"root": "package_seed", "feed_scope": feed_scope()}
    path = tmp_path / "synthetic.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    calls = []
    for script in SCRIPTS:
        monkeypatch.syspath_prepend(str(script.parent))
        namespace = runpy.run_path(str(script), run_name="calendar_runner_test")
        function_globals = namespace["main"].__globals__

        def credentials(_):
            calls.append(True)
            raise LookupError("not available")

        def forbidden(*args, **kwargs):
            pytest.fail("Store construction was reached for the gate-only case")

        function_globals["load_credentials"] = credentials
        function_globals["create_store"] = forbidden
        function_globals["configure_run_logging"] = lambda _: "test"
        assert namespace["main"](["--config", str(path), "--env-file", "must-not-read"]) == 2
        out = capsys.readouterr().out
        assert "credentials_unavailable" in out
        assert "calendar_package_seed_unsupported" not in out
        assert str(tmp_path) not in out
    assert calls == [True] * 11
    assert not (tmp_path / "calendar_package_seed").exists()


def test_missing_feed_scope_stops_before_credentials(monkeypatch, tmp_path, capsys):
    config = synthetic_config(tmp_path)
    config["calendars"] = {"root": "dir"}
    path = tmp_path / "synthetic.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    for script in SCRIPTS:
        monkeypatch.syspath_prepend(str(script.parent))
        namespace = runpy.run_path(str(script), run_name="calendar_runner_test")
        function_globals = namespace["main"].__globals__

        def forbidden(*args, **kwargs):
            pytest.fail("credential or runtime construction was reached")

        function_globals["load_credentials"] = forbidden
        function_globals["create_store"] = forbidden
        function_globals["configure_run_logging"] = forbidden
        assert namespace["main"](["--config", str(path), "--env-file", "must-not-read"]) == 2
        out = capsys.readouterr().out
        assert "calendar_feed_scope_unconfigured" in out


def test_conflicting_feed_scope_stops_before_credentials(monkeypatch, tmp_path, capsys):
    config = synthetic_config(tmp_path)
    config["calendars"] = {"root": "dir", "feed_scope": feed_scope(contract="IF0001")}
    path = tmp_path / "synthetic.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    for script in SCRIPTS:
        monkeypatch.syspath_prepend(str(script.parent))
        namespace = runpy.run_path(str(script), run_name="calendar_runner_test")
        function_globals = namespace["main"].__globals__

        def forbidden(*args, **kwargs):
            pytest.fail("credential or runtime construction was reached")

        function_globals["load_credentials"] = forbidden
        function_globals["create_store"] = forbidden
        function_globals["configure_run_logging"] = forbidden
        for extra in ([], ["--dry-run"]):
            assert namespace["main"](["--config", str(path), *extra]) == 2
            out = capsys.readouterr().out
            assert "calendar_feed_scope_conflict" in out


def test_missing_section_dry_run_does_not_invoke_parser(monkeypatch, tmp_path, capsys):
    from backtrader.service import trading_calendar_config
    def forbidden(*args, **kwargs):
        pytest.fail("missing calendar section must not invoke parser")
    monkeypatch.setattr(trading_calendar_config, "parse_direct_calendar_status", forbidden)
    path = tmp_path / "synthetic.yaml"
    path.write_text(yaml.safe_dump(synthetic_config(tmp_path)), encoding="utf-8")
    for script in SCRIPTS:
        monkeypatch.syspath_prepend(str(script.parent))
        namespace = runpy.run_path(str(script), run_name="calendar_runner_test")
        assert namespace["main"](["--config", str(path), "--dry-run"]) == 0
        assert "unconfigured" in capsys.readouterr().out


def test_all_direct_store_calls_use_explicit_parameters(monkeypatch, tmp_path):
    from backtrader.stores import btapistore
    seen = []
    monkeypatch.setattr(btapistore, "BtApiStore", lambda **kwargs: seen.append(kwargs))
    config = synthetic_config(tmp_path)
    config["calendars"] = {
        "root": "relative",
        "feed_scope": {"IF0000": {"route": "CTP___FUTURE", "venue": "CFFEX",
                                  "kind": "future", "product": "IF",
                                  "contract": "IF0000"}},
    }
    for script in SCRIPTS:
        monkeypatch.syspath_prepend(str(script.parent))
        namespace = runpy.run_path(str(script), run_name="calendar_runner_test")
        namespace["create_store"].__globals__["configure_catalog_cache"] = lambda _: None
        namespace["create_store"](config, {"user_id": "unused", "password": "unused"},
                                  tmp_path / "config.yaml")
        kwargs = seen[-1]
        assert kwargs["calendar_config_file"] == tmp_path / "config.yaml"
        assert kwargs["calendar_config"] == {"calendars": {"root": "relative"}}
        assert "feed_scope" not in kwargs["calendar_config"]["calendars"]
        assert kwargs["calendar_ctp_routes"] == (namespace["ROUTE"],)
        missing = dict(config)
        missing.pop("calendars")
        namespace["create_store"](missing, {"user_id": "unused", "password": "unused"})
        assert seen[-1]["calendar_config"] is None
        assert seen[-1]["calendar_config_file"] is None
        assert seen[-1]["calendar_ctp_routes"] is None
    assert len(seen) == 22

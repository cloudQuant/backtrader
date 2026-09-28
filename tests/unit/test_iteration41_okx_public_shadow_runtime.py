"""Offline acceptance of the 010 OKX public shadow observer."""

from __future__ import annotations

import asyncio
import importlib
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import socket
import sys
import time
from types import SimpleNamespace

import pytest
import yaml

from backtrader_runtime import (
    PRESET_POLICY_VIOLATION,
    RegisteredRuntime,
    RuntimeConfigError,
    RuntimeRegistry,
    validate_runtime_config,
)
import backtrader_runtime.cli as runtime_cli_module
from backtrader_runtime.cli import main as runtime_cli
from backtrader_runtime.runner import _loaded_registered_runner


REPO = Path(__file__).resolve().parents[2]
RUNNER_MODULE = "examples.010_live_examples.run_okx_shadow_runtime"
CONFIG_EXAMPLE = (
    REPO / "examples" / "010_live_examples" / "runtime-okx-shadow" / "config.example.yaml"
)
_DEFAULT_BOOK = object()


@pytest.fixture
def runner():
    return importlib.import_module(RUNNER_MODULE)


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    """These tests use only fake providers and must not open a socket."""

    attempted = []
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def reject(*args, **kwargs):
        attempted.append(True)
        raise AssertionError("the OKX shadow acceptance tests must not access the network")

    def guarded_connect(sock, address):
        if isinstance(address, tuple) and address and address[0] in ("127.0.0.1", "::1"):
            return original_connect(sock, address)
        return reject(sock, address)

    def guarded_connect_ex(sock, address):
        if isinstance(address, tuple) and address and address[0] in ("127.0.0.1", "::1"):
            return original_connect_ex(sock, address)
        return reject(sock, address)

    monkeypatch.setattr(socket, "getaddrinfo", reject)
    monkeypatch.setattr(socket, "create_connection", reject)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    yield
    assert attempted == []


@pytest.fixture
def runtime(tmp_path, runner):
    directory = tmp_path / "runtime-okx-shadow"
    directory.mkdir()
    registration = RegisteredRuntime(
        runtime_dir=directory,
        strategy_id=runner.STRATEGY_ID,
        runtime_id=runner.RUNTIME_ID,
        allowed_presets=("shadow",),
        allowed_parameter_keys=("symbols", "duration_seconds", "orderbook_limit"),
        runner_module=RUNNER_MODULE,
        bootstrap_parameters=(
            ("symbols", ("BTC/USDT:USDT", "ETH/USDT:USDT")),
            ("duration_seconds", 10),
            ("orderbook_limit", 5),
        ),
    )
    registry = RuntimeRegistry((registration,))
    raw = yaml.safe_load(CONFIG_EXAMPLE.read_text(encoding="utf-8"))
    raw["parameters"]["duration_seconds"] = 1
    _write_config(directory, raw)
    return directory, raw, registry


def _write_config(directory: Path, raw: dict) -> None:
    (directory / "config.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


class FakeMarketClient:
    def __init__(self, *, update=True, close_error=False, book=_DEFAULT_BOOK):
        self.update = update
        self.close_error = close_error
        self.book_matches_requested_symbol = book is _DEFAULT_BOOK
        self.book = (
            {
                "symbol": "BTC/USDT:USDT",
                "bids": [[1.0, 1.0]],
                "asks": [[2.0, 1.0]],
            }
            if self.book_matches_requested_symbol
            else book
        )
        self.reads = []
        self.closed = False
        self.submitted_orders = 0
        self.cancelled_orders = 0

    async def load_markets(self):
        self.reads.append(("load_markets", None))
        return {"BTC/USDT:USDT": {}, "ETH/USDT:USDT": {}}

    async def watch_order_book(self, symbol, *, limit):
        self.reads.append(("watch_order_book", symbol, limit))
        if self.update:
            await asyncio.sleep(0.01)
            if self.book_matches_requested_symbol:
                return {**self.book, "symbol": symbol}
            return self.book
        await asyncio.Event().wait()

    async def close(self):
        self.closed = True
        if self.close_error:
            raise RuntimeError("provider close failed")

    async def submit_order(self, *_args, **_kwargs):
        self.submitted_orders += 1

    async def cancel_order(self, *_args, **_kwargs):
        self.cancelled_orders += 1


def test_code_owned_registry_has_a_separate_shadow_runtime(runner):
    registry = runner.runtime_registry()
    replay = registry.require_runtime_dir(REPO / "examples" / "010_live_examples" / "runtime")
    shadow = registry.require_runtime_dir(runner.DEFAULT_RUNTIME_DIR)

    assert replay.allowed_presets == ("replay",)
    assert shadow.allowed_presets == ("shadow",)
    assert shadow.strategy_id == runner.STRATEGY_ID
    assert shadow.runtime_id == runner.RUNTIME_ID
    assert shadow.allowed_secrets_refs == ("none",)
    assert shadow.capability_modules == ()


def test_private_strategy_import_keeps_class_module_in_private_sys_modules(runner):
    registration = runner.runtime_registry().require_runtime_dir(runner.DEFAULT_RUNTIME_DIR)
    public_examples_before = {
        name: module
        for name, module in sys.modules.items()
        if name == "examples" or name.startswith("examples.")
    }
    strategy_name = "examples.010_live_examples.live_mixbroker_okx_demo"
    public_strategy_before = sys.modules.get(strategy_name)

    with _loaded_registered_runner(registration) as loaded_runner:
        root_private_name = loaded_runner.__spec__.name
        assert loaded_runner.__name__ == RUNNER_MODULE
        assert root_private_name != RUNNER_MODULE
        assert sys.modules[root_private_name] is loaded_runner

        strategy_module = loaded_runner.importlib.import_module(strategy_name)
        strategy_private_name = strategy_module.__name__
        strategy_class = strategy_module.LiveMultiSymbolStrategy
        assert strategy_private_name.startswith(root_private_name.rsplit(".", 1)[0] + ".")
        assert strategy_module.__spec__.name == strategy_private_name
        assert sys.modules[strategy_private_name] is strategy_module
        assert strategy_class.__module__ == strategy_private_name
        assert sys.modules[strategy_class.__module__] is strategy_module
        assert sys.modules.get(strategy_name) is public_strategy_before

    public_examples_after = {
        name: module
        for name, module in sys.modules.items()
        if name == "examples" or name.startswith("examples.")
    }
    assert public_examples_after == public_examples_before


@pytest.mark.parametrize(
    "reason",
    (
        "strategy_callback_dependency_unavailable",
        "strategy_callback_initialization_failed",
    ),
)
def test_strategy_callback_initialization_rejections_are_reported_pre_io(
    runner, runtime, monkeypatch, reason
):
    directory, _raw, registry = runtime

    def fail_dispatch(*_args, **_kwargs):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "passive strategy callback initialization failed",
            field_path="runtime.runner",
            reason=reason,
        )

    monkeypatch.setattr(runtime_cli_module, "dispatch_registered_runtime", fail_dispatch)
    errors = io.StringIO()
    status = runtime_cli(
        ["run", "--strategy-dir", str(directory)],
        registry=registry,
        environ={},
        stdout=io.StringIO(),
        stderr=errors,
    )

    assert status == 2
    payload = json.loads(errors.getvalue())
    assert payload["reason"] == reason
    assert payload["diagnostic"]["offline"] is True
    assert payload["diagnostic"]["provider_preflight_started"] is False
    assert "provider_io_may_have_started" not in payload["diagnostic"]


def test_unsealed_runner_call_rejects_before_provider_factory(runner, runtime, monkeypatch):
    directory, _raw, registry = runtime
    called = []

    def provider_factory():
        called.append(True)
        raise AssertionError("provider factory ran before the config seal")

    monkeypatch.setattr(runner, "_new_read_only_client", provider_factory)

    with pytest.raises(RuntimeConfigError) as failure:
        runner.run_runtime(directory, registry=registry)

    assert failure.value.reason == "runner_dispatch_required"
    assert called == []


def test_unapproved_symbol_is_rejected_before_provider_factory(runner, runtime, monkeypatch):
    directory, raw, registry = runtime
    raw["parameters"]["symbols"] = ["BTC/USDT:USDT", "DOGE/USDT:USDT"]
    _write_config(directory, raw)
    effective = validate_runtime_config(directory, registry)
    called = []
    monkeypatch.setattr(runner, "_new_read_only_client", lambda: called.append(True))

    with pytest.raises(RuntimeConfigError) as failure:
        runner.run_runtime(
            directory,
            registry=registry,
            effective=effective,
        )

    assert failure.value.reason == "invalid_symbols"
    assert called == []


def test_public_exchange_options_ignore_credentials_and_proxy_environment(runner, monkeypatch):
    monkeypatch.setenv("OKX_API_KEY", "ignored-key")
    monkeypatch.setenv("OKX_SECRET", "ignored-secret")
    monkeypatch.setenv("OKX_PASSWORD", "ignored-passphrase")
    monkeypatch.setenv("HTTPS_PROXY", "http://user:password@127.0.0.1:15732")

    options = runner._build_exchange_config()

    assert options == {
        "enableRateLimit": True,
        "timeout": 3000,
        "aiohttp_trust_env": False,
        "options": {"defaultType": "swap"},
    }
    assert not {"apiKey", "secret", "password", "httpsProxy", "wsProxy"} & set(options)


def test_ccxt_shadow_in_current_directory_is_rejected_before_import(runner, monkeypatch, tmp_path):
    shadow_package = tmp_path / "ccxt" / "__init__.py"
    monkeypatch.setattr(
        runner.importlib.util,
        "find_spec",
        lambda name: importlib.machinery.ModuleSpec(name, loader=None, origin=str(shadow_package)),
    )

    with pytest.raises(RuntimeConfigError) as failure:
        runner._installed_ccxt_root()

    assert failure.value.reason == "provider_origin_untrusted"


def test_bootstrap_doctor_and_dispatched_run_use_the_valid_safe_default(
    runner, monkeypatch, tmp_path
):
    directory = tmp_path / "runtime-okx-shadow"
    directory.mkdir()
    registration = RegisteredRuntime(
        runtime_dir=directory,
        strategy_id=runner.STRATEGY_ID,
        runtime_id=runner.RUNTIME_ID,
        allowed_presets=("shadow",),
        allowed_parameter_keys=("symbols", "duration_seconds", "orderbook_limit"),
        runner_module=RUNNER_MODULE,
        bootstrap_parameters=(
            ("symbols", ("BTC/USDT:USDT", "ETH/USDT:USDT")),
            ("duration_seconds", 10),
            ("orderbook_limit", 5),
        ),
    )
    registry = RuntimeRegistry((registration,))
    unrelated_cwd = tmp_path / "unrelated"
    unrelated_cwd.mkdir()
    (unrelated_cwd / "config.yaml").write_text("not: a runtime config\n", encoding="utf-8")
    monkeypatch.chdir(unrelated_cwd)

    bootstrap_out = io.StringIO()
    assert (
        runtime_cli(
            ["bootstrap", "--strategy-dir", str(directory)],
            registry=registry,
            environ={},
            stdout=bootstrap_out,
            stderr=io.StringIO(),
        )
        == 0
    )
    bootstrapped = validate_runtime_config(directory, registry)
    assert bootstrapped.preset == "shadow"
    assert dict(bootstrapped.parameters) == {
        "symbols": ("BTC/USDT:USDT", "ETH/USDT:USDT"),
        "duration_seconds": 10,
        "orderbook_limit": 5,
    }

    doctor_out = io.StringIO()
    assert (
        runtime_cli(
            ["doctor", "--strategy-dir", str(directory)],
            registry=registry,
            environ={},
            stdout=doctor_out,
            stderr=io.StringIO(),
        )
        == 0
    )
    assert json.loads(doctor_out.getvalue())["status"] == "diagnostic"

    fast_config = yaml.safe_load((directory / "config.yaml").read_text(encoding="utf-8"))
    fast_config["parameters"]["duration_seconds"] = 1
    _write_config(directory, fast_config)
    fake = FakeMarketClient()
    monkeypatch.setattr(runner, "_new_read_only_client", lambda: fake)
    run_out = io.StringIO()
    run_err = io.StringIO()
    assert (
        runtime_cli(
            ["run", "--strategy-dir", str(directory), "--full-report"],
            registry=registry,
            environ={},
            stdout=run_out,
            stderr=run_err,
        )
        == 0
    )
    payload = json.loads(run_out.getvalue())
    report = payload["report"]["result"]

    assert payload["status"] == "completed"
    assert report["status"] == "PUBLIC_SHADOW_OBSERVED"
    assert report["runtime_config"]["mode"] == "simulation"
    assert report["runtime_config"]["preset"] == "shadow"
    assert report["account_read_calls"] == 0
    assert report["order_write_calls"] == 0
    assert report["cancel_write_calls"] == 0
    assert report["hypothetical_fill_count"] == 0
    assert report["requested_orderbook_limit"] == 5
    strategy_observation = report["strategy_observation"]
    assert strategy_observation["status"] == "CALLBACK_OBSERVED"
    assert strategy_observation["callback"] == "LiveMultiSymbolStrategy.notify_orderbook"
    assert strategy_observation["callback_invocations"] == report["orderbooks_received"]
    assert strategy_observation["callback_stats"]["orderbooks"] == report["orderbooks_received"]
    assert (
        strategy_observation["scope"]
        == "PASSIVE_PUBLIC_ORDERBOOK_CALLBACK_ONLY_NO_CEREBRO_OR_BROKER"
    )
    assert fake.closed
    assert fake.submitted_orders == 0
    assert fake.cancelled_orders == 0


def test_timeout_and_cancellation_resistant_watch_are_bounded(runner, runtime, monkeypatch):
    directory, _raw, registry = runtime
    effective = validate_runtime_config(directory, registry)
    monkeypatch.setattr(runner, "READ_TIMEOUT_SECONDS", 5.0)
    fake = FakeMarketClient(update=False)
    original_watch = fake.watch_order_book

    async def resist_one_cancel(symbol, *, limit):
        try:
            return await original_watch(symbol, limit=limit)
        except asyncio.CancelledError:
            # The first cancellation is ignored. Cleanup must issue a second
            # cancellation and still remain within its explicit wait bound.
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return None

    fake.watch_order_book = resist_one_cancel
    monkeypatch.setattr(runner, "_new_read_only_client", lambda: fake)
    started = time.monotonic()
    with pytest.raises(RuntimeConfigError) as failure:
        runner.run_runtime(
            directory,
            registry=registry,
            effective=effective,
        )
    elapsed = time.monotonic() - started

    assert failure.value.reason == "public_market_observation_empty"
    assert elapsed < 3.0
    assert fake.closed
    assert fake.submitted_orders == 0
    assert fake.cancelled_orders == 0


def test_run_deadline_cancellations_are_not_transport_timeouts(runner, monkeypatch):
    fake = FakeMarketClient(update=False)
    monkeypatch.setattr(runner, "READ_TIMEOUT_SECONDS", 5.0)

    report = asyncio.run(
        runner._observe_public_markets(
            lambda: fake,
            ("BTC/USDT:USDT",),
            0.05,
        )
    )
    counts = report["provider_operation_counts"]

    assert report["status"] == "PUBLIC_SHADOW_NO_UPDATES"
    assert counts["public_market_read_timeouts"] == 0
    assert (
        counts["run_deadline_read_cancellations"] + counts["run_deadline_watcher_cancellations"]
        == 1
    ), counts
    assert counts["provider_startup_timeouts"] == 0
    assert counts["provider_shutdown_timeouts"] == 0
    assert fake.closed


def test_unreviewed_provider_versions_fail_before_client_creation(runner, monkeypatch, tmp_path):
    ccxt_root = tmp_path / "site-packages" / "ccxt"
    aiohttp_root = tmp_path / "site-packages" / "aiohttp"
    ccxt = SimpleNamespace(__file__=str(ccxt_root / "__init__.py"), __version__="4.1.47")
    aiohttp = SimpleNamespace(__file__=str(aiohttp_root / "__init__.py"), __version__="3.13.3")
    ccxtpro = SimpleNamespace(
        __file__=str(ccxt_root / "pro.py"),
        okx=lambda _config: client_constructions.append(True),
    )
    modules = {"ccxt": ccxt, "aiohttp": aiohttp, "ccxt.pro": ccxtpro}
    imports = []
    client_constructions = []

    def import_module(name):
        imports.append(name)
        return modules[name]

    monkeypatch.setattr(runner, "_installed_ccxt_root", lambda: ccxt_root)
    monkeypatch.setattr(runner, "_installed_aiohttp_root", lambda: aiohttp_root)
    monkeypatch.setattr(runner.importlib, "import_module", import_module)

    with pytest.raises(RuntimeConfigError) as failure:
        runner._new_read_only_client()

    assert failure.value.reason == "provider_dependency_version_unreviewed"
    assert "okx-public-shadow" in failure.value.message
    assert imports == ["ccxt", "aiohttp"]
    assert client_constructions == []


@pytest.mark.parametrize(
    "book",
    [
        None,
        {},
        {"symbol": "BTC/USDT:USDT", "bids": [], "asks": [[2.0, 1.0]]},
        {
            "symbol": "BTC/USDT:USDT",
            "bids": [[float("nan"), 1.0]],
            "asks": [[2.0, 1.0]],
        },
        {
            "symbol": "BTC/USDT:USDT",
            "bids": [[1.0, 0.0]],
            "asks": [[2.0, 1.0]],
        },
        {
            "symbol": "DOGE/USDT:USDT",
            "bids": [[1.0, 1.0]],
            "asks": [[2.0, 1.0]],
        },
        {"bids": [[1.0, 1.0]], "asks": [[2.0, 1.0]]},
    ],
)
def test_malformed_or_empty_books_do_not_count_as_observations(runner, runtime, book, monkeypatch):
    directory, _raw, registry = runtime
    effective = validate_runtime_config(directory, registry)
    fake = FakeMarketClient(book=book)
    monkeypatch.setattr(runner, "_new_read_only_client", lambda: fake)

    with pytest.raises(RuntimeConfigError) as failure:
        runner.run_runtime(
            directory,
            registry=registry,
            effective=effective,
        )

    assert failure.value.reason == "public_market_read_failed"
    assert fake.closed
    assert fake.submitted_orders == 0
    assert fake.cancelled_orders == 0


def test_startup_timeout_closes_client_and_never_reaches_order_methods(
    runner, runtime, monkeypatch
):
    directory, _raw, registry = runtime
    effective = validate_runtime_config(directory, registry)
    monkeypatch.setattr(runner, "STARTUP_TIMEOUT_SECONDS", 0.05)
    fake = FakeMarketClient()

    async def stalled_startup():
        await asyncio.Event().wait()

    fake.load_markets = stalled_startup
    monkeypatch.setattr(runner, "_new_read_only_client", lambda: fake)
    started = time.monotonic()
    with pytest.raises(RuntimeConfigError) as failure:
        runner.run_runtime(
            directory,
            registry=registry,
            effective=effective,
        )

    assert failure.value.reason == "public_market_startup_incomplete"
    assert time.monotonic() - started < 3.0
    assert fake.closed
    assert fake.submitted_orders == 0
    assert fake.cancelled_orders == 0


def test_startup_error_closes_client_and_fails_dispatched_run(runner, runtime, monkeypatch):
    directory, _raw, registry = runtime
    effective = validate_runtime_config(directory, registry)
    fake = FakeMarketClient()

    async def failed_startup():
        raise RuntimeError("market metadata unavailable")

    fake.load_markets = failed_startup
    monkeypatch.setattr(runner, "_new_read_only_client", lambda: fake)
    with pytest.raises(RuntimeConfigError) as failure:
        runner.run_runtime(
            directory,
            registry=registry,
            effective=effective,
        )

    assert failure.value.reason == "public_market_startup_incomplete"
    assert fake.closed
    assert fake.submitted_orders == 0
    assert fake.cancelled_orders == 0


def test_provider_close_failure_fails_dispatched_run(runner, runtime, monkeypatch):
    directory, _raw, registry = runtime
    effective = validate_runtime_config(directory, registry)
    fake = FakeMarketClient(close_error=True)
    monkeypatch.setattr(runner, "READ_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(runner, "_new_read_only_client", lambda: fake)

    with pytest.raises(RuntimeConfigError) as failure:
        runner.run_runtime(
            directory,
            registry=registry,
            effective=effective,
        )

    assert failure.value.reason == "provider_shutdown_incomplete"
    assert fake.closed
    assert fake.submitted_orders == 0
    assert fake.cancelled_orders == 0


def test_real_cli_fails_closed_when_public_stream_never_produces_a_book(
    runner, runtime, monkeypatch
):
    directory, _raw, registry = runtime
    monkeypatch.setattr(runner, "READ_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(runner, "_new_read_only_client", lambda: FakeMarketClient(update=False))
    errors = io.StringIO()

    exit_code = runtime_cli(
        ["run", "--strategy-dir", str(directory)],
        registry=registry,
        environ={},
        stdout=io.StringIO(),
        stderr=errors,
    )

    assert exit_code == 2
    payload = json.loads(errors.getvalue())
    assert payload["reason"] == "public_market_observation_empty"


def test_real_read_only_client_wrapper_exposes_no_execution_methods(runner):
    exchange = FakeMarketClient()
    client = runner._ReadOnlyMarketClient(exchange)

    assert callable(client.load_markets)
    assert callable(client.watch_order_book)
    assert callable(client.close)
    assert not hasattr(client, "submit_order")
    assert not hasattr(client, "cancel_order")
    assert not hasattr(client, "create_order")


def test_strategy_callback_observer_has_no_broker_or_order_action(runner):
    symbol = "BTC/USDT:USDT"
    observer = runner._new_strategy_callback_observer((symbol,))

    assert observer.p.symbols == (symbol,)
    assert not hasattr(observer, "broker")
    assert not hasattr(observer, "cerebro")
    assert not hasattr(observer, "env")
    for action in runner._STRATEGY_ORDER_ACTIONS:
        with pytest.raises(RuntimeConfigError) as failure:
            getattr(observer, action)()
        assert failure.value.reason == "shadow_order_action_disabled"


@pytest.mark.parametrize(
    ("error_factory", "expected_reason"),
    (
        pytest.param(
            lambda: ModuleNotFoundError("No module named 'pytz'", name="pytz"),
            "strategy_callback_dependency_unavailable",
            id="missing-dependency",
        ),
        pytest.param(
            lambda: RuntimeError("callback import failed"),
            "strategy_callback_initialization_failed",
            id="callback-initialization",
        ),
    ),
)
def test_strategy_callback_initialization_fails_before_provider_creation(
    runner, monkeypatch, error_factory, expected_reason
):
    imports = []
    providers = []

    def failed_import(name):
        imports.append(name)
        raise error_factory()

    monkeypatch.setattr(runner.importlib, "import_module", failed_import)

    async def observe():
        return await runner._observe_public_markets(
            lambda: providers.append(True),
            ("BTC/USDT:USDT",),
            1,
        )

    with pytest.raises(RuntimeConfigError) as failure:
        asyncio.run(observe())

    assert failure.value.reason == expected_reason
    if expected_reason == "strategy_callback_dependency_unavailable":
        assert 'pip install -e ".[okx-public-shadow]"' in failure.value.message
    assert imports == ["examples.010_live_examples.live_mixbroker_okx_demo"]
    assert providers == []


def test_callback_stats_must_match_the_invocations(runner):
    symbol = "BTC/USDT:USDT"
    fake = FakeMarketClient()

    class InconsistentObserver:
        def notify_orderbook(self, _event):
            pass

        def get_stats(self):
            return {"orderbooks": {}}

    report = asyncio.run(
        runner._observe_public_markets(
            lambda: fake,
            (symbol,),
            0.05,
            observer_factory=lambda _symbols: InconsistentObserver(),
        )
    )

    assert report["strategy_observation"]["callback_invocations"][symbol] > 0
    assert report["strategy_observation"]["status"] == "CALLBACK_EVIDENCE_INVALID"
    assert report["provider_operation_counts"]["public_read_errors"] == 1
    assert fake.closed


def test_strategy_callback_receives_only_the_requested_public_depth(runner):
    symbol = "BTC/USDT:USDT"
    book = {
        "symbol": symbol,
        "bids": [[float(100 - i), 1.0] for i in range(8)],
        "asks": [[float(101 + i), 1.0] for i in range(8)],
    }
    received = []

    class CallbackObserver:
        def notify_orderbook(self, event):
            received.append(event)

        def get_stats(self):
            return {"orderbooks": {symbol: sum(1 for event in received if event.symbol == symbol)}}

    fake = FakeMarketClient(book=book)
    report = asyncio.run(
        runner._observe_public_markets(
            lambda: fake,
            (symbol,),
            0.05,
            observer_factory=lambda _symbols: CallbackObserver(),
        )
    )

    assert received
    assert all(len(event.data[side]) == 5 for event in received for side in ("bids", "asks"))
    assert all(event.symbol == symbol for event in received)
    assert report["strategy_observation"]["callback_invocations"][symbol] == len(received)
    assert fake.submitted_orders == 0
    assert fake.cancelled_orders == 0

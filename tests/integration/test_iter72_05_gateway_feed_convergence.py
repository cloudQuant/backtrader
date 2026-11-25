"""Iteration 72.05 INTEGRATION_SIM: Backtrader Feed convergence after Gateway MD disconnect.

Proves against the real CURVE synthetic Gateway (pinned to committed SDK fixture
``bt_api_py@896549b2``) and real ``BtApiFeed`` + ``GatewayMarketAdapter`` +
``GatewayMarketSubscriptionClient``:
1. Both ``IF2612`` and ``IH2612`` Feeds enter ``LIVE`` on ``connection_generation=1``.
2. An MD disconnect is injected while an owner market poll is in flight; Gateway
   reconnects on ``connection_generation=2`` and starts the convergence timer.
3. Both Backtrader Feeds observe ``DELAYED`` on the old epoch without implicit
   resync, then execute explicit ``acknowledge_data_loss=True`` resync, receive
   fresh ticks on ``connection_generation=2``, and return to ``LIVE`` well within
   the 30-second convergence budget (72.05 DoD #1).
4. Without a bound clock verification proof, ``feed.trade_qualification().ok``
   remains ``False`` even after ``LIVE`` data continuity recovers (72.05 DoD #3).
5. Gateway child process closes cleanly with exit code 0 and zero cleanup errors.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


_SDK_COMMIT = "896549b2"
_SDK_HELPER_PATH = "tests/integration/test_iter63_ctp_gateway_joint_service.py"
_SDK_HELPER_BLOB = "180af2915b9377e326e5da500397a0758842e9aa"
_RESULT_PREFIX = "ITER72_05_FEED_CONVERGENCE_RESULT="
_CONVERGENCE_BUDGET_SECONDS = 30.0


def _sdk_repo_root() -> Path:
    configured = os.environ.get("BT_API_PY_ROOT")
    return Path(configured) if configured else Path("D:/bt_api_py")


def _add_sdk_paths(sdk_root: Path) -> None:
    roots = [sdk_root, sdk_root / "tests"]
    roots.extend(sorted((sdk_root / "bt_api").glob("bt_api_*/src")))
    for root in reversed(roots):
        value = str(root.resolve())
        if value in sys.path:
            sys.path.remove(value)
        sys.path.insert(0, value)


def _load_committed_sdk_fixture(sdk_root: Path):
    import types

    _add_sdk_paths(sdk_root)
    source = subprocess.check_output(
        ["git", "show", f"{_SDK_COMMIT}:{_SDK_HELPER_PATH}"],
        cwd=sdk_root,
    )
    blob = hashlib.sha1(
        b"blob " + str(len(source)).encode("ascii") + b"\0" + source
    ).hexdigest()
    if blob != _SDK_HELPER_BLOB:
        raise RuntimeError("PINNED_SDK_FIXTURE_BLOB_MISMATCH")

    module_name = "tests.integration.test_iter63_ctp_gateway_joint_service"
    module = sys.modules.get(module_name)
    if module is not None:
        return module
    module = types.ModuleType(module_name)
    module.__file__ = str(sdk_root / _SDK_HELPER_PATH)
    module.__package__ = "tests.integration"
    sys.modules[module_name] = module
    try:
        exec(compile(source, module.__file__, "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


def _gateway_process_target(sdk_root_text: str, *args) -> None:
    sdk_root = Path(sdk_root_text)
    fixture = _load_committed_sdk_fixture(sdk_root)
    ctp_tests = sdk_root / "bt_api" / "bt_api_ctp" / "tests"
    if str(ctp_tests) not in sys.path:
        sys.path.insert(0, str(ctp_tests))
    import test_market_provider

    orig_emit = test_market_provider._SyntheticMdClient.emit_tick
    counters: dict[str, int] = {}

    def complete_quote_emit(self, *e_args, **kwargs):
        sym = str(kwargs.get("InstrumentID") or "")
        seq = counters.get(sym, 0) + 1
        counters[sym] = seq
        last = float(kwargs.get("LastPrice", 4001.0))
        kwargs.setdefault("BidPrice1", round(last - 0.2, 1))
        kwargs.setdefault("AskPrice1", round(last + 0.2, 1))
        kwargs.setdefault("BidVolume1", 5)
        kwargs.setdefault("AskVolume1", 5)
        kwargs.setdefault("UpperLimitPrice", 4500.0)
        kwargs.setdefault("LowerLimitPrice", 3500.0)
        kwargs.setdefault("PreSettlementPrice", 4000.0)
        kwargs.setdefault("OpenPrice", 4000.0)
        kwargs.setdefault("HighestPrice", max(4000.0, last))
        kwargs.setdefault("LowestPrice", min(4000.0, last))
        kwargs.setdefault("OpenInterest", 1000.0)
        kwargs["Volume"] = 100 + seq * 2
        kwargs.setdefault("Turnover", round(last * (100 + seq * 2) * 300.0, 2))
        kwargs["UpdateTime"] = f"09:30:{min(59, seq):02d}"
        return orig_emit(self, *e_args, **kwargs)

    test_market_provider._SyntheticMdClient.emit_tick = complete_quote_emit
    fixture._gateway(*args)


class _DispatchSink:
    def __init__(self) -> None:
        self.events = []
        self.datas = ()
        self._tradingcal = None

    def dispatch_channel_event(self, event) -> None:
        self.events.append(event)


class _GatewayApiFacade:
    def __init__(self, session) -> None:
        self._session = session

    def market_subscription(self, _route, name: str):
        return self._session.market_client.subscription(name)


class _GatewayStoreFacade:
    def __init__(self, config, api) -> None:
        self._gateway_strategy_config = config
        self.gateway_strategy_config = config
        self.gateway_api = api
        self.gateway_session_generation = 1
        self._started = True

    def start(self, *, data=None):
        return None


def _drain_statuses(feed) -> list[int]:
    return [status for status, _args, _kwargs in feed.get_notifications()]


def _pump_feed(feed, predicate, *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        feed._load()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("GATEWAY_FEED_EVENT_TIMEOUT")


def _run_convergence_scenario(sdk_root: Path, temp_root: Path) -> None:
    _add_sdk_paths(sdk_root)
    fixture = _load_committed_sdk_fixture(sdk_root)
    bt_root = Path(__file__).resolve().parents[2]
    bt_root_text = str(bt_root.resolve())
    if bt_root_text in sys.path:
        sys.path.remove(bt_root_text)
    sdk_path_count = 2 + len(list((sdk_root / "bt_api").glob("bt_api_*/src")))
    sys.path.insert(sdk_path_count, bt_root_text)

    import multiprocessing
    import queue
    from types import SimpleNamespace

    import zmq
    from bt_api_gateway.direct_command_journal import GatewayDirectCommandJournal
    from bt_api_py.gateway_strategy_market import (
        GatewayMarketClientSettings,
        GatewayMarketSubscriptionClient,
        GatewayMarketSubscriptionSettings,
    )
    from bt_api_py.order_correlation_issuer import DurableOrderCorrelationIssuer
    import backtrader as bt
    from backtrader.feeds.btapifeed import BtApiFeed

    temp_root.mkdir(parents=True, exist_ok=True)
    fixture._secure_tmp_path(temp_root)
    (temp_root / "guard").mkdir(exist_ok=True)
    (temp_root / "flow").mkdir(exist_ok=True)
    journal = GatewayDirectCommandJournal.create(
        temp_root / "orders.sqlite", fixture.SCOPE, generation="provisioned"
    )
    issuer = DurableOrderCorrelationIssuer(temp_root / "identity.sqlite")
    issuer_id = issuer.issuer_id
    issuer.close()

    rpc, market_endpoint = fixture._free_endpoint(), fixture._free_endpoint()
    server_keys = zmq.curve_keypair()
    client_keys = (zmq.curve_keypair(), zmq.curve_keypair(), zmq.curve_keypair())
    ctx = multiprocessing.get_context("spawn")
    poll_armed, poll_entered, poll_release = ctx.Event(), ctx.Event(), ctx.Event()
    dequeued = ctx.Value("i", 0)
    maintenance_entered = ctx.Event()
    events, controls = ctx.Queue(), ctx.Queue()
    blocked_poll = (poll_armed, poll_entered, poll_release, dequeued, maintenance_entered)
    gateway = ctx.Process(
        target=_gateway_process_target,
        args=(
            str(sdk_root),
            str(temp_root),
            rpc,
            market_endpoint,
            server_keys,
            client_keys,
            journal.journal_id,
            issuer_id,
            events,
            controls,
            None,
            blocked_poll,
        ),
    )

    session = None
    feeds = []
    ack_calls = []
    original_accept_resync = GatewayMarketSubscriptionClient.accept_resync
    received_by_feed = {}
    try:
        gateway.start()
        ready = events.get(timeout=20)
        assert ready == ("ready", gateway.pid) and gateway.pid != os.getpid(), ready

        session = fixture._session(
            fixture.CLIENT_A,
            client_keys[0],
            server_keys[0],
            rpc,
            market_endpoint,
            journal.journal_id,
            "IF2612",
            temp_root,
        )
        session.start(timeout_seconds=10)

        subscriptions = {
            "ticks": GatewayMarketSubscriptionSettings(
                fixture._key("IF2612"), require_source_descriptor=True
            ),
            "second_ticks": GatewayMarketSubscriptionSettings(
                fixture._key("IH2612"), require_source_descriptor=True
            ),
        }
        settings = GatewayMarketClientSettings(subscriptions, fixture.MARKET_OPS)
        instruments = {
            item.key.instrument.instrument_id: item.key.instrument
            for item in subscriptions.values()
        }
        config = SimpleNamespace(
            exchange_name="gateway-a",
            market_settings=settings,
            instruments_by_ref=instruments,
            route=session.route,
            peer=fixture.SERVICE,
        )
        store = _GatewayStoreFacade(config, _GatewayApiFacade(session))

        for symbol in ("IF2612", "IH2612"):
            sink = _DispatchSink()
            feed = BtApiFeed(
                dataname=symbol,
                store=store,
                provider="btapi",
                timeframe=bt.TimeFrame.Ticks,
                backfill_start=False,
                qcheck=0.0,
                price_tick=0.2,
                gateway_clock_verification=None,
            )
            feed._env = sink
            feed._start()
            feeds.append(feed)
            received_by_feed[symbol] = sink.events
        feeds_by_symbol = dict(zip(("IF2612", "IH2612"), feeds))

        def _tick_events(sym: str):
            return [ev for ev in received_by_feed[sym] if hasattr(ev.data, "last_price")]

        for symbol, price in (("IF2612", 4120.0), ("IH2612", 4121.0)):
            controls.put(("tick", symbol, price))
            assert events.get(timeout=5) == ("tick", symbol, price)
            feed = feeds_by_symbol[symbol]
            _pump_feed(
                feed,
                lambda s=symbol, p=price: bool(_tick_events(s)) and float(_tick_events(s)[-1].data.last_price) == p,
            )
            ev0 = _tick_events(symbol)[-1].data
            assert float(ev0.last_price) == price
            statuses = _drain_statuses(feed)
            assert feed.LIVE in statuses, (
                symbol, statuses, getattr(feed, "_laststatus", None),
                getattr(ev0, "data_quality", None),
                getattr(ev0, "quality_flags", None),
                getattr(ev0, "continuity", None),
                getattr(ev0, "stale", None),
                getattr(ev0, "stale_reason", None),
                getattr(ev0, "execution_eligible", None),
                feed._gateway_market_adapter.recovery_reason(),
                getattr(feed, "_continuity_degraded", None),
            )
            assert feed._gateway_market_adapter._projector._source.connection_generation == 1

        def observed_accept_resync(self, *, acknowledge_data_loss, timeout_seconds=5.0):
            ack_calls.append((id(self), acknowledge_data_loss))
            return original_accept_resync(
                self,
                acknowledge_data_loss=acknowledge_data_loss,
                timeout_seconds=timeout_seconds,
            )

        GatewayMarketSubscriptionClient.accept_resync = observed_accept_resync
        controls.put("arm_recovery_trace")
        armed = events.get(timeout=5)
        assert armed[0] == "recovery_trace_armed", armed
        poll_armed.set()
        controls.put(("tick", "IF2612", 4123.0))
        assert events.get(timeout=5) == ("tick", "IF2612", 4123.0)
        assert poll_entered.wait(5) and maintenance_entered.wait(5)
        assert dequeued.value == 1

        controls.put("md_disconnect")
        md_fault = events.get(timeout=5)
        assert md_fault[:3] == ("md_disconnected", 1, 1), md_fault
        old_epochs = {
            symbol: feeds_by_symbol[symbol]._gateway_market_adapter._projector._source.epoch
            for symbol in ("IF2612", "IH2612")
        }

        poll_release.set()
        t_owner_reconnect_start = time.monotonic()
        controls.put(("drive_md_recovery", 1, 1))
        recovered = events.get(timeout=12)
        assert recovered[0] == "md_reconnected", recovered
        new_generation = recovered[3]
        assert new_generation > 1, recovered
        t_owner_recovered = time.monotonic()

        for symbol in ("IF2612", "IH2612"):
            feed = feeds_by_symbol[symbol]
            # Drain any pre-disconnect buffered tick until the Feed observes
            # the rotated source epoch and emits DELAYED (still on old epoch,
            # before any explicit resync acknowledgement).
            seen_delayed = []
            def _wait_delayed(f=feed, bucket=seen_delayed):
                sts = _drain_statuses(f)
                if f.DELAYED in sts:
                    bucket.append(True)
                    return True
                return False
            _pump_feed(feed, _wait_delayed, timeout=10.0)
            assert seen_delayed
            adapter = feed._gateway_market_adapter
            assert adapter._projector._source.connection_generation == 1
            assert adapter._projector._source.epoch == old_epochs[symbol]
            assert not ack_calls

        resync_live_seen = {}
        for symbol in ("IF2612", "IH2612"):
            feed = feeds_by_symbol[symbol]
            _pump_feed(
                feed,
                lambda f=feed: f._gateway_market_adapter._projector._source.connection_generation == new_generation,
                timeout=10.0,
            )
            resync_live_seen[symbol] = feed.LIVE in _drain_statuses(feed)
            adapter = feed._gateway_market_adapter
            assert adapter._projector._source.connection_generation == new_generation
            assert adapter._projector._source.epoch != old_epochs[symbol]

        assert len(ack_calls) == 2 and all(ack is True for _client, ack in ack_calls), ack_calls

        post_resync_counts = {
            symbol: len(_tick_events(symbol)) for symbol in ("IF2612", "IH2612")
        }
        for symbol, price in (("IF2612", 4124.0), ("IH2612", 4125.0)):
            controls.put(("tick", symbol, price))
            assert events.get(timeout=5) == ("tick", symbol, price)
            feed = feeds_by_symbol[symbol]
            _pump_feed(
                feed,
                lambda s=symbol, count=post_resync_counts[symbol], p=price: (
                    len(_tick_events(s)) > count and float(_tick_events(s)[-1].data.last_price) == p
                ),
            )
            delivered = _tick_events(symbol)[post_resync_counts[symbol]:]
            assert len(delivered) >= 1
            assert float(delivered[-1].data.last_price) == price
            adapter = feed._gateway_market_adapter
            assert adapter._projector._source.connection_generation == new_generation
            assert adapter._projector._source.epoch != old_epochs[symbol]
            assert resync_live_seen[symbol] or (feed.LIVE in _drain_statuses(feed))
            assert feed._laststatus == feed.LIVE
            assert feed.trade_qualification().ok is False

        convergence_from_owner_s = round(time.monotonic() - t_owner_recovered, 3)
        total_recovery_s = round(time.monotonic() - t_owner_reconnect_start, 3)
        assert convergence_from_owner_s <= _CONVERGENCE_BUDGET_SECONDS
        assert total_recovery_s <= _CONVERGENCE_BUDGET_SECONDS

        print(
            _RESULT_PREFIX
            + json.dumps(
                {
                    "all_resync_acknowledged_data_loss": True,
                    "convergence_from_owner_s": convergence_from_owner_s,
                    "feed_live_after_fresh_tick": True,
                    "new_generation": new_generation,
                    "old_generation": 1,
                    "resync_acknowledgements": len(ack_calls),
                    "symbols": ["IF2612", "IH2612"],
                    "total_recovery_s": total_recovery_s,
                    "trade_qualification_remains_false": True,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    finally:
        GatewayMarketSubscriptionClient.accept_resync = original_accept_resync
        poll_release.set()
        for feed in feeds:
            try:
                feed.stop()
            except Exception:
                pass
        if session is not None:
            session.close(timeout_seconds=10)
        try:
            controls.put("stop")
        except Exception:
            pass
        gateway.join(15)
        if gateway.is_alive():
            gateway.terminate()
            gateway.join(5)
            raise AssertionError("SYNTHETIC_GATEWAY_PROCESS_DID_NOT_STOP")
        remaining = []
        while True:
            try:
                remaining.append(events.get_nowait())
            except queue.Empty:
                break
        assert gateway.exitcode == 0 and not any(
            item[0] in {"error", "cleanup_error"} for item in remaining
        ), remaining
        assert ("closed", 1) in remaining, remaining


def test_iter72_05_gateway_md_disconnect_feed_converges_within_30s(tmp_path):
    sdk_root = _sdk_repo_root()
    if not (sdk_root / ".git").is_dir():
        pytest.skip("local bt_api_py checkout is required for the synthetic CURVE fixture")
    script = Path(__file__).resolve()
    temp_root = tmp_path / "iter72-05-feed-convergence"
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-u", str(script), "--run-iter72-05", str(sdk_root), str(temp_root)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    rows = [
        line[len(_RESULT_PREFIX):]
        for line in result.stdout.splitlines()
        if line.startswith(_RESULT_PREFIX)
    ]
    assert len(rows) == 1, result.stdout
    summary = json.loads(rows[0])
    assert summary["old_generation"] == 1
    assert summary["new_generation"] == 2
    assert summary["symbols"] == ["IF2612", "IH2612"]
    assert summary["resync_acknowledgements"] == 2
    assert summary["all_resync_acknowledged_data_loss"] is True
    assert summary["feed_live_after_fresh_tick"] is True
    assert summary["trade_qualification_remains_false"] is True
    assert summary["convergence_from_owner_s"] <= _CONVERGENCE_BUDGET_SECONDS
    assert summary["total_recovery_s"] <= _CONVERGENCE_BUDGET_SECONDS


if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "--run-iter72-05":
    _run_convergence_scenario(Path(sys.argv[2]), Path(sys.argv[3]))

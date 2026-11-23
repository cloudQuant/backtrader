"""Dual-mode Feed parity, port boundaries, non-live isolation, and live_state mode stamp tests (T-028/T-029).

Covers:
- S-02 / S-10: DirectBtApiFeed vs GatewayBtApiFeed OHLCV & strategy callback parity
- T-025: MarketSourcePort (DirectMarketSourcePort vs GatewayMarketSourcePort + 0.02s idle backoff + capability negative matrix)
- T-026: CalendarQueryPort (LocalCalendarQueryPort vs GatewayCalendarQueryPort rejecting mixed feed_scope)
- D62S-08a: Standalone non-live ReplayBtApiFeed & ServiceReadOnlyStore isolation
- S-06: isinstance hierarchy & zero-metaclass-conflict checks
- T-028 / R62S-11: live_state immutable mode stamp (v1 -> v2 upgrade, LiveStateModeMismatch, Gateway pending.json refusal in direct mode)
"""

from __future__ import annotations

import datetime as dt
import socket
import time
from pathlib import Path
from typing import List

import pytest
import yaml

import backtrader as bt
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.market_protocol import MarketInstrumentKey

from backtrader.feeds import (
    BaseBtApiFeed,
    BtApiFeed,
    DirectBtApiFeed,
    GatewayBtApiFeed,
    ReplayBtApiFeed,
)
from backtrader.feeds._calendar_query_port import (
    GatewayCalendarQueryPort,
    LocalCalendarQueryPort,
)
from backtrader.feeds._market_source_port import (
    GATEWAY_IDLE_POLL_SECONDS,
    DirectMarketSourcePort,
    GatewayMarketSourcePort,
)
from backtrader.live_state import (
    IDENTITY_MODE_VERSION,
    LiveStateError,
    LiveStateModeMismatch,
    StrategyStateDir,
    initialize_identity,
    load_identity,
    read_audit,
    stamp_identity_mode,
)
from backtrader.live_state.gateway_pending import GatewayPendingHost
from backtrader.stores import (
    BaseBtApiStore,
    GatewayReadinessProof,
    LiveCompositionError,
    ProcessModeFence,
    ServiceReadOnlyStore,
    create_direct_store,
    create_gateway_store,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_GATEWAY_YAML = REPO_ROOT / "examples/live/007_ctp/sa_dual_ma_gateway/config.yaml"


@pytest.fixture(autouse=True)
def _guard_env(monkeypatch):
    ProcessModeFence._reset_for_tests()

    def _forbid_socket(*args, **kwargs):
        raise AssertionError("Offline parity/isolation tests must never open sockets")

    monkeypatch.setattr(socket, "socket", _forbid_socket)
    monkeypatch.setattr(socket, "create_connection", _forbid_socket)
    yield
    ProcessModeFence._reset_for_tests()


def _make_gateway_store(tmp_path: Path, *, mode_stamp: str | None = "gateway"):
    state = StrategyStateDir.initialize(tmp_path, mode=mode_stamp)
    raw = yaml.safe_load(SAMPLE_GATEWAY_YAML.read_text(encoding="utf-8"))
    text = yaml.safe_dump(raw, sort_keys=False).replace(
        "replace-with-registered-strategy-uuid", state.strategy_uuid
    )
    cfg = yaml.safe_load(text)
    cfg["mode"] = "gateway"
    gw_b = cfg["gateway_strategy"]["binding"]
    binding = GatewayCommandBinding(
        journal_id=gw_b["journal_id"],
        account_scope=gw_b["account_scope"],
        strategy_scope=gw_b["strategy_scope"],
        principal=gw_b["principal"],
    )
    host = GatewayPendingHost.upgrade_for_gateway(state.strategy_dir, state.strategy_uuid, binding)
    profiles = {
        "security": {"role": "client"},
        "risk-security": {"role": "client"},
        "execution-security": {"role": "client"},
    }
    now_ns = time.time_ns()
    proof = GatewayReadinessProof(
        schema_version=1,
        proof_generation=1,
        issued_at_ns=now_ns - 1_000_000,
        expires_at_ns=now_ns + 60_000_000_000,
        gateway_service_id="gateway",
        gateway_instance_id="instance",
        gateway_scope_ref="scope",
        account_scope=binding.account_scope,
        strategy_scope=binding.strategy_scope,
        route="CTP___FUTURE",
        strategy_principal_has_submit=False,
        strategy_principal_has_reserve=False,
        delegated_cancel_enabled=True,
        risk_required=True,
        risk_service_ref="risk-a",
        risk_protocol_version="v1",
        risk_state="READY",
        execution_required=True,
        execution_service_ref="execution-a",
        execution_protocol_version="v2",
        execution_state="READY",
        execution_direct_path_disabled=True,
        monitor_required=True,
        monitor_service_ref="monitor-a",
        monitor_protocol_version="v1",
        last_acked_heartbeat_age_ms=100,
        monitor_stop_new_active=False,
        runtime_supervision_expected=True,
        runtime_service_ref="runtime-a",
        registered_run_id="run-parity",
    )
    store = create_gateway_store(
        config=cfg,
        gateway_host=host,
        gateway_security_profiles=profiles,
        gateway_readiness_proof=proof,
        expected_run_id="run-parity",
        enforce_process_fence=False,
    )
    return store, state


# ---------------------------------------------------------------------------
# Feed Parity & MarketSourcePort / CalendarQueryPort
# ---------------------------------------------------------------------------


def test_direct_and_gateway_feed_ports_and_isinstance_hierarchy(tmp_path):
    direct_store = create_direct_store(
        config={"mode": "direct", "exchange_kwargs": {"CTP___FUTURE": {}}},
        enforce_process_fence=False,
    )
    gateway_store, _ = _make_gateway_store(tmp_path)

    direct_feed = direct_store.getdata(dataname="SA701", backfill_start=False)
    gateway_feed = gateway_store.getdata(dataname="SA701")

    assert isinstance(direct_feed, DirectBtApiFeed)
    assert isinstance(direct_feed, BtApiFeed)
    assert isinstance(direct_feed, BaseBtApiFeed)
    assert not isinstance(direct_feed, GatewayBtApiFeed)
    assert isinstance(direct_feed.market_source_port, DirectMarketSourcePort)
    assert isinstance(direct_feed.calendar_query_port, LocalCalendarQueryPort)
    assert direct_feed.run_binding is direct_store.run_binding
    assert direct_feed.live_mode == "direct"

    assert isinstance(gateway_feed, GatewayBtApiFeed)
    assert isinstance(gateway_feed, BtApiFeed)
    assert isinstance(gateway_feed, BaseBtApiFeed)
    assert not isinstance(gateway_feed, DirectBtApiFeed)
    assert isinstance(gateway_feed.market_source_port, GatewayMarketSourcePort)
    assert isinstance(gateway_feed.calendar_query_port, GatewayCalendarQueryPort)
    assert gateway_feed.market_source_port.idle_poll_seconds == GATEWAY_IDLE_POLL_SECONDS
    assert gateway_feed.market_source_port.idle_poll_seconds == 0.02
    assert gateway_feed.run_binding is gateway_store.run_binding
    assert gateway_feed.live_mode == "gateway"


def test_direct_and_gateway_feed_cross_binding_rejected(tmp_path):
    direct_store = create_direct_store(
        config={"mode": "direct", "exchange_kwargs": {"CTP___FUTURE": {}}},
        enforce_process_fence=False,
    )
    gateway_store, _ = _make_gateway_store(tmp_path)

    with pytest.raises(LiveCompositionError) as exc1:
        direct_store.getdata(dataname="SA701", data_cls=GatewayBtApiFeed)
    assert exc1.value.code == "RUN_BINDING_MISMATCH"

    with pytest.raises(LiveCompositionError) as exc2:
        gateway_store.getdata(dataname="SA701", data_cls=DirectBtApiFeed)
    assert exc2.value.code == "RUN_BINDING_MISMATCH"

    with pytest.raises(LiveCompositionError) as exc3:
        DirectBtApiFeed(dataname="SA701", store=gateway_store)
    assert exc3.value.code == "RUN_BINDING_MISMATCH"

    with pytest.raises(LiveCompositionError) as exc4:
        GatewayBtApiFeed(dataname="SA701", store=direct_store)
    assert exc4.value.code == "RUN_BINDING_MISMATCH"


@pytest.mark.parametrize(
    "bad_kwargs",
    [
        {"backfill_start": True},
        {"orderbook_as_ticks": True},
        {"cohort_source_mode": True, "historical_bars": (), "live_bars": ()},
        {"closed_bar_quote_capture": True},
        {"historical_bars": [{"datetime": dt.datetime(2026, 11, 1, 9, 0, tzinfo=dt.timezone.utc), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]},
    ],
)
def test_gateway_feed_capability_negative_matrix(bad_kwargs):
    with pytest.raises(ValueError, match="GATEWAY_MARKET_FEED_CONFIGURATION_UNSUPPORTED"):
        GatewayBtApiFeed(dataname="SA701", **bad_kwargs)


def test_gateway_feed_forbids_local_calendar_scope_overrides():
    for field in ("calendar_route", "calendar_venue", "calendar_kind", "calendar_product", "calendar_contract"):
        with pytest.raises(LiveCompositionError) as exc:
            GatewayBtApiFeed(dataname="SA701", **{field: "CZCE"})
        assert exc.value.code == "CALENDAR_SCOPE_CONFLICT"


def test_direct_feed_forbids_gateway_only_options():
    with pytest.raises(LiveCompositionError) as exc1:
        DirectBtApiFeed(dataname="SA701", gateway_clock_verification=True)
    assert exc1.value.code == "MODE_CONFLICT"

    with pytest.raises(LiveCompositionError) as exc2:
        DirectBtApiFeed(dataname="SA701", allow_stale_market_feed=True)
    assert exc2.value.code == "MODE_CONFLICT"

    feed = DirectBtApiFeed(dataname="SA701")
    with pytest.raises(LiveCompositionError) as exc3:
        feed.instrument_status_observation()
    assert exc3.value.code == "MODE_CONFLICT"


def test_dual_mode_feed_bar_projection_parity():
    """Same bar payload sequence produces identical OHLCV lines across Direct and Gateway Feeds."""
    bars = [
        {
            "datetime": dt.datetime(2026, 11, 1, 9, 1, tzinfo=dt.timezone.utc),
            "open": 1500.0,
            "high": 1510.0,
            "low": 1495.0,
            "close": 1505.0,
            "volume": 120.0,
            "bar_final": True,
        },
        {
            "datetime": dt.datetime(2026, 11, 1, 9, 2, tzinfo=dt.timezone.utc),
            "open": 1505.0,
            "high": 1512.0,
            "low": 1500.0,
            "close": 1508.0,
            "volume": 85.0,
            "bar_final": True,
        },
    ]

    class _Recorder(bt.Strategy):
        def __init__(self):
            self.rows: List[tuple] = []

        def next(self):
            self.rows.append(
                (
                    float(self.data.open[0]),
                    float(self.data.high[0]),
                    float(self.data.low[0]),
                    float(self.data.close[0]),
                    float(self.data.volume[0]),
                )
            )

    def _run_feed(feed_obj):
        cerebro = bt.Cerebro()
        cerebro.adddata(feed_obj, name="SA701")
        cerebro.addstrategy(_Recorder)
        strats = cerebro.run()
        return strats[0].rows

    # Direct feed via historical_bars (finite load once drained)
    direct_feed = DirectBtApiFeed(dataname="SA701", backfill_start=False, historical_bars=bars)
    orig_direct_load = direct_feed._load

    def _finite_direct_load():
        if not direct_feed._history and not direct_feed._live:
            return False
        return orig_direct_load()

    direct_feed._load = _finite_direct_load  # type: ignore[method-assign]
    direct_rows = _run_feed(direct_feed)

    # Gateway feed receives the exact same bars via its internal live bar publication pipeline
    gateway_feed = GatewayBtApiFeed(dataname="SA701")
    for raw_bar in bars:
        gateway_feed._live.append(dict(raw_bar))
    orig_load = gateway_feed._load

    def _finite_load():
        if not gateway_feed._live:
            return False
        return orig_load()

    gateway_feed._load = _finite_load  # type: ignore[method-assign]
    gateway_rows = _run_feed(gateway_feed)

    assert direct_rows == gateway_rows == [
        (1500.0, 1510.0, 1495.0, 1505.0, 120.0),
        (1505.0, 1512.0, 1500.0, 1508.0, 85.0),
    ]


# ---------------------------------------------------------------------------
# Standalone Non-Live Tools (D62S-08a)
# ---------------------------------------------------------------------------


def test_service_readonly_store_isolation_and_write_refusal():
    class ServiceReadProxy:
        def __init__(self):
            self.started = False
            self.stopped = False

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

        def get_cash(self):
            return 12345.5

        def get_value(self):
            return 12500.0

        def get_positions(self):
            return [{"instrument": "SA701", "volume": 1}]

    ServiceReadProxy.__module__ = "backtrader.service.service_read_proxy"

    # Rejects non-proxy input
    with pytest.raises(LiveCompositionError) as exc_bad:
        ServiceReadOnlyStore(object())
    assert exc_bad.value.code == "NON_LIVE_TOOL_CONFLICT"

    proxy = ServiceReadProxy()
    store = ServiceReadOnlyStore(proxy)
    assert not isinstance(store, BaseBtApiStore)
    assert store.read_only is True
    assert store.service_read_only is True

    store.start()
    assert store.is_connected is True
    assert store.get_cash() == 12345.5
    assert store.get_value() == 12500.0
    assert store.get_positions() == [{"instrument": "SA701", "volume": 1}]

    for method_name in ("getbroker", "make_order", "cancel_order", "place_order", "submit_order"):
        with pytest.raises(LiveCompositionError) as exc_w:
            getattr(store, method_name)()
        assert exc_w.value.code == "NON_LIVE_TOOL_CONFLICT"

    with pytest.raises(LiveCompositionError) as exc_start_broker:
        store.start(broker=object())
    assert exc_start_broker.value.code == "NON_LIVE_TOOL_CONFLICT"

    store.stop()
    assert store.is_connected is False


def test_replay_btapi_feed_isolation():
    from bt_api_py.replay_market_contracts import (
        ReplayMarketMode,
        ReplayMarketPollStatus,
        ReplayMarketTickEvent,
        ReplayMarketTickPollResult,
        ReplayVolumeSemantics,
    )

    inst = MarketInstrumentKey(
        provider="ctp",
        venue="CZCE",
        environment="demo",
        product_type="future",
        instrument_id="SA701",
        native_symbol="SA701",
    )

    class _FakeReplayPort:
        replay_mode = ReplayMarketMode.REPLAY
        replay_source_ref = "local-parquet-v1"
        replay_epoch = "epoch-1"
        instrument = inst

        def __init__(self):
            self._idx = 0
            self._started = False
            self._closed = False

        def start_replay(self, symbol):
            assert symbol == "SA701"
            self._started = True

        def poll_replay_tick(self, symbol):
            assert symbol == "SA701"
            if self._idx == 0:
                self._idx += 1
                ev = ReplayMarketTickEvent(
                    mode=self.replay_mode,
                    source_ref=self.replay_source_ref,
                    replay_epoch=self.replay_epoch,
                    instrument=inst,
                    event_time_utc=dt.datetime(2026, 11, 1, 9, 0, tzinfo=dt.timezone.utc),
                    sequence=1,
                    last_price=1500.0,
                    delta_volume=10.0,
                    volume_semantics=ReplayVolumeSemantics.DELTA,
                )
                return ReplayMarketTickPollResult(status=ReplayMarketPollStatus.EVENT, event=ev)
            return ReplayMarketTickPollResult(
                status=ReplayMarketPollStatus.EOF,
                final_event_time_watermark_utc=dt.datetime(
                    2026, 11, 1, 9, 1, tzinfo=dt.timezone.utc
                ),
            )

        def close_replay(self, symbol):
            assert symbol == "SA701"
            self._closed = True

    port = _FakeReplayPort()

    # Forbids store binding
    with pytest.raises(LiveCompositionError) as exc_store:
        ReplayBtApiFeed(dataname="SA701", store=object(), replay_market_tick_port=port)
    assert exc_store.value.code == "NON_LIVE_TOOL_CONFLICT"

    feed = ReplayBtApiFeed(dataname="SA701", replay_market_tick_port=port)
    assert not isinstance(feed, BaseBtApiFeed)
    assert not isinstance(feed, BtApiFeed)
    assert feed.islive() is False
    assert feed.store is None

    cerebro = bt.Cerebro()
    cerebro.adddata(feed, name="SA701")

    class _Capture(bt.Strategy):
        def __init__(self):
            self.closes: List[float] = []

        def next(self):
            self.closes.append(float(self.data.close[0]))

    cerebro.addstrategy(_Capture)
    strats = cerebro.run()
    assert strats[0].closes == [1500.0]
    assert feed.replay_exhausted is True
    assert port._closed is True


# ---------------------------------------------------------------------------
# live_state Immutable Mode Stamp (T-028 / R62S-11)
# ---------------------------------------------------------------------------


def test_live_state_immutable_mode_stamp_and_cross_mode_refusal(tmp_path):
    dir_direct = tmp_path / "strat_direct"
    dir_direct.mkdir()
    ident_d = initialize_identity(dir_direct, mode="direct")
    assert ident_d.version == IDENTITY_MODE_VERSION == 2
    assert ident_d.mode == "direct"
    assert load_identity(dir_direct, expected_mode="direct") == ident_d

    with pytest.raises(LiveStateModeMismatch) as exc_cross:
        load_identity(dir_direct, expected_mode="gateway")
    assert exc_cross.value.code == "mode_mismatch"

    with pytest.raises(LiveStateModeMismatch):
        StrategyStateDir(dir_direct, expected_mode="gateway")

    # Mode stamp is strictly immutable once set
    with pytest.raises(LiveStateModeMismatch):
        stamp_identity_mode(dir_direct, mode="gateway", operator="op", reason="attempt-flip")

    # Legacy v1 directory can be explicitly upgraded once via stamp_identity_mode
    dir_v1 = tmp_path / "strat_v1"
    dir_v1.mkdir()
    ident_v1 = initialize_identity(dir_v1)
    assert ident_v1.version == 1
    assert ident_v1.mode is None
    # require_mode_stamp=True rejects unstamped v1 dir
    with pytest.raises(LiveStateModeMismatch):
        load_identity(dir_v1, expected_mode="direct", require_mode_stamp=True)

    upgraded = stamp_identity_mode(dir_v1, mode="gateway", operator="op", reason="explicit-upgrade")
    assert upgraded.version == 2
    assert upgraded.mode == "gateway"
    assert upgraded.strategy_uuid == ident_v1.strategy_uuid
    assert any(row.get("event") == "identity_mode_stamped" for row in read_audit(dir_v1))
    # Idempotent same-mode stamp succeeds
    assert stamp_identity_mode(dir_v1, mode="gateway", operator="op", reason="repeat") == upgraded
    # Cross-mode stamp fails
    with pytest.raises(LiveStateModeMismatch):
        stamp_identity_mode(dir_v1, mode="direct", operator="op", reason="flip")


def test_live_state_gateway_pending_refused_in_direct_mode_and_gateway_store_rejects_direct_dir(tmp_path):
    # 1. Gateway-upgraded pending.json (v2..v8) is refused when opened as direct
    gw_dir = tmp_path / "gw_upgraded_v1"
    gw_dir.mkdir()
    state = StrategyStateDir.initialize(gw_dir)
    binding = GatewayCommandBinding("journal", "account", state.strategy_uuid, "principal")
    GatewayPendingHost.upgrade_for_gateway(state.strategy_dir, state.strategy_uuid, binding)
    with pytest.raises(LiveStateModeMismatch):
        load_identity(gw_dir, expected_mode="direct")
    with pytest.raises(LiveStateError) as exc_upg:
        stamp_identity_mode(gw_dir, mode="direct", operator="op", reason="wrong-mode")
    assert exc_upg.value.code == "mode_upgrade_blocked_active_state"

    # 2. GatewayBtApiStore rejects a strategy directory stamped for mode='direct'
    direct_dir = tmp_path / "direct_stamped"
    direct_dir.mkdir()
    with pytest.raises(LiveCompositionError) as exc_store:
        _make_gateway_store(direct_dir, mode_stamp="direct")
    assert exc_store.value.code == "LIVE_STATE_MODE_MISMATCH"

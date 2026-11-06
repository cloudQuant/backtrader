"""Fake Store / BtApi facade for BtApiBroker direct-mode unit tests.

Evidence level: UNIT/FAKE.  The fake implements exactly the facade surface that
``backtrader.brokers._btapi_direct_mode`` calls and mimics the SDK coordinator
ordering: the host pre-dispatch port is committed with a real
``bt_api_base.direct_write_protocol.PreDispatchRecord`` *before* anything is
"sent".  Durable state uses the real :mod:`backtrader.live_state` package in a
temporary strategy directory.  Nothing here contacts a provider or account.
"""

from __future__ import annotations

import collections
import datetime as dt
import itertools
import threading
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import backtrader as bt
from backtrader import live_state as ls
from backtrader.brokers.btapibroker import BtApiBroker
from bt_api_base.direct_write_protocol import (
    DirectAccountFacts,
    DirectBalanceFact,
    DirectExecutionEvent,
    DirectExecutionEventKind,
    DirectOrderStatus,
    DirectPositionFact,
    NativeOrderIdentity,
    PreDispatchRecord,
    SettlementStatus,
    WriteAdmissionDenied,
    WriteOperation,
)
from bt_api_base.trading_session_protocol import (
    TradingPhase,
    TradingSessionState,
    TradingWindow,
    TradingWindowKind,
)
from bt_api_py.direct_write import CorrelatedDirectEvent, DirectWriteOutcome

EXCHANGE = "CTP___FUTURE"
SYMBOL = "rb2701"
OTHER_SYMBOL = "hc2701"
VENUE = "SHFE"
TODAY = "20261105"
YESTERDAY = "20261104"
TOMORROW = "20261106"
ACCOUNT_REF = "simnow:000001"
FRONT_ID = 1
SESSION_ID = 1001
T0 = dt.datetime(2026, 11, 5, 7, 0, tzinfo=dt.timezone.utc)  # 15:00 Asia/Shanghai


def _utc_text(value: Optional[dt.datetime] = None) -> str:
    value = value or dt.datetime.now(dt.timezone.utc)
    return (
        value.astimezone(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# data feed
# ---------------------------------------------------------------------------
class ListFeed(bt.feeds.DataBase):
    """A real ``DataBase`` loaded from ``(datetime, price)`` tuples."""

    params = (("bars", ()),)

    def start(self):
        super().start()
        self._idx = 0

    def _load(self):
        if self._idx >= len(self.p.bars):
            return False
        when, price = self.p.bars[self._idx]
        self._idx += 1
        self.lines.datetime[0] = bt.date2num(when)
        for name in ("open", "high", "low", "close"):
            getattr(self.lines, name)[0] = price
        self.lines.volume[0] = 1.0
        self.lines.openinterest[0] = 0.0
        return True


def make_feed(symbol: str = SYMBOL, price: float = 3500.0) -> ListFeed:
    feed = ListFeed(dataname=symbol, bars=[(dt.datetime(2026, 11, 5, 9, 1), price)])
    feed._start()
    assert feed.load() is True
    feed.qualification = SimpleNamespace(ok=True, reasons=())
    # The Broker reads ``data.trade_qualification()`` (BtApiFeed contract).
    feed.trade_qualification = lambda: feed.qualification
    return feed


def not_live(feed) -> None:
    feed.qualification = SimpleNamespace(ok=False, reasons=("FEED_NOT_LIVE",))


def not_qualified(feed, reason: str = "SOURCE_STALE") -> None:
    feed.qualification = SimpleNamespace(ok=False, reasons=(reason,))


def qualified(feed) -> None:
    feed.qualification = SimpleNamespace(ok=True, reasons=())


# ---------------------------------------------------------------------------
# facts / events builders
# ---------------------------------------------------------------------------
def position(side: str, total: float, today=None, yesterday=None, *, symbol=SYMBOL, venue=VENUE):
    return DirectPositionFact(
        symbol=symbol, venue=venue, side=side, total=float(total), today=today, yesterday=yesterday
    )


def balance(total: float = 1_000_000.0, available: float = 900_000.0) -> DirectBalanceFact:
    return DirectBalanceFact(currency="CNY", balance=total, available=available)


def native_identity(order_ref: str, *, trading_day: str = TODAY, **extra) -> NativeOrderIdentity:
    fields = {
        "front_id": FRONT_ID,
        "session_id": SESSION_ID,
        "order_ref": order_ref,
        "trading_day": trading_day,
        "exchange_id": VENUE,
    }
    fields.update(extra)
    return NativeOrderIdentity(
        exchange_name=EXCHANGE, client_order_id=order_ref, fields=fields, session_generation=1
    )


def order_event(
    identity: NativeOrderIdentity,
    status: str,
    *,
    sys_id: Optional[str] = "1001",
    side: str = "buy",
    offset: str = "open",
    qty: float = 1.0,
    filled: float = 0.0,
    remaining: Optional[float] = None,
    price: float = 3500.0,
    symbol: str = SYMBOL,
    kind: DirectExecutionEventKind = DirectExecutionEventKind.ORDER,
    error_code: Optional[str] = None,
) -> DirectExecutionEvent:
    return DirectExecutionEvent(
        kind=kind,
        exchange_name=EXCHANGE,
        symbol=symbol,
        identity=identity,
        exchange_order_id=sys_id,
        status=DirectOrderStatus(status),
        side=side,
        offset=offset,
        order_qty=qty,
        filled_qty=filled,
        remaining_qty=qty - filled if remaining is None else remaining,
        limit_price=price,
        trading_day=TODAY,
        error_code=error_code,
    )


def trade_event(
    trade_id: str,
    *,
    sys_id: str = "1001",
    side: str = "buy",
    offset: str = "open",
    qty: float = 1.0,
    price: float = 3500.0,
    symbol: str = SYMBOL,
    order_ref: Optional[str] = None,
) -> DirectExecutionEvent:
    """A CTP-like trade return: keyed by ExchangeID + OrderSysID only."""
    identity = NativeOrderIdentity(
        exchange_name=EXCHANGE,
        client_order_id=order_ref,
        fields={"exchange_id": VENUE, "order_sys_id": sys_id},
    )
    return DirectExecutionEvent(
        kind=DirectExecutionEventKind.TRADE,
        exchange_name=EXCHANGE,
        symbol=symbol,
        identity=identity,
        exchange_order_id=sys_id,
        side=side,
        offset=offset,
        trade_id=trade_id,
        trade_price=price,
        trade_qty=qty,
        trading_day=TODAY,
    )


# ---------------------------------------------------------------------------
# trading-session schedule
# ---------------------------------------------------------------------------
def window(start: dt.datetime, end: dt.datetime, day: dt.date = dt.date(2026, 11, 6)):
    return TradingWindow(
        trading_day=day,
        kind=TradingWindowKind.CONTINUOUS,
        start_utc=start,
        end_utc=end,
        session_id="day",
    )


class FakeSchedule:
    """Provider schedule stand-in; tests set ``phase``/``next_window``/``reason``."""

    def __init__(self, phase: TradingPhase = TradingPhase.CONTINUOUS, next_window=None):
        self.phase = phase
        self.next_window = next_window
        self.reason: Optional[str] = None
        self.trading_day = dt.date(2026, 11, 5)  # the venue calendar's day now
        self.calls: List[tuple] = []

    def session_state(self, instrument_id: str, at_utc: dt.datetime) -> TradingSessionState:
        self.calls.append((instrument_id, at_utc))
        reason = self.reason
        if self.phase is TradingPhase.UNKNOWN and not reason:
            reason = "calendar_unknown"
        return TradingSessionState(
            instrument_id=instrument_id,
            at_utc=at_utc,
            phase=self.phase,
            trading_day=self.trading_day,
            current_window=None,
            next_continuous=self.next_window,
            calendar_ref="fake-calendar",
            reason=reason,
        )


# ---------------------------------------------------------------------------
# BtApi facade
# ---------------------------------------------------------------------------
class FakeAdmission:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def is_enabled(self, exchange_name: str) -> bool:
        return bool(self.enabled) and exchange_name == EXCHANGE


class FakeProvider:
    def __init__(self, reference: Optional[str] = ACCOUNT_REF):
        self.reference = reference

    def account_reference(self) -> Optional[str]:
        return self.reference


class FakeDirectWrites:
    def __init__(self, provider: FakeProvider):
        self._provider = provider

    def provider(self, exchange_name: str) -> FakeProvider:
        assert exchange_name == EXCHANGE
        return self._provider


class FakeApi:
    """Facade methods the direct-mode mixin calls; nothing else."""

    def __init__(self) -> None:
        self.write_admission = FakeAdmission(True)
        self.provider = FakeProvider()
        self._writes = FakeDirectWrites(self.provider)
        self.trading_day = TODAY
        self.session_generation: Optional[int] = 1
        # Provider session readers (instance attributes, so tests may replace
        # or delete them like a provider without the capability).
        self.provider.trading_day = lambda: self.trading_day
        self.provider.session_generation = lambda: self.session_generation
        # Read-only settlement state of the current session (the SDK
        # coordinator's read-first step): ``settlement_readback`` when set,
        # else "still to confirm"; ``settlement_error`` raises.  Never commits.
        self.provider.settlement_status = self._read_settlement_status
        self.settlement_reads: List[str] = []
        self.positions: List[DirectPositionFact] = []
        self.active_orders: List[DirectExecutionEvent] = []
        self.orders: List[DirectExecutionEvent] = []  # terminal orders of the day
        self.trades: List[DirectExecutionEvent] = []
        self.balance: Optional[DirectBalanceFact] = balance()
        self.complete = True
        self.blockers: tuple = ()
        self.incomplete_reads = 0  # the next N reads come back incomplete
        self.schedule: Optional[FakeSchedule] = FakeSchedule()
        self.settlement_result = SettlementStatus.CONFIRMED
        # SDK readback answered without any commit (CONFIRMED / UNKNOWN), or an
        # exception raised before anything was committed.
        self.settlement_readback: Optional[SettlementStatus] = None
        self.settlement_error: Optional[Exception] = None
        self.outcomes: collections.deque = collections.deque()
        self.make_order_error: Optional[Exception] = None
        self.cancel_sent: Optional[bool] = True
        self.auto_cancel_events = False
        self.events: collections.deque = collections.deque()
        self.facts_calls: List[Dict[str, Any]] = []
        self.place_calls: List[SimpleNamespace] = []
        self.cancel_calls: List[SimpleNamespace] = []
        self.settlement_calls: List[SimpleNamespace] = []
        self._refs = itertools.count(1)
        self._lock = threading.Lock()

    # -- read side --------------------------------------------------------
    def direct_account_facts(self, exchange_name: str, **sections: Any) -> DirectAccountFacts:
        with self._lock:
            self.facts_calls.append(dict(sections))
            complete = self.complete
            if self.incomplete_reads > 0:
                self.incomplete_reads -= 1
                complete = False
        all_orders = sections.get("all_orders", False)
        return DirectAccountFacts(
            exchange_name=exchange_name,
            trading_day=self.trading_day,
            session_generation=self.session_generation,
            observed_at_utc=_utc_text(),
            positions=tuple(self.positions) if sections.get("positions", True) else None,
            active_orders=(
                tuple(self.active_orders) if sections.get("active_orders", True) else None
            ),
            trades=tuple(self.trades) if sections.get("trades", False) else None,
            balance=self.balance if sections.get("balance", True) else None,
            complete=complete,
            blockers=self.blockers if not complete else (),
            orders=tuple(self.orders) + tuple(self.active_orders) if all_orders else None,
        )

    def direct_writes(self) -> FakeDirectWrites:
        return self._writes

    def trading_session_schedule(self, exchange_name: str) -> FakeSchedule:
        if self.schedule is None:
            raise LookupError("no trading-session provider")
        return self.schedule

    # -- write side (SDK coordinator ordering) ------------------------------
    @staticmethod
    def _commit(port: Any, record: PreDispatchRecord) -> Optional[str]:
        try:
            marker = port.commit(record)
        except Exception:
            return None
        return marker if type(marker) is str and marker else None

    def _read_settlement_status(self) -> SettlementStatus:
        self.settlement_reads.append(self.trading_day)
        if self.settlement_error is not None:
            raise self.settlement_error
        if self.settlement_readback is not None:
            return self.settlement_readback
        return SettlementStatus.UNCONFIRMED

    def ensure_settlement_confirmed(self, exchange_name, *, pre_dispatch_commit, host_scope):
        if self.settlement_error is not None:
            self.settlement_calls.append(
                SimpleNamespace(marker_id=None, host_scope=host_scope, trading_day=self.trading_day)
            )
            raise self.settlement_error
        if self.settlement_readback is not None:
            self.settlement_calls.append(
                SimpleNamespace(marker_id=None, host_scope=host_scope, trading_day=self.trading_day)
            )
            return self.settlement_readback
        record = PreDispatchRecord(
            operation=WriteOperation.SETTLEMENT_CONFIRM,
            host_scope=host_scope,
            exchange_name=exchange_name,
            symbol=None,
            identity=None,
            target_identity=None,
            request_summary={},
            trading_day=self.trading_day,
            session_generation=self.session_generation,
            created_at_utc=_utc_text(),
        )
        marker = self._commit(pre_dispatch_commit, record)
        self.settlement_calls.append(
            SimpleNamespace(marker_id=marker, host_scope=host_scope, trading_day=self.trading_day)
        )
        if marker is None:
            return SettlementStatus.UNKNOWN
        return self.settlement_result

    def make_order(
        self, exchange_name, request, *, pre_dispatch_commit, host_scope, request_summary=None
    ):
        if not self.write_admission.is_enabled(exchange_name):
            raise WriteAdmissionDenied("write_admission_disabled", exchange_name)
        if self.make_order_error is not None:
            raise self.make_order_error
        order_ref = f"{next(self._refs):012d}"
        identity = native_identity(order_ref, trading_day=self.trading_day)
        record = PreDispatchRecord(
            operation=WriteOperation.PLACE,
            host_scope=host_scope,
            exchange_name=exchange_name,
            symbol=request.symbol,
            identity=identity,
            target_identity=None,
            request_summary=dict(request_summary or {}),
            trading_day=identity.fields.get("trading_day"),
            session_generation=identity.session_generation,
            created_at_utc=_utc_text(),
        )
        marker = self._commit(pre_dispatch_commit, record)
        # "Send" happens only now: prove the marker was durable first.
        durable = marker is not None and pre_dispatch_commit.store.get(marker) is not None
        spec = self.outcomes.popleft() if self.outcomes else {"sent": True}
        call = SimpleNamespace(
            request=request,
            identity=identity,
            marker_id=marker,
            summary=dict(request_summary or {}),
            host_scope=host_scope,
            durable_before_send=durable,
        )
        self.place_calls.append(call)
        if marker is None:
            return DirectWriteOutcome(False, identity, None, "pre_dispatch_commit_failed")
        return DirectWriteOutcome(
            sent=spec.get("sent", True),
            identity=identity,
            marker_id=marker,
            error_code=spec.get("error_code"),
        )

    def cancel_order(
        self, exchange_name, symbol, *, pre_dispatch_commit, target_identity, host_scope
    ):
        assert type(target_identity) is NativeOrderIdentity
        record = PreDispatchRecord(
            operation=WriteOperation.CANCEL,
            host_scope=host_scope,
            exchange_name=exchange_name,
            symbol=symbol,
            identity=None,
            target_identity=target_identity,
            request_summary={},
            trading_day=target_identity.fields.get("trading_day"),
            session_generation=1,
            created_at_utc=_utc_text(),
        )
        marker = self._commit(pre_dispatch_commit, record)
        self.cancel_calls.append(
            SimpleNamespace(symbol=symbol, target=target_identity, marker_id=marker)
        )
        if marker is None:
            return DirectWriteOutcome(False, target_identity, None, "pre_dispatch_commit_failed")
        if self.auto_cancel_events and self.cancel_sent:
            self.push(
                order_event(
                    target_identity,
                    "cancelled",
                    sys_id=target_identity.fields.get("order_sys_id"),
                    symbol=symbol,
                )
            )
        return DirectWriteOutcome(self.cancel_sent, target_identity, marker)

    def push(self, event: DirectExecutionEvent) -> None:
        self.events.append(
            CorrelatedDirectEvent(
                event=event,
                matched=True,
                evidence="direct_identity_match",
                marker_id=None,
                host_scope=None,
            )
        )

    def poll_direct_execution_events(self, exchange_name: str, max_events: int = 256):
        out = []
        while self.events and len(out) < max_events:
            out.append(self.events.popleft())
        return tuple(out)


class FakeStore:
    """The Store attributes the direct-mode Broker reads."""

    def __init__(self, api: FakeApi, feeds: List[Any], *, direct_write_mode: bool = True):
        self.direct_write_mode = direct_write_mode
        self._sdk_exchanges = {EXCHANGE: {}}
        self.sdk_api = api
        self._data_feeds = list(feeds)
        self.start_calls: List[Any] = []
        self.stop_calls = 0

    def start(self, broker=None):
        self.start_calls.append(broker)

    def stop(self):
        self.stop_calls += 1


# ---------------------------------------------------------------------------
# environment
# ---------------------------------------------------------------------------
class Env:
    """One strategy directory, one fake facade, one Store, real feeds."""

    def __init__(self, tmp_path) -> None:
        self.strategy_dir = tmp_path / "strategy"
        self.strategy_dir.mkdir()
        self.api = FakeApi()
        self.feed = make_feed(SYMBOL)
        self.other_feed = make_feed(OTHER_SYMBOL, price=3300.0)
        self.store = FakeStore(self.api, [self.feed, self.other_feed])
        self.brokers: List[BtApiBroker] = []
        self.strategy = SimpleNamespace(name="direct-strategy")

    def broker(self, **params: Any) -> BtApiBroker:
        values = {"strategy_dir": str(self.strategy_dir), "stop_cancel_timeout": 0.2}
        values.update(params)
        broker = BtApiBroker(store=self.store, **values)
        self.brokers.append(broker)
        return broker

    def start(self, **params: Any) -> BtApiBroker:
        broker = self.broker(**params)
        broker.start()
        return broker

    def init_flat(self) -> str:
        """First initialization on a flat account, then a clean stop."""
        saved = (list(self.api.positions), list(self.api.active_orders))
        self.api.positions, self.api.active_orders = [], []
        broker = self.start(first_init=True)
        account_hash = broker._direct_account_hash
        broker.stop()
        self.api.positions, self.api.active_orders = saved
        return account_hash

    def state(self) -> ls.StrategyStateDir:
        return ls.StrategyStateDir(str(self.strategy_dir))

    def write_snapshot(self, positions: Dict[str, Any], *, trading_day: str = TODAY, **extra):
        state = self.state()
        current = state.snapshot.read()
        current.update(positions=positions, trading_day=trading_day, **extra)
        current.pop("updated_at_utc", None)
        state.snapshot.write(current)

    def seed_marker(
        self,
        order_ref: str,
        *,
        trading_day: str = TODAY,
        local_seq: int = 1,
        bt_ref: int = 1,
        symbol: str = SYMBOL,
        status: str = "DISPATCHED",
    ):
        """A place marker exactly as the SDK coordinator commits it."""
        state = self.state()
        identity = native_identity(order_ref, trading_day=trading_day)
        record = PreDispatchRecord(
            operation=WriteOperation.PLACE,
            host_scope=state.strategy_uuid,
            exchange_name=EXCHANGE,
            symbol=symbol,
            identity=identity,
            target_identity=None,
            request_summary={"local_seq": local_seq},
            trading_day=trading_day,
            session_generation=1,
            created_at_utc=_utc_text(),
        )
        marker_id = state.pending.commit(record, local_seq=local_seq, bt_ref=bt_ref)
        assert marker_id is not None
        if status != "PREPARED":
            assert state.pending.mark(marker_id, status)
        return marker_id, identity

    def close(self) -> None:
        for broker in self.brokers:
            if broker._direct_active():
                try:
                    broker.stop()
                except Exception:
                    pass
            crash(broker)


def crash(broker: BtApiBroker) -> None:
    """Simulate a process death: no cancels, no snapshot, lock released by the OS."""
    broker._direct_facts_stop.set()
    broker._direct_release_lock()
    broker._direct_on = False


def quiet(broker: BtApiBroker) -> None:
    """Stop the background facts poller so a test drives every read itself."""
    broker._direct_facts_stop.set()
    thread = broker._direct_facts_thread
    if thread is not None:
        thread.join(timeout=5.0)


def run_day_switch(broker: BtApiBroker) -> Dict[str, Any]:
    """One facts-poller verification attempt of the pending switch, then ``next``."""
    broker._direct_day_switch_due = 0.0
    broker._direct_day_switch_poll()
    broker.next()
    return dict(broker.get_direct_reconcile_report().get("trading_day_switch") or {})


def snap(long=(0, 0, 0), short=(0, 0, 0)) -> Dict[str, Any]:
    """One snapshot entry: ``(total, today, yesterday)`` per side."""

    def side(values):
        total, today, yesterday = values
        return {"total": total, "today": today, "yesterday": yesterday}

    return {"long": side(long), "short": side(short), "net": long[0] - short[0]}


def drain(broker: BtApiBroker) -> List[Any]:
    out = []
    while True:
        item = broker.get_notification()
        if item is None:
            return out
        out.append(item)


def last_status(notifications: List[Any]) -> List[str]:
    return [bt.Order.Status[item.status] for item in notifications]

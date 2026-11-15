"""Direct-mode gate over the committed SDK 67.06 status composition.

Evidence level: UNIT/FAKE.  The Broker/Store/facade are the direct-mode fakes and
the SDK composition is the committed module; observations are real CTP
projections and ledger views from synthetic callback fields.  The calendar
answer is a synthetic declaration.  Nothing contacts a provider or account and
no result authorizes trading.
"""

import datetime as dt

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")
pytest.importorskip("bt_api_ctp", reason="observations need the bt_api_ctp projection")

import backtrader as bt
from bt_api_base.trading_session_protocol import TradingPhase
from bt_api_ctp.instrument_status_observation import (
    RECEIVE_CLOCK_MONOTONIC_NS,
    InstrumentStatusLedger,
    InstrumentStatusSessionFacts,
    project_native_instrument_status,
)
from bt_api_py.instrument_status_composition import (
    CALENDAR_COMPLETE,
    PHASE_CLOSED,
    PHASE_CONTINUOUS,
    REASON_CALENDAR_CLOSED_DAY,
    REASON_CALENDAR_OPEN_UNCLASSIFIED,
    CalendarDayAnswer,
    InstrumentStatusScope,
    compose_instrument_status,
)

from backtrader.brokers import _btapi_direct_mode as direct_mode

from ._fakes import (
    EXCHANGE,
    SYMBOL,
    T0,
    TOMORROW,
    VENUE,
    not_live,
    not_qualified,
    quiet,
    window,
)

DAY = dt.date(2026, 11, 5)
GENERATION = 1


class Port:
    """Explicit status source: records scopes, returns one fixed view."""

    def __init__(self, view=None):
        self.view = view
        self.scopes = []

    def observation(self, scope):
        self.scopes.append(scope)
        return self.view


def native_fields(status, *, symbol=SYMBOL):
    return {
        "ExchangeID": VENUE,
        "ExchangeInstID": symbol,
        "InstrumentID": symbol,
        "InstrumentStatus": status,
        "TradingSegmentSN": 1,
        "EnterTime": "09:00:00",
        "EnterReason": "1",
    }


def view(status, *, generation=GENERATION, day=DAY, symbol=SYMBOL):
    projection = project_native_instrument_status(
        native_fields(status, symbol=symbol),
        session=InstrumentStatusSessionFacts(
            session_generation=str(generation),
            trading_day=day.strftime("%Y%m%d"),
            source_sequence=1,
            receive_clock_domain=RECEIVE_CLOCK_MONOTONIC_NS,
            receive_time=1001,
            source_available=True,
        ),
    )
    assert projection.accepted is True
    ledger = InstrumentStatusLedger(
        session_generation=str(generation), trading_day=day.strftime("%Y%m%d")
    )
    assert ledger.observe(projection).applied is True
    return ledger.view(VENUE, symbol)


def attach(env, port, *, calendar_phase=PHASE_CONTINUOUS):
    """Answer through the real SDK composition with a synthetic calendar."""
    env.store.instrument_status_source_configured = lambda: True
    calls = []

    def instrument_status(**kwargs):
        calls.append(kwargs)
        scope = InstrumentStatusScope(
            kwargs["venue"],
            kwargs["instrument"],
            kwargs["trading_day"],
            kwargs["session_generation"],
        )
        closed = calendar_phase == PHASE_CLOSED
        calendar = CalendarDayAnswer(
            CALENDAR_COMPLETE,
            calendar_phase,
            REASON_CALENDAR_CLOSED_DAY if closed else REASON_CALENDAR_OPEN_UNCLASSIFIED,
            "cal-test",
            scope.venue,
            scope.instrument,
            scope.trading_day,
            coverage_status="DECLARED_UNVERIFIED",
        )
        return compose_instrument_status(
            scope=scope,
            observation=port.observation(scope),
            calendar=calendar,
        )

    env.store.instrument_status = instrument_status
    return calls


def set_scope(feed, *, contract=SYMBOL):
    feed.p.calendar_route = EXCHANGE
    feed.p.calendar_venue = VENUE
    feed.p.calendar_kind = "future"
    feed.p.calendar_product = "rb"
    feed.p.calendar_contract = contract


def buy(env, broker, **kwargs):
    kwargs.setdefault("offset", "open")
    return broker.buy(env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit, **kwargs)


def test_tradable_immediate_order_reaches_the_send(env):
    broker = env.start(first_init=True)
    port = Port(view("2"))  # continuous
    calls = attach(env, port)
    set_scope(env.feed)
    order = buy(env, broker)
    assert order.status == bt.Order.Submitted
    assert len(env.api.place_calls) == 1
    assert order.info.get("instrument_status") is None
    (call,) = calls
    assert call["route"] == EXCHANGE
    assert call["instrument"] == SYMBOL
    assert call["trading_day"] == DAY
    assert call["session_generation"] == "1"
    assert [(scope.venue, scope.instrument, scope.session_generation) for scope in port.scopes] == [
        (VENUE, SYMBOL, "1")
    ]


@pytest.mark.parametrize(
    "status, code",
    [
        ("1", direct_mode.INSTRUMENT_STATUS_PAUSED),  # no_trading
        ("6", direct_mode.INSTRUMENT_STATUS_CLOSED),  # closed
    ],
)
def test_paused_and_closed_refuse_without_send(env, status, code):
    broker = env.start(first_init=True)
    attach(env, Port(view(status)))
    set_scope(env.feed)
    order = buy(env, broker)
    assert order.status == bt.Order.Rejected
    assert order.info["error_code"] == code
    assert code in direct_mode.INSTRUMENT_STATUS_CODES
    assert env.api.place_calls == []
    assert env.state().pending.active() == []
    details = order.info["instrument_status"]
    assert details["state"] in ("PAUSED", "CLOSED")
    assert details["source"] == "OBSERVATION"


def test_absent_observation_refuses_a_calendar_only_answer(env):
    broker = env.start(first_init=True)
    attach(env, Port(None))
    set_scope(env.feed)
    order = buy(env, broker)
    assert order.status == bt.Order.Rejected
    assert order.info["error_code"] == direct_mode.INSTRUMENT_STATUS_NO_OBSERVATION
    assert order.info["instrument_status"]["observation_state"] == "ABSENT"
    assert env.api.place_calls == []


def test_unknown_or_invalid_observation_refuses(env):
    broker = env.start(first_init=True)
    attach(env, Port(view("9")))  # unknown native category
    set_scope(env.feed)
    assert buy(env, broker).info["error_code"] == direct_mode.INSTRUMENT_STATUS_UNKNOWN
    assert env.api.place_calls == []


@pytest.mark.parametrize("change", ["generation", "trading_day"])
def test_generation_and_day_rollover_invalidate_the_observation(env, change):
    broker = env.start(first_init=True)
    attach(env, Port(view("2")))  # current for generation 1 / day 20261105
    set_scope(env.feed)
    quiet(broker)  # no background probe: this test advances the reconciled facts
    if change == "generation":
        broker._direct_session_generation = GENERATION + 1
    else:
        env.api.trading_day = TOMORROW
        broker._direct_trading_day = TOMORROW
    order = buy(env, broker)
    assert order.status == bt.Order.Rejected
    assert order.info["error_code"] == direct_mode.INSTRUMENT_STATUS_UNKNOWN
    assert env.api.place_calls == []


def test_unproven_scope_refuses_without_consulting_the_source(env):
    broker = env.start(first_init=True)
    port = Port(view("2"))
    attach(env, port)
    set_scope(env.feed, contract="cu9999")  # not the order's native symbol
    order = buy(env, broker)
    assert order.info["error_code"] == direct_mode.INSTRUMENT_STATUS_SCOPE_INVALID
    assert port.scopes == []
    assert env.api.place_calls == []


def test_configured_source_that_cannot_answer_is_unavailable(env):
    broker = env.start(first_init=True)
    attach(env, Port(view("2")))
    set_scope(env.feed)
    env.store.instrument_status = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("private"))
    assert buy(env, broker).info["error_code"] == direct_mode.INSTRUMENT_STATUS_UNAVAILABLE
    assert env.api.place_calls == []

    env.store.instrument_status_source_configured = lambda: (_ for _ in ()).throw(
        RuntimeError("private")
    )
    assert buy(env, broker).info["error_code"] == direct_mode.INSTRUMENT_STATUS_UNAVAILABLE
    assert env.api.place_calls == []


def test_waiting_orders_keep_their_existing_contract(env, clock):
    broker = env.start(first_init=True)
    port = Port(view("2"))
    attach(env, port)
    set_scope(env.feed)
    env.api.schedule.phase = TradingPhase.CLOSED
    env.api.schedule.next_window = window(T0 + dt.timedelta(hours=1), T0 + dt.timedelta(hours=3))
    not_qualified(env.feed, "SOURCE_STALE")
    order = buy(env, broker, valid=bt.Order.DAY)
    assert order.status == bt.Order.Submitted
    assert order.info["waiting_session"] is True
    assert port.scopes == []
    assert env.api.place_calls == []


def test_existing_refusals_keep_their_code_and_skip_the_gate(env):
    broker = env.start(first_init=True)
    port = Port(view("2"))
    attach(env, port)
    set_scope(env.feed)
    not_live(env.feed)
    order = buy(env, broker)
    assert order.info["error_code"] == "target_feed_not_live"
    assert port.scopes == []
    assert env.api.place_calls == []


def test_gate_is_inactive_without_a_configured_source(env):
    broker = env.start(first_init=True)
    set_scope(env.feed)
    port = Port(view("6"))  # a CLOSED view that must not be consulted
    env.store.instrument_status = lambda **kwargs: port.observation(None)
    order = buy(env, broker)
    assert order.status == bt.Order.Submitted
    assert port.scopes == []
    assert len(env.api.place_calls) == 1

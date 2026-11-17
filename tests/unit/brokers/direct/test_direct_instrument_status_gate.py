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
    PHASE_AUCTION,
    PHASE_CLOSED,
    PHASE_CONTINUOUS,
    REASON_CALENDAR_CLOSED_DAY,
    REASON_CALENDAR_OPEN_UNCLASSIFIED,
    CalendarDayAnswer,
    InstrumentStatusScope,
    compose_instrument_status,
)

from ._fakes import (
    EXCHANGE,
    SYMBOL,
    T0,
    VENUE,
    not_live,
    not_qualified,
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
            "calendar-v1",
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


@pytest.mark.parametrize("status", ["1", "6", "9", None])
def test_immediate_order_does_not_consult_status(env, status):
    broker = env.start(first_init=True)
    port = Port(None if status is None else view(status))
    calls = attach(env, port)
    set_scope(env.feed)
    order = buy(env, broker)
    assert order.status == bt.Order.Submitted
    assert len(env.api.place_calls) == 1 and calls == [] and port.scopes == []
    assert order.info.get("instrument_status") is None


def create_waiting(env, clock, port, *, calendar_phase=PHASE_CONTINUOUS, target_day=DAY):
    broker = env.start(first_init=True)
    calls = attach(env, port, calendar_phase=calendar_phase)
    set_scope(env.feed)
    env.api.schedule.phase = TradingPhase.CLOSED
    env.api.schedule.next_window = window(T0 + dt.timedelta(hours=1), T0 + dt.timedelta(hours=3), day=target_day)
    not_qualified(env.feed, "SOURCE_STALE")
    order = buy(env, broker)
    record = env.state().waiting.get(order.info["waiting_id"])
    target = dict(record["target_session"])
    assert order.status == bt.Order.Submitted and not calls and not env.api.place_calls
    clock["value"] = T0 + dt.timedelta(hours=1)
    env.api.schedule.phase = TradingPhase.CONTINUOUS
    env.feed.qualification.ok = True
    return broker, order, target, calls


@pytest.mark.parametrize("status", ["1", "6", "9", None])
def test_waiting_status_unavailable_or_paused_holds_original_target(env, clock, status):
    port = Port(None if status is None else view(status))
    broker, order, target, calls = create_waiting(env, clock, port)
    broker.next()
    waiting = env.state().waiting.get(order.info["waiting_id"])
    assert order.status == bt.Order.Submitted and waiting["status"] == "WAITING"
    assert waiting["target_session"] == target and not env.api.place_calls
    assert len(calls) == 1
    broker.next()
    assert env.state().waiting.get(order.info["waiting_id"])["target_session"] == target
    assert not env.api.place_calls


def test_current_continuous_waiting_dispatches_once(env, clock):
    port = Port(view("2"))
    broker, order, target, calls = create_waiting(env, clock, port)
    broker.next()
    assert len(env.api.place_calls) == 1
    assert env.state().waiting.get(order.info["waiting_id"])["target_session"] == target
    broker.next()
    assert len(env.api.place_calls) == 1 and calls[0]["at"] == clock["value"]


def test_known_closed_calendar_and_current_continuous_remain_within_original_target(env, clock):
    broker, order, target, calls = create_waiting(env, clock, Port(view("2")), calendar_phase=PHASE_CLOSED)
    env.api.schedule.phase = TradingPhase.CLOSED
    broker.next()
    assert len(env.api.place_calls) == 1
    assert env.state().waiting.get(order.info["waiting_id"])["target_session"] == target
    assert order.info["instrument_status"]["source"] == "OBSERVATION"
    assert order.info["instrument_status"]["calendar_stale"] is True
    assert order.info["instrument_status"]["conflict"] is not None


def test_ledger_never_observed_keeps_waiting_without_recovery_proof(env, clock):
    ledger = InstrumentStatusLedger(session_generation="1", trading_day="20261105")
    broker, order, target, calls = create_waiting(env, clock, Port(ledger.view(VENUE, SYMBOL)))
    broker.next()
    assert not env.api.place_calls and order.status == bt.Order.Submitted
    assert order.info["instrument_status"]["observation_state"] == "ABSENT"
    waiting = env.state().waiting.get(order.info["waiting_id"])
    assert waiting["status"] == "WAITING" and waiting["target_session"] == target


def test_disconnect_then_old_pause_stays_unknown_until_sdk_proves_recovery(env, clock):
    ledger = InstrumentStatusLedger(session_generation="1", trading_day="20261105")
    assert ledger.observe(project_native_instrument_status(native_fields("1"),
        session=InstrumentStatusSessionFacts(session_generation="1", trading_day="20261105",
            source_sequence=1, receive_clock_domain=RECEIVE_CLOCK_MONOTONIC_NS,
            receive_time=1001, source_available=True))).applied
    port = Port(ledger.view(VENUE, SYMBOL))
    broker, order, target, calls = create_waiting(env, clock, port)
    broker.next()
    assert not env.api.place_calls
    ledger.mark_source_unavailable()
    port.view = ledger.view(VENUE, SYMBOL)
    broker.next()
    assert not env.api.place_calls
    ledger.begin_session_generation("2", "20261105")
    port.view = ledger.view(VENUE, SYMBOL)
    broker._direct_session_generation = 2
    broker.next()
    assert not env.api.place_calls  # SDK still classifies the old ledger entry STALE
    assert env.state().waiting.get(order.info["waiting_id"])["target_session"] == target


def test_new_pause_and_auction_do_not_dispatch(env, clock):
    port = Port(view("1"))
    broker, order, target, calls = create_waiting(env, clock, port)
    broker.next()
    assert not env.api.place_calls
    port.view = view("0")  # auction
    broker.next()
    assert not env.api.place_calls
    env.api.schedule.phase = TradingPhase.AUCTION
    broker.next()
    assert not env.api.place_calls
    assert env.state().waiting.get(order.info["waiting_id"])["target_session"] == target


def test_unproven_scope_and_source_exception_hold_waiting(env, clock):
    broker, order, target, calls = create_waiting(env, clock, Port(view("2")))
    set_scope(env.feed, contract="other")
    broker.next()
    assert not calls and not env.api.place_calls
    set_scope(env.feed)
    env.store.instrument_status = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("private"))
    broker.next()
    assert not env.api.place_calls
    assert env.state().waiting.get(order.info["waiting_id"])["target_session"] == target


def test_existing_refusals_keep_their_code_and_skip_status(env):
    broker = env.start(first_init=True)
    port = Port(view("2"))
    attach(env, port)
    set_scope(env.feed)
    not_live(env.feed)
    order = buy(env, broker)
    assert order.info["error_code"] == "target_feed_not_live"
    assert not port.scopes and not env.api.place_calls


def test_status_changes_during_precheck_hold_before_marker(env, clock):
    port = Port(view("2"))
    broker, order, target, calls = create_waiting(env, clock, port)
    original = broker._direct_precheck
    def precheck(*args, **kwargs):
        result = original(*args, **kwargs)
        port.view = view("1")
        return result
    broker._direct_precheck = precheck
    broker.next()
    assert len(calls) == 2 and not env.api.place_calls
    assert env.state().waiting.get(order.info["waiting_id"])["status"] == "WAITING"
    assert env.state().waiting.get(order.info["waiting_id"])["target_session"] == target


@pytest.mark.parametrize('failure', ['duck', 'calendar_version', 'configured_error'])
def test_status_contract_failure_holds_waiting(env, clock, failure):
    from types import SimpleNamespace
    from dataclasses import replace
    broker, order, target, calls = create_waiting(env, clock, Port(view("2")))
    original = env.store.instrument_status
    if failure == 'duck':
        env.store.instrument_status = lambda **kwargs: SimpleNamespace(state='TRADABLE', session_phase='CONTINUOUS')
    elif failure == 'calendar_version':
        env.store.instrument_status = lambda **kwargs: replace(original(**kwargs), calendar_ref='different-version')
    else:
        env.store.instrument_status_source_configured = lambda: (_ for _ in ()).throw(RuntimeError('private'))
    broker.next()
    assert not env.api.place_calls
    assert env.state().waiting.get(order.info['waiting_id'])['status'] == 'WAITING'
    assert env.state().waiting.get(order.info['waiting_id'])['target_session'] == target


def test_current_continuous_overrides_known_auction_within_target(env, clock):
    broker, order, target, calls = create_waiting(env, clock, Port(view("2")), calendar_phase=PHASE_AUCTION)
    env.api.schedule.phase = TradingPhase.AUCTION
    broker.next()
    assert len(env.api.place_calls) == 1
    assert order.info["instrument_status"]["session_phase"] == "CONTINUOUS"
    assert order.info["instrument_status"]["conflict"] is not None
    assert env.state().waiting.get(order.info["waiting_id"])["target_session"] == target


def test_current_status_cannot_override_a_different_target_trading_day(env, clock):
    broker, order, target, calls = create_waiting(
        env, clock, Port(view("2")), target_day=DAY + dt.timedelta(days=1))
    broker.next()
    assert not calls and not env.api.place_calls
    waiting = env.state().waiting.get(order.info["waiting_id"])
    assert waiting["status"] == "WAITING" and waiting["target_session"] == target


@pytest.mark.parametrize('change', ['generation', 'day', 'day_switch', 'account_gap',
                                  'past_end', 'target', 'qualification', 'calendar_binding'])
def test_status_read_cannot_send_after_binding_changes(env, clock, change):
    port = Port(view('2'))
    broker, order, target, calls = create_waiting(env, clock, port)
    meta = broker._direct_meta[order.ref]
    original_day = broker._direct_trading_day
    original_generation = broker._direct_session_generation
    original_switch = broker._direct_day_switch
    original_gap = broker._direct_return_gap
    original_target = meta['target_session']
    original_calendar_ref = env.feed.calendar_state.calendar_ref
    original_read = env.store.instrument_status
    reads = []
    def changing_read(**kwargs):
        result = original_read(**kwargs)
        reads.append(kwargs)
        if len(reads) == 2:
            if change == 'generation':
                broker._direct_session_generation = original_generation + 1
            elif change == 'day':
                broker._direct_trading_day = '20261106'
            elif change == 'day_switch':
                broker._direct_day_switch = {'synthetic': True}
            elif change == 'account_gap':
                broker._direct_return_gap = {'scope': 'account'}
            elif change == 'past_end':
                clock['value'] = T0 + dt.timedelta(hours=3)
            elif change == 'target':
                meta['target_session'] = dict(original_target, trading_day='20261106')
            elif change == 'qualification':
                env.feed.qualification.ok = False
            elif change == 'calendar_binding':
                env.feed.calendar_state.calendar_ref = 'different-version'
        return result
    env.store.instrument_status = changing_read
    try:
        broker.next()
        waiting = env.state().waiting.get(order.info['waiting_id'])
        assert len(reads) == 2 and waiting['status'] == 'WAITING'
        assert waiting['target_session'] == target and not env.api.place_calls
        assert not env.state().pending.active()
    finally:
        broker._direct_trading_day = original_day
        broker._direct_session_generation = original_generation
        broker._direct_day_switch = original_switch
        broker._direct_return_gap = original_gap
        meta['target_session'] = original_target
        env.feed.calendar_state.calendar_ref = original_calendar_ref
    if change == 'past_end':
        broker.next()
        assert env.state().waiting.get(order.info['waiting_id'])['status'] == 'EXPIRED'
        assert order.status == order.Expired and not env.api.place_calls


def test_final_precheck_can_publish_pause_before_last_status_read(env, clock):
    port = Port(view('2'))
    broker, order, target, calls = create_waiting(env, clock, port)
    original = broker._direct_precheck
    checks = []
    def changing_precheck(*args, **kwargs):
        result = original(*args, **kwargs)
        checks.append(True)
        if len(checks) == 2:
            port.view = view('1')
        return result
    broker._direct_precheck = changing_precheck
    broker.next()
    waiting = env.state().waiting.get(order.info['waiting_id'])
    assert len(checks) == len(calls) == 2
    assert waiting['status'] == 'WAITING' and waiting['target_session'] == target
    assert not env.state().pending.active() and not env.api.place_calls

"""Trading-permission facts in the direct-mode precheck (iteration 62, D62-25, 62.03).

After the startup reconciliation a CTP-style route reads the strategy
instruments' permission facts once.  An order is refused locally only when the
facts are complete, still belong to the provider's current session and trading
day, and are a definitive negative for that instrument; unknown or incomplete
facts allow the order (the venue stays authoritative) and are reported.  The
BT ``net``/``dual_side`` projection and the venue's two-sided positions play
no part.  UNIT/FAKE: fake facade, real ``backtrader.live_state``.
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt

from ._fakes import EXCHANGE, OTHER_SYMBOL, SYMBOL, TODAY, VENUE, position, snap

DENIED = "trading_permission_denied:trading_code_absent"


def _fact(name, status, reason, complete=True):
    return SimpleNamespace(name=name, status=status, reason=reason, query_complete=complete)


def _entry(symbol, outcome="no_negative_found", denial=(), venue=VENUE, facts=None):
    if facts is None:
        facts = (
            _fact("investor_active", "known_positive", "investor_active"),
            _fact("trading_code", "known_positive", "speculation_code_active"),
            _fact("instrument_trading", "known_positive", "instrument_trading"),
        )
    return SimpleNamespace(
        symbol=symbol,
        venue=venue,
        outcome=outcome,
        denial_reasons=tuple(denial),
        facts=facts,
        trading_code_kinds=("speculation",),
    )


def _negative(symbol, reason="trading_code_absent"):
    return _entry(
        symbol,
        outcome="known_negative",
        denial=(reason,),
        facts=(
            _fact("investor_active", "known_positive", "investor_active"),
            _fact("trading_code", "known_negative", reason),
            _fact("instrument_trading", "known_positive", "instrument_trading"),
        ),
    )


def _permissions(*entries, complete=True, consistent=True, blockers=(), generation=1, day=TODAY):
    return SimpleNamespace(
        scope="instrument_permission",
        proves_permission=False,
        complete=complete,
        session_consistent=consistent,
        trading_day=day,
        session_generation=generation,
        native_queries=4,
        blockers=tuple(blockers),
        instruments=tuple(entries),
    )


class Reader:
    """``BtApi.direct_trading_permissions`` stand-in."""

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def __call__(self, exchange_name, symbols, **kwargs):
        self.calls.append((exchange_name, tuple(symbols), kwargs))
        if self.error is not None:
            raise self.error
        return self.result


def _install(env, result=None, *, error=None, generation=1, day=TODAY):
    env.store._sdk_routes = {SYMBOL: EXCHANGE, OTHER_SYMBOL: EXCHANGE}
    reader = Reader(result, error)
    env.api.direct_trading_permissions = reader
    session = {"generation": generation, "day": day}
    env.api.provider.session_generation = lambda: session["generation"]
    env.api.provider.trading_day = lambda: session["day"]
    return reader, session


def _buy(env, broker, feed=None, **kwargs):
    kwargs.setdefault("offset", "open")
    return broker.buy(
        env.strategy, feed or env.feed, 1, price=3500.0, exectype=bt.Order.Limit, **kwargs
    )


def _sent_symbols(env):
    return [call.request.symbol for call in env.api.place_calls]


# ---------------------------------------------------------------------------
# read and report
# ---------------------------------------------------------------------------
def test_permissions_are_read_once_after_reconciliation_and_reported(env):
    env.store.contract_metadata = {SYMBOL: {"exchange": "shfe"}}
    reader, _session = _install(env, _permissions(_entry(SYMBOL), _entry(OTHER_SYMBOL)))
    broker = env.start(first_init=True, direct_permission_timeout=2.0)
    ((exchange, symbols, kwargs),) = reader.calls
    assert exchange == EXCHANGE and symbols == tuple(sorted((SYMBOL, OTHER_SYMBOL)))
    assert kwargs == {"exchange_ids": {SYMBOL: "SHFE"}, "timeout": 2.0, "max_duration": 60.0}
    report = broker.get_direct_reconcile_report()["permissions"]
    assert report["status"] == "complete" and report["current"] is True
    assert report["proves_permission"] is False
    assert report["instruments"][SYMBOL]["outcome"] == "no_negative_found"
    assert report["instruments"][SYMBOL]["facts"]["trading_code"] == (
        "known_positive:speculation_code_active"
    )
    _buy(env, broker)
    assert _sent_symbols(env) == [SYMBOL]
    assert len(reader.calls) == 1  # never re-read in the order path


def test_the_report_is_bounded_and_value_free(env):
    reader, _session = _install(
        env,
        _permissions(
            _entry(SYMBOL, outcome="unknown"),
            complete=False,
            blockers=("trading_code_query_incomplete[-1:timeout:partial:CTP:raw venue text]",),
        ),
    )
    broker = env.start(first_init=True)
    report = broker.get_direct_reconcile_report()["permissions"]
    assert report["status"] == "incomplete"
    assert report["blockers"] == ["trading_code_query_incomplete"]
    text = repr(report)
    assert "raw venue text" not in text and "simnow:000001" not in text


# ---------------------------------------------------------------------------
# definitive negatives refuse locally, in both BT position modes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mode", ["net", "dual_side"])
def test_a_complete_definitive_negative_refuses_the_order_and_sends_nothing(env, mode):
    _install(env, _permissions(_negative(SYMBOL), _entry(OTHER_SYMBOL)))
    broker = env.start(first_init=True, position_mode=mode)
    extra = {"position_side": "long"} if mode == "dual_side" else {}
    order = _buy(env, broker, **extra)
    assert order.status == bt.Order.Rejected
    assert order.info["error_code"] == DENIED
    assert env.api.place_calls == []
    assert env.state().pending.active() == []  # nothing durable, nothing reserved
    # Another instrument without a negative is unaffected.
    other = _buy(env, broker, env.other_feed, **extra)
    assert other.status == bt.Order.Submitted
    assert _sent_symbols(env) == [OTHER_SYMBOL]


@pytest.mark.parametrize(
    "reason", ["trading_code_inactive", "instrument_not_trading", "investor_inactive"]
)
def test_each_definitive_reason_is_carried_into_the_refusal(env, reason):
    _install(env, _permissions(_negative(SYMBOL, reason), _entry(OTHER_SYMBOL)))
    broker = env.start(first_init=True)
    order = _buy(env, broker)
    assert order.info["error_code"] == f"trading_permission_denied:{reason}"
    assert env.api.place_calls == []


def test_close_orders_are_refused_on_a_definitive_negative_too(env):
    env.init_flat()
    env.write_snapshot({SYMBOL: snap(long=(1, 0, 1))})
    env.api.positions = [position("long", 1, 0, 1)]
    _install(env, _permissions(_negative(SYMBOL, "instrument_not_trading"), _entry(OTHER_SYMBOL)))
    broker = env.start()
    order = broker.sell(
        env.strategy,
        env.feed,
        1,
        price=3500.0,
        exectype=bt.Order.Limit,
        offset="close_yesterday",
    )
    assert order.info["error_code"] == "trading_permission_denied:instrument_not_trading"
    assert env.api.place_calls == []


# ---------------------------------------------------------------------------
# unknown, incomplete, stale: allowed (the venue decides) and reported
# ---------------------------------------------------------------------------
def test_an_incomplete_result_never_refuses_even_with_a_negative_entry(env):
    _install(env, _permissions(_negative(SYMBOL), complete=False, blockers=("x_query_failed",)))
    broker = env.start(first_init=True)
    order = _buy(env, broker)
    assert order.status == bt.Order.Submitted
    assert broker.get_direct_reconcile_report()["permissions"]["status"] == "incomplete"


def test_a_result_read_across_a_session_change_never_refuses(env):
    _install(env, _permissions(_negative(SYMBOL), consistent=False))
    broker = env.start(first_init=True)
    assert _buy(env, broker).status == bt.Order.Submitted


def test_investor_and_trading_code_alone_allow_but_prove_nothing(env):
    facts = (
        _fact("investor_active", "known_positive", "investor_active"),
        _fact("trading_code", "known_positive", "speculation_code_active"),
        _fact("instrument_trading", "unknown", "instrument_paused"),
    )
    _install(env, _permissions(_entry(SYMBOL, outcome="unknown", facts=facts)))
    broker = env.start(first_init=True)
    assert _buy(env, broker).status == bt.Order.Submitted
    entry = broker.get_direct_reconcile_report()["permissions"]["instruments"][SYMBOL]
    assert entry["outcome"] == "unknown" and entry["denial_reasons"] == []
    assert broker.get_direct_reconcile_report()["permissions"]["proves_permission"] is False


@pytest.mark.parametrize(
    "change",
    [
        lambda session: session.update(generation=2),  # reconnect
        lambda session: session.update(generation=None),
    ],
)
def test_facts_of_another_session_or_trading_day_no_longer_refuse(env, change):
    _reader, session = _install(env, _permissions(_negative(SYMBOL)))
    broker = env.start(first_init=True)
    assert _buy(env, broker).info["error_code"] == DENIED
    change(session)
    order = _buy(env, broker)
    assert order.status == bt.Order.Submitted
    assert broker.get_direct_reconcile_report()["permissions"]["current"] is False
    assert broker._direct_permission_denials == {}


def test_facts_of_the_previous_trading_day_no_longer_refuse_after_the_switch(env):
    """A trading-day roll first freezes new orders (R-3); then the old facts are stale."""
    from ._fakes import quiet, run_day_switch

    _reader, session = _install(env, _permissions(_negative(SYMBOL)))
    broker = env.start(first_init=True)
    quiet(broker)
    assert _buy(env, broker).info["error_code"] == DENIED
    session.update(day="20261106")
    env.api.trading_day = "20261106"
    assert _buy(env, broker).info["error_code"] == "trading_day_switch_pending"
    assert run_day_switch(broker)["status"] == "completed"
    order = _buy(env, broker)
    assert order.status == bt.Order.Submitted
    assert broker.get_direct_reconcile_report()["permissions"]["current"] is False
    assert broker._direct_permission_denials == {}


def test_a_provider_that_cannot_tell_its_session_never_refuses(env):
    _install(env, _permissions(_negative(SYMBOL)))
    del env.api.provider.session_generation
    broker = env.start(first_init=True)
    assert _buy(env, broker).status == bt.Order.Submitted


def test_a_failed_read_is_reported_and_orders_stay_allowed(env):
    _install(env, error=TimeoutError("front busy"))
    broker = env.start(first_init=True)
    assert broker.get_direct_reconcile_report()["permissions"] == {
        "status": "read_failed",
        "reason": "TimeoutError",
    }
    assert _buy(env, broker).status == bt.Order.Submitted


def test_an_unreadable_result_proves_nothing(env):
    _install(env, SimpleNamespace(complete=True))
    broker = env.start(first_init=True)
    assert broker.get_direct_reconcile_report()["permissions"]["status"] == "unreadable"
    assert _buy(env, broker).status == bt.Order.Submitted


# ---------------------------------------------------------------------------
# routes and facades without the capability are unchanged
# ---------------------------------------------------------------------------
def test_a_facade_without_the_read_is_unchanged(env):
    env.store._sdk_routes = {SYMBOL: EXCHANGE}
    assert not hasattr(env.api, "direct_trading_permissions")
    broker = env.start(first_init=True)
    assert "permissions" not in broker.get_direct_reconcile_report()
    assert _buy(env, broker).status == bt.Order.Submitted


def test_a_provider_without_the_capability_is_unchanged(env):
    error = RuntimeError("capability_not_supported")
    error.code = "capability_not_supported"
    reader, _session = _install(env, error=error)
    broker = env.start(first_init=True)
    assert len(reader.calls) == 1
    assert "permissions" not in broker.get_direct_reconcile_report()
    assert _buy(env, broker).status == bt.Order.Submitted


def test_routes_without_offsets_never_read_permissions(env):
    """OKX/Binance-like routes (no explicit offset) are unchanged."""
    reader, _session = _install(env, _permissions(_negative(SYMBOL)))
    broker = env.start(first_init=True, require_offset=False)
    assert reader.calls == []
    assert "permissions" not in broker.get_direct_reconcile_report()
    order = broker.buy(env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit)
    assert order.status == bt.Order.Submitted


def test_the_check_can_be_switched_off(env):
    reader, _session = _install(env, _permissions(_negative(SYMBOL)))
    broker = env.start(first_init=True, direct_permission_check=False)
    assert reader.calls == []
    assert _buy(env, broker).status == bt.Order.Submitted


def test_permissions_are_read_even_while_writes_are_disabled(env):
    """A read-only start (write admission off) still reports the facts."""
    env.api.write_admission.enabled = False
    reader, _session = _install(env, _permissions(_negative(SYMBOL)))
    broker = env.start(first_init=True)
    assert len(reader.calls) == 1
    report = broker.get_direct_reconcile_report()["permissions"]
    assert report["instruments"][SYMBOL]["denial_reasons"] == ["trading_code_absent"]
    assert _buy(env, broker).info["error_code"] == "write_admission_disabled"


# ---------------------------------------------------------------------------
# two-sided venue positions are no reason to refuse BT net (D62-25)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mode", ["net", "dual_side"])
def test_two_sided_venue_positions_do_not_refuse_either_bt_mode(env, mode):
    env.init_flat()
    env.write_snapshot({SYMBOL: snap(long=(1, 0, 1), short=(1, 0, 1))})
    env.api.positions = [position("long", 1, 0, 1), position("short", 1, 0, 1)]
    _install(env, _permissions(_entry(SYMBOL), _entry(OTHER_SYMBOL)))
    broker = env.start(position_mode=mode)
    assert broker.direct_writes_blocked() == {}
    extra = {"position_side": "long"} if mode == "dual_side" else {}
    order = _buy(env, broker, **extra)
    assert order.status == bt.Order.Submitted
    assert broker.getposition(env.feed).size == 0  # net projection of a locked position
    assert broker.getposition(env.feed, side="long").size == 1
    assert broker.getposition(env.feed, side="short").size == 1


# ---------------------------------------------------------------------------
# the CTP provider's neutral type (when installed)
# ---------------------------------------------------------------------------
def test_the_ctp_result_type_drives_the_same_refusal(env):
    module = pytest.importorskip("bt_api_ctp.trading_permission_facts")
    fact = module.PermissionFact

    def entry(symbol, code_status, code_reason):
        return module.InstrumentPermissionFacts(
            symbol=symbol,
            venue=VENUE,
            facts=(
                fact("investor_active", "known_positive", "investor_active", True),
                fact("trading_code", code_status, code_reason, True),
                fact("instrument_trading", "known_positive", "instrument_trading", True),
            ),
        )

    facts = module.TradingPermissionFacts(
        exchange_name=EXCHANGE,
        trading_day=TODAY,
        session_generation=1,
        observed_at_utc="2026-11-05T07:00:00Z",
        instruments=(
            entry(SYMBOL, "known_negative", "trading_code_absent"),
            entry(OTHER_SYMBOL, "known_positive", "speculation_code_active"),
        ),
        session_consistent=True,
    )
    _install(env, facts)
    broker = env.start(first_init=True)
    assert _buy(env, broker).info["error_code"] == DENIED
    assert _buy(env, broker, env.other_feed).status == bt.Order.Submitted

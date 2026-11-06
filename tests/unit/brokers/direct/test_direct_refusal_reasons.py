"""Target-data refusal reasons in direct mode (iteration 62 decision 6, 2026-11-06).

A refused order reports the main cause in ``error_code`` (prefix
``target_data_not_tradable:`` kept for log consumers), the full reason list in
``order.info["refusal_reasons"]`` and in the error message, and the full list
in one throttled warning per cause.  Formerly only the first three reasons
were joined into ``error_code`` (``RECEIVE_TIME_STALE`` could be cut off).

UNIT/FAKE: fake facade + real ``backtrader.live_state`` in ``tmp_path``.
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt
from backtrader.brokers import _btapi_direct_mode as direct_mode

from ._fakes import SYMBOL, not_live


@pytest.fixture
def broker(env):
    return env.start(first_init=True)


@pytest.fixture
def warnings(monkeypatch):
    calls = []
    monkeypatch.setattr(direct_mode, "throttled_warning", lambda *a, **k: calls.append(a))
    return calls


def _refused(env, broker, *reasons):
    env.feed.qualification = SimpleNamespace(ok=False, reasons=tuple(reasons))
    order = broker.buy(
        env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit, offset="open"
    )
    assert order.status == bt.Order.Rejected
    assert env.api.place_calls == []
    return order


def test_main_cause_in_error_code_and_every_reason_kept(env, broker, warnings):
    # The SimNow hc2701 shape (2026-11-05) plus the reason that used to be cut off.
    reasons = (
        "FRESHNESS_STALE",
        "UPSTREAM_EXECUTION_INELIGIBLE",
        "EVENT_TIME_STALE",
        "RECEIVE_TIME_STALE",
    )
    order = _refused(env, broker, *reasons)
    assert order.info["error_code"] == "target_data_not_tradable:RECEIVE_TIME_STALE"
    assert order.info["refusal_reasons"] == reasons
    assert order.info["error_msg"].endswith("(all reasons: " + ",".join(reasons) + ")")
    (call,) = warnings
    assert call[1] == "direct_order_refused:target_data_not_tradable:RECEIVE_TIME_STALE"
    assert call[3:] == (SYMBOL, order.info["error_code"], ",".join(reasons))


@pytest.mark.parametrize(
    "reasons, main",
    [
        (
            ("UPSTREAM_EXECUTION_INELIGIBLE", "FRESHNESS_STALE", "EVENT_TIME_STALE"),
            "EVENT_TIME_STALE",
        ),
        (("UPSTREAM_EXECUTION_INELIGIBLE", "FRESHNESS_STALE"), "FRESHNESS_STALE"),
        (
            ("UPSTREAM_EXECUTION_INELIGIBLE", "FRESHNESS_UNAVAILABLE", "SOURCE_CLOCK_UNVERIFIED"),
            "SOURCE_CLOCK_UNVERIFIED",
        ),
        (("RECEIVE_TIME_STALE", "RECEIVE_CLOCK_UNVERIFIED"), "RECEIVE_CLOCK_UNVERIFIED"),
        (("RECEIVE_TIME_STALE", "TICK_EVENT_TIME_UNAVAILABLE"), "TICK_EVENT_TIME_UNAVAILABLE"),
        (("REALTIME_TICK_UNAVAILABLE",), "REALTIME_TICK_UNAVAILABLE"),
        (("RECEIVE_TIME_STALE", "RECEIVE_TIME_MAX_AGE_INVALID"), "RECEIVE_TIME_MAX_AGE_INVALID"),
        (("UPSTREAM_EXECUTION_INELIGIBLE",), "UPSTREAM_EXECUTION_INELIGIBLE"),
        (("NEW_CODE", "UPSTREAM_EXECUTION_INELIGIBLE"), "UPSTREAM_EXECUTION_INELIGIBLE"),
        (("NEW_CODE", "OTHER_CODE"), "NEW_CODE"),
        ((), "UNSPECIFIED"),
    ],
)
def test_main_cause_priority(env, broker, reasons, main):
    order = _refused(env, broker, *reasons)
    assert order.info["error_code"] == "target_data_not_tradable:" + main
    assert order.info["refusal_reasons"] == reasons


def test_not_live_keeps_its_code_and_the_full_list(env, broker, warnings):
    env.feed.qualification = SimpleNamespace(
        ok=False, reasons=("FEED_NOT_LIVE", "REALTIME_TICK_UNAVAILABLE")
    )
    order = broker.buy(
        env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit, offset="open"
    )
    assert order.info["error_code"] == "target_feed_not_live"
    assert order.info["refusal_reasons"] == ("FEED_NOT_LIVE", "REALTIME_TICK_UNAVAILABLE")
    assert len(warnings) == 1


def test_other_refusals_carry_no_reason_list(env, broker, warnings):
    order = broker.buy(env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit)
    assert order.info["error_code"] == "explicit_offset_required"
    assert "refusal_reasons" not in order.info
    assert warnings == []


def test_accepted_orders_are_not_logged(env, broker, warnings):
    not_live(env.other_feed)  # another feed does not matter (D62-15b)
    order = broker.buy(
        env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit, offset="open"
    )
    assert order.status == bt.Order.Submitted
    assert warnings == []

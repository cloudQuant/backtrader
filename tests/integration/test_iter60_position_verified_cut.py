"""F4 (复验报告 2026-11-03): the direct position subscription's ledger evidence.

Only a bound ``BootstrapPositionReporter`` (verified snapshot cut + contiguous
stream) can make a report complete; the Store snapshot/push state is
diagnostic and always incomplete. The verifier is a local test double.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

pytest.importorskip("bt_api_py.position_stream_bootstrap")

from backtrader.stores._account_position_subscription import (  # noqa: E402
    StoreAccountPositionSubscription,
)
from bt_api_py.account_position_stream import BootstrapPositionReporter  # noqa: E402

from bt_api_base.account_protocol import (  # noqa: E402
    AccountKey,
    AccountPosition,
    AccountResourceKey,
)
from bt_api_base.market_protocol import MarketInstrumentKey  # noqa: E402
from bt_api_base.position_bootstrap_protocol import (  # noqa: E402
    PositionStreamBinding,
    PositionStreamEvent,
    PositionStreamSnapshot,
)
from bt_api_py.position_stream_bootstrap import PositionStreamBootstrap  # noqa: E402


def _row(quantity="1"):
    return AccountPosition(
        AccountResourceKey("future", "default"),
        MarketInstrumentKey("ctp", "CZCE", "simnow", "future", "SA2701", "SA2701"),
        "net",
        quantity,
        "contracts",
        None,
        None,
        "2026-11-03T00:00:00Z",
    )


class _Verifier:
    """Local test double, not a provider adapter."""

    def __init__(self, binding):
        self.binding, self.claims = binding, []

    def verify_binding(self, binding):
        return binding == self.binding

    def verify_snapshot(self, binding, snapshot):
        return binding == self.binding and snapshot in self.claims

    def verify_event(self, binding, event):
        return binding == self.binding and event in self.claims

    def verify_live(self, binding, now_ns):
        return binding == self.binding


def _build():
    binding = PositionStreamBinding(
        AccountKey("ctp", "simnow", "simnow", "local-account"),
        "account-a", "CTP___FUTURE", "session-1", 1, 1, "ready-receipt", 200,
    )
    verifier = _Verifier(binding)
    now = [100]
    return binding, verifier, now, PositionStreamBootstrap(binding, verifier, clock_ns=lambda: now[0])


def _snapshot(binding, verifier, *, cut, rows):
    snapshot = PositionStreamSnapshot(binding, cut, 90, "snapshot-receipt", tuple(rows))
    verifier.claims.append(snapshot)
    return snapshot


def _event(binding, verifier, seq, quantity):
    event = PositionStreamEvent(binding, seq, 95, f"event-{seq}", _row(quantity))
    verifier.claims.append(event)
    return event


class _Store:
    _sdk_mode = True
    provider = "ctp"

    def __init__(self, hook=None):
        self.reads = 0
        if hook is not None:
            self.position_stream_verified_cut = hook

    def get_positions(self):
        self.reads += 1
        return [
            {
                "data_name": "SA2701",
                "side": "net",
                "quantity": "2",
                "observed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
        ]


def _cut():
    binding, verifier, now, stream = _build()
    stream.push(_event(binding, verifier, 11, "2"))
    stream.install_snapshot(_snapshot(binding, verifier, cut=10, rows=()))
    return BootstrapPositionReporter(
        stream, account_ref="account-a", source="ctp:verified-cut", clock_ns=lambda: now[0]
    )


def test_without_a_verified_cut_every_report_is_incomplete():
    subscription = StoreAccountPositionSubscription(_Store(), "account-a")
    subscription.on_position_event({"symbol": "SA2701", "position_side": "net", "quantity": 2})
    report = subscription.report()
    assert report.complete is False  # snapshot + pushes are diagnostic only


def test_a_bound_verified_cut_is_the_only_evidence():
    store = _Store()
    subscription = StoreAccountPositionSubscription(store, "account-a", verified_cut=_cut())
    report = subscription.report()
    assert report.complete is True and report.positions == {"SA2701": Decimal("2")}
    assert store.reads == 0  # no diagnostic snapshot read once a cut is bound


def test_store_hook_supplies_the_verified_cut():
    cut = _cut()
    subscription = StoreAccountPositionSubscription(_Store(hook=lambda ref: cut), "account-a")
    assert subscription.verified_cut is cut and subscription.report().complete is True


def test_verified_cut_must_belong_to_the_account():
    with pytest.raises(ValueError):
        StoreAccountPositionSubscription(_Store(), "account-b", verified_cut=_cut())
    with pytest.raises(ValueError):
        StoreAccountPositionSubscription(_Store(), "account-a", verified_cut=object())


def test_a_broken_cut_stays_incomplete():
    binding, verifier, now, stream = _build()
    stream.install_snapshot(_snapshot(binding, verifier, cut=10, rows=(_row("2"),)))
    stream.interrupt("STREAM_DISCONNECTED")
    cut = BootstrapPositionReporter(stream, account_ref="account-a", source="ctp:verified-cut")
    subscription = StoreAccountPositionSubscription(_Store(), "account-a", verified_cut=cut)
    assert subscription.report().complete is False

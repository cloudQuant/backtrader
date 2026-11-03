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


# ---------------------------------------------------------------------------
# Provider-declared cut capability through the Store hooks (F4, end to end)
# ---------------------------------------------------------------------------


class _CutProvider:
    """FAKE provider capability: numbered pushes, sequenced snapshot (UNIT/FAKE)."""

    def __init__(self, now):
        self.now, self.positions, self.sequence, self.epoch = now, {}, 0, 0
        self.claims, self.binding, self.during_read, self.listener = [], None, None, None

    def change(self, name, quantity, deliver=True):
        self.positions[name] = quantity
        self.sequence += 1
        event = {"kind": "position", "symbol": name, "position_side": "net",
                 "quantity": quantity, "epoch": self.epoch, "sequence": self.sequence}
        if deliver:
            self.listener(event)

    def open_position_stream(self, account_ref):
        self.epoch += 1
        self.sequence = 0
        self.binding = PositionStreamBinding(
            AccountKey("ctp", "simnow", "simnow", "local-account"),
            account_ref, "FAKE", "session-1", 1, self.epoch, f"ready-{self.epoch}",
            self.now[0] + 10**12,
        )
        return self.binding

    def position_stream_verifier(self, binding):
        provider = self

        class _V:
            def verify_binding(self, b):
                return b == provider.binding

            def verify_snapshot(self, b, snapshot):
                return b == provider.binding and snapshot in provider.claims

            def verify_event(self, b, event):
                return b == provider.binding and event in provider.claims

            def verify_live(self, b, now_ns):
                return b == provider.binding

        return _V()

    def read_position_cut(self, binding):
        cut = self.sequence
        rows = tuple(_row(str(q)) for name, q in self.positions.items() if q)
        if self.during_read is not None:
            self.during_read()
        snapshot = PositionStreamSnapshot(binding, cut, self.now[0], f"cut-{cut}", rows)
        self.claims.append(snapshot)
        return snapshot

    def position_stream_event(self, binding, raw):
        if raw.get("epoch") != binding.subscription_epoch:
            return None
        event = PositionStreamEvent(
            binding, raw["sequence"], self.now[0], f"push-{raw['sequence']}",
            _row(str(raw["quantity"])),
        )
        self.claims.append(event)
        return event


class _CapabilityStore(_Store):
    def __init__(self, capability, reason=None):
        super().__init__()
        self._capability, self._reason = capability, reason

    def position_stream_cut_capability(self, account_ref):
        return self._capability, self._reason


def _subscribe(store):
    """Mirror ``BtApiStore.subscribe_account_positions`` (listener before read)."""
    subscription = StoreAccountPositionSubscription(store, "account-a")
    if store._capability is not None:
        store._capability.listener = subscription.on_position_event
    subscription.start()
    return subscription


def test_push_during_cut_read_is_replayed_and_the_ledger_balances(tmp_path):
    """F4 counterexample: X=1 pushed during the read of an empty snapshot."""
    from bt_api_py.strategy_ledger import (
        InstrumentTerms, LedgerIntent, SqliteStrategyLedger, StrategyBudget,
    )
    import time

    now = [time.time_ns()]
    provider = _CutProvider(now)
    provider.during_read = lambda: provider.change("SA2701", 1)
    store = _CapabilityStore(provider)
    subscription = _subscribe(store)
    report = subscription.report()
    assert report.complete is True and report.positions == {"SA2701": Decimal("1")}
    assert store.reads == 0  # evidence never comes from a per-query provider read
    ledger = SqliteStrategyLedger(
        tmp_path / "ledger.sqlite3",
        account_ref="account-a",
        instruments={"SA2701": InstrumentTerms(Decimal("1"), "CNY", "futures")},
        budgets={"A": StrategyBudget(Decimal("1000000"), "CNY")},
    )
    try:
        assert ledger.reconcile(subscription.report()).state == "RESIDUAL"  # empty book
        ledger.reserve(LedgerIntent("a", "A", "SA2701", "BUY", Decimal("1"), Decimal("10")))
        ledger.apply_execution("a", cumulative_quantity=1, average_price=10)
        assert ledger.reconcile(subscription.report()).state == "BALANCED"
        subscription.on_disconnect()
        outcome = ledger.reconcile(subscription.report())
        assert (outcome.state, outcome.reason) == ("UNVERIFIED", "REPORT_INCOMPLETE")
    finally:
        ledger.close()


def test_interrupted_cut_reopens_a_new_epoch_rate_limited():
    now = [10**18]
    provider = _CutProvider(now)
    store = _CapabilityStore(provider)
    subscription = StoreAccountPositionSubscription(
        store, "account-a", baseline_interval_seconds=1.0, clock_ns=lambda: now[0]
    )
    provider.listener = subscription.on_position_event
    assert subscription.start() is True
    provider.change("SA2701", 3, deliver=False)  # lost push
    provider.change("SA2701", 4)  # gap detected
    assert subscription.report().complete is False and provider.epoch == 1
    now[0] += 2 * 10**9
    report = subscription.report()
    assert provider.epoch == 2 and report.complete is True
    assert report.positions == {"SA2701": Decimal("4")}


def test_undeclared_provider_stays_incomplete_with_the_missing_fact():
    store = _CapabilityStore(None, "POSITION_PUSH_HAS_NO_SEQUENCE")
    subscription = _subscribe(store)
    assert subscription.cut_unavailable_reason == "POSITION_PUSH_HAS_NO_SEQUENCE"
    assert subscription.report().complete is False


def test_btapistore_hook_resolves_through_the_sdk():
    from types import SimpleNamespace

    from backtrader.stores.btapistore import BtApiStore

    for provider, reason in (
        ("OKX___SWAP", "POSITION_PUSH_HAS_NO_SEQUENCE"),
        ("BINANCE___SWAP", "POSITION_PUSH_HAS_NO_UPDATE_ID"),
        ("CTP___FUTURE", "NO_POSITION_PUSH"),
    ):
        fake = SimpleNamespace(_api=object(), provider=provider)
        assert BtApiStore.position_stream_cut_capability(fake, "account-a") == (None, reason)
    declared = _CutProvider([1])
    fake = SimpleNamespace(
        _api=SimpleNamespace(position_stream_cut_capability=declared), provider="x"
    )
    assert BtApiStore.position_stream_cut_capability(fake, "account-a") == (declared, None)


def test_btapistore_installs_the_listener_before_the_first_read():
    import time
    from types import SimpleNamespace

    from backtrader.stores.btapistore import BtApiStore

    provider = _CutProvider([time.time_ns()])
    store = SimpleNamespace(
        _sdk_mode=True, provider="fake", _account_position_subscription=None,
        position_stream_cut_capability=lambda ref: (provider, None),
    )
    # The Store's event dispatch routes pushes to the *installed* subscription;
    # a push during the first snapshot read must reach it and be replayed.
    provider.listener = lambda event: store._account_position_subscription.on_position_event(
        event
    )
    provider.during_read = lambda: provider.change("SA2701", 2)
    subscription = BtApiStore.subscribe_account_positions(store, "account-a")
    assert store._account_position_subscription is subscription
    report = subscription.report()
    assert report.complete is True and report.positions == {"SA2701": Decimal("2")}

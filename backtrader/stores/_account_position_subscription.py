"""Direct-mode account positions by subscription, for strategy-ledger reconciliation.

Iteration 60 (acceptance report F5, user decision 2026-11-03): in direct mode
the provider's websocket position channel feeds an SDK
``bt_api_py.account_position_stream.StreamedAccountPositions``; the strategy
ledger reconciles against its ``report()`` without a provider read per query.

A websocket only pushes *changes*, so it cannot prove by itself that a quiet
account is still current, nor that no push was lost. The current Store snapshot
projection has no provider watermark tying it to the stream, and the Store
does not install this listener until after its initial read. Consequently these
snapshots and pushes are diagnostic only: reconciliation remains incomplete
until a trusted snapshot/stream continuity contract is available.

That contract is ``bt_api_py.position_stream_bootstrap.PositionStreamBootstrap``
behind a trusted provider verifier (snapshot at a stream cut + contiguous
sequenced events + a current lease). A provider declares that it can supply
it through the SDK's neutral ``PositionStreamCutCapability``; the SDK's
``VerifiedPositionStreamCut`` then opens the push subscription *before* the
snapshot read, buffers pushes during the read and replays those after the cut
(F4), and re-opens a new subscription epoch after an interruption. Evidence
sources, in order:

1. ``verified_cut=``: a ``BootstrapPositionReporter`` or a
   ``VerifiedPositionStreamCut`` for this account;
2. the Store's ``position_stream_verified_cut(account_ref)`` hook (same types);
3. the Store's ``position_stream_cut_capability(account_ref)`` hook, which
   returns ``(capability, reason)`` from the SDK resolver.

With none of them every report is incomplete and ``cut_unavailable_reason``
names the missing provider fact. None of the built-in providers declares the
capability today (see ``bt_api_py.position_stream_bootstrap.
PROVIDER_CUT_UNAVAILABLE``): the OKX ``positions`` channel carries no
sequence, Binance ``ACCOUNT_UPDATE`` has no update id and pushes changed
positions only, and CTP has no position push at all.

The Store keeps only this framework wiring; the evidence rules live in the SDK.
"""

from __future__ import annotations

import datetime as _dt
import time
from decimal import Decimal, InvalidOperation

__all__ = ["StoreAccountPositionSubscription"]


def _utc_ns(text):
    if type(text) is not str or not text:
        return None
    try:
        moment = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return int(moment.timestamp() * 1_000_000_000)


def _seconds_ns(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not number > 0 or number != number or number == float("inf"):
        return None
    return int(number * 1_000_000_000)


class StoreAccountPositionSubscription:
    """Keep one account's subscribed positions for ``AccountPositionReport``s."""

    def __init__(
        self,
        store,
        account_ref,
        *,
        baseline_interval_seconds=10.0,
        clock_ns=time.time_ns,
        verified_cut=None,
    ):
        from bt_api_py.account_position_stream import (
            BootstrapPositionReporter,
            StreamedAccountPositions,
        )

        if not getattr(store, "_sdk_mode", False):
            raise ValueError("account position subscriptions need the unified SDK path")
        interval = float(baseline_interval_seconds)
        if not interval > 0:
            raise ValueError("baseline_interval_seconds must be positive")
        provider = getattr(store, "provider", None) or "sdk"
        self.positions = StreamedAccountPositions(
            account_ref, f"btapistore:{provider}:position_stream", clock_ns=clock_ns
        )
        self._store = store
        self._clock_ns = clock_ns
        self._interval_ns = int(interval * 1_000_000_000)
        self._baseline_ns = None
        self.baseline_failures = 0
        from bt_api_py.position_stream_bootstrap import VerifiedPositionStreamCut

        self.cut_unavailable_reason = None
        if verified_cut is None:
            hook = getattr(store, "position_stream_verified_cut", None)
            verified_cut = hook(account_ref) if callable(hook) else None
        if verified_cut is None:
            resolver = getattr(store, "position_stream_cut_capability", None)
            capability, reason = resolver(account_ref) if callable(resolver) else (
                None, "PROVIDER_CUT_NOT_DECLARED"
            )
            if capability is not None:
                verified_cut = VerifiedPositionStreamCut(
                    capability,
                    account_ref=account_ref,
                    source=f"btapistore:{provider}:verified_position_cut",
                    clock_ns=clock_ns,
                    retry_interval_ns=self._interval_ns,
                )
            else:
                self.cut_unavailable_reason = reason
        if verified_cut is not None and (
            type(verified_cut) not in (BootstrapPositionReporter, VerifiedPositionStreamCut)
            or verified_cut.account_ref != account_ref
        ):
            raise ValueError(
                "verified_cut must be this account's BootstrapPositionReporter"
                " or VerifiedPositionStreamCut"
            )
        self.verified_cut = verified_cut
        self._driver = verified_cut if type(verified_cut) is VerifiedPositionStreamCut else None
        self._driver_reporter = None if self._driver is None else self._driver.reporter()

    @property
    def account_ref(self):
        return self.positions.account_ref

    # -- feeding -----------------------------------------------------------

    def start(self):
        """Open the verified cut when a provider declared one, else a baseline."""

        if self._driver is not None:
            return self._driver.start()
        if self.verified_cut is not None:
            return self.verified_cut.report().complete
        return self.baseline()

    def baseline(self):
        """Replace the state with one complete SDK position snapshot."""

        read_ns = int(self._clock_ns())
        revision = self.positions.snapshot_revision()
        try:
            rows = self._store.get_positions()
            snapshot: dict[tuple[str, str], Decimal] = {}
            observed: list[int] = []
            for row in rows:
                name, side = row.get("data_name"), row.get("side")
                quantity = Decimal(str(row.get("quantity")))
                stamp = _utc_ns(row.get("observed_at_utc"))
                if (
                    type(name) is not str
                    or not name
                    or side not in ("net", "long", "short")
                    or not quantity.is_finite()
                    or stamp is None
                ):
                    raise ValueError("position row is not usable evidence")
                key = (name, side)
                snapshot[key] = snapshot.get(key, Decimal("0")) + quantity
                observed.append(stamp)
        except (InvalidOperation, ValueError, TypeError, AttributeError):
            self._failed("BASELINE_ROW_INVALID")
            return False
        except Exception:
            self._failed("BASELINE_READ_FAILED")
            return False
        # The oldest row's provider time: an old row cannot look fresh.
        unchanged = self.positions.apply_unverified_snapshot(
            snapshot, observed_ns=min(observed) if observed else read_ns, revision=revision
        )
        self._baseline_ns = read_ns
        if not unchanged:
            self.baseline_failures += 1
        # The read carries no stream watermark, including when no local event
        # was observed. Quiet locally does not establish provider continuity.
        return False

    def on_position_event(self, event):
        """Apply one SDK ``position`` event (absolute quantity)."""

        if self._driver is not None:
            # The verified cut owns ledger evidence; the diagnostic state below
            # is still kept for display.
            self._driver.on_event(event)
        name = event.get("symbol")
        side = event.get("position_side") or "net"
        if event.get("quantity_known") is False:
            self.positions.mark_interrupted("POSITION_QUANTITY_UNKNOWN")
            return
        stamp = _seconds_ns(event.get("exchange_time")) or _seconds_ns(event.get("local_time"))
        try:
            quantity = Decimal(str(event.get("quantity")))
            if type(name) is not str or not name or side not in ("net", "long", "short"):
                raise ValueError
            self.positions.apply_position(name, side, quantity, observed_ns=stamp)
        except Exception:
            self.positions.mark_interrupted("POSITION_EVENT_INVALID")

    def on_disconnect(self, event=None):
        if self._driver is not None:
            self._driver.on_disconnect("STREAM_DISCONNECTED")
        self.positions.mark_interrupted("STREAM_DISCONNECTED")

    def _failed(self, reason):
        self.baseline_failures += 1
        self.positions.mark_interrupted(reason)

    # -- reading -----------------------------------------------------------

    def report(self):
        """Evidence for the ledger: the verified cut, else always incomplete.

        Without a verified cut the diagnostic state is refreshed (baseline when
        due or interrupted) and returned, but it is never complete.
        """

        if self._driver is not None:
            # Re-open a new subscription epoch after an interruption, rate
            # limited by the baseline interval; never a provider read per query.
            self._driver.restart_if_due()
            return self._driver_reporter.report()
        if self.verified_cut is not None:
            return self.verified_cut.report()
        now = int(self._clock_ns())
        due = self._baseline_ns is None or now - self._baseline_ns >= self._interval_ns
        if due or self.positions.interruption not in (
            None, "BASELINE_CONTINUITY_UNPROVEN", "BASELINE_STREAM_CHANGED"
        ):
            self.baseline()
        return self.positions.report()

    __call__ = report

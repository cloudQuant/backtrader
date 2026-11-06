"""Automatic acceptance of a provider-declared tick-stream restart (Store side).

Iteration 62, D62-38 point 7 (continuity-7). After a front disconnect the CTP
direct adapter starts a new market-data session and, once it is ticking,
declares ``PROVIDER_RESYNC_REQUIRED`` for every channel of the lost session
(bt_api_ctp ``1b45673``; the SDK owner keeps that code as the subscription's
``recovery_code``, SDK ``dec197d4``). The SDK never acknowledges the data loss
itself; the consumer must call ``accept_resync(acknowledge_data_loss=True)``,
which binds the channel to the new session under a new epoch.

This module holds only the Backtrader decision of *when* the Store makes that
call for a tick channel:

* only for ``PROVIDER_RESYNC_REQUIRED``; every other recovery code (queue
  overflow, cursor gap, source mismatch, route change, a provider poll failure
  without a declared cause) stays fail closed until an explicit decision;
* ``PROVIDER_RESYNC_FAILED`` is retried only for a symbol whose own restart is
  open: the SDK owner replaces the declared code with it after an
  ``accept_resync`` of that provider session failed (the provider was still
  recovering), so it continues a restart whose data loss this Store already
  acknowledged. (The SDK owner keys provider sessions by route *and*
  instrument, so a failed resync re-marks only that symbol's channels.)
* attempts per symbol back off: immediately, then 1, 2, 5, 10 and 30 s
  (30 s cap); a success resets the symbol;
* never after the Store was asked to stop, until a new start resets it;
* only for direct provider streams. A Store whose ticks come from a Gateway
  market runtime (``market_runtime_factory``) keeps every recovery fail closed:
  there ``PROVIDER_RESYNC_REQUIRED`` is a hub-side projector resync that may
  keep the same connection/subscription scope, so the Feed would not
  invalidate a bar spanning the lost ticks. The CTP direct restart always
  binds a new MD session with a higher connection generation.

Neutral contracts, provider sessions and queues stay with the SDK/provider.
The Store's health projection is unchanged: its ``stale`` flag stays the
cumulative loss evidence of the typed path (a resync does not clear it). The
Feed decides LIVE and trade qualification from the ticks themselves: the new
epoch is a new scope, the open bar is invalidated, and the first fresh, valid
tick of the new session is tradable (D62-38).
"""

from __future__ import annotations

import time
from typing import Callable, Dict, Optional, Tuple

#: The only provider-declared cause the Store acknowledges by itself.
RESYNC_REQUIRED_CODE = "PROVIDER_RESYNC_REQUIRED"
#: SDK owner code after a failed ``accept_resync`` of the same provider session.
RESYNC_FAILED_CODE = "PROVIDER_RESYNC_FAILED"
#: Delay before attempt ``n + 1`` after attempt ``n`` (index ``n``, capped).
RESYNC_BACKOFF_SECONDS: Tuple[float, ...] = (0.0, 1.0, 2.0, 5.0, 10.0, 30.0)


class _Restart:
    """One symbol's open provider restart."""

    __slots__ = ("attempts", "next_attempt_at", "warned")

    def __init__(self) -> None:
        self.attempts = 0
        self.next_attempt_at = 0.0  # the first attempt is immediate
        self.warned = False


class TickStreamResyncPolicy:
    """Per-symbol state of the Store's automatic tick-stream resync."""

    def __init__(
        self, *, enabled: bool = True, monotonic: Callable[[], float] = time.monotonic
    ) -> None:
        self._enabled = enabled is True
        self._monotonic = monotonic
        self._restarts: Dict[str, _Restart] = {}
        self._fenced = False

    # -- lifecycle ---------------------------------------------------------

    def fence(self) -> None:
        """Stop: no automatic resync from now on (until :meth:`reset`)."""
        self._fenced = True

    def reset(self) -> None:
        """A new Store start: forget every restart and lift the stop fence."""
        self._restarts.clear()
        self._fenced = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def fenced(self) -> bool:
        return self._fenced

    # -- decisions ---------------------------------------------------------

    def due(self, symbol: str, recovery_code: Optional[str]) -> bool:
        """Whether the Store should call ``accept_resync`` for ``symbol`` now.

        Called for a tick channel in RECOVERY_REQUIRED. Opens a restart for
        ``PROVIDER_RESYNC_REQUIRED``; keeps one open for
        ``PROVIDER_RESYNC_FAILED``; any other code ends it (fail closed).
        """
        if not self._enabled:
            return False
        restart = self._restarts.get(symbol)
        if recovery_code == RESYNC_REQUIRED_CODE:
            if restart is None:
                restart = self._restarts[symbol] = _Restart()
        elif recovery_code != RESYNC_FAILED_CODE or restart is None:
            self._restarts.pop(symbol, None)
            return False
        if self._fenced:
            return False
        return self._monotonic() >= restart.next_attempt_at

    def begin_attempt(self, symbol: str) -> Tuple[int, bool]:
        """Record one attempt; return ``(attempt_number, warn_now)``.

        The next attempt is allowed after the backoff of this attempt, so an
        unexpected error raised by the attempt still cannot cause a loop.
        """
        restart = self._restarts.setdefault(symbol, _Restart())
        restart.attempts += 1
        delay = RESYNC_BACKOFF_SECONDS[min(restart.attempts, len(RESYNC_BACKOFF_SECONDS) - 1)]
        restart.next_attempt_at = self._monotonic() + delay
        warn_now = not restart.warned
        restart.warned = True
        return restart.attempts, warn_now

    def retry_in(self, symbol: str) -> float:
        """Seconds until the next attempt of ``symbol`` is allowed."""
        restart = self._restarts.get(symbol)
        if restart is None:
            return 0.0
        return max(restart.next_attempt_at - self._monotonic(), 0.0)

    def succeeded(self, symbol: str) -> int:
        """Close the restart of ``symbol``; return how many attempts it took."""
        restart = self._restarts.pop(symbol, None)
        return restart.attempts if restart is not None else 0

    def observe_active(self, symbol: str) -> None:
        """The stream of ``symbol`` is active: no restart is pending for it."""
        if self._restarts:
            self._restarts.pop(symbol, None)


__all__ = (
    "RESYNC_BACKOFF_SECONDS",
    "RESYNC_FAILED_CODE",
    "RESYNC_REQUIRED_CODE",
    "TickStreamResyncPolicy",
)

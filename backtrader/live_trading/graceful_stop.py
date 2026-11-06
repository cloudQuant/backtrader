"""Graceful stop of a live ``Cerebro`` run on SIGTERM (iteration 62, S-23).

An operating system (or a supervisor such as bt_api_runtime) stops a process
with SIGTERM, whose default action ends the process at once: ``cerebro.run()``
never returns, so the Broker's stop path (e.g. the direct mode's cancel of the
strategy's own working orders, the wait for an in-flight write, the final
snapshot and the run-lock release) never runs.  Inside
:func:`stop_on_terminate` a SIGTERM instead requests ``cerebro.runstop()``,
the same graceful stop as a run timeout, so ``run()`` returns and the caller's
normal stop and ``finally`` paths run.

* Installed on the main thread only (Python delivers signals there); on any
  other thread nothing is installed and ``installed`` is empty.
* SIGINT is untouched (Ctrl+C keeps raising ``KeyboardInterrupt``).
* A signal before the run is active (setup, Broker start) is latched and
  delivered as soon as the run scope opens; ``runstop()`` alone would ignore it.
* A second SIGTERM while the stop is running only repeats the request: it
  never aborts the graceful stop.  To end a hung stop use SIGKILL.
* Windows: ``TerminateProcess`` (also ``os.kill`` with SIGTERM) cannot be
  caught at all; SIGBREAK (Ctrl+Break, or ``CTRL_BREAK_EVENT`` sent to the
  process group) is registered where available and handled like SIGTERM.
* The previous handlers are restored when the context exits.

The handler itself only sets flags and calls ``runstop()`` (thread-safe); it
never logs, so it cannot block on a lock held by the interrupted code.
"""

from __future__ import annotations

import signal
import threading
from typing import Any, Dict, Optional, Tuple

__all__ = ("TerminateStop", "stop_on_terminate")

_POLL_SECONDS = 0.05


def _terminate_signals() -> Tuple[int, ...]:
    names = ("SIGTERM", "SIGBREAK")  # SIGBREAK exists on Windows only
    return tuple(getattr(signal, name) for name in names if hasattr(signal, name))


class TerminateStop:
    """Context manager: SIGTERM/SIGBREAK request a graceful ``cerebro.runstop()``.

    Attributes:
        installed: names of the signals whose handler this context installed.
        received: name of the first terminate signal received, else ``None``.
        count: number of terminate signals received.
    """

    def __init__(self, cerebro: Any) -> None:
        if not callable(getattr(cerebro, "runstop", None)):
            raise TypeError("stop_on_terminate needs an object with runstop()")
        self._cerebro = cerebro
        self._previous: Dict[int, Any] = {}
        self._closed = threading.Event()
        self._pending = threading.Event()
        self._deliverer: Optional[threading.Thread] = None
        self.installed: Tuple[str, ...] = ()
        self.received: Optional[str] = None
        self.count = 0

    def __enter__(self) -> "TerminateStop":
        if threading.current_thread() is not threading.main_thread():
            return self
        names = []
        for signum in _terminate_signals():
            try:
                self._previous[signum] = signal.signal(signum, self._handle)
            except (OSError, RuntimeError):
                continue  # not catchable here; the default stays
            names.append(signal.Signals(signum).name)
        self.installed = tuple(names)
        return self

    def __exit__(self, *_exc: Any) -> None:
        self._closed.set()
        for signum, previous in self._previous.items():
            try:
                signal.signal(signum, previous if previous is not None else signal.SIG_DFL)
            except (OSError, RuntimeError, ValueError):
                pass
        self._previous.clear()
        deliverer = self._deliverer
        if deliverer is not None:
            deliverer.join(timeout=1.0)

    def _handle(self, signum: int, _frame: Any) -> None:
        self.count += 1
        if self.received is None:
            self.received = signal.Signals(signum).name
        self._request_stop()

    def _request_stop(self) -> None:
        cerebro = self._cerebro
        if getattr(cerebro, "_run_active", True):
            cerebro.runstop()
            return
        # Not running yet: runstop() would be ignored, so deliver it once the
        # run scope opens (or drop it when this context closes first).
        self._pending.set()
        if self._deliverer is None:
            self._deliverer = threading.Thread(
                target=self._deliver_pending, name="bt-terminate-stop", daemon=True
            )
            self._deliverer.start()

    def _deliver_pending(self) -> None:
        cerebro = self._cerebro
        while not self._closed.wait(_POLL_SECONDS):
            if self._pending.is_set() and getattr(cerebro, "_run_active", False):
                cerebro.runstop()
                return


def stop_on_terminate(cerebro: Any) -> TerminateStop:
    """Return a context in which SIGTERM (SIGBREAK on Windows) stops ``cerebro`` gracefully.

    Example::

        with stop_on_terminate(cerebro) as termination:
            cerebro.run()
        print(termination.received)  # e.g. "SIGTERM", or None
    """
    return TerminateStop(cerebro)

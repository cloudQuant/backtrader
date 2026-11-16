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
* The first request (signal or :meth:`TerminateStop.request`) also records its
  source and UTC time (iteration 66, §5.2 B1(1)): the status file and the final
  summary publish them so a supervisor can start its stop deadline at the real
  first request.  The handler still only assigns flags and calls ``runstop()``
  (thread-safe); it never takes a lock, logs or does I/O.

The handler itself only sets flags and calls ``runstop()`` (thread-safe); it
never logs, so it cannot block on a lock held by the interrupted code.
"""

from __future__ import annotations

import datetime as _dt
import signal
import threading
from typing import Any, Dict, Optional, Tuple

from .stop_request_file import StopRequestFileSource

__all__ = ("TerminateStop", "stop_on_terminate")

_POLL_SECONDS = 0.05
_STOP_FILE_POLL_SECONDS = 0.2
#: Sources a request may name; ``stop_file``/``internal`` arrive through
#: :meth:`TerminateStop.request`, never through a signal.
STOP_REQUEST_SOURCES = ("SIGTERM", "SIGBREAK", "stop_file", "internal")


def _terminate_signals() -> Tuple[int, ...]:
    names = ("SIGTERM", "SIGBREAK")  # SIGBREAK exists on Windows only
    return tuple(getattr(signal, name) for name in names if hasattr(signal, name))


def _utc_text() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="microseconds")


class TerminateStop:
    """Context manager: SIGTERM/SIGBREAK request a graceful ``cerebro.runstop()``.

    Attributes:
        installed: names of the signals whose handler this context installed.
        received: name of the first terminate signal received, else ``None``.
        count: number of terminate signals received.
        source: first stop request source, including non-signal ones
            (``SIGTERM``/``SIGBREAK``/``stop_file``/``internal``), else ``None``.
        requested_at_utc: UTC time of the first stop request, else ``None``.
    """

    def __init__(
        self,
        cerebro: Any,
        *,
        stop_request_file: Optional[str] = None,
        stop_request_strategy_uuid: Optional[str] = None,
        stop_request_run_id: Optional[str] = None,
        stop_file_poll_interval_s: float = _STOP_FILE_POLL_SECONDS,
    ) -> None:
        if not callable(getattr(cerebro, "runstop", None)):
            raise TypeError("stop_on_terminate needs an object with runstop()")
        self._cerebro = cerebro
        self._previous: Dict[int, Any] = {}
        self._closed = threading.Event()
        self._pending = threading.Event()
        self._deliverer: Optional[threading.Thread] = None
        self._stop_file_thread: Optional[threading.Thread] = None
        self._stop_file_source: Optional[StopRequestFileSource] = None
        if stop_request_file is not None:
            # The opt-in file channel is bound to this exact strategy and run;
            # a missing identity would make every request unverifiable, so it
            # is refused here instead of silently weakening the check.
            if stop_request_strategy_uuid is None or stop_request_run_id is None:
                raise ValueError("stop_request_file needs strategy_uuid and run_id")
            if (
                type(stop_file_poll_interval_s) is bool
                or type(stop_file_poll_interval_s) not in (int, float)
                or not 0.0 < float(stop_file_poll_interval_s) <= 60.0
            ):
                raise ValueError("stop_file_poll_interval_s")
            self._stop_file_source = StopRequestFileSource(
                stop_request_file,
                strategy_uuid=stop_request_strategy_uuid,
                run_id=stop_request_run_id,
            )
        self._stop_file_poll_interval_s = float(stop_file_poll_interval_s)
        self.installed: Tuple[str, ...] = ()
        self.received: Optional[str] = None
        self.count = 0
        self.source: Optional[str] = None
        self.requested_at_utc: Optional[str] = None

    def __enter__(self) -> "TerminateStop":
        if self._stop_file_source is not None:
            self._stop_file_thread = threading.Thread(
                target=self._poll_stop_file,
                name="bt-stop-file",
                daemon=True,
            )
            self._stop_file_thread.start()
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
        for worker in (self._deliverer, self._stop_file_thread):
            if worker is not None:
                worker.join(timeout=1.0)

    def _handle(self, signum: int, _frame: Any) -> None:
        self.request(signal.Signals(signum).name, signal=True)

    def request(
        self,
        source: str = "internal",
        *,
        signal: bool = False,
        at_utc: Optional[str] = None,
    ) -> None:
        """Request the graceful stop from a non-signal caller (or the handler).

        Reuses the same latch as the signal handler: the request reaches
        ``runstop()`` now when the run is active, otherwise as soon as it opens.
        Only the first request records ``source``/``requested_at_utc``; later
        ones (including a second signal) only repeat the request.  ``at_utc``
        lets a stop-file request keep the supervisor's original request time.
        """
        if signal:
            self.count += 1
            if self.received is None:
                self.received = source
        if self.source is None:
            self.source = source if source in STOP_REQUEST_SOURCES else "internal"
            self.requested_at_utc = (
                at_utc if at_utc is not None else _utc_text()
            )
        self._request_stop()

    def _poll_stop_file(self) -> None:
        source = self._stop_file_source
        if source is None:  # pragma: no cover - only built with a source
            return
        while not self._closed.wait(self._stop_file_poll_interval_s):
            if self.source is not None:
                return  # a signal already requested the stop
            try:
                state = source.poll()
            except Exception:  # noqa: BLE001 - an unreadable request is not a stop
                continue
            if state is not None:
                self.request(state[0], at_utc=state[1])
                return

    def request_state(self) -> Optional[Tuple[str, Optional[str]]]:
        """``(source, requested_at_utc)`` of the first request, else ``None``.

        Lock-free and side-effect free: safe to poll from a status thread.
        """
        source = self.source
        if source is None:
            return None
        return source, self.requested_at_utc

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


def stop_on_terminate(
    cerebro: Any,
    *,
    stop_request_file: Optional[str] = None,
    stop_request_strategy_uuid: Optional[str] = None,
    stop_request_run_id: Optional[str] = None,
) -> TerminateStop:
    """Return a context in which SIGTERM (SIGBREAK on Windows) stops ``cerebro`` gracefully.

    Example::

        with stop_on_terminate(cerebro) as termination:
            cerebro.run()
        print(termination.received)  # e.g. "SIGTERM", or None

    ``stop_request_file`` opts into the local stop-file channel (iteration 66,
    §5.2 B1): a valid ``bt_api_stop_request/v1`` document for this exact
    strategy UUID and run id requests the same graceful stop as a signal.  It
    is off unless the caller supplies the path, the strategy UUID and the run
    id; a malformed, expired, duplicate or cross-unit document is ignored.
    """
    return TerminateStop(
        cerebro,
        stop_request_file=stop_request_file,
        stop_request_strategy_uuid=stop_request_strategy_uuid,
        stop_request_run_id=stop_request_run_id,
    )

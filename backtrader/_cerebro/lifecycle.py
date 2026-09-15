"""Cerebro run-scope lifecycle mixin (iteration 28 split).

Moved verbatim from ``backtrader/cerebro.py``: run scope begin/end,
external channel scope retention and runstop publication.
"""

# pylint: disable=no-member
# Mixin state (``_run_scope_token`` etc.) is created by ``Cerebro.__init__``
# on the assembled class; it cannot be seen from this partial class alone.
import threading

from ..utils.log_message import get_logger

logger = get_logger(__name__)


class RunLifecycleMixin:
    """Run-scope lifecycle half of Cerebro (see module docstring)."""

    def _begin_run(self):
        """Start one synchronized run-stop scope for this Cerebro instance."""
        with self._runstop_lock:
            if self._run_active:
                raise RuntimeError("Cerebro is already running")
            self._event_stop.clear()
            self._run_scope_token += 1
            self._run_scope_owner = threading.get_ident()
            self._run_active = True
            return self._run_scope_token

    def _open_run_scope(self):
        """Open a run scope and roll it back if an overridden start hook fails."""
        with self._runstop_lock:
            previous_token = self._run_scope_token

        try:
            self._begin_run()
            with self._runstop_lock:
                if not self._run_active or self._run_scope_owner != threading.get_ident():
                    raise RuntimeError("Cerebro run scope was not published by the calling thread")
                return self._run_scope_token
        except BaseException:
            # A subclass can call ``super()._begin_run()`` and then fail. Only
            # retire a scope created by this thread after the snapshot; never
            # clear another thread's active run after a rejected re-entry.
            logger.error("lifecycle:41 exception before re-raise (BaseException)", exc_info=True)
            self._end_run_if_started_by_current_thread(previous_token)
            raise

    def _end_run_if_started_by_current_thread(self, previous_token):
        """Undo a partially opened scope without touching a different active run."""
        with self._runstop_lock:
            if (
                self._run_active
                and self._run_scope_owner == threading.get_ident()
                and self._run_scope_token != previous_token
            ):
                self._retire_run_scope_locked()

    def _retire_run_scope_locked(self):
        """Clear one active run scope while ``_runstop_lock`` is held."""
        self._run_active = False
        self._run_scope_owner = None
        self._event_stop.clear()
        self._external_channel_token = None
        self._external_channel_runstrats = None
        self._external_channel_closing = False

    def _end_run(self, token):
        """Retire only this caller's run-stop scope.

        A timer that fires after another run has already opened remains an
        ordinary stop request for that later active scope; callers must cancel
        or generation-bind such timers before reusing the instance.
        """
        with self._runstop_lock:
            if (
                not self._run_active
                or self._run_scope_owner != threading.get_ident()
                or self._run_scope_token != token
            ):
                return
            self._retire_run_scope_locked()

    def _retain_external_channel_scope(self, token, runstrats):
        """Keep a ``run(channel=True)`` session active until its owner closes it."""
        with self._runstop_lock:
            if (
                not self._run_active
                or self._run_scope_owner != threading.get_ident()
                or self._run_scope_token != token
            ):
                raise RuntimeError("Cerebro external channel scope was not published by its owner")
            self._external_channel_token = token
            self._external_channel_runstrats = runstrats
            self._external_channel_closing = False

    def close_channel(self):
        """Tear down an external ``run(channel=True)`` session on its owner thread.

        ``runstop()`` only publishes a stop request.  The thread which called
        ``run(channel=True)`` must call this method after its external driver
        has stopped dispatching callbacks.  This keeps broker and strategy
        teardown out of foreign Timer or worker threads.

        Returns:
            ``True`` if an external channel session was closed, otherwise
            ``False`` when no such session is active.

        Raises:
            RuntimeError: If a different thread tries to close the active
                external channel session.
        """
        with self._runstop_lock:
            token = self._external_channel_token
            if token is None or not self._run_active or self._run_scope_token != token:
                return False
            if self._run_scope_owner != threading.get_ident():
                raise RuntimeError("Cerebro external channel must be closed by its owner thread")
            if self._external_channel_closing:
                return False

            self._external_channel_closing = True
            self._event_stop.set()
            runstrats = self._external_channel_runstrats

        try:
            self._teardown_channel(runstrats)
        finally:
            self._end_run(token)
        return True

    # When called from within a strategy or elsewhere, stops execution quickly
    def runstop(self):
        """Request prompt termination of the currently active run.

        Calls from a strategy or another thread are safe.  Calls made while
        no ``run`` / optimization worker is active are ignored so a delayed
        ``threading.Timer`` cannot stop a later, unrelated run.
        """
        with self._runstop_lock:
            if self._run_active:
                self._event_stop.set()

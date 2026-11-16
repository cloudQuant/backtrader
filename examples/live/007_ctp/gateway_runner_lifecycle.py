"""Retain the 007 runner's original resources until Store cleanup is proven."""
from __future__ import annotations

import json
import signal
import threading

# Also keeps the resources alive if a test hook or an embedding caller escapes.
RETAINED = []


class RunnerLifecycle:
    def __init__(self, host, profiles):
        self.host = host
        self.profiles = profiles
        self.store = None
        self.broker = None
        self.cerebro = None
        self.contract = None
        self.termination = None
        self.timer = None
        self.runstrategies_entered = False
        self.retained = False
        self._signal_previous = {}
        self._guard_pending = None

    def install_signal_guard(self):
        """Keep terminate signals bounded across TerminateStop.__exit__."""
        if threading.current_thread() is not threading.main_thread():
            return
        for name in ("SIGTERM", "SIGBREAK"):
            signum = getattr(signal, name, None)
            if signum is not None:
                self._signal_previous[signum] = signal.signal(signum, self._guard_signal)

    def _guard_signal(self, signum, _frame):
        self._guard_pending = signum

    def deliver_guarded_stop(self):
        # A signal just before TerminateStop entered must still request a stop.
        pending, self._guard_pending = self._guard_pending, None
        if pending is not None:
            self.termination.request(signal.Signals(pending).name, signal=True)

    def restore_signal_guard(self):
        if threading.current_thread() is not threading.main_thread():
            return
        for signum, previous in self._signal_previous.items():
            signal.signal(signum, previous)
        self._signal_previous.clear()

    def cleanup_confirmed(self):
        store = self.store
        if store is None:
            # GatewayPendingHost is a file adapter; Store construction does not
            # start the Gateway or acquire the run lock, database or API.
            return True
        try:
            attempted = store._gateway_start_attempted
            return (type(attempted) is bool
                    and store._gateway_composition_uncertain is False
                    and store._api is None
                    and store._gateway_execution_db is None
                    and store._gateway_run_lock is None
                    and (attempted is False or store._gateway_closed is True))
        except BaseException:
            return False

    def prepare_cleanup(self):
        if self.timer is not None:
            try:
                self.timer.cancel()
            except BaseException:
                pass
        # Cerebro owns stop after entering runstrategies, including failures.
        # Only a pre-entry failure may initiate this one bounded Store stop.
        if not self.cleanup_confirmed() and not self.runstrategies_entered and self.store is not None:
            try:
                self.store.stop(timeout=5.0)
            except BaseException:
                pass
        return self.cleanup_confirmed()

    def arm_retention(self, wait_hook=None):
        if not self.retained:
            RETAINED.append(self)
            self.retained = True
        # No automatic retry, rebuild, release, or termination.  Keep default
        # SIGTERM/SIGINT from discarding the owning process in CLI use.
        if wait_hook is None and threading.current_thread() is threading.main_thread():
            for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
                sig = getattr(signal, name, None)
                if sig is not None:
                    try:
                        signal.signal(sig, signal.SIG_IGN)
                    except BaseException:
                        pass

    def retain(self, wait_hook=None):
        self.arm_retention(wait_hook)
        try:
            print(json.dumps({"status": "RETAINED", "error_code": "GATEWAY_CLEANUP_UNCERTAIN"}), flush=True)
        except BaseException:
            pass
        if wait_hook is not None:
            wait_hook(self)
        event = threading.Event()
        while True:
            try:
                event.wait(60)
            except BaseException:
                # Includes KeyboardInterrupt/SystemExit delivered to an
                # embedding caller: uncertainty must not discard ownership.
                continue

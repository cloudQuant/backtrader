"""SIGTERM requests a graceful Cerebro stop (iteration 62, user decision S-23).

``backtrader.live_trading.stop_on_terminate`` turns SIGTERM (and SIGBREAK
where it exists) into ``cerebro.runstop()``: ``run()`` returns and the
caller's normal stop/``finally`` path runs; a second SIGTERM during the stop
does not abort it; the previous handlers are restored afterwards; SIGINT is
untouched; nothing is installed off the main thread; a signal before the run
scope opens is delivered once it opens.

Evidence: UNIT/FAKE. The subprocess test runs a real Cerebro with a fake
never-ending live feed and a fake Broker whose stop takes one second; no
network, no account. Skipped where SIGTERM cannot be delivered to a handler.
"""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import textwrap
import threading
import time

import pytest

from backtrader.live_trading import TerminateStop, stop_on_terminate

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not hasattr(signal, "SIGTERM"),
    reason="SIGTERM is not delivered to a Python handler on this platform",
)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _FakeCerebro:
    def __init__(self, active=True):
        self._run_active = active
        self.stops = 0

    def runstop(self):
        self.stops += 1


@pytest.fixture
def sentinel_handler():
    calls = []

    def handler(signum, frame):
        calls.append(signum)

    previous = signal.signal(signal.SIGTERM, handler)
    try:
        yield handler, calls
    finally:
        signal.signal(signal.SIGTERM, previous)


def test_sigterm_requests_runstop_and_the_previous_handler_is_restored(sentinel_handler):
    handler, calls = sentinel_handler
    cerebro = _FakeCerebro()
    sigint = signal.getsignal(signal.SIGINT)
    with stop_on_terminate(cerebro) as termination:
        assert "SIGTERM" in termination.installed
        assert signal.getsignal(signal.SIGINT) is sigint  # SIGINT untouched
        signal.raise_signal(signal.SIGTERM)
        assert (cerebro.stops, termination.received, termination.count) == (1, "SIGTERM", 1)
        signal.raise_signal(signal.SIGTERM)  # a second one only repeats the request
        assert (cerebro.stops, termination.count) == (2, 2)
    assert signal.getsignal(signal.SIGTERM) is handler
    assert calls == []
    signal.raise_signal(signal.SIGTERM)  # restored: the previous handler runs again
    assert calls == [signal.SIGTERM] and cerebro.stops == 2


def test_nothing_is_installed_off_the_main_thread(sentinel_handler):
    handler, _calls = sentinel_handler
    result = {}

    def worker():
        with stop_on_terminate(_FakeCerebro()) as termination:
            result["installed"] = termination.installed
            result["handler"] = signal.getsignal(signal.SIGTERM)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert result == {"installed": (), "handler": handler}


def test_a_signal_before_the_run_opens_is_delivered_when_it_opens(sentinel_handler):
    cerebro = _FakeCerebro(active=False)
    with stop_on_terminate(cerebro) as termination:
        signal.raise_signal(signal.SIGTERM)
        time.sleep(0.2)
        assert cerebro.stops == 0  # runstop() would be ignored before the run
        cerebro._run_active = True
        deadline = time.monotonic() + 2.0
        while cerebro.stops == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert cerebro.stops == 1
        assert termination.received == "SIGTERM"


def test_a_latched_signal_is_dropped_when_the_context_closes_first(sentinel_handler):
    cerebro = _FakeCerebro(active=False)
    with stop_on_terminate(cerebro):
        signal.raise_signal(signal.SIGTERM)
    cerebro._run_active = True
    time.sleep(0.2)
    assert cerebro.stops == 0


def test_an_object_without_runstop_is_refused():
    with pytest.raises(TypeError):
        TerminateStop(object())


_CHILD = textwrap.dedent("""
    import datetime, json, signal, time
    import backtrader as bt
    from backtrader.live_trading import stop_on_terminate

    class LiveFeed(bt.feeds.DataBase):
        def islive(self):
            return True

        def start(self):
            super().start()
            self._sent = False

        def _load(self):
            if not self._sent:
                self._sent = True
                self.lines.datetime[0] = bt.date2num(datetime.datetime(2026, 11, 6, 9, 0))
                for name in ("open", "high", "low", "close", "volume"):
                    getattr(self.lines, name)[0] = 1.0
                self.lines.openinterest[0] = 0.0
                return True
            time.sleep(0.02)
            return None

    class SlowStopBroker(bt.brokers.BackBroker):
        stopped = False

        def stop(self):
            print("STOPPING", flush=True)
            time.sleep(1.0)  # the parent sends a second SIGTERM meanwhile
            self.stopped = True
            super().stop()

    class Ready(bt.Strategy):
        def next(self):
            if not getattr(self, "_ready", False):
                self._ready = True
                print("READY", flush=True)

    cerebro = bt.Cerebro(stdstats=False)
    broker = SlowStopBroker()
    cerebro.setbroker(broker)
    cerebro.adddata(LiveFeed())
    cerebro.addstrategy(Ready)
    termination = stop_on_terminate(cerebro)
    try:
        with termination:
            cerebro.run()
    finally:
        print(json.dumps({
            "status": "SUMMARY",
            "stop_signal": termination.received,
            "signals": termination.count,
            "broker_stopped": broker.stopped,
            "handler_restored": signal.getsignal(signal.SIGTERM) is signal.SIG_DFL,
        }), flush=True)
    """)


def _start_reader(process):
    """Collect the child's stdout lines on a thread; reads never block the test."""
    lines = queue.Queue()

    def pump():
        for line in process.stdout:
            lines.put(line.strip())
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    return lines


def _read_until(lines, marker, timeout, seen):
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(f"{marker} not seen in {timeout} s; output so far: {seen}")
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            continue
        if line is None:
            raise AssertionError(f"child ended before {marker}; output: {seen}")
        seen.append(line)
        if line == marker:
            return


def test_sigterm_in_a_subprocess_runs_the_stop_path_and_writes_the_summary(tmp_path):
    script = tmp_path / "child.py"
    script.write_text(_CHILD, encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=ROOT, PYTHONDONTWRITEBYTECODE="1")
    process = subprocess.Popen(
        [sys.executable, str(script)],
        cwd=str(tmp_path),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    seen = []
    try:
        lines = _start_reader(process)
        _read_until(lines, "READY", 60, seen)
        process.send_signal(signal.SIGTERM)
        _read_until(lines, "STOPPING", 30, seen)
        process.send_signal(signal.SIGTERM)  # during the stop: must not abort it
        process.wait(timeout=30)
        while True:
            line = lines.get(timeout=5)
            if line is None:
                break
            seen.append(line)
    finally:
        if process.poll() is None:
            process.kill()  # SIGKILL: a broken handler may ignore SIGTERM
            process.wait()
    output = "\n".join(seen)
    assert process.returncode == 0
    summary = json.loads(output.strip().splitlines()[-1])
    assert summary == {
        "status": "SUMMARY",
        "stop_signal": "SIGTERM",
        "signals": 2,
        "broker_stopped": True,
        "handler_restored": True,
    }

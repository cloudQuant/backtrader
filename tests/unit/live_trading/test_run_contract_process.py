"""INTEGRATION_SIM: a real strategy process, SIGTERM, the contract files, exit code.

A child process runs an ordinary ``Cerebro`` on a fake directmode Broker (fake
facade, real ``backtrader.live_state``) with one working order, writes the
heartbeat status file, then receives SIGTERM.  The parent asserts that:

* the run stopped gracefully (the order was cancelled, not left working),
* ``state/run_status.json`` was written by the heartbeat thread and ended in
  ``STOPPED``,
* ``state/last_run.json`` is the runtime's strict summary with this PID and
  ``SIGTERM`` as the stop source,
* the process exit code is ``0``.

Evidence: INTEGRATION_SIM with fakes only (no provider, account or network).
Skipped where SIGTERM cannot reach a Python handler.
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

import pytest

from backtrader.live_trading import read_run_status

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not hasattr(signal, "SIGTERM"),
    reason="SIGTERM is not delivered to a Python handler on this platform",
)

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


_CHILD = textwrap.dedent("""
    import datetime, json, sys, time, uuid
    from pathlib import Path

    import backtrader as bt
    from backtrader.live_trading import RunStatusWriter, stop_on_terminate
    from tests.unit.brokers.direct._fakes import Env, order_event

    run_dir = Path(sys.argv[1])
    env = Env(run_dir)


    class Owner:
        \"\"\"The order owner of this process: receives Broker notifications.\"\"\"

        def _addnotification(self, order, quicknotify=False):
            pass

        def notify_order(self, order):
            pass


    env.strategy = Owner()
    env.init_flat()
    broker = env.start(stop_cancel_timeout=5.0)
    broker.buy(env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit, offset="open")
    call = env.api.place_calls[-1]
    env.api.push(order_event(call.identity, "accepted", sys_id="7001", qty=1))
    broker.next()
    env.api.auto_cancel_events = True


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
                    getattr(self.lines, name)[0] = 3500.0
                self.lines.openinterest[0] = 0.0
                return True
            time.sleep(0.02)
            return None


    class Hold(bt.Strategy):
        def next(self):
            if not getattr(self, "_ready", False):
                self._ready = True
                print("READY", flush=True)


    cerebro = bt.Cerebro(stdstats=False)
    cerebro.setbroker(broker)
    # The direct-mode fake Store implements only the facade the Broker calls;
    # Cerebro also drains Store notifications each loop.
    env.store.get_notifications = lambda *args, **kwargs: []
    cerebro.adddata(LiveFeed())
    cerebro.addstrategy(Hold)
    termination = stop_on_terminate(cerebro)
    contract = RunStatusWriter(
        env.strategy_dir,
        run_id=str(uuid.uuid4()),
        broker=broker,
        stop_request_provider=termination.request_state,
    )
    contract.start()
    contract.set_phase("LIVE")
    result = None
    try:
        with termination:
            cerebro.run()
    finally:
        result = contract.finish(broker_summary=broker.get_shutdown_summary())
    print(json.dumps({
        "outcome": result.outcome,
        "exit_code": result.exit_code,
        "summary_written": result.summary_written,
        "cancels": len(env.api.cancel_calls),
        "places": len(env.api.place_calls),
    }), flush=True)
    env.close()
    raise SystemExit(result.exit_code)
    """)


def _start_reader(process):
    lines = queue.Queue()

    def pump():
        for line in process.stdout:
            lines.put(line.strip())
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    return lines


def _read_until(lines, marker, timeout, seen):
    import time as _time

    deadline = _time.monotonic() + timeout
    while True:
        remaining = deadline - _time.monotonic()
        if remaining <= 0:
            raise AssertionError(f"{marker} not seen in {timeout} s; output: {seen}")
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            continue
        if line is None:
            raise AssertionError(f"child ended before {marker}; output: {seen}")
        seen.append(line)
        if line == marker:
            return


def test_sigterm_stops_a_direct_run_and_writes_the_process_contract(tmp_path):
    script = tmp_path / "child.py"
    script.write_text(_CHILD, encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    stderr_path = tmp_path / "child.err"
    environment = dict(os.environ, PYTHONPATH=ROOT, PYTHONDONTWRITEBYTECODE="1")
    seen = []
    with open(stderr_path, "wb") as stderr:
        process = subprocess.Popen(
            [sys.executable, str(script), str(run_dir)],
            cwd=str(tmp_path),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
        )
    try:
        lines = _start_reader(process)
        try:
            _read_until(lines, "READY", 120, seen)
        except AssertionError as exc:
            diagnosis = open(stderr_path, "r", encoding="utf-8", errors="replace").read()[-4000:]
            raise AssertionError(f"{exc}\nstderr: {diagnosis}") from None
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=120)
        while True:
            try:
                line = lines.get(timeout=10)
            except queue.Empty:
                break
            if line is None:
                break
            seen.append(line)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    output = "\n".join(seen)
    diagnosis = open(stderr_path, "r", encoding="utf-8", errors="replace").read()[-4000:]
    assert process.returncode == 0, f"output: {output}\nstderr: {diagnosis}"
    payload = json.loads(seen[-1])
    assert payload == {
        "outcome": "STOPPED",
        "exit_code": 0,
        "summary_written": True,
        "cancels": 1,
        "places": 1,
    }, f"output: {output}\nstderr: {diagnosis}"

    state = run_dir / "strategy" / "state"
    summary = json.loads((state / "last_run.json").read_text(encoding="utf-8"))
    assert summary["schema"] == "bt_api_run_summary/v1"
    assert summary["outcome"] == "STOPPED"
    assert summary["stop_source"] == "SIGTERM"
    assert summary["stop_requested_at_utc"] is not None
    assert summary["process"]["pid"] == process.pid
    assert summary["working_orders_unresolved"] is False
    assert summary["write_in_flight_unresolved"] is False
    assert summary["unknown_unresolved"] is False

    status = read_run_status(state / "run_status.json")
    assert status["phase"] == "STOPPED"
    assert status["heartbeat_sequence"] >= 2
    assert status["pid"] == process.pid
    assert status["stop_source"] == "SIGTERM"
    assert status["stop_budget"]["proven"] is False
    # B5: the Broker's own parameters reach the file (not a guessed default).
    assert status["stop_budget"]["parameters"]["stop_cancel_timeout"] == 5.0
    assert status["stop_budget"]["components"]["committed_write_wait_s"] == 35.0
    details = json.loads((state / "last_run_details.json").read_text(encoding="utf-8"))
    assert details["broker_status"] == "STOPPED"
    assert details["exit_code"] == 0

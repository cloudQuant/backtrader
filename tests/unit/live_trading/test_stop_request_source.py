"""Stop request source and first request time (iteration 66, §5.2 B1 remainder).

Iteration 62's :class:`~backtrader.live_trading.TerminateStop` turns SIGTERM into
``cerebro.runstop()``.  The process contract additionally needs *which* source
requested the stop and *when* it was first requested (the supervisor's
``t_term`` and the status/summary files).  A non-signal entry point reuses the
same latch, so a stop-file request and a signal have identical effects.

Evidence: UNIT/FAKE.
"""

from __future__ import annotations

import signal
import sys
import time

import pytest

from backtrader.live_trading import stop_on_terminate


class _FakeCerebro:
    def __init__(self, active=True):
        self._run_active = active
        self.stops = 0

    def runstop(self):
        self.stops += 1


def test_request_state_is_empty_before_any_request():
    termination = stop_on_terminate(_FakeCerebro())
    assert termination.request_state() is None
    assert termination.source is None and termination.requested_at_utc is None


def test_a_non_signal_request_stops_an_active_run_and_records_its_source():
    cerebro = _FakeCerebro()
    with stop_on_terminate(cerebro) as termination:
        termination.request("stop_file")
        assert cerebro.stops == 1
        source, at = termination.request_state()
        assert source == "stop_file"
        assert at.endswith("+00:00")


def test_only_the_first_request_is_recorded():
    cerebro = _FakeCerebro()
    with stop_on_terminate(cerebro) as termination:
        termination.request("stop_file", signal=False)
        first = termination.request_state()
        time.sleep(0.01)
        termination.request("internal")
        assert termination.request_state() == first
        assert cerebro.stops == 2  # the later request still repeats the request


def test_a_request_before_the_run_opens_is_delivered_when_it_opens():
    cerebro = _FakeCerebro(active=False)
    with stop_on_terminate(cerebro) as termination:
        termination.request("stop_file")
        time.sleep(0.15)
        assert cerebro.stops == 0  # runstop() before the run scope would be lost
        cerebro._run_active = True
        deadline = time.monotonic() + 2.0
        while cerebro.stops == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert cerebro.stops == 1
        assert termination.request_state()[0] == "stop_file"


def test_an_unknown_source_collapses_to_a_finite_code():
    with stop_on_terminate(_FakeCerebro()) as termination:
        termination.request("0 123456 password")
        assert termination.request_state()[0] == "internal"


def test_a_signal_records_its_name_and_time():
    if sys.platform == "win32" or not hasattr(signal, "SIGTERM"):  # pragma: no cover - platform
        pytest.skip("SIGTERM is not delivered to a Python handler here")
    cerebro = _FakeCerebro()
    with stop_on_terminate(cerebro) as termination:
        signal.raise_signal(signal.SIGTERM)
        assert termination.count == 1 and termination.received == "SIGTERM"
        source, at = termination.request_state()
        assert source == "SIGTERM" and at.endswith("+00:00")


def test_the_status_writer_reads_the_request_through_the_provider(tmp_path):
    from backtrader.live_trading import RunStatusWriter, read_run_status
    import uuid

    directory = tmp_path / "strategy"
    directory.mkdir()
    cerebro = _FakeCerebro(active=False)
    termination = stop_on_terminate(cerebro)
    writer = RunStatusWriter(
        directory,
        run_id=str(uuid.uuid4()),
        strategy_uuid=str(uuid.uuid4()),
        heartbeat_interval_s=0.05,
        stop_request_provider=termination.request_state,
    )
    writer.start()
    try:
        termination.request("stop_file")
        writer._write_status()
        document = read_run_status(writer.path)
        assert document["stop_source"] == "stop_file"
        assert document["stop_requested_at_utc"] == termination.requested_at_utc
    finally:
        writer.stop_heartbeat()

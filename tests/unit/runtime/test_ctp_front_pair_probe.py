from __future__ import annotations

from dataclasses import dataclass
import subprocess
import threading

import pytest

import backtrader_runtime.ctp_front_pair_probe as front_pair_probe
from backtrader_runtime.ctp_front_pair_probe import (
    CtpFrontPairProbeError,
    select_ctp_front_pair,
)


@dataclass
class _Socket:
    close_calls: int = 0
    close_fails: bool = False

    def close(self):
        self.close_calls += 1
        if self.close_fails:
            raise OSError("fixture close failed")


class _ProbeFixture:
    def __init__(self, latencies):
        self.latencies = {host: list(values) for host, values in latencies.items()}
        self.elapsed = 0.0
        self.calls = []
        self.sockets = []

    def clock(self):
        return self.elapsed

    def connect(self, host, port, timeout):
        self.calls.append((host, port, timeout))
        samples = self.latencies.get(host)
        if not samples:
            self.elapsed += timeout
            raise TimeoutError("fixture endpoint unreachable")
        latency = samples.pop(0)
        if latency is None:
            self.elapsed += timeout
            raise TimeoutError("fixture endpoint timed out")
        self.elapsed += latency
        sock = _Socket()
        self.sockets.append(sock)
        return sock


class _FakeWorker:
    def __init__(self, fixture, *, dns_latency=0.01, tcp_latency=0.02, timeout=False):
        self.fixture = fixture
        self.dns_latency = dns_latency
        self.tcp_latency = tcp_latency
        self.timeout = timeout
        self.returncode = 0
        self.killed = False
        self.communicate_timeouts = []

    def communicate(self, *, timeout):
        self.communicate_timeouts.append(timeout)
        if self.timeout and not self.killed:
            raise subprocess.TimeoutExpired("fixture", timeout)
        if self.killed:
            return b"", None
        self.fixture.elapsed += self.dns_latency + self.tcp_latency
        output = "%.9f,%.9f" % (self.dns_latency, self.tcp_latency)
        return output.encode("ascii"), None

    def kill(self):
        self.killed = True
        self.returncode = -9


def _pair(md, td):
    return {"md_front": md, "td_front": td}


def _selector(pairs, fixture, *, timeout=3.0, max_pairs=8, samples=3):
    return select_ctp_front_pair(
        pairs,
        timeout_seconds=timeout,
        max_pairs=max_pairs,
        repeated_samples=samples,
        connector=fixture.connect,
        clock=fixture.clock,
    )


def test_selects_pair_with_lowest_worst_endpoint_median_and_preserves_exact_config():
    configured = (
        _pair("tcp://198.51.100.1:10131", "tcp://198.51.100.2:10130"),
        _pair("tcp://198.51.100.3:10131", "tcp://198.51.100.4:10130"),
    )
    fixture = _ProbeFixture(
        {
            "198.51.100.1": [0.010, 0.010, 0.010],
            "198.51.100.2": [0.090, 0.090, 0.090],
            "198.51.100.3": [0.070, 0.070, 0.070],
            "198.51.100.4": [0.070, 0.070, 0.070],
        }
    )

    selected = _selector(configured, fixture)

    assert selected.pair.md_front == configured[1]["md_front"]
    assert selected.pair.td_front == configured[1]["td_front"]
    assert selected.config_index == 1
    assert selected.latency_score_ms == pytest.approx(70.0)
    assert tuple(item.pair.md_front for item in selected.evidence) == tuple(
        item["md_front"] for item in configured
    )
    assert len(fixture.calls) == 2 * len(configured) * 3
    assert all(call[2] == 3.0 for call in fixture.calls)
    assert all(sock.close_calls == 1 for sock in fixture.sockets)


def test_latency_tie_selects_first_configured_pair():
    configured = (
        _pair("tcp://198.51.100.5:10131", "tcp://198.51.100.6:10130"),
        _pair("tcp://198.51.100.7:10131", "tcp://198.51.100.8:10130"),
    )
    fixture = _ProbeFixture(
        {
            host: [0.025, 0.025]
            for host in (
                "198.51.100.5",
                "198.51.100.6",
                "198.51.100.7",
                "198.51.100.8",
            )
        }
    )

    selected = _selector(configured, fixture, samples=2)

    assert selected.pair.md_front == configured[0]["md_front"]
    assert selected.config_index == 0


def test_failed_candidate_is_skipped_only_in_favor_of_another_configured_pair():
    configured = (
        _pair("tcp://198.51.100.9:10131", "tcp://198.51.100.10:10130"),
        _pair("tcp://198.51.100.11:10131", "tcp://198.51.100.12:10130"),
    )
    fixture = _ProbeFixture(
        {
            "198.51.100.9": [None, 0.02],
            "198.51.100.10": [0.02, 0.02],
            "198.51.100.11": [0.05, 0.05],
            "198.51.100.12": [0.05, 0.05],
        }
    )

    selected = _selector(configured, fixture, samples=2)

    assert selected.config_index == 1
    assert selected.evidence[0].reachable is False
    assert selected.evidence[0].md.median_latency_ms is None
    assert selected.evidence[1].reachable is True
    assert all(
        call[0]
        in {"198.51.100.9", "198.51.100.10", "198.51.100.11", "198.51.100.12"}
        for call in fixture.calls
    )


def test_majority_connected_pair_uses_successful_samples_and_never_invents_front():
    configured = (
        _pair("tcp://198.51.100.19:10131", "tcp://198.51.100.20:10130"),
    )
    fixture = _ProbeFixture(
        {
            "198.51.100.19": [0.010, None, 0.030],
            "198.51.100.20": [0.020, 0.040, None],
        }
    )

    selected = _selector(configured, fixture)

    assert selected.config_index == 0
    assert selected.pair.md_front == configured[0]["md_front"]
    assert selected.pair.td_front == configured[0]["td_front"]
    assert selected.evidence[0].reachable is True
    assert selected.evidence[0].md.median_latency_ms == pytest.approx(20.0)
    assert selected.evidence[0].td.median_latency_ms == pytest.approx(30.0)
    assert selected.latency_score_ms == pytest.approx(30.0)


def test_one_of_three_connections_is_insufficient_even_when_both_sides_connect_once():
    configured = (_pair("tcp://198.51.100.21:10131", "tcp://198.51.100.22:10130"),)
    fixture = _ProbeFixture(
        {"198.51.100.21": [None, 0.010, None], "198.51.100.22": [None, 0.010, None]}
    )

    with pytest.raises(CtpFrontPairProbeError, match="no_configured_front_pair_reachable") as exc:
        _selector(configured, fixture)

    assert exc.value.evidence[0].reachable is False
    assert exc.value.evidence[0].md.median_latency_ms is None
    assert exc.value.evidence[0].td.median_latency_ms is None


def test_all_configured_pairs_failed_raises_with_complete_evidence():
    configured = (
        _pair("tcp://198.51.100.13:10131", "tcp://198.51.100.14:10130"),
    )
    fixture = _ProbeFixture({"198.51.100.13": [None, None], "198.51.100.14": [None, None]})

    with pytest.raises(CtpFrontPairProbeError, match="no_configured_front_pair_reachable") as exc:
        _selector(configured, fixture, samples=2)

    assert len(exc.value.evidence) == 1
    assert exc.value.evidence[0].reachable is False
    assert all(not sample.connected for sample in exc.value.evidence[0].md.samples)
    assert all(not sample.connected for sample in exc.value.evidence[0].td.samples)


@pytest.mark.parametrize(
    "bad_front",
    (
        "tcp://user:password@front.example:10130",
        "tcp://front.example:10130?secret=x",
        "http://front.example:10130",
        "tcp://front.example",
        "tcp://front.example:70000",
        "tcp://front.example:10130/path",
        "tcp://[2001:db8::1]:10130",
    ),
)
def test_invalid_or_credential_bearing_address_rejected_before_network(bad_front):
    fixture = _ProbeFixture({})

    with pytest.raises(CtpFrontPairProbeError):
        _selector((_pair(bad_front, "tcp://td.example:10130"),), fixture, samples=1)

    assert fixture.calls == []


def test_hostname_front_uses_injected_isolated_worker():
    fixture = _ProbeFixture({})
    commands = []
    workers = []

    def process_factory(command):
        commands.append(command)
        worker = _FakeWorker(fixture)
        workers.append(worker)
        return worker

    selected = select_ctp_front_pair(
        (_pair("tcp://md-front.example:10131", "tcp://td-front.example:10130"),),
        timeout_seconds=3,
        max_pairs=8,
        repeated_samples=1,
        process_factory=process_factory,
        clock=fixture.clock,
    )

    assert selected.pair.md_front == "tcp://md-front.example:10131"
    assert selected.pair.td_front == "tcp://td-front.example:10130"
    assert [command[-3:] for command in commands] == [
        ["md-front.example", "10131", "3.0"],
        ["td-front.example", "10130", "3.0"],
    ]
    assert all(command[1:4] == ["-I", "-S", "-c"] for command in commands)
    assert len(workers) == 2
    assert all(not worker.killed for worker in workers)
    assert selected.evidence[0].md.samples[0].dns_resolution_ms == pytest.approx(10.0)
    assert selected.evidence[0].md.samples[0].tcp_connect_ms == pytest.approx(20.0)
    assert selected.evidence[0].md.samples[0].latency_ms == pytest.approx(30.0)
    assert fixture.calls == []


def test_default_probe_runs_distinct_endpoints_concurrently_and_closes_sockets(monkeypatch):
    configured = (_pair("tcp://198.51.100.101:10131", "tcp://198.51.100.102:10130"),)
    rendezvous = threading.Barrier(2)
    lock = threading.Lock()
    active = 0
    maximum_active = 0
    active_by_host = {}
    maximum_active_by_host = {}
    calls_by_host = {}
    sockets = []

    def fake_default_connect(host, port, timeout):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
            active_by_host[host] = active_by_host.get(host, 0) + 1
            maximum_active_by_host[host] = max(
                maximum_active_by_host.get(host, 0), active_by_host[host]
            )
            calls_by_host[host] = calls_by_host.get(host, 0) + 1
        try:
            # This barrier would time out if endpoint jobs ran serially.
            rendezvous.wait(timeout=1.0)
            sock = _Socket()
            sockets.append(sock)
            return sock
        finally:
            with lock:
                active -= 1
                active_by_host[host] -= 1

    monkeypatch.setattr(front_pair_probe, "_default_connect", fake_default_connect)

    selected = select_ctp_front_pair(
        configured,
        timeout_seconds=3,
        max_pairs=8,
        repeated_samples=2,
    )

    assert selected.pair.md_front == configured[0]["md_front"]
    assert selected.evidence[0].reachable is True
    assert maximum_active == 2
    assert maximum_active_by_host == {
        "198.51.100.101": 1,
        "198.51.100.102": 1,
    }
    assert calls_by_host == {"198.51.100.101": 2, "198.51.100.102": 2}
    assert len(sockets) == 4
    assert all(sock.close_calls == 1 for sock in sockets)


def test_hostname_worker_timeout_is_killed_and_pair_fails_closed():
    fixture = _ProbeFixture({})
    workers = []

    def process_factory(command):
        worker = _FakeWorker(fixture, timeout=True)
        workers.append(worker)
        return worker

    with pytest.raises(CtpFrontPairProbeError, match="no_configured_front_pair_reachable") as exc:
        select_ctp_front_pair(
            (_pair("tcp://md-timeout.example:10131", "tcp://td-timeout.example:10130"),),
            timeout_seconds=3,
            max_pairs=8,
            repeated_samples=1,
            process_factory=process_factory,
            clock=fixture.clock,
        )

    assert len(workers) == 2
    assert all(worker.killed for worker in workers)
    assert all(worker.communicate_timeouts == [3.0, 0.25] for worker in workers)
    assert all(item.md.samples[0].connected is False for item in exc.value.evidence)


def test_hostname_worker_gets_a_second_bounded_kill_and_reap_attempt():
    fixture = _ProbeFixture({})
    workers = []

    class StubbornWorker(_FakeWorker):
        def __init__(self):
            super().__init__(fixture)
            self.kill_calls = 0

        def communicate(self, *, timeout):
            self.communicate_timeouts.append(timeout)
            raise subprocess.TimeoutExpired("fixture", timeout)

        def kill(self):
            self.kill_calls += 1
            self.killed = True
            self.returncode = -9

    def process_factory(command):
        worker = StubbornWorker()
        workers.append(worker)
        return worker

    with pytest.raises(CtpFrontPairProbeError, match="no_configured_front_pair_reachable"):
        select_ctp_front_pair(
            (_pair("tcp://md-timeout.example:10131", "tcp://td-timeout.example:10130"),),
            timeout_seconds=3,
            max_pairs=8,
            repeated_samples=1,
            process_factory=process_factory,
            clock=fixture.clock,
        )

    assert len(workers) == 2
    assert all(worker.kill_calls == 2 for worker in workers)
    assert all(worker.communicate_timeouts == [3.0, 0.25, 0.25] for worker in workers)


def test_mixed_ip_and_hostname_pairs_are_ranked_by_dns_plus_tcp_latency():
    configured = (
        _pair("tcp://md-host-slower.example:10131", "tcp://198.51.100.61:10130"),
        _pair("tcp://198.51.100.62:10131", "tcp://td-host-faster.example:10130"),
    )
    fixture = _ProbeFixture(
        {
            "198.51.100.61": [0.06],
            "198.51.100.62": [0.04],
        }
    )
    workers = []

    def process_factory(command):
        host = command[-3]
        timings = {
            "md-host-slower.example": (0.20, 0.01),
            "td-host-faster.example": (0.01, 0.02),
        }
        dns_latency, tcp_latency = timings[host]
        worker = _FakeWorker(
            fixture,
            dns_latency=dns_latency,
            tcp_latency=tcp_latency,
        )
        workers.append(worker)
        return worker

    selected = select_ctp_front_pair(
        configured,
        timeout_seconds=3,
        max_pairs=8,
        repeated_samples=1,
        connector=fixture.connect,
        process_factory=process_factory,
        clock=fixture.clock,
    )

    assert selected.config_index == 1
    assert selected.latency_score_ms == pytest.approx(40.0)
    assert selected.evidence[0].md.samples[0].latency_ms == pytest.approx(210.0)
    assert selected.evidence[0].td.samples[0].dns_resolution_ms == pytest.approx(0.0)
    assert selected.evidence[1].td.samples[0].latency_ms == pytest.approx(30.0)
    assert len(workers) == 2


def test_unknown_fields_and_duplicate_pairs_fail_before_network():
    fixture = _ProbeFixture({})

    with pytest.raises(CtpFrontPairProbeError, match="front_pair_fields_invalid"):
        _selector(
            (_pair("tcp://198.51.100.15:10131", "tcp://198.51.100.16:10130") | {"profile": "x"},),
            fixture,
        )
    with pytest.raises(CtpFrontPairProbeError, match="duplicate_front_pair"):
        _selector(
            (
                _pair("tcp://198.51.100.15:10131", "tcp://198.51.100.16:10130"),
                _pair("tcp://198.51.100.15:10131", "tcp://198.51.100.16:10130"),
            ),
            fixture,
        )

    assert fixture.calls == []


def test_pair_limit_is_rejected_without_truncation_or_probe():
    configured = tuple(
        _pair(f"tcp://198.51.100.{17 + index}:10131", f"tcp://198.51.100.{25 + index}:10130")
        for index in range(2)
    )
    fixture = _ProbeFixture({})

    with pytest.raises(CtpFrontPairProbeError, match="front_pair_count_exceeds_limit"):
        _selector(configured, fixture, max_pairs=1)

    assert fixture.calls == []


@pytest.mark.parametrize(
    ("timeout", "max_pairs", "samples"),
    (
        (0, 1, 1),
        (11, 1, 1),
        (1, 0, 1),
        (1, 9, 1),
        (1, 1, 0),
        (1, 1, 6),
        (10, 8, 2),  # bounded aggregate connect budget
    ),
)
def test_timeout_limits_and_aggregate_budget_fail_closed(timeout, max_pairs, samples):
    fixture = _ProbeFixture({})
    pair_count = 8 if timeout == 10 else 1
    configured = tuple(
        _pair(
            f"tcp://198.51.100.{40 + index}:10131",
            f"tcp://198.51.100.{50 + index}:10130",
        )
        for index in range(pair_count)
    )

    with pytest.raises(CtpFrontPairProbeError):
        _selector(
            configured,
            fixture,
            timeout=timeout,
            max_pairs=max_pairs,
            samples=samples,
        )

    assert fixture.calls == []


def test_one_failed_sample_does_not_hide_two_successful_connections():
    configured = (_pair("tcp://198.51.100.29:10131", "tcp://198.51.100.30:10130"),)
    fixture = _ProbeFixture(
        {"198.51.100.29": [0.01, None, 0.01], "198.51.100.30": [0.01, 0.01, 0.01]}
    )

    selected = _selector(configured, fixture)

    assert len(selected.evidence[0].md.samples) == 3
    assert selected.evidence[0].reachable is True
    assert selected.evidence[0].md.median_latency_ms == pytest.approx(10.0)


def test_socket_close_failure_fails_pair_closed():
    configured = (_pair("tcp://198.51.100.33:10131", "tcp://198.51.100.34:10130"),)
    sock = _Socket(close_fails=True)
    times = iter((0.0, 0.01))

    with pytest.raises(CtpFrontPairProbeError, match="no_configured_front_pair_reachable") as exc:
        select_ctp_front_pair(
            configured,
            timeout_seconds=3,
            max_pairs=8,
            repeated_samples=1,
            connector=lambda host, port, timeout: sock,
            clock=lambda: next(times),
        )

    assert exc.value.evidence[0].reachable is False
    assert exc.value.evidence[0].md.samples[0].connected is False


def test_connect_over_timeout_fails_closed():
    configured = (_pair("tcp://198.51.100.31:10131", "tcp://198.51.100.32:10130"),)
    fixture = _ProbeFixture({"198.51.100.31": [4.0], "198.51.100.32": [0.01]})

    with pytest.raises(CtpFrontPairProbeError, match="no_configured_front_pair_reachable"):
        _selector(configured, fixture, samples=1, timeout=3.0)


def test_global_deadline_caps_connect_timeout_and_stops_later_probes():
    configured = (
        _pair("tcp://198.51.100.201:10131", "tcp://198.51.100.202:10130"),
        _pair("tcp://198.51.100.203:10131", "tcp://198.51.100.204:10130"),
    )
    fixture = _ProbeFixture(
        {
            "198.51.100.201": [0.06],
            "198.51.100.202": [0.05],
        }
    )

    with pytest.raises(CtpFrontPairProbeError, match="probe_global_deadline_exceeded") as exc:
        select_ctp_front_pair(
            configured,
            timeout_seconds=3.0,
            max_pairs=8,
            repeated_samples=1,
            connector=fixture.connect,
            clock=fixture.clock,
            deadline_monotonic=0.1,
        )

    assert [call[0] for call in fixture.calls] == [
        "198.51.100.201",
        "198.51.100.202",
    ]
    assert [call[2] for call in fixture.calls] == pytest.approx([0.1, 0.04])
    assert exc.value.evidence[0].md.samples[0].connected is True
    assert exc.value.evidence[0].td.samples[0].failure == "probe_global_deadline_exceeded"
    assert all(not item.reachable for item in exc.value.evidence)


def test_deadline_expiring_after_all_connects_prevents_pair_selection():
    configured = (_pair("tcp://198.51.100.205:10131", "tcp://198.51.100.206:10130"),)
    clock_values = iter((0.0, 0.01, 0.02, 0.03, 1.01))
    calls = []

    def connector(host, port, timeout):
        calls.append((host, port, timeout))
        return _Socket()

    with pytest.raises(CtpFrontPairProbeError, match="probe_global_deadline_exceeded") as exc:
        select_ctp_front_pair(
            configured,
            timeout_seconds=3.0,
            max_pairs=8,
            repeated_samples=1,
            connector=connector,
            clock=lambda: next(clock_values),
            deadline_monotonic=1.0,
        )

    assert [call[0] for call in calls] == ["198.51.100.205", "198.51.100.206"]
    assert [call[2] for call in calls] == pytest.approx([1.0, 0.98])
    assert len(exc.value.evidence) == 1
    assert exc.value.evidence[0].reachable is True
    assert exc.value.evidence[0].md.samples[0].connected is True
    assert exc.value.evidence[0].td.samples[0].connected is True


def test_expired_global_deadline_starts_no_probe():
    configured = (_pair("tcp://198.51.100.207:10131", "tcp://198.51.100.208:10130"),)
    fixture = _ProbeFixture({})

    with pytest.raises(CtpFrontPairProbeError, match="probe_global_deadline_exceeded"):
        select_ctp_front_pair(
            configured,
            timeout_seconds=3.0,
            max_pairs=8,
            repeated_samples=1,
            connector=fixture.connect,
            clock=fixture.clock,
            deadline_monotonic=0.0,
        )

    assert fixture.calls == []

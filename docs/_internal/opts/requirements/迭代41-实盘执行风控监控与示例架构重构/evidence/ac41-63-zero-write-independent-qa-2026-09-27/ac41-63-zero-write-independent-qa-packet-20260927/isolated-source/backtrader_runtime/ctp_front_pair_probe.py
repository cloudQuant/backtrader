"""Credential-free, config-only CTP MD/TD front reachability selection.

This module probes only the exact TCP endpoints supplied by the caller. It
does not consult SDK profile tables, infer endpoints from time, discover other
fronts, read credentials, log in, or authorize trading. It is a small network
diagnostic that returns the selected configured pair and detached timing
evidence. Callers must perform their separate config and execution admission.

Each endpoint must connect in a strict majority of its bounded samples. The
latency score is the larger of the successful-sample medians for MD and TD,
so a fast market-data front cannot hide a slow trading front. Ties retain
config order. Numeric IPv4 addresses use direct timed sockets. Hostname
resolution and connect run in a child Python process; the reported connection
latency includes DNS plus TCP connect time but excludes interpreter startup.
The parent imposes a wall-clock timeout and kills a hung worker. Callers may
also provide an absolute monotonic deadline to cap each connect by the time
remaining to a larger operation budget. This is fail-closed deadline accounting,
not a hard whole-command deadline: process creation, socket operations, close,
and worker cleanup can outlast it. Independent configured endpoints run in a
bounded pool, while repeated samples for each endpoint remain sequential.
"""

from __future__ import annotations

import ipaddress
import math
import os
import socket
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from statistics import median
from typing import Any, Callable, Optional
from urllib.parse import urlsplit


_MAX_PAIRS = 8
_MAX_REPEATED_SAMPLES = 5
_MAX_TIMEOUT_SECONDS = 10.0
_MAX_WORST_CASE_SECONDS = 180.0
_MAX_CONCURRENT_ENDPOINTS = 8
_WORKER_TERMINATION_GRACE_SECONDS = 0.25
_WORKER_TERMINATION_ATTEMPTS = 2
_HOSTNAME_WORKER_SCRIPT = (
    "import socket, sys, time\n"
    "host = sys.argv[1]\n"
    "port = int(sys.argv[2])\n"
    "timeout = float(sys.argv[3])\n"
    "dns_started = time.perf_counter()\n"
    "addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)\n"
    "dns_elapsed = time.perf_counter() - dns_started\n"
    "for family, socktype, proto, _, sockaddr in addresses:\n"
    "    connection = socket.socket(family, socktype, proto)\n"
    "    try:\n"
    "        connection.settimeout(timeout)\n"
    "        connect_started = time.perf_counter()\n"
    "        connection.connect(sockaddr)\n"
    "        connect_elapsed = time.perf_counter() - connect_started\n"
    "        connection.close()\n"
    "        sys.stdout.write('%.9f,%.9f' % (dns_elapsed, connect_elapsed))\n"
    "        break\n"
    "    except OSError:\n"
    "        connection.close()\n"
    "else:\n"
    "    sys.exit(1)\n"
)


class CtpFrontPairProbeError(ValueError):
    """The configured front set cannot be selected safely."""

    def __init__(self, reason: str, evidence: tuple["CtpFrontPairEvidence", ...] = ()) -> None:
        self.reason = reason
        self.evidence = evidence
        super().__init__(reason)


@dataclass(frozen=True)
class CtpConfiguredFrontPair:
    """One exact MD/TD address pair supplied by runtime configuration."""

    md_front: str
    td_front: str


@dataclass(frozen=True)
class CtpFrontProbeSample:
    """One credential-free TCP connect observation."""

    connected: bool
    # DNS resolution plus TCP connect time; worker startup is excluded.
    latency_ms: Optional[float]
    failure: Optional[str] = None
    dns_resolution_ms: Optional[float] = None
    tcp_connect_ms: Optional[float] = None


@dataclass(frozen=True)
class CtpFrontEndpointEvidence:
    """Repeated measurements for one configured endpoint."""

    front: str
    samples: tuple[CtpFrontProbeSample, ...]

    @property
    def median_latency_ms(self) -> Optional[float]:
        connected = tuple(
            sample.latency_ms
            for sample in self.samples
            if sample.connected and sample.latency_ms is not None
        )
        if len(connected) < len(self.samples) // 2 + 1:
            return None
        return float(median(connected))


@dataclass(frozen=True)
class CtpFrontPairEvidence:
    """Detached latency and reachability evidence for a candidate pair."""

    config_index: int
    pair: CtpConfiguredFrontPair
    md: CtpFrontEndpointEvidence
    td: CtpFrontEndpointEvidence
    reachable: bool
    latency_score_ms: Optional[float]


@dataclass(frozen=True)
class CtpFrontPairSelection:
    """Selected configured pair; this object carries no execution authority."""

    pair: CtpConfiguredFrontPair
    config_index: int
    latency_score_ms: float
    evidence: tuple[CtpFrontPairEvidence, ...]
    timeout_seconds: float
    repeated_samples: int


@dataclass(frozen=True)
class _ParsedFront:
    original: str
    host: str
    port: int
    ip_literal: bool


@dataclass(frozen=True)
class _RemoteProbeConnection:
    """Marker for a TCP socket already closed in the isolated worker."""

    latency_ms: float
    dns_resolution_ms: float
    tcp_connect_ms: float

    def close(self) -> None:
        return None


def _parse_front(value: Any) -> _ParsedFront:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or any(ord(character) < 0x21 or ord(character) == 0x7F for character in value)
    ):
        raise CtpFrontPairProbeError("front_address_invalid")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise CtpFrontPairProbeError("front_address_invalid") from error
    if (
        parsed.scheme != "tcp"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or host is None
        or not host
        or port is None
        or not 1 <= port <= 65535
        or parsed.path
        or parsed.query
        or parsed.fragment
        or "@" in parsed.netloc
        or value != "tcp://{0}:{1}".format(host, port)
    ):
        raise CtpFrontPairProbeError("front_address_must_be_plain_tcp_host_port")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if ":" in host:
            raise CtpFrontPairProbeError("front_address_host_invalid") from None
        try:
            ascii_host = host.encode("idna").decode("ascii").lower()
        except (UnicodeError, ValueError) as error:
            raise CtpFrontPairProbeError("front_address_host_invalid") from error
        labels = ascii_host.rstrip(".").split(".")
        if (
            not ascii_host
            or len(ascii_host) > 254
            or any(
                not label
                or len(label) > 63
                or not label[0].isalnum()
                or not label[-1].isalnum()
                or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in label)
                for label in labels
            )
        ):
            raise CtpFrontPairProbeError("front_address_host_invalid") from None
        return _ParsedFront(value, ascii_host, port, False)
    if address.version == 6:
        # The runtime config parser currently canonicalizes fronts as
        # tcp://host:port and does not accept bracketed IPv6 authorities.
        raise CtpFrontPairProbeError("front_address_ipv6_not_supported_by_config")
    return _ParsedFront(value, host, port, True)


def _configured_pairs(value: Any, *, max_pairs: int) -> tuple[tuple[CtpConfiguredFrontPair, _ParsedFront, _ParsedFront], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise CtpFrontPairProbeError("front_pairs_required")
    if len(value) > max_pairs:
        raise CtpFrontPairProbeError("front_pair_count_exceeds_limit")
    parsed_pairs = []
    seen = set()
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"md_front", "td_front"}:
            raise CtpFrontPairProbeError("front_pair_fields_invalid")
        pair = CtpConfiguredFrontPair(md_front=item["md_front"], td_front=item["td_front"])
        md = _parse_front(pair.md_front)
        td = _parse_front(pair.td_front)
        key = (pair.md_front, pair.td_front)
        if key in seen:
            raise CtpFrontPairProbeError("duplicate_front_pair")
        seen.add(key)
        parsed_pairs.append((pair, md, td))
    return tuple(parsed_pairs)


def _default_connect(host: str, port: int, timeout_seconds: float) -> Any:
    """Open a TCP socket directly; no CTP SDK, login, or protocol request."""

    address = ipaddress.ip_address(host)
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        connection.settimeout(timeout_seconds)
        connection.connect((str(address), port))
        return connection
    except Exception:
        connection.close()
        raise


def _deadline_connect(
    host: str,
    port: int,
    timeout_seconds: float,
    *,
    deadline_monotonic: float,
    deadline_clock: Callable[[], float],
) -> Any:
    """Connect to an IP literal while rechecking the shared operation deadline."""

    address = ipaddress.ip_address(host)
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        remaining = deadline_monotonic - deadline_clock()
        if remaining <= 0:
            raise TimeoutError("probe_global_deadline_exceeded")
        connection.settimeout(min(timeout_seconds, remaining))
        if deadline_clock() >= deadline_monotonic:
            raise TimeoutError("probe_global_deadline_exceeded")
        connection.connect((str(address), port))
        return connection
    except Exception:
        connection.close()
        raise


def _default_process_factory(command: list[str], **kwargs: Any) -> Any:
    options = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.DEVNULL,
        "shell": False,
        "close_fds": True,
    }
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    options.update(kwargs)
    return subprocess.Popen(command, **options)


def _bounded_hostname_connect(
    host: str,
    port: int,
    timeout_seconds: float,
    *,
    process_factory: Callable[..., Any],
    deadline_clock: Callable[[], float],
    deadline_monotonic: Optional[float] = None,
) -> _RemoteProbeConnection:
    """Resolve and connect in an isolated, killable child process."""

    command = [
        sys.executable,
        "-I",
        "-S",
        "-c",
        _HOSTNAME_WORKER_SCRIPT,
        host,
        str(port),
        str(timeout_seconds),
    ]
    deadline = deadline_clock() + timeout_seconds
    if deadline_monotonic is not None:
        deadline = min(deadline, deadline_monotonic)
        if deadline <= deadline_clock():
            raise TimeoutError("probe_global_deadline_exceeded")
    worker = process_factory(command)
    remaining = max(0.0, deadline - deadline_clock())
    try:
        output, _ = worker.communicate(timeout=remaining)
    except subprocess.TimeoutExpired as error:
        for _ in range(_WORKER_TERMINATION_ATTEMPTS):
            try:
                worker.kill()
            except Exception:
                pass
            try:
                worker.communicate(timeout=_WORKER_TERMINATION_GRACE_SECONDS)
                break
            except subprocess.TimeoutExpired:
                continue
        raise TimeoutError("hostname_probe_deadline_exceeded") from error
    if worker.returncode != 0 or not isinstance(output, bytes):
        raise ConnectionError("hostname_probe_failed")
    try:
        dns_seconds, connect_seconds = (
            float(component) for component in output.decode("ascii").split(",")
        )
    except (UnicodeError, ValueError) as error:
        raise ConnectionError("hostname_probe_latency_invalid") from error
    if (
        not math.isfinite(dns_seconds)
        or not math.isfinite(connect_seconds)
        or dns_seconds < 0
        or not 0 <= connect_seconds <= timeout_seconds
        or dns_seconds + connect_seconds > timeout_seconds
    ):
        raise ConnectionError("hostname_probe_latency_invalid")
    return _RemoteProbeConnection(
        latency_ms=round((dns_seconds + connect_seconds) * 1000.0, 6),
        dns_resolution_ms=round(dns_seconds * 1000.0, 6),
        tcp_connect_ms=round(connect_seconds * 1000.0, 6),
    )


def _probe_one(
    front: _ParsedFront,
    *,
    timeout_seconds: float,
    connector: Callable[[str, int, float], Any],
    clock: Callable[[], float],
    deadline_monotonic: Optional[float] = None,
) -> CtpFrontProbeSample:
    connection = None
    try:
        started = clock()
        if deadline_monotonic is not None:
            remaining = deadline_monotonic - started
            if remaining <= 0:
                return CtpFrontProbeSample(False, None, "probe_global_deadline_exceeded")
            connect_timeout = min(timeout_seconds, remaining)
        else:
            connect_timeout = timeout_seconds
        connection = connector(front.host, front.port, connect_timeout)
        finished = clock()
        if deadline_monotonic is not None and finished >= deadline_monotonic:
            return CtpFrontProbeSample(False, None, "probe_global_deadline_exceeded")
        elapsed = finished - started
        if not math.isfinite(elapsed) or elapsed < 0 or elapsed > connect_timeout:
            return CtpFrontProbeSample(False, None, "connect_timeout_or_clock_invalid")
        measured_latency = getattr(connection, "latency_ms", None)
        dns_latency = getattr(connection, "dns_resolution_ms", 0.0)
        tcp_latency = getattr(connection, "tcp_connect_ms", None)
        if measured_latency is not None:
            if (
                isinstance(measured_latency, bool)
                or type(measured_latency) not in (int, float)
                or not math.isfinite(measured_latency)
                or measured_latency < 0
                or measured_latency > connect_timeout * 1000.0
            ):
                return CtpFrontProbeSample(False, None, "worker_latency_invalid")
            elapsed_ms = float(measured_latency)
            if (
                isinstance(dns_latency, bool)
                or type(dns_latency) not in (int, float)
                or not math.isfinite(dns_latency)
                or dns_latency < 0
                or tcp_latency is None
                or isinstance(tcp_latency, bool)
                or type(tcp_latency) not in (int, float)
                or not math.isfinite(tcp_latency)
                or tcp_latency < 0
                or abs(elapsed_ms - dns_latency - tcp_latency) > 0.00001
            ):
                return CtpFrontProbeSample(False, None, "worker_latency_invalid")
        else:
            elapsed_ms = elapsed * 1000.0
            dns_latency = 0.0
            tcp_latency = elapsed_ms
        close = getattr(connection, "close", None)
        if not callable(close):
            return CtpFrontProbeSample(False, None, "connection_handle_invalid")
        try:
            close()
        except Exception as error:
            return CtpFrontProbeSample(False, None, type(error).__name__[:64])
        connection = None
        return CtpFrontProbeSample(
            True,
            round(elapsed_ms, 6),
            dns_resolution_ms=round(float(dns_latency), 6),
            tcp_connect_ms=round(float(tcp_latency), 6),
        )
    except Exception as error:
        return CtpFrontProbeSample(False, None, type(error).__name__[:64])
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def select_ctp_front_pair(
    front_pairs: Sequence[Mapping[str, str]],
    *,
    timeout_seconds: float,
    max_pairs: int,
    repeated_samples: int,
    connector: Optional[Callable[[str, int, float], Any]] = None,
    process_factory: Optional[Callable[..., Any]] = None,
    clock: Optional[Callable[[], float]] = None,
    deadline_monotonic: Optional[float] = None,
) -> CtpFrontPairSelection:
    """Pick the lowest-latency reachable pair from explicit config entries.

    All addresses are parsed before any socket opens. ``max_pairs`` is a hard
    bound: excess config entries fail before probing instead of being silently
    truncated. Every candidate receives the same number of MD and TD samples;
    each endpoint needs a strict majority of successful samples. If every
    configured pair is ineligible, a typed error contains failure evidence
    and no pair is chosen.

    Use a timeout of at least 3 seconds for typical CTP fronts. The maximum
    aggregate probe budget, including a bounded worker termination grace, is
    180 seconds across all configured endpoints. The default runtime path runs
    at most eight endpoint jobs at once; injected connector, worker-process
    factory or clock dependencies run serially for deterministic offline tests.
    ``deadline_monotonic`` is an optional absolute deadline in the same clock
    domain as ``clock`` (or ``time.perf_counter`` when no clock is injected).
    Each connect receives at most the remaining time, and no connect is started
    after the deadline is observed. This cannot bound a blocking OS call,
    connector, process factory, socket close, or worker cleanup as a whole.
    """

    if (
        isinstance(timeout_seconds, bool)
        or type(timeout_seconds) not in (int, float)
        or not math.isfinite(float(timeout_seconds))
        or not 0 < float(timeout_seconds) <= _MAX_TIMEOUT_SECONDS
    ):
        raise CtpFrontPairProbeError("probe_timeout_out_of_bounds")
    if type(max_pairs) is not int or not 1 <= max_pairs <= _MAX_PAIRS:
        raise CtpFrontPairProbeError("max_pairs_out_of_bounds")
    if type(repeated_samples) is not int or not 1 <= repeated_samples <= _MAX_REPEATED_SAMPLES:
        raise CtpFrontPairProbeError("repeated_samples_out_of_bounds")
    if deadline_monotonic is None:
        deadline = None
    else:
        if isinstance(deadline_monotonic, bool) or type(deadline_monotonic) not in (int, float):
            raise CtpFrontPairProbeError("probe_deadline_invalid")
        try:
            deadline = float(deadline_monotonic)
        except (OverflowError, ValueError) as error:
            raise CtpFrontPairProbeError("probe_deadline_invalid") from error
        if not math.isfinite(deadline):
            raise CtpFrontPairProbeError("probe_deadline_invalid")
    timeout = float(timeout_seconds)
    candidates = _configured_pairs(front_pairs, max_pairs=max_pairs)
    worst_case = len(candidates) * 2 * repeated_samples * (
        timeout + _WORKER_TERMINATION_ATTEMPTS * _WORKER_TERMINATION_GRACE_SECONDS
    )
    if worst_case > _MAX_WORST_CASE_SECONDS:
        raise CtpFrontPairProbeError("probe_budget_exceeds_limit")
    # Keep injected dependencies deterministic for offline callers and tests.
    # The runtime path has independent endpoint jobs, so probe those in a
    # bounded pool while keeping each endpoint's repeated samples sequential.
    use_parallel_probes = connector is None and process_factory is None and clock is None
    process_factory = process_factory or _default_process_factory
    now = clock or time.perf_counter

    def probe_endpoint(front: _ParsedFront) -> tuple[CtpFrontProbeSample, ...]:
        def hostname_connector(host: str, port: int, timeout_value: float) -> Any:
            return _bounded_hostname_connect(
                host,
                port,
                timeout_value,
                process_factory=process_factory,
                deadline_clock=now,
                deadline_monotonic=deadline,
            )

        def deadline_connector(host: str, port: int, timeout_value: float) -> Any:
            assert deadline is not None
            return _deadline_connect(
                host,
                port,
                timeout_value,
                deadline_monotonic=deadline,
                deadline_clock=now,
            )

        if front.ip_literal:
            if connector is not None:
                endpoint_connector = connector
            elif deadline is None:
                endpoint_connector = _default_connect
            else:
                endpoint_connector = deadline_connector
        else:
            endpoint_connector = hostname_connector
        samples = []
        for _ in range(repeated_samples):
            samples.append(
                _probe_one(
                    front,
                    timeout_seconds=timeout,
                    connector=endpoint_connector,
                    clock=now,
                    deadline_monotonic=deadline,
                )
            )
        return tuple(samples)

    endpoints = tuple(
        (index, side, front)
        for index, (_, md_front, td_front) in enumerate(candidates)
        for side, front in (("md", md_front), ("td", td_front))
    )
    if use_parallel_probes and len(endpoints) > 1:
        worker_count = min(_MAX_CONCURRENT_ENDPOINTS, len(endpoints))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(probe_endpoint, front) for _, _, front in endpoints]
            endpoint_samples = [future.result() for future in futures]
    else:
        endpoint_samples = [probe_endpoint(front) for _, _, front in endpoints]

    samples_by_endpoint = {
        (index, side): samples
        for (index, side, _), samples in zip(endpoints, endpoint_samples)
    }
    evidence = []
    for index, (pair, _, _) in enumerate(candidates):
        md_samples = samples_by_endpoint[(index, "md")]
        td_samples = samples_by_endpoint[(index, "td")]
        md = CtpFrontEndpointEvidence(pair.md_front, md_samples)
        td = CtpFrontEndpointEvidence(pair.td_front, td_samples)
        md_median = md.median_latency_ms
        td_median = td.median_latency_ms
        reachable = md_median is not None and td_median is not None
        score = max(md_median, td_median) if reachable else None
        evidence.append(
            CtpFrontPairEvidence(
                config_index=index,
                pair=pair,
                md=md,
                td=td,
                reachable=reachable,
                latency_score_ms=score,
            )
        )

    reachable_pairs = tuple(item for item in evidence if item.reachable)
    if not reachable_pairs:
        if deadline is not None and now() >= deadline:
            raise CtpFrontPairProbeError("probe_global_deadline_exceeded", tuple(evidence))
        raise CtpFrontPairProbeError("no_configured_front_pair_reachable", tuple(evidence))
    selected = min(reachable_pairs, key=lambda item: (item.latency_score_ms, item.config_index))
    selection = CtpFrontPairSelection(
        pair=selected.pair,
        config_index=selected.config_index,
        latency_score_ms=selected.latency_score_ms,
        evidence=tuple(evidence),
        timeout_seconds=timeout,
        repeated_samples=repeated_samples,
    )
    if deadline is not None and now() >= deadline:
        raise CtpFrontPairProbeError("probe_global_deadline_exceeded", tuple(evidence))
    return selection


__all__ = [
    "CtpConfiguredFrontPair",
    "CtpFrontEndpointEvidence",
    "CtpFrontPairEvidence",
    "CtpFrontPairProbeError",
    "CtpFrontPairSelection",
    "CtpFrontProbeSample",
    "select_ctp_front_pair",
]

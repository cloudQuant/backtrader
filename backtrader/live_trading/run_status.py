"""BT process contract of one live run (iteration 66, §5.2 B2/B3/B5).

A supervised live strategy process has no terminal exit code its owner can
observe: the runtime that restarted it did not spawn it.  This module gives the
process two atomic files and an exit-code mapping (R1: the runtime only reads
them; the strategy process never imports the runtime, INV66-02):

``state/run_status.json`` (B2, heartbeat)
    Written by an independent daemon thread every ``heartbeat_interval_s``
    (never from the per-bar hot path), atomically, so a reader sees either the
    previous or the next complete document.  The fields and their names follow
    what ``bt_api_runtime.supervision.status.StatusObservation`` consumes
    (``run_id``, ``pid``, ``phase``, ``heartbeat_sequence``, ``stop_budget_s``,
    ``budget_proven``, ``last_error_code``, ``write_block_reasons``) plus the
    timestamps from which that adapter derives ``heartbeat_age_s``
    (``updated_at_utc``) and ``main_loop_age_s``
    (``main_loop_last_progress_utc``).  Everything else the plan requires is
    additive: strategy UUID, heartbeat interval, per-data state, counts, the
    composed stop budget, and the stop request source and first time.

    The key set is a strict whitelist and every value comes from a finite
    vocabulary, a number, a UUID or an ISO-8601 UTC timestamp: no credential,
    price or free text can be written.  Code-shaped values are additionally
    screened for secret markers, but a caller must still pass framework-
    generated finite codes — a code-shaped account identifier would pass the
    shape filter, so identifiers are never passed here.

``state/last_run.json`` (B3, final summary)
    Exactly the twelve fields of ``bt_api_run_contract.states.FinalSummary``
    (``schema`` = ``bt_api_run_summary/v1``), because the runtime's
    ``JsonSummarySource`` rejects any other key set.  The Broker's
    ``get_shutdown_summary()``, the exit code, the exit reason code and the
    composed budget cannot be added there without breaking that reader, so
    they go to the companion ``state/last_run_details.json``
    (``backtrader.run_details/v1``); the two files are written one after the
    other at stop and a reader must treat a detail file without a summary file
    as UNKNOWN.

Exit codes (frozen here for 66.01/66.03): ``0`` clean ``STOPPED`` (including a
provable ``NOT_STARTED``: a stop before any account write), ``2`` ``BLOCKED``,
``3`` ``STOPPED_WITH_WORKING_ORDERS``, ``4`` ``STOPPED_WITH_WRITE_IN_FLIGHT``,
``1`` an unexpected exception or any other unresolved outcome — the process
never claims success for a stop it cannot prove (e.g. a start aborted after a
committed settlement write).

Stop budget (B5)
    ``compute_stop_budget`` composes the serial worst case of the stop phases
    from the Broker parameters and from externally *proven* bounds.  A phase
    whose upper bound is not provable is published as ``null`` and named in
    ``unproven_phases``; ``proven``/``stop_budget_s`` stay false/``null``, so
    the runtime's E3 (SIGKILL) can never be timed from a guessed value
    (INV66-10).  A configuration value is not by itself a proof.

Evidence level: UNIT/FAKE.  Nothing here contacts a provider or an account,
reads a credential or needs a network.  Windows is untested.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import os
import re
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, cast

from ..utils.log_message import get_logger, throttled_warning
from ..live_state import atomic_write_json, read_json

_log = get_logger(__name__)

__all__ = (
    "DATA_STATES",
    "DEFAULT_HEARTBEAT_INTERVAL_S",
    "EXIT_BLOCKED",
    "EXIT_CODES",
    "EXIT_STOPPED",
    "EXIT_STOPPED_WITH_WORKING_ORDERS",
    "EXIT_STOPPED_WITH_WRITE_IN_FLIGHT",
    "EXIT_UNEXPECTED",
    "LAST_RUN_DETAILS_FILENAME",
    "LAST_RUN_FILENAME",
    "MAX_HEARTBEAT_INTERVAL_S",
    "MIN_HEARTBEAT_INTERVAL_S",
    "OUTCOMES",
    "PHASES",
    "RunConclusion",
    "RunFacts",
    "RunStatusError",
    "RunStatusWriter",
    "STATE_DIRNAME",
    "STATUS_FILENAME",
    "STATUS_SCHEMA",
    "STOP_SOURCES",
    "compute_stop_budget",
    "derive_outcome",
    "direct_run_facts",
    "direct_stop_budget",
    "exit_code_for",
    "last_run_details_path",
    "last_run_path",
    "read_process_identity",
    "read_run_status",
    "run_status_path",
)

# ---------------------------------------------------------------------------
# contract constants
# ---------------------------------------------------------------------------
STATE_DIRNAME = "state"  # same directory as ``backtrader.live_state``
STATUS_FILENAME = "run_status.json"
LAST_RUN_FILENAME = "last_run.json"
LAST_RUN_DETAILS_FILENAME = "last_run_details.json"

STATUS_SCHEMA = "bt_api_run_status/v1"
#: The runtime's ``FinalSummary.SUMMARY_SCHEMA``; ``last_run.json`` is exactly
#: that document, so the value is fixed by the other repository.
SUMMARY_SCHEMA = "bt_api_run_summary/v1"
DETAILS_SCHEMA = "backtrader.run_details/v1"
BUDGET_SCHEMA = "bt_stop_budget/v1"

PHASES = ("INITIALIZING", "RECONCILING", "WARMUP", "LIVE", "STOPPING", "STOPPED")
#: Per-data state: LIVE (may back an order now), WARMUP (feed not live or not
#: qualified), STOPPED, UNKNOWN (no evidence either way).
DATA_STATES = ("LIVE", "WARMUP", "STOPPED", "UNKNOWN")
#: Same vocabulary as ``bt_api_run_contract.states.StopSource``.
STOP_SOURCES = ("SIGTERM", "SIGBREAK", "stop_file", "internal", "UNKNOWN")
#: Same vocabulary as ``bt_api_run_contract.states.SummaryOutcome``.
OUTCOMES = (
    "STOPPED",
    "STOPPED_WITH_WORKING_ORDERS",
    "STOPPED_WITH_WRITE_IN_FLIGHT",
    "BLOCKED",
    "CRASHED",
    "KILLED",
    "UNKNOWN",
)

EXIT_STOPPED = 0
EXIT_UNEXPECTED = 1
EXIT_BLOCKED = 2
EXIT_STOPPED_WITH_WORKING_ORDERS = 3
EXIT_STOPPED_WITH_WRITE_IN_FLIGHT = 4

#: Outcome -> process exit code (66.02 freezes these values for 66.01/66.03).
#: ``UNKNOWN``/``KILLED`` are not enumerated by the plan's five codes; they exit
#: ``1`` (the fail-closed "did not conclude cleanly" code), never ``0``.
EXIT_CODES = {
    "STOPPED": EXIT_STOPPED,
    "STOPPED_WITH_WORKING_ORDERS": EXIT_STOPPED_WITH_WORKING_ORDERS,
    "STOPPED_WITH_WRITE_IN_FLIGHT": EXIT_STOPPED_WITH_WRITE_IN_FLIGHT,
    "BLOCKED": EXIT_BLOCKED,
    "CRASHED": EXIT_UNEXPECTED,
    "KILLED": EXIT_UNEXPECTED,
    "UNKNOWN": EXIT_UNEXPECTED,
}

MIN_HEARTBEAT_INTERVAL_S = 0.05
MAX_HEARTBEAT_INTERVAL_S = 300.0
DEFAULT_HEARTBEAT_INTERVAL_S = 1.0
#: Bound on the per-data index: a malformed large index must fail at the
#: setter instead of silently invalidating every later heartbeat document.
_MAX_DATA_INDEX = 256

#: Every key the heartbeat document may contain (B2's "strict key whitelist").
STATUS_KEYS = frozenset(
    {
        "schema",
        "strategy_uuid",
        "run_id",
        "pid",
        "phase",
        "updated_at_utc",
        "heartbeat_sequence",
        "heartbeat_interval_s",
        "main_loop_last_progress_utc",
        "datas",
        "write_block_reasons",
        "unknown_unresolved_count",
        "active_order_count",
        "stop_budget_s",
        "budget_proven",
        "stop_budget",
        "last_error_code",
        "stop_source",
        "stop_requested_at_utc",
    }
)
BUDGET_KEYS = frozenset(
    {"schema", "proven", "total_seconds", "unproven_phases", "components", "parameters"}
)
BUDGET_COMPONENT_KEYS = frozenset(
    {
        "start_in_progress_s",
        "startup_facts_retry_s",
        "cancel_request_s",
        "cancel_wait_s",
        "committed_write_wait_s",
        "tail_s",
    }
)
#: Components that are summed into ``total_seconds`` (strict serial worst case;
#: ``startup_facts_retry_s`` is a step of ``start_in_progress_s``, informational).
BUDGET_TOTAL_COMPONENTS = (
    "start_in_progress_s",
    "cancel_request_s",
    "cancel_wait_s",
    "committed_write_wait_s",
    "tail_s",
)
BUDGET_PARAMETER_KEYS = frozenset(
    {
        "stop_cancel_timeout",
        "direct_stop_write_timeout",
        "direct_startup_facts_attempts",
        "direct_facts_timeout",
        "direct_startup_facts_retry_delay",
    }
)
DATA_KEYS = frozenset({"index", "state"})

#: Finite code syntax shared with the runtime's ``_validate.token``.
_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SECRET_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "authorization",
    "api_key",
    "apikey",
    "private_key",
)

ERROR_CODES = frozenset(
    {
        "run_status_error",
        "invalid_strategy_dir",
        "invalid_run_id",
        "invalid_interval",
        "invalid_phase",
        "invalid_data_index",
        "invalid_code",
        "invalid_stop_source",
        "invalid_timestamp",
        "invalid_budget",
        "status_document_invalid",
        "status_write_failed",
        "process_identity_unavailable",
        "value_not_json_safe",
    }
)


class RunStatusError(RuntimeError):
    """A contract violation; ``code`` is one of the finite :data:`ERROR_CODES`."""

    def __init__(self, code: str = "run_status_error", detail: str = "") -> None:
        if type(code) is not str or code not in ERROR_CODES:
            code = "run_status_error"
        self.code = code
        self.detail = detail if type(detail) is str else ""
        super().__init__(f"{code}: {self.detail}" if self.detail else code)


# ---------------------------------------------------------------------------
# small validators
# ---------------------------------------------------------------------------
def _is_code(value: Any) -> bool:
    return type(value) is str and _CODE_RE.match(value) is not None


_STATUS_TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def _is_status_token(value: Any) -> bool:
    """A Broker summary status (``STOPPED``, ``STOPPED_WITH_WRITE_IN_FLIGHT`` ...)."""
    return type(value) is str and _STATUS_TOKEN_RE.match(value) is not None


def _is_number(value: Any) -> bool:
    return type(value) in (int, float) and not isinstance(value, bool)


def _copy_json(value: Any) -> Any:
    """A fresh JSON value (the budget is immutable after construction)."""
    return json.loads(json.dumps(value, allow_nan=False))


def _finite_non_negative(value: Any) -> Optional[float]:
    if not _is_number(value):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        return None
    return number


def _positive_int(value: Any) -> Optional[int]:
    if type(value) is not int or value < 1:
        return None
    return value


def _utc_text(moment: Optional[_dt.datetime] = None) -> str:
    value = moment or _dt.datetime.now(_dt.timezone.utc)
    if not isinstance(value, _dt.datetime):
        raise RunStatusError("invalid_timestamp")
    if value.tzinfo is None:
        raise RunStatusError("invalid_timestamp")
    return value.astimezone(_dt.timezone.utc).isoformat(timespec="microseconds")


def _is_utc_text(value: Any) -> bool:
    if type(value) is not str or not value or len(value) > 64:
        return False
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == _dt.timedelta(0)


def _canonical_uuid(value: Any) -> str:
    if type(value) is not str:
        raise RunStatusError("invalid_run_id")
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise RunStatusError("invalid_run_id") from None


def _is_uuid4_text(value: Any) -> bool:
    if type(value) is not str:
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return parsed.version == 4 and str(parsed) == value


def run_status_path(strategy_dir: Any) -> str:
    """``<strategy_dir>/state/run_status.json`` (no directory is created)."""
    return os.path.join(os.fspath(strategy_dir), STATE_DIRNAME, STATUS_FILENAME)


def last_run_path(strategy_dir: Any) -> str:
    """``<strategy_dir>/state/last_run.json`` (the runtime's strict summary)."""
    return os.path.join(os.fspath(strategy_dir), STATE_DIRNAME, LAST_RUN_FILENAME)


def last_run_details_path(strategy_dir: Any) -> str:
    """``<strategy_dir>/state/last_run_details.json`` (BT-side evidence)."""
    return os.path.join(os.fspath(strategy_dir), STATE_DIRNAME, LAST_RUN_DETAILS_FILENAME)


# ---------------------------------------------------------------------------
# process identity (B3)
# ---------------------------------------------------------------------------
_BOOTTIME_SEC = re.compile(r"sec\s*=\s*(\d+)")


def _os_boot_id() -> Optional[str]:
    """Stable OS boot identifier, mirroring ``bt_api_runtime.supervision.clock``.

    ``None`` when it cannot be read (Windows has no standard-library source);
    then persisted deadlines are not comparable across a runtime restart and
    callers must report UNKNOWN instead of inferring a wait.
    """
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/sys/kernel/random/boot_id", "r", encoding="ascii") as handle:
                return handle.read().strip() or None
        except OSError:
            return None
    if sys.platform == "darwin":
        try:
            output = subprocess.run(
                ["sysctl", "-n", "kern.boottime"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        match = _BOOTTIME_SEC.search(output)
        return "darwin:{}".format(match.group(1)) if match else None
    return None


def _command_digest(argv: Sequence[str]) -> str:
    """The runtime's ``command_digest``: SHA-256 over NUL-terminated argv items."""
    import hashlib

    hasher = hashlib.sha256()
    for item in argv:
        hasher.update(str(item).encode("utf-8", "surrogateescape"))
        hasher.update(b"\x00")
    return "sha256:" + hasher.hexdigest()


def _linux_identity(pid: int) -> Optional[Dict[str, Any]]:
    try:
        with open("/proc/{}/stat".format(pid), "r", encoding="utf-8") as handle:
            stat = handle.read()
        with open("/proc/{}/cmdline".format(pid), "rb") as handle:
            cmdline = handle.read()
    except OSError:
        return None
    closing = stat.rfind(")")
    if closing < 0:
        return None
    fields = stat[closing + 2 :].split()
    if len(fields) < 20:
        return None
    argv = [part.decode("utf-8", "surrogateescape") for part in cmdline.split(b"\x00") if part]
    return {
        "pid": pid,
        "create_time": "linux:{}".format(fields[19]),
        "boot_id": _os_boot_id() or "unavailable",
        "command_digest": _command_digest(argv),
        "source": "linux_proc",
    }


def _ps_identity(pid: int) -> Optional[Dict[str, Any]]:
    if os.name == "nt":  # pragma: no cover - Windows only
        return None
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart=", "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    parts = result.stdout.strip().split(None, 5)
    if len(parts) < 6:
        return None
    return {
        "pid": pid,
        "create_time": " ".join(parts[:5]),
        "boot_id": _os_boot_id() or "unavailable",
        "command_digest": _command_digest([parts[5]]),
        "source": "ps",
    }


def _windows_identity(pid: int) -> Optional[Dict[str, Any]]:
    if os.name != "nt":
        return None
    try:
        import psutil
    except ImportError:
        return None
    try:
        process = psutil.Process(pid)
        create_time = "{:.6f}".format(process.create_time())
        argv = process.cmdline()
    except Exception:
        return None
    return {
        "pid": pid,
        "create_time": "win:{}".format(create_time),
        "boot_id": "windows-boot-unavailable",
        "command_digest": _command_digest(argv),
        "source": "windows_psutil",
    }


def read_process_identity(pid: Optional[int] = None) -> Dict[str, Any]:
    """Best-effort ``ProcessIdentityRef`` fields of this (or ``pid``) process.

    The four fields ``pid``/``create_time``/``boot_id``/``command_digest`` are
    produced by the same procedures as ``bt_api_runtime.supervision.posix`` (or
    ``bt_api_runtime.supervision.windows`` on Windows) so that a summary
    written here can equal the runtime's own reference.  When the OS cannot
    supply them, the values are ``"unavailable"`` (never invented): the runtime
    then reports UNKNOWN instead of a clean stop, which is the intended
    fail-closed result.  ``source`` records which procedure ran; it is BT-side
    evidence and is not part of the summary document.
    """
    target = os.getpid() if pid is None else int(pid)
    if os.name == "nt":
        identity = _windows_identity(target)
        if identity is not None:
            return identity
    if sys.platform.startswith("linux"):
        identity = _linux_identity(target)
        if identity is not None:
            return identity
    identity = _ps_identity(target)
    if identity is not None:
        return identity
    return {
        "pid": target,
        "create_time": "unavailable",
        "boot_id": _os_boot_id() or "unavailable",
        "command_digest": "unavailable",
        "source": "unavailable",
    }


# ---------------------------------------------------------------------------
# stop budget (B5)
# ---------------------------------------------------------------------------
def _budget_component(name: str, unproven: List[str], value: Optional[float]) -> Optional[float]:
    if value is None:
        if name != "startup_facts_retry_s":
            unproven.append(name[: -len("_s")])
        return None
    return value


def compute_stop_budget(
    *,
    stop_cancel_timeout: Any = None,
    direct_stop_write_timeout: Any = None,
    startup_facts_attempts: Any = None,
    direct_facts_timeout: Any = None,
    startup_facts_retry_delay: Any = None,
    start_in_progress_bound_s: Any = None,
    cancel_request_bound_s: Any = None,
    tail_bound_s: Any = None,
) -> Dict[str, Any]:
    """Compose the conservative stop budget published in the status file.

    ``start_in_progress_s`` (login, reconciliation, the startup facts read,
    permission read and the settlement step), ``cancel_request_s`` (one venue
    cancel request) and ``tail_s`` (final snapshot, Store stop) have no bound
    this framework proves by itself: they are ``None`` unless the caller passes
    a bound proven elsewhere (provider/SDK contract, or a deployment that
    enforces one).  ``cancel_wait_s`` (``stop_cancel_timeout``) and
    ``committed_write_wait_s`` (``direct_stop_write_timeout``) are deadlines
    this framework itself enforces, so their configured values are bounds.

    The total is a strict *serial* sum of the five phases; no overlap is
    credited, which can only over-estimate.  ``proven`` is false while any
    phase is unproven, and then ``total_seconds`` is ``None``: the runtime must
    not time SIGKILL from it (INV66-10).
    """
    unproven: List[str] = []

    attempts = _positive_int(startup_facts_attempts)
    facts_timeout = _finite_non_negative(direct_facts_timeout)
    retry_delay = _finite_non_negative(startup_facts_retry_delay)
    retry_total: Optional[float] = None
    if attempts is not None and facts_timeout is not None and retry_delay is not None:
        retry_total = attempts * facts_timeout + (attempts - 1) * retry_delay

    components = {
        "start_in_progress_s": _budget_component(
            "start_in_progress_s", unproven, _finite_non_negative(start_in_progress_bound_s)
        ),
        "startup_facts_retry_s": _budget_component("startup_facts_retry_s", unproven, retry_total),
        "cancel_request_s": _budget_component(
            "cancel_request_s", unproven, _finite_non_negative(cancel_request_bound_s)
        ),
        "cancel_wait_s": _budget_component(
            "cancel_wait_s", unproven, _finite_non_negative(stop_cancel_timeout)
        ),
        "committed_write_wait_s": _budget_component(
            "committed_write_wait_s", unproven, _finite_non_negative(direct_stop_write_timeout)
        ),
        "tail_s": _budget_component("tail_s", unproven, _finite_non_negative(tail_bound_s)),
    }
    proven = not unproven
    total: Optional[float] = None
    if proven:
        total = float(sum(cast(float, components[name]) for name in BUDGET_TOTAL_COMPONENTS))
    parameters = {
        "stop_cancel_timeout": _finite_non_negative(stop_cancel_timeout),
        "direct_stop_write_timeout": _finite_non_negative(direct_stop_write_timeout),
        "direct_startup_facts_attempts": attempts,
        "direct_facts_timeout": facts_timeout,
        "direct_startup_facts_retry_delay": retry_delay,
    }
    return {
        "schema": BUDGET_SCHEMA,
        "proven": proven,
        "total_seconds": total,
        "unproven_phases": sorted(unproven),
        "components": components,
        "parameters": parameters,
    }


def direct_stop_budget(broker: Any, **proven: Any) -> Dict[str, Any]:
    """``compute_stop_budget`` from a direct-mode ``BtApiBroker``'s parameters.

    ``proven`` forwards ``start_in_progress_bound_s``/``cancel_request_bound_s``/
    ``tail_bound_s`` for deployments that can prove those phases; without them
    the budget is published as unproven.  Parameters that are missing or
    invalid are published as ``null`` and leave their phase unproven.
    """
    params = getattr(broker, "p", None)

    def read(name: str) -> Any:
        return getattr(params, name, None) if params is not None else None

    return compute_stop_budget(
        stop_cancel_timeout=read("stop_cancel_timeout"),
        direct_stop_write_timeout=read("direct_stop_write_timeout"),
        startup_facts_attempts=read("direct_startup_facts_attempts"),
        direct_facts_timeout=read("direct_facts_timeout"),
        startup_facts_retry_delay=read("direct_startup_facts_retry_delay"),
        **proven,
    )


def _validate_budget(budget: Any) -> Dict[str, Any]:
    if type(budget) is not dict or set(budget) != BUDGET_KEYS:
        raise RunStatusError("invalid_budget", "keys")
    if budget["schema"] != BUDGET_SCHEMA:
        raise RunStatusError("invalid_budget", "schema")
    if type(budget["proven"]) is not bool:
        raise RunStatusError("invalid_budget", "proven")
    total = budget["total_seconds"]
    if total is not None and _finite_non_negative(total) is None:
        raise RunStatusError("invalid_budget", "total_seconds")
    if budget["proven"] and total is None:
        raise RunStatusError("invalid_budget", "total_seconds")
    if not budget["proven"] and total is not None:
        raise RunStatusError("invalid_budget", "total_seconds")
    phases = budget["unproven_phases"]
    if type(phases) is not list or any(not _is_code(item) for item in phases):
        raise RunStatusError("invalid_budget", "unproven_phases")
    if budget["proven"] and phases:
        raise RunStatusError("invalid_budget", "unproven_phases")
    components = budget["components"]
    if type(components) is not dict or set(components) != BUDGET_COMPONENT_KEYS:
        raise RunStatusError("invalid_budget", "components")
    for name, value in components.items():
        if value is not None and _finite_non_negative(value) is None:
            raise RunStatusError("invalid_budget", name)
    parameters = budget["parameters"]
    if type(parameters) is not dict or set(parameters) != BUDGET_PARAMETER_KEYS:
        raise RunStatusError("invalid_budget", "parameters")
    for name, value in parameters.items():
        if value is not None and _finite_non_negative(value) is None:
            raise RunStatusError("invalid_budget", name)
    if budget["proven"] and any(components[name] is None for name in BUDGET_TOTAL_COMPONENTS):
        raise RunStatusError("invalid_budget", "components")
    return budget


# ---------------------------------------------------------------------------
# facts from a direct-mode Broker (thread-safe, non-blocking)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RunFacts:
    """The Broker facts the status file may publish; ``None`` means UNKNOWN.

    ``None`` is never replaced by ``0`` or ``()``: an unreadable or unprovable
    value stays unknown, so a reader cannot mistake it for a proven empty set.
    """

    write_block_reasons: Optional[Tuple[str, ...]] = None
    unknown_unresolved_count: Optional[int] = None
    active_order_count: Optional[int] = None
    last_error_code: Optional[str] = None


def _codes_from(values: Any) -> Optional[Tuple[str, ...]]:
    """Sorted finite codes; anything else collapses to one ``unclassified`` code.

    A value that is not a finite lowercase code, or that looks like a secret,
    is never published as itself: the status file cannot carry free text.
    """
    if values is None or isinstance(values, (str, bytes, bytearray)):
        return None
    try:
        items = list(values)
    except TypeError:
        return None
    codes = set()
    for item in items:
        code = _publishable_code(item)
        codes.add(code if code is not None else "unclassified")
    return tuple(sorted(codes))


def _publishable_code(value: Any) -> Optional[str]:
    if not _is_code(value):
        return None
    lowered = value.lower()
    if any(marker in lowered for marker in _SECRET_MARKERS):
        return None
    return cast(str, value)


def direct_run_facts(broker: Any) -> RunFacts:
    """Read a direct-mode Broker's publishable facts without blocking the heartbeat.

    Runs on the heartbeat thread, so it takes ``_direct_lock`` only when it is
    free: a contended lock means the strategy thread is inside a live-state
    operation, and waiting there could deadlock against the file lock it holds.
    Contention or any read failure yields an all-``None`` :class:`RunFacts`
    (UNKNOWN), never a zero count.  Reads no file and no provider.
    """
    lock = getattr(broker, "_direct_lock", None)
    acquired = False
    try:
        if lock is not None:
            acquired = lock.acquire(blocking=False)
            if not acquired:
                return RunFacts()
        if not bool(getattr(broker, "_direct_active", lambda: False)()):
            return RunFacts()
        blocked = broker.direct_writes_blocked()
        reasons = _codes_from(dict(blocked).values())
        orders = broker.orders
        active = sum(1 for order in list(orders.values()) if order.alive())
        metas = list(getattr(broker, "_direct_meta", {}).values())
        unknown = sum(1 for meta in metas if meta.get("unknown") or meta.get("day_unknown"))
        for entry in list(getattr(broker, "_direct_fill_gaps", {}).values()):
            if entry.get("state") == "unknown":
                unknown += 1
        settlement = getattr(broker, "_direct_settlement", None)
        if settlement is not None and settlement.get("status") == "manual_required":
            unknown += 1
        return RunFacts(
            write_block_reasons=reasons,
            unknown_unresolved_count=int(unknown),
            active_order_count=int(active),
            last_error_code=None,
        )
    except Exception:  # a status read is never allowed to break the heartbeat
        return RunFacts()
    finally:
        if acquired and lock is not None:
            lock.release()


def _validate_facts(facts: Any) -> RunFacts:
    """Normalize any provider result; unusable fields become UNKNOWN."""
    if isinstance(facts, RunFacts):
        reasons = facts.write_block_reasons
        unknown = facts.unknown_unresolved_count
        active = facts.active_order_count
        error = facts.last_error_code
    elif isinstance(facts, Mapping):
        reasons = facts.get("write_block_reasons")
        unknown = facts.get("unknown_unresolved_count")
        active = facts.get("active_order_count")
        error = facts.get("last_error_code")
    else:
        return RunFacts()
    return RunFacts(
        write_block_reasons=_codes_from(reasons),
        unknown_unresolved_count=(unknown if type(unknown) is int and unknown >= 0 else None),
        active_order_count=active if type(active) is int and active >= 0 else None,
        last_error_code=_publishable_code(error),
    )


# ---------------------------------------------------------------------------
# the heartbeat writer (B2)
# ---------------------------------------------------------------------------
class RunStatusWriter:
    """Heartbeat + final summary of one live run (B2/B3/B5).

    One writer per process.  Start it before the run's side effects and finish
    it after the Broker stopped::

        termination = stop_on_terminate(cerebro)
        contract = RunStatusWriter(
            STRATEGY_DIR,
            run_id=run_id,
            broker=broker,
            stop_request_provider=termination.request_state,
        )
        contract.start()
        try:
            with termination:
                cerebro.run()
        finally:
            result = contract.finish(broker_summary=broker.get_shutdown_summary())
        return result.exit_code

    The heartbeat thread only serializes in-memory state (and the injected,
    non-blocking facts provider); it never runs provider, Broker or strategy
    code.  All document builds validate the strict key whitelist before the
    atomic replace, so an invalid or secret-bearing field fails the write
    instead of reaching the file.
    """

    def __init__(
        self,
        strategy_dir: Any,
        *,
        run_id: Optional[str] = None,
        heartbeat_interval_s: Any = DEFAULT_HEARTBEAT_INTERVAL_S,
        strategy_uuid: Optional[str] = None,
        broker: Any = None,
        facts_provider: Optional[Callable[[], Any]] = None,
        feeds: Optional[Sequence[Any]] = None,
        stop_budget: Optional[Mapping[str, Any]] = None,
        stop_request_provider: Optional[Callable[[], Any]] = None,
        process_identity: Optional[Mapping[str, Any]] = None,
        clock: Optional[Callable[[], _dt.datetime]] = None,
    ) -> None:
        directory = os.fspath(strategy_dir) if strategy_dir is not None else ""
        if type(directory) is not str or not directory or not os.path.isdir(directory):
            raise RunStatusError("invalid_strategy_dir")
        self.strategy_dir = directory
        self.run_id = _canonical_uuid(run_id) if run_id is not None else str(uuid.uuid4())
        if not _is_uuid4_text(strategy_uuid) and strategy_uuid is not None:
            raise RunStatusError("invalid_run_id", "strategy_uuid")
        self._strategy_uuid = strategy_uuid
        if (
            not _is_number(heartbeat_interval_s)
            or not math.isfinite(float(heartbeat_interval_s))
            or not MIN_HEARTBEAT_INTERVAL_S
            <= float(heartbeat_interval_s)
            <= MAX_HEARTBEAT_INTERVAL_S
        ):
            raise RunStatusError("invalid_interval")
        self.heartbeat_interval_s = float(heartbeat_interval_s)
        self.pid = os.getpid()
        self._clock = clock or (lambda: _dt.datetime.now(_dt.timezone.utc))
        self._facts_provider = facts_provider
        if self._facts_provider is None and broker is not None:
            self._facts_provider = lambda: direct_run_facts(broker)
        if feeds is None and broker is not None:
            store = getattr(broker, "store", None)
            feeds = getattr(store, "_data_feeds", None)
        self._feeds = list(feeds or ())
        if stop_budget is None:
            # A direct-mode Broker publishes its own parameters; anything else
            # publishes an empty (unproven) budget rather than guessed values.
            stop_budget = (
                direct_stop_budget(broker) if broker is not None else compute_stop_budget()
            )
        self._stop_budget = _validate_budget(dict(stop_budget))
        self._stop_request_provider = stop_request_provider
        self._process_identity = dict(process_identity) if process_identity else None

        self.state_dir = os.path.join(directory, STATE_DIRNAME)
        self.path = run_status_path(directory)
        self.last_run_path = last_run_path(directory)
        self.last_run_details_path = last_run_details_path(directory)

        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._phase = "INITIALIZING"
        self._sequence = 0
        self._loop_progress: Optional[str] = None
        self._data_states: Dict[int, str] = {}
        self._last_error_code: Optional[str] = None
        self._status_write_failed = False
        self._stop_source: Optional[str] = None
        self._stop_requested_at_utc: Optional[str] = None
        self._finished: Optional[RunConclusion] = None

    # -- public state -------------------------------------------------------
    @property
    def phase(self) -> str:
        with self._lock:
            return self._phase

    @property
    def heartbeat_sequence(self) -> int:
        with self._lock:
            return self._sequence

    @property
    def finished(self) -> bool:
        return self._finished is not None

    def set_phase(self, phase: str) -> None:
        if phase not in PHASES:
            raise RunStatusError("invalid_phase")
        with self._lock:
            if self._finished is not None:
                return
            self._phase = phase

    def loop_progress(self) -> None:
        """Record that the main loop advanced (in memory only; no file write)."""
        with self._lock:
            self._loop_progress = _utc_text(self._clock())

    def set_data_state(self, index: int, state: str) -> None:
        if type(index) is not int or not 0 <= index < _MAX_DATA_INDEX:
            raise RunStatusError("invalid_data_index")
        if state not in DATA_STATES:
            raise RunStatusError("invalid_phase", "data_state")
        with self._lock:
            self._data_states[index] = state

    def set_last_error(self, code: Optional[str]) -> None:
        if code is not None and not _is_code(code):
            raise RunStatusError("invalid_code")
        if code is not None and any(marker in code.lower() for marker in _SECRET_MARKERS):
            raise RunStatusError("invalid_code", "secret_marker")
        with self._lock:
            self._last_error_code = code

    def note_stop_request(self, source: str, at_utc: Optional[str] = None) -> None:
        """Record the first stop request (source and UTC time); later ones are ignored."""
        if source not in STOP_SOURCES:
            raise RunStatusError("invalid_stop_source")
        if at_utc is not None and not _is_utc_text(at_utc):
            raise RunStatusError("invalid_timestamp")
        with self._lock:
            self._note_stop_request_locked(source, at_utc)

    def _note_stop_request_locked(self, source: str, at_utc: Optional[str]) -> None:
        if self._stop_source is not None:
            return
        self._stop_source = source
        self._stop_requested_at_utc = at_utc or _utc_text(self._clock())

    def _pull_stop_request(self) -> None:
        provider = self._stop_request_provider
        if provider is None or self._stop_source is not None:
            return
        try:
            state = provider()
        except Exception:  # an unreadable request source is not a stop
            return
        if not state:
            return
        try:
            source, at_utc = state
        except (TypeError, ValueError):
            return
        if source not in STOP_SOURCES:
            return
        with self._lock:
            self._note_stop_request_locked(source, at_utc if _is_utc_text(at_utc) else None)

    # -- heartbeat thread ---------------------------------------------------
    def start(self) -> "RunStatusWriter":
        """Write the first document and start the independent heartbeat thread."""
        with self._lock:
            if self._thread is not None:
                return self
            self._closed.clear()
        self._write_status()
        thread = threading.Thread(target=self._heartbeat, name="bt-run-status", daemon=True)
        with self._lock:
            self._thread = thread
        thread.start()
        return self

    def _heartbeat(self) -> None:
        while not self._closed.wait(self.heartbeat_interval_s):
            self._write_status()

    def stop_heartbeat(self, timeout: float = 5.0) -> None:
        self._closed.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)

    def __enter__(self) -> "RunStatusWriter":
        return self.start()

    def __exit__(self, *_exc: Any) -> None:
        self.stop_heartbeat()

    # -- document -----------------------------------------------------------
    def _strategy_uuid_read(self) -> Optional[str]:
        with self._lock:
            if self._strategy_uuid is not None:
                return self._strategy_uuid
        try:
            from ..live_state import load_identity

            identity = load_identity(self.strategy_dir)
        except Exception:  # not initialized, mismatch, corrupt: no UUID yet
            return None
        value = getattr(identity, "strategy_uuid", None)
        if not _is_uuid4_text(value):
            return None
        with self._lock:
            if self._strategy_uuid is None:
                self._strategy_uuid = value
        return value

    def _data_document(self) -> List[Dict[str, Any]]:
        with self._lock:
            overrides = dict(self._data_states)
        count = len(self._feeds)
        indexes = sorted(set(overrides) | set(range(count)))
        document = []
        for index in indexes:
            state = overrides.get(index)
            if state is None:
                feed = self._feeds[index] if index < count else None
                state = _feed_data_state(feed)
            document.append({"index": index, "state": state})
        return document

    def _facts(self) -> RunFacts:
        if self._facts_provider is None:
            return RunFacts()
        try:
            return _validate_facts(self._facts_provider())
        except Exception:
            return RunFacts()

    def _pre_write(self) -> None:
        self._pull_stop_request()

    def _document(self) -> Dict[str, Any]:
        self._pre_write()
        facts = self._facts()
        strategy_uuid = self._strategy_uuid_read()
        datas = self._data_document()
        with self._lock:
            self._sequence += 1
            last_error = self._last_error_code
            if self._status_write_failed and last_error is None:
                last_error = "status_write_failed"
            budget = self._stop_budget
            document = {
                "schema": STATUS_SCHEMA,
                "strategy_uuid": strategy_uuid,
                "run_id": self.run_id,
                "pid": self.pid,
                "phase": self._phase,
                "updated_at_utc": _utc_text(self._clock()),
                "heartbeat_sequence": self._sequence,
                "heartbeat_interval_s": self.heartbeat_interval_s,
                "main_loop_last_progress_utc": self._loop_progress,
                "datas": datas,
                "write_block_reasons": (
                    None if facts.write_block_reasons is None else list(facts.write_block_reasons)
                ),
                "unknown_unresolved_count": facts.unknown_unresolved_count,
                "active_order_count": facts.active_order_count,
                "stop_budget_s": budget["total_seconds"],
                "budget_proven": budget["proven"],
                "stop_budget": _copy_json(budget),
                "last_error_code": last_error,
                "stop_source": self._stop_source,
                "stop_requested_at_utc": self._stop_requested_at_utc,
            }
        _validate_status_document(document)
        return document

    def _write_status(self) -> bool:
        try:
            document = self._document()
            _ensure_state_dir(self.state_dir)
            atomic_write_json(self.path, document)
        except Exception as exc:
            with self._lock:
                self._status_write_failed = True
            throttled_warning(
                _log,
                "run_status_write_failed",
                "run status write failed (%s): readers see the previous document",
                type(exc).__name__,
            )
            return False
        with self._lock:
            self._status_write_failed = False
        return True

    # -- final summary ------------------------------------------------------
    def finish(
        self,
        *,
        broker_summary: Optional[Mapping[str, Any]] = None,
        exception: Optional[BaseException] = None,
        process_identity: Optional[Mapping[str, Any]] = None,
    ) -> "RunConclusion":
        """Stop the heartbeat, write the STOPPED document and the final summary.

        Idempotent: a second call returns the first conclusion.  Never raises
        for an unreadable/unwritable summary: that conclusion carries
        ``summary_written=False`` and ``exit_code=1`` (a stop whose result is
        not on disk cannot be proven clean).
        """
        if self._finished is not None:
            return self._finished
        self.stop_heartbeat()
        self._pull_stop_request()
        with self._lock:
            self._phase = "STOPPED"
        self._write_status()
        facts = self._facts()
        with self._lock:
            stop_source = self._stop_source or "UNKNOWN"
            stop_at = self._stop_requested_at_utc
            sequence = self._sequence
            budget = json.loads(json.dumps(self._stop_budget))
            last_error = self._last_error_code
        outcome, flags = derive_outcome(broker_summary, exception=exception)
        identity = (
            dict(process_identity)
            if process_identity
            else (self._process_identity or read_process_identity(self.pid))
        )
        identity = _validated_identity(identity, self.pid)
        summary_document = {
            "schema": SUMMARY_SCHEMA,
            "strategy_uuid": self._strategy_uuid_read(),
            "run_id": self.run_id,
            "process": {
                "pid": identity["pid"],
                "create_time": identity["create_time"],
                "boot_id": identity["boot_id"],
                "command_digest": identity["command_digest"],
            },
            "outcome": outcome,
            "stop_source": stop_source,
            "stop_requested_at_utc": stop_at,
            "working_orders_unresolved": flags["working_orders_unresolved"],
            "write_in_flight_unresolved": flags["write_in_flight_unresolved"],
            "unknown_unresolved": flags["unknown_unresolved"],
            "startup_rejected": flags["startup_rejected"],
            "rejection_code": flags["rejection_code"],
        }
        exit_code = exit_code_for(outcome)
        details_document = {
            "schema": DETAILS_SCHEMA,
            "strategy_uuid": summary_document["strategy_uuid"],
            "run_id": self.run_id,
            "pid": self.pid,
            "process_identity_source": identity["source"],
            "outcome": outcome,
            "exit_code": exit_code,
            "reason": (
                flags["reason"] if flags["reason"] in _FINITE_REASONS else "unknown_outcome"
            ),
            "broker_status": flags["broker_status"],
            "broker_summary": _bounded_summary(broker_summary),
            "stop_source": stop_source,
            "stop_requested_at_utc": stop_at,
            "heartbeat_sequence": sequence,
            "heartbeat_interval_s": self.heartbeat_interval_s,
            "stop_budget": budget,
            "write_block_reasons": (
                None if facts.write_block_reasons is None else list(facts.write_block_reasons)
            ),
            "unknown_unresolved_count": facts.unknown_unresolved_count,
            "active_order_count": facts.active_order_count,
            "last_error_code": last_error,
            "exception_type": flags["exception_type"],
        }
        written = True
        write_error: Optional[str] = None
        try:
            _ensure_state_dir(self.state_dir)
            if summary_document["strategy_uuid"] is None:
                # The strict summary cannot carry a null UUID; write only the
                # details, so the runtime reports UNKNOWN (never a clean stop).
                raise RunStatusError("process_identity_unavailable", "strategy_uuid")
            atomic_write_json(self.last_run_path, summary_document)
            atomic_write_json(self.last_run_details_path, details_document)
        except RunStatusError as exc:
            written = False
            write_error = exc.code
        except Exception as exc:
            written = False
            write_error = type(exc).__name__
            if not _is_code(write_error):
                write_error = "status_write_failed"
        if not written:
            details_document["summary_written"] = False
            details_document["write_error"] = write_error
            details_document["exit_code"] = EXIT_UNEXPECTED
            try:
                _ensure_state_dir(self.state_dir)
                atomic_write_json(self.last_run_details_path, details_document)
            except Exception:
                pass
            exit_code = EXIT_UNEXPECTED
        conclusion = RunConclusion(
            outcome=outcome,
            exit_code=exit_code,
            summary_written=written,
            summary=summary_document,
            details=details_document,
        )
        self._finished = conclusion
        return conclusion


@dataclass(frozen=True)
class RunConclusion:
    """What ``finish`` wrote and which process exit code it implies."""

    outcome: str
    exit_code: int
    summary_written: bool
    summary: Dict[str, Any]
    details: Dict[str, Any]


def _feed_data_state(feed: Any) -> str:
    """LIVE/WARMUP/UNKNOWN of one data feed, from its public qualification."""
    reader = getattr(feed, "trade_qualification", None)
    if not callable(reader):
        return "UNKNOWN"
    try:
        qualification = reader()
    except Exception:
        return "UNKNOWN"
    ok = getattr(qualification, "ok", None)
    if ok is True:
        return "LIVE"
    if ok is False:
        return "WARMUP"
    return "UNKNOWN"


def _ensure_state_dir(path: str) -> None:
    """Create ``state/`` (mode 0700) when missing; never change an existing mode."""
    if os.path.isdir(path):
        return
    os.makedirs(path, mode=0o700, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:  # pragma: no cover - permission edge
        pass


# ---------------------------------------------------------------------------
# outcome and exit code (B3)
# ---------------------------------------------------------------------------
_FINITE_REASONS = frozenset(
    {
        "stopped_clean",
        "stopped_with_working_orders",
        "stopped_with_write_in_flight",
        "not_started_no_write",
        "startup_rejected",
        "stop_requested_during_start",
        "unexpected_exception",
        "summary_unavailable",
        "unknown_outcome",
    }
)


def derive_outcome(
    broker_summary: Optional[Mapping[str, Any]],
    *,
    exception: Optional[BaseException] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Map a stop to the runtime's outcome vocabulary and its own flags.

    The Broker's ``get_shutdown_summary()["status"]`` is authoritative for what
    the stop proved; an exception only decides between a refusal (``BLOCKED``,
    with a finite rejection code), a requested mid-start abort (the summary
    decides; a committed/unknown settlement write is ``UNKNOWN``) and a crash.
    An absent or unfamiliar summary is ``UNKNOWN`` (never a clean stop).
    """
    summary = broker_summary if isinstance(broker_summary, Mapping) else {}
    raw_status = summary.get("status")
    broker_status = raw_status if _is_status_token(raw_status) else None
    flags: Dict[str, Any] = {
        "reason": "unknown_outcome",
        "broker_status": broker_status,
        "startup_rejected": False,
        "rejection_code": None,
        "working_orders_unresolved": False,
        "write_in_flight_unresolved": False,
        "unknown_unresolved": True,
        "exception_type": None,
    }
    if exception is not None:
        code = getattr(exception, "code", None)
        name = type(exception).__name__
        if re.match(r"^[A-Za-z_][A-Za-z0-9_.]{0,63}$", name):
            flags["exception_type"] = name
        requested_stop = code == "stop_requested"
        if not requested_stop and _is_code(code) and isinstance(exception, RuntimeError):
            # A refused precondition (DirectModeError/LiveStateError): a finite
            # rejection code is the only thing that can support BLOCKED.
            if hasattr(exception, "detail"):
                flags.update(
                    reason="startup_rejected",
                    startup_rejected=True,
                    rejection_code=code,
                    unknown_unresolved=False,
                )
                return "BLOCKED", flags
        if not requested_stop:
            flags.update(reason="unexpected_exception", unknown_unresolved=True)
            return "CRASHED", flags
        # A requested stop aborted the start: the Broker's own summary says
        # whether anything was written; never assume a clean NOT_STARTED.
    if broker_status is None:
        return "UNKNOWN", flags
    unresolved = summary.get("unresolved_working_orders")
    if type(unresolved) is int and unresolved > 0:
        flags["working_orders_unresolved"] = True
    if broker_status == "STOPPED":
        flags["unknown_unresolved"] = False
        if flags["working_orders_unresolved"]:
            flags["reason"] = "stopped_with_working_orders"
            return "STOPPED_WITH_WORKING_ORDERS", flags
        flags["reason"] = "stopped_clean"
        return "STOPPED", flags
    if broker_status == "NOT_STARTED":
        # A provable no-write start abort: nothing was cancelled or written.
        flags["unknown_unresolved"] = False
        flags["reason"] = "not_started_no_write"
        return "STOPPED", flags
    if broker_status == "STOPPED_WITH_WORKING_ORDERS":
        flags["working_orders_unresolved"] = True
        flags["unknown_unresolved"] = False
        flags["reason"] = "stopped_with_working_orders"
        return "STOPPED_WITH_WORKING_ORDERS", flags
    if broker_status == "STOPPED_WITH_WRITE_IN_FLIGHT":
        flags["write_in_flight_unresolved"] = True
        flags["unknown_unresolved"] = False
        flags["reason"] = "stopped_with_write_in_flight"
        return "STOPPED_WITH_WRITE_IN_FLIGHT", flags
    if broker_status == "UNKNOWN":
        flags["reason"] = (
            "stop_requested_during_start"
            if summary.get("reason") == "stop_requested_during_start"
            else "unknown_outcome"
        )
        return "UNKNOWN", flags
    if broker_status == "BLOCKED":
        # A status token alone is not a verifiable rejection record
        # (INV66-04): only an exception carrying a finite rejection code (the
        # branch above) proves BLOCKED. Without it the outcome stays UNKNOWN
        # and the process exits 1, matching the runtime's
        # summarize_stop_state instead of disagreeing with it.
        flags["reason"] = "blocked_unproven"
        return "UNKNOWN", flags
    return "UNKNOWN", flags


def exit_code_for(outcome: str) -> int:
    """The process exit code of one outcome (unlisted values fail closed with 1)."""
    return EXIT_CODES.get(outcome, EXIT_UNEXPECTED)


# ---------------------------------------------------------------------------
# document validation and readers
# ---------------------------------------------------------------------------
def _validate_status_document(document: Any) -> Dict[str, Any]:
    """Enforce the strict whitelist and every finite value of a status document."""
    if type(document) is not dict:
        raise RunStatusError("status_document_invalid", "type")
    keys = set(document)
    if keys != STATUS_KEYS:
        missing = sorted(STATUS_KEYS - keys)
        extra = sorted(keys - STATUS_KEYS)
        raise RunStatusError(
            "status_document_invalid",
            "missing={} extra={}".format(",".join(missing), ",".join(extra)),
        )
    for key in keys:
        lowered = key.lower()
        if any(marker in lowered for marker in _SECRET_MARKERS):
            raise RunStatusError("status_document_invalid", "secret_key")
    if document["schema"] != STATUS_SCHEMA:
        raise RunStatusError("status_document_invalid", "schema")
    uuid_text = document["strategy_uuid"]
    if uuid_text is not None and not _is_uuid4_text(uuid_text):
        raise RunStatusError("status_document_invalid", "strategy_uuid")
    _canonical_uuid(document["run_id"])
    if type(document["pid"]) is not int or document["pid"] <= 0:
        raise RunStatusError("status_document_invalid", "pid")
    if document["phase"] not in PHASES:
        raise RunStatusError("status_document_invalid", "phase")
    if not _is_utc_text(document["updated_at_utc"]):
        raise RunStatusError("status_document_invalid", "updated_at_utc")
    if type(document["heartbeat_sequence"]) is not int or document["heartbeat_sequence"] < 1:
        raise RunStatusError("status_document_invalid", "heartbeat_sequence")
    interval = document["heartbeat_interval_s"]
    if (
        not _is_number(interval)
        or not MIN_HEARTBEAT_INTERVAL_S <= float(interval) <= MAX_HEARTBEAT_INTERVAL_S
    ):
        raise RunStatusError("status_document_invalid", "heartbeat_interval_s")
    progress = document["main_loop_last_progress_utc"]
    if progress is not None and not _is_utc_text(progress):
        raise RunStatusError("status_document_invalid", "main_loop_last_progress_utc")
    datas = document["datas"]
    if type(datas) is not list or len(datas) > 256:
        raise RunStatusError("status_document_invalid", "datas")
    seen = set()
    for entry in datas:
        if type(entry) is not dict or set(entry) != DATA_KEYS:
            raise RunStatusError("status_document_invalid", "datas")
        if type(entry["index"]) is not int or entry["index"] < 0 or entry["index"] in seen:
            raise RunStatusError("status_document_invalid", "datas")
        seen.add(entry["index"])
        if entry["state"] not in DATA_STATES:
            raise RunStatusError("status_document_invalid", "datas")
    reasons = document["write_block_reasons"]
    if reasons is not None:
        if type(reasons) is not list or any(not _is_code(item) for item in reasons):
            raise RunStatusError("status_document_invalid", "write_block_reasons")
    for name in ("unknown_unresolved_count", "active_order_count"):
        value = document[name]
        if value is not None and (type(value) is not int or value < 0):
            raise RunStatusError("status_document_invalid", name)
    budget_s = document["stop_budget_s"]
    if budget_s is not None and _finite_non_negative(budget_s) is None:
        raise RunStatusError("status_document_invalid", "stop_budget_s")
    if type(document["budget_proven"]) is not bool:
        raise RunStatusError("status_document_invalid", "budget_proven")
    budget = _validate_budget(document["stop_budget"])
    if budget["total_seconds"] != budget_s or budget["proven"] != document["budget_proven"]:
        raise RunStatusError("status_document_invalid", "stop_budget")
    error = document["last_error_code"]
    if error is not None and not _is_code(error):
        raise RunStatusError("status_document_invalid", "last_error_code")
    source = document["stop_source"]
    if source is not None and source not in STOP_SOURCES:
        raise RunStatusError("status_document_invalid", "stop_source")
    stop_at = document["stop_requested_at_utc"]
    if stop_at is not None and not _is_utc_text(stop_at):
        raise RunStatusError("status_document_invalid", "stop_requested_at_utc")
    return document


def read_run_status(path: Any) -> Dict[str, Any]:
    """Read and validate one status document (strict JSON, strict whitelist)."""
    document = read_json(os.fspath(path))
    return _validate_status_document(document)


def _validated_identity(identity: Mapping[str, Any], pid: int) -> Dict[str, Any]:
    def text(value: Any) -> str:
        if type(value) is not str or not value or len(value) > 128:
            return "unavailable"
        if any(ord(char) < 0x20 for char in value):
            return "unavailable"
        return value

    return {
        "pid": pid,
        "create_time": text(identity.get("create_time")),
        "boot_id": text(identity.get("boot_id")),
        "command_digest": text(identity.get("command_digest")),
        "source": text(identity.get("source")) if identity.get("source") else "unavailable",
    }


def _bounded_summary(value: Any, depth: int = 0, budget: Optional[List[int]] = None) -> Any:
    """A JSON-safe, size-bounded copy of the Broker summary; never raises.

    Secret-looking keys are dropped rather than the whole evidence, strings are
    capped at 128 characters and the item budget at 64.
    """
    if budget is None:
        budget = [0]
    budget[0] += 1
    if budget[0] > 64 or depth > 3:
        return None
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        return value
    if type(value) is float:
        return value if math.isfinite(value) else None
    if type(value) is str:
        return value if len(value) <= 128 else None
    if isinstance(value, Mapping):
        result: Dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str or not _is_code(key):
                continue
            if any(marker in key.lower() for marker in _SECRET_MARKERS):
                continue
            result[key] = _bounded_summary(item, depth + 1, budget)
        return result
    if isinstance(value, (list, tuple)):
        return [_bounded_summary(item, depth + 1, budget) for item in list(value)[:16]]
    return None

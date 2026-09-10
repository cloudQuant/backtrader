"""Credential-safe, hash-bound evidence for the Iteration 22 example."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import threading
import time
from collections import deque
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

SENSITIVE_PARTS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "credential",
    "auth_code",
    "authcode",
    "api_key",
    "apikey",
    "api_secret",
    "apisecret",
    "investor_id",
    "investorid",
    "user_id",
    "userid",
    "account_id",
    "accountid",
    "app_id",
    "appid",
    "access_key",
    "accesskey",
    "private_key",
    "privatekey",
)


class EvidenceWriteError(RuntimeError):
    """Raised after the evidence lane has latched a durable failure."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_tree_hash(paths: Iterable[Path | str]) -> str:
    records = []
    for raw_path in sorted((Path(value) for value in paths), key=lambda item: str(item)):
        records.append({"name": raw_path.name, "sha256": sha256_file(raw_path)})
    return sha256_json(records)


def account_fingerprint(broker_id: str, investor_id: str) -> str:
    if not broker_id or not investor_id:
        return ""
    return "acct_" + sha256_bytes(f"{broker_id}:{investor_id}".encode("utf-8"))[:16]


def _sensitive_key(key: Any) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_PARTS)


def redact(value: Any, *, secret_values: Iterable[str] = ()) -> Any:
    """Recursively redact credential fields and known sentinel values."""

    secrets = tuple(str(item) for item in secret_values if str(item))
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Mapping):
        return {
            str(key): "***" if _sensitive_key(key) else redact(item, secret_values=secrets)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact(item, secret_values=secrets) for item in value]
    if isinstance(value, BaseException):
        value = f"{type(value).__name__}: {' '.join(map(str, value.args))}"
    if isinstance(value, str):
        result = value
        for secret in secrets:
            result = result.replace(secret, "***")
        return result
    return value


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        _fsync_directory(path.parent)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            if not text.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        _fsync_directory(path.parent)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class EvidenceWriter:
    """Write the fixed evidence set with bounded, priority-aware persistence.

    High-value execution events are written and fsynced before ``append``
    returns.  High-rate quote/bar/signal records use one bounded background
    lane and are fsynced in batches.  Any queue overflow or writer failure is
    latched permanently for the run and closes opening admission; it is never
    represented as successful evidence.
    """

    STREAMS = ("quotes", "bars", "signals", "orders", "trades", "risk_events")
    CRITICAL_STREAMS = frozenset({"orders", "trades", "risk_events"})

    def __init__(
        self,
        directory: Path | str,
        *,
        secret_values: Iterable[str] = (),
        min_free_bytes: int = 1_000_000_000,
        rotate_bytes: int = 100_000_000,
        audit_queue_limit: int = 10_000,
        audit_batch_size: int = 256,
        audit_flush_interval: float = 0.05,
        max_rotated_files_per_stream: int = 128,
    ) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.secret_values = tuple(str(item) for item in secret_values if str(item))
        self.min_free_bytes = int(min_free_bytes)
        self.rotate_bytes = int(rotate_bytes)
        if self.rotate_bytes <= 0:
            raise ValueError("rotate_bytes must be positive")
        self.audit_queue_limit = int(audit_queue_limit)
        self.audit_batch_size = int(audit_batch_size)
        self.audit_flush_interval = float(audit_flush_interval)
        self.max_rotated_files_per_stream = int(max_rotated_files_per_stream)
        if self.audit_queue_limit <= 0:
            raise ValueError("audit_queue_limit must be positive")
        if self.audit_batch_size <= 0:
            raise ValueError("audit_batch_size must be positive")
        if self.audit_flush_interval <= 0:
            raise ValueError("audit_flush_interval must be positive")
        if self.max_rotated_files_per_stream <= 0:
            raise ValueError("max_rotated_files_per_stream must be positive")
        self.opening_allowed = True
        self.failure_reason = ""
        self.counts = dict.fromkeys(self.STREAMS, 0)
        self.enqueued_counts = dict.fromkeys(self.STREAMS, 0)
        self.dropped_counts = dict.fromkeys(self.STREAMS, 0)
        self.rotation_counts = dict.fromkeys(self.STREAMS, 0)
        self.max_pending_counts = dict.fromkeys(self.STREAMS, 0)
        self.max_pending_total = 0
        self._io_lock = threading.RLock()
        self._condition = threading.Condition(threading.RLock())
        self._audit_queue: deque[tuple[str, bytes]] = deque()
        self._pending_counts = dict.fromkeys(self.STREAMS, 0)
        self._writer_busy = False
        self._stop_requested = False
        self._closed = False
        self._last_disk_check_monotonic = 0.0
        self._last_disk_check_ok = False
        self._check_disk()
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="iter22-evidence-writer",
            daemon=True,
        )
        self._writer_thread.start()

    def _latch_failure(self, reason: str) -> None:
        with self._condition:
            self.opening_allowed = False
            if not self.failure_reason:
                self.failure_reason = str(reason)
            self._condition.notify_all()

    def _check_disk(self) -> bool:
        now = time.monotonic()
        if now - self._last_disk_check_monotonic < 1.0:
            return self._last_disk_check_ok
        try:
            free = shutil.disk_usage(self.directory).free
        except OSError:
            self._last_disk_check_monotonic = now
            self._last_disk_check_ok = False
            self._latch_failure("disk_status_unavailable")
            return False
        self._last_disk_check_monotonic = now
        self._last_disk_check_ok = free >= self.min_free_bytes
        if free < self.min_free_bytes:
            self._latch_failure("disk_free_below_limit")
            return False
        return True

    def _rotate_if_needed(self, stream: str, path: Path, incoming_bytes: int) -> None:
        try:
            current_size = path.stat().st_size
        except FileNotFoundError:
            return
        if current_size == 0 or current_size + incoming_bytes <= self.rotate_bytes:
            return
        index = self.rotation_counts[stream] + 1
        rotated = path.with_name(f"{path.name}.{index:04d}")
        while rotated.exists():
            index += 1
            rotated = path.with_name(f"{path.name}.{index:04d}")
        if index > self.max_rotated_files_per_stream:
            self._latch_failure("evidence_rotation_limit")
            raise EvidenceWriteError("evidence rotation limit reached")
        # The active file may contain a just-written normal-lane batch.  Sync
        # it before rename so the rotation boundary cannot acknowledge data
        # that only exists in the page cache.
        with path.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(path, rotated)
        _fsync_directory(self.directory)
        self.rotation_counts[stream] = index

    def _write_encoded(self, stream: str, encoded: bytes, *, durable: bool) -> None:
        path = self.directory / f"{stream}.jsonl"
        with self._io_lock:
            self._rotate_if_needed(stream, path, len(encoded))
            with path.open("ab") as handle:
                handle.write(encoded)
                handle.flush()
                if durable:
                    os.fsync(handle.fileno())

    def _sync_streams(self, streams: set[str]) -> None:
        with self._io_lock:
            for stream in streams:
                path = self.directory / f"{stream}.jsonl"
                if not path.exists():
                    continue
                with path.open("rb") as handle:
                    os.fsync(handle.fileno())

    def _writer_loop(self) -> None:
        while True:
            with self._condition:
                if not self._audit_queue and not self._stop_requested:
                    self._condition.wait(self.audit_flush_interval)
                if not self._audit_queue and self._stop_requested:
                    self._closed = True
                    self._condition.notify_all()
                    return
                batch = []
                while self._audit_queue and len(batch) < self.audit_batch_size:
                    item = self._audit_queue.popleft()
                    self._pending_counts[item[0]] -= 1
                    batch.append(item)
                self._writer_busy = bool(batch)

            written: list[str] = []
            try:
                for stream, encoded in batch:
                    self._write_encoded(stream, encoded, durable=False)
                    written.append(stream)
                self._sync_streams(set(written))
            except Exception:
                with self._condition:
                    # The exact prefix already written before an I/O error is
                    # unknowable without a successful fsync.  Count the whole
                    # batch and pending lane as unacknowledged and stop using
                    # it; never retry and risk duplicate audit rows.
                    for stream, _encoded in batch:
                        self.dropped_counts[stream] += 1
                    while self._audit_queue:
                        stream, _encoded = self._audit_queue.popleft()
                        self._pending_counts[stream] -= 1
                        self.dropped_counts[stream] += 1
                    self._writer_busy = False
                    self._stop_requested = True
                    self._latch_failure("evidence_write_failed")
                continue

            with self._condition:
                for stream in written:
                    self.counts[stream] += 1
                self._writer_busy = False
                self._condition.notify_all()

    def write_json(self, name: str, payload: Any) -> Path:
        safe = redact(payload, secret_values=self.secret_values)
        path = self.directory / name
        try:
            with self._io_lock:
                atomic_write_json(path, safe)
                if name == "daily_report.json":
                    rows = []
                    if isinstance(safe, Mapping):
                        for key in (
                            "mode",
                            "purpose",
                            "trading_day",
                            "status",
                            "g3_gate_status",
                            "g4_gate_status",
                            "research_status",
                        ):
                            if key in safe:
                                value = str(safe[key]).replace("|", "\\|").replace("\n", " ")
                                rows.append(f"| {key} | {value} |")
                    markdown = [
                        "# Iteration 22 Daily Report",
                        "",
                        "| Field | Value |",
                        "| --- | --- |",
                        *rows,
                        "",
                        "## Machine-readable payload",
                        "",
                        "```json",
                        json.dumps(safe, ensure_ascii=False, indent=2, sort_keys=True, default=str),
                        "```",
                    ]
                    atomic_write_text(self.directory / "daily_report.md", "\n".join(markdown))
        except Exception:
            self._latch_failure("evidence_write_failed")
            raise
        return path

    def append(self, stream: str, payload: Any) -> Path:
        if stream not in self.STREAMS:
            raise ValueError(f"unsupported evidence stream {stream!r}")
        if self._closed or self._stop_requested:
            self._latch_failure("evidence_writer_closed")
            raise EvidenceWriteError("evidence writer is closed")
        capacity_ok = self._check_disk()
        if not capacity_ok and stream not in self.CRITICAL_STREAMS:
            raise EvidenceWriteError(self.failure_reason or "evidence capacity unavailable")
        path = self.directory / f"{stream}.jsonl"
        safe = redact(payload, secret_values=self.secret_values)
        encoded = (canonical_json(safe) + "\n").encode("utf-8")

        if stream not in self.CRITICAL_STREAMS:
            with self._condition:
                if len(self._audit_queue) >= self.audit_queue_limit:
                    self.dropped_counts[stream] += 1
                    self._latch_failure("audit_queue_full")
                    raise EvidenceWriteError("bounded audit queue is full")
                self._audit_queue.append((stream, encoded))
                self._pending_counts[stream] += 1
                self.enqueued_counts[stream] += 1
                self.max_pending_counts[stream] = max(
                    self.max_pending_counts[stream], self._pending_counts[stream]
                )
                self.max_pending_total = max(self.max_pending_total, len(self._audit_queue))
                self._condition.notify()
            return path

        try:
            self._write_encoded(stream, encoded, durable=True)
            with self._condition:
                self.counts[stream] += 1
                self.enqueued_counts[stream] += 1
        except Exception:
            with self._condition:
                self.dropped_counts[stream] += 1
            self._latch_failure("evidence_write_failed")
            raise
        return path

    @property
    def pending_counts(self) -> dict[str, int]:
        with self._condition:
            return dict(self._pending_counts)

    def drain(self, timeout: float = 30.0) -> bool:
        """Wait until every accepted normal-lane record is fsynced."""
        deadline = time.monotonic() + max(float(timeout), 0.0)
        with self._condition:
            while self._audit_queue or self._writer_busy:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._latch_failure("evidence_drain_timeout")
                    return False
                self._condition.wait(min(remaining, 0.25))
            return True

    def close(self, timeout: float = 30.0) -> bool:
        drained = self.drain(timeout)
        with self._condition:
            self._stop_requested = True
            self._condition.notify_all()
        remaining = max(float(timeout), 0.0)
        self._writer_thread.join(remaining)
        if self._writer_thread.is_alive():
            self._latch_failure("evidence_writer_shutdown_timeout")
            return False
        return drained and not any(self.dropped_counts.values())

    def manifest(
        self,
        *,
        run_id: str,
        purpose: str,
        mode: str,
        environment: str,
        candidate_id: str,
        config_hash: str,
        code_hash: str,
        data_hash: str,
        account_id_hash: str,
        instrument: str,
        trading_day: str,
        started_at_utc: str,
        fee_source: str,
        hypothetical_fills: bool,
    ) -> dict[str, Any]:
        payload = {
            "schema_version": "iter22.manifest.v1",
            "iteration": 22,
            "run_id": run_id,
            "purpose": purpose,
            "mode": mode,
            "environment": environment,
            "candidate_id": candidate_id,
            "config_hash": config_hash,
            "code_hash": code_hash,
            "data_hash": data_hash,
            "account_fingerprint": account_id_hash or None,
            "instrument_id": instrument or None,
            "trading_day": trading_day or None,
            "started_at_utc": started_at_utc,
            "fee_source": fee_source or None,
            "execution_basis": "hypothetical_next_bar" if hypothetical_fills else "none_or_simnow",
            "hypothetical_fills": bool(hypothetical_fills),
            "research_status": "RESEARCH_NOT_ESTABLISHED",
            "runtime": {
                "python": sys.version.split()[0],
                "executable": sys.executable,
                "platform": platform.platform(),
                "architecture": platform.machine(),
            },
            "exit_status": "RUNNING",
        }
        self.write_json("manifest.json", payload)
        return payload

    def finalize_manifest(self, manifest: dict[str, Any], exit_status: str) -> None:
        healthy = self.close()
        updated = dict(manifest)
        evidence_complete = bool(healthy and self.opening_allowed)
        updated["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
        updated["exit_status"] = exit_status if evidence_complete else "FAIL_EVIDENCE_INCOMPLETE"
        if not evidence_complete:
            for gate_name in ("g3_gate_status", "g4_gate_status"):
                if str(updated.get(gate_name) or "").startswith("PASS"):
                    updated[gate_name] = "INCOMPLETE"
            observation = updated.get("observation_evidence")
            if isinstance(observation, Mapping):
                observation = dict(observation)
                if str(observation.get("g3_gate_status") or "").startswith("PASS"):
                    observation["g3_gate_status"] = "INCOMPLETE"
                checks = observation.get("g3_checks")
                if isinstance(checks, Mapping):
                    checks = dict(checks)
                    checks["evidence_complete"] = False
                    observation["g3_checks"] = checks
                updated["observation_evidence"] = observation
        updated["evidence_counts"] = dict(self.counts)
        updated["evidence_enqueued_counts"] = dict(self.enqueued_counts)
        updated["evidence_dropped_counts"] = dict(self.dropped_counts)
        updated["evidence_pending_counts"] = self.pending_counts
        updated["evidence_max_pending_counts"] = dict(self.max_pending_counts)
        updated["evidence_max_pending_total"] = self.max_pending_total
        updated["evidence_rotations"] = dict(self.rotation_counts)
        updated["evidence_health"] = {
            "complete": evidence_complete,
            "failure_reason": self.failure_reason or None,
            "queue_limit": self.audit_queue_limit,
        }
        manifest.clear()
        manifest.update(updated)
        self.write_json("manifest.json", updated)


BUSINESS_SUMMARY_VOLATILE_FIELDS = frozenset(
    {
        "run_id",
        "started_at_utc",
        "ended_at_utc",
        "evidence_directory",
        "business_summary_hash",
        # TradeLogger is retained in the emitted report as a complete generic
        # runtime envelope.  It has its own timestamps, run id, monitoring and
        # callback counts, none of which are replay-business inputs.
        "trade_logger",
    }
)


def business_summary_hash(report: Mapping[str, Any]) -> str:
    """Hash the deterministic SA business summary, not runtime telemetry.

    The complete ``trade_logger`` payload remains available to operators in
    the report.  It is intentionally omitted from this hash because its
    lifecycle timestamps and observer telemetry change for equivalent replay
    runs.  Excluding an already-assigned hash also makes this function
    idempotent when callers validate a persisted report.
    """

    normalized = {
        key: value for key, value in report.items() if key not in BUSINESS_SUMMARY_VOLATILE_FIELDS
    }
    return sha256_json(normalized)

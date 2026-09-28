"""The daily cleaning pipeline: pull -> verify -> merge -> K-line -> reclaim.

Ordering is a safety decision.  Reclamation runs *after* the K lines are built,
not right after the merge, so a failure while building bars leaves the remote
copy in place and the day can be retried.  Every stage writes its outcome to the
manifest before the next one starts, so an interrupted run resumes instead of
repeating (or skipping) work.

The venue naming rules are injected as a ``classifier``; this module must stay
free of CTP-specific imports.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from bt_api_ctp.cleaner.config import CleanerConfig
from bt_api_ctp.cleaner.contracts import Classifier
from bt_api_ctp.cleaner.kline.build import DayBuildReport, build_day
from bt_api_ctp.cleaner.manifest import (
    STATUS_DELETED,
    STATUS_DISCOVERED,
    STATUS_FAILED,
    STATUS_MERGED,
    STATUS_PULLED,
    STATUS_VERIFIED,
    Manifest,
)
from bt_api_ctp.cleaner.merge import DayMergeReport, drop_staging_day, merge_day
from bt_api_ctp.cleaner.pull import PullBackend, PullError, create_backend
from bt_api_ctp.cleaner.reclaim import ReclaimReport, execute_reclaim
from bt_api_ctp.cleaner.verify import verify_staged_day

_logger = logging.getLogger(__name__)

try:  # pragma: no cover - Windows has no fcntl
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class HostRunReport:
    """What one host contributed to this run."""

    name: str
    backend: str
    days_seen: list[str] = field(default_factory=list)
    #: Complete days that still needed pulling.
    days_ready: list[str] = field(default_factory=list)
    #: Days without ``report.json`` -- collection had not finished.
    days_incomplete: list[str] = field(default_factory=list)
    #: Days already merged or reclaimed by an earlier run.
    days_already_done: list[str] = field(default_factory=list)
    days_pulled: list[str] = field(default_factory=list)
    verify_failures: list[str] = field(default_factory=list)
    fetch_files: int = 0
    fetch_bytes: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class PipelineReport:
    """Result of one pipeline invocation, ready for the JSON report."""

    started_at: str
    dry_run: bool = False
    finished_at: str = ""
    hosts: dict[str, HostRunReport] = field(default_factory=dict)
    merge: dict[str, DayMergeReport] = field(default_factory=dict)
    kline: dict[str, DayBuildReport] = field(default_factory=dict)
    reclaim: ReclaimReport = field(default_factory=ReclaimReport)


@contextmanager
def process_lock(path: Path | str) -> Iterator[None]:
    """Refuse a second concurrent cleaner run on the same data root."""
    if fcntl is None:  # pragma: no cover - Windows fallback
        yield
        return
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError(f"another cleaner run already holds {lock_path}") from error
        try:
            handle.write(f"{os.getpid()}\n")
            handle.flush()
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _run_lock(config: CleanerConfig, dry_run: bool) -> Iterator[None]:
    """A dry run mutates nothing, so it does not need (or create) the lock."""
    if dry_run:
        yield
        return
    with process_lock(config.lock_path):
        yield


def _open_backends(config: CleanerConfig) -> list[PullBackend]:
    return [create_backend(host) for host in config.hosts]


def _discover(
    manifest: Manifest,
    backends: list[PullBackend],
    *,
    only_day: str | None,
) -> dict[str, HostRunReport]:
    reports: dict[str, HostRunReport] = {}
    for backend in backends:
        host_report = HostRunReport(name=backend.name, backend=backend.backend)
        reports[backend.name] = host_report
        try:
            days = backend.list_days()
        except PullError as error:
            host_report.errors.append(str(error))
            continue
        if only_day is not None:
            days = [day for day in days if day == only_day]
        host_report.days_seen = days
        for day in days:
            status = manifest.status(backend.name, day)
            if status in (STATUS_MERGED, STATUS_DELETED):
                host_report.days_already_done.append(day)
                continue
            try:
                if not backend.has_report(day):
                    host_report.days_incomplete.append(day)
                    continue
            except PullError as error:
                host_report.errors.append(f"{day}: {error}")
                continue
            host_report.days_ready.append(day)
    return reports


def _pull_and_verify(
    config: CleanerConfig,
    manifest: Manifest,
    backends: list[PullBackend],
    reports: dict[str, HostRunReport],
    *,
    dry_run: bool,
) -> None:
    if dry_run:
        return
    for backend in backends:
        host_report = reports[backend.name]
        staging_host = Path(config.staging_root) / backend.name
        for day in host_report.days_ready:
            try:
                manifest.mark(backend.name, day, STATUS_DISCOVERED)
                remote_files = backend.list_day_files(day)
                fetch = backend.fetch_day(day, staging_host)
                host_report.fetch_files += fetch.files
                host_report.fetch_bytes += fetch.bytes
                manifest.mark(backend.name, day, STATUS_PULLED)

                verification = verify_staged_day(remote_files, staging_host, day)
                if not verification.ok:
                    message = "; ".join(verification.problems[:3])
                    manifest.mark(backend.name, day, STATUS_FAILED, error=message)
                    host_report.verify_failures.append(f"{day}: {message}")
                    continue
                manifest.mark(backend.name, day, STATUS_VERIFIED, files=verification.files)
                host_report.days_pulled.append(day)
            except Exception as error:
                _logger.exception("pull failed for %s/%s", backend.name, day)
                manifest.mark(backend.name, day, STATUS_FAILED, error=str(error))
                host_report.errors.append(f"{day}: {error}")


def _verified_days(manifest: Manifest, backends: list[PullBackend]) -> list[str]:
    return sorted(
        {
            day
            for backend in backends
            for day in manifest.days(backend.name)
            if manifest.status(backend.name, day) == STATUS_VERIFIED
        }
    )


def _verified_hosts(manifest: Manifest, backends: list[PullBackend], day: str) -> list[str]:
    """Hosts whose copy of ``day`` verified -- the only ones safe to merge."""
    return [
        backend.name
        for backend in backends
        if manifest.status(backend.name, day) == STATUS_VERIFIED
    ]


def _merge_days(
    config: CleanerConfig,
    manifest: Manifest,
    backends: list[PullBackend],
    days: list[str],
    *,
    dry_run: bool,
) -> dict[str, DayMergeReport]:
    merged: dict[str, DayMergeReport] = {}
    for day in days:
        hosts = _verified_hosts(manifest, backends, day)
        if not hosts and not dry_run:
            continue
        if dry_run:
            merged[day] = DayMergeReport(trading_day=day)
            continue
        report = merge_day(config.tick_root, config.staging_root, day, hosts=hosts)
        merged[day] = report
        for name in hosts:
            manifest.mark(name, day, STATUS_MERGED)
        drop_staging_day(config.staging_root, day, hosts=hosts)
    return merged


def _kline_days(
    config: CleanerConfig,
    manifest: Manifest,
    classifier: Classifier,
    days: list[str],
    *,
    dry_run: bool,
) -> dict[str, DayBuildReport]:
    built: dict[str, DayBuildReport] = {}
    for day in days:
        if dry_run:
            continue
        report = build_day(
            config.tick_root,
            config.kline_root,
            day,
            classifier=classifier,
            periods=config.periods,
            include_options=config.include_options,
        )
        built[day] = report
        manifest.mark_klined(day)
    return built


def _reclaim_all(
    config: CleanerConfig, manifest: Manifest, backends: list[PullBackend], *, dry_run: bool
) -> ReclaimReport:
    combined = ReclaimReport(dry_run=dry_run)
    for backend in backends:
        partial = execute_reclaim(
            manifest,
            backend,
            enabled=config.delete_remote_after_verify,
            dry_run=dry_run,
        )
        combined.decisions.extend(partial.decisions)
        combined.deleted.extend(partial.deleted)
        combined.failed.extend(partial.failed)
    return combined


def run(
    config: CleanerConfig,
    *,
    classifier: Classifier,
    only_day: str | None = None,
    dry_run: bool = False,
) -> PipelineReport:
    """Full daily run: pull, verify, merge, build K lines, then reclaim."""
    report = PipelineReport(started_at=_now(), dry_run=dry_run)
    with _run_lock(config, dry_run):
        backends = _open_backends(config)
        try:
            manifest = Manifest(config.manifest_path)
            report.hosts = _discover(manifest, backends, only_day=only_day)
            _pull_and_verify(config, manifest, backends, report.hosts, dry_run=dry_run)
            report.merge = _merge_days(
                config, manifest, backends, _verified_days(manifest, backends), dry_run=dry_run
            )
            report.kline = _kline_days(
                config, manifest, classifier, manifest.days_needing_kline(), dry_run=dry_run
            )
            report.reclaim = _reclaim_all(config, manifest, backends, dry_run=dry_run)
        finally:
            for backend in backends:
                backend.close()
    report.finished_at = _now()
    return report


def pull_only(
    config: CleanerConfig, *, only_day: str | None = None, dry_run: bool = False
) -> PipelineReport:
    """Pull and verify only; merge and reclaim stay untouched."""
    report = PipelineReport(started_at=_now(), dry_run=dry_run)
    with _run_lock(config, dry_run):
        backends = _open_backends(config)
        try:
            manifest = Manifest(config.manifest_path)
            report.hosts = _discover(manifest, backends, only_day=only_day)
            _pull_and_verify(config, manifest, backends, report.hosts, dry_run=dry_run)
        finally:
            for backend in backends:
                backend.close()
    report.finished_at = _now()
    return report


def merge_only(
    config: CleanerConfig, *, classifier: Classifier, dry_run: bool = False
) -> PipelineReport:
    """Merge every verified day, then build the K lines that are missing."""
    report = PipelineReport(started_at=_now(), dry_run=dry_run)
    with _run_lock(config, dry_run):
        backends = _open_backends(config)
        try:
            manifest = Manifest(config.manifest_path)
            report.merge = _merge_days(
                config, manifest, backends, _verified_days(manifest, backends), dry_run=dry_run
            )
            report.kline = _kline_days(
                config, manifest, classifier, manifest.days_needing_kline(), dry_run=dry_run
            )
        finally:
            for backend in backends:
                backend.close()
    report.finished_at = _now()
    return report


def kline_only(
    config: CleanerConfig,
    *,
    classifier: Classifier,
    days: list[str] | None = None,
    backfill: bool = False,
    dry_run: bool = False,
) -> PipelineReport:
    """Build K lines for explicit days, pending days, or every tick day."""
    report = PipelineReport(started_at=_now(), dry_run=dry_run)
    with _run_lock(config, dry_run):
        manifest = Manifest(config.manifest_path)
        if backfill:
            tick_root = Path(config.tick_root)
            selected = (
                sorted(
                    path.name
                    for path in tick_root.iterdir()
                    if path.is_dir() and path.name.isdigit() and len(path.name) == 8
                )
                if tick_root.is_dir()
                else []
            )
        elif days is not None:
            selected = sorted(days)
        else:
            selected = manifest.days_needing_kline()
        report.kline = _kline_days(config, manifest, classifier, selected, dry_run=dry_run)
    report.finished_at = _now()
    return report


__all__ = [
    "HostRunReport",
    "PipelineReport",
    "kline_only",
    "merge_only",
    "process_lock",
    "pull_only",
    "run",
]

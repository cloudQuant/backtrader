"""Decide and execute remote reclamation under triple protection.

Remote data is deleted only when *all three* hold, which is the operational
reading of 迭代06 需求 3 ("确认已经拉取过数据的服务器，可以删除……如果没拉取之前，不要删除"):

1. the manifest says the day is ``merged`` (pulled, verified, merged);
2. the config enables reclamation (``delete_remote_after_verify``);
3. the target is a well-formed trading-day path under ``remote_data_root``.

A failed delete leaves the manifest at ``merged`` so the next run retries it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from bt_api_ctp.cleaner.manifest import STATUS_DELETED, STATUS_MERGED, Manifest
from bt_api_ctp.cleaner.pull.backend import PullBackend, is_day_name

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReclaimDecision:
    """Whether one host/day may be deleted, and why (for the dry-run report)."""

    host: str
    day: str
    delete: bool
    reason: str
    path: str = ""


@dataclass
class ReclaimReport:
    """What the reclaim stage decided and did."""

    decisions: list[ReclaimDecision] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def planned(self) -> list[str]:
        return [f"{item.host}/{item.day}" for item in self.decisions if item.delete]


def safe_day_path(remote_root: str, day: str) -> str:
    """Build ``<remote_root>/<day>`` after validating both parts.

    Raises:
        ValueError: if the day is malformed or the root is empty.
    """
    if not is_day_name(day):
        raise ValueError(f"not a trading day: {day!r}")
    root = remote_root.rstrip("/\\")
    if not root:
        raise ValueError("remote_data_root is empty")
    return f"{root}/{day}"


def plan_reclaim(manifest: Manifest, host: str, day: str, *, enabled: bool) -> ReclaimDecision:
    """Decide whether ``host/day`` may be deleted."""
    status = manifest.status(host, day)
    if not enabled:
        return ReclaimDecision(host, day, False, "reclaim disabled by config")
    if status is None:
        return ReclaimDecision(host, day, False, "not in manifest")
    if status != STATUS_MERGED:
        return ReclaimDecision(host, day, False, f"status={status}")
    return ReclaimDecision(host, day, True, "verified and merged")


def execute_reclaim(
    manifest: Manifest,
    backend: PullBackend,
    *,
    enabled: bool = True,
    dry_run: bool = False,
) -> ReclaimReport:
    """Delete the days that pass :func:`plan_reclaim`."""
    report = ReclaimReport(dry_run=dry_run)
    for day in manifest.days(backend.name):
        decision = plan_reclaim(manifest, backend.name, day, enabled=enabled)
        try:
            path = safe_day_path(getattr(backend, "remote_root", ""), day)
        except ValueError as error:
            decision = ReclaimDecision(backend.name, day, False, f"unsafe path: {error}")
            report.decisions.append(decision)
            continue
        decision = ReclaimDecision(
            decision.host, decision.day, decision.delete, decision.reason, path
        )
        report.decisions.append(decision)
        if not decision.delete or dry_run:
            continue
        try:
            backend.delete_day(day)
        except Exception as error:
            _logger.exception("failed to reclaim %s/%s", backend.name, day)
            report.failed.append(f"{backend.name}/{day}: {error}")
            continue
        manifest.mark(backend.name, day, STATUS_DELETED)
        report.deleted.append(f"{backend.name}/{day}")
    return report


__all__ = ["ReclaimDecision", "ReclaimReport", "execute_reclaim", "plan_reclaim", "safe_day_path"]

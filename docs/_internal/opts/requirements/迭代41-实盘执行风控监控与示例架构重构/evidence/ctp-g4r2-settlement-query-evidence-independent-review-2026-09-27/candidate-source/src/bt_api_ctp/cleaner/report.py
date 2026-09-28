"""Serialise a pipeline run into the daily cleaning report.

The report is the operator-facing account of one run: what each host
contributed, what the merge changed, what the K-line build produced, what was
reclaimed, and every anomaly that deserves a look (verify failures, schema
drift, unknown instruments, unreadable files).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from bt_api_ctp.cleaner.pipeline import PipelineReport


def report_day(report: PipelineReport) -> str:
    """The trading day the report is named after (the newest one it touched)."""
    days = set(report.merge) | set(report.kline)
    for host in report.hosts.values():
        days.update(host.days_pulled)
    return max(days) if days else datetime.now().strftime("%Y%m%d")


def report_path(report_dir: Path | str, report: PipelineReport) -> Path:
    return Path(report_dir) / f"clean-{report_day(report)}.json"


def build_payload(report: PipelineReport) -> dict:
    """Build the JSON payload, including the aggregated anomaly list."""
    anomalies: list[str] = []
    hosts: dict[str, dict] = {}
    for name, host in sorted(report.hosts.items()):
        for failure in host.verify_failures:
            anomalies.append(f"verify failed [{name}]: {failure}")
        for error in host.errors:
            anomalies.append(f"host error [{name}]: {error}")
        hosts[name] = {
            "backend": host.backend,
            "days_seen": host.days_seen,
            "days_ready": host.days_ready,
            "days_pulled": host.days_pulled,
            "days_incomplete": host.days_incomplete,
            "days_already_done": host.days_already_done,
            "verify_failures": host.verify_failures,
            "fetch_files": host.fetch_files,
            "fetch_bytes": host.fetch_bytes,
            "errors": host.errors,
        }

    merge: dict[str, dict] = {}
    for day, entry in sorted(report.merge.items()):
        for note in entry.schema_drift:
            anomalies.append(f"schema drift [{day}]: {note}")
        merge[day] = {
            "instruments": entry.instruments,
            "added": entry.added,
            "deduped": entry.deduped,
            "total": entry.total,
            "schema_drift": entry.schema_drift,
        }

    kline: dict[str, dict] = {}
    for day, entry in sorted(report.kline.items()):
        for name in entry.skipped_unknown:
            anomalies.append(f"unknown instrument [{day}]: {name}")
        for name in entry.unreadable:
            anomalies.append(f"unreadable tick file [{day}]: {name}")
        kline[day] = {
            "instruments": entry.instruments,
            "rows": entry.rows,
            "bars_added": entry.bars_added,
            "skipped_combination": entry.skipped_combination,
            "skipped_option": entry.skipped_option,
            "skipped_unknown": entry.skipped_unknown,
            "unreadable": entry.unreadable,
            "unparseable_rows": entry.unparseable_rows,
            "bars_without_price": entry.bars_without_price,
        }

    reclaim = {
        "dry_run": report.reclaim.dry_run,
        "planned": report.reclaim.planned,
        "deleted": report.reclaim.deleted,
        "failed": report.reclaim.failed,
        "decisions": [
            {
                "host": item.host,
                "day": item.day,
                "delete": item.delete,
                "reason": item.reason,
                "path": item.path,
            }
            for item in report.reclaim.decisions
        ],
    }
    for failure in report.reclaim.failed:
        anomalies.append(f"reclaim failed: {failure}")

    return {
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "dry_run": report.dry_run,
        "hosts": hosts,
        "merge": merge,
        "kline": kline,
        "reclaim": reclaim,
        "anomalies": anomalies,
    }


def write_report(report: PipelineReport, report_dir: Path | str) -> Path:
    """Write the report atomically and return its path."""
    path = report_path(report_dir, report)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp_path.write_text(
            json.dumps(build_payload(report), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
    return path


__all__ = ["build_payload", "report_day", "report_path", "write_report"]

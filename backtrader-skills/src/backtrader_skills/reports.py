"""Auditable JSON and Markdown run reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .canonical import atomic_write_bytes, atomic_write_json, file_hash


def write_run_reports(directory: Path, result: dict[str, Any]) -> list[dict[str, Any]]:
    json_path = directory / "run-result.json"
    markdown_path = directory / "report.md"
    atomic_write_json(json_path, result)
    lines = [
        f"# Backtrader Skills Run {result['run_id']}",
        "",
        f"- Status: `{result['status']}`",
        f"- Manifest: `{result['manifest_hash']}`",
        f"- Comparison profile: `{result['comparison']['metrics']['profile_hash']}`",
        "",
        "## Metrics",
        "",
        "| Metric | Unit | runonce | runnext |",
        "| --- | --- | ---: | ---: |",
    ]
    vector = result["modes"]["runonce"]
    event = result["modes"]["runnext"]
    for key, unit in vector["metric_units"].items():
        lines.append(f"| `{key}` | {unit} | {vector['metrics'][key]} | {event['metrics'][key]} |")
    lines.extend(
        [
            "",
            "## Parity",
            "",
            f"- Metrics: `{'passed' if result['comparison']['metrics']['passed'] else 'failed'}`",
            f"- Events: `{'passed' if result['comparison']['events']['passed'] else 'failed'}`",
            "",
            "## Isolation boundary",
            "",
            "The candidate was imported only in fixed child processes. This is process isolation, "
            "not a complete operating-system sandbox; P0 also applies AST, import, path, and offline "
            "data gates.",
            "",
        ]
    )
    atomic_write_bytes(markdown_path, "\n".join(lines).encode("utf-8"))
    return [
        {
            "path": markdown_path.name,
            "role": "run_report_markdown",
            "bytes": markdown_path.stat().st_size,
            "sha256": file_hash(markdown_path),
        }
    ]

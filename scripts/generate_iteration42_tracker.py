#!/usr/bin/env python
"""Generate the Iteration 42 per-example tracker (JSON + Markdown).

Reads each example directory's newest ``evidence/live-*/run.json`` (if any)
and merges it with the round status table.  The tracker records, per the
iteration plan §7.1: dry / replay / live status, tier, trigger, env scope,
order counts, cleanup, evidence SHA-256 and the round commit.

Usage::

    python scripts/generate_iteration42_tracker.py [--out DIR]

Pure standard library; reads only git-ignored run evidence plus the pinned
status table below (no network, no private config).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples"
DEFAULT_OUT = (
    REPO
    / "docs"
    / "_internal"
    / "opts"
    / "requirements"
    / "迭代42-示例策略模拟盘贯通与四件套标准化"
    / "evidence"
)

# Round status table (updated per round; live fields are refined from evidence).
EXAMPLES_STATUS: Dict[str, Dict[str, Any]] = {
    "012_1_midfreq_cross_exchange": {
        "dry": "PASS", "replay": "PASS", "live": "BLOCKED",
        "tier": "self_check_only", "trigger": "none",
        "env_scope": "OKX+Binance demo (dual-venue)",
        "note": "demo round trip blocked by the expired qualification window (zero-code flip)",
        "commit": "7cfad68bc",
    },
    "012_2_event_driven_cross_exchange": {
        "dry": "PASS", "replay": "PASS", "live": "BLOCKED",
        "tier": "self_check_only", "trigger": "none",
        "env_scope": "OKX+Binance demo (dual-venue)",
        "note": "structural block: HFT admission (event_path_models) is out of iteration scope",
        "commit": "90cf8914a",
    },
    "013_3_sa_midfreq_simnow": {
        "dry": "PASS", "replay": "PASS", "live": "PENDING_SESSION",
        "tier": "pending", "trigger": "drill",
        "env_scope": "SimNow standard fronts (1-8 MD/TD pairs)",
        "note": "first-ever Store/Broker registered-sim arming recorded; drill awaiting session",
        "commit": "eb3da84f3",
    },
    "013_1_midfreq_cross_arbitrage": {
        "dry": "PASS", "replay": "PASS", "live": "PENDING_SESSION",
        "tier": "pending", "trigger": "drill",
        "env_scope": "SimNow standard fronts (m/RM legs)",
        "note": "per-leg registered-sim arm switching; defect fixes per plan §4",
        "commit": "0150641a3",
    },
    "013_2_highfreq_calendar_arbitrage": {
        "dry": "PASS", "replay": "PASS", "live": "PENDING_SESSION",
        "tier": "pending", "trigger": "drill",
        "env_scope": "SimNow standard fronts (rb calendar legs)",
        "note": "same-exchange calendar spread; HFT status stays FAIL/NOT_ADMITTED",
        "commit": "e91e3638b",
    },
    "014_1_ctp_options_lowfreq": {
        "dry": "PASS", "replay": "PASS", "live": "BLOCKED",
        "tier": "self_check_only", "trigger": "none",
        "env_scope": "SimNow options (SA C/P/F) - adapter not integrated",
        "note": "strict feed-sealed evidence adapter round required (plan R6-R8 scope revision)",
        "commit": "e7dc0e4a6",
    },
    "014_2_ctp_options_midfreq": {
        "dry": "PASS", "replay": "PASS", "live": "BLOCKED",
        "tier": "self_check_only", "trigger": "none",
        "env_scope": "SimNow options (F_LOCAL fixture) - adapter not integrated",
        "note": "needs real contract mapping plus the strict evidence adapter round",
        "commit": "e7dc0e4a6",
    },
    "015_ctp_options_highfreq": {
        "dry": "PASS", "replay": "PASS", "live": "BLOCKED",
        "tier": "self_check_only", "trigger": "none",
        "env_scope": "SimNow options tick (cohort fixture) - adapter not integrated",
        "note": "HFT latency conclusion excluded (FAIL/NOT_ADMITTED)",
        "commit": "e7dc0e4a6",
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _latest_live_run(directory: Path) -> Optional[Dict[str, Any]]:
    evidence = directory / "evidence"
    if not evidence.is_dir():
        return None
    candidates = sorted(evidence.glob("live-*/run.json"), key=lambda path: path.stat().st_mtime)
    if not candidates:
        return None
    path = candidates[-1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"run_json": str(path), "sha256": None, "parse_error": True}
    orders = payload.get("orders") or {}
    reconciliation = payload.get("reconciliation") or {}
    run = payload.get("run") or {}
    return {
        "run_json": str(path),
        "sha256": _sha256(path),
        "status": payload.get("status"),
        "tier": payload.get("tier"),
        "trigger": payload.get("trigger"),
        "reason": payload.get("reason"),
        "seconds": run.get("seconds"),
        "entry_fills": orders.get("filled_entry_lots", orders.get("entry_by_symbol")),
        "close_fills": orders.get("filled_close_lots", orders.get("close_by_symbol")),
        "active_orders": orders.get("active_orders"),
        "open_position_rows": reconciliation.get("open_position_rows"),
    }


def build_tracker() -> Dict[str, Any]:
    rows = []
    for name, status in sorted(EXAMPLES_STATUS.items()):
        directory = EXAMPLES / name
        row = dict(status)
        row["example"] = name
        row["run_py"] = str(directory / "run.py")
        live = _latest_live_run(directory)
        if live is not None:
            row["live_evidence"] = live
            if live.get("status") in {"PASS", "FAIL", "UNKNOWN"}:
                row["live"] = live["status"]
                row["tier"] = live.get("tier") or row["tier"]
                row["trigger"] = live.get("trigger") or row["trigger"]
        rows.append(row)
    return {
        "schema": "iteration42-tracker-v1",
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "examples": rows,
    }


def _markdown(tracker: Dict[str, Any]) -> str:
    lines = [
        "# 迭代42 示例 tracker（自动生成）",
        "",
        f"生成时间（UTC）：`{tracker['generated_utc']}`",
        "",
        "| 示例 | dry | replay | live | tier | trigger | env_scope | commit | 备注 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in tracker["examples"]:
        lines.append(
            "| {example} | {dry} | {replay} | {live} | {tier} | {trigger} | {env} | `{commit}` | {note} |".format(
                example=row["example"],
                dry=row["dry"],
                replay=row["replay"],
                live=row["live"],
                tier=row["tier"],
                trigger=row["trigger"],
                env=row["env_scope"],
                commit=row["commit"],
                note=row["note"],
            )
        )
    lines.append("")
    lines.append("live 详情（若已跑）见各示例 `evidence/live-*/run.json`（SHA-256 记录在 JSON tracker）。")
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tracker = build_tracker()
    json_path = out_dir / "iteration42-example-tracker.json"
    md_path = out_dir / "iteration42-example-tracker.md"
    json_path.write_text(
        json.dumps(tracker, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    md_path.write_text(_markdown(tracker), encoding="utf-8")
    print(
        json.dumps(
            {
                "json": str(json_path),
                "json_sha256": _sha256(json_path),
                "markdown": str(md_path),
                "markdown_sha256": _sha256(md_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

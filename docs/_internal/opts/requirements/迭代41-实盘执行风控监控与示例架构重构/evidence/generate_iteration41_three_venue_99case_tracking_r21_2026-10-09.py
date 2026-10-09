"""Generate the r21 three-venue 99-case acceptance tracker (2026-10-09).

Reads the newest per-case evidence JSON from each suite's
``cases/<ID>/evidence/`` directory (preferring the newest PASS run when one
exists, otherwise the newest run of any status), records each selected
evidence file's SHA-256, and writes a self-contained JSON + Markdown tracker.

Usage:
    C:/anaconda3/python.exe generate_iteration41_three_venue_99case_tracking_r21_2026-10-09.py \
        --main-commit <sha> --sdk-commit <sha>

Optional16 status is read from optional16/acceptance-matrix.json when present.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[6]
CERT = REPO / "examples" / "000_live_certification"
OUT_DIR = Path(__file__).resolve().parent
VENUES = ("binance", "okx", "simnow")
CASE_IDS = [
    "B01", "B02", "C01", "E01", "E02", "E03", "EM01", "EM02", "EM03",
    "L01", "L02", "L03", "L04", "M01", "M02", "M03", "M04", "M05",
    "O01", "O02", "O03", "T01", "T02", "T03", "TH01", "TH02", "TH03",
    "TH04", "TH05", "TH06", "V01", "V02", "V03",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_runs(evidence_dir: Path):
    runs = []
    if not evidence_dir.is_dir():
        return runs
    for path in sorted(evidence_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        runs.append(
            {
                "file": path.name,
                "status": str(data.get("status", "UNKNOWN")),
                "reason": str(data.get("reason", "") or ""),
                "sha256": _sha256(path),
                "live": bool(data.get("live")),
            }
        )
    return runs


def _select(runs):
    """Newest PASS when one exists, else the newest run."""
    if not runs:
        return None
    passes = [r for r in runs if r["status"] == "PASS"]
    pool = passes or runs
    return max(pool, key=lambda r: r["file"])


def build(main_commit: str, sdk_commit: str, archive_dir: Path | None = None) -> dict:
    venues_block = {}
    totals = {"PASS": 0, "BLOCKED": 0, "FAIL": 0, "UNKNOWN": 0, "NOT_RUN": 0}
    blocked = []
    for venue in VENUES:
        cases_block = {}
        for case_id in CASE_IDS:
            evidence_dir = CERT / f"{venue}_penetration" / "cases" / case_id / "evidence"
            selected = _select(_load_runs(evidence_dir))
            if selected is None:
                status = "NOT_RUN"
                entry = {"status": status}
            else:
                status = selected["status"]
                source = evidence_dir / selected["file"]
                entry = {
                    "status": status,
                    "reason": selected["reason"],
                    "evidence": str(
                        (CERT / f"{venue}_penetration" / "cases" / case_id / "evidence" / selected["file"]).relative_to(REPO)
                    ).replace("\\", "/"),
                    "evidence_sha256": selected["sha256"],
                    "live": selected["live"],
                }
                if archive_dir is not None:
                    target_dir = archive_dir / venue
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target = target_dir / f"{case_id}__{selected['file']}"
                    target.write_bytes(source.read_bytes())
                    entry["archived_path"] = str(target.relative_to(REPO)).replace("\\", "/")
                if status == "BLOCKED":
                    blocked.append({"venue": venue, "case": case_id, "reason": entry["reason"]})
            cases_block[case_id] = entry
            totals[status] = totals.get(status, 0) + 1
        venues_block[venue] = {
            "cases": cases_block,
            "summary": {
                status: sum(1 for c in cases_block.values() if c["status"] == status)
                for status in ("PASS", "BLOCKED", "FAIL", "UNKNOWN", "NOT_RUN")
            },
        }

    matrix_path = CERT / "optional16" / "acceptance-matrix.json"
    if matrix_path.is_file():
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        optional = {
            "status": "PRESENT",
            "path": "examples/000_live_certification/optional16/acceptance-matrix.json",
            "sha256": _sha256(matrix_path),
            "summary": matrix.get("summary"),
        }
    else:
        optional = {"status": "PENDING_BUILD_OR_RUN"}

    return {
        "schema": "iteration41-three-venue-99-case-acceptance-tracking",
        "revision": "r21",
        "as_of_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "methodology": (
            "three-file cases (config.yaml + <ID>_strategy.py + run.py); per-run evidence JSON "
            "under cases/<ID>/evidence/ (git-ignored, SHA-256 recorded here); newest PASS preferred, "
            "otherwise the newest run; blocked entries carry the reason from the run"
        ),
        "commits": {
            "backtrader_dev": main_commit,
            "bt_api_ctp_dev": sdk_commit,
        },
        "totals": totals,
        "blocked": blocked,
        "venues": venues_block,
        "optional16": optional,
    }


def render_md(doc: dict) -> str:
    lines = [
        "# Iteration 41 — three-venue 99-case acceptance tracker (r21)",
        "",
        f"- as_of_utc: `{doc['as_of_utc']}`",
        f"- commits: backtrader dev `{doc['commits']['backtrader_dev']}`, bt_api_ctp dev `{doc['commits']['bt_api_ctp_dev']}`",
        f"- totals: **{doc['totals']['PASS']} PASS / {doc['totals']['BLOCKED']} BLOCKED / "
        f"{doc['totals']['FAIL']} FAIL / {doc['totals']['NOT_RUN']} NOT_RUN** (99 cases)",
        f"- optional16: `{doc['optional16'].get('status')}`",
        "",
        "Methodology: " + doc["methodology"],
        "",
    ]
    for venue, block in doc["venues"].items():
        summary = block["summary"]
        lines.append(f"## {venue} — {summary['PASS']} PASS / {summary['BLOCKED']} BLOCKED / {summary['NOT_RUN']} NOT_RUN")
        lines.append("")
        lines.append("| case | status | reason | evidence | sha256 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for case_id, entry in block["cases"].items():
            lines.append(
                f"| {case_id} | {entry['status']} | {entry.get('reason', '')} | "
                f"`{Path(entry.get('evidence', '')).name}` | `{entry.get('evidence_sha256', '')[:12]}` |"
            )
        lines.append("")
    if doc["blocked"]:
        lines.append("## Blocked cases (evidence-backed)")
        lines.append("")
        for item in doc["blocked"]:
            lines.append(f"- {item['venue']}/{item['case']}: {item['reason']}")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-commit", required=True)
    parser.add_argument("--sdk-commit", required=True)
    parser.add_argument("--archive", action="store_true", help="copy selected evidence into the archive dir")
    args = parser.parse_args()
    archive_dir = OUT_DIR / "r21-case-evidence" if args.archive else None
    if archive_dir is not None and archive_dir.exists():
        import shutil

        shutil.rmtree(archive_dir)
    doc = build(args.main_commit, args.sdk_commit, archive_dir=archive_dir)
    if archive_dir is not None:
        doc["evidence_archive"] = str(archive_dir.relative_to(REPO)).replace("\\", "/")
    json_path = OUT_DIR / "iteration41-three-venue-99-case-acceptance-tracking-r21-2026-10-09.json"
    md_path = OUT_DIR / "iteration41-three-venue-99-case-acceptance-tracking-r21-2026-10-09.md"
    json_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(render_md(doc), encoding="utf-8")
    print("totals:", doc["totals"])
    print("written:", json_path.name, md_path.name)


if __name__ == "__main__":
    main()

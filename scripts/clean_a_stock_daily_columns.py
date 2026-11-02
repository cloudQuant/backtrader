#!/usr/bin/env python3
"""Create the seven-column derived copy of the a_stocks daily panel."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import shutil
import sys
import time
from pathlib import Path
from typing import List, Sequence, Tuple

SOURCE_COLUMNS = (
    "trade_date",
    "trade_time",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "minute_count",
    "first_trade_time",
    "last_trade_time",
    "missing_or_invalid_count",
    "invalid_day",
)
KEEP_COLUMNS = ("trade_time", "open", "high", "low", "close", "volume", "amount")
DROPPED_COLUMNS = tuple(column for column in SOURCE_COLUMNS if column not in KEEP_COLUMNS)
_QUOTE_CHARS = ',"\r\n'


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _project_file(
    source_path: Path,
    entry: dict,
    keep_indices: Sequence[int],
    keep_columns: Sequence[str],
) -> Tuple[bytes, int]:
    raw = source_path.read_bytes()
    if b"\r" in raw:
        raise ValueError("%s: CRLF line endings are not supported" % source_path.name)
    if len(raw) != int(entry["bytes"]):
        raise ValueError("%s: byte size does not match the manifest" % source_path.name)
    if _sha256(raw) != entry["sha256"]:
        raise ValueError("%s: sha256 does not match the manifest" % source_path.name)

    rows = list(csv.reader(io.StringIO(raw.decode("utf-8"))))
    if not rows or tuple(rows[0]) != SOURCE_COLUMNS:
        raise ValueError("%s: unexpected header" % source_path.name)
    body = rows[1:]
    if len(body) != int(entry["rows"]):
        raise ValueError("%s: row count does not match the manifest" % source_path.name)

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(keep_columns)
    expected: List[Tuple[str, ...]] = []
    for line_number, row in enumerate(body, 2):
        if len(row) != len(SOURCE_COLUMNS):
            raise ValueError(
                "%s:%d: unexpected field count" % (source_path.name, line_number)
            )
        kept = tuple(row[index] for index in keep_indices)
        if any(not value for value in kept):
            raise ValueError(
                "%s:%d: empty retained field" % (source_path.name, line_number)
            )
        if any(any(character in value for character in _QUOTE_CHARS) for value in kept):
            raise ValueError(
                "%s:%d: retained field requires CSV quoting" % (source_path.name, line_number)
            )
        expected.append(kept)
        writer.writerow(kept)

    payload = buffer.getvalue().encode("utf-8")
    reread = list(csv.reader(io.StringIO(payload.decode("utf-8"))))
    if not reread or tuple(reread[0]) != tuple(keep_columns):
        raise ValueError("%s: written header mismatch" % source_path.name)
    if [tuple(row) for row in reread[1:]] != expected:
        raise ValueError("%s: written fields differ from the source" % source_path.name)
    return payload, len(expected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="tests/datas/a_stocks", type=Path)
    parser.add_argument("--target", default="tests/datas/a_stocks_clean", type=Path)
    args = parser.parse_args()

    source_root = args.source.resolve()
    target_root = args.target.resolve()
    if source_root == target_root:
        raise SystemExit("source and target must differ")
    if target_root.exists():
        raise SystemExit("target already exists: %s" % target_root)

    manifest_path = source_root / "_metadata" / "manifest.json"
    source_manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(source_manifest_bytes.decode("utf-8"))
    entries = list(manifest["output"]["symbols"])
    if len(entries) != int(manifest["output"]["csv_file_count"]):
        raise SystemExit("source manifest csv_file_count mismatch")

    keep_indices = [SOURCE_COLUMNS.index(column) for column in KEEP_COLUMNS]
    staging = target_root.with_name(target_root.name + ".tmp")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    metadata_dir = staging / "_metadata"
    metadata_dir.mkdir()

    started = time.perf_counter()
    cleaned_entries = []
    total_rows = 0
    total_bytes = 0
    try:
        for index, entry in enumerate(entries, 1):
            payload, rows = _project_file(
                source_root / entry["file"], entry, keep_indices, KEEP_COLUMNS
            )
            (staging / entry["file"]).write_bytes(payload)
            cleaned = dict(entry)
            cleaned["bytes"] = len(payload)
            cleaned["sha256"] = _sha256(payload)
            cleaned_entries.append(cleaned)
            total_rows += rows
            total_bytes += len(payload)
            if index % 500 == 0 or index == len(entries):
                print("projected %d/%d files" % (index, len(entries)), flush=True)

        if total_rows != int(manifest["output"]["daily_rows"]):
            raise SystemExit("projected row total does not match the source manifest")

        calendar_source = source_root / manifest["output"]["observed_calendar_csv"]
        calendar_payload = calendar_source.read_bytes()
        (metadata_dir / "observed_calendar.csv").write_bytes(calendar_payload)
        if (metadata_dir / "observed_calendar.csv").read_bytes() != calendar_payload:
            raise SystemExit("observed_calendar.csv copy mismatch")

        manifest["output"]["symbols"] = cleaned_entries
        manifest["output"]["columns"] = list(KEEP_COLUMNS)
        manifest["output"]["format"] = (
            "one UTF-8 CSV per symbol; no combined daily table; columns: "
            + ",".join(KEEP_COLUMNS)
        )
        manifest["output"]["total_bytes"] = total_bytes
        manifest["cleaning"] = {
            "script": "scripts/clean_a_stock_daily_columns.py",
            "source_directory_name": source_root.name,
            "source_manifest_sha256": _sha256(source_manifest_bytes),
            "source_csv_file_count": len(entries),
            "source_daily_rows": int(manifest["output"]["daily_rows"]),
            "source_total_bytes": sum(int(entry["bytes"]) for entry in entries),
            "kept_columns": list(KEEP_COLUMNS),
            "dropped_columns": list(DROPPED_COLUMNS),
            "verification": {
                "csv_file_count": len(cleaned_entries),
                "daily_rows": total_rows,
                "retained_field_mismatches": 0,
                "source_file_hashes_checked": len(cleaned_entries),
                "observed_calendar_bytes": len(calendar_payload),
            },
        }
        manifest_payload = (
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        (metadata_dir / "manifest.json").write_bytes(manifest_payload)
        staging.replace(target_root)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    elapsed = time.perf_counter() - started
    source_bytes = sum(int(entry["bytes"]) for entry in entries)
    print(
        "source: %d files, %d rows, %d bytes"
        % (len(entries), int(manifest["output"]["daily_rows"]), source_bytes)
    )
    print(
        "target: %d files, %d rows, %d bytes (%.1f%% smaller)"
        % (
            len(cleaned_entries),
            total_rows,
            total_bytes,
            100.0 * (1.0 - total_bytes / float(source_bytes)),
        )
    )
    print("dropped columns: %s" % ",".join(DROPPED_COLUMNS))
    print("manifest sha256: %s" % _sha256(manifest_payload))
    print("elapsed: %.1fs" % elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())

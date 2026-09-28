"""Verify a staged copy against the remote listing before it may be merged.

Three levels, cheapest first:

1. every remote final file exists locally;
2. every local file has the remote's byte size;
3. every local parquet opens and reports a row count.

The row count is recorded in the manifest so the merged result can later be
shown to account for it.  A verification problem keeps the remote data: the
caller must not delete something it could not prove it copied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pyarrow.parquet as pq

from bt_api_ctp.cleaner.pull.backend import RemoteFile, relative_parts


@dataclass
class VerifyResult:
    """Outcome of verifying one staged day."""

    day: str
    ok: bool = True
    problems: list[str] = field(default_factory=list)
    #: Verified file records for the manifest.
    files: list[dict] = field(default_factory=list)
    total_rows: int = 0


def verify_staged_day(
    remote_files: list[RemoteFile], staged_root: Path | str, day: str
) -> VerifyResult:
    """Compare ``<staged_root>/<day>`` with the remote listing."""
    result = VerifyResult(day=day)
    root = Path(staged_root) / day
    expected = {file.rel_path: file.size_bytes for file in remote_files}

    for rel_path, size_bytes in sorted(expected.items()):
        local = root.joinpath(*relative_parts(rel_path)[1:])
        if not local.is_file():
            result.problems.append(f"missing: {rel_path}")
            continue
        actual_size = local.stat().st_size
        if actual_size != size_bytes:
            result.problems.append(
                f"size mismatch: {rel_path} remote={size_bytes} local={actual_size}"
            )
            continue
        rows = 0
        if local.suffix == ".parquet":
            try:
                rows = pq.ParquetFile(local).metadata.num_rows
            except Exception as error:
                result.problems.append(f"unreadable: {rel_path} ({error})")
                continue
        result.files.append({"rel_path": rel_path, "size_bytes": actual_size, "rows": rows})
        result.total_rows += rows

    # Files staged for this day that the remote no longer lists would merge
    # stale rows, so treat them as a problem too.
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel_path = path.relative_to(Path(staged_root)).as_posix()
            if rel_path not in expected:
                result.problems.append(f"unexpected local file: {rel_path}")

    result.ok = not result.problems
    return result


__all__ = ["VerifyResult", "verify_staged_day"]

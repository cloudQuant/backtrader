"""Shared utility functions for certification cases."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Set


def read_json_lines(path: Path) -> List[Dict[str, Any]]:
    """Read a JSON-lines log file and return a list of dicts."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def extract_event_types(entries: List[Dict[str, Any]]) -> List[str]:
    """Return ordered list of event_type values."""
    return [e.get("event_type", "") for e in entries]


def extract_event_type_set(entries: List[Dict[str, Any]]) -> Set[str]:
    """Return unique set of event_type values."""
    return {e.get("event_type", "") for e in entries}


def collect_evidence_files(log_dir: str | Path) -> List[str]:
    """List all files in *log_dir* as evidence paths."""
    log_dir = Path(log_dir)
    if not log_dir.exists():
        return []
    return sorted(str(p) for p in log_dir.iterdir() if p.is_file())

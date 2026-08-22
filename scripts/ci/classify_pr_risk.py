"""Classify a PR's risk level and suggest labels from its changed paths.

Deterministic, path-based classifier. Emits *suggested* labels; maintainers
retain final override authority and record the reason.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Highest-first ordering; a PR takes the highest risk across all changed paths.
_RISK_ORDER = {"R0": 0, "R1": 1, "R2": 2, "R3": 3}

# R3 — supply chain / security / release (explicit core-maintainer approval).
_R3_PREFIXES = (
    "setup.py",
    "pyproject.toml",
    "requirements.txt",
    "MANIFEST.in",
    "SECURITY.md",
    ".github/workflows/",
)

# R2 — core / compatibility (domain owner + second maintainer).
_R2_PREFIXES = (
    "backtrader/lineroot.py",
    "backtrader/linebuffer.py",
    "backtrader/lineseries.py",
    "backtrader/lineiterator.py",
    "backtrader/metabase.py",
    "backtrader/cerebro.py",
    "backtrader/strategy.py",
    "backtrader/broker.py",
    "backtrader/brokers/",
    "backtrader/feeds/",
)

# R0 — docs / tests / non-behavioral tooling.
_R0_PREFIXES = ("docs/", "tests/", ".github/ISSUE_TEMPLATE/", ".github/PULL_REQUEST_TEMPLATE/")
_R0_SUFFIXES = (".md",)

# area:* suggestion, first match wins.
_AREA_RULES: Tuple[Tuple[str, str], ...] = (
    ("backtrader/broker.py", "area:broker"),
    ("backtrader/brokers/", "area:broker"),
    ("backtrader/feeds/", "area:feeds"),
    ("backtrader/indicators/", "area:indicators"),
    ("backtrader/analyzers/", "area:analyzers"),
    ("backtrader/observers/", "area:observers"),
    ("docs/", "area:docs"),
    ("tests/", "area:tests"),
    (".github/", "area:ci"),
    ("scripts/", "area:ci"),
    ("backtrader/", "area:core"),
)


def _normalize(path: str) -> str:
    return path.replace("\\", "/")


def _classify_single(path: str) -> str:
    p = _normalize(path)
    for prefix in _R3_PREFIXES:
        if p == prefix or p.startswith(prefix):
            return "R3"
    for prefix in _R2_PREFIXES:
        if p == prefix or p.startswith(prefix):
            return "R2"
    if p.endswith(_R0_SUFFIXES) or p.startswith(_R0_PREFIXES):
        return "R0"
    return "R1"


def classify_risk(paths: List[str]) -> str:
    """Return the highest risk level (R0–R3) across the changed paths."""
    if not paths:
        return "R0"
    highest = max(_RISK_ORDER[_classify_single(p)] for p in paths)
    for level, order in _RISK_ORDER.items():
        if order == highest:
            return level
    return "R0"


def suggest_area(paths: List[str]) -> str:
    """Suggest a single ``area:*`` label from the changed paths."""
    for path in paths:
        p = _normalize(path)
        for prefix, label in _AREA_RULES:
            if p == prefix.rstrip("/") or p.startswith(prefix):
                return label
    return "area:core"


def suggest_labels(paths: List[str]) -> Dict[str, str]:
    """Return suggested labels (risk + area) for the changed paths."""
    return {"risk": classify_risk(paths), "area": suggest_area(paths)}


def paths_from_file(path: Path) -> List[str]:
    """Read one changed path per line from a UTF-8 file."""
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_github_output(path: Path, labels: Dict[str, str]) -> None:
    """Write fixed classifier values in the GitHub Actions output-file format."""
    path.open("a", encoding="utf-8").write(f"risk={labels['risk']}\narea={labels['area']}\n")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify a PR's risk level and suggest labels from changed paths."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--paths",
        nargs="+",
        help="Changed file paths (space-separated).",
    )
    source.add_argument(
        "--paths-file",
        type=Path,
        help="UTF-8 file containing one changed path per line.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        help="Optional GitHub Actions output file to receive risk and area values.",
    )
    args = parser.parse_args(argv)

    paths = args.paths if args.paths is not None else paths_from_file(args.paths_file)
    labels = suggest_labels(paths)
    if args.format == "json":
        print(json.dumps(labels, sort_keys=True))
    else:
        print(f"risk={labels['risk']}")
        print(f"area={labels['area']}")
        print("NOTE: these are suggestions; maintainers retain final override authority.")
    if args.github_output is not None:
        write_github_output(args.github_output, labels)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI for each venue's live penetration certification entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .cases import CASES, CaseSpec
from .config import Grants, load_config
from .models import CertificationError, Status
from .runner import case_proof_fields, run_live


def _run_cli(
    venue: str,
    fixed_case_id: str | None = None,
    fixed_case_spec: CaseSpec | None = None,
    fixed_proof_fields: tuple[str, ...] | None = None,
) -> int:
    """Run either a venue suite or one structurally bound live case."""
    if fixed_case_id is not None and (
        CASES.get(fixed_case_id) != fixed_case_spec
        or case_proof_fields(fixed_case_id) != fixed_proof_fields
    ):
        raise CertificationError("case strategy differs from the protected live contract")
    parser = argparse.ArgumentParser(
        description=(
            f"Managed live penetration certification for {venue}"
            if fixed_case_id is None
            else f"Managed live {fixed_case_id} penetration certification for {venue}"
        )
    )
    parser.add_argument(
        "--config", type=Path, required=True, help="YAML file containing env variable references"
    )
    if fixed_case_id is None:
        selection = parser.add_mutually_exclusive_group()
        selection.add_argument(
            "--case", action="append", choices=sorted(CASES), help="Select one or more case IDs"
        )
        selection.add_argument("--all", action="store_true", help="Select all enabled cases")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--allow-dangerous", action="store_true")
    parser.add_argument("--allow-production-write", action="store_true")
    parser.add_argument("--confirm", help="Exact venue/environment risk confirmation phrase")
    args = parser.parse_args()
    try:
        config = load_config(args.config, venue)
        if fixed_case_id is None:
            selected = (
                [
                    case_id
                    for case_id in CASES
                    if case_id in config.cases and config.cases[case_id].enabled
                ]
                if args.all or not args.case
                else args.case
            )
        else:
            selected = [fixed_case_id]
        grants = Grants(
            args.allow_write, args.allow_dangerous, args.allow_production_write, args.confirm
        )
        results, summary_path = run_live(config, selected, grants, args.evidence_dir)
    except (CertificationError, OSError, ValueError) as exc:
        # Avoid printing backend/OS exception strings, which can contain connection details.
        print(json.dumps({"status": "BLOCKED", "error_type": type(exc).__name__}), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "venue": config.venue,
                "results": [
                    {
                        "case_id": result.case_id,
                        "status": result.status.value,
                        "reason": result.reason,
                    }
                    for result in results
                ],
                "summary": str(summary_path),
            },
            ensure_ascii=False,
        )
    )
    if any(result.status == Status.FAILED for result in results):
        return 1
    return 2 if any(result.status == Status.BLOCKED for result in results) else 0


def run_venue_cli(venue: str) -> int:
    """Run a configured live venue certification and return a process exit code."""
    return _run_cli(venue)


def run_case_cli(
    venue: str,
    case_id: str,
    case_spec: CaseSpec,
    proof_fields: tuple[str, ...],
) -> int:
    """Run exactly one case whose local strategy matches the protected contract."""
    return _run_cli(venue, case_id, case_spec, proof_fields)

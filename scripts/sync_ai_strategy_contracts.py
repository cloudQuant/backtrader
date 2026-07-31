#!/usr/bin/env python
"""Vendor the authoritative AI strategy contracts into standalone products."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY_ROOT / "contracts" / "ai-strategy-v1"
PRODUCT_FILES = {
    "backtrader-skills": {
        "strategy-spec-v1.schema.json": "resources/contracts/strategy-spec-v1.schema.json",
        "dataset-manifest-v1.schema.json": "resources/contracts/dataset-manifest-v1.schema.json",
        "corpus-manifest-v1.schema.json": "resources/contracts/corpus-manifest-v1.schema.json",
        "artifact-manifest-v1.schema.json": (
            "resources/contracts/strategy-artifact-manifest-v1.schema.json"
        ),
        "validation-report-v1.schema.json": (
            "resources/contracts/validation-report-v1.schema.json"
        ),
        "run-manifest-v1.schema.json": "resources/contracts/run-manifest-v1.schema.json",
        "run-result-v1.schema.json": "resources/contracts/run-result-v1.schema.json",
        "comparison-profile-v1.json": "resources/policies/comparison-profile-v1.json",
    },
    "backtrader-mcp": {
        "strategy-spec-v1.schema.json": ("src/backtrader_mcp/schemas/strategy-spec.schema.json"),
        "dataset-manifest-v1.schema.json": (
            "src/backtrader_mcp/schemas/dataset-manifest.schema.json"
        ),
        "corpus-manifest-v1.schema.json": (
            "src/backtrader_mcp/schemas/corpus-manifest.schema.json"
        ),
        "artifact-manifest-v1.schema.json": (
            "src/backtrader_mcp/schemas/artifact-manifest.schema.json"
        ),
        "validation-report-v1.schema.json": (
            "src/backtrader_mcp/schemas/validation-report.schema.json"
        ),
        "run-manifest-v1.schema.json": ("src/backtrader_mcp/schemas/run-manifest.schema.json"),
        "run-result-v1.schema.json": "src/backtrader_mcp/schemas/run-result.schema.json",
        "comparison-profile-v1.json": ("src/backtrader_mcp/policies/comparison-profile-v1.json"),
    },
    "backtrader-agent": {
        "strategy-spec-v1.schema.json": (
            "src/backtrader_agent/resources/contracts/strategy-spec-v1.schema.json"
        ),
        "dataset-manifest-v1.schema.json": (
            "src/backtrader_agent/resources/contracts/dataset-manifest-v1.schema.json"
        ),
        "corpus-manifest-v1.schema.json": (
            "src/backtrader_agent/resources/contracts/corpus-manifest-v1.schema.json"
        ),
        "artifact-manifest-v1.schema.json": (
            "src/backtrader_agent/resources/contracts/artifact-manifest-v1.schema.json"
        ),
        "validation-report-v1.schema.json": (
            "src/backtrader_agent/resources/contracts/validation-report-v1.schema.json"
        ),
        "run-manifest-v1.schema.json": (
            "src/backtrader_agent/resources/contracts/run-manifest-v1.schema.json"
        ),
        "run-result-v1.schema.json": (
            "src/backtrader_agent/resources/contracts/run-result-v1.schema.json"
        ),
        "comparison-profile-v1.json": (
            "src/backtrader_agent/resources/policies/comparison-profile-v1.json"
        ),
    },
}


def sync(product: str, *, check: bool) -> list[str]:
    failures: list[str] = []
    for source_name, destination_name in PRODUCT_FILES[product].items():
        source = SOURCE / source_name
        destination = REPOSITORY_ROOT / product / destination_name
        if check:
            if not destination.is_file() or destination.read_bytes() != source.read_bytes():
                failures.append(f"{product}/{destination_name}")
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "products",
        nargs="*",
        default=None,
        metavar="PRODUCT",
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    products = args.products or sorted(PRODUCT_FILES)
    unknown = sorted(set(products) - set(PRODUCT_FILES))
    if unknown:
        parser.error(
            "unknown product(s): "
            + ", ".join(unknown)
            + "; choose from "
            + ", ".join(sorted(PRODUCT_FILES))
        )
    failures = [failure for product in products for failure in sync(product, check=args.check)]
    if failures:
        for failure in failures:
            print(f"contract copy differs: {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

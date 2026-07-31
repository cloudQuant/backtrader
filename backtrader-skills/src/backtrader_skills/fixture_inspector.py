"""Ephemeral fixture inspection used by the root compatibility script."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from .data import DataRegistry
from .runtime import RuntimePaths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--format", default="generic_csv")
    parser.add_argument("--timezone", default="UTC")
    args = parser.parse_args(argv)
    fixture = args.fixture.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="backtrader-skills-inspect-") as temp:
        registry = DataRegistry(RuntimePaths(Path(temp)))
        registry.add_root(fixture.parent, root_id="fixture")
        result = registry.inspect(
            {
                "name": "fixture",
                "symbol": fixture.stem,
                "source": {
                    "root_id": "fixture",
                    "relative_path": fixture.name,
                    "source_type": "local_file",
                },
                "format": args.format,
                "timezone": args.timezone,
            }
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Render a GitHub Rulesets API payload from an Iteration 140 manifest.

The tracked manifests include local audit metadata (the branch key, rollout
notes, and activation record). GitHub's REST endpoint must not receive those
keys. This program removes them deterministically; it never calls GitHub and
never handles credentials.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


_LOCAL_ONLY_KEYS = {"branch", "_governance_notes", "_activation"}
_REQUIRED_API_KEYS = {"name", "target", "enforcement", "conditions", "rules"}


def render_payload(manifest: Dict[str, Any], enforcement: Optional[str] = None) -> Dict[str, Any]:
    """Return the API-safe subset of a tracked ruleset manifest."""
    missing = sorted(_REQUIRED_API_KEYS - set(manifest))
    if missing:
        raise ValueError(f"manifest is missing required API keys: {', '.join(missing)}")

    payload = {key: value for key, value in manifest.items() if key not in _LOCAL_ONLY_KEYS}
    if enforcement is not None:
        payload["enforcement"] = enforcement
    return payload


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render an Iteration 140 Rulesets API payload without local audit metadata."
    )
    parser.add_argument("manifest", type=Path, help="Path to dev/development/master manifest JSON.")
    parser.add_argument(
        "--enforcement",
        choices=("active", "disabled", "evaluate"),
        help="Override enforcement for a controlled rollout or rollback.",
    )
    parser.add_argument("--output", type=Path, help="Write JSON to this file instead of stdout.")
    args = parser.parse_args(argv)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    payload = render_payload(manifest, args.enforcement)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

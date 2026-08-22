"""Tests for rendering GitHub Rulesets API payloads from tracked manifests."""

from __future__ import annotations

import json
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.ci.render_github_ruleset_payload import render_payload  # noqa: E402


def test_render_payload_strips_local_audit_metadata():
    manifest = json.loads(
        (_REPO_ROOT / ".github" / "governance" / "rulesets" / "dev.json").read_text(
            encoding="utf-8"
        )
    )
    payload = render_payload(manifest)
    assert payload["name"] == "dev-ruleset"
    assert payload["enforcement"] == "evaluate"
    assert "branch" not in payload
    assert "_governance_notes" not in payload
    assert "_activation" not in payload


def test_render_payload_can_override_enforcement():
    payload = render_payload(
        {
            "branch": "dev",
            "name": "dev-ruleset",
            "target": "branch",
            "enforcement": "evaluate",
            "conditions": {},
            "rules": [],
        },
        enforcement="active",
    )
    assert payload["enforcement"] == "active"

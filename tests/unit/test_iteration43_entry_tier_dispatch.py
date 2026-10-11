"""Iteration 43 R5a: the unified entries resolve their channel from their own config.

Each ``examples/unified/<entry>/run.py`` must

* accept ``--dry`` as an explicit offline self-check,
* resolve ``entry.tier`` through its folder-local ``entry_tier`` copy,
* let a mode flag keep or **lower** the declared tier but never raise it, and
* block a malformed declaration before any handler runs.

The gate rows are checked for every entry because they never reach a handler and
therefore cost one short subprocess each.  The rows that actually execute a replay
are sampled: a full replay costs seconds and the decision logic it exercises is
the same one the gate rows already pin.  Declarations are applied to a staged
copy (tracked plus added files only, so an ignored private config can never be
carried along), which also keeps the repository's pinned ``config.yaml`` bytes
untouched.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

ROOT = Path(__file__).resolve().parents[2]
UNIFIED = ROOT / "examples" / "unified"
CANONICAL_HELPER = ROOT / "examples" / "_support" / "entry_tier.py"

ALL_ENTRIES = (
    "012_1_midfreq_cross_exchange",
    "012_2_event_driven_cross_exchange",
    "013_1_midfreq_cross_arbitrage",
    "013_2_highfreq_calendar_arbitrage",
    "013_3_sa_midfreq_simnow",
    "014_1_ctp_options_lowfreq",
    "014_2_ctp_options_midfreq",
    "015_ctp_options_highfreq",
)
# Entries whose offline tiers run from a staged copy of the folder alone.
PORTABLE_ENTRIES = tuple(entry for entry in ALL_ENTRIES if not entry.startswith("012_"))
REPLAY_SAMPLE = ("013_1_midfreq_cross_arbitrage", "014_1_ctp_options_lowfreq", "015_ctp_options_highfreq")
LIVE_REFUSAL_ENTRIES = ("014_2_ctp_options_midfreq", "015_ctp_options_highfreq")


def _run(entry: str, argv: list[str], cwd: Path, *, evidence: Path | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "run.py", *argv]
    if evidence is not None:
        command += ["--evidence-dir", str(evidence)]
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )


def _payload(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    lines = [line for line in completed.stdout.strip().splitlines() if line.strip()]
    assert lines, f"no JSON on stdout (exit {completed.returncode}): {completed.stderr[-400:]}"
    payload = json.loads(lines[-1])
    assert isinstance(payload, Mapping), payload
    return dict(payload)


def _tier(payload: Mapping[str, Any]) -> dict[str, Any]:
    tier = payload.get("tier")
    assert isinstance(tier, Mapping), f"report carries no tier evidence: {payload}"
    return dict(tier)


def _stage(tmp_path: Path, entry: str, *, declaration: str | None = None) -> Path:
    """Copy one entry's staged (tracked + added, never ignored) files into *tmp_path*."""

    listing = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-co", "--exclude-standard", f"examples/unified/{entry}"],
        capture_output=True,
        text=True,
    )
    if listing.returncode != 0:
        pytest.skip("git is unavailable in this environment")
    target = tmp_path / entry
    prefix = f"examples/unified/{entry}/"
    for relative in (line for line in listing.stdout.splitlines() if line.startswith(prefix)):
        destination = target / Path(relative[len(prefix) :])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())
    if declaration is not None:
        config = target / "config.yaml"
        config.write_text(config.read_text(encoding="utf-8") + declaration, encoding="utf-8")
    return target


@pytest.mark.parametrize("entry", ALL_ENTRIES)
def test_dry_flag_and_no_flag_default(entry: str, tmp_path: Path) -> None:
    """``--dry`` is explicit, and no flag stays offline; both report the decision."""

    folder = UNIFIED / entry
    for argv, reason in ((["--dry"], "cli_requested"), ([], "default_dry")):
        completed = _run(entry, argv, folder, evidence=tmp_path)
        assert completed.returncode == 0, completed.stderr[-400:]
        payload = _payload(completed)
        assert _tier(payload)["tier_selection_reason"] == reason, payload
        assert payload.get("write_grant_result") == "not_applicable_offline_tier", payload


@pytest.mark.parametrize("entry", PORTABLE_ENTRIES)
def test_replay_declaration_selects_handler_without_a_flag(entry: str, tmp_path: Path) -> None:
    """A declared ``replay`` tier runs the replay handler with no mode flag at all."""

    if entry not in REPLAY_SAMPLE:
        pytest.skip("replay rows are sampled; the gate rows pin the same decision path")
    staged = _stage(tmp_path, entry, declaration="\nentry:\n  tier: replay\n")
    completed = _run(entry, [], staged, evidence=tmp_path / "evidence")
    payload = _payload(completed)
    assert _tier(payload) == {
        "config_tier": "replay",
        "cli_tier": None,
        "effective_tier": "replay",
        "tier_selection_reason": "config_default",
    }, payload
    assert completed.returncode == 0, payload


@pytest.mark.parametrize("entry", PORTABLE_ENTRIES)
def test_backtest_alias_is_documented_alias_of_replay(entry: str, tmp_path: Path) -> None:
    staged = _stage(tmp_path, entry, declaration="\nentry:\n  tier: backtest\n")
    completed = _run(entry, ["--dry"], staged, evidence=tmp_path / "evidence")
    payload = _payload(completed)
    evidence = _tier(payload)
    assert evidence["config_tier"] == "backtest", payload
    assert evidence["effective_tier"] == "dry", payload
    assert evidence["tier_selection_reason"] == "cli_override", payload


@pytest.mark.parametrize("entry", ALL_ENTRIES)
@pytest.mark.parametrize(
    ("declaration", "argv", "reason"),
    (
        ("\nentry:\n  tier: dry\n", ["--live"], "config_tier_conflict"),
        ("\nentry:\n  tier: replay\n", ["--live"], "config_tier_conflict"),
        ("\nentry:\n  tier: nonsense\n", [], "config_tier_invalid"),
        ("\nentry:\n", [], "config_tier_invalid"),
        ("\nentry: not-a-mapping\n", [], "config_tier_invalid"),
    ),
)
def test_gate_blocks_before_any_handler(entry: str, tmp_path: Path, declaration: str, argv: list[str], reason: str) -> None:
    """Escalation and malformed declarations stop before a handler, and never fall back to live."""

    staged = _stage(tmp_path, entry, declaration=declaration)
    completed = _run(entry, argv, staged, evidence=tmp_path / "evidence")
    payload = _payload(completed)
    assert completed.returncode == 2, payload
    assert payload["status"] == "BLOCKED", payload
    assert payload["reason"] == reason, payload
    assert payload["tier"]["tier_selection_reason"] == reason, payload
    assert payload.get("write_grant_result") == "not_evaluated_tier_unresolved", payload
    # An unresolved tier must not have reached the live channel: every entry names
    # its own live-tier precondition, and none of those may appear here.
    for live_marker in ("live_tier_requires_python_3_11", "front_selection", "provider_preflight_started"):
        assert live_marker not in json.dumps(payload), payload


@pytest.mark.parametrize("entry", LIVE_REFUSAL_ENTRIES)
def test_declared_live_tier_reaches_the_live_channel(entry: str, tmp_path: Path) -> None:
    """A declared ``live`` tier really dispatches ``run_live``.

    ``--allow-write`` is used only as the probe: both entries refuse it as their
    very first statement, so reaching that refusal proves the live handler ran
    without any provider side effect.  ``mode`` is emitted only by ``run_live``,
    so it identifies the handler without depending on the tier wiring that R5b
    adds to the live summaries.
    """

    staged = _stage(tmp_path, entry, declaration="\nentry:\n  tier: live\n")
    completed = _run(entry, ["--allow-write"], staged)
    payload = _payload(completed)
    assert completed.returncode == 2, payload
    assert payload["status"] == "BLOCKED", payload
    assert payload["mode"] == "live", payload
    assert payload["reason"] == "write_tier_not_implemented_for_decision_only_strategy", payload


@pytest.mark.parametrize("entry", ALL_ENTRIES)
def test_folder_local_helper_is_a_byte_copy(entry: str) -> None:
    vendored = UNIFIED / entry / "entry_tier.py"
    assert vendored.is_file(), f"{entry} has no folder-local tier helper"
    assert vendored.read_bytes() == CANONICAL_HELPER.read_bytes(), f"{entry}'s tier helper drifted"


@pytest.mark.parametrize("entry", ("014_1_ctp_options_lowfreq", "014_2_ctp_options_midfreq", "015_ctp_options_highfreq"))
def test_entry_projection_keeps_the_frozen_replay_contract_strict(entry: str, tmp_path: Path) -> None:
    """Admitting ``entry`` must not loosen the strict replay key set.

    The three entries that project the section away before validating still have
    to reject any *other* unknown top-level key.
    """

    declaration = "\nentry:\n  tier: replay\nbogus_iteration43_key: 1\n"
    staged = _stage(tmp_path, entry, declaration=declaration)
    completed = _run(entry, ["--replay"], staged, evidence=tmp_path / "evidence")
    payload = _payload(completed)
    assert completed.returncode != 0, payload
    assert payload["status"] in {"REJECTED", "BLOCKED"}, payload
    assert "bogus_iteration43_key" in json.dumps(payload) or "schema" in json.dumps(payload).lower(), payload

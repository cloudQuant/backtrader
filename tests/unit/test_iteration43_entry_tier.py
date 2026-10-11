"""Truth-table contract for the config-selected entry tier of the unified examples."""

from __future__ import annotations

import importlib

import pytest

entry_tier = importlib.import_module("examples._support.entry_tier")


def _config(tier):
    if tier is None:
        return {"mode": "replay"}
    return {"entry": {"tier": tier}}


@pytest.mark.parametrize(
    ("declared", "cli", "expected_tier", "expected_reason"),
    [
        # No declaration: the CLI keeps selecting the channel, as before.
        (None, None, "dry", entry_tier.REASON_DEFAULT_DRY),
        (None, "dry", "dry", entry_tier.REASON_CLI_REQUESTED),
        (None, "replay", "replay", entry_tier.REASON_CLI_REQUESTED),
        (None, "live", "live", entry_tier.REASON_CLI_REQUESTED),
        # An explicit dry caps the example: no mode flag may lift it.
        ("dry", None, "dry", entry_tier.REASON_CONFIG_DEFAULT),
        ("dry", "dry", "dry", entry_tier.REASON_CONFIG_DEFAULT),
        ("dry", "replay", "dry", entry_tier.REASON_CONFLICT),
        ("dry", "live", "dry", entry_tier.REASON_CONFLICT),
        # replay (and its documented backtest alias) may only be lowered.
        ("replay", None, "replay", entry_tier.REASON_CONFIG_DEFAULT),
        ("backtest", None, "replay", entry_tier.REASON_CONFIG_DEFAULT),
        ("backtest", "dry", "dry", entry_tier.REASON_CLI_OVERRIDE),
        ("backtest", "replay", "replay", entry_tier.REASON_CONFIG_DEFAULT),
        ("backtest", "live", "replay", entry_tier.REASON_CONFLICT),
        # live may be lowered to replay or the offline self-check.
        ("live", None, "live", entry_tier.REASON_CONFIG_DEFAULT),
        ("live", "dry", "dry", entry_tier.REASON_CLI_OVERRIDE),
        ("live", "replay", "replay", entry_tier.REASON_CLI_OVERRIDE),
        ("live", "live", "live", entry_tier.REASON_CONFIG_DEFAULT),
    ],
)
def test_tier_truth_table(declared, cli, expected_tier, expected_reason) -> None:
    decision = entry_tier.decide(_config(declared), cli)

    assert decision.effective_tier == expected_tier
    assert decision.reason == expected_reason


@pytest.mark.parametrize(
    "config",
    [
        {"entry": None},
        {"entry": "live"},
        {"entry": {"tier": None}},
        {"entry": {"tier": 7}},
        {"entry": {"tier": "production"}},
        {"entry": {"tier": ""}},
    ],
)
def test_malformed_or_unknown_tier_is_rejected_not_defaulted(config) -> None:
    decision = entry_tier.decide(config, None)

    assert decision.reason == entry_tier.REASON_INVALID
    assert entry_tier.invalid(decision)
    assert decision.effective_tier == "dry"


def test_conflicts_are_flagged_for_the_caller() -> None:
    conflict = entry_tier.decide(_config("dry"), "live")
    ok = entry_tier.decide(_config("live"), "replay")

    assert entry_tier.conflict(conflict)
    assert not entry_tier.conflict(ok)


def test_evidence_records_both_requests_and_the_resolved_tier() -> None:
    evidence = entry_tier.decide(_config("backtest"), "dry").as_evidence()

    assert evidence == {
        "config_tier": "backtest",
        "cli_tier": "dry",
        "effective_tier": "dry",
        "tier_selection_reason": entry_tier.REASON_CLI_OVERRIDE,
    }


def test_absent_entry_section_keeps_the_legacy_offline_default() -> None:
    decision = entry_tier.decide({"mode": "replay", "venue": "simnow"}, None)

    assert decision.config_tier is None
    assert decision.effective_tier == "dry"
    assert decision.reason == entry_tier.REASON_DEFAULT_DRY

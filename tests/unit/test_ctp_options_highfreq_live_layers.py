"""Live evidence layering coverage for the Iteration 30 example.

The layers are derived from evidence the run already collected, so a caller
cannot claim a higher layer than the proof it holds: L0/L1 may pass while L2 is
blocked by the upstream qualification gap.
"""

from __future__ import annotations

import importlib

runner = importlib.import_module("examples.015_ctp_options_highfreq.run")

SYMBOLS = ("FG701", "FG701C970", "FG701P970")

BINDING = {
    "actual_environment_profile": "set1_group1_vpn",
    "profile_family_prefix": "set1",
    "connection_generation": 1,
    "trading_day": "20260917",
    "account_fingerprint_sha256": "a" * 64,
}


def _layers(**overrides):
    kwargs = {
        "binding": BINDING,
        "expected_symbols": SYMBOLS,
        "accepted_symbols": list(SYMBOLS),
        "tick_counts": dict.fromkeys(SYMBOLS, 3),
        "callback_counts": {"tick": 9, "bar": 0, "idle": 100, "next": 0},
        "idle_without_trusted_now_count": 0,
        "clock_violation_count": 0,
        "clock_rejection_latched": False,
        "confirmed_cohorts": 0,
        "last_quality_flags": ("SOURCE_CLOCK_UNVERIFIED", "UPSTREAM_EXECUTION_INELIGIBLE"),
        "execution_eligible_ticks": 0,
        "forbidden_write_attempts": {},
        "last_screen": None,
        "ordinary_intent_count": 0,
    }
    kwargs.update(overrides)
    return runner.build_live_evidence_layers(**kwargs)


def test_connection_layer_passes_and_reports_the_bound_session() -> None:
    layers = _layers()
    l0 = layers["L0_connection_read_only"]
    assert l0["status"] == "PASS"
    assert l0["evidence"]["actual_environment_profile"] == "set1_group1_vpn"
    assert l0["evidence"]["profile_family_prefix"] == "set1"
    assert l0["evidence"]["forbidden_write_attempts"] == {}


def test_connection_layer_fails_when_a_write_attempt_is_recorded() -> None:
    layers = _layers(forbidden_write_attempts={"pump": 1})
    assert layers["L0_connection_read_only"]["status"] == "FAIL"


def test_subscription_layer_requires_every_expected_leg() -> None:
    layers = _layers(accepted_symbols=["FG701"])
    l1 = layers["L1_subscription_and_ticks"]
    assert l1["status"] == "INCOMPLETE"
    assert l1["evidence"]["missing_symbols"] == ["FG701C970", "FG701P970"]


def test_subscription_layer_passes_with_per_leg_counts_and_idle_health() -> None:
    l1 = _layers()["L1_subscription_and_ticks"]
    assert l1["status"] == "PASS"
    assert l1["evidence"]["tick_counts"] == dict.fromkeys(SYMBOLS, 3)
    assert l1["evidence"]["idle_without_trusted_now_count"] == 0
    assert l1["evidence"]["clock_violation_count"] == 0
    assert l1["evidence"]["clock_rejection_latched"] is False


def test_qualification_layer_is_blocked_when_the_upstream_never_qualifies() -> None:
    l2 = _layers()["L2_quote_qualification"]
    assert l2["status"] == "BLOCKED_BY_UPSTREAM_QUALIFICATION"
    assert l2["reason"] == "UPSTREAM_EXECUTION_NOT_ISSUED"
    assert l2["evidence"]["last_quality_flags"] == [
        "SOURCE_CLOCK_UNVERIFIED",
        "UPSTREAM_EXECUTION_INELIGIBLE",
    ]
    assert l2["evidence"]["execution_eligible_ticks"] == 0


def test_qualification_layer_passes_only_with_eligible_unflagged_ticks() -> None:
    l2 = _layers(last_quality_flags=(), execution_eligible_ticks=9)["L2_quote_qualification"]
    assert l2["status"] == "PASS"


def test_cohort_and_screen_layers_follow_the_qualification_block() -> None:
    layers = _layers()
    assert layers["L3_cohort"]["status"] == "BLOCKED_BY_UPSTREAM_QUALIFICATION"
    assert layers["L3_cohort"]["evidence"]["confirmed_cohorts"] == 0
    assert layers["L4_economic_screen"]["status"] == "BLOCKED_BY_UPSTREAM_QUALIFICATION"
    assert layers["L4_economic_screen"]["evidence"]["last_screen"] is None


def test_cohort_layer_reports_confirmed_cohorts_and_screen_when_reachable() -> None:
    layers = _layers(
        last_quality_flags=(),
        execution_eligible_ticks=9,
        confirmed_cohorts=2,
        last_screen={"conversion": {"net_screen_cny": "30", "eligible": True}},
        ordinary_intent_count=1,
    )
    assert layers["L3_cohort"]["status"] == "PASS"
    assert layers["L3_cohort"]["evidence"]["confirmed_cohorts"] == 2
    assert layers["L4_economic_screen"]["status"] == "PASS"
    assert layers["L4_economic_screen"]["evidence"]["ordinary_intent_count"] == 1


def test_layer_order_is_frozen_and_observable() -> None:
    layers = _layers()
    assert tuple(layers) == runner.LIVE_EVIDENCE_LAYER_ORDER

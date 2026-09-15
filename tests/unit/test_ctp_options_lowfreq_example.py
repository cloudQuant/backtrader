"""Independent contract tests for the Iteration 23 replay example."""

from __future__ import annotations

import ast
import copy
import importlib
import json
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "014_1_ctp_options_lowfreq"


def _load_runner():
    return importlib.import_module("examples.014_1_ctp_options_lowfreq.run")


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


def test_example_packages_keep_same_named_modules_isolated():
    low_timing = importlib.import_module("examples.014_1_ctp_options_lowfreq.execution_timing")
    mid_timing = importlib.import_module("examples.014_2_ctp_options_midfreq.execution_timing")
    high_timing = importlib.import_module("examples.015_ctp_options_highfreq.execution_timing")

    assert low_timing.__package__ == "examples.014_1_ctp_options_lowfreq"
    assert mid_timing.__package__ == "examples.014_2_ctp_options_midfreq"
    assert high_timing.__package__ == "examples.015_ctp_options_highfreq"
    assert low_timing is not mid_timing
    assert mid_timing is not high_timing


def test_directory_is_a_direct_self_contained_strategy_entrypoint():
    required = {"config.yaml", "run.py", "ctp_options_lowfreq_strategy.py", "README.md"}
    assert required.issubset({path.name for path in EXAMPLE.iterdir()})
    for source in (EXAMPLE / "run.py", EXAMPLE / "ctp_options_lowfreq_strategy.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        assert not any(name == "examples" or name.startswith("examples.") for name in imported)
        source_text = source.read_text(encoding="utf-8")
        assert "sys.path" not in source_text
        assert "importlib" not in source_text
        assert "pkgutil" not in source_text


def test_replay_runs_a_complete_local_basket_and_never_reports_external_writes(runner):
    config = runner.load_config()
    report = runner.run_replay(config, "eligible")
    repeated = runner.run_replay(config, "eligible")

    assert report["status"] == "LOCAL_REPLAY_PASS"
    assert report["state"] == "FLAT"
    assert report["flat_status"] == "LOCAL_BASKET_FLAT_UNVERIFIED"
    assert report["ordinary_decisions"] == 2
    assert len(report["orders"]) == 6
    assert report["entry_confirmation_bars"] == 2
    assert report["minimum_holding_minutes"] == 30
    kinds = [event["kind"] for event in report["events"]]
    assert kinds == [
        "entry_confirmation_pending",
        "entry_decision",
        "basket_open",
        "exit_decision",
        "local_basket_flat_unverified",
    ]
    exit_event = next(event for event in report["events"] if event["kind"] == "exit_decision")
    assert exit_event["held_minutes"] >= report["minimum_holding_minutes"]
    assert all(size == 0.0 for size in report["positions"].values())
    assert report["external_request_counts"] == {"network": 0, "order_write": 0}
    assert "no CTP request" in report["evidence_boundary"]
    assert report["barrier"]["clock_mode"] == "replay"
    assert report["barrier"]["late_bar_policy"] == "retired_bucket_no_backfill"
    assert report["timing_projection"]["fill_timing"]["status"] == "FILL_TIMING_UNKNOWN"
    assert report["timing_projection"]["confirmed_fill_quantity"] == 0
    assert report["timing_projection"]["risk_actions"] == []
    evidence = report["evidence_package"]
    assert set(evidence) == {
        "bar_cohorts.jsonl",
        "indicative_scores.jsonl",
        "bar_only_access_audit.json",
        "capital_path_states.jsonl",
    }
    assert evidence["bar_cohorts.jsonl"]
    assert any(row["ready"] for row in evidence["bar_cohorts.jsonl"])
    assert evidence["indicative_scores.jsonl"]
    assert evidence["bar_only_access_audit.json"]["external_write_status"] == "ZERO_EXTERNAL_WRITE"
    assert evidence["bar_only_access_audit.json"]["forbidden_market_inputs"] == [
        "tick",
        "bid",
        "ask",
        "order_book",
        "last_trade",
    ]
    assert evidence["capital_path_states.jsonl"]
    assert report["evidence_package_sha256"] == repeated["evidence_package_sha256"]
    assert report == repeated


def test_no_edge_and_budget_rejection_are_fail_closed(runner):
    config = runner.load_config()
    no_edge = runner.run_replay(config, "no_edge")
    budget = runner.run_replay(config, "budget_reject")

    assert no_edge["ordinary_decisions"] == 0
    assert no_edge["orders"] == []
    assert budget["ordinary_decisions"] == 0
    assert budget["orders"] == []
    assert budget["rejections"] == ["BUDGET_REJECTED"]


@pytest.mark.parametrize("mode", ("shadow", "simnow", "production"))
def test_non_replay_api_entry_is_fail_closed_before_cerebro(mode, runner):
    config = copy.deepcopy(runner.load_config())
    config["mode"] = mode

    with pytest.raises(runner.RunnerConfigurationError, match="REPLAY_MODE_REQUIRED"):
        runner.run_replay(config, "no_edge")


def test_misaligned_three_leg_closed_bars_reset_confirmation_and_do_not_trade(runner):
    report = runner.run_replay(runner.load_config(), "misaligned")

    assert report["state"] == "FLAT"
    assert report["ordinary_decisions"] == 0
    assert report["orders"] == []
    assert "TRIPLE_LEG_TIMESTAMP_MISMATCH" in report["rejections"]
    assert not any(event["kind"] == "entry_decision" for event in report["events"])


def test_idle_probe_has_no_local_clock_fallback_and_explicit_facts_are_separate(runner):
    config = runner.load_config()
    idle = runner.run_replay(config, "eligible", invoke_idle_probe=True)
    assert idle["timing_projection"]["clock_rejection_latched"] is True
    assert idle["timing_projection"]["risk_actions"] == []
    facts = [
        {
            "leg": symbol,
            "quantity": 1,
            "status": "completed",
            "fill_lower_ns": 0,
            "fill_upper_ns": 0,
            "source": "synthetic_timestamped_execution",
        }
        for symbol in ("CZCE.SA701", "CZCE.SA701C1080", "CZCE.SA701P1080")
    ]
    explicit = runner.run_replay(config, "eligible", synthetic_execution_facts=facts)
    assert explicit["timing_projection"]["fill_timing"]["status"] == "FILL_TIMING_UNKNOWN"
    assert explicit["timing_projection"]["confirmed_fill_quantity"] == 0
    assert explicit["timing_projection"]["fill_timing"]["possible_exposure"] is True
    assert explicit["timing_projection"]["quarantined_execution_facts"]
    assert all(order["fill_timing"] == "FILL_TIMING_UNKNOWN" for order in explicit["orders"])


def test_config_unknown_field_is_rejected_before_replay(tmp_path, runner):
    config = copy.deepcopy(runner.load_config())
    config["unexpected"] = True

    with pytest.raises(runner.RunnerConfigurationError, match="declared schema"):
        runner.validate_config(config)

    external_path = tmp_path / "invalid.yaml"
    external_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(runner.RunnerConfigurationError, match="must remain inside"):
        runner.load_config(external_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("capital_limit", 10001, "CNY 10000"),
        ("ordinary_limit", 8001, "CNY 8000"),
        ("recovery_reserve", 1999, "at least CNY 2000"),
    ),
)
def test_fixed_budget_boundaries_are_rejected_before_replay(
    tmp_path, runner, field, value, message
):
    config = copy.deepcopy(runner.load_config())
    config["budget"][field] = value

    with pytest.raises(runner.RunnerConfigurationError, match=message):
        runner.validate_config(config)


@pytest.mark.parametrize(
    ("group", "field", "value"),
    (
        ("strategy_params", "entry_z", 2.49),
        ("strategy_params", "minimum_score", 19),
        ("timing", "session_stop_entry_seconds", 1799),
        ("timing", "session_exit_seconds", 599),
        ("timing", "session_handover_seconds", 179),
    ),
)
def test_frozen_signal_and_session_thresholds_cannot_be_weakened(runner, group, field, value):
    config = copy.deepcopy(runner.load_config())
    config[group][field] = value
    with pytest.raises(runner.RunnerConfigurationError):
        runner.validate_config(config)


def test_stricter_signal_and_session_thresholds_remain_valid(runner):
    config = copy.deepcopy(runner.load_config())
    config["strategy_params"].update(entry_z=2.51, minimum_score=21)
    config["timing"].update(
        session_stop_entry_seconds=1900,
        session_exit_seconds=700,
        session_handover_seconds=200,
    )
    runner.validate_config(config)


class _CallbackOrder:
    Submitted = 1
    Accepted = 2
    Partial = 3
    Completed = 4
    Rejected = 5

    def __init__(self, *, ref, symbol, buy, status, created_size=1, executed_size=1):
        self.ref = ref
        self.status = status
        self.data = SimpleNamespace(_name=symbol)
        self.created = SimpleNamespace(size=created_size)
        self.executed = SimpleNamespace(size=executed_size, price=10.0)
        self._buy = buy

    def isbuy(self):
        return self._buy

    def getstatusname(self):
        return "Rejected"


def _callback_harness(strategy_type):
    strategy = object.__new__(strategy_type)
    strategy._planned_legs = [{"symbol": "P", "side": "buy", "size": 1}]
    strategy._leg_index = 0
    strategy._pending_order = None
    strategy._pending_order_ref = None
    strategy._submission_in_flight = True
    strategy._submitted_order_ids_by_leg = {}
    strategy._terminal_order_refs = set()
    strategy._state = "ENTERING"
    strategy._rejections = []
    strategy._cycle_events = []
    strategy._order_projection = []
    submitted = []
    strategy._record = lambda kind, **values: strategy._cycle_events.append(
        {"kind": kind, **values}
    )
    strategy._submit_next_leg = lambda: submitted.append("next")
    return strategy, submitted


def test_early_callback_is_correlated_and_foreign_or_partial_callbacks_halt(runner):
    strategy_type = runner.CtpOptionsLowfreqStrategy
    early, submitted = _callback_harness(strategy_type)
    strategy_type.notify_order(
        early,
        _CallbackOrder(ref=7, symbol="P", buy=True, status=_CallbackOrder.Completed),
    )
    assert early._leg_index == 1
    assert early._state == "ENTERING"
    assert early._submitted_order_ids_by_leg == {"P": {"7"}}
    assert submitted == ["next"]

    foreign, submitted = _callback_harness(strategy_type)
    foreign._submission_in_flight = False
    foreign._pending_order_ref = 7
    strategy_type.notify_order(
        foreign,
        _CallbackOrder(ref=8, symbol="P", buy=True, status=_CallbackOrder.Completed),
    )
    assert foreign._leg_index == 0
    assert foreign._state == "HALTED"
    assert foreign._rejections == ["UNEXPECTED_ORDER_CALLBACK"]
    assert submitted == []


def test_scoped_completed_protection_requires_confirmed_fill_before_next_leg(runner):
    strategy_type = runner.CtpOptionsLowfreqStrategy
    strict, submitted = _callback_harness(strategy_type)
    strict.p = SimpleNamespace(clock_provider=lambda: None)
    strict._confirmed_fill_by_leg = {}
    strategy_type.notify_order(
        strict,
        _CallbackOrder(ref=12, symbol="P", buy=True, status=_CallbackOrder.Completed),
    )
    assert strict._state == "HALTED"
    assert strict._leg_index == 0
    assert strict._rejections == ["PROTECTION_FILL_CONFIRMATION_REQUIRED"]
    assert submitted == []

    confirmed, submitted = _callback_harness(strategy_type)
    confirmed.p = SimpleNamespace(clock_provider=lambda: None)
    confirmed._confirmed_fill_by_leg = {"P": 1.0}
    strategy_type.notify_order(
        confirmed,
        _CallbackOrder(ref=13, symbol="P", buy=True, status=_CallbackOrder.Completed),
    )
    assert confirmed._state == "ENTERING"
    assert confirmed._leg_index == 1
    assert submitted == ["next"]

    partial, submitted = _callback_harness(strategy_type)
    strategy_type.notify_order(
        partial,
        _CallbackOrder(
            ref=9,
            symbol="P",
            buy=True,
            status=_CallbackOrder.Partial,
            executed_size=0.5,
        ),
    )
    assert partial._leg_index == 0
    assert partial._state == "HALTED"
    assert partial._rejections == ["PARTIAL_FILL_RECOVERY_REQUIRED"]
    assert submitted == []


def test_partial_is_not_terminal_and_late_completed_fact_is_kept_without_new_leg(runner):
    strategy_type = runner.CtpOptionsLowfreqStrategy
    strategy, submitted = _callback_harness(strategy_type)
    strategy._submit_next_leg = lambda: (
        submitted.append("next") if strategy._state != "HALTED" else None
    )
    partial_order = _CallbackOrder(
        ref=10,
        symbol="P",
        buy=True,
        status=_CallbackOrder.Partial,
        executed_size=0.5,
    )
    strategy_type.notify_order(strategy, partial_order)
    assert 10 not in strategy._terminal_order_refs
    assert strategy._state == "HALTED"

    completed_order = _CallbackOrder(
        ref=10,
        symbol="P",
        buy=True,
        status=_CallbackOrder.Completed,
        executed_size=1.0,
    )
    strategy_type.notify_order(strategy, completed_order)
    assert 10 in strategy._terminal_order_refs
    assert [item["status"] for item in strategy._order_projection] == ["partial", "completed"]
    assert strategy._state == "HALTED"
    assert submitted == []


def test_partial_to_canceled_keeps_terminal_fact_and_ignores_late_duplicate(runner):
    strategy_type = runner.CtpOptionsLowfreqStrategy
    strategy, submitted = _callback_harness(strategy_type)
    partial_order = _CallbackOrder(
        ref=11,
        symbol="P",
        buy=True,
        status=_CallbackOrder.Partial,
        executed_size=0.5,
    )
    strategy_type.notify_order(strategy, partial_order)
    canceled_order = _CallbackOrder(
        ref=11,
        symbol="P",
        buy=True,
        status=_CallbackOrder.Rejected,
        executed_size=0.5,
    )
    canceled_order.getstatusname = lambda: "Canceled"
    strategy_type.notify_order(strategy, canceled_order)
    strategy_type.notify_order(
        strategy,
        _CallbackOrder(
            ref=11,
            symbol="P",
            buy=True,
            status=_CallbackOrder.Completed,
            executed_size=1.0,
        ),
    )
    assert 11 in strategy._terminal_order_refs
    assert [item["status"] for item in strategy._order_projection] == ["partial", "canceled"]
    assert strategy._state == "HALTED"
    assert submitted == []


def test_shadow_mode_blocks_before_any_external_client_is_constructed():
    completed = subprocess.run(
        [sys.executable, "run.py", "--mode", "shadow"],
        cwd=EXAMPLE,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    report = json.loads(completed.stdout)
    assert report["status"] == "BLOCKED"
    assert report["external_request_counts"] == {"network": 0, "order_write": 0}

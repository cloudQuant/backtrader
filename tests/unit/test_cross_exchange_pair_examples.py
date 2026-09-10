import ast
import copy
from dataclasses import replace
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
MID = EXAMPLES / "012_1_midfreq_cross_exchange"
EVENT = EXAMPLES / "012_2_event_driven_cross_exchange"
MANIFEST = EXAMPLES / "strategy-candidate-manifest.json"
MODULES = {
    "012_1_midfreq_cross_exchange": importlib.import_module(
        "examples.012_1_midfreq_cross_exchange.run"
    ),
    "012_2_event_driven_cross_exchange": importlib.import_module(
        "examples.012_2_event_driven_cross_exchange.run"
    ),
}


def candidate_hash(candidate):
    payload = {
        key: value
        for key, value in candidate.items()
        if key not in {"candidate_sha256", "demo_approval"}
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            result.append(("." * node.level) + (node.module or ""))
    return result, tree


def test_examples_are_source_self_contained_and_have_no_path_mutation():
    forbidden = ("cross_exchange_arbitrage_support", "012_1_midfreq", "_btapi_")
    for directory in (MID, EVENT):
        for filename in ("run.py", "strategy.py"):
            path = directory / filename
            names, tree = imports(path)
            source = path.read_text(encoding="utf-8")
            assert "sys.path" not in source
            assert not any(token in name for name in names for token in forbidden)
            assert not any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "__import__"
                for node in ast.walk(tree)
            )


def test_cross_venue_planning_and_candidate_policy_do_not_live_in_backtrader_utils():
    assert not (ROOT / "backtrader" / "utils" / "cross_exchange.py").exists()
    assert not (ROOT / "backtrader" / "utils" / "demo_approval.py").exists()
    for directory in (MID, EVENT):
        runner_source = (directory / "run.py").read_text(encoding="utf-8")
        strategy_source = (directory / "strategy.py").read_text(encoding="utf-8")
        assert "bt_api_py" in runner_source
        assert "examples.strategy_candidate_approval" in runner_source
        assert "bt_api_py" in strategy_source
        assert "backtrader.utils." not in runner_source
        assert "backtrader.utils." not in strategy_source


def test_event_strategy_neither_imports_nor_inherits_mid_strategy():
    names, tree = imports(EVENT / "strategy.py")
    assert not any("012_1" in name for name in names)
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    hft_strategy = classes["CrossExchangeArbitrageStrategy"]
    assert [ast.unparse(base) for base in hft_strategy.bases] == ["bt.Strategy"]
    assert "RobustBasisWindow" not in classes


def test_manifest_uniquely_resolves_two_runnable_candidates():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    candidates = data["candidates"]
    assert len(candidates) == 2
    assert {row["strategy_id"] for row in candidates} == set(MODULES)
    for candidate in candidates:
        assert candidate["candidate_sha256"] == candidate_hash(candidate)
        directory = (MANIFEST.parent / candidate["resolved_example_path"]).resolve()
        assert directory in {MID.resolve(), EVENT.resolve()}
        assert (directory / candidate["entrypoint"]).is_file()
        assert (directory / candidate["strategy_module"]).is_file()
        assert (
            candidate["strategy_sha256"]
            == hashlib.sha256((directory / candidate["strategy_module"]).read_bytes()).hexdigest()
        )
        assert (
            candidate["runner_sha256"]
            == hashlib.sha256((directory / candidate["entrypoint"]).read_bytes()).hexdigest()
        )
        assert (
            candidate["config_sha256"]
            == hashlib.sha256((directory / "config.yaml").read_bytes()).hexdigest()
        )
        assert candidate["strategy_class"] == "CrossExchangeArbitrageStrategy"
        assert candidate["allowed_modes"] == ["replay", "shadow"]
        assert candidate["research_status"] == "RESEARCH_REJECTED"
        assert candidate["oos"]["status"] == "NOT_CONSUMED_TRAINING_SCREEN_FAILED"
        assert candidate["oos"]["demo_pair_eligible"] is False
        assert candidate["economic_screen"]["status"] == "RESEARCH_REJECTED"
        evidence_path = (MANIFEST.parent / candidate["economic_screen"]["path"]).resolve()
        assert (
            candidate["economic_screen"]["sha256"]
            == hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        )
    event_candidate = next(row for row in candidates if row["strategy_id"].startswith("012_2"))
    assert event_candidate["hft_label"] == "event_driven"
    assert event_candidate["hft_gate"]["status"] == "FAIL"
    assert event_candidate["selection_adr"]["lead_lag"].startswith("NOT_ADMITTED")
    assert event_candidate["selection_adr"]["maker_taker"].startswith("DEFERRED")


@pytest.mark.parametrize("strategy_id", tuple(MODULES))
def test_runner_and_strategy_import_normally_without_dynamic_loader(strategy_id):
    runner = MODULES[strategy_id]
    strategy = importlib.import_module(f"examples.{strategy_id}.strategy")

    assert strategy_id == runner.STRATEGY_ID
    assert strategy.CrossExchangeArbitrageStrategy.__module__.endswith(".strategy")


@pytest.mark.parametrize("strategy_id", tuple(MODULES))
def test_runner_binds_account_maximum_loss_threshold_into_sdk_config(strategy_id, monkeypatch):
    runner = MODULES[strategy_id]
    risk = replace(
        runner.risk_from_config(runner.load_config()),
        account_maximum_loss_bps="17.125",
    )
    captured = {}

    def fake_store(**kwargs):
        captured.update(kwargs)
        return captured

    monkeypatch.setattr(runner, "BtApiStore", fake_store)

    store = runner.build_store("shadow", risk=risk)

    assert store["config"]["account_maximum_loss_bps"] == "17.125"


@pytest.mark.parametrize("strategy_id", tuple(MODULES))
@pytest.mark.parametrize("scenario", ("profitable", "loss", "no_edge", "partial", "unknown", "gap"))
def test_replay_mechanics_fixtures_have_stable_report_contract(strategy_id, scenario):
    report = MODULES[strategy_id].run_replay(scenario)

    assert report["status"] == "FORMULA_CHECK_PASS"
    assert report["evidence_level"] == "R0_FORMULA_FIXTURE"
    assert report["research_status"] == "RESEARCH_REJECTED"
    assert report["profitability_claim"] == "NONE_SYNTHETIC_FIXTURE_ONLY"
    for field in (
        "gross_pnl",
        "net_pnl",
        "cost_breakdown",
        "fee_source",
        "fee_rate_per_fill",
        "maximum_drawdown",
        "win_rate",
        "expectancy_per_trade",
        "latency_ms",
        "markouts_quote",
        "unhedged_duration_seconds",
        "reject_reasons",
    ):
        assert field in report
    assert report["orders_submitted"] == report["fills"] == 0
    assert report["execution_status"] == "NOT_RUN"
    assert report["partial_fill_ratio"] is None
    assert report["gross_pnl"] is report["net_pnl"] is None
    assert report["maximum_drawdown"] is report["win_rate"] is None
    assert report["expectancy_per_trade"] is None
    if scenario == "unknown":
        assert report["final_state"] == "FORMULA_UNKNOWN_BRANCH"
    else:
        assert report["final_state"] == "NO_EXECUTION"


@pytest.mark.parametrize("strategy_id", tuple(MODULES))
def test_replay_business_projection_is_stable_and_excludes_trade_logger_telemetry(strategy_id):
    runner = MODULES[strategy_id]
    first = runner.run_replay("no_edge")
    second = runner.run_replay("no_edge")

    assert first["business_summary"] == runner.business_summary(first)
    assert first["business_summary_hash"] == runner.business_summary_hash(first)
    assert first["business_summary"] == second["business_summary"]
    assert first["business_summary_hash"] == second["business_summary_hash"]

    telemetry_changed = copy.deepcopy(first)
    telemetry_changed["trade_logger"] = {
        "run_id": "different-observer-run",
        "generated_at": "2026-09-10T00:02:00+00:00",
        "finalized_at": "2026-09-10T00:02:01+00:00",
        "monitoring": {"counts": {"observer_callbacks": 999}},
    }
    assert runner.business_summary_hash(telemetry_changed) == first["business_summary_hash"]

    business_changed = copy.deepcopy(telemetry_changed)
    business_changed["final_state"] = "DIFFERENT_BUSINESS_STATE"
    assert runner.business_summary_hash(business_changed) != first["business_summary_hash"]


@pytest.mark.parametrize("strategy_id", tuple(MODULES))
@pytest.mark.parametrize(
    ("strategy", "message"),
    (
        (
            SimpleNamespace(
                stats=SimpleNamespace(trade_logger=SimpleNamespace(final_report=lambda: None))
            ),
            "TradeLogger final report is unavailable",
        ),
        (
            SimpleNamespace(
                stats=SimpleNamespace(
                    trade_logger=SimpleNamespace(
                        final_report=lambda: {"finalized": False, "extensions": {"cross_venue": {}}}
                    )
                )
            ),
            "TradeLogger final report is unavailable",
        ),
        (
            SimpleNamespace(
                stats=SimpleNamespace(
                    trade_logger=SimpleNamespace(
                        final_report=lambda: {"finalized": True, "extensions": {}}
                    )
                )
            ),
            "TradeLogger final report is missing cross_venue evidence",
        ),
    ),
)
def test_trade_logger_report_fails_closed_without_a_frozen_cross_venue_extension(
    strategy_id, strategy, message
):
    with pytest.raises(MODULES[strategy_id].RunnerConfigurationError, match=message):
        MODULES[strategy_id]._trade_logger_report(strategy)


@pytest.mark.parametrize("strategy_id", tuple(MODULES))
def test_post_run_reconciliation_is_a_hash_bound_revision_of_frozen_trade_logger_evidence(
    strategy_id,
):
    runner = MODULES[strategy_id]
    frozen = {
        "reconciliation_required": True,
        "remote_flat_proven": False,
        "confirmed_fill_events": 2,
    }
    reconciled = {
        **frozen,
        "reconciliation_required": False,
        "remote_flat_proven": True,
    }
    reconcile_snapshot = {"generation": 7, "positions": [], "open_orders": []}
    execution_summary = {"generation": 7, "identity_binding_sha256": "a" * 64}

    revision = runner._post_run_reconciliation_revision(
        frozen,
        reconciled,
        reconcile_snapshot,
        execution_summary,
    )

    assert frozen["remote_flat_proven"] is False
    assert revision["status"] == "APPLIED_AFTER_TRADE_LOGGER_FINALIZATION"
    assert revision["outcome"] == "REMOTE_FLAT_PROVEN"
    assert revision["frozen_trade_logger_extension"] == frozen
    assert revision["reconciled_cross_venue_extension"] == reconciled
    assert revision["frozen_trade_logger_extension_sha256"] == runner._canonical_hash(frozen)
    assert revision["reconciled_cross_venue_extension_sha256"] == runner._canonical_hash(reconciled)
    assert revision["reconcile_snapshot_sha256"] == runner._canonical_hash(reconcile_snapshot)
    assert revision["execution_summary_sha256"] == runner._canonical_hash(execution_summary)
    hash_payload = dict(revision)
    revision_hash = hash_payload.pop("revision_sha256")
    assert revision_hash == runner._canonical_hash(hash_payload)


@pytest.mark.parametrize("directory", (MID, EVENT))
def test_local_env_template_and_ignore_rules_have_no_values(directory):
    template = (directory / ".env.example").read_text(encoding="utf-8").splitlines()
    assert template
    assert all(line and line.endswith("=") and line.count("=") == 1 for line in template)
    ignored = (directory / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored
    assert "reports/" in ignored
    assert any("receipt" in line for line in ignored)


@pytest.mark.parametrize("directory", (MID, EVENT))
def test_readme_disclaims_profit_and_never_points_credentials_to_support(directory):
    readme = (directory / "README.md").read_text(encoding="utf-8")
    assert "不构成未来盈利保证" in readme or "不证明可持续盈利" in readme
    assert "cross_exchange_arbitrage_support/.env" not in readme
    assert "python -m" in readme


def test_frozen_configs_match_iteration_21_preregistration():
    mid = yaml.safe_load((MID / "config.yaml").read_text())["strategy_params"]
    event = yaml.safe_load((EVENT / "config.yaml").read_text())["strategy_params"]
    assert (mid["zscore_window"], mid["entry_zscore"], mid["confirmations"]) == (120, "3.0", 3)
    assert (mid["exit_zscore"], mid["maximum_holding_seconds"]) == ("0.5", "300.0")
    assert (mid["minimum_net_edge_bps"], mid["quantity_base"]) == ("1.0", "0.01")
    assert event["minimum_opportunity_lifetime_seconds"] == "0.500"
    assert event["maximum_quote_age_seconds"] == "0.50"
    assert event["maximum_venue_skew_seconds"] == "0.25"
    assert event["entry_deadline_seconds"] == event["hedge_deadline_seconds"] == "1.0"
    assert event["pair_deadline_seconds"] == "2.5"
    assert (event["minimum_net_edge_bps"], event["quantity_base"]) == ("1.0", "0.01")

"""Tests for iteration 71 Mypy typing governance, CI baseline pins, and pure annotation fixes."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    tomllib = None


REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "test.yml"


def _load_pyproject():
    if tomllib is None:
        pytest.skip("tomllib requires Python 3.11+")
    return tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))


def _module_pattern_matches(pattern: str, module_names):
    regex = "^" + re.escape(pattern).replace(r"\*", ".*") + "$"
    compiled = re.compile(regex)
    return [name for name in module_names if compiled.match(name)]


def _all_backtrader_modules():
    modules = []
    pkg_root = REPO_ROOT / "backtrader"
    for path in sorted(pkg_root.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        modules.append(".".join(parts))
    return modules


def test_pyproject_mypy_top_level_and_overrides_invariants():
    data = _load_pyproject()
    mypy_cfg = data["tool"]["mypy"]

    assert mypy_cfg["python_version"] == "3.8"
    assert mypy_cfg["no_site_packages"] is True
    assert mypy_cfg["ignore_missing_imports"] is True
    assert mypy_cfg["warn_unused_configs"] is True
    assert mypy_cfg["warn_unused_ignores"] is True
    assert mypy_cfg["show_error_codes"] is True

    overrides = mypy_cfg.get("overrides", [])
    assert overrides, "Expected granular [[tool.mypy.overrides]] entries"

    all_modules = _all_backtrader_modules()
    for entry in overrides:
        # Never allow blanket ignore_errors = true bypasses.
        assert entry.get("ignore_errors", False) is False
        modules = entry.get("module", [])
        if isinstance(modules, str):
            modules = [modules]
        assert modules, "Each mypy override must specify at least one module pattern"
        codes = entry.get("disable_error_code", [])
        assert codes, "Each mypy override must specify narrow disable_error_code entries"
        for pattern in modules:
            assert _module_pattern_matches(
                pattern, all_modules
            ), f"Mypy override pattern matches no module: {pattern}"


def test_strict_typed_modules_are_not_covered_by_mypy_overrides():
    data = _load_pyproject()
    overrides = data["tool"]["mypy"]["overrides"]
    all_patterns = []
    for entry in overrides:
        modules = entry["module"]
        if isinstance(modules, str):
            all_patterns.append(modules)
        else:
            all_patterns.extend(modules)

    strict_modules = [
        "backtrader.events",
        "backtrader.futures.calendar",
        "backtrader.research.factor_indicator",
        "backtrader.research.specs",
        "backtrader.research.strict",
        "backtrader.research.factor_report",
        "backtrader.factor_execution.factor_execution",
        "backtrader.factor_execution.factor_execution_facts",
        "backtrader.live_trading.run_status",
        "backtrader.live_trading.interface",
        "backtrader.trade",
        "backtrader.utils.log_message",
    ]
    for mod in strict_modules:
        matching = [p for p in all_patterns if _module_pattern_matches(p, [mod])]
        assert not matching, f"Strict module {mod} unexpectedly matched override(s): {matching}"


def test_ci_workflow_pins_ruff_mypy_and_zero_threshold():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "'ruff==0.16.2'" in workflow
    assert "'mypy==1.16.1'" in workflow
    assert "MYPY_THRESHOLD=0" in workflow
    assert "mypy backtrader --config-file=pyproject.toml" in workflow


def test_pure_annotation_fixes_preserve_runtime_contracts():
    from backtrader.events import MarketOrderBookEnvelope
    from backtrader.futures.calendar import _url
    from backtrader.live_trading.run_status import _publishable_code, compute_stop_budget
    from backtrader.research.strict import live_source_binding_active
    from backtrader.trade import Trade
    from backtrader.utils.log_message import _get_logging_config_snapshot

    # utils.log_message
    snap = _get_logging_config_snapshot()
    assert snap is None or isinstance(snap, dict)

    # events.MarketOrderBookEnvelope typed properties
    instrument = SimpleNamespace(product_type="SPOT")
    key = SimpleNamespace(channel="orderbook", instrument=instrument)
    source = SimpleNamespace(key=key)
    cursor = SimpleNamespace(stream_id="s1", epoch=1, sequence=7)
    clock = SimpleNamespace(
        source=source,
        cursor=cursor,
        provider_event_time_utc="2026-11-21T00:00:00Z",
        freshness_status="FRESH",
    )
    sdk_event = SimpleNamespace(
        source=source,
        cursor=cursor,
        instrument=instrument,
        clock=clock,
        key=key,
        complete_state=True,
        bids=(SimpleNamespace(price=100.0, quantity=2.0),),
        asks=(SimpleNamespace(price=101.0, quantity=3.0),),
        provider_sequence=42,
        provider_previous_sequence=41,
        snapshot_or_delta="snapshot",
        continuity_status="CONTINUOUS",
        stale=False,
        stale_reason="",
        recovery_snapshot=False,
    )
    env = MarketOrderBookEnvelope(
        sdk_event=sdk_event,
        data_name="BTCUSDT",
        exchange_name="BINANCE",
    )
    assert env.sequence == 42
    assert env.snapshot_or_delta == "snapshot"
    assert env.continuity_status == "CONTINUOUS"
    assert env.stale is False
    assert env.stale_reason == ""
    assert env.recovery_snapshot is False
    assert env.event_id == "s1:1:7"

    # futures.calendar._url
    assert _url("https://example.com/calendar.json", "url") == "https://example.com/calendar.json"
    with pytest.raises(ValueError, match="HTTPS"):
        _url("http://example.com/calendar.json", "url")

    # live_trading.run_status
    budget = compute_stop_budget(
        stop_cancel_timeout=2.0,
        direct_stop_write_timeout=3.0,
        startup_facts_attempts=2,
        direct_facts_timeout=1.5,
        startup_facts_retry_delay=0.5,
        start_in_progress_bound_s=1.0,
        cancel_request_bound_s=1.0,
        tail_bound_s=0.5,
    )
    assert budget["proven"] is True
    assert budget["total_seconds"] == pytest.approx(7.5)
    assert _publishable_code("clean_stop") == "clean_stop"
    assert _publishable_code("api_secret_leak") is None

    # research.strict
    assert live_source_binding_active() is False

    # trade.Trade.update with non-callable order.info.get and verified recovery info
    fake_data_obj = type("FakeData", (), {"datetime": [739941.0], "__len__": lambda self: 5})()
    fake_comminfo = SimpleNamespace(getvaluesize=lambda s, p: s * p)
    order_plain = SimpleNamespace(
        info=SimpleNamespace(get="not_callable"),
        p=SimpleNamespace(simulated=False),
    )
    tr1 = Trade(data=fake_data_obj)
    tr1.update(
        order_plain, size=1, price=10.0, value=10.0, commission=0.0, pnl=0.0, comminfo=fake_comminfo
    )
    assert tr1.baropen == 5
    assert tr1.dtopen == 739941.0

    order_verified = SimpleNamespace(
        info={
            "service_execution_recovery_v2_trade_time_verified": True,
            "service_execution_recovery_v2_trade_bar_index": 3,
            "service_execution_recovery_match_time_ns": 1_700_000_000_000_000_000,
            "service_execution_recovery_v2_match_datenum": 739940.5,
        },
        p=SimpleNamespace(simulated=False),
    )
    tr2 = Trade(data=fake_data_obj)
    tr2.update(
        order_verified,
        size=1,
        price=10.0,
        value=10.0,
        commission=0.0,
        pnl=0.0,
        comminfo=fake_comminfo,
    )
    assert tr2.baropen == 3
    assert tr2.dtopen == 739940.5

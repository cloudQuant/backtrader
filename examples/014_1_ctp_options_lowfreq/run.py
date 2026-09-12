#!/usr/bin/env python
"""Run the self-contained CTP options low-frequency replay strategy."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import backtrader as bt
import pandas as pd
import yaml

try:
    from .ctp_options_lowfreq_strategy import CtpOptionsLowfreqStrategy
except ImportError:  # Direct execution through this directory's run.py.
    from ctp_options_lowfreq_strategy import CtpOptionsLowfreqStrategy

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "config.yaml"
STRATEGY_ID = "ctp_options_lowfreq"
MODES = frozenset({"replay", "shadow", "simnow", "production"})

try:
    from .simnow_adapter import SimNowBlocked, SimNowOptionsAdapter
except ImportError:  # Direct execution through this directory's run.py.
    from simnow_adapter import SimNowBlocked, SimNowOptionsAdapter


class RunnerConfigurationError(ValueError):
    """Raised before a strategy or any external client can be constructed."""


def _canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _finite_number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise RunnerConfigurationError(f"{name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RunnerConfigurationError(f"{name} must be a number") from exc
    if not math.isfinite(number) or (positive and number <= 0):
        raise RunnerConfigurationError(
            f"{name} must be finite{' and positive' if positive else ''}"
        )
    return number


def _contained_config_path(path: Path | str) -> Path:
    """Resolve a config only when it remains inside this strategy directory."""

    requested = Path(path).expanduser()
    resolved = (requested if requested.is_absolute() else HERE / requested).resolve()
    try:
        resolved.relative_to(HERE)
    except ValueError as exc:
        raise RunnerConfigurationError("config must remain inside this example directory") from exc
    if not resolved.is_file():
        raise RunnerConfigurationError("config does not exist inside this example directory")
    return resolved


def load_config(path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    try:
        with _contained_config_path(path).open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except OSError as exc:
        raise RunnerConfigurationError("unable to read local config") from exc
    except yaml.YAMLError as exc:
        raise RunnerConfigurationError("invalid local config YAML") from exc
    return validate_config(raw)


def validate_config(raw: Any) -> dict[str, Any]:
    """Validate the complete fixed schema after its path has been contained."""

    if not isinstance(raw, dict):
        raise RunnerConfigurationError("configuration must be a mapping")
    expected = {
        "schema_version",
        "strategy_id",
        "mode",
        "candidate",
        "budget",
        "strategy_params",
        "timing",
    }
    if set(raw) != expected:
        raise RunnerConfigurationError("configuration fields are not the declared schema")
    if raw["schema_version"] != 1 or raw["strategy_id"] != STRATEGY_ID:
        raise RunnerConfigurationError("configuration does not identify this strategy")
    if raw["mode"] not in MODES:
        raise RunnerConfigurationError("unsupported mode")
    candidate = raw["candidate"]
    budget = raw["budget"]
    params = raw["strategy_params"]
    timing = raw["timing"]
    if (
        not isinstance(candidate, dict)
        or not isinstance(budget, dict)
        or not isinstance(params, dict)
        or not isinstance(timing, dict)
    ):
        raise RunnerConfigurationError(
            "candidate, budget, strategy_params and timing must be mappings"
        )
    if set(candidate) != {"future", "call", "put", "strike", "multiplier", "discount"}:
        raise RunnerConfigurationError("candidate fields are not the declared schema")
    symbols = (candidate["future"], candidate["call"], candidate["put"])
    if (
        any(not isinstance(symbol, str) or not symbol.strip() for symbol in symbols)
        or len(set(symbols)) != 3
    ):
        raise RunnerConfigurationError("candidate requires three distinct non-empty leg symbols")
    for name in ("strike", "multiplier", "discount"):
        candidate[name] = _finite_number(candidate[name], f"candidate.{name}", positive=True)
    if set(budget) != {"capital_limit", "ordinary_limit", "recovery_reserve"}:
        raise RunnerConfigurationError("budget fields are not the declared schema")
    for name in budget:
        budget[name] = _finite_number(budget[name], f"budget.{name}")
    if budget["capital_limit"] != 10000:
        raise RunnerConfigurationError("capital_limit must equal the CNY 10000 strategy cap")
    if budget["ordinary_limit"] > 8000:
        raise RunnerConfigurationError("ordinary_limit must not exceed the CNY 8000 ordinary cap")
    if budget["recovery_reserve"] < 2000:
        raise RunnerConfigurationError("recovery_reserve must be at least CNY 2000")
    if budget["ordinary_limit"] + budget["recovery_reserve"] > budget["capital_limit"]:
        raise RunnerConfigurationError("ordinary plus recovery budget exceeds capital limit")
    allowed_params = {
        "window",
        "entry_z",
        "exit_z",
        "minimum_score",
        "round_trip_cost",
        "projected_entry_capital",
        "price_tick",
        "bar_minutes",
        "confirmation_bars",
        "minimum_holding_minutes",
        "max_holding_bars",
    }
    if set(params) != allowed_params:
        raise RunnerConfigurationError("strategy_params fields are not the declared schema")
    integer_params = {
        "window",
        "bar_minutes",
        "confirmation_bars",
        "minimum_holding_minutes",
        "max_holding_bars",
    }
    for name in allowed_params - integer_params:
        params[name] = _finite_number(
            params[name], f"strategy_params.{name}", positive=name != "minimum_score"
        )
    for name in integer_params:
        if (
            isinstance(params[name], bool)
            or int(params[name]) != params[name]
            or int(params[name]) <= 0
        ):
            raise RunnerConfigurationError(f"strategy_params.{name} must be a positive integer")
        params[name] = int(params[name])
    if params["bar_minutes"] != 15:
        raise RunnerConfigurationError("strategy_params.bar_minutes must be 15")
    if params["confirmation_bars"] != 2:
        raise RunnerConfigurationError("strategy_params.confirmation_bars must be 2")
    if params["entry_z"] < 2.5:
        raise RunnerConfigurationError("strategy_params.entry_z must be at least 2.5")
    if params["minimum_score"] < 20.0:
        raise RunnerConfigurationError("strategy_params.minimum_score must be at least 20")
    if params["minimum_holding_minutes"] < 30:
        raise RunnerConfigurationError(
            "strategy_params.minimum_holding_minutes must be at least 30"
        )
    if params["max_holding_bars"] * params["bar_minutes"] < params["minimum_holding_minutes"]:
        raise RunnerConfigurationError(
            "maximum holding duration must cover the minimum holding duration"
        )
    if params["projected_entry_capital"] > budget["ordinary_limit"]:
        raise RunnerConfigurationError("projected entry capital exceeds the ordinary budget")
    if params["projected_entry_capital"] + budget["recovery_reserve"] > budget["capital_limit"]:
        raise RunnerConfigurationError(
            "projected entry plus recovery reserve exceeds capital limit"
        )
    expected_timing = {
        "first_send_seconds",
        "completion_seconds",
        "minimum_hold_seconds",
        "maximum_hold_seconds",
        "risk_bar_max_age_seconds",
        "session_stop_entry_seconds",
        "session_exit_seconds",
        "session_handover_seconds",
    }
    if set(timing) != expected_timing:
        raise RunnerConfigurationError("timing fields are not the declared schema")
    for name in expected_timing:
        if (
            isinstance(timing[name], bool)
            or int(timing[name]) != timing[name]
            or int(timing[name]) <= 0
        ):
            raise RunnerConfigurationError(f"timing.{name} must be a positive integer")
        timing[name] = int(timing[name])
    if timing["first_send_seconds"] != 1:
        raise RunnerConfigurationError("timing.first_send_seconds must be 1")
    if timing["completion_seconds"] != 60:
        raise RunnerConfigurationError("timing.completion_seconds must be 60")
    if timing["minimum_hold_seconds"] < 1800:
        raise RunnerConfigurationError("timing.minimum_hold_seconds must be at least 1800")
    if timing["maximum_hold_seconds"] > 7200:
        raise RunnerConfigurationError("timing.maximum_hold_seconds must be at most 7200")
    if timing["maximum_hold_seconds"] < timing["minimum_hold_seconds"]:
        raise RunnerConfigurationError("timing maximum hold cannot be below minimum hold")
    if timing["minimum_hold_seconds"] < params["minimum_holding_minutes"] * 60:
        raise RunnerConfigurationError("minimum holding seconds cannot weaken minutes setting")
    if timing["maximum_hold_seconds"] > params["max_holding_bars"] * params["bar_minutes"] * 60:
        raise RunnerConfigurationError("maximum holding bars cannot weaken timing maximum")
    if timing["risk_bar_max_age_seconds"] > 910:
        raise RunnerConfigurationError("timing.risk_bar_max_age_seconds must be at most 910")
    if timing["session_stop_entry_seconds"] < 1800:
        raise RunnerConfigurationError("timing.session_stop_entry_seconds must be at least 1800")
    if timing["session_exit_seconds"] < 600:
        raise RunnerConfigurationError("timing.session_exit_seconds must be at least 600")
    if timing["session_handover_seconds"] < 180:
        raise RunnerConfigurationError("timing.session_handover_seconds must be at least 180")
    if timing["session_handover_seconds"] > timing["session_exit_seconds"]:
        raise RunnerConfigurationError("timing handover window must fit inside exit window")
    return raw


def _bar(close: float) -> dict[str, float]:
    return {
        "open": close,
        "high": close + 10.0,
        "low": max(1.0, close - 10.0),
        "close": close,
        "volume": 100.0,
        "openinterest": 0.0,
    }


def replay_bars(candidate: Mapping[str, Any], scenario: str) -> dict[str, list[dict[str, float]]]:
    if scenario not in {"eligible", "no_edge", "budget_reject", "misaligned"}:
        raise RunnerConfigurationError("unsupported replay scenario")
    result = {candidate["future"]: [], candidate["call"]: [], candidate["put"]: []}
    start = datetime(2026, 9, 10, 9, 0)
    for index in range(40):
        residual = 1.0 if index % 2 else -1.0
        values = (1000.0, 30.0 + residual, 30.0)
        for symbol, close in zip(result, values):
            result[symbol].append(
                {"datetime": start + timedelta(minutes=15 * index), **_bar(close)}
            )
    if scenario == "no_edge":
        tail = [(1000.0, 30.0, 30.0)] * 12
    else:
        tail = [(1000.0, 140.0, 40.0)] * 2 + [(1000.0, 30.0, 30.0)] * 11
    for offset, values in enumerate(tail, start=40):
        for symbol, close in zip(result, values):
            result[symbol].append(
                {"datetime": start + timedelta(minutes=15 * offset), **_bar(close)}
            )
    if scenario != "no_edge":
        # The local broker evaluates an order against the next bar.  Preserve
        # a deliberately wide *synthetic* call-bar range while the staged
        # entry/exit orders cross it; the close remains the same closed-bar
        # research input and no tick/depth evidence is invented.
        for index in range(41, min(47, len(result[candidate["call"]]))):
            result[candidate["call"]][index]["high"] = 136.0
            result[candidate["call"]][index]["low"] = 20.0
    if scenario == "misaligned":
        result[candidate["call"]][41]["datetime"] += timedelta(minutes=1)
    return result


def _feed(rows: list[dict[str, float]]):
    frame = pd.DataFrame(rows).set_index("datetime")
    return bt.feeds.PandasData(dataname=frame)


def run_replay(
    config: Mapping[str, Any],
    scenario: str = "eligible",
    *,
    synthetic_execution_facts: list[Mapping[str, Any]] | None = None,
    idle_now: Any = None,
    invoke_idle_probe: bool = False,
) -> dict[str, Any]:
    """Run only the explicit offline replay contract.

    Callers may use this function outside the CLI, so the mode fence must live
    here rather than relying on ``main()`` to reject shadow/SimNow/production.
    """
    if not isinstance(config, Mapping) or config.get("mode") != "replay":
        raise RunnerConfigurationError("REPLAY_MODE_REQUIRED")
    candidate = config["candidate"]
    params = dict(config["strategy_params"])
    if scenario == "budget_reject":
        params["projected_entry_capital"] = config["budget"]["ordinary_limit"] + 1.0
    params.update(
        candidate_id=f"{STRATEGY_ID}-replay-v1",
        future_symbol=candidate["future"],
        call_symbol=candidate["call"],
        put_symbol=candidate["put"],
        strike=candidate["strike"],
        multiplier=candidate["multiplier"],
        discount=candidate["discount"],
        capital_limit=config["budget"]["capital_limit"],
        ordinary_limit=config["budget"]["ordinary_limit"],
        recovery_reserve=config["budget"]["recovery_reserve"],
        first_send_seconds=config["timing"]["first_send_seconds"],
        completion_seconds=config["timing"]["completion_seconds"],
        minimum_hold_seconds=config["timing"]["minimum_hold_seconds"],
        maximum_hold_seconds=config["timing"]["maximum_hold_seconds"],
        risk_bar_max_age_seconds=config["timing"]["risk_bar_max_age_seconds"],
        session_stop_entry_seconds=config["timing"]["session_stop_entry_seconds"],
        session_exit_seconds=config["timing"]["session_exit_seconds"],
        session_handover_seconds=config["timing"]["session_handover_seconds"],
    )
    symbols = (candidate["future"], candidate["call"], candidate["put"])
    # These are explicit replay-only reference limits.  They make the local
    # price consumer structurally complete while remaining clearly synthetic;
    # they are never treated as CTP instrument or account evidence.
    params["price_ticks"] = dict.fromkeys(symbols, params["price_tick"])
    params["exchange_limits"] = {
        symbol: {
            "lower": 0.01,
            "upper": 10_000_000.0,
            "source": "synthetic-replay-price-limit-fixture",
        }
        for symbol in symbols
    }
    synthetic_fee = float(params["round_trip_cost"]) / 6.0
    params["fee_schedule"] = dict.fromkeys(
        (
            "open_buy",
            "open_sell",
            "close_buy",
            "close_sell",
            "close_today_buy",
            "close_today_sell",
        ),
        synthetic_fee,
    )
    params["exit_reserve"] = 0.0
    params["financing_reserve"] = 0.0
    params["model_reserve"] = 0.0
    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    cerebro.broker.setcash(config["budget"]["capital_limit"])
    for symbol, rows in replay_bars(candidate, scenario).items():
        cerebro.adddata(_feed(rows), name=symbol)
    cerebro.addstrategy(CtpOptionsLowfreqStrategy, **params)
    strategy = cerebro.run(runonce=False)[0]
    if synthetic_execution_facts:
        for fact in synthetic_execution_facts:
            strategy.record_execution_fact(fact)
    if idle_now is not None:
        strategy.notify_idle(idle_now)
    elif invoke_idle_probe:
        strategy.notify_idle()
    report = strategy.report()
    report.update(
        status="LOCAL_REPLAY_PASS",
        mode="replay",
        scenario=scenario,
        config_sha256=_canonical_hash(config),
        direct_entrypoint=str(HERE / "run.py"),
    )
    report["evidence_package_sha256"] = _canonical_hash(report["evidence_package"])
    return report


def _blocked_report(mode: str, config: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "mode": mode,
        "status": "BLOCKED",
        "reason": "CTP_OPTION_BUNDLE_AUTHORIZATION_AND_LIVE_PREFLIGHT_REQUIRED",
        "config_sha256": _canonical_hash(config),
        "external_request_counts": {"network": 0, "order_write": 0},
    }


def run_simnow_engineering_smoke(
    config: Mapping[str, Any], *, api: Any = None
) -> dict[str, Any]:
    """Run the injected, read-only SimNow engineering smoke path.

    A real native API must be supplied by the SDK-owned launcher.  This
    example never loads credentials or creates that client itself.
    """

    if not isinstance(config, Mapping) or config.get("mode") != "simnow":
        raise RunnerConfigurationError("SIMNOW_MODE_REQUIRED")
    try:
        adapter = SimNowOptionsAdapter(config, api=api)
        return adapter.run_engineering_smoke()
    except SimNowBlocked as exc:
        if api is None:
            request_counts = {"network": 0, "order_write": 0}
        elif bool(getattr(api, "iter23_pure_mock", False)):
            request_counts = {"network": 0, "order_write": 0}
        else:
            request_counts = {"network": "NOT_OBSERVED", "order_write": "NOT_OBSERVED"}
        return {
            "mode": "simnow",
            "purpose": "engineering_smoke",
            "status": "BLOCKED",
            "reason": str(exc),
            "external_request_counts": request_counts,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--mode", choices=sorted(MODES))
    parser.add_argument("--purpose", choices=("engineering_smoke",), default=None)
    parser.add_argument(
        "--scenario",
        choices=("eligible", "no_edge", "budget_reject", "misaligned"),
        default="eligible",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        mode = args.mode or config["mode"]
        report = (
            run_replay(config, args.scenario)
            if mode == "replay"
            else run_simnow_engineering_smoke({**deepcopy(config), "mode": mode})
            if mode == "simnow" and args.purpose == "engineering_smoke"
            else _blocked_report(mode, config)
        )
    except RunnerConfigurationError as exc:
        report = {
            "status": "REJECTED",
            "reason": str(exc),
            "external_request_counts": {"network": 0, "order_write": 0},
        }
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if mode == "replay" else 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Direct, offline entry point for the self-contained Iteration 24 fixture."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import backtrader as bt
import pandas as pd
import yaml

try:
    from .ctp_options_midfreq_strategy import (
        CTPOptionsMidFrequencyStrategy,
        ConfigurationError,
        validate_config,
    )
    from .execution_fixture import (
        TimingFixtureFeed,
        build_normal_exit_fixture,
        build_timing_fixture,
    )
    from .fq2_fixture import REPLAY_BASE, ReplayQuoteProducer
except ImportError:  # Direct execution through this directory's run.py.
    from ctp_options_midfreq_strategy import (
        CTPOptionsMidFrequencyStrategy,
        ConfigurationError,
        validate_config,
    )
    from execution_fixture import (
        TimingFixtureFeed,
        build_normal_exit_fixture,
        build_timing_fixture,
    )
    from fq2_fixture import REPLAY_BASE, ReplayQuoteProducer

EXAMPLE_DIR = Path(__file__).resolve().parent


def _canonical_config_hash(raw_config: Dict[str, Any]) -> str:
    encoded = json.dumps(
        raw_config, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _contained_config_path(path: Path | str) -> Path:
    """Resolve a config only when it remains inside this strategy directory."""

    requested = Path(path).expanduser()
    resolved = (requested if requested.is_absolute() else EXAMPLE_DIR / requested).resolve()
    try:
        resolved.relative_to(EXAMPLE_DIR)
    except ValueError as error:
        raise ConfigurationError(
            "CONFIG_PATH", "config must remain inside this example directory"
        ) from error
    if not resolved.is_file():
        raise ConfigurationError(
            "CONFIG_PATH", "config does not exist inside this example directory"
        )
    return resolved


def load_config(path: Path | str = EXAMPLE_DIR / "config.yaml") -> Dict[str, Any]:
    """Load the contained YAML config as a mapping; reject anything else."""

    try:
        loaded = yaml.safe_load(_contained_config_path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise ConfigurationError("CONFIG_READ", f"unable to read config: {error}") from error
    except yaml.YAMLError as error:
        raise ConfigurationError("CONFIG_YAML", f"invalid yaml: {error}") from error
    if not isinstance(loaded, dict):
        raise ConfigurationError("CONFIG_SCHEMA", "config root must be a mapping")
    return loaded


def _minute_rows(config: Dict[str, Any], scenario: str) -> Dict[str, pd.DataFrame]:
    """Build three aligned local minute feeds without opening a market connection."""

    if scenario == "no_edge":
        residuals = [0] * 61
    elif scenario == "edge":
        residuals = [10 if index % 2 == 0 else -10 for index in range(60)] + [80]
    else:
        raise ConfigurationError("REPLAY_SCENARIO", f"unknown local scenario {scenario!r}")

    candidate = config["candidate"]
    multiplier = float(candidate["multiplier"])
    strike = float(candidate["strike"])
    discount_factor = float(candidate["discount_factor"])
    start = REPLAY_BASE.replace(tzinfo=None) + timedelta(minutes=1)
    futures: List[Dict[str, Any]] = []
    calls: List[Dict[str, Any]] = []
    puts: List[Dict[str, Any]] = []
    for offset, residual_cny in enumerate(residuals):
        timestamp = start + timedelta(minutes=offset)
        future = strike
        put = 9.5
        call = put + discount_factor * (future - strike) + (float(residual_cny) / multiplier)
        for target, close in ((futures, future), (calls, call), (puts, put)):
            target.append(
                {
                    "datetime": timestamp,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1.0,
                    "openinterest": 0.0,
                }
            )

    def frame(rows: List[Dict[str, Any]]) -> pd.DataFrame:
        return pd.DataFrame(rows).set_index("datetime")

    return {"future": frame(futures), "call": frame(calls), "put": frame(puts)}


def _producer_for(config: Dict[str, Any]) -> ReplayQuoteProducer:
    candidate = config["candidate"]
    return ReplayQuoteProducer(
        candidate_id=candidate["candidate_id"],
        exchange=candidate["exchange"],
        rules_hash=candidate["rules_hash"],
        contracts=candidate["contracts"],
        scenario=config["replay"]["scenario"],
        strike=candidate["strike"],
        multiplier=candidate["multiplier"],
        discount_factor=candidate["discount_factor"],
    )


def run_replay(
    raw_config: Dict[str, Any],
    scenario: Optional[str] = None,
    inject_cutoff_tick: bool = False,
    inject_at_cutoff_tick: bool = False,
) -> Dict[str, Any]:
    """Run explicit local evidence through actual Cerebro and BackBroker."""

    effective = copy.deepcopy(raw_config)
    if scenario is not None:
        replay = effective.get("replay")
        if isinstance(replay, dict):
            replay["scenario"] = scenario
    config = validate_config(effective)
    if config["mode"] != "replay":
        raise ConfigurationError(
            "ENGINEERING_OBSERVATION_API_ONLY",
            "engineering observation must use the injected live Store/Feed/Cerebro entry point",
        )
    producer = _producer_for(config)
    frames = _minute_rows(config, config["replay"]["scenario"])

    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    cerebro.broker.setcash(float(config["replay"]["initial_cash_cny"]))
    for name in ("future", "call", "put"):
        cerebro.adddata(
            bt.feeds.PandasData(
                dataname=frames[name],
                timeframe=bt.TimeFrame.Minutes,
                compression=config["signal"]["bar_minutes"],
            ),
            name=name,
        )
    cerebro.addstrategy(
        CTPOptionsMidFrequencyStrategy,
        config=config,
        quote_producer=producer,
    )
    strategies = cerebro.run()
    strategy = strategies[0]

    decisions_before_tick = strategy.build_report()["ordinary_decision_count"]
    if inject_cutoff_tick or inject_at_cutoff_tick:
        if strategy.last_closed_minute is None:
            raise RuntimeError("fixture did not close any minute")
        tick = producer.tick_for(
            60,
            symbol=config["candidate"]["contracts"]["future"],
            at_cutoff=inject_at_cutoff_tick,
        )
        strategy.notify_tick(tick)
    report = strategy.build_report()
    report["ordinary_decision_count_before_tick"] = decisions_before_tick
    report["config_sha256"] = _canonical_config_hash(effective)
    report["synthetic_scenario"] = config["replay"]["scenario"]
    report["cerebro"] = {
        "strategy": CTPOptionsMidFrequencyStrategy.__name__,
        "feed_count": len(cerebro.datas),
        "broker_class": type(cerebro.broker).__name__,
    }
    report["self_contained_runtime"] = True
    return report


def run_timing_replay(
    raw_config: Dict[str, Any], *, normal_exit_fixture: bool = False
) -> Dict[str, Any]:
    """Run the MF-T1 projector through real Cerebro ``next`` and idle hooks."""

    config = validate_config(copy.deepcopy(raw_config))
    if config["mode"] != "replay":
        raise ConfigurationError(
            "ENGINEERING_OBSERVATION_API_ONLY",
            "engineering observation cannot run a local timing replay fixture",
        )
    provider = build_normal_exit_fixture() if normal_exit_fixture else build_timing_fixture()
    feed = TimingFixtureFeed(
        idle_polls=provider.idle_count,
        bar_count=2 if normal_exit_fixture else 1,
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False, quicknotify=True)
    cerebro.adddata(feed, name="mf-t1-timing-feed")
    cerebro.addstrategy(
        CTPOptionsMidFrequencyStrategy,
        config=config,
        timing_provider=provider,
    )
    strategies = cerebro.run(runonce=False, preload=False)
    strategy = strategies[0]
    report = strategy.build_report()
    report["config_sha256"] = _canonical_config_hash(raw_config)
    report["cerebro"] = {
        "strategy": CTPOptionsMidFrequencyStrategy.__name__,
        "feed_count": len(cerebro.datas),
        "broker_class": type(cerebro.broker).__name__,
        "actual_next_callback": True,
        "actual_notify_idle_callback": strategy.build_report()["timing"]["idle_callback_count"] > 0,
        "feed_returned_none": feed.idle_returns > 0,
    }
    report["external_network_requests"] = 0
    report["external_trade_writes"] = 0
    report["execution_permission"] = "NOT_PROVEN"
    return report


def run_engineering_smoke(raw_config: Dict[str, Any], *, api: Any = None) -> Dict[str, Any]:
    """Build the real Store/Feed/Broker/Cerebro chain without starting it.

    A production caller must inject an already-authenticated SDK object.  The
    command-line path intentionally supplies none, so it fails closed before
    any transport, subscription, order, or credential lookup can occur.
    """

    smoke_config = copy.deepcopy(raw_config)
    # The replay schema validates the candidate/risk contract; the adapter
    # owns the live-mode admission and still requires an explicit SDK object.
    smoke_config["mode"] = "replay"
    config = validate_config(smoke_config)
    try:
        from .simnow_adapter import build_engineering_smoke
    except ImportError:
        from simnow_adapter import build_engineering_smoke
    return build_engineering_smoke(config=config, api=api)


def run_engineering_observation(
    raw_config: Dict[str, Any],
    *,
    api: Any = None,
    store: Any = None,
    store_ownership: Any = None,
    environment_profile: str,
    run_seconds: float,
    feed_clock: Any,
    clock_mapping: Any,
    closed_bar_evidence_provider: Any,
) -> Dict[str, Any]:
    """Run the explicit, bounded Set-2 zero-write strategy observation.

    This does not load ``.env``, choose an SDK, or expose a CLI path that could
    accidentally connect with ambient credentials.  Callers may inject either
    an API object or one governed Store whose lifecycle they explicitly
    transfer; the adapter rejects mixed ownership.  Its runtime mode is
    explicit and distinct from the local replay fixture, while the outer
    report remains a ``shadow`` observation so it cannot be confused with
    G3/G4 execution.
    """

    if not isinstance(raw_config, dict) or raw_config.get("mode") not in {
        "replay",
        "engineering_observation",
    }:
        raise ConfigurationError(
            "ENGINEERING_OBSERVATION_MODE",
            "engineering observation accepts only the frozen replay template or explicit runtime mode",
        )
    runtime_config = copy.deepcopy(raw_config)
    runtime_config["mode"] = "engineering_observation"
    config = validate_config(runtime_config)
    try:
        from .simnow_adapter import run_engineering_observation as _run_observation
    except ImportError:
        from simnow_adapter import run_engineering_observation as _run_observation
    return _run_observation(
        config=config,
        api=api,
        store=store,
        store_ownership=store_ownership,
        environment_profile=environment_profile,
        run_seconds=run_seconds,
        feed_clock=feed_clock,
        clock_mapping=clock_mapping,
        closed_bar_evidence_provider=closed_bar_evidence_provider,
    )


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=EXAMPLE_DIR / "config.yaml")
    parser.add_argument("--mode", choices=("replay", "shadow", "simnow", "production"))
    parser.add_argument(
        "--purpose",
        choices=("engineering_smoke",),
        help="build the injected, fail-closed SimNow engineering chain without starting it",
    )
    parser.add_argument("--scenario", choices=("no_edge", "edge"))
    parser.add_argument(
        "--timing",
        action="store_true",
        help="run the local MF-T1 execution timing projection through Cerebro idle callbacks",
    )
    parser.add_argument(
        "--timing-normal-exit",
        action="store_true",
        help="run the local actual-Cerebro two-minute normal-exit fixture",
    )
    parser.add_argument(
        "--inject-cutoff-tick",
        action="store_true",
        help="replay-test only: validate one explicit quote after the ordinary next decision",
    )
    parser.add_argument(
        "--inject-at-cutoff-tick",
        action="store_true",
        help="replay-test only: prove a receive timestamp at the cutoff is rejected",
    )
    return parser.parse_args()


def main() -> int:
    """Dispatch the offline CLI, print one JSON report, and return exit status."""

    args = _arguments()
    try:
        raw_config = load_config(args.config)
        if args.mode is not None:
            raw_config["mode"] = args.mode
        if args.purpose == "engineering_smoke":
            if args.mode != "simnow":
                raise ConfigurationError(
                    "ENGINEERING_SMOKE_MODE", "engineering_smoke requires --mode simnow"
                )
            # No API factory, environment lookup, or .env loading is allowed
            # in this entry point.  Tests and a separately governed launcher
            # may call run_engineering_smoke(..., api=explicit_api).
            raise ConfigurationError(
                "SDK_NOT_INJECTED",
                "engineering_smoke requires an explicit injected SDK object; CLI performs no connection",
            )
        if args.timing or args.timing_normal_exit:
            if args.scenario or args.inject_cutoff_tick or args.inject_at_cutoff_tick:
                raise ConfigurationError(
                    "TIMING_ARGUMENTS", "timing replay cannot be combined with FQ2 tick arguments"
                )
            report = run_timing_replay(raw_config, normal_exit_fixture=args.timing_normal_exit)
        else:
            report = run_replay(
                raw_config,
                args.scenario,
                args.inject_cutoff_tick,
                args.inject_at_cutoff_tick,
            )
    except ConfigurationError as error:
        report = {
            "status": "REJECTED",
            "error_code": error.code,
            "message": str(error),
            "external_network_requests": 0,
            "external_trade_writes": 0,
        }
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

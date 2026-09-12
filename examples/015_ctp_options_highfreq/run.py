#!/usr/bin/env python
"""Run the self-contained Iteration 25 CTP-options tick replay.

``replay`` consumes only the fixture beside this file through Backtrader's
channel mode, ``Event``/``TickEvent`` and ``TickBroker``.  It opens no socket,
submits no broker order, creates no actual fill and emits no PnL.  Other modes
are intentionally rejected before a session can be built.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import backtrader as bt
import yaml
from backtrader.brokers.tickbroker import TickBroker
from backtrader.channel import Event, EventPriority
from backtrader.events import BarEvent, TickEvent

try:
    from .ctp_options_highfreq_strategy import CtpOptionsHighfreqStrategy, canonical_sha256
except ImportError:  # Direct execution through this directory's run.py.
    from ctp_options_highfreq_strategy import CtpOptionsHighfreqStrategy, canonical_sha256


HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "config.yaml"
FIXTURE_SCHEMA = "iter25.ctp-options-tick-fixture.v1"
CONFIG_SCHEMA = "ctp-options-candidate.v1"
FROZEN_FEED_UPPER_BOUNDS_MS = {
    "max_quote_age_ms": 250.0,
    "max_cross_leg_skew_ms": 100.0,
    "max_source_age_upper_ms": 250.0,
    "max_source_skew_upper_ms": 100.0,
    "max_source_clock_error_ms": 5.0,
}
MODES = frozenset({"replay", "shadow", "simnow", "production"})
REPLAY_PURPOSES = frozenset({"formula"})
_CREDENTIAL_TOKENS = ("password", "secret", "token", "auth_code", "api_key", "credential")


class RunnerConfigurationError(ValueError):
    """A fail-closed configuration or mode error with no side effect."""


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RunnerConfigurationError(f"{name} must be a mapping")
    return dict(value)


def _finite(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise RunnerConfigurationError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RunnerConfigurationError(f"{name} must be a finite number") from exc
    if not math.isfinite(number) or (positive and number <= 0):
        raise RunnerConfigurationError(f"{name} must be a finite positive number")
    return number


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise RunnerConfigurationError(f"{name} must be a positive integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise RunnerConfigurationError(f"{name} must be a positive integer") from exc
    if number <= 0:
        raise RunnerConfigurationError(f"{name} must be a positive integer")
    if isinstance(value, str) and str(number) != value.strip():
        raise RunnerConfigurationError(f"{name} must be a positive integer")
    return number


def _require_exact_keys(value: Mapping[str, Any], *, name: str, keys: set[str]) -> dict[str, Any]:
    result = _mapping(value, name)
    unknown = sorted(set(result) - keys)
    missing = sorted(keys - set(result))
    if unknown or missing:
        parts = []
        if unknown:
            parts.append(f"unknown={unknown}")
        if missing:
            parts.append(f"missing={missing}")
        raise RunnerConfigurationError(f"{name} keys are invalid ({', '.join(parts)})")
    return result


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            yield str(key)
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_bytes(encoded.encode("utf-8"))


def _within_example(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(HERE)
    except ValueError as exc:
        raise RunnerConfigurationError("fixture must remain inside this example directory") from exc
    return resolved


def load_config(path: Path | str = DEFAULT_CONFIG) -> tuple[dict[str, Any], Path]:
    """Load and strictly validate this example's configuration only."""

    config_path = Path(path)
    if not config_path.is_absolute():
        candidate = HERE / config_path
        config_path = candidate if candidate.exists() else config_path.resolve()
    config_path = _within_example(config_path)
    if not config_path.is_file():
        raise RunnerConfigurationError(f"config does not exist: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config = _mapping(raw, "config root")
    validate_config(config)
    return config, config_path.resolve()


def validate_config(config: Mapping[str, Any]) -> None:
    """Reject unsafe, ambiguous, or unfrozen candidate settings before runtime."""

    root = _require_exact_keys(
        config,
        name="config root",
        keys={
            "schema_version",
            "candidate_id",
            "mode",
            "purpose",
            "production_enabled",
            "contracts",
            "feed",
            "risk",
            "signal",
            "execution",
            "replay",
        },
    )
    if root["schema_version"] != CONFIG_SCHEMA:
        raise RunnerConfigurationError("unsupported config schema")
    if not isinstance(root["candidate_id"], str) or not root["candidate_id"].strip():
        raise RunnerConfigurationError("candidate_id must be non-empty")
    mode = str(root["mode"])
    if mode not in MODES:
        raise RunnerConfigurationError("unsupported mode")
    if not isinstance(root["production_enabled"], bool) or root["production_enabled"]:
        raise RunnerConfigurationError("production_enabled must remain false")

    contracts = _require_exact_keys(
        root["contracts"], name="contracts", keys={"exchange", "future", "call", "put"}
    )
    if contracts["exchange"] not in {"CFFEX", "SHFE", "DCE", "CZCE", "INE", "GFEX"}:
        raise RunnerConfigurationError("contracts.exchange must be an exact CTP exchange ID")
    symbols = tuple(contracts[role] for role in ("future", "call", "put"))
    if len(set(symbols)) != 3 or any(
        not isinstance(symbol, str) or not symbol.strip() for symbol in symbols
    ):
        raise RunnerConfigurationError(
            "contracts must contain three distinct non-empty identifiers"
        )

    feed = _require_exact_keys(
        root["feed"],
        name="feed",
        keys={
            "timeframe",
            "dispatch_ticks",
            "dispatch_bars",
            "max_quote_age_ms",
            "max_cross_leg_skew_ms",
            "max_source_age_upper_ms",
            "max_source_skew_upper_ms",
            "max_source_clock_error_ms",
            "complete_cohort_confirmations",
        },
    )
    if feed["timeframe"] != "ticks" or feed["dispatch_ticks"] is not True:
        raise RunnerConfigurationError("the candidate requires tick dispatch")
    if feed["dispatch_bars"] is not False:
        raise RunnerConfigurationError("bar dispatch is forbidden for this tick-only candidate")
    for key in (
        "max_quote_age_ms",
        "max_cross_leg_skew_ms",
        "max_source_age_upper_ms",
        "max_source_skew_upper_ms",
        "max_source_clock_error_ms",
    ):
        value = _finite(feed[key], f"feed.{key}", positive=True)
        if value > FROZEN_FEED_UPPER_BOUNDS_MS[key]:
            raise RunnerConfigurationError(
                f"feed.{key} exceeds its frozen upper bound "
                f"{FROZEN_FEED_UPPER_BOUNDS_MS[key]:g}ms"
            )
    if (
        _positive_int(feed["complete_cohort_confirmations"], "feed.complete_cohort_confirmations")
        != 2
    ):
        raise RunnerConfigurationError("the candidate requires exactly two complete cohorts")

    risk = _require_exact_keys(
        root["risk"],
        name="risk",
        keys={
            "capital_cap_cny",
            "working_cny",
            "recovery_reserve_cny",
            "daily_loss_limit_cny",
            "basket_loss_limit_cny",
            "lots_per_leg",
            "max_cycles",
        },
    )
    if (
        _finite(risk["capital_cap_cny"], "risk.capital_cap_cny", positive=True) != 10_000
        or _finite(risk["working_cny"], "risk.working_cny", positive=True) != 8_000
        or _finite(risk["recovery_reserve_cny"], "risk.recovery_reserve_cny", positive=True)
        != 2_000
    ):
        raise RunnerConfigurationError("the 10000/8000/2000 capital contract is frozen")
    if _positive_int(risk["lots_per_leg"], "risk.lots_per_leg") != 1:
        raise RunnerConfigurationError("the candidate requires one lot per leg")
    if _positive_int(risk["max_cycles"], "risk.max_cycles") != 1:
        raise RunnerConfigurationError("the candidate permits one cycle only")
    _finite(risk["daily_loss_limit_cny"], "risk.daily_loss_limit_cny", positive=True)
    _finite(risk["basket_loss_limit_cny"], "risk.basket_loss_limit_cny", positive=True)

    signal = _require_exact_keys(
        root["signal"], name="signal", keys={"entry_buffer_cny", "total_reserve_cny"}
    )
    if _finite(signal["entry_buffer_cny"], "signal.entry_buffer_cny", positive=True) != 20:
        raise RunnerConfigurationError("the initial entry buffer is frozen at 20 CNY")
    _finite(signal["total_reserve_cny"], "signal.total_reserve_cny", positive=True)

    execution = _require_exact_keys(
        root["execution"],
        name="execution",
        keys={
            "order_type",
            "ordinary_requests_per_second",
            "max_daily_write_attempts",
            "max_daily_ordinary_attempts",
            "safety_daily_reserved_attempts",
        },
    )
    if execution["order_type"] != "limit":
        raise RunnerConfigurationError("only limit-order semantics are admissible")
    if _positive_int(execution["ordinary_requests_per_second"], "execution.rate") > 2:
        raise RunnerConfigurationError("ordinary request rate cannot exceed two per second")
    if _positive_int(execution["max_daily_write_attempts"], "execution.max_writes") != 100:
        raise RunnerConfigurationError("daily write budget must remain 100")
    if _positive_int(execution["max_daily_ordinary_attempts"], "execution.max_ordinary") != 80:
        raise RunnerConfigurationError("daily ordinary budget must remain 80")
    if _positive_int(execution["safety_daily_reserved_attempts"], "execution.safety_reserve") != 20:
        raise RunnerConfigurationError("daily safety reserve must remain 20")

    replay = _require_exact_keys(
        root["replay"], name="replay", keys={"fixture", "scenario", "starting_cash"}
    )
    if not isinstance(replay["fixture"], str) or not replay["fixture"].strip():
        raise RunnerConfigurationError("replay.fixture must be a local relative path")
    _within_example(HERE / replay["fixture"])
    starting_cash = _finite(replay["starting_cash"], "replay.starting_cash", positive=True)
    if starting_cash < _finite(risk["capital_cap_cny"], "risk.capital_cap_cny", positive=True):
        raise RunnerConfigurationError("replay.starting_cash must cover the capital cap")

    if any(any(token in key.lower() for token in _CREDENTIAL_TOKENS) for key in _walk_keys(root)):
        raise RunnerConfigurationError("credentials are not permitted in config.yaml")


def effective_config(
    config: Mapping[str, Any], *, mode: str | None = None, purpose: str | None = None
) -> dict[str, Any]:
    """Create the hash-bound config used for one process without env overrides."""

    effective = copy.deepcopy(dict(config))
    if mode is not None:
        effective["mode"] = mode
    if purpose is not None:
        effective["purpose"] = purpose
    validate_config(effective)
    return effective


def load_fixture(config: Mapping[str, Any]) -> tuple[dict[str, Any], Path, str]:
    replay = _mapping(config["replay"], "replay")
    fixture_path = _within_example(HERE / str(replay["fixture"]))
    if not fixture_path.is_file():
        raise RunnerConfigurationError("replay fixture does not exist")
    raw_bytes = fixture_path.read_bytes()
    try:
        fixture = _mapping(json.loads(raw_bytes), "fixture root")
    except json.JSONDecodeError as exc:
        raise RunnerConfigurationError("replay fixture is not valid JSON") from exc
    if fixture.get("schema_version") != FIXTURE_SCHEMA:
        raise RunnerConfigurationError("unsupported replay fixture schema")
    return fixture, fixture_path, _sha256_bytes(raw_bytes)


def validate_bundle(fixture: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    """Freeze a synthetic C/P/F bundle without parsing contract names."""

    bundle = _mapping(fixture.get("bundle"), "fixture.bundle")
    if set(bundle) != {"discount_factor", "strike", "future", "call", "put"}:
        raise RunnerConfigurationError("fixture bundle fields are incomplete")
    legs = {
        role: _mapping(bundle[role], f"fixture.bundle.{role}") for role in ("future", "call", "put")
    }
    expected_kinds = {"future": "future", "call": "call", "put": "put"}
    contracts = _mapping(config["contracts"], "contracts")
    for role, leg in legs.items():
        if leg.get("kind") != expected_kinds[role] or leg.get("symbol") != contracts[role]:
            raise RunnerConfigurationError("fixture leg identity does not match frozen config")
        for field in (
            "symbol",
            "exchange_id",
            "underlying_id",
            "multiplier",
            "tick_size",
            "min_lot",
        ):
            if field not in leg:
                raise RunnerConfigurationError(f"fixture {role} lacks {field}")
        if leg["exchange_id"] != contracts["exchange"]:
            raise RunnerConfigurationError("fixture exchange does not match frozen config")
        if _finite(leg["multiplier"], f"fixture {role}.multiplier", positive=True) <= 0:
            raise RunnerConfigurationError("invalid multiplier")
        if _finite(leg["tick_size"], f"fixture {role}.tick_size", positive=True) <= 0:
            raise RunnerConfigurationError("invalid tick size")
        if _positive_int(leg["min_lot"], f"fixture {role}.min_lot") != 1:
            raise RunnerConfigurationError("fixture must use integer one-lot legs")
    if (
        legs["call"]["underlying_id"] != legs["future"]["symbol"]
        or legs["put"]["underlying_id"] != legs["future"]["symbol"]
    ):
        raise RunnerConfigurationError("option underlying must be the frozen future")
    if legs["call"].get("expiry") != legs["put"].get("expiry"):
        raise RunnerConfigurationError("call and put expiry must match")
    if legs["call"].get("strike") != legs["put"].get("strike") or str(
        legs["call"].get("strike")
    ) != str(bundle["strike"]):
        raise RunnerConfigurationError("call and put strike must match the frozen bundle")
    if len({str(leg["multiplier"]) for leg in legs.values()}) != 1:
        raise RunnerConfigurationError("all three multipliers must match")
    if (
        legs["call"].get("exercise_style") != "european"
        or legs["put"].get("exercise_style") != "european"
    ):
        raise RunnerConfigurationError("only european exercise is admitted to the formula fixture")
    if (
        legs["call"].get("premium_style") != "premium"
        or legs["put"].get("premium_style") != "premium"
    ):
        raise RunnerConfigurationError("only premium-style options are admitted to the fixture")
    _finite(bundle["discount_factor"], "fixture.discount_factor", positive=True)
    _finite(bundle["strike"], "fixture.strike", positive=True)
    return bundle


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _make_tick(
    *,
    role: str,
    bundle: Mapping[str, Any],
    quote: Mapping[str, Any],
    source_epoch: float,
    receive_epoch: float,
    receive_monotonic_ns: int,
    sequence: int,
    rules_hash: str,
    trading_day: str,
    source: str,
) -> TickEvent:
    leg = _mapping(bundle[role], f"bundle.{role}")
    tick = TickEvent(
        timestamp=source_epoch,
        symbol=str(leg["symbol"]),
        exchange=str(leg["exchange_id"]),
        asset_type="future" if role == "future" else "option",
        local_time=receive_epoch,
        exchange_time=source_epoch,
        received_wall_time=receive_epoch,
        received_monotonic_ns=receive_monotonic_ns,
        clock_domain_id="iter25-fixture-monotonic-v1",
        sequence=sequence,
        continuity_status="continuous",
        source=source,
        price=float(quote["last"]),
        volume=1.0,
        direction="buy",
        bid_price=float(quote["bid"]),
        ask_price=float(quote["ask"]),
        bid_volume=float(quote["bid_size"]),
        ask_volume=float(quote["ask_size"]),
    )
    tick.schema_version = "ctp.quote.v2"
    tick.volume_semantics = "delta"
    tick.event_time_utc = _iso(source_epoch)
    tick.recv_time_utc = _iso(receive_epoch)
    tick.recv_monotonic_ns = receive_monotonic_ns
    tick.ingest_seq = sequence
    tick.connection_generation = 1
    tick.subscription_epoch = 1
    tick.rules_hash = rules_hash
    tick.source_clock_quality = "verified"
    tick.receive_clock_quality = "verified"
    tick.source_clock_error_ms = 0.0
    tick.receive_clock_error_ms = 0.0
    tick.freshness_verified = True
    tick.trading_day = trading_day
    tick.action_day = trading_day
    tick.cum_volume = float(sequence)
    tick.cumulative_volume = float(sequence)
    tick.delta_volume = 1.0
    tick.open_interest = 1000.0
    tick.lower_limit = 1.0
    tick.upper_limit = 100000.0
    tick.volume_complete = True
    tick.volume_quality = "CONTINUOUS"
    tick.quality_flags = ()
    tick.execution_eligible = True
    tick.event_time_source = "fixture_utc"
    # The public cohort core never substitutes quote receipt time for current
    # time.  This direct replay has no Store/Feed dispatch queue, so its
    # fixture carries explicit deterministic decision-boundary evidence.
    tick.cohort_decision_now_monotonic_ns = receive_monotonic_ns
    tick.cohort_decision_now_epoch = _iso(receive_epoch)
    tick.cohort_decision_now_clock_domain_id = tick.clock_domain_id
    tick.cohort_decision_now_receive_clock_error_ms = 0.0
    tick.cohort_decision_now_receive_clock_quality = "verified"
    tick.cohort_decision_now_freshness_verified = True
    return tick


def _cohort_events(
    fixture: Mapping[str, Any], bundle: Mapping[str, Any], scenario: str
) -> list[Event]:
    base = _finite(fixture.get("start_epoch"), "fixture.start_epoch", positive=True)
    source = str(fixture.get("source") or "local_synthetic_fixture")
    trading_day = str(fixture.get("trading_day") or "")
    if len(trading_day) != 8 or not trading_day.isdigit():
        raise RunnerConfigurationError("fixture trading_day must be YYYYMMDD")
    quotes = _mapping(fixture.get("base_quotes"), "fixture.base_quotes")
    if set(quotes) != {"future", "call", "put"}:
        raise RunnerConfigurationError("fixture must contain three base quotes")
    rules_hash = canonical_sha256(bundle)
    cohort_count = {
        "valid_cohort": 2,
        "insufficient_cohort": 1,
        "duplicate_payload": 2,
        "mixed_trading_day": 2,
        "quality_gap": 2,
        "quality_flag": 2,
        "incomplete_volume": 2,
        "volume_quality_gap": 2,
        "out_of_limit": 2,
        "execution_ineligible": 2,
    }.get(scenario)
    if scenario == "bar_only":
        bar = BarEvent(
            timestamp=base,
            symbol=str(bundle["future"]["symbol"]),
            exchange=str(bundle["future"]["exchange_id"]),
            asset_type="futures",
            local_time=base,
            open=1000.0,
            high=1001.0,
            low=999.0,
            close=1000.0,
            volume=1.0,
            openinterest=1000.0,
        )
        return [
            Event(
                timestamp=bar.timestamp,
                priority=EventPriority.BAR,
                sequence=1,
                channel_type="bar",
                channel_name=bar.symbol,
                data=bar,
            )
        ]
    if scenario == "stale_source":
        cohort_count = 1
    if cohort_count is None:
        raise RunnerConfigurationError(f"unsupported replay scenario: {scenario}")

    events: list[Event] = []
    sequence = 0
    roles = ("future", "call", "put")
    for cohort_index in range(cohort_count):
        cohort_base = base + cohort_index * 0.050
        for role_index, role in enumerate(roles):
            sequence += 1
            source_epoch = cohort_base + role_index * 0.005
            receive_epoch = source_epoch + 0.001
            if scenario == "duplicate_payload" and cohort_index == 1:
                source_epoch = base + role_index * 0.005
            if scenario == "stale_source" and role == "put":
                source_epoch -= 60.0
                receive_epoch = cohort_base + role_index * 0.005 + 0.001
            event_trading_day = trading_day
            if scenario == "mixed_trading_day" and cohort_index == 1 and role == "put":
                event_trading_day = "20260911"
            receive_monotonic_ns = int((1_000_000.0 + receive_epoch - base) * 1_000_000_000)
            tick = _make_tick(
                role=role,
                bundle=bundle,
                quote=_mapping(quotes[role], f"fixture.base_quotes.{role}"),
                source_epoch=source_epoch,
                receive_epoch=receive_epoch,
                receive_monotonic_ns=receive_monotonic_ns,
                sequence=sequence,
                rules_hash=rules_hash,
                trading_day=event_trading_day,
                source=source,
            )
            if scenario == "quality_gap":
                tick.continuity_status = "gap"
            elif scenario == "quality_flag":
                tick.quality_flags = ("CONNECTION_GENERATION_CHANGED",)
            elif scenario == "incomplete_volume":
                tick.volume_complete = False
            elif scenario == "volume_quality_gap":
                tick.volume_quality = "BASELINE"
            elif scenario == "out_of_limit":
                tick.ask_price = float(tick.upper_limit) + 1.0
            elif scenario == "execution_ineligible":
                tick.execution_eligible = False
            events.append(
                Event(
                    # Channel ordering is local receipt order.  TickEvent retains the
                    # exchange/source timestamp so source-freshness is evaluated
                    # separately from the delivery clock.
                    timestamp=receive_epoch,
                    priority=EventPriority.TICK,
                    sequence=sequence,
                    channel_type="tick",
                    channel_name=tick.symbol,
                    data=tick,
                )
            )
    return sorted(events)


def _strategy_params(config: Mapping[str, Any], bundle: Mapping[str, Any]) -> dict[str, Any]:
    feed = _mapping(config["feed"], "feed")
    risk = _mapping(config["risk"], "risk")
    signal = _mapping(config["signal"], "signal")
    symbols = tuple(str(bundle[role]["symbol"]) for role in ("future", "call", "put"))
    return {
        "mode": str(config["mode"]),
        "candidate_id": str(config["candidate_id"]),
        "symbols": symbols,
        "exchange_id": str(bundle["future"]["exchange_id"]),
        "bundle": copy.deepcopy(dict(bundle)),
        "bundle_hash": canonical_sha256(bundle),
        "tick_sizes": {
            str(bundle[role]["symbol"]): float(bundle[role]["tick_size"])
            for role in bundle
            if role in {"future", "call", "put"}
        },
        "lots_per_leg": int(risk["lots_per_leg"]),
        "max_quote_age_ms": float(feed["max_quote_age_ms"]),
        "max_cross_leg_skew_ms": float(feed["max_cross_leg_skew_ms"]),
        "max_source_age_ms": float(feed["max_source_age_upper_ms"]),
        "max_source_skew_ms": float(feed["max_source_skew_upper_ms"]),
        "max_source_clock_error_ms": float(feed["max_source_clock_error_ms"]),
        "complete_cohort_confirmations": int(feed["complete_cohort_confirmations"]),
        "entry_buffer_cny": signal["entry_buffer_cny"],
        "total_reserve_cny": signal["total_reserve_cny"],
    }


def business_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    """Exclude process/output paths while retaining deterministic candidate facts."""

    volatile = {"report_path", "manifest_path", "runtime_chain"}
    return {key: value for key, value in report.items() if key not in volatile}


def run_replay(
    config: Mapping[str, Any],
    *,
    scenario: str | None = None,
    output_directory: Path | str | None = None,
    invoke_idle_probe: bool = False,
    invoke_next_probe: bool = False,
) -> dict[str, Any]:
    """Run a deterministic, zero-network and zero-order channel replay."""

    validate_config(config)
    if str(config["mode"]) != "replay":
        raise RunnerConfigurationError("REPLAY_MODE_REQUIRED")
    if str(config["purpose"]) not in REPLAY_PURPOSES:
        raise RunnerConfigurationError("REPLAY_PURPOSE_NOT_IMPLEMENTED_FAIL_CLOSED")
    fixture, fixture_path, fixture_hash = load_fixture(config)
    bundle = validate_bundle(fixture, config)
    chosen_scenario = str(scenario or _mapping(config["replay"], "replay")["scenario"])
    events = _cohort_events(fixture, bundle, chosen_scenario)

    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    broker = TickBroker(cash=float(_mapping(config["replay"], "replay")["starting_cash"]))
    cerebro.setbroker(broker)
    cerebro.addstrategy(CtpOptionsHighfreqStrategy, **_strategy_params(config, bundle))
    strategies = cerebro.run(channel=events)
    strategy = strategies[0]
    if invoke_idle_probe:
        strategy.notify_idle()
    if invoke_next_probe:
        strategy.next()

    report = strategy.replay_report()
    report.update(
        schema_version="iter25.ctp-options-highfreq-replay-report.v1",
        status="LOCAL_REPLAY_PASS",
        scenario=chosen_scenario,
        config_sha256=_canonical_hash(dict(config)),
        fixture_sha256=fixture_hash,
        bundle_sha256=canonical_sha256(bundle),
        fixture_path=str(fixture_path.relative_to(HERE)),
        external_network_requests=0,
        external_write_requests=0,
        simulated_broker_orders=0,
        market_evidence=False,
        profitability_evidence=False,
        runtime_chain={
            "cerebro": f"{type(cerebro).__module__}.{type(cerebro).__name__}",
            "broker": f"{type(broker).__module__}.{type(broker).__name__}",
            "event": f"{Event.__module__}.{Event.__name__}",
            "tick_event": f"{TickEvent.__module__}.{TickEvent.__name__}",
            "strategy": f"{type(strategy).__module__}.{type(strategy).__name__}",
        },
    )
    report["business_summary"] = business_summary(report)
    report["business_summary_hash"] = _canonical_hash(report["business_summary"])
    if output_directory is not None:
        directory = Path(output_directory).resolve()
        directory.mkdir(parents=True, exist_ok=False)
        report_path = directory / "report.json"
        manifest_path = directory / "run_manifest.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "iter25.ctp-options-highfreq-manifest.v1",
                    "mode": "replay",
                    "purpose": str(config["purpose"]),
                    "config_sha256": report["config_sha256"],
                    "fixture_sha256": fixture_hash,
                    "bundle_sha256": report["bundle_sha256"],
                    "external_network_requests": 0,
                    "external_write_requests": 0,
                    "actual_fills": 0,
                    "pnl_fields_emitted": False,
                    "hft_status": "NOT_ADMITTED",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        report["report_path"] = str(report_path)
        report["manifest_path"] = str(manifest_path)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--mode", choices=sorted(MODES))
    parser.add_argument("--purpose")
    parser.add_argument("--scenario")
    parser.add_argument("--output-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config, _ = load_config(args.config)
        config = effective_config(config, mode=args.mode, purpose=args.purpose)
        mode = str(config["mode"])
        if mode == "production":
            raise RunnerConfigurationError("PRODUCTION_NOT_SUPPORTED")
        if mode == "simnow":
            raise RunnerConfigurationError("SIMNOW_NOT_IMPLEMENTED_FAIL_CLOSED")
        if mode == "shadow":
            raise RunnerConfigurationError("SHADOW_NOT_IMPLEMENTED_NO_NETWORK")
        report = run_replay(
            config,
            scenario=args.scenario,
            output_directory=args.output_dir,
        )
    except (OSError, RunnerConfigurationError, ValueError) as exc:
        print(json.dumps({"status": "FAIL_CLOSED", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

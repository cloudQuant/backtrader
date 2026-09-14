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
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import backtrader as bt
import yaml
from backtrader.brokers.tickbroker import TickBroker
from backtrader.channel import Event, EventPriority
from backtrader.events import BarEvent, TickEvent
from backtrader.feeds import ClockMapping, CtpCohortNow

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
FROZEN_TIMING_MS = {
    "leg_timeout_ms": 1_000,
    "unhedged_timeout_ms": 3_000,
    "maximum_holding_timeout_ms": 60_000,
    "idle_interval_ms": 50,
}
MODES = frozenset({"replay", "shadow", "simnow", "production"})
REPLAY_PURPOSES = frozenset({"formula"})
_CREDENTIAL_TOKENS = ("password", "secret", "token", "auth_code", "api_key", "credential")
_ADAPTER_SCOPED_WRITE_EVIDENCE_BOUNDARY = (
    "NOT_PROVEN: the adapter membrane and market_data_only Broker only observe "
    "adapter-routed attempts; they cannot attest raw external provider writes."
)


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
            "timing",
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

    timing = _require_exact_keys(
        root["timing"],
        name="timing",
        keys={
            "provider_contract",
            "runtime_provider",
            "synthetic_fixtures_only",
            "leg_timeout_ms",
            "unhedged_timeout_ms",
            "maximum_holding_timeout_ms",
            "idle_interval_ms",
        },
    )
    if timing["provider_contract"] != "explicit_immutable_same_scope_read_model_v1":
        raise RunnerConfigurationError("timing provider contract is frozen")
    if timing["runtime_provider"] != "unavailable":
        raise RunnerConfigurationError("the replay must not configure a runtime timing provider")
    if timing["synthetic_fixtures_only"] is not True:
        raise RunnerConfigurationError("only local synthetic timing fixtures are permitted")
    for key, expected in FROZEN_TIMING_MS.items():
        if _positive_int(timing[key], f"timing.{key}") != expected:
            raise RunnerConfigurationError(f"timing.{key} is frozen at {expected}ms")

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


class _ObservationTrustedNowProvider:
    """Validate caller-owned CTP time evidence at the Feed dispatch boundary.

    ``BtApiFeed`` intentionally swallows provider exceptions to keep a raw
    malformed quote from crashing its dispatch loop.  This wrapper therefore
    retains the first failure and lets the outer observation boundary reject
    the whole run only after normal, read-only shutdown has completed.
    """

    _SYNTHETIC_MARKERS = ("fixture", "replay", "synthetic")

    def __init__(
        self,
        *,
        provider: Callable[[Any], CtpCohortNow],
        mapping: ClockMapping,
        expected_symbols: tuple[str, ...],
        observation_duration_seconds: float,
        observation_blocked: type[Exception],
    ) -> None:
        self._provider = provider
        self._mapping = mapping
        self._expected_symbols = expected_symbols
        self._observation_window_ns = int(math.ceil(observation_duration_seconds * 1_000_000_000.0))
        self._observation_blocked = observation_blocked
        self._failure: Exception | None = None
        self.calls = 0
        self._accepted_symbols: set[str] = set()
        self._initial_coherent_mono_ns: int | None = None

    @property
    def accepted_symbols(self) -> list[str]:
        return [symbol for symbol in self._expected_symbols if symbol in self._accepted_symbols]

    def __call__(self, tick: Any) -> CtpCohortNow:
        self.calls += 1
        try:
            self._validate_tick(tick)
            now = self._provider(tick)
            if not isinstance(now, CtpCohortNow):
                self._reject(
                    "TRUSTED_COHORT_NOW_REQUIRED",
                    "live observation requires CtpCohortNow evidence",
                )
            if now.clock_domain_id != self._mapping.clock_domain_id:
                self._reject(
                    "TRUSTED_COHORT_NOW_DOMAIN",
                    "trusted CTP time must use the live mapping clock domain",
                )
            tick_receive_ns = getattr(tick, "recv_monotonic_ns", None)
            if type(tick_receive_ns) is not int or now.now_monotonic_ns < tick_receive_ns:
                self._reject(
                    "TRUSTED_COHORT_NOW_STALE",
                    "trusted CTP time predates the delivered quote",
                )
            try:
                self._mapping.validate_pair(now.now_epoch, now.now_monotonic_ns / 1_000_000_000.0)
            except (TypeError, ValueError, OverflowError):
                self._reject(
                    "TRUSTED_COHORT_NOW_MAPPING",
                    "trusted CTP time is outside the caller-owned live mapping",
                )
            self._require_observation_window_coverage(now)
            self._accepted_symbols.add(str(tick.symbol))
            return now
        except Exception as error:
            if self._failure is None:
                self._failure = error
            raise

    def require_complete(self) -> None:
        """Turn swallowed Feed validation failures into a terminal run result."""

        if self._failure is not None:
            raise self._failure
        missing = [
            symbol for symbol in self._expected_symbols if symbol not in self._accepted_symbols
        ]
        if missing:
            self._reject(
                "TRUSTED_COHORT_NOW_INCOMPLETE",
                "live observation did not receive trusted CTP time for every configured leg",
            )

    def _require_observation_window_coverage(self, now: CtpCohortNow) -> None:
        """Bind the complete bounded run to its first coherent live time.

        The wall-clock watchdog may remain active while an otherwise live
        source is idle.  A mapping that merely covers already-delivered ticks
        cannot attest that idle part of the requested observation interval.
        The first CTP-coherent time is therefore a conservative trusted origin:
        the mapping must remain valid for the entire requested interval after
        it, including its declared calibration error.
        """

        if self._initial_coherent_mono_ns is not None:
            return
        required_valid_until_ns = (
            now.now_monotonic_ns + self._observation_window_ns + self._mapping.error_bound_ns
        )
        if required_valid_until_ns > self._mapping.valid_until_mono_ns:
            self._reject(
                "LIVE_CLOCK_MAPPING_DURATION_REQUIRED",
                "trusted clock mapping does not cover the full engineering observation window",
            )
        self._initial_coherent_mono_ns = now.now_monotonic_ns

    def _validate_tick(self, tick: Any) -> None:
        if getattr(tick, "schema_version", None) != "ctp.quote.v2":
            self._reject(
                "LIVE_CTP_QUOTE_REQUIRED", "live observation requires strict CTP-v2 quotes"
            )
        if getattr(tick, "clock_domain_id", None) != self._mapping.clock_domain_id:
            self._reject(
                "LIVE_QUOTE_CLOCK_DOMAIN",
                "CTP quote clock domain differs from the caller-owned live mapping",
            )
        if getattr(tick, "connection_generation", None) != self._mapping.connection_generation:
            self._reject(
                "LIVE_QUOTE_GENERATION",
                "CTP quote generation differs from the caller-owned live mapping",
            )
        if getattr(tick, "rules_hash", None) != self._mapping.rules_hash:
            self._reject(
                "LIVE_QUOTE_RULES_HASH",
                "CTP quote rules identity differs from the frozen candidate bundle",
            )
        source_values = (
            str(getattr(tick, "source", "") or "").lower(),
            str(getattr(tick, "event_time_source", "") or "").lower(),
        )
        if any(marker in value for value in source_values for marker in self._SYNTHETIC_MARKERS):
            self._reject(
                "SYNTHETIC_QUOTE_SOURCE",
                "engineering observation rejects replay or synthetic quote provenance",
            )

    def _reject(self, code: str, message: str) -> None:
        raise self._observation_blocked(code, message)


class _ObservationLifecycleProbe(bt.Analyzer):
    """Start the deadline only once the real strategy lifecycle is active."""

    params = (("on_started", None),)

    def start(self) -> None:
        on_started = self.p.on_started
        if not callable(on_started):
            raise RuntimeError("engineering observation lifecycle callback is unavailable")
        on_started()


def _require_engineering_duration(run_seconds: Any, observation_blocked: type[Exception]) -> float:
    if isinstance(run_seconds, bool):
        raise observation_blocked(
            "ENGINEERING_DURATION", "run_seconds must be a bounded positive number"
        )
    try:
        seconds = float(run_seconds)
    except (TypeError, ValueError) as error:
        raise observation_blocked(
            "ENGINEERING_DURATION", "run_seconds must be a bounded positive number"
        ) from error
    if not math.isfinite(seconds) or not 0.0 < seconds <= 3600.0:
        raise observation_blocked(
            "ENGINEERING_DURATION", "engineering observation must run for at most 3600 seconds"
        )
    return seconds


def _require_live_clock_mapping(
    mapping: Any,
    *,
    bundle_hash: str,
    observation_blocked: type[Exception],
) -> ClockMapping:
    if not isinstance(mapping, ClockMapping):
        raise observation_blocked(
            "LIVE_CLOCK_MAPPING_REQUIRED", "engineering observation requires a live ClockMapping"
        )
    source = str(mapping.source or "").lower()
    if (
        mapping.synthetic is not False
        or mapping.rules_hash != bundle_hash
        or any(marker in source for marker in ("fixture", "replay", "synthetic"))
    ):
        raise observation_blocked(
            "LIVE_CLOCK_MAPPING_REQUIRED",
            "engineering observation requires a non-synthetic candidate-bound ClockMapping",
        )
    return mapping


def _require_feed_clock(feed_clock: Any, observation_blocked: type[Exception]) -> None:
    if not any(
        callable(getattr(feed_clock, name, None))
        for name in ("monotonic_ns", "monotonic_now", "monotonic")
    ):
        raise observation_blocked(
            "LIVE_FEED_CLOCK_REQUIRED",
            "engineering observation requires an injected monotonic feed clock",
        )


def _observation_shutdown_summary(
    broker: Any, store: Any, observation_blocked: type[Exception]
) -> dict[str, Any]:
    getter = getattr(broker, "get_shutdown_summary", None)
    try:
        summary = getter() if callable(getter) else None
    except Exception as error:
        raise observation_blocked(
            "SHUTDOWN_INCOMPLETE", "market-data-only shutdown evidence could not be read"
        ) from error
    if not isinstance(summary, Mapping):
        raise observation_blocked(
            "SHUTDOWN_INCOMPLETE", "market-data-only shutdown evidence is unavailable"
        )
    if (
        summary.get("status") not in {"OBSERVATION_ONLY", "OBSERVATION_ONLY_NONFLAT"}
        or summary.get("market_data_only") is not True
        or summary.get("cancel_requested") != 0
        or summary.get("close_requested") != 0
        or summary.get("store_shutdown_state") != "PASS"
    ):
        raise observation_blocked(
            "SHUTDOWN_INCOMPLETE", "market-data-only shutdown did not prove a zero-write stop"
        )
    try:
        health = store.get_command_health()
    except Exception as error:
        raise observation_blocked(
            "SHUTDOWN_INCOMPLETE", "Store shutdown health could not be read"
        ) from error
    if not isinstance(health, Mapping) or health.get("shutdown_state") != "PASS":
        raise observation_blocked("SHUTDOWN_INCOMPLETE", "Store shutdown health is not PASS")
    return {
        "status": str(summary["status"]),
        "market_data_only": True,
        "cancel_requested": 0,
        "close_requested": 0,
        "store_shutdown_state": "PASS",
    }


def _unstarted_observation_graph_shutdown_proven(
    *,
    broker: Any | None,
    store: Any | None,
    guarded_api: Any | None,
) -> bool:
    """Prove that a graph which never started could not have written.

    A construction failure can happen after a Store, Broker, or one Feed has
    been created but before Cerebro starts either transport.  The normal
    broker summary is deliberately ``NOT_STARTED`` in that state, so it cannot
    meet the stricter live-session shutdown projection.  It is nevertheless
    safe only when the Store confirms that it never connected and the
    deny-default membrane observed no attempted write.
    """

    if store is None:
        return broker is None
    try:
        health = store.get_command_health()
    except Exception:
        return False
    if not isinstance(health, Mapping) or health.get("shutdown_state") not in {
        "NOT_STARTED",
        "PASS",
    }:
        return False
    if getattr(store, "is_connected", None) is not False:
        return False
    if broker is not None:
        try:
            summary = broker.get_shutdown_summary()
        except Exception:
            return False
        if not isinstance(summary, Mapping) or summary.get("status") != "NOT_STARTED":
            return False
    if guarded_api is not None:
        try:
            audit = guarded_api.audit()
        except Exception:
            return False
        if not isinstance(audit, Mapping) or audit.get("forbidden_write_attempts") != {}:
            return False
    return True


def _force_observation_graph_shutdown(
    *,
    broker: Any | None,
    feeds: Iterable[Any],
    store: Any | None,
    guarded_api: Any | None,
    observation_blocked: type[Exception],
) -> None:
    """Stop every constructed graph component and prove a zero-write teardown.

    This is only used when normal Cerebro cleanup was skipped.  It attempts
    every stop in dependency order even if an earlier stop fails, and a
    shutdown-proof failure intentionally takes precedence over the initiating
    construction or binding exception.
    """

    cleanup_failed = False
    if broker is not None:
        try:
            broker.stop()
        except BaseException:
            cleanup_failed = True
    for feed in feeds:
        try:
            feed.stop()
        except BaseException:
            cleanup_failed = True
    if store is not None:
        try:
            store.stop(timeout=2.0)
        except BaseException:
            cleanup_failed = True
    if cleanup_failed:
        raise observation_blocked(
            "SHUTDOWN_INCOMPLETE",
            "engineering observation could not stop every constructed component",
        )
    if store is None:
        return
    try:
        _observation_shutdown_summary(broker, store, observation_blocked)
    except observation_blocked:
        if not _unstarted_observation_graph_shutdown_proven(
            broker=broker,
            store=store,
            guarded_api=guarded_api,
        ):
            raise


def _require_ctp_session_binding(
    store: Any,
    mapping: ClockMapping,
    observation_blocked: type[Exception],
) -> dict[str, Any]:
    """Bind this run through the owned Store's public CTP read accessor."""

    if store.is_connected is not True:
        raise observation_blocked(
            "CTP_SESSION_STORE_UNREADY",
            "engineering observation requires a connected owned Store before session binding",
        )
    try:
        get_state = getattr(store, "get_ctp_session_state")
    except AttributeError:
        raise observation_blocked(
            "CTP_SESSION_STATE_REQUIRED",
            "public CTP session-state evidence is unavailable",
        ) from None
    if not callable(get_state):
        raise observation_blocked(
            "CTP_SESSION_STATE_REQUIRED",
            "public CTP session-state evidence is unavailable",
        )
    try:
        state = get_state()
    except Exception:
        raise observation_blocked(
            "CTP_SESSION_STATE_REQUIRED",
            "public CTP session-state evidence could not be read",
        ) from None
    if not isinstance(state, Mapping):
        raise observation_blocked(
            "CTP_SESSION_STATE_REQUIRED",
            "public CTP session-state evidence must be a mapping",
        )
    required_fields = {
        "environment_profile",
        "connected",
        "read_only_ready",
        "execution_gate_armed",
        "account_fingerprint",
        "connection_generation",
    }
    if not required_fields.issubset(state):
        raise observation_blocked(
            "CTP_SESSION_STATE_REQUIRED",
            "public CTP session-state evidence is incomplete",
        )

    actual_profile = state.get("environment_profile")
    if not isinstance(actual_profile, str) or not actual_profile.startswith("set2_7x24"):
        raise observation_blocked(
            "CTP_SESSION_PROFILE_REQUIRED",
            "connected CTP session is not the required Set-2 7x24 environment",
        )
    if state.get("connected") is not True:
        raise observation_blocked(
            "CTP_SESSION_CONNECTED_REQUIRED",
            "public CTP session-state evidence is not connected",
        )
    if state.get("read_only_ready") is not True:
        raise observation_blocked(
            "CTP_SESSION_READ_ONLY_REQUIRED",
            "public CTP session-state evidence is not read-only ready",
        )
    if state.get("execution_gate_armed") is not False:
        raise observation_blocked(
            "CTP_SESSION_EXECUTION_GATE_REQUIRED",
            "public CTP session-state evidence reports an armed execution gate",
        )
    account_fingerprint = state.get("account_fingerprint")
    if not isinstance(account_fingerprint, str) or not account_fingerprint.strip():
        raise observation_blocked(
            "CTP_SESSION_FINGERPRINT_REQUIRED",
            "public CTP session-state evidence lacks an account fingerprint",
        )
    generation = state.get("connection_generation")
    if (
        type(generation) is not int
        or generation <= 0
        or generation != mapping.connection_generation
    ):
        raise observation_blocked(
            "CTP_SESSION_GENERATION_REQUIRED",
            "public CTP session generation does not match the trusted clock mapping",
        )

    binding = {
        "source": "BtApiStore.get_ctp_session_state",
        "exchange_name": "CTP___FUTURE",
        "actual_environment_profile": actual_profile,
        "profile_family_prefix": "set2_7x24",
        "account_fingerprint_sha256": hashlib.sha256(
            account_fingerprint.encode("utf-8")
        ).hexdigest(),
        "read_only_ready": True,
        "execution_gate_armed": False,
        "connection_generation": generation,
        "clock_mapping_id": mapping.mapping_id,
        "clock_mapping_generation": mapping.connection_generation,
    }
    trading_day = state.get("trading_day")
    if isinstance(trading_day, str) and trading_day.strip():
        binding["trading_day"] = trading_day.strip()
    return binding


def run_engineering_observation(
    config: Mapping[str, Any],
    *,
    api: Any,
    environment_profile: str,
    run_seconds: float,
    feed_clock: Any,
    clock_mapping: ClockMapping,
    live_now_provider: Callable[[Any], CtpCohortNow],
) -> dict[str, Any]:
    """Run one bounded, injected, zero-write Set-2 strategy observation.

    This is deliberately not a CLI mode and does not load credentials.  A
    separately governed CTP owner must inject both the already-created API and
    the calibrated clock evidence.  Successful completion proves only that
    this strategy callback chain observed live-shaped data in a forced
    market-data-only session; it cannot establish G3, G4, profitability, or
    HFT admission.
    """

    try:
        from .engineering_smoke import (
            ENGINEERING_OBSERVATION_G3_STATUS,
            ENGINEERING_OBSERVATION_MAX_SECONDS,
            SECOND_SET_ENGINEERING_PROFILE,
            EngineeringObservationBlocked,
            _ObservationReadOnlyApi,
        )
    except ImportError:  # Direct module loading from this example directory.
        from engineering_smoke import (  # type: ignore[no-redef]
            ENGINEERING_OBSERVATION_G3_STATUS,
            ENGINEERING_OBSERVATION_MAX_SECONDS,
            SECOND_SET_ENGINEERING_PROFILE,
            EngineeringObservationBlocked,
            _ObservationReadOnlyApi,
        )

    if api is None:
        raise EngineeringObservationBlocked(
            "SDK_NOT_INJECTED", "engineering observation requires an explicit API object"
        )
    if environment_profile != SECOND_SET_ENGINEERING_PROFILE:
        raise EngineeringObservationBlocked(
            "SECOND_SET_PROFILE_REQUIRED",
            "engineering observation is restricted to the second SimNow profile",
        )
    seconds = _require_engineering_duration(run_seconds, EngineeringObservationBlocked)
    if seconds > ENGINEERING_OBSERVATION_MAX_SECONDS:
        raise EngineeringObservationBlocked(
            "ENGINEERING_DURATION", "engineering observation must run for at most 3600 seconds"
        )
    if not callable(live_now_provider):
        raise EngineeringObservationBlocked(
            "TRUSTED_COHORT_NOW_REQUIRED",
            "engineering observation requires an injected CtpCohortNow provider",
        )
    _require_feed_clock(feed_clock, EngineeringObservationBlocked)

    effective = effective_config(config, mode="shadow", purpose="observation")
    fixture, _fixture_path, _fixture_hash = load_fixture(effective)
    bundle = validate_bundle(fixture, effective)
    bundle_hash = canonical_sha256(bundle)
    mapping = _require_live_clock_mapping(
        clock_mapping,
        bundle_hash=bundle_hash,
        observation_blocked=EngineeringObservationBlocked,
    )
    symbols = tuple(str(bundle[role]["symbol"]) for role in ("future", "call", "put"))
    trusted_now = _ObservationTrustedNowProvider(
        provider=live_now_provider,
        mapping=mapping,
        expected_symbols=symbols,
        observation_duration_seconds=seconds,
        observation_blocked=EngineeringObservationBlocked,
    )
    # This ceiling starts before the native graph exists.  A slow Store,
    # Broker, Feed, or session binding must consume the same one-hour budget
    # as strategy observation; it cannot earn a fresh full hour afterwards.
    started_at = time.monotonic()
    lifecycle_deadline = started_at + ENGINEERING_OBSERVATION_MAX_SECONDS
    lifecycle_started = threading.Event()
    deadline_stop_requested = threading.Event()
    lifecycle_deadline_stop_requested = threading.Event()
    lifecycle_lock = threading.Lock()
    lifecycle_started_at: list[float] = []
    deadline_timer: list[threading.Timer] = []
    lifecycle_deadline_timer: list[threading.Timer] = []
    session_identity: list[dict[str, Any]] = []
    cerebro_ref: list[Any] = []
    guarded_api: Any | None = None
    store: Any | None = None
    broker: Any | None = None
    cerebro: Any | None = None
    feeds: list[Any] = []

    def request_lifecycle_deadline_stop() -> None:
        lifecycle_deadline_stop_requested.set()
        with lifecycle_lock:
            active_cerebro = cerebro_ref[0] if cerebro_ref else None
        if active_cerebro is not None:
            active_cerebro.runstop()

    def lifecycle_expired() -> bool:
        if time.monotonic() >= lifecycle_deadline:
            request_lifecycle_deadline_stop()
        return lifecycle_deadline_stop_requested.is_set()

    def require_lifecycle_budget() -> None:
        if lifecycle_expired():
            raise EngineeringObservationBlocked(
                "OBSERVATION_LIFECYCLE_DURATION_EXCEEDED",
                "engineering observation exhausted its end-to-end 3600-second lifecycle budget",
            )

    def cancel_watchdog(timer: threading.Timer | None) -> EngineeringObservationBlocked | None:
        if timer is None:
            return None
        timer.cancel()
        timer.join(timeout=1.0)
        if timer.is_alive():
            return EngineeringObservationBlocked(
                "WATCHDOG_INCOMPLETE", "engineering observation watchdog did not stop"
            )
        return None

    def start_lifecycle_deadline_watchdog() -> None:
        remaining_seconds = lifecycle_deadline - time.monotonic()
        if remaining_seconds <= 0.0:
            request_lifecycle_deadline_stop()
            return
        timer = threading.Timer(remaining_seconds, request_lifecycle_deadline_stop)
        timer.name = "iter25-engineering-observation-lifecycle-deadline"
        timer.daemon = True
        with lifecycle_lock:
            lifecycle_deadline_timer.append(timer)
        timer.start()

    # It can fire before Cerebro exists.  In that case the event makes every
    # construction checkpoint fail closed before ``run()`` clears its own
    # stop event for a new scope.
    start_lifecycle_deadline_watchdog()
    construction_error: BaseException | None = None
    construction_shutdown_error: EngineeringObservationBlocked | None = None
    try:
        require_lifecycle_budget()
        guarded_api = _ObservationReadOnlyApi(api)
        store = bt.stores.BtApiStore(
            provider="btapi",
            api=guarded_api,
            config={"execution_config": {"market_data_only": True}},
            autostart=False,
        )
        require_lifecycle_budget()
        broker = store.getbroker(
            market_data_only=True,
            flatten_on_stop=False,
            force_refresh_queries=False,
            account_refresh_interval=3600.0,
            positions_refresh_interval=3600.0,
            open_orders_refresh_interval=3600.0,
            sdk_preflight=False,
            cash=float(_mapping(effective["replay"], "replay")["starting_cash"]),
        )
        require_lifecycle_budget()
        cerebro = bt.Cerebro(stdstats=False, quicknotify=True, runonce=False)
        with lifecycle_lock:
            cerebro_ref.append(cerebro)
        cerebro.setbroker(broker)
        require_lifecycle_budget()
        for symbol, role in zip(symbols, ("future", "call", "put")):
            feed = store.getdata(
                dataname=symbol,
                timeframe=bt.TimeFrame.Ticks,
                compression=1,
                backfill_start=False,
                dispatch_ticks=True,
                dispatch_bars=False,
                qcheck=0.01,
                price_tick=float(bundle[role]["tick_size"]),
                clock=feed_clock,
                ctp_decision_now_provider=trusted_now,
            )
            feeds.append(feed)
            cerebro.adddata(feed, name=feed._dataname)
            require_lifecycle_budget()
        cerebro.addstrategy(CtpOptionsHighfreqStrategy, **_strategy_params(effective, bundle))
        require_lifecycle_budget()
    except BaseException as error:
        construction_error = error
        with lifecycle_lock:
            deadline = deadline_timer[0] if deadline_timer else None
            lifecycle_timer = lifecycle_deadline_timer[0] if lifecycle_deadline_timer else None
        for timer in (deadline, lifecycle_timer):
            watchdog_error = cancel_watchdog(timer)
            if watchdog_error is not None:
                construction_shutdown_error = watchdog_error
        try:
            _force_observation_graph_shutdown(
                broker=broker,
                feeds=feeds,
                store=store,
                guarded_api=guarded_api,
                observation_blocked=EngineeringObservationBlocked,
            )
        except EngineeringObservationBlocked as shutdown_failure:
            construction_shutdown_error = shutdown_failure
        if construction_shutdown_error is not None:
            raise construction_shutdown_error from construction_error
        if isinstance(construction_error, EngineeringObservationBlocked):
            raise construction_error from None
        raise EngineeringObservationBlocked(
            "ENGINEERING_CONSTRUCTION_FAILED",
            "engineering observation could not construct its native graph",
        ) from construction_error

    def request_deadline_stop() -> None:
        deadline_stop_requested.set()
        if cerebro is not None:
            cerebro.runstop()

    def start_deadline_watchdog() -> None:
        """Spend only the remaining end-to-end budget after session binding."""

        lifecycle_budget_exhausted = False
        with lifecycle_lock:
            if lifecycle_started.is_set():
                return
            lifecycle_started_at.append(time.monotonic())
            lifecycle_started.set()
            remaining_seconds = lifecycle_deadline - time.monotonic()
            if remaining_seconds <= 0.0 or lifecycle_deadline_stop_requested.is_set():
                lifecycle_budget_exhausted = True
            else:
                timer = threading.Timer(min(seconds, remaining_seconds), request_deadline_stop)
                timer.name = "iter25-engineering-observation-watchdog"
                timer.daemon = True
                deadline_timer.append(timer)
                timer.start()
        if lifecycle_budget_exhausted:
            request_lifecycle_deadline_stop()

    def bind_session_then_start_deadline() -> None:
        session_identity.append(
            _require_ctp_session_binding(
                store,
                mapping,
                EngineeringObservationBlocked,
            )
        )
        start_deadline_watchdog()

    try:
        cerebro.addanalyzer(_ObservationLifecycleProbe, on_started=bind_session_then_start_deadline)
        require_lifecycle_budget()
    except BaseException as error:
        with lifecycle_lock:
            deadline = deadline_timer[0] if deadline_timer else None
            lifecycle_timer = lifecycle_deadline_timer[0] if lifecycle_deadline_timer else None
        for timer in (deadline, lifecycle_timer):
            watchdog_error = cancel_watchdog(timer)
            if watchdog_error is not None:
                construction_shutdown_error = watchdog_error
        try:
            _force_observation_graph_shutdown(
                broker=broker,
                feeds=feeds,
                store=store,
                guarded_api=guarded_api,
                observation_blocked=EngineeringObservationBlocked,
            )
        except EngineeringObservationBlocked as shutdown_failure:
            construction_shutdown_error = shutdown_failure
        if construction_shutdown_error is not None:
            raise construction_shutdown_error from error
        if isinstance(error, EngineeringObservationBlocked):
            raise error from None
        raise EngineeringObservationBlocked(
            "ENGINEERING_CONSTRUCTION_FAILED",
            "engineering observation could not finish constructing its native graph",
        ) from error

    strategies: list[Any] | None = None
    run_error: BaseException | None = None
    shutdown_error: EngineeringObservationBlocked | None = None
    run_finished_at = started_at
    try:
        strategies = cerebro.run(preload=False, runonce=False)
    except BaseException as error:
        run_error = error
    finally:
        run_finished_at = time.monotonic()
        with lifecycle_lock:
            deadline = deadline_timer[0] if deadline_timer else None
            lifecycle_timer = lifecycle_deadline_timer[0] if lifecycle_deadline_timer else None
        for timer in (deadline, lifecycle_timer):
            watchdog_error = cancel_watchdog(timer)
            if watchdog_error is not None:
                shutdown_error = watchdog_error
        # An error-path summary reader is evidence, not cleanup itself.  Treat
        # a failed read as unproven so the forced graph teardown below still
        # runs; otherwise a getter exception could escape this ``finally`` and
        # bypass Broker, Feed, and Store shutdown altogether.
        try:
            shutdown_getter = getattr(broker, "get_shutdown_summary", None)
            shutdown_before = shutdown_getter() if callable(shutdown_getter) else None
        except BaseException:
            shutdown_before = None
        aborted_before_normal_teardown = run_error is not None and (
            bool(getattr(store, "is_connected", False))
            or not isinstance(shutdown_before, Mapping)
            or shutdown_before.get("status") == "NOT_STARTED"
        )
        if aborted_before_normal_teardown:
            try:
                _force_observation_graph_shutdown(
                    broker=broker,
                    feeds=feeds,
                    store=store,
                    guarded_api=guarded_api,
                    observation_blocked=EngineeringObservationBlocked,
                )
            except EngineeringObservationBlocked as error:
                shutdown_error = error
        if run_error is not None and shutdown_error is None:
            try:
                _observation_shutdown_summary(broker, store, EngineeringObservationBlocked)
            except EngineeringObservationBlocked as error:
                shutdown_error = error
    ended_at = time.monotonic()
    elapsed_seconds = ended_at - started_at
    lifecycle_complete = (
        elapsed_seconds <= ENGINEERING_OBSERVATION_MAX_SECONDS
        and not lifecycle_deadline_stop_requested.is_set()
    )

    if shutdown_error is not None:
        raise shutdown_error
    if not lifecycle_complete:
        raise EngineeringObservationBlocked(
            "OBSERVATION_LIFECYCLE_DURATION_EXCEEDED",
            "engineering observation exceeded its end-to-end 3600-second lifecycle budget",
        )
    if run_error is not None:
        if isinstance(run_error, EngineeringObservationBlocked):
            raise run_error
        raise EngineeringObservationBlocked(
            "ENGINEERING_RUN_FAILED",
            "engineering observation did not complete its native lifecycle",
        ) from run_error
    if not isinstance(strategies, list) or len(strategies) != 1:
        raise EngineeringObservationBlocked(
            "ENGINEERING_STRATEGY_MISSING",
            "engineering observation did not produce one strategy instance",
        )
    strategy = strategies[0]
    if not isinstance(strategy, CtpOptionsHighfreqStrategy):
        raise EngineeringObservationBlocked(
            "ENGINEERING_STRATEGY_TYPE",
            "engineering observation did not run CtpOptionsHighfreqStrategy",
        )
    shutdown = _observation_shutdown_summary(broker, store, EngineeringObservationBlocked)
    trusted_now.require_complete()
    write_guard = guarded_api.audit()
    if write_guard["forbidden_write_attempts"]:
        raise EngineeringObservationBlocked(
            "FORBIDDEN_WRITE_ATTEMPT", "engineering observation attempted an API write"
        )
    adapter_scoped_write_attempts = sum(write_guard["forbidden_write_attempts"].values())
    strategy_report = strategy.replay_report()
    if strategy_report.get("hft_status") != "NOT_ADMITTED":
        raise EngineeringObservationBlocked(
            "HFT_ADMISSION_STATE_INVALID", "engineering observation cannot alter HFT admission"
        )
    if broker.get_param("market_data_only") is not True:
        raise EngineeringObservationBlocked(
            "MARKET_DATA_ONLY_REQUIRED", "engineering observation broker is not read-only"
        )
    if getattr(store, "_sdk_mode", False) and not store._is_sdk_market_data_only():
        raise EngineeringObservationBlocked(
            "MARKET_DATA_ONLY_REQUIRED", "managed Store is not read-only"
        )
    if not lifecycle_started.is_set() or not lifecycle_started_at:
        raise EngineeringObservationBlocked(
            "ENGINEERING_LIFECYCLE_MISSING",
            "engineering observation did not enter the strategy lifecycle",
        )
    if len(session_identity) != 1:
        raise EngineeringObservationBlocked(
            "CTP_SESSION_STATE_REQUIRED",
            "engineering observation did not bind exactly one connected CTP session",
        )
    if not deadline_stop_requested.is_set():
        raise EngineeringObservationBlocked(
            "ENGINEERING_DURATION_INCOMPLETE",
            "engineering observation ended before its bounded deadline",
        )

    return {
        "schema_version": "iter25.ctp-options-highfreq-engineering-observation.v1",
        "status": "PASS_ENGINEERING_STRATEGY_OBSERVATION",
        "mode": "shadow",
        "purpose": "observation",
        "requested_environment_profile": str(environment_profile),
        "session_binding": session_identity[0],
        "config_sha256": _canonical_hash(effective),
        "bundle_sha256": bundle_hash,
        "chain": {
            "store": type(store).__name__,
            "feeds": [type(feed).__name__ for feed in feeds],
            "broker": type(broker).__name__,
            "cerebro": type(cerebro).__name__,
            "strategy": type(strategy).__name__,
        },
        "duration": {
            "requested_seconds": seconds,
            "elapsed_seconds": elapsed_seconds,
            "strategy_started": True,
            "active_window_elapsed_seconds": run_finished_at - lifecycle_started_at[0],
            "deadline_stop_requested": deadline_stop_requested.is_set(),
            "lifecycle_deadline_stop_requested": lifecycle_deadline_stop_requested.is_set(),
            "elapsed_within_maximum": lifecycle_complete,
            "maximum_seconds": ENGINEERING_OBSERVATION_MAX_SECONDS,
        },
        "feed_evidence": {
            "clock_mapping_id": mapping.mapping_id,
            "clock_domain": mapping.clock_domain_id,
            "clock_source": mapping.source,
            "synthetic": False,
            "trusted_cohort_now_calls": trusted_now.calls,
            "accepted_symbols": trusted_now.accepted_symbols,
        },
        "strategy": {
            "callback_counts": dict(strategy.callback_counts),
            "ordinary_intent_count": len(strategy._ordinary_intents),
            "hft_status": "NOT_ADMITTED",
            "execution_permission": "NOT_PROVEN",
        },
        "write_guard": write_guard,
        "shutdown": shutdown,
        "adapter_scoped_write_attempts": adapter_scoped_write_attempts,
        "external_trade_writes": "NOT_PROVEN",
        "external_trade_writes_basis": _ADAPTER_SCOPED_WRITE_EVIDENCE_BOUNDARY,
        "pnl_fields_emitted": False,
        "gates": {
            "G3_first_set_read_only": ENGINEERING_OBSERVATION_G3_STATUS,
            "G3_evaluation": "NOT_APPLICABLE_ENGINEERING_ONLY",
            "G4_simnow_mechanical": "NOT_RUN",
            "HFT_admission": "NOT_ADMITTED",
        },
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

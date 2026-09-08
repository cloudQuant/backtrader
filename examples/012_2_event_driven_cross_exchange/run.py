"""Run the independent event-driven OKX/Binance perpetual strategy."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import time
from typing import Mapping

import backtrader as bt
from backtrader.brokers.hft.exchange import SimpleExchangeModel
from backtrader.brokers.mixbroker import MixBroker
from backtrader.comminfo import ComminfoFuturesPercent
from backtrader.stores.btapistore import BtApiStore
from bt_api_py import (
    CrossVenueLeg as InstrumentRule,
    FeeSchedule,
    FundingSnapshot,
    InstrumentSpec,
    coerce_funding_snapshot,
    decimal_value,
)
from examples.strategy_candidate_approval import (
    APPROVAL_PUBLIC_KEY_SHA256,
    DemoApprovalVerificationError,
    collect_runtime_source_provenance,
    verify_demo_approval,
    write_private_json_report,
)
import yaml

if __package__:
    from .strategy import CrossExchangeArbitrageStrategy, EventArbitrageEngine, EventBook
    from .strategy import EventPathQualification
    from .strategy import EventDrivenRisk, VENUE_SYMBOLS
else:
    from strategy import CrossExchangeArbitrageStrategy, EventArbitrageEngine, EventBook
    from strategy import EventPathQualification
    from strategy import EventDrivenRisk, VENUE_SYMBOLS


HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE.parent / "strategy-candidate-manifest.json"
DEMO_APPROVAL_TRUST_ROOT = HERE.parent / "demo-approval-trust-root.pem"
DEMO_APPROVAL_PUBLIC_KEY_SHA256 = APPROVAL_PUBLIC_KEY_SHA256
DEFAULT_CONFIG = HERE / "config.yaml"
STRATEGY_ID = "012_2_event_driven_cross_exchange"
EXCHANGES = {"okx": "OKX___SWAP", "binance": "BINANCE___SWAP"}
SCENARIOS = ("profitable", "loss", "no_edge", "partial", "unknown", "gap")
MODES = ("replay", "shadow", "paper-live", "demo")
OKX_API_REGIONS = frozenset({"global", "eea", "us", "tr"})
CONSERVATIVE_TAKER_FEE = Decimal("0.0006")
PAPER_RISK_LEDGER_PATH = (
    Path.home() / ".bt_api_py" / "paper-ledgers" / "okx-binance-perpetual-usdt.account-risk.json"
)


class RunnerConfigurationError(ValueError):
    pass


class DemoApprovalError(RunnerConfigurationError):
    pass


def mode_policy(mode):
    if mode not in MODES:
        raise RunnerConfigurationError(f"unsupported mode: {mode}")
    return {
        "network": mode != "replay",
        "sdk_writes": mode == "demo",
        "hypothetical_fills": mode == "paper-live",
        "fills_forbidden": mode in {"replay", "shadow"},
    }


def _canonical_hash(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _file_sha256(path: Path, label: str) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        raise RunnerConfigurationError(f"{label} is unavailable") from exc


def load_config(path: Path = DEFAULT_CONFIG):
    with Path(path).open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    required = {
        "schema_version",
        "strategy_id",
        "venues",
        "observation",
        "funding",
        "strategy_params",
    }
    if set(config) - (required | {"mode", "run_timeout_seconds", "okx_api_region"}):
        raise RunnerConfigurationError("configuration contains unknown top-level fields")
    if not required.issubset(config) or config["strategy_id"] != STRATEGY_ID:
        raise RunnerConfigurationError("configuration does not describe this strategy")
    if config.get("schema_version") != 2:
        raise RunnerConfigurationError("configuration schema_version must be 2")
    if "mode" in config:
        mode_policy(config["mode"])
    if config["venues"] != VENUE_SYMBOLS:
        raise RunnerConfigurationError("only the configured perpetual contracts are supported")
    api_region = config.get("okx_api_region", "global")
    if not isinstance(api_region, str) or api_region not in OKX_API_REGIONS:
        raise RunnerConfigurationError("okx_api_region must be global, eea, us or tr")
    config["okx_api_region"] = api_region
    return config


def load_candidate(manifest_path: Path = MANIFEST_PATH):
    path = Path(manifest_path).resolve()
    with path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    matches = [
        row for row in manifest.get("candidates", []) if row.get("strategy_id") == STRATEGY_ID
    ]
    if len(matches) != 1:
        raise RunnerConfigurationError("manifest must contain exactly one strategy candidate")
    candidate = matches[0]
    payload = {
        key: value
        for key, value in candidate.items()
        if key not in {"candidate_sha256", "demo_approval"}
    }
    if candidate.get("candidate_sha256") != _canonical_hash(payload):
        raise RunnerConfigurationError("candidate fingerprint does not match manifest content")
    resolved = (path.parent / candidate["resolved_example_path"]).resolve()
    entrypoint = (resolved / candidate["entrypoint"]).resolve()
    strategy_path = (resolved / candidate["strategy_module"]).resolve()
    config_path = (resolved / "config.yaml").resolve()
    if resolved != HERE or entrypoint != Path(__file__).resolve():
        raise RunnerConfigurationError("manifest resolves to a different example")
    if strategy_path.parent != resolved or config_path.parent != resolved:
        raise RunnerConfigurationError("manifest content paths escape the example directory")
    if _file_sha256(entrypoint, "runner source") != candidate.get("runner_sha256"):
        raise RunnerConfigurationError("runner source fingerprint mismatch")
    if _file_sha256(strategy_path, "strategy source") != candidate.get("strategy_sha256"):
        raise RunnerConfigurationError("strategy source fingerprint mismatch")
    if _file_sha256(config_path, "candidate config") != candidate.get("config_sha256"):
        raise RunnerConfigurationError("candidate config fingerprint mismatch")
    return manifest, candidate, path


def _validate_network_admission(manifest, candidate, mode, preflight, config):
    """Apply the manifest and config mode contract before any Store is created."""

    if preflight and mode != "demo":
        raise RunnerConfigurationError("preflight is only valid for demo mode")
    manifest_status = manifest.get("manifest_status")
    if not isinstance(manifest_status, str) or not manifest_status.strip():
        raise RunnerConfigurationError("manifest_status is missing")
    configured_mode = config.get("mode")
    if configured_mode is not None and configured_mode != mode:
        raise RunnerConfigurationError("configuration mode does not match the requested mode")
    allowed_modes = candidate.get("allowed_modes")
    conditional_modes = candidate.get("conditional_modes")
    if (
        not isinstance(allowed_modes, list)
        or any(not isinstance(item, str) or item not in MODES for item in allowed_modes)
        or len(set(allowed_modes)) != len(allowed_modes)
    ):
        raise RunnerConfigurationError("candidate allowed_modes is invalid")
    if not isinstance(conditional_modes, Mapping) or any(
        key not in MODES or not isinstance(value, str) or not value
        for key, value in conditional_modes.items()
    ):
        raise RunnerConfigurationError("candidate conditional_modes is invalid")

    if preflight:
        return {
            "manifest_status": manifest_status,
            "candidate_mode_status": conditional_modes.get("demo", "NOT_DECLARED"),
            "execution_admitted": False,
            "preflight_only": True,
        }

    error_cls = DemoApprovalError if mode == "demo" else RunnerConfigurationError
    if mode in {"paper-live", "demo"} and candidate.get("research_status") != "PASS":
        raise error_cls(f"{mode} requires a PASS research candidate")
    if mode not in allowed_modes:
        condition = conditional_modes.get(mode, "NOT_ALLOWED")
        raise error_cls(f"candidate mode {mode} is not admitted: {condition}")
    condition = conditional_modes.get(mode)
    if condition is not None and condition.upper().startswith("PROHIBITED"):
        raise error_cls(f"candidate mode {mode} is prohibited: {condition}")
    if mode == "paper-live" and manifest_status not in {
        "PAPER_LIVE_APPROVED",
        "DEMO_APPROVED",
    }:
        raise RunnerConfigurationError("manifest_status does not authorize paper-live execution")
    if mode == "demo" and manifest_status != "DEMO_APPROVED":
        raise DemoApprovalError("manifest_status does not authorize demo execution")
    return {
        "manifest_status": manifest_status,
        "candidate_mode_status": condition or "ALLOWED",
        "execution_admitted": True,
        "preflight_only": False,
    }


def _bounded_requested_duration(duration, config):
    requested = decimal_value(duration, "duration")
    configured = decimal_value(config.get("run_timeout_seconds"), "run_timeout_seconds")
    if requested <= 0 or configured <= 0:
        raise RunnerConfigurationError("duration bounds must be finite and positive")
    if requested > configured:
        raise RunnerConfigurationError("duration exceeds the candidate-bound run timeout")
    return requested


def _approval_lease(receipt, requested_duration, risk, shutdown_seconds, now=None):
    constraints = receipt.get("constraints")
    if not isinstance(constraints, Mapping):
        raise DemoApprovalError("demo approval constraints are missing")
    maximum_duration = decimal_value(
        constraints.get("maximum_duration_seconds"), "approval maximum duration"
    )
    maximum_quantity = decimal_value(
        constraints.get("maximum_quantity_base"), "approval maximum quantity"
    )
    maximum_order_count = constraints.get("maximum_order_count")
    if (
        maximum_duration <= 0
        or maximum_quantity <= 0
        or type(maximum_order_count) is not int
        or maximum_order_count <= 0
    ):
        raise DemoApprovalError("demo approval constraints are invalid")
    if requested_duration > maximum_duration:
        raise DemoApprovalError("duration exceeds the signed demo approval limit")
    if risk.quantity_base > maximum_quantity:
        raise DemoApprovalError("quantity exceeds the signed demo approval limit")
    expires_raw = receipt.get("expires_at")
    try:
        expires_at = datetime.fromisoformat(str(expires_raw)[:-1] + "+00:00")
    except (TypeError, ValueError) as exc:
        raise DemoApprovalError("demo approval expiry is invalid") from exc
    if not isinstance(expires_raw, str) or not expires_raw.endswith("Z"):
        raise DemoApprovalError("demo approval expiry is invalid")
    checked_at = now or datetime.now(timezone.utc)
    if checked_at.tzinfo is None:
        raise DemoApprovalError("demo approval clock must be timezone-aware")
    remaining = decimal_value(
        (expires_at - checked_at.astimezone(timezone.utc)).total_seconds(),
        "approval remaining duration",
    )
    if requested_duration > remaining or remaining <= shutdown_seconds:
        raise DemoApprovalError("demo approval expires before the requested run can shut down")
    return {
        "expires_at": expires_raw,
        "maximum_duration_seconds": str(maximum_duration),
        "maximum_order_count": maximum_order_count,
        "maximum_quantity_base": str(maximum_quantity),
        "remaining_seconds_at_check": str(remaining),
    }


def require_demo_approval(candidate, manifest_path: Path):
    try:
        runtime_source = collect_runtime_source_provenance()
        return verify_demo_approval(
            candidate=candidate,
            manifest_path=manifest_path,
            canonical_manifest_path=MANIFEST_PATH,
            trust_root_path=DEMO_APPROVAL_TRUST_ROOT,
            expected_strategy_id=STRATEGY_ID,
            runtime_source=runtime_source,
            expected_public_key_sha256=DEMO_APPROVAL_PUBLIC_KEY_SHA256,
        )
    except DemoApprovalVerificationError as exc:
        raise DemoApprovalError(str(exc)) from exc


def risk_from_config(config) -> EventDrivenRisk:
    allowed = set(asdict(EventDrivenRisk()))
    params = dict(config["strategy_params"])
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise RunnerConfigurationError("unknown strategy parameters: " + ", ".join(unknown))
    return EventDrivenRisk(**params)


def funding_settings_from_config(config):
    values = config.get("funding")
    allowed = {"refresh_interval_seconds", "max_age_seconds"}
    if not isinstance(values, Mapping) or set(values) != allowed:
        raise RunnerConfigurationError("funding configuration fields are incomplete or unknown")
    refresh = decimal_value(values["refresh_interval_seconds"], "funding_refresh_interval")
    max_age = decimal_value(values["max_age_seconds"], "funding_max_age")
    if not 0 < refresh < max_age:
        raise RunnerConfigurationError("funding refresh or age is invalid")
    return {"refresh_interval_seconds": refresh, "max_age_seconds": max_age}


def event_path_models_from_candidate(candidate, risk: EventDrivenRisk):
    """Load content-addressed OOS path models bound by the candidate manifest."""

    if candidate.get("research_status") != "PASS":
        return ()
    rows = candidate.get("event_path_models")
    if not isinstance(rows, list) or not rows:
        return ()
    result = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise RunnerConfigurationError("event path model must be a typed mapping")
        try:
            model = EventPathQualification(**row)
        except (TypeError, ValueError) as exc:
            raise RunnerConfigurationError("event path model is invalid") from exc
        reason = model.rejection(minimum_samples=max(1, int(risk.minimum_markout_samples)))
        if reason is not None:
            raise RunnerConfigurationError(f"event path model rejected: {reason}")
        result.append(model)
    if len({model.path_key for model in result}) != len(result):
        raise RunnerConfigurationError("event path model bindings must be unique")
    return tuple(result)


def required_observation_duration(config, risk: EventDrivenRisk) -> Decimal:
    observation = config["observation"]
    allowed = {
        "minimum_statistical_seconds",
        "shutdown_buffer_seconds",
        "require_funding_settlement",
    }
    if set(observation) != allowed:
        raise RunnerConfigurationError("observation configuration fields are incomplete or unknown")
    statistical = decimal_value(observation["minimum_statistical_seconds"])
    shutdown = decimal_value(observation["shutdown_buffer_seconds"])
    if statistical <= 0 or shutdown < 0:
        raise RunnerConfigurationError("observation durations are invalid")
    return statistical + risk.maximum_holding_seconds + shutdown


def validate_duration(
    duration,
    config,
    risk,
    *,
    next_funding_times=(),
    active_observation_seconds=None,
):
    value = decimal_value(duration, "duration")
    required = required_observation_duration(config, risk)
    if value < required:
        raise RunnerConfigurationError(
            f"duration {value}s is below required observation duration {required}s"
        )
    funding_required = bool(config["observation"]["require_funding_settlement"])
    future = [decimal_value(item) for item in next_funding_times if item is not None]
    now = decimal_value(time.time())
    active_horizon = (
        value
        if active_observation_seconds is None
        else decimal_value(active_observation_seconds, "active_observation_seconds")
    )
    if active_horizon <= 0 or active_horizon > value:
        raise RunnerConfigurationError("active observation duration is invalid")
    settlement_margin = decimal_value(
        config["funding"]["refresh_interval_seconds"],
        "funding_settlement_observation_margin",
    )
    funding_cutoff = now + active_horizon - settlement_margin
    if funding_required and (len(future) != len(VENUE_SYMBOLS) or max(future) >= funding_cutoff):
        raise RunnerConfigurationError("duration does not cover a required funding settlement")
    return {
        "requested_seconds": str(value),
        "required_seconds": str(required),
        "maximum_holding_seconds": str(risk.maximum_holding_seconds),
        "funding_horizon_seconds": str(active_horizon),
        "funding_observation_margin_seconds": str(settlement_margin),
        "funding_validation": "IN_SCOPE" if funding_required else "NOT_RUN",
    }


def replay_rules() -> Mapping[str, InstrumentRule]:
    return {
        "okx": InstrumentRule(
            multiplier=Decimal("0.01"),
            quantity_step=Decimal("0.01"),
            minimum_quantity=Decimal("0.01"),
            minimum_notional=Decimal(0),
            price_tick=Decimal("0.1"),
            taker_fee=CONSERVATIVE_TAKER_FEE,
        ),
        "binance": InstrumentRule(
            multiplier=Decimal(1),
            quantity_step=Decimal("0.001"),
            minimum_quantity=Decimal("0.001"),
            minimum_notional=Decimal("50"),
            price_tick=Decimal("0.1"),
            taker_fee=CONSERVATIVE_TAKER_FEE,
        ),
    }


def _book(
    venue,
    bid,
    ask,
    timestamp,
    sequence,
    *,
    previous=None,
    snapshot_or_delta="snapshot",
    continuity_status="snapshot",
    recovery=False,
):
    depth = (
        (decimal_value(bid), Decimal("0.04")),
        (decimal_value(bid) - 1, Decimal("0.04")),
    )
    asks = (
        (decimal_value(ask), Decimal("0.04")),
        (decimal_value(ask) + 1, Decimal("0.04")),
    )
    return EventBook(
        venue=venue,
        bids=depth,
        asks=asks,
        exchange_time=decimal_value(timestamp),
        receive_time=decimal_value(timestamp),
        sequence=sequence,
        previous_sequence=previous,
        snapshot_or_delta=snapshot_or_delta,
        continuity_status=continuity_status,
        recovery_snapshot=recovery,
    )


def replay_events(scenario, risk: EventDrivenRisk):
    if scenario not in SCENARIOS:
        raise RunnerConfigurationError("unsupported replay scenario")
    sequence = {"okx": 0, "binance": 0}
    count = 6
    for index in range(count):
        timestamp = Decimal(index) / Decimal(4)
        wide = scenario in {"profitable", "loss", "partial", "unknown"}
        binance_bid = Decimal("60400") if wide else Decimal("60000")
        binance_ask = binance_bid + Decimal(1)
        for venue, bid, ask in (
            ("okx", Decimal("59999"), Decimal("60000")),
            ("binance", binance_bid, binance_ask),
        ):
            previous = sequence[venue] or None
            sequence[venue] += 1
            if scenario == "gap" and index == 2 and venue == "binance":
                sequence[venue] += 1
                yield _book(
                    venue,
                    bid,
                    ask,
                    timestamp,
                    sequence[venue],
                    previous=previous - 1,
                    snapshot_or_delta="delta",
                    continuity_status="gap",
                )
                continue
            yield _book(
                venue,
                bid,
                ask,
                timestamp,
                sequence[venue],
                previous=previous,
            )


def _metric_report(gross: Decimal, costs: Decimal, trades: int):
    net = gross - costs
    losses = min(net, Decimal(0))
    return {
        "gross_pnl": str(gross),
        "total_cost": str(costs),
        "net_pnl": str(net),
        "maximum_drawdown": str(abs(losses)),
        "return_drawdown_ratio": None if losses == 0 else str(net / abs(losses)),
        "win_rate": str(Decimal(1) if trades and net > 0 else Decimal(0)),
        "expectancy_per_trade": str(net / trades if trades else Decimal(0)),
        "trade_count": trades,
        "cost_to_gross_ratio": None if gross == 0 else str(costs / abs(gross)),
        "latency_ms": {"p50": 0, "p95": 0, "p99": 0, "samples": trades},
        "markouts_quote": {"10": [], "50": [], "100": [], "500": []},
        "unhedged_duration_seconds": {"p50": 0, "p95": 0, "p99": 0, "max": 0},
    }


def _formula_fixture_metrics():
    """Return explicit non-execution metrics for deterministic formula fixtures."""
    return {
        "gross_pnl": None,
        "total_cost": None,
        "net_pnl": None,
        "maximum_drawdown": None,
        "return_drawdown_ratio": None,
        "win_rate": None,
        "expectancy_per_trade": None,
        "trade_count": 0,
        "cost_to_gross_ratio": None,
        "latency_ms": {"p50": None, "p95": None, "p99": None, "samples": 0},
        "markouts_quote": {"10": [], "50": [], "100": [], "500": []},
        "unhedged_duration_seconds": {
            "p50": None,
            "p95": None,
            "p99": None,
            "max": None,
        },
    }


def run_replay(
    scenario="profitable",
    config_path: Path = DEFAULT_CONFIG,
    manifest_path: Path = MANIFEST_PATH,
):
    config = load_config(config_path)
    _, candidate, _ = load_candidate(manifest_path)
    if _file_sha256(config_path, "run config") != candidate["config_sha256"]:
        raise RunnerConfigurationError("run config is not bound to the selected candidate")
    risk = risk_from_config(config)
    admission_models = event_path_models_from_candidate(candidate, risk)
    engine = EventArbitrageEngine(
        replay_rules(),
        risk,
        admission_models=admission_models,
    )
    intent = None
    for book in replay_events(scenario, risk):
        engine.update_book(book)
        if book.venue != "binance":
            continue
        decision = engine.evaluate(book.receive_time)
        if decision is not None and intent is None:
            intent = decision
            if scenario == "unknown":
                engine.mark_unknown()
    final_state = "FORMULA_UNKNOWN_BRANCH" if scenario == "unknown" else "NO_EXECUTION"
    report = {
        "status": "FORMULA_CHECK_PASS",
        "strategy_id": STRATEGY_ID,
        "mode": "replay",
        "scenario": scenario,
        "evidence_level": "R0_FORMULA_FIXTURE",
        "research_status": candidate["research_status"],
        "candidate_sha256": candidate["candidate_sha256"],
        "config_sha256": candidate["config_sha256"],
        "normalized_config_sha256": _canonical_hash(config),
        "strategy_sha256": candidate["strategy_sha256"],
        "event_path_model_count": len(admission_models),
        "configuration": config,
        "orders_submitted": 0,
        "fills": 0,
        "execution_status": "NOT_RUN",
        "partial_fill_ratio": None,
        "unknown_execution": False,
        "synthetic_branch": scenario,
        "final_state": final_state,
        "cost_breakdown": intent.cost.as_dict() if intent else None,
        "fee_source": dict.fromkeys(VENUE_SYMBOLS, "conservative_bound"),
        "fee_rate_per_fill": {venue: str(rule.taker_fee) for venue, rule in engine.rules.items()},
        "reject_reasons": dict(engine.reject_reasons),
        "engine": engine.report(),
        "profitability_claim": "NONE_SYNTHETIC_FIXTURE_ONLY",
    }
    report.update(_formula_fixture_metrics())
    report["markouts_quote"] = engine.report()["markouts_quote"]
    if scenario == "no_edge" and intent is not None:
        report["status"] = "FORMULA_CHECK_FAIL"
    if scenario == "gap" and not engine.reject_reasons["sequence_gap"]:
        report["status"] = "FORMULA_CHECK_FAIL"
    if scenario == "unknown" and final_state != "FORMULA_UNKNOWN_BRANCH":
        report["status"] = "FORMULA_CHECK_FAIL"
    return report


def _load_demo_credentials(path: Path):
    from dotenv import dotenv_values

    names = (
        "OKX_DEMO_API_KEY",
        "OKX_DEMO_SECRET",
        "OKX_DEMO_PASSPHRASE",
        "BINANCE_DEMO_API_KEY",
        "BINANCE_DEMO_SECRET",
    )
    values = dotenv_values(path) if path.is_file() else {}
    result = {name: os.environ.get(name) or values.get(name) or "" for name in names}
    missing = [name for name, value in result.items() if not str(value).strip()]
    if missing:
        raise RunnerConfigurationError("missing demo credential variables: " + ", ".join(missing))
    return result


def _exchange_kwargs(mode, credentials=None, okx_api_region="global"):
    environment = "demo" if mode == "demo" else "production"
    result = {exchange: {"environment": environment} for exchange in EXCHANGES.values()}
    if okx_api_region not in OKX_API_REGIONS:
        raise RunnerConfigurationError("okx_api_region must be global, eea, us or tr")
    if environment == "demo" and okx_api_region == "tr":
        raise RunnerConfigurationError("OKX TR demo endpoints are not verified")
    result[EXCHANGES["okx"]]["api_region"] = okx_api_region
    if credentials:
        result[EXCHANGES["okx"]].update(
            public_key=credentials["OKX_DEMO_API_KEY"],
            private_key=credentials["OKX_DEMO_SECRET"],
            passphrase=credentials["OKX_DEMO_PASSPHRASE"],
        )
        result[EXCHANGES["binance"]].update(
            public_key=credentials["BINANCE_DEMO_API_KEY"],
            private_key=credentials["BINANCE_DEMO_SECRET"],
        )
    return result


def build_store(
    mode,
    env_file=HERE / ".env",
    risk=None,
    funding_settings=None,
    okx_api_region="global",
):
    credentials = _load_demo_credentials(Path(env_file)) if mode == "demo" else None
    risk = risk or EventDrivenRisk()
    funding_settings = funding_settings or {
        "refresh_interval_seconds": Decimal("5"),
        "max_age_seconds": Decimal("30"),
    }
    execution = {
        "market_data_only": mode != "demo",
        "account_currency": "USDT",
        "required_environments": {
            EXCHANGES[v]: "demo" if mode == "demo" else "production" for v in VENUE_SYMBOLS
        },
        "strategy_id": STRATEGY_ID,
        "account_maximum_loss_bps": str(risk.account_maximum_loss_bps),
    }
    return BtApiStore(
        provider="btapi",
        backend="direct",
        config={
            "exchange_kwargs": _exchange_kwargs(mode, credentials, okx_api_region),
            "symbol_routes": {VENUE_SYMBOLS[v]: EXCHANGES[v] for v in VENUE_SYMBOLS},
            **execution,
            "require_account_risk": mode == "demo",
            "book_queue_size": 1,
            "funding_refresh_interval_seconds": str(funding_settings["refresh_interval_seconds"]),
            "funding_max_age_seconds": str(funding_settings["max_age_seconds"]),
        },
    )


def _require_typed_contract(value, expected_type, label):
    if not isinstance(value, expected_type):
        raise RunnerConfigurationError(f"{label} must be a public SDK contract")
    if value.available is not True:
        raise RunnerConfigurationError(f"{label} is unavailable")
    if value.freshness.stale:
        raise RunnerConfigurationError(f"{label} is stale")
    return value


def _rules_from_store(store, mode):
    if mode not in {"shadow", "paper-live", "demo"}:
        raise RunnerConfigurationError("instrument rules require a network mode")
    rules = {}
    fee_sources = {}
    for venue, symbol in VENUE_SYMBOLS.items():
        label = f"{venue} InstrumentSpec"
        instrument = _require_typed_contract(
            store.get_typed_instrument_spec(symbol), InstrumentSpec, label
        )
        if mode == "demo":
            fee_label = f"{venue} account FeeSchedule"
            fees = _require_typed_contract(
                store.get_typed_fee_schedule(symbol), FeeSchedule, fee_label
            )
            if not fees.account_id or fees.taker_rate is None:
                raise RunnerConfigurationError(f"{fee_label} is incomplete")
            fee = fees
            fee_sources[venue] = f"account_fee_schedule:{fees.source}"
        else:
            fee = CONSERVATIVE_TAKER_FEE
            fee_sources[venue] = "conservative_bound"
        try:
            rules[venue] = InstrumentRule.from_sdk_contracts(instrument, fee)
        except ValueError as exc:
            raise RunnerConfigurationError(f"{label} contains an unsafe value") from exc
    return rules, fee_sources


def _funding_from_store(store):
    result = {}
    for venue, symbol in VENUE_SYMBOLS.items():
        label = f"{venue} public FundingSnapshot"
        snapshot = _require_typed_contract(
            store.get_typed_funding_snapshot(symbol), FundingSnapshot, label
        )
        try:
            snapshot = coerce_funding_snapshot(
                snapshot,
                now_epoch=decimal_value(time.time(), "funding_now"),
                expected_exchange_name=EXCHANGES[venue],
                expected_symbol=symbol,
            )
        except ValueError as exc:
            raise RunnerConfigurationError(f"{label} is invalid: {exc}") from exc
        assert snapshot.rate is not None
        assert snapshot.settlement_interval_seconds is not None
        result[venue] = (
            snapshot.rate,
            snapshot.next_funding_epoch,
            Decimal(snapshot.settlement_interval_seconds),
            snapshot.source,
        )
    return result


def _cached_funding_provider(store, max_age_seconds):
    def provider():
        return {
            venue: store.get_cached_funding_snapshot(
                symbol,
                max_age_seconds=float(max_age_seconds),
            )
            for venue, symbol in VENUE_SYMBOLS.items()
        }

    return provider


def _readiness(store, rules, risk):
    venues = {}
    for venue, symbol in VENUE_SYMBOLS.items():
        environment = store.get_environment_info(symbol)
        account = store.get_account_config(symbol)
        quantity_native = rules[venue].base_to_native(risk.quantity_base)
        readiness = store.get_order_readiness(
            symbol,
            quantity_native,
            position_mode="dual_side",
        )
        if environment.get("environment") != "demo" or account.get("position_mode") != "dual_side":
            raise RunnerConfigurationError(
                f"{venue} demo environment or dual-side mode is not ready"
            )
        if account.get("can_trade") is not True:
            raise RunnerConfigurationError(f"{venue} demo account cannot trade")
        if readiness.get("ready") is not True:
            raise RunnerConfigurationError(f"{venue} order readiness is false")
        venues[venue] = {
            "environment": environment,
            "position_mode": account.get("position_mode"),
            "can_trade": account.get("can_trade"),
            "ready": readiness.get("ready"),
        }

    account_risk = store.get_account_risk_snapshot()
    reconcile = store.get_reconcile_snapshot()
    execution_summary = reconcile.get("execution_summary")
    baseline_initialized = bool(
        isinstance(account_risk, Mapping)
        and account_risk.get("baseline_equity") is None
        and account_risk.get("loss_limit_breached") is False
        and "baseline_missing" in (account_risk.get("blocked_reasons") or ())
    )
    if baseline_initialized:
        if not _reconcile_snapshot_ready_for_baseline(reconcile):
            raise RunnerConfigurationError("demo reconciliation evidence is incomplete")
        if reconcile.get("positions") or reconcile.get("open_orders"):
            raise RunnerConfigurationError("demo account must be flat with no open orders")
        store.initialize_account_risk_baseline()
        reconcile = store.get_reconcile_snapshot()
        execution_summary = reconcile.get("execution_summary")
        account_risk = store.get_account_risk_snapshot()
    else:
        if not _reconcile_snapshot_proven(reconcile):
            raise RunnerConfigurationError("demo reconciliation evidence is incomplete")
        if not _execution_summary_proven(execution_summary):
            raise RunnerConfigurationError("demo execution journal is not proven clean")
        if reconcile.get("positions") or reconcile.get("open_orders"):
            raise RunnerConfigurationError("demo account must be flat with no open orders")
    if not _reconcile_snapshot_proven(reconcile):
        raise RunnerConfigurationError("post-baseline reconciliation evidence is incomplete")
    if not _execution_summary_proven(execution_summary):
        raise RunnerConfigurationError("post-baseline execution journal is not proven clean")
    if not _account_risk_proven(account_risk, execution_summary):
        raise RunnerConfigurationError("demo account-risk baseline is not proven")
    if reconcile.get("positions") or reconcile.get("open_orders"):
        raise RunnerConfigurationError("demo account must be flat with no open orders")
    return {
        "status": "PASS",
        "venues": venues,
        "positions": reconcile.get("positions"),
        "open_orders": reconcile.get("open_orders"),
        "reconcile_snapshot": reconcile,
        "execution_summary": execution_summary,
        "account_risk_snapshot": account_risk,
        "exchange_operations": "READ_ONLY",
        "local_persistence": {
            "account_risk_baseline_initialized": baseline_initialized,
            "may_write_local_execution_ledger": baseline_initialized,
        },
    }


def _store_shutdown_proven(health):
    return bool(
        isinstance(health, Mapping)
        and health.get("shutdown_state") == "PASS"
        and int(health.get("queue_depth", 0) or 0) == 0
        and not health.get("inflight")
        and not health.get("worker_alive")
        and not health.get("close_thread_alive")
        and health.get("broker_update_conservation") is True
        and not health.get("last_error_code")
    )


def _preflight_readiness_complete(readiness):
    return bool(
        isinstance(readiness, Mapping)
        and readiness.get("status") == "PASS"
        and set(readiness.get("venues") or ()) == set(VENUE_SYMBOLS)
    )


def _preflight_readiness_summary(readiness):
    """Keep proof booleans while excluding account, balance, and order payloads."""

    if not isinstance(readiness, Mapping):
        return {"status": "INCOMPLETE", "venues": {}}
    raw_venues = readiness.get("venues")
    raw_venues = raw_venues if isinstance(raw_venues, Mapping) else {}
    venues = {}
    for venue in VENUE_SYMBOLS:
        row = raw_venues.get(venue)
        if not isinstance(row, Mapping):
            continue
        environment = row.get("environment")
        environment = environment if isinstance(environment, Mapping) else {}
        api_region = environment.get("api_region")
        venues[venue] = {
            "environment": (
                environment.get("environment")
                if environment.get("environment") in {"demo", "production"}
                else "UNKNOWN"
            ),
            "simulated": environment.get("simulated") is True,
            "verified": environment.get("verified") is True,
            "api_region": api_region if api_region in OKX_API_REGIONS else None,
            "position_mode": (
                row.get("position_mode")
                if row.get("position_mode") in {"dual_side", "net"}
                else "UNKNOWN"
            ),
            "can_trade": row.get("can_trade") is True,
            "ready": row.get("ready") is True,
        }
    reconcile = readiness.get("reconcile_snapshot")
    execution = readiness.get("execution_summary")
    account_risk = readiness.get("account_risk_snapshot")
    local = readiness.get("local_persistence")
    local = local if isinstance(local, Mapping) else {}
    positions = readiness.get("positions")
    open_orders = readiness.get("open_orders")
    return {
        "status": readiness.get("status") if readiness.get("status") == "PASS" else "INCOMPLETE",
        "venues": venues,
        "position_count": len(positions) if isinstance(positions, (list, tuple)) else None,
        "open_order_count": len(open_orders) if isinstance(open_orders, (list, tuple)) else None,
        "reconciliation_proven": _reconcile_snapshot_proven(reconcile),
        "execution_summary_proven": _execution_summary_proven(execution),
        "account_risk_proven": _account_risk_proven(account_risk, execution),
        "exchange_operations": (
            "READ_ONLY" if readiness.get("exchange_operations") == "READ_ONLY" else "UNKNOWN"
        ),
        "local_persistence": {
            "account_risk_baseline_initialized": (
                local.get("account_risk_baseline_initialized") is True
            ),
            "may_write_local_execution_ledger": (
                local.get("may_write_local_execution_ledger") is True
            ),
        },
    }


def _execution_summary_proven(summary):
    collections = (list, tuple, set, frozenset)
    if not isinstance(summary, Mapping):
        return False
    try:
        active_orders = summary["active_orders"]
        generation = int(summary.get("generation", summary.get("session_generation", 0)) or 0)
        fencing_epoch = int(summary.get("fencing_epoch", 0) or 0)
        as_of_monotonic_ns = int(summary.get("as_of_monotonic_ns", 0) or 0)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    return bool(
        not isinstance(active_orders, bool)
        and isinstance(active_orders, int)
        and active_orders == 0
        and generation > 0
        and fencing_epoch > 0
        and as_of_monotonic_ns > 0
        and summary.get("session_enabled") is True
        and _is_sha256(summary.get("identity_binding_sha256"))
        and summary.get("evidence_complete") is True
        and summary.get("trading_blocked") is False
        and isinstance(summary.get("unknown_ids"), collections)
        and not summary["unknown_ids"]
        and isinstance(summary.get("fee_unresolved_orders"), collections)
        and not summary["fee_unresolved_orders"]
        and isinstance(summary.get("funding_unresolved_orders", ()), collections)
        and not summary.get("funding_unresolved_orders", ())
        and not summary.get("evidence_errors")
        and not summary.get("error_code")
    )


def _is_sha256(value):
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _reconcile_snapshot_proven(snapshot):
    if not isinstance(snapshot, Mapping):
        return False
    configured = set(snapshot.get("configured_venues") or ())
    reconciled = set(snapshot.get("reconciled_venues") or ())
    summary = snapshot.get("execution_summary")
    return bool(
        configured == reconciled == set(VENUE_SYMBOLS)
        and isinstance(snapshot.get("positions"), list)
        and isinstance(snapshot.get("open_orders"), list)
        and snapshot.get("evidence_complete") is True
        and not snapshot.get("evidence_errors")
        and _execution_summary_proven(summary)
        and snapshot.get("identity_binding_sha256") == summary.get("identity_binding_sha256")
    )


def _reconcile_snapshot_ready_for_baseline(snapshot):
    """Accept only the expected risk-baseline latch during first startup."""

    if not isinstance(snapshot, Mapping):
        return False
    configured = set(snapshot.get("configured_venues") or ())
    reconciled = set(snapshot.get("reconciled_venues") or ())
    summary = snapshot.get("execution_summary")
    if not isinstance(summary, Mapping):
        return False
    relaxed_summary = dict(summary)
    if relaxed_summary.get("evidence_errors") != ["account_risk_baseline_required"]:
        return False
    relaxed_summary["evidence_errors"] = []
    relaxed_summary["trading_blocked"] = False
    return bool(
        configured == reconciled == set(VENUE_SYMBOLS)
        and isinstance(snapshot.get("positions"), list)
        and isinstance(snapshot.get("open_orders"), list)
        and snapshot.get("evidence_complete") is True
        and not snapshot.get("evidence_errors")
        and _execution_summary_proven(relaxed_summary)
        and snapshot.get("identity_binding_sha256") == summary.get("identity_binding_sha256")
    )


def _account_risk_proven(snapshot, execution_summary):
    if not isinstance(snapshot, Mapping) or not isinstance(execution_summary, Mapping):
        return False
    try:
        generation = snapshot["generation"]
        fencing_epoch = snapshot["fencing_epoch"]
        as_of_monotonic_ns = snapshot["as_of_monotonic_ns"]
        owner_pid = snapshot["owner_pid"]
        clock_domain_id = snapshot["clock_domain_id"]
        baseline = decimal_value(snapshot["baseline_equity"], "baseline_equity")
        current = decimal_value(snapshot["current_equity"], "current_equity")
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return False
    current_pid = os.getpid()
    now_monotonic_ns = time.monotonic_ns()
    return bool(
        not any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (
                generation,
                fencing_epoch,
                as_of_monotonic_ns,
                owner_pid,
            )
        )
        and generation > 0
        and fencing_epoch == execution_summary.get("fencing_epoch")
        and 0 < as_of_monotonic_ns <= now_monotonic_ns
        and owner_pid == current_pid
        and clock_domain_id == f"process:{current_pid}:monotonic"
        and baseline > 0
        and current.is_finite()
        and set(snapshot.get("configured_venues") or ()) == set(VENUE_SYMBOLS)
        and snapshot.get("durable") is True
        and snapshot.get("trading_blocked") is False
        and snapshot.get("evidence_complete") is True
        and not snapshot.get("evidence_errors")
        and not snapshot.get("error_code")
        and _is_sha256(snapshot.get("identity_binding_sha256"))
        and snapshot.get("identity_binding_sha256")
        == execution_summary.get("identity_binding_sha256")
    )


def _paper_flatness(broker):
    positions = {}
    flat = not list(broker.get_orders_open())
    for venue, symbol in VENUE_SYMBOLS.items():
        long_position = getattr(broker, "long_positions", {}).get(symbol)
        short_position = getattr(broker, "short_positions", {}).get(symbol)
        long_size = decimal_value(getattr(long_position, "size", 0) or 0)
        short_size = decimal_value(getattr(short_position, "size", 0) or 0)
        positions[venue] = {"long": str(long_size), "short": str(short_size)}
        flat = flat and long_size == 0 and short_size == 0
    return {"flat": flat, "positions": positions, "open_orders": len(broker.get_orders_open())}


def _realized_metrics(strategy_report):
    rows = strategy_report.get("execution_economics", ())
    if not isinstance(rows, (list, tuple)):
        return _formula_fixture_metrics(), False
    parsed = []
    try:
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError
            parsed.append(
                (
                    decimal_value(row["gross_pnl"], "gross_pnl"),
                    decimal_value(row["realized_net"], "realized_net"),
                )
            )
    except (KeyError, TypeError, ValueError):
        return _formula_fixture_metrics(), False
    gross = sum((row[0] for row in parsed), Decimal(0))
    nets = [row[1] for row in parsed]
    net = sum(nets, Decimal(0))
    costs = gross - net
    running = Decimal(0)
    peak = Decimal(0)
    maximum_drawdown = Decimal(0)
    for value in nets:
        running += value
        peak = max(peak, running)
        maximum_drawdown = max(maximum_drawdown, peak - running)
    trades = len(parsed)
    metrics = {
        "gross_pnl": str(gross),
        "total_cost": str(costs),
        "net_pnl": str(net),
        "maximum_drawdown": str(maximum_drawdown),
        "return_drawdown_ratio": (None if maximum_drawdown == 0 else str(net / maximum_drawdown)),
        "win_rate": str(Decimal(sum(value > 0 for value in nets)) / trades) if trades else "0",
        "expectancy_per_trade": str(net / trades) if trades else "0",
        "trade_count": trades,
        "cost_to_gross_ratio": None if gross == 0 else str(costs / abs(gross)),
        "latency_ms": {"p50": None, "p95": None, "p99": None, "samples": 0},
        "markouts_quote": strategy_report.get(
            "markouts_quote", {"10": [], "50": [], "100": [], "500": []}
        ),
        "unhedged_duration_seconds": {
            "p50": None,
            "p95": None,
            "p99": None,
            "max": strategy_report.get("unhedged_duration_max"),
        },
    }
    fills = int(strategy_report.get("confirmed_fill_events", 0) or 0)
    return metrics, fills == 0 or bool(parsed)


def _funding_economics_proven(strategy_report):
    rows = strategy_report.get("execution_economics")
    if not isinstance(rows, (list, tuple)) or not rows:
        return False
    allowed = {
        "actual_ledger",
        "no_settlement_expected",
        "no_settlement_expected_failed_cycle",
    }
    try:
        return all(
            row.get("funding_evidence_status") in allowed
            and decimal_value(row["signed_funding_cashflow"], "signed_funding_cashflow").is_finite()
            for row in rows
            if isinstance(row, Mapping)
        ) and all(isinstance(row, Mapping) for row in rows)
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return False


def _approval_lease_status_proven(status, approval_lease):
    if not isinstance(status, Mapping) or not isinstance(approval_lease, Mapping):
        return False
    maximum = approval_lease.get("maximum_order_count")
    count = status.get("operation_count")
    return bool(
        status.get("enabled") is True
        and status.get("expires_at_utc") == approval_lease.get("expires_at")
        and type(maximum) is int
        and status.get("maximum_order_count") == maximum
        and type(count) is int
        and 0 <= count <= maximum
    )


def _demo_broker_kwargs(approval_lease, shutdown_seconds):
    if not isinstance(approval_lease, Mapping):
        raise DemoApprovalError("demo broker requires a verified approval lease")
    expires_at = approval_lease.get("expires_at")
    maximum_order_count = approval_lease.get("maximum_order_count")
    if (
        not isinstance(expires_at, str)
        or not expires_at.endswith("Z")
        or type(maximum_order_count) is not int
        or maximum_order_count <= 0
    ):
        raise DemoApprovalError("demo broker approval lease is invalid")
    return {
        "position_mode": "dual_side",
        "position_sync_policy": "startup",
        "shutdown_timeout": float(shutdown_seconds),
        "approval_expires_at_utc": expires_at,
        "approval_max_order_count": maximum_order_count,
    }


def _safe_exception_type(exc):
    name = type(exc).__name__
    if (
        not name
        or len(name) > 80
        or not name[0].isalpha()
        or any(not (char.isascii() and (char.isalnum() or char == "_")) for char in name)
    ):
        return "Exception"
    return name


def _safe_exchange_error_code(exc):
    for attribute in ("error_code", "code", "status_code"):
        try:
            value = getattr(exc, attribute, None)
        except Exception:
            continue
        if type(value) is int and 0 < value <= 999999:
            return str(value)
        if isinstance(value, str) and value.isascii() and value.isdigit() and 1 <= len(value) <= 6:
            return value
    return None


def _safe_preflight_failure_code(exc):
    """Map known local validation failures without exposing provider text."""

    message = str(exc)
    known = {
        "demo reconciliation evidence is incomplete": "RECONCILIATION_INCOMPLETE",
        "demo execution journal is not proven clean": "EXECUTION_JOURNAL_NOT_CLEAN",
        "demo account must be flat with no open orders": "ACCOUNT_NOT_FLAT",
        "post-baseline reconciliation evidence is incomplete": (
            "POST_BASELINE_RECONCILIATION_INCOMPLETE"
        ),
        "post-baseline execution journal is not proven clean": (
            "POST_BASELINE_EXECUTION_JOURNAL_NOT_CLEAN"
        ),
        "demo account-risk baseline is not proven": "ACCOUNT_RISK_BASELINE_NOT_PROVEN",
    }
    for venue in VENUE_SYMBOLS:
        upper = venue.upper()
        known[f"{venue} demo environment or dual-side mode is not ready"] = (
            f"{upper}_ENVIRONMENT_OR_POSITION_MODE_NOT_READY"
        )
        known[f"{venue} demo account cannot trade"] = f"{upper}_CANNOT_TRADE"
        known[f"{venue} order readiness is false"] = f"{upper}_ORDER_NOT_READY"
    return known.get(message, "PREFLIGHT_OPERATION_FAILED")


def _preflight_failure_report(candidate, config, admission, stage, exc):
    """Return an auditable failure without serializing vendor exception contents."""

    return {
        "status": "PREFLIGHT_FAILED_PENDING_SHUTDOWN",
        "mode": "demo",
        "orders_submitted": 0,
        "fills": 0,
        "execution_status": "NOT_RUN",
        "candidate_sha256": candidate["candidate_sha256"],
        "config_sha256": candidate["config_sha256"],
        "normalized_config_sha256": _canonical_hash(config),
        "strategy_sha256": candidate["strategy_sha256"],
        "admission": admission,
        "readiness": {
            "status": "FAIL",
            "venues": {},
            "exchange_operations": "READ_ONLY_ATTEMPTED",
            "local_persistence": {"status": "UNKNOWN_DUE_TO_FAILURE"},
        },
        "preflight_failure": {
            "failure_code": _safe_preflight_failure_code(exc),
            "stage": stage,
            "exception_type": _safe_exception_type(exc),
            "exchange_error_code": _safe_exchange_error_code(exc),
            "detail": "REDACTED",
        },
        "profitability_claim": "NONE_PREFLIGHT_ONLY",
    }


def _preflight_store_health_summary(health):
    """Expose shutdown proof fields while dropping diagnostic/account payloads."""

    if not isinstance(health, Mapping):
        return {
            "shutdown_state": "UNKNOWN",
            "queue_depth": None,
            "inflight_count": None,
            "worker_alive": None,
            "close_thread_alive": None,
            "broker_update_conservation": False,
            "last_error_present": None,
        }
    shutdown_state = health.get("shutdown_state")
    if shutdown_state not in {"PASS", "FAIL", "INCOMPLETE"}:
        shutdown_state = "UNKNOWN"
    queue_depth = health.get("queue_depth")
    if type(queue_depth) is not int or queue_depth < 0:
        queue_depth = None
    inflight = health.get("inflight")
    if type(inflight) is int and inflight >= 0:
        inflight_count = inflight
    elif isinstance(inflight, (Mapping, list, tuple, set, frozenset)):
        inflight_count = len(inflight)
    elif inflight is None:
        inflight_count = 0
    else:
        inflight_count = None
    return {
        "shutdown_state": shutdown_state,
        "queue_depth": queue_depth,
        "inflight_count": inflight_count,
        "worker_alive": health.get("worker_alive") is True,
        "close_thread_alive": health.get("close_thread_alive") is True,
        "broker_update_conservation": health.get("broker_update_conservation") is True,
        "last_error_present": bool(health.get("last_error_code")),
    }


def run_network(
    mode,
    duration,
    config_path=DEFAULT_CONFIG,
    env_file=HERE / ".env",
    preflight=False,
    manifest_path=MANIFEST_PATH,
):
    if mode not in {"shadow", "paper-live", "demo"}:
        raise RunnerConfigurationError("network mode is invalid")
    if mode == "demo" and Path(manifest_path).resolve() != MANIFEST_PATH.resolve():
        raise DemoApprovalError("demo requires the canonical manifest path")
    config = load_config(config_path)
    manifest, candidate, resolved_manifest_path = load_candidate(manifest_path)
    if _file_sha256(config_path, "run config") != candidate["config_sha256"]:
        raise RunnerConfigurationError("run config is not bound to the selected candidate")
    admission = _validate_network_admission(manifest, candidate, mode, preflight, config)
    risk = risk_from_config(config)
    funding_settings = funding_settings_from_config(config)
    mode_policy(mode)
    admission_models = event_path_models_from_candidate(candidate, risk)
    requested_duration = _bounded_requested_duration(duration, config)
    shutdown_seconds = decimal_value(
        config["observation"]["shutdown_buffer_seconds"], "shutdown_buffer_seconds"
    )
    active_seconds = requested_duration - shutdown_seconds
    if active_seconds <= 0:
        raise RunnerConfigurationError("duration does not leave a positive active window")
    approval_lease = None
    if mode == "demo" and not preflight:
        receipt = require_demo_approval(candidate, resolved_manifest_path)
        approval_lease = _approval_lease(
            receipt,
            requested_duration,
            risk,
            shutdown_seconds,
        )
    if mode in {"paper-live", "demo"} and not preflight and not admission_models:
        raise RunnerConfigurationError(
            "execution requires immutable direction/first-venue/fee/depth/latency path models"
        )
    store = build_store(
        mode,
        env_file,
        risk,
        funding_settings,
        okx_api_region=config["okx_api_region"],
    )
    report = None
    store_health = None
    preflight_stage = "store_start"
    try:
        store.start()
        preflight_stage = "instrument_and_fee_metadata"
        rules, fee_sources = _rules_from_store(store, mode)
        preflight_stage = "funding_metadata"
        funding_contracts = _funding_from_store(store)
        rules = {
            venue: replace(rule, funding_interval_seconds=funding_contracts[venue][2])
            for venue, rule in rules.items()
        }
        funding_sources = {venue: values[3] for venue, values in funding_contracts.items()}
        duration_gate = validate_duration(
            requested_duration,
            config,
            risk,
            next_funding_times=[value[1] for value in funding_contracts.values()],
            active_observation_seconds=active_seconds,
        )
        duration_gate.update(
            active_observation_seconds=str(active_seconds),
            shutdown_buffer_seconds=str(shutdown_seconds),
        )
        preflight_stage = "readiness"
        preflight_report = _readiness(store, rules, risk) if mode == "demo" else None
        preflight_stage = "complete"
        if preflight:
            report = {
                "status": "PREFLIGHT_PENDING_SHUTDOWN",
                "mode": mode,
                "orders_submitted": 0,
                "fills": 0,
                "execution_status": "NOT_RUN",
                "candidate_sha256": candidate["candidate_sha256"],
                "config_sha256": candidate["config_sha256"],
                "normalized_config_sha256": _canonical_hash(config),
                "strategy_sha256": candidate["strategy_sha256"],
                "admission": admission,
                "event_path_model_count": len(admission_models),
                "duration_gate": duration_gate,
                "fee_source": fee_sources,
                "funding_source": funding_sources,
                "fee_rate_per_fill": {venue: str(rule.taker_fee) for venue, rule in rules.items()},
                "readiness": _preflight_readiness_summary(preflight_report),
                "profitability_claim": "NONE_PREFLIGHT_ONLY",
            }
        else:
            if mode == "demo":
                broker = store.getbroker(**_demo_broker_kwargs(approval_lease, shutdown_seconds))
            else:
                broker_kwargs = {
                    "cash": 2000,
                    "position_mode": "dual_side",
                    "exchange_model": SimpleExchangeModel(),
                }
                if mode == "paper-live":
                    broker_kwargs.update(
                        account_risk_ledger_path=PAPER_RISK_LEDGER_PATH,
                        account_risk_venues=tuple(VENUE_SYMBOLS),
                    )
                broker = MixBroker(**broker_kwargs)
            for venue, rule in rules.items():
                broker.addcommissioninfo(
                    ComminfoFuturesPercent(
                        commission=float(rule.taker_fee), mult=float(rule.multiplier), margin=1
                    ),
                    name=VENUE_SYMBOLS[venue],
                )
            initial_value = decimal_value(broker.getvalue(), "initial_broker_value")
            cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
            cerebro.setbroker(broker)
            for symbol in VENUE_SYMBOLS.values():
                cerebro.adddata(
                    store.getdata(
                        dataname=symbol,
                        timeframe=bt.TimeFrame.Ticks,
                        orderbook_as_ticks=True,
                        backfill_start=False,
                        qcheck=0.01,
                    ),
                    name=symbol,
                )
            cerebro.addstrategy(
                CrossExchangeArbitrageStrategy,
                rules=rules,
                risk=risk,
                funding_snapshot_provider=_cached_funding_provider(
                    store, funding_settings["max_age_seconds"]
                ),
                funding_exchange_routes=EXCHANGES,
                funding_max_age_seconds=funding_settings["max_age_seconds"],
                admission_models=admission_models,
                execution_enabled=mode != "shadow",
                shadow=mode == "shadow",
            )
            if approval_lease is not None:
                expires_at = datetime.fromisoformat(approval_lease["expires_at"][:-1] + "+00:00")
                lease_active_seconds = (
                    decimal_value(
                        (expires_at - datetime.now(timezone.utc)).total_seconds(),
                        "approval active duration",
                    )
                    - shutdown_seconds
                )
                if lease_active_seconds < active_seconds:
                    raise DemoApprovalError(
                        "demo approval no longer covers the requested active window"
                    )
            timer = threading.Timer(float(active_seconds), cerebro.runstop)
            timer.daemon = True
            timer.start()
            try:
                strategy = cerebro.run()[0]
            finally:
                timer.cancel()
            strategy_report = strategy.report()
            final_value = decimal_value(broker.getvalue(), "final_broker_value")
            broker_value_change = final_value - initial_value
            submitted = int(strategy_report.get("submitted_order_count", 0) or 0)
            fills = int(strategy_report.get("confirmed_fill_events", 0) or 0)
            if mode == "shadow" and (submitted or fills or broker_value_change != 0):
                raise RunnerConfigurationError("shadow mode produced an order, fill, or PnL")

            shutdown_state = None
            reconcile_snapshot = None
            execution_summary = None
            account_risk_snapshot = None
            approval_lease_status = None
            paper_flatness = None
            if mode == "demo":
                shutdown_state = broker.get_shutdown_state()
                reconcile_snapshot = broker.get_last_reconcile_result()
                execution_summary = broker.get_execution_summary()
                approval_lease_status = broker.get_approval_lease_status()
                if strategy_report.get("reconciliation_required"):
                    strategy.confirm_remote_flat(
                        reconcile_snapshot,
                        execution_summary=execution_summary,
                    )
                    strategy_report = strategy.report()
                account_risk_snapshot = broker.get_account_risk_snapshot()
            elif mode == "paper-live":
                paper_flatness = _paper_flatness(broker)
                account_risk_snapshot = broker.get_account_risk_snapshot()

            metrics, economics_complete = _realized_metrics(strategy_report)
            report = {
                "status": "NETWORK_RUN_PENDING_SHUTDOWN_PROOF",
                "mode": mode,
                "evidence_level": (
                    "R2_SHADOW" if mode == "shadow" else "R3_DEMO" if mode == "demo" else "R1_PAPER"
                ),
                "research_status": candidate["research_status"],
                "candidate_sha256": candidate["candidate_sha256"],
                "config_sha256": candidate["config_sha256"],
                "normalized_config_sha256": _canonical_hash(config),
                "strategy_sha256": candidate["strategy_sha256"],
                "admission": admission,
                "approval_lease": approval_lease,
                "configuration": config,
                "duration_gate": duration_gate,
                "orders_submitted": submitted,
                "fills": fills,
                "partial_fill_ratio": None,
                "execution_status": "NOT_RUN" if mode == "shadow" else "EXECUTION_OBSERVED",
                "execution_economics_complete": economics_complete,
                "broker_value_change": str(broker_value_change),
                "cost_breakdown": strategy_report.get("cost_breakdowns", []),
                "fee_source": fee_sources,
                "funding_source": funding_sources,
                "fee_rate_per_fill": {venue: str(rule.taker_fee) for venue, rule in rules.items()},
                "reject_reasons": strategy_report.get("reject_reasons", {}),
                "strategy": strategy_report,
                "broker_shutdown": shutdown_state,
                "reconcile_snapshot": reconcile_snapshot,
                "execution_summary": execution_summary,
                "account_risk_snapshot": account_risk_snapshot,
                "approval_lease_status": approval_lease_status,
                "paper_flatness": paper_flatness,
                "profitability_claim": "NONE_OBSERVATIONAL_ONLY",
            }
            report.update(metrics)
    except Exception as exc:
        if not preflight:
            raise
        report = _preflight_failure_report(candidate, config, admission, preflight_stage, exc)
    finally:
        try:
            store_health = store.stop(timeout=float(shutdown_seconds))
        except Exception as exc:
            store_health = {
                "shutdown_state": "FAIL",
                "error_type": type(exc).__name__,
            }

    store_stop_proven = _store_shutdown_proven(store_health)
    report["store_health"] = (
        _preflight_store_health_summary(store_health) if preflight else store_health
    )
    report["store_stop_proven"] = store_stop_proven
    if preflight:
        readiness_complete = _preflight_readiness_complete(report.get("readiness"))
        report["readiness_complete"] = readiness_complete
        if report.get("preflight_failure"):
            report["status"] = "PREFLIGHT_FAILED"
        else:
            report["status"] = (
                "PREFLIGHT_PASS"
                if store_stop_proven and readiness_complete
                else "PREFLIGHT_INCOMPLETE"
            )
        return report
    if mode == "shadow":
        report["status"] = "SHADOW_PASS" if store_stop_proven else "INCOMPLETE"
    elif mode == "paper-live":
        risk_snapshot = report.get("account_risk_snapshot") or {}
        paper_safe = bool(
            store_stop_proven
            and (report.get("paper_flatness") or {}).get("flat") is True
            and risk_snapshot.get("evidence_complete") is True
            and risk_snapshot.get("durable") is True
            and report.get("execution_economics_complete") is True
            and not report["strategy"].get("reconciliation_required")
            and not report["strategy"].get("unknown_execution")
        )
        report["status"] = "PAPER_OBSERVATION_PASS" if paper_safe else "INCOMPLETE"
    else:
        shutdown_safe = (report.get("broker_shutdown") or {}).get("status") == "PASS"
        summary_safe = _execution_summary_proven(report.get("execution_summary"))
        risk_snapshot = report.get("account_risk_snapshot") or {}
        funding_safe = _funding_economics_proven(report["strategy"])
        lease_safe = _approval_lease_status_proven(
            report.get("approval_lease_status"),
            report.get("approval_lease"),
        )
        strategy_safe = bool(
            not report["strategy"].get("reconciliation_required")
            and not report["strategy"].get("unknown_execution")
            and (report["fills"] == 0 or report["strategy"].get("remote_flat_proven") is True)
        )
        demo_safe = bool(
            store_stop_proven
            and shutdown_safe
            and summary_safe
            and strategy_safe
            and report.get("execution_economics_complete") is True
            and report["fills"] > 0
            and funding_safe
            and risk_snapshot.get("evidence_complete") is True
            and risk_snapshot.get("durable") is True
            and lease_safe
        )
        report["status"] = (
            "DEMO_EXECUTION_PASS"
            if demo_safe
            else ("INCOMPLETE_INSUFFICIENT_SAMPLE" if report["fills"] == 0 else "INCOMPLETE")
        )
    return report


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=MODES, default="replay")
    parser.add_argument("--scenario", choices=SCENARIOS, default="profitable")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--env-file", type=Path, default=HERE / ".env")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    duration = args.duration or float(config.get("run_timeout_seconds", 0))
    if not math.isfinite(duration) or duration <= 0:
        raise RunnerConfigurationError("duration must be finite and positive")
    if args.preflight and args.mode != "demo":
        raise RunnerConfigurationError("--preflight is only valid with --mode demo")
    report = (
        run_replay(args.scenario, args.config, args.manifest)
        if args.mode == "replay"
        else run_network(
            args.mode,
            duration,
            args.config,
            args.env_file,
            args.preflight,
            args.manifest,
        )
    )
    output = args.output or HERE / "reports" / f"{args.mode}-{args.scenario}.json"
    write_private_json_report(output, report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return (
        0
        if report["status"]
        in {
            "FORMULA_CHECK_PASS",
            "SHADOW_PASS",
            "PAPER_OBSERVATION_PASS",
            "DEMO_EXECUTION_PASS",
            "PREFLIGHT_PASS",
        }
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_CONFIG",
    "DEMO_APPROVAL_TRUST_ROOT",
    "DEMO_APPROVAL_PUBLIC_KEY_SHA256",
    "DemoApprovalError",
    "MANIFEST_PATH",
    "MODES",
    "RunnerConfigurationError",
    "event_path_models_from_candidate",
    "load_candidate",
    "load_config",
    "require_demo_approval",
    "required_observation_duration",
    "risk_from_config",
    "run_network",
    "run_replay",
    "validate_duration",
]

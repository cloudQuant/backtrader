#!/usr/bin/env python
"""Run the Iteration 22 SA strategy in replay, shadow, or admitted SimNow mode."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import hmac
import importlib.metadata
import importlib.util
import inspect
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from collections import deque
from copy import deepcopy
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

# Direct execution places only the example directory on ``sys.path``.  Pin the
# source checkout before importing Backtrader so evidence cannot silently bind
# to a stale site-packages installation.
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import backtrader as bt  # noqa: E402
import yaml  # noqa: E402

from backtrader.brokers.btapibroker import BtApiBroker  # noqa: E402
from backtrader.events import TickEvent  # noqa: E402
from backtrader.stores.btapistore import BtApiStore  # noqa: E402

try:
    from .reporting import (
        EvidenceWriter,
        account_fingerprint,
        business_summary_hash,
        redact,
        sha256_file,
        sha256_json,
        source_tree_hash,
    )
    from .risk import DailyRiskStore
    from .strategy import RuntimeControl, SAMidFrequencyStrategy
except ImportError:  # Direct execution from the repository root.
    from reporting import (
        EvidenceWriter,
        account_fingerprint,
        business_summary_hash,
        redact,
        sha256_file,
        sha256_json,
        source_tree_hash,
    )
    from risk import DailyRiskStore
    from strategy import RuntimeControl, SAMidFrequencyStrategy


HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "config.yaml"
MODES = ("replay", "shadow", "simnow")
PURPOSES = ("observation", "engineering_smoke", "natural_signal")
BEIJING = ZoneInfo("Asia/Shanghai")
CTP_EXCHANGE = "CTP___FUTURE"
SDK_PROFILE_NAMES = {
    "simnow_first_group1": "set1_group1",
    "simnow_first_group2": "set1_group2",
    "simnow_second_7x24": "set2_7x24",
}
SDK_REACHABLE_PROFILE_FAMILIES = {
    "set1": frozenset({"set1_group1", "set1_group1_vpn", "set1_group2"}),
    "set2": frozenset({"set2_7x24", "set2_7x24_4000x", "set2_7x24_vpn"}),
}
# The frozen Iteration 22 profile still records the historical set2 front as
# its static configuration.  A live construction probes the named SDK route
# below, where the 4000x pair must carry its own strict CTP profile name.
SDK_REACHABLE_PROFILE_TARGETS = {
    "simnow_second_7x24": "set2_7x24_4000x",
}
FROZEN_PROFILES = {
    "simnow_first_group1": {
        "kind": "simnow",
        "market_alignment": "actual_market_hours",
        "td_front": "tcp://180.168.146.187:10201",
        "md_front": "tcp://180.168.146.187:10211",
    },
    "simnow_first_group2": {
        "kind": "simnow",
        "market_alignment": "actual_market_hours",
        "td_front": "tcp://180.168.146.187:10202",
        "md_front": "tcp://180.168.146.187:10212",
    },
    "simnow_second_7x24": {
        "kind": "simnow",
        "market_alignment": "engineering_only",
        "td_front": "tcp://180.168.146.187:10130",
        "md_front": "tcp://180.168.146.187:10131",
    },
}
SA_PATTERN = re.compile(r"^SA\d{3,4}$", re.IGNORECASE)
FROZEN_WEIGHTS = {
    "h_imbalance": 0.45,
    "h_micro_dev": 0.20,
    "h_ofi": 0.25,
    "h_momentum": 0.10,
    "score_h": 0.40,
    "score_k": 0.60,
    "k_trend": 0.65,
    "k_return3": 0.35,
}
SOURCE_FILES = (
    "run.py",
    "strategy.py",
    "features.py",
    "signal_model.py",
    "risk.py",
    "reporting.py",
)
_RECEIPT_VALIDATION_MARKER = object()
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
ARMING_PROOF_KEYS = frozenset(
    {
        "account_fingerprint",
        "trading_day",
        "instrument",
        "connection_generation",
        "environment_profile",
        "receipt_sha256",
        "native_sha256",
        "ctp_package_sha256",
        "source_hashes_sha256",
        "dependency_hashes_sha256",
        "preflight_sha256",
    }
)
EXECUTION_AUTHORIZATION_FIELDS = frozenset(
    {
        "schema_version",
        "authorization_kind",
        "authorization_key_id",
        "issued_at_utc",
        "expires_at_utc",
        "account_fingerprint",
        "trading_day",
        "instrument",
        "connection_generation",
        "environment_profile",
        "receipt_sha256",
        "stage_a_snapshot_sha256",
        "stage_a_query_request_ids",
        "stage_b_snapshot_sha256",
        "stage_b_query_request_ids",
        "preflight_sha256",
        "runtime_executable_sha256",
        "native_sha256",
        "ctp_package_sha256",
        "source_hashes_sha256",
        "dependency_hashes_sha256",
        "evidence_hashes_sha256",
        "gate_statuses",
        "signature_hmac_sha256",
    }
)
OPERATOR_TAKEOVER_FIELDS = frozenset(
    {
        "schema_version",
        "action",
        "approval_key_id",
        "run_id",
        "account_fingerprint",
        "trading_day",
        "instrument",
        "recovery_evidence_sha256",
        "acknowledged_at_utc",
        "signature_hmac_sha256",
    }
)
RECOVERY_MONITOR_POLL_SECONDS = 0.25
RECOVERY_INCOMPLETE_EXIT_CODE = 3
WRITE_REQUEST_COUNT_KEYS = (
    "settlement_confirm",
    "order_insert",
    "order_action",
)
PROFILE_SELECTION_ENV = "ITER22_SIMNOW_PROFILE"
API_DIAGNOSTIC_PROFILE = "simnow_second_7x24"
API_DIAGNOSTIC_QUERY_NAMES = (
    "account",
    "positions",
    "orders",
    "trades",
    "instruments",
)
CREDENTIAL_KEY_PARTS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "credential",
    "auth_code",
    "authcode",
    "api_key",
    "apikey",
    "api_secret",
    "apisecret",
    "investor_id",
    "investorid",
    "user_id",
    "userid",
    "account_id",
    "accountid",
    "app_id",
    "appid",
    "access_key",
    "accesskey",
    "private_key",
    "privatekey",
)


class RunnerConfigurationError(RuntimeError):
    pass


class PreflightError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True, init=False)
class AdmissionReceipt:
    """Opaque result of complete receipt validation.

    Network order admission accepts only instances minted by
    :func:`validate_receipt`; a caller cannot pass an unchecked ``dict`` into
    :func:`run_network` and turn writes on.
    """

    _payload: dict[str, Any]
    _marker: object

    def __init__(self, payload: Mapping[str, Any], marker: object) -> None:
        if marker is not _RECEIPT_VALIDATION_MARKER:
            raise RunnerConfigurationError("AdmissionReceipt must come from validate_receipt")
        object.__setattr__(self, "_payload", deepcopy(dict(payload)))
        object.__setattr__(self, "_marker", marker)

    def get(self, key: str, default: Any = None) -> Any:
        return deepcopy(self._payload.get(key, default))

    def __getitem__(self, key: str) -> Any:
        return deepcopy(self._payload[key])

    def evidence_view(self) -> dict[str, Any]:
        return deepcopy(self._payload)

    @property
    def validated(self) -> bool:
        return self._marker is _RECEIPT_VALIDATION_MARKER


def _mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    for method_name in ("to_dict", "model_dump", "as_dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            result = method()
            if isinstance(result, Mapping):
                return dict(result)
    try:
        return dict(vars(value))
    except TypeError:
        return {}


def _attach_trade_logger(
    cerebro: bt.Cerebro,
    output_directory: Path,
    *,
    startup_snapshot_file: str | None = None,
    startup_account_observation: Mapping[str, Any] | None = None,
) -> None:
    """Attach the framework-level report owner for one controlled SA run.

    EvidenceWriter remains the authoritative durable audit lane for high-rate
    quote, bar, signal, order, trade, and risk evidence.  TradeLogger keeps
    the generic in-memory runtime report and a compact operational log set.
    """
    cerebro.addobserver(
        bt.observers.TradeLogger,
        obsname="trade_logger",
        log_dir=str(output_directory / "trade-logger"),
        log_format="json",
        log_to_console=False,
        log_ticks=False,
        log_bars=False,
        log_positions=False,
        log_indicators=False,
        log_value=False,
        log_position_snapshot=False,
        # This compact startup artifact is intentionally separate from the
        # legacy end-of-run, price-bearing ``current_position.yaml``.  The
        # observer writes it solely from the broker's already-hydrated cache.
        startup_snapshot_file=startup_snapshot_file,
        # A caller-supplied Stage-B projection remains separate from the
        # generic broker cache. This lets TradeLogger retain account-wide
        # startup evidence even when an SDK observation session intentionally
        # exposes an empty account cache.
        startup_account_observation=deepcopy(startup_account_observation),
    )


def _final_sa_report(strategy: Any) -> dict[str, Any]:
    """Read the frozen SA extension from the named generic TradeLogger."""
    observer = getattr(getattr(strategy, "stats", None), "trade_logger", None)
    final_report = getattr(observer, "final_report", None)
    if not callable(final_report):
        raise RuntimeError("named TradeLogger final report is unavailable")
    generic = final_report()
    if not isinstance(generic, Mapping):
        raise RuntimeError("TradeLogger did not freeze a final report")
    if generic.get("finalized") is not True:
        raise RuntimeError("TradeLogger final report is not finalized")
    extensions = _mapping(generic.get("extensions"))
    context = _mapping(extensions.get("sa_midfreq"))
    if not context:
        raise RuntimeError("TradeLogger final report is missing the sa_midfreq extension")
    if bool(getattr(strategy, "_trade_logger_context_failed_since_success", False)):
        raise RuntimeError("TradeLogger sa_midfreq extension is stale after a publish failure")
    return {**context, "trade_logger": generic}


def _load_env_file(path: Path) -> None:
    """Load this example's local .env without evaluating shell syntax."""

    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_config(
    path: Path | str = DEFAULT_CONFIG, *, env_values: Mapping[str, str] | None = None
) -> tuple[dict[str, Any], Path]:
    config_path = Path(path)
    if not config_path.is_absolute():
        candidate = HERE / config_path
        config_path = candidate if candidate.exists() else config_path.resolve()
    if not config_path.is_file():
        raise RunnerConfigurationError(f"config does not exist: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RunnerConfigurationError("config root must be a mapping")
    if env_values is None:
        validate_config(raw)
        return raw, config_path.resolve()
    return effective_profile_config(raw, env_values), config_path.resolve()


def effective_profile_config(
    config: Mapping[str, Any], env_values: Mapping[str, str]
) -> dict[str, Any]:
    """Copy ``config`` and bind it to one frozen SimNow profile.

    ``ITER22_SIMNOW_PROFILE`` is intentionally a profile *name*, never a
    free-form front address.  The copied configuration is the only object
    handed to validation, receipt binding, hashing, and runtime construction.
    ``_load_env_file`` preserves pre-existing process values, so process
    environment values naturally override this example's local ``.env``.
    """

    effective = deepcopy(dict(config))
    configured = str(effective.get("environment") or "").strip()
    override = env_values.get(PROFILE_SELECTION_ENV)
    selected = configured if override is None or override == "" else str(override)
    if selected not in FROZEN_PROFILES:
        raise RunnerConfigurationError(
            f"{PROFILE_SELECTION_ENV} must be one exact frozen SimNow profile name"
        )
    effective["environment"] = selected
    validate_config(effective)
    return effective


def validate_config(config: Mapping[str, Any]) -> None:
    mode = str(config.get("mode", "shadow"))
    if mode not in MODES:
        raise RunnerConfigurationError(f"unsupported mode {mode!r}")
    environment = str(config.get("environment") or "")
    lowered = environment.lower()
    if not environment or any(token in lowered for token in ("prod", "production", "real_money")):
        raise RunnerConfigurationError("only an explicit SimNow environment is permitted")
    profiles = config.get("profiles")
    if not isinstance(profiles, Mapping) or environment not in profiles:
        raise RunnerConfigurationError("the selected SimNow profile is missing")
    if set(profiles) != set(FROZEN_PROFILES) or any(
        _mapping(profiles.get(name)) != expected for name, expected in FROZEN_PROFILES.items()
    ):
        raise RunnerConfigurationError("SimNow profiles must match the frozen MD/TD pairs")
    profile = _mapping(profiles[environment])
    if profile.get("kind") != "simnow":
        raise RunnerConfigurationError("profile kind must be simnow")
    if not profile.get("td_front") or not profile.get("md_front"):
        raise RunnerConfigurationError("SimNow MD and TD fronts must be configured as a pair")
    if config.get("timezone") != "Asia/Shanghai":
        raise RunnerConfigurationError("timezone must be Asia/Shanghai")
    signal_config = _mapping(config.get("signal"))
    weights = _mapping(signal_config.get("weights"))
    if weights != FROZEN_WEIGHTS:
        raise RunnerConfigurationError("v0 signal weights do not match the frozen candidate")
    execution = _mapping(config.get("execution"))
    if execution.get("order_type") != "limit" or execution.get("time_in_force") != "GFD":
        raise RunnerConfigurationError("v0 execution is limit GFD only")
    if (
        float(execution.get("entry_timeout_seconds", 0)) != 3
        or float(execution.get("cancel_timeout_seconds", 0)) != 5
    ):
        raise RunnerConfigurationError("v0 GFD entry/cancel deadlines must remain 3/5 seconds")
    protection = float(execution.get("entry_protection_ticks", math.nan))
    if not math.isfinite(protection) or not 0 <= protection <= 1:
        raise RunnerConfigurationError("entry_protection_ticks must be between zero and one")
    if int(execution.get("max_exit_requotes", -1)) != 2:
        raise RunnerConfigurationError("v0 permits exactly two bounded residual exit requotes")
    risk = _mapping(config.get("risk"))
    if risk.get("lots") != 1 or risk.get("max_position_lots") != 1:
        raise RunnerConfigurationError("v0 requires one lot and maximum exposure of one lot")
    if risk.get("cash_check_enabled") is not True:
        raise RunnerConfigurationError("cash_check_enabled cannot be disabled")
    if int(risk.get("maximum_consecutive_losses", 0)) != 3:
        raise RunnerConfigurationError("v0 consecutive-loss halt must remain three")
    if (
        float(risk.get("min_hold_seconds", 0)) != 60
        or float(risk.get("max_hold_seconds", 0)) != 900
    ):
        raise RunnerConfigurationError("v0 hold bounds must remain 60 and 900 seconds")
    warmup = _mapping(config.get("warmup"))
    if int(warmup.get("bars", 0)) != 60 or float(warmup.get("quote_seconds", 0)) != 60:
        raise RunnerConfigurationError("v0 warmup must remain 60 bars and 60 quote seconds")
    if (
        float(signal_config.get("confirm_seconds", 0)) != 2
        or int(signal_config.get("confirm_quotes", 0)) != 3
    ):
        raise RunnerConfigurationError("v0 confirmation must remain two seconds and three quotes")
    if (
        float(signal_config.get("entry_score", math.nan)) != 0.35
        or float(signal_config.get("exit_score", math.nan)) != 0.10
    ):
        raise RunnerConfigurationError("v0 entry/exit scores do not match the frozen candidate")
    feed = _mapping(config.get("feed"))
    if (
        feed.get("timeframe") != "minutes"
        or int(feed.get("compression", 0)) != 1
        or feed.get("dispatch_ticks") is not True
        or feed.get("dispatch_bars") is not True
        or feed.get("backfill_start") is not False
        or float(feed.get("qcheck", math.nan)) != 0.20
    ):
        raise RunnerConfigurationError("v0 requires one-minute bars plus tick/bar dispatch")
    quality = _mapping(config.get("quality"))
    exact_quality = {
        "max_quote_age_seconds": 2.0,
        "exit_quote_age_seconds": 5.0,
        "max_bar_age_seconds": 90.0,
        "maximum_spread_ticks": 2.0,
        "minimum_depth_lots": 5.0,
        "watermark_milliseconds": 500.0,
    }
    if any(
        not math.isclose(float(quality.get(name, math.nan)), expected)
        for name, expected in exact_quality.items()
    ):
        raise RunnerConfigurationError("quality policy differs from the frozen v0 contract")
    research = _mapping(config.get("research"))
    if set(research) != {"status"} or research.get("status") not in {
        "RESEARCH_NOT_ESTABLISHED",
        "RESEARCH_ADMITTED",
        "RESEARCH_REJECTED",
    }:
        raise RunnerConfigurationError("research.status is missing or unsupported")
    metadata = _mapping(config.get("metadata_expectation"))
    if (
        float(metadata.get("price_tick", 0)) != 1
        or float(metadata.get("volume_multiple", 0)) != 20
        or int(metadata.get("minimum_order_lots", 0)) != 1
    ):
        raise RunnerConfigurationError("SA v0 expects PriceTick=1 and VolumeMultiple=20")
    exact_risk = {
        "daily_loss_cny": 500.0,
        "daily_loss_equity_fraction": 0.005,
        "cooldown_seconds": 60.0,
        "maximum_entry_attempts": 30.0,
        "maximum_write_requests": 100.0,
        "emergency_write_reserve": 20.0,
        "drain_timeout_seconds": 120.0,
    }
    if any(
        not math.isclose(float(risk.get(name, math.nan)), expected)
        for name, expected in exact_risk.items()
    ):
        raise RunnerConfigurationError("risk policy differs from the frozen v0 contract")
    fee_policy = _mapping(config.get("fee_policy"))
    replay_fee = _mapping(fee_policy.get("replay_fixture"))
    exact_replay_fee = {
        "open_money_rate": 0.0,
        "open_volume_rate": 2.0,
        "close_money_rate": 0.0,
        "close_volume_rate": 4.0,
        "close_today_money_rate": 0.0,
        "close_today_volume_rate": 4.0,
        "entry_slip_ticks": 1.0,
        "exit_slip_ticks": 1.0,
        "edge_buffer_ticks": 1.0,
    }
    if (
        fee_policy.get("require_account_verified_for_simnow") is not True
        or fee_policy.get("conservative_manual") is not None
        or replay_fee.get("source") != "synthetic_formula_fixture"
        or replay_fee.get("verified") is not False
        or any(
            not math.isclose(float(replay_fee.get(name, math.nan)), expected)
            for name, expected in exact_replay_fee.items()
        )
    ):
        raise RunnerConfigurationError("fee policy differs from the frozen v0 contract")
    evidence = _mapping(config.get("evidence"))
    if any(
        int(evidence.get(name, 0)) <= 0
        for name in (
            "minimum_free_bytes",
            "quote_queue_limit",
            "audit_queue_limit",
            "rotate_bytes",
            "retain_trading_days",
        )
    ):
        raise RunnerConfigurationError("evidence capacity limits must be positive")
    if any(
        any(token in str(key).lower() for token in CREDENTIAL_KEY_PARTS)
        for key in _walk_keys(config)
    ):
        raise RunnerConfigurationError("credentials must not appear in config.yaml")


def _walk_keys(value: Any):
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield key
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def _strict_request_counts(value: Any) -> tuple[dict[str, int], bool]:
    """Return request counters only when the complete write-key contract is present."""

    if not isinstance(value, Mapping):
        return {}, False
    raw = dict(value)
    if any(name not in raw for name in WRITE_REQUEST_COUNT_KEYS):
        return {}, False
    counts: dict[str, int] = {}
    for key, item in raw.items():
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            return {}, False
        counts[str(key)] = item
    return counts, True


def config_hash(config: Mapping[str, Any]) -> str:
    return sha256_json(config)


def code_hash() -> str:
    return source_tree_hash(HERE / name for name in SOURCE_FILES)


def module_identity(module_name: str, distribution_name: str | None = None) -> dict[str, Any]:
    """Identify one installed/importable component without importing native code."""

    spec = importlib.util.find_spec(module_name)
    origin = str(Path(spec.origin).resolve()) if spec and spec.origin else ""
    try:
        version = importlib.metadata.version(distribution_name or module_name)
    except importlib.metadata.PackageNotFoundError:
        version = None
    return {
        "module": module_name,
        "version": version,
        "path": origin or None,
        "sha256": sha256_file(origin) if origin and Path(origin).is_file() else None,
        "found": bool(spec),
    }


def runtime_component_identities() -> dict[str, Any]:
    """Bind reports to the imported framework and public SDK facade."""

    return {
        "backtrader": module_identity("backtrader", "backtrader"),
        "backtrader_trade_logger": module_identity(
            "backtrader.observers.trade_logger", "backtrader"
        ),
        "backtrader_store": module_identity("backtrader.stores.btapistore", "backtrader"),
        "backtrader_feed": module_identity("backtrader.feeds.btapifeed", "backtrader"),
        "backtrader_broker": module_identity("backtrader.brokers.btapibroker", "backtrader"),
        "bt_api_py": module_identity("bt_api_py", "bt-api-py"),
        "bt_api_py_facade": module_identity("bt_api_py.bt_api", "bt-api-py"),
        "bt_api_py_execution_session": module_identity("bt_api_py._execution_session", "bt-api-py"),
    }


def _sdk_profile_family(profile: str) -> str:
    normalized = str(profile or "").strip().lower()
    for family, profiles in SDK_REACHABLE_PROFILE_FAMILIES.items():
        if normalized in profiles:
            return family
    raise RunnerConfigurationError("configured SimNow profile has no approved SDK family")


def _select_reachable_ctp_fronts(
    configured_profile: str,
    *,
    reachable_selector: Callable[..., Any] | None = None,
) -> tuple[str, str, str]:
    """Choose one TCP-reachable pair from the SDK's frozen profile family.

    The CTP plugin owns the endpoint registry and probes TD/MD without
    credentials. This runner never derives a route from VPN geography and
    accepts only the named profiles recorded in ``SDK_REACHABLE_PROFILE_FAMILIES``.
    """

    family = _sdk_profile_family(configured_profile)
    selector = reachable_selector
    if selector is None:
        try:
            from bt_api_ctp.ctp_env_selector import select_reachable_ctp_environment
        except ImportError as exc:
            raise RunnerConfigurationError(
                "bt_api_ctp with reachable SimNow profile selection is required"
            ) from exc
        selector = select_reachable_ctp_environment
    require_exact_profile = configured_profile in SDK_REACHABLE_PROFILE_TARGETS.values()
    selector_kwargs: dict[str, str] = {"env": family}
    if require_exact_profile:
        selector_kwargs.update(
            profile=configured_profile,
            require_profile=configured_profile,
        )
    else:
        selector_kwargs["require_profile"] = family
    selection = selector(**selector_kwargs)
    profile = str(getattr(selection, "profile", "") or "").strip().lower()
    td_front = str(getattr(selection, "td_front", "") or "").strip()
    md_front = str(getattr(selection, "md_front", "") or "").strip()
    if require_exact_profile and profile != configured_profile:
        raise RunnerConfigurationError(
            "reachable CTP selection did not return the required exact profile"
        )
    if profile not in SDK_REACHABLE_PROFILE_FAMILIES[family] or not td_front or not md_front:
        raise RunnerConfigurationError(
            "reachable CTP selection did not return one complete approved profile"
        )
    return profile, td_front, md_front


def resolve_fronts(
    config: Mapping[str, Any],
    env: Mapping[str, str],
    *,
    select_reachable: bool = False,
    reachable_selector: Callable[..., Any] | None = None,
) -> dict[str, str]:
    profile_name = str(config["environment"])
    profile = _mapping(config["profiles"][profile_name])
    td_override = str(
        env.get("CTP_TD_FRONT") or env.get("SIMNOW_TD_FRONT") or env.get("simnow_td_front") or ""
    ).strip()
    md_override = str(
        env.get("CTP_MD_FRONT") or env.get("SIMNOW_MD_FRONT") or env.get("simnow_md_front") or ""
    ).strip()
    if bool(td_override) != bool(md_override):
        raise RunnerConfigurationError("CTP_TD_FRONT and CTP_MD_FRONT must be overridden together")
    selected_profile = profile_name
    if td_override:
        matches = [
            name
            for name, value in _mapping(config["profiles"]).items()
            if _mapping(value).get("kind") == "simnow"
            and str(_mapping(value).get("td_front")) == td_override
            and str(_mapping(value).get("md_front")) == md_override
        ]
        if len(matches) != 1:
            raise RunnerConfigurationError(
                "explicit CTP fronts must match one complete approved SimNow profile"
            )
        selected_profile = matches[0]
        if selected_profile != profile_name:
            raise RunnerConfigurationError(
                "explicit CTP fronts must match the selected SimNow profile"
            )
        profile = _mapping(config["profiles"][selected_profile])
    resolved = {
        "profile": selected_profile,
        "profile_basis": profile_name,
        "sdk_profile": SDK_PROFILE_NAMES.get(selected_profile, ""),
        "market_alignment": str(profile.get("market_alignment")),
        "td_front": td_override or str(profile["td_front"]),
        "md_front": md_override or str(profile["md_front"]),
    }
    if not select_reachable or td_override:
        return resolved
    reachable_profile = SDK_REACHABLE_PROFILE_TARGETS.get(
        selected_profile,
        resolved["sdk_profile"],
    )
    sdk_profile, td_front, md_front = _select_reachable_ctp_fronts(
        reachable_profile,
        reachable_selector=reachable_selector,
    )
    return {
        **resolved,
        "sdk_profile": sdk_profile,
        "td_front": td_front,
        "md_front": md_front,
    }


def credentials(env: Mapping[str, str]) -> dict[str, str]:
    values = {
        "investor_id": str(
            env.get("CTP_USER_ID") or env.get("SIMNOW_USER_ID") or env.get("simnow_user_id") or ""
        ).strip(),
        "password": str(
            env.get("CTP_PASSWORD")
            or env.get("SIMNOW_PASSWORD")
            or env.get("simnow_password")
            or ""
        ),
        "broker_id": str(
            env.get("CTP_BROKER_ID")
            or env.get("SIMNOW_BROKER_ID")
            or env.get("simnow_broker_id")
            or "9999"
        ).strip(),
        "app_id": str(
            env.get("CTP_APP_ID") or env.get("SIMNOW_APP_ID") or env.get("simnow_app_id") or ""
        ).strip(),
        "auth_code": str(
            env.get("CTP_AUTH_CODE")
            or env.get("SIMNOW_AUTH_CODE")
            or env.get("simnow_auth_code")
            or ""
        ).strip(),
    }
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise RunnerConfigurationError(
            "missing required SimNow environment values: " + ",".join(missing)
        )
    return values


def source_file_hashes() -> dict[str, str]:
    return {name: sha256_file(HERE / name) for name in SOURCE_FILES}


def dependency_identity_hashes() -> dict[str, str]:
    return {
        name: sha256_json(identity) for name, identity in runtime_component_identities().items()
    }


def _require_hash(value: Any, name: str) -> str:
    result = str(value or "").lower()
    if _HEX64.fullmatch(result) is None:
        raise RunnerConfigurationError(f"receipt {name} must be a SHA-256")
    return result


def _validated_receipt(receipt: Any) -> bool:
    return isinstance(receipt, AdmissionReceipt) and receipt.validated


def _revalidate_admission_receipt(
    receipt: AdmissionReceipt,
    *,
    config: Mapping[str, Any],
    mode: str,
    purpose: str,
) -> AdmissionReceipt:
    """Recheck the signed receipt at the irreversible network boundary.

    ``AdmissionReceipt`` is intentionally useful as a strong API type, but a
    Python object alone is not an authority boundary.  Re-reading the original
    bytes and verifying their operator-owned HMAC here prevents callers from
    constructing or mutating an object and then invoking ``run_network``
    directly.
    """

    if not _validated_receipt(receipt):
        raise RunnerConfigurationError("SimNow order runs require a validated receipt")
    receipt_path = str(receipt.get("_path") or "")
    receipt_sha256 = str(receipt.get("_receipt_sha256") or "").lower()
    if not receipt_path or _HEX64.fullmatch(receipt_sha256) is None:
        raise RunnerConfigurationError("validated receipt provenance is incomplete")
    verified = validate_receipt(
        receipt_path,
        config=config,
        mode=mode,
        purpose=purpose,
    )
    if not hmac.compare_digest(receipt_sha256, str(verified.get("_receipt_sha256") or "")):
        raise RunnerConfigurationError("validated receipt changed before network admission")
    if receipt.evidence_view() != verified.evidence_view():
        raise RunnerConfigurationError("validated receipt object differs from signed receipt")
    return verified


def _assert_receipt_current(receipt: AdmissionReceipt) -> None:
    """Recheck the signed approval clock immediately before atomic arming."""

    try:
        issued = datetime.fromisoformat(
            str(receipt.get("issued_at_utc") or "").replace("Z", "+00:00")
        )
        expires = datetime.fromisoformat(
            str(receipt.get("expires_at_utc") or "").replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise PreflightError("admission receipt validity interval became invalid") from exc
    now = datetime.now(timezone.utc)
    if issued.tzinfo is None or expires.tzinfo is None or issued > now or expires <= now:
        raise PreflightError("admission receipt expired before SDK execution arming")


def _build_execution_authorization_grant(
    *,
    receipt: AdmissionReceipt,
    stage_a_snapshot: Mapping[str, Any],
    stage_a: Mapping[str, Any],
    stage_b_snapshot: Mapping[str, Any],
    preflight: Mapping[str, Any],
    environment_profile: str,
) -> dict[str, Any]:
    """Mint the one-use Store authorization only from validated live evidence."""

    if not _validated_receipt(receipt):
        raise PreflightError("execution authorization requires a validated receipt")
    _assert_receipt_current(receipt)
    gate_statuses = _mapping(receipt.get("gates"))
    if set(gate_statuses) != {"G1", "G2", "G3"} or any(
        gate_statuses.get(name) != "PASS" for name in ("G1", "G2", "G3")
    ):
        raise PreflightError("execution authorization requires PASS for G1, G2, and G3")

    def request_ids(snapshot: Mapping[str, Any], expected: tuple[str, ...]) -> dict[str, int]:
        rows = snapshot.get("query_results")
        if not isinstance(rows, Mapping) or any(name not in rows for name in expected):
            raise PreflightError("execution authorization query evidence shape is incomplete")
        result: dict[str, int] = {}
        for name in expected:
            value = rows[name]
            completed = _complete_query(value, name)
            if completed.get("accepted_complete") is not True:
                raise PreflightError("execution authorization query evidence is incomplete")
            raw = _mapping(value).get("request_id")
            if type(raw) is not int or raw <= 0:
                raise PreflightError("execution authorization query request ID is invalid")
            result[name] = raw
        if len(set(result.values())) != len(result):
            raise PreflightError("execution authorization query request IDs are not distinct")
        return result

    stage_a_ids = request_ids(
        stage_a_snapshot,
        ("account", "positions", "orders", "trades", "instruments"),
    )
    stage_b_ids = request_ids(
        stage_b_snapshot,
        (
            "account",
            "positions",
            "orders",
            "trades",
            "instruments",
            "margin_rate",
            "commission_rate",
        ),
    )
    if set(stage_a_ids.values()) & set(stage_b_ids.values()):
        raise PreflightError("Stage A and Stage B authorization request IDs overlap")
    stage_a_hash = _require_hash(stage_a_snapshot.get("snapshot_sha256"), "stage_a_snapshot_sha256")
    stage_b_hash = _require_hash(stage_b_snapshot.get("snapshot_sha256"), "stage_b_snapshot_sha256")
    preflight_hash = _require_hash(preflight.get("preflight_sha256"), "preflight_sha256")
    identity = _mapping(preflight.get("query_identity"))
    instrument = str(_mapping(preflight.get("selection")).get("instrument") or "").upper()
    account = str(receipt.get("account_fingerprint") or "")
    trading_day = str(identity.get("trading_day") or "")
    generation = identity.get("connection_generation")
    if (
        not SA_PATTERN.fullmatch(instrument)
        or str(receipt.get("instrument") or "").upper() != instrument
        or receipt.get("trading_day") != trading_day
        or receipt.get("account_fingerprint") != account
        or type(generation) is not int
        or generation <= 0
    ):
        raise PreflightError("execution authorization identity is incomplete or mismatched")
    key_id = str(os.environ.get("ITER22_APPROVAL_KEY_ID") or "").strip()
    secret = str(os.environ.get("ITER22_APPROVAL_HMAC_KEY") or "")
    if not key_id or len(secret.encode("utf-8")) < 32:
        raise PreflightError("execution authorization trust root is unavailable")
    unsigned = {
        "schema_version": "backtrader.ctp.execution-authorization.v1",
        "authorization_kind": "hmac_sha256",
        "authorization_key_id": key_id,
        "issued_at_utc": receipt.get("issued_at_utc"),
        "expires_at_utc": receipt.get("expires_at_utc"),
        "account_fingerprint": account,
        "trading_day": trading_day,
        "instrument": f"CZCE.{instrument}",
        "connection_generation": generation,
        "environment_profile": environment_profile,
        "receipt_sha256": _require_hash(receipt.get("_receipt_sha256"), "receipt_sha256"),
        "stage_a_snapshot_sha256": stage_a_hash,
        "stage_a_query_request_ids": stage_a_ids,
        "stage_b_snapshot_sha256": stage_b_hash,
        "stage_b_query_request_ids": stage_b_ids,
        "preflight_sha256": preflight_hash,
        "runtime_executable_sha256": sha256_file(Path(sys.executable).resolve()),
        "native_sha256": _require_hash(receipt.get("native_sha256"), "native_sha256"),
        "ctp_package_sha256": _require_hash(
            receipt.get("ctp_package_sha256"), "ctp_package_sha256"
        ),
        "source_hashes_sha256": sha256_json(_mapping(receipt.get("source_hashes"))),
        "dependency_hashes_sha256": sha256_json(_mapping(receipt.get("dependency_hashes"))),
        "evidence_hashes_sha256": sha256_json(_mapping(receipt.get("evidence_hashes"))),
        "gate_statuses": gate_statuses,
    }
    canonical = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    grant = {
        **unsigned,
        "signature_hmac_sha256": hmac.new(
            secret.encode("utf-8"), canonical, hashlib.sha256
        ).hexdigest(),
    }
    if set(grant) != EXECUTION_AUTHORIZATION_FIELDS:
        raise PreflightError("internal execution authorization shape is invalid")
    return grant


def validate_receipt(
    path: Path | str,
    *,
    config: Mapping[str, Any],
    mode: str,
    purpose: str,
) -> AdmissionReceipt:
    receipt_path = Path(path)
    if not receipt_path.is_file():
        raise RunnerConfigurationError("SimNow admission receipt is missing")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_version") != "iter22.simnow-admission.v2"
    ):
        raise RunnerConfigurationError("unsupported SimNow admission receipt")
    configured_key_id = str(os.environ.get("ITER22_APPROVAL_KEY_ID") or "").strip()
    approval_key = str(os.environ.get("ITER22_APPROVAL_HMAC_KEY") or "")
    if not configured_key_id or len(approval_key.encode("utf-8")) < 32:
        raise RunnerConfigurationError("local Iteration 22 approval trust root is unavailable")
    if not hmac.compare_digest(str(receipt.get("approval_key_id") or ""), configured_key_id):
        raise RunnerConfigurationError("receipt approval key identity mismatch")
    supplied_signature = str(receipt.get("signature_hmac_sha256") or "").lower()
    unsigned = {key: value for key, value in receipt.items() if key != "signature_hmac_sha256"}
    canonical = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    expected_signature = hmac.new(
        approval_key.encode("utf-8"), canonical, hashlib.sha256
    ).hexdigest()
    if _HEX64.fullmatch(supplied_signature) is None or not hmac.compare_digest(
        supplied_signature, expected_signature
    ):
        raise RunnerConfigurationError("receipt approval signature is missing or invalid")
    expected = {
        "candidate_id": config.get("candidate_id"),
        "config_hash": config_hash(config),
        "code_hash": code_hash(),
        "mode": mode,
        "purpose": purpose,
        "environment": config.get("environment"),
    }
    mismatches = [key for key, value in expected.items() if receipt.get(key) != value]
    if mismatches:
        raise RunnerConfigurationError(
            "admission receipt identity mismatch: " + ",".join(mismatches)
        )
    try:
        issued = datetime.fromisoformat(
            str(receipt.get("issued_at_utc", "")).replace("Z", "+00:00")
        )
        expires = datetime.fromisoformat(
            str(receipt.get("expires_at_utc", "")).replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise RunnerConfigurationError("admission receipt validity interval is invalid") from exc
    now = datetime.now(timezone.utc)
    if (
        issued.tzinfo is None
        or expires.tzinfo is None
        or issued > now
        or expires <= now
        or issued >= expires
    ):
        raise RunnerConfigurationError("admission receipt is expired")
    gates = _mapping(receipt.get("gates"))
    if any(gates.get(name) != "PASS" for name in ("G1", "G2", "G3")):
        raise RunnerConfigurationError("admission receipt requires PASS for G1, G2, and G3")
    if int(receipt.get("maximum_lots", 0)) != 1:
        raise RunnerConfigurationError("admission receipt maximum_lots must equal one")
    maximum_writes = int(receipt.get("maximum_write_requests", 0))
    configured_maximum_writes = int(_mapping(config.get("risk"))["maximum_write_requests"])
    if maximum_writes <= 0 or maximum_writes > configured_maximum_writes:
        raise RunnerConfigurationError(
            "admission receipt maximum_write_requests is missing or exceeds config"
        )
    research = str(receipt.get("research_status") or "")
    configured_research = str(_mapping(config.get("research")).get("status") or "")
    if research != configured_research:
        raise RunnerConfigurationError("receipt research status differs from frozen config")
    if research == "RESEARCH_REJECTED":
        raise RunnerConfigurationError("a research-rejected candidate cannot submit SimNow orders")
    if purpose == "natural_signal" and research != "RESEARCH_ADMITTED":
        raise RunnerConfigurationError("natural_signal requires RESEARCH_ADMITTED config")
    if purpose == "engineering_smoke" and int(receipt.get("remaining_smoke_attempts", 0)) <= 0:
        raise RunnerConfigurationError("engineering smoke attempt budget is exhausted")
    if purpose == "natural_signal" and not re.fullmatch(
        r"[0-9a-f]{64}", str(receipt.get("signal_preregistration_sha256") or "").lower()
    ):
        raise RunnerConfigurationError(
            "natural_signal receipt requires a frozen signal preregistration SHA-256"
        )
    instrument = str(receipt.get("instrument") or "")
    if not SA_PATTERN.fullmatch(instrument):
        raise RunnerConfigurationError("receipt must freeze an actual SA InstrumentID")
    account = str(receipt.get("account_fingerprint") or "")
    trading_day = str(receipt.get("trading_day") or "")
    if re.fullmatch(r"acct_[0-9a-f]{16}", account) is None:
        raise RunnerConfigurationError("receipt account_fingerprint is invalid")
    if len(trading_day) != 8 or not trading_day.isdigit():
        raise RunnerConfigurationError("receipt TradingDay is invalid")

    expected_sources = source_file_hashes()
    if _mapping(receipt.get("source_hashes")) != expected_sources:
        raise RunnerConfigurationError("receipt source hashes differ from the running source tree")
    expected_dependencies = dependency_identity_hashes()
    if _mapping(receipt.get("dependency_hashes")) != expected_dependencies:
        raise RunnerConfigurationError("receipt dependency hashes differ from imported components")
    _require_hash(receipt.get("native_sha256"), "native_sha256")
    _require_hash(receipt.get("ctp_package_sha256"), "ctp_package_sha256")
    reviewer = _mapping(receipt.get("reviewer"))
    if not str(reviewer.get("id") or "").strip():
        raise RunnerConfigurationError("receipt reviewer identity is required")
    _require_hash(reviewer.get("approval_sha256"), "reviewer.approval_sha256")
    evidence_hashes = _mapping(receipt.get("evidence_hashes"))
    if set(evidence_hashes) != {"G1", "G2", "G3"}:
        raise RunnerConfigurationError("receipt must bind G1/G2/G3 evidence hashes")
    for gate, value in evidence_hashes.items():
        _require_hash(value, f"evidence_hashes.{gate}")
    expected_research_hash = sha256_json(_mapping(config.get("research")))
    if (
        _require_hash(receipt.get("research_config_sha256"), "research_config_sha256")
        != expected_research_hash
    ):
        raise RunnerConfigurationError("receipt research config hash mismatch")
    receipt_calendar_hash = _require_hash(
        receipt.get("session_calendar_sha256"), "session_calendar_sha256"
    )
    configured_calendar_hash = str(
        _mapping(config.get("trading_calendar")).get("sha256") or ""
    ).lower()
    if receipt_calendar_hash != configured_calendar_hash:
        raise RunnerConfigurationError("receipt session calendar hash differs from config")

    trigger = _mapping(receipt.get("engineering_trigger"))
    if purpose == "engineering_smoke":
        required_trigger = {
            "trigger_id",
            "instrument",
            "trading_day",
            "side",
            "not_before_utc",
            "not_after_utc",
            "minimum_ingest_seq",
        }
        if set(trigger) != required_trigger:
            raise RunnerConfigurationError("engineering smoke requires a complete frozen trigger")
        if trigger.get("instrument") != instrument or trigger.get("trading_day") != trading_day:
            raise RunnerConfigurationError("engineering trigger identity differs from receipt")
        if trigger.get("side") not in {"long", "short"}:
            raise RunnerConfigurationError("engineering trigger side must be long or short")
        try:
            not_before = datetime.fromisoformat(
                str(trigger["not_before_utc"]).replace("Z", "+00:00")
            )
            not_after = datetime.fromisoformat(str(trigger["not_after_utc"]).replace("Z", "+00:00"))
            minimum_sequence = int(trigger["minimum_ingest_seq"])
        except (ValueError, TypeError) as exc:
            raise RunnerConfigurationError("engineering trigger values are invalid") from exc
        if (
            not_before.tzinfo is None
            or not_after.tzinfo is None
            or not_before >= not_after
            or minimum_sequence <= 0
        ):
            raise RunnerConfigurationError("engineering trigger bounds are invalid")
        expected_trigger_hash = sha256_json(trigger)
        if (
            _require_hash(receipt.get("engineering_trigger_sha256"), "engineering_trigger_sha256")
            != expected_trigger_hash
        ):
            raise RunnerConfigurationError("engineering trigger hash mismatch")
    elif trigger or receipt.get("engineering_trigger_sha256"):
        raise RunnerConfigurationError(
            "natural_signal receipt cannot contain an engineering trigger"
        )

    safe = dict(receipt)
    safe["_path"] = str(receipt_path.resolve())
    safe["_receipt_sha256"] = sha256_file(receipt_path)
    return AdmissionReceipt(safe, _RECEIPT_VALIDATION_MARKER)


def _validate_receipt_runtime_profile(
    receipt: AdmissionReceipt | None, identity: Mapping[str, Any]
) -> None:
    """Prevent an environment override from escaping the receipt-bound profile."""

    if receipt is None:
        return
    if not _validated_receipt(receipt):
        raise RunnerConfigurationError("network admission receipt was not validated")
    if str(identity.get("profile") or "") != str(receipt.get("environment") or ""):
        raise RunnerConfigurationError(
            "runtime SimNow profile differs from the admission receipt environment"
        )
    if str(identity.get("account_fingerprint") or "") != str(
        receipt.get("account_fingerprint") or ""
    ):
        raise RunnerConfigurationError("runtime account differs from admission receipt")


def _field(record: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if record.get(name) is not None:
            return record[name]
    return default


def _has_field(record: Mapping[str, Any], *names: str) -> bool:
    return any(name in record and record.get(name) is not None for name in names)


def _finite_nonnegative(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise PreflightError(f"{label} must be a finite nonnegative number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PreflightError(f"{label} must be a finite nonnegative number") from exc
    if not math.isfinite(result) or result < 0:
        raise PreflightError(f"{label} must be a finite nonnegative number")
    return result


def _load_trading_calendar(config: Mapping[str, Any]) -> dict[str, Any] | None:
    """Load a hash-frozen exchange calendar; never synthesize trading days."""

    calendar_config = _mapping(config.get("trading_calendar"))
    artifact_name = str(calendar_config.get("artifact") or "").strip()
    expected_hash = str(calendar_config.get("sha256") or "").strip().lower()
    if not artifact_name and not expected_hash:
        return None
    if not artifact_name or len(expected_hash) != 64:
        raise PreflightError("BLOCKED_CTP_TRADING_CALENDAR: artifact/hash pair is incomplete")
    artifact = Path(artifact_name)
    if not artifact.is_absolute():
        artifact = (HERE / artifact).resolve()
    try:
        actual_hash = sha256_file(artifact) if artifact.is_file() else ""
    except OSError as exc:
        raise PreflightError(
            "BLOCKED_CTP_TRADING_CALENDAR: artifact is unavailable for hash verification"
        ) from exc
    if actual_hash != expected_hash:
        raise PreflightError("BLOCKED_CTP_TRADING_CALENDAR: artifact is missing or hash-mismatched")
    try:
        payload = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreflightError(
            "BLOCKED_CTP_TRADING_CALENDAR: artifact is unreadable or invalid JSON"
        ) from exc
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema_version") != "iter22.czce-trading-calendar.v1"
        or str(payload.get("exchange") or "").upper() not in {"CZCE", "ZCE"}
        or not payload.get("source")
        or not payload.get("as_of_utc")
        or not isinstance(payload.get("trading_days"), list)
    ):
        raise PreflightError("BLOCKED_CTP_TRADING_CALENDAR: artifact contract is invalid")
    days = []
    for raw_day in payload["trading_days"]:
        text = str(raw_day).replace("-", "")
        try:
            day = datetime.strptime(text, "%Y%m%d").date()
        except ValueError as exc:
            raise PreflightError(
                "BLOCKED_CTP_TRADING_CALENDAR: artifact contains an invalid date"
            ) from exc
        days.append(day)
    if days != sorted(set(days)):
        raise PreflightError(
            "BLOCKED_CTP_TRADING_CALENDAR: trading days are not unique and ordered"
        )
    return {
        "days": days,
        "source": str(payload["source"]),
        "as_of_utc": str(payload["as_of_utc"]),
        "sha256": expected_hash,
        "path": str(artifact),
    }


def _apply_trading_calendar(
    records: list[Mapping[str, Any]],
    calendar: Mapping[str, Any] | None,
    trading_day: str,
) -> list[dict[str, Any]]:
    """Attach remaining-trading-day evidence to queried instruments."""

    normalized = [_mapping(item) for item in records]
    if calendar is None:
        return normalized
    try:
        current = datetime.strptime(str(trading_day).replace("-", "")[:8], "%Y%m%d").date()
    except ValueError as exc:
        raise PreflightError("session TradingDay is invalid") from exc
    days = tuple(calendar["days"])
    if current not in days:
        raise PreflightError(
            "BLOCKED_CTP_TRADING_CALENDAR: session TradingDay is absent from artifact"
        )
    current_index = days.index(current)
    prior_trading_day = days[current_index - 1] if current_index > 0 else None
    coverage_through = days[-1]
    for item in normalized:
        expiry_text = str(_field(item, "last_trading_day", "expire_date", "ExpireDate", default=""))
        try:
            expiry = datetime.strptime(expiry_text[:8], "%Y%m%d").date()
        except ValueError:
            continue
        item["trading_calendar_source"] = calendar["source"]
        item["trading_calendar_as_of_utc"] = calendar["as_of_utc"]
        item["trading_calendar_sha256"] = calendar["sha256"]
        item["trading_calendar_coverage_complete"] = expiry <= coverage_through
        item["trading_calendar_coverage_through"] = coverage_through.strftime("%Y%m%d")
        item["trading_calendar_expiry_date"] = expiry.strftime("%Y%m%d")
        item["expected_prior_trading_day"] = (
            prior_trading_day.strftime("%Y%m%d") if prior_trading_day is not None else ""
        )
        if not item["trading_calendar_coverage_complete"]:
            # A partial calendar must never be mistaken for a complete count of
            # remaining trading days.  Remove both accepted aliases in case a
            # caller supplied a stale derived value alongside the raw CTP row.
            item.pop("trading_days_to_expiry", None)
            item.pop("remaining_trading_days", None)
            continue
        item["trading_days_to_expiry"] = sum(current < day <= expiry for day in days)
    return normalized


def select_contract(
    records: list[Mapping[str, Any]],
    policy: Mapping[str, Any],
    *,
    configured_instrument: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Select or validate one actual SA month without accepting continuous aliases."""

    if today is None:
        raise PreflightError("contract selection requires the CTP session TradingDay")
    mode = str(policy.get("mode") or "auto")
    minimum_days = int(policy.get("minimum_trading_days_to_expiry", 5))
    normalized = [_mapping(item) for item in records]
    decisions = []
    eligible = []
    for item in normalized:
        instrument = str(
            _field(item, "instrument_id", "InstrumentID", "instrument", "symbol", default="")
        )
        exchange = str(_field(item, "exchange_id", "ExchangeID", "exchange", default="")).upper()
        product = str(_field(item, "product_id", "ProductID", default="")).upper()
        reason = "eligible"
        if not SA_PATTERN.fullmatch(instrument):
            reason = "not_actual_sa_month"
        elif exchange not in {"CZCE", "ZCE"}:
            reason = "wrong_exchange"
        elif product and product != "SA":
            reason = "wrong_product"
        elif _field(item, "is_trading", "IsTrading", default=True) not in {
            True,
            "1",
            "true",
            "True",
        }:
            reason = "not_trading"
        expiry_text = str(_field(item, "last_trading_day", "expire_date", "ExpireDate", default=""))
        try:
            expiry = datetime.strptime(expiry_text[:8], "%Y%m%d").date()
        except ValueError:
            expiry = None
            reason = "expiry_missing_or_invalid"
        if (
            reason == "eligible"
            and _field(item, "trading_calendar_coverage_complete", default=None) is False
        ):
            reason = "trading_calendar_coverage_incomplete"
        else:
            remaining_days = _field(
                item,
                "trading_days_to_expiry",
                "remaining_trading_days",
                default=None,
            )
            if remaining_days is None:
                reason = "trading_days_to_expiry_missing"
            else:
                try:
                    remaining_days = int(remaining_days)
                except (TypeError, ValueError):
                    reason = "trading_days_to_expiry_invalid"
                else:
                    if remaining_days < minimum_days:
                        reason = "expiry_lt_minimum_trading_days"
        if expiry is not None and expiry < today:
            reason = "contract_already_expired"
        decisions.append({"instrument": instrument, "reason": reason})
        if reason == "eligible":
            eligible.append((item, expiry))
    if mode == "manual":
        instrument = str(configured_instrument or "")
        if not SA_PATTERN.fullmatch(instrument):
            raise PreflightError("manual selection requires an actual SA month code")
        if not policy.get("manual_reviewed_at") or not policy.get("manual_source"):
            raise PreflightError("manual selection requires review date and source")
        match = next(
            (
                item
                for item, _expiry in eligible
                if str(
                    _field(
                        item, "instrument_id", "InstrumentID", "instrument", "symbol", default=""
                    )
                ).upper()
                == instrument.upper()
            ),
            None,
        )
        if match is None:
            selected_is_calendar_uncovered = any(
                decision["instrument"].upper() == instrument.upper()
                and decision["reason"] == "trading_calendar_coverage_incomplete"
                for decision in decisions
            )
            if selected_is_calendar_uncovered:
                raise PreflightError(
                    "BLOCKED_CTP_TRADING_CALENDAR: manual contract expiry is outside calendar coverage"
                )
            raise PreflightError(
                "manual SA contract is absent or ineligible in the complete snapshot"
            )
        expected_remaining = policy.get("manual_trading_days_to_expiry")
        expected_calendar_source = str(policy.get("manual_trading_days_source") or "")
        expected_calendar_hash = str(
            policy.get("manual_trading_days_evidence_sha256") or ""
        ).lower()
        if (
            expected_remaining is None
            or not expected_calendar_source
            or not re.fullmatch(r"[0-9a-f]{64}", expected_calendar_hash)
        ):
            raise PreflightError(
                "manual selection requires frozen remaining-trading-day value/source/hash"
            )
        if (
            int(expected_remaining) != int(match["trading_days_to_expiry"])
            or expected_calendar_source != str(match.get("trading_calendar_source") or "")
            or expected_calendar_hash != str(match.get("trading_calendar_sha256") or "").lower()
        ):
            raise PreflightError("manual remaining-trading-day evidence does not match artifact")
        try:
            reviewed_at = datetime.fromisoformat(
                str(policy["manual_reviewed_at"]).replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise PreflightError("manual review timestamp is invalid") from exc
        if reviewed_at.tzinfo is None:
            raise PreflightError("manual review timestamp must include a timezone")
        return {
            "status": "MANUAL_VALIDATED",
            "instrument": instrument.upper(),
            "source": str(policy["manual_source"]),
            "reviewed_at": str(policy["manual_reviewed_at"]),
            "remaining_trading_days": int(match["trading_days_to_expiry"]),
            "trading_days_evidence": {
                "source": expected_calendar_source,
                "sha256": expected_calendar_hash,
                "as_of_utc": match.get("trading_calendar_as_of_utc"),
            },
            "candidates": decisions,
            "metadata": match,
        }
    if mode != "auto":
        raise RunnerConfigurationError("contract_selection.mode must be auto or manual")
    if any(item["reason"] == "trading_calendar_coverage_incomplete" for item in decisions):
        raise PreflightError(
            "BLOCKED_CTP_TRADING_CALENDAR: calendar does not cover every eligible SA expiry"
        )
    if not eligible:
        if any(item["reason"] == "trading_days_to_expiry_missing" for item in decisions):
            raise PreflightError(
                "BLOCKED_CTP_TRADING_CALENDAR: remaining trading days are unproven"
            )
        raise PreflightError("complete instrument snapshot contains no eligible SA month")
    if any(
        _field(item, "ranking_evidence_complete", default=False) is not True
        for item, _expiry in eligible
    ):
        raise PreflightError(
            "BLOCKED_CTP_PRIOR_DAY_RANKING_EVIDENCE: complete prior-day ranking is absent"
        )
    for item, _expiry in eligible:
        for label, aliases in (
            ("open_interest", ("open_interest", "OpenInterest")),
            ("volume", ("volume", "Volume")),
        ):
            value = _field(item, *aliases, default=None)
            if value is None or not math.isfinite(float(value)) or float(value) < 0:
                raise PreflightError(
                    f"BLOCKED_CTP_PRIOR_DAY_RANKING_EVIDENCE: {label} is incomplete"
                )
    ranking_days = {
        str(_field(item, "ranking_trading_day", "trading_day", "TradingDay", default=""))
        for item, _expiry in eligible
    }
    if len(ranking_days) != 1 or "" in ranking_days:
        raise PreflightError(
            "automatic main-contract ranking requires one complete prior TradingDay"
        )
    expected_prior_days = {
        str(_field(item, "expected_prior_trading_day", default="")) for item, _expiry in eligible
    }
    if (
        len(expected_prior_days) != 1
        or "" in expected_prior_days
        or ranking_days != expected_prior_days
    ):
        raise PreflightError(
            "BLOCKED_CTP_PRIOR_DAY_RANKING_EVIDENCE: ranking is not the prior complete TradingDay"
        )
    ranked = sorted(
        eligible,
        key=lambda pair: (
            -float(_field(pair[0], "open_interest", "OpenInterest", default=-1)),
            -float(_field(pair[0], "volume", "Volume", default=-1)),
            pair[1],
            str(_field(pair[0], "instrument_id", "InstrumentID", "instrument", "symbol")),
        ),
    )
    winner = ranked[0][0]
    instrument = str(
        _field(winner, "instrument_id", "InstrumentID", "instrument", "symbol")
    ).upper()
    return {
        "status": "AUTO_RANKED",
        "instrument": instrument,
        "ranking_trading_day": next(iter(ranking_days)),
        "source": str(_field(winner, "source", default="sdk_complete_instrument_query")),
        "candidates": decisions,
        "metadata": winner,
    }


def _complete_query(value: Any, name: str) -> dict[str, Any]:
    result = _mapping(value)
    if not result:
        return {
            "query_name": name,
            "complete": False,
            "accepted_complete": False,
            "records": [],
            "failure": "missing_result",
        }
    result.setdefault("query_name", name)
    if isinstance(result.get("request_id"), bool) or isinstance(
        result.get("connection_generation"), bool
    ):
        request_id = generation = 0
    else:
        try:
            request_id = int(result.get("request_id") or 0)
            generation = int(result.get("connection_generation") or 0)
        except (TypeError, ValueError):
            request_id = generation = 0
    complete = (
        result.get("complete") is True
        and result.get("is_last_seen") is True
        and result.get("timed_out") is False
        and result.get("error_code") in {None, "", 0, "0"}
        and result.get("error_message") in {None, ""}
        and result.get("unsupported") is not True
        and request_id > 0
        and generation > 0
        and bool(str(result.get("account_fingerprint") or "").strip())
        and bool(result.get("completed_at_utc"))
        and isinstance(result.get("records"), (list, tuple))
    )
    result["accepted_complete"] = complete
    if not complete:
        result.setdefault("failure", "query_not_complete")
    records = result.get("records")
    result["records"] = list(records or []) if isinstance(records, (list, tuple)) else []
    return result


def _invoke_public(store: Any, names: tuple[str, ...], *args, **kwargs) -> Any:
    for name in names:
        method = getattr(store, name, None)
        if not callable(method):
            continue
        signature = inspect.signature(method)
        if args or kwargs:
            try:
                signature.bind(*args, **kwargs)
            except TypeError:
                # Do not silently drop a requested CTP scope and issue an
                # unbounded fallback query.
                return None
            return method(*args, **kwargs)
        return method()
    return None


QUERY_METHODS = {
    "account": ("query_account_result", "get_account_query_result"),
    "positions": ("query_positions_result", "get_positions_query_result"),
    "orders": ("query_orders_result", "get_orders_query_result"),
    "trades": ("query_trades_result", "get_trades_query_result"),
    "instruments": ("query_instruments_result", "get_instruments_query_result"),
    "fees": (
        "query_instrument_commission_rate_result",
        "query_instrument_commission_result",
        "query_commission_result",
    ),
    "margin": (
        "query_instrument_margin_rate_result",
        "query_instrument_margin_result",
        "query_margin_result",
    ),
}


def public_preflight_snapshot(
    store: Any,
    instrument: str | None = None,
    *,
    product_id: str | None = None,
    exchange_id: str | None = None,
) -> dict[str, Any]:
    """Read only public Store contracts; never reach into native/client attributes."""

    combined = getattr(store, "get_ctp_preflight_snapshot", None)
    if callable(combined):
        query_kwargs = {}
        if instrument:
            query_kwargs["instrument_id"] = instrument
        elif product_id:
            query_kwargs["product_id"] = str(product_id).strip().upper()
        if exchange_id:
            query_kwargs["exchange_id"] = str(exchange_id).strip().upper()
        raw = combined(**query_kwargs) if query_kwargs else combined()
        snapshot = _mapping(raw)
        queries = _mapping(snapshot.get("query_results") or snapshot.get("queries"))
        if "commission_rate" in queries:
            queries.setdefault("fees", queries["commission_rate"])
        if "margin_rate" in queries:
            queries.setdefault("margin", queries["margin_rate"])
        snapshot["queries"] = {
            name: _complete_query(value, name) for name, value in queries.items()
        }
        snapshot.setdefault("session", {})
        snapshot["session"] = _mapping(snapshot["session"])
        snapshot["session"].setdefault(
            "auto_settlement_confirm", snapshot.get("auto_settlement_confirm")
        )
        return snapshot
    session = _invoke_public(store, ("get_ctp_session_state", "get_session_state"))
    queries = {}
    for name, methods in QUERY_METHODS.items():
        if name in {"fees", "margin"} and not instrument:
            continue
        if name in {"fees", "margin"}:
            value = _invoke_public(store, methods, instrument)
        elif name == "trades":
            scope = {}
            if instrument:
                scope["instrument_id"] = instrument
            if exchange_id:
                scope["exchange_id"] = str(exchange_id).strip().upper()
            value = _invoke_public(store, methods, **scope)
        elif name == "instruments":
            scope = {}
            if instrument:
                scope["instrument_id"] = instrument
            if product_id:
                scope["product_id"] = str(product_id).strip().upper()
            if exchange_id:
                scope["exchange_id"] = str(exchange_id).strip().upper()
            value = _invoke_public(store, methods, **scope)
        else:
            value = _invoke_public(store, methods)
        queries[name] = _complete_query(value, name)
    return {"session": _mapping(session), "queries": queries}


def _query_records(snapshot: Mapping[str, Any], name: str) -> list[dict[str, Any]]:
    query = _mapping(_mapping(snapshot.get("queries")).get(name))
    if query.get("accepted_complete") is not True:
        raise PreflightError(f"{name} query is missing or incomplete")
    return [_mapping(item) for item in query.get("records") or []]


def _query_evidence(
    snapshot: Mapping[str, Any], names: tuple[str, ...]
) -> dict[str, dict[str, Any]]:
    """Project terminal query metadata without copying account record payloads."""

    queries = _mapping(snapshot.get("queries"))
    keys = (
        "request_id",
        "connection_generation",
        "account_fingerprint",
        "completed_at_utc",
        "complete",
        "accepted_complete",
        "is_last_seen",
        "timed_out",
        "unsupported",
        "error_code",
        "error_message",
    )
    evidence = {}
    for name in names:
        query = _mapping(queries.get(name))
        records = list(query.get("records") or ())
        evidence[name] = {
            **{key: query.get(key) for key in keys},
            "record_count": len(records),
            "records_sha256": sha256_json(records),
        }
    return evidence


def _query_session_identity(
    snapshot: Mapping[str, Any], query: Mapping[str, Any], label: str
) -> dict[str, Any]:
    """Validate identity/time fields shared by instrument-specific CTP reads."""

    session = _mapping(snapshot.get("session"))
    try:
        query_generation = int(query.get("connection_generation") or 0)
        session_generation = int(session.get("connection_generation") or 0)
        completed = datetime.fromisoformat(
            str(query.get("completed_at_utc") or "").replace("Z", "+00:00")
        )
    except (TypeError, ValueError) as exc:
        raise PreflightError(f"{label} query session identity is invalid") from exc
    account = str(query.get("account_fingerprint") or "")
    trading_day = str(session.get("trading_day") or "")
    if (
        query_generation <= 0
        or query_generation != session_generation
        or re.fullmatch(r"[0-9a-f]{16}", _account_core(account).lower()) is None
        or len(trading_day) != 8
        or not trading_day.isdigit()
        or completed.tzinfo is None
    ):
        raise PreflightError(f"{label} query session identity is incomplete or mismatched")
    return {
        "connection_generation": query_generation,
        "account_fingerprint": account,
        "trading_day": trading_day,
        "effective_at": str(query.get("completed_at_utc")),
    }


def validate_metadata(metadata: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    expected = _mapping(config.get("metadata_expectation"))
    tick = float(_field(metadata, "price_tick", "PriceTick", "tick_size", default=0) or 0)
    multiplier = float(
        _field(metadata, "volume_multiple", "VolumeMultiple", "multiplier", default=0) or 0
    )
    minimum = int(
        _field(
            metadata,
            "minimum_order_lots",
            "MinLimitOrderVolume",
            "min_size",
            "min_quantity",
            default=0,
        )
        or 0
    )
    if tick != float(expected["price_tick"]) or multiplier != float(expected["volume_multiple"]):
        raise PreflightError("SA metadata differs from frozen PriceTick/VolumeMultiple")
    if minimum != int(expected["minimum_order_lots"]):
        raise PreflightError("SA minimum order size differs from one lot")
    return {
        "price_tick": tick,
        "volume_multiple": multiplier,
        "minimum_order_lots": minimum,
    }


def fee_snapshot(
    snapshot: Mapping[str, Any],
    config: Mapping[str, Any],
    mode: str,
    *,
    instrument: str,
) -> dict[str, Any]:
    query = _mapping(_mapping(snapshot.get("queries")).get("fees"))
    records = _query_records(snapshot, "fees")
    if len(records) != 1:
        raise PreflightError("successful empty fee query cannot prove applicable SA fees")
    fee = records[0]
    field_names = {
        "open_money_rate": "OpenRatioByMoney",
        "open_volume_rate": "OpenRatioByVolume",
        "close_money_rate": "CloseRatioByMoney",
        "close_volume_rate": "CloseRatioByVolume",
        "close_today_money_rate": "CloseTodayRatioByMoney",
        "close_today_volume_rate": "CloseTodayRatioByVolume",
    }
    missing = [key for key, name in field_names.items() if not _has_field(fee, name)]
    if missing:
        raise PreflightError("fee record fields are incomplete: " + ",".join(missing))
    record_instrument = str(fee.get("InstrumentID") or "").upper()
    if record_instrument != str(instrument).upper():
        raise PreflightError("fee record is not bound to the selected instrument")
    normalized = {
        key: _finite_nonnegative(fee[name], f"fee.{key}") for key, name in field_names.items()
    }
    keys = tuple(field_names)
    identity = _query_session_identity(snapshot, query, "fee")
    normalized.update(
        verified=True,
        source="ctp_account_commission_query",
        effective_at=identity["effective_at"],
        expires_at=identity["trading_day"],
        query_request_id=query.get("request_id"),
        instrument=record_instrument,
        connection_generation=identity["connection_generation"],
        account_fingerprint=identity["account_fingerprint"],
        trading_day=identity["trading_day"],
        entry_slip_ticks=float(
            _mapping(config["fee_policy"])["replay_fixture"]["entry_slip_ticks"]
        ),
        exit_slip_ticks=float(_mapping(config["fee_policy"])["replay_fixture"]["exit_slip_ticks"]),
        edge_buffer_ticks=float(
            _mapping(config["fee_policy"])["replay_fixture"]["edge_buffer_ticks"]
        ),
    )
    if all(normalized[key] == 0 for key in keys):
        raise PreflightError("all-zero fee schedule is not accepted")
    return normalized


def validate_margin(snapshot: Mapping[str, Any], *, instrument: str) -> dict[str, Any]:
    query = _mapping(_mapping(snapshot.get("queries")).get("margin"))
    records = _query_records(snapshot, "margin")
    if len(records) != 1:
        raise PreflightError("margin query must return exactly one selected-instrument record")
    money_rates = []
    volume_rates = []
    for row in records:
        record_instrument = str(row.get("InstrumentID") or "").upper()
        if record_instrument != str(instrument).upper():
            raise PreflightError("margin record is not bound to the selected instrument")
        required = (
            "LongMarginRatioByMoney",
            "ShortMarginRatioByMoney",
            "LongMarginRatioByVolume",
            "ShortMarginRatioByVolume",
        )
        if any(not _has_field(row, name) for name in required):
            raise PreflightError("margin record fields are incomplete")
        money_rates.extend(
            _finite_nonnegative(row[name], f"margin.{name}") for name in required[:2]
        )
        volume_rates.extend(
            _finite_nonnegative(row[name], f"margin.{name}") for name in required[2:]
        )
    if not any(value > 0 for value in (*money_rates, *volume_rates)):
        raise PreflightError("margin query contains no positive applicable rate")
    identity = _query_session_identity(snapshot, query, "margin")
    result = {
        "maximum_money_rate": max(money_rates or [0.0]),
        "maximum_volume_rate": max(volume_rates or [0.0]),
        "source": "ctp_account_margin_query",
        "query_request_id": query.get("request_id"),
        "effective_at": identity["effective_at"],
        "instrument": str(instrument).upper(),
        "connection_generation": identity["connection_generation"],
        "account_fingerprint": identity["account_fingerprint"],
        "trading_day": identity["trading_day"],
    }
    return result


def validate_position_records(records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Reject position rows whose CTP identity or quantity split is ambiguous."""

    normalized = []
    for row in records:
        item = _mapping(row)
        required_groups = {
            "instrument": ("InstrumentID",),
            "exchange": ("ExchangeID",),
            "direction": ("PosiDirection",),
            "hedge": ("HedgeFlag",),
            "position": ("Position",),
            "today": ("TodayPosition",),
            "yesterday": ("YdPosition",),
            "long_frozen": ("LongFrozen",),
            "short_frozen": ("ShortFrozen",),
        }
        missing = [
            label for label, names in required_groups.items() if not _has_field(item, *names)
        ]
        if missing:
            raise PreflightError("position record fields are incomplete: " + ",".join(missing))
        instrument = str(_field(item, *required_groups["instrument"]) or "").upper()
        exchange = str(_field(item, *required_groups["exchange"]) or "").upper()
        direction = str(_field(item, *required_groups["direction"]) or "").lower()
        hedge = str(_field(item, *required_groups["hedge"]) or "").lower()
        if not SA_PATTERN.fullmatch(instrument):
            raise PreflightError("position record instrument is invalid")
        if exchange not in {"CZCE", "ZCE"}:
            raise PreflightError("position record exchange is invalid")
        if direction not in {"2", "3", "long", "short"}:
            raise PreflightError("position record direction is invalid")
        if hedge not in {"1", "speculation", "spec", "speculate"}:
            raise PreflightError("position record hedge flag is invalid")
        position = _finite_nonnegative(
            _field(item, *required_groups["position"]), "position.Position"
        )
        today = _finite_nonnegative(_field(item, *required_groups["today"]), "position.Today")
        yesterday = _finite_nonnegative(
            _field(item, *required_groups["yesterday"]), "position.Yesterday"
        )
        long_frozen = _finite_nonnegative(
            _field(item, *required_groups["long_frozen"]), "position.LongFrozen"
        )
        short_frozen = _finite_nonnegative(
            _field(item, *required_groups["short_frozen"]), "position.ShortFrozen"
        )
        if any(
            not value.is_integer()
            for value in (position, today, yesterday, long_frozen, short_frozen)
        ):
            raise PreflightError("position quantities must be whole lots")
        if not math.isclose(position, today + yesterday, rel_tol=0, abs_tol=1e-12):
            raise PreflightError("position TodayPosition/YdPosition do not sum to Position")
        if max(long_frozen, short_frozen) > position:
            raise PreflightError("position frozen quantity exceeds Position")
        normalized.append(
            {
                **item,
                "instrument": instrument,
                "exchange": exchange,
                "direction": direction,
                "hedge": hedge,
                "position_lots": int(position),
                "today_lots": int(today),
                "yesterday_lots": int(yesterday),
                "long_frozen_lots": int(long_frozen),
                "short_frozen_lots": int(short_frozen),
            }
        )
    return normalized


def _startup_account_observation(
    *,
    positions: list[Mapping[str, Any]],
    active_orders_count: int,
    query_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the durable, credential-free Stage-B account observation.

    This is deliberately an account-wide CTP preflight projection.  A
    ``BtApiBroker`` cache can be scoped to registered feeds, whereas this
    artifact must show every nonzero position returned by the authoritative
    Stage-B query before a strategy starts.  It contains no raw CTP account,
    investor, order, or credential identifiers.
    """

    projected_positions = [
        {
            "instrument": str(item["instrument"]),
            "exchange": str(item["exchange"]),
            "direction": str(item["direction"]),
            "hedge": str(item["hedge"]),
            "position_lots": int(item["position_lots"]),
            "today_lots": int(item["today_lots"]),
            "yesterday_lots": int(item["yesterday_lots"]),
            "long_frozen_lots": int(item["long_frozen_lots"]),
            "short_frozen_lots": int(item["short_frozen_lots"]),
        }
        for item in positions
        if int(item["position_lots"]) != 0
    ]
    projected_positions.sort(
        key=lambda item: (
            item["instrument"],
            item["exchange"],
            item["direction"],
            item["hedge"],
        )
    )
    return {
        "schema_version": "iter22.startup-account-observation.v1",
        "source": "ctp_preflight_stage_b",
        "scope": "account_wide",
        "read_only": True,
        "account_fingerprint": str(query_identity.get("account_fingerprint") or ""),
        "trading_day": str(query_identity.get("trading_day") or ""),
        "connection_generation": int(query_identity.get("connection_generation") or 0),
        "nonzero_position_record_count": len(projected_positions),
        "gross_position_lots": sum(int(item["position_lots"]) for item in projected_positions),
        "active_orders_count": int(active_orders_count),
        "positions": projected_positions,
    }


def _account_core(value: Any) -> str:
    text = str(value or "")
    return text[5:] if text.startswith("acct_") else text


def _stage_identity(
    snapshot: Mapping[str, Any], names: tuple[str, ...], expected_account: str
) -> dict[str, Any]:
    queries = _mapping(snapshot.get("queries"))
    accepted = [_mapping(queries.get(name)) for name in names]
    generations = {int(item.get("connection_generation") or 0) for item in accepted}
    accounts = {_account_core(item.get("account_fingerprint")) for item in accepted}
    request_ids = [int(item.get("request_id") or 0) for item in accepted]
    session = _mapping(snapshot.get("session"))
    trading_day = str(session.get("trading_day") or "")
    if len(generations) != 1 or 0 in generations:
        raise PreflightError("query connection generations are incomplete or mixed")
    if len(accounts) != 1 or "" in accounts:
        raise PreflightError("query account fingerprints are incomplete or mixed")
    if expected_account and next(iter(accounts)) != _account_core(expected_account):
        raise PreflightError("query account fingerprint differs from configured account")
    if len(set(request_ids)) != len(request_ids) or any(value <= 0 for value in request_ids):
        raise PreflightError("each preflight query requires a distinct positive request ID")
    if not trading_day:
        raise PreflightError("session TradingDay is missing")
    if int(session.get("connection_generation") or 0) != next(iter(generations)):
        raise PreflightError("session/query connection generation mismatch")
    return {
        "connection_generation": next(iter(generations)),
        "account_fingerprint": next(iter(accounts)),
        "trading_day": trading_day,
    }


def _validate_read_only_session(
    snapshot: Mapping[str, Any], *, expected_profile: str, allowed_confirm_count: int = 0
) -> tuple[dict[str, Any], dict[str, int]]:
    session = _mapping(snapshot.get("session"))
    if session.get("auto_settlement_confirm") is not False:
        raise PreflightError("session did not prove auto_settlement_confirm=false")
    if expected_profile and session.get("environment_profile") != expected_profile:
        raise PreflightError("SDK did not prove the selected SimNow profile")
    counts, counts_complete = _strict_request_counts(session.get("request_counts"))
    if not counts_complete:
        raise PreflightError("session request_counts write-key evidence is incomplete")
    if counts["settlement_confirm"] != int(allowed_confirm_count):
        raise PreflightError("unexpected settlement confirmation request count")
    if any(counts[key] for key in WRITE_REQUEST_COUNT_KEYS if key != "settlement_confirm"):
        raise PreflightError("preflight observed a forbidden state-changing request")
    if session.get("read_only_ready") is not True:
        raise PreflightError("CTP read-only session is not ready")
    return session, counts


def establish_read_only_ctp_session(
    store: BtApiStore,
    *,
    expected_profile: str,
) -> dict[str, Any]:
    """Connect through a read-only settlement query before a confirmation write.

    A newly built BtApi facade owns a CTP request feed but does not start its
    native session until the first typed operation. Settlement preparation must
    therefore establish that session through a query which cannot confirm
    settlement or submit/cancel an order, then prove the resulting state before
    taking the explicit confirmation branch.
    """

    initial_verification = store.verify_ctp_settlement(timeout=5.0)
    if initial_verification.get("read_only_safe") is not True:
        raise PreflightError("initial settlement readback did not prove zero write requests")
    session_before = store.get_ctp_session_state()
    _validate_read_only_session(
        {"session": session_before},
        expected_profile=expected_profile,
        allowed_confirm_count=0,
    )
    return initial_verification


def validate_api_diagnostic_snapshot(
    snapshot: Mapping[str, Any], *, identity: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate the Set-2 API diagnostic without selecting a strategy contract.

    This deliberately proves only the managed CTP session and the five public
    query families required to identify it.  It neither treats an instrument
    list as a contract-selection result nor treats API connectivity as strategy
    execution evidence.
    """

    session, request_counts = _validate_read_only_session(
        snapshot,
        expected_profile=str(identity.get("sdk_profile") or ""),
    )
    if snapshot.get("read_only_safe") is not True:
        raise PreflightError("query snapshot did not prove read_only_safe=true")
    if snapshot.get("write_request_free") is not True:
        raise PreflightError("query snapshot did not prove write_request_free=true")
    request_count_delta, delta_complete = _strict_request_counts(
        snapshot.get("request_count_delta")
    )
    if not delta_complete:
        raise PreflightError("query snapshot write request delta is incomplete")
    if any(request_count_delta[name] != 0 for name in WRITE_REQUEST_COUNT_KEYS):
        raise PreflightError("query snapshot observed a state-changing request")
    for name in API_DIAGNOSTIC_QUERY_NAMES:
        _query_records(snapshot, name)
    query_identity = _stage_identity(
        snapshot,
        API_DIAGNOSTIC_QUERY_NAMES,
        str(identity.get("account_fingerprint") or ""),
    )
    session_account = str(session.get("account_fingerprint") or "")
    expected_account = str(identity.get("account_fingerprint") or "")
    if not session_account or _account_core(session_account) != _account_core(expected_account):
        raise PreflightError("session account fingerprint differs from configured account")
    if _account_core(session_account) != _account_core(query_identity["account_fingerprint"]):
        raise PreflightError("session and public query account fingerprints differ")
    if str(session.get("trading_day") or "") != query_identity["trading_day"]:
        raise PreflightError("session and public query TradingDay differ")
    if int(session.get("connection_generation") or 0) != int(
        query_identity["connection_generation"]
    ):
        raise PreflightError("session and public query connection generation differ")

    query_evidence = _query_evidence(snapshot, API_DIAGNOSTIC_QUERY_NAMES)
    snapshot_hash = str(snapshot.get("snapshot_sha256") or "").lower()
    if _HEX64.fullmatch(snapshot_hash) is None:
        snapshot_hash = sha256_json(
            {
                "session": {
                    "account_fingerprint": session_account,
                    "trading_day": query_identity["trading_day"],
                    "connection_generation": query_identity["connection_generation"],
                    "environment_profile": session.get("environment_profile"),
                    "auto_settlement_confirm": session.get("auto_settlement_confirm"),
                    "request_counts": request_counts,
                },
                "request_count_delta": request_count_delta,
                "queries": query_evidence,
            }
        )
    return {
        "schema_version": "iter22.ctp-api-diagnostic.v1",
        "status": "PASS_API_DIAGNOSTIC",
        "strategy_status": "NOT_RUN",
        "session": {
            "connected": session.get("connected") is True,
            "read_only_ready": session.get("read_only_ready") is True,
            "trading_ready": session.get("trading_ready") is True,
            "auto_settlement_confirm": session.get("auto_settlement_confirm"),
            "environment_profile": session.get("environment_profile"),
            "account_fingerprint": session_account,
            "trading_day": query_identity["trading_day"],
            "connection_generation": query_identity["connection_generation"],
            "request_counts": request_counts,
            "request_count_delta": request_count_delta,
        },
        "query_identity": query_identity,
        "query_evidence": query_evidence,
        "query_snapshot_sha256": snapshot_hash,
        "query_names": list(API_DIAGNOSTIC_QUERY_NAMES),
    }


def validate_api_diagnostic_shutdown(health: Any) -> dict[str, Any]:
    """Require the Store to prove a clean shutdown before accepting the diagnostic."""

    if not isinstance(health, Mapping):
        raise PreflightError("Store shutdown did not return health evidence")
    if health.get("shutdown_state") != "PASS":
        raise PreflightError("Store shutdown is not PASS")
    if health.get("last_error_code") not in {None, ""}:
        raise PreflightError("Store shutdown reported an error")
    for field in ("worker_alive", "close_thread_alive"):
        if health.get(field) is not False:
            raise PreflightError(f"Store shutdown did not prove {field}=false")
    return {
        "shutdown_state": "PASS",
        "last_error_code": "",
        "worker_alive": False,
        "close_thread_alive": False,
    }


def validate_stage_a(
    snapshot: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    receipt: Mapping[str, Any] | None,
    expected_account: str,
    expected_profile: str,
) -> dict[str, Any]:
    session, counts = _validate_read_only_session(snapshot, expected_profile=expected_profile)
    required = ("account", "positions", "orders", "trades", "instruments")
    for name in required:
        _query_records(snapshot, name)
    identity = _stage_identity(snapshot, required, expected_account)
    if receipt and str(receipt.get("trading_day") or "") != identity["trading_day"]:
        raise PreflightError("session TradingDay differs from admission receipt")
    accounts = _query_records(snapshot, "account")
    if len(accounts) != 1:
        raise PreflightError("account query must contain exactly one record")
    equity = float(_field(accounts[0], "equity", "Balance", "balance", "value", default=0) or 0)
    available = float(_field(accounts[0], "available", "Available", "cash", default=-1) or 0)
    if not math.isfinite(equity) or equity <= 0:
        raise PreflightError("account query must prove positive finite equity")
    if not math.isfinite(available) or available < 0:
        raise PreflightError("account query must prove nonnegative finite available cash")
    policy = _mapping(config.get("contract_selection"))
    configured = str((receipt or {}).get("instrument") or config.get("instrument") or "")
    try:
        session_trading_date = datetime.strptime(
            identity["trading_day"].replace("-", "")[:8], "%Y%m%d"
        ).date()
    except ValueError as exc:
        raise PreflightError("session TradingDay is invalid") from exc
    instrument_records = _apply_trading_calendar(
        _query_records(snapshot, "instruments"),
        _load_trading_calendar(config),
        identity["trading_day"],
    )
    selection = select_contract(
        instrument_records,
        policy,
        configured_instrument=configured,
        today=session_trading_date,
    )
    if receipt and selection["instrument"] != configured.upper():
        raise PreflightError("complete contract query does not validate the receipt instrument")
    if receipt:
        calendar_hash = str(
            _mapping(selection.get("trading_days_evidence")).get("sha256")
            or _field(selection.get("metadata") or {}, "trading_calendar_sha256", default="")
            or ""
        ).lower()
        if calendar_hash != str(receipt.get("session_calendar_sha256") or "").lower():
            raise PreflightError("contract session calendar differs from admission receipt")
    # Stage A validates the actual CTP InstrumentField metadata before an
    # instrument-specific fee/margin query is issued.
    selection["validated_metadata"] = validate_metadata(selection["metadata"], config)
    return {
        "session": session,
        "request_counts": counts,
        "identity": identity,
        "selection": selection,
        "account": {"equity": equity, "available": available},
        "query_evidence": _query_evidence(snapshot, required),
    }


def validate_preflight(
    snapshot: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    mode: str,
    receipt: Mapping[str, Any] | None = None,
    stage_a: Mapping[str, Any] | None = None,
    expected_account: str = "",
    expected_profile: str = "",
    allow_execution_recovery: bool = False,
) -> dict[str, Any]:
    separate_stage_a = stage_a is not None
    stage_a_result = dict(
        stage_a
        or validate_stage_a(
            snapshot,
            config,
            receipt=receipt,
            expected_account=expected_account,
            expected_profile=expected_profile,
        )
    )
    session, request_counts = _validate_read_only_session(
        snapshot, expected_profile=expected_profile
    )
    for required in ("account", "positions", "orders", "trades", "instruments", "fees", "margin"):
        _query_records(snapshot, required)
    stage_b_identity = _stage_identity(
        snapshot,
        ("account", "positions", "orders", "trades", "instruments", "fees", "margin"),
        expected_account,
    )
    if stage_b_identity != stage_a_result["identity"]:
        raise PreflightError("Stage A and Stage B query identity changed")
    stage_a_request_ids = {
        int(_mapping(item).get("request_id") or 0)
        for item in _mapping(stage_a_result.get("query_evidence")).values()
    }
    stage_b_request_ids = {
        int(_mapping(_mapping(snapshot.get("queries")).get(name)).get("request_id") or 0)
        for name in ("account", "positions", "orders", "trades", "instruments", "fees", "margin")
    }
    if separate_stage_a and stage_a_request_ids & stage_b_request_ids:
        raise PreflightError("Stage A and Stage B query request IDs must be globally distinct")

    stage_b_accounts = _query_records(snapshot, "account")
    if len(stage_b_accounts) != 1:
        raise PreflightError("Stage B account query must contain exactly one record")
    equity = float(
        _field(stage_b_accounts[0], "equity", "Balance", "balance", "value", default=0) or 0
    )
    available = float(
        _field(stage_b_accounts[0], "available", "Available", "cash", default=-1) or 0
    )
    if not math.isfinite(equity) or equity <= 0:
        raise PreflightError("Stage B account query must prove positive finite equity")
    if not math.isfinite(available) or available < 0:
        raise PreflightError("Stage B account query must prove nonnegative finite available cash")

    selection = dict(stage_a_result["selection"])
    instrument_rows = _query_records(snapshot, "instruments")
    if not any(
        str(_field(row, "instrument_id", "InstrumentID", default="")).upper()
        == selection["instrument"]
        for row in instrument_rows
    ):
        raise PreflightError("Stage B does not contain the frozen SA instrument")
    stage_a_metadata = validate_metadata(selection["metadata"], config)
    stage_b_row = next(
        row
        for row in instrument_rows
        if str(_field(row, "instrument_id", "InstrumentID", default="")).upper()
        == selection["instrument"]
    )
    normalized_metadata = validate_metadata(stage_b_row, config)
    if normalized_metadata != stage_a_metadata:
        raise PreflightError("Stage A and Stage B instrument metadata changed")
    margin = validate_margin(snapshot, instrument=selection["instrument"])
    fee = fee_snapshot(snapshot, config, mode, instrument=selection["instrument"])
    positions = validate_position_records(_query_records(snapshot, "positions"))
    orders = _query_records(snapshot, "orders")
    nonzero_positions = [item for item in positions if int(item["position_lots"]) != 0]
    active_orders = [
        item
        for item in orders
        if str(_field(item, "status", default="")).lower()
        not in {"completed", "canceled", "cancelled", "rejected", "expired"}
    ]
    ready_shadow = session.get("read_only_ready") is True
    ready_simnow_base = (
        ready_shadow
        and (session.get("trading_ready") is True or session.get("ready") is True)
        and str(session.get("settlement_state") or "").lower() in {"confirmed", "ready"}
        and equity > 0
        and available >= 0
        and fee["verified"]
        and str(config.get("environment")) != "simnow_second_7x24"
    )
    recovery_required = bool(nonzero_positions or active_orders)
    ready_simnow = ready_simnow_base and not recovery_required
    ready_for_recovery = bool(allow_execution_recovery and ready_simnow_base and recovery_required)
    if mode == "shadow" and not ready_shadow:
        raise PreflightError("market-data/read-only session is not ready")
    if mode == "simnow" and not (ready_simnow or ready_for_recovery):
        raise PreflightError("SimNow trading readiness is incomplete")
    startup_account_observation = _startup_account_observation(
        positions=positions,
        active_orders_count=len(active_orders),
        query_identity=stage_b_identity,
    )
    return {
        "status": "PASS",
        "ready_for_shadow": ready_shadow,
        "ready_for_simnow": ready_simnow,
        "ready_for_recovery": ready_for_recovery,
        "recovery_required": recovery_required,
        "session": session,
        "query_identity": stage_b_identity,
        "request_counts": request_counts,
        "selection": selection,
        "metadata": normalized_metadata,
        "margin": margin,
        "fee": fee,
        "account": {"equity": equity, "available": available},
        "positions_count": len(nonzero_positions),
        "active_orders_count": len(active_orders),
        "startup_account_observation": startup_account_observation,
        "query_evidence": _query_evidence(
            snapshot,
            ("account", "positions", "orders", "trades", "instruments", "fees", "margin"),
        ),
    }


def _validate_ctp_package_manifest(diagnostics: Mapping[str, Any]) -> list[dict[str, str]]:
    """Validate the public SDK's deterministic Python-source package identity."""

    raw = diagnostics.get("ctp_package_manifest")
    if type(raw) is not list or not raw:
        raise PreflightError("CTP package manifest is missing")
    manifest: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != {"path", "sha256"}:
            raise PreflightError("CTP package manifest row has an invalid shape")
        path = str(item.get("path") or "")
        digest = str(item.get("sha256") or "").lower()
        parts = path.split("/")
        if (
            not path
            or path.startswith("/")
            or "\\" in path
            or any(part in {"", ".", "..", "__pycache__"} for part in parts)
            or not path.endswith(".py")
            or not _HEX64.fullmatch(digest)
        ):
            raise PreflightError("CTP package manifest row is invalid")
        manifest.append({"path": path, "sha256": digest})
    if manifest != sorted(manifest, key=lambda item: item["path"]):
        raise PreflightError("CTP package manifest paths are not sorted")
    if len({item["path"] for item in manifest}) != len(manifest):
        raise PreflightError("CTP package manifest paths are not unique")
    canonical = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    expected = hashlib.sha256(canonical).hexdigest()
    observed = str(diagnostics.get("ctp_package_sha256") or "").lower()
    if observed != expected:
        raise PreflightError("CTP package manifest hash is invalid")
    return manifest


def native_probe() -> dict[str, Any]:
    """Probe CTP native loading in an isolated child process."""

    script = r"""
import hashlib, importlib, json, pathlib, platform, sys
result = {"ready": False, "python": sys.version.split()[0], "platform": platform.platform(), "architecture": platform.machine()}
try:
    package = importlib.import_module("bt_api_ctp")
    probe = getattr(package, "get_ctp_native_diagnostics", None)
    if not callable(probe):
        raise RuntimeError("bt_api_ctp_public_native_diagnostics_missing")
    status = dict(probe())
    result.update(status)
    result["ready"] = status.get("native_loaded") is True
    package_path = pathlib.Path(package.__file__).resolve()
    result["bt_api_ctp_path"] = str(package_path)
    result["bt_api_ctp_version"] = getattr(package, "__version__", None)
    package_root = package_path.parent
    actual_manifest = [
        {
            "path": path.relative_to(package_root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(
            (
                candidate
                for candidate in package_root.rglob("*.py")
                if candidate.is_file()
                and "__pycache__" not in candidate.relative_to(package_root).parts
            ),
            key=lambda candidate: candidate.relative_to(package_root).as_posix(),
        )
    ]
    canonical_manifest = json.dumps(
        actual_manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    actual_package_sha256 = hashlib.sha256(canonical_manifest).hexdigest()
    result["ctp_package_manifest_verified"] = bool(
        actual_manifest == status.get("ctp_package_manifest")
        and actual_package_sha256 == status.get("ctp_package_sha256")
    )
    if not result["ctp_package_manifest_verified"]:
        result["ready"] = False
        result["reason"] = "ctp_package_manifest_mismatch"
    package_dir = pathlib.Path(str(status.get("package_dir") or ""))
    native_files = []
    for name in status.get("matching_extensions") or ():
        path = (package_dir / str(name)).resolve()
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            native_files.append({"path": str(path), "sha256": digest})
    result["native_files"] = native_files
    if result["ready"] and not native_files:
        result["ready"] = False
        result["reason"] = "loaded_native_file_identity_missing"
except BaseException as exc:
    result["reason"] = type(exc).__name__
print(json.dumps(result, sort_keys=True))
raise SystemExit(0 if result.get("ready") else 3)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=20, check=False
    )
    output = completed.stdout.strip().splitlines()
    try:
        result = json.loads(output[-1]) if output else {}
    except json.JSONDecodeError:
        result = {}
    try:
        result["ctp_package_manifest"] = _validate_ctp_package_manifest(result)
    except PreflightError as exc:
        result["ready"] = False
        result["reason"] = str(exc)
    result["exit_code"] = completed.returncode
    result["signal"] = -completed.returncode if completed.returncode < 0 else None
    result["accepted"] = bool(
        completed.returncode == 0
        and result.get("ready") is True
        and result.get("ctp_package_manifest_verified") is True
        and _HEX64.fullmatch(str(result.get("ctp_package_sha256") or "").lower())
    )
    return result


class AccountLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.handle.close()
            raise RunnerConfigurationError(
                "another local writer owns the SimNow account lock"
            ) from exc
        return self

    def __exit__(self, *_args):
        if self.handle is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


class ReplayClock:
    def __init__(self, wall: float, monotonic_value: float = 1000.0) -> None:
        self.wall = float(wall)
        self.monotonic_value = float(monotonic_value)

    def set(self, wall: float, monotonic_value: float) -> None:
        self.wall = float(wall)
        self.monotonic_value = float(monotonic_value)

    def utc_now(self) -> float:
        return self.wall

    def monotonic_now(self) -> float:
        return self.monotonic_value

    def monotonic(self) -> float:
        return self.monotonic_value

    def monotonic_ns(self) -> int:
        return int(self.monotonic_value * 1_000_000_000)

    def advance(self, seconds: float) -> None:
        self.wall += float(seconds)
        self.monotonic_value += float(seconds)


class ReplayClient:
    """Read-only local event source consumed through ``BtApiStore``."""

    def __init__(self, ticks, clock: ReplayClock, *, eof_event_time_watermark: float) -> None:
        self.ticks = deque(ticks)
        self.clock = clock
        self.connected = False
        self.subscriptions = []
        self.eof_event_time_watermark = float(eof_event_time_watermark)

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def subscribe(self, symbol) -> None:
        self.subscriptions.append(symbol)

    def supports_live_ticks(self, _symbol) -> bool:
        return True

    def has_pending_tick(self, _symbol) -> bool:
        return bool(self.ticks)

    def is_source_exhausted(self, _symbol) -> bool:
        return not self.ticks

    def get_source_event_time_watermark(self, _symbol) -> float:
        return self.eof_event_time_watermark

    def poll_tick(self, symbol):
        if not self.ticks:
            return None
        tick = self.ticks[0]
        if tick.symbol != symbol:
            return None
        tick = self.ticks.popleft()
        self.clock.set(tick.timestamp, tick.recv_monotonic_ns / 1e9)
        return tick


def generate_replay_ticks(fixture: Mapping[str, Any], scenario: str):
    if fixture.get("schema_version") != "iter22.synthetic-quote-fixture.v1":
        raise RunnerConfigurationError("unsupported replay fixture schema")
    interval = float(fixture["tick_interval_seconds"])
    tick_size = float(fixture["price_tick"])
    base = float(fixture["base_price"])
    cumulative = float(fixture["starting_cumulative_volume"])
    sequence = 0
    monotonic_value = 1000.0
    for session_start, session_end in fixture["sessions"]:
        start = datetime.fromisoformat(session_start).timestamp()
        end = datetime.fromisoformat(session_end).timestamp()
        event_time = start
        while event_time < end:
            sequence += 1
            monotonic_value += interval
            elapsed_minutes = int((event_time - start) // 60)
            second = int(event_time - start) % 60
            if scenario == "trend":
                center = base + 3 * elapsed_minutes + (second % 10) - 5
                bid_size, ask_size = float(fixture["bid_size"]), float(fixture["ask_size"])
            elif scenario == "reverse":
                center = base - 3 * elapsed_minutes - (second % 10) + 5
                bid_size, ask_size = float(fixture["ask_size"]), float(fixture["bid_size"])
            elif scenario == "no_signal":
                center = base + ((second % 10) - 5)
                bid_size = ask_size = 10.0
            else:
                raise RunnerConfigurationError(f"unknown replay scenario {scenario!r}")
            last = round(center / tick_size) * tick_size
            bid = last - tick_size
            ask = last
            cumulative += 1
            tick = TickEvent(
                timestamp=event_time,
                symbol=str(fixture["instrument"]),
                exchange=str(fixture["exchange"]),
                asset_type="futures",
                local_time=event_time,
                exchange_time=event_time,
                received_wall_time=event_time,
                received_monotonic_ns=int(monotonic_value * 1e9),
                sequence=sequence,
                continuity_status="continuous",
                source=str(fixture["source"]),
                price=last,
                volume=1.0,
                bid_price=bid,
                ask_price=ask,
                bid_volume=bid_size,
                ask_volume=ask_size,
            )
            tick.schema_version = "ctp.quote.v2"
            tick.event_time_utc = datetime.fromtimestamp(event_time, timezone.utc).isoformat()
            tick.recv_time_utc = tick.event_time_utc
            tick.recv_monotonic_ns = int(monotonic_value * 1e9)
            tick.ingest_seq = sequence
            tick.connection_generation = int(fixture["connection_generation"])
            tick.trading_day = str(fixture["trading_day"])
            tick.action_day = (
                datetime.fromtimestamp(event_time, timezone.utc)
                .astimezone(BEIJING)
                .strftime("%Y%m%d")
            )
            tick.cum_volume = cumulative
            tick.cumulative_volume = cumulative
            tick.delta_volume = 1.0
            tick.volume_semantics = "delta"
            tick.volume_complete = True
            tick.volume_quality = "continuous"
            tick.event_time_source = "fixture_utc"
            tick.open_interest = 100000.0
            tick.quality_flags = ()
            tick.lower_limit = float(fixture["lower_limit"])
            tick.upper_limit = float(fixture["upper_limit"])
            yield tick
            event_time += interval


def _strategy_params(
    config: Mapping[str, Any],
    *,
    mode: str,
    purpose: str,
    instrument: str,
    trading_day: str,
    metadata: Mapping[str, Any],
    fee: Mapping[str, Any],
    risk_store: DailyRiskStore,
    reporter: EvidenceWriter,
    control: RuntimeControl,
    admitted: bool,
    preflight_ready: bool,
    clock=None,
    run_deadline=None,
    hypothetical_fills=False,
    connection_generation=0,
    account_id_hash="",
    environment_profile="",
    maximum_entry_attempts=None,
    entry_budget_key="all",
    engineering_trigger=None,
    session_calendar_sha256="",
    session_state_provider=None,
    execution_recovery=None,
    startup_account_observation=None,
) -> dict[str, Any]:
    warmup = _mapping(config.get("warmup"))
    signal_config = _mapping(config.get("signal"))
    execution = _mapping(config.get("execution"))
    risk = _mapping(config.get("risk"))
    quality = _mapping(config.get("quality"))
    return {
        "mode": mode,
        "purpose": purpose,
        "candidate_id": config["candidate_id"],
        "instrument": instrument,
        "trading_day": trading_day,
        "connection_generation": int(connection_generation or 0),
        "account_fingerprint": account_id_hash,
        "environment_profile": environment_profile,
        "tick_size": metadata["price_tick"],
        "multiplier": metadata["volume_multiple"],
        "lots": risk["lots"],
        "entry_score": signal_config["entry_score"],
        "exit_score": signal_config["exit_score"],
        "confirm_seconds": signal_config["confirm_seconds"],
        "confirm_quotes": signal_config["confirm_quotes"],
        "warmup_bars": warmup["bars"],
        "warmup_quote_seconds": warmup["quote_seconds"],
        "max_bar_age_seconds": quality["max_bar_age_seconds"],
        "max_quote_age_seconds": quality["max_quote_age_seconds"],
        "exit_quote_age_seconds": quality["exit_quote_age_seconds"],
        "watermark_milliseconds": quality["watermark_milliseconds"],
        "minimum_depth_lots": quality["minimum_depth_lots"],
        "maximum_spread_ticks": quality["maximum_spread_ticks"],
        "minimum_hold_seconds": risk["min_hold_seconds"],
        "maximum_hold_seconds": risk["max_hold_seconds"],
        "cooldown_seconds": risk["cooldown_seconds"],
        "entry_timeout_seconds": execution["entry_timeout_seconds"],
        "cancel_timeout_seconds": execution["cancel_timeout_seconds"],
        "drain_timeout_seconds": risk["drain_timeout_seconds"],
        "entry_protection_ticks": execution["entry_protection_ticks"],
        "max_exit_requotes": execution["max_exit_requotes"],
        "maximum_entry_attempts": int(
            risk["maximum_entry_attempts"]
            if maximum_entry_attempts is None
            else maximum_entry_attempts
        ),
        "entry_budget_key": entry_budget_key,
        "maximum_write_requests": risk["maximum_write_requests"],
        "emergency_write_reserve": risk["emergency_write_reserve"],
        "daily_loss_cny": risk["daily_loss_cny"],
        "daily_loss_equity_fraction": risk["daily_loss_equity_fraction"],
        "admitted": admitted,
        "preflight_ready": preflight_ready,
        "hypothetical_fills": hypothetical_fills,
        "fee": dict(fee),
        "price_limits": {
            "lower": metadata.get("lower_limit"),
            "upper": metadata.get("upper_limit"),
        },
        "risk_store": risk_store,
        "reporter": reporter,
        "runtime_control": control,
        "clock": clock,
        "run_deadline_monotonic": run_deadline,
        "research_status": str(_mapping(config.get("research")).get("status") or ""),
        "engineering_trigger": dict(engineering_trigger or {}),
        "session_calendar_sha256": str(session_calendar_sha256 or ""),
        "session_state_provider": session_state_provider,
        "execution_recovery": deepcopy(execution_recovery),
        "startup_account_observation": deepcopy(startup_account_observation),
    }


def _run_id(mode: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"iter22-{mode}-{stamp}-{uuid.uuid4().hex[:8]}"


def _evidence_directory(config: Mapping[str, Any], run_id: str, override: Path | None) -> Path:
    if override is not None:
        return override.resolve()
    base = HERE / str(_mapping(config.get("evidence")).get("directory", "reports"))
    return (base / run_id).resolve()


def _claim_output_directory(path: Path) -> Path:
    """Exclusively claim a fresh evidence directory before any run-side effects."""

    directory = path.resolve()
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise RunnerConfigurationError(
            f"output directory already exists and cannot be reused: {directory}"
        ) from exc
    return directory


def _append_retention_audit(path: Path, payload: Mapping[str, Any]) -> None:
    """Append and fsync one root-level retention decision."""

    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str) + "\n"
    ).encode("utf-8")
    with path.open("ab") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _retention_protection(directory: Path, manifest: Mapping[str, Any]) -> tuple[bool, str]:
    """Return a conservative protection decision for one completed run."""

    if manifest.get("retention_protected") is True:
        return True, "manifest_retention_protected"
    if manifest.get("research_reference_sha256") or manifest.get("acceptance_reference_sha256"):
        return True, "manifest_frozen_reference"
    marker = directory / "evidence-protection.json"
    if not marker.exists():
        return False, ""
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True, "unreadable_protection_marker"
    reference = str(payload.get("reference_sha256") or "").lower()
    valid = (
        payload.get("schema_version") == "iter22.evidence-protection.v1"
        and payload.get("run_id") == manifest.get("run_id")
        and payload.get("kind") in {"research", "acceptance"}
        and re.fullmatch(r"[0-9a-f]{64}", reference) is not None
    )
    return True, "frozen_reference" if valid else "invalid_protection_marker"


def _valid_retention_release(
    directory: Path, manifest: Mapping[str, Any], manifest_hash: str
) -> tuple[bool, str]:
    marker = directory / "retention-release.json"
    if not marker.is_file():
        return False, "release_missing"
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        released_at = datetime.fromisoformat(
            str(payload.get("released_at_utc") or "").replace("Z", "+00:00")
        )
    except (OSError, json.JSONDecodeError, ValueError):
        return False, "release_invalid"
    valid = (
        payload.get("schema_version") == "iter22.retention-release.v1"
        and payload.get("run_id") == manifest.get("run_id")
        and str(payload.get("manifest_sha256") or "").lower() == manifest_hash
        and released_at.tzinfo is not None
        and bool(str(payload.get("released_by") or "").strip())
        and bool(str(payload.get("reason") or "").strip())
    )
    return valid, "release_verified" if valid else "release_invalid"


def apply_evidence_retention(root: Path | str, *, retain_trading_days: int) -> dict[str, Any]:
    """Delete only explicitly released, unprotected runs older than the retained days.

    The policy intentionally prefers disk growth to deleting evidence whose
    release cannot be proved.  A research or acceptance protection marker is
    never overridden by a release marker.
    """

    retain = int(retain_trading_days)
    if retain <= 0:
        raise RunnerConfigurationError("retain_trading_days must be positive")
    root_path = Path(root).resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    audit_path = root_path / "retention_audit.jsonl"
    lock = AccountLock(root_path / ".retention.lock")
    try:
        lock.__enter__()
    except RunnerConfigurationError:
        return {
            "status": "SKIPPED_LOCK_BUSY",
            "retain_trading_days": retain,
            "audit_path": str(audit_path),
            "deleted_runs": [],
        }
    try:
        entries = []
        invalid_directories = []
        for directory in sorted(root_path.iterdir(), key=lambda item: item.name):
            if directory.is_symlink() or not directory.is_dir():
                continue
            manifest_path = directory / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                day_text = str(manifest.get("trading_day") or "").replace("-", "")
                trading_day = datetime.strptime(day_text, "%Y%m%d").date()
            except (OSError, json.JSONDecodeError, ValueError):
                invalid_directories.append(directory.name)
                continue
            if manifest.get("schema_version") != "iter22.manifest.v1":
                invalid_directories.append(directory.name)
                continue
            if str(manifest.get("exit_status") or "") in {"", "RUNNING"}:
                continue
            entries.append((directory, manifest_path, manifest, trading_day))

        for directory_name in invalid_directories:
            _append_retention_audit(
                audit_path,
                {
                    "at_utc": datetime.now(timezone.utc).isoformat(),
                    "directory": directory_name,
                    "result": "SKIPPED_INVALID_MANIFEST",
                    "reason": "identity_or_trading_day_unproven",
                },
            )

        all_days = sorted({item[3] for item in entries})
        retained_days = set(all_days[-retain:])
        deleted_runs = []
        protected_runs = []
        unreleased_runs = []
        invalid_releases = []
        for directory, manifest_path, manifest, trading_day in entries:
            if trading_day in retained_days:
                continue
            protected, protection_reason = _retention_protection(directory, manifest)
            decision = {
                "at_utc": datetime.now(timezone.utc).isoformat(),
                "run_id": manifest.get("run_id"),
                "trading_day": trading_day.strftime("%Y%m%d"),
                "directory": directory.name,
            }
            if protected:
                protected_runs.append(str(manifest.get("run_id") or directory.name))
                _append_retention_audit(
                    audit_path,
                    {**decision, "result": "SKIPPED_PROTECTED", "reason": protection_reason},
                )
                continue
            manifest_hash = sha256_file(manifest_path)
            released, release_reason = _valid_retention_release(directory, manifest, manifest_hash)
            if not released:
                target = str(manifest.get("run_id") or directory.name)
                if release_reason == "release_missing":
                    unreleased_runs.append(target)
                else:
                    invalid_releases.append(target)
                _append_retention_audit(
                    audit_path,
                    {**decision, "result": "SKIPPED_NOT_RELEASED", "reason": release_reason},
                )
                continue
            if directory.resolve().parent != root_path:
                raise RuntimeError("retention candidate escaped the evidence root")
            _append_retention_audit(
                audit_path,
                {**decision, "result": "DELETE_STARTED", "reason": release_reason},
            )
            shutil.rmtree(directory)
            _append_retention_audit(
                audit_path,
                {**decision, "result": "DELETED", "reason": release_reason},
            )
            deleted_runs.append(str(manifest.get("run_id") or directory.name))
        return {
            "status": "COMPLETE",
            "retain_trading_days": retain,
            "distinct_completed_trading_days": len(all_days),
            "retained_trading_days": [item.strftime("%Y%m%d") for item in sorted(retained_days)],
            "deleted_runs": deleted_runs,
            "protected_runs": protected_runs,
            "unreleased_runs": unreleased_runs,
            "invalid_release_runs": invalid_releases,
            "invalid_manifest_directories": invalid_directories,
            "audit_path": str(audit_path),
        }
    finally:
        lock.__exit__(None, None, None)


def run_replay(
    config: Mapping[str, Any],
    *,
    output_directory: Path,
    scenario: str,
    run_id: str | None = None,
    retention_root: Path | None = None,
) -> dict[str, Any]:
    output_directory = _claim_output_directory(output_directory)
    replay = _mapping(config.get("replay"))
    fixture_path = HERE / str(replay["fixture"])
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture_hash = sha256_file(fixture_path)
    instrument = str(fixture["instrument"])
    metadata = {
        "price_tick": float(fixture["price_tick"]),
        "volume_multiple": float(fixture["volume_multiple"]),
        "minimum_order_lots": 1,
        "lower_limit": float(fixture["lower_limit"]),
        "upper_limit": float(fixture["upper_limit"]),
    }
    fee = dict(_mapping(config["fee_policy"])["replay_fixture"])
    if replay.get("hypothetical_fills") is True:
        raise RunnerConfigurationError(
            "this native BtApiBroker replay has no local fill model; "
            "hypothetical_fills must remain false"
        )
    run_id = run_id or _run_id("replay")
    evidence_config = _mapping(config["evidence"])
    interval = float(fixture["tick_interval_seconds"])
    estimated_ticks = sum(
        max(
            int(
                (
                    datetime.fromisoformat(end).timestamp()
                    - datetime.fromisoformat(start).timestamp()
                )
                / interval
            ),
            0,
        )
        for start, end in fixture["sessions"]
    )
    replay_queue_limit = max(
        min(
            int(evidence_config["audit_queue_limit"]),
            int(evidence_config["quote_queue_limit"]),
        ),
        min(3 * estimated_ticks + 1_000, 100_000),
    )
    reporter = EvidenceWriter(
        output_directory,
        min_free_bytes=int(evidence_config["minimum_free_bytes"]),
        rotate_bytes=int(evidence_config["rotate_bytes"]),
        audit_queue_limit=replay_queue_limit,
    )
    manifest = reporter.manifest(
        run_id=run_id,
        purpose="engineering_fixture",
        mode="replay",
        environment="local_fixture",
        candidate_id=str(config["candidate_id"]),
        config_hash=config_hash(config),
        code_hash=code_hash(),
        data_hash=fixture_hash,
        account_id_hash="acct_replay_fixture",
        instrument=instrument,
        trading_day=str(fixture["trading_day"]),
        started_at_utc=datetime.now(timezone.utc).isoformat(),
        fee_source=str(fee["source"]),
        hypothetical_fills=False,
    )
    manifest["source_components"] = runtime_component_identities()
    manifest["g4_gate_status"] = "NOT_RUN"
    manifest["execution_basis"] = "none"
    manifest["replay_audit_queue_limit"] = replay_queue_limit
    store = None
    report: dict[str, Any] | None = None
    failure: BaseException | None = None
    exit_status = "FAIL_CLOSED"
    try:
        retention = (
            apply_evidence_retention(
                retention_root,
                retain_trading_days=int(_mapping(config["evidence"])["retain_trading_days"]),
            )
            if retention_root is not None
            else {
                "status": "NOT_APPLICABLE_EXPLICIT_OUTPUT_DIRECTORY",
                "retain_trading_days": int(_mapping(config["evidence"])["retain_trading_days"]),
            }
        )
        manifest["retention"] = retention
        reporter.write_json("retention.json", retention)
        reporter.write_json(
            "contract_selection.json",
            {
                "status": "FIXTURE_ONLY",
                "instrument": instrument,
                "source": str(fixture["source"]),
                "market_evidence": False,
            },
        )
        reporter.write_json(
            "preflight.json",
            {
                "status": "FIXTURE_ONLY",
                "network": "NOT_RUN",
                "orders_to_sdk": 0,
                "market_evidence": False,
            },
        )
        first_epoch = datetime.fromisoformat(fixture["sessions"][0][0]).timestamp()
        clock = ReplayClock(first_epoch)
        eof_watermark = datetime.fromisoformat(fixture["sessions"][-1][1]).timestamp() + 0.5
        client = ReplayClient(
            generate_replay_ticks(fixture, scenario),
            clock,
            eof_event_time_watermark=eof_watermark,
        )
        broker_metadata = {
            **metadata,
            "tick_size": metadata["price_tick"],
            "contract_multiplier": metadata["volume_multiple"],
            "min_size": 1,
            "lot_size": 1,
            "quantity_step": 1,
            "currency": "CNY",
        }
        store = BtApiStore(
            provider="ctp",
            api=client,
            cash=float(replay["starting_cash"]),
            value=float(replay["starting_cash"]),
            contract_metadata={instrument: broker_metadata},
        )
        cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
        broker = BtApiBroker(
            store=store,
            provider="ctp",
            cash=float(replay["starting_cash"]),
            value=float(replay["starting_cash"]),
            position_mode="net",
            contract_metadata={instrument: broker_metadata},
            validation_enabled=True,
            sdk_preflight=False,
            flatten_on_stop=False,
            force_refresh_queries=False,
        )
        cerebro.setbroker(broker)
        feed = store.getdata(
            dataname=instrument,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            dispatch_ticks=True,
            dispatch_bars=True,
            backfill_start=False,
            qcheck=0.0,
            clock=clock,
        )
        cerebro.adddata(feed, name=instrument)
        _attach_trade_logger(cerebro, output_directory)
        risk_store = DailyRiskStore(output_directory / "replay-risk.json")
        risk_store.load_or_create(
            account_fingerprint="acct_replay_fixture",
            trading_day=str(fixture["trading_day"]),
            starting_equity=float(replay["starting_cash"]),
            reconciliation_complete=True,
        )
        params = _strategy_params(
            config,
            mode="replay",
            purpose="engineering_fixture",
            instrument=instrument,
            trading_day=str(fixture["trading_day"]),
            metadata=metadata,
            fee=fee,
            risk_store=risk_store,
            reporter=reporter,
            control=RuntimeControl(),
            admitted=False,
            preflight_ready=True,
            clock=clock,
            connection_generation=int(fixture["connection_generation"]),
            account_id_hash="acct_replay_fixture",
            environment_profile="local_fixture",
            hypothetical_fills=False,
        )
        cerebro.addstrategy(SAMidFrequencyStrategy, **params)
        strategies = cerebro.run(preload=False, runonce=False)
        report = _final_sa_report(strategies[0])
        report.update(
            run_id=run_id,
            scenario=scenario,
            fixture_sha256=fixture_hash,
            evidence_directory=str(output_directory),
            execution_basis="none",
            hypothetical_fills=False,
            pnl_fields_emitted=False,
            market_evidence=False,
            profitability_evidence=False,
            sdk_write_requests=0,
            g4_gate_status="NOT_RUN",
            runtime_chain={
                "cerebro": f"{type(cerebro).__module__}.{type(cerebro).__name__}",
                "store": f"{type(store).__module__}.{type(store).__name__}",
                "feed": f"{type(feed).__module__}.{type(feed).__name__}",
                "broker": f"{type(broker).__module__}.{type(broker).__name__}",
                "strategy": (f"{type(strategies[0]).__module__}.{type(strategies[0]).__name__}"),
            },
        )
        if report.get("orders") or report.get("position_lots") != 0:
            raise RuntimeError("read-only replay attempted execution or ended non-flat")
        report["business_summary_hash"] = business_summary_hash(report)
        reporter.write_json(
            "reconciliation.json",
            {
                "status": "LOCAL_FIXTURE_ONLY",
                "position_lots": report["position_lots"],
                "unknown_intents": report["unknown_intents"],
                "sdk_write_requests": 0,
            },
        )
        reporter.write_json(
            "daily_report.json",
            {
                "mode": "replay",
                "trading_day": str(fixture["trading_day"]),
                "execution_basis": "none",
                "hypothetical_fills": False,
                "pnl_fields_emitted": False,
                "research_status": str(_mapping(config.get("research")).get("status") or ""),
            },
        )
        exit_status = "PASS_REPLAY_PATH"
    except BaseException as exc:
        failure = exc
        for filename, payload in (
            (
                "failure.json",
                {
                    "status": "FAIL_CLOSED",
                    "error_code": type(exc).__name__,
                    "message": str(exc),
                },
            ),
            (
                "reconciliation.json",
                {"status": "NOT_PROVEN", "position_lots": None, "unknown_intents": None},
            ),
            (
                "daily_report.json",
                {
                    "mode": "replay",
                    "status": "FAIL_CLOSED",
                    "pnl_fields_emitted": False,
                },
            ),
        ):
            try:
                reporter.write_json(filename, payload)
            except Exception:
                pass
    finally:
        if store is not None:
            try:
                store.stop()
            except BaseException as exc:
                if failure is None:
                    failure = exc
                    exit_status = "FAIL_CLOSED"
        try:
            reporter.finalize_manifest(manifest, exit_status)
        except BaseException as exc:
            if failure is None:
                failure = exc
    if failure is not None:
        raise failure
    if report is None:
        raise RuntimeError("replay ended without a report")
    return report


def _strategy_identity_sha256(config: Mapping[str, Any], *, purpose: str) -> str:
    """Bind SDK journal ownership to stable candidate provenance across restarts."""

    material = {
        "schema_version": "iter22.strategy-identity.v1",
        "candidate_id": str(config.get("candidate_id") or ""),
        "purpose": str(purpose or ""),
        "config_sha256": config_hash(config),
        "source_hashes": source_file_hashes(),
    }
    return sha256_json(material)


def _build_live_store(
    config: Mapping[str, Any],
    env_values: Mapping[str, str],
    *,
    mode: str,
    purpose: str,
    state_directory: Path,
    allow_order_writes: bool,
    api_cls=None,
    store_cls=BtApiStore,
    reachable_selector: Callable[..., Any] | None = None,
) -> tuple[BtApiStore, dict[str, Any], list[str]]:
    """Build the only managed CTP client through ``provider='btapi'``.

    The Store owns construction of the top-level :class:`bt_api_py.BtApi` and
    its durable execution session.  The example never opens a native Trader
    client or a second query connection.
    """

    if allow_order_writes and mode != "simnow":
        raise RunnerConfigurationError("order writes are permitted only in simnow mode")
    if allow_order_writes and purpose not in {"engineering_smoke", "natural_signal"}:
        raise RunnerConfigurationError("order writes require an admitted SimNow purpose")
    fronts = resolve_fronts(
        config,
        env_values,
        select_reachable=True,
        reachable_selector=reachable_selector,
    )
    credential_values = credentials(env_values)
    account_id_hash = account_fingerprint(
        credential_values["broker_id"], credential_values["investor_id"]
    )
    sdk_state = state_directory / account_id_hash / "sdk"
    exchange_kwargs = {
        CTP_EXCHANGE: {
            "broker_id": credential_values["broker_id"],
            "user_id": credential_values["investor_id"],
            "password": credential_values["password"],
            "app_id": credential_values["app_id"],
            "auth_code": credential_values["auth_code"],
            "td_front": fronts["td_front"],
            "md_front": fronts["md_front"],
            "ctp_env_profile": fronts["sdk_profile"],
            "require_ctp_profile": fronts["sdk_profile"],
            "auto_settlement_confirm": False,
        }
    }
    execution_config = {
        # Every network session starts read-only.  The admitted SimNow path is
        # armed atomically only after both query stages bind the live account,
        # TradingDay, instrument, generation, profile, native file and receipt.
        "market_data_only": True,
        "order_journal": str(sdk_state / "orders.jsonl"),
        "account_risk_state": str(sdk_state / "account-risk.json"),
        "require_order_journal": True,
        "account_currency": "CNY",
        "required_environments": {CTP_EXCHANGE: "demo"},
        "strategy_id": f"{config['candidate_id']}:{purpose}",
        "strategy_identity_sha256": _strategy_identity_sha256(config, purpose=purpose),
    }
    store_options = {
        "provider": "btapi",
        "backend": "direct",
        "config": {
            "exchange_kwargs": exchange_kwargs,
            # A single exchange is deliberately configured.  The Store binds
            # the frozen instrument to it after Stage A selection without a
            # second client or a private route mutation.
            "symbol_routes": {},
            "execution_config": execution_config,
            "require_account_risk": bool(allow_order_writes),
            "book_queue_size": 1,
        },
    }
    if allow_order_writes:
        authorization_key_id = str(env_values.get("ITER22_APPROVAL_KEY_ID") or "").strip()
        authorization_secret = str(env_values.get("ITER22_APPROVAL_HMAC_KEY") or "")
        if not authorization_key_id or len(authorization_secret.encode("utf-8")) < 32:
            raise RunnerConfigurationError("execution authorization trust root is unavailable")
        # Keep the trust root outside the SDK configuration object.  BtApiStore
        # consumes and removes these private constructor options before it
        # instantiates BtApi, so the secret cannot be forwarded to a provider.
        store_options["execution_authorization_key_id"] = authorization_key_id
        store_options["execution_authorization_secret"] = authorization_secret
    if api_cls is not None:
        store_options["api_cls"] = api_cls
    store = store_cls(**store_options)
    safe_identity = {
        "profile": fronts["profile"],
        "profile_basis": fronts["profile_basis"],
        "sdk_profile": fronts["sdk_profile"],
        "market_alignment": fronts["market_alignment"],
        "td_front": fronts["td_front"],
        "md_front": fronts["md_front"],
        "account_fingerprint": account_id_hash,
    }
    secrets = [
        credential_values["investor_id"],
        credential_values["password"],
        credential_values["auth_code"],
        credential_values["app_id"],
        str(env_values.get("ITER22_APPROVAL_HMAC_KEY") or ""),
    ]
    return store, safe_identity, [value for value in secrets if value]


def _observation_evidence(
    report: Mapping[str, Any],
    terminal_session: Mapping[str, Any],
    identity: Mapping[str, Any],
    *,
    preflight_only: bool = False,
) -> dict[str, Any]:
    """Build the machine-judgeable G3 observation boundary."""

    observed = _mapping(report.get("observation_evidence"))
    counts, request_counts_complete = _strict_request_counts(terminal_session.get("request_counts"))
    forbidden_counts = {
        name: counts[name] if request_counts_complete else None for name in WRITE_REQUEST_COUNT_KEYS
    }
    valid_seconds = float(observed.get("valid_session_seconds") or 0.0)
    completed_bars = int(observed.get("qualified_completed_bars") or 0)
    quote_window_seconds = float(report.get("quote_window_seconds") or 0.0)
    expected_generation = observed.get("expected_connection_generation")
    terminal_generation = terminal_session.get("connection_generation")
    expected_day = str(observed.get("trading_day") or "")
    terminal_day = str(terminal_session.get("trading_day") or "")
    try:
        generation_matches = bool(expected_generation) and int(expected_generation) == int(
            terminal_generation or 0
        )
    except (TypeError, ValueError):
        generation_matches = False
    checks = {
        "first_set_profile": identity.get("profile")
        in {"simnow_first_group1", "simnow_first_group2"},
        "actual_market_alignment": identity.get("market_alignment") == "actual_market_hours",
        "valid_observation_seconds_gte_3600": valid_seconds >= 3600.0,
        "qualified_completed_bars_gte_60": completed_bars >= 60,
        "qualified_quote_window_seconds_gte_60": quote_window_seconds >= 60.0,
        "request_count_evidence_complete": request_counts_complete,
        "write_request_counts_zero": request_counts_complete
        and all(value == 0 for value in forbidden_counts.values()),
        "profile_matches": terminal_session.get("environment_profile")
        == identity.get("sdk_profile"),
        "trading_day_matches": bool(expected_day) and expected_day == terminal_day,
        "generation_matches": generation_matches,
    }
    if preflight_only:
        gate_status = "NOT_RUN_PREFLIGHT_ONLY"
    else:
        gate_status = "PASS" if all(checks.values()) else "INCOMPLETE"
    return {
        **observed,
        "profile": identity.get("profile"),
        "sdk_profile": identity.get("sdk_profile"),
        "market_alignment": identity.get("market_alignment"),
        "terminal_trading_day": terminal_day or None,
        "terminal_connection_generation": terminal_generation,
        "request_counts_terminal": counts,
        "forbidden_write_request_counts": forbidden_counts,
        "valid_session_seconds": valid_seconds,
        "qualified_completed_bars": completed_bars,
        "qualified_quote_window_seconds": quote_window_seconds,
        "g3_checks": checks,
        "g3_gate_status": gate_status,
    }


SHUTDOWN_ZERO_COUNT_KEYS = (
    "active_order_count",
    "local_position_count",
    "remote_position_count",
    "unknown_intent_count",
    "unmatched_trade_count",
)


def _shutdown_summary_complete(value: Any) -> bool:
    summary = _mapping(value)
    return bool(
        summary.get("status") == "PASS"
        and summary.get("remote_flat_proven") is True
        and summary.get("store_shutdown_state") == "PASS"
        and all(
            type(summary.get(name)) is int and summary.get(name) == 0
            for name in SHUTDOWN_ZERO_COUNT_KEYS
        )
    )


def _report_stopped_flat(report: Mapping[str, Any], shutdown_summary: Any) -> bool:
    return bool(
        report.get("state") == "STOPPED_FLAT"
        and type(report.get("position_lots")) is int
        and report.get("position_lots") == 0
        and type(report.get("unknown_intents")) is int
        and report.get("unknown_intents") == 0
        and "active_order" in report
        and report.get("active_order") is None
        and _shutdown_summary_complete(shutdown_summary)
    )


def _g4_evidence(
    report: Mapping[str, Any],
    *,
    purpose: str,
    receipt: Mapping[str, Any] | None,
    shutdown_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Judge the controlled SimNow cycle separately from process shutdown."""

    if purpose not in {"engineering_smoke", "natural_signal"}:
        return {
            "g4_gate_status": "NOT_RUN",
            "g4_checks": {},
            "actual_closed_cycles": 0,
        }
    shutdown = _mapping(shutdown_summary)

    shutdown_complete = _shutdown_summary_complete(shutdown)

    def stable_cycle(value: Mapping[str, Any]) -> bool:
        item = _mapping(value)
        cycle_id = str(item.get("cycle_id") or "")
        account = str(item.get("account_fingerprint") or "")
        trading_day = str(item.get("trading_day") or "")
        instrument = str(item.get("instrument") or "").upper()
        exchange = str(item.get("exchange") or "").upper()
        generation = item.get("connection_generation")
        cycle_hash = str(item.get("cycle_identity_sha256") or "")
        order_rows = [_mapping(row) for row in item.get("order_identities") or ()]
        trade_rows = [_mapping(row) for row in item.get("trade_identities") or ()]
        order_ids = {str(row.get("order_sys_id") or "") for row in order_rows}
        trade_ids = {str(row.get("trade_id") or "") for row in trade_rows}
        trade_order_ids = {str(row.get("order_sys_id") or "") for row in trade_rows}
        return bool(
            _HEX64.fullmatch(cycle_id)
            and _HEX64.fullmatch(cycle_hash)
            and re.fullmatch(r"acct_[0-9a-f]{16}", account)
            and len(trading_day) == 8
            and trading_day.isdigit()
            and SA_PATTERN.fullmatch(instrument)
            and exchange == "CZCE"
            and type(generation) is int
            and generation > 0
            and len(order_ids) >= 2
            and "" not in order_ids
            and len(trade_ids) >= 2
            and "" not in trade_ids
            and trade_order_ids.issubset(order_ids)
            and all(
                row.get(name) not in {None, ""}
                for row in order_rows
                for name in (
                    "instrument",
                    "exchange",
                    "front_id",
                    "session_id",
                    "order_ref",
                    "order_sys_id",
                )
            )
            and all(
                str(row.get("instrument") or "").upper() == instrument
                and str(row.get("exchange") or "").upper() == exchange
                for row in order_rows
            )
            and all(
                row.get(name) not in {None, ""}
                for row in trade_rows
                for name in ("instrument", "exchange", "trade_id", "order_sys_id")
            )
            and all(
                str(row.get("instrument") or "").upper() == instrument
                and str(row.get("exchange") or "").upper() == exchange
                for row in trade_rows
            )
        )

    proofs = [
        _mapping(item)
        for item in report.get("reconciliation_proofs") or ()
        if _mapping(item).get("phase") == "closed"
        and _mapping(item).get("complete") is True
        and _mapping(item).get("distinct_request_ids") is True
        and len(set(_mapping(item).get("request_ids") or ())) == 2
        and _mapping(item).get("ctp_order_identity_complete") is True
        and _mapping(item).get("ctp_trade_identity_complete") is True
        and _mapping(item).get("cycle_binding_complete") is True
        and stable_cycle(_mapping(item))
    ]
    actual_trades = [
        _mapping(item)
        for item in report.get("trades") or ()
        if _mapping(item).get("hypothetical") is False
        and _mapping(item).get("ctp_identity_complete") is True
        and stable_cycle(_mapping(item))
    ]
    joined_cycles = []
    for trade in actual_trades:
        for proof in proofs:
            identity_names = (
                "cycle_id",
                "cycle_identity_sha256",
                "account_fingerprint",
                "trading_day",
                "connection_generation",
                "instrument",
                "exchange",
                "order_identities",
                "trade_identities",
            )
            if all(trade.get(name) == proof.get(name) for name in identity_names):
                joined_cycles.append(
                    {
                        "cycle_id": trade["cycle_id"],
                        "cycle_identity_sha256": trade["cycle_identity_sha256"],
                        "reconciliation_snapshot_hash": proof.get("snapshot_hash"),
                    }
                )
                break
    unique_joined_cycles = {
        (item["cycle_id"], item["cycle_identity_sha256"]) for item in joined_cycles
    }
    checks = {
        "receipt_bound_to_purpose": bool(receipt) and str(receipt.get("purpose") or "") == purpose,
        "receipt_bound_to_account": bool(receipt)
        and receipt.get("account_fingerprint") == report.get("account_fingerprint"),
        "receipt_bound_to_trading_day": bool(receipt)
        and receipt.get("trading_day") == report.get("trading_day"),
        "receipt_bound_to_instrument": bool(receipt)
        and str(receipt.get("instrument") or "").upper()
        == str(report.get("instrument") or "").upper(),
        "actual_open_close_cycle_gte_1": bool(unique_joined_cycles),
        "post_close_two_round_reconciliation": bool(unique_joined_cycles),
        "broker_shutdown_remote_flat": shutdown_complete,
        "stopped_flat": _report_stopped_flat(report, shutdown),
        "natural_signal_preregistered": purpose != "natural_signal"
        or bool(receipt and receipt.get("signal_preregistration_sha256")),
        "engineering_trigger_executed": purpose != "engineering_smoke"
        or report.get("engineering_trigger_fired") is True,
    }
    return {
        "g4_gate_status": "PASS" if all(checks.values()) else "INCOMPLETE",
        "g4_checks": checks,
        "actual_closed_cycles": len(unique_joined_cycles),
        "joined_closed_cycles": joined_cycles,
        "post_close_reconciliation_proofs": proofs,
        "broker_shutdown_summary": shutdown,
    }


def _recovery_takeover_scope_sha256(plan: Mapping[str, Any]) -> str:
    """Hash recovery evidence without binding an operator to a short-lived token."""

    public = deepcopy(dict(plan))
    public.pop("recovery_token_sha256", None)
    return sha256_json(public)


def _recovery_plan_evidence(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Persist a plan fingerprint and actions without persisting its one-shot token."""

    public = deepcopy(dict(plan))
    token = public.pop("recovery_token_sha256", None)
    public["recovery_token_present"] = bool(_HEX64.fullmatch(str(token or "")))
    public["plan_sha256"] = sha256_json(dict(plan))
    public["takeover_scope_sha256"] = _recovery_takeover_scope_sha256(plan)
    return public


def _verify_operator_takeover(
    path: Path,
    *,
    run_id: str,
    account_fingerprint: str,
    trading_day: str,
    instrument: str,
    recovery_plan: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Verify a run-bound operator handoff without trusting process-local flags."""

    if not path.exists():
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return {"verified": False, "error_code": "operator_takeover_unreadable"}
    artifact_sha256 = hashlib.sha256(raw).hexdigest()
    if len(raw) > 64 * 1024:
        return {
            "verified": False,
            "error_code": "operator_takeover_oversized",
            "artifact_sha256": artifact_sha256,
        }
    try:
        candidate = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {
            "verified": False,
            "error_code": "operator_takeover_invalid_json",
            "artifact_sha256": artifact_sha256,
        }
    if not isinstance(candidate, Mapping) or set(candidate) != OPERATOR_TAKEOVER_FIELDS:
        return {
            "verified": False,
            "error_code": "operator_takeover_invalid_shape",
            "artifact_sha256": artifact_sha256,
        }
    takeover = dict(candidate)
    expected_identity = {
        "schema_version": "backtrader.ctp.operator-takeover.v1",
        "action": "takeover_execution_recovery",
        "approval_key_id": str(os.environ.get("ITER22_APPROVAL_KEY_ID") or "").strip(),
        "run_id": run_id,
        "account_fingerprint": account_fingerprint,
        "trading_day": trading_day,
        "instrument": f"CZCE.{instrument.upper()}",
        "recovery_evidence_sha256": _recovery_takeover_scope_sha256(recovery_plan),
    }
    if any(takeover.get(name) != value for name, value in expected_identity.items()):
        return {
            "verified": False,
            "error_code": "operator_takeover_identity_mismatch",
            "artifact_sha256": artifact_sha256,
        }
    secret = str(os.environ.get("ITER22_APPROVAL_HMAC_KEY") or "")
    supplied_signature = str(takeover.get("signature_hmac_sha256") or "").lower()
    if not expected_identity["approval_key_id"] or len(secret.encode("utf-8")) < 32:
        return {
            "verified": False,
            "error_code": "operator_takeover_trust_root_unavailable",
            "artifact_sha256": artifact_sha256,
        }
    try:
        acknowledged = datetime.fromisoformat(
            str(takeover.get("acknowledged_at_utc") or "").replace("Z", "+00:00")
        )
    except ValueError:
        acknowledged = None
    if (
        acknowledged is None
        or acknowledged.tzinfo is None
        or acknowledged > datetime.now(timezone.utc)
    ):
        return {
            "verified": False,
            "error_code": "operator_takeover_timestamp_invalid",
            "artifact_sha256": artifact_sha256,
        }
    unsigned = {
        name: takeover[name] for name in OPERATOR_TAKEOVER_FIELDS if name != "signature_hmac_sha256"
    }
    canonical = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    expected_signature = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    if _HEX64.fullmatch(supplied_signature) is None or not hmac.compare_digest(
        supplied_signature, expected_signature
    ):
        return {
            "verified": False,
            "error_code": "operator_takeover_signature_invalid",
            "artifact_sha256": artifact_sha256,
        }
    return {
        "verified": True,
        "error_code": None,
        "artifact_sha256": artifact_sha256,
        "approval_key_id": takeover["approval_key_id"],
        "run_id": takeover["run_id"],
        "account_fingerprint": takeover["account_fingerprint"],
        "trading_day": takeover["trading_day"],
        "instrument": takeover["instrument"],
        "recovery_evidence_sha256": takeover["recovery_evidence_sha256"],
        "acknowledged_at_utc": takeover["acknowledged_at_utc"],
    }


def _complete_flat_execution_recovery(
    store: Any,
    plan: Mapping[str, Any],
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Ask the SDK to prove its two-query FLAT barrier and consume the token once."""

    token = str(plan.get("recovery_token_sha256") or "")
    complete = getattr(store, "complete_execution_recovery", None)
    if plan.get("allowed_actions") != ["complete"] or not _HEX64.fullmatch(token):
        raise PreflightError("SDK FLAT recovery plan is not completable")
    if not callable(complete):
        completion = {
            "completed": False,
            "status": "failed",
            "error_code": "public_recovery_completion_unavailable",
        }
        history.append({"event": "complete", **completion})
        return completion
    try:
        value = complete(recovery_token_sha256=token)
    except Exception:
        completion = {
            "completed": False,
            "status": "failed",
            "error_code": "recovery_completion_failed",
        }
        history.append({"event": "complete", **completion})
        return completion
    expected_fields = {
        "completed",
        "armed",
        "market_data_only",
        "recovery_only",
        "requires_new_preflight",
        "recovery_token_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        completion = {
            "completed": False,
            "status": "failed",
            "error_code": "recovery_completion_invalid",
        }
        history.append({"event": "complete", **completion})
        return completion
    result = dict(value)
    if not (
        result.get("completed") is True
        and result.get("armed") is False
        and result.get("market_data_only") is True
        and result.get("recovery_only") is False
        and result.get("requires_new_preflight") is True
        and result.get("recovery_token_sha256") == token
    ):
        completion = {
            "completed": False,
            "status": "failed",
            "error_code": "recovery_completion_unproven",
        }
        history.append({"event": "complete", **completion})
        return completion
    completion = {"completed": True, "status": "completed", "error_code": None}
    history.append({"event": "complete", **completion})
    return completion


def _orchestrate_execution_recovery(
    store: Any, proof: Mapping[str, Any], *, command_timeout: float
) -> dict[str, Any]:
    """Execute only the ordered SDK recovery plan and return its final read model."""

    prepare = getattr(store, "prepare_execution_recovery", None)
    arm = getattr(store, "arm_execution_recovery", None)
    if not callable(prepare) or not callable(arm):
        raise PreflightError("public SDK execution recovery capability is unavailable")
    history: list[dict[str, Any]] = []
    write_actions = {"arms": 0, "cancels": 0, "closes": 0}

    def prepare_once() -> dict[str, Any]:
        value = prepare(dict(proof))
        if not isinstance(value, Mapping):
            raise PreflightError("SDK execution recovery plan is invalid")
        result = dict(value)
        history.append({"event": "prepare", "plan": _recovery_plan_evidence(result)})
        return result

    def arm_once(plan: Mapping[str, Any]) -> None:
        token = str(plan.get("recovery_token_sha256") or "")
        value = arm(dict(proof), recovery_token_sha256=token)
        if not isinstance(value, Mapping) or value.get("recovery_only") is not True:
            raise PreflightError("SDK execution recovery arming was not proven")
        write_actions["arms"] += 1
        history.append(
            {
                "event": "arm",
                "execution_cycle_id": value.get("execution_cycle_id"),
                "proof_sha256": value.get("proof_sha256"),
            }
        )

    def complete_flat_once(plan: Mapping[str, Any]) -> dict[str, Any]:
        return _complete_flat_execution_recovery(store, plan, history)

    def require_v0_close_plan(plan: Mapping[str, Any]) -> None:
        actions = plan.get("allowed_closes")
        if (
            plan.get("allowed_actions") != ["close"]
            or plan.get("allowed_cancels") != []
            or type(actions) is not list
            or len(actions) != 1
        ):
            raise PreflightError("SDK recovery plan is not a single close-only v0 action")
        action = actions[0]
        if not isinstance(action, Mapping):
            raise PreflightError("SDK recovery close action is invalid")
        position_side = str(action.get("position_side") or "").lower()
        expected_side = "sell" if position_side == "long" else "buy"
        scope = f"{str(action.get('exchange_id') or '').upper()}.{str(action.get('symbol') or '').upper()}"
        if not (
            action.get("execution_cycle_id") == plan.get("execution_cycle_id")
            and scope == str(plan.get("instrument") or proof.get("instrument") or "").upper()
            and str(action.get("exchange_id") or "").upper() == "CZCE"
            and position_side in {"long", "short"}
            and str(action.get("side") or "").lower() == expected_side
            and str(action.get("offset") or "").lower() == "close"
            and action.get("quantity") == "1"
            and action.get("quantity_unit") == "contracts"
        ):
            raise PreflightError("SDK recovery close action is not executable by Iteration 22 v0")

    plan = prepare_once()
    if plan.get("status") == "FLAT":
        completion = complete_flat_once(plan)
        return {
            "plan": plan,
            "history": history,
            "write_actions": write_actions,
            "armed_for_close": False,
            "completion": completion,
        }
    if plan.get("status") == "MANUAL_INTERVENTION":
        return {
            "plan": plan,
            "history": history,
            "write_actions": write_actions,
            "armed_for_close": False,
            "completion": None,
        }
    if plan.get("status") != "RECOVERABLE":
        raise PreflightError("SDK execution recovery status is invalid")

    allowed_cancels = list(plan.get("allowed_cancels") or ())
    if allowed_cancels:
        if plan.get("allowed_actions") != ["cancel"]:
            raise PreflightError("SDK recovery cancellation plan has invalid allowed actions")
        cancel_token = str(plan.get("recovery_token_sha256") or "")
        cancel_cycle_id = plan.get("execution_cycle_id")
        arm_once(plan)
        cancel = getattr(store, "cancel_execution_recovery_orders", None)
        wait = getattr(store, "wait_for_commands", None)
        if not callable(cancel) or not callable(wait):
            raise PreflightError("SDK execution recovery cancellation capability is unavailable")
        receipts = cancel(recovery_token_sha256=plan["recovery_token_sha256"])
        if type(receipts) is not list or len(receipts) != len(allowed_cancels):
            raise PreflightError("SDK execution recovery cancellation set was not fully queued")
        write_actions["cancels"] += len(receipts)
        history.append({"event": "cancel", "count": len(receipts)})
        if wait(max(float(command_timeout), 0.0)) is not True:
            raise PreflightError(
                "SDK execution recovery cancellation did not reach a terminal result"
            )
        plan = prepare_once()
        if str(plan.get("recovery_token_sha256") or "") == cancel_token:
            raise PreflightError("SDK recovery refresh did not rotate its one-shot token")
        if (
            plan.get("status") == "RECOVERABLE"
            and plan.get("execution_cycle_id") != cancel_cycle_id
        ):
            raise PreflightError("SDK recovery refresh changed its execution cycle")
        if plan.get("status") == "FLAT":
            completion = complete_flat_once(plan)
            return {
                "plan": plan,
                "history": history,
                "write_actions": write_actions,
                "armed_for_close": False,
                "completion": completion,
            }
        if plan.get("status") == "MANUAL_INTERVENTION":
            return {
                "plan": plan,
                "history": history,
                "write_actions": write_actions,
                "armed_for_close": False,
                "completion": None,
            }
        if plan.get("status") != "RECOVERABLE":
            raise PreflightError("SDK recovery refresh did not produce a close-only plan")
        require_v0_close_plan(plan)
        arm_once(plan)
    else:
        require_v0_close_plan(plan)
        arm_once(plan)

    return {
        "plan": plan,
        "history": history,
        "write_actions": write_actions,
        "armed_for_close": True,
        "completion": None,
    }


def _flat_recovery_completion_proven(
    plan: Mapping[str, Any], completion: Mapping[str, Any]
) -> bool:
    remote = _mapping(plan.get("remote_position"))
    position_fields = {
        "long_today",
        "long_yesterday",
        "short_today",
        "short_yesterday",
    }
    try:
        remote_flat = set(remote) == position_fields and all(
            int(remote[name]) == 0 for name in position_fields
        )
    except (TypeError, ValueError):
        remote_flat = False
    return bool(
        plan.get("status") == "FLAT"
        and remote_flat
        and completion.get("completed") is True
        and completion.get("status") == "completed"
        and completion.get("error_code") is None
    )


def _monitor_read_only_execution_recovery(
    store: Any,
    proof: Mapping[str, Any],
    initial_outcome: Mapping[str, Any],
    *,
    run_id: str,
    account_fingerprint: str,
    trading_day: str,
    instrument: str,
    operator_takeover_path: Path,
    stop_reason: Callable[[], str | None],
    persist: Callable[[Mapping[str, Any]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    poll_interval: float = RECOVERY_MONITOR_POLL_SECONDS,
) -> dict[str, Any]:
    """Keep startup recovery read-only until SDK FLAT, handoff, or a forced stop."""

    if not math.isfinite(float(poll_interval)) or float(poll_interval) < 0:
        raise ValueError("recovery monitor poll interval must be finite and nonnegative")
    prepare = getattr(store, "prepare_execution_recovery", None)
    if not callable(prepare):
        raise PreflightError("public SDK execution recovery capability is unavailable")
    plan = dict(_mapping(initial_outcome.get("plan")))
    history = list(initial_outcome.get("history") or ())
    write_actions = dict(initial_outcome.get("write_actions") or {})
    completion = dict(_mapping(initial_outcome.get("completion"))) or None
    iterations = 0
    last_takeover_artifact = None

    def snapshot(
        monitor_exit: str | None = None,
        *,
        operator_takeover: Mapping[str, Any] | None = None,
        forced_reason: str | None = None,
    ) -> dict[str, Any]:
        return {
            "plan": dict(plan),
            "history": list(history),
            "write_actions": dict(write_actions),
            "armed_for_close": False,
            "completion": dict(completion) if completion else None,
            "monitor_active": monitor_exit is None,
            "monitor_iterations": iterations,
            "monitor_exit": monitor_exit,
            "operator_takeover": (
                dict(operator_takeover) if isinstance(operator_takeover, Mapping) else None
            ),
            "forced_termination_reason": forced_reason,
        }

    def persist_snapshot(value: Mapping[str, Any]) -> None:
        if persist is not None:
            persist(value)

    history.append(
        {
            "event": "read_only_monitor_started",
            "poll_interval_seconds": float(poll_interval),
        }
    )
    current = snapshot()
    persist_snapshot(current)
    if _flat_recovery_completion_proven(plan, _mapping(completion)):
        current = snapshot("flat_completed")
        persist_snapshot(current)
        return current

    while True:
        takeover = _verify_operator_takeover(
            operator_takeover_path,
            run_id=run_id,
            account_fingerprint=account_fingerprint,
            trading_day=trading_day,
            instrument=instrument,
            recovery_plan=plan,
        )
        if takeover is not None:
            artifact_sha256 = takeover.get("artifact_sha256")
            artifact_identity = artifact_sha256 or takeover.get("error_code")
            if takeover.get("verified") is True:
                history.append({"event": "operator_takeover_verified", "evidence": takeover})
                current = snapshot("operator_takeover", operator_takeover=takeover)
                persist_snapshot(current)
                return current
            if artifact_identity != last_takeover_artifact:
                history.append({"event": "operator_takeover_rejected", "evidence": takeover})
                last_takeover_artifact = artifact_identity
                persist_snapshot(snapshot())

        forced_reason = str(stop_reason() or "").strip()
        if forced_reason:
            history.append({"event": "forced_termination", "reason": forced_reason})
            current = snapshot("forced_termination", forced_reason=forced_reason)
            persist_snapshot(current)
            return current

        sleep(float(poll_interval))
        forced_reason = str(stop_reason() or "").strip()
        if forced_reason:
            history.append({"event": "forced_termination", "reason": forced_reason})
            current = snapshot("forced_termination", forced_reason=forced_reason)
            persist_snapshot(current)
            return current

        iterations += 1
        try:
            value = prepare(dict(proof))
        except Exception as exc:
            history.append(
                {
                    "event": "monitor_prepare_failed",
                    "error_code": type(exc).__name__,
                    "iteration": iterations,
                }
            )
            persist_snapshot(snapshot())
            continue
        if not isinstance(value, Mapping) or value.get("status") not in {
            "FLAT",
            "RECOVERABLE",
            "MANUAL_INTERVENTION",
        }:
            history.append(
                {
                    "event": "monitor_prepare_rejected",
                    "error_code": "invalid_recovery_plan",
                    "iteration": iterations,
                }
            )
            persist_snapshot(snapshot())
            continue
        plan = dict(value)
        completion = None
        history.append(
            {
                "event": "monitor_prepare",
                "iteration": iterations,
                "plan": _recovery_plan_evidence(plan),
            }
        )
        if plan.get("status") == "FLAT":
            try:
                completion = _complete_flat_execution_recovery(store, plan, history)
            except PreflightError:
                completion = {
                    "completed": False,
                    "status": "failed",
                    "error_code": "recovery_flat_plan_uncompletable",
                }
                history.append({"event": "complete", **completion})
            if _flat_recovery_completion_proven(plan, _mapping(completion)):
                current = snapshot("flat_completed")
                persist_snapshot(current)
                return current
        persist_snapshot(snapshot())


def _terminal_recovery_result(
    outcome: Mapping[str, Any],
    *,
    run_id: str,
    identity: Mapping[str, Any],
    instrument: str,
    output_directory: Path,
) -> dict[str, Any]:
    """Build an explicit read-only result when SDK recovery cannot enter close mode."""

    plan = _mapping(outcome.get("plan"))
    status = str(plan.get("status") or "")
    remote = _mapping(plan.get("remote_position"))
    position_fields = (
        "long_today",
        "long_yesterday",
        "short_today",
        "short_yesterday",
    )
    try:
        position_lots = (
            sum(int(remote[name]) for name in position_fields)
            if set(remote) == set(position_fields)
            else None
        )
    except (KeyError, TypeError, ValueError):
        position_lots = None
    completion = _mapping(outcome.get("completion"))
    completed = _flat_recovery_completion_proven(plan, completion)
    monitor_exit = str(outcome.get("monitor_exit") or "")
    if completed:
        state = "STOPPED_FLAT"
        state_reason = "sdk_recovery_completion_proved_flat"
    elif monitor_exit == "operator_takeover":
        state = "MANUAL_INTERVENTION"
        state_reason = "verified_operator_takeover"
    elif monitor_exit == "forced_termination":
        state = "MANUAL_INTERVENTION"
        state_reason = str(outcome.get("forced_termination_reason") or "forced_termination")
    else:
        state = "MANUAL_INTERVENTION"
        state_reason = (
            "sdk_recovery_completion_unproven"
            if status == "FLAT"
            else "sdk_recovery_requires_manual_intervention"
        )
    return {
        "run_id": run_id,
        "mode": "simnow",
        "purpose": "execution_recovery",
        "state": state,
        "state_reason": state_reason,
        "account_fingerprint": identity.get("account_fingerprint"),
        "environment_profile": identity.get("sdk_profile"),
        "instrument": instrument,
        "trading_day": plan.get("trading_day"),
        "position_lots": position_lots,
        "active_order": None,
        "remote_active_orders": (
            None if status == "MANUAL_INTERVENTION" else len(plan.get("allowed_cancels") or ())
        ),
        "unknown_intents": len(plan.get("unknown_ids") or ()),
        "orders": [],
        "trades": [],
        "pnl_fields_emitted": False,
        "execution_recovery": {
            "recovery_only": True,
            "status": status if completed else "MANUAL_INTERVENTION",
            "prepared_status": status,
            "completed": completed,
            "completion": dict(completion) if completion else None,
            "monitor_exit": monitor_exit or None,
            "monitor_iterations": int(outcome.get("monitor_iterations") or 0),
            "operator_takeover": _mapping(outcome.get("operator_takeover")) or None,
            "forced_termination_reason": outcome.get("forced_termination_reason"),
            "normal_closed_cycles": 0,
            "history": list(outcome.get("history") or ()),
            "write_actions": dict(outcome.get("write_actions") or {}),
        },
        "g4_gate_status": "NOT_RUN",
        "g4_checks": {},
        "actual_closed_cycles": 0,
        "evidence_directory": str(output_directory),
    }


def _finalize_recovery_runtime_result(
    result: Mapping[str, Any], outcome: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Freeze recovery evidence outside the normal G4 cycle accounting."""

    finalized = dict(result)
    recovery_report = _mapping(finalized.get("execution_recovery"))
    recovery_refs = {
        _mapping(item).get("ref")
        for item in finalized.get("orders") or ()
        if _mapping(item).get("role") == "recovery_exit"
    }
    normal_roles = {
        str(_mapping(item).get("role") or "")
        for item in finalized.get("orders") or ()
        if str(_mapping(item).get("role") or "") in {"entry", "exit"}
    }
    if normal_roles:
        raise RuntimeError("recovery-only run emitted a normal cycle order")
    recovery_write_actions = dict(outcome.get("write_actions") or {})
    recovery_write_actions["closes"] = len({value for value in recovery_refs if value is not None})
    recovery_report.update(
        history=list(outcome.get("history") or ()),
        write_actions=recovery_write_actions,
        normal_closed_cycles=0,
    )
    finalized["execution_recovery"] = recovery_report
    finalized.update(
        g4_gate_status="NOT_RUN",
        g4_checks={},
        actual_closed_cycles=0,
    )
    return finalized, recovery_report


def _validate_network_invocation(
    config: Mapping[str, Any],
    *,
    mode: str,
    purpose: str,
    preflight_only: bool,
    prepare_settlement: bool,
    receipt: AdmissionReceipt | None,
    run_seconds: float,
    maximum_smoke_entry_attempts: int | None,
) -> int:
    """Enforce the write boundary for API callers as well as the CLI."""

    validate_config(config)
    if mode not in {"shadow", "simnow"}:
        raise RunnerConfigurationError("network runner accepts shadow or simnow only")
    if preflight_only and prepare_settlement:
        raise RunnerConfigurationError("preflight and settlement preparation are exclusive")
    if not math.isfinite(float(run_seconds)) or float(run_seconds) < 0:
        raise RunnerConfigurationError("run_seconds must be finite and nonnegative")
    if mode == "shadow":
        if prepare_settlement or purpose != "observation" or receipt is not None:
            raise RunnerConfigurationError("shadow network runs are read-only observation only")
    elif preflight_only or prepare_settlement:
        if purpose != "observation" or receipt is not None or float(run_seconds) != 0:
            raise RunnerConfigurationError(
                "SimNow preflight/settlement actions are receipt-free observation with no duration"
            )
    else:
        if purpose not in {"engineering_smoke", "natural_signal"}:
            raise RunnerConfigurationError("SimNow order runs require an admitted purpose")
        if not _validated_receipt(receipt):
            raise RunnerConfigurationError("SimNow order runs require a validated receipt")
        if float(run_seconds) <= 0:
            raise RunnerConfigurationError("SimNow order runs require a bounded positive duration")
        if receipt.get("mode") != mode or receipt.get("purpose") != purpose:
            raise RunnerConfigurationError("validated receipt does not match network invocation")
    if purpose == "engineering_smoke":
        attempts = 2 if maximum_smoke_entry_attempts is None else int(maximum_smoke_entry_attempts)
        if attempts not in {1, 2}:
            raise RunnerConfigurationError("engineering smoke attempts must be one or two")
        return attempts
    if maximum_smoke_entry_attempts is not None:
        raise RunnerConfigurationError("smoke attempt budget is valid only for engineering_smoke")
    return 0


def _validate_api_diagnostic_invocation(
    config: Mapping[str, Any],
    *,
    mode: str,
    purpose: str,
    receipt: AdmissionReceipt | None,
    run_seconds: float,
) -> None:
    """Reject every API-diagnostic invocation that could become a trading run."""

    validate_config(config)
    profile = str(config.get("environment") or "")
    profile_config = _mapping(_mapping(config.get("profiles")).get(profile))
    if (
        profile != API_DIAGNOSTIC_PROFILE
        or profile_config.get("market_alignment") != "engineering_only"
    ):
        raise RunnerConfigurationError(
            "--api-diagnostic requires the simnow_second_7x24 engineering-only profile"
        )
    if mode != "shadow":
        raise RunnerConfigurationError("--api-diagnostic is a shadow observation only")
    if purpose != "observation":
        raise RunnerConfigurationError("--api-diagnostic requires purpose=observation")
    if receipt is not None:
        raise RunnerConfigurationError("--api-diagnostic never consumes an admission receipt")
    if not math.isfinite(float(run_seconds)) or float(run_seconds) != 0:
        raise RunnerConfigurationError("--api-diagnostic does not consume run duration")


def _api_diagnostic_reference_scope(config: Mapping[str, Any]) -> dict[str, str | None]:
    """Return the bounded reference-data scope for the Set-2 diagnostic.

    Set-2 is an engineering-only session.  It must prove the public
    instruments query without issuing an unbounded all-market request, but it
    never selects a concrete contract or begins strategy preflight.
    """

    selection = _mapping(config.get("contract_selection"))
    product_id = str(selection.get("product") or "").strip().upper()
    exchange_id = str(selection.get("exchange") or "").strip().upper()
    if not product_id or not exchange_id:
        raise RunnerConfigurationError(
            "--api-diagnostic requires a bounded contract_selection product and exchange"
        )
    return {
        "instrument_id": None,
        "product_id": product_id,
        "exchange_id": exchange_id,
    }


def _write_api_diagnostic_construction_failure(
    *,
    config: Mapping[str, Any],
    output_directory: Path,
    mode: str,
    purpose: str,
    run_id: str,
    failure: BaseException,
) -> None:
    """Persist a credential-safe fail-closed record before a Store exists.

    Reachable-front selection and Store construction happen before credentials
    can be reduced to their account fingerprint.  Keep this fallback payload
    deliberately small: it records the stable exception class and stage, never
    an exception message, endpoint, config body, or environment value.
    """

    evidence_config = _mapping(config.get("evidence"))
    try:
        reporter = EvidenceWriter(
            output_directory,
            secret_values=(),
            min_free_bytes=int(evidence_config["minimum_free_bytes"]),
            rotate_bytes=int(evidence_config["rotate_bytes"]),
            audit_queue_limit=min(
                int(evidence_config["audit_queue_limit"]),
                int(evidence_config["quote_queue_limit"]),
            ),
        )
    except Exception:
        # The original construction error remains authoritative.  This best-
        # effort path must not emit an unsafe raw fallback when the evidence
        # destination itself is unavailable.
        return

    manifest: dict[str, Any] | None = None
    try:
        manifest = reporter.manifest(
            run_id=run_id,
            purpose=purpose,
            mode=mode,
            environment=str(config.get("environment") or ""),
            candidate_id=str(config.get("candidate_id") or ""),
            config_hash=config_hash(config),
            code_hash=code_hash(),
            data_hash="",
            account_id_hash="",
            instrument="",
            trading_day="",
            started_at_utc=datetime.now(timezone.utc).isoformat(),
            fee_source="",
            hypothetical_fills=False,
        )
        manifest.update(
            api_diagnostic_status="FAIL_CLOSED_API_DIAGNOSTIC",
            strategy_status="NOT_RUN",
            g3_gate_status="NOT_RUN_API_DIAGNOSTIC",
            g4_gate_status="NOT_RUN_API_DIAGNOSTIC",
            execution_basis="none",
            failure_stage="live_store_construction",
            failure_code=type(failure).__name__,
            source_components={},
            retention={"status": "NOT_APPLICABLE_API_DIAGNOSTIC"},
        )
        failure_payload = {
            "schema_version": "iter22.ctp-api-diagnostic.v1",
            "status": "FAIL_CLOSED",
            "strategy_status": "NOT_RUN",
            "g3_gate_status": "NOT_RUN_API_DIAGNOSTIC",
            "g4_gate_status": "NOT_RUN_API_DIAGNOSTIC",
            "failure_stage": "live_store_construction",
            "error_code": type(failure).__name__,
            "message": "live_store_construction_failed",
        }
        reporter.write_json("api_diagnostic.json", failure_payload)
        reporter.write_json(
            "preflight.json",
            {
                "status": "FAIL_CLOSED_API_DIAGNOSTIC",
                "strategy_status": "NOT_RUN",
                "failure_stage": "live_store_construction",
            },
        )
        reporter.write_json(
            "contract_selection.json",
            {"status": "NOT_RUN_API_DIAGNOSTIC_NO_CONTRACT"},
        )
        reporter.write_json(
            "reconciliation.json",
            {"status": "NOT_RUN_API_DIAGNOSTIC_NO_EXECUTION"},
        )
        reporter.write_json(
            "daily_report.json",
            {
                "status": "FAIL_CLOSED_API_DIAGNOSTIC",
                "strategy_status": "NOT_RUN",
                "pnl_fields_emitted": False,
            },
        )
    except Exception:
        # Avoid replacing the selector/Store error or serializing it while
        # attempting to report a secondary evidence failure.
        pass
    finally:
        if manifest is not None:
            try:
                reporter.finalize_manifest(manifest, "FAIL_CLOSED")
            except Exception:
                pass
        else:
            try:
                reporter.close()
            except Exception:
                pass


def _network_failure_gate_status(
    failure: BaseException, manifest: Mapping[str, Any]
) -> dict[str, str]:
    """Keep fail-closed network evidence explicit about an unmet gate."""

    default_g3 = str(manifest.get("g3_gate_status") or "NOT_RUN")
    default_g4 = str(manifest.get("g4_gate_status") or "NOT_RUN")
    if isinstance(failure, PreflightError) and str(failure).startswith(
        "BLOCKED_CTP_TRADING_CALENDAR:"
    ):
        return {
            "g3_gate_status": "BLOCKED_CTP_TRADING_CALENDAR",
            "g4_gate_status": "BLOCKED_G3",
        }
    return {"g3_gate_status": default_g3, "g4_gate_status": default_g4}


def run_api_diagnostic(
    config: Mapping[str, Any],
    *,
    mode: str,
    purpose: str,
    receipt: AdmissionReceipt | None,
    output_directory: Path,
    run_seconds: float,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run the narrow Set-2 CTP API/session diagnostic.

    The diagnostic starts the existing managed Store in its default
    ``market_data_only`` state, performs one public query snapshot, and stops.
    It never selects an SA contract, verifies/prepares settlement, subscribes,
    arms execution, or invokes order/cancel APIs.
    """

    _load_env_file(HERE / ".env")
    config = effective_profile_config(config, os.environ)
    _validate_api_diagnostic_invocation(
        config,
        mode=mode,
        purpose=purpose,
        receipt=receipt,
        run_seconds=run_seconds,
    )
    reference_query_scope = _api_diagnostic_reference_scope(config)
    output_directory = _claim_output_directory(output_directory)
    run_id = run_id or _run_id("api-diagnostic")
    evidence_config = _mapping(config["evidence"])
    state_directory = (HERE / str(_mapping(config["evidence"])["state_directory"])).resolve()
    try:
        store, identity, secrets = _build_live_store(
            config,
            os.environ,
            mode="shadow",
            purpose="observation",
            state_directory=state_directory,
            allow_order_writes=False,
        )
    except BaseException as exc:
        _write_api_diagnostic_construction_failure(
            config=config,
            output_directory=output_directory,
            mode=mode,
            purpose=purpose,
            run_id=run_id,
            failure=exc,
        )
        raise
    reporter = EvidenceWriter(
        output_directory,
        secret_values=secrets,
        min_free_bytes=int(evidence_config["minimum_free_bytes"]),
        rotate_bytes=int(evidence_config["rotate_bytes"]),
        audit_queue_limit=min(
            int(evidence_config["audit_queue_limit"]),
            int(evidence_config["quote_queue_limit"]),
        ),
    )
    manifest = reporter.manifest(
        run_id=run_id,
        purpose=purpose,
        mode=mode,
        environment=str(config["environment"]),
        candidate_id=str(config["candidate_id"]),
        config_hash=config_hash(config),
        code_hash=code_hash(),
        data_hash="",
        account_id_hash=identity["account_fingerprint"],
        instrument="",
        trading_day="",
        started_at_utc=datetime.now(timezone.utc).isoformat(),
        fee_source="",
        hypothetical_fills=False,
    )
    manifest.update(
        environment_profile=identity["sdk_profile"],
        profile_basis=identity["profile_basis"],
        market_alignment=identity["market_alignment"],
        source_components=runtime_component_identities(),
        execution_basis="none",
        api_diagnostic_status="PENDING",
        strategy_status="NOT_RUN",
        g3_gate_status="NOT_RUN_API_DIAGNOSTIC",
        g4_gate_status="NOT_RUN_API_DIAGNOSTIC",
        retention={"status": "NOT_APPLICABLE_API_DIAGNOSTIC"},
        research_status=str(_mapping(config.get("research")).get("status") or ""),
    )
    store_start_attempted = False
    failure: BaseException | None = None
    exit_status = "FAIL_CLOSED"
    result: dict[str, Any] | None = None
    try:
        probe = native_probe()
        reporter.write_json("native_probe.json", probe)
        manifest["source_components"]["bt_api_ctp"] = {
            "module": "bt_api_ctp",
            "version": probe.get("bt_api_ctp_version"),
            "path": probe.get("bt_api_ctp_path"),
            "sha256": probe.get("ctp_package_sha256"),
            "package_manifest": probe.get("ctp_package_manifest") or [],
            "package_manifest_verified": probe.get("ctp_package_manifest_verified") is True,
            "native_files": probe.get("native_files") or [],
            "native_loaded": probe.get("native_loaded") is True,
        }
        if not probe.get("accepted"):
            raise PreflightError("CTP native probe did not prove the target extension is loaded")

        # ``start`` can allocate native resources before a later connection or
        # authentication failure.  Treat the call itself as requiring cleanup,
        # rather than only a fully returned start, so the failure path closes
        # the managed Store as well.
        store_start_attempted = True
        store.start()
        snapshot = public_preflight_snapshot(
            store,
            reference_query_scope["instrument_id"],
            product_id=str(reference_query_scope["product_id"]),
            exchange_id=str(reference_query_scope["exchange_id"]),
        )
        diagnostic = validate_api_diagnostic_snapshot(snapshot, identity=identity)
        terminal_session = _mapping(store.get_ctp_session_state())
        _validate_read_only_session(
            {"session": terminal_session}, expected_profile=identity["sdk_profile"]
        )
        if _account_core(terminal_session.get("account_fingerprint")) != _account_core(
            diagnostic["query_identity"]["account_fingerprint"]
        ):
            raise PreflightError("terminal session account fingerprint differs from public queries")
        if (
            str(terminal_session.get("trading_day") or "")
            != diagnostic["query_identity"]["trading_day"]
        ):
            raise PreflightError("terminal session TradingDay differs from public queries")
        if int(terminal_session.get("connection_generation") or 0) != int(
            diagnostic["query_identity"]["connection_generation"]
        ):
            raise PreflightError("terminal session generation differs from public queries")

        api_diagnostic = {
            **diagnostic,
            "mode": mode,
            "purpose": purpose,
            "profile": identity["profile"],
            "sdk_profile": identity["sdk_profile"],
            "market_alignment": identity["market_alignment"],
            "reference_query_scope": reference_query_scope,
            "g3_gate_status": "NOT_RUN_API_DIAGNOSTIC",
            "g4_gate_status": "NOT_RUN_API_DIAGNOSTIC",
            "contract_selection_status": "NOT_RUN_API_DIAGNOSTIC_NO_CONTRACT",
            "reconciliation_status": "NOT_RUN_API_DIAGNOSTIC_NO_EXECUTION",
            "daily_report_status": "NOT_RUN_API_DIAGNOSTIC",
            "execution_basis": "none",
            "pnl_fields_emitted": False,
        }
        shutdown = store.stop()
        store_start_attempted = False
        api_diagnostic["shutdown"] = validate_api_diagnostic_shutdown(shutdown)
        diagnostic_hash = sha256_json(api_diagnostic)
        manifest.update(
            api_diagnostic_status="PASS_API_DIAGNOSTIC",
            api_diagnostic_sha256=diagnostic_hash,
            preflight_sha256=diagnostic["query_snapshot_sha256"],
            trading_day=diagnostic["query_identity"]["trading_day"],
            network_data_identity={
                "provider": "btapi",
                "exchange": CTP_EXCHANGE,
                "account_fingerprint": identity["account_fingerprint"],
                "environment_profile": identity["sdk_profile"],
                "trading_day": diagnostic["query_identity"]["trading_day"],
                "connection_generation": diagnostic["query_identity"]["connection_generation"],
                "query_snapshot_sha256": diagnostic["query_snapshot_sha256"],
                "instrument": None,
            },
        )
        manifest["data_hash"] = sha256_json(manifest["network_data_identity"])
        reporter.write_json("api_diagnostic.json", api_diagnostic)
        reporter.write_json(
            "preflight.json",
            {
                "status": "PASS_API_DIAGNOSTIC",
                "strategy_status": "NOT_RUN",
                "session": diagnostic["session"],
                "query_identity": diagnostic["query_identity"],
                "query_evidence": diagnostic["query_evidence"],
                "query_snapshot_sha256": diagnostic["query_snapshot_sha256"],
                "reference_query_scope": reference_query_scope,
            },
        )
        reporter.write_json(
            "contract_selection.json",
            {
                "status": "NOT_RUN_API_DIAGNOSTIC_NO_CONTRACT",
                "reason": "api diagnostic does not select an SA contract",
            },
        )
        reporter.write_json(
            "reconciliation.json",
            {
                "status": "NOT_RUN_API_DIAGNOSTIC_NO_EXECUTION",
                "complete": False,
                "strategy_status": "NOT_RUN",
            },
        )
        reporter.write_json(
            "daily_report.json",
            {
                "status": "NOT_RUN_API_DIAGNOSTIC",
                "mode": mode,
                "purpose": purpose,
                "strategy_status": "NOT_RUN",
                "pnl_fields_emitted": False,
                "execution_basis": "none",
            },
        )
        result = {
            "run_id": run_id,
            "mode": mode,
            "purpose": purpose,
            "status": "PASS_API_DIAGNOSTIC",
            "strategy_status": "NOT_RUN",
            "g3_gate_status": "NOT_RUN_API_DIAGNOSTIC",
            "g4_gate_status": "NOT_RUN_API_DIAGNOSTIC",
            "account_fingerprint": identity["account_fingerprint"],
            "environment_profile": identity["sdk_profile"],
            "query_snapshot_sha256": diagnostic["query_snapshot_sha256"],
            "request_counts": diagnostic["session"]["request_counts"],
            "request_count_delta": diagnostic["session"]["request_count_delta"],
            "api_diagnostic_sha256": diagnostic_hash,
            "evidence_directory": str(output_directory),
        }
        exit_status = "PASS_API_DIAGNOSTIC"
    except BaseException as exc:
        failure = exc
        manifest.update(
            api_diagnostic_status="FAIL_CLOSED_API_DIAGNOSTIC",
            strategy_status="NOT_RUN",
            g3_gate_status="NOT_RUN_API_DIAGNOSTIC",
            g4_gate_status="NOT_RUN_API_DIAGNOSTIC",
        )
        failure_payload = {
            "schema_version": "iter22.ctp-api-diagnostic.v1",
            "status": "FAIL_CLOSED",
            "strategy_status": "NOT_RUN",
            "g3_gate_status": "NOT_RUN_API_DIAGNOSTIC",
            "g4_gate_status": "NOT_RUN_API_DIAGNOSTIC",
            "error_code": type(exc).__name__,
            "message": str(exc),
        }
        for filename, payload in (
            ("api_diagnostic.json", failure_payload),
            (
                "preflight.json",
                {"status": "FAIL_CLOSED_API_DIAGNOSTIC", "strategy_status": "NOT_RUN"},
            ),
            ("contract_selection.json", {"status": "NOT_RUN_API_DIAGNOSTIC_NO_CONTRACT"}),
            ("reconciliation.json", {"status": "NOT_RUN_API_DIAGNOSTIC_NO_EXECUTION"}),
            (
                "daily_report.json",
                {
                    "status": "FAIL_CLOSED_API_DIAGNOSTIC",
                    "strategy_status": "NOT_RUN",
                    "pnl_fields_emitted": False,
                },
            ),
        ):
            try:
                reporter.write_json(filename, payload)
            except Exception:
                pass
    finally:
        if store_start_attempted:
            try:
                shutdown = store.stop()
                store_start_attempted = False
                if failure is None:
                    validate_api_diagnostic_shutdown(shutdown)
            except BaseException as exc:
                if failure is None:
                    failure = exc
                    exit_status = "FAIL_CLOSED"
        try:
            reporter.finalize_manifest(manifest, exit_status)
        except BaseException as exc:
            if failure is None:
                failure = exc
    if failure is not None:
        raise failure
    if result is None:
        raise RuntimeError("API diagnostic ended without a report")
    return result


def run_network(
    config: Mapping[str, Any],
    *,
    mode: str,
    purpose: str,
    preflight_only: bool,
    prepare_settlement: bool,
    receipt: AdmissionReceipt | None,
    output_directory: Path,
    run_seconds: float,
    maximum_smoke_entry_attempts: int | None = None,
    run_id: str | None = None,
    retention_root: Path | None = None,
) -> dict[str, Any]:
    # API callers do not pass through ``main``.  Load the local trust root
    # before revalidating a signed receipt, and do both before claiming an
    # output directory or constructing a Store.
    _load_env_file(HERE / ".env")
    config = effective_profile_config(config, os.environ)
    if receipt is not None and mode == "simnow" and not preflight_only and not prepare_settlement:
        receipt = _revalidate_admission_receipt(
            receipt,
            config=config,
            mode=mode,
            purpose=purpose,
        )
    maximum_smoke_entry_attempts = _validate_network_invocation(
        config,
        mode=mode,
        purpose=purpose,
        preflight_only=preflight_only,
        prepare_settlement=prepare_settlement,
        receipt=receipt,
        run_seconds=run_seconds,
        maximum_smoke_entry_attempts=maximum_smoke_entry_attempts,
    )
    output_directory = _claim_output_directory(output_directory)
    state_directory = (HERE / str(_mapping(config["evidence"])["state_directory"])).resolve()
    allow_order_writes = bool(
        mode == "simnow"
        and _validated_receipt(receipt)
        and not preflight_only
        and not prepare_settlement
    )
    store, identity, secrets = _build_live_store(
        config,
        os.environ,
        mode=mode,
        purpose=purpose,
        state_directory=state_directory,
        allow_order_writes=allow_order_writes,
    )
    run_id = run_id or _run_id(mode)
    evidence_config = _mapping(config["evidence"])
    reporter = EvidenceWriter(
        output_directory,
        secret_values=secrets,
        min_free_bytes=int(evidence_config["minimum_free_bytes"]),
        rotate_bytes=int(evidence_config["rotate_bytes"]),
        audit_queue_limit=min(
            int(evidence_config["audit_queue_limit"]),
            int(evidence_config["quote_queue_limit"]),
        ),
    )
    started = datetime.now(timezone.utc).isoformat()
    instrument_hint = str((receipt or {}).get("instrument") or config.get("instrument") or "")
    manifest = reporter.manifest(
        run_id=run_id,
        purpose=purpose,
        mode=mode,
        environment=str(config["environment"]),
        candidate_id=str(config["candidate_id"]),
        config_hash=config_hash(config),
        code_hash=code_hash(),
        data_hash="",
        account_id_hash=identity["account_fingerprint"],
        instrument=instrument_hint,
        trading_day="",
        started_at_utc=started,
        fee_source="",
        hypothetical_fills=False,
    )
    manifest.update(
        environment_profile=identity["sdk_profile"],
        profile_basis=identity["profile_basis"],
        market_alignment=identity["market_alignment"],
        admission_receipt_sha256=(
            sha256_file(receipt["_path"]) if receipt and receipt.get("_path") else None
        ),
        source_components=runtime_component_identities(),
        g3_gate_status="NOT_RUN",
        g4_gate_status="NOT_RUN",
        execution_basis=("simnow_native" if allow_order_writes else "none"),
        research_status=str(_mapping(config.get("research")).get("status") or ""),
    )
    store_started = False
    account_lock: AccountLock | None = None
    result: dict[str, Any] | None = None
    broker: BtApiBroker | None = None
    failure: BaseException | None = None
    exit_status = "FAIL_CLOSED"
    try:
        _validate_receipt_runtime_profile(receipt, identity)
        retention = (
            apply_evidence_retention(
                retention_root,
                retain_trading_days=int(evidence_config["retain_trading_days"]),
            )
            if retention_root is not None
            else {
                "status": "NOT_APPLICABLE_EXPLICIT_OUTPUT_DIRECTORY",
                "retain_trading_days": int(evidence_config["retain_trading_days"]),
            }
        )
        manifest["retention"] = retention
        reporter.write_json("retention.json", retention)
        probe = native_probe()
        reporter.write_json("native_probe.json", probe)
        manifest["source_components"]["bt_api_ctp"] = {
            "module": "bt_api_ctp",
            "version": probe.get("bt_api_ctp_version"),
            "path": probe.get("bt_api_ctp_path"),
            "sha256": probe.get("ctp_package_sha256"),
            "package_manifest": probe.get("ctp_package_manifest") or [],
            "package_manifest_verified": probe.get("ctp_package_manifest_verified") is True,
            "native_files": probe.get("native_files") or [],
            "native_loaded": probe.get("native_loaded") is True,
        }
        if not probe.get("accepted"):
            raise PreflightError("CTP native probe did not prove the target extension is loaded")
        if allow_order_writes:
            if receipt.get("source_hashes") != source_file_hashes():
                raise PreflightError("source tree changed after receipt validation")
            if receipt.get("dependency_hashes") != dependency_identity_hashes():
                raise PreflightError("runtime dependencies changed after receipt validation")
            loaded_native_hash = str(
                probe.get("loaded_module_sha256")
                or probe.get("loaded_native_sha256")
                or probe.get("native_loaded_sha256")
                or probe.get("loaded_extension_sha256")
                or ""
            ).lower()
            if not loaded_native_hash and len(probe.get("native_files") or ()) == 1:
                loaded_native_hash = str(probe["native_files"][0].get("sha256") or "").lower()
            if loaded_native_hash != str(receipt.get("native_sha256") or "").lower():
                raise PreflightError("loaded CTP native extension differs from admission receipt")
            if (
                str(probe.get("ctp_package_sha256") or "").lower()
                != str(receipt.get("ctp_package_sha256") or "").lower()
            ):
                raise PreflightError("loaded CTP package differs from admission receipt")

        if not preflight_only and not prepare_settlement:
            # Every full network run loads (and may initialize/roll) the shared
            # daily-risk ledger, including read-only shadow runs.  Serialize
            # the complete session so a shadow process cannot overwrite an
            # admitted writer's counters with an earlier snapshot.
            account_lock = AccountLock(
                state_directory / identity["account_fingerprint"] / "writer.lock"
            )
            account_lock.__enter__()
        store.start()
        store_started = True

        if prepare_settlement:
            initial_verification = establish_read_only_ctp_session(
                store,
                expected_profile=identity["sdk_profile"],
            )
            with AccountLock(state_directory / identity["account_fingerprint"] / "writer.lock"):
                preparation = store.prepare_ctp_settlement(timeout=5.0)
                verification = store.verify_ctp_settlement(timeout=5.0)
            reporter.write_json(
                "settlement_preparation.json",
                {
                    "initial_read_only_verification": initial_verification,
                    "preparation": preparation,
                    "verification": verification,
                },
            )
            if preparation.get("evidence_complete") is not True:
                raise PreflightError("explicit settlement confirmation was not proven")
            if (
                verification.get("evidence_complete") is not True
                or verification.get("read_only_safe") is not True
            ):
                raise PreflightError("settlement confirmation readback was not proven")
            terminal = store.get_ctp_session_state()
            result = {
                "run_id": run_id,
                "mode": mode,
                "purpose": purpose,
                "prepare_settlement": True,
                "status": "PASS_SETTLEMENT_PREPARED",
                "account_fingerprint": identity["account_fingerprint"],
                "environment_profile": identity["sdk_profile"],
                "request_counts": _mapping(terminal.get("request_counts")),
                "g4_gate_status": "NOT_RUN",
                "evidence_directory": str(output_directory),
            }
            reporter.write_json(
                "preflight.json",
                {
                    "status": "NOT_RUN_SETTLEMENT_PREPARATION_ONLY",
                    "preflight_only": False,
                },
            )
            reporter.write_json(
                "contract_selection.json",
                {"status": "NOT_RUN_SETTLEMENT_PREPARATION_ONLY"},
            )
            reporter.write_json(
                "reconciliation.json",
                {
                    "status": "SETTLEMENT_CONFIRMATION_READ_BACK",
                    "complete": verification.get("evidence_complete") is True,
                },
            )
            reporter.write_json(
                "daily_report.json",
                {
                    "mode": mode,
                    "purpose": purpose,
                    "settlement_preparation_only": True,
                    "pnl_fields_emitted": False,
                },
            )
            exit_status = "PASS_SETTLEMENT_PREPARED"
        else:
            settlement_verification = None
            if mode == "simnow":
                settlement_verification = store.verify_ctp_settlement(timeout=5.0)
                reporter.write_json("settlement_verification.json", settlement_verification)
                if (
                    settlement_verification.get("evidence_complete") is not True
                    or settlement_verification.get("read_only_safe") is not True
                ):
                    raise PreflightError(
                        "SimNow settlement is not read-only verified; run --prepare-settlement"
                    )

            # Stage A deliberately omits instrument-specific margin/commission
            # queries. It proves the account and execution state while using
            # the server-side SA product filter to avoid an unbounded global
            # instrument response before freezing one actual SA month.
            contract_exchange = (
                str(_mapping(config.get("contract_selection")).get("exchange") or "")
                .strip()
                .upper()
            )
            if not contract_exchange:
                raise PreflightError(
                    "contract selection exchange is required for scoped trade query"
                )
            snapshot_a = public_preflight_snapshot(
                store,
                None,
                product_id="SA",
                exchange_id=contract_exchange,
            )
            stage_a = validate_stage_a(
                snapshot_a,
                config,
                receipt=receipt,
                expected_account=identity["account_fingerprint"],
                expected_profile=identity["sdk_profile"],
            )
            instrument = stage_a["selection"]["instrument"]

            # Stage B queries fee/margin for the already frozen instrument and
            # rejects any generation/account/TradingDay change between stages.
            snapshot_b = public_preflight_snapshot(
                store,
                instrument,
                exchange_id=contract_exchange,
            )
            preflight = validate_preflight(
                snapshot_b,
                config,
                mode=mode,
                receipt=receipt,
                stage_a=stage_a,
                expected_account=identity["account_fingerprint"],
                expected_profile=identity["sdk_profile"],
                allow_execution_recovery=allow_order_writes,
            )
            preflight["stage_a"] = stage_a
            preflight["settlement_verification"] = settlement_verification
            preflight["environment_identity"] = identity
            preflight_hash_material = dict(preflight)
            preflight["preflight_sha256"] = sha256_json(preflight_hash_material)
            startup_account_observation = {
                **_mapping(preflight["startup_account_observation"]),
                "preflight_sha256": preflight["preflight_sha256"],
            }
            manifest["preflight_sha256"] = preflight["preflight_sha256"]
            manifest["startup_account_observation_sha256"] = sha256_json(
                startup_account_observation
            )
            manifest["instrument_id"] = instrument
            manifest["trading_day"] = preflight["query_identity"]["trading_day"]
            manifest["fee_source"] = preflight["fee"]["source"]
            manifest["network_data_identity"] = {
                "provider": "btapi",
                "exchange": CTP_EXCHANGE,
                "schema_version": "ctp.quote.v2",
                "account_fingerprint": identity["account_fingerprint"],
                "environment_profile": identity["sdk_profile"],
                "trading_day": preflight["query_identity"]["trading_day"],
                "connection_generation": preflight["query_identity"]["connection_generation"],
                "instrument": instrument,
                "native_sha256": (
                    (receipt or {}).get("native_sha256")
                    or next(
                        (
                            item.get("sha256")
                            for item in probe.get("native_files") or ()
                            if item.get("sha256")
                        ),
                        None,
                    )
                ),
                "ctp_package_sha256": probe.get("ctp_package_sha256"),
            }
            manifest["data_hash"] = sha256_json(manifest["network_data_identity"])

            # Subscription occurs only after static identity, metadata, fee and
            # margin checks have succeeded.  Daily limits remain dynamic and
            # must still arrive on a current ctp.quote.v2 event before entry.
            store.subscribe(instrument)
            preflight["subscription_requested"] = True
            preflight["daily_price_limits_source"] = "current_ctp_quote_v2"
            reporter.write_json("preflight.json", preflight)
            reporter.write_json("contract_selection.json", preflight["selection"])
            reporter.write_json("startup_account_observation.json", startup_account_observation)

            if preflight_only:
                terminal = store.get_ctp_session_state()
                observation = _observation_evidence({}, terminal, identity, preflight_only=True)
                result = {
                    "run_id": run_id,
                    "mode": mode,
                    "purpose": purpose,
                    "preflight_only": True,
                    "preflight_status": "PASS",
                    "orders_submitted": 0,
                    "cancels_submitted": 0,
                    "settlement_confirm_submitted": 0,
                    "account_fingerprint": identity["account_fingerprint"],
                    "instrument": instrument,
                    "observation_evidence": observation,
                    "g4_gate_status": "NOT_RUN",
                    "evidence_directory": str(output_directory),
                }
                reporter.write_json(
                    "reconciliation.json",
                    {
                        "status": "READ_ONLY_PREFLIGHT",
                        "complete": True,
                        "query_identity": preflight["query_identity"],
                    },
                )
                reporter.write_json(
                    "daily_report.json",
                    {
                        "mode": mode,
                        "preflight_only": True,
                        "account_fingerprint": identity["account_fingerprint"],
                        "instrument": instrument,
                        "trading_day": preflight["query_identity"]["trading_day"],
                        "pnl_fields_emitted": False,
                        "observation_evidence": observation,
                    },
                )
                exit_status = "PASS_PREFLIGHT"
            else:
                trading_day = str(preflight["session"].get("trading_day") or "")
                if not trading_day:
                    raise PreflightError("session TradingDay is missing")
                risk_path = state_directory / identity["account_fingerprint"] / "daily-risk.json"
                risk_store = DailyRiskStore(risk_path)
                risk_record = risk_store.load_or_create(
                    account_fingerprint=identity["account_fingerprint"],
                    trading_day=trading_day,
                    starting_equity=float(preflight["account"]["equity"]),
                    reconciliation_complete=True,
                )
                maximum_entry_attempts = int(_mapping(config["risk"])["maximum_entry_attempts"])
                entry_budget_key = "all"
                if purpose == "engineering_smoke" and not preflight.get("recovery_required"):
                    requested = int(maximum_smoke_entry_attempts)
                    receipt_remaining = int((receipt or {}).get("remaining_smoke_attempts", 0))
                    global_remaining = max(2 - int(risk_record.smoke_entry_attempts), 0)
                    run_allowance = min(requested, receipt_remaining, global_remaining)
                    if run_allowance <= 0:
                        raise PreflightError("engineering smoke entry-attempt budget is exhausted")
                    maximum_entry_attempts = int(risk_record.smoke_entry_attempts) + run_allowance
                    entry_budget_key = "engineering_smoke"

                execution_recovery = None
                recovery_outcome = None
                if allow_order_writes:
                    receipt = _revalidate_admission_receipt(
                        receipt,
                        config=config,
                        mode=mode,
                        purpose=purpose,
                    )
                    _assert_receipt_current(receipt)
                    authorization_grant = _build_execution_authorization_grant(
                        receipt=receipt,
                        stage_a_snapshot=snapshot_a,
                        stage_a=stage_a,
                        stage_b_snapshot=snapshot_b,
                        preflight=preflight,
                        environment_profile=identity["sdk_profile"],
                    )
                    configure_authorization = getattr(
                        store, "configure_ctp_execution_authorization", None
                    )
                    if not callable(configure_authorization):
                        raise PreflightError(
                            "public CTP execution authorization capability is unavailable"
                        )
                    authorization_result = configure_authorization(authorization_grant)
                    authorization_sha256 = sha256_json(authorization_grant)
                    if not isinstance(authorization_result, Mapping) or not (
                        authorization_result.get("configured") is True
                        and authorization_result.get("market_data_only") is True
                        and authorization_result.get("grant_sha256") == authorization_sha256
                    ):
                        raise PreflightError(
                            "Store rejected the signed CTP execution authorization"
                        )
                    arming_proof = {
                        "account_fingerprint": identity["account_fingerprint"],
                        "trading_day": trading_day,
                        "instrument": f"CZCE.{instrument}",
                        "connection_generation": preflight["query_identity"][
                            "connection_generation"
                        ],
                        "environment_profile": identity["sdk_profile"],
                        "receipt_sha256": receipt.get("_receipt_sha256"),
                        "native_sha256": receipt.get("native_sha256"),
                        "ctp_package_sha256": receipt.get("ctp_package_sha256"),
                        "source_hashes_sha256": sha256_json(receipt.get("source_hashes")),
                        "dependency_hashes_sha256": sha256_json(receipt.get("dependency_hashes")),
                        "preflight_sha256": preflight["preflight_sha256"],
                    }
                    if set(arming_proof) != ARMING_PROOF_KEYS:
                        raise PreflightError("internal SDK arming proof shape is invalid")
                    expected_arming_hash = sha256_json(arming_proof)
                    manifest["execution_authorization_sha256"] = authorization_sha256
                    manifest["execution_arming_sha256"] = expected_arming_hash

                    if preflight.get("recovery_required") is True:
                        recovery_outcome = _orchestrate_execution_recovery(
                            store,
                            arming_proof,
                            command_timeout=float(
                                _mapping(config["risk"])["drain_timeout_seconds"]
                            ),
                        )

                        def persist_recovery(value: Mapping[str, Any]) -> None:
                            evidence = {
                                "history": list(value.get("history") or ()),
                                "write_actions": dict(value.get("write_actions") or {}),
                                "armed_for_close": value.get("armed_for_close") is True,
                                "monitor_active": value.get("monitor_active") is True,
                                "monitor_iterations": int(value.get("monitor_iterations") or 0),
                                "monitor_exit": value.get("monitor_exit"),
                                "operator_takeover": _mapping(value.get("operator_takeover"))
                                or None,
                                "forced_termination_reason": value.get("forced_termination_reason"),
                            }
                            preflight["execution_recovery"] = evidence
                            reporter.write_json("execution_recovery.json", evidence)

                        persist_recovery(recovery_outcome)
                        reporter.write_json(
                            "execution_arm_proof.json",
                            {
                                "proof": arming_proof,
                                "proof_sha256": expected_arming_hash,
                                "authorization_grant_sha256": authorization_sha256,
                                "mode": "recovery_only",
                                "recovery_history": list(recovery_outcome["history"]),
                            },
                        )
                        if recovery_outcome["armed_for_close"] is not True:
                            if not _flat_recovery_completion_proven(
                                _mapping(recovery_outcome.get("plan")),
                                _mapping(recovery_outcome.get("completion")),
                            ):
                                monitor_stop = {"reason": None}

                                def request_monitor_stop(reason: str) -> None:
                                    if monitor_stop["reason"] is None:
                                        monitor_stop["reason"] = reason

                                previous_sigint = signal.getsignal(signal.SIGINT)
                                previous_sigterm = signal.getsignal(signal.SIGTERM)
                                signal.signal(
                                    signal.SIGINT,
                                    lambda *_args: request_monitor_stop("operator_sigint"),
                                )
                                signal.signal(
                                    signal.SIGTERM,
                                    lambda *_args: request_monitor_stop("operator_sigterm"),
                                )
                                try:
                                    recovery_outcome = _monitor_read_only_execution_recovery(
                                        store,
                                        arming_proof,
                                        recovery_outcome,
                                        run_id=run_id,
                                        account_fingerprint=identity["account_fingerprint"],
                                        trading_day=trading_day,
                                        instrument=instrument,
                                        operator_takeover_path=(
                                            output_directory / "operator_takeover.json"
                                        ),
                                        stop_reason=lambda: monitor_stop["reason"],
                                        persist=persist_recovery,
                                        sleep=time.sleep,
                                        poll_interval=RECOVERY_MONITOR_POLL_SECONDS,
                                    )
                                finally:
                                    signal.signal(signal.SIGINT, previous_sigint)
                                    signal.signal(signal.SIGTERM, previous_sigterm)
                            execution_recovery = dict(recovery_outcome["plan"])
                            persist_recovery(recovery_outcome)
                            reporter.write_json(
                                "execution_arm_proof.json",
                                {
                                    "proof": arming_proof,
                                    "proof_sha256": expected_arming_hash,
                                    "authorization_grant_sha256": authorization_sha256,
                                    "mode": "recovery_only",
                                    "recovery_history": list(recovery_outcome["history"]),
                                },
                            )
                            result = _terminal_recovery_result(
                                recovery_outcome,
                                run_id=run_id,
                                identity=identity,
                                instrument=instrument,
                                output_directory=output_directory,
                            )
                            reporter.write_json("preflight.json", preflight)
                            reporter.write_json("reconciliation.json", result)
                            reporter.write_json(
                                "daily_report.json",
                                {
                                    "mode": "simnow",
                                    "purpose": "execution_recovery",
                                    "status": result["state"],
                                    "pnl_fields_emitted": False,
                                    "g4_gate_status": "NOT_RUN",
                                    "actual_closed_cycles": 0,
                                    "execution_recovery": result["execution_recovery"],
                                },
                            )
                            if result["state"] == "STOPPED_FLAT":
                                exit_status = "RECOVERY_STOPPED_FLAT"
                            elif recovery_outcome.get("monitor_exit") == "operator_takeover":
                                exit_status = "RECOVERY_OPERATOR_TAKEOVER"
                            elif recovery_outcome.get("monitor_exit") == "forced_termination":
                                exit_status = "RECOVERY_FORCED_TERMINATION"
                            else:
                                exit_status = "MANUAL_INTERVENTION"
                            return result
                        execution_recovery = dict(recovery_outcome["plan"])
                    else:
                        arm = getattr(store, "arm_sdk_execution", None)
                        if not callable(arm):
                            raise PreflightError(
                                "public atomic SDK execution arming is unavailable"
                            )
                        arm_result = arm(arming_proof)
                        if not isinstance(arm_result, Mapping) or not (
                            arm_result.get("armed") is True
                            and arm_result.get("market_data_only") is False
                            and arm_result.get("proof_sha256") == expected_arming_hash
                        ):
                            raise PreflightError(
                                "SDK execution arming did not prove the bound identity"
                            )
                        preflight["execution_arming"] = {
                            "armed": True,
                            "proof_sha256": expected_arming_hash,
                            "authorization_grant_sha256": authorization_sha256,
                        }
                        reporter.write_json(
                            "execution_arm_proof.json",
                            {
                                "proof": arming_proof,
                                "proof_sha256": expected_arming_hash,
                                "authorization_grant_sha256": authorization_sha256,
                                "preflight_sha256": preflight["preflight_sha256"],
                                "query_request_ids": {
                                    "stage_a": {
                                        name: item.get("request_id")
                                        for name, item in stage_a["query_evidence"].items()
                                    },
                                    "stage_b": {
                                        name: item.get("request_id")
                                        for name, item in preflight["query_evidence"].items()
                                    },
                                },
                                "store_result": dict(arm_result),
                            },
                        )
                    reporter.write_json("preflight.json", preflight)

                broker = BtApiBroker(
                    store=store,
                    provider="btapi",
                    position_mode="dual_side",
                    max_order_size=1,
                    cash_check_enabled=True,
                    sdk_preflight=False,
                    require_complete_ctp_evidence=True,
                    # A shadow session is observation-only.  It may attach to
                    # an account that already has external positions or
                    # orders, but must never cancel, flatten, or otherwise
                    # mutate that account during its controlled shutdown.
                    market_data_only=not allow_order_writes,
                    startup_account_state={
                        key: startup_account_observation.get(key)
                        for key in (
                            "nonzero_position_record_count",
                            "gross_position_lots",
                            "active_orders_count",
                        )
                    },
                    flatten_on_stop=allow_order_writes and execution_recovery is None,
                    execution_recovery=execution_recovery,
                    shutdown_timeout=float(_mapping(config["risk"])["drain_timeout_seconds"]),
                    approval_expires_at_utc=(receipt or {}).get("expires_at_utc"),
                    approval_max_order_count=(receipt or {}).get("maximum_write_requests"),
                )
                cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
                cerebro.setbroker(broker)
                feed_config = dict(_mapping(config["feed"]))
                feed_config.pop("timeframe", None)
                feed = store.getdata(
                    dataname=instrument,
                    timeframe=bt.TimeFrame.Minutes,
                    **feed_config,
                )
                cerebro.adddata(feed, name=instrument)
                _attach_trade_logger(
                    cerebro,
                    output_directory,
                    startup_snapshot_file="startup_cached_positions.yaml",
                    startup_account_observation=startup_account_observation,
                )
                control = RuntimeControl()
                deadline = time.monotonic() + float(run_seconds) if run_seconds > 0 else None
                params = _strategy_params(
                    config,
                    mode=mode,
                    purpose=purpose,
                    instrument=instrument,
                    trading_day=trading_day,
                    metadata=preflight["metadata"],
                    fee=preflight["fee"],
                    risk_store=risk_store,
                    reporter=reporter,
                    control=control,
                    admitted=mode == "simnow" and receipt is not None,
                    preflight_ready=(
                        (
                            preflight["ready_for_simnow"]
                            or preflight.get("ready_for_recovery") is True
                        )
                        if mode == "simnow"
                        else preflight["ready_for_shadow"]
                    ),
                    run_deadline=deadline,
                    connection_generation=preflight["query_identity"]["connection_generation"],
                    account_id_hash=identity["account_fingerprint"],
                    environment_profile=identity["sdk_profile"],
                    maximum_entry_attempts=maximum_entry_attempts,
                    entry_budget_key=entry_budget_key,
                    engineering_trigger=(receipt or {}).get("engineering_trigger"),
                    session_calendar_sha256=(receipt or {}).get("session_calendar_sha256", ""),
                    session_state_provider=store.get_ctp_session_state,
                    execution_recovery=execution_recovery,
                    startup_account_observation=startup_account_observation,
                )
                cerebro.addstrategy(SAMidFrequencyStrategy, **params)
                previous_sigint = signal.getsignal(signal.SIGINT)
                previous_sigterm = signal.getsignal(signal.SIGTERM)
                signal.signal(
                    signal.SIGINT,
                    lambda *_args: control.request_stop("operator_sigint"),
                )
                signal.signal(
                    signal.SIGTERM,
                    lambda *_args: control.request_stop("operator_sigterm"),
                )
                try:
                    strategies = cerebro.run(preload=False, runonce=False)
                finally:
                    signal.signal(signal.SIGINT, previous_sigint)
                    signal.signal(signal.SIGTERM, previous_sigterm)

                result = _final_sa_report(strategies[0])
                shutdown_reader = getattr(broker, "get_shutdown_summary", None)
                shutdown_summary = _mapping(shutdown_reader()) if callable(shutdown_reader) else {}
                manifest["controlled_drain"] = shutdown_summary
                terminal = _mapping(result.get("terminal_session_state"))
                if not terminal:
                    terminal = _mapping(store.get_ctp_session_state())
                observation = _observation_evidence(result, terminal, identity)
                result.update(
                    run_id=run_id,
                    account_fingerprint=identity["account_fingerprint"],
                    environment_profile=identity["sdk_profile"],
                    observation_evidence=observation,
                    broker_shutdown_summary=shutdown_summary,
                    evidence_directory=str(output_directory),
                )
                manifest["observation_evidence"] = observation
                if mode == "shadow":
                    result["g4_gate_status"] = "NOT_RUN"
                    if result.get("orders") or result.get("pnl_fields_emitted") is not False:
                        raise RuntimeError("shadow invariant failed: order or PnL output observed")
                    reporter.write_json(
                        "daily_report.json",
                        {
                            "mode": "shadow",
                            "account_fingerprint": identity["account_fingerprint"],
                            "instrument": instrument,
                            "trading_day": trading_day,
                            "zero_trade_day": True,
                            "fills_forbidden": True,
                            "pnl_fields_emitted": False,
                            "observation_evidence": observation,
                        },
                    )
                    exit_status = (
                        "PASS_SHADOW_G3"
                        if observation["g3_gate_status"] == "PASS"
                        and _shutdown_summary_complete(shutdown_summary)
                        else "INCOMPLETE_SHADOW_OBSERVATION"
                    )
                elif execution_recovery is not None:
                    result, recovery_report = _finalize_recovery_runtime_result(
                        result,
                        recovery_outcome or {},
                    )
                    manifest["g4_gate_status"] = "NOT_RUN"
                    reporter.write_json("execution_recovery.json", recovery_report)
                    reporter.write_json(
                        "daily_report.json",
                        {
                            "mode": "simnow",
                            "purpose": "execution_recovery",
                            "account_fingerprint": identity["account_fingerprint"],
                            "instrument": instrument,
                            "trading_day": trading_day,
                            "gross_pnl": None,
                            "net_pnl_estimated": None,
                            "net_pnl_verified": None,
                            "g4_gate_status": "NOT_RUN",
                            "actual_closed_cycles": 0,
                            "execution_recovery": recovery_report,
                        },
                    )
                    exit_status = (
                        "RECOVERY_STOPPED_FLAT"
                        if recovery_report.get("completed") is True
                        and _report_stopped_flat(result, shutdown_summary)
                        else "MANUAL_INTERVENTION"
                    )
                else:
                    g4 = _g4_evidence(
                        result,
                        purpose=purpose,
                        receipt=receipt,
                        shutdown_summary=shutdown_summary,
                    )
                    result.update(g4)
                    manifest["g4_gate_status"] = g4["g4_gate_status"]
                    reporter.write_json(
                        "daily_report.json",
                        {
                            "mode": "simnow",
                            "purpose": purpose,
                            "account_fingerprint": identity["account_fingerprint"],
                            "instrument": instrument,
                            "trading_day": trading_day,
                            "gross_pnl": result.get("gross_pnl"),
                            "net_pnl_estimated": result.get("net_pnl"),
                            "net_pnl_verified": None,
                            "research_status": str(
                                _mapping(config.get("research")).get("status") or ""
                            ),
                            "observation_evidence": observation,
                            **g4,
                        },
                    )
                    exit_status = (
                        "COMPLETE_STOPPED_FLAT"
                        if _report_stopped_flat(result, shutdown_summary)
                        else "MANUAL_INTERVENTION"
                    )
                reporter.write_json(
                    "reconciliation.json",
                    {
                        "status": result["state"],
                        "position_lots": result["position_lots"],
                        "active_order": result["active_order"],
                        "unknown_intents": result["unknown_intents"],
                        "reconciliation_proofs": result.get("reconciliation_proofs") or [],
                        "g4_gate_status": result.get("g4_gate_status", "NOT_RUN"),
                        "execution_recovery": result.get("execution_recovery"),
                        "broker_shutdown_summary": shutdown_summary,
                        "terminal_session": terminal,
                    },
                )
    except BaseException as exc:
        failure = exc
        gate_status = _network_failure_gate_status(exc, manifest)
        manifest.update(gate_status)
        controlled_drain = {"status": "NOT_STARTED"}
        if broker is not None:
            shutdown_state = getattr(broker, "get_shutdown_state", None)
            if callable(shutdown_state):
                try:
                    controlled_drain = _mapping(shutdown_state())
                except Exception:
                    controlled_drain = {"status": "UNAVAILABLE"}
            if controlled_drain.get("status") == "NOT_STARTED":
                try:
                    controlled_drain = _mapping(broker.stop())
                except Exception as drain_exc:
                    controlled_drain = {
                        "status": "FAIL",
                        "reason": f"controlled_drain_failed:{type(drain_exc).__name__}",
                    }
        manifest["controlled_drain"] = controlled_drain
        safe_failure = {
            "status": "FAIL_CLOSED",
            "error_code": type(exc).__name__,
            "message": str(exc),
            **gate_status,
            "controlled_drain": controlled_drain,
        }
        for filename, payload in (
            ("failure.json", safe_failure),
            (
                "reconciliation.json",
                {
                    "status": "NOT_PROVEN",
                    "position_lots": None,
                    "unknown_intents": None,
                    **gate_status,
                    "failure": safe_failure,
                },
            ),
            (
                "daily_report.json",
                {
                    "mode": mode,
                    "purpose": purpose,
                    "status": "FAIL_CLOSED",
                    "pnl_fields_emitted": False if mode == "shadow" else None,
                    **gate_status,
                },
            ),
        ):
            try:
                reporter.write_json(filename, payload)
            except Exception:
                pass
    finally:
        if store_started:
            try:
                store.stop()
            except BaseException as exc:
                if failure is None:
                    failure = exc
                    exit_status = "MANUAL_INTERVENTION"
        if account_lock is not None:
            try:
                account_lock.__exit__(None, None, None)
            except BaseException as exc:
                if failure is None:
                    failure = exc
                    exit_status = "MANUAL_INTERVENTION"
        try:
            reporter.finalize_manifest(manifest, exit_status)
        except BaseException as exc:
            if failure is None:
                failure = exc
        # A recovery-only terminal result may already be pending as a return
        # value.  Raising from the end of ``finally`` prevents Store shutdown,
        # account-lock release, or evidence sealing failures from being hidden
        # by that pending success result.
        if failure is not None:
            raise failure
    if failure is not None:
        raise failure
    if result is None:
        raise RuntimeError("network run ended without a report")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--mode", choices=MODES, help="default comes from config.yaml (shadow)")
    parser.add_argument("--purpose", choices=PURPOSES, default="observation")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--preflight-only",
        action="store_true",
        help="read-only; never confirms settlement or writes orders",
    )
    actions.add_argument(
        "--prepare-settlement",
        action="store_true",
        help="explicit SimNow settlement confirmation plus read-only verification",
    )
    actions.add_argument(
        "--api-diagnostic",
        action="store_true",
        help="Set-2 read-only CTP API/session query diagnostic; never runs the strategy",
    )
    parser.add_argument(
        "--admission-receipt",
        type=Path,
        help="required for any non-preflight SimNow order path",
    )
    parser.add_argument(
        "--max-smoke-entry-attempts",
        type=int,
        default=None,
        help="new engineering-smoke attempts in this run, clamped by receipt and daily state",
    )
    parser.add_argument(
        "--run-seconds", type=float, default=0.0, help="starts controlled drain after this duration"
    )
    parser.add_argument("--scenario", choices=("no_signal", "trend", "reverse"))
    parser.add_argument("--output-dir", type=Path)
    return parser


def _cli_report_exit_code(report: Mapping[str, Any]) -> int:
    """Return nonzero unless an SDK recovery-only run proved stopped-flat."""

    recovery = _mapping(report.get("execution_recovery"))
    state = str(report.get("state") or "")
    monitor_exit = str(recovery.get("monitor_exit") or "")
    if state in {"MANUAL_INTERVENTION", "RECOVERY_FORCED_TERMINATION"} or monitor_exit in {
        "forced_termination",
        "operator_takeover",
    }:
        return RECOVERY_INCOMPLETE_EXIT_CODE
    recovery_run = bool(
        recovery.get("recovery_only") is True
        or str(report.get("purpose") or "") == "execution_recovery"
    )
    if not recovery_run:
        return 0
    if state == "STOPPED_FLAT" and recovery.get("completed") is True:
        return 0
    return RECOVERY_INCOMPLETE_EXIT_CODE


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _load_env_file(HERE / ".env")
    config, _path = load_config(args.config, env_values=os.environ)
    mode = args.mode or str(config.get("mode", "shadow"))
    if args.scenario is not None and mode != "replay":
        raise RunnerConfigurationError("--scenario is valid only in replay mode")
    if mode == "replay" and args.purpose != "observation":
        raise RunnerConfigurationError("replay does not consume a network trading purpose")
    if mode == "replay" and args.run_seconds != 0:
        raise RunnerConfigurationError("--run-seconds is valid only in a network mode")
    read_only_action = args.preflight_only or args.prepare_settlement or args.api_diagnostic
    if read_only_action and args.run_seconds != 0:
        raise RunnerConfigurationError("read-only/preparation actions do not consume run duration")
    if read_only_action and mode == "replay":
        raise RunnerConfigurationError(
            "--preflight-only/--prepare-settlement/--api-diagnostic require a network mode"
        )
    if args.prepare_settlement and mode != "simnow":
        raise RunnerConfigurationError("--prepare-settlement is valid only in simnow mode")
    if args.admission_receipt and mode != "simnow":
        raise RunnerConfigurationError("--admission-receipt is valid only in simnow mode")
    if args.admission_receipt and read_only_action:
        raise RunnerConfigurationError(
            "admission receipts are not consumed by read-only/preparation actions"
        )
    if (
        mode == "simnow"
        and not args.preflight_only
        and not args.prepare_settlement
        and not args.api_diagnostic
        and args.admission_receipt is None
    ):
        raise RunnerConfigurationError("simnow order mode requires --admission-receipt")
    if mode != "simnow" and args.purpose != "observation" and mode != "replay":
        raise RunnerConfigurationError("network trading purposes are reserved for simnow mode")
    if mode == "simnow" and (args.preflight_only or args.prepare_settlement):
        if args.purpose != "observation":
            raise RunnerConfigurationError(
                "preflight and settlement preparation use purpose=observation"
            )
    elif (
        mode == "simnow"
        and not args.api_diagnostic
        and args.purpose
        not in {
            "engineering_smoke",
            "natural_signal",
        }
    ):
        raise RunnerConfigurationError(
            "SimNow order runs require engineering_smoke or natural_signal purpose"
        )
    if args.api_diagnostic:
        _validate_api_diagnostic_invocation(
            config,
            mode=mode,
            purpose=args.purpose,
            receipt=None,
            run_seconds=args.run_seconds,
        )
    if args.max_smoke_entry_attempts is not None and not 1 <= args.max_smoke_entry_attempts <= 2:
        raise RunnerConfigurationError("--max-smoke-entry-attempts must be one or two")
    if args.max_smoke_entry_attempts is not None and not (
        mode == "simnow" and args.purpose == "engineering_smoke"
    ):
        raise RunnerConfigurationError(
            "--max-smoke-entry-attempts is valid only for SimNow engineering_smoke"
        )
    receipt = None
    if args.admission_receipt is not None:
        receipt = validate_receipt(
            args.admission_receipt,
            config=config,
            mode=mode,
            purpose=args.purpose,
        )
    run_id = _run_id("api-diagnostic" if args.api_diagnostic else mode)
    output_directory = _evidence_directory(config, run_id, args.output_dir)
    retention_root = (
        (HERE / str(_mapping(config["evidence"])["directory"])).resolve()
        if args.output_dir is None
        else None
    )
    if args.api_diagnostic:
        report = run_api_diagnostic(
            config,
            mode=mode,
            purpose=args.purpose,
            receipt=None,
            output_directory=output_directory,
            run_seconds=args.run_seconds,
            run_id=run_id,
        )
    elif mode == "replay":
        scenario = args.scenario or str(_mapping(config["replay"])["scenario"])
        report = run_replay(
            config,
            output_directory=output_directory,
            scenario=scenario,
            run_id=run_id,
            retention_root=retention_root,
        )
    else:
        report = run_network(
            config,
            mode=mode,
            purpose=args.purpose,
            preflight_only=args.preflight_only,
            prepare_settlement=args.prepare_settlement,
            receipt=receipt,
            output_directory=output_directory,
            run_seconds=args.run_seconds,
            maximum_smoke_entry_attempts=args.max_smoke_entry_attempts,
            run_id=run_id,
            retention_root=retention_root,
        )
    print(json.dumps(redact(report), ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return _cli_report_exit_code(report)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        known = isinstance(exc, (RunnerConfigurationError, PreflightError, ValueError))
        secret_values = tuple(
            str(os.environ.get(name) or "")
            for name in (
                "CTP_USER_ID",
                "CTP_PASSWORD",
                "CTP_APP_ID",
                "CTP_AUTH_CODE",
                "SIMNOW_USER_ID",
                "SIMNOW_PASSWORD",
                "SIMNOW_APP_ID",
                "SIMNOW_AUTH_CODE",
                "simnow_user_id",
                "simnow_password",
                "simnow_app_id",
                "simnow_auth_code",
                "ITER22_APPROVAL_HMAC_KEY",
            )
            if os.environ.get(name)
        )
        safe_message = redact(
            str(exc) if known else "run failed closed; inspect redacted evidence",
            secret_values=secret_values,
        )
        payload = {
            "status": "FAIL_CLOSED",
            "error_code": type(exc).__name__,
            "message": safe_message,
        }
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from None

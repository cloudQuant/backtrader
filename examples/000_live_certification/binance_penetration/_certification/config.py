"""Strict configuration and risk authorization for live runs."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from .cases import CASES
from .models import CertificationError, Risk

VENUES = frozenset(
    {
        "okx",
        "binance",
        "bitget",
        "bybit",
        "coinbase",
        "dydx",
        "gateio",
        "htx",
        "hyperliquid",
        "ib_web",
        "mt5",
        "kraken",
        "mexc",
    }
)
_ENV = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")
_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SYMBOL = re.compile(r"^[A-Za-z0-9_:/.-]{1,80}$")


def _strip_package_prefix(value: str) -> str:
    return value[len("bt_api_") :] if value.startswith("bt_api_") else value


def _mapping(value: Any, label: str, keys: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise CertificationError(f"{label} must be a mapping with string keys")
    if keys is not None and (unknown := set(value) - keys):
        raise CertificationError(f"{label} has unknown keys: {sorted(unknown)}")
    return value


def _required(mapping: dict[str, Any], name: str, label: str) -> Any:
    if name not in mapping:
        raise CertificationError(f"{label}.{name} is required")
    return mapping[name]


def _boolean(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise CertificationError(f"{label} must be boolean")
    return value


def _positive_decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise CertificationError(f"{label} must be positive")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise CertificationError(f"{label} must be numeric") from exc
    if not result.is_finite() or result <= 0:
        raise CertificationError(f"{label} must be finite and positive")
    return result


def _env_name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ENV.fullmatch(value):
        raise CertificationError(f"{label} must be an environment-variable name")
    return value


@dataclass(frozen=True)
class Environment:
    name: str
    kind: str


@dataclass(frozen=True)
class BackendConfig:
    kind: str
    target: str | None
    endpoint_env: str | None
    token_env: str | None


@dataclass(frozen=True)
class TopologyConfig:
    """Requested provider route; no reviewed implementation is registered yet."""

    transport: str
    execution: bool
    risk: bool
    monitor: bool


@dataclass(frozen=True)
class Policy:
    allow_write: bool
    allow_dangerous: bool
    allow_production_write: bool
    max_actions: int
    max_quantity: Decimal
    max_notional: Decimal
    allowed_instruments: frozenset[str]
    max_total_actions: int
    max_total_quantity: Decimal
    max_total_notional: Decimal
    max_price_deviation_bps: Decimal
    notional_currency: str

    def authorize(self, risk: Risk, environment: Environment, grants: Grants) -> None:
        if risk == Risk.READ:
            return
        if not (self.allow_write and grants.allow_write):
            raise CertificationError("write action needs config and CLI --allow-write")
        if risk == Risk.DANGEROUS and not (self.allow_dangerous and grants.allow_dangerous):
            raise CertificationError("dangerous action needs config and CLI authorization")
        if environment.kind == "production" and not (
            self.allow_production_write and grants.allow_production_write
        ):
            raise CertificationError("production write needs config and CLI authorization")


@dataclass(frozen=True)
class Grants:
    allow_write: bool = False
    allow_dangerous: bool = False
    allow_production_write: bool = False
    confirm: str | None = None


@dataclass(frozen=True)
class CaseConfig:
    enabled: bool
    params: dict[str, Any]


@dataclass(frozen=True)
class Config:
    venue: str
    environment: Environment
    backend: BackendConfig
    policy: Policy
    cases: dict[str, CaseConfig]
    credentials: dict[str, str]
    topology: TopologyConfig | None = None

    def confirmation_phrase(self, risk: Risk) -> str:
        level = "DANGEROUS" if risk == Risk.DANGEROUS else "WRITE"
        if self.environment.kind == "production":
            level = "PRODUCTION_" + level
        return f"{self.venue}:{self.environment.name}:{level}"

    def resolve_credentials(self) -> dict[str, str]:
        resolved = {}
        for key, env_name in self.credentials.items():
            value = os.environ.get(env_name)
            if not value:
                raise CertificationError(
                    f"required credential environment variable {env_name} is empty"
                )
            resolved[key] = value
        return resolved


def _validate_params(case_id: str, params: Any, policy: Policy, enabled: bool) -> dict[str, Any]:
    spec = CASES[case_id]
    data = _mapping(params, f"cases.{case_id}.params", set(spec.required + spec.optional))
    missing = set(spec.required) - set(data)
    if missing and enabled:
        raise CertificationError(f"cases.{case_id} missing parameters: {sorted(missing)}")
    validated = dict(data)
    for key, value in data.items():
        if key in {
            "symbol",
            "side",
            "order_type",
            "position_id",
            "external_ref",
            "remote_id",
            "reason_code",
            "source_request_id",
            "source_session_id",
            "new_session_id",
            "evidence_window_id",
            "operator_ref",
            "authorization_ref",
            "restriction_ref",
            "restoration_ref",
            "strategy_ref",
            "trace_ref",
            "order_ref",
            "trade_ref",
            "rule_ref",
            "config_snapshot_id",
            "position_snapshot_id",
            "order_snapshot_id",
        }:
            if not isinstance(value, str) or not _SYMBOL.fullmatch(value):
                raise CertificationError(f"cases.{case_id}.params.{key} must be a short identifier")
        elif key in {"quantity", "price"}:
            validated[key] = str(_positive_decimal(value, f"cases.{case_id}.params.{key}"))
        elif key in {"order_count", "repeat_count"}:
            minimum = 3 if case_id == "TH06" else 2
            if type(value) is not int or not minimum <= value <= 5:
                raise CertificationError(f"cases.{case_id}.params.{key} must be in {minimum}..5")
        elif key in {"expected_threshold", "baseline_count", "window_seconds"}:
            if type(value) is not int or value < 0 or value > 10000:
                raise CertificationError(f"cases.{case_id}.params.{key} must be a bounded integer")
        elif key == "reduce_only":
            validated[key] = _boolean(value, f"cases.{case_id}.params.reduce_only")
    if "side" in validated and validated["side"].lower() not in {"buy", "sell"}:
        raise CertificationError(f"cases.{case_id}.params.side must be buy or sell")
    if "side" in validated:
        validated["side"] = validated["side"].lower()
    if "symbol" in validated and validated["symbol"] not in policy.allowed_instruments:
        raise CertificationError(f"cases.{case_id}.params.symbol is not in allowed_instruments")
    if "price" in validated:
        order_type = validated.get("order_type", "limit")
        if not isinstance(order_type, str) or order_type.lower() != "limit":
            raise CertificationError(f"cases.{case_id}.params.order_type must be limit")
        validated["order_type"] = "limit"
    if "quantity" in validated:
        quantity = Decimal(validated["quantity"])
        if quantity > policy.max_quantity:
            raise CertificationError(f"cases.{case_id} exceeds max_quantity")
    expected = {"TH01": 5, "TH02": 2, "TH03": 10, "TH04": 3, "TH05": 3, "TH06": 2}
    if case_id in expected and enabled and validated["expected_threshold"] != expected[case_id]:
        raise CertificationError(f"cases.{case_id} expected_threshold must be {expected[case_id]}")
    if case_id == "TH05" and enabled and validated["window_seconds"] != 60:
        raise CertificationError("TH05 window_seconds must be 60")
    if case_id in {"TH02", "TH04"} and enabled and validated["repeat_count"] != 2:
        raise CertificationError(f"{case_id} repeat_count must be 2")
    if case_id in {"TH02", "TH04", "TH06"} and enabled:
        increments = 4 if case_id == "TH04" else validated["repeat_count"]
        if (
            not validated["baseline_count"]
            < expected[case_id]
            <= validated["baseline_count"] + increments
        ):
            raise CertificationError(f"{case_id} baseline/repeat does not cross threshold")
    if case_id in {"T02", "O02"} and enabled and validated.get("reduce_only") is not True:
        raise CertificationError(f"{case_id} requires reduce_only")
    return validated


def load_config(path: str | Path, expected_venue: str) -> Config:
    expected_venue = _strip_package_prefix(expected_venue)
    if expected_venue not in VENUES:
        raise CertificationError(f"unsupported venue: {expected_venue}")
    with Path(path).open("r", encoding="utf-8") as stream:
        raw = yaml.safe_load(stream)
    root = _mapping(
        raw,
        "config",
        {
            "schema_version",
            "venue",
            "environment",
            "backend",
            "policy",
            "cases",
            "credentials",
            "defaults",
            "topology",
        },
    )
    if type(_required(root, "schema_version", "config")) is not int or root["schema_version"] != 2:
        raise CertificationError("schema_version must be 2")
    venue = _required(root, "venue", "config")
    if isinstance(venue, str):
        venue = _strip_package_prefix(venue)
    if venue != expected_venue:
        raise CertificationError("config venue does not match CLI venue")
    env = _mapping(_required(root, "environment", "config"), "environment", {"name", "kind"})
    name, kind = _required(env, "name", "environment"), _required(env, "kind", "environment")
    if (
        not isinstance(name, str)
        or not _NAME.fullmatch(name)
        or kind not in {"sandbox", "production"}
    ):
        raise CertificationError("environment needs a valid name and sandbox|production kind")
    environment = Environment(name, kind)
    topology = None
    if "topology" in root:
        route = _mapping(
            root["topology"], "topology", {"transport", "execution", "risk", "monitor"}
        )
        transport = _required(route, "transport", "topology")
        if not isinstance(transport, str) or transport not in {"direct", "gateway_zmq"}:
            raise CertificationError("topology.transport must be direct or gateway_zmq")
        topology = TopologyConfig(
            transport,
            *(
                _boolean(_required(route, name, "topology"), f"topology.{name}")
                for name in ("execution", "risk", "monitor")
            ),
        )
    backend_data = _mapping(
        _required(root, "backend", "config"),
        "backend",
        {"kind", "target", "endpoint_env", "token_env"},
    )
    backend_kind = _required(backend_data, "kind", "backend")
    if backend_kind == "python_factory":
        target = _required(backend_data, "target", "backend")
        if not isinstance(target, str) or not re.fullmatch(
            r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", target
        ):
            raise CertificationError("backend.target must be module:function")
        if set(backend_data) - {"kind", "target"}:
            raise CertificationError("python_factory accepts only target")
        backend = BackendConfig(backend_kind, target, None, None)
    elif backend_kind == "http_json":
        if set(backend_data) - {"kind", "endpoint_env", "token_env"}:
            raise CertificationError("http_json accepts only endpoint_env and token_env")
        backend = BackendConfig(
            backend_kind,
            None,
            _env_name(_required(backend_data, "endpoint_env", "backend"), "backend.endpoint_env"),
            _env_name(backend_data["token_env"], "backend.token_env")
            if "token_env" in backend_data
            else None,
        )
    else:
        raise CertificationError("backend.kind must be python_factory or http_json")
    limits = _mapping(
        _required(root, "policy", "config"),
        "policy",
        {
            "allow_write",
            "allow_dangerous",
            "allow_production_write",
            "max_actions",
            "max_quantity",
            "max_notional",
            "allowed_instruments",
            "max_total_actions",
            "max_total_quantity",
            "max_total_notional",
            "max_price_deviation_bps",
            "notional_currency",
        },
    )
    max_actions = _required(limits, "max_actions", "policy")
    if type(max_actions) is not int or not 1 <= max_actions <= 100:
        raise CertificationError("policy.max_actions must be an integer in 1..100")
    max_total_actions = _required(limits, "max_total_actions", "policy")
    if type(max_total_actions) is not int or not 1 <= max_total_actions <= 1000:
        raise CertificationError("policy.max_total_actions must be an integer in 1..1000")
    instruments = _required(limits, "allowed_instruments", "policy")
    if (
        not isinstance(instruments, list)
        or not instruments
        or any(not isinstance(item, str) or not _SYMBOL.fullmatch(item) for item in instruments)
        or len(set(instruments)) != len(instruments)
    ):
        raise CertificationError("policy.allowed_instruments must list unique instrument names")
    deviation = _required(limits, "max_price_deviation_bps", "policy")
    if isinstance(deviation, bool) or not isinstance(deviation, (str, int, float)):
        raise CertificationError("policy.max_price_deviation_bps must be numeric")
    try:
        deviation_decimal = Decimal(str(deviation))
    except InvalidOperation as exc:
        raise CertificationError("policy.max_price_deviation_bps must be numeric") from exc
    if not deviation_decimal.is_finite() or not 0 <= deviation_decimal <= 10000:
        raise CertificationError("policy.max_price_deviation_bps must be in 0..10000")
    policy = Policy(
        _boolean(_required(limits, "allow_write", "policy"), "policy.allow_write"),
        _boolean(_required(limits, "allow_dangerous", "policy"), "policy.allow_dangerous"),
        _boolean(
            _required(limits, "allow_production_write", "policy"), "policy.allow_production_write"
        ),
        max_actions,
        _positive_decimal(_required(limits, "max_quantity", "policy"), "policy.max_quantity"),
        _positive_decimal(_required(limits, "max_notional", "policy"), "policy.max_notional"),
        frozenset(instruments),
        max_total_actions,
        _positive_decimal(
            _required(limits, "max_total_quantity", "policy"), "policy.max_total_quantity"
        ),
        _positive_decimal(
            _required(limits, "max_total_notional", "policy"), "policy.max_total_notional"
        ),
        deviation_decimal,
        _required(limits, "notional_currency", "policy"),
    )
    if not isinstance(policy.notional_currency, str) or not re.fullmatch(
        r"[A-Z0-9]{2,16}", policy.notional_currency
    ):
        raise CertificationError("policy.notional_currency must be a currency code")
    configured = _mapping(_required(root, "cases", "config"), "cases")
    if not configured:
        raise CertificationError("cases must select at least one live case")
    unknown = set(configured) - set(CASES)
    if unknown:
        raise CertificationError(f"unknown case IDs: {sorted(unknown)}")
    defaults = _mapping(root.get("defaults", {}), "defaults", {"params"})
    default_params = _mapping(
        defaults.get("params", {}),
        "defaults.params",
        set().union(*(set(s.required + s.optional) for s in CASES.values())),
    )
    cases = {}
    for case_id, case_data in configured.items():
        item = _mapping(case_data, f"cases.{case_id}", {"params", "enabled"})
        enabled = _boolean(item.get("enabled", True), f"cases.{case_id}.enabled")
        overrides = _mapping(item.get("params", {}), f"cases.{case_id}.params")
        applicable = set(CASES[case_id].required + CASES[case_id].optional)
        merged = {key: value for key, value in default_params.items() if key in applicable}
        merged.update(overrides)
        cases[case_id] = CaseConfig(enabled, _validate_params(case_id, merged, policy, enabled))
    credential_refs = _mapping(root.get("credentials", {}), "credentials")
    credentials = {}
    for key, value in credential_refs.items():
        if not _NAME.fullmatch(key):
            raise CertificationError("credential names must be simple lowercase identifiers")
        credentials[key] = _env_name(value, f"credentials.{key}")
    if "account" not in credentials:
        raise CertificationError("credentials.account environment-variable reference is required")
    return Config(venue, environment, backend, policy, cases, credentials, topology)

#!/usr/bin/env python
"""013_3 standard entry — dry self-check / offline replay / SimNow live run.

Usage (any interpreter; the live CTP path requires CPython 3.11, e.g.
``C:/anaconda3/python.exe``):

    python run.py                       # dry: config + credential env NAMES only
    python run.py --replay              # offline frozen-fixture replay (0 network, 0 writes)
    python run.py --live --allow-write  # real SimNow simulation account, bounded round trip
    python run.py --live --allow-write --drill --drill-side long   # engineering drill window

Exit codes: 0 PASS, 1 FAIL, 2 BLOCKED, 3 UNKNOWN.

Live execution goes through the SDK narrow registered-sim admission
(``simnow_direct``); the stock Store/managed/production write routes remain
closed.  Evidence is written under ``evidence/<run_id>/`` (git-ignored).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import signal
import sys
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
CHECKOUT_ROOT = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DRILL_SESSIONS = (("00:00", "23:59"),)
EXIT_PASS, EXIT_FAIL, EXIT_BLOCKED, EXIT_UNKNOWN = 0, 1, 2, 3


class LiveRejected(RuntimeError):
    """Bounded live-path rejection carrying a reason and value-free details."""

    def __init__(self, reason: str, details: Optional[Mapping[str, Any]] = None, exit_code: int = EXIT_BLOCKED):
        super().__init__(reason)
        self.reason = str(reason)
        self.details = dict(details or {})
        self.exit_code = int(exit_code)


def _json_print(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def _utc_iso(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(float(epoch), datetime.timezone.utc).isoformat()


def _resolve_ref(value: Any, env: Mapping[str, str], *, field: str) -> str:
    """Resolve a literal or ``{env: NAME}`` reference; never print values."""
    if isinstance(value, Mapping):
        name = str(value.get("env") or "").strip()
        if not name:
            raise LiveRejected("credential_ref_missing_name", {"field": field})
        resolved = str(env.get(name, "") or "").strip()
        if not resolved:
            raise LiveRejected("credential_env_missing", {"field": field, "env_name": name})
        return resolved
    text = str(value or "").strip()
    if not text:
        raise LiveRejected("config_value_missing", {"field": field})
    return text


def _load_env() -> Dict[str, str]:
    """Load the checkout-root .env values by name (values never echoed)."""
    import legacy_runner

    env_path = CHECKOUT_ROOT / ".env"
    legacy_runner._load_env_file(env_path)
    return dict(os.environ)


NEW_SECTIONS = frozenset(
    {
        "schema_version",
        "venue",
        "credentials",
        "live_contract",
        "fronts",
        "live_market_data",
        "policy",
        "timeouts",
        "drill",
    }
)


def _ensure_dev_sdk_path(*, strict: bool = False) -> None:
    """Prefer the dev bt_api_py source tree over any installed copy.

    Mirrors the certification-suite provenance rule: the native CTP path is
    exercised against the reviewed dev source (``BT_API_PY_ROOT``, default
    ``D:/bt_api_py``), never a stale site-packages copy.  In ``strict`` mode a
    resolved-but-wrong origin fails closed before any session exists.
    """
    import importlib.util

    root = Path(os.environ.get("BT_API_PY_ROOT") or "D:/bt_api_py").expanduser()
    # Only the base and CTP source trees are added: the facade package
    # directory also ships a ``backtrader`` integration shim and must never
    # shadow the real framework package.
    candidates = (
        root / "bt_api" / "bt_api_base" / "src",
        root / "bt_api" / "bt_api_ctp" / "src",
    )
    for extra in reversed(candidates):
        if not extra.is_dir():
            continue
        text = str(extra)
        if text in sys.path:
            sys.path.remove(text)
        sys.path.insert(0, text)
    if not strict:
        return
    root_text = str(root).replace("\\", "/").lower()
    loaded = sys.modules.get("bt_api_ctp")
    if loaded is not None:
        origin = getattr(loaded, "__file__", "") or ""
        if root_text not in str(origin).replace("\\", "/").lower():
            raise LiveRejected("sdk_origin_not_dev_source", {"module": "bt_api_ctp"})
        return
    spec = importlib.util.find_spec("bt_api_ctp")
    origin = getattr(spec, "origin", None)
    if origin is None or root_text not in str(origin).replace("\\", "/").lower():
        raise LiveRejected("sdk_origin_not_dev_source", {"module": "bt_api_ctp", "found": origin is not None})


def _load_config() -> Tuple[Dict[str, Any], Dict[str, Any], Path]:
    """Load the full config and a sanitized view for the frozen legacy validator.

    The frozen legacy validator forbids any key containing credential-like
    substrings anywhere in its input.  The iteration-42 sections name credential
    environment variables, so the validator only ever sees the sanitized view;
    the new sections are validated separately by ``_new_section_errors``.
    """
    import yaml

    import legacy_runner

    path = legacy_runner.DEFAULT_CONFIG
    if not path.is_file():
        raise legacy_runner.RunnerConfigurationError(f"config does not exist: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise legacy_runner.RunnerConfigurationError("config root must be a mapping")
    legacy = {key: deepcopy(value) for key, value in raw.items() if key not in NEW_SECTIONS}
    legacy_runner.validate_config(legacy)
    return raw, legacy, path.resolve()


def _new_section_errors(config: Mapping[str, Any]) -> list:
    errors = []
    if int(config.get("schema_version") or 0) != 2:
        errors.append("schema_version_must_be_2")
    if str(config.get("venue") or "") != "simnow":
        errors.append("venue_must_be_simnow")
    credentials = config.get("credentials")
    if not isinstance(credentials, Mapping) or not credentials:
        errors.append("credentials_section_missing")
    else:
        for key, value in credentials.items():
            if not key.endswith("_env") or not isinstance(value, str) or not value.strip():
                errors.append(f"credential_name_invalid:{key}")
    live_contract = config.get("live_contract")
    if not isinstance(live_contract, Mapping) or not live_contract.get("instrument"):
        errors.append("live_contract_instrument_missing")
    if not isinstance(live_contract, Mapping) or not live_contract.get("exchange"):
        errors.append("live_contract_exchange_missing")
    pairs = ((config.get("fronts") or {}) or {}).get("pairs")
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= 8:
        errors.append("fronts_pairs_must_be_1_to_8")
    else:
        for index, item in enumerate(pairs):
            if not isinstance(item, Mapping) or not item.get("td_env") or not item.get("md_env"):
                errors.append(f"front_pair_invalid:{index}")
    policy = config.get("policy")
    if not isinstance(policy, Mapping) or policy.get("allow_write") is not False:
        errors.append("policy_allow_write_must_default_false")
    timeouts = config.get("timeouts")
    if not isinstance(timeouts, Mapping):
        errors.append("timeouts_section_missing")
    return errors


# --------------------------------------------------------------------------- dry
import entry_tier  # noqa: E402  (folder-local copy of examples/_support/entry_tier.py)


def run_dry(tier_evidence: Optional[Mapping[str, Any]] = None) -> int:
    try:
        config, _legacy, config_path = _load_config()
    except Exception as exc:
        _json_print({"status": "REJECTED", "mode": "dry", "error": f"{type(exc).__name__}: {exc}"})
        return EXIT_BLOCKED
    errors = _new_section_errors(config)
    credentials = dict(config.get("credentials") or {})
    report = {
        "tier": dict(tier_evidence or {}),
        "write_grant_result": "not_applicable_offline_tier",
        "status": "DRY",
        "mode": "dry",
        "config_path": config_path.name,
        "strategy_id": "example.013_3.sa_midfreq_simnow",
        "credential_env_names": sorted(str(name) for name in credentials.values()),
        "front_pair_count": len(((config.get("fronts") or {}) or {}).get("pairs") or []),
        "network": 0,
        "provider_sessions": 0,
        "errors": errors,
    }
    if errors:
        report["status"] = "REJECTED"
        _json_print(report)
        return EXIT_BLOCKED
    _json_print(report)
    return EXIT_PASS


# ------------------------------------------------------------------------ replay
def run_replay(
    scenario: Optional[str],
    evidence_dir: Optional[Path],
    tier_evidence: Optional[Mapping[str, Any]] = None,
) -> int:
    import legacy_runner

    try:
        config, legacy_config, _ = _load_config()
    except Exception as exc:
        _json_print({"status": "REJECTED", "mode": "replay", "error": f"{type(exc).__name__}: {exc}"})
        return EXIT_BLOCKED
    replay_config = deepcopy(legacy_config)
    replay_config["mode"] = "replay"
    try:
        legacy_runner.validate_config(replay_config)
    except Exception as exc:
        _json_print({"status": "REJECTED", "mode": "replay", "error": f"{type(exc).__name__}: {exc}"})
        return EXIT_BLOCKED
    chosen_scenario = str(
        scenario or ((config.get("replay") or {}) or {}).get("scenario") or "no_signal"
    )
    run_id = f"replay-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    output_directory = Path(evidence_dir) if evidence_dir else (HERE / "evidence" / run_id)
    # The legacy replay runner claims a fresh directory itself; only the
    # parent must exist.
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = legacy_runner.run_replay(
            replay_config,
            output_directory=output_directory,
            scenario=chosen_scenario,
            retention_root=None,
        )
    except Exception as exc:
        _json_print(
            {
                "status": "REJECTED",
                "mode": "replay",
                "run_id": run_id,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        return EXIT_FAIL
    orders = report.get("orders") or []
    writes = report.get("sdk_write_requests")
    ok = not orders and writes == 0
    summary = {
        "tier": dict(tier_evidence or {}),
        "write_grant_result": "not_applicable_offline_tier",
        "status": "LOCAL_REPLAY_PASS" if ok else "REPLAY_WRITE_DETECTED",
        "mode": "replay",
        "run_id": run_id,
        "scenario": chosen_scenario,
        "evidence_directory": str(output_directory),
        "orders": len(orders),
        "sdk_write_requests": writes,
        "external_request_counts": {"network": 0, "order_write": 0},
        "boundary": "SYNTHETIC_REPLAY_ONLY_NOT_MARKET_OR_PROFITABILITY_EVIDENCE",
    }
    _json_print(summary)
    return EXIT_PASS if ok else EXIT_FAIL


# -------------------------------------------------------------------------- live
def _rows(result: Any) -> list:
    if isinstance(result, Mapping):
        values = result.get("rows")
        if values is None:
            values = result.get("records")
        return [dict(row) if isinstance(row, Mapping) else row for row in (values or [])]
    for attr in ("records", "rows", "data"):
        values = getattr(result, attr, None)
        if isinstance(values, (list, tuple)):
            return [dict(row) if isinstance(row, Mapping) else row for row in values]
    return []


def _row_get(row: Any, *names: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        for name in names:
            if row.get(name) is not None:
                return row[name]
        return default
    for name in names:
        value = getattr(row, name, None)
        if value is not None:
            return value
    return default


_ACTIVE_ORDER_STATUS = {"1", "2", "3", "b", "c", "PARTTRADEDQUEUEING", "NOTTOUCHED", "TOUCHED"}


def _order_is_active(row: Any) -> bool:
    status = str(_row_get(row, "OrderStatus", "order_status", default="") or "")
    if status in {"0", "4", "5", "a"}:
        return False
    remaining = _row_get(row, "VolumeTotal", "volume_total")
    traded = _row_get(row, "VolumeTraded", "volume_traded", default=0)
    try:
        if remaining is not None and float(remaining) - float(traded or 0) <= 0:
            return False
    except (TypeError, ValueError):
        pass
    return bool(status)


def _position_is_open(row: Any) -> bool:
    for name in ("Position", "position", "YdPosition", "TodayPosition"):
        value = _row_get(row, name)
        try:
            if value is not None and float(value) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _live_preflight(store, instrument: str, exchange: str, config: Mapping[str, Any], timeout: float) -> Dict[str, Any]:
    """Bounded read-only preflight; every fact needed for admission and evidence."""
    login = store.registered_sim_login_facts()
    if not (login.get("read_only_ready") or login.get("trading_ready")):
        raise LiveRejected("login_not_read_ready", {"login": login})
    trading_day = str(login.get("trading_day") or "")
    if len(trading_day) != 8 or int(login.get("connection_generation") or 0) <= 0:
        raise LiveRejected("login_facts_invalid", {"trading_day_shape": len(trading_day)})
    account = _rows(store.registered_sim_query("account_result", timeout=timeout))
    positions = _rows(store.registered_sim_query("positions_result", timeout=timeout))
    orders = _rows(store.registered_sim_query("orders_result", timeout=timeout))
    instruments = _rows(
        store.registered_sim_query(
            "instruments_result", timeout=timeout, instrument_id=instrument, exchange_id=exchange
        )
    )
    instrument_row = None
    for row in instruments:
        if str(_row_get(row, "InstrumentID", "instrument_id", default="")).upper() == instrument.upper():
            instrument_row = row
            break
    if instrument_row is None:
        raise LiveRejected("instrument_not_found", {"instrument": instrument, "exchange": exchange})
    price_tick = _row_get(instrument_row, "PriceTick", "price_tick")
    volume_multiple = _row_get(instrument_row, "VolumeMultiple", "volume_multiple")
    lower_limit = _row_get(instrument_row, "LowerLimitPrice", "lower_limit_price")
    upper_limit = _row_get(instrument_row, "UpperLimitPrice", "upper_limit_price")
    open_rows = [row for row in positions if _position_is_open(row)]
    active_orders = [row for row in orders if _order_is_active(row)]
    starting_equity = 0.0
    if account:
        try:
            starting_equity = float(_row_get(account[0], "Balance", "balance", default=0.0) or 0.0)
        except (TypeError, ValueError):
            starting_equity = 0.0
    expectations = dict(config.get("metadata_expectation") or {})
    metadata = {
        "price_tick": float(price_tick) if price_tick not in (None, "") else float(expectations.get("price_tick") or 0),
        "volume_multiple": float(volume_multiple)
        if volume_multiple not in (None, "")
        else float(expectations.get("volume_multiple") or 0),
        "lower_limit": float(lower_limit) if lower_limit not in (None, "") else None,
        "upper_limit": float(upper_limit) if upper_limit not in (None, "") else None,
    }
    if int(metadata["price_tick"]) != int(expectations.get("price_tick", 0)) or int(
        metadata["volume_multiple"]
    ) != int(expectations.get("volume_multiple", 0)):
        raise LiveRejected(
            "instrument_metadata_mismatch",
            {
                "price_tick": metadata["price_tick"],
                "volume_multiple": metadata["volume_multiple"],
                "expected_price_tick": expectations.get("price_tick"),
                "expected_volume_multiple": expectations.get("volume_multiple"),
            },
        )
    fee = _preflight_fee(store, instrument, exchange, config, timeout)
    preflight = {
        "login": login,
        "trading_day": trading_day,
        "account_rows": len(account),
        "positions_open_rows": len(open_rows),
        "orders_active_rows": len(active_orders),
        "starting_equity": starting_equity,
        "metadata": metadata,
        "fee": fee,
    }
    if open_rows or active_orders:
        raise LiveRejected(
            "account_not_clean_for_pilot",
            {
                "positions_open_rows": len(open_rows),
                "orders_active_rows": len(active_orders),
                "pilot_requires_flat_and_no_active_orders": True,
            },
        )
    return preflight


def _preflight_fee(store, instrument: str, exchange: str, config: Mapping[str, Any], timeout: float) -> Dict[str, Any]:
    """Prefer the provider commission-rate readback; conservative fallback otherwise."""
    fallback = dict((((config.get("fee_policy") or {}) or {}).get("replay_fixture") or {}))
    try:
        rates = _rows(
            store.registered_sim_query(
                "instrument_commission_rate_result",
                timeout=timeout,
                instrument_id=instrument,
                exchange_id=exchange,
            )
        )
    except Exception:
        rates = []
    if rates:
        row = rates[0]
        def _rate(name):
            value = _row_get(row, name)
            try:
                return float(value) if value not in (None, "") else 0.0
            except (TypeError, ValueError):
                return 0.0
        return {
            "source": "provider_commission_rate",
            "verified": True,
            "open_money_rate": _rate("OpenRatioByMoney"),
            "open_volume_rate": _rate("OpenRatioByVolume"),
            "close_money_rate": _rate("CloseRatioByMoney"),
            "close_volume_rate": _rate("CloseRatioByVolume"),
            "close_today_money_rate": _rate("CloseTodayRatioByMoney"),
            "close_today_volume_rate": _rate("CloseTodayRatioByVolume"),
            "entry_slip_ticks": int(fallback.get("entry_slip_ticks") or 1),
            "exit_slip_ticks": int(fallback.get("exit_slip_ticks") or 1),
            "edge_buffer_ticks": int(fallback.get("edge_buffer_ticks") or 1),
        }
    return {
        "source": "conservative_fallback",
        "verified": False,
        "open_money_rate": float(fallback.get("open_money_rate") or 0),
        "open_volume_rate": float(fallback.get("open_volume_rate") or 2),
        "close_money_rate": float(fallback.get("close_money_rate") or 0),
        "close_volume_rate": float(fallback.get("close_volume_rate") or 4),
        "close_today_money_rate": float(fallback.get("close_today_money_rate") or 0),
        "close_today_volume_rate": float(fallback.get("close_today_volume_rate") or 4),
        "entry_slip_ticks": int(fallback.get("entry_slip_ticks") or 1),
        "exit_slip_ticks": int(fallback.get("exit_slip_ticks") or 1),
        "edge_buffer_ticks": int(fallback.get("edge_buffer_ticks") or 1),
    }


def run_live(args) -> int:
    if sys.version_info[:2] != (3, 11):
        _json_print(
            {
                "status": "BLOCKED",
                "mode": "live",
                "reason": "live_tier_requires_python_3_11",
                "current": f"{sys.version_info.major}.{sys.version_info.minor}",
                "hint": "run the live tier with the reviewed C:/anaconda3/python.exe (3.11)",
            }
        )
        return EXIT_BLOCKED

    # The dev SDK source paths must precede any bt_api_ctp import: importing
    # simnow_direct eagerly builds the CTP wrapper class, and an installed
    # site-packages bt_api_ctp must never be bound.  The strict origin check
    # below still fails closed if this preload was skipped or defeated.
    _ensure_dev_sdk_path()

    import backtrader as bt

    import legacy_runner
    import simnow_direct
    from backtrader.brokers.btapibroker import BtApiBroker
    from sa_midfreq_strategy import RuntimeControl

    if not args.allow_write:
        _json_print(
            {
                "status": "REJECTED",
                "mode": "live",
                "error": "write_consent_missing",
                "hint": "live SimNow acceptance requires an explicit --allow-write grant",
            }
        )
        return EXIT_BLOCKED
    try:
        config, legacy_config, config_path = _load_config()
    except Exception as exc:
        _json_print({"status": "REJECTED", "mode": "live", "error": f"{type(exc).__name__}: {exc}"})
        return EXIT_BLOCKED
    errors = _new_section_errors(config)
    if errors:
        _json_print({"status": "REJECTED", "mode": "live", "errors": errors})
        return EXIT_BLOCKED
    env = _load_env()
    _ensure_dev_sdk_path(strict=True)
    timeouts = dict(config.get("timeouts") or {})
    policy = dict(config.get("policy") or {})
    run_seconds = float(args.run_seconds or timeouts.get("run_seconds") or 540.0)
    if run_seconds > 3600.0:
        run_seconds = 3600.0
    run_id = (
        f"live-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        f"-{uuid.uuid4().hex[:8]}"
    )
    output_directory = Path(args.evidence_dir) if args.evidence_dir else (HERE / "evidence" / run_id)
    output_directory.mkdir(parents=True, exist_ok=True)
    summary: Dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "example_id": "013_3_sa_midfreq_simnow",
        "mode": "live",
        "status": "STARTING",
        "trigger": "drill" if args.drill else "natural",
        "evidence_directory": str(output_directory),
    }
    started_mono = time.monotonic()
    started_wall = time.time()

    def _write_summary() -> None:
        try:
            (output_directory / "run.json").write_text(
                json.dumps(summary, ensure_ascii=False, sort_keys=True, default=str),
                encoding="utf-8",
            )
        except OSError:
            pass

    store = None
    frozen = False
    try:
        instrument = _resolve_ref(
            (config.get("live_contract") or {}).get("instrument"), env, field="live_contract.instrument"
        )
        exchange = _resolve_ref(
            (config.get("live_contract") or {}).get("exchange"), env, field="live_contract.exchange"
        )
        credentials = {
            "broker_id": _resolve_ref(env.get(str((config.get("credentials") or {}).get("broker_id_env"))), {}, field="broker_id"),
            "user_id": _resolve_ref(env.get(str((config.get("credentials") or {}).get("user_id_env"))), {}, field="user_id"),
            "password": _resolve_ref(env.get(str((config.get("credentials") or {}).get("password_env"))), {}, field="password"),
            "app_id": _resolve_ref(env.get(str((config.get("credentials") or {}).get("app_id_env"))), {}, field="app_id"),
            "auth_code": _resolve_ref(env.get(str((config.get("credentials") or {}).get("auth_code_env"))), {}, field="auth_code"),
        }
        # Non-reversible account fingerprint: the same derivation the frozen
        # risk store and evidence pipeline expect.
        account_fingerprint = legacy_runner.account_fingerprint(
            credentials["broker_id"], credentials["user_id"]
        )
        if not account_fingerprint:
            raise LiveRejected("account_fingerprint_unavailable")
        selection = simnow_direct.select_front_pair(
            ((config.get("fronts") or {}) or {}).get("pairs") or [],
            env,
            samples=3,
            connect_timeout=3.0,
        )
        strategy_path = HERE / "sa_midfreq_strategy.py"
        import hashlib as _hashlib

        config_digest = simnow_direct.canonical_sha256(
            {"config_sha256": _hashlib.sha256(config_path.read_bytes()).hexdigest()}
        )
        identity_sha = simnow_direct.strategy_identity_sha256(strategy_path, config)
        # A new admission never shares another run's gate.  Whole pairs are
        # attempted in ranked order (fresh session per attempt) strictly before
        # any write; the first armable pair wins and every attempt is recorded.
        attempts: list = []
        store = None
        armed = None
        for candidate in selection["ordered_pairs"]:
            attempt_record: Dict[str, Any] = {
                "index": candidate["index"],
                "kind": candidate["kind"],
                "whitelisted": candidate["whitelisted"],
                "score_ms": candidate["score_ms"],
            }
            attempt_store = simnow_direct.RegisteredSimStore(
                provider="ctp",
                backend="direct",
                config={
                    "md_front": candidate["md_front"],
                    "td_front": candidate["td_front"],
                    "broker_id": credentials["broker_id"],
                    "investor_id": credentials["user_id"],
                    "password": credentials["password"],
                    "app_id": credentials["app_id"],
                    "auth_code": credentials["auth_code"],
                    "auto_settlement_confirm": False,
                    "allow_zero_login_response": bool(
                        ((config.get("live_market_data") or {}) or {}).get(
                            "allow_zero_login_response", False
                        )
                    ),
                    # CTP positions are directionally separate; declare the
                    # dual-side ledger capability for this wrapper route.
                    "supports_dual_side": True,
                },
            )
            try:
                attempt_store.start()
                try:
                    ready = attempt_store.registered_sim_wait_ready(
                        timeout=float(timeouts.get("login_seconds") or 30.0)
                    )
                except Exception:
                    ready = False
                login_facts: Dict[str, Any] = {}
                try:
                    login_facts = attempt_store.registered_sim_login_facts()
                except Exception:
                    login_facts = {}
                if not ready or not (
                    login_facts.get("read_only_ready") or login_facts.get("trading_ready")
                ):
                    raise LiveRejected(
                        "login_not_ready", {"login": login_facts, "wait_ready": ready}
                    )
                preflight = _live_preflight(
                    attempt_store,
                    instrument,
                    exchange,
                    config,
                    float(timeouts.get("query_seconds") or 8.0),
                )
                attempt_preflight_sha = simnow_direct.canonical_sha256(
                    {
                        "config_digest": config_digest,
                        "login": preflight["login"],
                        "metadata": preflight["metadata"],
                        "account_rows": preflight["account_rows"],
                        "positions_open_rows": preflight["positions_open_rows"],
                        "orders_active_rows": preflight["orders_active_rows"],
                        "started_utc": _utc_iso(started_wall),
                    }
                )
                arm_result = attempt_store.registered_sim_arm(
                    instrument=instrument,
                    exchange=exchange,
                    md_front=candidate["md_front"],
                    strategy_identity_sha256=identity_sha,
                    execution_cycle_id=run_id,
                    preflight_sha256=attempt_preflight_sha,
                )
                attempt_record["admission"] = "armed"
                attempts.append(attempt_record)
                store = attempt_store
                armed = {
                    "candidate": candidate,
                    "preflight": preflight,
                    "account_fingerprint": account_fingerprint,
                    "preflight_sha": attempt_preflight_sha,
                    "arm_result": arm_result,
                }
                break
            except Exception as exc:
                attempt_record["error"] = f"{type(exc).__name__}: {exc}"
                attempts.append(attempt_record)
                try:
                    attempt_store.registered_sim_disarm("pair_attempt_failed")
                except Exception:
                    pass
                try:
                    attempt_store.stop(timeout=float(timeouts.get("stop_seconds") or 12.0))
                except Exception:
                    pass
                store = None
        summary["admission_attempts"] = attempts
        if armed is None:
            raise LiveRejected("no_admissible_front_pair", {"attempts": attempts})
        armed_candidate = armed["candidate"]
        preflight = armed["preflight"]
        account_fingerprint = armed["account_fingerprint"]
        preflight_sha = armed["preflight_sha"]
        arm_result = armed["arm_result"]
        summary["environment"] = {
            "venue": "simnow",
            "front_selection": selection["receipt"],
            "selected_index": armed_candidate["index"],
            "selected_whitelisted": armed_candidate["whitelisted"],
            "instrument": instrument,
            "exchange": exchange,
            "environment_switched_after_write": False,
        }
        summary["preflight"] = {
            "trading_day": preflight["trading_day"],
            "connection_generation": preflight["login"].get("connection_generation"),
            "account_rows": preflight["account_rows"],
            "starting_equity": preflight["starting_equity"],
            "metadata": preflight["metadata"],
            "fee_source": preflight["fee"]["source"],
            "fee_verified": preflight["fee"]["verified"],
            "pilot_account_flat_and_clean": True,
        }
        summary["admission"] = {
            "admitted": bool(arm_result.get("armed")),
            "instrument": arm_result.get("instrument"),
            "exchange": arm_result.get("exchange_id"),
            "execution_cycle_id": run_id,
            "strategy_identity_sha256": identity_sha,
            "preflight_sha256": preflight_sha,
            "gate_state": arm_result.get("state"),
        }

        # The sealed-bar evidence chain consumes caller-owned tick provenance:
        # without it every live bar is rejected for a missing
        # connection_generation (a 7x24 rehearsal showed 9/9 bars
        # schema-invalid, closed_bars=0), so the drill could never fire.
        # Attach the run-scoped provenance before the feed subscribes.
        live_domain = f"iter42-sa-live-{uuid.uuid4().hex[:12]}"
        live_session_segment = f"czce-sa-live:{preflight['trading_day']}"
        live_generation = int(preflight["login"].get("connection_generation") or 0)
        store.configure_live_tick_provenance(
            {
                "clock_domain_id": live_domain,
                "rules_hash": str(identity_sha or ""),
                "session_segment": live_session_segment,
                "generation": live_generation,
                "source": "iter42:ctp_sa_midfreq:registered-sim",
            }
        )
        summary["live_tick_provenance"] = {
            "domain": live_domain,
            "session_segment": live_session_segment,
            "generation": live_generation,
        }

        purpose = "engineering_smoke" if args.drill else "natural_signal"
        trigger = None
        if args.drill:
            delay = float(args.drill_delay_seconds if args.drill_delay_seconds is not None else 30.0)
            window = float(args.drill_window_seconds if args.drill_window_seconds is not None else 600.0)
            now_wall = time.time()
            trigger = {
                "trigger_id": f"drill-{uuid.uuid4().hex[:8]}",
                "instrument": instrument,
                "trading_day": preflight["trading_day"],
                "minimum_ingest_seq": 0,
                "not_before_utc": _utc_iso(now_wall + delay),
                "not_after_utc": _utc_iso(now_wall + delay + window),
                "side": str(args.drill_side or "long"),
            }
            summary["drill"] = dict(trigger)
        risk_store = legacy_runner.DailyRiskStore(output_directory / "risk.json")
        risk_store.load_or_create(
            account_fingerprint=account_fingerprint,
            trading_day=preflight["trading_day"],
            starting_equity=float(preflight["starting_equity"] or 0.0),
            reconciliation_complete=True,
        )
        writer = legacy_runner.EvidenceWriter(output_directory)
        control = RuntimeControl()
        deadline_mono = started_mono + run_seconds
        params = legacy_runner._strategy_params(
            legacy_config,
            mode="simnow",
            purpose=purpose,
            instrument=instrument,
            trading_day=preflight["trading_day"],
            metadata=preflight["metadata"],
            fee=preflight["fee"],
            risk_store=risk_store,
            reporter=writer,
            control=control,
            admitted=True,
            preflight_ready=True,
            run_deadline=deadline_mono,
            connection_generation=int(preflight["login"].get("connection_generation") or 0),
            account_id_hash=account_fingerprint,
            environment_profile="simnow_registered_sim",
            entry_budget_key="all",
            engineering_trigger=trigger,
        )
        if args.drill:
            params["sessions"] = DRILL_SESSIONS
            params["warmup_bars"] = int(
                args.drill_warmup_bars if args.drill_warmup_bars is not None else 8
            )
        broker = BtApiBroker(
            store=store,
            provider="btapi",
            position_mode="dual_side",
            max_order_size=int(policy.get("max_position_lots") or 1),
            cash_check_enabled=True,
            sdk_preflight=False,
            require_complete_ctp_evidence=True,
            market_data_only=False,
            startup_account_state={
                "nonzero_position_record_count": 0,
                "gross_position_lots": 0,
                "active_orders_count": 0,
            },
            flatten_on_stop=False,
            shutdown_timeout=float(timeouts.get("drain_seconds") or 120.0),
        )
        cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
        cerebro.setbroker(broker)
        feed_config = dict(config.get("feed") or {})
        feed_config.pop("timeframe", None)
        feed = store.getdata(
            dataname=instrument,
            timeframe=bt.TimeFrame.Minutes,
            **feed_config,
        )
        cerebro.adddata(feed, name=instrument)
        legacy_runner._attach_trade_logger(
            cerebro,
            output_directory,
            console=False,
            startup_snapshot_file=None,
            startup_account_observation=None,
        )
        strategy_cls = __import__("sa_midfreq_strategy").SAMidFrequencyStrategy
        cerebro.addstrategy(strategy_cls, **params)

        previous_sigint = signal.getsignal(signal.SIGINT)
        previous_sigterm = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGINT, lambda *_a: control.request_stop("operator_sigint"))
        signal.signal(signal.SIGTERM, lambda *_a: control.request_stop("operator_sigterm"))

        def _strategy_instance():
            runstrats = getattr(cerebro, "runstrats", None) or []
            if runstrats and runstrats[0]:
                return runstrats[0][0]
            return None

        def _idle_pump() -> None:
            # The SA strategy's supervision loop (reconciliation retries,
            # stale-quote timeouts and the bounded drain reconciliation) is
            # driven by notify_idle; live feeds with ticking quotes never
            # trigger it implicitly, so this pump is what lets the drain
            # reach STOPPED_FLAT in-run instead of stalling in RECOVERING.
            # It intentionally ignores ``control.stop_reason``: the duration
            # stop latches there first, and the pump must keep running
            # through the drain grace until the engine itself stops.
            hard_deadline = (
                deadline_mono
                + float(timeouts.get("drain_seconds") or 120.0)
                + 2.0 * float(timeouts.get("stop_seconds") or 12.0)
            )
            while True:
                if time.monotonic() >= hard_deadline:
                    return
                stop_event = getattr(getattr(cerebro, "_event_stop", None), "is_set", None)
                if callable(stop_event) and stop_event():
                    return
                strategy = _strategy_instance()
                if strategy is not None:
                    try:
                        strategy.notify_idle()
                    except Exception:
                        pass
                time.sleep(1.0)

        def _watchdog() -> None:
            while True:
                now = time.monotonic()
                if now >= deadline_mono:
                    control.request_stop("run_duration_elapsed")
                    break
                signal_deadline = started_mono + float(timeouts.get("warmup_seconds") or 90.0) + float(
                    timeouts.get("signal_deadline_seconds") or 300.0
                )
                if not args.drill and now >= signal_deadline:
                    control.request_stop("signal_window_elapsed")
                    break
                time.sleep(0.5)
            # Hard-stop fallback: give the strategy its bounded drain plus a
            # stop-grace, then stop the loop even if it is still working.
            hard_deadline = (
                deadline_mono
                + float(timeouts.get("drain_seconds") or 120.0)
                + 2.0 * float(timeouts.get("stop_seconds") or 12.0)
            )
            while time.monotonic() < hard_deadline:
                if control.stop_reason and getattr(
                    getattr(cerebro, "_event_stop", None), "is_set", lambda: False
                )():
                    return
                time.sleep(1.0)
            try:
                cerebro.runstop()
            except Exception:
                pass

        watchdog = threading.Thread(target=_watchdog, name="sa-run-watchdog", daemon=True)
        idle_thread = threading.Thread(target=_idle_pump, name="sa-run-idle-pump", daemon=True)
        watchdog.start()
        idle_thread.start()
        summary["status"] = "RUNNING"
        _write_summary()
        run_error = None
        try:
            cerebro.run()
        except Exception as exc:  # keep bounded evidence even on loop failure
            run_error = f"{type(exc).__name__}: {exc}"
        finally:
            watchdog.join(timeout=2.0)
            idle_thread.join(timeout=2.0)
            signal.signal(signal.SIGINT, previous_sigint)
            signal.signal(signal.SIGTERM, previous_sigterm)
            control.request_stop("run_finished")

        runstrats = getattr(cerebro, "runstrats", None) or []
        strategy_instance = runstrats[0][0] if runstrats and runstrats[0] else None
        state = str(getattr(strategy_instance, "state", "") or "")
        state_reason = str(getattr(strategy_instance, "state_reason", "") or "")
        strategy_diagnostics: Dict[str, Any] = {}
        if strategy_instance is not None:
            builder = getattr(strategy_instance, "_report_context", None)
            if callable(builder):
                try:
                    context = builder() or {}
                    strategy_diagnostics = {
                        key: context.get(key)
                        for key in (
                            "state",
                            "state_reason",
                            "closed_bars",
                            "quote_window_seconds",
                            "invalid_quotes",
                            "block_counts",
                            "unknown_intents",
                            "active_order",
                            "evidence_failure_count",
                            "evidence_failure_reason",
                            "risk_failure_count",
                            "risk_failure_reason",
                        )
                    }
                except Exception as exc:
                    strategy_diagnostics = {"error": f"{type(exc).__name__}: {exc}"}
        # Session-scoped trade accounting: only orders submitted by THIS run
        # may count as the acceptance round trip (the shared simulation
        # account can carry unrelated order/trade history).
        our_order_refs = set()
        try:
            order_state = getattr(store._api, "_order_state", None)
            if isinstance(order_state, dict):
                our_order_refs = set(order_state)
        except Exception:
            our_order_refs = set()
        # Post-run authoritative readback.
        try:
            final_positions = _rows(store.registered_sim_query("positions_result", timeout=8.0))
            final_orders = _rows(store.registered_sim_query("orders_result", timeout=8.0))
            final_trades = _rows(store.registered_sim_query("trades_result", timeout=8.0))
            final_account = _rows(store.registered_sim_query("account_result", timeout=8.0))
        except Exception as exc:
            final_positions, final_orders, final_trades, final_account = [], [], [], []
            summary["post_run_query_error"] = f"{type(exc).__name__}: {exc}"
        residual_open = [row for row in final_positions if _position_is_open(row)]
        residual_active = [row for row in final_orders if _order_is_active(row)]
        filled_entry = 0.0
        filled_close = 0.0
        scoped_trade_rows = 0
        for row in final_trades:
            ref = str(_row_get(row, "OrderRef", "order_ref", default="") or "").strip()
            if ref not in our_order_refs:
                continue
            scoped_trade_rows += 1
            offset = str(_row_get(row, "OffsetFlag", "offset_flag", default="") or "")
            volume = float(_row_get(row, "Volume", "volume", default=0) or 0)
            if offset == "0":
                filled_entry += volume
            else:
                filled_close += volume
        gate = store.registered_sim_status()
        summary.update(
            {
                "run": {
                    "started_utc": _utc_iso(started_wall),
                    "finished_utc": _utc_iso(time.time()),
                    "seconds": round(time.monotonic() - started_mono, 3),
                    "state": state,
                    "state_reason": state_reason,
                    "run_error": run_error,
                },
                "orders": {
                    "trade_rows": scoped_trade_rows,
                    "filled_entry_lots": filled_entry,
                    "filled_close_lots": filled_close,
                    "active_orders": len(residual_active),
                    "scoped_to_session": True,
                    "session_order_refs": len(our_order_refs),
                    "account_trade_rows": len(final_trades),
                },
                "strategy_diagnostics": strategy_diagnostics,
                "reconciliation": {
                    "open_position_rows": len(residual_open),
                    "account_rows": len(final_account),
                    "gate_state": gate,
                },
            }
        )
        if run_error is not None:
            summary["status"] = "UNKNOWN"
            code = EXIT_UNKNOWN
        elif residual_open or residual_active:
            summary["status"] = "UNKNOWN"
            summary["reason"] = "residual_exposure_after_run"
            code = EXIT_UNKNOWN
            frozen = True
        elif filled_entry > 0 and filled_close > 0 and filled_close >= filled_entry:
            summary["status"] = "PASS"
            code = EXIT_PASS
        elif filled_entry == 0 and filled_close == 0:
            summary["status"] = "FAIL"
            summary["reason"] = "no_fill_round_trip"
            code = EXIT_FAIL
        else:
            summary["status"] = "UNKNOWN"
            summary["reason"] = "partial_round_trip"
            code = EXIT_UNKNOWN
        summary["tier"] = "fill_round_trip" if summary["status"] == "PASS" else "lifecycle_only"
        summary["writes_policy"] = {"max_actions": policy.get("max_actions"), "allow_write": True}
        _write_summary()
        return code
    except simnow_direct.SimNowDirectError as exc:
        summary.update({"status": "BLOCKED", "reason": exc.reason, "details": exc.details})
        _write_summary()
        _json_print(summary)
        return EXIT_BLOCKED
    except LiveRejected as exc:
        summary.update({"status": "BLOCKED", "reason": exc.reason, "details": exc.details})
        _write_summary()
        _json_print(summary)
        return exc.exit_code
    except Exception as exc:
        summary.update({"status": "BLOCKED", "reason": f"{type(exc).__name__}: {exc}"})
        _write_summary()
        _json_print(summary)
        return EXIT_BLOCKED
    finally:
        if store is not None:
            try:
                if frozen:
                    store.registered_sim_freeze("residual_exposure_after_run")
                else:
                    store.registered_sim_disarm("run_finished")
            except Exception:
                pass
            try:
                store.stop(timeout=float((config.get("timeouts") or {}).get("stop_seconds") or 12.0))
            except Exception:
                pass
        _write_summary()
        _json_print(summary)


# -------------------------------------------------------------------------- main
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    try:
        _ensure_dev_sdk_path()
    except Exception:
        pass
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replay", action="store_true", help="offline frozen-fixture replay")
    mode.add_argument("--dry", action="store_true", help="force the offline config self-check")
    mode.add_argument("--live", action="store_true", help="run against the SimNow simulation account")
    parser.add_argument("--allow-write", action="store_true", help="grant bounded real write actions")
    parser.add_argument("--allow-dangerous", action="store_true", help="reserved; no dangerous action exists")
    parser.add_argument("--scenario", default=None, help="replay scenario name")
    parser.add_argument("--run-seconds", type=float, default=None, help="live run window override (bounded)")
    parser.add_argument("--evidence-dir", default=None)
    parser.add_argument("--drill", action="store_true", help="engineering drill window instead of natural signals")
    parser.add_argument("--drill-side", choices=("long", "short"), default="long")
    parser.add_argument("--drill-delay-seconds", type=float, default=None)
    parser.add_argument("--drill-window-seconds", type=float, default=None)
    parser.add_argument("--drill-warmup-bars", type=int, default=None)
    # ``parse_known_args`` keeps unknown values out of any echoed error text.
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        print(
            json.dumps(
                {
                    "status": "REJECTED",
                    "error": "unknown_arguments_rejected",
                    "unknown_count": len(unknown),
                },
                sort_keys=True,
            )
        )
        return EXIT_BLOCKED
    if args.allow_dangerous:
        print(json.dumps({"status": "REJECTED", "error": "no_dangerous_actions_defined"}))
        return EXIT_BLOCKED
    # ``config.entry.tier`` selects the channel; a mode flag may only keep or
    # lower it, and a malformed declaration is rejected before any provider side
    # effect instead of falling back toward live.
    try:
        tier_config = _load_config()[0]
    except Exception as exc:  # a config that cannot be read is not a live request
        _json_print({"status": "BLOCKED", "reason": f"tier_config_unreadable:{type(exc).__name__}"})
        return EXIT_BLOCKED
    cli_tier = "live" if args.live else "replay" if args.replay else "dry" if args.dry else None
    decision = entry_tier.decide(tier_config, cli_tier)
    if entry_tier.invalid(decision) or entry_tier.conflict(decision):
        _json_print(
            {
                "status": "BLOCKED",
                "reason": decision.reason,
                "tier": decision.as_evidence(),
                "write_grant_result": "not_evaluated_tier_unresolved",
            }
        )
        return EXIT_BLOCKED
    args.tier_decision = decision
    if decision.effective_tier == "live":
        return run_live(args)
    if decision.effective_tier == "replay":
        return run_replay(
            args.scenario,
            Path(args.evidence_dir) if args.evidence_dir else None,
            decision.as_evidence(),
        )
    return run_dry(decision.as_evidence())


if __name__ == "__main__":
    raise SystemExit(main())

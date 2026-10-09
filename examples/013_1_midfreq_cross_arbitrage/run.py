#!/usr/bin/env python
"""013_1 standard entry — dry self-check / offline replay / SimNow live run.

Usage (any interpreter; the live CTP path requires CPython 3.11, e.g.
``C:/anaconda3/python.exe``):

    python run.py                       # dry: config + credential env NAMES only
    python run.py --replay [--scenario S]  # offline frozen-fixture replay (0 network, 0 writes)
    python run.py --live --allow-write  # real SimNow simulation account, bounded pair round trip
    python run.py --live --allow-write --drill --drill-side long   # engineering drill window

Exit codes: 0 PASS, 1 FAIL, 2 BLOCKED, 3 UNKNOWN.

Live execution goes through the SDK narrow registered-sim admission
(``simnow_direct``): one admission authorizes one instrument, so the two legs
(m/RM) switch the arm strictly between writes; the stock Store/managed/
production write routes remain closed.  Evidence is written under
``evidence/<run_id>/`` (git-ignored).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import signal
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
CHECKOUT_ROOT = HERE.parents[1]

EXIT_PASS, EXIT_FAIL, EXIT_BLOCKED, EXIT_UNKNOWN = 0, 1, 2, 3

# m (DCE) and rm (CZCE) share the delivery-month calendar; the exchange is a
# property of the product and is never inferred from the front address.
PRODUCT_EXCHANGES = {"m": "DCE", "rm": "CZCE"}

NEW_SECTIONS = frozenset(
    {
        "schema_version",
        "venue",
        "credentials",
        "live_contracts",
        "fronts",
        "live_market_data",
        "instrument_metadata",
        "policy",
        "timeouts",
        "drill",
    }
)


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
    """Merge the checkout-root .env into a name->value view (never injected).

    Values are read by name only; nothing is written back into ``os.environ``
    so the process keeps its own proxy/network settings (injecting .env proxy
    hints once broke an SDK HTTP client through a dead local proxy).
    """
    values = dict(os.environ)
    env_path = CHECKOUT_ROOT / ".env"
    if env_path.is_file():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key and key not in values:
                values[key] = value.strip().strip('"').strip("'")
    return values


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
    found = importlib.util.find_spec("bt_api_ctp")
    origin = getattr(found, "origin", None)
    if origin is None or root_text not in str(origin).replace("\\", "/").lower():
        raise LiveRejected("sdk_origin_not_dev_source", {"module": "bt_api_ctp", "found": origin is not None})


def _load_config() -> Tuple[Dict[str, Any], Path]:
    """Read the raw config; the iteration-42 sections are checked separately."""
    import yaml

    path = HERE / "config.yaml"
    if not path.is_file():
        raise LiveRejected("config_missing", {"config": path.name})
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise LiveRejected("config_root_not_mapping")
    return raw, path.resolve()


def _new_section_errors(config: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    if int(config.get("schema_version") or 0) != 2:
        errors.append("schema_version_must_be_2")
    if str(config.get("venue") or "") != "simnow":
        errors.append("venue_must_be_simnow")
    credentials = config.get("credentials")
    if not isinstance(credentials, Mapping) or not credentials:
        errors.append("credentials_section_missing")
    else:
        for key, value in credentials.items():
            if not str(key).endswith("_env") or not isinstance(value, str) or not value.strip():
                errors.append(f"credential_name_invalid:{key}")
    contracts = config.get("live_contracts")
    if not isinstance(contracts, Mapping):
        errors.append("live_contracts_section_missing")
    else:
        symbols = contracts.get("symbols")
        if symbols != "auto" and not (
            isinstance(symbols, list) and all(isinstance(item, str) and item for item in symbols)
        ):
            errors.append("live_contracts_symbols_invalid")
        exchanges = contracts.get("exchanges")
        if not isinstance(exchanges, Mapping) or not exchanges:
            errors.append("live_contracts_exchanges_missing")
    pairs = ((config.get("fronts") or {}) or {}).get("pairs")
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= 8:
        errors.append("fronts_pairs_must_be_1_to_8")
    else:
        for index, item in enumerate(pairs):
            if not isinstance(item, Mapping) or not item.get("td_env") or not item.get("md_env"):
                errors.append(f"front_pair_invalid:{index}")
    metadata = config.get("instrument_metadata")
    if not isinstance(metadata, Mapping) or not metadata:
        errors.append("instrument_metadata_missing")
    else:
        for product, expectation in metadata.items():
            if not isinstance(expectation, Mapping) or not expectation.get("price_tick") or not expectation.get(
                "volume_multiple"
            ):
                errors.append(f"instrument_metadata_invalid:{product}")
    policy = config.get("policy")
    if not isinstance(policy, Mapping) or policy.get("allow_write") is not False:
        errors.append("policy_allow_write_must_default_false")
    timeouts = config.get("timeouts")
    if not isinstance(timeouts, Mapping):
        errors.append("timeouts_section_missing")
    return errors


def _resolve_live_contracts(config: Mapping[str, Any]) -> List[Tuple[str, str]]:
    """Resolve the two live legs as exact ``(instrument, exchange)`` pairs."""
    import legacy_runner

    contracts = dict(config.get("live_contracts") or {})
    configured = contracts.get("symbols")
    if configured in (None, "", "auto"):
        symbols = [str(item) for item in legacy_runner.resolve_symbols()]
    elif isinstance(configured, list):
        symbols = [str(item) for item in configured]
    else:
        raise LiveRejected("live_contracts_symbols_invalid")
    if len(symbols) != 2:
        raise LiveRejected("exactly_two_live_legs_required", {"count": len(symbols)})
    overrides = dict(contracts.get("exchanges") or {})
    resolved: List[Tuple[str, str]] = []
    seen = set()
    for symbol in symbols:
        product = "".join(ch for ch in symbol if ch.isalpha()).lower()
        exchange = str(overrides.get(product) or PRODUCT_EXCHANGES.get(product) or "").upper()
        if not exchange:
            raise LiveRejected("unknown_live_product_exchange", {"product": product})
        if exchange in seen:
            raise LiveRejected("live_legs_pick_distinct_exchanges", {"exchange": exchange})
        seen.add(exchange)
        resolved.append((symbol, exchange))
    return resolved


# --------------------------------------------------------------------------- dry
def run_dry() -> int:
    try:
        config, config_path = _load_config()
    except Exception as exc:
        _json_print({"status": "REJECTED", "mode": "dry", "error": f"{type(exc).__name__}: {exc}"})
        return EXIT_BLOCKED
    errors = _new_section_errors(config)
    contracts: List[Tuple[str, str]] = []
    try:
        contracts = _resolve_live_contracts(config)
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    credentials = dict(config.get("credentials") or {})
    report = {
        "status": "DRY" if not errors else "REJECTED",
        "mode": "dry",
        "config_path": config_path.name,
        "strategy_id": "example.013_1.midfreq_cross_arbitrage",
        "credential_env_names": sorted(str(name) for name in credentials.values()),
        "live_contracts": [
            {"instrument": symbol, "exchange": exchange} for symbol, exchange in contracts
        ],
        "front_pair_count": len(((config.get("fronts") or {}) or {}).get("pairs") or []),
        "network": 0,
        "provider_sessions": 0,
        "errors": errors,
    }
    _json_print(report)
    return EXIT_PASS if not errors else EXIT_BLOCKED


# ------------------------------------------------------------------------ replay
def run_replay(scenario: Optional[str], evidence_dir: Optional[Path]) -> int:
    import legacy_runner

    chosen = str(scenario or ((_safe_config().get("replay") or {}) or {}).get("scenario") or "profitable")
    run_id = (
        f"replay-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        f"-{uuid.uuid4().hex[:8]}"
    )
    output_directory = Path(evidence_dir) if evidence_dir else (HERE / "evidence" / run_id)
    output_directory.mkdir(parents=True, exist_ok=True)
    try:
        report = legacy_runner.run_replay(scenario=chosen)
    except Exception as exc:
        _json_print(
            {
                "status": "REJECTED",
                "mode": "replay",
                "run_id": run_id,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        return EXIT_BLOCKED
    (output_directory / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, default=str, indent=2) + "\n",
        encoding="utf-8",
    )
    flat = all(abs(float(size or 0.0)) < 1e-12 for size in (report.get("positions") or {}).values())
    finalized = (report.get("trade_logger") or {}).get("finalized") is True
    ok = flat and finalized
    summary = {
        "status": "LOCAL_REPLAY_PASS" if ok else "REPLAY_INCOMPLETE",
        "mode": "replay",
        "run_id": run_id,
        "scenario": chosen,
        "evidence_directory": str(output_directory),
        "pair_actions": report.get("pair_actions"),
        "business_summary_hash": report.get("business_summary_hash"),
        "external_request_counts": {"network": 0, "order_write": 0},
        "boundary": "SYNTHETIC_REPLAY_ONLY_NOT_MARKET_OR_PROFITABILITY_EVIDENCE",
    }
    _json_print(summary)
    return EXIT_PASS if ok else EXIT_FAIL


def _safe_config() -> Dict[str, Any]:
    try:
        config, _path = _load_config()
        return config
    except Exception:
        return {}


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


def _instrument_metadata(
    store, symbol: str, exchange: str, config: Mapping[str, Any], timeout: float
) -> Dict[str, Any]:
    """Read and validate one instrument's metadata against the frozen expectation."""
    rows = _rows(
        store.registered_sim_query(
            "instruments_result", timeout=timeout, instrument_id=symbol, exchange_id=exchange
        )
    )
    row = None
    for item in rows:
        if str(_row_get(item, "InstrumentID", "instrument_id", default="")).upper() == symbol.upper():
            row = item
            break
    if row is None:
        raise LiveRejected("instrument_not_found", {"instrument": symbol, "exchange": exchange})
    price_tick = _row_get(row, "PriceTick", "price_tick")
    volume_multiple = _row_get(row, "VolumeMultiple", "volume_multiple")
    product = "".join(ch for ch in symbol if ch.isalpha()).lower()
    expectation = dict((config.get("instrument_metadata") or {}).get(product) or {})
    metadata = {
        "instrument": symbol,
        "exchange": exchange,
        "price_tick": float(price_tick) if price_tick not in (None, "") else None,
        "volume_multiple": float(volume_multiple) if volume_multiple not in (None, "") else None,
    }
    expected_tick = float(expectation.get("price_tick") or 0)
    expected_multiple = float(expectation.get("volume_multiple") or 0)
    if (
        metadata["price_tick"] is None
        or metadata["volume_multiple"] is None
        or abs(metadata["price_tick"] - expected_tick) > 1e-9
        or abs(metadata["volume_multiple"] - expected_multiple) > 1e-9
    ):
        raise LiveRejected(
            "instrument_metadata_mismatch",
            {
                "instrument": symbol,
                "exchange": exchange,
                "price_tick": metadata["price_tick"],
                "volume_multiple": metadata["volume_multiple"],
                "expected_price_tick": expected_tick,
                "expected_volume_multiple": expected_multiple,
            },
        )
    return metadata


def _live_preflight(
    store,
    contracts: List[Tuple[str, str]],
    config: Mapping[str, Any],
    timeout: float,
) -> Dict[str, Any]:
    """Bounded read-only preflight covering both legs and the shared account."""
    login = store.registered_sim_login_facts()
    if not (login.get("read_only_ready") or login.get("trading_ready")):
        raise LiveRejected("login_not_read_ready", {"login": login})
    trading_day = str(login.get("trading_day") or "")
    if len(trading_day) != 8 or int(login.get("connection_generation") or 0) <= 0:
        raise LiveRejected("login_facts_invalid", {"trading_day_shape": len(trading_day)})
    account = _rows(store.registered_sim_query("account_result", timeout=timeout))
    positions = _rows(store.registered_sim_query("positions_result", timeout=timeout))
    orders = _rows(store.registered_sim_query("orders_result", timeout=timeout))
    metadata = [
        _instrument_metadata(store, symbol, exchange, config, timeout)
        for symbol, exchange in contracts
    ]
    open_rows = [row for row in positions if _position_is_open(row)]
    active_orders = [row for row in orders if _order_is_active(row)]
    starting_equity = 0.0
    if account:
        try:
            starting_equity = float(_row_get(account[0], "Balance", "balance", default=0.0) or 0.0)
        except (TypeError, ValueError):
            starting_equity = 0.0
    if open_rows or active_orders:
        raise LiveRejected(
            "account_not_clean_for_pilot",
            {
                "positions_open_rows": len(open_rows),
                "orders_active_rows": len(active_orders),
                "pilot_requires_flat_and_no_active_orders": True,
            },
        )
    return {
        "login": login,
        "trading_day": trading_day,
        "account_rows": len(account),
        "positions_open_rows": len(open_rows),
        "orders_active_rows": len(active_orders),
        "starting_equity": starting_equity,
        "metadata": metadata,
    }


def _account_fingerprint(broker_id: str, user_id: str) -> str:
    payload = json.dumps(
        {"broker_id": str(broker_id), "user_id": str(user_id)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _attach_trade_logger(cerebro, output_directory: Path) -> None:
    """Attach the named report owner with console streaming disabled."""
    import backtrader as bt

    cerebro.addobserver(
        bt.observers.TradeLogger,
        obsname="trade_logger",
        log_dir=str(output_directory),
        log_format="json",
        log_to_console=False,
        log_positions=False,
        log_indicators=False,
        log_ticks=False,
        log_bars=False,
        log_value=False,
        log_position_snapshot=False,
    )


def run_live(args) -> int:
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
        config, config_path = _load_config()
    except Exception as exc:
        _json_print({"status": "REJECTED", "mode": "live", "error": f"{type(exc).__name__}: {exc}"})
        return EXIT_BLOCKED
    errors = _new_section_errors(config)
    if errors:
        _json_print({"status": "REJECTED", "mode": "live", "errors": errors})
        return EXIT_BLOCKED
    try:
        env = _load_env()
        _ensure_dev_sdk_path(strict=True)
        contracts = _resolve_live_contracts(config)
    except LiveRejected as exc:
        _json_print({"status": "BLOCKED", "mode": "live", "reason": exc.reason, "details": exc.details})
        return exc.exit_code
    except Exception as exc:
        _json_print({"status": "BLOCKED", "mode": "live", "reason": f"{type(exc).__name__}: {exc}"})
        return EXIT_BLOCKED

    import backtrader as bt

    import legacy_runner
    import simnow_direct
    from backtrader.brokers.btapibroker import BtApiBroker

    timeouts = dict(config.get("timeouts") or {})
    policy = dict(config.get("policy") or {})
    strategy_params = dict(config.get("strategy_params") or {})
    run_seconds = float(args.run_seconds or timeouts.get("run_seconds") or 600.0)
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
        "example_id": "013_1_midfreq_cross_arbitrage",
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
        credentials = {
            "broker_id": _resolve_ref(
                env.get(str((config.get("credentials") or {}).get("broker_id_env"))),
                {},
                field="broker_id",
            ),
            "user_id": _resolve_ref(
                env.get(str((config.get("credentials") or {}).get("user_id_env"))),
                {},
                field="user_id",
            ),
            "password": _resolve_ref(
                env.get(str((config.get("credentials") or {}).get("password_env"))),
                {},
                field="password",
            ),
            "app_id": _resolve_ref(
                env.get(str((config.get("credentials") or {}).get("app_id_env"))),
                {},
                field="app_id",
            ),
            "auth_code": _resolve_ref(
                env.get(str((config.get("credentials") or {}).get("auth_code_env"))),
                {},
                field="auth_code",
            ),
        }
        account_fingerprint = _account_fingerprint(credentials["broker_id"], credentials["user_id"])
        selection = simnow_direct.select_front_pair(
            ((config.get("fronts") or {}) or {}).get("pairs") or [],
            env,
            samples=3,
            connect_timeout=3.0,
        )
        strategy_path = HERE / "pair_arbitrage_strategy.py"
        config_digest = simnow_direct.canonical_sha256(
            {"config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest()}
        )
        identity_sha = simnow_direct.strategy_identity_sha256(
            strategy_path,
            {
                "strategy_id": "example.013_1.midfreq_cross_arbitrage",
                "instrument": "+".join(symbol for symbol, _exchange in contracts),
                "exchange": "+".join(exchange for _symbol, exchange in contracts),
            },
        )
        # Whole pairs are attempted in ranked order (fresh session per
        # attempt) strictly before any write; the first pair armable for BOTH
        # legs wins and every attempt is recorded.
        attempts: List[Dict[str, Any]] = []
        store = None
        armed: Optional[Dict[str, Any]] = None
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
                    raise LiveRejected("login_not_ready", {"login": login_facts, "wait_ready": ready})
                preflight = _live_preflight(
                    attempt_store,
                    contracts,
                    config,
                    float(timeouts.get("query_seconds") or 8.0),
                )
                # Verify the pair is armable for BOTH legs before any run:
                # arm the first leg, revoke, then arm the second leg and keep
                # it armed (the wrapper re-arms per write during the run).
                arm_states: List[Dict[str, Any]] = []
                for index, (symbol, exchange) in enumerate(contracts):
                    if index > 0:
                        attempt_store.registered_sim_disarm("admission_verify_next_leg")
                    arm_result = attempt_store.registered_sim_arm(
                        instrument=symbol,
                        exchange=exchange,
                        md_front=candidate["md_front"],
                        strategy_identity_sha256=identity_sha,
                        execution_cycle_id=run_id,
                        preflight_sha256=simnow_direct.canonical_sha256(
                            {
                                "config_digest": config_digest,
                                "login": preflight["login"],
                                "metadata": preflight["metadata"][index],
                                "account_rows": preflight["account_rows"],
                                "positions_open_rows": preflight["positions_open_rows"],
                                "orders_active_rows": preflight["orders_active_rows"],
                                "started_utc": _utc_iso(started_wall),
                            }
                        ),
                    )
                    arm_states.append(
                        {
                            "instrument": symbol,
                            "exchange": exchange,
                            "armed": bool(arm_result.get("armed")),
                            "gate_state": arm_result.get("state"),
                        }
                    )
                attempt_record["admission"] = "armed"
                attempt_record["legs"] = arm_states
                attempts.append(attempt_record)
                store = attempt_store
                armed = {
                    "candidate": candidate,
                    "preflight": preflight,
                    "account_fingerprint": account_fingerprint,
                    "arm_states": arm_states,
                }
                break
            except Exception as exc:
                attempt_record["error"] = f"{type(exc).__name__}: {exc}"
                if isinstance(exc, LiveRejected):
                    attempt_record["error_details"] = dict(exc.details)
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
        arm_states = armed["arm_states"]
        summary["environment"] = {
            "venue": "simnow",
            "front_selection": selection["receipt"],
            "selected_index": armed_candidate["index"],
            "selected_whitelisted": armed_candidate["whitelisted"],
            "contracts": [
                {"instrument": symbol, "exchange": exchange} for symbol, exchange in contracts
            ],
            "environment_switched_after_write": False,
        }
        summary["preflight"] = {
            "trading_day": preflight["trading_day"],
            "connection_generation": preflight["login"].get("connection_generation"),
            "account_rows": preflight["account_rows"],
            "starting_equity": preflight["starting_equity"],
            "metadata": preflight["metadata"],
            "pilot_account_flat_and_clean": True,
        }
        summary["admission"] = {
            "admitted": all(item["armed"] for item in arm_states),
            "legs": arm_states,
            "execution_cycle_id": run_id,
            "strategy_identity_sha256": identity_sha,
            "gate_state": arm_states[-1].get("gate_state"),
        }

        # Install the per-leg arm templates so every native write switches
        # (disarm+arm) to the exact outbound instrument strictly between
        # writes, then anchor the armed state for the second leg.
        arm_templates = {}
        for index, (symbol, exchange) in enumerate(contracts):
            arm_templates[(symbol, exchange)] = {
                "md_front": armed_candidate["md_front"],
                "strategy_identity_sha256": identity_sha,
                "execution_cycle_id": run_id,
                "preflight_sha256": simnow_direct.canonical_sha256(
                    {
                        "config_digest": config_digest,
                        "login": preflight["login"],
                        "metadata": preflight["metadata"][index],
                        "account_rows": preflight["account_rows"],
                        "positions_open_rows": preflight["positions_open_rows"],
                        "orders_active_rows": preflight["orders_active_rows"],
                        "started_utc": _utc_iso(started_wall),
                    }
                ),
            }
        store.registered_sim_configure_arm_templates(arm_templates)
        anchor_symbol, anchor_exchange = contracts[-1]
        store.registered_sim_ensure_arm(anchor_symbol, anchor_exchange)

        trigger = None
        if args.drill:
            delay = float(args.drill_delay_seconds if args.drill_delay_seconds is not None else 30.0)
            window = float(args.drill_window_seconds if args.drill_window_seconds is not None else 600.0)
            now_wall = time.time()
            trigger = {
                "trigger_id": f"drill-{uuid.uuid4().hex[:8]}",
                "instrument": "+".join(symbol for symbol, _exchange in contracts),
                "trading_day": preflight["trading_day"],
                "not_before_utc": _utc_iso(now_wall + delay),
                "not_after_utc": _utc_iso(now_wall + delay + window),
                "not_before_epoch": now_wall + delay,
                "not_after_epoch": now_wall + delay + window,
                "side": str(args.drill_side or "long"),
            }
            summary["drill"] = dict(trigger)

        params = dict(strategy_params)
        params["close_offsets"] = {
            symbol: legacy_runner.close_offset_for_exchange(exchange)
            for symbol, exchange in contracts
        }
        params["deadline_clock"] = time.monotonic
        params["broker_position_mode"] = "dual_side"
        if args.drill:
            drill_config = dict(config.get("drill") or {})
            params["max_pairs"] = 1
            params["max_holding_seconds"] = float(drill_config.get("hold_seconds") or 240.0)
            params["period"] = max(3, int(args.drill_warmup_bars if args.drill_warmup_bars is not None else 8))
            params["engineering_trigger"] = trigger
        broker = BtApiBroker(
            store=store,
            provider="btapi",
            position_mode="dual_side",
            max_order_size=int(strategy_params.get("order_lots") or 1),
            cash_check_enabled=True,
            sdk_preflight=False,
            require_complete_ctp_evidence=True,
            market_data_only=False,
            startup_account_state={
                "nonzero_position_record_count": int(preflight["positions_open_rows"]),
                "gross_position_lots": 0,
                "active_orders_count": int(preflight["orders_active_rows"]),
            },
            force_refresh_queries=False,
            position_sync_policy="startup",
            account_refresh_interval=3600.0,
            open_orders_refresh_interval=3600.0,
            flatten_on_stop=False,
            shutdown_timeout=float(timeouts.get("drain_seconds") or 120.0),
        )
        cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
        cerebro.setbroker(broker)
        feed_config = dict(config.get("feed") or {})
        feed_config.pop("timeframe", None)
        for symbol, _exchange in contracts:
            feed = store.getdata(
                dataname=symbol,
                timeframe=bt.TimeFrame.Minutes,
                **feed_config,
            )
            cerebro.adddata(feed, name=symbol)
        _attach_trade_logger(cerebro, output_directory)
        strategy_cls = __import__("pair_arbitrage_strategy").PairArbitrageStrategy
        cerebro.addstrategy(strategy_cls, **params)

        previous_sigint = signal.getsignal(signal.SIGINT)
        previous_sigterm = signal.getsignal(signal.SIGTERM)

        stop_requested = {"flag": False}

        def _request_stop(_reason: str) -> None:
            stop_requested["flag"] = True

        signal.signal(signal.SIGINT, lambda *_a: _request_stop("operator_sigint"))
        signal.signal(signal.SIGTERM, lambda *_a: _request_stop("operator_sigterm"))

        deadline_mono = started_mono + run_seconds

        def _watchdog() -> None:
            while True:
                if stop_requested["flag"] or time.monotonic() >= deadline_mono:
                    break
                time.sleep(0.5)
            # Hard-stop fallback: bounded drain plus stop-grace, then stop the
            # loop even if the strategy is still working.
            hard_deadline = (
                time.monotonic()
                + float(timeouts.get("drain_seconds") or 120.0)
                + 2.0 * float(timeouts.get("stop_seconds") or 12.0)
            )
            while time.monotonic() < hard_deadline:
                if getattr(getattr(cerebro, "_event_stop", None), "is_set", lambda: False)():
                    return
                time.sleep(1.0)
            try:
                cerebro.runstop()
            except Exception:
                pass

        watchdog = threading.Thread(target=_watchdog, name="pair-run-watchdog", daemon=True)
        watchdog.start()
        summary["status"] = "RUNNING"
        _write_summary()
        run_error = None
        try:
            cerebro.run()
        except Exception as exc:  # keep bounded evidence even on loop failure
            run_error = f"{type(exc).__name__}: {exc}"
        finally:
            stop_requested["flag"] = True
            watchdog.join(timeout=2.0)
            signal.signal(signal.SIGINT, previous_sigint)
            signal.signal(signal.SIGTERM, previous_sigterm)

        runstrats = getattr(cerebro, "runstrats", None) or []
        strategy_instance = runstrats[0][0] if runstrats and runstrats[0] else None
        strategy_diagnostics: Dict[str, Any] = {}
        if strategy_instance is not None:
            builder = getattr(strategy_instance, "_report_context", None)
            if callable(builder):
                try:
                    context = builder() or {}
                    strategy_diagnostics = {
                        key: context.get(key)
                        for key in (
                            "halted",
                            "halt_reason",
                            "pair_actions",
                            "open_attempts",
                            "ticks_seen",
                            "engineering_trigger_fired",
                            "positions",
                            "net_pnl",
                            "execution_state",
                        )
                    }
                except Exception as exc:
                    strategy_diagnostics = {"error": f"{type(exc).__name__}: {exc}"}
        # Session-scoped trade accounting: only orders submitted by THIS run
        # may count as the acceptance round trip (the shared simulation
        # account carries unrelated order/trade history).
        our_order_refs = set()
        try:
            order_state = getattr(store._api, "_order_state", None)
            if isinstance(order_state, dict):
                our_order_refs = set(order_state)
        except Exception:
            our_order_refs = set()
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
        entry_by_symbol = {symbol: 0.0 for symbol, _exchange in contracts}
        close_by_symbol = {symbol: 0.0 for symbol, _exchange in contracts}
        symbol_lookup = {symbol.upper(): symbol for symbol, _exchange in contracts}
        scoped_trade_rows = 0
        for row in final_trades:
            ref = str(_row_get(row, "OrderRef", "order_ref", default="") or "").strip()
            if ref not in our_order_refs:
                continue
            scoped_trade_rows += 1
            native_symbol = str(
                _row_get(row, "InstrumentID", "instrument_id", default="") or ""
            ).upper()
            symbol = symbol_lookup.get(native_symbol)
            if symbol is None:
                continue
            offset = str(_row_get(row, "OffsetFlag", "offset_flag", default="") or "")
            volume = float(_row_get(row, "Volume", "volume", default=0) or 0)
            if offset == "0":
                entry_by_symbol[symbol] += volume
            else:
                close_by_symbol[symbol] += volume
        gate = store.registered_sim_status()
        arm_history = store.registered_sim_arm_history()
        summary.update(
            {
                "run": {
                    "started_utc": _utc_iso(started_wall),
                    "finished_utc": _utc_iso(time.time()),
                    "seconds": round(time.monotonic() - started_mono, 3),
                    "run_error": run_error,
                },
                "orders": {
                    "trade_rows": scoped_trade_rows,
                    "entry_by_symbol": entry_by_symbol,
                    "close_by_symbol": close_by_symbol,
                    "active_orders": len(residual_active),
                    "scoped_to_session": True,
                    "session_order_refs": len(our_order_refs),
                    "account_trade_rows": len(final_trades),
                },
                "strategy_diagnostics": strategy_diagnostics,
                "arm_history": arm_history,
                "reconciliation": {
                    "open_position_rows": len(residual_open),
                    "account_rows": len(final_account),
                    "gate_state": gate,
                },
            }
        )
        entry_complete = all(entry_by_symbol[symbol] > 0 for symbol, _exchange in contracts)
        close_complete = all(
            close_by_symbol[symbol] >= entry_by_symbol[symbol] for symbol, _exchange in contracts
        )
        if run_error is not None:
            summary["status"] = "UNKNOWN"
            code = EXIT_UNKNOWN
        elif residual_open or residual_active:
            summary["status"] = "UNKNOWN"
            summary["reason"] = "residual_exposure_after_run"
            code = EXIT_UNKNOWN
            frozen = True
        elif entry_complete and close_complete:
            summary["status"] = "PASS"
            code = EXIT_PASS
        elif not any(entry_by_symbol.values()) and not any(close_by_symbol.values()):
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replay", action="store_true", help="offline frozen-fixture replay")
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
    if args.live:
        return run_live(args)
    if args.replay:
        return run_replay(args.scenario, Path(args.evidence_dir) if args.evidence_dir else None)
    return run_dry()


if __name__ == "__main__":
    # Direct CLI execution needs this folder and the checkout on the path; the
    # bootstrap stays inside the main guard by contract.
    for _bootstrap_path in (str(HERE), str(REPO_ROOT)):
        if _bootstrap_path not in sys.path:
            sys.path.insert(0, _bootstrap_path)
    raise SystemExit(main())

#!/usr/bin/env python
"""014_2 standard entry — dry self-check / offline replay / SimNow live observation.

Usage (Python 3.11 required for the live tier; dry/replay need only the core):

    python run.py                          # dry: config + live-readiness report (no network)
    python run.py --replay [--scenario S]  # offline minute FQ2 fixture replay (0 network, 0 writes)
    python run.py --live                   # live OBSERVATION tier (no write path exists)

Exit codes: 0 PASS, 1 FAIL, 2 BLOCKED, 3 UNKNOWN.

The strategy is decision-only by contract (its token outcomes are
``ENGINEERING_WRITE_DISABLED`` / ``REPLAY_WRITE_DISABLED`` and it never submits
an order), so the live tier is an **observation** acceptance: the real
direct registered-sim chain streams real ticks, the feed seals closed-minute
``BarEvidence`` plus captured quote windows, and the strategy computes its FQ2
features and decisions on live inputs.  Zero writes are possible on this
route; ``--allow-write`` is refused explicitly (the write tier would require a
strategy-level execution addition outside this iteration's scope).  Evidence
is written under ``evidence/<run_id>/`` (git-ignored).
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
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
CHECKOUT_ROOT = HERE.parents[1]

# Canonical example fence: a direct ``python run.py`` must bind the checkout
# copy of framework/SDK packages, never an installed one.
for _bootstrap_path in (str(HERE), str(REPO_ROOT)):
    if _bootstrap_path not in sys.path:
        sys.path.insert(0, _bootstrap_path)

EXIT_PASS, EXIT_FAIL, EXIT_BLOCKED, EXIT_UNKNOWN = 0, 1, 2, 3
STRATEGY_ID = "ctp_options_midfreq"
LIVE_ADAPTER_KEY = "live_adapter"
LIVE_CANDIDATE_ID = "ctp-options-midfreq-live-observe-r1"
LIVE_SESSION_SEGMENT_PREFIX = "czce-live-observe"
REQUIRED_LIVE_ENV_NAMES = ("CTP_BROKER_ID", "CTP_USER_ID", "CTP_PASSWORD", "CTP_APP_ID", "CTP_AUTH_CODE")


class LiveRejected(RuntimeError):
    """Bounded live-path rejection carrying a reason and value-free details."""

    def __init__(self, reason: str, details: Optional[Mapping[str, Any]] = None, exit_code: int = EXIT_BLOCKED):
        super().__init__(reason)
        self.reason = str(reason)
        self.details = dict(details or {})
        self.exit_code = int(exit_code)


def _load_legacy():
    """Return the folder-local legacy engine (package import or direct script)."""
    if __package__:
        from . import legacy_runner
    else:
        import legacy_runner
    return legacy_runner


def _json_print(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def _utc_iso(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(float(epoch), datetime.timezone.utc).isoformat()


def _load_raw_config() -> Dict[str, Any]:
    import yaml

    path = HERE / "config.yaml"
    if not path.is_file():
        raise LiveRejected("config_missing", {"config": path.name})
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise LiveRejected("config_root_not_mapping")
    return raw


def _load_env() -> Dict[str, str]:
    """Merge the checkout-root .env into a name->value view (never injected)."""
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
    """Prefer the dev bt_api_py source tree over any installed copy."""
    import importlib.util

    root = Path(os.environ.get("BT_API_PY_ROOT") or "D:/bt_api_py").expanduser()
    for extra in reversed((root / "bt_api" / "bt_api_base" / "src", root / "bt_api" / "bt_api_ctp" / "src")):
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


def _split_symbol(symbol: str) -> Tuple[str, str]:
    text = str(symbol or "").strip().upper()
    exchange, _, code = text.partition(".")
    if not exchange or not code:
        raise LiveRejected("live_symbol_needs_exchange_prefix", {"symbol": text})
    return code, exchange


def _live_section_errors(live: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    if int(live.get("schema_version") or 0) != 1:
        errors.append("live_adapter.schema_version_must_be_1")
    if str(live.get("venue") or "") != "simnow":
        errors.append("live_adapter.venue_must_be_simnow")
    credentials = live.get("credentials")
    if not isinstance(credentials, Mapping) or not credentials:
        errors.append("live_adapter.credentials_missing")
    else:
        for key, value in credentials.items():
            if not str(key).endswith("_env") or not isinstance(value, str) or not value.strip():
                errors.append(f"live_adapter.credential_invalid:{key}")
    pairs = ((live.get("fronts") or {}) or {}).get("pairs")
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= 8:
        errors.append("live_adapter.fronts_pairs_must_be_1_to_8")
    else:
        for index, item in enumerate(pairs):
            if not isinstance(item, Mapping) or not item.get("td_env") or not item.get("md_env"):
                errors.append(f"live_adapter.front_pair_invalid:{index}")
    candidate = live.get("live_candidate")
    if not isinstance(candidate, Mapping) or not isinstance(candidate.get("contracts"), Mapping):
        errors.append("live_adapter.live_candidate_missing")
    metadata = live.get("instrument_metadata")
    if not isinstance(metadata, Mapping) or not metadata:
        errors.append("live_adapter.instrument_metadata_missing")
    policy = live.get("policy")
    if not isinstance(policy, Mapping) or policy.get("allow_write") is not False:
        errors.append("live_adapter.policy_allow_write_must_default_false")
    if not isinstance(live.get("timeouts"), Mapping):
        errors.append("live_adapter.timeouts_missing")
    return errors


# --------------------------------------------------------------------------- dry
def run_dry() -> int:
    legacy = _load_legacy()

    errors: list = []
    config: Dict[str, Any] = {}
    try:
        config = legacy.load_config()
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    live: Dict[str, Any] = {}
    try:
        raw = _load_raw_config()
        live = dict(raw.get(LIVE_ADAPTER_KEY) or {})
        errors.extend(_live_section_errors(live))
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    candidate = dict(config.get("candidate") or {})
    report = {
        "status": "DRY" if not errors else "REJECTED",
        "mode": "dry",
        "strategy_id": STRATEGY_ID,
        "candidate_id": candidate.get("candidate_id"),
        "live_tier": {
            "status": "OBSERVATION_ONLY",
            "venue": live.get("venue"),
            "write_tier": "NOT_IMPLEMENTED_DECISION_ONLY_STRATEGY",
            "credential_env_names": sorted(
                str(value) for value in (live.get("credentials") or {}).values()
            ),
            "front_pair_count": len(((live.get("fronts") or {}) or {}).get("pairs") or []),
            "live_contracts": (live.get("live_candidate") or {}).get("contracts"),
        },
        "network": 0,
        "provider_sessions": 0,
        "errors": errors,
    }
    _json_print(report)
    return EXIT_PASS if not errors else EXIT_BLOCKED


# ------------------------------------------------------------------------ replay
def run_replay(scenario: Optional[str], evidence_dir: Optional[Path]) -> int:
    legacy = _load_legacy()

    chosen = str(scenario or "")
    run_id = (
        f"replay-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        f"-{uuid.uuid4().hex[:8]}"
    )
    output_directory = Path(evidence_dir) if evidence_dir else (HERE / "evidence" / run_id)
    output_directory.mkdir(parents=True, exist_ok=True)
    try:
        config = legacy.load_config()
        report = legacy.run_replay(config, scenario=(chosen or None))
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
    status = str(report.get("status") or "")
    ok = status == "LOCAL_REPLAY_PASS"
    _json_print(
        {
            "status": status or "UNKNOWN",
            "mode": "replay",
            "run_id": run_id,
            "scenario": chosen or (config.get("replay") or {}).get("scenario"),
            "evidence_directory": str(output_directory),
            "external_request_counts": {"network": 0, "order_write": 0},
            "boundary": "SYNTHETIC_REPLAY_ONLY_NOT_MARKET_OR_PROFITABILITY_EVIDENCE",
        }
    )
    return EXIT_PASS if ok else EXIT_FAIL


# ----------------------------------------------------------------- live observe
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


class _LiveClock:
    """Run-scoped live clock shared by tick stamps, evidence and observation."""

    def __init__(self, *, generation: int, rules_hash: str, source: str, validity_seconds: float) -> None:
        from backtrader.feeds import ClockMapping

        self.domain = f"iter42-ctp-options-mid-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.boot_id = uuid.uuid4().hex
        self.source = str(source)
        self.generation = int(generation)
        wall0 = datetime.datetime.now(datetime.timezone.utc)
        mono0 = time.monotonic_ns()
        self.mapping = ClockMapping(
            mapping_id=f"iter42-0142-{uuid.uuid4().hex[:12]}",
            wall_utc_at_anchor=wall0,
            mono_ns_at_anchor=mono0,
            clock_domain_id=self.domain,
            connection_generation=self.generation,
            source=self.source,
            # Wall and monotonic observations come from independent system
            # clocks; the 250 ms bound matches the trusted-time skew policy.
            error_bound_ns=250_000_000,
            valid_until_mono_ns=mono0 + int(float(validity_seconds) * 1_000_000_000.0),
            rules_hash=str(rules_hash),
            synthetic=False,
        )

    def provenance(self, *, session_segment: str) -> Dict[str, Any]:
        return {
            "clock_domain_id": self.domain,
            "rules_hash": self.mapping.rules_hash,
            "session_segment": str(session_segment),
            "generation": self.generation,
            "source": self.source,
        }


class _ObservationEvidenceProvider:
    """Freeze one Feed-sealed bar into live BarEvidence (FQ2 quote windows)."""

    def __init__(self, mapping: Any, candidate_id: str, timeframe_seconds: float) -> None:
        self.mapping = mapping
        self.candidate_id = str(candidate_id)
        self.timeframe_seconds = float(timeframe_seconds)

    def __call__(self, bar: Any) -> Any:
        from backtrader.feeds import BarEvidence

        seal_received_at = bar.available_at
        # A live environment whose quote timestamps cannot satisfy the
        # run-scoped mapping (e.g. an always-on simulation replaying a stale
        # trading day) is a bounded precondition failure, not an internal
        # fault: classify it before BarEvidence construction instead of
        # crashing the run.
        try:
            seal_received_mono_ns = self.mapping.map_wall_to_mono_ns(seal_received_at)
            self.mapping.validate_pair(
                seal_received_at, seal_received_mono_ns / 1_000_000_000.0
            )
        except ValueError as exc:
            age_seconds = None
            try:
                wall = seal_received_at
                if wall.tzinfo is None:
                    wall = wall.replace(tzinfo=datetime.timezone.utc)
                age_seconds = round(
                    (
                        datetime.datetime.now(datetime.timezone.utc)
                        - wall.astimezone(datetime.timezone.utc)
                    ).total_seconds(),
                    3,
                )
            except Exception:
                pass
            raise LiveRejected(
                "live_event_clock_outside_run_mapping",
                {
                    "symbol": str(getattr(bar, "symbol", "") or ""),
                    "available_age_seconds": age_seconds,
                    "error": str(exc),
                },
            ) from exc
        return BarEvidence(
            symbol=bar.symbol,
            exchange=bar.exchange,
            bucket_start=bar.bucket_start,
            bucket_end=bar.bucket_end,
            available_at=bar.available_at,
            seal_received_mono=seal_received_mono_ns / 1_000_000_000.0,
            seal_received_at=seal_received_at,
            trading_day=bar.trading_day,
            generation=bar.connection_generation,
            session_segment=bar.session_segment,
            rules_hash=bar.rules_hash,
            quality=bar.quality,
            volume_complete=bar.volume_complete,
            first_ingest_seq=bar.first_ingest_seq,
            last_ingest_seq=bar.last_ingest_seq,
            quote_cutoff_seq=bar.quote_cutoff_seq,
            bar_id=bar.bar_id,
            bar_sequence=bar.bar_sequence,
            closure_reason=bar.closure_reason,
            watermark=bar.watermark,
            max_event_time=bar.max_event_time,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            openinterest=bar.openinterest,
            clock_domain=self.mapping.clock_domain_id,
            clock_mode="live",
            candidate_id=self.candidate_id,
            timeframe_seconds=self.timeframe_seconds,
            trade_count=bar.trade_count,
            complete=bar.complete,
            clock_mapping=self.mapping,
            quote_events=tuple(
                {**dict(item), "candidate_id": self.candidate_id}
                for item in getattr(bar, "quote_events", ()) or ()
            ),
        )


def _live_strategy_config(legacy_config: Mapping[str, Any], live: Mapping[str, Any], rules_hash: str) -> Dict[str, Any]:
    """Build the strategy's config view: frozen sections + live candidate."""
    import copy

    view = copy.deepcopy(dict(legacy_config))
    overlay = dict(live.get("live_candidate") or {})
    candidate = dict(view.get("candidate") or {})
    candidate.update(
        {
            "candidate_id": LIVE_CANDIDATE_ID,
            "rules_hash": rules_hash,
            "exchange": str(overlay.get("exchange") or candidate.get("exchange") or ""),
            "contracts": dict(overlay.get("contracts") or candidate.get("contracts") or {}),
            "strike": overlay.get("strike", candidate.get("strike")),
            "multiplier": overlay.get("multiplier", candidate.get("multiplier")),
            "discount_factor": overlay.get("discount_factor", candidate.get("discount_factor")),
            "option_style": overlay.get("option_style", candidate.get("option_style")),
            "quantities": dict(overlay.get("quantities") or candidate.get("quantities") or {}),
            "price_ticks": dict(overlay.get("price_ticks") or candidate.get("price_ticks") or {}),
        }
    )
    view["candidate"] = candidate
    signal_overlay = dict(overlay.get("signal") or {})
    if signal_overlay:
        signal = dict(view.get("signal") or {})
        signal.update(signal_overlay)
        view["signal"] = signal
    view["mode"] = "engineering_observation"
    return view


def run_live(args) -> int:
    if args.allow_write:
        _json_print(
            {
                "status": "BLOCKED",
                "mode": "live",
                "reason": "write_tier_not_implemented_for_decision_only_strategy",
                "hint": (
                    "this strategy has no order path by contract; the live tier is a zero-write "
                    "observation of real sealed evidence and decisions"
                ),
            }
        )
        return EXIT_BLOCKED

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

    # Import order matters: legacy_runner's iteration-41 fence puts the
    # checkout root on sys.path before anything binds ``backtrader``.
    import legacy_runner
    import simnow_direct

    import backtrader as bt
    from backtrader.brokers.btapibroker import BtApiBroker
    try:
        raw_config = _load_raw_config()
        legacy_config = legacy_runner.load_config()
    except Exception as exc:
        _json_print({"status": "REJECTED", "mode": "live", "error": f"{type(exc).__name__}: {exc}"})
        return EXIT_BLOCKED
    live = dict(raw_config.get(LIVE_ADAPTER_KEY) or {})
    errors = _live_section_errors(live)
    if errors:
        _json_print({"status": "REJECTED", "mode": "live", "errors": errors})
        return EXIT_BLOCKED
    try:
        env = _load_env()
        _ensure_dev_sdk_path(strict=True)
    except LiveRejected as exc:
        _json_print({"status": "BLOCKED", "mode": "live", "reason": exc.reason, "details": exc.details})
        return exc.exit_code
    except Exception as exc:
        _json_print({"status": "BLOCKED", "mode": "live", "reason": f"{type(exc).__name__}: {exc}"})
        return EXIT_BLOCKED

    timeouts = dict(live.get("timeouts") or {})
    observation = dict(live.get("observation") or {})
    run_seconds = float(args.run_seconds or timeouts.get("run_seconds") or 4200.0)
    if run_seconds > 7200.0:
        run_seconds = 7200.0
    run_id = (
        f"live-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        f"-{uuid.uuid4().hex[:8]}"
    )
    output_directory = Path(args.evidence_dir) if args.evidence_dir else (HERE / "evidence" / run_id)
    output_directory.mkdir(parents=True, exist_ok=True)
    summary: Dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "example_id": "014_2_ctp_options_midfreq",
        "mode": "live",
        "tier": "observation_only_feed_sealed",
        "status": "STARTING",
        "trigger": "observation",
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
    try:
        credentials = {
            "broker_id": _resolve_ref(
                env.get(str((live.get("credentials") or {}).get("broker_id_env"))), {}, field="broker_id"
            ),
            "user_id": _resolve_ref(
                env.get(str((live.get("credentials") or {}).get("user_id_env"))), {}, field="user_id"
            ),
            "password": _resolve_ref(
                env.get(str((live.get("credentials") or {}).get("password_env"))), {}, field="password"
            ),
            "app_id": _resolve_ref(
                env.get(str((live.get("credentials") or {}).get("app_id_env"))), {}, field="app_id"
            ),
            "auth_code": _resolve_ref(
                env.get(str((live.get("credentials") or {}).get("auth_code_env"))), {}, field="auth_code"
            ),
        }
        selection = simnow_direct.select_front_pair(
            ((live.get("fronts") or {}) or {}).get("pairs") or [],
            env,
            samples=3,
            connect_timeout=3.0,
        )
        rules_hash = simnow_direct.canonical_sha256(
            {"strategy": STRATEGY_ID, "live_candidate": live.get("live_candidate"), "kind": "iter42-0142-observe-v1"}
        )
        strategy_view = _live_strategy_config(legacy_config, live, rules_hash)
        contracts = dict(strategy_view["candidate"]["contracts"])
        legs: List[Tuple[str, str, str]] = []
        for field in ("future", "call", "put"):
            full_symbol = str(contracts.get(field) or "")
            code, exchange = _split_symbol(full_symbol)
            legs.append((full_symbol, code, exchange))
        exchange = legs[0][2]

        attempts: List[Dict[str, Any]] = []
        store = None
        armed: Optional[Dict[str, Any]] = None
        for candidate_pair in selection["ordered_pairs"]:
            attempt_record: Dict[str, Any] = {
                "index": candidate_pair["index"],
                "kind": candidate_pair["kind"],
                "whitelisted": candidate_pair["whitelisted"],
                "score_ms": candidate_pair["score_ms"],
            }
            attempt_store = simnow_direct.RegisteredSimStore(
                provider="ctp",
                backend="direct",
                config={
                    "md_front": candidate_pair["md_front"],
                    "td_front": candidate_pair["td_front"],
                    "broker_id": credentials["broker_id"],
                    "investor_id": credentials["user_id"],
                    "password": credentials["password"],
                    "app_id": credentials["app_id"],
                    "auth_code": credentials["auth_code"],
                    "auto_settlement_confirm": False,
                    "allow_zero_login_response": bool(
                        ((live.get("live_market_data") or {}) or {}).get(
                            "allow_zero_login_response", False
                        )
                    ),
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
                query_timeout = float(timeouts.get("query_seconds") or 8.0)
                account = _rows(attempt_store.registered_sim_query("account_result", timeout=query_timeout))
                positions = _rows(
                    attempt_store.registered_sim_query("positions_result", timeout=query_timeout)
                )
                metadata = []
                for full_symbol, code, leg_exchange in legs:
                    rows = _rows(
                        attempt_store.registered_sim_query(
                            "instruments_result",
                            timeout=query_timeout,
                            instrument_id=code,
                            exchange_id=leg_exchange,
                        )
                    )
                    row = None
                    for item in rows:
                        if str(_row_get(item, "InstrumentID", "instrument_id", default="")).upper() == code.upper():
                            row = item
                            break
                    if row is None:
                        raise LiveRejected(
                            "instrument_not_found", {"instrument": code, "exchange": leg_exchange}
                        )
                    expectation = dict((live.get("instrument_metadata") or {}).get(full_symbol) or {})
                    tick = _row_get(row, "PriceTick", "price_tick")
                    multiple = _row_get(row, "VolumeMultiple", "volume_multiple")
                    if (
                        tick in (None, "")
                        or multiple in (None, "")
                        or abs(float(tick) - float(expectation.get("price_tick") or 0)) > 1e-9
                        or abs(float(multiple) - float(expectation.get("volume_multiple") or 0)) > 1e-9
                    ):
                        raise LiveRejected(
                            "instrument_metadata_mismatch",
                            {
                                "symbol": full_symbol,
                                "price_tick": tick,
                                "volume_multiple": multiple,
                                "expected": expectation,
                            },
                        )
                    metadata.append(
                        {
                            "symbol": full_symbol,
                            "price_tick": float(tick),
                            "volume_multiple": float(multiple),
                            "lower_limit": _row_get(row, "LowerLimitPrice", "lower_limit_price"),
                            "upper_limit": _row_get(row, "UpperLimitPrice", "upper_limit_price"),
                        }
                    )
                preflight = {
                    "login": login_facts,
                    "trading_day": str(login_facts.get("trading_day") or ""),
                    "account_rows": len(account),
                    "position_rows": len(positions),
                    "metadata": metadata,
                }
                attempt_record["admission"] = "observed"
                attempts.append(attempt_record)
                store = attempt_store
                armed = {"candidate": candidate_pair, "preflight": preflight}
                break
            except Exception as exc:
                attempt_record["error"] = f"{type(exc).__name__}: {exc}"
                if isinstance(exc, LiveRejected):
                    attempt_record["error_details"] = dict(exc.details)
                attempts.append(attempt_record)
                try:
                    attempt_store.stop(timeout=float(timeouts.get("stop_seconds") or 12.0))
                except Exception:
                    pass
                store = None
        summary["admission_attempts"] = attempts
        if armed is None:
            raise LiveRejected("no_admissible_front_pair", {"attempts": attempts})
        preflight = armed["preflight"]
        selected = armed["candidate"]
        summary["environment"] = {
            "venue": "simnow",
            "write_tier": "NOT_IMPLEMENTED_DECISION_ONLY_STRATEGY",
            "front_selection": selection["receipt"],
            "selected_index": selected["index"],
            "selected_whitelisted": selected["whitelisted"],
            "legs": [item[0] for item in legs],
            "exchange": exchange,
            "environment_switched_after_write": False,
        }
        summary["preflight"] = {
            "trading_day": preflight["trading_day"],
            "connection_generation": preflight["login"].get("connection_generation"),
            "account_rows": preflight["account_rows"],
            "position_rows": preflight["position_rows"],
            "metadata": preflight["metadata"],
        }

        clock = _LiveClock(
            generation=int(preflight["login"].get("connection_generation") or 0),
            rules_hash=rules_hash,
            source=f"iter42:{STRATEGY_ID}:registered-sim-observe",
            validity_seconds=min(run_seconds + 600.0, 7200.0),
        )
        session_segment = f"{LIVE_SESSION_SEGMENT_PREFIX}:{preflight['trading_day']}"
        store.configure_live_tick_provenance(clock.provenance(session_segment=session_segment))
        provider = _ObservationEvidenceProvider(clock.mapping, LIVE_CANDIDATE_ID, 60.0)
        summary["clock"] = {
            "domain": clock.domain,
            "generation": clock.generation,
            "rules_hash": rules_hash,
            "session_segment": session_segment,
            "mapping_id": clock.mapping.mapping_id,
            "synthetic": bool(clock.mapping.synthetic),
        }

        broker = BtApiBroker(
            store=store,
            provider="btapi",
            position_mode="net",
            max_order_size=1,
            cash_check_enabled=True,
            sdk_preflight=False,
            require_complete_ctp_evidence=False,
            market_data_only=True,
            startup_account_state={
                "nonzero_position_record_count": 0,
                "gross_position_lots": 0,
                "active_orders_count": 0,
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
        for full_symbol, code, _leg_exchange in legs:
            feed = store.getdata(
                dataname=code,
                timeframe=bt.TimeFrame.Minutes,
                compression=1,
                dispatch_bars=True,
                dispatch_ticks=False,
                backfill_start=False,
                qcheck=1.0,
                closed_bar_evidence_provider=provider,
                closed_bar_quote_capture=True,
                closed_bar_quote_limit=int(observation.get("quote_limit") or 240),
            )
            cerebro.adddata(feed, name=full_symbol)
        strategy_cls = __import__("ctp_options_midfreq_strategy").CTPOptionsMidFrequencyStrategy
        cerebro.addstrategy(
            strategy_cls,
            config=strategy_view,
            quote_producer=None,
            timing_provider=None,
            require_feed_bar_evidence=True,
            feed_evidence_clock_mode="live",
            feed_evidence_clock_domain=clock.domain,
            max_pending_feed_decisions=int(observation.get("max_pending_decisions") or 8),
        )

        previous_sigint = signal.getsignal(signal.SIGINT)
        previous_sigterm = signal.getsignal(signal.SIGTERM)
        stop_requested = {"flag": False}

        def _request_stop(_reason: str) -> None:
            stop_requested["flag"] = True

        signal.signal(signal.SIGINT, lambda *_a: _request_stop("operator_sigint"))
        signal.signal(signal.SIGTERM, lambda *_a: _request_stop("operator_sigterm"))

        deadline_mono = started_mono + run_seconds
        idle_interval = max(float((legacy_config.get("timing") or {}).get("idle_interval_ms") or 250) / 1000.0, 0.05)

        def _strategy_instance():
            runstrats = getattr(cerebro, "runstrats", None) or []
            if runstrats and runstrats[0]:
                return runstrats[0][0]
            return None

        def _idle_pump() -> None:
            while not stop_requested["flag"] and time.monotonic() < deadline_mono:
                strategy = _strategy_instance()
                if strategy is not None:
                    try:
                        strategy.notify_idle()
                    except Exception:
                        pass
                time.sleep(idle_interval)

        def _watchdog() -> None:
            while True:
                if stop_requested["flag"] or time.monotonic() >= deadline_mono:
                    break
                time.sleep(0.5)
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

        watchdog = threading.Thread(target=_watchdog, name="options-observe-watchdog", daemon=True)
        idle_thread = threading.Thread(target=_idle_pump, name="options-observe-idle", daemon=True)
        watchdog.start()
        idle_thread.start()
        summary["status"] = "RUNNING"
        _write_summary()
        run_error = None
        scope_fault: Optional[LiveRejected] = None
        try:
            cerebro.run()
        except LiveRejected as exc:
            scope_fault = exc
        except Exception as exc:
            run_error = f"{type(exc).__name__}: {exc}"
        finally:
            stop_requested["flag"] = True
            watchdog.join(timeout=2.0)
            idle_thread.join(timeout=2.0)
            signal.signal(signal.SIGINT, previous_sigint)
            signal.signal(signal.SIGTERM, previous_sigterm)

        strategy_instance = _strategy_instance()
        strategy_report: Dict[str, Any] = {}
        if strategy_instance is not None:
            builder = getattr(strategy_instance, "build_report", None) or getattr(
                strategy_instance, "report", None
            )
            if callable(builder):
                try:
                    strategy_report = builder() or {}
                except Exception as exc:
                    strategy_report = {"report_error": f"{type(exc).__name__}: {exc}"}
        (output_directory / "strategy_report.json").write_text(
            json.dumps(strategy_report, ensure_ascii=False, sort_keys=True, default=str, indent=2) + "\n",
            encoding="utf-8",
        )
        minute_events = list(strategy_report.get("minute_events") or [])
        feed_evidence_fault = (strategy_report.get("feed_evidence") or {}).get("fault")
        feature_minutes = [
            event
            for event in minute_events
            if str(event.get("kind") or "") in {"WARMUP", "ORDINARY_DECISION"}
        ]
        decisions = [
            event for event in minute_events if str(event.get("kind") or "") == "ORDINARY_DECISION"
        ]
        skip_reasons: Dict[str, int] = {}
        for event in minute_events:
            kind = str(event.get("kind") or "")
            if kind.startswith(("SKIP", "RESET")):
                skip_reasons[kind] = skip_reasons.get(kind, 0) + 1
        summary.update(
            {
                "run": {
                    "started_utc": _utc_iso(started_wall),
                    "finished_utc": _utc_iso(time.time()),
                    "seconds": round(time.monotonic() - started_mono, 3),
                    "run_error": run_error,
                },
                "observation": {
                    "feature_minutes": len(feature_minutes),
                    "decisions": len(decisions),
                    "decision_outcomes": [
                        str(event.get("outcome") or "") for event in decisions
                    ],
                    "skip_reasons": skip_reasons,
                    "feed_evidence_fault": feed_evidence_fault,
                },
                "external_request_counts": {"network": "NOT_PROVEN", "order_write": 0},
            }
        )
        if scope_fault is not None:
            summary["status"] = "BLOCKED"
            summary["reason"] = scope_fault.reason
            summary["details"] = dict(scope_fault.details)
            code_exit = EXIT_BLOCKED
        elif run_error is not None:
            summary["status"] = "UNKNOWN"
            code_exit = EXIT_UNKNOWN
        elif feed_evidence_fault:
            summary["status"] = "BLOCKED"
            summary["reason"] = f"feed_evidence_fault:{feed_evidence_fault}"
            code_exit = EXIT_BLOCKED
        elif len(feature_minutes) >= 1:
            summary["status"] = "OBSERVATION_PASS"
            code_exit = EXIT_PASS
        else:
            summary["status"] = "FAIL"
            summary["reason"] = "no_complete_minute_window"
            code_exit = EXIT_FAIL
        summary["tier"] = "observation_only_feed_sealed"
        _write_summary()
        return code_exit
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
                store.stop(timeout=float((live.get("timeouts") or {}).get("stop_seconds") or 12.0))
            except Exception:
                pass
        _write_summary()
        _json_print(summary)


# -------------------------------------------------------------------------- main
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replay", action="store_true", help="offline minute FQ2 fixture replay")
    mode.add_argument("--live", action="store_true", help="live observation tier (no write path)")
    parser.add_argument("--allow-write", action="store_true", help="refused: this strategy has no order path")
    parser.add_argument("--allow-dangerous", action="store_true", help="reserved; no dangerous action exists")
    parser.add_argument("--scenario", default=None, help="replay scenario name")
    parser.add_argument("--run-seconds", type=float, default=None, help="live observation window (bounded)")
    parser.add_argument("--evidence-dir", default=None)
    # ``parse_known_args`` keeps unknown values out of any echoed error text.
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        _json_print(
            {
                "status": "REJECTED",
                "error": "unknown_arguments_rejected",
                "unknown_count": len(unknown),
            }
        )
        return EXIT_BLOCKED
    if args.allow_dangerous:
        _json_print({"status": "REJECTED", "error": "no_dangerous_actions_defined"})
        return EXIT_BLOCKED
    if args.live:
        return run_live(args)
    if args.replay:
        return run_replay(args.scenario, Path(args.evidence_dir) if args.evidence_dir else None)
    return run_dry()


if __name__ == "__main__":
    # Script execution keeps this directory importable; the entry imports the
    # legacy engine lazily inside its functions only.
    raise SystemExit(main())

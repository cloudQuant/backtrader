#!/usr/bin/env python
"""014_1 standard entry — dry self-check / offline replay / SimNow live adapter.

Usage (Python 3.11 required for the live tier; dry/replay need only the core):

    python run.py                          # dry: config + live-readiness report (no network)
    python run.py --replay [--scenario S]  # offline frozen-fixture replay (0 network, 0 writes)
    python run.py --live --allow-write     # strict live C/P/F adapter, bounded round trip
    python run.py --live --allow-write --drill   # one-shot engineering drill (bounded window)

Exit codes: 0 PASS, 1 FAIL, 2 BLOCKED, 3 UNKNOWN.

Live tier: direct registered-sim chain (``simnow_direct``) with strict
feed-sealed closed-bar evidence — every tick is stamped with the run-scoped
clock identity (``live_tick_provenance``), each 15-minute closed bar is sealed
into ``BarEvidence`` bound to the same non-synthetic ``ClockMapping``, the
strategy receives it through the feed's ``closed_bar_evidence_provider`` +
``notify_bar`` and its execution windows run on the run clock provider.  The
three C/P/F legs switch the single-instrument registered-sim arm strictly
between writes.  The stock Store/managed/production write routes remain
closed.  Evidence is written under ``evidence/<run_id>/`` (git-ignored).
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
REPO_ROOT = HERE.parents[2]
CHECKOUT_ROOT = HERE.parents[2]

# Canonical example fence: a direct ``python run.py`` must bind the checkout
# copy of framework/SDK packages, never an installed one.
for _bootstrap_path in (str(HERE), str(REPO_ROOT)):
    if _bootstrap_path not in sys.path:
        sys.path.insert(0, _bootstrap_path)

EXIT_PASS, EXIT_FAIL, EXIT_BLOCKED, EXIT_UNKNOWN = 0, 1, 2, 3
STRATEGY_ID = "ctp_options_lowfreq"
LIVE_ADAPTER_KEY = "live_adapter"
LIVE_CANDIDATE_ID = "ctp-options-lowfreq-live-r1"
LIVE_SESSION_SEGMENT_PREFIX = "czce-live"
REQUIRED_LIVE_ENV_NAMES = ("CTP_BROKER_ID", "CTP_USER_ID", "CTP_PASSWORD", "CTP_APP_ID", "CTP_AUTH_CODE")


class LiveRejected(RuntimeError):
    """Bounded live-path rejection carrying a reason and value-free details."""

    def __init__(self, reason: str, details: Optional[Mapping[str, Any]] = None, exit_code: int = EXIT_BLOCKED):
        super().__init__(reason)
        self.reason = str(reason)
        self.details = dict(details or {})
        self.exit_code = int(exit_code)


_OBSERVATION_CLEANUP_KEEPALIVE: List[Any] = []


def _observation_cleanup_error(exc: BaseException, *, phase: str) -> Dict[str, str]:
    exception_type = type(exc).__name__
    if len(exception_type) > 64 or not exception_type.isascii() or not exception_type.isidentifier():
        exception_type = "Exception"
    return {"phase": phase, "exception_type": exception_type}


def _observation_close_health_error(health: Any, *, phase: str) -> Optional[Dict[str, str]]:
    if not isinstance(health, Mapping):
        return {"phase": phase, "reason": "health_not_mapping"}
    false_fields = (
        "worker_alive",
        "close_thread_alive",
        "funding_worker_alive",
        "restart_blocked_by_worker",
        "restart_blocked_by_close",
        "funding_restart_blocked_by_worker",
        "read_only_metadata_probe_active",
        "funding_inflight",
    )
    zero_fields = (
        "queue_depth",
        "inflight",
        "publications_pending",
        "broker_update_queue_depth",
        "funding_queue_depth",
        "funding_pending",
    )
    try:
        if "shutdown_state" not in health:
            return {"phase": phase, "reason": "health_field_missing", "field": "shutdown_state"}
        if health.get("shutdown_state") != "PASS":
            return {"phase": phase, "reason": "shutdown_state_not_pass"}
        for field in false_fields:
            if field not in health:
                return {"phase": phase, "reason": "health_field_missing", "field": field}
            if type(health[field]) is not bool or health[field] is not False:
                return {"phase": phase, "reason": "health_flag_not_false", "field": field}
        for field in zero_fields:
            if field not in health:
                return {"phase": phase, "reason": "health_field_missing", "field": field}
            if type(health[field]) is not int or health[field] != 0:
                return {"phase": phase, "reason": "health_count_not_zero", "field": field}
    except Exception:
        return {"phase": phase, "reason": "health_unreadable"}
    return None


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
    """Merge the checkout-root .env into a name->value view (never injected).

    Values are read by name only; nothing is written back into ``os.environ``
    so the process keeps its own network settings.
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
    """Prefer the dev bt_api_py source tree over any installed copy."""
    import importlib.util

    root = Path(os.environ.get("BT_API_PY_ROOT") or "D:/bt_api_py").expanduser()
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
    """Split ``EXCHANGE.CODE`` into ``(code, exchange)``; reject bare forms."""
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
import entry_tier  # noqa: E402  (folder-local copy of examples/_support/entry_tier.py)


def run_dry(tier_evidence: Optional[Mapping[str, Any]] = None) -> int:
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
        "entry_tier": dict(tier_evidence or {}),
        "write_grant_result": "not_applicable_offline_tier",
        "status": "DRY" if not errors else "REJECTED",
        "mode": "dry",
        "strategy_id": STRATEGY_ID,
        "candidate_legs": [candidate.get(name) for name in ("future", "call", "put")],
        "live_tier": {
            "status": "STRICT_ADAPTER",
            "venue": live.get("venue"),
            "credential_env_names": sorted(
                str(value) for value in (live.get("credentials") or {}).values()
            ),
            "front_pair_count": len(((live.get("fronts") or {}) or {}).get("pairs") or []),
            "evidence": "feed-sealed BarEvidence + run-scoped ClockMapping + registered-sim arms",
        },
        "network": 0,
        "provider_sessions": 0,
        "errors": errors,
    }
    _json_print(report)
    return EXIT_PASS if not errors else EXIT_BLOCKED


# ------------------------------------------------------------------------ replay
def run_replay(
    scenario: Optional[str],
    evidence_dir: Optional[Path],
    tier_evidence: Optional[Mapping[str, Any]] = None,
) -> int:
    legacy = _load_legacy()

    chosen = str(scenario or "eligible")
    run_id = (
        f"replay-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        f"-{uuid.uuid4().hex[:8]}"
    )
    output_directory = Path(evidence_dir) if evidence_dir else (HERE / "evidence" / run_id)
    output_directory.mkdir(parents=True, exist_ok=True)
    try:
        config = legacy.load_config()
        report = legacy.run_replay(config, chosen)
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
    ok = report.get("status") == "LOCAL_REPLAY_PASS"
    summary = {
        "entry_tier": dict(tier_evidence or {}),
        "write_grant_result": "not_applicable_offline_tier",
        "status": report.get("status"),
        "mode": "replay",
        "run_id": run_id,
        "scenario": chosen,
        "evidence_directory": str(output_directory),
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


def _leg_metadata(
    store, code: str, exchange: str, live: Mapping[str, Any], full_symbol: str, timeout: float
) -> Dict[str, Any]:
    """Read and validate one leg's metadata against the live expectation."""
    rows = _rows(
        store.registered_sim_query(
            "instruments_result", timeout=timeout, instrument_id=code, exchange_id=exchange
        )
    )
    row = None
    for item in rows:
        if str(_row_get(item, "InstrumentID", "instrument_id", default="")).upper() == code.upper():
            row = item
            break
    if row is None:
        raise LiveRejected("instrument_not_found", {"instrument": code, "exchange": exchange})
    price_tick = _row_get(row, "PriceTick", "price_tick")
    volume_multiple = _row_get(row, "VolumeMultiple", "volume_multiple")
    lower = _row_get(row, "LowerLimitPrice", "lower_limit_price")
    upper = _row_get(row, "UpperLimitPrice", "upper_limit_price")
    expectation = dict((live.get("instrument_metadata") or {}).get(full_symbol) or {})
    metadata = {
        "symbol": full_symbol,
        "code": code,
        "exchange": exchange,
        "price_tick": float(price_tick) if price_tick not in (None, "") else None,
        "volume_multiple": float(volume_multiple) if volume_multiple not in (None, "") else None,
        "lower_limit": float(lower) if lower not in (None, "") else None,
        "upper_limit": float(upper) if upper not in (None, "") else None,
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
                "symbol": full_symbol,
                "price_tick": metadata["price_tick"],
                "volume_multiple": metadata["volume_multiple"],
                "expected_price_tick": expected_tick,
                "expected_volume_multiple": expected_multiple,
            },
        )
    if metadata["lower_limit"] is None or metadata["upper_limit"] is None:
        raise LiveRejected("exchange_limits_unavailable", {"symbol": full_symbol})
    return metadata


def _leg_commission(store, code: str, exchange: str, timeout: float) -> Dict[str, Any]:
    """Best-effort provider commission-rate readback for one leg."""
    try:
        rows = _rows(
            store.registered_sim_query(
                "instrument_commission_rate_result",
                timeout=timeout,
                instrument_id=code,
                exchange_id=exchange,
            )
        )
    except Exception:
        rows = []
    if not rows:
        return {"source": "conservative_fallback", "verified": False}
    row = rows[0]

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
        "raw": {
            key: _row_get(row, key)
            for key in (
                "OpenRatioByMoney",
                "OpenRatioByVolume",
                "CloseRatioByMoney",
                "CloseRatioByVolume",
                "CloseTodayRatioByMoney",
                "CloseTodayRatioByVolume",
            )
        },
    }


class _LiveClock:
    """Run-scoped live clock shared by tick stamps, evidence and observation.

    The mapping is caller-owned and explicitly non-synthetic; the domain is
    run-scoped (process + run id) and every observation carries the same
    anchors so execution-window wall/monotonic math stays consistent.
    """

    def __init__(self, *, generation: int, rules_hash: str, source: str, validity_seconds: float) -> None:
        from backtrader.feeds import ClockMapping

        self.domain = f"iter42-ctp-options-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.boot_id = uuid.uuid4().hex
        self.source = str(source)
        self.generation = int(generation)
        wall0 = datetime.datetime.now(datetime.timezone.utc)
        mono0 = time.monotonic_ns()
        self.mapping = ClockMapping(
            mapping_id=f"iter42-0141-{uuid.uuid4().hex[:12]}",
            wall_utc_at_anchor=wall0,
            mono_ns_at_anchor=mono0,
            clock_domain_id=self.domain,
            connection_generation=self.generation,
            source=self.source,
            error_bound_ns=0,
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

    def observation(self) -> Dict[str, Any]:
        return {
            "monotonic_ns": time.monotonic_ns(),
            "wall_utc": datetime.datetime.now(datetime.timezone.utc),
            "domain": self.domain,
            "generation": self.generation,
            "trusted": True,
            "source": self.source,
            "boot_id": self.boot_id,
            "mapping_id": self.mapping.mapping_id,
            "mapping_anchor_mono_ns": self.mapping.mono_ns_at_anchor,
            "mapping_anchor_wall_utc": self.mapping.wall_utc_at_anchor,
            "mapping_error_ns": self.mapping.error_bound_ns,
            "mapping_valid_until_mono_ns": self.mapping.valid_until_mono_ns,
        }


class _LiveEvidenceProvider:
    """Turn one Feed-frozen closed bar event into trusted live BarEvidence."""

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
        )


def _attach_trade_logger(cerebro, output_directory: Path) -> None:
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


def _fee_schedule_from(commission: Mapping[str, Any], future_price: float, multiplier: float) -> Dict[str, float]:
    """Per-lot CNY fee schedule from provider rates (price-approximated)."""

    def leg(money_rate: float, volume_rate: float) -> float:
        return float(volume_rate) + float(money_rate) * float(future_price) * float(multiplier)

    return {
        "open_buy": leg(commission.get("open_money_rate", 0.0), commission.get("open_volume_rate", 0.0)),
        "open_sell": leg(commission.get("open_money_rate", 0.0), commission.get("open_volume_rate", 0.0)),
        "close_buy": leg(commission.get("close_money_rate", 0.0), commission.get("close_volume_rate", 0.0)),
        "close_sell": leg(commission.get("close_money_rate", 0.0), commission.get("close_volume_rate", 0.0)),
        "close_today_buy": leg(
            commission.get("close_today_money_rate", 0.0), commission.get("close_today_volume_rate", 0.0)
        ),
        "close_today_sell": leg(
            commission.get("close_today_money_rate", 0.0), commission.get("close_today_volume_rate", 0.0)
        ),
    }



# ------------------------------------------------------------------ live observe
def run_live_observe(args) -> int:
    """Open a real SimNow session, read it, and close it. Writes stay unreachable.

    The live tier used to demand ``--allow-write`` before it would even start, so
    an operator who only wanted to look at the account had no channel at all.
    This path keeps the same interpreter, dev-SDK, config and leg preconditions,
    selects a reachable whole front pair, logs in, and reads the account,
    positions, orders and trades before closing the session.

    It never builds a Broker or Cerebro, never calls ``registered_sim_arm``, and
    never submits or cancels an order; the store's own write counters are
    reported so the absence of writes is evidenced rather than asserted. Open
    positions or resting orders are reported, not refused: the clean-account
    gate is a precondition of the write drill, not of observation.
    """

    if sys.version_info[:2] != (3, 11):
        _json_print(
            {
                "status": "BLOCKED",
                "mode": "live",
                "channel": "observe",
                "reason": "live_tier_requires_python_3_11",
                "current": f"{sys.version_info.major}.{sys.version_info.minor}",
                "hint": "run the live tier with the reviewed C:/anaconda3/python.exe (3.11)",
            }
        )
        return EXIT_BLOCKED

    # Import order matters, exactly as in the drill: legacy_runner's iteration-41
    # fence puts the checkout root on sys.path before anything binds ``backtrader``.
    _ensure_dev_sdk_path()
    import legacy_runner
    import simnow_direct

    decision = getattr(args, "tier_decision", None)
    tier_evidence = decision.as_evidence() if decision is not None else {}
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
        legs: List[Tuple[str, str, str]] = []
        for key in ("future", "call", "put"):
            full_symbol = str(dict(legacy_config.get("candidate") or {}).get(key) or "")
            code, leg_exchange = _split_symbol(full_symbol)
            legs.append((full_symbol, code, leg_exchange))
        if len({item[1] for item in legs}) != 3:
            raise LiveRejected("three_distinct_legs_required")
        if len({item[2] for item in legs}) != 1:
            raise LiveRejected("single_exchange_options_bundle_required")
    except LiveRejected as exc:
        _json_print({"status": "BLOCKED", "mode": "live", "reason": exc.reason, "details": exc.details})
        return exc.exit_code
    except Exception as exc:
        _json_print({"status": "BLOCKED", "mode": "live", "reason": f"{type(exc).__name__}: {exc}"})
        return EXIT_BLOCKED
    exchange = legs[0][2]

    timeouts = dict(live.get("timeouts") or {})
    query_timeout = float(timeouts.get("query_seconds") or 8.0)
    run_id = (
        f"observe-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        f"-{uuid.uuid4().hex[:8]}"
    )
    output_directory = Path(args.evidence_dir) if args.evidence_dir else (HERE / "evidence" / run_id)
    output_directory.mkdir(parents=True, exist_ok=True)
    summary: Dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "example_id": '014_1_ctp_options_lowfreq',
        "mode": "live",
        "channel": "observe",
        "status": "STARTING",
        "entry_tier": dict(tier_evidence),
        "write_grant_result": "not_required_observation_only",
        "legs": [item[0] for item in legs],
        "exchange": exchange,
        "evidence_directory": str(output_directory),
    }

    def _write_summary() -> None:
        try:
            (output_directory / "run.json").write_text(
                json.dumps(summary, ensure_ascii=False, sort_keys=True, default=str),
                encoding="utf-8",
            )
        except OSError:
            pass

    store = None
    observation_ready_to_pass = False
    result_code = EXIT_BLOCKED
    try:
        credentials = {
            field: _resolve_ref(
                env.get(str((live.get("credentials") or {}).get(f"{field}_env"))), {}, field=field
            )
            for field in ("broker_id", "user_id", "password", "app_id", "auth_code")
        }
        selection = simnow_direct.select_front_pair(
            ((live.get("fronts") or {}) or {}).get("pairs") or [],
            env,
            samples=3,
            connect_timeout=3.0,
        )
        attempts: List[Dict[str, Any]] = []
        for candidate_pair in selection["ordered_pairs"]:
            record: Dict[str, Any] = {
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
                        ((live.get("live_market_data") or {}) or {}).get("allow_zero_login_response", False)
                    ),
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
                try:
                    login = attempt_store.registered_sim_login_facts()
                except Exception:
                    login = {}
                if not ready or not (login.get("read_only_ready") or login.get("trading_ready")):
                    raise LiveRejected("login_not_ready", {"login": login, "wait_ready": ready})
                positions = _rows(attempt_store.registered_sim_query("positions_result", timeout=query_timeout))
                orders = _rows(attempt_store.registered_sim_query("orders_result", timeout=query_timeout))
                record["login"] = login
                record["readings"] = {
                    "account_rows": len(_rows(attempt_store.registered_sim_query("account_result", timeout=query_timeout))),
                    "position_rows": len(positions),
                    "open_position_rows": len([row for row in positions if _position_is_open(row)]),
                    "order_rows": len(orders),
                    "active_order_rows": len([row for row in orders if _order_is_active(row)]),
                    "trade_rows": len(_rows(attempt_store.registered_sim_query("trades_result", timeout=query_timeout))),
                }
                record["result"] = "observed"
            except simnow_direct.SimNowDirectError as exc:
                record.update({"result": "blocked", "reason": exc.reason, "details": dict(exc.details)})
            except LiveRejected as exc:
                record.update({"result": "blocked", "reason": exc.reason, "details": dict(exc.details)})
            except Exception as exc:
                record.update({"result": "error", "reason": f"{type(exc).__name__}: {exc}"})
            attempts.append(record)
            if record["result"] == "observed":
                store = attempt_store
                break
            try:
                close_health = attempt_store.stop(timeout=float(timeouts.get("stop_seconds") or 12.0))
            except Exception as exc:
                cleanup_error = _observation_cleanup_error(exc, phase="front_attempt_stop")
            else:
                cleanup_error = _observation_close_health_error(close_health, phase="front_attempt_stop")
            if cleanup_error is not None:
                record.update({"cleanup_status": "uncertain", "cleanup_error": cleanup_error})
                _OBSERVATION_CLEANUP_KEEPALIVE.append(attempt_store)
                summary["admission_attempts"] = attempts
                raise LiveRejected(
                    "cleanup_uncertain",
                    {"front_index": record["index"], "cleanup_error": cleanup_error},
                )
            else:
                record["cleanup_status"] = "closed"
        summary["admission_attempts"] = attempts
        if store is None:
            raise LiveRejected("no_observable_front_pair", {"attempts": attempts})
        observed = next(record for record in attempts if record["result"] == "observed")
        summary["selected_pair_index"] = observed["index"]
        summary["selected_pair_kind"] = observed["kind"]
        summary["login"] = observed["login"]
        summary["readings"] = observed["readings"]
        try:
            summary["write_health"] = dict(store.registered_sim_write_health())
        except Exception as exc:
            summary["write_health_error"] = f"{type(exc).__name__}: {exc}"
        observation_ready_to_pass = True
    except simnow_direct.SimNowDirectError as exc:
        summary.update({"status": "BLOCKED", "reason": exc.reason, "details": dict(exc.details)})
        result_code = EXIT_BLOCKED
    except LiveRejected as exc:
        summary.update({"status": "BLOCKED", "reason": exc.reason, "details": dict(exc.details)})
        if exc.reason == "cleanup_uncertain":
            summary["cleanup_status"] = "uncertain"
            summary["cleanup_error"] = dict(exc.details.get("cleanup_error") or {})
        result_code = exc.exit_code
    except Exception as exc:
        summary.update({"status": "BLOCKED", "reason": f"{type(exc).__name__}: {exc}"})
        result_code = EXIT_BLOCKED
    finally:
        if store is not None:
            try:
                close_health = store.stop(timeout=float(timeouts.get("stop_seconds") or 12.0))
            except Exception as exc:
                cleanup_error = _observation_cleanup_error(exc, phase="selected_store_stop")
            else:
                cleanup_error = _observation_close_health_error(close_health, phase="selected_store_stop")
            if cleanup_error is not None:
                _OBSERVATION_CLEANUP_KEEPALIVE.append(store)
                summary.update(
                    {
                        "status": "BLOCKED",
                        "reason": "cleanup_uncertain",
                        "cleanup_status": "uncertain",
                        "cleanup_error": cleanup_error,
                    }
                )
                for record in summary.get("admission_attempts", []):
                    if record.get("result") == "observed":
                        record.update({"cleanup_status": "uncertain", "cleanup_error": cleanup_error})
                        break
                observation_ready_to_pass = False
                result_code = EXIT_BLOCKED
            else:
                summary["cleanup_status"] = "closed"
                for record in summary.get("admission_attempts", []):
                    if record.get("result") == "observed":
                        record["cleanup_status"] = "closed"
                        break
                if observation_ready_to_pass:
                    summary["status"] = "LIVE_OBSERVE_PASS"
                    summary["boundary"] = "SESSION_AND_QUERY_OBSERVATION_ONLY_NOT_MARKET_OR_PROFITABILITY_EVIDENCE"
                    result_code = EXIT_PASS
        _write_summary()
        _json_print(summary)
    return result_code


def run_live(args) -> int:
    tier_decision = getattr(args, "tier_decision", None)
    tier_evidence = tier_decision.as_evidence() if tier_decision is not None else {}
    write_grant_result = (
        "requested_not_yet_admitted"
        if getattr(args, "allow_write", False)
        else "not_requested"
    )
    if not args.allow_write:
        _json_print(
            {
                "entry_tier": dict(tier_evidence or {}),
                "write_grant_result": write_grant_result,
                "status": "REJECTED",
                "mode": "live",
                "error": "write_consent_missing",
                "hint": "live C/P/F acceptance requires an explicit --allow-write grant",
            }
        )
        return EXIT_BLOCKED
    if sys.version_info[:2] != (3, 11):
        _json_print(
            {
                "entry_tier": dict(tier_evidence or {}),
                "write_grant_result": write_grant_result,
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
        _json_print(
            {
                "entry_tier": dict(tier_evidence or {}),
                "write_grant_result": write_grant_result,
                "status": "REJECTED",
                "mode": "live",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        return EXIT_BLOCKED
    live = dict(raw_config.get(LIVE_ADAPTER_KEY) or {})
    errors = _live_section_errors(live)
    if errors:
        _json_print(
            {
                "entry_tier": dict(tier_evidence or {}),
                "write_grant_result": write_grant_result,
                "status": "REJECTED",
                "mode": "live",
                "errors": errors,
            }
        )
        return EXIT_BLOCKED
    try:
        env = _load_env()
        _ensure_dev_sdk_path(strict=True)
    except LiveRejected as exc:
        _json_print(
            {
                "entry_tier": dict(tier_evidence or {}),
                "write_grant_result": write_grant_result,
                "status": "BLOCKED",
                "mode": "live",
                "reason": exc.reason,
                "details": exc.details,
            }
        )
        return exc.exit_code
    except Exception as exc:
        _json_print(
            {
                "entry_tier": dict(tier_evidence or {}),
                "write_grant_result": write_grant_result,
                "status": "BLOCKED",
                "mode": "live",
                "reason": f"{type(exc).__name__}: {exc}",
            }
        )
        return EXIT_BLOCKED

    candidate = dict(legacy_config.get("candidate") or {})
    budget = dict(legacy_config.get("budget") or {})
    timing = dict(legacy_config.get("timing") or {})
    strategy_params = dict(legacy_config.get("strategy_params") or {})
    try:
        legs: List[Tuple[str, str, str]] = []
        for key in ("future", "call", "put"):
            full_symbol = str(candidate.get(key) or "")
            code, leg_exchange = _split_symbol(full_symbol)
            legs.append((full_symbol, code, leg_exchange))
        if len({item[1] for item in legs}) != 3:
            raise LiveRejected("three_distinct_legs_required")
        if len({item[2] for item in legs}) != 1:
            raise LiveRejected("single_exchange_options_bundle_required")
    except LiveRejected as exc:
        _json_print(
            {
                "entry_tier": dict(tier_evidence or {}),
                "write_grant_result": write_grant_result,
                "status": "BLOCKED",
                "mode": "live",
                "reason": exc.reason,
                "details": exc.details,
            }
        )
        return exc.exit_code
    exchange = legs[0][2]

    timeouts = dict(live.get("timeouts") or {})
    policy = dict(live.get("policy") or {})
    drill_config = dict(live.get("drill") or {})
    run_seconds = float(args.run_seconds or timeouts.get("run_seconds") or 3600.0)
    if run_seconds > 7200.0:
        run_seconds = 7200.0
    run_id = (
        f"live-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        f"-{uuid.uuid4().hex[:8]}"
    )
    output_directory = Path(args.evidence_dir) if args.evidence_dir else (HERE / "evidence" / run_id)
    output_directory.mkdir(parents=True, exist_ok=True)
    summary: Dict[str, Any] = {
        "entry_tier": dict(tier_evidence or {}),
        "write_grant_result": write_grant_result,
        "schema_version": 1,
        "run_id": run_id,
        "example_id": "014_1_ctp_options_lowfreq",
        "mode": "live",
        "tier": "strict_feed_sealed_evidence",
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
        config_path = HERE / "config.yaml"
        config_digest = simnow_direct.canonical_sha256(
            {"config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest()}
        )
        identity_sha = simnow_direct.strategy_identity_sha256(
            HERE / "ctp_options_lowfreq_strategy.py",
            {
                "strategy_id": STRATEGY_ID,
                "instrument": "+".join(item[1] for item in legs),
                "exchange": exchange,
            },
        )
        rules_hash = simnow_direct.canonical_sha256(
            {
                "candidate": [item[0] for item in legs],
                "exchange": exchange,
                "kind": "czce-options-rules-v1",
            }
        )

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
                query_timeout = float(timeouts.get("query_seconds") or 8.0)
                account = _rows(attempt_store.registered_sim_query("account_result", timeout=query_timeout))
                positions = _rows(
                    attempt_store.registered_sim_query("positions_result", timeout=query_timeout)
                )
                orders = _rows(attempt_store.registered_sim_query("orders_result", timeout=query_timeout))
                open_rows = [row for row in positions if _position_is_open(row)]
                active_orders = [row for row in orders if _order_is_active(row)]
                if open_rows or active_orders:
                    raise LiveRejected(
                        "account_not_clean_for_pilot",
                        {
                            "positions_open_rows": len(open_rows),
                            "orders_active_rows": len(active_orders),
                            "pilot_requires_flat_and_no_active_orders": True,
                        },
                    )
                metadata = []
                commissions = []
                for full_symbol, code, leg_exchange in legs:
                    metadata.append(
                        _leg_metadata(attempt_store, code, leg_exchange, live, full_symbol, query_timeout)
                    )
                    commissions.append(_leg_commission(attempt_store, code, leg_exchange, query_timeout))
                starting_equity = 0.0
                if account:
                    try:
                        starting_equity = float(
                            _row_get(account[0], "Balance", "balance", default=0.0) or 0.0
                        )
                    except (TypeError, ValueError):
                        starting_equity = 0.0
                preflight = {
                    "login": login_facts,
                    "trading_day": str(login_facts.get("trading_day") or ""),
                    "account_rows": len(account),
                    "positions_open_rows": len(open_rows),
                    "orders_active_rows": len(active_orders),
                    "starting_equity": starting_equity,
                    "metadata": metadata,
                    "commissions": commissions,
                }
                arm_states: List[Dict[str, Any]] = []
                for index, (full_symbol, code, leg_exchange) in enumerate(legs):
                    if index > 0:
                        attempt_store.registered_sim_disarm("admission_verify_next_leg")
                    arm_result = attempt_store.registered_sim_arm(
                        instrument=code,
                        exchange=leg_exchange,
                        md_front=candidate_pair["md_front"],
                        strategy_identity_sha256=identity_sha,
                        execution_cycle_id=run_id,
                        preflight_sha256=simnow_direct.canonical_sha256(
                            {
                                "config_digest": config_digest,
                                "login": preflight["login"],
                                "metadata": metadata[index],
                                "account_rows": preflight["account_rows"],
                                "positions_open_rows": preflight["positions_open_rows"],
                                "orders_active_rows": preflight["orders_active_rows"],
                                "started_utc": _utc_iso(started_wall),
                            }
                        ),
                    )
                    arm_states.append(
                        {
                            "symbol": full_symbol,
                            "armed": bool(arm_result.get("armed")),
                            "gate_state": arm_result.get("state"),
                        }
                    )
                attempt_record["admission"] = "armed"
                attempt_record["legs"] = arm_states
                attempts.append(attempt_record)
                store = attempt_store
                armed = {
                    "candidate": candidate_pair,
                    "preflight": preflight,
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
        arm_states = armed["arm_states"]
        summary["environment"] = {
            "venue": "simnow",
            "front_selection": selection["receipt"],
            "selected_index": armed_candidate["index"],
            "selected_whitelisted": armed_candidate["whitelisted"],
            "legs": [item[0] for item in legs],
            "exchange": exchange,
            "environment_switched_after_write": False,
        }
        summary["preflight"] = {
            "trading_day": preflight["trading_day"],
            "connection_generation": preflight["login"].get("connection_generation"),
            "account_rows": preflight["account_rows"],
            "starting_equity": preflight["starting_equity"],
            "metadata": preflight["metadata"],
            "commission_sources": [item.get("source") for item in preflight["commissions"]],
            "pilot_account_flat_and_clean": True,
        }
        summary["admission"] = {
            "admitted": all(item["armed"] for item in arm_states),
            "legs": arm_states,
            "execution_cycle_id": run_id,
            "strategy_identity_sha256": identity_sha,
            "rules_hash": rules_hash,
            "gate_state": arm_states[-1].get("gate_state"),
        }
        if summary["admission"].get("admitted") is True:
            summary["write_grant_result"] = "admitted"

        # Run-scoped live clock: same identity for tick stamps, sealed-bar
        # evidence, the strategy's clock provider and the execution windows.
        clock = _LiveClock(
            generation=int(preflight["login"].get("connection_generation") or 0),
            rules_hash=rules_hash,
            source=f"iter42:{STRATEGY_ID}:registered-sim",
            validity_seconds=min(run_seconds + 600.0, 7200.0),
        )
        session_segment = f"{LIVE_SESSION_SEGMENT_PREFIX}:{preflight['trading_day']}"
        store.configure_live_tick_provenance(clock.provenance(session_segment=session_segment))
        provider = _LiveEvidenceProvider(clock.mapping, LIVE_CANDIDATE_ID, 900.0)
        summary["clock"] = {
            "domain": clock.domain,
            "generation": clock.generation,
            "rules_hash": rules_hash,
            "session_segment": session_segment,
            "mapping_id": clock.mapping.mapping_id,
            "synthetic": bool(clock.mapping.synthetic),
        }

        # Per-leg arm templates (one SDK admission per instrument, switched
        # strictly between writes), anchored on the first outbound leg.
        arm_templates = {}
        for index, (full_symbol, code, leg_exchange) in enumerate(legs):
            arm_templates[(code, leg_exchange)] = {
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
                        "rules_hash": rules_hash,
                        "started_utc": _utc_iso(started_wall),
                    }
                ),
            }
        store.registered_sim_configure_arm_templates(arm_templates)
        drill_direction = str(drill_config.get("direction") or "conversion").strip().lower()
        first_leg_code = legs[2][1] if drill_direction == "conversion" else legs[1][1]
        store.registered_sim_ensure_arm(first_leg_code, exchange)

        trigger = None
        if args.drill:
            delay = float(args.drill_delay_seconds if args.drill_delay_seconds is not None else 180.0)
            window = float(args.drill_window_seconds if args.drill_window_seconds is not None else 900.0)
            now_wall = time.time()
            trigger = {
                "trigger_id": f"drill-{uuid.uuid4().hex[:8]}",
                "direction": drill_direction,
                "trading_day": preflight["trading_day"],
                "not_before_utc": _utc_iso(now_wall + delay),
                "not_after_utc": _utc_iso(now_wall + delay + window),
                "not_before_epoch": now_wall + delay,
                "not_after_epoch": now_wall + delay + window,
            }
            summary["drill"] = dict(trigger)

        params: Dict[str, Any] = {
            "candidate_id": LIVE_CANDIDATE_ID,
            "future_symbol": legs[0][0],
            "call_symbol": legs[1][0],
            "put_symbol": legs[2][0],
            "strike": float(candidate["strike"]),
            "multiplier": float(candidate["multiplier"]),
            "discount": float(candidate["discount"]),
            "capital_limit": float(budget["capital_limit"]),
            "ordinary_limit": float(budget["ordinary_limit"]),
            "recovery_reserve": float(budget["recovery_reserve"]),
            "first_send_seconds": int(timing["first_send_seconds"]),
            "completion_seconds": int(timing["completion_seconds"]),
            "minimum_hold_seconds": int(timing["minimum_hold_seconds"]),
            "maximum_hold_seconds": int(timing["maximum_hold_seconds"]),
            "risk_bar_max_age_seconds": int(timing["risk_bar_max_age_seconds"]),
            "session_stop_entry_seconds": int(timing["session_stop_entry_seconds"]),
            "session_exit_seconds": int(timing["session_exit_seconds"]),
            "session_handover_seconds": int(timing["session_handover_seconds"]),
        }
        for name, value in strategy_params.items():
            params[name] = value
        params.update(
            {
                "rules_hash": rules_hash,
                "price_ticks": {
                    item[0]: float(meta["price_tick"])
                    for item, meta in zip(legs, preflight["metadata"])
                },
                "exchange_limits": {
                    item[0]: {
                        "lower": float(meta["lower_limit"]),
                        "upper": float(meta["upper_limit"]),
                        "source": "provider_instrument_query",
                    }
                    for item, meta in zip(legs, preflight["metadata"])
                },
                "exit_reserve": 0.0,
                "financing_reserve": 0.0,
                "model_reserve": 0.0,
                "clock_provider": clock.observation,
                "require_feed_bar_evidence": True,
                "bar_evidence_clock_mode": "live",
                "bar_evidence_clock_domain": clock.domain,
                "broker_position_mode": "dual_side",
                "entry_offset": "open",
                "exit_offset": "close",
            }
        )
        fee_verified = all(item.get("verified") for item in preflight["commissions"])
        if fee_verified:
            params["fee_schedule"] = _fee_schedule_from(
                preflight["commissions"][0],
                float(strategy_params.get("projected_entry_capital") or 0.0)
                / max(float(candidate["multiplier"]) * float(candidate["strike"]), 1.0),
                float(candidate["multiplier"]),
            )
            summary["fee_schedule_source"] = "provider_commission_rate"
        else:
            params["fee_schedule"] = None
            summary["fee_schedule_source"] = "round_trip_cost_fallback"
        if args.drill and trigger is not None:
            params["engineering_trigger"] = trigger
            try:
                params["max_holding_bars"] = int(drill_config.get("max_holding_bars") or 2)
            except (TypeError, ValueError):
                params["max_holding_bars"] = 2

        broker = BtApiBroker(
            store=store,
            provider="btapi",
            position_mode="dual_side",
            max_order_size=1,
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
        for full_symbol, code, _leg_exchange in legs:
            feed = store.getdata(
                dataname=code,
                timeframe=bt.TimeFrame.Minutes,
                compression=15,
                dispatch_bars=True,
                dispatch_ticks=False,
                backfill_start=False,
                qcheck=0.20,
                closed_bar_evidence_provider=provider,
            )
            cerebro.adddata(feed, name=full_symbol)
        _attach_trade_logger(cerebro, output_directory)
        strategy_cls = __import__("ctp_options_lowfreq_strategy").CtpOptionsLowfreqStrategy
        cerebro.addstrategy(strategy_cls, **params)

        previous_sigint = signal.getsignal(signal.SIGINT)
        previous_sigterm = signal.getsignal(signal.SIGTERM)
        stop_requested = {"flag": False}

        def _request_stop(_reason: str) -> None:
            stop_requested["flag"] = True

        signal.signal(signal.SIGINT, lambda *_a: _request_stop("operator_sigint"))
        signal.signal(signal.SIGTERM, lambda *_a: _request_stop("operator_sigterm"))

        deadline_mono = started_mono + run_seconds

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
                time.sleep(1.0)

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

        watchdog = threading.Thread(target=_watchdog, name="options-run-watchdog", daemon=True)
        idle_thread = threading.Thread(target=_idle_pump, name="options-idle-pump", daemon=True)
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
            builder = getattr(strategy_instance, "report", None)
            if callable(builder):
                try:
                    strategy_report = builder() or {}
                except Exception as exc:
                    strategy_report = {"report_error": f"{type(exc).__name__}: {exc}"}
        (output_directory / "strategy_report.json").write_text(
            json.dumps(strategy_report, ensure_ascii=False, sort_keys=True, default=str, indent=2) + "\n",
            encoding="utf-8",
        )
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
        entry_by_leg = {item[0]: 0.0 for item in legs}
        close_by_leg = {item[0]: 0.0 for item in legs}
        lookup = {item[1].upper(): item[0] for item in legs}
        scoped_trade_rows = 0
        for row in final_trades:
            ref = str(_row_get(row, "OrderRef", "order_ref", default="") or "").strip()
            if ref not in our_order_refs:
                continue
            scoped_trade_rows += 1
            code = str(_row_get(row, "InstrumentID", "instrument_id", default="") or "").upper()
            full_symbol = lookup.get(code)
            if full_symbol is None:
                continue
            offset = str(_row_get(row, "OffsetFlag", "offset_flag", default="") or "")
            volume = float(_row_get(row, "Volume", "volume", default=0) or 0)
            if offset == "0":
                entry_by_leg[full_symbol] += volume
            else:
                close_by_leg[full_symbol] += volume
        state = str(strategy_report.get("state") or "")
        basket_status = str(strategy_report.get("basket_status") or "")
        gate = store.registered_sim_status()
        arm_history = store.registered_sim_arm_history()
        summary.update(
            {
                "run": {
                    "started_utc": _utc_iso(started_wall),
                    "finished_utc": _utc_iso(time.time()),
                    "seconds": round(time.monotonic() - started_mono, 3),
                    "strategy_state": state,
                    "basket_status": basket_status,
                    "run_error": run_error,
                },
                "orders": {
                    "trade_rows": scoped_trade_rows,
                    "entry_by_leg": entry_by_leg,
                    "close_by_leg": close_by_leg,
                    "active_orders": len(residual_active),
                    "scoped_to_session": True,
                    "session_order_refs": len(our_order_refs),
                    "account_trade_rows": len(final_trades),
                },
                "arm_history": arm_history,
                "reconciliation": {
                    "open_position_rows": len(residual_open),
                    "account_rows": len(final_account),
                    "gate_state": gate,
                },
            }
        )
        entry_complete = all(entry_by_leg[item[0]] > 0 for item in legs)
        close_complete = all(close_by_leg[item[0]] >= entry_by_leg[item[0]] for item in legs)
        if scope_fault is not None:
            summary["status"] = "BLOCKED"
            summary["reason"] = scope_fault.reason
            summary["details"] = dict(scope_fault.details)
            code_exit = EXIT_BLOCKED
        elif run_error is not None:
            summary["status"] = "UNKNOWN"
            code_exit = EXIT_UNKNOWN
        elif residual_open or residual_active:
            summary["status"] = "UNKNOWN"
            summary["reason"] = "residual_exposure_after_run"
            code_exit = EXIT_UNKNOWN
            frozen = True
        elif state == "HALTED" or basket_status == "RECOVERY_REQUIRED":
            summary["status"] = "UNKNOWN"
            summary["reason"] = "strategy_halted_or_recovery_required"
            code_exit = EXIT_UNKNOWN
            frozen = True
        elif entry_complete and close_complete:
            summary["status"] = "PASS"
            code_exit = EXIT_PASS
        elif not any(entry_by_leg.values()) and not any(close_by_leg.values()):
            summary["status"] = "FAIL"
            summary["reason"] = "no_fill_round_trip"
            code_exit = EXIT_FAIL
        else:
            summary["status"] = "UNKNOWN"
            summary["reason"] = "partial_round_trip"
            code_exit = EXIT_UNKNOWN
        summary["tier"] = "fill_round_trip" if summary["status"] == "PASS" else "lifecycle_only"
        summary["writes_policy"] = {"max_actions": policy.get("max_actions"), "allow_write": True}
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
                if frozen:
                    store.registered_sim_freeze("residual_exposure_after_run")
                else:
                    store.registered_sim_disarm("run_finished")
            except Exception:
                pass
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
    mode.add_argument("--replay", action="store_true", help="offline frozen-fixture replay")
    mode.add_argument("--dry", action="store_true", help="force the offline config self-check")
    mode.add_argument("--live", action="store_true", help="strict live C/P/F adapter")
    parser.add_argument("--allow-write", action="store_true", help="grant bounded real write actions")
    parser.add_argument("--allow-dangerous", action="store_true", help="reserved; no dangerous action exists")
    parser.add_argument("--scenario", default=None, help="replay scenario name")
    parser.add_argument("--run-seconds", type=float, default=None, help="live run window override (bounded)")
    parser.add_argument("--evidence-dir", default=None)
    parser.add_argument("--drill", action="store_true", help="one-shot engineering drill entry")
    parser.add_argument("--drill-delay-seconds", type=float, default=None)
    parser.add_argument("--drill-window-seconds", type=float, default=None)
    # ``parse_known_args`` keeps unknown values out of any echoed error text.
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        _json_print(
            {
                "entry_tier": {},
                "write_grant_result": "not_evaluated",
                "status": "REJECTED",
                "error": "unknown_arguments_rejected",
                "unknown_count": len(unknown),
            }
        )
        return EXIT_BLOCKED
    if args.allow_dangerous:
        _json_print(
            {
                "entry_tier": {},
                "write_grant_result": "not_evaluated",
                "status": "REJECTED",
                "error": "no_dangerous_actions_defined",
            }
        )
        return EXIT_BLOCKED
    # ``config.entry.tier`` selects the channel; a mode flag may only keep or
    # lower it, and a malformed declaration is rejected before any provider side
    # effect instead of falling back toward live.
    try:
        tier_config = _load_raw_config()
    except Exception as exc:  # a config that cannot be read is not a live request
        _json_print(
            {
                "entry_tier": {},
                "write_grant_result": "not_evaluated",
                "status": "BLOCKED",
                "reason": f"tier_config_unreadable:{type(exc).__name__}",
            }
        )
        return EXIT_BLOCKED
    cli_tier = "live" if args.live else "replay" if args.replay else "dry" if args.dry else None
    decision = entry_tier.decide(tier_config, cli_tier)
    if entry_tier.invalid(decision) or entry_tier.conflict(decision):
        _json_print(
            {
                "status": "BLOCKED",
                "reason": decision.reason,
                "entry_tier": decision.as_evidence(),
                "write_grant_result": "not_evaluated_tier_unresolved",
            }
        )
        return EXIT_BLOCKED
    args.tier_decision = decision
    if decision.effective_tier == "live":
        # The write drill keeps its explicit grant; without a grant the live tier
        # becomes this zero-write observation session instead of refusing to start.
        return run_live(args) if args.allow_write else run_live_observe(args)
    if decision.effective_tier == "replay":
        return run_replay(
            args.scenario,
            Path(args.evidence_dir) if args.evidence_dir else None,
            decision.as_evidence(),
        )
    return run_dry(decision.as_evidence())


if __name__ == "__main__":
    # Script execution keeps this directory importable; the entry imports the
    # legacy engine lazily inside its functions only.
    raise SystemExit(main())

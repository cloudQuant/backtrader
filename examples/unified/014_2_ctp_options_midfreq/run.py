#!/usr/bin/env python
"""014_2 standard entry — dry self-check / offline replay / managed-runtime seam.

Usage (Python 3.11 required for the live tier; dry/replay need only the core):

    python run.py                          # dry: config + live-readiness report (no network)
    python run.py --replay [--scenario S]  # offline minute FQ2 fixture replay (0 network, 0 writes)
    python run.py --live                   # live OBSERVATION tier (no write path exists)

Exit codes: 0 PASS, 1 FAIL, 2 BLOCKED, 3 UNKNOWN.

The previous direct SimNow/registered-sim live implementation has been retired.
The live entry accepts only explicit SDK-owned provider configuration and host
runtime bindings through ``bt_api_py.managed_runtime_composition``. The CLI has
no trusted host-injection source and returns ``BLOCKED``. Even with an injected
host, this strategy remains unavailable until the SDK exposes multi-instrument
option rules and a qualified market clock, and Backtrader has an adapter for
the composed SDK facade. Offline replay remains a separate synthetic path.
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
REPO_ROOT = HERE.parents[2]
CHECKOUT_ROOT = HERE.parents[2]

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


def _ensure_dev_sdk_path(*, strict: bool = False) -> None:
    """Prefer the public bt_api_py and neutral bt_api_base dev sources."""
    import importlib.util

    root = Path(os.environ.get("BT_API_PY_ROOT") or "D:/bt_api_py").expanduser()
    candidates = (root / "bt_api" / "bt_api_base" / "src", root)
    for extra in reversed(candidates):
        if not extra.is_dir():
            continue
        text = str(extra)
        if text in sys.path:
            sys.path.remove(text)
        sys.path.insert(0, text)
    if not strict:
        return

    root_text = str(root.resolve()).replace("\\", "/").lower()
    for name in ("bt_api_py", "bt_api_base"):
        loaded = sys.modules.get(name)
        if loaded is not None:
            origin = getattr(loaded, "__file__", "") or ""
        else:
            try:
                found = importlib.util.find_spec(name)
            except (ImportError, ValueError):
                found = None
            origin = getattr(found, "origin", None)
        normalized = str(origin or "").replace("\\", "/").lower()
        if not normalized or root_text not in normalized:
            raise LiveRejected("sdk_origin_not_dev_source", {"module": name})


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
def run_replay(
    scenario: Optional[str],
    evidence_dir: Optional[Path],
    tier_evidence: Optional[Mapping[str, Any]] = None,
) -> int:
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
        "entry_tier": dict(tier_evidence or {}),
        "write_grant_result": "not_applicable_offline_tier",
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


def _run_managed_runtime_host(
    args: Any,
    *,
    access_mode: str,
    provider_configuration: Any = None,
    runtime_binding: Any = None,
    authorization_source: Any = None,
    operator_grant: Any = None,
    registry: Any = None,
    unavailable_capabilities: Tuple[str, ...],
) -> int:
    """Use only the SDK's explicit host-bound composition seam.

    The command-line example has no trusted runtime-owner injection channel, so
    it stops before importing provider code or reading credential inputs. An
    embedding host may pass SDK-issued configuration, runtime binding and any
    required authorization objects explicitly. Composition alone does not
    supply the missing Backtrader strategy, Store/Broker, option-rules or
    qualified market-clock contracts; those remain unavailable.
    """
    decision = getattr(args, "tier_decision", None)
    entry_tier = decision.as_evidence() if decision is not None else {}
    base = {
        "status": "BLOCKED",
        "mode": "live",
        "backend": "bt_api_py.managed_runtime_composition",
        "access_mode": access_mode,
        "entry_tier": dict(entry_tier),
        "strategy_dispatched": False,
        "unavailable_capabilities": list(unavailable_capabilities),
    }
    if provider_configuration is None or runtime_binding is None:
        _json_print({**base, "reason": "managed_runtime_host_injection_required"})
        return EXIT_BLOCKED

    try:
        _ensure_dev_sdk_path(strict=True)
        from bt_api_py.managed_runtime_composition import (
            ManagedRuntimeCompositionError,
            compose_managed_runtime,
        )
    except Exception:
        _json_print({**base, "reason": "sdk_managed_runtime_composition_unavailable"})
        return EXIT_BLOCKED

    try:
        composition = compose_managed_runtime(
            provider_configuration,
            runtime_binding=runtime_binding,
            access_mode=access_mode,
            authorization_source=authorization_source,
            operator_grant=operator_grant,
            registry=registry,
        )
    except ManagedRuntimeCompositionError as exc:
        _json_print({**base, "reason": exc.code})
        return EXIT_BLOCKED
    except Exception:
        _json_print({**base, "reason": "managed_runtime_composition_failed"})
        return EXIT_BLOCKED

    result = {
        **base,
        "reason": "backtrader_managed_strategy_adapter_unavailable",
        "sdk_route": composition.exchange_name,
        "runtime_composed": True,
        "write_grant_result": (
            "not_used_strategy_not_dispatched"
            if access_mode == "managed_execution"
            else "not_applicable_read_only"
        ),
    }
    try:
        composition.close()
    except ManagedRuntimeCompositionError as exc:
        result.update(
            status="UNKNOWN",
            reason=exc.code,
            composition_close="unconfirmed",
        )
        _json_print(result)
        return EXIT_UNKNOWN
    result["composition_close"] = "closed"
    _json_print(result)
    return EXIT_BLOCKED


def run_live(
    args,
    *,
    provider_configuration: Any = None,
    runtime_binding: Any = None,
    registry: Any = None,
) -> int:
    if getattr(args, "allow_write", False):
        _json_print(
            {
                "status": "BLOCKED",
                "mode": "live",
                "reason": "write_tier_not_implemented_for_decision_only_strategy",
                "entry_tier": getattr(
                    getattr(args, "tier_decision", None), "as_evidence", lambda: {}
                )(),
                "write_grant_result": "refused_no_order_path_by_contract",
            }
        )
        return EXIT_BLOCKED
    return _run_managed_runtime_host(
        args,
        access_mode="read_only",
        provider_configuration=provider_configuration,
        runtime_binding=runtime_binding,
        registry=registry,
        unavailable_capabilities=(
            "backtrader_managed_store_feed_adapter",
            "multi_instrument_option_runtime",
            "provider_issued_option_contract_rules",
            "verified_market_data_clock",
        ),
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replay", action="store_true", help="offline minute FQ2 fixture replay")
    mode.add_argument("--dry", action="store_true", help="force the offline config self-check")
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
        return run_live(args)
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

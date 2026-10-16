"""Read-only service route for the 015 tick/cohort public entry.

This path keeps the ordinary ``BtApiStore`` / ``BtApiFeed`` / Cerebro stack
open for a short observation. CTP quote identity and receive timestamps alone
do not supply the strategy's separately required trusted decision clock, so
the strategy records ``TRUSTED_NOW_INVALID`` and admits no cohort.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import threading
import time
import uuid
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


EXIT_BLOCKED = 2
_LEGS = ("future", "call", "put")


def _emit(runner: Any, payload: Mapping[str, Any]) -> None:
    runner._json_print(payload)


def _first_strategy(results: Any) -> Any:
    """Normalize Cerebro's ordinary and optimized result shapes safely."""

    if not results:
        return None
    first = results[0]
    if isinstance(first, (list, tuple)):
        return first[0] if first else None
    return first


def _decimal(value: Any, field: str) -> Decimal:
    if type(value) not in {str, int, float}:
        raise ValueError(f"service_{field}_invalid")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"service_{field}_invalid") from None
    if not result.is_finite() or result <= 0:
        raise ValueError(f"service_{field}_invalid")
    return result


def _contracts(live: Mapping[str, Any], bundle: Mapping[str, Any]) -> dict[str, str]:
    candidate = live.get("live_candidate")
    raw = candidate.get("contracts") if isinstance(candidate, Mapping) else None
    if not isinstance(raw, Mapping) or set(raw) != set(_LEGS):
        raise ValueError("service_contract_set_invalid")
    result: dict[str, str] = {}
    for role in _LEGS:
        full_symbol = raw.get(role)
        item = bundle.get(role)
        if type(full_symbol) is not str or not isinstance(item, Mapping):
            raise ValueError("service_contract_identity_invalid")
        exchange, separator, instrument_id = full_symbol.partition(".")
        if not separator or not exchange or not instrument_id or "." in instrument_id:
            raise ValueError("service_contract_identity_invalid")
        if exchange != item.get("exchange_id") or instrument_id != item.get("symbol"):
            raise ValueError("service_contract_bundle_mismatch")
        result[role] = full_symbol
    if len(set(result.values())) != len(_LEGS):
        raise ValueError("service_contract_set_invalid")
    return result


def _instruments(
    service: Mapping[str, Any], contracts: Mapping[str, str], instrument_type: Any
) -> tuple[Any, ...]:
    account = service.get("account")
    if not isinstance(account, Mapping):
        raise ValueError("service_account_invalid")
    resources = account.get("resource_by_leg")
    if not isinstance(resources, Mapping) or set(resources) != set(_LEGS):
        raise ValueError("service_resource_set_invalid")
    qty_unit = account.get("qty_unit")
    if type(qty_unit) is not str or not qty_unit.strip():
        raise ValueError("service_quantity_unit_invalid")
    result = []
    for role in _LEGS:
        exchange, instrument_id = contracts[role].split(".", 1)
        result.append(
            instrument_type(
                instrument_id,
                instrument_id=instrument_id,
                exchange_id=exchange,
                resource=resources[role],
                qty_unit=qty_unit,
            )
        )
    return tuple(result)


def _validate_metadata(
    live: Mapping[str, Any],
    bundle: Mapping[str, Any],
    contracts: Mapping[str, str],
    metadata: Mapping[str, Any],
) -> None:
    expected_all = live.get("instrument_metadata")
    if not isinstance(expected_all, Mapping):
        raise ValueError("service_instrument_metadata_invalid")
    for role in _LEGS:
        full_symbol = contracts[role]
        instrument_id = full_symbol.split(".", 1)[1]
        item = metadata.get(instrument_id)
        bundle_item = bundle[role]
        expected = expected_all.get(full_symbol)
        if item is None or not isinstance(expected, Mapping):
            raise ValueError("service_instrument_metadata_missing")
        if item.instrument_id != instrument_id or item.exchange_id != full_symbol.split(".", 1)[0]:
            raise ValueError("service_instrument_identity_mismatch")
        if _decimal(item.price_tick, "price_tick") != _decimal(bundle_item.get("tick_size"), "price_tick"):
            raise ValueError("service_fixture_metadata_mismatch")
        if _decimal(item.price_tick, "price_tick") != _decimal(expected.get("price_tick"), "price_tick"):
            raise ValueError("service_config_metadata_mismatch")
        if type(item.volume_multiple) is not int:
            raise ValueError("service_volume_multiple_invalid")
        if item.volume_multiple != int(_decimal(bundle_item.get("multiplier"), "volume_multiple")):
            raise ValueError("service_fixture_metadata_mismatch")
        if item.volume_multiple != int(_decimal(expected.get("volume_multiple"), "volume_multiple")):
            raise ValueError("service_config_metadata_mismatch")


def _descriptor_projection(descriptor: Any) -> dict[str, Any]:
    key = getattr(descriptor, "key", None)
    return {
        "key": key.to_dict() if callable(getattr(key, "to_dict", None)) else None,
        "stream_id": getattr(descriptor, "stream_id", None),
        "epoch": getattr(descriptor, "epoch", None),
        "source": getattr(descriptor, "source", None),
        "connection_generation": getattr(descriptor, "connection_generation", None),
        "clock_domain_id": getattr(descriptor, "clock_domain_id", None),
        "clock_source_session_id": getattr(descriptor, "clock_source_session_id", None),
        "clock_source": getattr(descriptor, "clock_source", None),
        "clock_qualification": "NOT_QUALIFIED",
    }


def run_live_service(args: Any, raw_config: Mapping[str, Any], decision: Any, runner: Any) -> int:
    """Run the actual 015 Backtrader observation using SDK service clients."""

    tier_evidence = decision.as_evidence() if decision is not None else {}
    if getattr(args, "allow_write", False):
        _emit(
            runner,
            {
                "status": "BLOCKED",
                "mode": "live",
                "backend": "service",
                "reason": "service_backend_is_read_only",
                "write_grant_result": "refused_service_backend_has_no_write_route",
                "entry_tier": tier_evidence,
                "cohort_admission": "NOT_ADMITTED",
                "hft_status": "NOT_ADMITTED",
                "external_request_counts": {"order_write": 0},
            },
        )
        return EXIT_BLOCKED

    summary: dict[str, Any] = {
        "schema_version": 1,
        "example_id": "015_ctp_options_highfreq",
        "mode": "live",
        "backend": "service",
        "status": "STARTING",
        "entry_tier": tier_evidence,
        "write_grant_result": "not_requested_observation_only",
        "trusted_now_status": "TRUSTED_NOW_INVALID",
        "cohort_admission": "NOT_ADMITTED",
        "confirmed_cohort_count": 0,
        "hft_status": "NOT_ADMITTED",
        "external_request_counts": {"order_write": 0},
    }
    output_dir: Path | None = None
    session: Any = None
    strategy_report: dict[str, Any] = {}
    run_error: str | None = None
    started = time.monotonic()

    try:
        live = raw_config.get(runner.LIVE_ADAPTER_KEY)
        if not isinstance(live, Mapping) or live.get("backend") != "service":
            raise ValueError("service_live_adapter_invalid")
        service = live.get("service")
        if not isinstance(service, Mapping):
            raise ValueError("service_config_missing")
        timeout_config = dict(live.get("timeouts") or {})
        run_seconds = float(
            getattr(args, "run_seconds", None)
            or timeout_config.get("run_seconds")
            or 60.0
        )
        if not math.isfinite(run_seconds) or run_seconds <= 0:
            raise ValueError("service_run_window_invalid")
        run_seconds = min(run_seconds, 7200.0)

        legacy = runner._load_legacy()
        legacy_config, _config_path = legacy.load_config()
        observation_config = legacy.effective_config(
            legacy_config, mode="shadow", purpose="observation"
        )
        fixture, _fixture_path, fixture_hash = legacy.load_fixture(observation_config)
        bundle = legacy.validate_bundle(fixture, observation_config)
        contracts = _contracts(live, bundle)
        params = legacy._strategy_params(observation_config, bundle)
        params.update(
            mode="engineering_observation",
            candidate_id=runner.LIVE_CANDIDATE_ID,
            timing_provider=None,
            cohort_now_provider=None,
        )

        from backtrader_runtime.service_observation import (
            ServiceObservationInstrument,
            open_service_read_session,
        )
        import backtrader as bt

        instruments = _instruments(service, contracts, ServiceObservationInstrument)
        run_id = (
            f"live-service-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            f"-{uuid.uuid4().hex[:8]}"
        )
        output_dir = Path(args.evidence_dir) if args.evidence_dir else (
            Path(runner.HERE) / "evidence" / run_id
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        summary.update(
            run_id=run_id,
            evidence_directory=str(output_dir),
            live_window_seconds=run_seconds,
            strategy_bundle={
                "symbols": list(params["symbols"]),
                "bundle_hash": str(params["bundle_hash"]),
                "fixture_sha256": fixture_hash,
            },
        )

        with open_service_read_session(
            service,
            instruments=instruments,
            allow_write=False,
            timeout_seconds=float(timeout_config.get("stop_seconds") or 10.0),
        ) as session:
            metadata_by_name = session.metadata
            _validate_metadata(live, bundle, contracts, metadata_by_name)
            descriptors: dict[str, Any] = {}
            metadata_projection: dict[str, Any] = {}
            for role in _LEGS:
                name = contracts[role].split(".", 1)[1]
                descriptor = session.subscribe(name)
                descriptors[role] = descriptor
                metadata_projection[role] = {
                    "instrument_id": metadata_by_name[name].instrument_id,
                    "exchange_id": metadata_by_name[name].exchange_id,
                    "asset_type": metadata_by_name[name].asset_type,
                    "price_tick": metadata_by_name[name].price_tick,
                    "volume_multiple": metadata_by_name[name].volume_multiple,
                    "source_descriptor": _descriptor_projection(descriptor),
                }

            account_view = session.account_view
            account_observation = account_view.observation
            summary["service_session"] = {
                "runtime_state": session.runtime.state,
                "account_snapshot_id_present": bool(account_view.snapshot_id),
                "account_session_generation_present": bool(account_view.session_generation),
                "account_coverage_count": len(account_observation.coverage),
                "position_rows": len(account_observation.positions),
                "open_order_rows": len(account_observation.open_orders or ()),
                "instrument_metadata": metadata_projection,
                "market_subscriptions": len(descriptors),
            }

            account = service.get("account") or {}
            store = session.store
            broker = store.getbroker(
                market_data_only=True,
                position_mode=str(account.get("position_mode") or "net"),
                max_order_size=1,
                cash_check_enabled=True,
                sdk_preflight=False,
                require_complete_ctp_evidence=False,
                force_refresh_queries=False,
                position_sync_policy="startup",
                account_refresh_interval=3600.0,
                open_orders_refresh_interval=3600.0,
                flatten_on_stop=False,
                shutdown_timeout=float(timeout_config.get("stop_seconds") or 10.0),
            )
            cerebro = bt.Cerebro(stdstats=False, quicknotify=True, runonce=False)
            cerebro.setbroker(broker)
            for role in _LEGS:
                full_symbol = contracts[role]
                name = full_symbol.split(".", 1)[1]
                feed = store.getdata(
                    dataname=name,
                    timeframe=bt.TimeFrame.Ticks,
                    compression=1,
                    backfill_start=False,
                    dispatch_ticks=True,
                    dispatch_bars=False,
                    qcheck=0.01,
                    price_tick=float(bundle[role]["tick_size"]),
                )
                cerebro.adddata(feed, name=name)
            module_name = (
                f"{runner.__package__}.ctp_options_highfreq_strategy"
                if runner.__package__ else "ctp_options_highfreq_strategy"
            )
            import importlib

            strategy_module = importlib.import_module(module_name)
            try:
                Path(strategy_module.__file__).resolve().relative_to(Path(runner.HERE).resolve())
            except (OSError, ValueError):
                raise ValueError("service_strategy_origin_not_example") from None
            strategy_cls = strategy_module.CtpOptionsHighfreqStrategy
            cerebro.addstrategy(strategy_cls, **params)

            finished = threading.Event()

            def stop_window() -> None:
                if finished.wait(run_seconds):
                    return
                while not finished.is_set():
                    cerebro.runstop()
                    if finished.wait(0.05):
                        return

            stopper = threading.Thread(target=stop_window, name="015-service-window-stop", daemon=True)
            stopper.start()
            try:
                results = cerebro.run()
                strategy = _first_strategy(results)
            except Exception as exc:
                run_error = type(exc).__name__
                strategy = None
            finally:
                finished.set()
                stopper.join(timeout=2.0)
            if stopper.is_alive():
                run_error = run_error or "StopperJoinUnconfirmed"
            if strategy is not None:
                strategy_report = strategy.replay_report()

            rejected = dict(strategy_report.get("reject_counts") or {})
            tick_counts = dict(strategy_report.get("tick_counts") or {})
            trusted_now_invalid = int(rejected.get("TRUSTED_NOW_INVALID", 0)) > 0
            summary.update(
                status="BLOCKED",
                reason=(
                    "service_trusted_now_unavailable"
                    if trusted_now_invalid
                    else "service_tick_clock_unqualified"
                ),
                trusted_now_status="TRUSTED_NOW_INVALID" if trusted_now_invalid else "UNOBSERVED",
                cohort_admission="NOT_ADMITTED",
                confirmed_cohort_count=int(strategy_report.get("confirmed_cohorts") or 0),
                hft_status=str(strategy_report.get("hft_status") or "NOT_ADMITTED"),
                strategy_observation={
                    "strategy_created": strategy is not None,
                    "run_error_type": run_error,
                    "tick_callback_count": int((strategy_report.get("callback_counts") or {}).get("tick", 0)),
                    "tick_counts": tick_counts,
                    "reject_counts": rejected,
                    "ordinary_intent_count": int(strategy_report.get("ordinary_intent_count") or 0),
                    "timing_provider_status": strategy_report.get("timing_provider_status"),
                },
                provider_operations={
                    "account_snapshot": "COMPLETE",
                    "instrument_metadata": len(metadata_projection),
                    "market_subscriptions": len(descriptors),
                },
                external_request_counts={"order_write": 0},
            )
            (output_dir / "strategy_report.json").write_text(
                json.dumps(strategy_report, ensure_ascii=False, sort_keys=True, default=str, indent=2) + "\n",
                encoding="utf-8",
            )

        cleanup = getattr(session, "cleanup_report", {})
        cleanup_status = cleanup.get("status", "closed") if isinstance(cleanup, Mapping) else "closed"
        summary["cleanup_status"] = cleanup_status
        if cleanup_status not in {"closed", "CLOSED", "PASS"}:
            summary.update(status="BLOCKED", reason="service_cleanup_uncertain")
    except Exception as exc:
        summary.update(
            status="BLOCKED",
            reason="service_backend_failed",
            error_type=type(exc).__name__,
            error_code=getattr(exc, "code", None) if re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_]{0,79}", str(getattr(exc, "code", ""))
            ) else None,
            external_request_counts={"order_write": 0},
            cohort_admission="NOT_ADMITTED",
            hft_status="NOT_ADMITTED",
        )
        if session is not None:
            cleanup = getattr(session, "cleanup_report", {})
            if isinstance(cleanup, Mapping):
                summary["cleanup_status"] = cleanup.get("status", "unconfirmed")
    finally:
        summary.setdefault("strategy_observation", {}).setdefault(
            "elapsed_seconds", round(time.monotonic() - started, 3)
        )
        summary["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        if output_dir is not None:
            (output_dir / "run.json").write_text(
                json.dumps(summary, ensure_ascii=False, sort_keys=True, default=str, indent=2) + "\n",
                encoding="utf-8",
            )
        _emit(runner, summary)
    return EXIT_BLOCKED

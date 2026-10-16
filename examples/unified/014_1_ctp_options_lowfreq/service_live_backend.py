"""Read-only service route for the 014_1 three-leg live entry.

The service session supplies the ordinary SDK clients and a ``ServiceReadProxy``
to the same ``BtApiStore`` / ``BtApiFeed`` / Cerebro path as the example's
strategy.  The current CTP feed has source identity but no qualified receive
clock mapping, so no closed bar is promoted to a trusted ``BarEvidence`` and
this route always remains ``NOT_QUALIFIED`` with zero writes.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


EXIT_BLOCKED = 2
EXIT_UNKNOWN = 3
_LEG_NAMES = ("future", "call", "put")


def _emit(runner_module: Any, summary: Mapping[str, Any]) -> None:
    runner_module._json_print(summary)


def _first_strategy(results: Any) -> Any:
    """Normalize Cerebro's ordinary and optimized result shapes safely."""

    if not results:
        return None
    first = results[0]
    if isinstance(first, (list, tuple)):
        return first[0] if first else None
    return first


def _config_code(value: Any, field: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"service_{field}_invalid")
    return value


def _positive_decimal(value: Any, field: str) -> Decimal:
    if type(value) not in {int, float, str} or type(value) is bool:
        raise ValueError(f"service_{field}_invalid")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"service_{field}_invalid") from None
    if not number.is_finite() or number <= 0:
        raise ValueError(f"service_{field}_invalid")
    return number


def _contracts(live: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, str]:
    item = live.get("live_candidate")
    if not isinstance(item, Mapping):
        raise ValueError("service_live_candidate_invalid")
    raw = item.get("contracts")
    if not isinstance(raw, Mapping) or set(raw) != set(_LEG_NAMES):
        raise ValueError("service_contract_set_invalid")
    contracts: dict[str, str] = {}
    for leg in _LEG_NAMES:
        full_symbol = _config_code(raw.get(leg), "contract")
        if full_symbol != candidate.get(leg):
            raise ValueError("service_candidate_identity_mismatch")
        exchange, separator, instrument_id = full_symbol.partition(".")
        if not separator or not exchange or not instrument_id or "." in instrument_id:
            raise ValueError("service_contract_identity_invalid")
        contracts[leg] = full_symbol
    if len({contracts[leg].split(".", 1)[1] for leg in _LEG_NAMES}) != len(_LEG_NAMES):
        raise ValueError("service_contract_set_invalid")
    exchanges = {contracts[leg].split(".", 1)[0] for leg in _LEG_NAMES}
    if len(exchanges) != 1 or item.get("exchange") not in exchanges:
        raise ValueError("service_contract_exchange_invalid")
    return contracts


def _service_instruments(service: Mapping[str, Any], contracts: Mapping[str, str], instrument_type: Any):
    account = service.get("account")
    if not isinstance(account, Mapping):
        raise ValueError("service_account_invalid")
    resources = account.get("resource_by_leg")
    if not isinstance(resources, Mapping) or set(resources) != set(_LEG_NAMES):
        raise ValueError("service_account_resource_set_invalid")
    qty_unit = _config_code(account.get("qty_unit"), "quantity_unit")
    result = []
    for leg in _LEG_NAMES:
        exchange, instrument_id = contracts[leg].split(".", 1)
        result.append(
            instrument_type(
                instrument_id,
                instrument_id=instrument_id,
                exchange_id=exchange,
                resource=resources[leg],
                qty_unit=qty_unit,
            )
        )
    return tuple(result)


def _metadata_projection(item: Any, descriptor: Any) -> dict[str, Any]:
    key = getattr(descriptor, "key", None)
    instrument = getattr(key, "instrument", None)
    return {
        "instrument_id": item.instrument_id,
        "exchange_id": item.exchange_id,
        "asset_type": item.asset_type,
        "price_tick": item.price_tick,
        "volume_multiple": item.volume_multiple,
        "account_session_generation": item.account_session_generation,
        "connection_generation": item.source_connection_generation,
        "market_source_descriptor": {
            "key": key.to_dict() if callable(getattr(key, "to_dict", None)) else None,
            "instrument_id": getattr(instrument, "instrument_id", None),
            "native_symbol": getattr(instrument, "native_symbol", None),
            "stream_id": getattr(descriptor, "stream_id", None),
            "epoch": getattr(descriptor, "epoch", None),
            "source": getattr(descriptor, "source", None),
            "connection_generation": getattr(descriptor, "connection_generation", None),
            "clock_domain_id": getattr(descriptor, "clock_domain_id", None),
            "clock_source_session_id": getattr(descriptor, "clock_source_session_id", None),
            "clock_source": getattr(descriptor, "clock_source", None),
            "clock_qualification": "NOT_QUALIFIED",
        },
    }


def _validate_provider_metadata(
    live: Mapping[str, Any], contracts: Mapping[str, str], metadata: Mapping[str, Any]
) -> None:
    expected_all = live.get("instrument_metadata")
    if not isinstance(expected_all, Mapping):
        raise ValueError("service_instrument_metadata_invalid")
    for leg in _LEG_NAMES:
        full_symbol = contracts[leg]
        instrument_id = full_symbol.split(".", 1)[1]
        item = metadata.get(instrument_id)
        expected = expected_all.get(full_symbol)
        if item is None or not isinstance(expected, Mapping):
            raise ValueError("service_instrument_metadata_missing")
        if item.instrument_id != instrument_id or item.exchange_id != full_symbol.split(".", 1)[0]:
            raise ValueError("service_instrument_identity_mismatch")
        if (
            _positive_decimal(item.price_tick, "price_tick")
            != _positive_decimal(expected.get("price_tick"), "price_tick")
            or type(item.volume_multiple) is not int
            or item.volume_multiple != int(_positive_decimal(expected.get("volume_multiple"), "volume_multiple"))
        ):
            raise ValueError("service_instrument_metadata_mismatch")


def _descriptor_domain(descriptors: Mapping[str, Any]) -> str:
    if set(descriptors) != set(_LEG_NAMES):
        raise ValueError("service_market_descriptor_set_invalid")
    domains = {getattr(item, "clock_domain_id", None) for item in descriptors.values()}
    sessions = {getattr(item, "clock_source_session_id", None) for item in descriptors.values()}
    generations = {getattr(item, "connection_generation", None) for item in descriptors.values()}
    sources = {getattr(item, "clock_source", None) for item in descriptors.values()}
    if any(len(values) != 1 or None in values for values in (domains, sessions, generations, sources)):
        raise ValueError("service_market_descriptor_session_mismatch")
    return str(next(iter(domains)))


def _strategy_params(
    runner_module: Any,
    legacy_config: Mapping[str, Any],
    live: Mapping[str, Any],
    contracts: Mapping[str, str],
    metadata: Mapping[str, Any],
    clock_domain: str,
) -> tuple[dict[str, Any], str]:
    candidate = dict(legacy_config.get("candidate") or {})
    budget = dict(legacy_config.get("budget") or {})
    strategy_params = dict(legacy_config.get("strategy_params") or {})
    metadata_rows = {
        leg: metadata[contracts[leg].split(".", 1)[1]] for leg in _LEG_NAMES
    }
    rules_payload = {
        "candidate": [contracts[leg] for leg in _LEG_NAMES],
        "exchange": contracts["future"].split(".", 1)[0],
        "kind": "czce-options-rules-v1",
    }
    rules_hash = hashlib.sha256(
        json.dumps(
            rules_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    params: dict[str, Any] = {
        "candidate_id": runner_module.LIVE_CANDIDATE_ID,
        "future_symbol": contracts["future"],
        "call_symbol": contracts["call"],
        "put_symbol": contracts["put"],
        "strike": float(candidate["strike"]),
        "multiplier": float(candidate["multiplier"]),
        "discount": float(candidate["discount"]),
        "capital_limit": float(budget["capital_limit"]),
        "ordinary_limit": float(budget["ordinary_limit"]),
        "recovery_reserve": float(budget["recovery_reserve"]),
        **strategy_params,
        "rules_hash": rules_hash,
        "price_ticks": {
            contracts[leg]: float(_positive_decimal(metadata_rows[leg].price_tick, "price_tick"))
            for leg in _LEG_NAMES
        },
        # Descriptor equality supplies source identity only. No synthetic or
        # process-wall clock is installed as a decision clock.
        "clock_provider": None,
        "require_feed_bar_evidence": True,
        "bar_evidence_clock_mode": "live",
        "bar_evidence_clock_domain": clock_domain,
        "broker_position_mode": str(
            ((live.get("service") or {}).get("account") or {}).get("position_mode") or ""
        ),
        "entry_offset": "open",
        "exit_offset": "close",
        "exchange_limits": None,
    }
    params["max_pending_feed_decisions"] = int(
        ((live.get("observation") or {}).get("max_pending_decisions") or 8)
    )
    if not float(params.get("projected_entry_capital") or 0.0):
        params["projected_entry_capital"] = float(budget.get("path_requirement") or 1.0)
    return params, rules_hash


def run_live_service(args: Any, raw_config: Mapping[str, Any], decision: Any, runner_module: Any) -> int:
    """Run the ordinary three-feed Backtrader observation on the read proxy."""

    decision_evidence = decision.as_evidence() if decision is not None else {}
    if getattr(args, "allow_write", False):
        _emit(
            runner_module,
            {
                "status": "BLOCKED",
                "mode": "live",
                "backend": "service",
                "reason": "service_backend_is_read_only",
                "write_grant_result": "refused_service_backend_has_no_write_route",
                "entry_tier": dict(decision_evidence),
                "clock_qualification": "NOT_QUALIFIED",
                "external_request_counts": {"order_write": 0},
            },
        )
        return EXIT_BLOCKED
    if os.sys.version_info[:2] != (3, 11):
        _emit(
            runner_module,
            {
                "status": "BLOCKED",
                "mode": "live",
                "backend": "service",
                "reason": "live_tier_requires_python_3_11",
                "current": f"{os.sys.version_info.major}.{os.sys.version_info.minor}",
                "entry_tier": dict(decision_evidence),
                "clock_qualification": "NOT_QUALIFIED",
                "external_request_counts": {"order_write": 0},
            },
        )
        return EXIT_BLOCKED

    summary: dict[str, Any] = {
        "schema_version": 1,
        "example_id": "014_1_ctp_options_lowfreq",
        "mode": "live",
        "channel": "observe",
        "backend": "service",
        "tier": "service_feed_sealed_observation",
        "status": "STARTING",
        "entry_tier": dict(decision_evidence),
        "write_grant_result": "not_requested_observation_only",
        "clock_qualification": "NOT_QUALIFIED",
        "clock_reason": "ctp_receive_clock_mapping_unavailable",
        "source_identity_is_clock_qualification": False,
        "external_request_counts": {"order_write": 0},
    }
    output_directory: Path | None = None
    session: Any = None
    broker: Any = None
    store: Any = None
    run_exception: str | None = None
    strategy_report: dict[str, Any] = {}
    result_code = EXIT_BLOCKED
    started_mono = time.monotonic()

    try:
        live = raw_config.get(runner_module.LIVE_ADAPTER_KEY)
        if not isinstance(live, Mapping) or live.get("backend") != "service":
            raise ValueError("service_live_adapter_invalid")
        service = live.get("service")
        if not isinstance(service, Mapping):
            raise ValueError("service_config_missing")
        legacy = runner_module._load_legacy()
        legacy_config = legacy.load_config()
        candidate = dict(legacy_config.get("candidate") or {})
        contracts = _contracts(live, candidate)
        instrument_to_leg = {
            contracts[leg].split(".", 1)[1]: leg for leg in _LEG_NAMES
        }
        if len(instrument_to_leg) != len(_LEG_NAMES):
            raise ValueError("service_contract_set_invalid")
        timeout_config = dict(live.get("timeouts") or {})
        run_seconds = float(
            getattr(args, "run_seconds", None)
            or timeout_config.get("run_seconds")
            or 60.0
        )
        if not math.isfinite(run_seconds) or run_seconds <= 0:
            raise ValueError("service_run_window_invalid")
        run_seconds = min(run_seconds, 7200.0)

        from backtrader_runtime.service_observation import open_service_read_session
        from backtrader_runtime.service_observation import ServiceObservationInstrument
        import backtrader as bt

        instruments = _service_instruments(service, contracts, ServiceObservationInstrument)
        run_id = (
            f"live-service-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            f"-{uuid.uuid4().hex[:8]}"
        )
        output_directory = Path(args.evidence_dir) if args.evidence_dir else (
            Path(runner_module.HERE) / "evidence" / run_id
        )
        output_directory.mkdir(parents=True, exist_ok=True)
        summary.update(run_id=run_id, evidence_directory=str(output_directory), live_window_seconds=run_seconds)

        with open_service_read_session(
            service,
            instruments=instruments,
            allow_write=False,
            timeout_seconds=float(timeout_config.get("stop_seconds") or 10.0),
        ) as session:
            store = session.store
            descriptors = {}
            metadata_by_leg = {}
            metadata_projection = {}
            for leg in _LEG_NAMES:
                instrument_id = contracts[leg].split(".", 1)[1]
                descriptor = session.subscribe(instrument_id)
                descriptors[leg] = descriptor
                item = session.metadata[instrument_id]
                metadata_by_leg[leg] = item
                expected_resource = ((service.get("account") or {}).get("resource_by_leg") or {}).get(leg)
                if isinstance(expected_resource, Mapping) and expected_resource.get("product_type") != item.asset_type:
                    raise ValueError("service_resource_product_mismatch")
                metadata_projection[leg] = _metadata_projection(item, descriptor)
            _validate_provider_metadata(live, contracts, session.metadata)
            clock_domain = _descriptor_domain(descriptors)
            params, rules_hash = _strategy_params(
                runner_module, legacy_config, live, contracts,
                {contracts[leg].split(".", 1)[1]: metadata_by_leg[leg] for leg in _LEG_NAMES},
                clock_domain,
            )

            account_view = session.account_view
            account_observation = account_view.observation
            summary.update(
                service_session={
                    "runtime_state": session.runtime.state,
                    "account_snapshot_id_present": bool(account_view.snapshot_id),
                    "account_session_generation_present": bool(account_view.session_generation),
                    "account_coverage_count": len(account_observation.coverage),
                    "position_rows": len(account_observation.positions),
                    "open_order_rows": len(account_observation.open_orders or ()),
                    "metadata": metadata_projection,
                },
                strategy={
                    "strategy_id": runner_module.STRATEGY_ID,
                    "candidate_id": runner_module.LIVE_CANDIDATE_ID,
                    "contracts": contracts,
                    "rules_hash": rules_hash,
                },
                provider_operations={
                    "account_snapshot": "COMPLETE",
                    "instrument_metadata": len(metadata_by_leg),
                    "market_subscriptions": len(descriptors),
                },
            )

            broker = store.getbroker(
                market_data_only=True,
                position_mode=str((service.get("account") or {}).get("position_mode") or "net"),
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
            for leg in _LEG_NAMES:
                full_symbol = contracts[leg]
                instrument_id = full_symbol.split(".", 1)[1]
                feed = store.getdata(
                    dataname=instrument_id,
                    timeframe=bt.TimeFrame.Minutes,
                    compression=int((legacy_config.get("strategy_params") or {}).get("bar_minutes") or 15),
                    dispatch_bars=True,
                    dispatch_ticks=False,
                    backfill_start=False,
                    qcheck=0.1,
                    closed_bar_quote_capture=True,
                    closed_bar_quote_limit=int((live.get("observation") or {}).get("quote_limit") or 240),
                )
                cerebro.adddata(feed, name=full_symbol)
            strategy_cls = runner_module._load_strategy_class() if callable(
                getattr(runner_module, "_load_strategy_class", None)
            ) else None
            if strategy_cls is None:
                module_name = (
                    f"{runner_module.__package__}.ctp_options_lowfreq_strategy"
                    if runner_module.__package__ else "ctp_options_lowfreq_strategy"
                )
                import importlib

                module = importlib.import_module(module_name)
                try:
                    Path(module.__file__).resolve().relative_to(Path(runner_module.HERE).resolve())
                except (OSError, ValueError):
                    raise ValueError("service_strategy_origin_not_example") from None
                strategy_cls = module.CtpOptionsLowfreqStrategy
            cerebro.addstrategy(strategy_cls, **params)
            attach = getattr(runner_module, "_attach_trade_logger", None)
            if callable(attach):
                attach(cerebro, output_directory)

            finished = threading.Event()

            def stop_window() -> None:
                if finished.wait(run_seconds):
                    return
                while not finished.is_set():
                    cerebro.runstop()
                    if finished.wait(0.05):
                        return

            stopper = threading.Thread(target=stop_window, name="0141-service-window-stop", daemon=True)
            stopper.start()
            try:
                run_results = cerebro.run()
                strategy = _first_strategy(run_results)
            except Exception as exc:
                run_exception = type(exc).__name__
                strategy = None
            finally:
                finished.set()
                stopper.join(timeout=2.0)
            if stopper.is_alive():
                run_exception = run_exception or "StopperJoinUnconfirmed"
            if strategy is not None:
                try:
                    strategy_report = strategy.report() or {}
                except Exception as exc:
                    strategy_report = {"report_error": type(exc).__name__}
            (output_directory / "strategy_report.json").write_text(
                json.dumps(strategy_report, ensure_ascii=False, sort_keys=True, default=str, indent=2) + "\n",
                encoding="utf-8",
            )
            summary["run"] = {
                "seconds": round(time.monotonic() - started_mono, 3),
                "run_error_type": run_exception,
                "strategy_created": strategy is not None,
            }
            summary["observation"] = {
                "bar_cohorts": len((strategy_report.get("evidence") or {}).get("bar_cohorts.jsonl", [])),
                "barrier_clock_mode": (strategy_report.get("barrier") or {}).get("clock_mode"),
                "barrier_clock_domain": (strategy_report.get("barrier") or {}).get("clock_domain"),
                "rejections": list(strategy_report.get("rejections") or []),
            }
            summary.update(
                status="BLOCKED",
                reason="service_clock_mapping_unqualified" if run_exception is None else "service_cerebro_run_failed",
                clock_qualification="NOT_QUALIFIED",
                external_request_counts={"order_write": 0},
            )
        cleanup = getattr(session, "cleanup_report", {}) if session is not None else {}
        summary["cleanup_status"] = cleanup.get("status", "closed") if isinstance(cleanup, Mapping) else "closed"
        if summary["cleanup_status"] not in {"closed", "CLOSED", "PASS"}:
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
            clock_qualification="NOT_QUALIFIED",
        )
        if session is not None:
            cleanup = getattr(session, "cleanup_report", {})
            if isinstance(cleanup, Mapping):
                summary["cleanup_status"] = cleanup.get("status", "unconfirmed")
        result_code = EXIT_BLOCKED
    else:
        result_code = EXIT_BLOCKED
    finally:
        summary.setdefault("run", {}).setdefault("seconds", round(time.monotonic() - started_mono, 3))
        summary["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        if output_directory is not None:
            (output_directory / "run.json").write_text(
                json.dumps(summary, ensure_ascii=False, sort_keys=True, default=str, indent=2) + "\n",
                encoding="utf-8",
            )
        _emit(runner_module, summary)
    return result_code

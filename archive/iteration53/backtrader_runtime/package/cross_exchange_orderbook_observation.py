"""Read-only order-book observation for the two 012 cross-exchange examples.

Each exchange uses its own explicitly configured SDK session and account owner.
The result is an observation report only: it is not a synchronized opportunity,
strategy admission, write grant, or order path.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


_LEGS = (
    ("okx", "BTC-USDT-SWAP"),
    ("binance", "BTCUSDT"),
)


@dataclass(frozen=True)
class _LegPlan:
    leg: str
    symbol: str
    service: Mapping[str, Any]
    account_key: Any
    resource: Any
    market_key: Any
    qty_unit: str


def _text(value: Any) -> bool:
    return type(value) is str and bool(value) and value == value.strip()


def _leg_token(value: str) -> str:
    return value.casefold().replace("___", "_").split("_", 1)[0].split("-", 1)[0]


def _plan_leg(
    leg: str,
    symbol: str,
    config_path: str,
    *,
    strategy_id: str,
    depth: int,
):
    from backtrader_runtime import service_observation as sdk_observation

    service = sdk_observation.load_service_observation_config(config_path)
    identity = service.get("identity")
    account = service.get("account")
    market = service.get("market")
    if not isinstance(identity, Mapping) or identity.get("strategy_ref") != strategy_id:
        raise sdk_observation.ServiceObservationError("STRATEGY_IDENTITY_MISMATCH")
    if not isinstance(account, Mapping) or not isinstance(market, Mapping):
        raise sdk_observation.ServiceObservationError("SERVICE_SCOPE_CONFIG_INVALID")

    raw_key = account.get("key")
    if not isinstance(raw_key, Mapping):
        raise sdk_observation.ServiceObservationError("ACCOUNT_IDENTITY_INVALID")
    # The service's own authenticated AccountKey check remains authoritative.
    # These leg checks prevent a valid but wrongly routed account config from
    # being presented under the opposite exchange label.
    if (
        not _text(raw_key.get("provider"))
        or not _text(raw_key.get("venue"))
        or _leg_token(raw_key["provider"]) != leg
        or _leg_token(raw_key["venue"]) != leg
    ):
        raise sdk_observation.ServiceObservationError("ACCOUNT_LEG_IDENTITY_MISMATCH")

    resource_by_leg = account.get("resource_by_leg")
    coverage_raw = account.get("required_coverage")
    if (
        not isinstance(resource_by_leg, Mapping)
        or set(resource_by_leg) != {leg}
        or type(coverage_raw) not in (list, tuple)
        or not coverage_raw
        or len(coverage_raw) > 2048
    ):
        raise sdk_observation.ServiceObservationError("ACCOUNT_RESOURCE_SCOPE_INVALID")
    qty_unit = account.get("qty_unit")
    if not _text(qty_unit):
        raise sdk_observation.ServiceObservationError("ACCOUNT_QUANTITY_UNIT_INVALID")

    resource = sdk_observation.account_resource_key(resource_by_leg[leg])
    coverage = tuple(sdk_observation.account_resource_key(row) for row in coverage_raw)
    if resource not in coverage or len(set(coverage)) != len(coverage):
        raise sdk_observation.ServiceObservationError("ACCOUNT_RESOURCE_OUTSIDE_COVERAGE")

    # Import only from the SDK source selected and origin-checked by the shared
    # helper. The key copies identity from the configured account; instrument
    # symbols are fixed by the 012 example rather than caller supplied.
    from bt_api_base.account_protocol import AccountKey

    try:
        account_key = raw_key if type(raw_key) is AccountKey else AccountKey.from_dict(raw_key)
    except Exception:
        raise sdk_observation.ServiceObservationError("ACCOUNT_IDENTITY_INVALID") from None
    key_document = {
        "source_ref": market.get("source_ref"),
        "entitlement_ref": market.get("entitlement_ref"),
        "instrument": {
            "provider": account_key.provider,
            "venue": account_key.venue,
            "environment": account_key.environment,
            "product_type": resource.product_type,
            "instrument_id": symbol,
            "native_symbol": symbol,
        },
        "channel": "orderbook",
        "depth": depth,
        "timeframe": None,
    }
    market_key = sdk_observation.market_subscription_key(key_document)
    return _LegPlan(leg, symbol, service, account_key, resource, market_key, qty_unit)


def _account_projection(session: Any, expected_key: Any) -> dict[str, Any]:
    view = session.account_view
    observation = getattr(view, "observation", None)
    if observation is None or getattr(observation, "account_key", None) != expected_key:
        raise ValueError("account_snapshot_identity_invalid")
    flags = {
        name: getattr(observation, name, None)
        for name in ("balances_complete", "positions_complete", "open_orders_complete")
    }
    if any(type(value) is not bool for value in flags.values()):
        raise ValueError("account_snapshot_completeness_invalid")
    healthy = getattr(session.account_client, "healthy", None) is True
    fresh_until = getattr(view, "fresh_until_monotonic", None)
    fresh = type(fresh_until) in (int, float) and time.monotonic() < fresh_until
    return {
        "account_key_id": expected_key.account_key_id,
        "session_generation": getattr(view, "session_generation", None),
        "cursor": getattr(view, "cursor", None),
        "observed_at_utc": getattr(observation, "completed_at_utc", None),
        "consistency": getattr(observation, "consistency", None),
        "balances_complete": flags["balances_complete"],
        "positions_complete": flags["positions_complete"],
        "open_orders_complete": flags["open_orders_complete"],
        "coverage_count": len(getattr(observation, "coverage", ())),
        "balance_count": len(getattr(observation, "balances", ())),
        "position_count": len(getattr(observation, "positions", ())),
        "open_order_count": len(getattr(observation, "open_orders", ()) or ()),
        "facade_healthy": healthy,
        "fresh": fresh,
    }


def _source_projection(descriptor: Any, market_key: Any) -> dict[str, Any]:
    if (
        descriptor is None
        or getattr(descriptor, "key", None) != market_key
        or getattr(descriptor, "stream_id", None) != market_key.stream_id
        or type(getattr(descriptor, "epoch", None)) is not str
        or not descriptor.epoch
    ):
        raise ValueError("market_source_descriptor_mismatch")
    return {
        "key_matches": True,
        "stream_id": descriptor.stream_id,
        "epoch": descriptor.epoch,
        "provider": descriptor.provider,
        "source": descriptor.source,
        "connection_generation": descriptor.connection_generation,
        "clock_domain_id": descriptor.clock_domain_id,
        "clock_source_session_id": descriptor.clock_source_session_id,
        "clock_source": descriptor.clock_source,
        "clock_mapping_qualified": False,
        "freshness_qualified": False,
        "execution_eligible": False,
    }


def _book_projection(
    book: Any,
    plan: _LegPlan,
    *,
    depth: int,
    max_event_age_seconds: str,
) -> dict[str, Any]:
    from backtrader.events import OrderBookSnapshot

    if type(book) is not OrderBookSnapshot or not book.validate():
        raise ValueError("orderbook_snapshot_invalid")
    if (
        book.symbol != plan.market_key.instrument.native_symbol
        or book.exchange != plan.market_key.instrument.venue
        or book.asset_type != plan.market_key.instrument.product_type
        or book.stale is not False
        or book.continuity_status not in {"snapshot", "continuous"}
        or type(book.sequence) is not int
        or book.sequence < 0
    ):
        raise ValueError("orderbook_identity_or_continuity_invalid")
    return {
        "symbol": book.symbol,
        "exchange": book.exchange,
        "product_type": book.asset_type,
        "sequence": book.sequence,
        "previous_sequence": book.previous_sequence,
        "snapshot_or_delta": book.snapshot_or_delta,
        "continuity_status": book.continuity_status,
        "stale": book.stale,
        "stale_reason": book.stale_reason,
        "recovery_snapshot": book.recovery_snapshot,
        "timestamp": book.timestamp,
        "exchange_time": book.exchange_time,
        "received_wall_time": book.received_wall_time,
        "received_monotonic_ns": book.received_monotonic_ns,
        "clock_domain_id": book.clock_domain_id,
        "source": book.source,
        "qty_unit": plan.qty_unit,
        "quantity_multiplier": "1",
        "depth": depth,
        "max_event_age_seconds": max_event_age_seconds,
        "bids": [[str(price), str(quantity)] for price, quantity in book.bids[:depth]],
        "asks": [[str(price), str(quantity)] for price, quantity in book.asks[:depth]],
    }


def _observe_leg(
    plan: _LegPlan,
    *,
    timeout_ms: int,
    depth: int,
    max_event_age_seconds: str,
) -> dict[str, Any]:
    from backtrader_runtime import service_observation as sdk_observation

    session = None
    result: dict[str, Any] = {
        "leg": plan.leg,
        "symbol": plan.symbol,
        "status": "BLOCKED",
        "account_snapshot": None,
        "source": None,
        "orderbook": None,
        "cleanup": {"status": "NOT_STARTED"},
    }
    try:
        instrument = sdk_observation.ServiceObservationInstrument(
            dataname=plan.symbol,
            market_key=plan.market_key,
            resource=plan.resource,
            qty_unit=plan.qty_unit,
            quantity_multiplier="1",
            max_event_age_seconds=max_event_age_seconds,
            require_source_descriptor=True,
        )
        session = sdk_observation.open_service_read_session(
            plan.service,
            instruments=[instrument],
            allow_write=False,
            timeout_seconds=max(0.1, min(timeout_ms / 1000, 30.0)),
        )
        result["account_snapshot"] = _account_projection(session, plan.account_key)
        descriptor = session.subscribe(plan.symbol)
        result["source"] = _source_projection(descriptor, plan.market_key)

        deadline = time.monotonic() + timeout_ms / 1000
        book = None
        while True:
            book = session.poll_orderbook(plan.symbol)
            if book is not None or time.monotonic() >= deadline:
                break
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
        if book is not None:
            result["orderbook"] = _book_projection(
                book,
                plan,
                depth=depth,
                max_event_age_seconds=max_event_age_seconds,
            )
        account = result["account_snapshot"]
        account_ready = bool(
            account
            and account["facade_healthy"]
            and account["fresh"]
            and account["balances_complete"]
            and account["positions_complete"]
            and account["open_orders_complete"]
        )
        result["status"] = "OBSERVED" if account_ready and result["orderbook"] else "BLOCKED"
        if not result["orderbook"]:
            result["reason"] = "orderbook_observation_timeout"
        elif not account_ready:
            result["reason"] = "account_snapshot_incomplete_or_stale"
    except sdk_observation.ServiceObservationError as error:
        result["reason"] = error.code
        if error.code == "SERVICE_CLEANUP_UNCONFIRMED":
            result["cleanup"] = {"status": "UNCONFIRMED"}
    except ValueError:
        result["reason"] = "observation_invalid"
    except Exception:
        result["reason"] = "observation_failed"
    finally:
        if session is not None and result["cleanup"].get("status") == "NOT_STARTED":
            try:
                cleanup = session.close()
            except sdk_observation.ServiceObservationError as error:
                result["cleanup"] = {"status": "UNCONFIRMED", "reason": error.code}
            except Exception:
                result["cleanup"] = {"status": "UNCONFIRMED", "reason": "cleanup_failed"}
            else:
                result["cleanup"] = dict(cleanup)
                if cleanup.get("status") != "PASS":
                    result["cleanup"] = {"status": "UNCONFIRMED"}
    if result["cleanup"].get("status") != "PASS":
        result["status"] = "UNKNOWN"
        result["reason"] = "cleanup_unconfirmed"
    return result


def observe_cross_exchange_orderbooks(
    *,
    okx_config_path: str,
    binance_config_path: str,
    strategy_id: str,
    timeout_ms: int = 2000,
    depth: int = 20,
    max_event_age_seconds: str = "2",
) -> dict[str, Any]:
    """Observe the fixed 012 symbols through two separate read-only SDK sessions."""

    from backtrader_runtime import service_observation as sdk_observation

    if not _text(strategy_id):
        raise sdk_observation.ServiceObservationError("STRATEGY_ID_INVALID")
    if type(timeout_ms) is not int or not 100 <= timeout_ms <= 30_000:
        raise sdk_observation.ServiceObservationError("OBSERVATION_TIMEOUT_INVALID")
    if type(depth) is not int or not 1 <= depth <= 50:
        raise sdk_observation.ServiceObservationError("ORDERBOOK_DEPTH_INVALID")
    if type(max_event_age_seconds) is not str:
        raise sdk_observation.ServiceObservationError("ORDERBOOK_AGE_INVALID")
    try:
        max_age = Decimal(max_event_age_seconds)
    except (InvalidOperation, ValueError):
        raise sdk_observation.ServiceObservationError("ORDERBOOK_AGE_INVALID") from None
    if not max_age.is_finite() or max_age <= 0 or max_age > 30:
        raise sdk_observation.ServiceObservationError("ORDERBOOK_AGE_INVALID")
    if not _text(okx_config_path) or not _text(binance_config_path):
        raise sdk_observation.ServiceObservationError("SERVICE_CONFIG_PAIR_REQUIRED")

    # Fully validate both explicit service/account/resource identities before
    # opening either client runtime. A malformed second leg cannot leave the
    # first one connected.
    plans = tuple(
        _plan_leg(leg, symbol, path, strategy_id=strategy_id, depth=depth)
        for (leg, symbol), path in zip(_LEGS, (okx_config_path, binance_config_path), strict=True)
    )
    if plans[0].account_key.account_key_id == plans[1].account_key.account_key_id:
        raise sdk_observation.ServiceObservationError("ACCOUNT_OWNERS_MUST_BE_DISTINCT")

    legs = [
        _observe_leg(
            plan,
            timeout_ms=timeout_ms,
            depth=depth,
            max_event_age_seconds=max_event_age_seconds,
        )
        for plan in plans
    ]
    cleanup_ok = all(row.get("cleanup", {}).get("status") == "PASS" for row in legs)
    observed = all(row["status"] == "OBSERVED" for row in legs)
    unknown = any(row["status"] == "UNKNOWN" for row in legs) or not cleanup_ok
    return {
        "status": "OBSERVED" if observed and cleanup_ok else "UNKNOWN" if unknown else "BLOCKED",
        "observation_level": "INDEPENDENT_SERVICE_ORDERBOOK_SNAPSHOTS",
        "strategy_id": strategy_id,
        "research_status": "RESEARCH_REJECTED",
        "write_capability": "UNSUPPORTED",
        "trade_execution": "not_run",
        "execution_eligible": False,
        "cross_venue_alignment": "NOT_EVALUATED",
        "clock_mapping_qualified": False,
        "legs": legs,
    }


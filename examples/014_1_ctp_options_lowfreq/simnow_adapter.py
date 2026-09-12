"""Fail-closed SimNow adapter for the Iteration 23 low-frequency example.

The adapter is deliberately small and owns no CTP client.  A caller must
inject the already-created ``bt_api_py`` API object (or a pure mock).  This
keeps credential loading, native lifecycle and authorization in their owning
SDK while making the example's startup and reconciliation contract testable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

import backtrader as bt

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.stores.btapistore import BtApiStore

try:
    from .ctp_options_lowfreq_strategy import CtpOptionsLowfreqStrategy
except ImportError:  # Direct execution through this directory's run.py.
    from ctp_options_lowfreq_strategy import CtpOptionsLowfreqStrategy


class SimNowAdapterError(RuntimeError):
    """A missing or contradictory native precondition."""


class SimNowBlocked(SimNowAdapterError):
    """The adapter cannot safely enter the requested engineering path."""


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    for name in ("to_dict", "as_dict", "model_dump"):
        method = getattr(value, name, None)
        if callable(method):
            result = method()
            if isinstance(result, Mapping):
                return dict(result)
    try:
        return dict(vars(value))
    except TypeError as exc:
        raise SimNowBlocked("query record is not a mapping") from exc


def _records(value: Any, query_name: str) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        found = False
        for key in ("records", "data", "items", query_name):
            if key in value:
                value = value[key]
                found = True
                break
        if not found:
            return [_mapping(value)]
    if value is None or isinstance(value, (str, bytes)):
        raise SimNowBlocked(f"{query_name} query is incomplete")
    try:
        return [_mapping(item) for item in value]
    except TypeError as exc:
        raise SimNowBlocked(f"{query_name} query is not iterable") from exc


def _identity(record: Mapping[str, Any], name: str) -> Any:
    aliases = {
        "account": ("account_fingerprint", "account_id", "InvestorID", "account"),
        "trading_day": ("trading_day", "TradingDay"),
        "generation": ("generation", "connection_generation", "ConnectionGeneration"),
    }
    for key in aliases[name]:
        if key in record and record[key] not in (None, ""):
            return record[key]
    raise SimNowBlocked(f"{name} identity is missing")


def _canonical(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@dataclass(frozen=True)
class SimNowIdentity:
    account_fingerprint: str
    trading_day: str
    generation: int


@dataclass(frozen=True)
class ReconciliationResult:
    status: str
    identity: SimNowIdentity
    rounds: int
    snapshot_hashes: tuple[str, ...]
    positions: tuple[dict[str, Any], ...]
    active_orders: tuple[dict[str, Any], ...]
    unknown_intents: tuple[dict[str, Any], ...]

    @property
    def flat_verified(self) -> bool:
        return (
            self.status == "FLAT_VERIFIED"
            and not self.positions
            and not self.active_orders
            and not self.unknown_intents
        )


class SimNowOptionsAdapter:
    """One account/session adapter and one BT Store/Feed/Broker/Cerebro chain.

    ``api`` is intentionally mandatory.  This class never instantiates an API
    class, reads environment files, or calls a native write in smoke mode.
    """

    _terminal_order_states = frozenset({"completed", "canceled", "cancelled", "rejected", "expired"})

    def __init__(self, config: Mapping[str, Any], api: Any = None):
        if api is None:
            raise SimNowBlocked("SIMNOW_API_INJECTION_REQUIRED")
        self.config = config
        self.api = api
        # Pure mocks may opt into the small query protocol below.  A native
        # API never gets this escape hatch: it must go through BtApiStore's
        # public CTP snapshot methods.
        self._mock_query_mode = bool(getattr(api, "iter23_pure_mock", False))
        self.store: BtApiStore | None = None
        self.feed: Any = None
        self.feeds: list[Any] = []
        self.broker: BtApiBroker | None = None
        self.cerebro: bt.Cerebro | None = None
        self.identity: SimNowIdentity | None = None
        self._request_count_deltas: list[dict[str, Any]] = []

    def _ensure_store(self) -> BtApiStore:
        if self.store is None:
            candidate = self.config["candidate"]
            symbols = (candidate["future"], candidate["call"], candidate["put"])
            metadata = {
                symbol: {
                    "tick_size": 1.0,
                    "contract_multiplier": candidate["multiplier"],
                    "min_size": 1,
                    "lot_size": 1,
                    "quantity_step": 1,
                    "currency": "CNY",
                }
                for symbol in symbols
            }
            self.store = BtApiStore(
                provider="btapi",
                api=self.api,
                cash=float(self.config["budget"]["capital_limit"]),
                value=float(self.config["budget"]["capital_limit"]),
                contract_metadata=metadata,
                market_data_only=True,
            )
        return self.store

    @staticmethod
    def _strict_store_schema(snapshot: Mapping[str, Any], *, label: str) -> None:
        required = {
            "evidence_complete", "read_only_safe", "write_request_free",
            "account_fingerprint", "trading_day", "connection_generation",
            "flat", "active_order_count", "unknown_intent_count",
            "unmatched_trade_count",
        }
        missing = sorted(required.difference(snapshot))
        if missing:
            raise SimNowBlocked(f"{label}_SCHEMA_INCOMPLETE:{','.join(missing)}")
        if any(snapshot[field] != 0 for field in ("active_order_count", "unknown_intent_count", "unmatched_trade_count")):
            raise SimNowBlocked(f"{label}_NONFLAT_OR_UNKNOWN")
        if any(snapshot[field] is not True for field in ("evidence_complete", "read_only_safe", "write_request_free", "flat")):
            raise SimNowBlocked(f"{label}_NOT_READ_ONLY_COMPLETE_OR_FLAT")
        if not isinstance(snapshot["account_fingerprint"], str) or not snapshot["account_fingerprint"].strip():
            raise SimNowBlocked(f"{label}_IDENTITY_INCOMPLETE")
        if not isinstance(snapshot["trading_day"], str) or not snapshot["trading_day"].strip():
            raise SimNowBlocked(f"{label}_IDENTITY_INCOMPLETE")
        if type(snapshot["connection_generation"]) is not int or snapshot["connection_generation"] <= 0:
            raise SimNowBlocked(f"{label}_IDENTITY_INCOMPLETE")

    @staticmethod
    def _semantic_payload(snapshot: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "account_fingerprint": snapshot["account_fingerprint"],
            "trading_day": snapshot["trading_day"],
            "connection_generation": snapshot["connection_generation"],
            "flat": snapshot["flat"],
            "active_order_count": snapshot["active_order_count"],
            "unknown_intent_count": snapshot["unknown_intent_count"],
            "unmatched_trade_count": snapshot["unmatched_trade_count"],
            "positions": snapshot.get("nonzero_positions", snapshot.get("positions", [])),
            "active_orders": snapshot.get("active_orders", []),
        }

    def _record_request_counts(self, snapshot: Mapping[str, Any]) -> None:
        delta = snapshot.get("request_count_delta")
        if isinstance(delta, Mapping):
            self._request_count_deltas.append(dict(delta))

    def external_request_counts(self) -> dict[str, Any]:
        if self._mock_query_mode:
            return {"network": 0, "order_write": 0}
        if not self._request_count_deltas:
            return {"network": "NOT_OBSERVED", "order_write": "NOT_OBSERVED"}
        order_write = 0
        network = 0
        network_seen = False
        for delta in self._request_count_deltas:
            order_write += sum(int(delta.get(key, 0) or 0) for key in ("order_insert", "order_action"))
            if "network" in delta:
                network += int(delta["network"] or 0)
                network_seen = True
        return {"network": network if network_seen else "NOT_OBSERVED", "order_write": order_write}

    def _query(self, *names: str) -> Any:
        for name in names:
            method = getattr(self.api, name, None)
            if callable(method):
                return method()
        raise SimNowBlocked(f"native query capability unavailable: {names[0]}")

    def _snapshot(self) -> tuple[SimNowIdentity, dict[str, Any]]:
        if not self._mock_query_mode:
            store = self._ensure_store()
            candidate = self.config["candidate"]
            legs = [("CZCE", candidate[name].split(".", 1)[-1]) for name in ("future", "call", "put")]
            snapshot = _mapping(
                store.get_ctp_bundle_preflight_snapshot(
                    legs,
                    primary_leg=legs[0],
                    read_only=True,
                )
            )
            self._strict_store_schema(snapshot, label="CTP_BUNDLE_PREFLIGHT")
            self._record_request_counts(snapshot)
            identity = SimNowIdentity(
                snapshot["account_fingerprint"],
                snapshot["trading_day"],
                snapshot["connection_generation"],
            )
            positions = list(snapshot.get("nonzero_positions") or snapshot.get("positions") or [])
            active_orders = list(snapshot.get("active_orders") or [])
            unknown_count = int(snapshot.get("unknown_intent_count") or 0)
            unknown = [{"count": unknown_count}] if unknown_count else []
            payload = self._semantic_payload(snapshot)
            payload.update({"identity": identity.__dict__, "positions": positions, "active_orders": active_orders, "unknown_intents": unknown})
            return identity, payload
        account_rows = _records(self._query("query_account", "query_account_result"), "account")
        if len(account_rows) != 1:
            raise SimNowBlocked("account-wide query must contain exactly one record")
        account = account_rows[0]
        identity = SimNowIdentity(
            str(_identity(account, "account")),
            str(_identity(account, "trading_day")),
            int(_identity(account, "generation")),
        )
        positions = _records(self._query("query_positions", "query_positions_result"), "positions")
        orders = _records(self._query("query_orders", "query_orders_result"), "orders")
        unknown = _records(
            self._query("query_unknown_intents", "query_unknown_intents_result"),
            "unknown_intents",
        )
        for name, rows in (("positions", positions), ("orders", orders), ("unknown_intents", unknown)):
            for row in rows:
                row_account = row.get("account_fingerprint", row.get("account_id", identity.account_fingerprint))
                row_generation = int(row.get("generation", row.get("connection_generation", identity.generation)))
                if str(row_account) != identity.account_fingerprint or row_generation != identity.generation:
                    raise SimNowBlocked(f"{name} identity differs from account query")
        active_orders = [
            row
            for row in orders
            if str(row.get("status", "")).lower() not in self._terminal_order_states
        ]
        payload = {
            "identity": identity.__dict__,
            "account_fingerprint": identity.account_fingerprint,
            "trading_day": identity.trading_day,
            "connection_generation": identity.generation,
            "positions": positions,
            "active_orders": active_orders,
            "unknown_intents": unknown,
            "evidence_complete": True,
            "read_only_safe": True,
            "write_request_free": True,
            "flat": not positions and not active_orders and not unknown,
            "active_order_count": len(active_orders),
            "unknown_intent_count": len(unknown),
            "unmatched_trade_count": 0,
        }
        return identity, payload

    def startup_preflight(self) -> dict[str, Any]:
        """Query account-wide state before constructing/starting Cerebro."""

        identity, payload = self._snapshot()
        if (
            not payload.get("flat", False)
            or payload.get("active_order_count") != 0
            or payload.get("unknown_intent_count") != 0
            or payload.get("unmatched_trade_count") != 0
        ):
            raise SimNowBlocked("STARTUP_ACCOUNT_NOT_FLAT_OR_UNKNOWN")
        self.identity = identity
        return {
            "status": "PASS",
            "scope": "account_wide",
            "identity": identity.__dict__,
            "positions": [],
            "active_orders": [],
            "unknown_intents": [],
        }

    def reconcile(self, *, rounds: int = 2) -> ReconciliationResult:
        if rounds != 2:
            raise ValueError("Iter23 requires exactly two reconciliation rounds")
        if not self._mock_query_mode and self.store is not None:
            snapshots = []
            for _ in range(rounds):
                raw = _mapping(self.store.get_ctp_reconciliation_snapshot())
                self._strict_store_schema(raw, label="CTP_RECONCILIATION")
                self._record_request_counts(raw)
                identity = SimNowIdentity(raw["account_fingerprint"], raw["trading_day"], raw["connection_generation"])
                payload = self._semantic_payload(raw)
                payload.update({"identity": identity.__dict__, "positions": list(raw.get("nonzero_positions") or raw.get("positions") or []), "active_orders": list(raw.get("active_orders") or []), "unknown_intents": ([{"count": raw["unknown_intent_count"]}] if raw["unknown_intent_count"] else [])})
                snapshots.append((identity, payload))
        else:
            snapshots = [self._snapshot() for _ in range(rounds)]
        identities = {item[0] for item in snapshots}
        if len(identities) != 1:
            raise SimNowBlocked("RECONCILIATION_GENERATION_CHANGED")
        hashes = tuple(_canonical(self._semantic_payload(item[1])) for item in snapshots)
        if hashes[0] != hashes[1]:
            raise SimNowBlocked("RECONCILIATION_NOT_STABLE")
        final = snapshots[-1][1]
        status = (
            "FLAT_VERIFIED"
            if final.get("flat") is True
            and final.get("active_order_count") == 0
            and final.get("unknown_intent_count") == 0
            and final.get("unmatched_trade_count") == 0
            else "EXPOSURE_REMAINS"
        )
        return ReconciliationResult(status, snapshots[-1][0], rounds, hashes, tuple(final["positions"]), tuple(final["active_orders"]), tuple(final["unknown_intents"]))

    def build_chain(self) -> tuple[bt.Cerebro, BtApiStore, Any, BtApiBroker]:
        if self.identity is None:
            raise SimNowBlocked("STARTUP_PREFLIGHT_REQUIRED")
        candidate = self.config["candidate"]
        symbols = (candidate["future"], candidate["call"], candidate["put"])
        metadata = {symbol: {"tick_size": candidate.get("price_tick", 1.0), "contract_multiplier": candidate["multiplier"], "min_size": 1, "lot_size": 1, "quantity_step": 1, "currency": "CNY"} for symbol in symbols}
        self.store = self._ensure_store()
        self.broker = BtApiBroker(store=self.store, provider="btapi", cash=float(self.config["budget"]["capital_limit"]), value=float(self.config["budget"]["capital_limit"]), contract_metadata=metadata, sdk_preflight=False, market_data_only=True, flatten_on_stop=False, force_refresh_queries=False)
        self.cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
        self.cerebro.setbroker(self.broker)
        for symbol in symbols:
            self.feed = self.store.getdata(dataname=symbol, historical_bars=[], live_bars=[], backfill_start=False, dispatch_ticks=False, dispatch_bars=False, qcheck=0.0)
            self.feeds.append(self.feed)
            self.cerebro.adddata(self.feed, name=symbol)
        self.cerebro.addstrategy(CtpOptionsLowfreqStrategy, future_symbol=candidate["future"], call_symbol=candidate["call"], put_symbol=candidate["put"], strike=candidate["strike"], multiplier=candidate["multiplier"], discount=candidate["discount"], capital_limit=self.config["budget"]["capital_limit"], ordinary_limit=self.config["budget"]["ordinary_limit"], recovery_reserve=self.config["budget"]["recovery_reserve"], clock_provider=None)
        return self.cerebro, self.store, self.feed, self.broker

    def run_engineering_smoke(self) -> dict[str, Any]:
        preflight = self.startup_preflight()
        cerebro, store, feed, broker = self.build_chain()
        # No bars are consumed here: a live feed with no injected finite source
        # must not be allowed to turn an engineering smoke into an unbounded
        # wait.  Construction still exercises the single runtime ownership
        # chain; a real run belongs to the SDK-owned launcher.
        reconciliation = self.reconcile()
        return {
            "status": "ENGINEERING_SMOKE_PASS" if reconciliation.status == "FLAT_VERIFIED" else "BLOCKED",
            "mode": "simnow",
            "purpose": "engineering_smoke",
            "preflight": preflight,
            "reconciliation": {"status": reconciliation.status, "rounds": reconciliation.rounds, "snapshot_hashes": reconciliation.snapshot_hashes, "identity": reconciliation.identity.__dict__},
            "native_execution_status": "NOT_CLAIMED_NO_NATIVE_CONFIRMATION",
            "fill_claim_status": "NO_NATIVE_CONFIRMATION",
            "execution_authorization_status": "BLOCKED_TRUST_ROOT_MISSING",
            "market_data_only": True,
            "order_write_allowed": False,
            "flat_status": reconciliation.status,
            "external_request_counts": self.external_request_counts(),
            "runtime_chain": {"store": type(store).__name__, "store_provider": store.provider, "feeds": [type(item).__name__ for item in self.feeds], "broker": type(broker).__name__, "broker_provider": broker.provider, "cerebro": type(cerebro).__name__, "strategy": CtpOptionsLowfreqStrategy.__name__},
        }

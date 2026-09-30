"""Live backend v2 protocol and common strict parser for Python/HTTPS bridges."""

from __future__ import annotations

import importlib
import json
import os
from dataclasses import asdict, is_dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .config import Config
from .models import (
    Action,
    Attestation,
    BalanceState,
    Binding,
    CertificationError,
    Channel,
    CleanupReport,
    Fill,
    InstrumentSpec,
    LedgerEntry,
    MarketReference,
    Observation,
    OperationEvidence,
    OrderState,
    PositionState,
    Receipt,
    Reconciliation,
    StateSnapshot,
    UnsupportedCaseError,
)


class Backend(Protocol):
    """Managed bridge contract; close may release local resources only."""

    def attest(self) -> Attestation: ...
    def instrument_spec(self, symbol: str) -> InstrumentSpec: ...
    def reference_price(self, symbol: str) -> MarketReference: ...
    def snapshot(self, action: Action, phase: str) -> StateSnapshot: ...
    def execute(self, action: Action) -> Receipt: ...
    def observe(
        self, action: Action, receipt: Receipt, timeout_seconds: float
    ) -> list[Observation]: ...
    def reconcile(self, action: Action, timeout_seconds: float) -> Reconciliation: ...
    def cleanup(
        self,
        action: Action,
        authorized_orders: dict[str, str],
        authorized_external_order_ids: tuple[str, ...],
    ) -> CleanupReport: ...
    def close(self) -> None: ...


def _map(raw: Any, label: str, keys: set[str]) -> dict[str, Any]:
    if isinstance(raw, dict) and raw.get("unsupported") is True:
        raise UnsupportedCaseError(f"{label} unsupported")
    if not isinstance(raw, dict) or set(raw) != keys:
        raise CertificationError(f"{label} requires exact v2 fields")
    return raw


def _str(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CertificationError(f"{label} must be a nonempty string")
    return value


def _optional(value: Any, label: str) -> str | None:
    return None if value is None else _str(value, label)


def _decimal(value: Any, label: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise CertificationError(f"{label} must be decimal")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise CertificationError(f"{label} must be decimal") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise CertificationError(f"{label} must be finite and valid")
    return result


def _bool(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise CertificationError(f"{label} must be boolean")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        raise CertificationError(f"{label} must be a list")
    return list(value)


def _binding(raw: Any) -> Binding:
    x = _map(raw, "binding", {"venue", "environment_name", "environment_kind", "account_ref"})
    return Binding(
        *(
            _str(x[k], f"binding.{k}")
            for k in ("venue", "environment_name", "environment_kind", "account_ref")
        )
    )


def _channel(raw: Any) -> Channel:
    x = _map(raw, "channel", {"instance", "channel", "role"})
    role = _str(x["role"], "channel.role")
    if role not in {"command_response", "independent_event", "query", "state_snapshot"}:
        raise CertificationError("unknown channel role")
    return Channel(
        _str(x["instance"], "channel.instance"), _str(x["channel"], "channel.channel"), role
    )


def _attestation(raw: Any) -> Attestation:
    x = _map(
        raw,
        "attestation",
        {
            "contract_version",
            "binding",
            "provider_attestation_id",
            "provider_session_id",
            "channels",
            "source",
            "observed_at",
            "payload",
        },
    )
    if (
        type(x["contract_version"]) is not int
        or x["contract_version"] != 2
        or not isinstance(x["payload"], dict)
    ):
        raise CertificationError("v2 attestation required")
    channels = tuple(_channel(c) for c in _list(x["channels"], "channels"))
    if len({(c.instance, c.channel) for c in channels}) != len(channels):
        raise CertificationError("channel registry has duplicate source")
    return Attestation(
        2,
        _binding(x["binding"]),
        _str(x["provider_attestation_id"], "attestation.id"),
        _str(x["provider_session_id"], "attestation.session"),
        channels,
        _str(x["source"], "attestation.source"),
        _str(x["observed_at"], "attestation.time"),
        x["payload"],
    )


def _spec(raw: Any) -> InstrumentSpec:
    names = (
        "symbol",
        "spec_id",
        "product_type",
        "quantity_unit",
        "contract_value_currency",
        "base_currency",
        "quote_currency",
        "settlement_currency",
        "source",
        "source_instance",
        "source_channel",
        "observed_at",
    )
    x = _map(
        raw, "instrument_spec", {"binding", "contract_value", "price_tick", "quantity_step", *names}
    )
    return InstrumentSpec(
        _binding(x["binding"]),
        *(_str(x[k], f"spec.{k}") for k in names[:4]),
        _decimal(x["contract_value"], "spec.contract_value", positive=True),
        *(_str(x[k], f"spec.{k}") for k in names[4:8]),
        _decimal(x["price_tick"], "spec.price_tick", positive=True),
        _decimal(x["quantity_step"], "spec.quantity_step", positive=True),
        _str(x["source"], "spec.source"),
        _str(x["source_instance"], "spec.source_instance"),
        _str(x["source_channel"], "spec.source_channel"),
        _str(x["observed_at"], "spec.observed_at"),
    )


def _reference(raw: Any) -> MarketReference:
    x = _map(
        raw,
        "reference_price",
        {
            "binding",
            "symbol",
            "price",
            "provider_quote_id",
            "source",
            "source_instance",
            "source_channel",
            "observed_at",
        },
    )
    return MarketReference(
        _binding(x["binding"]),
        _str(x["symbol"], "reference.symbol"),
        _decimal(x["price"], "reference.price", positive=True),
        *(
            _str(x[k], f"reference.{k}")
            for k in (
                "provider_quote_id",
                "source",
                "source_instance",
                "source_channel",
                "observed_at",
            )
        ),
    )


def _operation(raw: Any) -> OperationEvidence:
    names = {
        "operation_id",
        "phase",
        "kind",
        "accepted",
        "provider_request_id",
        "provider_order_id",
        "client_order_id",
        "target_order_id",
        "symbol",
        "side",
        "quantity",
        "price",
        "order_type",
        "position_id",
        "reduce_only",
        "instrument_spec_id",
        "source_instance",
        "source_channel",
        "occurred_at",
        "observed_at",
    }
    x = _map(raw, "operation_evidence", names)
    return OperationEvidence(
        _str(x["operation_id"], "operation.id"),
        _str(x["phase"], "operation.phase"),
        _str(x["kind"], "operation.kind"),
        _bool(x["accepted"], "operation.accepted"),
        _str(x["provider_request_id"], "operation.request"),
        *(
            _optional(x[k], f"operation.{k}")
            for k in ("provider_order_id", "client_order_id", "target_order_id", "symbol")
        ),
        _optional(x["side"], "operation.side"),
        _decimal(x["quantity"], "operation.quantity"),
        _decimal(x["price"], "operation.price"),
        _optional(x["order_type"], "operation.order_type"),
        _optional(x["position_id"], "operation.position_id"),
        _bool(x["reduce_only"], "operation.reduce_only"),
        _optional(x["instrument_spec_id"], "operation.spec"),
        *(
            _str(x[k], f"operation.{k}")
            for k in ("source_instance", "source_channel", "occurred_at", "observed_at")
        ),
    )


def _receipt(raw: Any, action: Action) -> Receipt:
    x = _map(
        raw,
        "receipt",
        {
            "action",
            "correlation_id",
            "client_id",
            "accepted",
            "binding",
            "source",
            "source_instance",
            "source_channel",
            "occurred_at",
            "observed_at",
            "provider_response_id",
            "operations",
            "created_order_ids",
            "payload",
        },
    )
    if (x["action"], x["correlation_id"], x["client_id"]) != (
        action.name,
        action.correlation_id,
        action.client_id,
    ) or not isinstance(x["payload"], dict):
        raise CertificationError("receipt identity or payload invalid")
    return Receipt(
        action.name,
        action.correlation_id,
        action.client_id,
        _bool(x["accepted"], "receipt.accepted"),
        _binding(x["binding"]),
        *(
            _str(x[k], f"receipt.{k}")
            for k in (
                "source",
                "source_instance",
                "source_channel",
                "occurred_at",
                "observed_at",
                "provider_response_id",
            )
        ),
        tuple(_operation(o) for o in _list(x["operations"], "receipt.operations")),
        tuple(
            _str(v, "created_order_id") for v in _list(x["created_order_ids"], "created_order_ids")
        ),
        x["payload"],
    )


def _observation(raw: Any) -> Observation:
    x = _map(
        raw,
        "observation",
        {
            "kind",
            "correlation_id",
            "client_id",
            "binding",
            "source",
            "source_instance",
            "source_channel",
            "occurred_at",
            "observed_at",
            "evidence_window_id",
            "provider_event_id",
            "operation_ids",
            "provider_order_ids",
            "payload",
        },
    )
    if not isinstance(x["payload"], dict):
        raise CertificationError("observation payload invalid")
    return Observation(
        *(_str(x[k], f"observation.{k}") for k in ("kind", "correlation_id", "client_id")),
        _binding(x["binding"]),
        *(
            _str(x[k], f"observation.{k}")
            for k in (
                "source",
                "source_instance",
                "source_channel",
                "occurred_at",
                "observed_at",
                "evidence_window_id",
                "provider_event_id",
            )
        ),
        tuple(_str(v, "operation_id") for v in _list(x["operation_ids"], "operation_ids")),
        tuple(
            _str(v, "provider_order_id")
            for v in _list(x["provider_order_ids"], "provider_order_ids")
        ),
        x["payload"],
    )


def _order(raw: Any) -> OrderState:
    x = _map(
        raw,
        "order",
        {
            "order_id",
            "client_order_id",
            "symbol",
            "side",
            "price",
            "order_type",
            "position_id",
            "reduce_only",
            "instrument_spec_id",
            "status",
            "requested",
            "filled",
            "remaining",
        },
    )
    return OrderState(
        *(_str(x[k], f"order.{k}") for k in ("order_id", "client_order_id", "symbol", "side")),
        _decimal(x["price"], "order.price"),
        _str(x["order_type"], "order.order_type"),
        _optional(x["position_id"], "order.position_id"),
        _bool(x["reduce_only"], "order.reduce_only"),
        _optional(x["instrument_spec_id"], "order.instrument_spec_id"),
        _str(x["status"], "order.status"),
        *(_decimal(x[k], f"order.{k}") for k in ("requested", "filled", "remaining")),
    )


def _position(raw: Any) -> PositionState:
    x = _map(raw, "position", {"position_id", "symbol", "quantity"})
    return PositionState(
        _str(x["position_id"], "position.id"),
        _str(x["symbol"], "position.symbol"),
        _decimal(x["quantity"], "position.quantity"),
    )


def _balance(raw: Any) -> BalanceState:
    x = _map(raw, "balance", {"currency", "total"})
    return BalanceState(
        _str(x["currency"], "balance.currency"), _decimal(x["total"], "balance.total")
    )


def _fill(raw: Any) -> Fill:
    x = _map(
        raw,
        "fill",
        {
            "fill_id",
            "order_id",
            "symbol",
            "side",
            "quantity",
            "price",
            "base_delta",
            "quote_delta",
            "settlement_delta",
            "fee_currency",
            "fee",
            "position_id",
            "position_delta",
        },
    )
    return Fill(
        *(_str(x[k], f"fill.{k}") for k in ("fill_id", "order_id", "symbol", "side")),
        _decimal(x["quantity"], "fill.quantity", positive=True),
        _decimal(x["price"], "fill.price", positive=True),
        *(_decimal(x[k], f"fill.{k}") for k in ("base_delta", "quote_delta", "settlement_delta")),
        _str(x["fee_currency"], "fill.fee_currency"),
        _decimal(x["fee"], "fill.fee"),
        _optional(x["position_id"], "fill.position_id"),
        _decimal(x["position_delta"], "fill.position_delta"),
    )


def _ledger(raw: Any) -> LedgerEntry:
    x = _map(raw, "ledger", {"entry_id", "currency", "delta", "fill_id", "reason"})
    return LedgerEntry(
        _str(x["entry_id"], "ledger.id"),
        _str(x["currency"], "ledger.currency"),
        _decimal(x["delta"], "ledger.delta"),
        _optional(x["fill_id"], "ledger.fill_id"),
        _str(x["reason"], "ledger.reason"),
    )


def _snapshot(raw: Any) -> StateSnapshot:
    x = _map(
        raw,
        "snapshot",
        {
            "binding",
            "correlation_id",
            "snapshot_id",
            "phase",
            "scope",
            "complete",
            "pagination_complete",
            "control_state_digest",
            "orders",
            "positions",
            "balances",
            "fills",
            "ledger",
            "source",
            "source_instance",
            "source_channel",
            "observed_at",
        },
    )
    return StateSnapshot(
        _binding(x["binding"]),
        *(_str(x[k], f"snapshot.{k}") for k in ("correlation_id", "snapshot_id", "phase", "scope")),
        _bool(x["complete"], "snapshot.complete"),
        _bool(x["pagination_complete"], "snapshot.pagination_complete"),
        _str(x["control_state_digest"], "snapshot.control_state_digest"),
        tuple(_order(v) for v in _list(x["orders"], "orders")),
        tuple(_position(v) for v in _list(x["positions"], "positions")),
        tuple(_balance(v) for v in _list(x["balances"], "balances")),
        tuple(_fill(v) for v in _list(x["fills"], "fills")),
        tuple(_ledger(v) for v in _list(x["ledger"], "ledger")),
        *(
            _str(x[k], f"snapshot.{k}")
            for k in ("source", "source_instance", "source_channel", "observed_at")
        ),
    )


def _reconciliation(raw: Any, action: Action) -> Reconciliation:
    x = _map(
        raw,
        "reconciliation",
        {
            "binding",
            "correlation_id",
            "client_id",
            "provider_reconcile_id",
            "provider_state",
            "source",
            "observed_at",
            "receipt",
        },
    )
    return Reconciliation(
        _binding(x["binding"]),
        *(
            _str(x[k], f"reconcile.{k}")
            for k in (
                "correlation_id",
                "client_id",
                "provider_reconcile_id",
                "provider_state",
                "source",
                "observed_at",
            )
        ),
        _receipt(x["receipt"], action) if x["receipt"] is not None else None,
    )


def _cleanup(raw: Any) -> CleanupReport:
    x = _map(
        raw,
        "cleanup",
        {
            "binding",
            "correlation_id",
            "client_id",
            "provider_reconcile_id",
            "source",
            "observed_at",
            "operations",
        },
    )
    return CleanupReport(
        _binding(x["binding"]),
        *(
            _str(x[k], f"cleanup.{k}")
            for k in (
                "correlation_id",
                "client_id",
                "provider_reconcile_id",
                "source",
                "observed_at",
            )
        ),
        tuple(_operation(v) for v in _list(x["operations"], "cleanup.operations")),
    )


def _raw(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return value


class _NormalizedBackend:
    """All factory returns pass the same strict parser as HTTP JSON.

    The attested raw backend must implement close as local-resource release;
    it must not disconnect a provider session, cancel orders or mutate policy.
    """

    def __init__(self, raw: Any):
        self.raw = raw

    def attest(self) -> Attestation:
        return _attestation(_raw(self.raw.attest()))

    def instrument_spec(self, symbol: str) -> InstrumentSpec:
        return _spec(_raw(self.raw.instrument_spec(symbol)))

    def reference_price(self, symbol: str) -> MarketReference:
        return _reference(_raw(self.raw.reference_price(symbol)))

    def snapshot(self, action: Action, phase: str) -> StateSnapshot:
        return _snapshot(_raw(self.raw.snapshot(action, phase)))

    def execute(self, action: Action) -> Receipt:
        return _receipt(_raw(self.raw.execute(action)), action)

    def observe(
        self, action: Action, receipt: Receipt, timeout_seconds: float
    ) -> list[Observation]:
        return [
            _observation(_raw(v))
            for v in _list(self.raw.observe(action, receipt, timeout_seconds), "observe")
        ]

    def reconcile(self, action: Action, timeout_seconds: float) -> Reconciliation:
        return _reconciliation(_raw(self.raw.reconcile(action, timeout_seconds)), action)

    def cleanup(
        self,
        action: Action,
        authorized_orders: dict[str, str],
        authorized_external_order_ids: tuple[str, ...],
    ) -> CleanupReport:
        return _cleanup(
            _raw(
                self.raw.cleanup(
                    action,
                    authorized_orders,
                    authorized_external_order_ids,
                )
            )
        )

    def close(self) -> None:
        self.raw.close()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, request: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


class HttpJsonBackend:
    """Trust boundary: a managed HTTPS bridge must forward genuine provider data.

    Strict parsing, TLS and redirect refusal prevent malformed responses, but
    cannot make a dishonest bridge independent of its command path. Operators
    must audit and segregate the bridge's channel registry and credentials.
    """

    def __init__(
        self, endpoint: str, token: str | None, config: Config, credentials: dict[str, str]
    ):
        parsed = urlparse(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise CertificationError("bridge endpoint must be a plain HTTPS URL")
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.credentials = credentials
        self.context = {"venue": config.venue, "environment": asdict(config.environment)}
        self.opener = build_opener(_NoRedirect)

    def _post(self, method: str, body: dict[str, Any]) -> Any:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(  # noqa: S310 - HTTPS URL validated; redirects disabled
            f"{self.endpoint}/{method}",
            data=json.dumps(
                {**self.context, "credentials": self.credentials, **body}, default=str
            ).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=35) as response:
                if response.status != 200:
                    raise CertificationError(f"bridge {method} HTTP {response.status}")
                data = response.read(2_000_001)
                if len(data) > 2_000_000:
                    raise CertificationError("bridge response exceeds 2 MB")
                return json.loads(data)
        except CertificationError:
            raise
        except Exception as exc:
            raise CertificationError(f"bridge {method} failed ({type(exc).__name__})") from exc

    def attest(self) -> Attestation:
        return _attestation(self._post("attest", {}))

    def instrument_spec(self, symbol: str) -> InstrumentSpec:
        return _spec(self._post("instrument_spec", {"symbol": symbol}))

    def reference_price(self, symbol: str) -> MarketReference:
        return _reference(self._post("reference_price", {"symbol": symbol}))

    def snapshot(self, action: Action, phase: str) -> StateSnapshot:
        return _snapshot(self._post("snapshot", {"action": asdict(action), "phase": phase}))

    def execute(self, action: Action) -> Receipt:
        return _receipt(self._post("execute", {"action": asdict(action)}), action)

    def observe(
        self, action: Action, receipt: Receipt, timeout_seconds: float
    ) -> list[Observation]:
        return [
            _observation(v)
            for v in _list(
                self._post(
                    "observe",
                    {
                        "action": asdict(action),
                        "receipt": asdict(receipt),
                        "timeout_seconds": timeout_seconds,
                    },
                ),
                "observe",
            )
        ]

    def reconcile(self, action: Action, timeout_seconds: float) -> Reconciliation:
        return _reconciliation(
            self._post("reconcile", {"action": asdict(action), "timeout_seconds": timeout_seconds}),
            action,
        )

    def cleanup(
        self,
        action: Action,
        authorized_orders: dict[str, str],
        authorized_external_order_ids: tuple[str, ...],
    ) -> CleanupReport:
        return _cleanup(
            self._post(
                "cleanup",
                {
                    "action": asdict(action),
                    "authorized_orders": authorized_orders,
                    "authorized_external_order_ids": authorized_external_order_ids,
                },
            )
        )

    def close(self) -> None:
        self._post("close", {})


def create_backend(config: Config) -> Backend:
    credentials = config.resolve_credentials()
    if config.backend.kind == "http_json":
        endpoint = os.environ.get(config.backend.endpoint_env or "", "")
        token = (
            os.environ.get(config.backend.token_env or "", "") if config.backend.token_env else None
        )
        if not endpoint or (config.backend.token_env and not token):
            raise CertificationError("bridge endpoint or token environment variable is empty")
        return HttpJsonBackend(endpoint, token, config, credentials)
    assert config.backend.target is not None
    module_name, factory_name = config.backend.target.split(":", 1)
    raw = getattr(importlib.import_module(module_name), factory_name)(
        config=config, credentials=credentials
    )
    for method in (
        "attest",
        "instrument_spec",
        "reference_price",
        "snapshot",
        "execute",
        "observe",
        "reconcile",
        "cleanup",
        "close",
    ):
        if not callable(getattr(raw, method, None)):
            raise CertificationError(f"python backend lacks {method}")
    return _NormalizedBackend(raw)

"""Store-owned identity registry for unified SDK execution and reconciliation.

The registry is the single in-memory owner of the relationship between a
Backtrader order reference, the exact SDK facade/API objects, an SDK-issued
neutral correlation, and its Store-local lookup keys.  Reconciliation and
verified acknowledgement receipts share the same lock and generation, so a
clear cannot leave a verifier bound to an order entry from a retired session.

The registry deliberately does not inspect or copy the SDK's private issuer or
provider reservation handles.  The exact correlated execution facade retains
those opaque objects inside the SDK; Backtrader holds only its public
OrderCorrelation object and the facade identity that owns it.
"""

from __future__ import annotations

import copy
import threading
import uuid
from collections import OrderedDict
from collections.abc import Iterator, Mapping
from types import MappingProxyType
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

__all__ = ("StoreExecutionBindingRegistry", "StoreExecutionBindingRegistryError")


class StoreExecutionBindingRegistryError(RuntimeError):
    """Finite local registry failure that never includes order or account data."""

    def __init__(self, code: str) -> None:
        self.code = code if type(code) is str and code else "store_execution_binding_failed"
        super().__init__(self.code)


class _PreparationHandle:
    """Opaque handle for one in-progress Store-local SDK correlation request."""

    __slots__ = ("_registry", "_entry", "_generation")

    def __init__(self, registry: object, entry: object, generation: int) -> None:
        self._registry = registry
        self._entry = entry
        self._generation = generation

    def __repr__(self) -> str:
        return "_PreparationHandle(<opaque>)"


class _OrderEntry:
    __slots__ = (
        "identity",
        "reference",
        "order",
        "exchange_name",
        "symbol",
        "api",
        "execution_facade",
        "state",
        "correlation",
        "client_order_id",
        "account_id",
        "execution_contract",
    )

    def __init__(
        self,
        reference: int,
        order: Any,
        exchange_name: str,
        symbol: str,
        api: Any,
        execution_facade: Any,
    ) -> None:
        self.identity = object()
        self.reference = reference
        self.order = order
        self.exchange_name = exchange_name
        self.symbol = symbol
        self.api = api
        self.execution_facade = execution_facade
        self.state = "preparing"
        self.correlation = None
        self.client_order_id = None
        self.account_id = None
        self.execution_contract = None


class _BindingSnapshot(Mapping):
    """Read-only shallow view of one exact registry entry."""

    __slots__ = ("_registry", "_entry_identity", "_values")

    def __init__(self, registry: object, entry: _OrderEntry) -> None:
        self._registry = registry
        self._entry_identity = entry.identity
        self._values = MappingProxyType(
            {
                "state": entry.state,
                "order": entry.order,
                "bt_order_ref": entry.reference,
                "exchange_name": entry.exchange_name,
                "symbol": entry.symbol,
                "api": entry.api,
                "execution_facade": entry.execution_facade,
                "correlation": entry.correlation,
                "client_order_id": entry.client_order_id,
                "account_id": entry.account_id,
                "execution_contract": entry.execution_contract,
            }
        )

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return "_BindingSnapshot(<opaque>)"


class StoreExecutionBindingRegistry:
    """Own all SDK-correlated order and reconciliation bindings for one Store.

    A registry instance belongs to exactly one ``BtApiStore``.  All correlated
    indexes, exact API/facade identities, verified response receipts, and
    reconciliation projections are guarded by one lock.  Read methods return
    immutable snapshots; only registry methods can change a binding or consume
    a one-shot verifier.
    """

    def __init__(self, *, reconciliation_limit: int = 32) -> None:
        if type(reconciliation_limit) is not int or reconciliation_limit <= 0:
            raise ValueError("reconciliation_limit must be a positive integer")
        self._lock = threading.RLock()
        self._generation = 0
        self._by_ref: Dict[int, _OrderEntry] = {}
        self._by_correlation_identity: Dict[int, _OrderEntry] = {}
        self._by_local_ref: Dict[str, _OrderEntry] = {}
        self._by_client_id: Dict[Tuple[str, str], _OrderEntry] = {}
        self._verified_responses: Dict[str, Dict[str, Any]] = {}
        self._reconciliation: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._reconciliation_limit = reconciliation_limit

    def begin_preparation(
        self,
        *,
        reference: int,
        order: Any,
        exchange_name: str,
        symbol: str,
        api: Any,
        execution_facade: Any,
        supplied_client_order_id: Any,
    ) -> Tuple[Optional[_PreparationHandle], Any]:
        """Reserve one BT reference before asking the SDK to issue correlation."""

        if (
            type(reference) is not int
            or reference <= 0
            or type(exchange_name) is not str
            or not exchange_name
            or exchange_name != exchange_name.strip()
            or type(symbol) is not str
            or not symbol
            or symbol != symbol.strip()
            or api is None
            or execution_facade is None
        ):
            raise StoreExecutionBindingRegistryError("store_order_binding_invalid")
        with self._lock:
            existing = self._by_ref.get(reference)
            if existing is not None:
                if (
                    existing.order is order
                    and existing.exchange_name == exchange_name
                    and existing.symbol == symbol
                    and existing.api is api
                    and existing.execution_facade is execution_facade
                    and existing.state in {"prepared", "queued", "completed"}
                    and existing.correlation is not None
                ):
                    return None, existing.correlation
                raise StoreExecutionBindingRegistryError(
                    "bt_order_reference_correlation_conflict"
                )
            if not (
                supplied_client_order_id is None
                or (
                    type(supplied_client_order_id) is str
                    and supplied_client_order_id == ""
                )
            ):
                raise StoreExecutionBindingRegistryError(
                    "client_order_id_is_sdk_issued"
                )
            entry = _OrderEntry(
                reference,
                order,
                exchange_name,
                symbol,
                api,
                execution_facade,
            )
            self._by_ref[reference] = entry
            return _PreparationHandle(self, entry, self._generation), None

    def complete_preparation(
        self,
        handle: object,
        *,
        correlation: Any,
        correlation_type: type,
        account_id: str,
    ) -> _BindingSnapshot:
        """Atomically bind SDK correlation, exact facade/API, and BT reference."""

        if (
            type(handle) is not _PreparationHandle
            or handle._registry is not self
            or type(correlation) is not correlation_type
        ):
            raise StoreExecutionBindingRegistryError("sdk_correlation_binding_invalid")
        entry = handle._entry
        client_order_id = getattr(correlation, "client_order_id", None)
        if (
            type(account_id) is not str
            or not account_id
            or account_id != account_id.strip()
            or correlation.exchange_name != entry.exchange_name
            or correlation.symbol != entry.symbol
            or type(client_order_id) is not str
            or not client_order_id
            or client_order_id != client_order_id.strip()
        ):
            raise StoreExecutionBindingRegistryError("sdk_correlation_route_mismatch")
        with self._lock:
            if (
                handle._generation != self._generation
                or self._by_ref.get(entry.reference) is not entry
                or entry.state != "preparing"
                or entry.correlation is not None
            ):
                raise StoreExecutionBindingRegistryError("sdk_correlation_reservation_stale")
            if id(correlation) in self._by_correlation_identity:
                raise StoreExecutionBindingRegistryError("sdk_correlation_object_reused")
            client_key = (entry.exchange_name, client_order_id)
            previous = self._by_client_id.get(client_key)
            if previous is not None and previous is not entry:
                raise StoreExecutionBindingRegistryError("sdk_client_order_id_conflict")
            entry.correlation = correlation
            entry.client_order_id = client_order_id
            entry.account_id = account_id
            entry.state = "prepared"
            self._by_correlation_identity[id(correlation)] = entry
            self._by_local_ref[str(entry.reference)] = entry
            self._by_client_id[client_key] = entry
            return self._snapshot(entry)

    def fail_preparation(self, handle: object) -> None:
        """Keep a failed SDK issue attempt fenced as UNKNOWN for this BT ref."""

        if type(handle) is not _PreparationHandle or handle._registry is not self:
            return
        entry = handle._entry
        with self._lock:
            if (
                handle._generation == self._generation
                and self._by_ref.get(entry.reference) is entry
                and entry.state == "preparing"
            ):
                entry.state = "preparation_unknown"

    def by_ref(self, reference: Any) -> Optional[_BindingSnapshot]:
        if type(reference) is not int:
            return None
        with self._lock:
            entry = self._by_ref.get(reference)
            return None if entry is None else self._snapshot(entry)

    def by_correlation(self, correlation: Any) -> Optional[_BindingSnapshot]:
        if correlation is None:
            return None
        with self._lock:
            entry = self._by_correlation_identity.get(id(correlation))
            if entry is None or entry.correlation is not correlation:
                return None
            return self._snapshot(entry)

    def by_local_ref(self, local_ref: Any) -> Optional[_BindingSnapshot]:
        if type(local_ref) is int:
            key = str(local_ref)
        elif type(local_ref) is str:
            key = local_ref
        else:
            return None
        with self._lock:
            entry = self._by_local_ref.get(key)
            return None if entry is None else self._snapshot(entry)

    def by_client_id(
        self,
        exchange_name: Any,
        client_order_id: Any,
    ) -> Optional[_BindingSnapshot]:
        if type(exchange_name) is not str or type(client_order_id) is not str:
            return None
        with self._lock:
            entry = self._by_client_id.get((exchange_name, client_order_id))
            return None if entry is None else self._snapshot(entry)

    def find_client_id(
        self,
        client_order_id: Any,
        *,
        symbol: Optional[str] = None,
        api: Any = None,
        require_all_indexes: bool = False,
    ) -> Tuple[_BindingSnapshot, ...]:
        if type(client_order_id) is not str:
            return ()
        with self._lock:
            return tuple(
                self._snapshot(entry)
                for (_route, candidate_id), entry in self._by_client_id.items()
                if candidate_id == client_order_id
                and (symbol is None or entry.symbol == symbol)
                and (api is None or entry.api is api)
                and (not require_all_indexes or self._indexes_agree(entry))
            )

    def bound_order_by_client_id(
        self,
        exchange_name: str,
        client_order_id: str,
        *,
        api: Any,
        symbol: Optional[str] = None,
    ) -> Optional[_BindingSnapshot]:
        """Return an entry only when every local/token/client index agrees."""

        with self._lock:
            entry = self._by_client_id.get((exchange_name, client_order_id))
            if entry is None or (symbol is not None and entry.symbol != symbol):
                return None
            if (
                entry.api is not api
                or entry.correlation is None
                or not self._indexes_agree(entry)
            ):
                return None
            return self._snapshot(entry)

    def binding_is_current(self, snapshot: Any) -> bool:
        if type(snapshot) is not _BindingSnapshot or snapshot._registry is not self:
            return False
        with self._lock:
            entry = self._by_ref.get(snapshot.get("bt_order_ref"))
            return entry is not None and entry.identity is snapshot._entry_identity

    def binding_matches(
        self,
        snapshot: Any,
        *,
        correlation: Any = None,
        api: Any = None,
        exchange_name: Optional[str] = None,
        symbol: Optional[str] = None,
        states: Optional[Iterable[str]] = None,
        require_all_indexes: bool = False,
    ) -> bool:
        if type(snapshot) is not _BindingSnapshot or snapshot._registry is not self:
            return False
        with self._lock:
            entry = self._by_ref.get(snapshot.get("bt_order_ref"))
            if entry is None or entry.identity is not snapshot._entry_identity:
                return False
            if correlation is not None and entry.correlation is not correlation:
                return False
            if api is not None and entry.api is not api:
                return False
            if exchange_name is not None and entry.exchange_name != exchange_name:
                return False
            if symbol is not None and entry.symbol != symbol:
                return False
            if states is not None and entry.state not in states:
                return False
            return not require_all_indexes or self._indexes_agree(entry)

    def set_state(
        self,
        snapshot: Any,
        state: str,
        *,
        expected_states: Optional[Iterable[str]] = None,
    ) -> bool:
        if type(state) is not str or not state:
            return False
        if type(snapshot) is not _BindingSnapshot or snapshot._registry is not self:
            return False
        expected = None if expected_states is None else frozenset(expected_states)
        with self._lock:
            entry = self._by_ref.get(snapshot.get("bt_order_ref"))
            if entry is None or entry.identity is not snapshot._entry_identity:
                return False
            if entry.correlation is not None and not self._indexes_agree(entry):
                return False
            if expected is not None and entry.state not in expected:
                return False
            entry.state = state
            return True

    def set_state_by_correlation(self, correlation: Any, state: str) -> bool:
        if correlation is None or type(state) is not str or not state:
            return False
        with self._lock:
            entry = self._by_correlation_identity.get(id(correlation))
            if (
                entry is None
                or entry.correlation is not correlation
                or not self._indexes_agree(entry)
            ):
                return False
            entry.state = state
            return True

    def set_execution_contract(
        self,
        exchange_name: str,
        client_order_id: str,
        correlation: Any,
        api: Any,
        execution_contract: Any,
    ) -> bool:
        with self._lock:
            entry = self._by_client_id.get((exchange_name, client_order_id))
            if (
                entry is None
                or entry.correlation is not correlation
                or entry.api is not api
                or not self._indexes_agree(entry)
            ):
                return False
            entry.execution_contract = copy.deepcopy(execution_contract)
            return True

    def record_verified_response(
        self,
        verification_id: str,
        *,
        snapshot: Any,
        correlation: Any,
        api: Any,
        execution_facade: Any,
        operation: str,
        acknowledgement: Any,
        status: str,
    ) -> bool:
        """Atomically retain a verifier handle and mark the exact order complete."""

        if type(verification_id) is not str or not verification_id:
            return False
        if type(snapshot) is not _BindingSnapshot or snapshot._registry is not self:
            return False
        with self._lock:
            entry = self._by_ref.get(snapshot.get("bt_order_ref"))
            if (
                entry is None
                or entry.identity is not snapshot._entry_identity
                or entry.correlation is not correlation
                or entry.api is not api
                or entry.execution_facade is not execution_facade
                or verification_id in self._verified_responses
                or not self._indexes_agree(entry)
                or type(operation) is not str
                or operation not in {"submit", "cancel"}
                or type(status) is not str
                or status not in {"accepted", "rejected"}
                or getattr(acknowledgement, "correlation", None) is not correlation
                or getattr(acknowledgement, "operation", None) != operation
                or getattr(acknowledgement, "disposition", None) != status
            ):
                return False
            entry.state = "completed"
            self._verified_responses[verification_id] = {
                "entry": entry,
                "correlation": correlation,
                "api": api,
                "execution_facade": execution_facade,
                "operation": operation,
                "acknowledgement": acknowledgement,
                "status": status,
            }
            return True

    def verify_order_response_once(
        self,
        correlation: Any,
        response: Any,
        *,
        expected_operation: str,
        current_api: Any,
        correlation_type: type,
        acknowledgement_type: type,
        validate_current_api: Callable[[], Any],
    ) -> bool:
        """Consume exactly one response receipt for its bound API/correlation."""

        if type(correlation) is not correlation_type or not isinstance(response, Mapping):
            return False
        with self._lock:
            entry = self._by_correlation_identity.get(id(correlation))
            if entry is None or entry.correlation is not correlation or entry.api is not current_api:
                return False
            try:
                valid_route = validate_current_api()
            except Exception:
                return False
            if type(valid_route) is not bool or valid_route is not True:
                return False
            verification_id = response.get("verification_id")
            if type(verification_id) is not str or not verification_id:
                return False
            verified = self._verified_responses.get(verification_id)
            if (
                verified is None
                or verified.get("entry") is not entry
                or verified.get("correlation") is not correlation
                or verified.get("api") is not entry.api
                or verified.get("execution_facade") is not entry.execution_facade
                or type(verified.get("acknowledgement")) is not acknowledgement_type
                or not self._indexes_agree(entry)
            ):
                return False
            acknowledgement = verified["acknowledgement"]
            operation = verified.get("operation")
            if (
                acknowledgement.correlation is not correlation
                or acknowledgement.operation != operation
                or operation != expected_operation
                or response.get("kind") != "verified_order_ack"
                or response.get("operation") != operation
                or response.get("symbol") != correlation.symbol
                or response.get("exchange_name") != correlation.exchange_name
                or response.get("client_order_id") != correlation.client_order_id
                or response.get("status") != acknowledgement.disposition
                or response.get("verified_order_ack") is not True
            ):
                return False
            self._verified_responses.pop(verification_id, None)
            return True

    def retain_reconciliation_projection(
        self,
        kind: str,
        payload: Any,
        *,
        api: Any,
        route: str,
        facade: Any,
        handle: Any,
        result: Any,
        correlation: Any,
        local_ref: Any,
    ) -> Dict[str, Any]:
        """Retain one exact, one-shot SDK verifier and its Store projection."""

        if type(payload) is not dict or "store_verification_id" in payload:
            raise StoreExecutionBindingRegistryError(
                "reconciliation_projection_invalid"
            )
        if kind == "order":
            if type(local_ref) is not int or local_ref <= 0 or correlation is None:
                raise StoreExecutionBindingRegistryError(
                    "reconciliation_order_binding_invalid"
                )
        elif kind == "account":
            if correlation is not None or local_ref is not None:
                raise StoreExecutionBindingRegistryError(
                    "reconciliation_account_binding_invalid"
                )
        else:
            raise StoreExecutionBindingRegistryError(
                "reconciliation_projection_kind_invalid"
            )

        retained = dict(payload)
        with self._lock:
            while True:
                verification_id = uuid.uuid4().hex
                if verification_id not in self._reconciliation:
                    break
            retained["store_verification_id"] = verification_id
            entry = {
                "kind": kind,
                "api": api,
                "route": route,
                "facade": facade,
                "handle": handle,
                "result": result,
                "projection": copy.deepcopy(retained),
            }
            if kind == "order":
                bound = self._by_correlation_identity.get(id(correlation))
                if (
                    bound is None
                    or bound.correlation is not correlation
                    or bound.api is not api
                    or bound.reference != local_ref
                    or not self._indexes_agree(bound)
                ):
                    raise StoreExecutionBindingRegistryError(
                        "reconciliation_order_binding_invalid"
                    )
                entry["correlation"] = correlation
                entry["local_ref"] = local_ref
            while len(self._reconciliation) >= self._reconciliation_limit:
                self._reconciliation.popitem(last=False)
            self._reconciliation[verification_id] = entry
        return retained

    def consume_reconciliation_projection(self, verification_id: Any) -> Optional[Dict[str, Any]]:
        """Consume a retained reconciliation verifier once, before SDK revalidation."""

        if type(verification_id) is not str or not verification_id:
            return None
        with self._lock:
            entry = self._reconciliation.pop(verification_id, None)
            return None if entry is None else dict(entry)

    def clear(self) -> None:
        """Revoke every Store-local order and reconciliation handle atomically."""

        with self._lock:
            self._generation += 1
            self._by_ref.clear()
            self._by_correlation_identity.clear()
            self._by_local_ref.clear()
            self._by_client_id.clear()
            self._verified_responses.clear()
            self._reconciliation.clear()

    def _indexes_agree(self, entry: _OrderEntry) -> bool:
        correlation = entry.correlation
        return bool(
            correlation is not None
            and self._by_ref.get(entry.reference) is entry
            and self._by_correlation_identity.get(id(correlation)) is entry
            and self._by_local_ref.get(str(entry.reference)) is entry
            and self._by_client_id.get((entry.exchange_name, entry.client_order_id))
            is entry
        )

    def _snapshot(self, entry: _OrderEntry) -> _BindingSnapshot:
        return _BindingSnapshot(self, entry)

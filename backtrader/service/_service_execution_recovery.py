"""Backtrader recovery bindings for the SDK service execution flow.

The SDK owns recovery journals and neutral events. This module owns framework
strategy/Order bindings, trade projection, and local error adaptation.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
import hashlib
import json
from typing import Any, Optional

from ..execution.managed_execution import ManagedExecutionAdapterError

_RECOVERY_OWNER_PROJECTION_SCHEMA = "backtrader.service-execution-owner-projection.v1"
_RECOVERY_OWNER_PROJECTION_SCHEMA_V2 = "backtrader.service-execution-owner-projection.v2"
_STRATEGY_POSITION_OWNER_SCHEMA = "backtrader.strategy-position-owner.v1"
_STRATEGY_POSITION_BINDING_SCHEMA = "bt_api.strategy-position-binding.v1"
_LOCAL_STRATEGY_POSITION_KEY_PREFIX = "btlocal1_"


class ServiceExecutionAdapterError(ManagedExecutionAdapterError):
    """Finite local diagnostics for an unusable service execution adapter."""


class ServiceExecutionReadError(ServiceExecutionAdapterError):
    """A durable-record read failed and must not change order business state.

    ``applied_refs`` is filled by the Broker when a later read in the same
    refresh pass fails.  The refresh scheduler can then retain accurate apply
    counters while still treating the pass as failed and backing off.
    """

    def __init__(self, code: str, *, applied_refs: tuple[Any, ...] = ()) -> None:
        if (
            type(code) is not str
            or not code
            or len(code) > 64
            or not code.isascii()
            or not all(character.isalnum() or character in "_.-" for character in code)
        ):
            code = "service_execution_read_failed"
        self.code = code
        self.applied_refs = tuple(applied_refs)
        super().__init__(f"Managed service read failed ({code})")


def _owner_book_payload(snapshot: Any) -> dict[str, Any]:
    """Bind the execution-owned projection to the Backtrader error type."""
    from bt_api_py.service_recovery import project_service_owner_book_payload

    return project_service_owner_book_payload(snapshot, error_type=ServiceExecutionReadError)


def _order_recovery_binding(order: Any) -> Optional[dict[str, Any]]:
    tradeid = getattr(order, "tradeid", None)
    data_name = _data_name(order)
    if type(tradeid) is not int or not _reference(data_name):
        return None
    return {"tradeid": tradeid, "data_name": data_name}


def _local_strategy_position_key_ref(data_name: str, tradeid: int) -> Optional[str]:
    if not _reference(data_name) or type(tradeid) is not int or tradeid < 0:
        return None
    try:
        identity_json = json.dumps(
            {"data_name": data_name, "tradeid": tradeid},
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError):
        return None
    digest = hashlib.sha256(
        b"backtrader.strategy-position-key.v1\0" + identity_json.encode("utf-8")
    ).hexdigest()
    return _LOCAL_STRATEGY_POSITION_KEY_PREFIX + digest


def _strategy_position_owner_payload(
    data_name: str, tradeid: int, local_key_ref: str
) -> dict[str, Any]:
    from bt_api_py.service_recovery import is_local_strategy_position_key_ref
    if (
        not _reference(data_name)
        or type(tradeid) is not int
        or tradeid < 0
        or not is_local_strategy_position_key_ref(local_key_ref)
        or _local_strategy_position_key_ref(data_name, tradeid) != local_key_ref
    ):
        raise ServiceExecutionReadError("recovery_strategy_position_owner_invalid")
    return {
        "schema": _STRATEGY_POSITION_OWNER_SCHEMA,
        "data_name": data_name,
        "tradeid": tradeid,
        "local_position_key_ref": local_key_ref,
    }


def _position_owner_payload_matches(
    value: Any, data_name: Any, tradeid: Any, local_key_ref: Any
) -> bool:
    if not isinstance(value, Mapping) or frozenset(value) != {
        "schema",
        "data_name",
        "tradeid",
        "local_position_key_ref",
    }:
        return False
    expected_key = _local_strategy_position_key_ref(data_name, tradeid)
    return (
        value.get("schema") == _STRATEGY_POSITION_OWNER_SCHEMA
        and _reference(data_name)
        and type(tradeid) is int
        and tradeid >= 0
        and value.get("data_name") == data_name
        and type(value.get("tradeid")) is int
        and value.get("tradeid") == tradeid
        and expected_key is not None
        and expected_key == local_key_ref
        and value.get("local_position_key_ref") == local_key_ref
    )


def _data_name(order: Any) -> Optional[str]:
    data = getattr(order, "data", None)
    for attribute in ("_name", "dataname", "name"):
        value = getattr(data, attribute, None)
        if isinstance(value, str) and value:
            return value
    return None


def _recovery_error_code(error: BaseException) -> str:
    """Read an SDK's finite code without importing its implementation errors."""

    code = getattr(error, "code", None)
    if (
        type(code) is str
        and code
        and len(code) <= 96
        and code.isascii()
        and all(character.isalnum() or character in "_.:-" for character in code)
    ):
        return code
    return "recovery_flow_failed"


def _reference(value: Any) -> bool:
    from bt_api_py.service_execution import is_service_execution_reference

    return is_service_execution_reference(value)


class ServiceExecutionRecoveryMixin:
    """Bind framework recovery state to an injected SDK recovery flow."""

    def bind_recovery_namespace(self, namespace: Any) -> None:
        """Bind the opaque SDK namespace to the injected recovery flow."""

        flow = self._require_recovery_flow()
        try:
            flow.bind(namespace)
        except Exception as error:  # noqa: BLE001 - preserve a finite adapter boundary
            raise ServiceExecutionAdapterError(_recovery_error_code(error)) from None

    @property
    def recovery_namespace(self) -> Any:
        flow = self._require_recovery_flow()
        return flow.namespace

    def configure_recovery_event_context_resolver(self, resolver: Callable[..., Any]) -> None:
        """Install the Broker's immutable paper-fill-to-feed context mapper."""

        if not callable(resolver):
            raise ServiceExecutionAdapterError("invalid recovery event context resolver")
        flow = self._require_recovery_flow()
        try:
            flow.configure_event_context_resolver(resolver)
        except Exception as error:  # noqa: BLE001 - preserve a finite adapter boundary
            raise ServiceExecutionAdapterError(_recovery_error_code(error)) from None

    def configure_recovery_intent_context_resolver(
        self, resolver: Callable[[Any], Any]
    ) -> None:
        """Retain the BT Order to neutral recovery-context mapper locally."""

        if not callable(resolver):
            raise ServiceExecutionAdapterError("invalid recovery intent context resolver")
        self._require_recovery_flow()
        current = self._recovery_intent_context_resolver
        if current is not None and current is not resolver:
            raise ServiceExecutionAdapterError("recovery intent context resolver already configured")
        self._recovery_intent_context_resolver = resolver

    def ensure_strategy_genesis(self, *, trade_ledger_empty: bool) -> Mapping[str, Any]:
        """Bind V2 recovery to the run's original cut and an empty Strategy ledger."""

        if self._recovery_event_version != 2:
            raise ServiceExecutionReadError("strategy_genesis_requires_recovery_v2")
        try:
            return self._require_recovery().ensure_strategy_genesis(
                trade_ledger_empty=trade_ledger_empty
            )
        except Exception as error:  # noqa: BLE001 - recovery stays fail-closed
            raise ServiceExecutionReadError(_recovery_error_code(error)) from None

    def acquire_recovery_consumer_lease(self, owner_token: str) -> None:
        try:
            self._require_recovery().acquire_consumer_lease(owner_token)
        except Exception as error:  # noqa: BLE001 - recovery stays fail-closed
            raise ServiceExecutionReadError(_recovery_error_code(error)) from None

    def renew_recovery_consumer_lease(self, owner_token: str) -> None:
        flow = self._require_recovery()
        try:
            # The SDK recovery owner validates its current lease token and
            # retains the durable lease state; the framework adapter only
            # maps its finite failure into the Broker-facing read error.
            flow.renew_consumer_lease(owner_token)
        except Exception as error:  # noqa: BLE001 - recovery stays fail-closed
            raise ServiceExecutionReadError(_recovery_error_code(error)) from None

    def release_recovery_consumer_lease(self, owner_token: str) -> None:
        try:
            self._require_recovery().release_consumer_lease(owner_token)
        except Exception as error:  # noqa: BLE001 - recovery stays fail-closed
            raise ServiceExecutionReadError(_recovery_error_code(error)) from None

    def initialize_recovery(
        self,
        *,
        owner_book_reader: Optional[Callable[[], Any]] = None,
        page_limit: int = 128,
        max_pages: int = 64,
    ) -> Mapping[str, Any]:
        """Delegate snapshot and event-tail installation to the SDK flow."""

        if callable(owner_book_reader):
            source_reader = owner_book_reader
            owner_book_reader = lambda: _owner_book_payload(source_reader())
        try:
            return self._require_recovery().initialize(
                owner_book_reader=owner_book_reader,
                page_limit=page_limit,
                max_pages=max_pages,
            )
        except Exception as error:  # noqa: BLE001 - recovery reads fail closed
            raise ServiceExecutionReadError(self._recovery_read_code(error)) from None

    def refresh_recovery_cut(self) -> Mapping[str, Any]:
        """Revalidate the current service cut before admitting a new intent."""

        try:
            return self._require_recovery().refresh_cut()
        except Exception as error:  # noqa: BLE001 - recovery reads fail closed
            raise ServiceExecutionReadError(self._recovery_read_code(error)) from None

    @property
    def recovery_startup_cursor(self) -> Optional[int]:
        flow = self._recovery_flow
        return getattr(flow, "startup_cursor", None) if flow is not None else None

    def recovery_history(self) -> tuple[Mapping[str, Any], ...]:
        try:
            return self._require_recovery().history()
        except Exception as error:  # noqa: BLE001 - recovery reads fail closed
            raise ServiceExecutionReadError(self._recovery_read_code(error)) from None

    def recovery_baseline(self) -> Optional[Mapping[str, Any]]:
        try:
            return self._require_recovery().baseline()
        except Exception as error:  # noqa: BLE001 - recovery reads fail closed
            raise ServiceExecutionReadError(self._recovery_read_code(error)) from None

    @property
    def recovery_owner_position_reconciliation(self) -> Optional[Mapping[str, Any]]:
        """Return the latest SDK-owned local owner-book comparison."""

        flow = self._recovery_flow
        value = getattr(flow, "owner_position_reconciliation", None)
        return deepcopy(value) if isinstance(value, Mapping) else None

    def recovery_manifest(self, intent_id: str) -> Optional[Mapping[str, Any]]:
        try:
            manifest = self._require_recovery().manifest(intent_id)
            if manifest is not None and type(manifest) is not self._recovery_manifest_type:
                raise ServiceExecutionReadError("recovery_manifest_projection_invalid")
            return manifest
        except ServiceExecutionReadError:
            raise
        except Exception as error:  # noqa: BLE001 - recovery reads fail closed
            raise ServiceExecutionReadError(self._recovery_read_code(error)) from None

    def recovery_strategy_position_ref_for_key(
        self, data_name: str, tradeid: int
    ) -> Optional[str]:
        local_key_ref = _local_strategy_position_key_ref(data_name, tradeid)
        if local_key_ref is None:
            raise ServiceExecutionReadError("recovery_strategy_position_key_invalid")
        try:
            flow = self._require_recovery()
            reference = flow.strategy_position_ref_for_key(local_key_ref)
            if reference is None:
                return None
            if type(reference) is not self._recovery_position_ref_type:
                raise ServiceExecutionReadError("recovery_strategy_position_ref_invalid")
            owner = flow.strategy_position_owner_payload(reference)
            if not _position_owner_payload_matches(owner, data_name, tradeid, local_key_ref):
                raise ServiceExecutionReadError("recovery_strategy_position_owner_invalid")
            return reference.value
        except ServiceExecutionReadError:
            raise
        except Exception as error:  # noqa: BLE001 - recovery reads fail closed
            raise ServiceExecutionReadError(self._recovery_read_code(error)) from None

    def recovery_strategy_position_owner(self, strategy_position_ref: str) -> Mapping[str, Any]:
        from bt_api_py.service_recovery import is_strategy_position_ref
        if not is_strategy_position_ref(strategy_position_ref):
            raise ServiceExecutionReadError("recovery_strategy_position_ref_invalid")
        try:
            flow = self._require_recovery()
            reference = self._recovery_position_ref_type(strategy_position_ref)
            owner = flow.strategy_position_owner_payload(reference)
            if not isinstance(owner, Mapping):
                raise ServiceExecutionReadError("recovery_strategy_position_owner_unavailable")
            data_name = owner.get("data_name")
            tradeid = owner.get("tradeid")
            local_key_ref = owner.get("local_position_key_ref")
            if not _position_owner_payload_matches(owner, data_name, tradeid, local_key_ref):
                raise ServiceExecutionReadError("recovery_strategy_position_owner_invalid")
            resolved = flow.strategy_position_ref_for_key(local_key_ref)
            if type(resolved) is not self._recovery_position_ref_type or resolved.value != strategy_position_ref:
                raise ServiceExecutionReadError("recovery_strategy_position_owner_invalid")
            return deepcopy(dict(owner))
        except ServiceExecutionReadError:
            raise
        except Exception as error:  # noqa: BLE001 - recovery reads fail closed
            raise ServiceExecutionReadError(self._recovery_read_code(error)) from None

    def recovery_binding_owner(self, binding: Any) -> Mapping[str, Any]:
        """Resolve a legacy BT key or SDK-issued position reference locally."""
        from bt_api_py.service_recovery import is_strategy_position_ref

        if not isinstance(binding, Mapping):
            raise ServiceExecutionReadError("recovery_strategy_position_binding_invalid")
        if frozenset(binding) == {"data_name", "tradeid"}:
            data_name = binding.get("data_name")
            tradeid = binding.get("tradeid")
            if not _reference(data_name) or type(tradeid) is not int or tradeid < 0:
                raise ServiceExecutionReadError("recovery_strategy_position_binding_invalid")
            local_key_ref = _local_strategy_position_key_ref(data_name, tradeid)
            position_ref = self.recovery_strategy_position_ref_for_key(data_name, tradeid)
            return {
                "data_name": data_name,
                "tradeid": tradeid,
                "local_position_key_ref": local_key_ref,
                "strategy_position_ref": position_ref,
            }
        if (
            frozenset(binding)
            != {"schema", "local_position_key_ref", "strategy_position_ref"}
            or binding.get("schema") != _STRATEGY_POSITION_BINDING_SCHEMA
            or not _local_strategy_position_key_ref(binding.get("local_position_key_ref"))
            or not is_strategy_position_ref(binding.get("strategy_position_ref"))
        ):
            raise ServiceExecutionReadError("recovery_strategy_position_binding_invalid")
        position_ref = binding["strategy_position_ref"]
        owner = self.recovery_strategy_position_owner(position_ref)
        if owner.get("local_position_key_ref") != binding.get("local_position_key_ref"):
            raise ServiceExecutionReadError("recovery_strategy_position_binding_mismatch")
        return {
            "data_name": owner["data_name"],
            "tradeid": owner["tradeid"],
            "local_position_key_ref": owner["local_position_key_ref"],
            "strategy_position_ref": position_ref,
        }

    def recovery_intent_execution_context(
        self, intent_id: str
    ) -> Optional[Mapping[str, Any]]:
        try:
            return self._require_recovery().intent_execution_context(intent_id)
        except Exception as error:  # noqa: BLE001 - recovery reads fail closed
            raise ServiceExecutionReadError(self._recovery_read_code(error)) from None

    def claim_recovery_callback(self, receipt_id: str) -> Any:
        try:
            return self._require_recovery().claim_callback(receipt_id)
        except Exception as error:  # noqa: BLE001 - recovery reads fail closed
            raise ServiceExecutionReadError(self._recovery_read_code(error)) from None

    def acknowledge_recovery_callback(self, receipt_id: str) -> None:
        try:
            self._require_recovery().acknowledge_callback(receipt_id)
        except Exception as error:  # noqa: BLE001 - recovery writes fail closed
            raise ServiceExecutionReadError(self._recovery_read_code(error)) from None

    def _decode_recovery_owner_projection(
        self, projection: Any, *, receipt_id: Optional[str] = None
    ) -> Mapping[str, Any]:
        from bt_api_py.service_recovery import is_strategy_position_ref
        validator = self._recovery_owner_projection_validator
        if validator is None or not validator(projection, receipt_id=receipt_id):
            raise ServiceExecutionReadError("recovery_owner_projection_invalid")
        payload = projection.payload
        if projection.legacy:
            expected_fields = {
                "owner_ref",
                "local_key",
                "state_payload",
                "notification_payloads",
            }
            owner_ref = payload.get("owner_ref")
            local_key = payload.get("local_key")
            state = payload.get("state_payload")
            notifications = payload.get("notification_payloads")
            schema_valid = True
            strategy_position_ref = None
        else:
            expected_fields = {
                "schema",
                "owner_ref",
                "local_key",
                "state_payload",
                "notification_payloads",
            }
            owner_ref = payload.get("owner_ref")
            local_key = payload.get("local_key")
            state = payload.get("state_payload")
            notifications = payload.get("notification_payloads")
            strategy_position_ref = payload.get("strategy_position_ref")
            schema_valid = payload.get("schema") == _RECOVERY_OWNER_PROJECTION_SCHEMA
            if payload.get("schema") == _RECOVERY_OWNER_PROJECTION_SCHEMA_V2:
                expected_fields.add("strategy_position_ref")
                schema_valid = is_strategy_position_ref(strategy_position_ref)
        if frozenset(payload) != expected_fields:
            raise ServiceExecutionReadError("recovery_owner_projection_invalid")
        if (
            not schema_valid
            or type(owner_ref) is not str
            or not owner_ref
            or type(local_key) is not int
            or not isinstance(state, Mapping)
            or state.get("data_name") != owner_ref
            or type(state.get("tradeid")) is not int
            or state.get("tradeid") != local_key
            or type(notifications) is not list
            or len(notifications) != 1
            or not isinstance(notifications[0], Mapping)
            or frozenset(notifications[0]) != {"callback", "data_name", "tradeid"}
            or notifications[0].get("callback") != "notify_trade"
            or notifications[0].get("data_name") != owner_ref
            or type(notifications[0].get("tradeid")) is not int
            or notifications[0].get("tradeid") != local_key
            or (
                strategy_position_ref is not None
                and not is_strategy_position_ref(strategy_position_ref)
            )
            or (
                isinstance(state, Mapping)
                and state.get("schema") == "backtrader.managed_paper_trade.v2"
                and state.get("strategy_position_ref") != strategy_position_ref
            )
        ):
            raise ServiceExecutionReadError("recovery_owner_projection_invalid")
        return {
            "data_name": owner_ref,
            "tradeid": local_key,
            "state": deepcopy(dict(state)),
            "trade_notification": deepcopy(notifications),
            "receipt_id": projection.receipt_ref,
            "sequence": projection.sequence,
            "legacy": projection.legacy,
            "strategy_position_ref": strategy_position_ref,
        }

    def recovery_fill_projection(self, receipt_id: str) -> Optional[Mapping[str, Any]]:
        try:
            flow = self._require_recovery()
            value = flow.fill_projection(receipt_id)
            if value is None:
                return None
            if not isinstance(value, Mapping):
                raise ServiceExecutionReadError("recovery_fill_projection_invalid")
            result = deepcopy(dict(value))
            owner_projection = flow.owner_projection(receipt_id)
            if owner_projection is None:
                return result
            decoded = self._decode_recovery_owner_projection(
                owner_projection, receipt_id=receipt_id
            )
            legacy_state = result.get("trade_state")
            legacy_notifications = result.get("trade_notification")
            if legacy_state is None and legacy_notifications is None:
                result["trade_state"] = decoded["state"]
                result["trade_notification"] = decoded["trade_notification"]
            elif (
                legacy_state != decoded["state"]
                or legacy_notifications != decoded["trade_notification"]
            ):
                raise ServiceExecutionReadError("recovery_owner_projection_conflict")
            if decoded.get("strategy_position_ref") is not None:
                result["strategy_position_ref"] = decoded["strategy_position_ref"]
            return result
        except Exception as error:  # noqa: BLE001 - recovery reads fail closed
            raise ServiceExecutionReadError(self._recovery_read_code(error)) from None

    def persist_recovery_trade_projection(
        self,
        receipt_id: str,
        *,
        data_name: str,
        tradeid: int,
        trade_state: Mapping[str, Any],
        trade_notifications: Any,
        strategy_position_ref: Optional[str] = None,
    ) -> Mapping[str, Any]:
        from bt_api_py.service_recovery import is_strategy_position_ref
        try:
            flow = self._require_recovery()
            notifications = deepcopy(list(trade_notifications))
            local_key_ref = _local_strategy_position_key_ref(data_name, tradeid)
            if local_key_ref is None:
                raise ServiceExecutionReadError("recovery_strategy_position_key_invalid")
            if strategy_position_ref is not None and not is_strategy_position_ref(
                strategy_position_ref
            ):
                raise ServiceExecutionReadError("recovery_strategy_position_ref_invalid")
            owner_payload = _strategy_position_owner_payload(
                data_name, tradeid, local_key_ref
            )
            if strategy_position_ref is None:
                strategy_position_ref = self.recovery_strategy_position_ref_for_key(
                    data_name, tradeid
                )
            if strategy_position_ref is not None:
                known = flow.strategy_position_ref_for_key(local_key_ref)
                if (
                    type(known) is not self._recovery_position_ref_type
                    or known.value != strategy_position_ref
                ):
                    raise ServiceExecutionReadError("recovery_strategy_position_ref_mismatch")
            payload = {
                "schema": (
                    _RECOVERY_OWNER_PROJECTION_SCHEMA_V2
                    if strategy_position_ref is not None
                    else _RECOVERY_OWNER_PROJECTION_SCHEMA
                ),
                "owner_ref": data_name,
                "local_key": tradeid,
                "state_payload": deepcopy(dict(trade_state)),
                "notification_payloads": notifications,
            }
            if strategy_position_ref is not None:
                payload["strategy_position_ref"] = strategy_position_ref
            projection = self._recovery_owner_projection_type(
                receipt_ref=receipt_id,
                payload=payload,
                strategy_position_key_ref=local_key_ref,
                strategy_position_owner_payload=owner_payload,
            )
            persisted = flow.persist_owner_projection(projection)
            if not isinstance(persisted, Mapping):
                raise ServiceExecutionReadError("recovery_owner_projection_invalid")
            result = deepcopy(dict(persisted))
            persisted_ref = result.get("strategy_position_ref")
            if not is_strategy_position_ref(persisted_ref):
                raise ServiceExecutionReadError("recovery_strategy_position_ref_unavailable")
            if strategy_position_ref is not None and persisted_ref != strategy_position_ref:
                raise ServiceExecutionReadError("recovery_strategy_position_ref_mismatch")
            result["strategy_position_ref"] = persisted_ref
            result["trade_state"] = deepcopy(dict(trade_state))
            result["trade_notification"] = notifications
            return result
        except Exception as error:  # noqa: BLE001 - recovery writes fail closed
            raise ServiceExecutionReadError(self._recovery_read_code(error)) from None

    def recovery_trade_checkpoints(self) -> tuple[Mapping[str, Any], ...]:
        try:
            flow = self._require_recovery()
            legacy_projected: dict[tuple[str, int], Mapping[str, Any]] = {}
            new_projected: dict[tuple[str, int], Mapping[str, Any]] = {}
            latest_sequence: dict[tuple[str, int], int] = {}
            owner_values = flow.owner_projections()
            if type(owner_values) is not tuple:
                raise ServiceExecutionReadError("recovery_trade_checkpoints_invalid")
            for value in owner_values:
                decoded = self._decode_recovery_owner_projection(value)
                key = (decoded["data_name"], decoded["tradeid"])
                strategy_position_ref = decoded.get("strategy_position_ref")
                if strategy_position_ref is None:
                    strategy_position_ref = self.recovery_strategy_position_ref_for_key(*key)
                elif self.recovery_strategy_position_ref_for_key(*key) != strategy_position_ref:
                    raise ServiceExecutionReadError("recovery_trade_position_ref_conflict")
                checkpoint = {
                    "data_name": decoded["data_name"],
                    "tradeid": decoded["tradeid"],
                    "state": decoded["state"],
                    "receipt_id": decoded["receipt_id"],
                }
                if strategy_position_ref is not None:
                    checkpoint["strategy_position_ref"] = strategy_position_ref
                if decoded["legacy"]:
                    if key in legacy_projected:
                        raise ServiceExecutionReadError(
                            "recovery_trade_checkpoints_invalid"
                        )
                    legacy_projected[key] = checkpoint
                    continue
                sequence = decoded["sequence"]
                if type(sequence) is not int:
                    raise ServiceExecutionReadError("recovery_trade_checkpoints_invalid")
                if sequence > latest_sequence.get(key, 0):
                    new_projected[key] = checkpoint
                    latest_sequence[key] = sequence
            if set(legacy_projected).intersection(new_projected):
                raise ServiceExecutionReadError(
                    "recovery_trade_checkpoint_mixed_schema_ambiguous"
                )
            projected = {**legacy_projected, **new_projected}
            return tuple(projected[key] for key in sorted(projected))
        except Exception as error:  # noqa: BLE001 - recovery reads fail closed
            raise ServiceExecutionReadError(self._recovery_read_code(error)) from None

    def refresh_recovery_events(
        self,
        *,
        callback: Optional[Callable[[Any], Any]] = None,
        page_limit: int = 128,
        max_pages: int = 64,
        callback_limit: int = 32,
    ) -> Mapping[str, Any]:
        """Delegate ordered event consumption and callback delivery to the SDK."""

        try:
            return self._require_recovery().refresh_events(
                callback=callback,
                page_limit=page_limit,
                max_pages=max_pages,
                callback_limit=callback_limit,
            )
        except Exception as error:  # noqa: BLE001 - recovery reads fail closed
            raise ServiceExecutionReadError(self._recovery_read_code(error)) from None

    def _require_recovery_flow(self) -> Any:
        flow = self._recovery_flow
        if flow is None:
            raise ServiceExecutionReadError("recovery_namespace_unavailable")
        return flow

    def _require_recovery(self) -> Any:
        flow = self._require_recovery_flow()
        namespace = getattr(flow, "namespace", None)
        if namespace is None:
            raise ServiceExecutionReadError("recovery_namespace_unavailable")
        return flow

    def _strategy_position_binding_for_order(self, order: Any, intent_id: str):
        from bt_api_py.service_recovery import is_strategy_position_ref
        raw_binding = _order_recovery_binding(order)
        if raw_binding is None:
            raise ServiceExecutionReadError("recovery_strategy_position_key_invalid")
        data_name = raw_binding["data_name"]
        tradeid = raw_binding["tradeid"]
        local_key_ref = _local_strategy_position_key_ref(data_name, tradeid)
        if local_key_ref is None:
            raise ServiceExecutionReadError("recovery_strategy_position_key_invalid")
        owner_payload = _strategy_position_owner_payload(data_name, tradeid, local_key_ref)
        manifest = self.recovery_manifest(intent_id)
        if manifest is not None:
            stored = manifest.get("recovery_binding")
            if not isinstance(stored, Mapping):
                raise ServiceExecutionReadError("recovery_strategy_position_binding_invalid")
            if frozenset(stored) == {"data_name", "tradeid"}:
                if dict(stored) != raw_binding:
                    raise ServiceExecutionReadError("recovery_strategy_position_binding_mismatch")
                return raw_binding, None, local_key_ref
            if (
                stored.get("schema") != _STRATEGY_POSITION_BINDING_SCHEMA
                or stored.get("local_position_key_ref") != local_key_ref
                or not is_strategy_position_ref(stored.get("strategy_position_ref"))
            ):
                raise ServiceExecutionReadError("recovery_strategy_position_binding_mismatch")
            reference = self._recovery_position_ref_type(stored["strategy_position_ref"])
            stored_owner = self._require_recovery().strategy_position_owner_payload(reference)
            if not _position_owner_payload_matches(
                stored_owner, data_name, tradeid, local_key_ref
            ):
                raise ServiceExecutionReadError("recovery_strategy_position_owner_mismatch")
            return dict(stored), owner_payload, local_key_ref

        position_ref = self.recovery_strategy_position_ref_for_key(data_name, tradeid)
        binding = {
            "schema": _STRATEGY_POSITION_BINDING_SCHEMA,
            "local_position_key_ref": local_key_ref,
        }
        if position_ref is not None:
            binding["strategy_position_ref"] = position_ref
        return binding, owner_payload, local_key_ref

    def _attach_strategy_position_ref(self, order: Any, local_key_ref: Optional[str], value: Any):
        from bt_api_py.service_recovery import is_strategy_position_ref
        if local_key_ref is not None:
            addinfo = getattr(order, "addinfo", None)
            if callable(addinfo):
                addinfo(service_execution_local_position_key_ref=local_key_ref)
        if value is None:
            return None
        reference = (
            value.value
            if type(value) is self._recovery_position_ref_type
            else value
        )
        if not is_strategy_position_ref(reference):
            raise ServiceExecutionReadError("recovery_strategy_position_ref_invalid")
        addinfo = getattr(order, "addinfo", None)
        if not callable(addinfo):
            raise ServiceExecutionReadError("recovery_order_metadata_unavailable")
        addinfo(service_execution_strategy_position_ref=reference)
        return reference

    @staticmethod
    def _recovery_read_code(error: BaseException) -> str:
        if isinstance(error, TimeoutError):
            return "service_execution_recovery_read_timeout"
        code = _recovery_error_code(error)
        if code == "service_execution_request_failed":
            return "service_execution_recovery_read_failed"
        return f"service_execution_{code.lower()}"

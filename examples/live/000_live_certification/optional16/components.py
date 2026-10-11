"""Optional-component mounts for the Iteration-41 ``optional16`` matrix.

``wrap_client(client, config, topology, env)`` (frozen signature) wraps the
venue client the certification cases already use (direct ``BinanceDemoClient``
or ``optional16.GatewayClient``) with up to three optional components while
keeping the case-facing surface unchanged: ``connect``, ``account_config``,
``balances``, ``position_risk``, ``open_orders``, ``query_order``, ``filters``,
``mark_price``, ``place_order``, ``cancel_order``, ``describe``, ``calls``
(+ ``close``, ``frozen`` and every other attribute delegated to the base).

* ``risk``      -- dev SDK ``bt_api_risk`` durable gate around ``place_order``:
                   ``reserve`` -> ``claim_for_dispatch`` -> dispatch -> ``settle``.
* ``execution`` -- dev SDK ``bt_api_execution`` ``ManagedExecutionFacade``
                   around ``place_order`` and ``ManagedCancellationFacade``
                   around ``cancel_order`` in a per-run SQLite store; with
                   ``risk`` enabled both share the real gate through the SDK's
                   ``SharedRiskAdmissionAdapter``.
* ``monitor``   -- dev SDK ``bt_api_monitor`` ``DurableOutbox``: one durable
                   append + acknowledge per operation plus a signed
                   ``ReadOnlyEventService`` readback of the acknowledged page.

The same mounts accept the OKX v5 client surface as well
(``place_order(inst_id, side, sz=..., px=..., ord_type=..., pos_side=...)`` and
``cancel_order(inst_id, ord_id=..., cl_ord_id=...)``): ``sz``/``px``/
``ord_type`` are read as the quantity/price/order-type aliases for the mount's
own notional and intent math and the native tracking keyword (``cl_ord_id``)
takes the place of ``client_order_id``, while the provider dispatch always
receives the caller's own arguments.  ``policy.quantity_multiplier`` (contract
or maker multiplier, default 1) converts the venue quantity into notional and
the execution/risk scope's provider label comes from ``config["venue"]``
(default ``binance``).

Rules and dev-SDK snapshot limits (the README.md documents them in full):
a disabled component's package is never imported (``describe()`` reports the
``sys.modules`` delta); only real published SDK entry points are used and the
composition choices are recorded in ``adapter_notes``; an enabled-but-
unimportable component raises ``RuntimeError("component_unavailable:<name>")``;
a risk rejection raises ``RuntimeError("risk_rejected:<code>")`` before any
provider dispatch.  ``claim_for_dispatch`` installs the gate's durable
``dispatch-inflight`` latch with no resolver installed here, so one run admits
one risk-increasing order and a second ``place_order`` is rejected
``risk_rejected:FROZEN``.  ``MARKET`` orders have no pre-dispatch notional and
fail closed with ``risk`` enabled.  A post-dispatch settlement/review failure
is recorded but still returns the venue reply so the caller keeps the order
identity it must cancel.
"""

from __future__ import annotations

import hashlib
import inspect
import os
import re
import sys
import tempfile
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping

__all__ = ["ComponentError", "ComponentClientWrapper", "wrap_client"]

COMPONENT_FLAGS = ("execution", "risk", "monitor")
_PACKAGE_NAMES = {"execution": "bt_api_execution", "risk": "bt_api_risk", "monitor": "bt_api_monitor"}
_SDK_ROOT_ENV, _RUN_DIR_ENV, _DEFAULT_SDK_ROOT = "OPTIONAL16_SDK_ROOT", "OPTIONAL16_RUN_DIR", "D:/bt_api_py/bt_api"
_SCOPE, _CONSUMER = "optional16", "optional16-matrix"
_READBACK_TYPES = ("connect", "place_order", "cancel_order", "query_order")
_PLACE_POSITIONAL = ("order_type", "quantity", "price", "position_side", "time_in_force",
                     "reduce_only", "client_order_id", "close_position", "working_type")
_PLACE_ALIASES = (("sz", "quantity"), ("px", "price"), ("ord_type", "order_type"),
                  ("cl_ord_id", "client_order_id"))
_ALIAS_KEYS = ("sz", "px", "ord_type", "pos_side", "td_mode", "cl_ord_id")
_VENUE_REJECT_RE = re.compile(r"code=-?\d+")


class ComponentError(RuntimeError):
    """One requested optional component could not be mounted (fail closed)."""


# ------------------------------------------------------------------- helpers
def _flag(topology, name):
    return bool(topology.get(name)) if isinstance(topology, Mapping) else bool(getattr(topology, name, False))


def _transport(topology):
    value = topology.get("transport") if isinstance(topology, Mapping) else getattr(topology, "transport", None)
    return str(value or "direct")


def _case_id(config):
    value = str(config.get("case_id") or "case")
    return "".join(c for c in value if c.isalnum() or c in "._:-") or "case"


def _env_name(config):
    section = config.get("environment") or {}
    return str(section.get("name") or "demo") if isinstance(section, Mapping) else "demo"


def _account_ref(config, provider="binance"):
    """Synthetic per-config account reference from public fields only (never credentials)."""
    section = config.get("environment") or {}
    host = str(section.get("base_url") or "") if isinstance(section, Mapping) else ""
    seed = str(provider) + "|" + host + "|" + _env_name(config)
    return "o16-" + hashlib.sha256(seed.encode()).hexdigest()[:16]


def _run_dir(env):
    override = str(env.get(_RUN_DIR_ENV) or "") if isinstance(env, Mapping) else ""
    if override:
        path = Path(override)
        path.mkdir(parents=True, exist_ok=True)
        return path
    return Path(tempfile.mkdtemp(prefix="optional16-run-"))


def _import_snapshot():
    return {pkg for pkg in _PACKAGE_NAMES.values() if pkg in sys.modules}


def _load_component(name):
    """Import one optional dev-SDK package, adding its src path only now."""
    import importlib

    for package in (["base", "monitor"] if name == "monitor" else [name]):
        src = Path(os.environ.get(_SDK_ROOT_ENV) or _DEFAULT_SDK_ROOT) / ("bt_api_" + package) / "src"
        if src.is_dir() and str(src) not in sys.path:
            sys.path.insert(0, str(src))
    return importlib.import_module(_PACKAGE_NAMES[name])


def _decimal(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _first_present(mapping, *names):
    for name in names:
        value = mapping.get(name)
        if value is not None:
            return value
    return None


def _inspection_view(merged):
    """Canonical alias view of one call for the mount's own math.

    The view is never forwarded to the base client: the dispatch always keeps
    the caller's own keyword names (``sz``/``px``/``ord_type`` stay ``sz``/
    ``px``/``ord_type``; nothing is rewritten into binance naming).
    """
    view = dict(merged)
    for alias, canonical in _PLACE_ALIASES:
        if view.get(canonical) is None and alias in merged:
            view[canonical] = merged[alias]
    return view


def _quantity_multiplier(config):
    """Contract/maker multiplier from ``policy.quantity_multiplier`` (default 1).

    Accepted as int/float/str and must be strictly positive; anything else
    (including ``bool`` and ``None``) fails closed before any mount is built.
    """
    policy = config.get("policy") if isinstance(config, Mapping) else None
    if not isinstance(policy, Mapping) or "quantity_multiplier" not in policy:
        return Decimal(1)
    value = _decimal(policy.get("quantity_multiplier"))
    if value is None or value <= 0:
        raise ComponentError("policy_quantity_multiplier_invalid")
    return value


def _client_id_param(client):
    """Native client-order-id keyword of the base ``place_order`` (or None)."""
    try:
        params = inspect.signature(client.place_order).parameters
    except (TypeError, ValueError):
        return None
    if "cl_ord_id" in params:
        return "cl_ord_id"  # OKX v5 surface
    if "client_order_id" in params:
        return "client_order_id"  # binance surface
    return None


def _reply_order_id(reply):
    """Provider order id from either venue reply shape (``orderId``/``ordId``)."""
    value = _first_present(reply, "orderId", "ordId") if isinstance(reply, Mapping) else None
    return None if value is None else str(value)


def _code(exc):
    code = getattr(exc, "code", None)
    return code if isinstance(code, str) and code else type(exc).__name__


def _is_venue_rejection(exc):
    """Split a write failure into 'venue answered no' vs unknown outcome."""
    if getattr(exc, "code", None) is not None and hasattr(exc, "msg"):
        return True  # direct client BinanceApiError
    return "Rejected" in type(exc).__name__ and _VENUE_REJECT_RE.search(str(exc)) is not None


def _get(value, key):
    return value.get(key) if isinstance(value, Mapping) else None


def _cid():
    return "o16" + uuid.uuid4().hex[:20]


# ----------------------------------------------------------------- risk mount
class _RiskMount:
    """Smallest honest mount over the real ``bt_api_risk`` durable gate."""
    def __init__(self, run_dir, config, notes, provider="binance"):
        from bt_api_risk.core.admission import AccountScope, DurableRiskGate, RiskPolicy

        policy = config.get("policy") or {}
        max_orders = policy.get("max_orders")
        self.policy_id = "optional16-" + _case_id(config)
        self.gate_db = Path(run_dir) / "risk.sqlite"
        self.policy = RiskPolicy(policy_id=self.policy_id,
                                 max_increase_notional=_decimal(policy.get("max_notional_usdt")) or Decimal("0"),
                                 max_increase_count=int(max_orders) if isinstance(max_orders, int) and max_orders >= 0 else 1)
        self.gate = DurableRiskGate(self.gate_db, self.policy)
        self.account = AccountScope(provider=provider, account_id=_account_ref(config, provider),
                                    environment=_env_name(config))
        self.counts = {"reserved": 0, "claimed": 0, "settled": 0, "dispatch_unknown": 0}
        self.denials, self.last_denial = {}, ""
        notes.append("risk policy from case config: max_orders=%d max_notional_usdt=%s"
                     % (self.policy.max_increase_count, self.policy.max_increase_notional))
        notes.append("the gate's dispatch-inflight latch has no resolver here: one INCREASE order per run")
    def count(self, name):
        self.counts[name] = self.counts.get(name, 0) + 1
    def record_denial(self, code):
        self.denials[code] = self.denials.get(code, 0) + 1
        self.last_denial = code
    def admit_increase(self, intent_id, notional):
        """reserve -> claim; raises ``risk_rejected:<code>`` before dispatch."""
        from bt_api_risk.core.admission import IntentAction, RiskGateError, RiskIntent

        intent = RiskIntent(intent_id=intent_id, scope=self.account, action=IntentAction.INCREASE,
                            notional=notional, payload_fingerprint="optional16:" + intent_id)
        try:
            permit = self.gate.reserve(intent)
            self.count("reserved")
            self.gate.claim_for_dispatch(permit.permit_id, intent)
            self.count("claimed")
        except RiskGateError as exc:
            self.record_denial(_code(exc))
            raise ComponentError("risk_rejected:" + _code(exc)) from exc
        return permit
    def settle(self, permit):
        """Post-dispatch settlement; returns a note on failure instead of losing the order."""
        try:
            self.gate.settle(permit.permit_id)
            self.count("settled")
            return None
        except Exception as exc:
            self.record_denial("SETTLE_" + _code(exc))
            return "risk_settle_failed:" + _code(exc)
    def facts(self):
        try:
            snapshot = self.gate.snapshot(self.account)
        except Exception as exc:
            snapshot = {"snapshot_error": type(exc).__name__}
        return {"active": True, "package": _PACKAGE_NAMES["risk"], "policy_id": self.policy_id,
                "max_increase_count": self.policy.max_increase_count,
                "max_increase_notional": str(self.policy.max_increase_notional), "gate_db": str(self.gate_db),
                "counts": dict(self.counts), "denials": dict(self.denials), "last_denial": self.last_denial,
                "snapshot": snapshot}


class _DenialRecordingGate:
    """Forward to the SDK ``SharedRiskAdmissionAdapter``; record denial codes.

    ``reserve`` failures re-raise as ``AdmissionDenied`` so the execution
    facade produces a clean no-dispatch rejection record; the exact risk code
    stays on the risk mount for evidence.
    """
    def __init__(self, shared, risk, admission_denied, risk_error):
        self._shared, self._risk, self._admission_denied, self._risk_error = shared, risk, admission_denied, risk_error
    def _forward(self, method, *args):
        try:
            result = getattr(self._shared, method)(*args)
        except Exception as exc:
            self._risk.record_denial(("SETTLE_" if method == "settle" else "") + _code(exc))
            raise
        if method == "claim_for_dispatch":
            self._risk.count("claimed")
        elif method == "settle":
            self._risk.count("settled")
        return result
    def reserve(self, intent):
        try:
            permit = self._shared.reserve(intent)
        except self._risk_error as exc:
            self._risk.record_denial(_code(exc))
            raise self._admission_denied("risk_gate_denied") from exc
        except Exception as exc:
            self._risk.record_denial("MAP_" + _code(exc))
            raise
        self._risk.count("reserved")
        return permit
    def validate(self, permit_reference, intent):
        return self._forward("validate", permit_reference, intent)
    def claim_for_dispatch(self, permit_reference, intent):
        return self._forward("claim_for_dispatch", permit_reference, intent)
    def settle(self, permit_reference):
        return self._forward("settle", permit_reference)
    def release(self, permit_reference, reason):
        return self._forward("release", permit_reference, reason)


class _RiskCancelGate:
    """``CancelAdmissionGate`` over the real risk gate (CANCEL intents)."""
    def __init__(self, risk):
        self._risk = risk
    def _map(self, cancel_intent):
        from bt_api_risk.core.admission import IntentAction, RiskIntent

        return RiskIntent(intent_id="cancel-" + cancel_intent.cancel_id, scope=self._risk.account,
                          action=IntentAction.CANCEL, notional=Decimal("0"),
                          payload_fingerprint=cancel_intent.fingerprint)
    def reserve(self, cancel_intent):
        try:
            permit = self._risk.gate.reserve(self._map(cancel_intent))
        except Exception as exc:
            self._risk.record_denial(_code(exc))
            raise
        self._risk.count("reserved")
        return permit
    def validate(self, permit_reference, cancel_intent):
        return self._risk.gate.validate_permit(permit_reference, self._map(cancel_intent))
    def claim_before_dispatch(self, permit_reference, cancel_intent):
        from bt_api_execution import CancelDispatchClaimReceiptV1

        self._risk.gate.claim_for_dispatch(permit_reference, self._map(cancel_intent))
        self._risk.count("claimed")
        return CancelDispatchClaimReceiptV1(permit_reference=permit_reference,
                                            scope_key=cancel_intent.scope.key,
                                            cancel_id=cancel_intent.cancel_id,
                                            intent_fingerprint=cancel_intent.fingerprint)
    def settle(self, permit_reference):
        self._risk.gate.settle(permit_reference)
        self._risk.count("settled")
    def release(self, permit_reference, reason):
        return self._risk.gate.release(permit_reference, reason)


# -------------------------------------------------------------- execution mount
class _ExecutionMount:
    """Real managed execution/cancellation facades over a per-run SQLite store."""
    def __init__(self, run_dir, config, risk, notes, provider="binance", qty_multiplier=None):
        from bt_api_execution import (AdmissionDenied, ExecutionScope, ManagedCancellationFacade,
                                      ManagedExecutionFacade, SharedRiskAdmissionAdapter,
                                      SqliteExecutionStore)

        self.store_db = Path(run_dir) / "execution.sqlite"
        self.store = SqliteExecutionStore(str(self.store_db))
        case_id = _case_id(config)
        self.qty_multiplier = Decimal(1) if qty_multiplier is None else qty_multiplier
        self.scope = ExecutionScope(provider=provider, environment=_env_name(config),
                                    account_ref=_account_ref(config, provider), strategy_id=case_id)
        self.risk, self.counts, self.last_record, self.notes = risk, {}, {}, []
        if risk is not None:
            # The risk package is imported only when the risk mount is active.
            from bt_api_risk.core.admission import RiskGateError

            gate = _DenialRecordingGate(SharedRiskAdmissionAdapter(risk.gate, self._map_intent),
                                        risk, AdmissionDenied, RiskGateError)
            cancel_gate = _RiskCancelGate(risk)
            self.gate_kind = "SharedRiskAdmissionAdapter(DurableRiskGate)"
        else:
            gate, cancel_gate = None, None
            self.gate_kind = "allow_unprotected"
            notes.append("execution mounted without risk: both facades use the SDK's documented "
                         "allow_unprotected fixture path (no admission permit is issued)")
        self.facade = ManagedExecutionFacade(self.store, self.scope, writer_id="optional16-" + case_id,
                                             admission_gate=gate, allow_unprotected=gate is None)
        self.cancel_facade = ManagedCancellationFacade(
            self.store, self.scope, acquire_writer_lease=self.facade.acquire_writer_lease,
            admission_gate=cancel_gate, allow_unprotected=cancel_gate is None)
    def _map_intent(self, order_intent):
        from bt_api_risk.core.admission import IntentAction, RiskIntent

        return RiskIntent(intent_id=order_intent.intent_id, scope=self.risk.account,
                          action=IntentAction.INCREASE,
                          notional=((order_intent.price or Decimal("0")) * order_intent.quantity
                                    * self.qty_multiplier),
                          payload_fingerprint=order_intent.fingerprint)
    def count(self, name):
        self.counts[name] = self.counts.get(name, 0) + 1
    def note(self, message):
        if message not in self.notes:
            self.notes.append(message)
    def facts(self):
        return {"active": True, "package": _PACKAGE_NAMES["execution"], "store_db": str(self.store_db),
                "admission_gate": self.gate_kind,
                "scope": {"provider": self.scope.provider, "environment": self.scope.environment,
                          "strategy_id": self.scope.strategy_id, "account_ref_source": "synthetic-config-digest"},
                "counts": dict(self.counts), "last_record": dict(self.last_record), "notes": list(self.notes)}


class _DispatchPort:
    """Dispatch port calling the underlying client's own write method."""
    def __init__(self, call):
        self._call, self.raw_reply, self.provider_exc, self.rejection_reason = call, None, None, None
    def submit(self, order_intent):
        from bt_api_execution import ExecutionState, ProviderObservation

        try:
            reply = self._call()
        except Exception as exc:
            if not _is_venue_rejection(exc):
                raise  # transport-level uncertainty: the facade records UNKNOWN
            self.provider_exc = exc
            self.rejection_reason = "venue_rejected"
            return ProviderObservation(order_intent.intent_id, ExecutionState.REJECTED,
                                       reason_code="venue_rejected")
        self.raw_reply = reply if isinstance(reply, Mapping) else {}
        state = _order_state(self.raw_reply)
        fields = {}
        order_id = self.raw_reply.get("orderId")
        if order_id is not None:
            fields["provider_order_id"] = str(order_id)
        executed, average = _decimal(self.raw_reply.get("executedQty")), _decimal(self.raw_reply.get("avgPrice"))
        if executed is not None and executed > 0:
            fields["filled_quantity"] = executed
        if average is not None and average > 0:
            fields["average_price"] = average
        if state == ExecutionState.REJECTED:
            fields["reason_code"] = "venue_rejected"
        return ProviderObservation(order_intent.intent_id, state, **fields)
    def cancel(self, cancel_intent):
        from bt_api_execution import CancelObservation, ExecutionState

        try:
            reply = self._call()
        except Exception as exc:
            if not _is_venue_rejection(exc):
                raise
            self.provider_exc = exc
            self.rejection_reason = "venue_not_cancelled"
            return CancelObservation(cancel_intent.cancel_id, cancel_intent.target_intent_id,
                                     cancel_intent.provider_order_id, ExecutionState.REJECTED,
                                     reason_code="venue_not_cancelled")
        self.raw_reply = reply if isinstance(reply, Mapping) else {}
        status = str(self.raw_reply.get("status") or "").upper()
        if status == "CANCELED":
            state = ExecutionState.CANCELLED
        elif status in ("EXPIRED", "REJECTED"):
            state = ExecutionState.REJECTED
        else:
            state = ExecutionState.ACKED
        return CancelObservation(cancel_intent.cancel_id, cancel_intent.target_intent_id,
                                 cancel_intent.provider_order_id, state,
                                 reason_code="venue_not_cancelled" if state == ExecutionState.REJECTED else None)


def _order_state(reply):
    from bt_api_execution import ExecutionState

    state = {"NEW": ExecutionState.ACKED, "PARTIALLY_FILLED": ExecutionState.PARTIALLY_FILLED,
             "FILLED": ExecutionState.FILLED, "CANCELED": ExecutionState.CANCELLED,
             "EXPIRED": ExecutionState.CANCELLED,
             "REJECTED": ExecutionState.REJECTED}.get(str(reply.get("status") or "").upper())
    if state is not None:
        return state
    return ExecutionState.ACKED if reply.get("orderId") is not None else ExecutionState.REJECTED


# ----------------------------------------------------------------- monitor mount
class _MonitorMount:
    """``DurableOutbox`` append/ack plus one signed read-only page."""
    def __init__(self, run_dir):
        from bt_api_monitor import DurableOutbox

        self.outbox_db = Path(run_dir) / "monitor.sqlite"
        self.outbox = DurableOutbox(self.outbox_db)
        self.counts = {"appended": 0, "acknowledged": 0}
        self.events, self._readback = [], {"attempted": False}
    def record(self, kind, order_ref, status, **extra):
        from bt_api_monitor import OutboxEvent

        try:
            data = {"kind": kind, "status": status}
            if order_ref is not None:
                data["order_ref"] = str(order_ref)[:128]
            data.update({k: str(v)[:128] for k, v in extra.items() if v is not None})
            appended = self.outbox.append(OutboxEvent(event_id=uuid.uuid4().hex, scope=_SCOPE,
                                                      event_type=kind, data=data, occurred_at=time.time()))
            self.counts["appended"] += 1
            for item in self.outbox.read_pending(_CONSUMER, _SCOPE, 64):
                self.outbox.acknowledge(_CONSUMER, _SCOPE, item.sequence)
                self.counts["acknowledged"] += 1
            self.events.append({"sequence": appended.sequence, "kind": kind, "status": status})
        except Exception as exc:  # monitoring must not mask the operation itself
            self.events.append({"kind": kind, "status": "monitor_error", "error": type(exc).__name__})
    def readback_page(self):
        """One fresh signed ``ReadOnlyEventService`` page of the acknowledged events."""
        try:
            import hmac

            from bt_api_monitor import DurableOutbox
            from bt_api_monitor.readonly_events import (ReadOnlyEventService, sign_event_read_request,
                                                        verify_event_read_page)

            key = hmac.new(b"optional16-monitor", b"readback", "sha256").digest()
            service = ReadOnlyEventService(DurableOutbox(self.outbox_db, read_only=True), _SCOPE,
                                           _READBACK_TYPES, generation=1, hmac_key=key)
            request = sign_event_read_request(key=key, service_instance_ref=service.service_instance_ref,
                                              generation=service.generation, scope=_SCOPE, event_types=_READBACK_TYPES,
                                              after_sequence=0, limit=100, request_ref=uuid.uuid4().hex,
                                              nonce=uuid.uuid4().hex, issued_at=time.time())
            page = service.read_page(request)
            verify_event_read_page(request, page, key=key)
            self._readback.update({"ok": True, "events": len(page.events), "cursor": page.cursor,
                                   "has_more": page.has_more})
        except Exception as exc:
            self._readback.update({"ok": False, "error": type(exc).__name__})
        return self._readback
    def facts(self):
        try:
            checkpoint = self.outbox.checkpoint(_CONSUMER, _SCOPE)
        except Exception:
            checkpoint = None
        return {"active": True, "package": _PACKAGE_NAMES["monitor"], "outbox_db": str(self.outbox_db),
                "counts": dict(self.counts), "checkpoint": checkpoint, "events": self.events[-32:],
                "readback": self.readback_page()}


# --------------------------------------------------------------------- wrapper
class ComponentClientWrapper:
    """Duck-typed client wrapper; see the module docstring for the contract."""
    def __init__(self, base, config, topology, env=None):
        self._base = base
        self._config = config if isinstance(config, Mapping) else {}
        self._notes = []
        self._imports_before = _import_snapshot()
        self.transport = _transport(topology) or getattr(base, "transport", "direct")
        self.active = [flag for flag in COMPONENT_FLAGS if _flag(topology, flag)]
        self.run_dir = _run_dir(env)
        self._risk = self._exec = self._monitor = None
        self._order_intents, self._order_cids = {}, {}
        if not self.active:
            self._notes.append("no component flag was set; only the pass-through surface is active")
        for flag, factory in (("risk", self._mount_risk), ("execution", self._mount_execution),
                              ("monitor", self._mount_monitor)):
            if not _flag(topology, flag):
                continue
            try:
                _load_component(flag)  # lazy: a disabled package is never imported
            except Exception as exc:
                raise ComponentError("component_unavailable:" + flag) from exc
            factory()

    def _mount_risk(self):
        self._risk = _RiskMount(self.run_dir, self._config, self._notes)

    def _mount_execution(self):
        self._exec = _ExecutionMount(self.run_dir, self._config, self._risk, self._notes)

    def _mount_monitor(self):
        self._monitor = _MonitorMount(self.run_dir)

    # ----------------------------------------------------------- frozen surface
    def connect(self):
        facts = self._base.connect()
        self._monitor_record("connect", None, "ok", host=_get(facts, "host"))
        return facts
    def account_config(self):
        return self._base.account_config()
    def balances(self):
        return self._base.balances()
    def position_risk(self, symbol=None):
        return self._base.position_risk(symbol)
    def open_orders(self, symbol=None):
        return self._base.open_orders(symbol)
    def query_order(self, symbol, *, order_id=None, client_order_id=None):
        reply = self._base.query_order(symbol, order_id=order_id, client_order_id=client_order_id)
        self._monitor_record("query_order", order_id if order_id is not None else client_order_id,
                             "ok", order_status=_get(reply, "status"))
        return reply
    def filters(self, symbol):
        return self._base.filters(symbol)
    def mark_price(self, symbol):
        return self._base.mark_price(symbol)
    def place_order(self, symbol, side, *args, **kwargs):
        if len(args) > len(_PLACE_POSITIONAL):
            raise TypeError("place_order accepts at most %d positional extras" % len(_PLACE_POSITIONAL))
        merged = dict(zip(_PLACE_POSITIONAL, args))
        merged.update(kwargs)
        reference = merged.get("client_order_id")
        try:
            if self._exec is not None:
                reply = self._place_through_execution(symbol, side, merged)
            elif self._risk is not None:
                reply = self._place_through_risk(symbol, side, merged)
            else:
                reply = self._base.place_order(symbol, side, **merged)
        except Exception as exc:
            self._monitor_record("place_order", reference, "error", error=type(exc).__name__)
            raise
        reference = _get(reply, "_client_order_id") or reference
        self._monitor_record("place_order", reference, "ok", order_id=_get(reply, "orderId"))
        return reply
    def cancel_order(self, symbol, *args, **kwargs):
        if args:
            raise TypeError("cancel_order takes keyword arguments only in the component surface")
        reference = kwargs.get("order_id")
        if reference is None:
            reference = kwargs.get("client_order_id")
        try:
            if self._exec is not None:
                reply = self._cancel_through_execution(symbol, dict(kwargs))
            else:
                reply = self._base.cancel_order(symbol, **kwargs)
        except Exception as exc:
            self._monitor_record("cancel_order", reference, "error", error=type(exc).__name__)
            raise
        self._monitor_record("cancel_order", reference, "ok", cancel_status=_get(reply, "status"))
        return reply
    def describe(self):
        info = {}
        describe = getattr(self._base, "describe", None)
        if callable(describe):
            try:
                info.update(dict(describe() or {}))
            except Exception as exc:
                info["base_describe_error"] = type(exc).__name__
        after = _import_snapshot()
        base_transport = info.get("transport")
        info.update({
            "wrapper": "optional16.components",
            "transport": self.transport,
            "active_components": list(self.active),
            "run_dir": str(self.run_dir),
            "imports_observed": {"before": sorted(self._imports_before), "after": sorted(after),
                                 "delta": sorted(after - self._imports_before)},
            "components": {"risk": self._risk.facts() if self._risk else {"active": False},
                           "execution": self._exec.facts() if self._exec else {"active": False},
                           "monitor": self._monitor.facts() if self._monitor else {"active": False}},
            "adapter_notes": list(self._notes)})
        if base_transport and base_transport != self.transport:
            info["base_transport"] = base_transport
        return info
    def monitor_counts(self):
        if self._monitor is None:
            return {"monitor_active": False}
        facts = self._monitor.facts()
        return {"monitor_active": True, "counts": facts["counts"], "checkpoint": facts["checkpoint"],
                "readback": facts["readback"]}
    def close(self):
        try:
            return self._base.close()
        except Exception as exc:
            self._notes.append("base_close_failed:%s" % type(exc).__name__)
            return None

    # -------------------------------------------------------- delegated state
    @property
    def calls(self):
        return self._base.calls
    @property
    def frozen(self):
        return bool(getattr(self._base, "frozen", False))
    @property
    def frozen_reason(self):
        return getattr(self._base, "frozen_reason", "")
    def __getattr__(self, item):
        base = self.__dict__.get("_base")
        if base is None:
            raise AttributeError(item)
        return getattr(base, item)

    # ------------------------------------------------------------- internals
    def _monitor_record(self, kind, order_ref, status, **extra):
        if self._monitor is not None:
            self._monitor.record(kind, order_ref, status, **extra)
    def _place_through_risk(self, symbol, side, merged):
        self._risk.last_denial = ""
        notional = self._notional(merged)
        cid = merged.get("client_order_id") or _cid()
        merged["client_order_id"] = cid
        if notional is None or notional <= 0:
            self._risk.record_denial("NOTIONAL_UNAVAILABLE")
            raise ComponentError("risk_rejected:NOTIONAL_UNAVAILABLE")
        permit = self._risk.admit_increase(cid, notional)
        try:
            reply = self._base.place_order(symbol, side, **merged)
        except Exception:
            self._risk.count("dispatch_unknown")
            raise
        self._remember_order(cid, reply)
        failure = self._risk.settle(permit)
        if failure:
            self._notes.append(failure)
        return reply
    def _place_through_execution(self, symbol, side, merged):
        from bt_api_execution import (ExecutionState, OrderIntent, OrderType, PositionEffect,
                                      TimeInForce)
        from bt_api_execution import Side as ExecutionSide

        if self._risk is not None:
            self._risk.last_denial = ""
        cid = merged.get("client_order_id") or _cid()
        merged["client_order_id"] = cid
        quantity, price = _decimal(merged.get("quantity")), _decimal(merged.get("price"))
        if quantity is None or quantity <= 0:
            raise ComponentError("execution_rejected:quantity_required")
        order_type = str(merged.get("order_type") or "LIMIT").upper()
        if order_type == "LIMIT" and price is None:
            raise ComponentError("execution_rejected:limit_price_required")
        if self._risk is not None and (price is None or price <= 0):
            self._risk.record_denial("NOTIONAL_UNAVAILABLE")
            raise ComponentError("risk_rejected:NOTIONAL_UNAVAILABLE")
        try:
            type_value = OrderType(order_type)
            reduce_only = bool(merged.get("reduce_only"))
            intent = OrderIntent(
                intent_id=cid, scope=self._exec.scope,
                signal_id="%s-%s" % (self._exec.scope.strategy_id, cid), instrument=str(symbol),
                side=ExecutionSide(str(side).upper()),
                position_effect=PositionEffect.CLOSE if reduce_only else PositionEffect.OPEN,
                order_type=type_value, quantity=quantity,
                price=price if type_value == OrderType.LIMIT else None,
                time_in_force=TimeInForce(str(merged.get("time_in_force") or "GTC").upper()),
                reduce_only=reduce_only, metadata_version="optional16-v1",
                tags={"symbol": str(symbol), "client_order_id": cid})
        except Exception as exc:
            raise ComponentError("execution_rejected:invalid_intent:%s" % type(exc).__name__) from exc
        dispatcher = _DispatchPort(lambda: self._base.place_order(symbol, side, **merged))
        record = self._exec.facade.submit(intent, dispatcher)
        code = record.unknown_reason or dispatcher.rejection_reason or ""
        self._exec.count("submit_" + record.state.value.lower())
        self._exec.last_record = {"intent_id": cid, "state": record.state.value,
                                  "provider_order_id": record.provider_order_id, "reason": code or None,
                                  "review_required": bool(record.review_required)}
        accepted = (ExecutionState.ACKED, ExecutionState.PARTIALLY_FILLED, ExecutionState.FILLED,
                    ExecutionState.CANCELLED)
        if record.state in accepted:
            self._remember_order(cid, dispatcher.raw_reply, record.provider_order_id)
            if record.review_required:
                self._exec.note("execution_review_required:" + (code or "unknown"))
            payload = dict(dispatcher.raw_reply or {})
            order_id = record.provider_order_id
            if order_id is not None:
                payload["orderId"] = int(order_id) if str(order_id).isdigit() else order_id
            elif payload.get("orderId") is None:
                payload["_synthetic_reply"] = True
            payload.setdefault("clientOrderId", cid)
            payload["_client_order_id"] = cid
            return payload
        denial = self._risk.last_denial if self._risk is not None else ""
        if record.state == ExecutionState.REJECTED and dispatcher.provider_exc is not None:
            raise dispatcher.provider_exc
        if record.state in (ExecutionState.REJECTED, ExecutionState.BLOCKED):
            name = record.state.value.lower()
            raise ComponentError(("risk_rejected:" + denial) if denial
                                 else "execution_%s:%s" % (name, code or name))
        raise ComponentError("execution_unknown:" + (code or "dispatch_uncertain"))
    def _cancel_through_execution(self, symbol, merged):
        from bt_api_execution import CancelIntent, ExecutionState

        order_id, client_order_id = merged.get("order_id"), merged.get("client_order_id")
        provider_order_id = (str(order_id) if order_id is not None
                             else self._order_cids.get(str(client_order_id or "")))
        if provider_order_id is None:
            self._exec.note("cancel_passthrough_without_provider_identity")
            return self._base.cancel_order(symbol, **merged)
        target = self._order_intents.get(provider_order_id)
        if target is None and client_order_id is not None and str(client_order_id) in self._order_cids:
            target = str(client_order_id)
        if target is None:
            target = "unmanaged-" + provider_order_id
            self._exec.note("cancel_routed_for_unmanaged_order:" + provider_order_id)
        cancel_id = "o16c" + uuid.uuid4().hex[:20]
        intent = CancelIntent(cancel_id=cancel_id, scope=self._exec.scope, target_intent_id=target,
                              provider_order_id=provider_order_id, metadata_version="optional16-v1",
                              tags={"symbol": str(symbol)})
        dispatcher = _DispatchPort(lambda: self._base.cancel_order(symbol, **merged))
        record = self._exec.cancel_facade.cancel(intent, dispatcher)
        self._exec.count("cancel_" + record.state.value.lower())
        self._exec.last_record = {"cancel_id": cancel_id, "state": record.state.value,
                                  "provider_order_id": provider_order_id,
                                  "reason": record.unknown_reason or None,
                                  "review_required": bool(record.review_required)}
        if record.state in (ExecutionState.CANCELLED, ExecutionState.ACKED):
            if record.review_required:
                self._exec.note("cancel_review_required:" + (record.unknown_reason or "unknown"))
            payload = dict(dispatcher.raw_reply or {})
            payload.setdefault("orderId", int(provider_order_id) if provider_order_id.isdigit()
                               else provider_order_id)
            payload["_record_state"] = record.state.value
            return payload
        if record.state == ExecutionState.REJECTED and dispatcher.provider_exc is not None:
            raise dispatcher.provider_exc
        name = record.state.value.lower()
        prefix = {"rejected": "cancel_rejected", "blocked": "cancel_blocked"}.get(name, "cancel_unknown")
        raise ComponentError(prefix + ":" + (record.unknown_reason or name))
    def _remember_order(self, cid, reply, provider_order_id=None):
        order_id = provider_order_id
        if order_id is None and isinstance(reply, Mapping) and reply.get("orderId") is not None:
            order_id = str(reply["orderId"])
        if order_id is not None:
            self._order_intents[str(order_id)] = cid
            self._order_cids[cid] = str(order_id)
    @staticmethod
    def _notional(merged):
        price, quantity = _decimal(merged.get("price")), _decimal(merged.get("quantity"))
        if price is None or quantity is None or price <= 0 or quantity <= 0:
            return None
        return price * quantity


def wrap_client(client, config, topology, env=None):
    """Mount the enabled optional components on ``client`` (frozen signature).

    ``client`` is the base venue client, ``config`` the parsed case config,
    ``topology`` the effective mapping or ``optional16.spec.TopologySpec``,
    and ``env`` the credential-name mapping (used only for the optional
    ``OPTIONAL16_RUN_DIR`` override; values are never read or recorded).
    """
    try:
        return ComponentClientWrapper(client, config, topology, env)
    except ComponentError:
        raise
    except Exception as exc:
        raise ComponentError("component_init_failed:%s" % type(exc).__name__) from exc

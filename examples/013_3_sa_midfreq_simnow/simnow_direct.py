"""Direct registered-sim execution layer for the 013_3 SimNow live mode.

Scope (iteration 42, R1 decision; see the iteration plan §5.1):

* this module is example-local and opt-in.  It never changes the stock
  ``BtApiStore`` behaviour: when the registered-sim gate is not armed the
  store remains exactly as fail-closed as without this module;
* writes are admitted only through the SDK narrow registered-sim admission
  (``TraderClient.arm_execution_for_registered_sim``), which matches the
  bound TD front against the frozen SimNow/registered-simulation whitelist,
  requires a trading-ready session, and is one-shot per admission;
* every native order insert/cancel call passes the opaque capability
  returned by that admission entry;
* market data, historical/read queries, order/trade event pipelines and the
  ctp.quote.v2 feed stay on the stock wrapper/store code paths;
* when an execution outcome is unknown the gate freezes (no further writes)
  and the run must be reconciled before another admission.

The stock ``BtApiStore`` direct-CTP routes remain disabled; this module does
not reopen them.  It provides the example-owned bridge described in the
iteration 42 plan so a Backtrader strategy can trade a SimNow simulation
account without the (still closed) managed/production execution chain.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import socket
import statistics
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from backtrader.stores import btapistore as _btapistore
from backtrader.stores.btapistore import BtApiStore, BtApiStoreError

__all__ = [
    "RegisteredSimStore",
    "select_front_pair",
    "canonical_sha256",
    "strategy_identity_sha256",
]

# The wrapper class is produced by a reviewed private factory; subclassing the
# factory result keeps this example-local layer tiny while reusing the whole
# stock native session, MD, query and order-event machinery unchanged.
_CTP_WRAPPER_BASE = _btapistore._create_ctp_wrapper_class()

# Beijing has no DST; a fixed UTC+8 offset is exact.
_BEIJING = datetime.timezone(datetime.timedelta(hours=8))
_CZCE_SESSIONS = (("09:00", "10:15"), ("10:30", "11:30"), ("13:30", "15:00"))


def canonical_sha256(value: Any) -> str:
    """Return the SHA-256 of canonical JSON for one JSON-compatible value."""
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def strategy_identity_sha256(strategy_path, config: Mapping[str, Any]) -> str:
    """Bind the exact strategy source bytes and the declared instrument scope."""
    strategy_bytes = Path(strategy_path).read_bytes()
    return canonical_sha256(
        {
            "strategy_source_sha256": hashlib.sha256(strategy_bytes).hexdigest(),
            "strategy_id": str(config.get("strategy_id") or ""),
            "instrument": str(config.get("instrument") or ""),
            "exchange": str(config.get("exchange") or ""),
        }
    )


def _endpoint(front: str) -> Optional[tuple]:
    text = str(front or "").strip()
    if not text:
        return None
    if text.startswith("tcp://"):
        text = text[6:]
    host, _, port = text.rpartition(":")
    if not host or not port:
        return None
    try:
        return host, int(port)
    except ValueError:
        return None


def _probe(address, timeout: float) -> bool:
    try:
        with socket.create_connection(address, timeout=timeout):
            return True
    except OSError:
        return False


def _probe_endpoint(address, timeout: float, samples: int) -> List[Optional[float]]:
    """Return per-sample connect latencies (None = failed)."""
    results: List[Optional[float]] = []
    for _ in range(max(int(samples), 1)):
        started = time.monotonic()
        ok = _probe(address, timeout)
        results.append(round((time.monotonic() - started) * 1000.0, 3) if ok else None)
    return results


def _median_success(samples: Sequence[Optional[float]]) -> Optional[float]:
    good = [value for value in samples if value is not None]
    if not good:
        return None
    return float(statistics.median(good))


_LAST_WHITELIST_ERROR = ""


def _whitelisted_td(td_front: str) -> Optional[bool]:
    """Return whether the TD front matches the SDK frozen simulation whitelist.

    ``None`` means the SDK helper could not be consulted (treated as unknown,
    never as authorized).  The whitelist itself stays owned by the SDK.
    """
    global _LAST_WHITELIST_ERROR
    try:
        from bt_api_ctp.ctp_env_selector import (
            official_simnow_profile_for_td_front,
            registered_broker_sim_profile_for_td_front,
        )
    except Exception as exc:
        _LAST_WHITELIST_ERROR = f"{type(exc).__name__}: {exc}"
        return None
    try:
        if official_simnow_profile_for_td_front(td_front):
            return True
        if registered_broker_sim_profile_for_td_front(td_front):
            return True
        return False
    except Exception as exc:
        _LAST_WHITELIST_ERROR = f"{type(exc).__name__}: {exc}"
        return None


def select_front_pair(
    pairs: Sequence[Mapping[str, Any]],
    env: Mapping[str, str],
    *,
    samples: int = 3,
    connect_timeout: float = 3.0,
) -> Dict[str, Any]:
    """Select one whole MD/TD pair using the iteration-41/42 policy.

    A pair is eligible when both endpoints have at least one successful
    connection among the bounded samples.  Eligible pairs are ranked by
    standard-front preference first, then by the larger of the two
    successful-sample median latencies, with configuration order breaking
    ties.  Stability percentages are diagnostics only.

    Returns a value-free receipt plus an ordered candidate list (raw fronts)
    so the caller can attempt admission across pairs before any write.
    """
    if not pairs:
        raise SimNowDirectError("no_front_pairs_configured")
    candidates: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for index, item in enumerate(pairs):
        td_front = str(env.get(str(item.get("td_env") or ""), "") or "")
        md_front = str(env.get(str(item.get("md_env") or ""), "") or "")
        kind = str(item.get("kind") or "standard").strip().lower()
        entry: Dict[str, Any] = {"index": index, "kind": kind}
        if not td_front or not md_front:
            entry["reason"] = "missing_env"
            rejected.append(entry)
            continue
        td_addr = _endpoint(td_front)
        md_addr = _endpoint(md_front)
        if td_addr is None or md_addr is None:
            entry["reason"] = "invalid_endpoint"
            rejected.append(entry)
            continue
        td_samples = _probe_endpoint(td_addr, connect_timeout, samples)
        md_samples = _probe_endpoint(md_addr, connect_timeout, samples)
        td_median = _median_success(td_samples)
        md_median = _median_success(md_samples)
        entry["td_success"] = sum(1 for value in td_samples if value is not None)
        entry["md_success"] = sum(1 for value in md_samples if value is not None)
        if td_median is None or md_median is None:
            entry["reason"] = "no_whole_pair_connection"
            rejected.append(entry)
            continue
        candidates.append(
            {
                "index": index,
                "kind": kind,
                "td_front": td_front,
                "md_front": md_front,
                "whitelisted": _whitelisted_td(td_front),
                "score_ms": round(max(td_median, md_median), 3),
                "td_median_ms": round(td_median, 3),
                "md_median_ms": round(md_median, 3),
                "td_success": entry["td_success"],
                "md_success": entry["md_success"],
            }
        )
    if not candidates:
        raise SimNowDirectError(
            "no_front_pair_eligible", {"rejected": rejected, "samples": int(samples)}
        )

    def _kind_rank(kind: str) -> int:
        return 0 if kind not in {"7x24", "engineering", "simnow_7x24"} else 1

    def _in_czce_session() -> bool:
        """Whether the current Beijing time is inside a CZCE day session."""
        moment = datetime.datetime.now(datetime.timezone.utc).astimezone(_BEIJING)
        for start_text, end_text in _CZCE_SESSIONS:
            start = moment.replace(
                hour=int(start_text[:2]), minute=int(start_text[3:]), second=0, microsecond=0
            )
            end = moment.replace(
                hour=int(end_text[:2]), minute=int(end_text[3:]), second=0, microsecond=0
            )
            if start <= moment < end:
                return True
        return False

    in_session = _in_czce_session()

    def _session_rank(kind: str) -> int:
        is_7x24 = _kind_rank(kind) == 1
        # Standard fronts carry the real market but only stream during the
        # session; outside it the always-on engineering front is preferred.
        return 0 if (in_session != is_7x24) else 1

    def _whitelist_rank(flag: Optional[bool]) -> int:
        if flag is True:
            return 0
        if flag is None:
            return 1
        return 2

    candidates.sort(
        key=lambda item: (
            _session_rank(item["kind"]),
            _whitelist_rank(item["whitelisted"]),
            item["score_ms"],
            item["index"],
        )
    )
    selected = candidates[0]
    receipt = {
        "selected_index": selected["index"],
        "selected_kind": selected["kind"],
        "selected_whitelisted": selected["whitelisted"],
        "score_ms": selected["score_ms"],
        "td_median_ms": selected["td_median_ms"],
        "md_median_ms": selected["md_median_ms"],
        "td_success": selected["td_success"],
        "md_success": selected["md_success"],
        "samples": int(samples),
        "eligible": [
            {
                "index": item["index"],
                "kind": item["kind"],
                "whitelisted": item["whitelisted"],
                "score_ms": item["score_ms"],
                "td_success": item["td_success"],
                "md_success": item["md_success"],
            }
            for item in candidates
        ],
        "rejected": rejected,
        "whitelist_probe_error": _LAST_WHITELIST_ERROR or None,
        "environment_switched_after_write": False,
    }
    return {
        "td_front": selected["td_front"],
        "md_front": selected["md_front"],
        "receipt": receipt,
        "ordered_pairs": [
            {
                "index": item["index"],
                "kind": item["kind"],
                "td_front": item["td_front"],
                "md_front": item["md_front"],
                "whitelisted": item["whitelisted"],
                "score_ms": item["score_ms"],
            }
            for item in candidates
        ],
    }


class SimNowDirectError(RuntimeError):
    """Bounded example-layer error carrying a value-free reason and details."""

    def __init__(self, reason: str, details: Optional[Mapping[str, Any]] = None):
        super().__init__(reason)
        self.reason = str(reason)
        self.details = dict(details or {})


class RegisteredSimWrapper(_CTP_WRAPPER_BASE):
    """Stock CTP wrapper plus the registered-sim admission implementations.

    Only the three intentionally-disabled entry points are reimplemented; the
    native session, MD, query and order/trade event pipelines below them are
    stock code.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._registered_sim_capability = None
        self._registered_sim_state: Dict[str, Any] = {}
        self._registered_sim_lock = threading.RLock()
        # OrderRef -> "active" | "terminal"; drives the typed execution
        # summary the strategy requires at startup (stock wrapper never
        # prunes its pending map).
        self._order_state: Dict[str, str] = {}

    # ------------------------------------------------------------- admission
    def arm_registered_sim_execution(
        self,
        instrument_id: str,
        exchange_id: str = "",
        md_front: str = "",
        *,
        strategy_identity_sha256: str,
        execution_cycle_id: str,
        preflight_sha256: str,
    ) -> Dict[str, Any]:
        """Arm the SDK narrow SimNow/registered-simulation write admission."""
        with self._registered_sim_lock:
            client = self.trader_client
            if client is None or not getattr(client, "is_ready", False):
                raise BtApiStoreError("CTP trader client is not ready")
            capability, state = client.arm_execution_for_registered_sim(
                instrument_id=instrument_id,
                exchange_id=exchange_id,
                md_front=md_front,
                strategy_identity_sha256=strategy_identity_sha256,
                execution_cycle_id=execution_cycle_id,
                preflight_sha256=preflight_sha256,
            )
            self._registered_sim_capability = capability
            self._registered_sim_state = dict(state) if isinstance(state, Mapping) else {
                "state": str(state)
            }
            instrument = str(instrument_id or "").upper()
            if instrument and exchange_id:
                self._execution_instrument_exchanges[instrument] = str(exchange_id).upper()
            return {
                "armed": True,
                "instrument": instrument_id,
                "exchange_id": str(exchange_id or "").upper(),
                "state": dict(self._registered_sim_state),
            }

    def disarm_registered_sim_execution(self, reason: str = "registered_sim_disarmed") -> Dict[str, Any]:
        with self._registered_sim_lock:
            client = self.trader_client
            capability = self._registered_sim_capability
            self._registered_sim_capability = None
            if client is None or capability is None:
                return {"disarmed": True, "reason": str(reason), "native": False}
            method = getattr(client, "disarm_execution_gate", None)
            result: Any = None
            if callable(method):
                try:
                    result = method(capability, str(reason))
                except Exception as exc:  # bounded, surfaced to the caller
                    raise BtApiStoreError(
                        f"registered-sim disarm failed: {type(exc).__name__}"
                    ) from None
            return {"disarmed": True, "reason": str(reason), "native": True, "state": result}

    # ------------------------------------------------------- native dispatch
    def _registered_sim_capability_required(self):
        capability = self._registered_sim_capability
        if capability is None:
            raise BtApiStoreError("registered-sim execution capability is not armed")
        return capability

    def _send_native_order_insert(self, field, req_id):
        capability = self._registered_sim_capability_required()
        ret = self.trader_client.submit_order_insert(
            field, req_id, execution_capability=capability
        )
        if ret == 0:
            order_ref = str(getattr(field, "OrderRef", "") or "").strip()
            if order_ref:
                self._order_state[order_ref] = "active"
        return ret

    def _send_native_order_action(self, field, req_id):
        capability = self._registered_sim_capability_required()
        return self.trader_client.submit_order_action(
            field, req_id, execution_capability=capability
        )

    _TERMINAL_CTP_STATUS = frozenset({"0", "4", "5", "a"})

    def _handle_order(self, payload):
        """Stock pipeline plus local active/terminal order tracking."""
        try:
            super()._handle_order(payload)
        finally:
            try:
                extract = getattr(_btapistore, "_ctp_extract_fields", None)
                fields = getattr(_btapistore, "_CTP_ORDER_FIELDS", ())
                if callable(extract):
                    details = extract(payload, fields) or {}
                elif isinstance(payload, Mapping):
                    details = dict(payload)
                else:
                    details = {
                        "OrderRef": getattr(payload, "OrderRef", ""),
                        "OrderStatus": getattr(payload, "OrderStatus", ""),
                    }
                order_ref = str(details.get("OrderRef") or "").strip()
                status = str(details.get("OrderStatus") or "").strip()
                if order_ref and status:
                    if status in self._TERMINAL_CTP_STATUS:
                        self._order_state[order_ref] = "terminal"
                    else:
                        self._order_state[order_ref] = "active"
            except Exception:
                # Tracking is evidence-only; the stock pipeline already ran.
                pass


class RegisteredSimStore(BtApiStore):
    """``BtApiStore`` whose direct CTP write gate follows one armed admission.

    The gate starts closed and returns to closed on disarm or freeze, so the
    stock fail-close behaviour is preserved outside the admitted window.
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("api_cls", RegisteredSimWrapper)
        super().__init__(**kwargs)
        self._registered_sim_gate: Dict[str, Any] = {
            "armed": False,
            "frozen": False,
            "reason": "",
            "execution_cycle_id": "",
        }
        self._registered_sim_gate_lock = threading.RLock()

    # Keep the stock no-raw-client exposure for this route even while armed.
    @property
    def sdk_api(self) -> Any:
        return None

    def _is_ctp_write_provider(self) -> bool:
        gate = getattr(self, "_registered_sim_gate", None)
        if gate and gate.get("armed") and not gate.get("frozen"):
            return False
        return super()._is_ctp_write_provider()

    # ------------------------------------------------------------- admission
    def registered_sim_arm(
        self,
        *,
        instrument: str,
        exchange: str,
        md_front: str,
        strategy_identity_sha256: str,
        execution_cycle_id: str,
        preflight_sha256: str,
    ) -> Dict[str, Any]:
        """Open the write gate through the SDK registered-sim admission."""
        with self._registered_sim_gate_lock:
            if self._registered_sim_gate.get("frozen"):
                raise BtApiStoreError("registered-sim gate is frozen; reconcile first")
            api = self._ensure_api_ready()
            arm = getattr(api, "arm_registered_sim_execution", None)
            if not callable(arm):
                raise BtApiStoreError("registered-sim admission capability is unavailable")
            result = arm(
                instrument,
                exchange,
                md_front=md_front,
                strategy_identity_sha256=strategy_identity_sha256,
                execution_cycle_id=execution_cycle_id,
                preflight_sha256=preflight_sha256,
            )
            self._registered_sim_gate.update(
                {
                    "armed": True,
                    "frozen": False,
                    "reason": "",
                    "execution_cycle_id": str(execution_cycle_id),
                }
            )
            return dict(result or {})

    def registered_sim_disarm(self, reason: str = "operator_disarm") -> Dict[str, Any]:
        with self._registered_sim_gate_lock:
            self._registered_sim_gate.update({"armed": False, "reason": str(reason)})
            api = self._api
            native = False
            if api is not None:
                method = getattr(api, "disarm_registered_sim_execution", None)
                if callable(method):
                    method(str(reason))
                    native = True
            return {"disarmed": True, "reason": str(reason), "native": native}

    def registered_sim_freeze(self, reason: str) -> Dict[str, Any]:
        """Freeze writes after an unknown outcome; disarm stays additive."""
        with self._registered_sim_gate_lock:
            self._registered_sim_gate.update(
                {"armed": False, "frozen": True, "reason": str(reason)}
            )
            return {"frozen": True, "reason": str(reason)}

    def registered_sim_status(self) -> Dict[str, Any]:
        with self._registered_sim_gate_lock:
            return dict(self._registered_sim_gate)

    def registered_sim_write_health(self) -> Dict[str, Any]:
        """Gate state plus the local active-order count (value-free)."""
        gate = self.registered_sim_status()
        api = self._api
        active = 0
        state = getattr(api, "_order_state", None) if api is not None else None
        if isinstance(state, dict):
            active = sum(1 for value in state.values() if value != "terminal")
        elif api is not None and isinstance(getattr(api, "_pending_orders", None), dict):
            active = len(api._pending_orders)
        return {
            "armed": bool(gate.get("armed")),
            "frozen": bool(gate.get("frozen")),
            "active_orders": int(active),
        }

    def get_execution_summary(self) -> Dict[str, Any]:
        """Typed durable-execution summary for the registered-sim route.

        Mirrors the schema the strategy startup contract requires: an armed,
        not-frozen gate is the enabled session; the local order pipeline
        supplies the active count; UNKNOWN accounting freezes the gate and
        therefore reports ``trading_blocked`` with a stable unknown id.
        """
        health = self.registered_sim_write_health()
        frozen = bool(health["frozen"])
        armed = bool(health["armed"]) and not frozen
        return {
            "session_enabled": armed,
            "trading_blocked": frozen or not armed,
            "evidence_errors": [],
            "unknown_ids": ["registered_sim_frozen"] if frozen else [],
            "active_orders": int(health["active_orders"]),
            "fee_unresolved_orders": [],
            "evidence_complete": True,
            "source": "registered_sim_execution_summary_v1",
        }

    # ------------------------------------------------------------ read facts
    def registered_sim_wait_ready(self, timeout: float) -> bool:
        """Wait for the native session's read-ready state (login facts bound)."""
        api = self._ensure_api_ready()
        client = getattr(api, "trader_client", None)
        method = getattr(client, "wait_ready", None)
        if not callable(method):
            raise BtApiStoreError("CTP trader wait_ready is unavailable")
        return bool(method(timeout=timeout))

    def registered_sim_login_facts(self) -> Dict[str, Any]:
        api = self._ensure_api_ready()
        client = getattr(api, "trader_client", None)
        if client is None:
            raise BtApiStoreError("CTP trader client is unavailable")
        facts = {
            "front_id": int(getattr(client, "_front_id", 0) or 0),
            "session_id": int(getattr(client, "_session_id", 0) or 0),
            "trading_day": str(getattr(client, "_trading_day", "") or ""),
            "connection_generation": int(getattr(client, "_connection_generation", 0) or 0),
            "read_only_ready": bool(getattr(client, "is_read_only_ready", False)),
            "trading_ready": bool(getattr(client, "is_trading_ready", False)),
        }
        return facts

    def registered_sim_account_fingerprint(self) -> str:
        api = self._ensure_api_ready()
        client = getattr(api, "trader_client", None)
        if client is None:
            raise BtApiStoreError("CTP trader client is unavailable")
        return str(getattr(client, "_account_fingerprint", "") or "")

    def registered_sim_query(
        self, family: str, timeout: float = 8.0, attempts: int = 2, **filters
    ) -> Dict[str, Any]:
        """Run one bounded read query through the stock native wrapper.

        Reads use the proven bounded retry policy (one retry, longer backoff
        on flow control -2).  An incomplete result is never treated as an
        empty set: it fails closed with the completion facts.
        """
        api = self._ensure_api_ready()
        method = getattr(api, f"query_{family}", None)
        if not callable(method):
            raise BtApiStoreError(f"CTP query family unavailable: {family}")
        attempt = 0
        effective_timeout = float(timeout)
        while True:
            attempt += 1
            result = method(timeout=effective_timeout, **filters)
            if isinstance(result, Mapping):
                facts = {
                    "rows": list(result.get("rows") or result.get("records") or []),
                    "complete": bool(result.get("complete", True)),
                    "timed_out": bool(result.get("timed_out", False)),
                    "error_code": result.get("error_code"),
                    "request_id": result.get("request_id"),
                    "connection_generation": result.get("connection_generation"),
                    "attempt": attempt,
                }
            else:
                records = getattr(result, "records", None)
                facts = {
                    "rows": list(records or ()),
                    "complete": bool(getattr(result, "complete", False)),
                    "timed_out": bool(getattr(result, "timed_out", False)),
                    "error_code": getattr(result, "error_code", None),
                    "request_id": getattr(result, "request_id", None),
                    "connection_generation": getattr(result, "connection_generation", None),
                    "attempt": attempt,
                }
            if (
                facts["complete"]
                and not facts["timed_out"]
                and facts["error_code"] in (None, 0)
            ):
                return facts
            if attempt < max(int(attempts), 1):
                backoff = 1.5 + (2.0 if facts["error_code"] == -2 else 0.0)
                time.sleep(backoff)
                effective_timeout = max(effective_timeout * 1.5, effective_timeout + 4.0)
                continue
            raise SimNowDirectError(
                f"query_incomplete:{family}",
                {
                    "complete": facts["complete"],
                    "timed_out": facts["timed_out"],
                    "error_code": facts["error_code"],
                    "attempts": attempt,
                },
            )

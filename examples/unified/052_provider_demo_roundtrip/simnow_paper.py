"""Iteration 52 bounded SimNow registered-sim paper adapter (example-local).

The 052 runner composes one ordinary Backtrader strategy through
``bt_api_runtime.direct_backtrader.DirectBacktraderSession``.  SimNow needs the
reviewed direct registered-sim bridge from the 013_3 example, which is not an
importable package, so this module loads it by path and subclasses its
``RegisteredSimStore`` with the typed readiness/arming surface the session
expects.

Writes remain owned by the SDK registered-sim admission and the bridge's store
gate.  Every missing precondition raises a finite ``SimNowPaperError``; there is
no fallback to ``BtApiStore``, the SDK direct route or a local simulation.
Front addresses and credential values never enter ``repr``, facts or details.
"""

from __future__ import annotations

from paper_common import finite_number, public_login_facts, row_value

import hashlib
import importlib.util
import json
import math
import sys
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SIMNOW_DIRECT_PATH = (
    _REPO_ROOT / "examples" / "unified" / "013_3_sa_midfreq_simnow" / "simnow_direct.py"
)

SIMNOW_CREDENTIAL_NAMES: Tuple[Tuple[str, str], ...] = (
    ("app_id", "CTP_APP_ID"),
    ("auth_code", "CTP_AUTH_CODE"),
    ("broker_id", "CTP_BROKER_ID"),
    ("investor_id", "CTP_USER_ID"),
    ("password", "CTP_PASSWORD"),
)
_PLAN_FIELD_BY_SDK_FIELD = {
    "broker_id": "broker_id",
    "investor_id": "user_id",
    "password": "password",
    "app_id": "app_id",
    "auth_code": "auth_code",
}
_TERMINAL_ORDER_STATUS = frozenset({"0", "4", "5", "a"})
_SIMNOW_DIRECT_CACHE: Dict[Path, Any] = {}
_STORE_CLASS_CACHE: Dict[int, type] = {}


class SimNowPaperError(RuntimeError):
    """Bounded, value-free SimNow paper failure with a stable reason code."""

    def __init__(self, reason: str, details: Optional[Mapping[str, Any]] = None):
        super().__init__(str(reason))
        self.reason = str(reason)
        self.details = dict(details or {})


@dataclass(frozen=True)
class SimNowPaperPlan:
    """One exact binding: front pair, account, contract, strategy identity.

    Secret-bearing fields are excluded from ``repr``; the object grants no
    write authority - the SDK admission still decides that.
    """

    instrument: str
    exchange: str
    md_front: str = field(repr=False)
    td_front: str = field(repr=False)
    broker_id: str = field(repr=False)
    user_id: str = field(repr=False)
    password: str = field(repr=False)
    app_id: str = field(repr=False)
    auth_code: str = field(repr=False)
    strategy_identity_sha256: str
    execution_cycle_id: str
    price_tick: float = 1.0
    volume_multiple: float = 1.0
    quantity_step: float = 1.0
    min_quantity: float = 1.0
    max_quantity: float = 2.0
    quantity_unit: str = "contracts"
    position_mode: str = "dual_side"
    account_currency: str = "CNY"
    allow_zero_login_response: bool = True
    login_timeout: float = 30.0
    query_timeout: float = 8.0
    stop_timeout: float = 12.0
    credential_names: Tuple[Tuple[str, str], ...] = SIMNOW_CREDENTIAL_NAMES

    def __post_init__(self) -> None:
        for name in ("instrument", "exchange", "md_front", "td_front"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise SimNowPaperError("simnow_paper_field_missing", {"field": name})
        for name in ("broker_id", "user_id", "password", "app_id", "auth_code"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise SimNowPaperError("simnow_paper_field_missing", {"field": name})
        if len(str(self.strategy_identity_sha256)) != 64:
            raise SimNowPaperError("simnow_paper_strategy_identity_invalid")
        cycle = str(self.execution_cycle_id)
        if not cycle.strip() or not cycle.isascii():
            raise SimNowPaperError("simnow_paper_execution_cycle_invalid")
        for name in (
            "price_tick",
            "volume_multiple",
            "quantity_step",
            "min_quantity",
            "max_quantity",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SimNowPaperError("simnow_paper_contract_invalid", {"field": name})
            if not math.isfinite(float(value)) or float(value) <= 0:
                raise SimNowPaperError("simnow_paper_contract_invalid", {"field": name})
        if float(self.max_quantity) < float(self.min_quantity):
            raise SimNowPaperError("simnow_paper_quantity_bounds_invalid")
        if self.position_mode not in ("dual_side", "net"):
            raise SimNowPaperError("simnow_paper_position_mode_invalid")
        if not str(self.account_currency).isascii():
            raise SimNowPaperError("simnow_paper_account_currency_invalid")
        if not isinstance(self.credential_names, tuple) or not self.credential_names:
            raise SimNowPaperError("simnow_paper_credential_names_invalid")
        for item in self.credential_names:
            if (
                not isinstance(item, tuple)
                or len(item) != 2
                or not all(isinstance(part, str) and part for part in item)
            ):
                raise SimNowPaperError("simnow_paper_credential_names_invalid")

    def __repr__(self) -> str:
        return (
            "SimNowPaperPlan(instrument={!r}, exchange={!r}, price_tick={!r}, "
            "volume_multiple={!r}, quantity_step={!r}, min_quantity={!r}, "
            "max_quantity={!r}, position_mode={!r}, fronts=<redacted>, "
            "credentials=<redacted>, strategy_identity_sha256={!r}, "
            "execution_cycle_id={!r})"
        ).format(
            self.instrument,
            self.exchange,
            self.price_tick,
            self.volume_multiple,
            self.quantity_step,
            self.min_quantity,
            self.max_quantity,
            self.position_mode,
            self.strategy_identity_sha256,
            self.execution_cycle_id,
        )

    def credential_values(self) -> Dict[str, str]:
        """Return injected credential values keyed by environment name."""
        values: Dict[str, str] = {}
        for sdk_field, env_name in self.credential_names:
            plan_field = _PLAN_FIELD_BY_SDK_FIELD.get(sdk_field)
            if plan_field is None:
                raise SimNowPaperError(
                    "simnow_paper_credential_field_unknown", {"field": sdk_field}
                )
            values[env_name] = str(getattr(self, plan_field))
        return values


def build_simnow_plan(*, instrument: str, exchange: str, md_front: str, td_front: str,
                      broker_id: str, user_id: str, password: str, app_id: str,
                      auth_code: str, strategy_identity_sha256: str,
                      execution_cycle_id: str, **contract: Any) -> SimNowPaperPlan:
    """Validate and bind one exact SimNow paper plan."""
    if not str(td_front or "").strip() or not str(md_front or "").strip():
        raise SimNowPaperError("simnow_front_pair_missing")
    return SimNowPaperPlan(
        instrument=str(instrument).strip().upper(),
        exchange=str(exchange).strip().upper(),
        md_front=str(md_front).strip(),
        td_front=str(td_front).strip(),
        broker_id=str(broker_id),
        user_id=str(user_id),
        password=str(password),
        app_id=str(app_id),
        auth_code=str(auth_code),
        strategy_identity_sha256=str(strategy_identity_sha256),
        execution_cycle_id=str(execution_cycle_id),
        **contract,
    )


def load_simnow_direct(path: Optional[Any] = None) -> Any:
    """Load the reviewed 013_3 ``simnow_direct`` module by exact file path."""
    resolved = (Path(path) if path is not None else DEFAULT_SIMNOW_DIRECT_PATH).expanduser().resolve()
    if resolved in _SIMNOW_DIRECT_CACHE:
        return _SIMNOW_DIRECT_CACHE[resolved]
    if not resolved.is_file():
        raise SimNowPaperError(
            "simnow_direct_missing", {"file": resolved.name, "path": resolved.parent.name}
        )
    name = "iteration52_simnow_direct"
    spec = importlib.util.spec_from_file_location(name, resolved)
    if spec is None or spec.loader is None:
        raise SimNowPaperError("simnow_direct_unloadable", {"file": resolved.name})
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - finite code, no provider detail
        if previous is not None:
            sys.modules[name] = previous
        else:
            sys.modules.pop(name, None)
        raise SimNowPaperError(
            "simnow_direct_import_failed", {"error_type": type(exc).__name__}
        ) from None
    _SIMNOW_DIRECT_CACHE[resolved] = module
    return module


def build_simnow_profile(plan: SimNowPaperPlan, *, provider_ref: str, endpoint_ref: str,
                         account_ref: str, credential_ref: str, scope_ref: str):
    """Build the DirectProviderProfile; ``minutes`` matches the proven 013_3 CTP feed."""
    from bt_api_runtime.direct_backtrader import DirectProviderProfile

    return DirectProviderProfile(
        provider_ref=provider_ref,
        endpoint_ref=endpoint_ref,
        account_ref=account_ref,
        credential_ref=credential_ref,
        scope_ref=scope_ref,
        sdk_route_key="CTP___FUTURES",
        environment="simulation",
        account_currency=plan.account_currency,
        symbols=(plan.instrument,),
        credential_fields=tuple(plan.credential_names),
        position_mode=plan.position_mode,
        require_account_risk=False,
        account_maximum_loss_bps="50",
        account_risk_max_age_seconds="60",
        reconcile_attempts=2,
        reconcile_backoff_seconds=0.5,
        cancel_confirmation_timeout_seconds=5.0,
        supports_write=True,
        data_timeframe="minutes",
        readiness_quantity=float(plan.min_quantity),
    )


def _store_constructor_kwargs(plan: SimNowPaperPlan) -> Dict[str, Any]:
    return {
        "provider": "ctp",
        "backend": "direct",
        "config": {
            "md_front": plan.md_front,
            "td_front": plan.td_front,
            "broker_id": plan.broker_id,
            "investor_id": plan.user_id,
            "password": plan.password,
            "app_id": plan.app_id,
            "auth_code": plan.auth_code,
            "auto_settlement_confirm": False,
            "allow_zero_login_response": bool(plan.allow_zero_login_response),
            "supports_dual_side": plan.position_mode == "dual_side",
        },
    }


def build_store_class(base: type) -> type:
    """Return (and cache) ``SimNowPaperStore`` for one loaded store base."""
    if not isinstance(base, type):
        raise SimNowPaperError("simnow_store_base_unavailable")
    store_class = _STORE_CLASS_CACHE.get(id(base))
    if store_class is None:
        store_class = type("SimNowPaperStore", (SimNowPaperStoreMixin, base),
                           {"__module__": __name__})
        _STORE_CLASS_CACHE[id(base)] = store_class
    return store_class


def make_store_factory(plan: SimNowPaperPlan, *, simnow_module: Any = None):
    """Return the session store factory; the session config is never retained."""
    module = simnow_module if simnow_module is not None else load_simnow_direct()
    base = getattr(module, "RegisteredSimStore", None)
    if not isinstance(base, type):
        raise SimNowPaperError("simnow_store_base_unavailable")
    store_class = build_store_class(base)

    def factory(*, config: Any = None, profile: Any = None) -> Any:
        del config, profile  # may carry another route's credentials
        return store_class(plan=plan, simnow_module=module, **_store_constructor_kwargs(plan))

    return factory


def make_broker_factory(plan: SimNowPaperPlan):
    """Return a broker factory pinning the SimNow paper exposure contract."""

    def factory(*, store: Any, profile: Any, **kwargs: Any) -> Any:
        from backtrader.brokers.btapibroker import BtApiBroker

        kwargs.update(
            position_mode=plan.position_mode,
            max_order_size=max(int(plan.max_quantity), 1),
            cash_check_enabled=True,
            sdk_preflight=False,
            flatten_on_stop=False,
            shutdown_timeout=float(plan.stop_timeout),
            require_complete_ctp_evidence=True,
        )
        return BtApiBroker(store=store, provider="ctp", **kwargs)

    return factory


def adapt_roundtrip_strategy(strategy_cls: type) -> type:
    """Bind the shared strategy to CTP's GFD-only order contract.

    The strategy hard-codes an IOC closing limit; CTP first-version orders
    accept GFD only.  The adapter rewrites only an explicit non-GFD value on
    ``buy``/``sell`` so a partial fill can still be flattened.  The original
    strategy source is not modified.
    """
    if not isinstance(strategy_cls, type):
        raise SimNowPaperError("simnow_strategy_invalid")

    def _force_gfd(self, kwargs: Dict[str, Any]) -> None:
        requested = kwargs.get("time_in_force")
        if requested is not None and str(requested).strip().upper() not in {
            "GFD", "GOOD_FOR_DAY"
        }:
            kwargs["time_in_force"] = "GFD"

    class SimNowPaperRoundTripStrategy(strategy_cls):
        def buy(self, *args: Any, **kwargs: Any) -> Any:
            _force_gfd(self, kwargs)
            return super().buy(*args, **kwargs)

        def sell(self, *args: Any, **kwargs: Any) -> Any:
            _force_gfd(self, kwargs)
            return super().sell(*args, **kwargs)

    return SimNowPaperRoundTripStrategy


def _position_is_open(row: Any) -> bool:
    for name in ("Position", "position", "YdPosition", "TodayPosition"):
        try:
            value = row_value(row, name)
            if value is not None and float(value) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _order_is_active(row: Any) -> bool:
    status = str(row_value(row, "OrderStatus", "order_status", default="") or "")
    if status in _TERMINAL_ORDER_STATUS:
        return False
    remaining = row_value(row, "VolumeTotal", "volume_total")
    traded = row_value(row, "VolumeTraded", "volume_traded", default=0)
    try:
        if remaining is not None and float(remaining) - float(traded or 0) <= 0:
            return False
    except (TypeError, ValueError):
        pass
    return bool(status)


class SimNowPaperStoreMixin:
    """Typed paper surface over the 013_3 ``RegisteredSimStore`` bridge."""

    def __init__(self, *, plan: SimNowPaperPlan, simnow_module: Any = None,
                 **kwargs: Any) -> None:
        if not isinstance(plan, SimNowPaperPlan):
            raise SimNowPaperError("simnow_paper_plan_invalid")
        self._simnow_plan = plan
        self._simnow_module = simnow_module
        self._simnow_lock = threading.RLock()
        self._simnow_prepared = False
        self._simnow_stopped = False
        self._simnow_arm_count = 0
        self._simnow_arm_facts: Dict[str, Any] = {}
        self._simnow_login: Dict[str, Any] = {}
        self._simnow_metadata: Dict[str, Any] = {}
        self._simnow_rows: Dict[str, List[Any]] = {
            "account": [], "positions": [], "orders": [], "instruments": []
        }
        self._simnow_stop_facts: Dict[str, Any] = {"action": "not_stopped", "reason": ""}
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return (
            "SimNowPaperStore(instrument={!r}, exchange={!r}, fronts=<redacted>, "
            "credentials=<redacted>, prepared={!r}, armed={!r})"
        ).format(self._simnow_plan.instrument, self._simnow_plan.exchange,
                 self._simnow_prepared, self._simnow_arm_count == 1)

    def start(self, data: Any = None, broker: Any = None) -> Any:
        if self._simnow_prepared:
            # Feed.start() calls Store.start(data=feed) after the session
            # preflight already performed the one-shot admission.
            return super().start(data=data, broker=broker)
        try:
            result = super().start(data=data, broker=broker)
            self._simnow_prepare()
        except SimNowPaperError:
            self._simnow_abort_start("simnow_paper_start_failed")
            raise
        except Exception as exc:  # noqa: BLE001 - finite code only
            self._simnow_abort_start("simnow_paper_start_failed")
            raise SimNowPaperError(
                "simnow_paper_start_failed", {"error_type": type(exc).__name__}
            ) from None
        self._simnow_prepared = True
        return result

    def _simnow_prepare(self) -> None:
        plan = self._simnow_plan
        ready = bool(self.registered_sim_wait_ready(timeout=float(plan.login_timeout)))
        login = self.registered_sim_login_facts() or {}
        self._simnow_login = public_login_facts(login)
        if not ready or not (
            login.get("read_only_ready") is True or login.get("trading_ready") is True
        ):
            raise SimNowPaperError(
                "simnow_paper_login_not_ready",
                {
                    "wait_ready": ready,
                    "read_only_ready": bool(login.get("read_only_ready")),
                    "trading_ready": bool(login.get("trading_ready")),
                },
            )
        if len(str(login.get("trading_day") or "")) != 8 or int(
            login.get("connection_generation") or 0
        ) <= 0:
            raise SimNowPaperError("simnow_paper_login_facts_invalid")
        self._refresh_readiness()
        self._simnow_arm_once()
        # The registered-sim arm can publish trading readiness after login.
        self._simnow_login = public_login_facts(
            self.registered_sim_login_facts() or login
        )

    def _refresh_readiness(self) -> None:
        plan = self._simnow_plan
        account = self._query_rows("account_result")
        positions = self._query_rows("positions_result")
        orders = self._query_rows("orders_result")
        instruments = self._query_rows(
            "instruments_result", instrument_id=plan.instrument, exchange_id=plan.exchange
        )
        if not account:
            raise SimNowPaperError("simnow_paper_account_query_empty")
        row = self._exact_instrument_row(instruments)
        if row is None:
            raise SimNowPaperError(
                "simnow_paper_instrument_missing",
                {"instrument": plan.instrument, "exchange": plan.exchange},
            )
        price_tick = finite_number(row_value(row, "PriceTick", "price_tick"))
        volume_multiple = finite_number(row_value(row, "VolumeMultiple", "volume_multiple"))
        if price_tick is None or volume_multiple is None:
            raise SimNowPaperError("simnow_paper_instrument_metadata_missing")
        if abs(price_tick - float(plan.price_tick)) > 1e-9 or abs(
            volume_multiple - float(plan.volume_multiple)
        ) > 1e-9:
            raise SimNowPaperError(
                "simnow_paper_instrument_metadata_mismatch",
                {"price_tick": price_tick, "volume_multiple": volume_multiple,
                 "expected_price_tick": float(plan.price_tick),
                 "expected_volume_multiple": float(plan.volume_multiple)},
            )
        open_positions = [item for item in positions if _position_is_open(item)]
        active_orders = [item for item in orders if _order_is_active(item)]
        self._simnow_rows = {
            "account": account, "positions": positions,
            "orders": orders, "instruments": instruments,
        }
        self._simnow_metadata = self._instrument_metadata(row, price_tick, volume_multiple)
        self.contract_metadata[str(plan.instrument)] = dict(self._simnow_metadata)
        if open_positions:
            raise SimNowPaperError(
                "simnow_paper_account_not_flat", {"open_position_rows": len(open_positions)}
            )
        if active_orders:
            raise SimNowPaperError(
                "simnow_paper_open_orders_present", {"active_order_rows": len(active_orders)}
            )

    def _exact_instrument_row(self, rows: Sequence[Any]) -> Optional[Any]:
        plan = self._simnow_plan
        for row in rows:
            code = str(row_value(row, "InstrumentID", "instrument_id", default="") or "")
            if code.strip().upper() != plan.instrument:
                continue
            exchange_id = str(
                row_value(row, "ExchangeID", "exchange_id", default="") or ""
            ).strip().upper()
            if exchange_id and exchange_id != plan.exchange:
                continue
            return row
        return None

    def _instrument_metadata(self, row: Any, price_tick: float,
                             volume_multiple: float) -> Dict[str, Any]:
        plan = self._simnow_plan
        step, minimum = float(plan.quantity_step), float(plan.min_quantity)
        return {
            "instrument_id": plan.instrument,
            "exchange_id": str(
                row_value(row, "ExchangeID", "exchange_id", default=plan.exchange)
                or plan.exchange
            ).upper(),
            "multiplier": float(volume_multiple),
            "contract_value": float(volume_multiple),
            "contract_multiplier": 1.0,
            "tick_size": float(price_tick),
            "price_tick": float(price_tick),
            "min_price_tick": float(price_tick),
            "lot_size": step,
            "quantity_step": step,
            "min_size": minimum,
            "min_quantity": minimum,
            "min_order_size": minimum,
            "min_volume": minimum,
            "quantity_unit": plan.quantity_unit,
        }

    def _query_rows(self, family: str, *, attempts: int = 2, **filters: Any) -> List[Any]:
        try:
            facts = self.registered_sim_query(
                family, timeout=float(self._simnow_plan.query_timeout),
                attempts=int(attempts), **filters,
            )
        except Exception as exc:  # noqa: BLE001 - finite code only
            reason = getattr(exc, "reason", None)
            details: Dict[str, Any] = {"family": family}
            if isinstance(reason, str) and reason:
                details["query_reason"] = reason[:80]
            else:
                details["error_type"] = type(exc).__name__
            raise SimNowPaperError("simnow_paper_query_failed", details) from None
        if not isinstance(facts, Mapping):
            raise SimNowPaperError("simnow_paper_query_invalid", {"family": family})
        if facts.get("complete") is not True:
            raise SimNowPaperError("simnow_paper_query_incomplete", {"family": family})
        rows = facts.get("rows")
        if rows is None:
            rows = facts.get("records")
        return [dict(item) if isinstance(item, Mapping) else item for item in (rows or ())]

    def _simnow_arm_once(self) -> None:
        plan = self._simnow_plan
        if self._simnow_arm_count:
            raise SimNowPaperError("simnow_paper_arm_twice")
        preflight_sha = self._preflight_sha256()
        try:
            result = self.registered_sim_arm(
                instrument=plan.instrument,
                exchange=plan.exchange,
                md_front=plan.md_front,
                strategy_identity_sha256=plan.strategy_identity_sha256,
                execution_cycle_id=plan.execution_cycle_id,
                preflight_sha256=preflight_sha,
            )
        except SimNowPaperError:
            raise
        except Exception as exc:  # noqa: BLE001 - finite code only
            reason = getattr(exc, "reason", None)
            details = (
                {"admission_reason": str(reason)[:80]}
                if isinstance(reason, str) and reason
                else {"error_type": type(exc).__name__}
            )
            raise SimNowPaperError("simnow_paper_arm_failed", details) from None
        if not isinstance(result, Mapping) or result.get("armed") is not True:
            raise SimNowPaperError("simnow_paper_arm_rejected")
        self._simnow_arm_count = 1
        state = result.get("state")
        self._simnow_arm_facts = {
            "armed": True,
            "preflight_sha256": preflight_sha,
            "state_keys": sorted(str(key)[:40] for key in state) if isinstance(state, Mapping) else [],
        }

    def _preflight_sha256(self) -> str:
        plan = self._simnow_plan
        payload = {
            "schema": "iteration52.simnow-paper.preflight.v1",
            "instrument": plan.instrument,
            "exchange": plan.exchange,
            "md_front_sha256": hashlib.sha256(plan.md_front.encode("utf-8")).hexdigest(),
            "td_front_sha256": hashlib.sha256(plan.td_front.encode("utf-8")).hexdigest(),
            "login": dict(self._simnow_login),
            "account_rows": len(self._simnow_rows["account"]),
            "instrument_rows": len(self._simnow_rows["instruments"]),
            "metadata": {"price_tick": self._simnow_metadata.get("price_tick"),
                         "volume_multiple": self._simnow_metadata.get("multiplier")},
            "quantity": [plan.min_quantity, plan.max_quantity, plan.quantity_step],
            "execution_cycle_id": plan.execution_cycle_id,
            "strategy_identity_sha256": plan.strategy_identity_sha256,
        }
        canonical = getattr(self._simnow_module, "canonical_sha256", None)
        if callable(canonical):
            return str(canonical(payload))
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _simnow_abort_start(self, reason: str) -> None:
        try:
            self.registered_sim_freeze(reason)
        except Exception:  # noqa: BLE001 - shutdown continues
            pass
        try:
            super().stop(timeout=float(self._simnow_plan.stop_timeout))
        except Exception:  # noqa: BLE001 - shutdown continues
            pass
        self._simnow_stop_facts = {"action": "freeze", "reason": reason}

    def stop(self, timeout: Optional[float] = None) -> Any:
        already_stopped, self._simnow_stopped = self._simnow_stopped, True
        effective = float(self._simnow_plan.stop_timeout) if timeout is None else timeout
        if already_stopped:
            return super().stop(timeout=effective)
        action, facts = self._simnow_stop_decision()
        if action == "freeze":
            try:
                self.registered_sim_freeze(str(facts.get("reason") or "simnow_paper_frozen"))
            except Exception as exc:  # noqa: BLE001 - keep the finite action
                facts["freeze_error"] = type(exc).__name__
        elif action == "disarm":
            try:
                self.registered_sim_disarm("simnow_paper_clean_stop")
            except Exception as exc:  # noqa: BLE001 - fall back to a freeze
                facts["disarm_error"] = type(exc).__name__
                try:
                    self.registered_sim_freeze("simnow_paper_disarm_failed")
                except Exception:  # noqa: BLE001
                    pass
                facts["action"], facts["reason"] = "freeze", "simnow_paper_disarm_failed"
        self._simnow_stop_facts = facts
        return super().stop(timeout=effective)

    def _simnow_stop_decision(self) -> Tuple[str, Dict[str, Any]]:
        if not self._simnow_prepared:
            return "disarm", {"action": "disarm", "reason": "simnow_paper_never_started"}
        try:
            status = self.registered_sim_status() or {}
        except Exception:  # noqa: BLE001 - unreadable state is unresolved
            return "freeze", {"action": "freeze", "reason": "simnow_paper_stop_unresolved"}
        if not isinstance(status, Mapping):
            status = {}
        if status.get("frozen") is True:
            return "already_frozen", {
                "action": "frozen",
                "reason": str(status.get("reason") or "simnow_paper_already_frozen"),
            }
        try:
            positions = self._query_rows("positions_result", attempts=1)
            orders = self._query_rows("orders_result", attempts=1)
            summary = self.get_execution_summary()
        except Exception as exc:  # noqa: BLE001 - unresolved is a freeze
            return "freeze", {"action": "freeze",
                              "reason": "simnow_paper_stop_unresolved",
                              "error_type": type(exc).__name__}
        if not isinstance(summary, Mapping):
            summary = {}
        unknown_ids = summary.get("unknown_ids")
        unknown = list(unknown_ids) if isinstance(unknown_ids, (list, tuple, set)) else []
        open_positions = [item for item in positions if _position_is_open(item)]
        active_orders = [item for item in orders if _order_is_active(item)]
        facts = {
            "action": "disarm",
            "reason": "simnow_paper_clean_stop",
            "final_position_rows": len(open_positions),
            "final_order_rows": len(active_orders),
            "unknown_ids": len(unknown),
        }
        if open_positions or active_orders or unknown:
            facts["action"], facts["reason"] = "freeze", "simnow_paper_residual_exposure"
        return str(facts["action"]), facts

    def _require_symbol(self, dataname: Any) -> None:
        if str(dataname or "").strip().upper() != self._simnow_plan.instrument:
            raise SimNowPaperError(
                "simnow_paper_symbol_scope_mismatch",
                {"instrument": self._simnow_plan.instrument},
            )

    def _position_mode(self) -> str:
        directions = {
            str(row_value(row, "PosiDirection", "posi_direction", default="") or "")
            .strip().upper()
            for row in self._simnow_rows["positions"]
        }
        directions.discard("")
        if directions & {"2", "3"}:
            return "dual_side"
        if directions == {"1"}:
            return "net"
        return self._simnow_plan.position_mode

    def _gate_state(self) -> Dict[str, Any]:
        try:
            status = self.registered_sim_status() or {}
        except Exception:  # noqa: BLE001 - an unreadable gate is not armed
            return {"armed": False, "frozen": True, "reason": "gate_unreadable"}
        return dict(status) if isinstance(status, Mapping) else {}

    def _readiness_reasons(self) -> List[str]:
        plan = self._simnow_plan
        reasons: List[str] = []
        if not self._simnow_prepared:
            reasons.append("simnow_paper_not_started")
        if not (
            self._simnow_login.get("read_only_ready") is True
            or self._simnow_login.get("trading_ready") is True
        ):
            reasons.append("simnow_paper_login_not_ready")
        if not self._simnow_rows["account"]:
            reasons.append("simnow_paper_account_query_empty")
        if any(_position_is_open(row) for row in self._simnow_rows["positions"]):
            reasons.append("simnow_paper_account_not_flat")
        if any(_order_is_active(row) for row in self._simnow_rows["orders"]):
            reasons.append("simnow_paper_open_orders_present")
        if self._gate_state().get("frozen") is True:
            reasons.append("simnow_paper_gate_frozen")
        if self._simnow_arm_count != 1 or not self._simnow_arm_facts.get("armed"):
            reasons.append("simnow_paper_arm_not_confirmed")
        if not self._simnow_metadata:
            reasons.append("simnow_paper_instrument_not_ready")
        if plan.position_mode not in ("dual_side", "net"):
            reasons.append("simnow_paper_position_mode_invalid")
        return reasons

    def get_environment_info(self, dataname: str) -> Dict[str, Any]:
        """Return the registered-sim environment proof for this route."""
        self._require_symbol(dataname)
        return {
            "environment": "simulation",
            "venue": "SIMNOW",
            "instrument": self._simnow_plan.instrument,
            "exchange": self._simnow_plan.exchange,
            "source": "simnow_paper_registered_sim_v1",
        }

    def get_account_config(self, dataname: str) -> Dict[str, Any]:
        """Derive trading permission from the verified CTP login/query facts."""
        self._require_symbol(dataname)
        reasons = self._readiness_reasons()
        return {
            "can_trade": not reasons,
            "position_mode": self._position_mode(),
            "trading_ready": self._simnow_login.get("trading_ready") is True,
            "read_only_ready": self._simnow_login.get("read_only_ready") is True,
            "account_rows": len(self._simnow_rows["account"]),
            "reasons": reasons,
            "source": "simnow_paper_ctp_readiness_v1",
        }

    def get_order_readiness(self, dataname: str, quantity_native: Any, *,
                            margin_mode: str = "cross",
                            position_mode: Optional[str] = None) -> Dict[str, Any]:
        """Ready only for a flat, exposure-free, armed paper account."""
        self._require_symbol(dataname)
        plan = self._simnow_plan
        reasons = self._readiness_reasons()
        try:
            quantity = float(quantity_native)
        except (TypeError, ValueError):
            quantity = None
        if quantity is None or not math.isfinite(quantity) or quantity <= 0:
            reasons.append("simnow_paper_quantity_invalid")
        elif not (float(plan.min_quantity) <= quantity <= float(plan.max_quantity)):
            reasons.append("simnow_paper_quantity_out_of_bounds")
        observed_mode = self._position_mode()
        if position_mode is not None and str(position_mode) != observed_mode:
            reasons.append("simnow_paper_position_mode_mismatch")
        return {
            "ready": not reasons,
            "reasons": reasons,
            "margin_mode": margin_mode,
            "position_mode": observed_mode,
            "quantity_unit": plan.quantity_unit,
            "source": "simnow_paper_order_readiness_v1",
        }

    def get_instrument_spec(self, dataname: str) -> Dict[str, Any]:
        """Return the verified CTP contract rules for the bound instrument."""
        self._require_symbol(dataname)
        if not self._simnow_metadata:
            raise SimNowPaperError("simnow_paper_instrument_not_ready")
        self.contract_metadata[str(dataname)] = dict(self._simnow_metadata)
        return dict(self._simnow_metadata)

    def get_reconcile_snapshot(self) -> Dict[str, Any]:
        """Return the typed startup snapshot consumed by the session preflight."""
        if not self._simnow_prepared:
            raise SimNowPaperError("simnow_paper_not_started")
        positions = self._simnow_rows["positions"]
        orders = self._simnow_rows["orders"]
        open_positions = [dict(row) for row in positions if _position_is_open(row)]
        active_orders = [dict(row) for row in orders if _order_is_active(row)]
        try:
            summary = self.get_execution_summary()
        except Exception:  # noqa: BLE001 - counts stay explicit when unreadable
            summary = {}
        if not isinstance(summary, Mapping):
            summary = {}
        unknown_ids = summary.get("unknown_ids")
        unknown = list(unknown_ids) if isinstance(unknown_ids, (list, tuple, set)) else []
        active_count = summary.get("active_orders")
        if isinstance(active_count, bool) or not isinstance(active_count, int):
            active_count = len(active_orders)
        return {
            "schema_version": "iteration52.simnow-paper.reconcile.v1",
            "positions": open_positions,
            "open_orders": active_orders,
            "execution_summary": {
                "unknown_ids": unknown,
                "active_orders": int(active_count),
                "session_enabled": bool(summary.get("session_enabled")),
                "trading_blocked": bool(summary.get("trading_blocked", True)),
            },
            "trading_day": self._simnow_login.get("trading_day"),
            "connection_generation": self._simnow_login.get("connection_generation"),
            "source": "simnow_paper_startup_snapshot_v1",
        }

    def simnow_paper_facts(self) -> Dict[str, Any]:
        """Return value-free query/status facts for evidence."""
        return {
            "schema_version": 1,
            "venue": "SIMNOW",
            "environment": "simulation",
            "instrument": self._simnow_plan.instrument,
            "exchange": self._simnow_plan.exchange,
            "position_mode": self._position_mode(),
            "credential_env_names": [name for _, name in self._simnow_plan.credential_names],
            "prepared": bool(self._simnow_prepared),
            "login": dict(self._simnow_login),
            "account_rows": len(self._simnow_rows["account"]),
            "position_rows": len(self._simnow_rows["positions"]),
            "order_rows": len(self._simnow_rows["orders"]),
            "instrument_rows": len(self._simnow_rows["instruments"]),
            "arm": {
                "count": int(self._simnow_arm_count),
                "armed": bool(self._simnow_arm_facts.get("armed")),
                "preflight_sha256": self._simnow_arm_facts.get("preflight_sha256"),
            },
            "stop": dict(self._simnow_stop_facts),
        }

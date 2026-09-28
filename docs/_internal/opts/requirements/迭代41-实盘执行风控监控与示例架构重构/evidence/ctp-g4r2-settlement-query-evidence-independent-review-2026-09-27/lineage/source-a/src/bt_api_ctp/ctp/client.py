"""
高层封装 / High-level CTP Client Wrappers

提供简洁的 API，减少样板代码。3 行即可收行情或完成交易登录。

用法 / Usage:

    # 行情客户端
    from bt_api_py.ctp.client import MdClient

    def on_tick(data):
        print(data.InstrumentID, data.LastPrice)

    client = MdClient("tcp://182.254.243.31:30011", "9999", "user", "pass")
    client.on_tick = on_tick
    client.subscribe(["IF2603", "IC2603"])
    client.start()  # 阻塞

    # 交易客户端
    from bt_api_py.ctp.client import TraderClient

    client = TraderClient("tcp://182.254.243.31:30001", "9999", "user", "pass",
                          app_id="simnow_client_test", auth_code="0000000000000000")
    client.start()
    client.wait_ready(timeout=15)
    print(client.query_account())
"""

from __future__ import annotations

import hashlib
import importlib.machinery
import json
import logging
import math
import os
import queue
import re
import sys
import tempfile
import threading
import time
import uuid
import weakref
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import urlsplit

from bt_api_ctp.instrument import normalize_ctp_instrument
from bt_api_ctp.order_action import CtpOrderActionEvidence
from bt_api_ctp.query import (
    QueryResult,
    _attach_query_source,
    _new_query_session_scope,
    _new_query_source,
    _query_records_digest,
    _QuerySessionScope,
)

from . import _ctp_base
from ._ctp_base import (
    CtpNativeAbiError,
)
from ._ctp_base import (
    get_ctp_native_diagnostics as _get_vendored_ctp_native_diagnostics,
)
from ._ctp_base import (
    is_ctp_native_loaded as _is_vendored_ctp_native_loaded,
)
from .callback_events import CtpTraderCallbackSourceEvent, snapshot_exact_fields
from .callback_ingress import SKIP_ORIGINAL_CALLBACK as _CALLBACK_INGRESS_SKIP_ORIGINAL
from .ctp_md_api import CThostFtdcMdApi, CThostFtdcMdSpi
from .ctp_structs_common import (
    CThostFtdcReqAuthenticateField,
    CThostFtdcReqUserLoginField,
    CThostFtdcSettlementInfoConfirmField,
)
from .ctp_structs_query import (
    CThostFtdcQryDepthMarketDataField,
    CThostFtdcQryInstrumentCommissionRateField,
    CThostFtdcQryInstrumentField,
    CThostFtdcQryInstrumentMarginRateField,
    CThostFtdcQryInvestorPositionField,
    CThostFtdcQryOptionInstrCommRateField,
    CThostFtdcQryOptionInstrTradeCostField,
    CThostFtdcQryOrderField,
    CThostFtdcQrySettlementInfoConfirmField,
    CThostFtdcQryTradeField,
    CThostFtdcQryTradingAccountField,
)
from .ctp_trader_api import CThostFtdcTraderApi, CThostFtdcTraderSpi

_logger = logging.getLogger(__name__)

_TRADER_ORDER_CALLBACK_FIELDS = (
    "BrokerID",
    "InvestorID",
    "UserID",
    "InstrumentID",
    "ExchangeID",
    "OrderRef",
    "OrderSysID",
    "FrontID",
    "SessionID",
    "RequestID",
    "SequenceNo",
    "NotifySequence",
    "OrderStatus",
    "OrderSubmitStatus",
    "TradingDay",
)
_TRADER_ORDER_ACTION_CALLBACK_FIELDS = (
    "BrokerID",
    "InvestorID",
    "UserID",
    "InstrumentID",
    "ExchangeID",
    "OrderRef",
    "OrderSysID",
    "FrontID",
    "SessionID",
    "OrderActionRef",
    "RequestID",
    "ActionFlag",
    "ActionLocalID",
    "OrderActionStatus",
    "StatusMsg",
    "ActionDate",
    "ActionTime",
    "SessionReqSeq",
    "InvestUnitID",
)
_TRADER_CALLBACK_RSP_INFO_FIELDS = ("ErrorID", "ErrorMsg")

CTP_REQUEST_COUNT_KEYS = (
    "authenticate",
    "login",
    "settlement_confirm",
    "order_insert",
    "order_action",
    "query_account",
    "query_positions",
    "query_orders",
    "query_trades",
    "query_instruments",
    "query_margin_rate",
    "query_commission_rate",
    "query_depth_market_data",
    "query_option_trade_cost",
    "query_option_commission_rate",
    "query_settlement_confirmation",
)

_QUERY_FILTER_UNSET = object()
_TRADER_LOGIN_IDENTITY_SEAL = object()


# The CTP vendor API owns a native callback thread after ``Init()``.  On the
# macOS framework, calling ``Release()`` while a separate Python thread is
# blocked in ``Join()`` is unsafe.  A live native API still owns only a raw
# pointer to its SWIG director, however, so dropping ``_spi`` first turns the
# next callback into a use-after-free crash.  Keep a detached session alive
# after unregistering its callback from the native API.  The Join observer
# releases it once the vendor reports that its native thread has stopped.
#
# This registry is deliberately module-scoped rather than stored on a client:
# callers commonly discard a stopped feed/client before interpreter shutdown,
# while the vendor Join thread can still be alive.  There is no documented
# asynchronous CTP shutdown primitive that can safely replace this deferred
# lifetime on the audited macOS framework.  Entries must nevertheless be
# removed once Join returns so reconnects cannot retain completed sessions.
_RETIRED_CTP_NATIVE_SESSIONS_LOCK = threading.Lock()
_RETIRED_CTP_NATIVE_SESSIONS: list[tuple[Any, Any, threading.Thread | None]] = []
_RELEASING_CTP_NATIVE_SESSION_API_IDS: set[int] = set()
# IDs remain claimed while the API is alive so a repeated observer request can
# never issue Join twice. A successful Release removes the claim.
_CLAIMED_CTP_NATIVE_JOIN_API_IDS: set[int] = set()
_RETURNED_CTP_NATIVE_JOIN_API_IDS: set[int] = set()
# A failed native Release has an unknown partial outcome. Keep the session
# retained and permanently fence further Release calls for that API: a second
# attempt could double-free resources that the first call already freed.
_POISONED_CTP_NATIVE_SESSION_API_IDS: set[int] = set()
_RELEASED_CTP_NATIVE_SESSION_APIS: weakref.WeakSet[Any] = weakref.WeakSet()
_RELEASED_CTP_NATIVE_SESSION_API_IDS: set[int] = set()
_MAX_NATIVE_JOIN_WAIT_SECONDS = 60.0
_MAX_CTP_STOP_WAIT_SECONDS = 30.0
_NO_EXPECTED_NATIVE_API = object()
_CTP_NATIVE_LIFECYCLE_STATES: dict[int, _CtpNativeLifecycleState] = {}


@dataclass(frozen=True)
class CtpNativeJoinObservation:
    """Typed observation of the vendor ``Join`` call only.

    ``returned`` means Join returned its interface-thread exit code. It does
    not by itself certify that ``Release`` succeeded or that the process has
    no remaining native threads.
    """

    state: Literal["not_started", "pending", "returned", "failed"]
    return_code: int | None = None
    error_type: str | None = None


@dataclass(frozen=True)
class CtpNativeJoinWaitResult:
    """Result of one bounded wait for a native ``Join`` call to finish."""

    join_call_finished: bool
    observation: CtpNativeJoinObservation


@dataclass(frozen=True)
class CtpNativeStopReceipt:
    """Bounded observation of one exact native API stop attempt."""

    connection_generation: int
    join_required: bool
    join_completed: bool
    native_released: bool
    thread_alive: bool | None
    timed_out: bool
    lifecycle: CtpNativeLifecycleReceipt | None = None

    @property
    def complete(self) -> bool:
        return (
            self.native_released is True
            and (self.join_required is False or self.join_completed is True)
            and self.thread_alive is False
            and self.timed_out is False
            and (self.lifecycle is None or self.lifecycle.clean is True)
        )


@dataclass(frozen=True)
class CtpNativeLifecycleReceipt:
    """Per-generation evidence for exact CTP API/SPI teardown operations.

    This source-only receipt describes SDK calls that actually returned. It
    does not turn worker termination, timeout, or process containment into
    native cleanup evidence.
    """

    schema: Literal["ctp_native_lifecycle_receipt.v1"]
    client_kind: Literal["md", "trader"]
    session_generation: int
    connection_generation: int
    api_identity_token: str
    spi_identity_token: str
    api_object_id: int
    spi_object_id: int
    native_api_generation: int | None
    native_client_epoch: str | None
    native_api_source_id: str | None
    native_spi_source_id: str | None
    register_spi_state: Literal["not_attempted", "entered", "returned", "failed"]
    register_spi_return_type: str | None
    register_spi_error_type: str | None
    init_state: Literal["not_entered", "entered", "returned", "failed"]
    init_return_type: str | None
    init_error_type: str | None
    detach_state: Literal["not_attempted", "entered", "returned", "failed"]
    detach_return_type: str | None
    detach_error_type: str | None
    join_state: Literal["not_required", "not_started", "pending", "returned", "failed"]
    join_return_type: str | None
    join_return_code: int | None
    join_error_type: str | None
    release_attempt_count: int
    release_state: Literal["not_attempted", "entered", "returned", "failed"]
    release_return_type: str | None
    release_error_type: str | None
    timed_out: bool
    thread_alive: bool | None

    @property
    def clean(self) -> bool:
        return (
            self.release_attempt_count == 1
            and self.release_state == "returned"
            and self.detach_state == "returned"
            and self.register_spi_state in {"not_attempted", "returned"}
            and self.init_state in {"not_entered", "returned"}
            and self.join_state in {"not_required", "returned"}
            and self.thread_alive is False
            and self.timed_out is False
        )


class _CtpNativeLifecycleState:
    """Mutable, exact-object ledger used to build immutable stop receipts."""

    def __init__(
        self,
        *,
        client_kind: Literal["md", "trader"],
        session_generation: int,
        api: Any,
        spi: Any,
        native_api_generation: int | None = None,
        native_client_epoch: str | None = None,
        native_api_source_id: str | None = None,
        native_spi_source_id: str | None = None,
    ) -> None:
        self.lock = threading.RLock()
        self.api = api
        self.spi = spi
        self.client_kind = client_kind
        self.session_generation = session_generation
        self.api_identity_token = uuid.uuid4().hex
        self.spi_identity_token = uuid.uuid4().hex
        self.api_object_id = id(api)
        self.spi_object_id = id(spi)
        self.native_api_generation = native_api_generation
        self.native_client_epoch = native_client_epoch
        self.native_api_source_id = native_api_source_id
        self.native_spi_source_id = native_spi_source_id
        self.register_spi_state = "not_attempted"
        self.register_spi_return_type = None
        self.register_spi_error_type = None
        self.init_state = "not_entered"
        self.init_return_type = None
        self.init_error_type = None
        self.detach_state = "not_attempted"
        self.detach_return_type = None
        self.detach_error_type = None
        self.join_state = "not_started"
        self.join_return_type = None
        self.join_return_code = None
        self.join_error_type = None
        self.release_attempt_count = 0
        self.release_state = "not_attempted"
        self.release_return_type = None
        self.release_error_type = None

    def begin(
        self,
        operation: Literal["register_spi", "init", "detach", "join", "release"],
    ):
        with self.lock:
            if operation == "register_spi":
                if self.register_spi_state != "not_attempted":
                    return False
                self.register_spi_state = "entered"
            elif operation == "init":
                if self.init_state != "not_entered":
                    return False
                self.init_state = "entered"
            elif operation == "detach":
                if self.detach_state != "not_attempted":
                    return self.detach_state == "returned"
                self.detach_state = "entered"
            elif operation == "join":
                if self.join_state != "not_started":
                    return False
                self.join_state = "pending"
            elif operation == "release":
                if self.release_attempt_count != 0 or self.release_state != "not_attempted":
                    return False
                self.release_attempt_count = 1
                self.release_state = "entered"
            return True

    def mark_join_not_required(self) -> None:
        with self.lock:
            if self.join_state == "not_started":
                self.join_state = "not_required"

    def returned(
        self,
        operation: Literal["register_spi", "init", "detach", "join", "release"],
        result: Any,
    ) -> bool:
        with self.lock:
            if operation == "join":
                self.join_return_type = type(result).__name__
                if type(result) is not int:
                    self.join_state = "failed"
                    self.join_error_type = "unexpected_return_type"
                    return False
                self.join_state = "returned"
                self.join_return_code = result
                return True
            if operation in {"register_spi", "init", "detach", "release"}:
                state_name = {
                    "register_spi": "register_spi_state",
                    "init": "init_state",
                    "detach": "detach_state",
                    "release": "release_state",
                }[operation]
                error_name = {
                    "register_spi": "register_spi_error_type",
                    "init": "init_error_type",
                    "detach": "detach_error_type",
                    "release": "release_error_type",
                }[operation]
                return_name = {
                    "register_spi": "register_spi_return_type",
                    "init": "init_return_type",
                    "detach": "detach_return_type",
                    "release": "release_return_type",
                }[operation]
                setattr(self, return_name, type(result).__name__)
                if result is not None:
                    setattr(self, state_name, "failed")
                    setattr(self, error_name, "unexpected_return_type")
                    return False
            if operation == "register_spi":
                self.register_spi_state = "returned"
            elif operation == "init":
                self.init_state = "returned"
            elif operation == "detach":
                self.detach_state = "returned"
            elif operation == "release":
                self.release_state = "returned"
            return True

    def failed(
        self,
        operation: Literal["register_spi", "init", "detach", "join", "release"],
        error: BaseException,
    ) -> None:
        with self.lock:
            if operation == "register_spi":
                self.register_spi_state = "failed"
                self.register_spi_error_type = type(error).__name__
            elif operation == "init":
                self.init_state = "failed"
                self.init_error_type = type(error).__name__
            elif operation == "detach":
                self.detach_state = "failed"
                self.detach_error_type = type(error).__name__
            elif operation == "join":
                self.join_state = "failed"
                self.join_error_type = type(error).__name__
            elif operation == "release":
                self.release_state = "failed"
                self.release_error_type = type(error).__name__

    def snapshot(
        self,
        *,
        connection_generation: int,
        timed_out: bool = False,
        thread_alive: bool | None = None,
    ) -> CtpNativeLifecycleReceipt:
        with self.lock:
            return CtpNativeLifecycleReceipt(
                schema="ctp_native_lifecycle_receipt.v1",
                client_kind=self.client_kind,
                session_generation=self.session_generation,
                connection_generation=connection_generation,
                api_identity_token=self.api_identity_token,
                spi_identity_token=self.spi_identity_token,
                api_object_id=self.api_object_id,
                spi_object_id=self.spi_object_id,
                native_api_generation=self.native_api_generation,
                native_client_epoch=self.native_client_epoch,
                native_api_source_id=self.native_api_source_id,
                native_spi_source_id=self.native_spi_source_id,
                register_spi_state=self.register_spi_state,
                register_spi_return_type=self.register_spi_return_type,
                register_spi_error_type=self.register_spi_error_type,
                init_state=self.init_state,
                init_return_type=self.init_return_type,
                init_error_type=self.init_error_type,
                detach_state=self.detach_state,
                detach_return_type=self.detach_return_type,
                detach_error_type=self.detach_error_type,
                join_state=self.join_state,
                join_return_type=self.join_return_type,
                join_return_code=self.join_return_code,
                join_error_type=self.join_error_type,
                release_attempt_count=self.release_attempt_count,
                release_state=self.release_state,
                release_return_type=self.release_return_type,
                release_error_type=self.release_error_type,
                timed_out=timed_out,
                thread_alive=thread_alive,
            )


def _bind_ctp_native_lifecycle_state(
    client: Any,
    *,
    client_kind: Literal["md", "trader"],
    session_generation: int,
    api: Any,
    spi: Any,
) -> _CtpNativeLifecycleState:
    """Bind immutable API/SPI provenance before the first native call."""

    state = _CtpNativeLifecycleState(
        client_kind=client_kind,
        session_generation=session_generation,
        api=api,
        spi=spi,
        native_api_generation=(
            client._native_api_generation if client_kind == "trader" else None
        ),
        native_client_epoch=(
            client._native_client_epoch if client_kind == "trader" else None
        ),
        native_api_source_id=(
            client._native_api_source_id
            if client_kind == "trader" and type(client._native_api_source_id) is str
            else None
        ),
        native_spi_source_id=(
            getattr(spi, "_native_spi_source_id", None)
            if type(getattr(spi, "_native_spi_source_id", None)) is str
            else None
        ),
    )
    with _RETIRED_CTP_NATIVE_SESSIONS_LOCK:
        previous = _CTP_NATIVE_LIFECYCLE_STATES.get(id(api))
        if previous is not None and previous.api is api:
            raise RuntimeError("ctp_native_lifecycle_api_already_bound")
        _CTP_NATIVE_LIFECYCLE_STATES[id(api)] = state
    client._native_lifecycle_state = state
    return state


def _ctp_native_lifecycle_state_for_api(api: Any) -> _CtpNativeLifecycleState | None:
    with _RETIRED_CTP_NATIVE_SESSIONS_LOCK:
        state = _CTP_NATIVE_LIFECYCLE_STATES.get(id(api))
        return state if state is not None and state.api is api else None


def _record_ctp_native_call(
    api: Any,
    operation: Literal["register_spi", "init"],
    callback: Callable[[], Any],
) -> Any:
    """Capture return/exception evidence for one native startup operation."""

    state = _ctp_native_lifecycle_state_for_api(api)
    if state is not None and not state.begin(operation):
        raise RuntimeError("ctp_native_lifecycle_startup_call_repeated")
    try:
        result = callback()
    except BaseException as exc:
        if state is not None:
            state.failed(operation, exc)
        raise
    if state is not None and not state.returned(operation, result):
        raise RuntimeError("ctp_native_lifecycle_unexpected_void_return")
    return result


def _detach_ctp_native_spi_once(api: Any) -> bool:
    """Detach one exact SPI and record the native return before cleanup."""

    state = _ctp_native_lifecycle_state_for_api(api)
    if state is None:
        api.RegisterSpi(None)
        return True
    if not state.begin("detach"):
        return state.detach_state == "returned"
    try:
        result = api.RegisterSpi(None)
    except BaseException as exc:
        state.failed("detach", exc)
        with _RETIRED_CTP_NATIVE_SESSIONS_LOCK:
            _POISONED_CTP_NATIVE_SESSION_API_IDS.add(id(api))
            if not any(entry[0] is api for entry in _RETIRED_CTP_NATIVE_SESSIONS):
                _RETIRED_CTP_NATIVE_SESSIONS.append((api, state.spi, None))
        raise
    detached = state.returned("detach", result)
    if not detached:
        with _RETIRED_CTP_NATIVE_SESSIONS_LOCK:
            _POISONED_CTP_NATIVE_SESSION_API_IDS.add(id(api))
            if not any(entry[0] is api for entry in _RETIRED_CTP_NATIVE_SESSIONS):
                _RETIRED_CTP_NATIVE_SESSIONS.append((api, state.spi, None))
    return detached


class _CtpNativeJoinTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._finished = threading.Event()
        self._observation = CtpNativeJoinObservation("not_started")

    def begin(self) -> None:
        with self._lock:
            self._observation = CtpNativeJoinObservation("pending")
            self._finished.clear()

    def returned(self, result: Any) -> None:
        return_code = result if isinstance(result, int) and not isinstance(result, bool) else None
        with self._lock:
            self._observation = CtpNativeJoinObservation("returned", return_code=return_code)
            self._finished.set()

    def failed(self, error: BaseException) -> None:
        with self._lock:
            self._observation = CtpNativeJoinObservation(
                "failed", error_type=type(error).__name__
            )
            self._finished.set()

    def wait(self, timeout: float) -> CtpNativeJoinWaitResult:
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout < 0
            or timeout > _MAX_NATIVE_JOIN_WAIT_SECONDS
        ):
            raise ValueError("ctp_native_join_wait_timeout_out_of_range")
        join_call_finished = self._finished.wait(timeout)
        with self._lock:
            observation = self._observation
        return CtpNativeJoinWaitResult(join_call_finished, observation)


def _make_ctp_native_stop_receipt(
    client: Any,
    timeout: float,
    *,
    lock: Any,
    api_attribute: str,
) -> CtpNativeStopReceipt:
    """Stop one client and observe its exact Join/Release lifecycle boundedly."""

    if type(timeout) not in (int, float):
        raise ValueError("invalid CTP native stop timeout")
    try:
        timeout_seconds = float(timeout)
    except (OverflowError, ValueError):
        raise ValueError("invalid CTP native stop timeout") from None
    if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
        raise ValueError("invalid CTP native stop timeout")
    wait_seconds = min(timeout_seconds, _MAX_CTP_STOP_WAIT_SECONDS)

    with lock:
        api = getattr(client, api_attribute)
        connection_generation = int(client._connection_generation)
        thread = client._thread
        tracker = client._native_join_tracker
        lifecycle_state = getattr(client, "_native_lifecycle_state", None)
        if api is None:
            api = client._last_stopped_native_api
            connection_generation = (
                client._last_stopped_connection_generation if api is not None else connection_generation
            )
            join_required = client._last_stop_join_required
            thread = client._last_stop_join_thread
            tracker = client._last_stop_join_tracker
            lifecycle_state = getattr(client, "_last_stop_lifecycle_state", None)
        else:
            if lifecycle_state is None or lifecycle_state.api is not api:
                lifecycle_state = None
            native_may_be_live = client._native_init_started or client._join_active
            join_required = bool(
                native_may_be_live
                and (client._join_active or (thread is not None and thread.is_alive()))
            ) or _ctp_native_join_claimed(api)

    if api is None:
        return CtpNativeStopReceipt(
            connection_generation=connection_generation,
            join_required=False,
            join_completed=True,
            native_released=True,
            thread_alive=False,
            timed_out=False,
            lifecycle=None,
        )

    with lock:
        active_api = getattr(client, api_attribute)
    if active_api is api:
        # The expected API is checked by the same client lock that detaches it,
        # so a concurrent restart cannot make this receipt stop a newer API.
        client._stop_native_session(expected_api=api)

    if not join_required:
        lifecycle = (
            lifecycle_state.snapshot(
                connection_generation=connection_generation,
                timed_out=False,
                thread_alive=False,
            )
            if lifecycle_state is not None
            else None
        )
        return CtpNativeStopReceipt(
            connection_generation=connection_generation,
            join_required=False,
            join_completed=True,
            native_released=_ctp_native_api_release_confirmed(api),
            thread_alive=False,
            timed_out=False,
            lifecycle=lifecycle,
        )

    deadline = time.monotonic() + wait_seconds
    while True:
        result = tracker.wait(0.0) if tracker is not None else None
        observation = result.observation if result is not None else None
        join_completed = observation is not None and observation.state == "returned"
        join_failed = observation is not None and observation.state == "failed"
        native_released = _ctp_native_api_release_confirmed(api)
        release_poisoned = _ctp_native_api_release_poisoned(api)

        if thread is None:
            # This receipt reports the Python Join-observer thread, not the
            # native Join state. No observer was installed, so that thread is
            # definitively absent; tracker.join_completed remains the separate
            # evidence that prevents an active synchronous Join from being
            # reported complete.
            thread_alive = False
        elif thread is threading.current_thread():
            thread_alive = True
        else:
            remaining = max(0.0, deadline - time.monotonic())
            if thread.is_alive() and remaining > 0:
                try:
                    thread.join(remaining)
                except (AttributeError, RuntimeError):
                    pass
            thread_alive = thread.is_alive()

        native_released = _ctp_native_api_release_confirmed(api)
        if native_released and join_completed and thread_alive is False:
            lifecycle = (
                lifecycle_state.snapshot(
                    connection_generation=connection_generation,
                    timed_out=False,
                    thread_alive=False,
                )
                if lifecycle_state is not None
                else None
            )
            return CtpNativeStopReceipt(
                connection_generation=connection_generation,
                join_required=True,
                join_completed=True,
                native_released=True,
                thread_alive=False,
                timed_out=False,
                lifecycle=lifecycle,
            )
        if release_poisoned and join_completed and (thread is None or thread_alive is False):
            lifecycle = (
                lifecycle_state.snapshot(
                    connection_generation=connection_generation,
                    timed_out=False,
                    thread_alive=thread_alive,
                )
                if lifecycle_state is not None
                else None
            )
            return CtpNativeStopReceipt(
                connection_generation=connection_generation,
                join_required=True,
                join_completed=True,
                native_released=False,
                thread_alive=thread_alive,
                timed_out=False,
                lifecycle=lifecycle,
            )
        if join_failed and thread_alive is False:
            lifecycle = (
                lifecycle_state.snapshot(
                    connection_generation=connection_generation,
                    timed_out=False,
                    thread_alive=False,
                )
                if lifecycle_state is not None
                else None
            )
            return CtpNativeStopReceipt(
                connection_generation=connection_generation,
                join_required=True,
                join_completed=False,
                native_released=False,
                thread_alive=False,
                timed_out=False,
                lifecycle=lifecycle,
            )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = not join_failed
            lifecycle = (
                lifecycle_state.snapshot(
                    connection_generation=connection_generation,
                    timed_out=timed_out,
                    thread_alive=thread_alive,
                )
                if lifecycle_state is not None
                else None
            )
            return CtpNativeStopReceipt(
                connection_generation=connection_generation,
                join_required=True,
                join_completed=join_completed,
                native_released=native_released,
                thread_alive=thread_alive,
                timed_out=timed_out,
                lifecycle=lifecycle,
            )
        time.sleep(min(0.01, remaining))


def _retain_live_ctp_native_session(
    api: Any, spi: Any, join_thread: threading.Thread | None
) -> None:
    """Retain a live CTP API and its SWIG director after logical disconnect."""

    if api is None:
        return
    with _RETIRED_CTP_NATIVE_SESSIONS_LOCK:
        if any(existing_api is api for existing_api, _, _ in _RETIRED_CTP_NATIVE_SESSIONS):
            return
        _RETIRED_CTP_NATIVE_SESSIONS.append((api, spi, join_thread))


def _ctp_native_api_released_locked(api: Any) -> bool:
    if id(api) in _RELEASED_CTP_NATIVE_SESSION_API_IDS:
        return True
    try:
        return api in _RELEASED_CTP_NATIVE_SESSION_APIS
    except TypeError:
        return False


def _ctp_native_api_release_confirmed(api: Any) -> bool:
    with _RETIRED_CTP_NATIVE_SESSIONS_LOCK:
        return _ctp_native_api_released_locked(api)


def _ctp_native_api_release_poisoned(api: Any) -> bool:
    with _RETIRED_CTP_NATIVE_SESSIONS_LOCK:
        return id(api) in _POISONED_CTP_NATIVE_SESSION_API_IDS


def _register_ctp_native_api(api: Any) -> None:
    """Clear a recycled ID fallback when a factory returns a new API object."""

    with _RETIRED_CTP_NATIVE_SESSIONS_LOCK:
        _RELEASED_CTP_NATIVE_SESSION_API_IDS.discard(id(api))


def _set_retired_ctp_native_session_join_thread(api: Any, join_thread: threading.Thread) -> bool:
    """Claim one Join observer for a retained native session."""

    with _RETIRED_CTP_NATIVE_SESSIONS_LOCK:
        api_id = id(api)
        if (
            api_id in _CLAIMED_CTP_NATIVE_JOIN_API_IDS
            or api_id in _RELEASING_CTP_NATIVE_SESSION_API_IDS
            or api_id in _POISONED_CTP_NATIVE_SESSION_API_IDS
            or _ctp_native_api_released_locked(api)
        ):
            return False
        for index, (existing_api, spi, existing_thread) in enumerate(_RETIRED_CTP_NATIVE_SESSIONS):
            if existing_api is api:
                if existing_thread is not None:
                    return False
                _CLAIMED_CTP_NATIVE_JOIN_API_IDS.add(api_id)
                _RETIRED_CTP_NATIVE_SESSIONS[index] = (api, spi, join_thread)
                return True
    return False


def _claim_ctp_native_join(api: Any) -> bool:
    """Atomically claim the sole Join call permitted for this native API."""

    with _RETIRED_CTP_NATIVE_SESSIONS_LOCK:
        api_id = id(api)
        if (
            api_id in _CLAIMED_CTP_NATIVE_JOIN_API_IDS
            or api_id in _RELEASING_CTP_NATIVE_SESSION_API_IDS
            or api_id in _POISONED_CTP_NATIVE_SESSION_API_IDS
            or _ctp_native_api_released_locked(api)
        ):
            return False
        _CLAIMED_CTP_NATIVE_JOIN_API_IDS.add(api_id)
        return True


def _mark_ctp_native_join_returned(api: Any) -> None:
    with _RETIRED_CTP_NATIVE_SESSIONS_LOCK:
        api_id = id(api)
        if api_id in _CLAIMED_CTP_NATIVE_JOIN_API_IDS:
            _RETURNED_CTP_NATIVE_JOIN_API_IDS.add(api_id)


def _ctp_native_join_claimed(api: Any) -> bool:
    with _RETIRED_CTP_NATIVE_SESSIONS_LOCK:
        return id(api) in _CLAIMED_CTP_NATIVE_JOIN_API_IDS


def _ctp_native_join_returned(api: Any) -> bool:
    with _RETIRED_CTP_NATIVE_SESSIONS_LOCK:
        return id(api) in _RETURNED_CTP_NATIVE_JOIN_API_IDS


def _release_ctp_native_api_once(
    api: Any,
    *,
    spi: Any = None,
    join_thread: threading.Thread | None = None,
    after_join: bool = False,
) -> bool:
    """Detach and release one CTP API through the shared lifecycle fence.

    Immediate cleanup is valid only when no Join is active. Deferred cleanup
    is valid only for a retained API whose sole Join claim has completed. The
    same reservation protects the immediate detach call and Release call from
    duplicate concurrent cleanup. Any failed Release poisons and retains the
    API because its native state may have been partially freed.
    """

    retained: tuple[Any, Any, threading.Thread | None] | None = None
    api_id = id(api)
    lifecycle_state = _ctp_native_lifecycle_state_for_api(api)
    with _RETIRED_CTP_NATIVE_SESSIONS_LOCK:
        if (
            api_id in _RELEASING_CTP_NATIVE_SESSION_API_IDS
            or api_id in _POISONED_CTP_NATIVE_SESSION_API_IDS
            or _ctp_native_api_released_locked(api)
        ):
            return False
        for entry in _RETIRED_CTP_NATIVE_SESSIONS:
            if entry[0] is api:
                retained = entry
                break
        if after_join:
            if (
                api_id not in _CLAIMED_CTP_NATIVE_JOIN_API_IDS
                or api_id not in _RETURNED_CTP_NATIVE_JOIN_API_IDS
                or retained is None
                or (
                    lifecycle_state is not None
                    and lifecycle_state.detach_state != "returned"
                )
            ):
                return False
        elif api_id in _CLAIMED_CTP_NATIVE_JOIN_API_IDS or retained is not None:
            return False
        _RELEASING_CTP_NATIVE_SESSION_API_IDS.add(api_id)

    if not after_join:
        try:
            detached = _detach_ctp_native_spi_once(api)
        except BaseException as exc:
            with _RETIRED_CTP_NATIVE_SESSIONS_LOCK:
                _POISONED_CTP_NATIVE_SESSION_API_IDS.add(api_id)
                _RELEASING_CTP_NATIVE_SESSION_API_IDS.discard(api_id)
                if retained is None and not any(
                    entry[0] is api for entry in _RETIRED_CTP_NATIVE_SESSIONS
                ):
                    _RETIRED_CTP_NATIVE_SESSIONS.append((api, spi, join_thread))
            if isinstance(exc, Exception):
                _logger.error(
                    "CTP native SPI detach failed (error_type=%s)",
                    type(exc).__name__,
                )
                return False
            raise
        if not detached:
            with _RETIRED_CTP_NATIVE_SESSIONS_LOCK:
                _POISONED_CTP_NATIVE_SESSION_API_IDS.add(api_id)
                _RELEASING_CTP_NATIVE_SESSION_API_IDS.discard(api_id)
                if retained is None and not any(
                    entry[0] is api for entry in _RETIRED_CTP_NATIVE_SESSIONS
                ):
                    _RETIRED_CTP_NATIVE_SESSIONS.append((api, spi, join_thread))
            return False

    if lifecycle_state is not None and not lifecycle_state.begin("release"):
        with _RETIRED_CTP_NATIVE_SESSIONS_LOCK:
            _POISONED_CTP_NATIVE_SESSION_API_IDS.add(api_id)
            _RELEASING_CTP_NATIVE_SESSION_API_IDS.discard(api_id)
            if retained is None and not any(
                entry[0] is api for entry in _RETIRED_CTP_NATIVE_SESSIONS
            ):
                _RETIRED_CTP_NATIVE_SESSIONS.append((api, spi, join_thread))
        return False

    # A failed Release has an unknown partial outcome, so keep both Python
    # owners alive and fence every later attempt.
    release_succeeded = False
    pending_base_exception: BaseException | None = None
    try:
        result = api.Release()
        release_succeeded = (
            lifecycle_state.returned("release", result)
            if lifecycle_state is not None
            else True
        )
        if not release_succeeded:
            _logger.error("CTP native API Release returned an unexpected value")
    except BaseException as exc:
        if lifecycle_state is not None:
            lifecycle_state.failed("release", exc)
        if isinstance(exc, Exception):
            _logger.error(
                "CTP native API Release failed (error_type=%s)",
                type(exc).__name__,
            )
        else:
            pending_base_exception = exc
    finally:
        with _RETIRED_CTP_NATIVE_SESSIONS_LOCK:
            if not release_succeeded:
                _POISONED_CTP_NATIVE_SESSION_API_IDS.add(api_id)
                if retained is None and not any(
                    entry[0] is api for entry in _RETIRED_CTP_NATIVE_SESSIONS
                ):
                    _RETIRED_CTP_NATIVE_SESSIONS.append((api, spi, join_thread))
            _RELEASING_CTP_NATIVE_SESSION_API_IDS.discard(api_id)
            if release_succeeded:
                _CLAIMED_CTP_NATIVE_JOIN_API_IDS.discard(api_id)
                _RETURNED_CTP_NATIVE_JOIN_API_IDS.discard(api_id)
                try:
                    _RELEASED_CTP_NATIVE_SESSION_APIS.add(api)
                except TypeError:
                    _RELEASED_CTP_NATIVE_SESSION_API_IDS.add(api_id)
                _RETIRED_CTP_NATIVE_SESSIONS[:] = [
                    entry for entry in _RETIRED_CTP_NATIVE_SESSIONS if entry[0] is not api
                ]
                if _CTP_NATIVE_LIFECYCLE_STATES.get(api_id) is lifecycle_state:
                    _CTP_NATIVE_LIFECYCLE_STATES.pop(api_id, None)
    if pending_base_exception is not None:
        raise pending_base_exception
    return release_succeeded


def _release_retired_ctp_native_session_after_join(api: Any) -> bool:
    """Release a retained native API only after its Join returned."""

    with _RETIRED_CTP_NATIVE_SESSIONS_LOCK:
        retained = next((entry for entry in _RETIRED_CTP_NATIVE_SESSIONS if entry[0] is api), None)
    if retained is None:
        return False
    return _release_ctp_native_api_once(
        api,
        spi=retained[1],
        join_thread=retained[2],
        after_join=True,
    )


def _release_ctp_native_api_immediately(
    api: Any,
    spi: Any,
    *,
    state_lock: Any,
    pending_api_ids: set[int],
) -> bool:
    """Detach and release a non-joined API, fencing restart on uncertainty."""

    api_id = id(api)
    with state_lock:
        pending_api_ids.add(api_id)
    released = _release_ctp_native_api_once(api, spi=spi)
    if released or _ctp_native_api_release_confirmed(api):
        with state_lock:
            pending_api_ids.discard(api_id)
    return released


_CTP_EXECUTION_GATE_PROOF_FIELDS = (
    "account_fingerprint",
    "trading_day",
    "instrument",
    "connection_generation",
    "environment_profile",
    "preflight_sha256",
    "receipt_sha256",
    "native_sha256",
    "ctp_package_sha256",
    "source_hashes_sha256",
    "dependency_hashes_sha256",
)
_CTP_EXECUTION_GATE_BUNDLE_SCOPE_VERSION = "ctp-contract-bundle-v1"
_CTP_EXECUTION_GATE_BUNDLE_PROOF_FIELDS = (
    *_CTP_EXECUTION_GATE_PROOF_FIELDS,
    "scope_version",
    "authorized_instruments",
)
_CTP_EXECUTION_GATE_HASH_FIELDS = (
    "preflight_sha256",
    "receipt_sha256",
    "native_sha256",
    "ctp_package_sha256",
    "source_hashes_sha256",
    "dependency_hashes_sha256",
)
_CTP_EXCHANGES = {"CFFEX", "CZCE", "DCE", "GFEX", "INE", "SHFE"}
_CTP_EXCHANGE_ALIASES = {"ZCE": "CZCE"}
_CTP_INSTRUMENT_RE = re.compile(r"^[A-Z]{1,3}[0-9]{3,4}$")
_CTP_BUNDLE_INSTRUMENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*$")
_CTP_GATE_REASON_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_CTP_MANAGED_RUNTIME_ORDER_ID_RE = re.compile(r"^bt-managed-v1:[0-9a-f]{64}$")
_CTP_MANAGED_INTENT_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_CTP_MANAGED_ACTION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_CTP_MANAGED_ORDER_REF_RE = re.compile(r"^[0-9]{12}$")
_CTP_MANAGED_ORDER_SYS_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_CTP_MANAGED_NATIVE_ACTION_REF_RE = re.compile(r"^[0-9]{1,12}$")
# The public API view is intentionally much narrower than the SWIG object.
# Raw lifecycle calls can change the effective native connection while leaving
# the Python-side immutable front binding unchanged.  Keep the tiny allowlist
# to pure observation methods; typed query methods are handled separately.
_CTP_PUBLIC_NATIVE_READ_CALLS = frozenset({"GetApiVersion", "GetTradingDay"})


class CtpExecutionGateError(RuntimeError):
    """Credential-free, deterministic rejection from the managed CTP write gate."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _validate_managed_cancel_identity(
    *,
    runtime_order_id: Any,
    managed_intent_id: Any,
    runtime_action_id: Any,
    managed_cancel_intent_id: Any,
) -> bool:
    """Recognize and validate the explicit managed-cancel opt-in tuple.

    Calls that omit all four values keep the legacy cancellation contract.
    Supplying any value opts into the stricter managed contract, so partial
    identities never fall back to the legacy target alternatives.
    """

    values = (
        runtime_order_id,
        managed_intent_id,
        runtime_action_id,
        managed_cancel_intent_id,
    )
    if all(value is None for value in values):
        return False
    if any(value is None for value in values):
        raise CtpExecutionGateError("ctp_execution_gate_managed_cancel_identity_incomplete")
    if (
        type(runtime_order_id) is not str
        or _CTP_MANAGED_RUNTIME_ORDER_ID_RE.fullmatch(runtime_order_id) is None
        or type(managed_intent_id) is not str
        or _CTP_MANAGED_INTENT_ID_RE.fullmatch(managed_intent_id) is None
        or type(runtime_action_id) is not str
        or _CTP_MANAGED_ACTION_ID_RE.fullmatch(runtime_action_id) is None
        or type(managed_cancel_intent_id) is not str
        or _CTP_MANAGED_ACTION_ID_RE.fullmatch(managed_cancel_intent_id) is None
    ):
        raise CtpExecutionGateError("ctp_execution_gate_managed_cancel_identity_invalid")
    if runtime_action_id != managed_cancel_intent_id:
        raise CtpExecutionGateError("ctp_execution_gate_managed_cancel_action_mismatch")
    if managed_cancel_intent_id == managed_intent_id:
        raise CtpExecutionGateError("ctp_execution_gate_managed_cancel_intent_reused")
    return True


def _validate_managed_cancel_target_values(
    *,
    order_ref: Any,
    order_sys_id: Any,
    exchange_id: Any,
    front_id: Any,
    session_id: Any,
) -> None:
    """Validate the I9 cancel target tuple before allocating a request ID."""

    if (
        type(order_ref) is not str
        or _CTP_MANAGED_ORDER_REF_RE.fullmatch(order_ref) is None
        or type(order_sys_id) is not str
        or _CTP_MANAGED_ORDER_SYS_ID_RE.fullmatch(order_sys_id) is None
        or type(exchange_id) is not str
        or not exchange_id
        or exchange_id != exchange_id.strip()
        or not exchange_id.isascii()
        or type(front_id) is not int
        or front_id <= 0
        or type(session_id) is not int
        or session_id <= 0
    ):
        raise CtpExecutionGateError("ctp_execution_gate_managed_cancel_target_incomplete")


def _validate_managed_cancel_native_fields(
    snapshot: _ManagedOrderActionFieldSnapshot,
    request_id: int,
) -> None:
    """Require the complete SDK native-field target consumed by the I9 mapper."""

    identity = snapshot.identity
    if (
        type(snapshot.request_id_value) is not int
        or snapshot.request_id_value != request_id
        or identity.field_request_id != request_id
        or type(snapshot.front_id_value) is not int
        or identity.front_id is None
        or identity.front_id <= 0
        or type(snapshot.session_id_value) is not int
        or identity.session_id is None
        or identity.session_id <= 0
        or type(snapshot.order_action_ref_value) is not int
        or snapshot.order_action_ref_value != request_id
        or _CTP_MANAGED_ORDER_REF_RE.fullmatch(identity.order_ref) is None
        or _CTP_MANAGED_ORDER_SYS_ID_RE.fullmatch(identity.order_sys_id) is None
        or not identity.exchange_id
        or identity.exchange_id != identity.exchange_id.strip()
        or not identity.exchange_id.isascii()
        or not identity.instrument_id
        or identity.action_flag != "0"
        or _CTP_MANAGED_NATIVE_ACTION_REF_RE.fullmatch(identity.order_action_ref) is None
        or identity.order_action_ref != str(request_id)
    ):
        raise CtpExecutionGateError("ctp_execution_gate_managed_cancel_target_invalid")


def _copy_managed_order_action_field(
    template: Any,
    snapshot: _ManagedOrderActionFieldSnapshot,
) -> Any:
    """Build a detached native field exclusively from the validated snapshot."""

    identity = snapshot.identity
    try:
        detached = type(template)()
        if detached is template:
            raise TypeError("native field constructor did not create a distinct object")
        values = {
            "BrokerID": identity.broker_id,
            "InvestorID": identity.investor_id,
            "UserID": snapshot.user_id,
            "InstrumentID": identity.instrument_id,
            "ExchangeID": identity.exchange_id,
            "OrderRef": identity.order_ref,
            "OrderSysID": identity.order_sys_id,
            "FrontID": snapshot.front_id_value,
            "SessionID": snapshot.session_id_value,
            "RequestID": snapshot.request_id_value,
            "OrderActionRef": snapshot.order_action_ref_value,
            "ActionFlag": identity.action_flag,
        }
        for name, value in values.items():
            setattr(detached, name, value)
    except Exception as exc:
        raise CtpExecutionGateError(
            "ctp_execution_gate_managed_cancel_native_snapshot_unavailable"
        ) from exc
    if _managed_order_action_field_snapshot(detached) != snapshot:
        raise CtpExecutionGateError("ctp_execution_gate_managed_cancel_native_snapshot_mismatch")
    return detached


class CtpNativeCallbackConsumerError(RuntimeError):
    """Fail-closed rejection from the source callback-event consumer lease."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _NativeCallbackEventConsumerToken:
    """Identity-only capability for one source callback queue consumer."""

    __slots__ = ("__weakref__",)


@dataclass
class _NativeCallbackEventConsumerLease:
    token: _NativeCallbackEventConsumerToken
    source_instance_id: str
    native_client_epoch: str
    native_api_source_id: str
    native_api_generation: int
    queue_generation: int
    waiting: bool = False
    revoked: bool = False


# These objects deliberately have no public construction or retrieval API.
# A bare ``object()`` (or a mapping reconstructed from session-state fields)
# must never become a CTP write credential.  The parent SDK receives an owner
# capability through its private feed handshake and uses it only to install
# the managed gate.  The two one-shot grants below carry the mutable proof
# state; the capability itself is intentionally insufficient to arm orders or
# confirm settlement.
_CTP_CORE_EXECUTION_AUTHORITY_SEAL = object()
_CTP_EXECUTION_AUTHORIZATION_SEAL = object()


class _CtpCoreExecutionAuthority:
    """Opaque owner capability accepted only by the managed CTP boundary."""

    __slots__ = ("_seal", "_test_only")

    def __init__(self, seal: object, *, test_only: bool = False) -> None:
        if seal is not _CTP_CORE_EXECUTION_AUTHORITY_SEAL:
            raise CtpExecutionGateError("ctp_execution_gate_capability_required")
        self._seal = seal
        self._test_only = test_only


def _issue_ctp_execution_authority_for_core() -> object:
    """Private core/test seam; it is not part of the public feed contract.

    Production callers have no public route to this function.  It exists so
    the owning SDK can install a process-local capability before it exposes a
    CTP feed and so offline contract tests can exercise the native boundary.
    """

    return _CtpCoreExecutionAuthority(_CTP_CORE_EXECUTION_AUTHORITY_SEAL)


def _issue_ctp_execution_authority_for_test() -> object:
    """Private offline-test seam for exercising managed native transitions.

    This is intentionally separate from the parent/core issuer.  Only this
    marker permits compatibility construction of a one-shot token from a
    fixture mapping; a production core capability never does.
    """

    return _CtpCoreExecutionAuthority(_CTP_CORE_EXECUTION_AUTHORITY_SEAL, test_only=True)


def _is_ctp_core_execution_authority(value: object) -> bool:
    return bool(
        type(value) is _CtpCoreExecutionAuthority
        and getattr(value, "_seal", None) is _CTP_CORE_EXECUTION_AUTHORITY_SEAL
    )


def _is_ctp_test_execution_authority(value: object) -> bool:
    return bool(
        _is_ctp_core_execution_authority(value) and getattr(value, "_test_only", False) is True
    )


class _CtpExecutionAuthorization:
    """Native one-shot order-arm authorization, owned by one TraderClient."""

    __slots__ = (
        "_seal",
        "_client_ref",
        "_capability",
        "_proof",
        "_environment_profile",
        "_strategy_identity_sha256",
        "_execution_cycle_id",
        "_preflight_epoch",
        "_used",
    )

    def __init__(
        self,
        *,
        client: object,
        capability: object,
        proof: Mapping[str, Any],
        environment_profile: str,
        strategy_identity_sha256: str,
        execution_cycle_id: str,
        preflight_epoch: int,
    ) -> None:
        self._seal = _CTP_EXECUTION_AUTHORIZATION_SEAL
        self._client_ref = weakref.ref(client)
        self._capability = capability
        self._proof = dict(proof)
        self._environment_profile = environment_profile
        self._strategy_identity_sha256 = strategy_identity_sha256
        self._execution_cycle_id = execution_cycle_id
        self._preflight_epoch = preflight_epoch
        self._used = False


class _CtpSettlementAuthorization:
    """Native one-shot settlement-confirm authorization with a fixed budget."""

    __slots__ = (
        "_seal",
        "_client_ref",
        "_capability",
        "_account_fingerprint",
        "_trading_day",
        "_connection_generation",
        "_environment_profile",
        "_scope",
        "_budget",
        "_used",
    )

    def __init__(
        self,
        *,
        client: object,
        capability: object,
        account_fingerprint: str,
        trading_day: str,
        connection_generation: int,
        environment_profile: str,
        scope: str,
        budget: int,
    ) -> None:
        self._seal = _CTP_EXECUTION_AUTHORIZATION_SEAL
        self._client_ref = weakref.ref(client)
        self._capability = capability
        self._account_fingerprint = account_fingerprint
        self._trading_day = trading_day
        self._connection_generation = connection_generation
        self._environment_profile = environment_profile
        self._scope = scope
        self._budget = budget
        self._used = False


class _ManagedTraderApiView:
    """Dynamically expose the current native API through the managed gate."""

    def __init__(self, client: Any) -> None:
        # Keep no native API reference here.  A caller may cache this view or a
        # Req* callable before the SDK configures the gate; every invocation
        # must still observe the client's current API and gate state.
        self.__client_ref = weakref.ref(client)

    def __getattr__(self, name: str) -> Any:
        client = self.__client_ref()
        if client is None:
            raise CtpExecutionGateError("ctp_execution_gate_client_unavailable")
        if name.startswith("Req"):

            def invoke(*args: Any, **kwargs: Any) -> Any:
                current = self.__client_ref()
                if current is None:
                    raise CtpExecutionGateError("ctp_execution_gate_client_unavailable")
                return current._invoke_public_api_request(name, args, kwargs)

            return invoke
        value = client._get_public_api_attribute(name)
        if callable(value):

            def invoke(*args: Any, **kwargs: Any) -> Any:
                current = self.__client_ref()
                if current is None:
                    raise CtpExecutionGateError("ctp_execution_gate_client_unavailable")
                return current._invoke_public_api_callable(name, args, kwargs)

            return invoke
        return value


def _canonical_ctp_exchange(value: Any) -> str:
    exchange = str(value or "").strip().upper()
    exchange = _CTP_EXCHANGE_ALIASES.get(exchange, exchange)
    return exchange if exchange in _CTP_EXCHANGES else ""


def canonical_ctp_instrument(value: Any, exchange_id: Any = None) -> str:
    """Return the execution-gate contract identity as ``EXCHANGE.INSTRUMENT``."""

    text = str(value or "").strip().upper()
    supplied_exchange = _canonical_ctp_exchange(exchange_id)
    if not text or (exchange_id not in (None, "") and not supplied_exchange):
        return ""
    parts = text.split(".")
    if len(parts) == 1:
        exchange = supplied_exchange
        instrument = parts[0]
    elif len(parts) == 2:
        first_exchange = _canonical_ctp_exchange(parts[0])
        last_exchange = _canonical_ctp_exchange(parts[1])
        if bool(first_exchange) == bool(last_exchange):
            return ""
        exchange = first_exchange or last_exchange
        instrument = parts[1] if first_exchange else parts[0]
        if supplied_exchange and supplied_exchange != exchange:
            return ""
    else:
        return ""
    if not exchange or not _CTP_INSTRUMENT_RE.fullmatch(instrument):
        return ""
    letters = instrument.rstrip("0123456789")
    digits = instrument[len(letters) :]
    if exchange == "CZCE" and len(digits) == 4:
        digits = digits[-3:]
    return f"{exchange}.{letters}{digits}"


def canonical_ctp_bundle_instrument(value: Any, exchange_id: Any = None) -> str:
    """Return one exact raw native CTP contract identity for a V2 bundle.

    DCE option identifiers can contain hyphens and lowercase product codes.
    V2 deliberately preserves that native spelling and does not apply V1's
    legacy CZCE alias normalization before a submit/cancel reaches CTP.
    """
    text = str(value or "").strip()
    supplied_exchange = _canonical_ctp_exchange(exchange_id)
    if not text or (exchange_id not in (None, "") and not supplied_exchange):
        return ""
    parts = text.split(".")
    if len(parts) == 1:
        exchange = supplied_exchange
        instrument = parts[0]
    elif len(parts) == 2:
        first_exchange = _canonical_ctp_exchange(parts[0])
        last_exchange = _canonical_ctp_exchange(parts[1])
        if bool(first_exchange) == bool(last_exchange):
            return ""
        exchange = first_exchange or last_exchange
        instrument = parts[1] if first_exchange else parts[0]
        if supplied_exchange and supplied_exchange != exchange:
            return ""
    else:
        return ""
    if (
        not exchange
        or len(instrument) > 80
        or not _CTP_BUNDLE_INSTRUMENT_RE.fullmatch(instrument)
        or not any(character.isdigit() for character in instrument)
    ):
        return ""
    return f"{exchange}.{instrument}"


def _canonical_ctp_bundle_wire_instrument(value: Any, exchange_id: Any = None) -> str:
    """Return a V2 identity only when native CTP fields can stay verbatim.

    The V2 proof and recovery readers may canonicalize qualified forms such as
    ``DCE.m2701-C-3400``.  At the final native submit/cancel boundary the
    request fields are serialized unchanged, so only an exact bare
    ``InstrumentID`` paired with the canonical ``ExchangeID`` is safe.
    """
    if (
        not isinstance(value, str)
        or value != value.strip()
        or "." in value
        or not isinstance(exchange_id, str)
        or exchange_id != exchange_id.strip()
    ):
        return ""
    canonical = canonical_ctp_bundle_instrument(value, exchange_id)
    if not canonical:
        return ""
    exchange, instrument = canonical.split(".", 1)
    return canonical if instrument == value and exchange == exchange_id else ""


def _is_execution_gate_bundle(proof: Any) -> bool:
    return bool(
        isinstance(proof, Mapping)
        and proof.get("scope_version") == _CTP_EXECUTION_GATE_BUNDLE_SCOPE_VERSION
        and isinstance(proof.get("authorized_instruments"), (list, tuple))
    )


def _execution_gate_instruments(proof: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(proof, Mapping):
        return ()
    if _is_execution_gate_bundle(proof):
        return tuple(proof["authorized_instruments"])
    instrument = proof.get("instrument")
    return (instrument,) if isinstance(instrument, str) else ()


def _canonical_execution_gate_instrument(
    proof: Mapping[str, Any] | None,
    value: Any,
    exchange_id: Any = None,
    *,
    native_wire: bool = False,
) -> str:
    if _is_execution_gate_bundle(proof):
        if native_wire:
            return _canonical_ctp_bundle_wire_instrument(value, exchange_id)
        return canonical_ctp_bundle_instrument(value, exchange_id)
    return canonical_ctp_instrument(value, exchange_id)


def _execution_gate_proof(value: Any) -> tuple[dict[str, Any], str]:
    fields = set(value) if isinstance(value, Mapping) else set()
    is_bundle = fields == set(_CTP_EXECUTION_GATE_BUNDLE_PROOF_FIELDS)
    if fields == set(_CTP_EXECUTION_GATE_PROOF_FIELDS):
        proof = {field: value[field] for field in _CTP_EXECUTION_GATE_PROOF_FIELDS}
    elif is_bundle:
        proof = {field: value[field] for field in _CTP_EXECUTION_GATE_BUNDLE_PROOF_FIELDS}
    else:
        raise CtpExecutionGateError("ctp_execution_gate_invalid_proof")
    for field in (
        "account_fingerprint",
        "trading_day",
        "instrument",
        "environment_profile",
    ):
        item = proof[field]
        if not isinstance(item, str) or not item or item != item.strip():
            raise CtpExecutionGateError("ctp_execution_gate_invalid_proof")
    account_fingerprint = proof["account_fingerprint"]
    account_digest = account_fingerprint.removeprefix("acct_")
    if (
        account_fingerprint != account_fingerprint.lower()
        or not account_fingerprint.startswith("acct_")
        or len(account_digest) != 16
        or any(char not in "0123456789abcdef" for char in account_digest)
    ):
        raise CtpExecutionGateError("ctp_execution_gate_invalid_proof")
    canonical_instrument = (
        canonical_ctp_bundle_instrument(proof["instrument"])
        if is_bundle
        else canonical_ctp_instrument(proof["instrument"])
    )
    if not canonical_instrument or canonical_instrument != proof["instrument"]:
        raise CtpExecutionGateError("ctp_execution_gate_invalid_proof")
    if is_bundle:
        authorized = proof["authorized_instruments"]
        if (
            proof.get("scope_version") != _CTP_EXECUTION_GATE_BUNDLE_SCOPE_VERSION
            or not isinstance(authorized, (list, tuple))
            or not 2 <= len(authorized) <= 3
            or any(not isinstance(item, str) for item in authorized)
        ):
            raise CtpExecutionGateError("ctp_execution_gate_invalid_proof")
        canonical_authorized = tuple(canonical_ctp_bundle_instrument(item) for item in authorized)
        if (
            any(not item for item in canonical_authorized)
            or tuple(authorized) != canonical_authorized
            or tuple(sorted(canonical_authorized)) != canonical_authorized
            or len(set(canonical_authorized)) != len(canonical_authorized)
            or len({item.partition(".")[0] for item in canonical_authorized}) != 1
            or proof["instrument"] not in canonical_authorized
        ):
            raise CtpExecutionGateError("ctp_execution_gate_invalid_proof")
        proof["authorized_instruments"] = list(canonical_authorized)
    generation = proof["connection_generation"]
    if type(generation) is not int or generation <= 0:
        raise CtpExecutionGateError("ctp_execution_gate_invalid_proof")
    try:
        parsed_day = datetime.strptime(proof["trading_day"], "%Y%m%d")
    except ValueError:
        raise CtpExecutionGateError("ctp_execution_gate_invalid_proof") from None
    if parsed_day.strftime("%Y%m%d") != proof["trading_day"]:
        raise CtpExecutionGateError("ctp_execution_gate_invalid_proof")
    for field in _CTP_EXECUTION_GATE_HASH_FIELDS:
        digest = proof[field]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or digest != digest.lower()
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise CtpExecutionGateError("ctp_execution_gate_invalid_proof")
    serialized = json.dumps(
        proof, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return proof, hashlib.sha256(serialized).hexdigest()


def _execution_gate_reason(value: Any) -> str:
    reason = str(value or "execution_arm_revoked").strip().lower()
    return reason if _CTP_GATE_REASON_RE.fullmatch(reason) else "execution_arm_revoked"


def empty_ctp_request_counts() -> dict[str, int]:
    """Return the closed request-count schema used by strict read-only gates."""

    return dict.fromkeys(CTP_REQUEST_COUNT_KEYS, 0)


def _select_ctp_runtime_source() -> str:
    """Use only bt_api_ctp's bundled native extension at runtime.

    Switching a stateful CTP session between unrelated Python bindings changes
    callback ownership and native ABI assumptions.  The package therefore owns
    its runtime rather than accepting external ``ctp`` or ``openctp_ctp``
    process overrides.
    """
    return "vendored_bt_api_py"


_CTP_RUNTIME_SOURCE = _select_ctp_runtime_source()


def _is_native_extension_path(path: Path) -> bool:
    path_text = str(path)
    return any(path_text.endswith(suffix) for suffix in importlib.machinery.EXTENSION_SUFFIXES)


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _is_vendored_native_trader_api(api: Any) -> bool:
    if _CTP_RUNTIME_SOURCE != "vendored_bt_api_py":
        return False
    try:
        return isinstance(api, CThostFtdcTraderApi)
    except TypeError:
        return False


def _submit_trader_user_login(api: Any, field: CThostFtdcReqUserLoginField, request_id: int) -> Any:
    """Submit Trader login through the shared public ABI guard."""

    if not _is_vendored_native_trader_api(api):
        return api.ReqUserLogin(field, request_id)
    return _ctp_base._submit_public_trader_user_login(api, field, request_id)


def _ctp_python_package_identity(
    package_root: Path | None = None,
) -> tuple[list[dict[str, str]], str]:
    """Hash every controlled Python source under the installed CTP package."""

    if package_root is None:
        import bt_api_ctp

        package_root = Path(bt_api_ctp.__file__).resolve().parent
    else:
        package_root = Path(package_root).resolve()
    paths = sorted(
        (
            path
            for path in package_root.rglob("*.py")
            if path.is_file() and "__pycache__" not in path.relative_to(package_root).parts
        ),
        key=lambda path: path.relative_to(package_root).as_posix(),
    )
    manifest = [
        {
            "path": path.relative_to(package_root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in paths
    ]
    serialized = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return manifest, hashlib.sha256(serialized).hexdigest()


def _runtime_module_prefix() -> str:
    return "bt_api_ctp.ctp"


def _selected_runtime_modules() -> dict[str, str]:
    prefix = _runtime_module_prefix()
    paths: dict[str, str] = {}
    for module_name, module in tuple(sys.modules.items()):
        if module_name != prefix and not module_name.startswith(f"{prefix}."):
            continue
        origin = str(getattr(module, "__file__", "") or "")
        if origin:
            paths[module_name] = str(Path(origin).resolve())
    return dict(sorted(paths.items()))


def get_ctp_native_diagnostics() -> dict[str, Any]:
    """Report exact native binaries loaded for the selected CTP runtime."""
    if _CTP_RUNTIME_SOURCE == "vendored_bt_api_py":
        diagnostics: dict[str, Any] = dict(_get_vendored_ctp_native_diagnostics())
    else:
        diagnostics = {}

    package_manifest, package_sha256 = _ctp_python_package_identity()
    runtime_modules = _selected_runtime_modules()
    native_modules = {
        module_name: module_path
        for module_name, module_path in runtime_modules.items()
        if _is_native_extension_path(Path(module_path))
    }
    native_hashes = {
        module_path: _sha256_file(Path(module_path))
        for module_path in sorted(set(native_modules.values()))
    }
    native_hashes = {path: digest for path, digest in native_hashes.items() if digest}
    binding_classes = {
        name: {
            "module": cls.__module__,
            "module_path": runtime_modules.get(cls.__module__, ""),
        }
        for name, cls in (
            ("CThostFtdcMdApi", CThostFtdcMdApi),
            ("CThostFtdcMdSpi", CThostFtdcMdSpi),
            ("CThostFtdcTraderApi", CThostFtdcTraderApi),
            ("CThostFtdcTraderSpi", CThostFtdcTraderSpi),
        )
    }
    native_loaded = _is_vendored_ctp_native_loaded()
    loaded_paths = sorted(set(native_modules.values()))
    selected_path = loaded_paths[0] if loaded_paths else ""
    diagnostics_override = {
        "runtime_source": _CTP_RUNTIME_SOURCE,
        "native_loaded": native_loaded,
        "reason": (
            "native_loaded" if native_loaded else "selected_runtime_has_no_native_extension"
        ),
        "runtime_module_paths": runtime_modules,
        "native_module_paths": native_modules,
        "native_module_sha256": native_hashes,
        "binding_classes": binding_classes,
        "ctp_package_manifest": package_manifest,
        "ctp_package_sha256": package_sha256,
        "loaded_module_path": selected_path,
        "loaded_module_sha256": native_hashes.get(selected_path, ""),
    }
    diagnostics.update(diagnostics_override)
    return diagnostics


def is_ctp_native_loaded() -> bool:
    """Return whether the selected runtime has a verified loaded native binary."""
    return bool(get_ctp_native_diagnostics()["native_loaded"])


def _format_selected_native_diagnostics(diagnostics: dict[str, Any]) -> str:
    if diagnostics["native_loaded"]:
        return (
            f"CTP runtime {diagnostics['runtime_source']} loaded native module "
            f"{diagnostics['loaded_module_path']}"
        )
    detail = str(diagnostics.get("import_error") or diagnostics.get("reason") or "unknown")
    return f"CTP runtime {diagnostics['runtime_source']} has no verified native extension: {detail}"


def _check_native_module():
    """Raise ImportError early if the selected CTP native runtime is unavailable."""
    diagnostics = get_ctp_native_diagnostics()
    if diagnostics["native_loaded"]:
        return
    raise ImportError(
        f"{_format_selected_native_diagnostics(diagnostics)}. "
        "Install a native extension matching this OS, Python ABI, and selected CTP runtime."
    )


def get_ctp_runtime_source() -> str:
    return _CTP_RUNTIME_SOURCE


def _flow_dir(prefix):
    """Create a temp directory for CTP flow files."""
    h = hashlib.md5(prefix.encode("utf-8"), usedforsecurity=False).hexdigest()
    path = os.path.join(tempfile.gettempdir(), "ctp_client", h) + os.sep
    os.makedirs(path, exist_ok=True)
    return path


def _snapshot_ctp_field(field):
    """Create a plain dict snapshot from a SWIG field.

    Order / trade callbacks arrive on CTP's background thread. Converting the
    field to a plain dict inside the callback avoids leaking thread-bound SWIG
    objects to other threads or test assertions.
    """
    if field is None:
        return {}

    result = {}
    for attr in dir(field):
        if attr.startswith("_") or attr in {"this", "thisown"}:
            continue
        try:
            value = getattr(field, attr)
        except Exception:
            continue
        if not callable(value):
            result[attr] = value
    return result


def _native_text_field(field: Any, name: str) -> str:
    value = _native_field_value(field, name, "")
    return _native_text_value(value)


def _native_field_value(field: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(field, name, default) if field is not None else default
    except Exception:
        return default


def _native_text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _native_callback_flag(value: Any) -> bool | None:
    """Normalize SWIG callback flags without accepting coercible strings."""
    if type(value) is bool:
        return value
    if type(value) is int and value in (0, 1):
        return bool(value)
    return None


def _native_int_field(field: Any, name: str) -> int | None:
    return _native_int_value(_native_field_value(field, name, 0))


def _native_int_value(value: Any) -> int | None:
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return None


@dataclass(frozen=True)
class _OrderActionIdentity:
    broker_id: str
    investor_id: str
    order_action_ref: str
    order_ref: str
    field_request_id: int | None
    front_id: int | None
    session_id: int | None
    exchange_id: str
    order_sys_id: str
    action_flag: str
    instrument_id: str


@dataclass(frozen=True)
class _ManagedOrderActionFieldSnapshot:
    """One read of caller-owned fields plus the normalized callback identity."""

    identity: _OrderActionIdentity
    user_id: str
    request_id_value: Any
    front_id_value: Any
    session_id_value: Any
    order_action_ref_value: Any


def _managed_order_action_field_snapshot(field: Any) -> _ManagedOrderActionFieldSnapshot:
    """Read every field used by managed validation exactly once."""

    raw = {
        name: _native_field_value(field, name, default)
        for name, default in (
            ("BrokerID", ""),
            ("InvestorID", ""),
            ("UserID", ""),
            ("OrderActionRef", ""),
            ("OrderRef", ""),
            ("RequestID", 0),
            ("FrontID", 0),
            ("SessionID", 0),
            ("ExchangeID", ""),
            ("OrderSysID", ""),
            ("ActionFlag", ""),
            ("InstrumentID", ""),
        )
    }
    identity = _OrderActionIdentity(
        broker_id=_native_text_value(raw["BrokerID"]),
        investor_id=_native_text_value(raw["InvestorID"]),
        order_action_ref=_native_text_value(raw["OrderActionRef"]),
        order_ref=_native_text_value(raw["OrderRef"]),
        field_request_id=_native_int_value(raw["RequestID"]),
        front_id=_native_int_value(raw["FrontID"]),
        session_id=_native_int_value(raw["SessionID"]),
        exchange_id=_native_text_value(raw["ExchangeID"]),
        order_sys_id=_native_text_value(raw["OrderSysID"]),
        action_flag=_native_text_value(raw["ActionFlag"]),
        instrument_id=_native_text_value(raw["InstrumentID"]),
    )
    return _ManagedOrderActionFieldSnapshot(
        identity=identity,
        user_id=_native_text_value(raw["UserID"]),
        request_id_value=raw["RequestID"],
        front_id_value=raw["FrontID"],
        session_id_value=raw["SessionID"],
        order_action_ref_value=raw["OrderActionRef"],
    )


def _order_action_identity(field: Any) -> _OrderActionIdentity:
    return _OrderActionIdentity(
        broker_id=_native_text_field(field, "BrokerID"),
        investor_id=_native_text_field(field, "InvestorID"),
        order_action_ref=_native_text_field(field, "OrderActionRef"),
        order_ref=_native_text_field(field, "OrderRef"),
        field_request_id=_native_int_field(field, "RequestID"),
        front_id=_native_int_field(field, "FrontID"),
        session_id=_native_int_field(field, "SessionID"),
        exchange_id=_native_text_field(field, "ExchangeID"),
        order_sys_id=_native_text_field(field, "OrderSysID"),
        action_flag=_native_text_field(field, "ActionFlag"),
        instrument_id=_native_text_field(field, "InstrumentID"),
    )


class _QueryRecordSnapshot(dict[str, Any]):
    """Detached CTP query row retaining legacy attribute-style reads."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _snapshot_query_record(record: Any) -> _QueryRecordSnapshot:
    if isinstance(record, dict):
        return _QueryRecordSnapshot(record)
    return _QueryRecordSnapshot(_snapshot_ctp_field(record))


def _rsp_error(rsp_info: Any) -> tuple[int | None, str]:
    if rsp_info is None:
        return None, ""
    try:
        error_id = int(getattr(rsp_info, "ErrorID", 0) or 0)
    except (TypeError, ValueError):
        error_id = -1
    return error_id, str(getattr(rsp_info, "ErrorMsg", "") or "")


def _query_filter_items(filters: Mapping[str, str] | None) -> tuple[tuple[str, str], ...]:
    if filters is None:
        return ()
    if not isinstance(filters, Mapping):
        raise TypeError("query request intent filters must be a mapping")
    if any(type(name) is not str or type(value) is not str for name, value in filters.items()):
        raise TypeError("query request intent filters must contain exact strings")
    return tuple(sorted(filters.items()))


def _read_native_query_filter_items(
    field: Any,
    request_intent_items: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    """Read back only intended filter fields from the populated native request.

    Missing getters, non-string wrapper results and any setter normalization
    reject the request before a native query API is called. Unset fields are
    not added to the returned evidence.
    """
    if field is None:
        raise TypeError("native query filter field is required")
    readback: list[tuple[str, str]] = []
    for name, intended_value in request_intent_items:
        try:
            actual_value = getattr(field, name)
        except Exception as exc:
            raise ValueError(f"native query filter getter unavailable:{name}") from exc
        if type(actual_value) is not str:
            raise TypeError(f"native query filter getter type invalid:{name}")
        if actual_value != intended_value:
            raise ValueError(f"native query filter readback mismatch:{name}")
        readback.append((name, actual_value))
    return tuple(readback)


def _query_parameter_items(
    parameters: Mapping[str, float] | None,
) -> tuple[tuple[str, float], ...]:
    """Validate typed numeric query inputs without mixing them into filters."""
    if parameters is None:
        return ()
    if not isinstance(parameters, Mapping):
        raise TypeError("query request intent parameters must be a mapping")
    if any(
        type(name) is not str
        or type(value) is not float
        or not math.isfinite(value)
        for name, value in parameters.items()
    ):
        raise TypeError("query request intent parameters must contain finite floats")
    return tuple(sorted(parameters.items()))


def _read_native_query_parameter_items(
    field: Any,
    request_intent_items: tuple[tuple[str, float], ...],
) -> tuple[tuple[str, float], ...]:
    """Read back numeric request parameters before submission, exactly typed."""
    if field is None:
        raise TypeError("native query parameter field is required")
    readback: list[tuple[str, float]] = []
    for name, intended_value in request_intent_items:
        try:
            actual_value = getattr(field, name)
        except Exception as exc:
            raise ValueError(f"native query parameter getter unavailable:{name}") from exc
        if type(actual_value) is not float or not math.isfinite(actual_value):
            raise TypeError(f"native query parameter getter type invalid:{name}")
        if actual_value != intended_value:
            raise ValueError(f"native query parameter readback mismatch:{name}")
        readback.append((name, actual_value))
    return tuple(readback)


@dataclass
class _QueryAccumulator:
    request_type: str
    request_id: int
    connection_generation: int
    account_fingerprint: str
    started_at_utc: datetime
    event: threading.Event = dataclass_field(default_factory=threading.Event)
    records: list[Any] = dataclass_field(default_factory=list)
    completed_at_utc: datetime | None = None
    is_last_seen: bool = False
    error_code: int | None = None
    error_message: str = ""
    timed_out: bool = False
    sealed: bool = False
    late_callback_count: int = 0
    unsupported: bool = False
    submit_code: int | None = None
    source_issuer: object | None = None
    request_intent_filters: tuple[tuple[str, str], ...] = ()
    request_filters: tuple[tuple[str, str], ...] = ()
    request_intent_parameters: tuple[tuple[str, float], ...] = ()
    request_parameters: tuple[tuple[str, float], ...] = ()
    explicit_request_filters: tuple[str, ...] = ()
    trading_day: str = ""
    broker_id: str = ""
    investor_id: str = ""
    started_monotonic: float = 0.0
    completed_monotonic: float | None = None
    source_records_sha256: str | None = None

    def result(self) -> QueryResult[Any]:
        complete = (
            self.sealed
            and self.is_last_seen
            and not self.timed_out
            and not self.unsupported
            and self.error_code in (None, 0)
        )
        result = QueryResult(
            request_type=self.request_type,
            request_id=self.request_id,
            connection_generation=self.connection_generation,
            account_fingerprint=self.account_fingerprint,
            started_at_utc=self.started_at_utc,
            completed_at_utc=self.completed_at_utc,
            is_last_seen=self.is_last_seen,
            error_code=self.error_code,
            error_message=self.error_message,
            timed_out=self.timed_out,
            complete=complete,
            records=tuple(self.records),
            late_callback_count=self.late_callback_count,
            unsupported=self.unsupported,
            submit_code=self.submit_code,
        )
        if self.source_issuer is None:
            return result
        return _attach_query_source(
            result,
            _new_query_source(
                issuer=self.source_issuer,
                request_type=self.request_type,
                request_id=self.request_id,
                account_fingerprint=self.account_fingerprint,
                connection_generation=self.connection_generation,
                trading_day=self.trading_day,
                broker_id=self.broker_id,
                investor_id=self.investor_id,
                request_intent_filters=self.request_intent_filters,
                started_at_utc=self.started_at_utc,
                completed_at_utc=self.completed_at_utc,
                started_monotonic=self.started_monotonic,
                completed_monotonic=self.completed_monotonic,
                records_sha256=self.source_records_sha256,
                request_filters=self.request_filters,
                request_intent_parameters=self.request_intent_parameters,
                request_parameters=self.request_parameters,
                explicit_request_filters=self.explicit_request_filters,
            ),
        )


# ===========================================================================
#  MdClient - 行情客户端
# ===========================================================================


class _MdSpi(CThostFtdcMdSpi):
    def __init__(self, client, native_api=None):
        super().__init__()
        self._c = client
        self._native_api = native_api

    def _is_current_locked(self) -> bool:
        if self._native_api is None:
            # Offline unit tests can construct an unbound SPI directly.
            return True
        return self._c._spi is self and self._c._api is self._native_api

    def _is_current(self) -> bool:
        with self._c._state_lock:
            return self._is_current_locked()

    def OnFrontConnected(self):
        with self._c._state_lock:
            if not self._is_current_locked():
                return
            self._c._connection_generation += 1
            self._c._connected = True
            self._c._loggedin = False
            self._c._clear_active_md_identity_locked()
            generation = self._c._connection_generation
            front = self._c._bound_front
            request_id = self._c._begin_md_login_request_locked(generation)
            field = CThostFtdcReqUserLoginField()
            field.BrokerID = self._c._bound_broker_id
            field.UserID = self._c._bound_user_id
            field.Password = self._c.password
            api = self._c._api
        # 连接代次是断线/重连的唯一权威标识，必须留痕，否则无人值守时断线不可见。
        _logger.info(
            "CTP market-data front connected (generation=%s, front=%s)", generation, front
        )
        if request_id is None:
            _logger.error(
                "CTP market-data login request ID space exhausted (generation=%s)", generation
            )
            return
        if api is not None:
            result = api.ReqUserLogin(field, request_id)
            if type(result) is int and result != 0:
                with self._c._state_lock:
                    if (
                        self._is_current_locked()
                        and self._c._login_request_id == request_id
                        and self._c._login_request_generation == generation
                    ):
                        self._c._login_request_pending = False
                        self._c._login_request_id = None
                        self._c._login_request_generation = None
                        self._c._loggedin = False
                        self._c._clear_active_md_identity_locked()
                _logger.warning(
                    "CTP market-data login request rejected "
                    "(generation=%s, request_id=%s, result=%s)",
                    generation,
                    request_id,
                    result,
                )

    def OnFrontDisconnected(self, nReason):
        with self._c._state_lock:
            if not self._is_current_locked():
                return
            self._c._connected = False
            self._c._loggedin = False
            self._c._clear_active_md_identity_locked()
            self._c._login_request_pending = False
            self._c._login_request_id = None
            self._c._login_request_generation = None
            generation = self._c._connection_generation
            callback = self._c.on_disconnect
        # 常见原因码：0x1001 网络读失败、0x2001 接收心跳超时、0x2003 收到错误报文。
        _logger.warning(
            "CTP market-data front disconnected (reason=%s, generation=%s)", nReason, generation
        )
        if callback is not None:
            callback(nReason)

    def OnRspUserLogin(self, pRspUserLogin, pRspInfo, nRequestID, bIsLast):
        from bt_api_ctp.md_identity import MdIdentityObservation

        subscribe = None
        callback = None
        error_callback = None
        error_info = None
        login_ok = False
        trading_day = ""
        pending = 0
        generation = None
        with self._c._state_lock:
            if not self._is_current_locked():
                return
            generation = self._c._connection_generation
            terminal = type(bIsLast) in (bool, int) and bIsLast == 1
            current_request = (
                type(nRequestID) is int
                and self._c._login_request_pending
                and self._c._login_request_id == nRequestID
                and self._c._login_request_generation == generation
            )
            if not terminal or not current_request:
                return
            self._c._login_request_pending = False
            error_id = getattr(pRspInfo, "ErrorID", None) if pRspInfo is not None else None
            if pRspInfo is not None and type(error_id) is int and error_id == 0:
                self._c._loggedin = True
                login_ok = True
                broker_id = self._source_identity_text(
                    getattr(pRspUserLogin, "BrokerID", None)
                )
                user_id = self._source_identity_text(getattr(pRspUserLogin, "UserID", None))
                trading_day = self._source_identity_text(
                    getattr(pRspUserLogin, "TradingDay", None)
                )
                self._c._active_md_identity = MdIdentityObservation(
                    front=self._c._bound_front,
                    broker_id=broker_id,
                    user_id=user_id,
                    connection_generation=generation,
                    request_id=nRequestID,
                    trading_day=trading_day,
                    authenticated=True,
                )
                self._c._active_md_identity_api = (
                    self._native_api if self._native_api is not None else self._c._api
                )
                self._c._active_md_identity_spi = self
                pending = len(self._c._pending_instruments)
                if self._c._pending_instruments and self._c.auto_resubscribe_on_login:
                    subscribe = (self._c._api, list(self._c._pending_instruments))
                callback = self._c.on_login
            else:
                self._c._loggedin = False
                self._c._clear_active_md_identity_locked()
                error_callback = self._c.on_error
                error_info = pRspInfo
        if login_ok:
            _logger.info(
                "CTP market-data login ok (generation=%s, trading_day=%s, pending=%d)",
                generation,
                trading_day,
                pending,
            )
        else:
            _logger.warning(
                "CTP market-data login failed (generation=%s, error_id=%s, error_msg=%s)",
                generation,
                getattr(pRspInfo, "ErrorID", None),
                getattr(pRspInfo, "ErrorMsg", ""),
            )
        if subscribe is not None and subscribe[0] is not None:
            subscribe[0].SubscribeMarketData(subscribe[1])
        if callback is not None:
            callback(pRspUserLogin)
        if error_callback is not None:
            error_callback(error_info)

    @staticmethod
    def _source_identity_text(value):
        """Keep only exact nonempty callback strings; never synthesize fields."""

        return value if type(value) is str and value else None

    def OnRtnDepthMarketData(self, pDepthMarketData):
        with self._c._state_lock:
            if not self._is_current_locked():
                return
            callback = self._c.on_tick
        if callback is not None:
            callback(pDepthMarketData)

    def OnRspSubMarketData(self, pSpecificInstrument, pRspInfo, nRequestID, bIsLast):
        with self._c._state_lock:
            if not self._is_current_locked():
                return
            callback = self._c.on_subscribe
        if callback is not None:
            callback(pSpecificInstrument, pRspInfo)

    def OnRspError(self, pRspInfo, nRequestID, bIsLast):
        with self._c._state_lock:
            if not self._is_current_locked():
                return
            callback = self._c.on_error
        if callback is not None:
            callback(pRspInfo)


class MdClient:
    """行情客户端封装

    Args:
        front: 前置地址，如 "tcp://182.254.243.31:30011"
        broker_id: 经纪商代码
        user_id: 投资者代码
        password: 密码
    """

    def __init__(self, front, broker_id, user_id, password):
        self.front = front
        self.broker_id = broker_id
        self.user_id = user_id
        self.password = password
        # Constructor-bound identity is independent of mutable legacy fields.
        self.__bound_front = front if type(front) is str else None
        self.__bound_broker_id = broker_id if type(broker_id) is str else None
        self.__bound_user_id = user_id if type(user_id) is str else None

        self.on_tick = None  # callback(CThostFtdcDepthMarketDataField)
        self.on_login = None  # callback(CThostFtdcRspUserLoginField)
        self.on_error = None  # callback(CThostFtdcRspInfoField)
        # callback(CThostFtdcSpecificInstrumentField, CThostFtdcRspInfoField)
        self.on_subscribe = None
        # callback(nReason) - 前置断开通知，用于把断线时间窗写进完整性报告
        self.on_disconnect = None

        self._connected = False
        self._loggedin = False
        self._pending_instruments = []
        # True = 登录回调内直接全量重订阅（历史行为，向后兼容）；
        # False = 调用方自行异步分批重订阅，避免阻塞 CTP 原生回调线程。
        self.auto_resubscribe_on_login = True
        self._connection_generation = 0
        self._login_request_counter = 0
        self._login_request_id = None
        self._login_request_generation = None
        self._login_request_pending = False
        self._active_md_identity = None
        self._active_md_identity_api = None
        self._active_md_identity_spi = None
        self._api = None
        self._spi = None
        self._native_lifecycle_state: _CtpNativeLifecycleState | None = None
        self._last_stop_lifecycle_state: _CtpNativeLifecycleState | None = None
        self._thread = None
        self._join_active = False
        self._native_init_started = False
        # Native startup calls must run without ``_state_lock`` because a CTP
        # registration call may synchronously wait for a callback thread that
        # also needs this lock.  Keep a per-API in-flight count so stop can
        # detach/release only after the call has returned.
        self._startup_native_call_refs: dict[int, int] = {}
        self._deferred_startup_cleanups: dict[int, tuple[Any, Any, bool]] = {}
        self._native_join_tracker = _CtpNativeJoinTracker()
        self._pending_native_join_api_ids: set[int] = set()
        self._last_stopped_native_api = None
        self._last_stopped_connection_generation = 0
        self._last_stop_join_required = False
        self._last_stop_join_thread: threading.Thread | None = None
        self._last_stop_join_tracker: _CtpNativeJoinTracker | None = None
        self._lifecycle_generation = 0
        self._starting_generation: int | None = None
        self._startup_cancel_event = threading.Event()
        self._state_lock = threading.RLock()

    @property
    def _bound_front(self):
        return self.__bound_front

    @property
    def _bound_broker_id(self):
        return self.__bound_broker_id

    @property
    def _bound_user_id(self):
        return self.__bound_user_id

    @property
    def active_md_identity(self):
        """Atomic current login fact, not a feed/profile proof."""

        from bt_api_ctp.md_identity import MdIdentityObservation

        with self._state_lock:
            identity = self._active_md_identity
            if (
                identity is None
                or type(identity) is not MdIdentityObservation
                or not self._connected
                or not self._loggedin
                or self._login_request_pending
                or type(self._login_request_id) is not int
                or type(self._login_request_generation) is not int
                or type(self._connection_generation) is not int
                or identity.request_id != self._login_request_id
                or identity.connection_generation != self._login_request_generation
                or identity.connection_generation != self._connection_generation
                or identity.front != self._bound_front
                or identity.authenticated is not True
                or self._active_md_identity_api is not self._api
                or self._active_md_identity_spi is not self._spi
            ):
                return None
            return identity

    def _begin_md_login_request_locked(self, generation):
        """Record the exact request/generation pair before sending login."""

        if self._login_request_counter >= 2_147_483_647:
            self._login_request_id = None
            self._login_request_generation = None
            self._login_request_pending = False
            self._loggedin = False
            self._clear_active_md_identity_locked()
            return None
        self._login_request_counter += 1
        self._login_request_id = self._login_request_counter
        self._login_request_generation = generation
        self._login_request_pending = True
        return self._login_request_id

    def _clear_active_md_identity_locked(self):
        self._active_md_identity = None
        self._active_md_identity_api = None
        self._active_md_identity_spi = None

    def _reserve_start_generation(self) -> int:
        """Reserve one startup generation before creating the native API."""

        with self._state_lock:
            if self._pending_native_join_api_ids:
                raise RuntimeError("ctp_md_client_native_join_pending")
            if self._api is not None or self._starting_generation is not None:
                raise RuntimeError("ctp_md_client_already_started")
            self._lifecycle_generation += 1
            generation = self._lifecycle_generation
            self._starting_generation = generation
            self._startup_cancel_event.clear()
            self._connected = False
            self._loggedin = False
            self._clear_active_md_identity_locked()
            self._login_request_id = None
            self._login_request_generation = None
            self._login_request_pending = False
            return generation

    def _clear_start_reservation(self, generation: int) -> None:
        with self._state_lock:
            if self._starting_generation == generation:
                self._starting_generation = None

    def _is_start_current_locked(self, api: Any, spi: Any, generation: int) -> bool:
        return (
            self._lifecycle_generation == generation
            and self._starting_generation == generation
            and self._api is api
            and self._spi is spi
            and not self._startup_cancel_event.is_set()
        )

    def _run_startup_call(
        self,
        api: Any,
        spi: Any,
        generation: int,
        callback: Callable[[], Any],
        *,
        starts_native_thread: bool = False,
        lifecycle_operation: Literal["register_spi", "init"] | None = None,
    ) -> tuple[bool, bool]:
        """Run one native startup call outside the lifecycle lock.

        The generation check and in-flight reference are changed atomically,
        but vendor code runs unlocked so a synchronous callback can take the
        same lifecycle lock.  A concurrent stop records deferred cleanup and
        cancels all subsequent startup calls; the final reference performs
        that cleanup after the active native call returns.
        """
        with self._state_lock:
            if not self._is_start_current_locked(api, spi, generation):
                return False, False
            if starts_native_thread:
                # A re-entrant stop from Init() must treat the API as live
                # before the vendor is allowed to create its callback thread.
                self._native_init_started = True
                self._join_active = True
            # stop() sets its event before it waits for this lock.  Repeat the
            # precondition immediately before entering native code so a stop
            # that arrived during the preceding bookkeeping cancels this step.
            if not self._is_start_current_locked(api, spi, generation):
                if starts_native_thread:
                    self._native_init_started = False
                    self._join_active = False
                return False, False
            api_id = id(api)
            self._startup_native_call_refs[api_id] = (
                self._startup_native_call_refs.get(api_id, 0) + 1
            )

        callback_error: BaseException | None = None
        try:
            if lifecycle_operation is None:
                callback()
            else:
                _record_ctp_native_call(api, lifecycle_operation, callback)
        except BaseException as exc:
            callback_error = exc
            raise
        finally:
            deferred_cleanup = None
            with self._state_lock:
                ref_count = self._startup_native_call_refs.get(api_id, 0)
                if ref_count <= 1:
                    self._startup_native_call_refs.pop(api_id, None)
                    deferred_cleanup = self._deferred_startup_cleanups.pop(api_id, None)
                else:
                    self._startup_native_call_refs[api_id] = ref_count - 1
                active_after_call = self._is_start_current_locked(api, spi, generation)

            if deferred_cleanup is not None:
                try:
                    self._complete_deferred_startup_cleanup(*deferred_cleanup)
                except BaseException:
                    # Preserve the original startup exception.  The cleanup
                    # path has already retained/poisoned the native API where
                    # possible, so replacing the vendor exception would lose
                    # the failure that triggered the fail-closed path.
                    if callback_error is None:
                        raise
                    _logger.exception(
                        "CTP MD deferred startup cleanup failed while preserving startup error"
                    )

        return True, active_after_call

    def _complete_deferred_startup_cleanup(
        self, api: Any, spi: Any, native_may_be_live: bool
    ) -> None:
        """Finish stop cleanup after the last in-flight startup call returns."""

        if not native_may_be_live:
            _release_ctp_native_api_immediately(
                api,
                spi,
                state_lock=self._state_lock,
                pending_api_ids=self._pending_native_join_api_ids,
            )
            return

        _retain_live_ctp_native_session(api, spi, None)
        detach_error: BaseException | None = None
        try:
            _detach_ctp_native_spi_once(api)
        except BaseException as exc:
            detach_error = exc

        try:
            if _ctp_native_join_claimed(api):
                if _ctp_native_join_returned(api):
                    if _release_retired_ctp_native_session_after_join(api):
                        with self._state_lock:
                            self._pending_native_join_api_ids.discard(id(api))
            else:
                self._start_join_observer(api)
        except BaseException:
            if detach_error is None:
                raise
            _logger.exception(
                "CTP MD Join observer setup failed after deferred callback detach failure"
            )

        if detach_error is not None:
            raise detach_error

    def _abort_startup(
        self,
        api: Any,
        spi: Any,
        generation: int,
        *,
        native_init_may_be_live: bool = False,
    ) -> bool:
        """Clean up a failed startup only while this generation owns it."""

        release_now = False
        observe_join = False
        with self._state_lock:
            if not self._is_start_current_locked(api, spi, generation):
                return False
            native_live = native_init_may_be_live or self._native_init_started
            if native_live:
                self._pending_native_join_api_ids.add(id(api))
                _retain_live_ctp_native_session(api, spi, self._thread)
                observe_join = True
            else:
                self._pending_native_join_api_ids.add(id(api))
                release_now = True
                if self._native_lifecycle_state is not None:
                    self._native_lifecycle_state.mark_join_not_required()
            self._last_stopped_native_api = api
            self._last_stop_lifecycle_state = self._native_lifecycle_state
            self._last_stopped_connection_generation = self._connection_generation
            self._last_stop_join_required = native_live
            self._last_stop_join_thread = self._thread
            self._last_stop_join_tracker = self._native_join_tracker
            self._api = None
            self._spi = None
            self._thread = None
            self._join_active = False
            self._native_init_started = False
            self._starting_generation = None
            self._lifecycle_generation += 1
            self._connected = False
            self._loggedin = False
            self._clear_active_md_identity_locked()
            self._login_request_id = None
            self._login_request_generation = None
            self._login_request_pending = False

        if observe_join:
            detach_error: BaseException | None = None
            try:
                _detach_ctp_native_spi_once(api)
            except BaseException as exc:
                detach_error = exc
            try:
                self._start_join_observer(api)
            except BaseException:
                if detach_error is None:
                    raise
                _logger.exception(
                    "CTP MD Join observer setup failed after startup detach failure"
                )
            if detach_error is not None:
                raise detach_error
        elif release_now:
            _release_ctp_native_api_immediately(
                api,
                spi,
                state_lock=self._state_lock,
                pending_api_ids=self._pending_native_join_api_ids,
            )
        return True

    def _join_native_api(self, api: Any, *, _already_claimed: bool = False) -> None:
        if not _already_claimed and not _claim_ctp_native_join(api):
            return
        tracker = self._native_join_tracker
        lifecycle_state = _ctp_native_lifecycle_state_for_api(api)
        tracker.begin()
        if lifecycle_state is not None:
            lifecycle_state.begin("join")
        join_returned = False
        try:
            join_result = api.Join()
            join_returned = True
            if lifecycle_state is not None and not lifecycle_state.returned("join", join_result):
                tracker.failed(TypeError("ctp_native_join_unexpected_return_type"))
                raise TypeError("ctp_native_join_unexpected_return_type")
            tracker.returned(join_result)
            _mark_ctp_native_join_returned(api)
        except BaseException as exc:
            if lifecycle_state is not None and lifecycle_state.join_state == "pending":
                lifecycle_state.failed("join", exc)
            tracker.failed(exc)
            raise
        finally:
            if join_returned:
                with self._state_lock:
                    if self._api is api:
                        self._join_active = False
                        self._native_init_started = False
                    if self._thread is threading.current_thread():
                        self._thread = None
                retired_session_released = _release_retired_ctp_native_session_after_join(api)
                if retired_session_released:
                    with self._state_lock:
                        self._pending_native_join_api_ids.discard(id(api))

    def wait_native_join(self, timeout: float) -> CtpNativeJoinWaitResult:
        """Wait at most ``timeout`` seconds for the latest native Join call.

        ``timeout`` must be finite and between zero and 60 seconds. The typed
        result reports whether Join returned or raised; a returned Join does
        not certify a successful ``Release`` or an empty process.
        """

        return self._native_join_tracker.wait(timeout)

    def _start_join_observer(self, api: Any) -> bool:
        """Start one Join observer for either the current or retired session."""

        thread = threading.Thread(
            target=self._join_native_api,
            args=(api,),
            kwargs={"_already_claimed": True},
            daemon=True,
        )
        with self._state_lock:
            if self._api is api:
                if self._thread is not None or not _claim_ctp_native_join(api):
                    return False
                self._thread = thread
                self._join_active = True
            elif not _set_retired_ctp_native_session_join_thread(api, thread):
                return False
            elif self._last_stopped_native_api is api:
                self._last_stop_join_thread = thread
        thread.start()
        return True

    def subscribe(self, instruments):
        """订阅合约列表（可在 start 前或后调用）"""
        with self._state_lock:
            self._pending_instruments = list(instruments)
            api = self._api if self._loggedin else None
            pending_instruments = list(self._pending_instruments)
        if api is not None:
            api.SubscribeMarketData(pending_instruments)

    def subscribe_batched(
        self, instruments, *, batch_size=100, interval_sec=0.1, should_stop=None
    ):
        """分批订阅合约列表（可在 start 前或后调用）

        与 :meth:`subscribe` 的差异：

        - ``_pending_instruments`` 始终保存 **全量** 合约，因此断线重连后
          ``OnRspUserLogin`` 仍会重订阅全部合约，不会漏订；
        - 已登录时按 ``batch_size`` 分批提交，避免单次订阅过大；
        - 未登录时只记录待订阅全集，登录成功后统一订阅。

        Args:
            instruments: 合约代码列表
            batch_size: 每批订阅数量，必须 >= 1
            interval_sec: 批次之间的间隔秒数，0 表示不等待
            should_stop: 可选谓词，每批提交前调用；返回 True 时立即停止。
                供调用方在退出/关闭时中断一次长时间分批（例如重连后的全量
                重订阅），避免客户端已经 ``stop()`` 而本循环仍在调用原生接口。

        Returns:
            实际提交的批次数；未登录/无待订阅/被 ``should_stop`` 提前终止时为 0。
        """
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        pending = list(instruments)
        with self._state_lock:
            self._pending_instruments = pending
            api = self._api if self._loggedin else None
        if api is None or not pending:
            return 0
        submitted = 0
        for start in range(0, len(pending), batch_size):
            if should_stop is not None and should_stop():
                return submitted
            api.SubscribeMarketData(pending[start : start + batch_size])
            submitted += 1
            if interval_sec > 0 and start + batch_size < len(pending):
                time.sleep(interval_sec)
        return submitted

    def start(self, block=True):
        """启动连接

        Args:
            block: True=阻塞直到断开, False=后台线程运行
        """
        _check_native_module()
        generation = self._reserve_start_generation()
        flow = _flow_dir(f"md_{self._bound_broker_id}_{self._bound_user_id}")
        try:
            api = CThostFtdcMdApi.CreateFtdcMdApi(flow)
            _register_ctp_native_api(api)
        except BaseException:
            self._clear_start_reservation(generation)
            raise
        spi = _MdSpi(self, api)
        lifecycle_state = _bind_ctp_native_lifecycle_state(
            self,
            client_kind="md",
            session_generation=generation,
            api=api,
            spi=spi,
        )
        with self._state_lock:
            if (
                self._starting_generation != generation
                or self._lifecycle_generation != generation
                or self._startup_cancel_event.is_set()
            ):
                cancelled_before_registration = True
            else:
                cancelled_before_registration = False
                self._api = api
                self._spi = spi
                self._native_lifecycle_state = lifecycle_state
                self._native_init_started = False
                self._join_active = False
                self._native_join_tracker = _CtpNativeJoinTracker()
        if cancelled_before_registration:
            _release_ctp_native_api_immediately(
                api,
                spi,
                state_lock=self._state_lock,
                pending_api_ids=self._pending_native_join_api_ids,
            )
            return

        init_invoked = False

        def init_native_api() -> None:
            nonlocal init_invoked
            init_invoked = True
            api.Init()

        try:
            invoked, active = self._run_startup_call(
                api,
                spi,
                generation,
                lambda: api.RegisterSpi(spi),
                lifecycle_operation="register_spi",
            )
            if not invoked or not active:
                self._abort_startup(api, spi, generation)
                return
            invoked, active = self._run_startup_call(
                api, spi, generation, lambda: api.RegisterFront(self._bound_front)
            )
            if not invoked or not active:
                self._abort_startup(api, spi, generation)
                return
            invoked, active = self._run_startup_call(
                api,
                spi,
                generation,
                init_native_api,
                starts_native_thread=True,
                lifecycle_operation="init",
            )
            if not invoked:
                self._abort_startup(api, spi, generation)
                return
            if not active:
                # stop() detached this API while Init was running.  It is
                # retained already; attach a Join observer so the registry is
                # released when the native thread exits.
                self._start_join_observer(api)
                return
        except BaseException:
            # Init is a void vendor call, but if a binding raises after it was
            # entered, fail safe and retain until Join proves native shutdown.
            try:
                handled = self._abort_startup(
                    api,
                    spi,
                    generation,
                    native_init_may_be_live=init_invoked,
                )
                if init_invoked and not handled:
                    # A concurrent stop may have set the cancellation fence
                    # while Init raised.  Attach the observer whether it
                    # already retained the session or is about to do so.
                    self._start_join_observer(api)
            except BaseException:
                _logger.exception(
                    "CTP MD startup cleanup failed while preserving startup error"
                )
            raise

        if block:
            with self._state_lock:
                current = self._is_start_current_locked(api, spi, generation)
            if not current:
                self._start_join_observer(api)
                return
            try:
                self._join_native_api(api)
            except KeyboardInterrupt:
                pass
            finally:
                self.stop()
            return

        self._start_join_observer(api)

    def wait_ready(self, timeout=15):
        """等待登录就绪"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._state_lock:
                if self._loggedin:
                    return True
            time.sleep(0.2)
        with self._state_lock:
            return self._loggedin

    def _stop_native_session(self, *, expected_api: Any = _NO_EXPECTED_NATIVE_API) -> bool:
        """Stop a CTP market-data session without freeing a live SWIG director.

        An in-flight startup call is allowed to return before callback
        unregistration or Release. If Init may have started native threads,
        retain the API and director until the sole Join returns; the Join
        observer then releases the retained session.
        """

        # Set this before waiting for a native registration call's lock.  It
        # is the post-call fence that prevents RegisterFront/Init from running
        # when stop races RegisterSpi on another thread.
        if expected_api is _NO_EXPECTED_NATIVE_API:
            self._startup_cancel_event.set()
        with self._state_lock:
            api = self._api
            if expected_api is not _NO_EXPECTED_NATIVE_API and (
                api is None or api is not expected_api
            ):
                return False
            if expected_api is not _NO_EXPECTED_NATIVE_API:
                self._startup_cancel_event.set()
            # A stop issued while CreateFtdc* is still running must cancel the
            # reserved generation before start() can register it.
            self._lifecycle_generation += 1
            self._starting_generation = None
            self._loggedin = False
            self._connected = False
            self._clear_active_md_identity_locked()
            self._login_request_id = None
            self._login_request_generation = None
            self._login_request_pending = False
            spi = self._spi
            join_thread = self._thread
            native_may_be_live = self._native_init_started or self._join_active
            join_active = native_may_be_live and (
                self._join_active or (join_thread is not None and join_thread.is_alive())
            )
            if api is None:
                return False
            join_claimed = _ctp_native_join_claimed(api)
            join_required = bool(join_active or join_claimed)
            if not join_required and self._native_lifecycle_state is not None:
                self._native_lifecycle_state.mark_join_not_required()
            self._last_stopped_native_api = api
            self._last_stop_lifecycle_state = self._native_lifecycle_state
            self._last_stopped_connection_generation = self._connection_generation
            self._last_stop_join_required = join_required
            self._last_stop_join_thread = join_thread
            self._last_stop_join_tracker = self._native_join_tracker
            if join_active or join_claimed:
                self._pending_native_join_api_ids.add(id(api))
                _retain_live_ctp_native_session(api, spi, join_thread)
            else:
                self._pending_native_join_api_ids.add(id(api))
            self._api = None
            self._spi = None
            self._thread = None
            self._join_active = False
            self._native_init_started = False

            # A native startup call may still be inside vendor code.  Keep the
            # API/SPI alive and defer both callback detachment and Release
            # until that call returns; releasing concurrently with Init is
            # unsafe, and detaching concurrently with RegisterSpi can race the
            # vendor's own callback registration.
            startup_call_active = self._startup_native_call_refs.get(id(api), 0) > 0
            if startup_call_active:
                prior = self._deferred_startup_cleanups.get(id(api))
                self._deferred_startup_cleanups[id(api)] = (
                    api,
                    spi,
                    native_may_be_live or bool(prior and prior[2]),
                )
                if native_may_be_live:
                    _retain_live_ctp_native_session(api, spi, join_thread)

        if startup_call_active:
            return True

        if join_active:
            # RegisterSpi(None) is the vendor's documented callback
            # registration API; retaining ``spi`` above also protects a
            # callback already in flight while the registration is changed.
            with suppress(Exception):
                _detach_ctp_native_spi_once(api)
            return True

        if join_claimed:
            with suppress(Exception):
                _detach_ctp_native_spi_once(api)
            if _ctp_native_join_returned(api):
                if _release_retired_ctp_native_session_after_join(api):
                    with self._state_lock:
                        self._pending_native_join_api_ids.discard(id(api))
            return True

        _release_ctp_native_api_immediately(
            api,
            spi,
            state_lock=self._state_lock,
            pending_api_ids=self._pending_native_join_api_ids,
        )
        return True

    def stop(self):
        self._stop_native_session()

    def stop_and_wait(self, timeout: float = 2.0) -> CtpNativeStopReceipt:
        """Stop this market-data API and return a bounded lifecycle receipt."""

        return _make_ctp_native_stop_receipt(
            self,
            timeout,
            lock=self._state_lock,
            api_attribute="_api",
        )

    @property
    def native_lifecycle_receipt(self) -> CtpNativeLifecycleReceipt | None:
        """Snapshot the current exact API/SPI teardown evidence without waiting."""

        with self._state_lock:
            state = self._native_lifecycle_state
            if state is None or (self._api is not None and state.api is not self._api):
                state = self._last_stop_lifecycle_state
            connection_generation = self._connection_generation
            thread = self._thread or self._last_stop_join_thread
        if state is None:
            return None
        return state.snapshot(
            connection_generation=connection_generation,
            timed_out=False,
            thread_alive=thread.is_alive() if thread is not None else False,
        )

    @property
    def is_ready(self):
        with self._state_lock:
            return self._connected and self._loggedin

    @property
    def connection_generation(self):
        with self._state_lock:
            return self._connection_generation


# ===========================================================================
#  TraderClient - 交易客户端
# ===========================================================================


def _fence_trader_spi_callback(callback):
    @wraps(callback)
    def guarded(self, *args, **kwargs):
        client = self._c
        with client._query_state_lock:
            client._callback_inflight_refs += 1
            current = self._is_current_locked()
        try:
            if not current:
                return None
            # Callback bodies take the state lock only while mutating SDK
            # state. User callbacks may synchronously start a typed query.
            return callback(self, *args, **kwargs)
        finally:
            with client._query_state_lock:
                client._callback_inflight_refs = max(0, client._callback_inflight_refs - 1)
                client._maybe_finish_deferred_native_release_locked()

    return guarded


@dataclass(frozen=True)
class _TraderLoginIdentityObservation:
    """Fenced native identity accepted for one login request and generation."""

    _seal: object
    broker_id: str
    user_id: str
    trading_day: str
    connection_generation: int
    request_id: int


@dataclass
class _TraderCallbackIngressState:
    """Process-local side of a durable, opt-in Trader callback owner."""

    owner_handle: Any
    owner_intent_id: str
    append_sink: Any
    session_binder: Callable[..., Any]
    command_binding_verifier: Callable[..., Any]
    poison_sink: Callable[..., Any] | None = None
    phase: str = "PRE_START"
    sequence: int = 0
    prelogin_front_seen: bool = False
    active_session: Any = None
    login_bind_pending: bool = False
    pending_login_callback: tuple[Callable[..., Any], Any] | None = None
    poisoned: bool = False
    poison_reason: str | None = None
    native_call_refs: int = 0
    callback_refs: int = 0
    command_lease: Any = None
    current_source_tags: tuple[str, str, str, str, int, int] | None = None
    current_source_tags_object: Any = None
    used_command_ids: set[str] = dataclass_field(default_factory=set)
    retired_sources: list[tuple[Any, Any]] = dataclass_field(default_factory=list)


@dataclass(frozen=True)
class CtpManagedNativeCallLeaseV2:
    """Opaque one-shot pin for a V2 Store-claimed managed native request."""

    _seal: object
    _owner_handle: Any
    _binding: Any
    _api: Any
    _spi: Any
    _active_session: Any
    _source_tags: tuple[str, str, str, str, int, int]
    _method_name: str
    _nonce: str
    _binding_payload_json: str
    _logical_request_payload_json: str
    _native_request_payload_json: str


_CTP_MANAGED_NATIVE_CALL_LEASE_SEAL = object()
_CTP_MANAGED_BINDING_PAYLOAD_KEYS = frozenset(
    {
        "binding_type",
        "owner_intent_id",
        "account_key",
        "scope_key",
        "command_id",
        "operation",
        "trading_day",
        "request_payload_json",
        "request_payload_sha256",
        "native_request_payload_json",
        "native_request_payload_sha256",
        "reservation_managed_intent_id",
        "managed_action_id",
        "runtime_order_id",
        "order_ref",
        "native_request_id",
        "native_action_ref",
        "cancel_target_order_ref",
        "cancel_target_exchange_id",
        "cancel_target_order_sys_id",
        "cancel_target_front_id",
        "cancel_target_session_id",
        "session_binding_sha256",
        "session_generation_id",
        "dispatch_front_id",
        "dispatch_session_id",
        "writer_owner_id",
        "writer_fencing_token",
        "expires_at_ns",
    }
)
_CTP_MANAGED_SUBMIT_REQUIRED_FIELDS = frozenset(
    {
        "InstrumentID",
        "OrderRef",
        "Direction",
        "CombOffsetFlag",
        "CombHedgeFlag",
        "OrderPriceType",
        "LimitPrice",
        "VolumeTotalOriginal",
        "TimeCondition",
        "ExchangeID",
    }
)
_CTP_MANAGED_SUBMIT_OPTIONAL_FIELDS = frozenset(
    {
        "BrokerID",
        "InvestorID",
        "UserID",
        "GTDDate",
        "VolumeCondition",
        "MinVolume",
        "ContingentCondition",
        "StopPrice",
        "ForceCloseReason",
        "IsAutoSuspend",
        "UserForceClose",
        "IsSwapOrder",
        "BusinessUnit",
        "InvestUnitID",
        "AccountID",
        "RequestID",
    }
)
_CTP_MANAGED_CANCEL_REQUIRED_FIELDS = frozenset(
    {
        "InstrumentID",
        "OrderRef",
        "ExchangeID",
        "OrderSysID",
        "FrontID",
        "SessionID",
        "ActionFlag",
        "LimitPrice",
        "VolumeChange",
    }
)
_CTP_MANAGED_CANCEL_OPTIONAL_FIELDS = frozenset(
    {
        "BrokerID",
        "InvestorID",
        "UserID",
        "InvestUnitID",
        "AccountID",
        "RequestID",
        "OrderActionRef",
    }
)
_CTP_MANAGED_PRICE_FIELDS = frozenset({"LimitPrice", "StopPrice"})
_CTP_MANAGED_INTEGER_FIELDS = frozenset(
    {
        "FrontID",
        "SessionID",
        "RequestID",
        "OrderActionRef",
        "VolumeTotalOriginal",
        "MinVolume",
        "IsAutoSuspend",
        "UserForceClose",
        "IsSwapOrder",
        "VolumeChange",
    }
)
_CTP_INGRESS_SAFE_REQUEST_METHODS = frozenset(
    {
        "ReqAuthenticate",
        "ReqUserLogin",
        "ReqQryTradingAccount",
        "ReqQryInvestorPosition",
        "ReqQryOrder",
        "ReqQryTrade",
        "ReqQryInstrument",
        "ReqQryInstrumentMarginRate",
        "ReqQryInstrumentCommissionRate",
        "ReqQryOptionInstrTradeCost",
        "ReqQryOptionInstrCommRate",
        "ReqQryDepthMarketData",
        "ReqQrySettlementInfoConfirm",
        "ReqSettlementInfoConfirm",
    }
)


def _managed_native_binding_payload(
    binding: Any, owner_intent_id: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Validate the logical and Store-generated native payload of a V2 binding."""

    if type(binding).__name__ != "CtpManagedNativeCallBindingV2":
        raise CtpExecutionGateError("ctp_managed_native_binding_untyped")
    to_payload = getattr(binding, "to_payload", None)
    if not callable(to_payload):
        raise CtpExecutionGateError("ctp_managed_native_binding_untyped")
    try:
        envelope = to_payload()
    except Exception as exc:
        raise CtpExecutionGateError("ctp_managed_native_binding_unreadable") from exc
    if type(envelope) is not dict or set(envelope) != _CTP_MANAGED_BINDING_PAYLOAD_KEYS:
        raise CtpExecutionGateError("ctp_managed_native_binding_schema_invalid")
    if (
        envelope.get("binding_type") != "ctp_managed_native_call_binding.v2"
        or envelope.get("owner_intent_id") != owner_intent_id
        or envelope.get("operation") not in {"SUBMIT", "CANCEL"}
    ):
        raise CtpExecutionGateError("ctp_managed_native_binding_identity_invalid")
    if type(envelope.get("managed_action_id")) is not str or not envelope[
        "managed_action_id"
    ].strip():
        raise CtpExecutionGateError("ctp_managed_native_binding_action_invalid")
    for name in (
        "owner_intent_id",
        "account_key",
        "scope_key",
        "command_id",
        "trading_day",
        "request_payload_json",
        "request_payload_sha256",
        "native_request_payload_json",
        "native_request_payload_sha256",
        "reservation_managed_intent_id",
        "managed_action_id",
        "runtime_order_id",
        "order_ref",
        "session_binding_sha256",
        "session_generation_id",
        "writer_owner_id",
    ):
        value = envelope.get(name)
        if type(value) is not str or not value or value != value.strip():
            raise CtpExecutionGateError("ctp_managed_native_binding_text_invalid")
    for name in (
        "native_request_id",
        "dispatch_front_id",
        "dispatch_session_id",
        "writer_fencing_token",
        "expires_at_ns",
    ):
        if type(envelope.get(name)) is not int or envelope[name] <= 0:
            raise CtpExecutionGateError("ctp_managed_native_binding_integer_invalid")
    if envelope["native_request_id"] > 2_147_483_647:
        raise CtpExecutionGateError("ctp_managed_native_binding_integer_invalid")

    def read_canonical_payload(text_key: str, digest_key: str) -> dict[str, Any]:
        digest = envelope[digest_key]
        if type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest, re.ASCII) is None:
            raise CtpExecutionGateError("ctp_managed_native_binding_digest_invalid")
        payload_text = envelope[text_key]
        try:
            payload = json.loads(payload_text)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CtpExecutionGateError("ctp_managed_native_request_payload_invalid") from exc
        if type(payload) is not dict or any(type(key) is not str for key in payload):
            raise CtpExecutionGateError("ctp_managed_native_request_payload_invalid")
        canonical_payload = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        if (
            canonical_payload != payload_text
            or hashlib.sha256(payload_text.encode("utf-8")).hexdigest() != digest
        ):
            raise CtpExecutionGateError("ctp_managed_native_request_payload_digest_mismatch")
        return payload

    payload = read_canonical_payload("request_payload_json", "request_payload_sha256")
    native_payload = read_canonical_payload(
        "native_request_payload_json", "native_request_payload_sha256"
    )

    if envelope["operation"] == "SUBMIT":
        allowed = _CTP_MANAGED_SUBMIT_REQUIRED_FIELDS | _CTP_MANAGED_SUBMIT_OPTIONAL_FIELDS
        required = _CTP_MANAGED_SUBMIT_REQUIRED_FIELDS
    else:
        allowed = _CTP_MANAGED_CANCEL_REQUIRED_FIELDS | _CTP_MANAGED_CANCEL_OPTIONAL_FIELDS
        required = _CTP_MANAGED_CANCEL_REQUIRED_FIELDS
    if not required.issubset(payload) or set(payload) - allowed:
        raise CtpExecutionGateError("ctp_managed_native_request_payload_fields_invalid")
    if "OrderActionRef" in payload:
        raise CtpExecutionGateError("ctp_managed_native_logical_action_ref_forbidden")
    if envelope["operation"] == "CANCEL":
        action_ref = envelope.get("native_action_ref")
        if type(action_ref) is not int or not (1 <= action_ref <= 2_147_483_647):
            raise CtpExecutionGateError("ctp_managed_native_binding_action_ref_invalid")
        expected_native_payload = dict(payload)
        expected_native_payload["OrderActionRef"] = action_ref
        expected_native_text = json.dumps(
            expected_native_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        if envelope["native_request_payload_json"] != expected_native_text:
            raise CtpExecutionGateError("ctp_managed_native_payload_action_ref_mismatch")
        target_fields = {
            "OrderRef": envelope.get("cancel_target_order_ref"),
            "ExchangeID": envelope.get("cancel_target_exchange_id"),
            "OrderSysID": envelope.get("cancel_target_order_sys_id"),
            "FrontID": envelope.get("cancel_target_front_id"),
            "SessionID": envelope.get("cancel_target_session_id"),
            "ActionFlag": "0",
        }
        if (
            type(envelope.get("cancel_target_front_id")) is not int
            or envelope["cancel_target_front_id"] <= 0
            or type(envelope.get("cancel_target_session_id")) is not int
            or envelope["cancel_target_session_id"] <= 0
            or envelope.get("order_ref") != envelope.get("cancel_target_order_ref")
            or any(
                type(envelope.get(name)) is not str
                or not envelope[name]
                or envelope[name] != envelope[name].strip()
                or not envelope[name].isascii()
                for name in (
                    "cancel_target_order_ref",
                    "cancel_target_exchange_id",
                    "cancel_target_order_sys_id",
                )
            )
            or any(
                _managed_payload_scalar(key, payload.get(key))
                != _managed_payload_scalar(key, value)
                for key, value in target_fields.items()
            )
            or (
                "RequestID" in payload
                and (
                    type(payload["RequestID"]) is not int
                    or payload["RequestID"] != envelope["native_request_id"]
                )
            )
            or payload.get("LimitPrice") not in (0, 0.0)
            or payload.get("VolumeChange") != 0
            or type(payload.get("VolumeChange")) is not int
        ):
            raise CtpExecutionGateError("ctp_managed_native_cancel_binding_mismatch")
    else:
        if envelope.get("native_action_ref") is not None:
            raise CtpExecutionGateError("ctp_managed_native_submit_binding_mismatch")
        if envelope["native_request_payload_json"] != envelope["request_payload_json"]:
            raise CtpExecutionGateError("ctp_managed_native_submit_payload_mismatch")
        if (
            envelope.get("order_ref") != payload.get("OrderRef")
            or any(
                envelope.get(name) is not None
                for name in (
                    "cancel_target_order_ref",
                    "cancel_target_exchange_id",
                    "cancel_target_order_sys_id",
                    "cancel_target_front_id",
                    "cancel_target_session_id",
                )
            )
            or (
                "RequestID" in payload
                and (
                    type(payload["RequestID"]) is not int
                    or payload["RequestID"] != envelope["native_request_id"]
                )
            )
        ):
            raise CtpExecutionGateError("ctp_managed_native_submit_binding_mismatch")
    return envelope, payload, native_payload


def _managed_native_field_scalar(name: str, value: Any) -> Any:
    """Normalize one allowlisted CTP getter without weakening its type."""

    if name in _CTP_MANAGED_PRICE_FIELDS:
        if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)):
            raise CtpExecutionGateError("ctp_managed_native_field_numeric_invalid")
        try:
            normalized = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise CtpExecutionGateError("ctp_managed_native_field_numeric_invalid") from exc
        if not normalized.is_finite():
            raise CtpExecutionGateError("ctp_managed_native_field_numeric_invalid")
        return normalized
    if name in _CTP_MANAGED_INTEGER_FIELDS:
        if type(value) is not int:
            raise CtpExecutionGateError("ctp_managed_native_field_integer_invalid")
        return value
    if type(value) is not str or not value.isascii() or value != value.strip():
        raise CtpExecutionGateError("ctp_managed_native_field_text_invalid")
    return value


def _managed_payload_scalar(name: str, value: Any) -> Any:
    if name in _CTP_MANAGED_PRICE_FIELDS:
        if type(value) not in (int, float, str) or (
            type(value) is float and not math.isfinite(value)
        ):
            raise CtpExecutionGateError("ctp_managed_native_payload_numeric_invalid")
        try:
            normalized = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise CtpExecutionGateError("ctp_managed_native_payload_numeric_invalid") from exc
        if not normalized.is_finite():
            raise CtpExecutionGateError("ctp_managed_native_payload_numeric_invalid")
        return normalized
    if name in _CTP_MANAGED_INTEGER_FIELDS:
        if type(value) is not int:
            raise CtpExecutionGateError("ctp_managed_native_payload_integer_invalid")
        return value
    if type(value) is not str or not value.isascii() or value != value.strip():
        raise CtpExecutionGateError("ctp_managed_native_payload_text_invalid")
    return value


def _copy_managed_native_field(
    field: Any,
    payload: dict[str, Any],
    *,
    extra_values: Mapping[str, Any] | None = None,
) -> Any:
    """Detach, set and getter-verify precisely the fields in the Store payload."""

    values = dict(payload)
    if extra_values:
        for name, value in extra_values.items():
            if name in values and values[name] != value:
                raise CtpExecutionGateError("ctp_managed_native_field_extra_mismatch")
            values[name] = value
    normalized = {name: _managed_payload_scalar(name, value) for name, value in values.items()}
    try:
        source_snapshot = {
            name: _managed_native_field_scalar(name, getattr(field, name))
            for name in normalized
        }
        if source_snapshot != normalized:
            raise CtpExecutionGateError("ctp_managed_native_field_binding_mismatch")
        detached = type(field)()
        if detached is field:
            raise TypeError("native field constructor reused caller field")
        for name, value in values.items():
            setter_value = (
                float(_managed_payload_scalar(name, value))
                if name in _CTP_MANAGED_PRICE_FIELDS
                else value
            )
            setattr(detached, name, setter_value)
        actual = {
            name: _managed_native_field_scalar(name, getattr(detached, name))
            for name in values
        }
    except CtpExecutionGateError:
        raise
    except Exception as exc:
        raise CtpExecutionGateError("ctp_managed_native_field_snapshot_unavailable") from exc
    if actual != normalized:
        raise CtpExecutionGateError("ctp_managed_native_field_snapshot_mismatch")
    return detached


def _is_callback_ingress_poison_receipt(receipt: Any, owner_id: str, sequence: int) -> bool:
    """Accept only the typed, committed poison acknowledgement from the fixed sink."""

    return (
        type(receipt).__name__ == "CtpTraderCallbackIngressPoisonAckV2"
        and getattr(receipt, "owner_intent_id", None) == owner_id
        and getattr(receipt, "durable_state", None) == "POISONED"
        and type(getattr(receipt, "last_source_sequence", None)) is int
        and getattr(receipt, "last_source_sequence", None) == sequence
        and getattr(receipt, "committed", None) is True
    )


@dataclass(frozen=True)
class _TraderLoginError:
    """Sanitized login identity failure passed to the legacy error callback."""

    ErrorID: int
    ErrorMsg: str


class _TraderSpi(CThostFtdcTraderSpi):
    def __init__(self, client, native_api=None):
        super().__init__()
        self._c = client
        self._native_api = native_api
        self._native_spi_source_id = uuid.uuid4().hex
        self._native_api_generation: int | None = None
        self._native_client_epoch: str | None = None
        self._native_api_source_id: str | None = None
        self._callback_source_tags: Any = None

    def _is_current_locked(self) -> bool:
        if self._native_api is None:
            # Offline unit tests construct an unbound SPI directly.
            return True
        return self._c._spi is self and self._c._api is self._native_api

    def _is_current(self) -> bool:
        with self._c._query_state_lock:
            return self._is_current_locked()

    @_fence_trader_spi_callback
    def OnFrontConnected(self):
        with self._c._query_state_lock:
            if not self._is_current_locked():
                return
            self._c._on_front_connected()
            field = CThostFtdcReqAuthenticateField()
            field.BrokerID = self._c._bound_broker_id
            field.UserID = self._c._bound_user_id
            field.AppID = self._c.app_id
            field.AuthCode = self._c.auth_code
            request_id = self._c._next_request_id()
            generation = self._c._connection_generation
            self._c._authentication_request_id = request_id
            self._c._authentication_connection_generation = generation
            self._c._record_request("authenticate")
            api = self._c._api
        try:
            ret = self._c._invoke_session_native_request(
                api,
                "ReqAuthenticate",
                field,
                request_id,
            )
        except Exception as exc:
            with self._c._query_state_lock:
                if (
                    self._c._authentication_request_id == request_id
                    and self._c._authentication_connection_generation == generation
                    and self._c._connection_generation == generation
                ):
                    self._c._authentication_state = "failed"
                    self._c._last_session_error = {
                        "error": "authentication_submit_failed",
                        "detail": type(exc).__name__,
                    }
            return
        if ret not in (None, 0):
            with self._c._query_state_lock:
                if (
                    self._c._authentication_request_id == request_id
                    and self._c._authentication_connection_generation == generation
                    and self._c._connection_generation == generation
                ):
                    self._c._authentication_state = "failed"
                    self._c._last_session_error = {
                        "error": "authentication_submit_rejected",
                        "submit_code": ret,
                    }

    @_fence_trader_spi_callback
    def OnFrontDisconnected(self, nReason):
        with self._c._query_state_lock:
            if not self._is_current_locked():
                return
            self._c._on_front_disconnected(nReason)

    @_fence_trader_spi_callback
    def OnRspAuthenticate(self, pRspAuthenticateField, pRspInfo, nRequestID, bIsLast):
        error_callback = None
        login_submission = None
        with self._c._query_state_lock:
            accepted = (
                self._is_current_locked()
                and self._c._authentication_state == "authenticating"
                and self._c._authentication_request_id == int(nRequestID)
                and self._c._authentication_connection_generation == self._c._connection_generation
            )
            if not accepted:
                self._c._authentication_late_callback_count += 1
                return
            if _native_callback_flag(bIsLast) is not True:
                return
            self._c._authentication_request_id = None
            self._c._authentication_connection_generation = None
            error_id, _ = _rsp_error(pRspInfo)
            if error_id not in (None, 0):
                self._c._authentication_state = "failed"
                self._c._login_identity_observation = None
                self._c._trading_day = ""
                self._c._last_session_error = _snapshot_ctp_field(pRspInfo)
                error_callback = self._c.on_error
            else:
                self._c._authentication_state = "authenticated"
                self._c._login_identity_observation = None
                self._c._trading_day = ""
                field = CThostFtdcReqUserLoginField()
                field.BrokerID = self._c._bound_broker_id
                field.UserID = self._c._bound_user_id
                field.Password = self._c.password
                request_id = self._c._next_request_id()
                generation = self._c._connection_generation
                self._c._login_state = "logging_in"
                self._c._login_request_id = request_id
                self._c._login_connection_generation = generation
                self._c._record_request("login")
                login_submission = (self._c._api, field, request_id, generation)
        if error_callback is not None:
            error_callback(pRspInfo)
            return
        if login_submission is None:
            return
        api, field, request_id, generation = login_submission
        try:
            ret = self._c._invoke_session_native_request(
                api,
                "ReqUserLogin",
                field,
                request_id,
                request_submitter=lambda pinned_api, request_args: _submit_trader_user_login(
                    pinned_api, *request_args
                ),
            )
        except Exception as exc:
            with self._c._query_state_lock:
                if (
                    self._c._login_request_id == request_id
                    and self._c._login_connection_generation == generation
                    and self._c._connection_generation == generation
                ):
                    self._c._login_state = "failed"
                    self._c._login_identity_observation = None
                    self._c._trading_day = ""
                    self._c._last_session_error = {
                        "error": "login_submit_failed",
                        "detail": (
                            exc.code if isinstance(exc, CtpNativeAbiError) else type(exc).__name__
                        ),
                    }
            return
        if ret not in (None, 0):
            with self._c._query_state_lock:
                if (
                    self._c._login_request_id == request_id
                    and self._c._login_connection_generation == generation
                    and self._c._connection_generation == generation
                ):
                    self._c._login_state = "failed"
                    self._c._login_identity_observation = None
                    self._c._trading_day = ""
                    self._c._last_session_error = {
                        "error": "login_submit_rejected",
                        "submit_code": ret,
                    }

    @_fence_trader_spi_callback
    def OnRspUserLogin(self, pRspUserLogin, pRspInfo, nRequestID, bIsLast):
        login_callback = None
        error_callback = None
        error_info = pRspInfo
        with self._c._query_state_lock:
            try:
                request_id = int(nRequestID)
            except (TypeError, ValueError, OverflowError):
                request_id = -1
            accepted = (
                self._is_current_locked()
                and self._c._login_state == "logging_in"
                and self._c._login_request_id == request_id
                and self._c._login_connection_generation == self._c._connection_generation
            )
            if not accepted:
                self._c._login_late_callback_count += 1
                return
            if _native_callback_flag(bIsLast) is not True:
                return
            generation = self._c._connection_generation
            self._c._login_request_id = None
            self._c._login_connection_generation = None
            error_id, _ = _rsp_error(pRspInfo)
            broker_id = _native_text_field(pRspUserLogin, "BrokerID").strip()
            user_id = _native_text_field(pRspUserLogin, "UserID").strip()
            trading_day = _native_text_field(pRspUserLogin, "TradingDay").strip()
            failure_reason = ""
            if error_id not in (None, 0):
                failure_reason = "provider_login_rejected"
            elif not broker_id or broker_id != self._c._bound_broker_id:
                failure_reason = "broker_id_mismatch"
            elif not user_id or user_id != self._c._bound_user_id:
                failure_reason = "user_id_mismatch"
            elif (
                len(trading_day) != 8
                or not trading_day.isascii()
                or not trading_day.isdigit()
            ):
                failure_reason = "trading_day_invalid"
            else:
                try:
                    datetime.strptime(trading_day, "%Y%m%d")
                except ValueError:
                    failure_reason = "trading_day_invalid"

            if not failure_reason:
                self._c._login_state = "logged_in"
                self._c._front_id = getattr(pRspUserLogin, "FrontID", 0)
                self._c._session_id = getattr(pRspUserLogin, "SessionID", 0)
                self._c._trading_day = trading_day
                self._c._login_identity_observation = _TraderLoginIdentityObservation(
                    _seal=_TRADER_LOGIN_IDENTITY_SEAL,
                    broker_id=broker_id,
                    user_id=user_id,
                    trading_day=trading_day,
                    connection_generation=generation,
                    request_id=request_id,
                )
                with suppress(TypeError, ValueError):
                    self._c._max_order_ref = max(
                        self._c._max_order_ref,
                        int(getattr(pRspUserLogin, "MaxOrderRef", "") or 0),
                    )
                self._c._ready = False
                self._c._settlement_readback_verified = False
                self._c._settlement_proof_source = "none"
                self._c._settlement_proof_query_request_id = None
                # Settlement confirmation is a real terminal write.  Do not
                # synthesize an authorization from ``auto_settlement_confirm``
                # during login: an SDK-managed, explicit confirmation with its
                # opaque capability is required before this session can trade.
                # Keeping the logged-in session read-only remains sufficient
                # for account, position, instrument and quote discovery.
                self._c._settlement_state = "not_requested"
                login_callback = self._c.on_login
            else:
                self._c._login_state = "failed"
                self._c._login_identity_observation = None
                self._c._trading_day = ""
                self._c._ready = False
                self._c._last_session_error = {
                    "error": "login_identity_rejected",
                    "reason": failure_reason,
                }
                error_callback = self._c.on_error
                if error_callback is not None and error_id == 0:
                    error_info = _TraderLoginError(ErrorID=-1, ErrorMsg=failure_reason)
        if login_callback is not None:
            ingress = self._c._callback_ingress
            if ingress is None:
                login_callback(pRspUserLogin)
            else:
                with self._c._query_state_lock:
                    ingress.pending_login_callback = (login_callback, pRspUserLogin)
        if error_callback is not None:
            error_callback(error_info)

    @staticmethod
    def _source_identity_text(value):
        """Keep only exact nonempty callback strings; never synthesize fields."""

        return value if type(value) is str and value else None

    @_fence_trader_spi_callback
    def OnRspSettlementInfoConfirm(self, pSettlementInfoConfirm, pRspInfo, nRequestID, bIsLast):
        error_callback = None
        with self._c._query_state_lock:
            if not self._is_current_locked():
                return
            if not self._c._accept_settlement_callback(nRequestID, pSettlementInfoConfirm):
                return
            error_id, _ = _rsp_error(pRspInfo)
            if error_id in (None, 0):
                self._c._settlement_state = "confirmed"
                self._c._ready = False
                self._c._settlement_readback_verified = False
                self._c._settlement_proof_source = "direct_confirmation"
                self._c._settlement_proof_query_request_id = None
                self._c._revoke_execution_gate_locked(
                    "ctp_execution_gate_settlement_direct_confirmation_requires_readback"
                )
            else:
                self._c._settlement_state = "failed"
                self._c._ready = False
                self._c._settlement_readback_verified = False
                self._c._last_session_error = _snapshot_ctp_field(pRspInfo)
                error_callback = self._c.on_error
            self._c._settlement_done.set()
        if error_callback is not None:
            error_callback(pRspInfo)

    @_fence_trader_spi_callback
    def OnRspQryTradingAccount(self, pTradingAccount, pRspInfo, nRequestID, bIsLast):
        if not self._is_current():
            return
        self._c._handle_query_callback("account", pTradingAccount, pRspInfo, nRequestID, bIsLast)

    @_fence_trader_spi_callback
    def OnRspQryInvestorPosition(self, pPos, pRspInfo, nRequestID, bIsLast):
        if not self._is_current():
            return
        self._c._handle_query_callback("positions", pPos, pRspInfo, nRequestID, bIsLast)

    @_fence_trader_spi_callback
    def OnRspQryOrder(self, pOrder, pRspInfo, nRequestID, bIsLast):
        if not self._is_current():
            return
        self._c._handle_query_callback("orders", pOrder, pRspInfo, nRequestID, bIsLast)

    @_fence_trader_spi_callback
    def OnRspQryTrade(self, pTrade, pRspInfo, nRequestID, bIsLast):
        if not self._is_current():
            return
        self._c._handle_query_callback("trades", pTrade, pRspInfo, nRequestID, bIsLast)

    @_fence_trader_spi_callback
    def OnRspQryInstrument(self, pInstrument, pRspInfo, nRequestID, bIsLast):
        if not self._is_current():
            return
        self._c._handle_query_callback("instruments", pInstrument, pRspInfo, nRequestID, bIsLast)

    @_fence_trader_spi_callback
    def OnRspQryDepthMarketData(self, pDepthMarketData, pRspInfo, nRequestID, bIsLast):
        self._c._handle_query_callback(
            "depth_market_data", pDepthMarketData, pRspInfo, nRequestID, bIsLast
        )

    @_fence_trader_spi_callback
    def OnRspQryOptionInstrTradeCost(self, pOptionInstrTradeCost, pRspInfo, nRequestID, bIsLast):
        self._c._handle_query_callback(
            "option_trade_cost", pOptionInstrTradeCost, pRspInfo, nRequestID, bIsLast
        )

    @_fence_trader_spi_callback
    def OnRspQryOptionInstrCommRate(self, pOptionInstrCommRate, pRspInfo, nRequestID, bIsLast):
        self._c._handle_query_callback(
            "option_commission_rate",
            pOptionInstrCommRate,
            pRspInfo,
            nRequestID,
            bIsLast,
        )

    @_fence_trader_spi_callback
    def OnRspQryInstrumentMarginRate(self, pInstrumentMarginRate, pRspInfo, nRequestID, bIsLast):
        if not self._is_current():
            return
        self._c._handle_query_callback(
            "margin_rate", pInstrumentMarginRate, pRspInfo, nRequestID, bIsLast
        )

    @_fence_trader_spi_callback
    def OnRspQryInstrumentCommissionRate(
        self, pInstrumentCommissionRate, pRspInfo, nRequestID, bIsLast
    ):
        if not self._is_current():
            return
        self._c._handle_query_callback(
            "commission_rate",
            pInstrumentCommissionRate,
            pRspInfo,
            nRequestID,
            bIsLast,
        )

    @_fence_trader_spi_callback
    def OnRspQrySettlementInfoConfirm(self, pSettlementInfoConfirm, pRspInfo, nRequestID, bIsLast):
        if not self._is_current():
            return
        self._c._handle_query_callback(
            "settlement_confirmation",
            pSettlementInfoConfirm,
            pRspInfo,
            nRequestID,
            bIsLast,
        )

    @_fence_trader_spi_callback
    def OnRtnOrder(self, pOrder):
        self._c._handle_order_return(pOrder, origin_api=self._native_api, origin_spi=self)

    @_fence_trader_spi_callback
    def OnRspOrderAction(self, pInputOrderAction, pRspInfo, nRequestID, bIsLast):
        self._c._handle_order_action_callback(
            source="OnRspOrderAction",
            field=pInputOrderAction,
            rsp_info=pRspInfo,
            request_id=nRequestID,
            is_last=bIsLast,
            origin_api=self._native_api,
            origin_spi=self,
        )

    @_fence_trader_spi_callback
    def OnErrRtnOrderAction(self, pOrderAction, pRspInfo):
        self._c._handle_order_action_callback(
            source="OnErrRtnOrderAction",
            field=pOrderAction,
            rsp_info=pRspInfo,
            request_id=None,
            is_last=None,
            origin_api=self._native_api,
            origin_spi=self,
        )

    @_fence_trader_spi_callback
    def OnRtnTrade(self, pTrade):
        if not self._is_current():
            return
        self._c._push_trade_event(pTrade)

    @_fence_trader_spi_callback
    def OnRspOrderInsert(self, pInputOrder, pRspInfo, nRequestID, bIsLast):
        if not self._is_current():
            return
        self._c._push_error_event(
            event_type="order_insert_response",
            rsp_info=pRspInfo,
            field=pInputOrder,
            request_id=nRequestID,
        )

    @_fence_trader_spi_callback
    def OnErrRtnOrderInsert(self, pInputOrder, pRspInfo):
        if not self._is_current():
            return
        self._c._push_error_event(
            event_type="order_insert_error",
            rsp_info=pRspInfo,
            field=pInputOrder,
        )

    @_fence_trader_spi_callback
    def OnRspError(self, pRspInfo, nRequestID, bIsLast):
        if not self._is_current():
            return
        self._c._handle_query_error(pRspInfo, nRequestID, bIsLast)
        self._c._push_error_event(
            event_type="response_error",
            rsp_info=pRspInfo,
            request_id=nRequestID,
        )


def _dispatch_trader_spi_callback(
    spi: _TraderSpi,
    callback_name: str,
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
    original: Callable[..., Any],
) -> Any:
    """Class-level dispatcher shared by managed and ordinary Trader clients."""

    client = getattr(spi, "_c", None)
    if client is None:
        return None
    return client._dispatch_callback_ingress(spi, callback_name, args, kwargs, original)


def _ctp_query_callback_name(request_type: str) -> str | None:
    """Map each SDK query accumulator kind to its one exact callback family."""

    return {
        "account": "OnRspQryTradingAccount",
        "positions": "OnRspQryInvestorPosition",
        "orders": "OnRspQryOrder",
        "trades": "OnRspQryTrade",
        "instruments": "OnRspQryInstrument",
        "depth_market_data": "OnRspQryDepthMarketData",
        "option_trade_cost": "OnRspQryOptionInstrTradeCost",
        "option_commission_rate": "OnRspQryOptionInstrCommRate",
        "margin_rate": "OnRspQryInstrumentMarginRate",
        "commission_rate": "OnRspQryInstrumentCommissionRate",
        "settlement_confirmation": "OnRspQrySettlementInfoConfirm",
    }.get(request_type)


def _validate_explicit_ctp_front(front: Any) -> None:
    """Validate an explicitly configured CTP TCP endpoint without probing it."""

    if (
        type(front) is not str
        or not front
        or front != front.strip()
        or len(front) > 128
    ):
        raise ValueError("invalid configured CTP front")
    try:
        parsed = urlsplit(front)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid configured CTP front") from exc
    if (
        parsed.scheme != "tcp"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or port is None
        or not 1 <= port <= 65535
        or any(char.isspace() or ord(char) < 32 for char in front)
        or front != f"tcp://{parsed.hostname}:{port}"
    ):
        raise ValueError("invalid configured CTP front")


class TraderClient:
    """交易客户端封装

    Args:
        front: 交易前置地址
        broker_id: 经纪商代码
        user_id: 投资者代码
        password: 密码
        app_id: 客户端 AppID
        auth_code: 认证码
    """

    def __init__(
        self,
        front,
        broker_id,
        user_id,
        password,
        app_id="simnow_client_test",
        auth_code="0000000000000000",
        auto_settlement_confirm=False,
        *,
        md_front: str | None = None,
        ctp_env_profile: str | None = None,
    ):
        if (md_front is None) != (ctp_env_profile is None):
            raise ValueError(
                "explicit CTP front pair and profile must be supplied together"
            )
        if ctp_env_profile is not None:
            if (
                type(ctp_env_profile) is not str
                or not ctp_env_profile
                or ctp_env_profile != ctp_env_profile.strip()
            ):
                raise ValueError("invalid CTP environment profile")
            _validate_explicit_ctp_front(front)
            _validate_explicit_ctp_front(md_front)

        # Keep the identity and TD front that created this client separate
        # from the historically public compatibility attributes below.  A
        # caller can mutate ``broker_id``/``user_id``/``front`` on a Python
        # object, but that must not retarget a session whose preflight proof
        # was bound to the original account and native front.
        self._bound_front = str(front or "").strip()
        self.__bound_md_front = md_front
        self.__bound_ctp_env_profile = ctp_env_profile
        self._bound_broker_id = str(broker_id or "").strip()
        self._bound_user_id = str(user_id or "").strip()
        self.front = front
        self.md_front = md_front
        self.broker_id = broker_id
        self.user_id = user_id
        self.password = password
        self.app_id = app_id
        self.auth_code = auth_code
        self.auto_settlement_confirm = bool(auto_settlement_confirm)
        self._account_fingerprint = hashlib.sha256(
            f"{self._bound_broker_id}:{self._bound_user_id}".encode()
        ).hexdigest()[:16]

        self.on_login = None  # callback(CThostFtdcRspUserLoginField)
        self.on_order = None  # callback(CThostFtdcOrderField)
        self.on_trade = None  # callback(CThostFtdcTradeField)
        self.on_error = None  # callback(CThostFtdcRspInfoField)

        self._connected = False
        self._ready = False
        self._authentication_state = "disconnected"
        self._login_state = "disconnected"
        self._settlement_state = "unknown"
        self._trading_day = ""
        self._last_session_error: dict[str, Any] = {}
        self._connection_generation = 0
        self._req_id = 0
        self._front_id = 0
        self._session_id = 0
        self._api_view = _ManagedTraderApiView(self)
        self._native_api_generation = 0
        self._native_client_epoch: str | None = None
        self._native_api_source_id: str | None = None
        self._api = None
        self._session_native_api = None
        self._session_native_front: str | None = None
        self._native_lifecycle_state: _CtpNativeLifecycleState | None = None
        self._last_stop_lifecycle_state: _CtpNativeLifecycleState | None = None
        self._spi = None
        self._thread = None
        self._join_active = False
        self._native_init_started = False
        self._native_join_tracker = _CtpNativeJoinTracker()
        self._pending_native_join_api_ids: set[int] = set()
        self._last_stopped_native_api = None
        self._last_stopped_connection_generation = 0
        self._last_stop_join_required = False
        self._last_stop_join_thread: threading.Thread | None = None
        self._last_stop_join_tracker: _CtpNativeJoinTracker | None = None
        self._lifecycle_generation = 0
        self._starting_generation: int | None = None
        self._startup_cancel_event = threading.Event()
        self._settlement_done = threading.Event()
        self._settlement_request_id: int | None = None
        self._settlement_connection_generation: int | None = None
        self._settlement_account_fingerprint: str | None = None
        self._settlement_trading_day: str | None = None
        self._settlement_late_callback_count = 0
        self._settlement_proof_source = "none"
        self._settlement_proof_query_request_id: int | None = None
        self._settlement_readback_verified = False
        self._authentication_request_id: int | None = None
        self._authentication_connection_generation: int | None = None
        self._authentication_late_callback_count = 0
        self._login_request_id: int | None = None
        self._login_connection_generation: int | None = None
        self._login_late_callback_count = 0
        self._login_identity_observation: _TraderLoginIdentityObservation | None = None
        self._query_done = threading.Event()
        self._last_account = None
        self._last_positions = []
        self._last_orders = []
        self._last_instrument = None
        self._last_margin_rate = None
        self._last_commission_rate = None
        self._query_lock = threading.Lock()
        self._query_state_lock = threading.RLock()
        self._query_history: dict[int, _QueryAccumulator] = {}
        self._order_action_history: dict[tuple[int, str], CtpOrderActionEvidence] = {}
        self._order_action_identities: dict[tuple[int, str], _OrderActionIdentity] = {}
        self._managed_cancel_actions_seen: set[str] = set()
        self._order_action_late_callback_count = 0
        # Every typed query source and session scope from this client share an
        # opaque issuer.  Equal account strings from a different object or a
        # hand-built mapping can therefore never certify the same query.
        self._query_evidence_issuer = object()
        self._orphan_query_callbacks: list[dict[str, Any]] = []
        self._request_counts: dict[str, int] = empty_ctp_request_counts()
        self._execution_gate_capability: object | None = None
        self._execution_gate_proof: dict[str, Any] | None = None
        self._execution_gate_proof_sha256: str | None = None
        self._execution_gate_environment_profile: str | None = None
        self._execution_gate_strategy_identity_sha256: str | None = None
        self._execution_gate_cycle_id: str | None = None
        self._execution_gate_revocation_reason: str | None = None
        self._execution_gate_native_api = None
        # A settlement confirmation deliberately invalidates every arm proof
        # issued before it.  It is a terminal account write, so a subsequent
        # order arm must be based on a fresh preflight rather than a cached
        # public session snapshot.
        self._execution_preflight_epoch = 0
        self._last_query_submitted_at = 0.0
        try:
            self._query_interval = max(
                0.0, float(os.environ.get("BT_API_PY_CTP_QUERY_INTERVAL_SEC") or 1.05)
            )
        except ValueError:
            self._query_interval = 1.05
        self._max_order_ref = 0
        self._order_ref_lock = threading.Lock()
        self._order_events = queue.Queue()
        self._trade_events = queue.Queue()
        self._error_events = queue.Queue()
        self._callback_source_instance_id = uuid.uuid4().hex
        self._callback_source_sequence = 0
        self._native_callback_queue_generation = 0
        self._native_callback_events = queue.Queue()
        self._native_callback_event_condition = threading.Condition(self._query_state_lock)
        self._native_callback_consumer_lease: _NativeCallbackEventConsumerLease | None = None
        self._native_callback_legacy_waiters = 0
        self._native_callback_released_consumer_tokens = weakref.WeakSet()
        self._callback_ingress: _TraderCallbackIngressState | None = None
        self._managed_native_call_leases: dict[str, CtpManagedNativeCallLeaseV2] = {}
        self._managed_callback_thread_state = threading.local()
        self._callback_ingress_deferred_cleanup: tuple[Any, Any, bool, bool] | None = None
        self._callback_ingress_cleanup_scheduled = False
        self._native_stop_in_progress = False
        self._native_request_inflight_refs = 0
        self._callback_inflight_refs = 0

    @property
    def _bound_md_front(self) -> str | None:
        """Return the constructor-bound market-data front without a setter."""

        return self.__bound_md_front

    @property
    def ctp_env_profile(self) -> str | None:
        """Return the constructor-bound CTP environment profile without a setter."""

        return self.__bound_ctp_env_profile

    @property
    def _api(self) -> Any:
        return getattr(self, "_TraderClient__native_api", None)

    def _poison_callback_ingress_locked(
        self,
        reason_code: str,
        *,
        source_tags: tuple[str, str, str, str, int, int] | None = None,
    ) -> None:
        """Latch a one-way managed-source fence while the lifecycle lock is held."""

        state = getattr(self, "_callback_ingress", None)
        if state is None or state.poisoned:
            return
        allowed_reasons = {
            "owner_stop",
            "source_replaced",
            "disconnect",
            "lifecycle_transition",
            "source_gap",
            "queue_overflow",
            "unknown_source",
            "unsupported_financial",
            "capture_incomplete",
            "callback_handler_error",
            "append_failure",
            "append_commit_unknown",
            "native_call_ambiguous",
            "native_call_receipt_mismatch",
            "native_call_lease_failure",
            "source_identity_mismatch",
        }
        if reason_code not in allowed_reasons:
            reason_code = "source_gap"
        state.poisoned = True
        state.phase = "POISONED"
        state.poison_reason = reason_code
        state.active_session = None
        state.login_bind_pending = False
        managed_leases = getattr(self, "_managed_native_call_leases", {})
        for nonce, lease in tuple(managed_leases.items()):
            if state.command_lease is lease:
                managed_leases.pop(nonce, None)
                state.command_lease = None
                state.native_call_refs = max(0, state.native_call_refs - 1)
        if getattr(self, "_execution_gate_capability", None) is not None:
            self._revoke_execution_gate_locked(f"ctp_callback_ingress_{reason_code}")
        poison_sink = state.poison_sink
        if poison_sink is None:
            return
        source_tags = source_tags or state.current_source_tags
        try:
            receipt = poison_sink(
                state.owner_handle,
                reason_code,
                source_tags=source_tags,
                last_sequence=state.sequence,
            )
        except BaseException:
            # The durable owner intent is itself a permanent restart fence.
            # Keep this process poisoned when its additional poison write is
            # absent or ambiguous.
            return
        if not _is_callback_ingress_poison_receipt(receipt, state.owner_intent_id, state.sequence):
            state.poison_reason = "append_commit_unknown"

    @_api.setter
    def _api(self, value: Any) -> None:
        current = getattr(self, "_TraderClient__native_api", None)
        if current is value:
            return
        lock = getattr(self, "_query_state_lock", None)
        if lock is None:
            self.__native_api = value
            if current is not None and hasattr(self, "_login_identity_observation"):
                self._login_identity_observation = None
            self._native_api_generation = getattr(self, "_native_api_generation", 0) + 1
            self._native_callback_queue_generation = (
                getattr(self, "_native_callback_queue_generation", 0) + 1
            )
            self._native_client_epoch = uuid.uuid4().hex if value is not None else None
            self._native_api_source_id = uuid.uuid4().hex if value is not None else None
            return
        with lock:
            ingress = getattr(self, "_callback_ingress", None)
            if ingress is not None and current is not None and current is not value:
                self._poison_callback_ingress_locked(
                    "owner_stop" if value is None else "source_replaced"
                )
                if not getattr(self, "_native_stop_in_progress", False):
                    spi = getattr(self, "_spi", None)
                    join_thread = getattr(self, "_thread", None)
                    join_claimed = _ctp_native_join_claimed(current)
                    join_required = bool(
                        getattr(self, "_join_active", False)
                        or join_claimed
                        or (join_thread is not None and join_thread.is_alive())
                    )
                    if join_required:
                        # A replacement can race an active Join just like
                        # stop(). Keep the exact old director alive in the
                        # retired-session registry until Join proves return;
                        # the deferred cleanup tuple only spans callback/Req
                        # reference drain and may be cleared earlier.
                        _retain_live_ctp_native_session(current, spi, join_thread)
                    self._callback_ingress_deferred_cleanup = (
                        current,
                        spi,
                        join_required,
                        join_claimed,
                    )
                    self._maybe_finish_deferred_native_release_locked()
            self._revoke_native_callback_event_consumer_locked(
                "ctp_native_callback_consumer_native_api_changed"
            )
            if getattr(self, "_execution_gate_capability", None) is not None:
                self._revoke_execution_gate_locked("ctp_execution_gate_native_api_changed")
            if hasattr(self, "_execution_preflight_epoch"):
                self._execution_preflight_epoch += 1
            self._session_native_api = None
            self._session_native_front = None
            if current is not None and hasattr(self, "_login_identity_observation"):
                self._login_identity_observation = None
            # Any callbacks from the previous SPI become stale immediately.
            self._spi = None
            self.__native_api = value
            self._native_api_generation = getattr(self, "_native_api_generation", 0) + 1
            self._native_callback_queue_generation = (
                getattr(self, "_native_callback_queue_generation", 0) + 1
            )
            self._native_client_epoch = uuid.uuid4().hex if value is not None else None
            self._native_api_source_id = uuid.uuid4().hex if value is not None else None
            condition = getattr(self, "_native_callback_event_condition", None)
            if condition is not None:
                condition.notify_all()

    def install_callback_ingress_sink(
        self,
        owner_handle: Any,
        append_sink: Any,
        session_binder: Callable[..., Any],
        command_binding_verifier: Callable[..., Any],
    ) -> None:
        """Install the fixed durable callback owner before any native start.

        The caller must first persist a one-shot Store owner intent. The SDK
        keeps the exact sink, binder, and verifier objects for this client;
        none can be replaced after installation.
        """

        owner_intent_id = getattr(owner_handle, "owner_intent_id", None)
        if (
            type(owner_intent_id) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", owner_intent_id, re.ASCII)
            is None
        ):
            raise CtpExecutionGateError("ctp_callback_ingress_owner_handle_invalid")
        if not callable(getattr(append_sink, "append", None)) or not callable(
            getattr(append_sink, "poison_ingress", None)
        ):
            raise CtpExecutionGateError("ctp_callback_ingress_sink_invalid")
        if not callable(session_binder) or not callable(command_binding_verifier):
            raise CtpExecutionGateError("ctp_callback_ingress_binding_invalid")

        with self._query_state_lock:
            if self._callback_ingress is not None:
                raise CtpExecutionGateError("ctp_callback_ingress_already_installed")
            if (
                self._api is not None
                or self._starting_generation is not None
                or self._native_api_generation != 0
                or self._callback_source_sequence != 0
                or self._connected
                or self._login_identity_observation is not None
                or self._native_callback_consumer_lease is not None
                or self._native_callback_legacy_waiters != 0
                or not self._native_callback_events.empty()
                or not self._order_events.empty()
                or not self._trade_events.empty()
                or not self._error_events.empty()
                or self._pending_native_join_api_ids
                or self._query_history
            ):
                raise CtpExecutionGateError("ctp_callback_ingress_cutover_not_clean")

            state = _TraderCallbackIngressState(
                owner_handle=owner_handle,
                owner_intent_id=owner_intent_id,
                append_sink=append_sink,
                session_binder=session_binder,
                command_binding_verifier=command_binding_verifier,
                poison_sink=append_sink.poison_ingress,
            )
            # Install the same code-owned dispatcher on every generated SPI
            # method. The helper checks exact inventory equality and is
            # idempotent only for this dispatcher.
            from .callback_ingress import install_trader_spi_callback_dispatch

            install_trader_spi_callback_dispatch(_TraderSpi, _dispatch_trader_spi_callback)
            self._callback_ingress = state

    def bind_active_callback_session(self, owner_handle: Any) -> Any:
        """Bind the installed owner after this SDK accepts terminal login."""

        with self._query_state_lock:
            state = self._callback_ingress
            observation = self._login_identity_observation
            spi = self._spi
            api = self._api
            if (
                state is None
                or owner_handle is not state.owner_handle
                or state.owner_intent_id != getattr(owner_handle, "owner_intent_id", None)
                or state.poisoned
                or state.active_session is not None
                or state.phase != "LOGIN_BIND_PENDING"
                or not state.login_bind_pending
                or observation is None
                or observation._seal is not _TRADER_LOGIN_IDENTITY_SEAL
                or self._current_login_identity_locked() is not observation
                or spi is None
                or api is None
                or spi._native_api is not api
                or spi._native_api_source_id != self._native_api_source_id
                or spi._native_api_generation != self._native_api_generation
                or spi._native_client_epoch != self._native_client_epoch
                or self._session_native_api is not api
            ):
                self._poison_callback_ingress_locked("lifecycle_transition")
                raise CtpExecutionGateError("ctp_callback_ingress_login_binding_invalid")

            tags = spi._callback_source_tags
            tag_values = (
                getattr(tags, "source_instance_id", None),
                getattr(tags, "native_client_epoch", None),
                getattr(tags, "native_api_source_id", None),
                getattr(tags, "native_spi_source_id", None),
                getattr(tags, "native_api_generation", None),
                getattr(tags, "connection_generation", None),
            )
            if (
                tags is not state.current_source_tags_object
                or tag_values != state.current_source_tags
            ):
                self._poison_callback_ingress_locked("source_identity_mismatch")
                raise CtpExecutionGateError("ctp_callback_ingress_source_identity_mismatch")
            try:
                session = state.session_binder(
                    owner_handle,
                    observation=observation,
                    source_tags=tags,
                    high_watermark=state.sequence,
                )
            except BaseException as exc:
                self._poison_callback_ingress_locked("lifecycle_transition")
                raise CtpExecutionGateError("ctp_callback_ingress_session_bind_failed") from exc
            expected_tags = (
                tags.source_instance_id,
                tags.native_client_epoch,
                tags.native_api_source_id,
                tags.native_spi_source_id,
                tags.native_api_generation,
                tags.connection_generation,
            )
            session_identity_matches = (
                type(session).__name__ == "CtpCallbackSessionBindingV1"
                and type(getattr(session, "source_high_watermark", None)) is int
                and type(getattr(session, "source_connection_generation", None)) is int
                and type(getattr(session, "connection_generation", None)) is int
                and type(getattr(session, "native_api_generation", None)) is int
                and type(getattr(session, "dispatch_front_id", None)) is int
                and type(getattr(session, "dispatch_session_id", None)) is int
                and all(
                    type(getattr(session, name, None)) is str
                    and bool(getattr(session, name, None))
                    for name in (
                        "owner_intent_id",
                        "account_key",
                        "scope_key",
                        "trading_day",
                        "session_generation_id",
                        "source_instance_id",
                        "native_client_epoch",
                        "native_api_source_id",
                        "native_spi_source_id",
                        "session_binding_sha256",
                    )
                )
                and getattr(session, "owner_intent_id", None) == state.owner_intent_id
                and getattr(session, "source_instance_id", None) == tags.source_instance_id
                and getattr(session, "native_client_epoch", None) == tags.native_client_epoch
                and getattr(session, "native_api_source_id", None) == tags.native_api_source_id
                and getattr(session, "native_spi_source_id", None) == tags.native_spi_source_id
                and getattr(session, "native_api_generation", None)
                == tags.native_api_generation
                and getattr(session, "connection_generation", None)
                == observation.connection_generation
                and getattr(session, "source_high_watermark", None) == state.sequence
                and getattr(session, "trading_day", None) == observation.trading_day
                and getattr(session, "dispatch_front_id", None) == self._front_id
                and getattr(session, "dispatch_session_id", None) == self._session_id
                and type(getattr(session, "session_binding_sha256", None)) is str
                and re.fullmatch(
                    r"[0-9a-f]{64}",
                    getattr(session, "session_binding_sha256", ""),
                    re.ASCII,
                )
                is not None
            )
            if not session_identity_matches:
                self._poison_callback_ingress_locked("lifecycle_transition")
                raise CtpExecutionGateError("ctp_callback_ingress_session_bind_unconfirmed")
            source_tags_tuple = expected_tags
            if tuple(
                getattr(session, name, None)
                for name in (
                    "source_instance_id",
                    "native_client_epoch",
                    "native_api_source_id",
                    "native_spi_source_id",
                    "native_api_generation",
                    "source_connection_generation",
                )
            ) != source_tags_tuple:
                self._poison_callback_ingress_locked("source_identity_mismatch")
                raise CtpExecutionGateError("ctp_callback_ingress_session_source_mismatch")
            state.active_session = session
            state.phase = "ACTIVE"
            state.login_bind_pending = False
            return session

    def _invoke_session_native_request(
        self,
        api: Any,
        method_name: str,
        *args: Any,
        request_submitter: Callable[[Any, tuple[Any, ...]], Any] | None = None,
        settlement_authorization: Any = None,
    ) -> Any:
        """Invoke a pinned session Req with every SDK lock released.

        This internal lease is limited to authentication, login, and read-only
        queries. Managed order/action sends use their Store-issued one-shot
        `CtpManagedNativeCallLeaseV2` instead.
        """

        if not method_name.startswith("Req"):
            raise CtpExecutionGateError("ctp_managed_native_request_kind_blocked")
        with self._query_state_lock:
            state = self._callback_ingress
            if api is None or self._api is not api or (state is not None and self._spi is None):
                if state is not None:
                    self._poison_callback_ingress_locked("source_identity_mismatch")
                raise CtpExecutionGateError("ctp_managed_native_request_source_mismatch")
            if state is not None:
                if state.poisoned or state.phase not in {"PRE_LOGIN", "ACTIVE"}:
                    raise CtpExecutionGateError("ctp_callback_ingress_owner_poisoned")
                if method_name not in _CTP_INGRESS_SAFE_REQUEST_METHODS:
                    self._poison_callback_ingress_locked("unsupported_financial")
                    raise CtpExecutionGateError("ctp_callback_ingress_native_request_unsupported")
                if method_name in {"ReqAuthenticate", "ReqUserLogin"}:
                    if state.phase != "PRE_LOGIN" or state.active_session is not None:
                        self._poison_callback_ingress_locked("lifecycle_transition")
                        raise CtpExecutionGateError("ctp_callback_ingress_lifecycle_request_invalid")
                elif state.phase != "ACTIVE" or state.active_session is None:
                    self._poison_callback_ingress_locked("lifecycle_transition")
                    raise CtpExecutionGateError("ctp_callback_ingress_query_before_active")
                if method_name == "ReqSettlementInfoConfirm":
                    if (
                        type(settlement_authorization) is not _CtpSettlementAuthorization
                        or settlement_authorization._seal is not _CTP_EXECUTION_AUTHORIZATION_SEAL
                        or settlement_authorization._client_ref() is not self
                        or settlement_authorization._used is not True
                        or settlement_authorization._account_fingerprint
                        != self._account_fingerprint
                        or settlement_authorization._trading_day != self._trading_day
                        or settlement_authorization._connection_generation
                        != self._connection_generation
                        or len(args) < 2
                        or type(args[1]) is not int
                        or args[1] != self._settlement_request_id
                    ):
                        raise CtpExecutionGateError("ctp_settlement_authorization_required")
                    if state.command_lease is not None:
                        raise CtpExecutionGateError("ctp_native_request_inflight")
                    state.command_lease = settlement_authorization
                spi = self._spi
                if (
                    spi._native_api is not api
                    or spi._callback_source_tags is None
                    or spi._callback_source_tags.native_api_generation != self._native_api_generation
                    or spi._callback_source_tags.native_api_source_id != self._native_api_source_id
                ):
                    self._poison_callback_ingress_locked("source_identity_mismatch")
                    raise CtpExecutionGateError("ctp_callback_ingress_source_identity_mismatch")
            else:
                spi = self._spi
            method = None
            if request_submitter is None:
                try:
                    method = getattr(api, method_name, None)
                except BaseException:
                    if state is not None:
                        self._poison_callback_ingress_locked("native_call_lease_failure")
                    raise
                if not callable(method):
                    if state is not None:
                        self._poison_callback_ingress_locked("native_call_lease_failure")
                    raise CtpExecutionGateError("ctp_native_request_method_unavailable")
            elif not callable(request_submitter):
                if state is not None:
                    self._poison_callback_ingress_locked("native_call_lease_failure")
                raise CtpExecutionGateError("ctp_native_request_submitter_unavailable")
            if state is not None:
                state.native_call_refs += 1
            self._native_request_inflight_refs += 1

        call_failed = False
        invalid_return_type = False
        try:
            if request_submitter is None:
                result = method(*args)
            else:
                result = request_submitter(api, args)
        except BaseException:
            call_failed = True
            raise
        finally:
            with self._query_state_lock:
                self._native_request_inflight_refs = max(
                    0, self._native_request_inflight_refs - 1
                )
                if state is not None:
                    state.native_call_refs -= 1
                    if state.command_lease is settlement_authorization:
                        state.command_lease = None
                    if call_failed:
                        self._poison_callback_ingress_locked("native_call_ambiguous")
                    elif type(result) is not int:
                        invalid_return_type = True
                        self._poison_callback_ingress_locked("native_call_ambiguous")
                    elif result != 0 and method_name in {"ReqAuthenticate", "ReqUserLogin"}:
                        self._poison_callback_ingress_locked("lifecycle_transition")
                self._maybe_finish_deferred_native_release_locked()
        if invalid_return_type:
            raise CtpExecutionGateError("ctp_callback_ingress_native_request_result_invalid")
        return result

    def acquire_managed_native_call_lease(
        self,
        owner_handle: Any,
        binding: Any,
    ) -> CtpManagedNativeCallLeaseV2:
        """Pin the exact active API/SPI for one Store-claimed command call."""

        with self._query_state_lock:
            state = self._callback_ingress
            if (
                state is None
                or owner_handle is not state.owner_handle
                or state.poisoned
                or state.phase != "ACTIVE"
                or state.active_session is None
                or state.command_lease is not None
                or state.native_call_refs != 0
                or self._native_request_inflight_refs != 0
            ):
                raise CtpExecutionGateError("ctp_managed_native_call_owner_unavailable")
            api = self._api
            spi = self._spi
            tags = getattr(spi, "_callback_source_tags", None) if spi is not None else None
            if (
                api is None
                or spi is None
                or spi._native_api is not api
                or tags is None
                or tags != state.current_source_tags_object
                or self._session_native_api is not api
            ):
                self._poison_callback_ingress_locked("source_identity_mismatch")
                raise CtpExecutionGateError("ctp_managed_native_call_source_mismatch")

            try:
                verified = state.command_binding_verifier(owner_handle, binding)
            except BaseException as exc:
                self._poison_callback_ingress_locked("native_call_lease_failure")
                raise CtpExecutionGateError("ctp_managed_native_call_binding_rejected") from exc
            if verified is not binding:
                self._poison_callback_ingress_locked("native_call_lease_failure")
                raise CtpExecutionGateError("ctp_managed_native_call_binding_rejected")
            try:
                envelope, _payload, _native_payload = _managed_native_binding_payload(
                    binding,
                    state.owner_intent_id,
                )
            except Exception as exc:
                self._poison_callback_ingress_locked("native_call_lease_failure")
                if isinstance(exc, CtpExecutionGateError):
                    raise
                raise CtpExecutionGateError(
                    "ctp_managed_native_call_binding_invalid"
                ) from exc
            session = state.active_session
            session_values = {
                "account_key": getattr(session, "account_key", None),
                "scope_key": getattr(session, "scope_key", None),
                "trading_day": getattr(session, "trading_day", None),
                "session_binding_sha256": getattr(session, "session_binding_sha256", None),
                "session_generation_id": getattr(session, "session_generation_id", None),
                "dispatch_front_id": getattr(session, "dispatch_front_id", None),
                "dispatch_session_id": getattr(session, "dispatch_session_id", None),
            }
            if (
                any(envelope.get(name) != value for name, value in session_values.items())
                or envelope["expires_at_ns"] <= time.time_ns()
                or envelope["operation"] not in {"SUBMIT", "CANCEL"}
                or (
                    envelope["operation"] == "SUBMIT"
                    and envelope["native_action_ref"] is not None
                )
                or (
                    envelope["operation"] == "CANCEL"
                    and (
                        type(envelope["managed_action_id"]) is not str
                        or not envelope["managed_action_id"]
                    )
                )
            ):
                self._poison_callback_ingress_locked("native_call_lease_failure")
                raise CtpExecutionGateError("ctp_managed_native_call_binding_session_mismatch")

            source_tag_tuple = (
                tags.source_instance_id,
                tags.native_client_epoch,
                tags.native_api_source_id,
                tags.native_spi_source_id,
                tags.native_api_generation,
                tags.connection_generation,
            )
            if (
                getattr(session, "source_instance_id", None) != source_tag_tuple[0]
                or getattr(session, "native_client_epoch", None) != source_tag_tuple[1]
                or getattr(session, "native_api_source_id", None) != source_tag_tuple[2]
                or getattr(session, "native_spi_source_id", None) != source_tag_tuple[3]
                or getattr(session, "native_api_generation", None) != source_tag_tuple[4]
                or getattr(session, "source_connection_generation", None) != source_tag_tuple[5]
                or getattr(session, "connection_generation", None) != self._connection_generation
                or type(getattr(session, "source_high_watermark", None)) is not int
                or session.source_high_watermark > state.sequence
            ):
                self._poison_callback_ingress_locked("source_identity_mismatch")
                raise CtpExecutionGateError("ctp_managed_native_call_session_source_mismatch")

            used_commands = getattr(state, "used_command_ids", None)
            if used_commands is None:
                state.used_command_ids = set()
                used_commands = state.used_command_ids
            command_id = envelope["command_id"]
            if command_id in used_commands:
                self._poison_callback_ingress_locked("native_call_lease_failure")
                raise CtpExecutionGateError("ctp_managed_native_call_binding_reused")
            operation = envelope["operation"]
            method_name = "ReqOrderInsert" if operation == "SUBMIT" else "ReqOrderAction"
            lease = CtpManagedNativeCallLeaseV2(
                _seal=_CTP_MANAGED_NATIVE_CALL_LEASE_SEAL,
                _owner_handle=owner_handle,
                _binding=binding,
                _api=api,
                _spi=spi,
                _active_session=session,
                _source_tags=source_tag_tuple,
                _method_name=method_name,
                _nonce=uuid.uuid4().hex,
                _binding_payload_json=json.dumps(
                    envelope,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                ),
                _logical_request_payload_json=envelope["request_payload_json"],
                _native_request_payload_json=envelope["native_request_payload_json"],
            )
            used_commands.add(command_id)
            state.command_lease = lease
            state.native_call_refs += 1
            self._managed_native_call_leases[lease._nonce] = lease
            return lease

    def release_managed_native_call_lease(self, lease: CtpManagedNativeCallLeaseV2) -> None:
        """Poison and retire an acquired lease that was not sent."""

        with self._query_state_lock:
            state = self._callback_ingress
            current = self._managed_native_call_leases.get(
                getattr(lease, "_nonce", "")
            )
            if (
                state is None
                or current is not lease
                or lease._seal is not _CTP_MANAGED_NATIVE_CALL_LEASE_SEAL
            ):
                raise CtpExecutionGateError("ctp_managed_native_call_lease_invalid")
            self._managed_native_call_leases.pop(lease._nonce, None)
            state.command_lease = None
            state.native_call_refs = max(0, state.native_call_refs - 1)
            self._poison_callback_ingress_locked("native_call_lease_failure")
            self._maybe_finish_deferred_native_release_locked()

    def _submit_with_managed_native_call_lease(
        self,
        lease: CtpManagedNativeCallLeaseV2,
        field: Any,
        request_id: int,
        *,
        method_name: str,
    ) -> Any:
        with self._query_state_lock:
            state = self._callback_ingress
            current = self._managed_native_call_leases.get(
                getattr(lease, "_nonce", "")
            )
            if (
                state is None
                or current is not lease
                or state.command_lease is not lease
                or lease._seal is not _CTP_MANAGED_NATIVE_CALL_LEASE_SEAL
                or lease._owner_handle is not state.owner_handle
                or state.poisoned
                or state.phase != "ACTIVE"
                or state.active_session is not lease._active_session
                or self._api is not lease._api
                or self._spi is not lease._spi
                or getattr(lease._spi, "_callback_source_tags", None) is None
                or (
                    getattr(lease._spi, "_callback_source_tags", None)
                    != getattr(state, "current_source_tags_object", None)
                )
                or lease._source_tags
                != (
                    getattr(lease._spi._callback_source_tags, "source_instance_id", None),
                    getattr(lease._spi._callback_source_tags, "native_client_epoch", None),
                    getattr(lease._spi._callback_source_tags, "native_api_source_id", None),
                    getattr(lease._spi._callback_source_tags, "native_spi_source_id", None),
                    getattr(lease._spi._callback_source_tags, "native_api_generation", None),
                    getattr(lease._spi._callback_source_tags, "connection_generation", None),
                )
            ):
                if state is not None and current is lease:
                    self._managed_native_call_leases.pop(lease._nonce, None)
                    if state.command_lease is lease:
                        state.command_lease = None
                    state.native_call_refs = max(0, state.native_call_refs - 1)
                    self._poison_callback_ingress_locked("source_identity_mismatch")
                    self._maybe_finish_deferred_native_release_locked()
                raise CtpExecutionGateError("ctp_managed_native_call_lease_invalid")

            self._managed_native_call_leases.pop(lease._nonce, None)
            state.command_lease = None
            self._native_request_inflight_refs += 1
            try:
                binding = lease._binding
                envelope, payload, native_payload = _managed_native_binding_payload(
                    binding,
                    state.owner_intent_id,
                )
                if (
                    envelope["operation"]
                    != ("SUBMIT" if method_name == "ReqOrderInsert" else "CANCEL")
                    or method_name != lease._method_name
                    or envelope["expires_at_ns"] <= time.time_ns()
                    or json.dumps(
                        envelope,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                        allow_nan=False,
                    )
                    != lease._binding_payload_json
                    or envelope["request_payload_json"] != lease._logical_request_payload_json
                    or envelope["native_request_payload_json"]
                    != lease._native_request_payload_json
                    or type(request_id) is not int
                    or request_id != envelope["native_request_id"]
                ):
                    raise CtpExecutionGateError("ctp_managed_native_call_binding_changed")
                detached_extras: dict[str, Any] = {}
                if envelope["operation"] == "CANCEL":
                    detached_extras = {"RequestID": envelope["native_request_id"]}
                for field_name, expected_identity in (
                    ("BrokerID", self._bound_broker_id),
                    ("InvestorID", self._bound_user_id),
                    ("UserID", self._bound_user_id),
                ):
                    if field_name in payload and payload[field_name] != expected_identity:
                        raise CtpExecutionGateError(
                            "ctp_managed_native_field_account_mismatch"
                        )
                detached = _copy_managed_native_field(
                    field,
                    native_payload,
                    extra_values=detached_extras,
                )
                if envelope["operation"] == "CANCEL":
                    if (
                        _managed_native_field_scalar("RequestID", detached.RequestID)
                        != envelope["native_request_id"]
                        or _managed_native_field_scalar(
                            "OrderActionRef", detached.OrderActionRef
                        )
                        != envelope["native_action_ref"]
                        or payload.get("OrderRef") != envelope["cancel_target_order_ref"]
                        or payload.get("ExchangeID")
                        != envelope["cancel_target_exchange_id"]
                        or payload.get("OrderSysID")
                        != envelope["cancel_target_order_sys_id"]
                        or payload.get("FrontID") != envelope["cancel_target_front_id"]
                        or payload.get("SessionID") != envelope["cancel_target_session_id"]
                        or payload.get("ActionFlag") != "0"
                    ):
                        raise CtpExecutionGateError("ctp_managed_native_cancel_field_mismatch")
                native_method = getattr(lease._api, method_name, None)
                if not callable(native_method):
                    raise CtpExecutionGateError("ctp_managed_native_call_method_unavailable")
            except BaseException:
                state.native_call_refs = max(0, state.native_call_refs - 1)
                self._native_request_inflight_refs = max(
                    0, self._native_request_inflight_refs - 1
                )
                self._poison_callback_ingress_locked("native_call_lease_failure")
                self._maybe_finish_deferred_native_release_locked()
                raise

        call_failed = False
        invalid_result = False
        lifecycle_invalid = False
        try:
            result = native_method(detached, request_id)
        except BaseException:
            call_failed = True
            raise
        finally:
            with self._query_state_lock:
                state.native_call_refs = max(0, state.native_call_refs - 1)
                self._native_request_inflight_refs = max(0, self._native_request_inflight_refs - 1)
                invalid_result = not call_failed and (type(result) is not int or result != 0)
                lifecycle_invalid = (
                    self._callback_ingress is not state
                    or state.poisoned
                    or state.phase != "ACTIVE"
                    or state.owner_handle is not lease._owner_handle
                    or state.active_session is not lease._active_session
                    or self._api is not lease._api
                    or self._spi is not lease._spi
                    or getattr(lease._spi, "_callback_source_tags", None)
                    != getattr(state, "current_source_tags_object", None)
                )
                if call_failed or invalid_result or lifecycle_invalid:
                    self._poison_callback_ingress_locked("native_call_ambiguous")
                self._maybe_finish_deferred_native_release_locked()
        if invalid_result or lifecycle_invalid:
            raise CtpExecutionGateError("ctp_managed_native_call_result_ambiguous")
        return result

    def submit_order_insert_with_lease(
        self,
        lease: CtpManagedNativeCallLeaseV2,
        field: Any,
        request_id: int,
    ) -> Any:
        """Invoke exactly one pinned ReqOrderInsert without holding SDK locks."""

        return self._submit_with_managed_native_call_lease(
            lease,
            field,
            request_id,
            method_name="ReqOrderInsert",
        )

    def submit_order_action_with_lease(
        self,
        lease: CtpManagedNativeCallLeaseV2,
        field: Any,
        request_id: int,
    ) -> Any:
        """Invoke exactly one pinned ReqOrderAction without holding SDK locks."""

        return self._submit_with_managed_native_call_lease(
            lease,
            field,
            request_id,
            method_name="ReqOrderAction",
        )

    def _dispatch_callback_ingress(
        self,
        spi: _TraderSpi,
        callback_name: str,
        args: tuple[Any, ...],
        kwargs: Mapping[str, Any],
        original: Callable[..., Any],
    ) -> Any:
        """Append one exact-origin callback before invoking its old handler."""

        from .callback_ingress import (
            CtpTraderCallbackClass,
            CtpTraderCallbackDisposition,
            CtpTraderCallbackIngressAckV2,
            CtpTraderCallbackPhase,
            CtpTraderCallbackSourceTagsV2,
            build_callback_ingress_record_v2,
            callback_ingress_disposition,
            validate_expected_prelogin_step,
        )

        with self._query_state_lock:
            state = self._callback_ingress
            if state is not None:
                state.callback_refs += 1
        if state is None:
            original(spi, *args, **dict(kwargs))
            return _CALLBACK_INGRESS_SKIP_ORIGINAL

        record = None
        disposition = CtpTraderCallbackDisposition.POISON
        call_original_on_poison = callback_name == "OnFrontDisconnected"
        callback_failed = False
        try:
            with self._query_state_lock:
                if self._callback_ingress is not state or state.poisoned:
                    return _CALLBACK_INGRESS_SKIP_ORIGINAL
                state = self._callback_ingress
                if state is None:
                    callback_without_ingress = True
                    source_tags = None
                else:
                    callback_without_ingress = False
                    source_tags = getattr(spi, "_callback_source_tags", None)
                if callback_without_ingress:
                    pass
                elif type(source_tags) is not CtpTraderCallbackSourceTagsV2:
                    self._poison_callback_ingress_locked("source_identity_mismatch")
                    return _CALLBACK_INGRESS_SKIP_ORIGINAL
                else:
                    if state.poisoned or state.phase == "POISONED":
                        phase = CtpTraderCallbackPhase.POISONED
                    elif state.phase == "ACTIVE":
                        phase = CtpTraderCallbackPhase.ACTIVE
                    else:
                        phase = CtpTraderCallbackPhase.PRE_LOGIN

                    state.sequence += 1
                    try:
                        record = build_callback_ingress_record_v2(
                            owner_intent_id=state.owner_intent_id,
                            callback_name=callback_name,
                            source_phase=phase,
                            source_tags=source_tags,
                            source_sequence=state.sequence,
                            callback_monotonic_ns=time.monotonic_ns(),
                            connection_generation=self._connection_generation,
                            args=args,
                            kwargs=kwargs,
                        )
                    except BaseException:
                        self._poison_callback_ingress_locked("capture_incomplete")
                        return _CALLBACK_INGRESS_SKIP_ORIGINAL

                    if not record.capture_complete:
                        self._poison_callback_ingress_locked("capture_incomplete")
                        return _CALLBACK_INGRESS_SKIP_ORIGINAL

                    origin_tags = (
                        source_tags.source_instance_id,
                        source_tags.native_client_epoch,
                        source_tags.native_api_source_id,
                        source_tags.native_spi_source_id,
                        source_tags.native_api_generation,
                        source_tags.connection_generation,
                    )
                    current_origin = (
                        self._callback_source_instance_id,
                        self._native_client_epoch,
                        self._native_api_source_id,
                        getattr(self._spi, "_native_spi_source_id", None),
                        self._native_api_generation,
                        getattr(
                            getattr(self._spi, "_callback_source_tags", None),
                            "connection_generation",
                            None,
                        ),
                    )
                    poison_reason = None
                    if (
                        origin_tags != current_origin
                        or spi._native_api is not self._api
                        or spi is not self._spi
                        or origin_tags != state.current_source_tags
                    ):
                        poison_reason = "source_identity_mismatch"

                    active_query_request_id = None
                    active_query_kind = None
                    if phase is CtpTraderCallbackPhase.ACTIVE:
                        request_id_slot = 1 if callback_name == "OnRspError" else 2
                        raw_request_id = record.scalar_argument(request_id_slot)
                        accumulator = None
                        if type(raw_request_id) is int:
                            accumulator = self._query_history.get(raw_request_id)
                        if accumulator is not None:
                            active_query_request_id = raw_request_id
                            active_query_kind = _ctp_query_callback_name(
                                accumulator.request_type
                            )
                        if callback_name != "OnRspError" and active_query_kind != callback_name:
                            active_query_request_id = None
                            active_query_kind = None

                    disposition = callback_ingress_disposition(
                        record,
                        active_query_request_id=active_query_request_id,
                        active_query_kind=active_query_kind,
                    )
                    expected_prelogin = False
                    if phase is CtpTraderCallbackPhase.PRE_LOGIN:
                        if callback_name == "OnFrontConnected":
                            expected_prelogin = (
                                not state.prelogin_front_seen
                                and self._connection_generation == 0
                                and self._connected is False
                            )
                        elif callback_name == "OnRspAuthenticate":
                            expected_prelogin = (
                                state.prelogin_front_seen
                                and self._authentication_state == "authenticating"
                                and self._authentication_request_id == record.scalar_argument(2)
                                and self._authentication_connection_generation
                                == self._connection_generation
                                and validate_expected_prelogin_step(
                                    record,
                                    expected_callback_name=callback_name,
                                    expected_request_id=self._authentication_request_id,
                                    bound_broker_id=self._bound_broker_id,
                                    bound_user_id=self._bound_user_id,
                                )
                            )
                        elif callback_name == "OnRspUserLogin":
                            expected_prelogin = (
                                state.prelogin_front_seen
                                and self._authentication_state == "authenticated"
                                and self._login_state == "logging_in"
                                and self._login_request_id == record.scalar_argument(2)
                                and self._login_connection_generation == self._connection_generation
                                and validate_expected_prelogin_step(
                                    record,
                                    expected_callback_name=callback_name,
                                    expected_request_id=self._login_request_id,
                                    bound_broker_id=self._bound_broker_id,
                                    bound_user_id=self._bound_user_id,
                                )
                            )
                        if not expected_prelogin:
                            disposition = CtpTraderCallbackDisposition.POISON
                        elif callback_name == "OnFrontConnected":
                            state.prelogin_front_seen = True
                        elif callback_name == "OnRspUserLogin":
                            state.phase = "LOGIN_BIND_PENDING"
                            state.login_bind_pending = True
                        elif callback_name == "OnRspAuthenticate":
                            state.phase = "PRE_LOGIN"

                    try:
                        ack = state.append_sink.append(record)
                        if type(ack) is not CtpTraderCallbackIngressAckV2:
                            raise TypeError("callback ingress sink returned an untyped acknowledgement")
                        ack.validate_for(record)
                    except BaseException:
                        self._poison_callback_ingress_locked("append_commit_unknown")
                        return _CALLBACK_INGRESS_SKIP_ORIGINAL

                    if poison_reason is not None:
                        disposition = CtpTraderCallbackDisposition.POISON
                    if disposition is CtpTraderCallbackDisposition.POISON:
                        reason = poison_reason or (
                            "disconnect"
                            if callback_name == "OnFrontDisconnected"
                            else "unsupported_financial"
                            if record.callback_class is CtpTraderCallbackClass.UNSUPPORTED_FINANCIAL
                            else "lifecycle_transition"
                        )
                        self._poison_callback_ingress_locked(reason, source_tags=origin_tags)
                        call_original_on_poison = callback_name == "OnFrontDisconnected"

            if disposition is CtpTraderCallbackDisposition.POISON and not call_original_on_poison:
                return _CALLBACK_INGRESS_SKIP_ORIGINAL

            try:
                original(spi, *args, **dict(kwargs))
            except BaseException:
                with self._query_state_lock:
                    self._poison_callback_ingress_locked("callback_handler_error")
                callback_failed = True
                return _CALLBACK_INGRESS_SKIP_ORIGINAL

            pending_login_callback = None
            if callback_name == "OnRspUserLogin" and state.login_bind_pending:
                try:
                    self.bind_active_callback_session(state.owner_handle)
                except BaseException:
                    callback_failed = True
                    return _CALLBACK_INGRESS_SKIP_ORIGINAL
                with self._query_state_lock:
                    pending_login_callback = state.pending_login_callback
                    state.pending_login_callback = None
                if pending_login_callback is not None:
                    callback, field = pending_login_callback
                    try:
                        callback(field)
                    except BaseException:
                        with self._query_state_lock:
                            self._poison_callback_ingress_locked("callback_handler_error")
                        callback_failed = True
                        return _CALLBACK_INGRESS_SKIP_ORIGINAL
            return _CALLBACK_INGRESS_SKIP_ORIGINAL
        finally:
            with self._query_state_lock:
                current_state = self._callback_ingress
                if current_state is not None:
                    current_state.callback_refs = max(0, current_state.callback_refs - 1)
                    if callback_failed:
                        self._poison_callback_ingress_locked("callback_handler_error")
                    self._maybe_finish_deferred_native_release_locked()

    def _maybe_finish_deferred_native_release_locked(self) -> None:
        state = self._callback_ingress
        if (
            (state is not None and state.native_call_refs != 0)
            or (state is not None and state.callback_refs != 0)
            or self._callback_ingress_deferred_cleanup is None
            or self._callback_ingress_cleanup_scheduled
            or self._native_request_inflight_refs != 0
            or self._callback_inflight_refs != 0
        ):
            return
        self._callback_ingress_cleanup_scheduled = True
        thread = threading.Thread(
            target=self._finish_deferred_native_release,
            name="bt-api-ctp-ingress-release",
            daemon=True,
        )
        thread.start()

    def _finish_deferred_native_release(self) -> None:
        with self._query_state_lock:
            state = self._callback_ingress
            pending = self._callback_ingress_deferred_cleanup
            if (
                pending is None
                or (state is not None and state.native_call_refs != 0)
                or (state is not None and state.callback_refs != 0)
                or self._native_request_inflight_refs != 0
                or self._callback_inflight_refs != 0
            ):
                self._callback_ingress_cleanup_scheduled = False
                return
            api, spi, join_required, join_claimed = pending
            self._callback_ingress_deferred_cleanup = None
            self._callback_ingress_cleanup_scheduled = False

        # Native lifecycle operations run without SDK locks. The retained
        # exact API/SPI pair remains pinned until both callback and request
        # references have drained.
        if join_required or join_claimed:
            with suppress(Exception):
                _detach_ctp_native_spi_once(api)
            if _ctp_native_join_returned(api):
                if not _release_retired_ctp_native_session_after_join(api):
                    _release_ctp_native_api_immediately(
                        api,
                        spi,
                        state_lock=self._query_state_lock,
                        pending_api_ids=self._pending_native_join_api_ids,
                    )
            return
        _release_ctp_native_api_immediately(
            api,
            spi,
            state_lock=self._query_state_lock,
            pending_api_ids=self._pending_native_join_api_ids,
        )

    def _bound_identity_is_current(self, *, require_active_front: bool = False) -> bool:
        """Check that public compatibility attributes still name this session.

        This predicate deliberately has no side effects because readiness
        readers use it.  Mutating a public feed/client field may never switch
        the account or front used by an already authenticated managed session.
        """

        current_fingerprint = hashlib.sha256(
            f"{str(self.broker_id or '').strip()}:{str(self.user_id or '').strip()}".encode()
        ).hexdigest()[:16]
        if (
            str(self.front or "").strip() != self._bound_front
            or str(self.broker_id or "").strip() != self._bound_broker_id
            or str(self.user_id or "").strip() != self._bound_user_id
            or current_fingerprint != self._account_fingerprint
        ):
            return False
        return not require_active_front or self._session_native_front == self._bound_front

    def _require_bound_identity_locked(self, *, require_active_front: bool = False) -> None:
        """Fail closed before a managed native write can use mutable identity."""

        if not self._bound_identity_is_current(require_active_front=False):
            self._revoke_execution_gate_locked("ctp_execution_gate_account_identity_changed")
            raise CtpExecutionGateError("ctp_execution_gate_account_identity_changed")
        if require_active_front and self._session_native_front != self._bound_front:
            self._revoke_execution_gate_locked("ctp_execution_gate_front_profile_mismatch")
            raise CtpExecutionGateError("ctp_execution_gate_front_profile_mismatch")

    def _require_native_field_identity_locked(
        self,
        field: Any,
        *,
        require_user_id: bool,
    ) -> None:
        """Bind each typed order field to the immutable authenticated account."""

        self._require_bound_identity_locked(require_active_front=True)
        broker_id = str(getattr(field, "BrokerID", "") or "")
        investor_id = str(getattr(field, "InvestorID", "") or "")
        user_id = str(getattr(field, "UserID", "") or "")
        if (
            broker_id != self._bound_broker_id
            or investor_id != self._bound_user_id
            or (require_user_id and user_id != self._bound_user_id)
            or (not require_user_id and user_id and user_id != self._bound_user_id)
        ):
            self._revoke_execution_gate_locked("ctp_execution_gate_native_field_identity_mismatch")
            raise CtpExecutionGateError("ctp_execution_gate_native_field_identity_mismatch")

    def _require_native_field_identity_snapshot_locked(
        self,
        snapshot: _ManagedOrderActionFieldSnapshot,
        *,
        require_user_id: bool,
    ) -> None:
        """Validate account fields from the same detached read as the target."""

        self._require_bound_identity_locked(require_active_front=True)
        identity = snapshot.identity
        if (
            identity.broker_id != self._bound_broker_id
            or identity.investor_id != self._bound_user_id
            or (require_user_id and snapshot.user_id != self._bound_user_id)
            or (not require_user_id and snapshot.user_id and snapshot.user_id != self._bound_user_id)
        ):
            self._revoke_execution_gate_locked("ctp_execution_gate_native_field_identity_mismatch")
            raise CtpExecutionGateError("ctp_execution_gate_native_field_identity_mismatch")

    def _invoke_public_api_request(
        self,
        name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        """Resolve a cached public Req* callable at invocation time."""

        with self._query_state_lock:
            if self._callback_ingress is not None:
                raise CtpExecutionGateError("ctp_callback_ingress_typed_request_required")
            is_read_query = name.startswith(("ReqQry", "ReqQuery"))
            if not is_read_query:
                # Never expose native request writes through the public API
                # view.  A caller could otherwise cache ``ReqOrderInsert``
                # before the SDK installs its capability, then bypass the
                # typed final-gate check entirely.  Authentication/login
                # requests are internal lifecycle operations for the same
                # reason.
                raise CtpExecutionGateError("ctp_execution_gate_native_write_blocked")
            if self._execution_gate_capability is not None:
                # Managed callers must use the typed query methods so request
                # IDs, generation fencing and the one-query-at-a-time lock
                # cannot be bypassed through a cached native Req* handle.
                raise CtpExecutionGateError("ctp_execution_gate_raw_request_blocked")
            api = self._api
            if api is None:
                raise CtpExecutionGateError("ctp_execution_gate_native_api_unavailable")
            target = getattr(api, name)
        return target(*args, **kwargs)

    def _get_public_api_attribute(self, name: str) -> Any:
        """Resolve a non-request native attribute without storing it in the view."""

        with self._query_state_lock:
            api = self._api
            if api is None:
                raise AttributeError(name)
            return getattr(api, name)

    def _invoke_public_api_callable(
        self,
        name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        """Fence cached non-request native callables after gate installation."""

        if name not in _CTP_PUBLIC_NATIVE_READ_CALLS:
            # This guard applies before a managed capability is installed as
            # well.  Otherwise a caller could cache/use RegisterFront, Init
            # or Release on an unmanaged API, then promote that altered native
            # session into a managed execution session later.
            raise CtpExecutionGateError("ctp_execution_gate_native_lifecycle_blocked")
        with self._query_state_lock:
            api = self._api
            if api is None:
                raise CtpExecutionGateError("ctp_execution_gate_native_api_unavailable")
            target = getattr(api, name)
            if not callable(target):
                raise TypeError(f"native API attribute {name!r} is not callable")
        return target(*args, **kwargs)

    def _execution_gate_state_locked(self) -> dict[str, Any]:
        proof = self._execution_gate_proof
        return {
            "managed": self._execution_gate_capability is not None,
            "armed": proof is not None,
            "connection_generation": (
                proof.get("connection_generation") if proof is not None else None
            ),
            "trading_day": proof.get("trading_day") if proof is not None else None,
            "instrument": proof.get("instrument") if proof is not None else None,
            "scope_version": proof.get("scope_version") if proof is not None else None,
            "authorized_instruments": (
                list(proof["authorized_instruments"]) if _is_execution_gate_bundle(proof) else None
            ),
            "environment_profile": self._execution_gate_environment_profile,
            "proof_sha256": self._execution_gate_proof_sha256,
            "revocation_reason": self._execution_gate_revocation_reason,
        }

    def get_execution_gate_state(self) -> dict[str, Any]:
        """Return the managed native-order gate without exposing its capability."""

        with self._query_state_lock:
            return self._execution_gate_state_locked()

    def configure_execution_gate(self, capability: object) -> dict[str, Any]:
        """Install the SDK-owned opaque capability and start disarmed."""

        if not _is_ctp_core_execution_authority(capability):
            raise CtpExecutionGateError("ctp_execution_gate_capability_required")
        with self._query_state_lock:
            installed = self._execution_gate_capability
            if installed is not None and installed is not capability:
                raise CtpExecutionGateError("ctp_execution_gate_already_configured")
            if installed is None:
                self._execution_gate_capability = capability
                self._execution_gate_proof = None
                self._execution_gate_proof_sha256 = None
                self._execution_gate_environment_profile = None
                self._execution_gate_strategy_identity_sha256 = None
                self._execution_gate_cycle_id = None
                self._execution_gate_revocation_reason = None
            return self._execution_gate_state_locked()

    def _issue_execution_authorization_for_core(
        self,
        capability: object,
        proof: Mapping[str, Any],
        *,
        environment_profile: str,
        environment_verified: bool,
        strategy_identity_sha256: str,
        execution_cycle_id: str,
    ) -> object:
        """Create one native arm grant after the core has checked preflight.

        This intentionally private method is the only mapping-to-grant bridge.
        ``arm_execution_gate`` itself accepts the returned opaque grant, never
        a caller-provided proof mapping.  The grant is consumed by its first
        arm attempt, including a failed context check.
        """

        with self._query_state_lock:
            if not _is_ctp_core_execution_authority(capability):
                raise CtpExecutionGateError("ctp_execution_gate_capability_required")
            if capability is not self._execution_gate_capability:
                raise CtpExecutionGateError("ctp_execution_gate_capability_mismatch")
            self._require_bound_identity_locked(require_active_front=True)
            normalized, _proof_sha256 = _execution_gate_proof(proof)
            profile = str(environment_profile or "").strip()
            if self.auto_settlement_confirm is not False:
                raise CtpExecutionGateError("ctp_execution_gate_auto_settlement_confirm_enabled")
            if not self.is_trading_ready:
                raise CtpExecutionGateError("ctp_execution_gate_session_not_trading_ready")
            if (
                environment_verified is not True
                or not profile
                or profile != normalized["environment_profile"]
                or normalized["connection_generation"] != self._connection_generation
                or normalized["account_fingerprint"] != f"acct_{self._account_fingerprint}"
                or normalized["trading_day"] != self._trading_day
                or self._api is None
                or self._api is not self._session_native_api
            ):
                raise CtpExecutionGateError("ctp_execution_gate_authorization_context_mismatch")
            if (
                not isinstance(strategy_identity_sha256, str)
                or len(strategy_identity_sha256) != 64
                or any(char not in "0123456789abcdef" for char in strategy_identity_sha256)
                or not isinstance(execution_cycle_id, str)
                or not execution_cycle_id
                or execution_cycle_id != execution_cycle_id.strip()
                or len(execution_cycle_id) > 128
            ):
                raise CtpExecutionGateError("ctp_execution_gate_authorization_identity_invalid")
            return _CtpExecutionAuthorization(
                client=self,
                capability=capability,
                proof=normalized,
                environment_profile=profile,
                strategy_identity_sha256=strategy_identity_sha256,
                execution_cycle_id=execution_cycle_id,
                preflight_epoch=self._execution_preflight_epoch,
            )

    def _issue_settlement_authorization_for_core(
        self,
        capability: object,
        *,
        environment_profile: str,
        environment_verified: bool,
        scope: str = "settlement_confirmation",
        budget: int = 1,
    ) -> object:
        """Create one independent, account/day/generation-bound write grant."""

        with self._query_state_lock:
            if not _is_ctp_core_execution_authority(capability):
                raise CtpExecutionGateError("ctp_execution_gate_capability_required")
            if capability is not self._execution_gate_capability:
                raise CtpExecutionGateError("ctp_execution_gate_capability_mismatch")
            self._require_bound_identity_locked(require_active_front=True)
            profile = str(environment_profile or "").strip()
            if self.auto_settlement_confirm is not False:
                raise CtpExecutionGateError("ctp_execution_gate_auto_settlement_confirm_enabled")
            if (
                environment_verified is not True
                or not profile
                or self._execution_gate_proof is not None
                or not self.is_read_only_ready
                or self._connection_generation <= 0
                or not self._trading_day
                or self._api is None
                or self._api is not self._session_native_api
                or scope != "settlement_confirmation"
                or type(budget) is not int
                or budget != 1
            ):
                raise CtpExecutionGateError("ctp_settlement_authorization_context_mismatch")
            return _CtpSettlementAuthorization(
                client=self,
                capability=capability,
                account_fingerprint=f"acct_{self._account_fingerprint}",
                trading_day=self._trading_day,
                connection_generation=self._connection_generation,
                environment_profile=profile,
                scope=scope,
                budget=budget,
            )

    def _issue_execution_authorization_for_test(
        self,
        capability: object,
        proof: Mapping[str, Any],
        *,
        strategy_identity_sha256: str = "0" * 64,
        execution_cycle_id: str = "controlled-test-cycle",
    ) -> object:
        """Explicit offline-only issuer for native contract tests.

        It remains private and requires the separately marked test authority.
        ``arm_execution_gate`` itself never accepts a proof mapping, including
        in tests, so production and fixture call paths exercise the same
        opaque one-shot consumption boundary.
        """

        if not _is_ctp_test_execution_authority(capability):
            raise CtpExecutionGateError("ctp_execution_gate_authorization_required")
        profile = str(proof.get("environment_profile") or "").strip()
        return self._issue_execution_authorization_for_core(
            capability,
            proof,
            environment_profile=profile,
            environment_verified=True,
            strategy_identity_sha256=strategy_identity_sha256,
            execution_cycle_id=execution_cycle_id,
        )

    def _issue_settlement_authorization_for_test(
        self,
        capability: object,
        *,
        environment_profile: str = "controlled-test-environment",
    ) -> object:
        """Explicit offline-only issuer for a single settlement write."""

        if not _is_ctp_test_execution_authority(capability):
            raise CtpExecutionGateError("ctp_settlement_authorization_required")
        return self._issue_settlement_authorization_for_core(
            capability,
            environment_profile=environment_profile,
            environment_verified=True,
        )

    def _revoke_execution_gate_locked(self, reason: Any) -> None:
        if self._execution_gate_capability is None:
            return
        # A revocation must invalidate every independently issued, unconsumed
        # arm grant from this native preflight.  The issuer permits more than
        # one opaque grant for controlled core workflows, so clearing only the
        # currently armed proof would otherwise leave a sibling grant usable
        # on the same account/day/generation.
        self._execution_preflight_epoch = getattr(self, "_execution_preflight_epoch", 0) + 1
        self._execution_gate_proof = None
        self._execution_gate_proof_sha256 = None
        self._execution_gate_environment_profile = None
        self._execution_gate_strategy_identity_sha256 = None
        self._execution_gate_cycle_id = None
        self._execution_gate_native_api = None
        self._execution_gate_revocation_reason = _execution_gate_reason(reason)

    def _require_execution_write_locked(
        self,
        capability: object | None,
        instrument: Any,
        exchange_id: Any = None,
    ) -> None:
        installed = self._execution_gate_capability
        if installed is None:
            raise CtpExecutionGateError("ctp_execution_gate_capability_required")
        if capability is not installed:
            raise CtpExecutionGateError("ctp_execution_gate_capability_mismatch")
        self._require_bound_identity_locked(require_active_front=True)
        proof = self._execution_gate_proof
        if proof is None:
            raise CtpExecutionGateError("ctp_execution_gate_unarmed")
        mismatches = (
            (
                self._api is None
                or self._api is not self._execution_gate_native_api
                or self._api is not self._session_native_api,
                "ctp_execution_gate_native_api_mismatch",
            ),
            (
                self._connection_generation != proof["connection_generation"],
                "ctp_execution_gate_connection_generation_mismatch",
            ),
            (
                f"acct_{self._account_fingerprint}" != proof["account_fingerprint"],
                "ctp_execution_gate_account_fingerprint_mismatch",
            ),
            (
                self._trading_day != proof["trading_day"],
                "ctp_execution_gate_trading_day_mismatch",
            ),
            (
                not self.is_trading_ready,
                "ctp_execution_gate_session_not_trading_ready",
            ),
            (
                _canonical_execution_gate_instrument(
                    proof,
                    instrument,
                    exchange_id,
                    native_wire=True,
                )
                not in _execution_gate_instruments(proof),
                "ctp_execution_gate_instrument_mismatch",
            ),
        )
        for mismatched, code in mismatches:
            if mismatched:
                self._revoke_execution_gate_locked(code)
                raise CtpExecutionGateError(code)

    def require_execution_write(
        self,
        capability: object | None,
        instrument: Any,
        exchange_id: Any = None,
    ) -> None:
        """Reject a managed order write before request IDs or native calls change."""

        with self._query_state_lock:
            self._require_execution_write_locked(capability, instrument, exchange_id)

    def arm_execution_gate(
        self,
        capability: object,
        authorization: object,
        *,
        _environment_profile: object | None = None,
        _environment_verified: object = False,
    ) -> dict[str, Any]:
        """Consume one core-issued grant to bind native order writes.

        A proof mapping is intentionally rejected here.  Public session state
        and its hashes are evidence only; they cannot establish a native write
        permission without the private, one-shot authorization created by the
        core-owned issuer above.
        """

        with self._query_state_lock:
            if (
                not _is_ctp_core_execution_authority(capability)
                or capability is not self._execution_gate_capability
            ):
                raise CtpExecutionGateError("ctp_execution_gate_capability_mismatch")
            try:
                if (
                    type(authorization) is not _CtpExecutionAuthorization
                    or authorization._seal is not _CTP_EXECUTION_AUTHORIZATION_SEAL
                    or authorization._client_ref() is not self
                    or authorization._capability is not capability
                    or authorization._used
                ):
                    raise CtpExecutionGateError("ctp_execution_gate_authorization_required")
                self._require_bound_identity_locked(require_active_front=True)
                normalized, proof_sha256 = _execution_gate_proof(authorization._proof)
                profile = authorization._environment_profile
                if (
                    authorization._preflight_epoch != self._execution_preflight_epoch
                    or not profile
                    or profile != normalized["environment_profile"]
                    or _environment_verified is not True
                    or str(_environment_profile or "").strip() != profile
                ):
                    raise CtpExecutionGateError("ctp_execution_gate_environment_profile_mismatch")
                if self.auto_settlement_confirm is not False:
                    raise CtpExecutionGateError(
                        "ctp_execution_gate_auto_settlement_confirm_enabled"
                    )
                if normalized["connection_generation"] != self._connection_generation:
                    raise CtpExecutionGateError("ctp_execution_gate_connection_generation_mismatch")
                if normalized["account_fingerprint"] != f"acct_{self._account_fingerprint}":
                    raise CtpExecutionGateError("ctp_execution_gate_account_fingerprint_mismatch")
                if normalized["trading_day"] != self._trading_day:
                    raise CtpExecutionGateError("ctp_execution_gate_trading_day_mismatch")
                if self._api is None or self._api is not self._session_native_api:
                    raise CtpExecutionGateError("ctp_execution_gate_native_api_mismatch")
                if not self.is_trading_ready:
                    raise CtpExecutionGateError("ctp_execution_gate_session_not_trading_ready")
                if self._execution_gate_proof is not None:
                    raise CtpExecutionGateError("ctp_execution_gate_already_armed")
            except CtpExecutionGateError as exc:
                if type(authorization) is _CtpExecutionAuthorization:
                    authorization._used = True
                self._revoke_execution_gate_locked(exc.code)
                raise
            authorization._used = True
            self._execution_gate_proof = normalized
            self._execution_gate_proof_sha256 = proof_sha256
            self._execution_gate_environment_profile = profile
            self._execution_gate_strategy_identity_sha256 = authorization._strategy_identity_sha256
            self._execution_gate_cycle_id = authorization._execution_cycle_id
            self._execution_gate_native_api = self._api
            self._execution_gate_revocation_reason = None
            return self._execution_gate_state_locked()

    def disarm_execution_gate(
        self,
        capability: object,
        reason: str = "execution_arm_revoked",
    ) -> dict[str, Any]:
        """Idempotently revoke managed native order writes."""

        with self._query_state_lock:
            if capability is not self._execution_gate_capability:
                raise CtpExecutionGateError("ctp_execution_gate_capability_mismatch")
            bounded_reason = _execution_gate_reason(reason)
            if self._execution_gate_proof is not None:
                self._revoke_execution_gate_locked(bounded_reason)
            else:
                # An explicit disarm is also a revocation boundary when no
                # proof is currently armed: sibling opaque grants may still
                # exist and must require a new preflight.
                self._execution_preflight_epoch = getattr(self, "_execution_preflight_epoch", 0) + 1
                if self._execution_gate_revocation_reason is None:
                    self._execution_gate_revocation_reason = bounded_reason
            return self._execution_gate_state_locked()

    def arm_execution_for_registered_sim(
        self,
        *,
        instrument_id: str,
        exchange_id: str = "",
        md_front: str = "",
        strategy_identity_sha256: str,
        execution_cycle_id: str,
        preflight_sha256: str,
        settlement_timeout: float = 15.0,
    ) -> tuple[object, dict[str, Any]]:
        """Arm native order writes for a registered broker simulation front.

        This is the typed admission entry for direct (non-SDK-managed) CTP
        callers that run against a broker-provided *simulation* front whose
        endpoint pair is frozen in ``ctp_env_selector``'s registered broker
        simulation registry.  It grants the same invariants the SimNow demo
        path grants — bound identity, settlement-confirm disabled, a
        trading-ready session, a one-shot arm, and per-write revalidation —
        and can never arm a production front because the session's TD front
        must match a frozen registry entry exactly.

        Sequence (each step fail-closed):
          1. prove bound identity + registered front pair (disarmed);
          2. install the core capability;
          3. if the session is not trading-ready yet, submit the explicitly
             authorized settlement confirmation and verify the server
             readback (settlement grants require a disarmed gate);
          4. issue the one-shot execution authorization and arm.

        Returns ``(capability, gate_state)``; the opaque capability must be
        passed to ``submit_order_insert``/``submit_order_action``.  Arming is
        idempotent while the current arm already authorizes the instrument.
        """
        from bt_api_ctp.ctp_env_selector import (
            registered_broker_sim_profile_for_td_front,
            verify_registered_broker_sim_profile,
        )

        def _require_hash(value: Any, code: str) -> str:
            text = str(value or "").strip().lower()
            if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
                raise CtpExecutionGateError(code)
            return text

        # ---- Phase 1: identity/environment proof, capability, idempotency ----
        with self._query_state_lock:
            self._require_bound_identity_locked(require_active_front=True)
            profile = registered_broker_sim_profile_for_td_front(self._bound_front)
            if not profile:
                raise CtpExecutionGateError("ctp_execution_gate_environment_unverified")
            if md_front and not verify_registered_broker_sim_profile(
                self._bound_front, md_front, profile
            ):
                raise CtpExecutionGateError("ctp_execution_gate_environment_unverified")
            if self.auto_settlement_confirm is not False:
                raise CtpExecutionGateError(
                    "ctp_execution_gate_auto_settlement_confirm_enabled"
                )

            instrument = canonical_ctp_instrument(instrument_id, exchange_id)
            if not instrument:
                raise CtpExecutionGateError("ctp_execution_gate_invalid_proof")

            capability = self._execution_gate_capability
            if capability is None:
                capability = _issue_ctp_execution_authority_for_core()
                self.configure_execution_gate(capability)
            if (
                self._execution_gate_proof is not None
                and self._execution_gate_revocation_reason is None
                and self._execution_gate_environment_profile == profile
                and instrument in _execution_gate_instruments(self._execution_gate_proof)
            ):
                return capability, dict(self._execution_gate_state_locked())

        # ---- Phase 2: settlement confirmation (needs a disarmed gate) ----
        # Both calls wait on server callbacks, so they must not run under the
        # query lock.
        if not self.is_trading_ready:
            with self._query_state_lock:
                settlement_authorization = self._issue_settlement_authorization_for_core(
                    capability,
                    environment_profile=profile,
                    environment_verified=True,
                )
            confirmed = self.confirm_settlement(
                max(float(settlement_timeout), 0.0),
                _execution_capability=capability,
                _settlement_authorization=settlement_authorization,
                _settlement_environment_profile=profile,
                _settlement_environment_verified=True,
            )
            if confirmed:
                self.verify_settlement_confirmation(
                    timeout=max(float(settlement_timeout), 0.0)
                )
            if not self.is_trading_ready:
                raise CtpExecutionGateError(
                    "ctp_execution_gate_settlement_not_confirmed"
                )

        # ---- Phase 3: one-shot execution authorization + arm ----
        with self._query_state_lock:
            self._require_bound_identity_locked(require_active_front=True)
            if registered_broker_sim_profile_for_td_front(self._bound_front) != profile:
                raise CtpExecutionGateError("ctp_execution_gate_environment_unverified")
            if not self.is_trading_ready:
                raise CtpExecutionGateError(
                    "ctp_execution_gate_session_not_trading_ready"
                )

            preflight = _require_hash(preflight_sha256, "ctp_execution_gate_invalid_proof")
            strategy_identity = _require_hash(
                strategy_identity_sha256,
                "ctp_execution_gate_authorization_identity_invalid",
            )
            cycle_id = str(execution_cycle_id or "").strip()
            if not cycle_id or cycle_id != execution_cycle_id or len(cycle_id) > 128:
                raise CtpExecutionGateError(
                    "ctp_execution_gate_authorization_identity_invalid"
                )

            native_digest = self._registered_sim_file_digest(
                "bt_api_ctp.ctp._ctp", "ctp_execution_gate_sim_measurement_unavailable"
            )
            package_digest = self._registered_sim_file_digest(
                "bt_api_ctp.ctp.client", "ctp_execution_gate_sim_measurement_unavailable"
            )
            source_digest = self._registered_sim_file_digest(
                "bt_api_ctp.ctp_env_selector",
                "ctp_execution_gate_sim_measurement_unavailable",
            )
            receipt = hashlib.sha256(
                "|".join(
                    (
                        "registered-sim",
                        strategy_identity,
                        cycle_id,
                        profile,
                        instrument,
                        str(self._trading_day),
                        str(self._connection_generation),
                    )
                ).encode("utf-8")
            ).hexdigest()
            dependency_digest = hashlib.sha256(
                (native_digest + package_digest + source_digest).encode("ascii")
            ).hexdigest()
            proof = {
                "account_fingerprint": f"acct_{self._account_fingerprint}",
                "trading_day": self._trading_day,
                "instrument": instrument,
                "connection_generation": self._connection_generation,
                "environment_profile": profile,
                "preflight_sha256": preflight,
                "receipt_sha256": receipt,
                "native_sha256": native_digest,
                "ctp_package_sha256": package_digest,
                "source_hashes_sha256": source_digest,
                "dependency_hashes_sha256": dependency_digest,
            }
            authorization = self._issue_execution_authorization_for_core(
                capability,
                proof,
                environment_profile=profile,
                environment_verified=True,
                strategy_identity_sha256=strategy_identity,
                execution_cycle_id=cycle_id,
            )
            state = self.arm_execution_gate(
                capability,
                authorization,
                _environment_profile=profile,
                _environment_verified=True,
            )
            return capability, dict(state)

    @staticmethod
    def _registered_sim_file_digest(module_name: str, error_code: str) -> str:
        """Measure one shipped module file for the registered-sim proof."""
        module = sys.modules.get(module_name)
        if module is None:
            import importlib

            try:
                module = importlib.import_module(module_name)
            except Exception as exc:  # pragma: no cover - measurement is optional at import time
                raise CtpExecutionGateError(error_code) from exc
        path = getattr(module, "__file__", "")
        if not path or not os.path.isfile(path):
            raise CtpExecutionGateError(error_code)
        digest = hashlib.sha256()
        try:
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise CtpExecutionGateError(error_code) from exc
        return digest.hexdigest()

    def submit_order_insert(
        self,
        field: Any,
        request_id: int,
        *,
        execution_capability: object | None = None,
    ) -> Any:
        """Submit one order under the same lock as the final managed-gate check."""

        with self._query_state_lock:
            if self._callback_ingress is not None:
                raise CtpExecutionGateError("ctp_managed_native_call_lease_required")
            self._require_execution_write_locked(
                execution_capability,
                getattr(field, "InstrumentID", ""),
                getattr(field, "ExchangeID", ""),
            )
            self._require_native_field_identity_locked(field, require_user_id=True)
            api = self._api
            if api is None:
                raise CtpExecutionGateError("ctp_execution_gate_native_api_unavailable")
            self._record_request("order_insert")
        return self._invoke_session_native_request(api, "ReqOrderInsert", field, request_id)

    def submit_order_action(
        self,
        field: Any,
        request_id: int,
        *,
        execution_capability: object | None = None,
        runtime_order_id: str | None = None,
        managed_intent_id: str | None = None,
        runtime_action_id: str | None = None,
        managed_cancel_intent_id: str | None = None,
    ) -> Any:
        """Submit one gated cancellation and retain its exact callback target.

        Supplying the managed identity tuple opts into the strict I9 target
        contract. Calls that omit it preserve the legacy OrderRef/OrderSysID
        target alternatives for existing public callers.
        """

        managed_cancel = _validate_managed_cancel_identity(
            runtime_order_id=runtime_order_id,
            managed_intent_id=managed_intent_id,
            runtime_action_id=runtime_action_id,
            managed_cancel_intent_id=managed_cancel_intent_id,
        )

        with self._query_state_lock:
            if self._callback_ingress is not None:
                raise CtpExecutionGateError("ctp_managed_native_call_lease_required")
            if type(request_id) is not int or request_id <= 0:
                raise CtpExecutionGateError("ctp_execution_gate_cancel_request_id_invalid")
            if managed_cancel:
                snapshot = _managed_order_action_field_snapshot(field)
                identity = snapshot.identity
                self._require_execution_write_locked(
                    execution_capability,
                    identity.instrument_id,
                    identity.exchange_id,
                )
                self._require_native_field_identity_snapshot_locked(
                    snapshot,
                    require_user_id=False,
                )
                api = self._api
                if api is None:
                    raise CtpExecutionGateError("ctp_execution_gate_native_api_unavailable")
                _validate_managed_cancel_native_fields(snapshot, request_id)
                request_field = _copy_managed_order_action_field(field, snapshot)
            else:
                self._require_execution_write_locked(
                    execution_capability,
                    getattr(field, "InstrumentID", ""),
                    getattr(field, "ExchangeID", ""),
                )
                self._require_native_field_identity_locked(field, require_user_id=False)
                api = self._api
                if api is None:
                    raise CtpExecutionGateError("ctp_execution_gate_native_api_unavailable")
                identity = _order_action_identity(field)
                request_field = field
            key = (request_id, identity.order_action_ref)
            order_identity_present = bool(
                (identity.order_ref and identity.front_id and identity.session_id)
                or (identity.order_sys_id and identity.exchange_id)
            )
            if (
                identity.field_request_id != request_id
                or not identity.order_action_ref
                or identity.action_flag != "0"
                or not order_identity_present
                or self._connection_generation <= 0
                or not self._trading_day
            ):
                raise CtpExecutionGateError("ctp_execution_gate_cancel_request_invalid")
            if key in self._order_action_history:
                raise CtpExecutionGateError("ctp_execution_gate_cancel_request_identity_reused")
            if any(
                known_request_id == request_id for known_request_id, _ in self._order_action_history
            ):
                raise CtpExecutionGateError("ctp_execution_gate_cancel_request_id_reused")
            if (
                managed_cancel
                and managed_cancel_intent_id in self._managed_cancel_actions_seen
            ):
                raise CtpExecutionGateError("ctp_execution_gate_managed_cancel_action_reused")

            now = datetime.now(timezone.utc)
            self._order_action_history[key] = CtpOrderActionEvidence(
                request_id=request_id,
                order_action_ref=identity.order_action_ref,
                status="unknown",
                account_fingerprint=f"acct_{self._account_fingerprint}",
                trading_day=self._trading_day,
                connection_generation=self._connection_generation,
                order_ref=identity.order_ref,
                order_sys_id=identity.order_sys_id,
                front_id=identity.front_id or 0,
                session_id=identity.session_id or 0,
                instrument_id=identity.instrument_id,
                exchange_id=identity.exchange_id,
                action_flag=identity.action_flag,
                evidence_source="",
                callback_received=False,
                evidence_received=False,
                error_code=None,
                error_message="",
                reason="awaiting_native_callback",
                submitted_at_utc=now,
                observed_at_utc=None,
                submit_code=None,
            )
            self._order_action_identities[key] = identity
            if managed_cancel:
                # Reserve before native dispatch: an exception can mean the
                # provider saw the request, so this action ID is never retried.
                self._managed_cancel_actions_seen.add(managed_cancel_intent_id)
            self._record_request("order_action")
        try:
            ret = self._invoke_session_native_request(
                api,
                "ReqOrderAction",
                request_field,
                request_id,
            )
        except Exception:
            with self._query_state_lock:
                if key in self._order_action_history:
                    self._order_action_history[key] = replace(
                        self._order_action_history[key], reason="native_submit_exception"
                    )
            raise
        try:
            submit_code = int(ret) if ret is not None else None
        except (TypeError, ValueError, OverflowError):
            submit_code = None
        with self._query_state_lock:
            if key in self._order_action_history:
                self._order_action_history[key] = replace(
                    self._order_action_history[key], submit_code=submit_code
                )
        return ret

    def get_order_action_evidence(
        self,
        request_id: int,
        *,
        order_action_ref: str | int | None = None,
    ) -> CtpOrderActionEvidence | None:
        try:
            normalized_request_id = int(request_id)
        except (TypeError, ValueError, OverflowError):
            return None
        with self._query_state_lock:
            if order_action_ref is None:
                matches = [
                    value
                    for (known_request_id, _), value in self._order_action_history.items()
                    if known_request_id == normalized_request_id
                ]
                return matches[0] if len(matches) == 1 else None
            return self._order_action_history.get((normalized_request_id, str(order_action_ref)))

    def _handle_order_return(self, field: Any, *, origin_api: Any, origin_spi: _TraderSpi) -> None:
        callback = None
        with self._query_state_lock:
            if origin_spi._native_api is not origin_api or not origin_spi._is_current_locked():
                return
            if origin_api is not None:
                self._record_native_callback_event(
                    origin_spi,
                    event_type="OnRtnOrder",
                    native_field=field,
                    field_names=_TRADER_ORDER_CALLBACK_FIELDS,
                )
            snapshot = _snapshot_ctp_field(field)
            if snapshot:
                self._order_events.put(snapshot)
            callback = self.on_order
        if callback is not None:
            callback(field)

    def _handle_order_action_callback(
        self,
        *,
        source: str,
        field: Any,
        rsp_info: Any,
        request_id: Any,
        is_last: Any,
        origin_api: Any,
        origin_spi: _TraderSpi,
    ) -> None:
        if type(is_last) is not bool:
            is_last = None

        error_callback = None
        with self._query_state_lock:
            if origin_spi._native_api is not origin_api or not origin_spi._is_current_locked():
                return

            identity = _order_action_identity(field)
            error_code, error_message = _rsp_error(rsp_info)
            request_value = (
                _native_int_field(field, "RequestID")
                if source == "OnErrRtnOrderAction" and request_id is None
                else request_id
            )
            try:
                normalized_request_id = int(request_value)
            except (TypeError, ValueError, OverflowError):
                normalized_request_id = None

            # Both source provenance and the typed target result are recorded
            # before releasing the API-generation lock. A replacement cannot
            # split one callback across two generations.
            if origin_api is not None:
                self._record_native_callback_event(
                    origin_spi,
                    event_type=source,
                    native_field=field,
                    field_names=_TRADER_ORDER_ACTION_CALLBACK_FIELDS,
                    rsp_info=rsp_info,
                    callback_fields=(
                        (("nRequestID", request_id), ("bIsLast", is_last))
                        if source == "OnRspOrderAction"
                        else ()
                    ),
                )

            if source == "OnRspOrderAction":
                candidates = [
                    key
                    for key in self._order_action_history
                    if normalized_request_id is not None and key[0] == normalized_request_id
                ]
                if len(candidates) != 1:
                    candidates = [key for key in candidates if key[1] == identity.order_action_ref]
            else:
                candidates = [
                    key for key in self._order_action_history if key[1] == identity.order_action_ref
                ]
                if identity.field_request_id not in (None, 0):
                    candidates = [key for key in candidates if key[0] == identity.field_request_id]
                exact_candidates = [
                    key for key in candidates if self._order_action_identities[key] == identity
                ]
                if exact_candidates:
                    candidates = exact_candidates

            if len(candidates) == 1:
                key = candidates[0]
                evidence = self._order_action_history[key]
                expected_identity = self._order_action_identities[key]
                identity_matches = expected_identity == identity
                scope_matches = (
                    evidence.account_fingerprint == f"acct_{self._account_fingerprint}"
                    and evidence.connection_generation == self._connection_generation
                    and evidence.trading_day == self._trading_day
                )
                order_identity_present = bool(
                    (identity.order_ref and identity.front_id and identity.session_id)
                    or (identity.order_sys_id and identity.exchange_id)
                )
                if evidence.status != "unknown" and (not identity_matches or not scope_matches):
                    self._order_action_late_callback_count += 1
                else:
                    updated = replace(
                        evidence,
                        evidence_source=source,
                        callback_received=True,
                        evidence_received=identity_matches and scope_matches,
                        error_code=error_code,
                        error_message=error_message,
                        observed_at_utc=datetime.now(timezone.utc),
                    )
                    if not identity_matches:
                        reason, status = "callback_identity_mismatch", "unknown"
                    elif identity.field_request_id != evidence.request_id:
                        reason, status = "native_request_id_mismatch", "unknown"
                        updated = replace(updated, evidence_received=False)
                    elif not scope_matches:
                        reason, status = "callback_session_scope_mismatch", "unknown"
                        updated = replace(updated, evidence_received=False)
                    elif not order_identity_present:
                        reason, status = "native_order_identity_incomplete", "unknown"
                        updated = replace(updated, evidence_received=False)
                    elif identity.action_flag != "0":
                        reason, status = "action_flag_not_cancel", "unknown"
                        updated = replace(updated, evidence_received=False)
                    elif error_code is None:
                        reason, status = "native_response_info_missing", "unknown"
                    elif source == "OnRspOrderAction" and is_last is not True:
                        reason, status = "native_response_not_terminal", "unknown"
                    elif error_code != 0:
                        reason, status = "native_cancel_rejected", "rejected"
                    elif source == "OnErrRtnOrderAction":
                        reason, status = "native_error_return_without_error_code", "unknown"
                    else:
                        reason, status = "cancel_request_accepted", "accepted"
                    if evidence.status == "rejected" and status == "accepted":
                        reason, status = evidence.reason, "rejected"
                    elif evidence.status == "accepted" and status == "unknown":
                        reason, status = evidence.reason, "accepted"
                    self._order_action_history[key] = replace(updated, status=status, reason=reason)
            else:
                self._order_action_late_callback_count += 1

            error_payload = {
                "event": "order_action_response"
                if source == "OnRspOrderAction"
                else "order_action_error",
                "request_id": normalized_request_id,
                "error_id": error_code if error_code is not None else 0,
                "error_msg": error_message,
                "field": _snapshot_ctp_field(field),
            }
            self._error_events.put(error_payload)
            error_callback = self.on_error if rsp_info is not None else None
        if error_callback is not None:
            error_callback(rsp_info)

    def _next_request_id(self) -> int:
        with self._query_state_lock:
            self._req_id += 1
            return self._req_id

    def _record_request(self, request_type: str) -> None:
        with self._query_state_lock:
            self._request_counts[request_type] = self._request_counts.get(request_type, 0) + 1

    def _clear_settlement_readback_locked(
        self,
        reason: str,
        *,
        request_id: int | None = None,
    ) -> None:
        """Invalidate server-readback proof and revoke any native write grant."""

        self._ready = False
        self._settlement_readback_verified = False
        self._settlement_proof_source = "none"
        self._settlement_proof_query_request_id = None
        self._last_session_error = {
            "error": reason,
            "query_request_id": request_id,
        }
        self._revoke_execution_gate_locked(reason)

    def _has_current_settlement_readback_locked(self) -> bool:
        return (
            self._settlement_readback_verified
            and self._settlement_proof_source == "confirmation_query"
            and self._settlement_proof_query_request_id is not None
            and self._settlement_connection_generation == self._connection_generation
            and self._settlement_account_fingerprint == self._account_fingerprint
            and self._settlement_trading_day == self._trading_day
        )

    def _on_front_connected(self) -> None:
        with self._query_state_lock:
            self._revoke_execution_gate_locked("ctp_execution_gate_connection_generation_changed")
            self._session_native_api = self._api
            # The registered front is fixed by start(); a reconnect does not
            # accept a mutable public ``front`` replacement.
            self._session_native_front = self._bound_front
            self._connection_generation += 1
            self._execution_preflight_epoch += 1
            self._connected = True
            self._ready = False
            self._authentication_state = "authenticating"
            self._login_state = "not_started"
            self._login_identity_observation = None
            self._trading_day = ""
            self._authentication_request_id = None
            self._authentication_connection_generation = None
            self._login_request_id = None
            self._login_connection_generation = None
            self._settlement_state = "unknown"
            self._settlement_request_id = None
            self._settlement_connection_generation = None
            self._settlement_account_fingerprint = None
            self._settlement_trading_day = None
            self._settlement_proof_source = "none"
            self._settlement_proof_query_request_id = None
            self._settlement_readback_verified = False
            self._last_session_error = {}

    def _on_front_disconnected(self, reason: Any) -> None:
        with self._query_state_lock:
            self._revoke_execution_gate_locked("ctp_execution_gate_disconnected")
            self._session_native_api = None
            self._session_native_front = None
            self._execution_preflight_epoch += 1
            self._connected = False
            self._ready = False
            self._authentication_state = "disconnected"
            self._login_state = "disconnected"
            self._login_identity_observation = None
            self._trading_day = ""
            self._authentication_request_id = None
            self._authentication_connection_generation = None
            self._login_request_id = None
            self._login_connection_generation = None
            self._settlement_state = "unknown"
            self._settlement_request_id = None
            self._settlement_connection_generation = None
            self._settlement_account_fingerprint = None
            self._settlement_trading_day = None
            self._settlement_proof_source = "none"
            self._settlement_proof_query_request_id = None
            self._settlement_readback_verified = False
            self._last_session_error = {"disconnect_reason": reason}
            for accumulator in self._query_history.values():
                if accumulator.sealed:
                    continue
                accumulator.error_code = -2
                accumulator.error_message = "connection_lost"
                accumulator.completed_at_utc = datetime.now(timezone.utc)
                accumulator.sealed = True
                accumulator.event.set()

    def _require_settlement_write_locked(
        self,
        execution_capability: object | None,
        settlement_authorization: object | None,
        settlement_environment_profile: object | None,
        settlement_environment_verified: object,
    ) -> _CtpSettlementAuthorization:
        installed = self._execution_gate_capability
        if installed is None or not _is_ctp_core_execution_authority(installed):
            raise CtpExecutionGateError("ctp_execution_gate_capability_required")
        if execution_capability is not installed:
            raise CtpExecutionGateError("ctp_execution_gate_capability_mismatch")
        self._require_bound_identity_locked(require_active_front=True)
        if (
            type(settlement_authorization) is not _CtpSettlementAuthorization
            or settlement_authorization._seal is not _CTP_EXECUTION_AUTHORIZATION_SEAL
            or settlement_authorization._client_ref() is not self
            or settlement_authorization._capability is not installed
            or settlement_authorization._used
            or settlement_authorization._scope != "settlement_confirmation"
            or settlement_authorization._budget != 1
            or settlement_authorization._connection_generation != self._connection_generation
            or settlement_authorization._account_fingerprint != f"acct_{self._account_fingerprint}"
            or settlement_authorization._trading_day != self._trading_day
            or settlement_environment_verified is not True
            or str(settlement_environment_profile or "").strip()
            != settlement_authorization._environment_profile
        ):
            raise CtpExecutionGateError("ctp_settlement_authorization_required")
        if self.auto_settlement_confirm is not False:
            raise CtpExecutionGateError("ctp_execution_gate_auto_settlement_confirm_enabled")
        if self._execution_gate_proof is not None:
            raise CtpExecutionGateError("ctp_execution_gate_settlement_requires_disarmed")
        if not self.is_read_only_ready or self._connection_generation <= 0 or not self._trading_day:
            raise CtpExecutionGateError("ctp_execution_gate_session_not_read_only_ready")
        if self._api is None or self._api is not self._session_native_api:
            raise CtpExecutionGateError("ctp_execution_gate_native_api_mismatch")
        return settlement_authorization

    def _request_settlement_confirmation(
        self,
        *,
        execution_capability: object | None = None,
        settlement_authorization: object | None = None,
        settlement_environment_profile: object | None = None,
        settlement_environment_verified: object = False,
        expected_generation: int | None = None,
    ) -> bool:
        with self._query_state_lock:
            authorization = self._require_settlement_write_locked(
                execution_capability,
                settlement_authorization,
                settlement_environment_profile,
                settlement_environment_verified,
            )
            if (
                expected_generation is not None
                and expected_generation != self._connection_generation
            ):
                return False
            if self._settlement_state == "confirmed":
                return True
            if (
                self._execution_gate_capability is not None
                and self._settlement_request_id is not None
            ):
                # One managed confirmation attempt is allowed per connection.
                return self._settlement_state == "confirming"
            api = self._api
            if api is None:
                raise CtpExecutionGateError("ctp_execution_gate_native_api_unavailable")
            # The terminal write consumes its independently issued budget and
            # invalidates every arm token/proof issued from the preceding
            # preflight epoch before a native method can run.
            authorization._used = True
            self._execution_preflight_epoch += 1
            self._revoke_execution_gate_locked("ctp_settlement_confirmation_invalidated_preflight")
            field = CThostFtdcSettlementInfoConfirmField()
            field.BrokerID = self._bound_broker_id
            field.InvestorID = self._bound_user_id
            request_id = self._next_request_id()
            self._settlement_done.clear()
            self._settlement_state = "confirming"
            self._settlement_request_id = request_id
            self._settlement_connection_generation = self._connection_generation
            self._settlement_account_fingerprint = self._account_fingerprint
            self._settlement_trading_day = self._trading_day
            self._ready = False
            self._settlement_readback_verified = False
            self._record_request("settlement_confirm")
            generation = self._connection_generation
        try:
            ret = self._invoke_session_native_request(
                api,
                "ReqSettlementInfoConfirm",
                field,
                request_id,
                settlement_authorization=authorization,
            )
        except Exception as exc:
            with self._query_state_lock:
                if (
                    self._settlement_state == "confirming"
                    and self._settlement_request_id == request_id
                    and self._settlement_connection_generation == generation
                    and self._connection_generation == generation
                ):
                    self._settlement_state = "failed"
                    self._last_session_error = {
                        "error": "settlement_confirm_submit_failed",
                        "detail": type(exc).__name__,
                    }
            return False
        if ret not in (None, 0):
            with self._query_state_lock:
                if (
                    self._settlement_state == "confirming"
                    and self._settlement_request_id == request_id
                    and self._settlement_connection_generation == generation
                    and self._connection_generation == generation
                ):
                    self._settlement_state = "failed"
                    self._last_session_error = {
                        "error": "settlement_confirm_submit_rejected",
                        "submit_code": ret,
                    }
            return False
        with self._query_state_lock:
            if self._connection_generation != generation:
                return False
            if self._settlement_request_id != request_id:
                return False
            if self._settlement_state == "failed":
                return False
            return True

    def _accept_settlement_callback(self, request_id: int, field: Any = None) -> bool:
        """Fence confirmation responses by request, generation and pending state."""
        with self._query_state_lock:
            accepted = (
                self._settlement_state == "confirming"
                and self._settlement_request_id == int(request_id)
                and self._settlement_connection_generation == self._connection_generation
                and self._settlement_account_fingerprint == self._account_fingerprint
                and self._settlement_trading_day == self._trading_day
            )
            field_broker = str(getattr(field, "BrokerID", "") or "")
            field_investor = str(getattr(field, "InvestorID", "") or "")
            field_trading_day = str(
                getattr(field, "TradingDay", "") or getattr(field, "ConfirmDate", "") or ""
            )
            if field_broker and field_broker != self._bound_broker_id:
                accepted = False
            if field_investor and field_investor != self._bound_user_id:
                accepted = False
            if field_trading_day and field_trading_day != self._trading_day:
                accepted = False
            if not accepted:
                self._settlement_late_callback_count += 1
                return False
            return True

    def confirm_settlement(
        self,
        timeout: float = 5.0,
        *,
        _execution_capability: object | None = None,
        _settlement_authorization: object | None = None,
        _settlement_environment_profile: object | None = None,
        _settlement_environment_verified: object = False,
    ) -> bool:
        """Submit confirmation; trading stays read-only until server readback."""
        with self._query_state_lock:
            self._require_settlement_write_locked(
                _execution_capability,
                _settlement_authorization,
                _settlement_environment_profile,
                _settlement_environment_verified,
            )
            if not self.is_read_only_ready:
                return False
            if self._settlement_state == "confirmed":
                return True
        if not self._request_settlement_confirmation(
            execution_capability=_execution_capability,
            settlement_authorization=_settlement_authorization,
            settlement_environment_profile=_settlement_environment_profile,
            settlement_environment_verified=_settlement_environment_verified,
        ):
            return False
        if not self._settlement_done.wait(max(float(timeout), 0.0)):
            with self._query_state_lock:
                if self._settlement_state == "confirmed":
                    return True
                if self._settlement_state == "confirming":
                    self._settlement_state = "failed"
                    self._ready = False
                    self._last_session_error = {"error": "settlement_confirm_timeout"}
                return False
        return self._settlement_state == "confirmed"

    def get_session_state(self) -> dict[str, Any]:
        """Return distinct authentication, login, settlement and query state."""
        with self._query_state_lock:
            execution_gate = self._execution_gate_state_locked()
            return {
                "connected": self._connected,
                "auth_state": self._authentication_state,
                "login_state": self._login_state,
                "settlement_state": self._settlement_state,
                "read_only_ready": self.is_read_only_ready,
                "trading_ready": self.is_trading_ready,
                "ready": self.is_ready,
                "auto_settlement_confirm": self.auto_settlement_confirm,
                "front_id": self._front_id,
                "session_id": self._session_id,
                "trading_day": self._trading_day,
                "connection_generation": self._connection_generation,
                "account_fingerprint": self._account_fingerprint,
                "settlement_request_id": self._settlement_request_id,
                "settlement_connection_generation": self._settlement_connection_generation,
                "settlement_account_fingerprint": self._settlement_account_fingerprint,
                "settlement_trading_day": self._settlement_trading_day,
                "settlement_late_callback_count": self._settlement_late_callback_count,
                "settlement_proof_source": self._settlement_proof_source,
                "settlement_proof_query_request_id": self._settlement_proof_query_request_id,
                "settlement_readback_verified": (self._has_current_settlement_readback_locked()),
                "authentication_request_id": self._authentication_request_id,
                "authentication_connection_generation": (
                    self._authentication_connection_generation
                ),
                "authentication_late_callback_count": (self._authentication_late_callback_count),
                "login_request_id": self._login_request_id,
                "login_connection_generation": self._login_connection_generation,
                "login_late_callback_count": self._login_late_callback_count,
                "request_counts": dict(self._request_counts),
                "last_error": dict(self._last_session_error),
                "execution_gate_managed": execution_gate["managed"],
                "execution_gate_armed": execution_gate["armed"],
                "execution_gate_connection_generation": execution_gate["connection_generation"],
                "execution_gate_instrument": execution_gate["instrument"],
                "execution_gate_scope_version": execution_gate["scope_version"],
                "execution_gate_authorized_instruments": execution_gate["authorized_instruments"],
                "execution_gate_proof_sha256": execution_gate["proof_sha256"],
                "execution_gate_revocation_reason": execution_gate["revocation_reason"],
            }

    def get_query_session_scope(self) -> _QuerySessionScope:
        """Return an opaque typed scope for strict read-only query consumers.

        The returned object is issued by this client instance and carries the
        current account/day/generation identity.  It is separate from the
        historical mapping returned by :meth:`get_session_state`, which stays
        a compatibility diagnostic view and cannot certify a query result.
        """

        # Capture this strict scope after the public session read.  This
        # preserves query-completion-to-scope latency in the same clock
        # domain when a client supplies a delayed session readback.  The
        # mapping returned by that read is deliberately ignored: only the
        # typed scope created below is trusted by evidence consumers.
        self.get_session_state()
        with self._query_state_lock:
            observation = self._current_login_identity_locked()
            if observation is None:
                broker_id = ""
                investor_id = ""
                trading_day = ""
                account_fingerprint = ""
                read_only_ready = False
            else:
                broker_id = observation.broker_id
                investor_id = observation.user_id
                trading_day = observation.trading_day
                account_fingerprint = hashlib.sha256(
                    f"{broker_id}:{investor_id}".encode()
                ).hexdigest()[:16]
                read_only_ready = True
            return _new_query_session_scope(
                issuer=self._query_evidence_issuer,
                account_fingerprint=account_fingerprint,
                connection_generation=self._connection_generation,
                trading_day=trading_day,
                broker_id=broker_id,
                investor_id=investor_id,
                read_only_ready=read_only_ready,
                captured_at_utc=datetime.now(timezone.utc),
                captured_monotonic=time.monotonic(),
            )

    def _current_login_identity_locked(
        self,
    ) -> _TraderLoginIdentityObservation | None:
        observation = self._login_identity_observation
        ingress = self._callback_ingress
        if (
            (ingress is not None and ingress.poisoned)
            or
            type(observation) is not _TraderLoginIdentityObservation
            or observation._seal is not _TRADER_LOGIN_IDENTITY_SEAL
            or observation.connection_generation != self._connection_generation
            or observation.connection_generation <= 0
            or observation.request_id <= 0
            or observation.broker_id != self._bound_broker_id
            or observation.user_id != self._bound_user_id
            or observation.trading_day != self._trading_day
            or self._login_state != "logged_in"
            or self._authentication_state != "authenticated"
            or not self._connected
        ):
            return None
        if not self._bound_identity_is_current(require_active_front=False):
            return None
        return observation

    def get_request_counts(self) -> dict[str, int]:
        """Return a read-only snapshot of native requests issued this session."""
        with self._query_state_lock:
            return dict(self._request_counts)

    def _reserve_start_generation(self) -> int:
        """Reserve one startup generation before creating the native API."""

        with self._query_state_lock:
            # Preserve the managed-gate revocation contract even when this is
            # a rejected re-entrant start attempt.
            self._revoke_execution_gate_locked("ctp_execution_gate_client_start")
            if self._pending_native_join_api_ids:
                raise RuntimeError("ctp_trader_client_native_join_pending")
            if self._api is not None or self._starting_generation is not None:
                raise RuntimeError("ctp_trader_client_already_started")
            self._lifecycle_generation += 1
            generation = self._lifecycle_generation
            self._starting_generation = generation
            self._startup_cancel_event.clear()
            return generation

    def _clear_start_reservation(self, generation: int) -> None:
        with self._query_state_lock:
            if self._starting_generation == generation:
                self._starting_generation = None

    def _is_start_current_locked(self, api: Any, spi: Any, generation: int) -> bool:
        return (
            self._lifecycle_generation == generation
            and self._starting_generation == generation
            and self._api is api
            and self._spi is spi
            and not self._startup_cancel_event.is_set()
        )

    def _run_startup_call(
        self,
        api: Any,
        spi: Any,
        generation: int,
        callback: Callable[[], Any],
        *,
        starts_native_thread: bool = False,
        lifecycle_operation: Literal["register_spi", "init"] | None = None,
    ) -> tuple[bool, bool]:
        """Run one native startup call with pre/post cancellation fences."""

        with self._query_state_lock:
            if not self._is_start_current_locked(api, spi, generation):
                return False, False
            if starts_native_thread:
                # A re-entrant stop from Init() must treat the API as live
                # before the vendor is allowed to create its callback thread.
                self._native_init_started = True
                self._join_active = True
            # stop() sets its event before it waits for this lock.  Repeat the
            # precondition immediately before entering native code so a stop
            # that arrived during the preceding bookkeeping cancels this step.
            if not self._is_start_current_locked(api, spi, generation):
                if starts_native_thread:
                    self._native_init_started = False
                    self._join_active = False
                return False, False
            ingress = self._callback_ingress
            self._native_request_inflight_refs += 1
            if ingress is not None:
                ingress.native_call_refs += 1

        callback_failed = False
        try:
            if lifecycle_operation is None:
                callback()
            else:
                _record_ctp_native_call(api, lifecycle_operation, callback)
        except BaseException:
            callback_failed = True
            raise
        finally:
            with self._query_state_lock:
                self._native_request_inflight_refs = max(
                    0, self._native_request_inflight_refs - 1
                )
                if ingress is not None:
                    ingress.native_call_refs = max(0, ingress.native_call_refs - 1)
                    if callback_failed:
                        self._poison_callback_ingress_locked("native_call_ambiguous")
                self._maybe_finish_deferred_native_release_locked()
        with self._query_state_lock:
            return True, self._is_start_current_locked(api, spi, generation)

    def _abort_startup(
        self,
        api: Any,
        spi: Any,
        generation: int,
        *,
        native_init_may_be_live: bool = False,
    ) -> bool:
        """Clean up a failed startup only while this generation owns it."""

        release_now = False
        observe_join = False
        with self._query_state_lock:
            if not self._is_start_current_locked(api, spi, generation):
                return False
            native_live = native_init_may_be_live or self._native_init_started
            if native_live:
                self._pending_native_join_api_ids.add(id(api))
                _retain_live_ctp_native_session(api, spi, self._thread)
                observe_join = True
            else:
                self._pending_native_join_api_ids.add(id(api))
                release_now = True
                if self._native_lifecycle_state is not None:
                    self._native_lifecycle_state.mark_join_not_required()
            self._last_stopped_native_api = api
            self._last_stop_lifecycle_state = self._native_lifecycle_state
            self._last_stopped_connection_generation = self._connection_generation
            self._last_stop_join_required = native_live
            self._last_stop_join_thread = self._thread
            self._last_stop_join_tracker = self._native_join_tracker
            self._api = None
            self._thread = None
            self._join_active = False
            self._native_init_started = False
            self._starting_generation = None
            self._lifecycle_generation += 1

        if observe_join:
            with suppress(Exception):
                _detach_ctp_native_spi_once(api)
            self._start_join_observer(api)
        elif release_now:
            _release_ctp_native_api_immediately(
                api,
                spi,
                state_lock=self._query_state_lock,
                pending_api_ids=self._pending_native_join_api_ids,
            )
        return True

    def _join_native_api(self, api: Any, *, _already_claimed: bool = False) -> None:
        if not _already_claimed and not _claim_ctp_native_join(api):
            return
        tracker = self._native_join_tracker
        lifecycle_state = _ctp_native_lifecycle_state_for_api(api)
        tracker.begin()
        if lifecycle_state is not None:
            lifecycle_state.begin("join")
        join_returned = False
        try:
            join_result = api.Join()
            join_returned = True
            if lifecycle_state is not None and not lifecycle_state.returned("join", join_result):
                tracker.failed(TypeError("ctp_native_join_unexpected_return_type"))
                raise TypeError("ctp_native_join_unexpected_return_type")
            tracker.returned(join_result)
            _mark_ctp_native_join_returned(api)
        except BaseException as exc:
            if lifecycle_state is not None and lifecycle_state.join_state == "pending":
                lifecycle_state.failed("join", exc)
            tracker.failed(exc)
            raise
        finally:
            if join_returned:
                with self._query_state_lock:
                    if self._api is api:
                        self._join_active = False
                        self._native_init_started = False
                    if self._thread is threading.current_thread():
                        self._thread = None
                retired_session_released = _release_retired_ctp_native_session_after_join(api)
                if retired_session_released:
                    with self._query_state_lock:
                        self._pending_native_join_api_ids.discard(id(api))

    def wait_native_join(self, timeout: float) -> CtpNativeJoinWaitResult:
        """Wait at most ``timeout`` seconds for the latest native Join call.

        ``timeout`` must be finite and between zero and 60 seconds. The typed
        result reports whether Join returned or raised; a returned Join does
        not certify a successful ``Release`` or an empty process.
        """

        return self._native_join_tracker.wait(timeout)

    def _start_join_observer(self, api: Any) -> bool:
        """Start one Join observer for either the current or retired session."""

        thread = threading.Thread(
            target=self._join_native_api,
            args=(api,),
            kwargs={"_already_claimed": True},
            daemon=True,
        )
        with self._query_state_lock:
            if self._api is api:
                if self._thread is not None or not _claim_ctp_native_join(api):
                    return False
                self._thread = thread
                self._join_active = True
            elif not _set_retired_ctp_native_session_join_thread(api, thread):
                return False
            elif self._last_stopped_native_api is api:
                self._last_stop_join_thread = thread
        thread.start()
        return True

    def start(self, block=False):
        """启动连接（默认后台运行）"""
        with self._query_state_lock:
            ingress_state = self._callback_ingress
            if ingress_state is not None and (
                ingress_state.poisoned or ingress_state.phase != "PRE_START"
            ):
                raise CtpExecutionGateError("ctp_callback_ingress_owner_not_startable")
        _check_native_module()
        generation = self._reserve_start_generation()
        with self._query_state_lock:
            self._require_bound_identity_locked(require_active_front=False)
        flow = _flow_dir(f"td_{self._bound_broker_id}_{self._bound_user_id}")
        api = None
        try:
            api = CThostFtdcTraderApi.CreateFtdcTraderApi(flow)
            _register_ctp_native_api(api)
        except BaseException:
            with self._query_state_lock:
                self._poison_callback_ingress_locked("source_gap")
            if api is not None:
                try:
                    _release_ctp_native_api_immediately(
                        api,
                        None,
                        state_lock=self._query_state_lock,
                        pending_api_ids=self._pending_native_join_api_ids,
                    )
                except BaseException:
                    pass
            self._clear_start_reservation(generation)
            raise
        spi = _TraderSpi(self, api)
        with self._query_state_lock:
            if (
                self._starting_generation != generation
                or self._lifecycle_generation != generation
                or self._startup_cancel_event.is_set()
            ):
                cancelled_before_registration = True
            else:
                cancelled_before_registration = False
                self._api = api
                self._spi = spi
                # The API setter assigns this generation's epoch/source IDs.
                # Bind the receipt only after those exact values exist.
                lifecycle_state = _bind_ctp_native_lifecycle_state(
                    self,
                    client_kind="trader",
                    session_generation=generation,
                    api=api,
                    spi=spi,
                )
                self._native_lifecycle_state = lifecycle_state
                spi._native_api_generation = self._native_api_generation
                spi._native_client_epoch = self._native_client_epoch
                spi._native_api_source_id = self._native_api_source_id
                if self._callback_ingress is not None:
                    from .callback_ingress import CtpTraderCallbackSourceTagsV2

                    spi._callback_source_tags = CtpTraderCallbackSourceTagsV2(
                        source_instance_id=self._callback_source_instance_id,
                        native_client_epoch=self._native_client_epoch,
                        native_api_source_id=self._native_api_source_id,
                        native_spi_source_id=spi._native_spi_source_id,
                        native_api_generation=self._native_api_generation,
                        connection_generation=self._connection_generation,
                    )
                    self._callback_ingress.current_source_tags = (
                        spi._callback_source_tags.source_instance_id,
                        spi._callback_source_tags.native_client_epoch,
                        spi._callback_source_tags.native_api_source_id,
                        spi._callback_source_tags.native_spi_source_id,
                        spi._callback_source_tags.native_api_generation,
                        spi._callback_source_tags.connection_generation,
                    )
                    self._callback_ingress.current_source_tags_object = (
                        spi._callback_source_tags
                    )
                    self._callback_ingress.phase = "PRE_LOGIN"
                self._native_init_started = False
                self._join_active = False
                self._native_join_tracker = _CtpNativeJoinTracker()
        if cancelled_before_registration:
            with self._query_state_lock:
                self._poison_callback_ingress_locked("owner_stop")
            _release_ctp_native_api_immediately(
                api,
                spi,
                state_lock=self._query_state_lock,
                pending_api_ids=self._pending_native_join_api_ids,
            )
            return

        init_invoked = False

        # ``RegisterFront`` below always receives this immutable value.  Keep
        # the exact native-front binding alongside the native API so a later
        # public ``front`` mutation cannot be mistaken for a verified
        # environment on reconnect.
        with self._query_state_lock:
            if self._api is not api or self._spi is not spi:
                self._abort_startup(api, spi, generation)
                return
            self._session_native_front = self._bound_front

        def init_native_api() -> None:
            nonlocal init_invoked
            init_invoked = True
            api.Init()

        try:
            startup_calls = (
                (lambda: api.RegisterSpi(spi), "register_spi"),
                (lambda: api.SubscribePrivateTopic(2), None),
                (lambda: api.SubscribePublicTopic(2), None),
                (lambda: api.RegisterFront(self._bound_front), None),
            )
            for startup_call, lifecycle_operation in startup_calls:
                invoked, active = self._run_startup_call(
                    api,
                    spi,
                    generation,
                    startup_call,
                    lifecycle_operation=lifecycle_operation,
                )
                if not invoked or not active:
                    self._abort_startup(api, spi, generation)
                    return
            invoked, active = self._run_startup_call(
                api,
                spi,
                generation,
                init_native_api,
                starts_native_thread=True,
                lifecycle_operation="init",
            )
            if not invoked:
                self._abort_startup(api, spi, generation)
                return
            if not active:
                # stop() detached this API while Init was running.  It is
                # retained already; attach a Join observer so the registry is
                # released when the native thread exits.
                self._start_join_observer(api)
                return
        except BaseException:
            # Init is a void vendor call, but if a binding raises after it was
            # entered, fail safe and retain until Join proves native shutdown.
            handled = self._abort_startup(
                api,
                spi,
                generation,
                native_init_may_be_live=init_invoked,
            )
            if init_invoked and not handled:
                # A concurrent stop may have set the cancellation fence while
                # Init raised.  Attach the observer whether it already
                # retained the session or is about to do so.
                self._start_join_observer(api)
            raise

        if block:
            with self._query_state_lock:
                current = self._is_start_current_locked(api, spi, generation)
            if not current:
                self._start_join_observer(api)
                return
            try:
                self._join_native_api(api)
            except KeyboardInterrupt:
                pass
            finally:
                self.stop()
            return

        self._start_join_observer(api)

    def wait_ready(self, timeout=15):
        """Wait for login, direct confirmation and matching server readback."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_ready:
                return True
            with self._query_state_lock:
                should_read_back = (
                    self.auto_settlement_confirm
                    and self.is_read_only_ready
                    and self._settlement_state == "confirmed"
                    and self._settlement_proof_source == "direct_confirmation"
                    and not self._has_current_settlement_readback_locked()
                )
            if should_read_back:
                remaining = max(0.0, deadline - time.time())
                self.verify_settlement_confirmation(timeout=min(5.0, remaining))
                continue
            time.sleep(min(0.2, max(0.0, deadline - time.time())))
        return self.is_ready

    def _new_query_accumulator(
        self,
        request_type: str,
        request_filters: Mapping[str, str] | None = None,
        explicit_request_filters: tuple[str, ...] = (),
        *,
        request_intent_filters: Mapping[str, str] | None = None,
        request_parameters: Mapping[str, float] | None = None,
        request_intent_parameters: Mapping[str, float] | None = None,
    ) -> _QueryAccumulator:
        request_id = self._next_request_id()
        filter_items = _query_filter_items(request_filters)
        intent_items = (
            filter_items
            if request_intent_filters is None
            else _query_filter_items(request_intent_filters)
        )
        if intent_items != filter_items:
            raise ValueError("native query filter readback does not match request intent")
        parameter_items = _query_parameter_items(request_parameters)
        parameter_intent_items = (
            parameter_items
            if request_intent_parameters is None
            else _query_parameter_items(request_intent_parameters)
        )
        if parameter_intent_items != parameter_items:
            raise ValueError("native query parameter readback does not match request intent")
        if (
            type(explicit_request_filters) is not tuple
            or any(type(name) is not str for name in explicit_request_filters)
            or len(explicit_request_filters) != len(set(explicit_request_filters))
            or any(name not in dict(filter_items) for name in explicit_request_filters)
        ):
            raise TypeError("explicit query filter names must identify captured filters")
        accumulator = _QueryAccumulator(
            request_type=request_type,
            request_id=request_id,
            connection_generation=self._connection_generation,
            account_fingerprint=self._account_fingerprint,
            started_at_utc=datetime.now(timezone.utc),
            source_issuer=self._query_evidence_issuer,
            request_intent_filters=intent_items,
            request_intent_parameters=parameter_intent_items,
            trading_day=self._trading_day,
            broker_id=self._bound_broker_id,
            investor_id=self._bound_user_id,
            request_filters=filter_items,
            request_parameters=parameter_items,
            explicit_request_filters=tuple(sorted(explicit_request_filters)),
            started_monotonic=time.monotonic(),
        )
        with self._query_state_lock:
            self._query_history[request_id] = accumulator
            while len(self._query_history) > 256:
                oldest_request_id = next(iter(self._query_history))
                oldest = self._query_history[oldest_request_id]
                if not oldest.sealed:
                    break
                self._query_history.pop(oldest_request_id, None)
        return accumulator

    def _local_query_failure(
        self,
        request_type: str,
        message: str,
        *,
        unsupported: bool = False,
        include_query_source: bool = True,
    ) -> QueryResult[Any]:
        accumulator = self._new_query_accumulator(request_type)
        if not include_query_source:
            accumulator.source_issuer = None
        accumulator.error_code = -3 if unsupported else -1
        accumulator.error_message = message
        accumulator.unsupported = unsupported
        accumulator.completed_at_utc = datetime.now(timezone.utc)
        accumulator.completed_monotonic = time.monotonic()
        accumulator.sealed = True
        accumulator.event.set()
        return accumulator.result()

    def _handle_query_callback(
        self,
        request_type: str,
        record: Any,
        rsp_info: Any,
        request_id: int,
        is_last: bool,
    ) -> None:
        error_code, error_message = _rsp_error(rsp_info)
        terminal_callback_at_utc = None
        terminal_callback_monotonic = None
        if is_last or error_code not in (None, 0):
            terminal_callback_at_utc = datetime.now(timezone.utc)
            terminal_callback_monotonic = time.monotonic()
        with self._query_state_lock:
            accumulator = self._query_history.get(int(request_id))
            if accumulator is None or accumulator.request_type != request_type:
                self._orphan_query_callbacks.append(
                    {
                        "request_type": request_type,
                        "request_id": request_id,
                        "connection_generation": self._connection_generation,
                        "is_last": bool(is_last),
                        "error_code": error_code,
                    }
                )
                del self._orphan_query_callbacks[:-256]
                return
            same_generation = accumulator.connection_generation == self._connection_generation
            if not same_generation:
                accumulator.late_callback_count += 1
                self._orphan_query_callbacks.append(
                    {
                        "request_type": request_type,
                        "request_id": request_id,
                        "connection_generation": self._connection_generation,
                        "is_last": bool(is_last),
                        "error_code": error_code,
                    }
                )
                del self._orphan_query_callbacks[:-256]
                return
            if (
                accumulator.sealed
                or accumulator.is_last_seen
                or accumulator.error_code not in (None, 0)
            ):
                accumulator.late_callback_count += 1
                return
            if record is not None:
                snapshot = _snapshot_query_record(record)
                if request_type == "instruments":
                    snapshot.update(normalize_ctp_instrument(snapshot))
                    # InstrumentField proves ExpireDate but carries neither an
                    # exchange trading calendar nor a prior-day market ranking.
                    snapshot.setdefault("expiry_date", snapshot.get("ExpireDate") or None)
                    snapshot.setdefault("trading_days_to_expiry", None)
                    snapshot.setdefault("remaining_trading_days", None)
                    snapshot.setdefault("trading_calendar_evidence_complete", False)
                    snapshot.setdefault("ranking_trading_day", None)
                    snapshot.setdefault("prior_trading_day_volume", None)
                    snapshot.setdefault("prior_trading_day_open_interest", None)
                    snapshot.setdefault("prior_day_ranking_evidence_complete", False)
                accumulator.records.append(snapshot)
            if error_code not in (None, 0):
                accumulator.error_code = error_code
                accumulator.error_message = error_message
            if is_last:
                accumulator.is_last_seen = True
            if is_last or error_code not in (None, 0):
                # The terminal callback is the authoritative completion
                # boundary.  Capture both clocks and the raw-row digest before
                # releasing the state lock; a slow native return or a later
                # adapter conversion must not renew or mutate this evidence.
                if accumulator.completed_at_utc is None:
                    accumulator.completed_at_utc = terminal_callback_at_utc
                    accumulator.completed_monotonic = terminal_callback_monotonic
                if accumulator.source_records_sha256 is None:
                    try:
                        accumulator.source_records_sha256 = _query_records_digest(
                            tuple(accumulator.records)
                        )
                    except (TypeError, ValueError):
                        # A malformed native row remains visible to legacy
                        # callers, but cannot be promoted by the strict
                        # evidence consumer without a bound digest.
                        accumulator.source_records_sha256 = None
                accumulator.event.set()

    def _handle_query_error(self, rsp_info: Any, request_id: int, is_last: bool) -> None:
        with self._query_state_lock:
            accumulator = self._query_history.get(int(request_id))
            request_type = accumulator.request_type if accumulator is not None else "unknown"
        self._handle_query_callback(request_type, None, rsp_info, request_id, is_last)

    def _execute_query(
        self,
        request_type: str,
        submit: Callable[[int], Any] | None,
        timeout: float,
        *,
        request_filter_field: Any | None = None,
        request_intent_filters: Mapping[str, str] | None = None,
        request_intent_parameters: Mapping[str, float] | None = None,
        explicit_request_filters: tuple[str, ...] = (),
    ) -> QueryResult[Any]:
        if not self.is_read_only_ready:
            return self._local_query_failure(request_type, "trader_not_logged_in")
        if not callable(submit):
            return self._local_query_failure(
                request_type,
                "native_query_unsupported",
                unsupported=True,
            )
        with self._query_lock:
            elapsed = time.monotonic() - self._last_query_submitted_at
            wait_time = self._query_interval - elapsed
            if wait_time > 0:
                time.sleep(wait_time)
            try:
                request_intent_items = _query_filter_items(request_intent_filters)
                request_filter_items = _read_native_query_filter_items(
                    request_filter_field,
                    request_intent_items,
                )
            except (TypeError, ValueError) as exc:
                return self._local_query_failure(
                    request_type,
                    f"native_query_filter_readback_failed:{exc}",
                    unsupported=True,
                    include_query_source=False,
                )
            try:
                request_intent_parameter_items = _query_parameter_items(
                    request_intent_parameters
                )
                request_parameter_items = _read_native_query_parameter_items(
                    request_filter_field,
                    request_intent_parameter_items,
                )
            except (TypeError, ValueError) as exc:
                return self._local_query_failure(
                    request_type,
                    f"native_query_parameter_readback_failed:{exc}",
                    unsupported=True,
                    include_query_source=False,
                )
            accumulator = self._new_query_accumulator(
                request_type,
                dict(request_filter_items),
                explicit_request_filters=explicit_request_filters,
                request_intent_filters=dict(request_intent_items),
                request_parameters=dict(request_parameter_items),
                request_intent_parameters=dict(request_intent_parameter_items),
            )
            self._record_request(f"query_{request_type}")
            self._last_query_submitted_at = time.monotonic()

        # Release the query-rate lock before entering native code. A vendor
        # Req may synchronously invoke a callback on this thread or wait for a
        # callback thread that must acquire SDK state locks.
        try:
            ret = submit(accumulator.request_id)
        except Exception as exc:
            accumulator.error_code = -4
            accumulator.error_message = f"query_submit_exception:{type(exc).__name__}"
            accumulator.completed_at_utc = datetime.now(timezone.utc)
            accumulator.completed_monotonic = time.monotonic()
            accumulator.sealed = True
            accumulator.event.set()
            return accumulator.result()
        accumulator.submit_code = None if ret is None else int(ret)
        if ret not in (None, 0):
            accumulator.error_code = int(ret)
            accumulator.error_message = "query_submit_rejected"
            accumulator.completed_at_utc = datetime.now(timezone.utc)
            accumulator.completed_monotonic = time.monotonic()
            accumulator.sealed = True
            accumulator.event.set()
            return accumulator.result()
        observed = accumulator.event.wait(max(float(timeout), 0.0))
        with self._query_state_lock:
            # If the terminal callback acquired the state lock at the
            # timeout boundary, it wins the race and remains complete.
            if (
                not observed
                and not accumulator.is_last_seen
                and accumulator.error_code in (None, 0)
            ):
                accumulator.timed_out = True
                accumulator.error_message = "query_timeout"
            if accumulator.completed_at_utc is None:
                accumulator.completed_at_utc = datetime.now(timezone.utc)
                accumulator.completed_monotonic = time.monotonic()
            accumulator.sealed = True
            accumulator.event.set()
            return accumulator.result()

    def get_query_result(self, request_id: int) -> QueryResult[Any] | None:
        """Return current evidence, including callbacks arriving after timeout."""
        with self._query_state_lock:
            accumulator = self._query_history.get(int(request_id))
            return accumulator.result() if accumulator is not None else None

    def query_account_result(self, timeout=5) -> QueryResult[Any]:
        field = CThostFtdcQryTradingAccountField()
        intent_filters = {
            "BrokerID": self._bound_broker_id,
            "InvestorID": self._bound_user_id,
        }
        try:
            for name, value in intent_filters.items():
                setattr(field, name, value)
        except Exception:
            return self._local_query_failure(
                "account",
                "native_query_fields_unsupported",
                unsupported=True,
                include_query_source=False,
            )
        api = self._api
        method = getattr(api, "ReqQryTradingAccount", None) if api is not None else None
        return self._execute_query(
            "account",
            (
                (lambda request_id: self._invoke_session_native_request(
                    api, "ReqQryTradingAccount", field, request_id
                ))
                if callable(method)
                else None
            ),
            timeout,
            request_filter_field=field,
            request_intent_filters=intent_filters,
        )

    def query_account(self, timeout=5):
        """Compatibility view; incomplete queries return ``None``."""
        return self.query_account_result(timeout=timeout).first

    def query_positions_result(self, timeout=5) -> QueryResult[Any]:
        field = CThostFtdcQryInvestorPositionField()
        intent_filters = {
            "BrokerID": self._bound_broker_id,
            "InvestorID": self._bound_user_id,
        }
        try:
            for name, value in intent_filters.items():
                setattr(field, name, value)
        except Exception:
            return self._local_query_failure(
                "positions",
                "native_query_fields_unsupported",
                unsupported=True,
                include_query_source=False,
            )
        api = self._api
        method = getattr(api, "ReqQryInvestorPosition", None) if api is not None else None
        return self._execute_query(
            "positions",
            (
                (lambda request_id: self._invoke_session_native_request(
                    api, "ReqQryInvestorPosition", field, request_id
                ))
                if callable(method)
                else None
            ),
            timeout,
            request_filter_field=field,
            request_intent_filters=intent_filters,
        )

    def query_positions(self, timeout=5):
        result = self.query_positions_result(timeout=timeout)
        return list(result.records) if result.complete else []

    def query_orders_result(
        self, instrument_id="", exchange_id="", order_sys_id="", timeout=5
    ) -> QueryResult[Any]:
        field = CThostFtdcQryOrderField()
        intent_filters = {
            "BrokerID": self._bound_broker_id,
            "InvestorID": self._bound_user_id,
            "InstrumentID": str(instrument_id or ""),
            "ExchangeID": str(exchange_id or ""),
            "OrderSysID": str(order_sys_id or ""),
        }
        try:
            for name, value in intent_filters.items():
                setattr(field, name, value)
        except Exception:
            return self._local_query_failure(
                "orders",
                "native_query_fields_unsupported",
                unsupported=True,
                include_query_source=False,
            )
        api = self._api
        method = getattr(api, "ReqQryOrder", None) if api is not None else None
        return self._execute_query(
            "orders",
            (
                (lambda request_id: self._invoke_session_native_request(
                    api, "ReqQryOrder", field, request_id
                ))
                if callable(method)
                else None
            ),
            timeout,
            request_filter_field=field,
            request_intent_filters=intent_filters,
        )

    def query_orders(self, instrument_id="", exchange_id="", order_sys_id="", timeout=5):
        result = self.query_orders_result(
            instrument_id=instrument_id,
            exchange_id=exchange_id,
            order_sys_id=order_sys_id,
            timeout=timeout,
        )
        return list(result.records) if result.complete else []

    def query_trades_result(
        self,
        instrument_id="",
        exchange_id="",
        trade_id="",
        start_time="",
        end_time="",
        timeout=5,
    ) -> QueryResult[Any]:
        field = CThostFtdcQryTradeField()
        intent_filters = {
            "BrokerID": self._bound_broker_id,
            "InvestorID": self._bound_user_id,
            "InstrumentID": str(instrument_id or ""),
            "ExchangeID": str(exchange_id or ""),
            "TradeID": str(trade_id or ""),
            "TradeTimeStart": str(start_time or ""),
            "TradeTimeEnd": str(end_time or ""),
        }
        try:
            for name, value in intent_filters.items():
                setattr(field, name, value)
        except Exception:
            return self._local_query_failure(
                "trades",
                f"native_trade_filter_unsupported:{name}",
                unsupported=True,
                include_query_source=False,
            )
        api = self._api
        method = getattr(api, "ReqQryTrade", None) if api is not None else None
        return self._execute_query(
            "trades",
            (
                (lambda request_id: self._invoke_session_native_request(
                    api, "ReqQryTrade", field, request_id
                ))
                if callable(method)
                else None
            ),
            timeout,
            request_filter_field=field,
            request_intent_filters=intent_filters,
        )

    def query_trades(self, **kwargs: Any) -> list[Any]:
        result = self.query_trades_result(**kwargs)
        return list(result.records) if result.complete else []

    def query_instruments_result(
        self, instrument_id="", exchange_id="", product_id="", timeout=5
    ) -> QueryResult[Any]:
        """Read all visible instruments with empty filters, including options.

        Native fields are preserved alongside normalized reference metadata.
        Only ``complete=True`` proves the matching terminal packet; visibility
        is limited to the connected front, account and trading day.
        """
        field = CThostFtdcQryInstrumentField()
        intent_filters = {"InstrumentID": str(instrument_id or "")}
        field.InstrumentID = intent_filters["InstrumentID"]
        if exchange_id:
            intent_filters["ExchangeID"] = str(exchange_id)
            field.ExchangeID = intent_filters["ExchangeID"]
        if product_id:
            try:
                intent_filters["ProductID"] = str(product_id)
                field.ProductID = intent_filters["ProductID"]
            except Exception:
                # Do not silently fall back to the potentially expensive,
                # unfiltered instrument query when this native ABI cannot
                # represent ProductID.
                return self._local_query_failure(
                    "instruments",
                    "native_instrument_filter_unsupported:ProductID",
                    unsupported=True,
                    include_query_source=False,
                )
        api = self._api
        method = getattr(api, "ReqQryInstrument", None) if api is not None else None
        return self._execute_query(
            "instruments",
            (
                (lambda request_id: self._invoke_session_native_request(
                    api, "ReqQryInstrument", field, request_id
                ))
                if callable(method)
                else None
            ),
            timeout,
            request_filter_field=field,
            request_intent_filters=intent_filters,
        )

    def query_instrument(self, instrument_id, exchange_id="", timeout=5):
        return self.query_instruments_result(
            instrument_id=instrument_id, exchange_id=exchange_id, timeout=timeout
        ).first

    def query_instrument_margin_rate_result(
        self, instrument_id, exchange_id="", hedge_flag=_QUERY_FILTER_UNSET, timeout=5
    ) -> QueryResult[Any]:
        hedge_flag_explicit = hedge_flag is not _QUERY_FILTER_UNSET
        if not hedge_flag_explicit:
            hedge_flag = "1"
        hedge_flag_value = str(hedge_flag or "")
        field = CThostFtdcQryInstrumentMarginRateField()
        intent_filters = {
            "BrokerID": self._bound_broker_id,
            "InvestorID": self._bound_user_id,
            "InstrumentID": str(instrument_id or ""),
            "ExchangeID": str(exchange_id or ""),
            "HedgeFlag": hedge_flag_value,
        }
        try:
            for name, value in intent_filters.items():
                setattr(field, name, value)
        except Exception:
            return self._local_query_failure(
                "margin_rate",
                "native_query_fields_unsupported",
                unsupported=True,
                include_query_source=False,
            )
        api = self._api
        method = getattr(api, "ReqQryInstrumentMarginRate", None) if api is not None else None
        return self._execute_query(
            "margin_rate",
            (
                (lambda request_id: self._invoke_session_native_request(
                    api, "ReqQryInstrumentMarginRate", field, request_id
                ))
                if callable(method)
                else None
            ),
            timeout,
            request_filter_field=field,
            request_intent_filters=intent_filters,
            explicit_request_filters=("HedgeFlag",) if hedge_flag_explicit else (),
        )

    def query_instrument_margin_rate(
        self, instrument_id, exchange_id="", hedge_flag=_QUERY_FILTER_UNSET, timeout=5
    ):
        return self.query_instrument_margin_rate_result(
            instrument_id,
            exchange_id=exchange_id,
            hedge_flag=hedge_flag,
            timeout=timeout,
        ).first

    def query_instrument_commission_rate_result(
        self, instrument_id, exchange_id="", timeout=5
    ) -> QueryResult[Any]:
        field = CThostFtdcQryInstrumentCommissionRateField()
        intent_filters = {
            "BrokerID": self._bound_broker_id,
            "InvestorID": self._bound_user_id,
            "InstrumentID": str(instrument_id or ""),
            "ExchangeID": str(exchange_id or ""),
        }
        try:
            for name, value in intent_filters.items():
                setattr(field, name, value)
        except Exception:
            return self._local_query_failure(
                "commission_rate",
                "native_query_fields_unsupported",
                unsupported=True,
                include_query_source=False,
            )
        api = self._api
        method = getattr(api, "ReqQryInstrumentCommissionRate", None) if api is not None else None
        return self._execute_query(
            "commission_rate",
            (
                (lambda request_id: self._invoke_session_native_request(
                    api, "ReqQryInstrumentCommissionRate", field, request_id
                ))
                if callable(method)
                else None
            ),
            timeout,
            request_filter_field=field,
            request_intent_filters=intent_filters,
        )

    def query_instrument_commission_rate(self, instrument_id, exchange_id="", timeout=5):
        return self.query_instrument_commission_rate_result(
            instrument_id, exchange_id=exchange_id, timeout=timeout
        ).first

    def _query_reference_result(self, request_type, field_type, method_name, values, timeout):
        """Build a read request without silently dropping unsupported ABI fields."""
        try:
            field = field_type()
            for name, value in values.items():
                setattr(field, name, value)
        except Exception:
            return self._local_query_failure(
                request_type,
                "native_query_fields_unsupported",
                unsupported=True,
                include_query_source=False,
            )
        api = self._api
        method = getattr(api, method_name, None) if api is not None else None
        return self._execute_query(
            request_type,
            (
                (lambda request_id: self._invoke_session_native_request(
                    api, method_name, field, request_id
                ))
                if callable(method)
                else None
            ),
            timeout,
            request_filter_field=field,
            request_intent_filters={
                name: value for name, value in values.items() if type(value) is str
            },
            request_intent_parameters={
                name: value for name, value in values.items() if type(value) is float
            },
        )

    def query_depth_market_data_result(
        self, instrument_id="", exchange_id="", timeout=5
    ) -> QueryResult[Any]:
        """Query TD reference quotes, or all visible quotes with empty filters.

        Raw source timestamps and prices are retained. A successful query is
        not evidence that the quotes are fresh, synchronized or executable.
        """
        return self._query_reference_result(
            "depth_market_data",
            CThostFtdcQryDepthMarketDataField,
            "ReqQryDepthMarketData",
            {
                "InstrumentID": str(instrument_id or ""),
                "ExchangeID": str(exchange_id or ""),
            },
            timeout,
        )

    def query_option_instrument_trade_cost_result(
        self,
        instrument_id,
        exchange_id="",
        hedge_flag="1",
        input_price=0.0,
        underlying_price=0.0,
        timeout=5,
    ) -> QueryResult[Any]:
        """Read the broker's option trade-cost response for the supplied prices.

        This preserves native FixedMargin/MiniMargin/Royalty fields; it is not
        a portfolio margin calculation. Zero inputs are passed as native zero
        without claiming a current executable price or a known pricing basis.
        """
        prices = {}
        for name, value in (
            ("InputPrice", input_price),
            ("UnderlyingPrice", underlying_price),
        ):
            if isinstance(value, bool):
                raise ValueError(f"{name} must be finite and non-negative")
            price = float(value)
            if not math.isfinite(price) or price < 0:
                raise ValueError(f"{name} must be finite and non-negative")
            prices[name] = price
        return self._query_reference_result(
            "option_trade_cost",
            CThostFtdcQryOptionInstrTradeCostField,
            "ReqQryOptionInstrTradeCost",
            {
                "BrokerID": self._bound_broker_id,
                "InvestorID": self._bound_user_id,
                "InstrumentID": str(instrument_id or ""),
                "ExchangeID": str(exchange_id or ""),
                "HedgeFlag": str(hedge_flag or ""),
                **prices,
            },
            timeout,
        )

    def query_option_instrument_commission_rate_result(
        self, instrument_id, exchange_id="", timeout=5
    ) -> QueryResult[Any]:
        """Read native option open/close/close-today and strike commission fields."""
        return self._query_reference_result(
            "option_commission_rate",
            CThostFtdcQryOptionInstrCommRateField,
            "ReqQryOptionInstrCommRate",
            {
                "BrokerID": self._bound_broker_id,
                "InvestorID": self._bound_user_id,
                "InstrumentID": str(instrument_id or ""),
                "ExchangeID": str(exchange_id or ""),
            },
            timeout,
        )

    def query_settlement_confirmation_result(self, timeout=5) -> QueryResult[Any]:
        field = CThostFtdcQrySettlementInfoConfirmField()
        intent_filters = {
            "BrokerID": self._bound_broker_id,
            "InvestorID": self._bound_user_id,
        }
        try:
            for name, value in intent_filters.items():
                setattr(field, name, value)
        except Exception:
            return self._local_query_failure(
                "settlement_confirmation",
                "native_query_fields_unsupported",
                unsupported=True,
                include_query_source=False,
            )
        api = self._api
        method = getattr(api, "ReqQrySettlementInfoConfirm", None) if api is not None else None
        return self._execute_query(
            "settlement_confirmation",
            (
                (lambda request_id: self._invoke_session_native_request(
                    api, "ReqQrySettlementInfoConfirm", field, request_id
                ))
                if callable(method)
                else None
            ),
            timeout,
            request_filter_field=field,
            request_intent_filters=intent_filters,
        )

    def verify_settlement_confirmation(self, timeout=5) -> QueryResult[Any]:
        """Read server confirmation and promote this matching session to trading ready."""
        with self._query_state_lock:
            expected_generation = self._connection_generation
            expected_fingerprint = self._account_fingerprint
            expected_trading_day = self._trading_day
            self._clear_settlement_readback_locked("ctp_execution_gate_settlement_readback_refresh")
        result = self.query_settlement_confirmation_result(timeout=timeout)
        failure_reason = ""
        if not result.complete:
            failure_reason = "ctp_execution_gate_settlement_readback_incomplete"
        elif result.connection_generation != expected_generation:
            failure_reason = "ctp_execution_gate_settlement_readback_stale_generation"
        elif result.account_fingerprint != expected_fingerprint:
            failure_reason = "ctp_execution_gate_settlement_readback_wrong_account"

        matched = False
        for record in result.records if not failure_reason else ():
            if isinstance(record, dict):
                getter = record.get
            else:

                def getter(name: str, default: Any = "") -> Any:
                    return getattr(record, name, default)

            broker_id = str(getter("BrokerID", "") or "")
            investor_id = str(getter("InvestorID", "") or "")
            confirmation_day = str(getter("TradingDay", "") or getter("ConfirmDate", "") or "")
            if broker_id != self._bound_broker_id:
                continue
            if investor_id != self._bound_user_id:
                continue
            if not confirmation_day or confirmation_day != expected_trading_day:
                continue
            matched = True
            break

        if not failure_reason and not matched:
            failure_reason = "ctp_execution_gate_settlement_readback_identity_mismatch"

        with self._query_state_lock:
            if not failure_reason and (
                self._connection_generation != expected_generation
                or self._account_fingerprint != expected_fingerprint
                or self._trading_day != expected_trading_day
            ):
                failure_reason = "ctp_execution_gate_settlement_readback_stale_generation"
            if not failure_reason and not self.is_read_only_ready:
                failure_reason = "ctp_execution_gate_settlement_readback_session_not_ready"
            if failure_reason:
                self._clear_settlement_readback_locked(
                    failure_reason,
                    request_id=result.request_id,
                )
            else:
                self._settlement_state = "confirmed"
                self._settlement_trading_day = expected_trading_day
                self._settlement_connection_generation = expected_generation
                self._settlement_account_fingerprint = expected_fingerprint
                self._settlement_proof_source = "confirmation_query"
                self._settlement_proof_query_request_id = result.request_id
                self._settlement_readback_verified = True
                self._ready = True
                self._last_session_error = {}
        return result

    def next_order_ref(self) -> str:
        """Return the next monotonic CTP OrderRef.

        CTP expects OrderRef to be unique and increasing during a session.
        """
        with self._order_ref_lock:
            self._max_order_ref += 1
            return str(self._max_order_ref)

    def wait_order_event(self, timeout=5):
        """Wait for the next order callback snapshot."""
        try:
            return self._order_events.get(timeout=timeout)
        except queue.Empty:
            return None

    def wait_trade_event(self, timeout=5):
        """Wait for the next trade callback snapshot."""
        try:
            return self._trade_events.get(timeout=timeout)
        except queue.Empty:
            return None

    def wait_error_event(self, timeout=5):
        """Wait for the next error callback snapshot."""
        try:
            return self._error_events.get(timeout=timeout)
        except queue.Empty:
            return None

    @staticmethod
    def _native_callback_wait_deadline(timeout: float | None) -> float | None:
        if timeout is None:
            return None
        if timeout < 0:
            raise ValueError("'timeout' must be a non-negative number")
        return time.monotonic() + timeout

    def _native_callback_consumer_is_live_locked(
        self, lease: _NativeCallbackEventConsumerLease
    ) -> bool:
        return bool(
            self._native_callback_consumer_lease is lease
            and not lease.revoked
            and self._api is not None
            and self._callback_source_instance_id == lease.source_instance_id
            and self._native_client_epoch == lease.native_client_epoch
            and self._native_api_source_id == lease.native_api_source_id
            and self._native_api_generation == lease.native_api_generation
            and self._native_callback_queue_generation == lease.queue_generation
        )

    def _revoke_native_callback_event_consumer_locked(self, _reason: str) -> None:
        lease = getattr(self, "_native_callback_consumer_lease", None)
        if lease is None or lease.revoked:
            return
        lease.revoked = True
        released_tokens = getattr(self, "_native_callback_released_consumer_tokens", None)
        if released_tokens is not None:
            released_tokens.add(lease.token)
        condition = getattr(self, "_native_callback_event_condition", None)
        if condition is not None:
            condition.notify_all()
        if not lease.waiting:
            self._native_callback_consumer_lease = None

    def _claim_native_callback_event_consumer(self) -> _NativeCallbackEventConsumerToken:
        """Claim the callback queue for one token-aware source consumer.

        The opaque token binds to this client, native API generation, and
        callback queue generation. It carries no native API/SPI references.
        """

        with self._query_state_lock:
            lease = self._native_callback_consumer_lease
            if lease is not None:
                if not self._native_callback_consumer_is_live_locked(lease):
                    self._revoke_native_callback_event_consumer_locked(
                        "ctp_native_callback_consumer_stale"
                    )
                lease = self._native_callback_consumer_lease
                if lease is not None:
                    code = (
                        "ctp_native_callback_consumer_previous_wait_active"
                        if lease.waiting
                        else "ctp_native_callback_consumer_already_claimed"
                    )
                    raise CtpNativeCallbackConsumerError(code)

            if self._native_callback_legacy_waiters:
                raise CtpNativeCallbackConsumerError(
                    "ctp_native_callback_consumer_legacy_wait_in_flight"
                )
            if (
                self._api is None
                or self._native_client_epoch is None
                or self._native_api_source_id is None
            ):
                raise CtpNativeCallbackConsumerError(
                    "ctp_native_callback_consumer_native_api_unavailable"
                )

            token = _NativeCallbackEventConsumerToken()
            self._native_callback_consumer_lease = _NativeCallbackEventConsumerLease(
                token=token,
                source_instance_id=self._callback_source_instance_id,
                native_client_epoch=self._native_client_epoch,
                native_api_source_id=self._native_api_source_id,
                native_api_generation=self._native_api_generation,
                queue_generation=self._native_callback_queue_generation,
            )
            return token

    def _wait_native_callback_event_for_consumer(
        self,
        token: object,
        timeout: float | None = 5,
    ) -> CtpTraderCallbackSourceEvent | None:
        """Wait under the current exclusive callback queue consumer lease."""

        deadline = self._native_callback_wait_deadline(timeout)
        if type(token) is not _NativeCallbackEventConsumerToken:
            raise CtpNativeCallbackConsumerError("ctp_native_callback_consumer_invalid_token")

        with self._query_state_lock:
            lease = self._native_callback_consumer_lease
            if lease is None or lease.token is not token:
                raise CtpNativeCallbackConsumerError("ctp_native_callback_consumer_stale_token")
            if not self._native_callback_consumer_is_live_locked(lease):
                self._revoke_native_callback_event_consumer_locked(
                    "ctp_native_callback_consumer_stale"
                )
                raise CtpNativeCallbackConsumerError("ctp_native_callback_consumer_stale_token")
            if lease.waiting:
                raise CtpNativeCallbackConsumerError("ctp_native_callback_consumer_competing_wait")

            lease.waiting = True
            self._native_callback_event_condition.notify_all()
            try:
                while True:
                    if not self._native_callback_consumer_is_live_locked(lease):
                        self._revoke_native_callback_event_consumer_locked(
                            "ctp_native_callback_consumer_stale"
                        )
                        raise CtpNativeCallbackConsumerError(
                            "ctp_native_callback_consumer_stale_token"
                        )

                    try:
                        # Dequeue and lease validation share the client lock.
                        # Callback recording uses that lock too, so a release,
                        # stop, or API replacement cannot race a stale dequeue.
                        return self._native_callback_events.get_nowait()
                    except queue.Empty:
                        remaining = None if deadline is None else deadline - time.monotonic()
                        if remaining is not None and remaining <= 0:
                            return None
                        self._native_callback_event_condition.wait(remaining)
            finally:
                lease.waiting = False
                if (
                    self._native_callback_consumer_lease is lease
                    and not self._native_callback_consumer_is_live_locked(lease)
                ):
                    self._revoke_native_callback_event_consumer_locked(
                        "ctp_native_callback_consumer_stale"
                    )
                if self._native_callback_consumer_lease is lease and lease.revoked:
                    self._native_callback_consumer_lease = None
                self._native_callback_event_condition.notify_all()

    def _release_native_callback_event_consumer(self, token: object) -> None:
        """Revoke a lease; repeated release of the same token is harmless."""

        with self._query_state_lock:
            lease = self._native_callback_consumer_lease
            if lease is None or lease.token is not token:
                try:
                    if token in self._native_callback_released_consumer_tokens:
                        return
                except TypeError:
                    pass
                raise CtpNativeCallbackConsumerError("ctp_native_callback_consumer_stale_token")
            self._revoke_native_callback_event_consumer_locked(
                "ctp_native_callback_consumer_released"
            )

    def wait_native_callback_event(self, timeout=5) -> CtpTraderCallbackSourceEvent | None:
        """Wait for a source-only callback record unless a lease owns the queue.

        This legacy read path remains available to one-off callers. Once a
        bridge claims the queue, bare waits reject so they cannot steal events.
        """

        deadline = self._native_callback_wait_deadline(timeout)
        with self._query_state_lock:
            lease = self._native_callback_consumer_lease
            if lease is not None:
                if not self._native_callback_consumer_is_live_locked(lease):
                    self._revoke_native_callback_event_consumer_locked(
                        "ctp_native_callback_consumer_stale"
                    )
                if self._native_callback_consumer_lease is not None:
                    raise CtpNativeCallbackConsumerError(
                        "ctp_native_callback_consumer_queue_leased"
                    )

            queue_generation = self._native_callback_queue_generation
            try:
                return self._native_callback_events.get_nowait()
            except queue.Empty:
                pass

            self._native_callback_legacy_waiters += 1
            self._native_callback_event_condition.notify_all()
            try:
                while True:
                    if queue_generation != self._native_callback_queue_generation:
                        return None
                    try:
                        return self._native_callback_events.get_nowait()
                    except queue.Empty:
                        remaining = None if deadline is None else deadline - time.monotonic()
                        if remaining is not None and remaining <= 0:
                            return None
                        self._native_callback_event_condition.wait(remaining)
            finally:
                self._native_callback_legacy_waiters -= 1
                self._native_callback_event_condition.notify_all()

    def _record_native_callback_event(
        self,
        origin_spi: _TraderSpi,
        *,
        event_type: str,
        native_field: Any,
        field_names: tuple[str, ...],
        rsp_info: Any = None,
        callback_fields: tuple[tuple[str, Any], ...] = (),
    ) -> CtpTraderCallbackSourceEvent | None:
        """Atomically retain source facts for one current native callback."""

        with self._query_state_lock:
            origin_api = origin_spi._native_api
            native_client_epoch = self._native_client_epoch
            native_api_source_id = self._native_api_source_id
            if (
                origin_api is None
                or native_client_epoch is None
                or native_api_source_id is None
                or self._api is not origin_api
                or self._spi is not origin_spi
            ):
                return None

            raw_fields: list[tuple[str, Any]] = []
            for name, value in callback_fields:
                if type(value) in (str, bytes, int, float, bool, type(None)):
                    raw_fields.append((name, value))
            raw_fields.extend(snapshot_exact_fields(native_field, field_names))
            raw_fields.extend(snapshot_exact_fields(rsp_info, _TRADER_CALLBACK_RSP_INFO_FIELDS))
            raw_correlation_fields = tuple(raw_fields)

            login_verified = bool(
                self._connected is True
                and self._login_state == "logged_in"
                and self._session_native_api is origin_api
                and self._connection_generation > 0
                and self._session_native_front == self._bound_front
                and self._bound_front
                and self._bound_broker_id
                and self._bound_user_id
                and self._trading_day
            )
            login_broker_id = self._bound_broker_id if login_verified else None
            login_investor_id = self._bound_user_id if login_verified else None
            login_front = self._session_native_front if login_verified else None
            login_trading_day = self._trading_day if login_verified else None
            login_front_id = (
                self._front_id if login_verified and type(self._front_id) is int else None
            )
            login_session_id = (
                self._session_id if login_verified and type(self._session_id) is int else None
            )
            callback_session_matches_login = None
            if login_verified:
                raw_values = dict(raw_correlation_fields)
                checks: list[bool] = []
                for field_name, expected in (
                    ("BrokerID", login_broker_id),
                    ("InvestorID", login_investor_id),
                    ("FrontID", login_front_id),
                    ("SessionID", login_session_id),
                    ("TradingDay", login_trading_day),
                ):
                    observed = raw_values.get(field_name)
                    if observed in (None, "", b"", 0):
                        continue
                    checks.append(type(observed) is type(expected) and observed == expected)
                if checks:
                    callback_session_matches_login = all(checks)

            self._callback_source_sequence += 1
            event = CtpTraderCallbackSourceEvent(
                event_type=event_type,  # type: ignore[arg-type]
                source_instance_id=self._callback_source_instance_id,
                native_client_epoch=native_client_epoch,
                native_api_source_id=native_api_source_id,
                native_spi_source_id=origin_spi._native_spi_source_id,
                source_sequence=self._callback_source_sequence,
                callback_monotonic_ns=time.monotonic_ns(),
                native_api_generation=self._native_api_generation,
                connection_generation=self._connection_generation,
                login_verified=login_verified,
                login_broker_id=login_broker_id,
                login_investor_id=login_investor_id,
                login_front=login_front,
                login_trading_day=login_trading_day,
                login_front_id=login_front_id,
                login_session_id=login_session_id,
                callback_session_matches_login=callback_session_matches_login,
                raw_correlation_fields=raw_correlation_fields,
                managed_session_epoch=None,
                managed_session_epoch_bound=False,
                scope_binding="unbound",
            )
            self._native_callback_events.put(event)
            self._native_callback_event_condition.notify_all()
            return event

    def _push_order_event(self, order_field) -> None:
        snapshot = _snapshot_ctp_field(order_field)
        if snapshot:
            self._order_events.put(snapshot)
        if self.on_order:
            self.on_order(order_field)

    def _push_trade_event(self, trade_field) -> None:
        snapshot = _snapshot_ctp_field(trade_field)
        if snapshot:
            self._trade_events.put(snapshot)
        if self.on_trade:
            self.on_trade(trade_field)

    def _push_error_event(self, event_type, rsp_info=None, field=None, request_id=None) -> None:
        payload = {
            "event": event_type,
            "request_id": request_id,
            "error_id": getattr(rsp_info, "ErrorID", 0) if rsp_info is not None else 0,
            "error_msg": (getattr(rsp_info, "ErrorMsg", "") if rsp_info is not None else ""),
            "field": _snapshot_ctp_field(field),
        }
        self._error_events.put(payload)
        if self.on_error and rsp_info is not None:
            self.on_error(rsp_info)

    @property
    def api(self):
        """Return the stable public view of the current native trader API."""
        return self._api_view

    def _stop_native_session(self, *, expected_api: Any = _NO_EXPECTED_NATIVE_API) -> bool:
        """Stop a CTP trader session without freeing a live SWIG director.

        The vendor macOS framework is unsafe if ``Release()`` races a live
        ``Join()``.  Detach the native callback first, then retain the API,
        director and Join thread until Join returns.  Once it has returned,
        the Join observer releases the retained session immediately.
        """

        # Set this before waiting for a native registration call's lock.  It
        # is the post-call fence that prevents later startup calls when stop
        # races RegisterSpi on another thread.
        if expected_api is _NO_EXPECTED_NATIVE_API:
            self._startup_cancel_event.set()
        with self._query_state_lock:
            api = self._api
            if expected_api is not _NO_EXPECTED_NATIVE_API and (
                api is None or api is not expected_api
            ):
                return False
            if expected_api is not _NO_EXPECTED_NATIVE_API:
                self._startup_cancel_event.set()
            # A stop issued while CreateFtdc* is still running must cancel the
            # reserved generation before start() can register it.
            self._lifecycle_generation += 1
            self._starting_generation = None
            self._on_front_disconnected("client_stop")
            spi = self._spi
            join_thread = self._thread
            native_may_be_live = self._native_init_started or self._join_active
            join_active = native_may_be_live and (
                self._join_active or (join_thread is not None and join_thread.is_alive())
            )
            if api is None:
                self._poison_callback_ingress_locked("owner_stop")
                return False
            join_claimed = _ctp_native_join_claimed(api)
            join_required = bool(join_active or join_claimed)
            if not join_required and self._native_lifecycle_state is not None:
                self._native_lifecycle_state.mark_join_not_required()
            self._last_stopped_native_api = api
            self._last_stop_lifecycle_state = self._native_lifecycle_state
            self._last_stopped_connection_generation = self._connection_generation
            self._last_stop_join_required = join_required
            self._last_stop_join_thread = join_thread
            self._last_stop_join_tracker = self._native_join_tracker
            if join_active or join_claimed:
                self._pending_native_join_api_ids.add(id(api))
                _retain_live_ctp_native_session(api, spi, join_thread)
            else:
                self._pending_native_join_api_ids.add(id(api))
            self._native_stop_in_progress = True
            self._api = None
            self._native_stop_in_progress = False
            self._thread = None
            self._join_active = False
            self._native_init_started = False
            ingress_state = self._callback_ingress
            defer_ingress_cleanup = (
                self._native_request_inflight_refs > 0
                or self._callback_inflight_refs > 0
                or (
                    ingress_state is not None
                    and (ingress_state.native_call_refs > 0 or ingress_state.callback_refs > 0)
                )
            )
            if defer_ingress_cleanup:
                self._callback_ingress_deferred_cleanup = (
                    api,
                    spi,
                    join_required,
                    join_claimed,
                )

        if defer_ingress_cleanup:
            # The final callback/request lease schedules RegisterSpi(None) and
            # Release outside all SDK locks. The permanent owner is already
            # poisoned, so no new managed call can start in the meantime.
            return True
        if join_active:
            # RegisterSpi(None) is the vendor's documented callback
            # registration API; retaining ``spi`` above also protects a
            # callback already in flight while the registration is changed.
            with suppress(Exception):
                _detach_ctp_native_spi_once(api)
            return True

        if join_claimed:
            with suppress(Exception):
                _detach_ctp_native_spi_once(api)
            if _ctp_native_join_returned(api):
                if _release_retired_ctp_native_session_after_join(api):
                    with self._query_state_lock:
                        self._pending_native_join_api_ids.discard(id(api))
            return True

        _release_ctp_native_api_immediately(
            api,
            spi,
            state_lock=self._query_state_lock,
            pending_api_ids=self._pending_native_join_api_ids,
        )
        return True

    def stop(self):
        self._stop_native_session()

    def stop_and_wait(self, timeout: float = 2.0) -> CtpNativeStopReceipt:
        """Stop this trader API and return a bounded lifecycle receipt."""

        return _make_ctp_native_stop_receipt(
            self,
            timeout,
            lock=self._query_state_lock,
            api_attribute="_api",
        )

    @property
    def native_lifecycle_receipt(self) -> CtpNativeLifecycleReceipt | None:
        """Snapshot the current exact API/SPI teardown evidence without waiting."""

        with self._query_state_lock:
            state = self._native_lifecycle_state
            if state is None or (self._api is not None and state.api is not self._api):
                state = self._last_stop_lifecycle_state
            connection_generation = self._connection_generation
            thread = self._thread or self._last_stop_join_thread
        if state is None:
            return None
        return state.snapshot(
            connection_generation=connection_generation,
            timed_out=False,
            thread_alive=thread.is_alive() if thread is not None else False,
        )

    @property
    def is_ready(self):
        if self.auto_settlement_confirm:
            return self.is_trading_ready
        return self.is_read_only_ready

    @property
    def is_read_only_ready(self):
        with self._query_state_lock:
            return self._current_login_identity_locked() is not None

    @property
    def is_trading_ready(self):
        with self._query_state_lock:
            return (
                self.is_read_only_ready
                and self._settlement_state == "confirmed"
                and self._ready
                and self._has_current_settlement_readback_locked()
            )

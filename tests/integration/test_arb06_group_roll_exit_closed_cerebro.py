"""Close both accepted source legs through the normal Cerebro group route.

The group and its OPEN fills come from the accepted local R249 synthetic
provider fixture. The test then uses the normal Coordinator and Risk Hosts,
whose only simulated edge is a fixed full-fill response for each CLOSE. It
does not contact a live exchange or account. Its Gateway account view is an
explicit synthetic projection of a persisted source fill plus the separate
peer Risk allocation.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
import time
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any

import pytest

from bt_api_execution import GroupOrderState, SqliteOrderGroupStore
from bt_api_execution.group_roll_exit_contracts import GroupRollExitClosedProofV1
from bt_api_risk import RiskDeniedError
from backtrader.stores.service_execution_group import ServiceExecutionGroupError
from tests.integration._arb06_two_leg_roll_exit_risk_fixture import (
    dim05_roll_exit_risk_host,
)


_R18_SUPPORT_RELATIVE_PATH = Path(
    "test_support/arb06_r18_bt_support/executed/tests/integration/"
    "test_arb06_group_roll_exit_cerebro_start_diagnostic.py"
)
_R18_SUPPORT_SHA256 = "040e036e3166e0a07a31ebc434b24639bd6dcbff5aad3625aba4f99804e999d4"
_R18_SUPPORT_MODULE = "_bt_arb06_r18_roll_exit_support_for_closed_successor"
_GROUP_ID = "group-arb06-two-leg-roll-exit-closed-01"
_SOURCE_LEG_IDS = ("leg-a", "leg-b")
_CLOSE_LIMIT_PRICE = Decimal("101")
_RISK_GROUP_ROLL_EXIT_SUBMIT = "orders.submit_group_roll_exit"
_RESERVATION_OPERATIONS = frozenset(
    {"reservations.reserve", "reservations.query", "reservations.release"}
)
_ACTION_WAIT_SECONDS = 12.0
_GROUP_CLOSE_WAIT_SECONDS = 12.0


def _assert_decimal_text_equal(value: object, expected: str) -> None:
    assert isinstance(value, str)
    actual_decimal = Decimal(value)
    expected_decimal = Decimal(expected)
    assert actual_decimal.is_finite()
    assert expected_decimal.is_finite()
    assert actual_decimal == expected_decimal


def _load_r18_support() -> ModuleType:
    source_path = Path(__file__).resolve().parents[2] / _R18_SUPPORT_RELATIVE_PATH
    source = source_path.read_bytes()
    if hashlib.sha256(source).hexdigest() != _R18_SUPPORT_SHA256:
        raise AssertionError("accepted R18 Cerebro support source pin changed")
    existing = sys.modules.get(_R18_SUPPORT_MODULE)
    if existing is not None:
        if Path(getattr(existing, "__file__", "")).resolve() != source_path:
            raise AssertionError("a different R18 support module is already loaded")
        return existing
    spec = importlib.util.spec_from_file_location(_R18_SUPPORT_MODULE, source_path)
    if spec is None or spec.loader is None:
        raise AssertionError("accepted R18 Cerebro support cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_R18_SUPPORT_MODULE] = module
    spec.loader.exec_module(module)
    return module


def _coordinator_host_factory_with_reservation_query(
    r18: ModuleType,
    *,
    tmp_path: Path,
    dim05: ModuleType,
    risk_case,
    endpoint: str,
    server_public: bytes,
    server_secret: bytes,
    strategy_client_public: bytes,
):
    """Extend the accepted Coordinator Host with its exact read-only Risk route."""

    base_factory = r18._coordinator_host_factory(
        tmp_path,
        dim05=dim05,
        risk_case=risk_case,
        endpoint=endpoint,
        server_public=server_public,
        server_secret=server_secret,
        strategy_client_public=strategy_client_public,
    )

    def factory(cleanups):
        host = base_factory(cleanups)
        config = host._config.to_public_dict()
        profiles = config["communication"]["profiles"]
        risk_transport_ref = risk_case.entry_client_binding["transport_ref"]
        reservation_transport_ref = risk_case.reservation_client_binding["transport_ref"]
        risk_security_ref = profiles[risk_transport_ref]["security_profile_ref"]
        reservation_security_ref = profiles[reservation_transport_ref]["security_profile_ref"]

        requested_operations = dict(host._trusted_clients.requested_operations or {})
        requested_operations["upstream.account_reservations"] = _RESERVATION_OPERATIONS
        host._trusted_clients = r18.TrustedServiceClients(
            scope_resolver={
                risk_case.entry_scope_ref: risk_case.owner_scope,
                risk_case.query_scope_ref: risk_case.owner_scope,
                risk_case.reservation_scope_ref: risk_case.owner_scope,
            }.__getitem__,
            peer_resolver={
                risk_case.risk_identity.actor_ref: risk_case.risk_identity,
                risk_case.reservation_identity.actor_ref: risk_case.reservation_identity,
            }.__getitem__,
            transport_factory=r18.ZmqTransportFactory(
                {
                    risk_security_ref: r18.ClientCurveKeys(
                        server_key=risk_case.server_public_key,
                        public_key=risk_case.client_public_key,
                        secret_key=risk_case.client_secret_key,
                    ),
                    reservation_security_ref: r18.ClientCurveKeys(
                        server_key=risk_case.reservation_server_public_key,
                        public_key=risk_case.reservation_client_public_key,
                        secret_key=risk_case.reservation_client_secret_key,
                    ),
                }
            ),
            requested_operations=requested_operations,
        )
        directory = dict(host._service_directory)
        reservation_config = r18.parse_service_config(
            dict(risk_case.reservation_service_config)
        )
        directory[risk_case.reservation_identity.actor_ref] = reservation_config
        host._service_directory = MappingProxyType(directory)
        return host

    return factory


def _safe_rpc_code(code: object) -> str | None:
    if (
        type(code) is str
        and 1 <= len(code) <= 96
        and "A" <= code[0] <= "Z"
        and all("A" <= character <= "Z" or "0" <= character <= "9" or character == "_" for character in code)
    ):
        return code
    return None


def _safe_rpc_error_code(error: BaseException) -> str | None:
    try:
        return _safe_rpc_code(getattr(error, "code", None))
    except BaseException:
        return None


def _safe_rpc_exception_class(error: BaseException) -> str:
    name = type(error).__name__
    if (
        type(name) is str
        and 1 <= len(name) <= 64
        and name[0].isascii()
        and name[0].isalpha()
        and all(character.isascii() and (character.isalnum() or character == "_") for character in name)
    ):
        return name
    return "UnknownException"


def _install_first_submit_failure_diagnostic(
    r18: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    risk_fixture: ModuleType,
) -> dict[str, Any]:
    """Observe only safe first-failure metadata before Coordinator normalization."""

    group_module = sys.modules.get(r18.GroupCoordinatorTarget.__module__)
    component_module = sys.modules.get(r18.ComponentResources.__module__)
    if group_module is None or component_module is None:
        raise AssertionError("fixed R18 SDK operation modules are not loaded")

    port_type = getattr(group_module, "_OrdersRpcPort", None)
    client_type = getattr(component_module, "BorrowedServiceClient", None)
    if port_type is None or client_type is None:
        raise AssertionError("fixed R18 Risk submit adapter types are unavailable")
    risk_group_module = importlib.import_module("bt_api_py.service_risk_group_roll_exit")
    risk_group_owner_type = getattr(risk_group_module, "RiskGroupRollExitOwner", None)
    if risk_group_owner_type is None:
        raise AssertionError("fixed Risk group roll-exit owner type is unavailable")

    original_submit = port_type.submit_group_roll_exit
    original_call = client_type.call
    original_group_submit = risk_group_owner_type._submit
    diagnostic: dict[str, Any] = {
        "rpc_attempts": 0,
        "reservation_operations": [],
        "reply_category": "not_called",
        "reply_code": None,
        "reply_phase": None,
        "first_failure": None,
    }

    def capture_failure(
        error: BaseException | None,
        *,
        phase: str,
        reply_category: str,
        code: object = None,
    ) -> None:
        try:
            if diagnostic["first_failure"] is not None:
                return
            diagnostic["first_failure"] = {
                "phase": phase,
                "transport_reply_category": reply_category,
                "exception_class": (
                    _safe_rpc_exception_class(error) if error is not None else None
                ),
                "code": _safe_rpc_code(code)
                if code is not None
                else (_safe_rpc_error_code(error) if error is not None else None),
                "transport_reply_code": _safe_rpc_code(diagnostic["reply_code"]),
                "transport_reply_phase": diagnostic["reply_phase"],
                "public_frames": (
                    _safe_public_exception_frames(risk_fixture, error)
                    if error is not None
                    else []
                ),
            }
        except BaseException:
            # Diagnostic projection must never replace the source exception.
            return

    def update_transport_reply(response: object) -> str:
        category = reply_category(response)
        code = _safe_rpc_code(response.get("code")) if isinstance(response, Mapping) else None
        phase = None
        if isinstance(response, Mapping):
            result = response.get("result")
            candidate_phase = result.get("phase") if isinstance(result, Mapping) else None
            if type(candidate_phase) is str and candidate_phase in {
                "UNSTARTED",
                "PREPARED",
                "SUBMIT_STARTED",
                "STATUS_OBSERVED",
                "UNKNOWN",
                "RESOLVED",
                "NOT_FOUND",
            }:
                phase = candidate_phase
        diagnostic["reply_category"] = category
        diagnostic["reply_code"] = code
        diagnostic["reply_phase"] = phase
        failure = diagnostic["first_failure"]
        if type(failure) is dict:
            failure["transport_reply_category"] = category
            failure["transport_reply_code"] = code
            failure["transport_reply_phase"] = phase
        return category

    def reply_category(response: object) -> str:
        if not isinstance(response, Mapping):
            return "malformed_reply"
        if response.get("ok") is True and response.get("code") == "OK":
            return "success_reply"
        if response.get("ok") is False:
            return "refusal_reply"
        return "malformed_reply"

    def diagnostic_call(self, mount, operation, arguments, **kwargs):
        if mount == "upstream.account_reservations":
            diagnostic["reservation_operations"].append(operation)
        if operation != _RISK_GROUP_ROLL_EXIT_SUBMIT:
            return original_call(self, mount, operation, arguments, **kwargs)
        diagnostic["rpc_attempts"] += 1
        diagnostic["reply_category"] = "no_reply"
        diagnostic["reply_code"] = None
        try:
            response = original_call(self, mount, operation, arguments, **kwargs)
        except Exception as error:
            capture_failure(
                error,
                phase="risk_submit_transport",
                reply_category="no_reply",
            )
            raise
        try:
            category = update_transport_reply(response)
        except BaseException:
            return response
        if category in {"refusal_reply", "malformed_reply"}:
            capture_failure(
                None,
                phase="risk_submit_rpc_reply",
                reply_category=category,
                code=diagnostic["reply_code"],
            )
        return response

    def diagnostic_group_submit(self, *args, **kwargs):
        try:
            return original_group_submit(self, *args, **kwargs)
        except Exception as error:
            capture_failure(
                error,
                phase="risk_group_roll_exit_owner_exception",
                reply_category="not_observed",
            )
            raise

    def diagnostic_submit(self, authorization):
        attempts_before = diagnostic["rpc_attempts"]
        diagnostic["reply_category"] = "not_called"
        try:
            return original_submit(self, authorization)
        except Exception as error:
            was_called = diagnostic["rpc_attempts"] != attempts_before
            capture_failure(
                error,
                phase=("risk_submit_reply_validation" if was_called else "risk_submit_pre_rpc"),
                reply_category=(diagnostic["reply_category"] if was_called else "not_called"),
            )
            raise

    monkeypatch.setattr(client_type, "call", diagnostic_call)
    monkeypatch.setattr(port_type, "submit_group_roll_exit", diagnostic_submit)
    monkeypatch.setattr(risk_group_owner_type, "_submit", diagnostic_group_submit)
    return diagnostic


def _safe_public_exception_frames(
    risk_fixture: ModuleType, error: BaseException
) -> list[dict[str, Any]]:
    """Keep only bounded SDK/fixture frame coordinates, never exception text."""

    try:
        projection = risk_fixture._public_exception_projection(error)
        source_frames = projection.get("frames", ())
    except BaseException:
        return []
    if type(source_frames) is not list:
        return []
    safe_sources = {
        "bt_api_py",
        "bt_api_base",
        "bt_api_execution",
        "bt_api_gateway",
        "bt_api_monitor",
        "bt_api_risk",
        "bt_api_transport_zmq",
        "fixture",
    }
    result: list[dict[str, Any]] = []
    for row in source_frames[-8:]:
        if type(row) is not dict:
            continue
        source = row.get("source")
        relative_file = row.get("file")
        line = row.get("line")
        function = row.get("function")
        parts = relative_file.split("/") if type(relative_file) is str else ()
        if (
            source not in safe_sources
            or type(relative_file) is not str
            or not relative_file
            or len(relative_file) > 512
            or relative_file.startswith("/")
            or "\\" in relative_file
            or any(part in {"", ".", ".."} for part in parts)
            or type(line) is not int
            or line <= 0
            or type(function) is not str
            or not 1 <= len(function) <= 128
            or not function.isascii()
            or not all(character.isalnum() or character in "_<>." for character in function)
        ):
            continue
        result.append(
            {"source": source, "file": relative_file, "line": line, "function": function}
        )
    return result


def _read_provider_fill_for_order(
    provider_path: str | Path, provider_order_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(provider_path).resolve()
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT order_json, fills_json FROM provider_orders").fetchall()
    matches = []
    for order_text, fills_text in rows:
        order = json.loads(order_text)
        if order.get("order_id") == provider_order_id:
            matches.append((order, json.loads(fills_text)))
    if len(matches) != 1:
        raise AssertionError("source provider order does not have one persisted ledger row")
    order, fills = matches[0]
    if type(fills) is not list or len(fills) != 1 or type(fills[0]) is not dict:
        raise AssertionError("each accepted source fill must have one persisted fill row")
    return order, fills[0]


def _read_persisted_spot_open_fill(
    snapshot, provider_path: str | Path, instrument: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    plans = [
        plan
        for plan in snapshot.request.legs
        if plan.maximum_intent.instrument == instrument
        and plan.maximum_intent.position_effect.value == "OPEN"
    ]
    if len(plans) != 1:
        raise AssertionError("account projection requires one persisted spot OPEN source leg")
    progress = {row.leg_id: row for row in snapshot.legs}[plans[0].leg_id]
    if progress.child_status is None or not progress.child_status.provider_order_id:
        raise AssertionError("spot OPEN source leg is missing its persisted provider receipt")
    order, fill = _read_provider_fill_for_order(
        provider_path, progress.child_status.provider_order_id
    )
    if (
        order.get("symbol") != instrument
        or fill.get("symbol") != instrument
        or fill.get("side") != "buy"
        or Decimal(str(fill.get("quantity"))) != progress.child_status.filled_quantity
        or Decimal(str(fill.get("trade_price"))) != progress.child_status.average_price
        or Decimal(str(fill.get("fee_amount")))
        != progress.child_status.cumulative_commission
        or fill.get("fee_currency") != "USD"
    ):
        raise AssertionError("spot OPEN account projection differs from its persisted fill")
    return order, fill


def _assert_source_fee_evidence(snapshot, provider_path: str | Path) -> None:
    plans = {plan.leg_id: plan for plan in snapshot.request.legs}
    progress = {row.leg_id: row for row in snapshot.legs}
    assert tuple(plans) == _SOURCE_LEG_IDS
    for leg_id in _SOURCE_LEG_IDS:
        plan = plans[leg_id]
        row = progress[leg_id]
        status = row.child_status
        assert status is not None
        assert status.provider_order_id
        assert status.filled_quantity > 0
        assert status.cumulative_commission == Decimal("-0.05")
        assert status.cumulative_commission_currency == "USD"
        order, fill = _read_provider_fill_for_order(provider_path, status.provider_order_id)
        assert order["symbol"] == plan.maximum_intent.instrument
        assert Decimal(order["filled"]) == status.filled_quantity
        assert Decimal(fill["quantity"]) == status.filled_quantity
        assert Decimal(fill["trade_price"]) == status.average_price
        assert Decimal(fill["fee_amount"]) == status.cumulative_commission
        assert fill["fee_currency"] == status.cumulative_commission_currency
        assert fill["symbol"] == plan.maximum_intent.instrument


def _terminal_action(strategy, action_id: str) -> Mapping[str, Any]:
    deadline = time.monotonic() + _ACTION_WAIT_SECONDS
    last_action: Mapping[str, Any] | None = None
    while time.monotonic() < deadline:
        response = strategy.query_group_roll_exit(action_id)
        if response.get("ok") is not True or response.get("code") != "OK":
            raise AssertionError("normal action status query did not succeed")
        result = response.get("result")
        if not isinstance(result, Mapping) or result.get("found") is not True:
            raise AssertionError("persisted roll-exit action disappeared during query")
        action = result.get("action")
        if not isinstance(action, Mapping):
            raise AssertionError("roll-exit status omitted its action projection")
        last_action = action
        if action.get("phase") == "RESOLVED":
            if action.get("close_state") != "FILLED":
                raise AssertionError("roll-exit action did not resolve as a full fill")
            return action
        if action.get("phase") in {"UNKNOWN", "REJECTED"}:
            raise AssertionError(("roll-exit action requires recovery", action))
        time.sleep(0.025)
    raise AssertionError(("roll-exit action did not resolve", last_action))


def _closed_group_snapshot(strategy):
    deadline = time.monotonic() + _GROUP_CLOSE_WAIT_SECONDS
    last_state: str | None = None
    while time.monotonic() < deadline:
        snapshot = strategy.query_group_order(_GROUP_ID)
        if snapshot is not None:
            last_state = getattr(snapshot.state, "value", str(snapshot.state))
            if snapshot.state is GroupOrderState.CLOSED:
                return snapshot
            if last_state == GroupOrderState.RECOVERY_REQUIRED.value:
                raise AssertionError("group entered recovery instead of proof-gated closure")
        time.sleep(0.025)
    raise AssertionError(("group close proof was not projected", last_state))


class _ClosedGroupStrategy:
    """Strategy methods are attached to the real Backtrader Strategy below."""

    params = (
        ("strategy_ref", None),
        ("portfolio_ref", None),
        ("group_id", None),
        ("source_leg_ids", None),
        ("risk_case", None),
        ("account_view", None),
        ("apply_spot_close", None),
    )

    def start(self):
        self.bind_service_execution_group()
        self.initial_account_view = self.p.account_view()

    def next(self):
        if getattr(self, "_close_submitted", False):
            return
        self.initial_broker_state = (
            self.broker.getcash(),
            self.broker.getvalue(),
            self.broker.getposition(self.data).size,
        )
        self.initial_sizer_size = self.getsizing(data=self.data, isbuy=True)
        self.initial_sizer_cash = self.sizer.last_cash
        self.initial_sizer_equity = self.sizer.last_equity
        self.initial_sizer_price = self.sizer.last_price
        self._close_submitted = True
        self.actions = []
        for leg_id in self.p.source_leg_ids:
            response = self.submit_group_roll_exit(self.p.group_id, leg_id, _CLOSE_LIMIT_PRICE)
            if response.get("ok") is not True or response.get("code") != "OK":
                raise AssertionError(("normal roll-exit submit failed", leg_id, response))
            result = response.get("result")
            if not isinstance(result, Mapping) or result.get("found") is not True:
                raise AssertionError(("roll-exit submit omitted its accepted action", leg_id))
            submitted = result.get("action")
            if not isinstance(submitted, Mapping) or submitted.get("source_leg_id") != leg_id:
                raise AssertionError(("roll-exit action source identity changed", leg_id))
            action = _terminal_action(self, submitted["action_id"])
            if action["group_id"] != self.p.group_id or action["source_leg_id"] != leg_id:
                raise AssertionError("terminal action no longer matches its source request")
            self.actions.append(action)
            if leg_id == self.p.source_leg_ids[0]:
                calls_before_replay = self.p.risk_case.provider_calls()
                replay_response = self.submit_group_roll_exit(
                    self.p.group_id, leg_id, _CLOSE_LIMIT_PRICE
                )
                replay_result = replay_response.get("result")
                replay_action = (
                    replay_result.get("action") if isinstance(replay_result, Mapping) else None
                )
                if (
                    replay_response.get("ok") is not True
                    or replay_response.get("code") != "OK"
                    or not isinstance(replay_action, Mapping)
                    or replay_action != action
                ):
                    raise AssertionError(
                        "same source-leg request did not replay its terminal action"
                    )
                if self.p.risk_case.provider_calls() != calls_before_replay:
                    raise AssertionError(
                        "same source-leg request dispatched another provider CLOSE"
                    )

        calls_before_replay = self.p.risk_case.provider_calls()
        if len(calls_before_replay) != 2:
            raise AssertionError("two source legs must produce exactly two Risk CLOSE calls")
        self.spot_close_fill = self.p.apply_spot_close()
        self.after_broker_state = (
            self.broker.getcash(),
            self.broker.getvalue(),
            self.broker.getposition(self.data).size,
        )
        self.after_sizer_size = self.getsizing(data=self.data, isbuy=True)
        self.after_sizer_cash = self.sizer.last_cash
        self.after_sizer_equity = self.sizer.last_equity
        self.after_sizer_price = self.sizer.last_price
        self.after_account_view = self.p.account_view()
        replayed = []
        for action in self.actions:
            replayed.append(_terminal_action(self, action["action_id"]))
        if replayed != self.actions:
            raise AssertionError("query replay changed a persisted close action")
        calls_after_replay = self.p.risk_case.provider_calls()
        if calls_after_replay != calls_before_replay:
            raise AssertionError("status replay dispatched another provider CLOSE")
        self.closed_snapshot = _closed_group_snapshot(self)
        calls_after_close = self.p.risk_case.provider_calls()
        if calls_after_close != calls_before_replay:
            raise AssertionError("aggregate closure dispatched an extra provider CLOSE")


class _PeerRiskObserverStrategy:
    """Observe the shared account as a second strategy with no group route."""

    params = (
        ("strategy_ref", None),
        ("portfolio_ref", None),
        ("account_ref", None),
        ("risk_case", None),
        ("account_view", None),
        ("instrument", None),
        ("account_bundle", None),
    )

    def start(self):
        self.initial_account_view = self.p.account_view()
        self.initial_broker_state = (
            self.broker.getcash(),
            self.broker.getvalue(),
            self.broker.getposition(self.data).size,
        )
        self.initial_peer_quantity = self.p.risk_case.available(
            self.p.strategy_ref, self.p.instrument
        )
        self.provider_calls_before_bind = self.p.risk_case.provider_calls()
        self.gateway_provider_counts_before_bind = _gateway_provider_counts(self.p.account_bundle)
        try:
            self.bind_service_execution_group()
        except ServiceExecutionGroupError as error:
            self.group_bind_denial_code = error.code
        else:
            raise AssertionError("peer strategy acquired the source group route")
        self.provider_calls_after_bind = self.p.risk_case.provider_calls()
        self.gateway_provider_counts_after_bind = _gateway_provider_counts(self.p.account_bundle)

    def next(self):
        self.after_account_view = self.p.account_view()
        self.after_broker_state = (
            self.broker.getcash(),
            self.broker.getvalue(),
            self.broker.getposition(self.data).size,
        )
        self.after_peer_quantity = self.p.risk_case.available(
            self.p.strategy_ref, self.p.instrument
        )


def _gateway_provider_counts(account_bundle) -> tuple[int, int, int]:
    provider = account_bundle["provider"]
    return (provider.connect_count, provider.read_count, provider.close_count)


def _assert_peer_instrument_unconfigured(risk_case, instrument: str) -> None:
    with pytest.raises(RiskDeniedError) as denied:
        risk_case.available(risk_case.peer_strategy_ref, instrument)
    assert denied.value.code == "CLOSE_POSITION_UNCONFIGURED"


def _backtrader_strategy_type(r18: ModuleType):
    # The helper class is created against the accepted Backtrader module used
    # by the frozen R18 source support, so no alternate package copy is loaded.
    return type(
        "_Arb06ClosedGroupStrategy",
        (r18.bt.Strategy,),
        {
            "__module__": __name__,
            "params": _ClosedGroupStrategy.params,
            "start": _ClosedGroupStrategy.start,
            "next": _ClosedGroupStrategy.next,
        },
    )


def _backtrader_peer_strategy_type(r18: ModuleType):
    return type(
        "_Arb06PeerRiskObserverStrategy",
        (r18.bt.Strategy,),
        {
            "__module__": __name__,
            "params": _PeerRiskObserverStrategy.params,
            "start": _PeerRiskObserverStrategy.start,
            "next": _PeerRiskObserverStrategy.next,
        },
    )


def _backtrader_cash_percent_sizer_type(r18: ModuleType):
    def _getsizing(self, _comminfo, cash, data, isbuy):
        self.last_cash = Decimal(str(cash))
        self.last_equity = Decimal(str(self.broker.getvalue()))
        self.last_price = Decimal(str(data.close[0]))
        if not isbuy or not self.last_price.is_finite() or self.last_price <= 0:
            return 0
        return int(self.last_cash * Decimal("0.50") / self.last_price)

    return type(
        "_Arb06AccountCashPercentSizer",
        (r18.bt.Sizer,),
        {"_getsizing": _getsizing},
    )


@pytest.mark.integration
def test_arb06_two_leg_group_roll_exit_closes_with_persisted_proof_and_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Close both actual filled source legs and preserve another strategy's position."""

    r18 = _load_r18_support()
    risk_fixture = r18._load_fixed_risk_fixture()
    submit_diagnostic = _install_first_submit_failure_diagnostic(
        r18, monkeypatch, risk_fixture
    )
    dim05 = __import__(r18._DIM05_SOURCE_MODULE, fromlist=["*"])
    source_fixture = r18.arb06._load_fixed_partial_group_fixture()
    seed_path = Path(os.environ[r18.arb06._SDK_PARTIAL_FIXTURE_ENV]).resolve()
    assert Path(source_fixture.__file__).resolve() == seed_path
    assert hashlib.sha256(seed_path.read_bytes()).hexdigest() == r18._SEED_GROUP_FIXTURE_SHA256
    assert source_fixture._V2_INSTRUMENT == dim05._V2_INSTRUMENT
    assert source_fixture._PERP_INSTRUMENT == dim05._PERP_INSTRUMENT

    accounts = ("account-a",)
    expected_orders = {
        "account-a": (
            (source_fixture._V2_INSTRUMENT, "2", "100", "buy-limit"),
            (source_fixture._PERP_INSTRUMENT, "3", "100", "sell-limit"),
        )
    }
    rule_specs = {
        "account-a": {
            source_fixture._V2_INSTRUMENT: "2",
            source_fixture._PERP_INSTRUMENT: "1",
        }
    }
    provider_source = (
        Path(os.environ[r18._SDK_TESTS_ROOT_ENV]).resolve()
        / "unit"
        / "_service_group_provider_fixtures.py"
    )

    with r18._spawnable_seed_fixture_imports(
        tmp_path,
        seed_source=seed_path,
        provider_source=provider_source,
    ), source_fixture._GroupCluster(
        tmp_path,
        accounts=accounts,
        instruments={
            "account-a": (
                source_fixture._V2_INSTRUMENT,
                source_fixture._PERP_INSTRUMENT,
            )
        },
        initial_states={"account-a": ("cancelled:1.5", "filled")},
        expected_orders=expected_orders,
        rule_specs=rule_specs,
    ) as seed_cluster:
        seeded = seed_cluster.submit_group(
            source_fixture._group_request(
                _GROUP_ID,
                seed_cluster.metadata_reference_ns,
                (
                    (
                        _SOURCE_LEG_IDS[0],
                        "account-a",
                        source_fixture.Side.BUY,
                        Decimal("2"),
                        source_fixture._V2_INSTRUMENT,
                    ),
                    (
                        _SOURCE_LEG_IDS[1],
                        "account-a",
                        source_fixture.Side.SELL,
                        Decimal("4"),
                        source_fixture._PERP_INSTRUMENT,
                    ),
                ),
            )
        )
        assert seeded.state is GroupOrderState.PAIRED
        metadata_reference_ns = seed_cluster.metadata_reference_ns
        account_paths = {
            account_ref: dict(paths) for account_ref, paths in seed_cluster.account_paths.items()
        }
        coordinator_paths = dict(seed_cluster.coordinator_paths)

    source_account_path = account_paths["account-a"]["provider"]
    _assert_source_fee_evidence(seeded, source_account_path)

    with dim05_roll_exit_risk_host(
        tmp_path,
        account_paths=account_paths,
        coordinator_paths=coordinator_paths,
        metadata_reference_ns=metadata_reference_ns,
        group_id=_GROUP_ID,
        source_leg_ids=_SOURCE_LEG_IDS,
        seed_fixture=source_fixture,
        submit_diagnostic=submit_diagnostic,
    ) as risk_case:
        source_positions = risk_case.source_positions
        assert tuple(position.leg_id for position in source_positions) == _SOURCE_LEG_IDS
        assert tuple(position.filled_quantity for position in source_positions) == (
            Decimal("1.5"),
            Decimal("3"),
        )
        assert risk_case.source_strategy_ref == dim05._STRATEGY
        assert risk_case.owner_scope == source_fixture._owner_scope("account-a")
        assert risk_case.run_id == source_fixture._RUN
        assert risk_case.coordinator_identity.principal_ref == source_fixture._COORDINATOR_PRINCIPAL
        assert risk_case.coordinator_identity.actor_ref == source_fixture._COORDINATOR_SERVICE_ID
        assert risk_case.available(
            risk_case.source_strategy_ref, source_positions[0].instrument
        ) == Decimal("1.5")
        assert risk_case.available(
            risk_case.source_strategy_ref, source_positions[1].instrument
        ) == Decimal("3")
        assert risk_case.peer_strategy_ref != risk_case.source_strategy_ref
        assert risk_case.available(
            risk_case.peer_strategy_ref, source_positions[0].instrument
        ) == Decimal("0.75")
        # The peer Risk fixture configures only its spot allocation; absence
        # of a PERP allocation is represented by the typed denial, not zero.
        _assert_peer_instrument_unconfigured(risk_case, source_positions[1].instrument)
        reservation_components = risk_case.reservation_component_capabilities()
        assert len(reservation_components) == 1
        assert reservation_components[0]["instance_id"] == risk_case.reservation_instance_id
        assert reservation_components[0]["declared_ports"] == ["service.group_reservations"]
        assert reservation_components[0]["capabilities"] == [
            {
                "port": "service.group_reservations",
                "operations": sorted(_RESERVATION_OPERATIONS),
            }
        ]
        # The component advertises its standard three-operation contract.
        # The coordinator's trusted grant is scoped to this exact account route;
        # the pass-through call spy below proves this scenario actually queries only.
        assert risk_case.reservation_grant.instance_id == risk_case.reservation_instance_id
        assert risk_case.reservation_grant.port == "service.group_reservations"
        assert risk_case.reservation_grant.scope_ref == risk_case.reservation_scope_ref
        assert risk_case.reservation_grant.scope == risk_case.owner_scope
        assert risk_case.reservation_grant.operations == _RESERVATION_OPERATIONS
        assert risk_case.reservation_identity.actor_ref == risk_case.reservation_service_config[
            "service_id"
        ]
        assert risk_case.reservation_identity.principal_ref == (
            f"group-owner-service-principal-{risk_case.account_ref}"
        )
        assert (
            risk_case.reservation_client_binding["service_id"]
            == risk_case.reservation_identity.actor_ref
        )
        assert (
            risk_case.reservation_client_binding["instance_id"]
            == risk_case.reservation_instance_id
        )
        assert risk_case.reservation_client_binding["scope_ref"] == risk_case.reservation_scope_ref
        assert risk_case.reservation_client_binding["account_ref"] == risk_case.account_ref
        assert risk_case.reservation_scope_ref == source_fixture._route_refs("account-a")[0]
        seed_owner_config = source_fixture._account_service_config(
            "account-a",
            risk_case.reservation_endpoint,
            risk_case.reservation_security_ref,
        )
        assert risk_case.reservation_service_config["service_id"] == seed_owner_config["service_id"]
        assert risk_case.reservation_service_config["scope_ref"] == seed_owner_config["scope_ref"]
        assert risk_case.reservation_service_config["registration_policy_ref"] == seed_owner_config[
            "registration_policy_ref"
        ]
        assert risk_case.reservation_service_config["service_requirements_ref"] == seed_owner_config[
            "service_requirements_ref"
        ]
        assert risk_case.reservation_service_config["components"]["risk"] == seed_owner_config[
            "components"
        ]["risk"]
        coordinator_config = risk_case.risk_client_service_config
        execution_mounts = tuple(
            row["mount"]
            for row in coordinator_config["clients"]["execution"]["settings"]["bindings"]
        )
        risk_mounts = tuple(
            row["mount"]
            for row in coordinator_config["clients"]["risk"]["settings"]["bindings"]
        )
        assert execution_mounts == (
            "upstream.group_roll_exit_orders",
            "upstream.group_roll_exit_order_query",
        )
        assert risk_mounts == ("upstream.account_reservations",)
        assert "portfolio_ref" not in risk_case.reservation_client_binding
        assert risk_case.reservation_identity.actor_ref == seed_owner_config["service_id"]
        assert risk_case.reservation_authority_versions == {
            "scope": "group-service-scope-v1",
            "registration": "group-registration-v1",
            "requirements": "group-requirements-v1",
        }
        assert risk_case.provider_calls() == ()

        account_bundle = None
        account_runtime = None
        monitor_registry = None
        coordinator_loop = None
        primary_registry = None
        primary_runtime = None
        store = None
        group_runtime = None
        try:
            account_bundle = r18._start_account_host(
                tmp_path,
                dim05=dim05,
                risk_case=risk_case,
            )
            account_runtime = account_bundle["runtime"]
            spot_source_order, spot_source_fill = _read_persisted_spot_open_fill(
                seeded,
                source_account_path,
                source_positions[0].instrument,
            )
            source_spot_quantity = Decimal(str(spot_source_fill["quantity"]))
            source_spot_price = Decimal(str(spot_source_fill["trade_price"]))
            source_spot_fee = Decimal(str(spot_source_fill["fee_amount"]))
            peer_spot_quantity = risk_case.available(
                risk_case.peer_strategy_ref, source_positions[0].instrument
            )
            if source_spot_quantity != source_positions[0].filled_quantity:
                raise AssertionError("persisted source fill differs from the Risk allocation")
            if peer_spot_quantity <= 0:
                raise AssertionError("the same-account peer has no live Risk allocation")
            opening_cash = Decimal("10000")
            projected_initial_cash = (
                opening_cash - source_spot_quantity * source_spot_price - source_spot_fee
            )
            projected_initial_quantity = source_spot_quantity + peer_spot_quantity
            account_state = account_bundle["state"]
            account_composition = (
                {
                    "strategy_ref": risk_case.source_strategy_ref,
                    "quantity": source_spot_quantity,
                    "source": "persisted-provider-open-fill",
                    "provider_order_id": spot_source_order["order_id"],
                },
                {
                    "strategy_ref": risk_case.peer_strategy_ref,
                    "quantity": peer_spot_quantity,
                    "source": "live-risk-strategy-allocation",
                    "account_ref": risk_case.account_ref,
                },
            )
            # The synthetic Gateway provider projects the shared account from
            # the persisted source fill and the independent live peer Risk
            # allocation. It is an account-facing provider leaf, not seeded
            # Risk state or a pre-closed group.
            with account_state._lock:
                if account_state._applied_fill is not None:
                    raise AssertionError("synthetic account already has a close fill")
                account_state.cash = projected_initial_cash
                account_state.quantity = projected_initial_quantity
                account_state.mark_price = source_spot_price
                account_state.account_composition = account_composition
            account_bundle["arb06_projection"] = {
                "opening_cash": opening_cash,
                "initial_cash": projected_initial_cash,
                "initial_quantity": projected_initial_quantity,
                "composition": account_composition,
                "source_fill": dict(spot_source_fill),
                "peer_risk_quantity": peer_spot_quantity,
            }
            projection_receipt = account_bundle["loop"].call(
                lambda deployment: deployment.account_session_worker.refresh()
            )
            if projection_receipt is None:
                raise AssertionError("Gateway did not publish the derived initial snapshot")
            account_bundle["initial_view"] = account_bundle["account_client"].refresh()
            monitor_registry, monitor_identity, monitor_scope, monitor_calls = (
                r18._new_monitor_registry(
                    tmp_path,
                    dim05=dim05,
                    risk_case=risk_case,
                )
            )
            coordinator_endpoint = r18._endpoint()
            coordinator_server_public, coordinator_server_secret = r18.zmq.curve_keypair()
            strategy_client_public, strategy_client_secret = r18.zmq.curve_keypair()
            coordinator_loop = r18._CoordinatorHostLoop(
                _coordinator_host_factory_with_reservation_query(
                    r18,
                    tmp_path=tmp_path,
                    dim05=dim05,
                    risk_case=risk_case,
                    endpoint=coordinator_endpoint,
                    server_public=coordinator_server_public,
                    server_secret=coordinator_server_secret,
                    strategy_client_public=strategy_client_public,
                )
            )
            coordinator_host = coordinator_loop.start()
            (
                primary_registry,
                primary_runtime,
                store,
                broker,
                ordinary_writes,
            ) = r18._make_primary_writer_runtime(
                tmp_path,
                api=account_bundle["api"],
                execution_domain_ref=dim05._DOMAIN,
                peer_strategy_id=risk_case.source_strategy_ref,
                account_ref=risk_case.account_ref,
                run_id=risk_case.run_id,
            )
            client_config = r18._strategy_group_config(
                strategy_ref=risk_case.source_strategy_ref,
                coordinator_service_id=risk_case.coordinator_service_id,
                coordinator_instance_id=risk_case.coordinator_instance_id,
                coordinator_endpoint=coordinator_host.endpoint,
                group_scope_ref=dim05._COORDINATOR_SCOPE_REF,
                monitor_scope_ref=r18._MONITOR_SCOPE_REF,
                monitor_endpoint=r18._endpoint(),
                portfolio_ref=dim05._PORTFOLIO,
            )
            group_scope = dim05._stable_strategy_scope((risk_case.account_ref,))
            transport_factory = r18.ZmqTransportFactory(
                {
                    r18._STRATEGY_SECURITY_REF: r18.ClientCurveKeys(
                        server_key=coordinator_server_public,
                        public_key=strategy_client_public,
                        secret_key=strategy_client_secret,
                    ),
                }
            )
            coordinator_operations: list[str] = []
            monitor_operations: list[str] = []

            def group_transport(profile, expected_peer):
                if profile["security_profile_ref"] == r18._STRATEGY_SECURITY_REF:
                    transport = transport_factory(profile, expected_peer)
                    return r18._RecordingTransport(
                        transport,
                        coordinator_operations,
                        frozenset({"groups.roll_exit", "groups.query_roll_exit"}),
                    )
                if profile["security_profile_ref"] == r18._MONITOR_SECURITY_REF:
                    if expected_peer != monitor_identity:
                        raise AssertionError("Monitor registry peer identity changed")
                    transport = r18._RegistryTransport(monitor_registry, monitor_identity)
                    return r18._RecordingTransport(
                        transport, monitor_operations, r18._MONITOR_OPERATIONS
                    )
                raise AssertionError("strategy runtime requested an unbound transport")

            group_runtime = r18.ServiceClientRuntime(
                client_config,
                identity=r18.WireIdentity(
                    r18.WireRole.STRATEGY_CLIENT,
                    dim05._STRATEGY_PRINCIPAL,
                    risk_case.source_strategy_ref,
                ),
                scope_resolver={
                    dim05._COORDINATOR_SCOPE_REF: group_scope,
                    r18._MONITOR_SCOPE_REF: monitor_scope,
                }.__getitem__,
                peer_resolver={
                    risk_case.coordinator_service_id: risk_case.coordinator_identity,
                    r18._MONITOR_SERVICE_ID: monitor_identity,
                }.__getitem__,
                transport_factory=group_transport,
                run_id=risk_case.run_id,
                requested_operations={
                    "broker.order_groups": r18._GROUP_OPERATIONS,
                    "broker.group_monitor": r18._MONITOR_OPERATIONS,
                },
            )
            route = r18.ServiceStrategyGroupRoute(
                strategy_ref=risk_case.source_strategy_ref,
                portfolio_ref=dim05._PORTFOLIO,
                account_refs=(risk_case.account_ref,),
                runtime=group_runtime,
                group_scope_ref=dim05._COORDINATOR_SCOPE_REF,
                monitor_scope_ref=r18._MONITOR_SCOPE_REF,
                owned=True,
            )
            session = r18.ServiceExecutionSession(
                primary_runtime,
                mount="broker.orders",
                scope_ref=r18._ORDINARY_ORDER_SCOPE_REF,
                query_mount="broker.order_query",
                query_scope_ref=r18._ORDINARY_QUERY_SCOPE_REF,
                strategy_group_routes=(route,),
            )
            strategy_type = _backtrader_strategy_type(r18)

            def apply_spot_close_to_account():
                close_calls = risk_case.provider_calls()
                if len(close_calls) != 2:
                    raise AssertionError("both source CLOSE fills must be persisted first")
                spot_calls = [
                    call for call in close_calls if call[0] == source_positions[0].instrument
                ]
                if len(spot_calls) != 1:
                    raise AssertionError("the spot source leg must have one Risk CLOSE fill")
                fill = r18._read_risk_close_fill(risk_case, spot_calls[0][4])
                fill_quantity = Decimal(str(fill["quantity"]))
                fill_price = Decimal(str(fill["trade_price"]))
                fill_fee = Decimal(str(fill["fee_amount"]))
                if fill_quantity != source_spot_quantity:
                    raise AssertionError("persisted close fill does not close the source holding")
                expected_cash = (
                    account_state.cash + fill_quantity * fill_price - fill_fee
                )
                account_state.apply_close_fill(fill)
                if account_state.quantity != peer_spot_quantity:
                    raise AssertionError("closing the source fill changed the peer holding")
                if account_state.cash != expected_cash:
                    raise AssertionError("Gateway cash projection differs from the close fill")
                account_bundle["arb06_projection"]["close_fill"] = dict(fill)
                account_bundle["arb06_projection"]["final_cash"] = account_state.cash
                account_bundle["arb06_projection"]["final_quantity"] = account_state.quantity
                refreshed = account_bundle["loop"].call(
                    lambda deployment: deployment.account_session_worker.refresh()
                )
                if refreshed is None:
                    raise AssertionError(
                        "Gateway account worker did not return its refresh receipt"
                    )
                previous_view = account_bundle["account_client"].last_view
                if previous_view is None:
                    raise AssertionError("account client lost its initial accepted snapshot")
                account_bundle["monotonic_now"][0] = previous_view.fresh_until_monotonic + 1.0
                return fill

            cerebro = r18.bt.Cerebro(stdstats=False, runonce=False, preload=False)
            cerebro.setbroker(broker)
            frame = r18.pandas.DataFrame(
                {
                    "open": [100.0],
                    "high": [101.0],
                    "low": [99.0],
                    "close": [100.5],
                    "volume": [1.0],
                    "openinterest": [0.0],
                },
                index=[r18.dt.datetime(2026, 10, 17)],
            )
            cerebro.adddata(
                r18.bt.feeds.PandasData(dataname=frame),
                name=source_positions[0].instrument,
            )
            cerebro.addstrategy(
                strategy_type,
                strategy_ref=risk_case.source_strategy_ref,
                portfolio_ref=dim05._PORTFOLIO,
                group_id=_GROUP_ID,
                source_leg_ids=_SOURCE_LEG_IDS,
                risk_case=risk_case,
                account_view=lambda: account_bundle["account_client"].snapshot(),
                apply_spot_close=apply_spot_close_to_account,
            )
            peer_strategy_type = _backtrader_peer_strategy_type(r18)
            cerebro.addstrategy(
                peer_strategy_type,
                strategy_ref=risk_case.peer_strategy_ref,
                portfolio_ref=dim05._PORTFOLIO,
                account_ref=risk_case.account_ref,
                risk_case=risk_case,
                account_view=lambda: account_bundle["account_client"].snapshot(),
                instrument=source_positions[0].instrument,
                account_bundle=account_bundle,
            )
            cerebro.addsizer(_backtrader_cash_percent_sizer_type(r18))
            strategies = session.run(cerebro)

            assert session.state == "closed"
            assert session.cleanup_report.errors == ()
            assert session.cleanup_report.store_connected is False
            assert session.cleanup_report.runtime_state == "closed"
            assert session.cleanup_report.unregister_uncertainties == 0
            assert session.cleanup_report.cleanup_failures == 0
            assert primary_runtime.state == "closed"
            assert group_runtime.state == "closed"
            assert group_runtime.unregister_uncertainties == 0
            assert group_runtime.cleanup_failures == 0
            assert store.is_connected is False
            assert len(strategies) == 2
            strategy, peer_strategy = strategies
            assert strategy.initial_account_view is not None
            assert strategy.initial_broker_state == (9_850.05, 10_075.05, 2.25)
            assert strategy.after_broker_state == (10_001.6, 10_076.6, 0.75)
            assert strategy.initial_sizer_cash == Decimal("9850.05")
            assert strategy.initial_sizer_equity == Decimal("10075.05")
            assert strategy.initial_sizer_price == Decimal("100.5")
            assert strategy.initial_sizer_size == 49
            assert int(
                strategy.initial_sizer_equity * Decimal("0.50")
                / strategy.initial_sizer_price
            ) == 50
            assert strategy.after_sizer_cash == Decimal("10001.6")
            assert strategy.after_sizer_equity == Decimal("10076.6")
            assert strategy.after_sizer_price == Decimal("100.5")
            assert strategy.after_sizer_size == 49
            assert int(
                strategy.after_sizer_equity * Decimal("0.50")
                / strategy.after_sizer_price
            ) == 50
            assert (
                strategy.after_account_view.snapshot_id != strategy.initial_account_view.snapshot_id
            )
            _assert_decimal_text_equal(
                strategy.initial_account_view.observation.positions[0].quantity, "2.25"
            )
            _assert_decimal_text_equal(
                strategy.initial_account_view.observation.valuation.available_cash, "9850.05"
            )
            _assert_decimal_text_equal(
                strategy.initial_account_view.observation.valuation.equity, "10075.05"
            )
            assert strategy.after_account_view.observation.to_dict() == (
                account_bundle["state"].observations[-1].to_dict()
            )
            _assert_decimal_text_equal(
                strategy.after_account_view.observation.positions[0].quantity, "0.75"
            )
            _assert_decimal_text_equal(
                strategy.after_account_view.observation.valuation.available_cash, "10001.60"
            )
            _assert_decimal_text_equal(
                strategy.after_account_view.observation.valuation.equity, "10076.60"
            )
            assert account_bundle["arb06_projection"]["initial_quantity"] == Decimal("2.25")
            assert account_bundle["arb06_projection"]["initial_cash"] == Decimal("9850.05")
            assert account_bundle["arb06_projection"]["final_quantity"] == Decimal("0.75")
            assert account_bundle["arb06_projection"]["final_cash"] == Decimal("10001.60")
            assert account_state.account_composition == account_bundle["arb06_projection"]["composition"]
            assert account_state.account_composition[0]["strategy_ref"] == (
                risk_case.source_strategy_ref
            )
            assert account_state.account_composition[0]["provider_order_id"] == (
                spot_source_order["order_id"]
            )
            assert account_state.account_composition[1]["strategy_ref"] == (
                risk_case.peer_strategy_ref
            )
            assert account_state.account_composition[1]["quantity"] == Decimal("0.75")
            assert peer_strategy.p.strategy_ref == risk_case.peer_strategy_ref
            assert peer_strategy.p.account_ref == risk_case.account_ref
            assert peer_strategy.p.strategy_ref != risk_case.source_strategy_ref
            assert peer_strategy.initial_peer_quantity == Decimal("0.75")
            assert peer_strategy.after_peer_quantity == Decimal("0.75")
            assert peer_strategy.initial_broker_state == (9_850.05, 10_075.05, 2.25)
            assert peer_strategy.after_broker_state == (10_001.6, 10_076.6, 0.75)
            _assert_decimal_text_equal(
                peer_strategy.initial_account_view.observation.positions[0].quantity, "2.25"
            )
            _assert_decimal_text_equal(
                peer_strategy.after_account_view.observation.positions[0].quantity, "0.75"
            )
            assert peer_strategy.group_bind_denial_code == "GROUP_ROUTE_UNAVAILABLE"
            assert peer_strategy.provider_calls_before_bind == ()
            assert peer_strategy.provider_calls_after_bind == ()
            assert peer_strategy.gateway_provider_counts_before_bind == (
                peer_strategy.gateway_provider_counts_after_bind
            )
            assert strategy.spot_close_fill["symbol"] == source_positions[0].instrument
            assert Decimal(strategy.spot_close_fill["quantity"]) == Decimal("1.5")
            assert Decimal(strategy.spot_close_fill["trade_price"]) == _CLOSE_LIMIT_PRICE
            assert Decimal(strategy.spot_close_fill["fee_amount"]) == Decimal("-0.05")
            assert strategy.spot_close_fill["fee_currency"] == "USD"
            assert tuple(action["source_leg_id"] for action in strategy.actions) == _SOURCE_LEG_IDS
            assert tuple(action["phase"] for action in strategy.actions) == (
                "RESOLVED",
                "RESOLVED",
            )
            assert tuple(action["close_state"] for action in strategy.actions) == (
                "FILLED",
                "FILLED",
            )
            assert coordinator_operations.count("groups.roll_exit") == 3
            assert coordinator_operations.count("groups.query_roll_exit") >= 4
            reservation_operations = submit_diagnostic["reservation_operations"]
            assert len(reservation_operations) >= 1
            assert set(reservation_operations) == {"reservations.query"}
            # This close node intentionally makes no Monitor call. Zero calls
            # are not Monitor acceptance; the separate accepted unhedged-alert
            # evidence is round 169's group.residual relay/outbox receipt at
            # bt_api_py/docs/迭代计划/迭代10-可选组件与可配置通信/evidence/
            # arb06-group-monitor-relay-20261016/root-adjudication.md.
            assert monitor_operations == []
            assert monitor_calls == []
            assert ordinary_writes == []

            final_snapshot = strategy.closed_snapshot
            assert final_snapshot.state is GroupOrderState.CLOSED
            assert final_snapshot.residual_base_units == Decimal("0")
            assert final_snapshot.error_code is None
            assert final_snapshot.budget_reservation is not None
            assert final_snapshot.budget_reservation.state.value == "RELEASED"
            assert tuple(item.phase.value for item in final_snapshot.reservations) == ("RELEASED",)
            assert tuple(row.leg_id for row in final_snapshot.legs) == _SOURCE_LEG_IDS
            for row, source_position in zip(final_snapshot.legs, source_positions, strict=True):
                assert row.child_status is not None
                assert row.child_status.filled_quantity == source_position.filled_quantity
                assert row.child_status.cumulative_commission == Decimal("-0.05")
                assert row.child_status.cumulative_commission_currency == "USD"

            close_calls = risk_case.provider_calls()
            assert len(close_calls) == 2
            by_close_identity = {(call[0], call[1], call[3]): call for call in close_calls}
            expected_close_order_type_by_side = {
                source_fixture.Side.BUY: "sell-limit",
                source_fixture.Side.SELL: "buy-limit",
            }
            assert tuple(plan.maximum_intent.side for plan in seeded.request.legs) == (
                source_fixture.Side.BUY,
                source_fixture.Side.SELL,
            )
            for position, plan in zip(source_positions, seeded.request.legs, strict=True):
                side = plan.maximum_intent.side
                assert type(side) is source_fixture.Side
                assert side in expected_close_order_type_by_side
                expected_order_type = expected_close_order_type_by_side[side]
                call = by_close_identity[
                    (position.instrument, position.filled_quantity, expected_order_type)
                ]
                assert call[2] == _CLOSE_LIMIT_PRICE
                close_fill = r18._read_risk_close_fill(risk_case, call[4])
                assert close_fill["symbol"] == position.instrument
                assert Decimal(close_fill["quantity"]) == position.filled_quantity
                assert Decimal(close_fill["trade_price"]) == _CLOSE_LIMIT_PRICE
                assert Decimal(close_fill["fee_amount"]) == Decimal("-0.05")
                assert close_fill["fee_currency"] == "USD"

            for position in source_positions:
                assert risk_case.available(
                    risk_case.source_strategy_ref, position.instrument
                ) == Decimal("0")
            assert risk_case.available(
                risk_case.peer_strategy_ref, source_positions[0].instrument
            ) == Decimal("0.75")
            _assert_peer_instrument_unconfigured(
                risk_case, source_positions[1].instrument
            )

            close_store = SqliteOrderGroupStore(coordinator_paths["groups"])
            try:
                closed_events = close_store.events(dim05._PORTFOLIO, _GROUP_ID)
            finally:
                close_store.close()
            close_events = [
                event for event in closed_events if event.event_type == "GROUP_ROLL_EXIT_CLOSED"
            ]
            assert len(close_events) == 1
            payload = close_events[0].payload
            assert payload["schema"] == "group-roll-exit-closed-event-v1"
            proof = GroupRollExitClosedProofV1.from_payload(payload["proof"])
            assert payload["proof_sha256"] == proof.proof_sha256
            assert proof.portfolio_ref == dim05._PORTFOLIO
            assert proof.group_fingerprint == seeded.request.fingerprint
            assert proof.group_id == _GROUP_ID
            assert proof.group_version == seeded.request.version == 2
            assert tuple(leg.leg_id for leg in proof.legs) == _SOURCE_LEG_IDS
            for leg_proof, source_row, action in zip(
                proof.legs, seeded.legs, strategy.actions, strict=True
            ):
                source_status = source_row.child_status
                assert source_status is not None
                assert leg_proof.source_intent_id == source_status.intent_id
                assert leg_proof.source_filled_quantity == source_status.filled_quantity
                assert leg_proof.source_fee.intent_id == source_status.intent_id
                assert leg_proof.source_fee.amount == source_status.cumulative_commission
                assert leg_proof.source_fee.currency == "USD"
                assert len(leg_proof.close_actions) == 1
                close_action = leg_proof.close_actions[0]
                assert close_action.action_id == action["action_id"]
                assert close_action.close_quantity == source_status.filled_quantity
                assert close_action.close_fee_amount == Decimal("-0.05")
                assert close_action.close_fee_currency == "USD"
                assert len(close_action.receipt_sha256) == 64
                assert len(close_action.close_fee_evidence_sha256) == 64
            assert proof.budget_release is not None
            assert proof.budget_release.from_state == "HELD"
            assert proof.budget_release.to_state == "RELEASED"
        finally:
            r18._close_test_resources(
                (
                    ("group runtime", lambda: r18._close_runtime(group_runtime)),
                    ("ordinary runtime", lambda: r18._close_runtime(primary_runtime)),
                    ("Backtrader store", lambda: r18._stop_store(store)),
                    (
                        "account Store facade",
                        lambda: r18._close_account_facade(account_bundle),
                    ),
                    (
                        "account facade runtime",
                        lambda: r18._close_account_runtime(account_runtime),
                    ),
                    ("ordinary registry", lambda: r18._close_registry(primary_registry)),
                    ("Coordinator Host", lambda: r18._close_host_loop(coordinator_loop)),
                    (
                        "Monitor registration registry",
                        lambda: r18._close_registry(monitor_registry),
                    ),
                    ("Gateway account Host", lambda: r18._close_account_host(account_bundle)),
                )
            )

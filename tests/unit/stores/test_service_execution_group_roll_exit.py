"""Focused checks for the Backtrader DIM05 public client bridge."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_py.service_runtime import RegisteredBinding
from backtrader.stores.service_execution_group import (
    ServiceExecutionGroupAdapter,
    ServiceExecutionGroupError,
    ServiceGroupRollExitUnknownOutcomeError,
    ServiceStrategyGroupRoute,
    _GROUP_OPERATIONS,
    _GROUP_ROLL_EXIT_OPERATIONS,
    _unique_group_binding,
)


_STRATEGY = "strategy-dim05"
_PORTFOLIO = "portfolio-dim05"
_GROUP = "group-dim05"
_SOURCE_LEG = "leg-open"
_ACTION = "roll-exit-action"


class _Runtime:
    state = "registered"

    def __init__(self, response):
        self.response = response
        self.calls = []

    def call(self, mount, operation, arguments, **kwargs):
        self.calls.append((mount, operation, dict(arguments), dict(kwargs)))
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def _route(runtime):
    return ServiceStrategyGroupRoute(
        strategy_ref=_STRATEGY,
        portfolio_ref=_PORTFOLIO,
        account_refs=("account-dim05",),
        runtime=runtime,
        group_scope_ref="coordinator-scope-dim05",
        monitor_scope_ref="monitor-scope-dim05",
        owned=False,
    )


def _adapter(runtime):
    route = _route(runtime)
    adapter = ServiceExecutionGroupAdapter(SimpleNamespace(), (route,))
    adapter._roll_exit_route_keys = frozenset({(_STRATEGY, _PORTFOLIO)})
    adapter._route_for = lambda strategy, broker: route
    return adapter


def _registered_runtime(group_operations):
    runtime = _Runtime(_success({"found": False, "action": None}))
    runtime.run_id = "run-dim05"
    runtime.identity = WireIdentity(
        WireRole.STRATEGY_CLIENT,
        "strategy-principal-dim05",
        actor_ref=_STRATEGY,
    )
    group_scope = WireScope(
        execution_domain_ref="simnow",
        account_refs=("account-dim05",),
        strategy_ref=_STRATEGY,
        run_id=runtime.run_id,
        portfolio_ref=_PORTFOLIO,
    )
    monitor_scope = WireScope(
        execution_domain_ref="simnow",
        strategy_ref=_STRATEGY,
        run_id=runtime.run_id,
        portfolio_ref=_PORTFOLIO,
    )

    def binding(mount, scope_ref, scope, operations):
        return RegisteredBinding(
            mount=mount,
            service_id="group-coordinator-dim05",
            instance_id="group-coordinator-instance-dim05",
            scope_ref=scope_ref,
            scope=scope,
            registration_id=f"registration-{scope_ref}",
            service_epoch="epoch-dim05",
            operations=operations,
            expires_at=1_900_000_000,
            policy_version="policy-dim05",
            requirements_version="requirements-dim05",
            transport_ref="transport-dim05",
            timeout=1.0,
        )

    runtime.bindings = (
        binding(
            "broker.order_groups",
            "coordinator-scope-dim05",
            group_scope,
            group_operations,
        ),
        binding(
            "broker.group_monitor",
            "monitor-scope-dim05",
            monitor_scope,
            frozenset({"monitor.read_after"}),
        ),
    )
    return runtime


def _action(*, action_id=_ACTION, group_id=_GROUP, source_leg_id=_SOURCE_LEG):
    return {
        "action_id": action_id,
        "group_id": group_id,
        "source_leg_id": source_leg_id,
        "phase": "RESOLVED",
        "close_state": "FILLED",
        "requested_quantity": "1.5",
        "filled_quantity": "1.5",
        "order_revision": 1,
        "detail_code": None,
        "updated_at_ns": 1_800_000_000_000_000_000,
    }


def _success(result):
    return {"ok": True, "code": "OK", "result": result}


def test_roll_exit_uses_exact_coordinator_payload_and_returns_bounded_projection():
    runtime = _Runtime(_success({"found": True, "action": _action()}))
    adapter = _adapter(runtime)

    reply = adapter.roll_exit(
        object(), object(), _GROUP, _SOURCE_LEG, Decimal("12.500")
    )

    assert runtime.calls == [
        (
            "broker.order_groups",
            "groups.roll_exit",
            {
                "group_id": _GROUP,
                "source_leg_id": _SOURCE_LEG,
                "limit_price": "12.500",
            },
            {"portfolio_ref": _PORTFOLIO, "scope_ref": "coordinator-scope-dim05"},
        )
    ]
    assert reply["result"]["found"] is True
    assert dict(reply["result"]["action"]) == _action()
    assert "authorization" not in reply["result"]["action"]
    with pytest.raises(TypeError):
        reply["result"]["action"]["phase"] = "UNKNOWN"


@pytest.mark.parametrize(
    "limit_price",
    [12.5, Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("1e129")],
)
def test_roll_exit_rejects_invalid_price_before_dispatch(limit_price):
    runtime = _Runtime(_success({"found": True, "action": _action()}))

    with pytest.raises(ServiceExecutionGroupError) as error:
        _adapter(runtime).roll_exit(
            object(), object(), _GROUP, _SOURCE_LEG, limit_price
        )

    assert error.value.code == "GROUP_ROLL_EXIT_REQUEST_INVALID"
    assert runtime.calls == []


def test_roll_exit_query_is_read_only_and_accepts_not_found():
    runtime = _Runtime(_success({"found": False, "action": None}))
    adapter = _adapter(runtime)

    reply = adapter.query_roll_exit(object(), object(), _ACTION)

    assert runtime.calls == [
        (
            "broker.order_groups",
            "groups.query_roll_exit",
            {"action_id": _ACTION},
            {"portfolio_ref": _PORTFOLIO, "scope_ref": "coordinator-scope-dim05"},
        )
    ]
    assert reply["result"] == {"found": False, "action": None}


def test_roll_exit_preserves_pre_dispatch_denial_and_fences_uncertain_store_error():
    denied = _Runtime(
        {"ok": False, "code": "GROUP_ROLL_EXIT_NOT_AUTHORIZED", "result": {}}
    )
    with pytest.raises(ServiceExecutionGroupError) as error:
        _adapter(denied).roll_exit(
            object(), object(), _GROUP, _SOURCE_LEG, Decimal("12.5")
        )
    assert error.value.code == "GROUP_ROLL_EXIT_NOT_AUTHORIZED"

    uncertain = _Runtime(
        {"ok": False, "code": "GROUP_ROLL_EXIT_STORE_UNAVAILABLE", "result": {}}
    )
    with pytest.raises(ServiceGroupRollExitUnknownOutcomeError) as error:
        _adapter(uncertain).roll_exit(
            object(), object(), _GROUP, _SOURCE_LEG, Decimal("12.5")
        )
    assert error.value.group_id == _GROUP
    assert error.value.source_leg_id == _SOURCE_LEG
    assert error.value.detail_code == "GROUP_ROLL_EXIT_STORE_UNAVAILABLE"


def test_roll_exit_rejects_a_success_reply_with_a_different_source_as_unknown():
    runtime = _Runtime(
        _success({"found": True, "action": _action(source_leg_id="another-leg")})
    )

    with pytest.raises(ServiceGroupRollExitUnknownOutcomeError):
        _adapter(runtime).roll_exit(
            object(), object(), _GROUP, _SOURCE_LEG, Decimal("12.5")
        )


def test_roll_exit_never_projects_internal_authorization_fields():
    action = _action()
    action["authorization"] = {"private": "must-not-cross-the-client-boundary"}
    runtime = _Runtime(_success({"found": True, "action": action}))

    with pytest.raises(ServiceGroupRollExitUnknownOutcomeError):
        _adapter(runtime).roll_exit(
            object(), object(), _GROUP, _SOURCE_LEG, Decimal("12.5")
        )


def test_group_binding_accepts_legacy_or_exact_roll_exit_operation_set():
    legacy = SimpleNamespace(
        active=True,
        mount="broker.order_groups",
        scope_ref="scope",
        operations=_GROUP_OPERATIONS,
    )
    extended = SimpleNamespace(
        active=True,
        mount="broker.order_groups",
        scope_ref="scope",
        operations=_GROUP_ROLL_EXIT_OPERATIONS,
    )
    unsupported = SimpleNamespace(
        active=True,
        mount="broker.order_groups",
        scope_ref="scope",
        operations=_GROUP_ROLL_EXIT_OPERATIONS | {"groups.cancel"},
    )

    assert _unique_group_binding((legacy,), "broker.order_groups", "scope") is legacy
    assert _unique_group_binding((extended,), "broker.order_groups", "scope") is extended
    with pytest.raises(ServiceExecutionGroupError):
        _unique_group_binding((unsupported,), "broker.order_groups", "scope")


@pytest.mark.parametrize(
    ("operations", "roll_exit_enabled"),
    [(_GROUP_OPERATIONS, False), (_GROUP_ROLL_EXIT_OPERATIONS, True)],
)
def test_route_validation_enables_only_the_exact_extended_binding(
    operations, roll_exit_enabled
):
    runtime = _registered_runtime(operations)
    route = _route(runtime)
    broker = object()
    adapter = ServiceExecutionGroupAdapter(
        SimpleNamespace(_broker=broker), (route,)
    )

    adapter.validate_registered_routes()

    route_key = (_STRATEGY, _PORTFOLIO)
    assert (route_key in adapter._roll_exit_route_keys) is roll_exit_enabled

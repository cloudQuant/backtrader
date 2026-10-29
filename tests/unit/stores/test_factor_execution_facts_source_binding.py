"""Source binding for sparse fee-pair OPEN and RELEASE Journal scopes."""

from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import threading
import time
import weakref

import pytest

import backtrader.stores.factor_execution_facts as facts_module
from backtrader.stores.factor_execution_facts import (
    FactorExecutionFacts,
    FactorExecutionFactsSourceError,
    fee_pair_facts_open_source_scope,
    fee_pair_facts_release_source_scope,
    validate_factor_execution_facts_source,
    validate_fee_pair_facts_source_lease,
)
from tests.unit.stores.test_factor_execution_facts import (
    _commission_row,
    _multi_target_commission_projection_case,
    _project,
    _refresh_all,
    _system_under_test,
)


def _source_backed_facts():
    now = datetime.now(timezone.utc)
    api, store, broker, journal, _coordinator, target = _system_under_test(now=now)
    receipt = _refresh_all(store, target)
    facts = _project(store, broker, target, now, query_set=receipt.query_set)
    return now, api, store, broker, journal, target, facts


def _install_fake_canonical_session_lock(monkeypatch):
    """Give the public fake SDK client a stable lock/getter binding."""

    def getters(client):
        lock = getattr(client, "_query_state_lock", None)
        if lock is None:
            lock = threading.RLock()
            client._query_state_lock = lock
        return client.get_query_session_scope, client.get_session_state, lock

    monkeypatch.setattr(facts_module, "_canonical_sdk_session_getters", getters)


@pytest.fixture(autouse=True)
def _bind_fake_clients_to_canonical_session_lock(monkeypatch):
    _install_fake_canonical_session_lock(monkeypatch)


def _pair_case(monkeypatch):
    _install_fake_canonical_session_lock(monkeypatch)
    case = _multi_target_commission_projection_case(
        (
            _commission_row(),
            _commission_row(instrument="i2510", exchange="DCE"),
        ),
        execution_target_ids=("A", "B"),
    )
    pair = (case.targets[0], case.targets[1])
    return case, pair


def _scope_args(facts):
    marker = facts._source_projection
    return {
        "now": marker.projected_at,
        "max_query_age": timedelta(seconds=10),
    }


def test_source_binding_accepts_real_store_broker_and_fake_query_leaves():
    now, _api, store, broker, _journal, _target, facts = _source_backed_facts()

    assert type(store).__name__ == "RegisteredSimStore"
    assert type(broker).__name__ == "BtApiBroker"
    assert validate_factor_execution_facts_source(facts, store, broker, now=now) is True


def test_projection_marker_retains_only_weak_object_bindings_and_request_ids():
    _now, _api, _store, _broker, _journal, _target, facts = _source_backed_facts()
    marker = facts._source_projection

    assert isinstance(marker.facts_ref, weakref.ReferenceType)
    assert isinstance(marker.store_ref, weakref.ReferenceType)
    assert isinstance(marker.broker_ref, weakref.ReferenceType)
    assert isinstance(marker.api_ref, weakref.ReferenceType)
    assert isinstance(marker.client_ref, weakref.ReferenceType)
    assert len(marker.core_entries) == 5
    assert all(type(request_id) is int for _family, _key, request_id in marker.core_entries)
    assert all(isinstance(record[3], weakref.ReferenceType) for record in marker.targets)


def test_constructed_replaced_and_cross_store_facts_are_rejected():
    now, _api, store, broker, _journal, _target, facts = _source_backed_facts()
    replaced = replace(facts, blockers=tuple(facts.blockers))
    constructed = FactorExecutionFacts(
        **{item.name: getattr(facts, item.name) for item in fields(facts) if item.init}
    )
    _other_api, other_store, other_broker, _journal2, _coordinator2, _target2 = (
        _system_under_test(now=now)
    )

    assert replaced == facts
    assert constructed == facts
    assert validate_factor_execution_facts_source(replaced, store, broker, now=now) is False
    assert validate_factor_execution_facts_source(constructed, store, broker, now=now) is False
    assert validate_factor_execution_facts_source(facts, other_store, broker, now=now) is False
    assert validate_factor_execution_facts_source(facts, store, other_broker, now=now) is False


def test_source_binding_rejects_session_change_cache_replacement_and_expiry():
    now, api, store, broker, _journal, target, facts = _source_backed_facts()
    assert validate_factor_execution_facts_source(facts, store, broker, now=now) is True

    api.trader_client._connection_generation += 1
    assert validate_factor_execution_facts_source(facts, store, broker, now=now) is False

    now2, _api2, store2, broker2, _journal2, target2, facts2 = _source_backed_facts()
    _refresh_all(store2, target2)
    assert validate_factor_execution_facts_source(facts2, store2, broker2, now=now2) is False

    now3, _api3, store3, broker3, _journal3, _target3, facts3 = _source_backed_facts()
    entry = store3._ctp_query_snapshots["account_result", ()]
    entry["source_expires_monotonic"] = time.monotonic() - 1
    assert validate_factor_execution_facts_source(facts3, store3, broker3, now=now3) is False
    assert (
        validate_factor_execution_facts_source(
            facts3, store3, broker3, now=now3 + timedelta(seconds=11)
        )
        is False
    )


def test_source_binding_rejects_current_broker_position_change():
    now, _api, _store, broker, _journal, target, facts = _source_backed_facts()
    data_name = broker._position_key(target.data)
    position = broker.positions[data_name]
    position.size = Decimal(position.size) + Decimal(1)

    assert validate_factor_execution_facts_source(facts, _store, broker, now=now) is False


def test_release_scope_holds_exact_pair_source_and_invalidates_lease_on_exit(monkeypatch):
    case, pair = _pair_case(monkeypatch)
    kwargs = _scope_args(case.facts)
    with fee_pair_facts_release_source_scope(
        case.store, case.broker, case.facts, targets=pair, **kwargs
    ) as lease:
        assert lease.is_for_operation("RELEASE")
        assert validate_fee_pair_facts_source_lease(
            lease, case.facts, operation="RELEASE"
        ) is True
        assert validate_fee_pair_facts_source_lease(
            lease, case.facts, operation="OPEN"
        ) is False
        lease.require_valid()
    assert validate_fee_pair_facts_source_lease(
        lease, case.facts, operation="RELEASE"
    ) is False


def test_release_scope_rejects_reconstructed_target_objects(monkeypatch):
    case, pair = _pair_case(monkeypatch)
    forged = replace(pair[0])

    with pytest.raises(FactorExecutionFactsSourceError), fee_pair_facts_release_source_scope(
        case.store,
        case.broker,
        case.facts,
        targets=(forged, pair[1]),
        **_scope_args(case.facts),
    ):
        pytest.fail("reconstructed target identity must block RELEASE")


def test_release_scope_rechecks_monotonic_expiry_before_commit(monkeypatch):
    case, pair = _pair_case(monkeypatch)
    entry = case.store._ctp_query_snapshots["account_result", ()]
    expiry = entry["source_expires_monotonic"]
    observed = [time.monotonic()]
    monkeypatch.setattr(facts_module.time, "monotonic", lambda: observed[0])

    with fee_pair_facts_release_source_scope(
        case.store, case.broker, case.facts, targets=pair, **_scope_args(case.facts)
    ) as lease:
        lease.require_valid()
        observed[0] = expiry + 0.001
        with pytest.raises(FactorExecutionFactsSourceError):
            lease.require_valid()


def test_release_scope_rejects_account_wide_dispatching_state(monkeypatch):
    case, pair = _pair_case(monkeypatch)
    case.api._dispatching_order_ids.add("synthetic-pending")

    with pytest.raises(
        FactorExecutionFactsSourceError
    ), fee_pair_facts_release_source_scope(
        case.store,
        case.broker,
        case.facts,
        targets=pair,
        **_scope_args(case.facts),
    ):
        pytest.fail("account-wide dispatching state must block RELEASE")


def test_open_scope_binds_quote_route_margin_commission_and_broker(monkeypatch):
    case, pair = _pair_case(monkeypatch)
    kwargs = _scope_args(case.facts)
    kwargs["quote_max_age"] = timedelta(seconds=2)
    with fee_pair_facts_open_source_scope(
        case.store, case.broker, case.facts, targets=pair, **kwargs
    ) as lease:
        assert case.store._latest_tick_lock.acquire(blocking=False) is False
        assert lease.is_for_operation("OPEN")
        assert validate_fee_pair_facts_source_lease(
            lease, case.facts, operation="OPEN"
        ) is True
        lease.require_valid()


def test_open_scope_fails_closed_if_quote_or_commission_source_changes(monkeypatch):
    case, pair = _pair_case(monkeypatch)
    target = pair[0]
    current_tick = case.store._latest_ticks[target.instrument]
    current_tick.sequence += 1
    with pytest.raises(FactorExecutionFactsSourceError), fee_pair_facts_open_source_scope(
        case.store,
        case.broker,
        case.facts,
        targets=pair,
        quote_max_age=timedelta(seconds=2),
        max_query_age=timedelta(seconds=10),
        now=case.facts._source_projection.projected_at,
    ):
        pytest.fail("changed consumed quote must block OPEN")

    case2, pair2 = _pair_case(monkeypatch)
    target2 = pair2[0]
    key = facts_module._query_snapshot_key(
        "instrument_commission_rate_result",
        {"instrument_id": target2.instrument, "exchange_id": target2.exchange},
    )
    old_entry = case2.store._ctp_commission_query_snapshots[key]
    replacement = dict(old_entry)
    replacement_rows = [dict(row) for row in old_entry["rows"]]
    replacement_rows[0]["OpenRatioByVolume"] = "9.0"
    replacement["rows"] = replacement_rows
    case2.store._ctp_commission_query_snapshots[key] = replacement
    with pytest.raises(FactorExecutionFactsSourceError), fee_pair_facts_open_source_scope(
        case2.store,
        case2.broker,
        case2.facts,
        targets=pair2,
        quote_max_age=timedelta(seconds=2),
        max_query_age=timedelta(seconds=10),
        now=case2.facts._source_projection.projected_at,
    ):
        pytest.fail("changed commission cache data must block OPEN")

    case3, pair3 = _pair_case(monkeypatch)
    margin_key = facts_module._query_snapshot_key(
        "instrument_margin_rate_result",
        {"instrument_id": pair3[0].instrument, "exchange_id": pair3[0].exchange, "hedge_flag": "1"},
    )
    old_margin_entry = case3.store._ctp_query_snapshots[margin_key]
    replacement_margin = dict(old_margin_entry)
    replacement_margin_rows = [dict(row) for row in old_margin_entry["rows"]]
    replacement_margin_rows[0]["LongMarginRatioByVolume"] = "99"
    replacement_margin["rows"] = replacement_margin_rows
    case3.store._ctp_query_snapshots[margin_key] = replacement_margin
    with pytest.raises(FactorExecutionFactsSourceError), fee_pair_facts_open_source_scope(
        case3.store,
        case3.broker,
        case3.facts,
        targets=pair3,
        quote_max_age=timedelta(seconds=2),
        max_query_age=timedelta(seconds=10),
        now=case3.facts._source_projection.projected_at,
    ):
        pytest.fail("changed margin cache data must block OPEN")

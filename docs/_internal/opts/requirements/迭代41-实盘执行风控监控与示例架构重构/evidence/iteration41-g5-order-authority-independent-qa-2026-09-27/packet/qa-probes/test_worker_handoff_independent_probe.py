from __future__ import annotations

from dataclasses import replace

import pytest

from bt_api_execution.errors import ContractValidationError
from bt_api_execution.ctp_single_worker_candidate import CtpManagedSingleWorkerCandidate
from test_g5_single_worker_action_handoff import (
    _open,
    _prepared,
    _reserve_action,
    _seed_order,
    _target_projection,
)


def test_identical_cancel_stage_reuses_exact_durable_action_identity(tmp_path):
    store, authority, scope, lease = _open(tmp_path / "duplicate-stage.sqlite3")
    try:
        order = _seed_order(authority, scope, lease)
        action = _reserve_action(authority, scope, lease, order)
        prepared = _prepared(order)
        projection = _target_projection(store, order, prepared)
        worker = CtpManagedSingleWorkerCandidate(store, scope, lease, authority)

        first = worker.stage_prepared_dispatch(
            prepared, cancel_target_projection=projection, action_identity=action
        )
        second = worker.stage_prepared_dispatch(
            prepared, cancel_target_projection=projection, action_identity=action
        )

        command = store.read_ctp_dispatch_command(scope, prepared.command_id)
        assert command is not None and command.status == "READY"
        assert first == second
        assert command.request_payload["OrderActionRef"] == action.native_action_ref
        assert store._connection.execute(
            "SELECT COUNT(*) FROM g5_ctp_worker_handoffs WHERE command_id=?",
            (prepared.command_id,),
        ).fetchone()[0] == 1
        assert store._connection.execute(
            "SELECT COUNT(*) FROM ctp_action_identity_reservations WHERE managed_action_id=?",
            (action.managed_action_id,),
        ).fetchone()[0] == 1
    finally:
        store.close()


def test_without_frozen_store_target_readback_cancel_fails_before_command(tmp_path):
    store, authority, scope, lease = _open(tmp_path / "missing-target-reader.sqlite3")
    try:
        assert not hasattr(type(store), "read_ctp_order_target_projection")
        order = _seed_order(authority, scope, lease)
        action = _reserve_action(authority, scope, lease, order)
        prepared = _prepared(order)
        projection = _target_projection(store, order, prepared)
        del store.read_ctp_order_target_projection
        worker = CtpManagedSingleWorkerCandidate(store, scope, lease, authority)

        with pytest.raises(ContractValidationError, match="target readback is unavailable"):
            worker.stage_prepared_dispatch(
                prepared, cancel_target_projection=projection, action_identity=action
            )

        assert store.read_ctp_dispatch_command(scope, prepared.command_id) is None
        assert store._connection.execute(
            "SELECT COUNT(*) FROM g5_ctp_worker_handoffs WHERE command_id=?",
            (prepared.command_id,),
        ).fetchone()[0] == 0
    finally:
        store.close()


def test_typed_but_altered_action_identity_cannot_stage_cancel(tmp_path):
    store, authority, scope, lease = _open(tmp_path / "altered-action-identity.sqlite3")
    try:
        order = _seed_order(authority, scope, lease)
        action = _reserve_action(authority, scope, lease, order)
        prepared = _prepared(order)
        projection = _target_projection(store, order, prepared)
        forged = replace(action, native_action_ref=action.native_action_ref + 1)
        worker = CtpManagedSingleWorkerCandidate(store, scope, lease, authority)

        with pytest.raises(ContractValidationError, match="typed ActionRef identity differs"):
            worker.stage_prepared_dispatch(
                prepared, cancel_target_projection=projection, action_identity=forged
            )

        assert store.read_ctp_dispatch_command(scope, prepared.command_id) is None
        assert store._connection.execute(
            "SELECT COUNT(*) FROM g5_ctp_worker_handoffs WHERE command_id=?",
            (prepared.command_id,),
        ).fetchone()[0] == 0
    finally:
        store.close()

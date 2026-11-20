"""Regression tests for R71-133: bounded Gateway history trim in PendingCommandStore."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest

pytest.importorskip("bt_api_py", reason="GatewayPendingHost requires bt_api_py")

from bt_api_base.direct_write_protocol import NativeOrderIdentity
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding, GatewayCommandRecord
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_py._contracts.models import OrderRequest, OrderType, Side
from bt_api_py.gateway_direct_client import (
    GatewayClientRoute,
    build_gateway_order_intent,
)

from backtrader.live_state import LiveStateError, PendingCommandStore, rebind_identity
from backtrader.live_state.gateway_pending import (
    GatewayPendingHost,
    has_unresolved_gateway_intents,
)
from backtrader.live_state.pending import HISTORY_LIMIT, validate_pending_state
from ._helpers import place_record


@pytest.fixture
def gateway_inputs():
    binding = GatewayCommandBinding("journal-r71", "account-r71", "strategy-r71", "principal-r71")
    route = GatewayClientRoute(
        "broker.direct_write",
        "service-r71",
        "instance-r71",
        "scope-r71",
        WireScope(
            "paper:demo",
            account_ref="account-r71",
            strategy_ref="strategy-r71",
            run_id="run-r71",
        ),
        WireIdentity(WireRole.STRATEGY_CLIENT, "principal-r71", "strategy-r71"),
    )

    def make_intent(key: str, *, price: str = "10"):
        req = OrderRequest(
            symbol="rb2610",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            account_id="account-r71",
            client_order_id=f"cid-{key}",
            price=Decimal(price),
            idempotency_key=key,
        )
        return build_gateway_order_intent(binding, route, req, ttl_seconds=10)

    return binding, route, make_intent


_STATE_VERSIONS = {
    "RESERVED": 1,
    "DISPATCHING": 2,
    "SENT": 3,
    "NOT_SENT": 3,
    "UNKNOWN": 3,
    "RELEASED": 2,
    "EXPIRED": 2,
}


def _record(intent, *, state: str = "RESERVED", native=None, strong=()):
    release_op = f"op-{intent.request_key}" if state == "RELEASED" else None
    release_ver = 1 if state == "RELEASED" else None
    return GatewayCommandRecord(
        1,
        intent.binding,
        intent.request_key,
        f"res-{intent.request_key}",
        intent.digest,
        state,
        _STATE_VERSIONS[state],
        "g1",
        "g1",
        True,
        9.0 if state == "RESERVED" else None,
        False,
        release_op,
        release_ver,
        native,
        strong,
    )


def _seed_gateway_terminal_marker(
    raw_state: dict, strategy_uuid: str, intent, record_state: str, idx: int
):
    """Build a valid v2 intent+record+TERMINAL marker directly in raw_state for fast bulk tests."""
    import hashlib
    from bt_api_py.gateway_direct_client import gateway_intent_to_mapping

    req_key = intent.request_key
    marker_id = str(uuid.uuid4())
    now = "2026-11-20T00:00:00Z"
    native = None
    strong = ()
    if record_state == "NOT_SENT":
        native = NativeOrderIdentity("CTP", f"cid-ns-{idx}", {"order_ref": str(idx + 1)}, 1)
        strong = (hashlib.sha256(f"strong-{idx}".encode()).hexdigest(),)
    record = _record(intent, state=record_state, native=native, strong=strong)
    raw_state["gateway"]["intents"][req_key] = {
        "intent": gateway_intent_to_mapping(intent),
        "record": record.to_mapping(),
        "marker_id": marker_id,
        "release": None,
        "local_seq": None,
        "bt_ref": None,
    }
    marker = {
        "marker_id": marker_id,
        "status": "TERMINAL",
        "operation": "place",
        "host_scope": strategy_uuid,
        "local_seq": None,
        "bt_ref": None,
        "exchange_name": native.exchange_name if native else None,
        "symbol": "rb2610",
        "client_order_id": native.client_order_id if native else None,
        "native_identity": dict(native.fields) if native else {},
        "target_identity": None,
        "request_summary": json.loads(intent.canonical_payload),
        "trading_day": None,
        "session_generation": native.session_generation if native else None,
        "created_at_utc": None,
        "committed_at_utc": now,
        "updated_at_utc": now,
        "facts": {},
        "transitions": [{"from": "PREPARED", "to": "TERMINAL", "at_utc": now}],
        "extra": {},
        "resolution": None,
        "gateway_ref": {"request_key": req_key},
    }
    raw_state["history"].append(marker)
    return marker_id


def test_r71_133_finalized_gateway_history_trimmed_to_default_500_while_active_preserved(
    state, gateway_inputs
):
    """600+ finalized Gateway markers are bounded to HISTORY_LIMIT (500); active markers stay."""
    binding, _, make_intent = gateway_inputs
    host = GatewayPendingHost.upgrade_for_gateway(
        state.strategy_dir, state.strategy_uuid, binding, max_entries=2000
    )

    # Create 2 active gateway markers (PREPARED and UNKNOWN) that must never be evicted.
    active_ids = []
    for key, target_status in (("active-prepared", None), ("active-unknown", "UNKNOWN")):
        intent = make_intent(key)
        host.save_intent(intent)
        rec = _record(intent, state="RESERVED")
        host.save_record(key, rec)
        mid = host.commit_pre_dispatch(key, rec)
        if target_status:
            assert state.pending.mark(mid, target_status)
        active_ids.append(mid)

    # Seed 610 finalized (RELEASED / NOT_SENT / EXPIRED) TERMINAL gateway markers in pending.json.
    with open(state.pending.path, encoding="utf-8") as fh:
        raw = json.load(fh)
    final_states = ("RELEASED", "NOT_SENT", "EXPIRED")
    seeded_ids = []
    for idx in range(610):
        intent = make_intent(f"fin-{idx:04d}")
        mid = _seed_gateway_terminal_marker(
            raw, state.strategy_uuid, intent, final_states[idx % len(final_states)], idx
        )
        seeded_ids.append((f"fin-{idx:04d}", mid))
    with open(state.pending.path, "w", encoding="utf-8") as fh:
        json.dump(raw, fh)

    # Trigger one normal write via PendingCommandStore to invoke _store(trim_history=True).
    extra_intent = make_intent("fin-trigger")
    host.save_intent(extra_intent)
    rec1 = _record(extra_intent, state="RESERVED")
    host.save_record("fin-trigger", rec1)
    trigger_mid = host.commit_pre_dispatch("fin-trigger", rec1)
    assert state.pending.mark(trigger_mid, "TERMINAL")
    rec2 = _record(extra_intent, state="RELEASED")
    host.save_record("fin-trigger", rec2)

    with open(state.pending.path, encoding="utf-8") as fh:
        after = json.load(fh)
    validate_pending_state(after, state.pending.path, state.strategy_uuid)

    # Bounded to HISTORY_LIMIT (500), keeping the most recent 500 finalized gateway markers.
    history_ids = [m["marker_id"] for m in after["history"]]
    expected_kept = [mid for _, mid in seeded_ids[-(HISTORY_LIMIT - 1) :]] + [trigger_mid]
    assert len(history_ids) == HISTORY_LIMIT
    assert history_ids == expected_kept

    # Evicted entries had their marker_id link cleared cleanly without becoming unresolved.
    evicted_key, _ = seeded_ids[0]
    assert after["gateway"]["intents"][evicted_key]["marker_id"] is None

    # Active gateway markers are 100% preserved.
    assert set(after["active"]) == set(active_ids)
    assert after["active"][active_ids[0]]["status"] == "PREPARED"
    assert after["active"][active_ids[1]]["status"] == "UNKNOWN"


def test_r71_133_non_finalized_and_sent_gateway_history_never_evicted(state, gateway_inputs):
    """RESERVED and SENT gateway markers stay pinned even when history_limit is small."""
    binding, _, make_intent = gateway_inputs
    host = GatewayPendingHost.upgrade_for_gateway(
        state.strategy_dir, state.strategy_uuid, binding, max_entries=100
    )
    store = PendingCommandStore(state.strategy_dir, state.strategy_uuid, history_limit=2)

    # 1. A RESERVED gateway marker marked TERMINAL (same contract as test_gateway_pending).
    reserved_intent = make_intent("pin-reserved")
    host.save_intent(reserved_intent)
    reserved_rec = _record(reserved_intent, state="RESERVED")
    host.save_record("pin-reserved", reserved_rec)
    reserved_mid = host.commit_pre_dispatch("pin-reserved", reserved_rec)
    assert store.mark(reserved_mid, "TERMINAL")

    # 2. A SENT gateway marker marked TERMINAL (must remain so _unresolved stays False).
    sent_intent = make_intent("pin-sent")
    host.save_intent(sent_intent)
    sent_res = _record(sent_intent, state="RESERVED")
    host.save_record("pin-sent", sent_res)
    sent_mid = host.commit_pre_dispatch("pin-sent", sent_res)
    sent_rec = _record(
        sent_intent,
        state="SENT",
        native=NativeOrderIdentity("CTP", "cid-pin-sent", {"order_ref": "1"}, 1),
        strong=("a" * 64,),
    )
    host.save_record("pin-sent", sent_rec)
    assert store.mark(sent_mid, "TERMINAL")

    # 3. Four finalized RELEASED gateway markers -> only the last 2 finalized should survive.
    final_mids = []
    for idx in range(4):
        key = f"rel-{idx}"
        intent = make_intent(key)
        host.save_intent(intent)
        rec_res = _record(intent, state="RESERVED")
        host.save_record(key, rec_res)
        mid = host.commit_pre_dispatch(key, rec_res)
        rec_rel = _record(intent, state="RELEASED")
        host.save_record(key, rec_rel)
        assert store.mark(mid, "TERMINAL")
        final_mids.append(mid)

    # 4. Also mix in 4 legacy non-gateway terminal markers -> bounded to 2.
    legacy_mids = []
    for idx in range(4):
        mid = store.commit(place_record(state.strategy_uuid, client_order_id=f"legacy-{idx}"))
        assert mid is not None
        assert store.mark(mid, "TERMINAL")
        legacy_mids.append(mid)

    with open(state.pending.path, encoding="utf-8") as fh:
        raw = json.load(fh)
    validate_pending_state(raw, state.pending.path, state.strategy_uuid)

    history_ids = [m["marker_id"] for m in raw["history"]]
    assert reserved_mid in history_ids
    assert sent_mid in history_ids
    assert [m for m in final_mids if m in history_ids] == final_mids[-2:]
    assert [m for m in legacy_mids if m in history_ids] == legacy_mids[-2:]

    # Because sent_mid is preserved and evicted released markers have state RELEASED,
    # no gateway intent flipped back to unresolved (rebind still succeeds once reserved is released).
    assert not has_unresolved_gateway_intents(raw)
    new_id = rebind_identity(
        state.strategy_dir, mode="new_instance", operator="test", reason="r71_133_verify"
    )
    assert new_id.strategy_uuid != state.strategy_uuid

    # Ensure rebind wasn't broken and invalid store history_limit is still refused.
    with pytest.raises(ValueError):
        PendingCommandStore(state.strategy_dir, state.strategy_uuid, history_limit=0)
    with pytest.raises(LiveStateError):
        PendingCommandStore(state.strategy_dir, "not-a-uuid")

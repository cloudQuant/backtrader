"""Count-only RegisteredSim state projection under native dispatch locks."""

from threading import Event, Thread

from backtrader.stores.registered_sim import RegisteredSimStore, RegisteredSimWrapper


def _store(*, terminal_limit=2, states=(), wrapper_type=RegisteredSimWrapper):
    api = wrapper_type(registered_sim_terminal_order_limit=terminal_limit)
    api._order_state.update(states)
    store = RegisteredSimStore(
        api=api,
        terminal_order_limit=terminal_limit,
        autostart=False,
    )
    return store, api


def test_registered_sim_capacity_reports_counts_and_distinguishes_unbounded_state():
    store, _api = _store(
        states=(
            ("order-private-a", "active"),
            ("order-private-b", "unknown"),
            ("order-private-c", "terminal"),
        )
    )

    facts = store.registered_sim_order_capacity_facts()

    assert facts["status"] == "OBSERVED"
    assert facts["active_order_count"] == 1
    assert facts["unknown_order_count"] == 1
    assert facts["terminal_order_count"] == 1
    assert facts["dispatching_order_count"] == 0
    assert facts["active_unknown_limit"] is None
    assert facts["active_unknown_bounded"] is False
    assert facts["terminal_order_limit"] == 2
    assert "order-private-a" not in repr(facts)


def test_registered_sim_capacity_reports_over_limit_and_missing_projection_as_incomplete():
    store, api = _store(states=(("terminal-a", "terminal"),))
    api._order_state["terminal-b"] = "terminal"
    api._order_state["terminal-c"] = "terminal"

    over = store.registered_sim_order_capacity_facts()
    assert over["status"] == "UNSTABLE_OR_OVER_CAPACITY"
    assert over["terminal_limit_respected"] is False

    class MissingFieldsWrapper(RegisteredSimWrapper):
        def registered_sim_order_capacity_facts(self):
            return {"schema": "backtrader.registered_sim_order_capacity.v1", "status": "OBSERVED"}

    malformed_store, _malformed_api = _store(wrapper_type=MissingFieldsWrapper)
    malformed = malformed_store.registered_sim_order_capacity_facts()
    assert malformed["status"] == "UNAVAILABLE"
    assert malformed["reason_code"] == "invalid_projection_counts"

    class DispatchingButObservedWrapper(RegisteredSimWrapper):
        def registered_sim_order_capacity_facts(self):
            facts = super().registered_sim_order_capacity_facts()
            facts["dispatching_order_count"] = 1
            return facts

    dispatching_store, _dispatching_api = _store(wrapper_type=DispatchingButObservedWrapper)
    dispatching = dispatching_store.registered_sim_order_capacity_facts()
    assert dispatching["status"] == "UNAVAILABLE"
    assert dispatching["reason_code"] == "invalid_projection_limits"


def test_registered_sim_capacity_never_constructs_an_uninitialized_api():
    store = RegisteredSimStore(autostart=False)

    facts = store.registered_sim_order_capacity_facts()

    assert facts["status"] == "UNAVAILABLE"
    assert facts["reason_code"] == "api_not_initialized"
    assert store._api is None


def test_registered_sim_capacity_during_native_dispatch_is_unavailable_then_stable():
    store, api = _store(states=(("existing-active", "active"),))
    entered = Event()
    release = Event()
    in_dispatch_facts = []

    def hold_dispatch_locks():
        with api._registered_sim_lock:
            with api._registered_sim_observation_lock:
                api._dispatching_order_ids.add("opaque-dispatch")
            entered.set()
            # The same thread may reenter the RLock. The published dispatch
            # marker must make all order-state counts unavailable.
            in_dispatch_facts.append(store.registered_sim_order_capacity_facts())
            release.wait(timeout=3)
            with api._registered_sim_observation_lock:
                api._dispatching_order_ids.clear()
            api._remember_order_state_locked("new-order", "unknown")

    worker = Thread(target=hold_dispatch_locks)
    worker.start()
    assert entered.wait(timeout=2)
    during = store.registered_sim_order_capacity_facts()
    release.set()
    worker.join(timeout=3)

    after = store.registered_sim_order_capacity_facts()

    assert not worker.is_alive()
    assert during["status"] == "UNAVAILABLE"
    assert during["reason_code"] == "state_lock_busy"
    assert "active_order_count" not in during
    assert after["status"] == "OBSERVED"
    assert after["active_order_count"] == 1
    assert after["unknown_order_count"] == 1
    assert len(in_dispatch_facts) == 1
    assert in_dispatch_facts[0]["status"] == "UNAVAILABLE"
    assert in_dispatch_facts[0]["reason_code"] == "native_dispatch_in_progress"
    assert "active_order_count" not in in_dispatch_facts[0]
    assert "unknown_order_count" not in in_dispatch_facts[0]
    assert "terminal_order_count" not in in_dispatch_facts[0]
    assert "opaque-dispatch" not in repr(during)
    assert "new-order" not in repr(after)


def test_registered_sim_synthetic_count_projection_has_no_active_unknown_cap():
    # These states are inserted directly; this verifies count-only projection,
    # not growth or retention across a real order lifecycle.
    states = tuple(
        [("active-{}".format(index), "active") for index in range(20)]
        + [("unknown-{}".format(index), "unknown") for index in range(20)]
        + [("terminal", "terminal")]
    )
    store, _api = _store(terminal_limit=1, states=states)

    facts = store.registered_sim_order_capacity_facts()

    assert facts["status"] == "OBSERVED"
    assert facts["active_order_count"] == 20
    assert facts["unknown_order_count"] == 20
    assert facts["active_unknown_limit"] is None
    assert facts["active_unknown_bounded"] is False
    assert facts["terminal_order_count"] == facts["terminal_order_limit"] == 1


def test_registered_sim_capacity_rejects_status_terminal_limit_disagreement():
    class ObservedWhileOverLimitWrapper(RegisteredSimWrapper):
        def registered_sim_order_capacity_facts(self):
            facts = super().registered_sim_order_capacity_facts()
            facts["status"] = "OBSERVED"
            return facts

    over_limit_store, _over_limit_api = _store(
        terminal_limit=2,
        states=(("terminal-a", "terminal"), ("terminal-b", "terminal"), ("terminal-c", "terminal")),
        wrapper_type=ObservedWhileOverLimitWrapper,
    )
    over_limit = over_limit_store.registered_sim_order_capacity_facts()
    assert over_limit["status"] == "UNAVAILABLE"
    assert over_limit["reason_code"] == "invalid_projection_limits"

    class OverLimitWhileWithinLimitWrapper(RegisteredSimWrapper):
        def registered_sim_order_capacity_facts(self):
            facts = super().registered_sim_order_capacity_facts()
            facts["status"] = "UNSTABLE_OR_OVER_CAPACITY"
            return facts

    within_limit_store, _within_limit_api = _store(
        terminal_limit=2,
        states=(("terminal-a", "terminal"),),
        wrapper_type=OverLimitWhileWithinLimitWrapper,
    )
    within_limit = within_limit_store.registered_sim_order_capacity_facts()
    assert within_limit["status"] == "UNAVAILABLE"
    assert within_limit["reason_code"] == "invalid_projection_limits"

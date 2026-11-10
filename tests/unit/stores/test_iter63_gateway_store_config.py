"""Explicit Gateway Store configuration and lifecycle; no network access."""
from pathlib import Path
from types import SimpleNamespace
from decimal import Decimal

import pytest
import yaml

from backtrader.live_state.gateway_pending import GatewayPendingHost
from backtrader.stores.btapistore import BtApiStore, BtApiStoreError
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_py.gateway_strategy_config import GatewayStrategyConfig
from bt_api_py.gateway_direct_client import build_gateway_order_intent
from bt_api_py._contracts.models import OrderRequest, OrderType, Side
from bt_api_py.service_runtime import ClientCurveKeys
from tests.unit.live_state.conftest import state as state, strategy_dir as strategy_dir


@pytest.fixture
def setup_gateway(state):
    path = (Path(__file__).resolve().parents[4] / "bt_api_py/examples/services"
            / "gateway-strategy-client.example.yaml")
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    binding = GatewayCommandBinding(**config["binding"])
    GatewayPendingHost.upgrade_for_gateway(state.strategy_dir, state.strategy_uuid, binding)
    GatewayPendingHost.upgrade_for_cancellation(state.strategy_dir, state.strategy_uuid, binding)
    GatewayPendingHost.upgrade_for_execution(
        state.strategy_dir, state.strategy_uuid, binding, consumer_ref="gexec:" + "a" * 64
    )
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    keys = {"security": ClientCurveKeys(b"a" * 40, b"b" * 40, b"c" * 40)}
    return config, host, keys


class FakeApi:
    def __init__(self):
        self.starts = 0
        self.closes = 0
        self.state = "new"
        self.close_complete = True

    def start(self, *, timeout_seconds):
        self.starts += 1
        self.state = "running"
        return self.status()

    def status(self):
        return SimpleNamespace(state=self.state, healthy=self.state == "running",
                               thread_alive=self.state == "running", cleanup_failures=0,
                               unregister_uncertainties=0, owner_cleanup_uncertainties=0)

    def close(self, *, timeout_seconds):
        self.closes += 1
        if self.close_complete:
            self.state = "closed"
        return self.status()


def make_store(setup_gateway):
    config, host, keys = setup_gateway
    return BtApiStore(config={"gateway_strategy": config}, gateway_host=host,
                      gateway_security_profiles=keys)


def test_configured_gateway_start_close_owns_facade_not_host(setup_gateway, monkeypatch):
    api = FakeApi()
    captured = []
    def create(_self, *, host, cancel_host, security_profiles):
        captured.append((host, cancel_host, security_profiles))
        return api
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", create)
    store = make_store(setup_gateway)
    assert store.gateway_api is None and not store.is_connected
    assert store.sdk_api is None
    store.start()
    assert store.gateway_api is api and store.gateway_host is setup_gateway[1]
    assert store.gateway_strategy_config.exchange_name == "CTP___FUTURE"
    assert store.is_connected and api.starts == 1
    store.start()
    assert api.starts == 1 and captured[0][0] is captured[0][1] is setup_gateway[1]
    store.stop()
    assert api.closes == 1 and store.gateway_api is None and not store.is_connected
    assert setup_gateway[1].list_intents() == ()
    with pytest.raises(BtApiStoreError, match="GATEWAY_STORE_CLOSED"):
        store.start()


def test_incomplete_close_keeps_same_api_for_retry(setup_gateway, monkeypatch):
    api = FakeApi()
    api.close_complete = False
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: api)
    store = make_store(setup_gateway)
    store.start()
    store.stop(timeout=1)
    assert store.gateway_api is api and store._shutdown_state == "INCOMPLETE"
    assert not store.is_connected
    with pytest.raises(BtApiStoreError, match="GATEWAY_START_REQUIRES_CLOSE"):
        store.start()
    api.close_complete = True
    store.stop(timeout=1)
    assert store.gateway_api is None and api.closes == 2


def test_no_gateway_market_or_aggregate_account_fallback(setup_gateway, monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: api)
    store = make_store(setup_gateway)
    with pytest.raises(BtApiStoreError, match="GATEWAY_MARKET_FEED_UNAVAILABLE"):
        store.start(data=object())
    assert api.starts == 0
    store.start()
    with pytest.raises(BtApiStoreError, match="GATEWAY_MARKET_FEED_UNAVAILABLE"):
        store.subscribe("IF2612")
    with pytest.raises(BtApiStoreError, match="GATEWAY_STRATEGY_BALANCE_UNAVAILABLE"):
        store.get_balance()
    with pytest.raises(BtApiStoreError, match="GATEWAY_STRATEGY_POSITIONS_UNAVAILABLE"):
        store.get_positions()
    store.stop()


def test_binding_and_mode_conflicts_fail_before_start(setup_gateway):
    config, host, keys = setup_gateway
    config["binding"]["journal_id"] = "another"
    with pytest.raises(BtApiStoreError, match="GATEWAY_HOST_BINDING_MISMATCH"):
        BtApiStore(config={"gateway_strategy": config}, gateway_host=host,
                   gateway_security_profiles=keys)
    with pytest.raises(BtApiStoreError, match="GATEWAY_CONFIGURATION_REQUIRED"):
        BtApiStore(gateway_host=host, gateway_security_profiles=keys)
    with pytest.raises(Exception, match="INVALID_GATEWAY_STRATEGY_CONFIG"):
        BtApiStore(config={"gateway_strategy": None}, gateway_host=host,
                   gateway_security_profiles=keys)


def test_zero_timeout_fences_and_retains_session_for_close_retry(setup_gateway, monkeypatch):
    api = FakeApi()
    api.close_complete = False
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: api)
    store = make_store(setup_gateway)
    store.start()
    store.stop(timeout=0)
    assert not store.is_connected and store.gateway_api is api and api.closes == 1
    api.close_complete = True
    store.stop(timeout=1)
    assert store.gateway_api is None and api.closes == 2


def test_failed_start_retains_exact_session_until_closed(setup_gateway, monkeypatch):
    class FailedApi(FakeApi):
        def start(self, *, timeout_seconds):
            self.state = "stopping"
            raise RuntimeError("synthetic_start_failure")

    api = FailedApi()
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: api)
    store = make_store(setup_gateway)
    with pytest.raises(RuntimeError, match="synthetic_start_failure"):
        store.start()
    assert store.gateway_api is api and not store.is_connected
    with pytest.raises(BtApiStoreError, match="GATEWAY_START_REQUIRES_CLOSE"):
        store.start()
    store.stop(timeout=1)
    assert api.closes == 1 and store.gateway_api is None


def test_zero_timeout_requests_facade_fence_even_when_worker_still_running(setup_gateway, monkeypatch):
    from bt_api_py.service_runtime_thread import ThreadedRuntimeError

    class TimedOutApi(FakeApi):
        def close(self, *, timeout_seconds):
            self.closes += 1
            if self.closes == 1:
                self.state = "stopping"
                raise ThreadedRuntimeError("CLOSE_TIMEOUT_WORKER_ALIVE")
            self.state = "closed"
            return self.status()

    api = TimedOutApi()
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: api)
    store = make_store(setup_gateway)
    store.start()
    store.stop(timeout=0)
    assert api.state == "stopping" and not store.is_connected
    assert store.gateway_api is api and store._shutdown_state == "INCOMPLETE"
    store.stop(timeout=1)
    assert store.gateway_api is None


@pytest.mark.parametrize("failures,timeout,outcome", [(2, 3, "PASS"), (99, 1, "RAISE"), (1, 0, "RAISE")])
def test_retryable_cleanup_failure_is_retried_within_the_stop_timeout(
        setup_gateway, monkeypatch, failures, timeout, outcome):
    # I63-E100: a market bootstrap still pending at the Gateway made the client
    # runtime report CLEANUP_FAILED; one further close lets it retry cleanup.
    from bt_api_py.service_runtime_thread import ThreadedRuntimeError

    class RetryableApi(FakeApi):
        def close(self, *, timeout_seconds):
            self.closes += 1
            if self.closes <= failures:
                self.state = "close_failed"
                raise ThreadedRuntimeError("CLEANUP_FAILED")
            self.state = "closed"
            return self.status()

    api = RetryableApi()
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: api)
    store = make_store(setup_gateway)
    store.start()
    if outcome == "PASS":
        store.stop(timeout=timeout)
        assert api.closes == failures + 1 and store.gateway_api is None
        assert store._shutdown_state == "PASS"
    else:
        with pytest.raises(ThreadedRuntimeError, match="CLEANUP_FAILED"):
            store.stop(timeout=timeout)
        assert store._shutdown_state == "INCOMPLETE" and not store.is_connected
        assert api.closes >= 1 if timeout else api.closes == 1


def test_explicit_strategy_binding_delegates_exact_config(setup_gateway, monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: api)
    store = make_store(setup_gateway)
    calls = []
    class Broker:
        def bind_gateway_execution_stream(self, strategy, **kwargs):
            calls.append((strategy, kwargs))
            return "bound"
    broker = Broker()
    strategy = SimpleNamespace(broker=broker)
    store.start(broker=broker)
    feed, sequence = object(), store.gateway_sequence
    assert store.bind_gateway_strategy(strategy, data_by_ref={"main": feed}, sequence=sequence) == "bound"
    args = calls[0][1]
    assert args["api"] is api and args["host"] is setup_gateway[1]
    assert args["sequence"] is sequence and args["data_by_ref"] == {"main": feed}
    assert args["orders_by_key"] == {}
    assert args["instrument_by_ref"]["main"].native_symbol == "IF2612"
    store.stop()


def test_store_acquires_run_lock_and_restores_ref_before_session(setup_gateway, state, monkeypatch):
    import itertools
    from backtrader.order import OrderBase
    from backtrader.live_state.atomic import LiveStateLocked

    monkeypatch.setattr(OrderBase, "refbasis", itertools.count(1))
    state.sequence.observe_ref(42)
    api = FakeApi()
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: api)
    store = make_store(setup_gateway)
    store.start()
    assert next(OrderBase.refbasis) >= 43
    with pytest.raises(LiveStateLocked):
        state.acquire_run_lock()
    store.stop()
    state.acquire_run_lock().release()


def test_borrowed_run_lock_is_rejected(setup_gateway, state):
    config, host, keys = setup_gateway
    lock = state.acquire_run_lock()
    try:
        with pytest.raises(BtApiStoreError, match="GATEWAY_BORROWED_LOCK_UNSUPPORTED"):
            BtApiStore(config={"gateway_strategy": config}, gateway_host=host,
                       gateway_security_profiles=keys, gateway_run_lock=lock)
        assert lock.held
    finally:
        lock.release()


def test_cleanup_uncertainty_keeps_owned_lock_until_confirmed(setup_gateway, state, monkeypatch):
    from backtrader.live_state.atomic import LiveStateLocked

    class UncertainApi(FakeApi):
        def status(self):
            status = super().status()
            status.unregister_uncertainties = 1 if self.closes == 1 else 0
            return status

    api = UncertainApi()
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: api)
    store = make_store(setup_gateway)
    store.start()
    store.stop()
    assert store.gateway_api is api and store._shutdown_state == "INCOMPLETE"
    with pytest.raises(LiveStateLocked):
        state.acquire_run_lock()
    store.stop()
    assert store.gateway_api is None
    state.acquire_run_lock().release()


def test_store_cannot_be_reused_after_process_change(setup_gateway, monkeypatch):
    from backtrader.service import gateway_config

    store = make_store(setup_gateway)
    original_pid = gateway_config.os.getpid()
    with monkeypatch.context() as patch:
        patch.setattr(gateway_config.os, "getpid", lambda: original_pid + 1)
        with pytest.raises(BtApiStoreError, match="GATEWAY_WRONG_PROCESS"):
            store.start()
        with pytest.raises(RuntimeError, match="GATEWAY_WRONG_PROCESS"):
            store.stop()
        assert not store.is_connected


def test_explicit_gateway_feed_registered_without_direct_subscribe(setup_gateway, monkeypatch):
    from backtrader.feeds.btapifeed import BtApiFeed

    api = FakeApi()
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: api)
    store = make_store(setup_gateway)
    feed = BtApiFeed(dataname="IF2612", store=store, backfill_start=False)
    assert feed._gateway_market_enabled_for_store(store) is True
    seen = []
    broker = SimpleNamespace(data_started=seen.append)
    store.start(data=feed, broker=broker)
    assert store._data_feeds == [feed] and seen == [feed] and api.starts == 1
    store.start(data=feed, broker=broker)
    assert seen == [feed] and api.starts == 1
    with pytest.raises(BtApiStoreError, match="GATEWAY_MARKET_FEED_UNAVAILABLE"):
        store.subscribe("IF2612")
    store.stop()


def _save_original_order(setup_gateway, state, *, lag=None, snapshot=True):
    from tests.unit.live_state.test_iter63_gateway_order_bootstrap import _snapshot

    config, host, _keys = setup_gateway
    from bt_api_py.gateway_strategy_config import parse_gateway_strategy_config
    parsed = parse_gateway_strategy_config(config)
    ref, image = _snapshot()
    seq = state.sequence.allocate(None if lag == "ref" else ref)
    if lag == "sequence":
        seq += 1
    request = OrderRequest(symbol="IF2612", side=Side.BUY, order_type=OrderType.LIMIT,
                           quantity=Decimal("1"), account_id=parsed.binding.account_scope,
                           client_order_id="client-a", price=Decimal("10"), idempotency_key="key-a")
    intent = build_gateway_order_intent(parsed.binding, parsed.route, request)
    if snapshot:
        host.save_order_intent(intent, local_seq=seq, bt_ref=ref, snapshot=image)
    else:
        host.save_intent(intent, local_seq=seq, bt_ref=ref)
    return ref, seq


@pytest.mark.parametrize("lag", ["ref", "sequence"])
def test_start_rejects_persisted_identity_ahead_of_allocator(setup_gateway, state, monkeypatch, lag):
    _save_original_order(setup_gateway, state, lag=lag)
    before = Path(state.pending.path).read_bytes()
    api = FakeApi()
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: api)
    store = make_store(setup_gateway)
    with pytest.raises(BtApiStoreError, match="GATEWAY_SEQUENCE_BEHIND_PENDING"):
        store.start()
    assert api.starts == 0 and Path(state.pending.path).read_bytes() == before
    lock = state.acquire_run_lock()
    lock.release()


def test_start_accepts_persisted_identity_within_allocator(setup_gateway, state, monkeypatch):
    _save_original_order(setup_gateway, state)
    api = FakeApi()
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: api)
    store = make_store(setup_gateway)
    store.start()
    assert api.starts == 1
    store.stop()


def test_start_rejects_intent_without_order_snapshot(setup_gateway, state, monkeypatch):
    _save_original_order(setup_gateway, state, snapshot=False)
    api = FakeApi()
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: api)
    store = make_store(setup_gateway)
    with pytest.raises(BtApiStoreError, match="GATEWAY_ORDER_STATE_INCOMPLETE"):
        store.start()
    assert api.starts == 0
    state.acquire_run_lock().release()


def test_start_rejects_old_pending_schema_without_mutating_it(tmp_path, setup_gateway):
    from backtrader.live_state import StrategyStateDir

    config, _, keys = setup_gateway
    path = tmp_path / "legacy-strategy"
    path.mkdir()
    state = StrategyStateDir.initialize(path)
    host = GatewayPendingHost.upgrade_for_gateway(
        path, state.strategy_uuid, GatewayCommandBinding(**config["binding"])
    )
    before = Path(state.pending.path).read_bytes()
    store = BtApiStore(config={"gateway_strategy": config}, gateway_host=host,
                       gateway_security_profiles=keys)
    with pytest.raises(BtApiStoreError, match="GATEWAY_ORDER_STATE_UPGRADE_REQUIRED"):
        store.start()
    assert Path(state.pending.path).read_bytes() == before
    state.acquire_run_lock().release()


def test_validation_exception_releases_owned_lock(setup_gateway, state, monkeypatch):
    host = setup_gateway[1]
    monkeypatch.setattr(host, "list_intents", lambda: (_ for _ in ()).throw(OSError("read failed")))
    store = make_store(setup_gateway)
    with pytest.raises(OSError, match="read failed"):
        store.start()
    assert store.gateway_api is None
    state.acquire_run_lock().release()


@pytest.mark.parametrize("duplicate", ["ref", "sequence"])
def test_duplicate_context_identities_are_rejected(setup_gateway, state, duplicate, monkeypatch):
    from backtrader.service.gateway_config import _check_gateway_sequence_consistency
    from backtrader.live_state import atomic, pending

    state.sequence.allocate(ref=1)
    state.sequence.allocate(ref=2)
    contexts = {
        "a": {"bt_ref": 1, "local_seq": 1},
        "b": {"bt_ref": 1 if duplicate == "ref" else 2,
              "local_seq": 1 if duplicate == "sequence" else 2},
    }
    raw = {"version": 5, "gateway": {"intents": contexts}}
    monkeypatch.setattr(atomic, "read_json", lambda _path: raw)
    monkeypatch.setattr(pending, "validate_pending_state", lambda value, _path, _uuid: value)
    class EnumeratedHost:
        def list_intents(self):
            return (SimpleNamespace(request_key="a"), SimpleNamespace(request_key="b"))
        def iter_order_snapshots(self):
            return {key: {"bt_ref": value["bt_ref"], "local_seq": value["local_seq"]}
                    for key, value in contexts.items()}

    with pytest.raises(BtApiStoreError, match="GATEWAY_ORDER_IDENTITY_DUPLICATE"):
        _check_gateway_sequence_consistency(EnumeratedHost(), state, BtApiStoreError)


def test_recovered_cancel_ref_above_high_water_is_rejected(setup_gateway, state, monkeypatch):
    from backtrader.service.gateway_config import _check_gateway_sequence_consistency
    from backtrader.live_state import atomic, pending

    state.sequence.allocate(ref=1)
    raw = {"version": 6, "gateway": {"intents": {"a": {"bt_ref": 1, "local_seq": 1}}}}
    monkeypatch.setattr(atomic, "read_json", lambda _path: raw)
    monkeypatch.setattr(pending, "validate_pending_state", lambda value, _path, _uuid: value)
    class EnumeratedHost:
        def list_intents(self):
            return (SimpleNamespace(request_key="a"),)
        def iter_order_snapshots(self):
            return {"a": {"bt_ref": 1, "local_seq": 1}}
        def local_order_notifications(self):
            return {"cancel:a": {"bt_ref": 2}}

    with pytest.raises(BtApiStoreError, match="GATEWAY_SEQUENCE_BEHIND_PENDING"):
        _check_gateway_sequence_consistency(EnumeratedHost(), state, BtApiStoreError)


def test_concurrent_sequence_change_rejects_and_releases_lock(setup_gateway, state, monkeypatch):
    host = setup_gateway[1]
    original = host.iter_order_snapshots
    def competing_allocation():
        result = original()
        state.sequence.allocate(ref=99)
        return result
    monkeypatch.setattr(host, "iter_order_snapshots", competing_allocation)
    store = make_store(setup_gateway)
    with pytest.raises(BtApiStoreError, match="GATEWAY_ORDER_STATE_CHANGED"):
        store.start()
    assert store.gateway_api is None
    state.acquire_run_lock().release()


def test_cancel_enabled_config_binds_same_durable_host_before_network(setup_gateway, monkeypatch):
    from bt_api_py.gateway_api import GatewayBtApi

    config, host, keys = setup_gateway
    for operation in ("direct.cancel", "direct.cancel_status"):
        if operation not in config["requested_operations"]:
            config["requested_operations"].append(operation)
    seen = []
    def inspect_before_start(api, *, timeout_seconds):
        seen.append((api._host, api._cancel_host, api._command._cancel_host))
        raise RuntimeError("stop-before-network")
    monkeypatch.setattr(GatewayBtApi, "start", inspect_before_start)
    store = BtApiStore(config={"gateway_strategy": config}, gateway_host=host,
                       gateway_security_profiles=keys)
    with pytest.raises(RuntimeError, match="stop-before-network"):
        store.start()
    assert seen == [(host, host, host)]
    store.stop()


def test_cancel_without_status_is_rejected_at_configuration(setup_gateway):
    config, host, keys = setup_gateway
    if "direct.cancel" not in config["requested_operations"]:
        config["requested_operations"].append("direct.cancel")
    config["requested_operations"] = [
        operation for operation in config["requested_operations"]
        if operation != "direct.cancel_status"
    ]
    with pytest.raises(ValueError, match="INVALID_GATEWAY_STRATEGY_CONFIG"):
        BtApiStore(config={"gateway_strategy": config}, gateway_host=host,
                   gateway_security_profiles=keys)


def test_gateway_contract_rules_compose_exact_instrument_and_route(setup_gateway):
    config, host, keys = setup_gateway
    rules = {"IF2612": {"exchange": "CFFEX", "quantity_unit": "lots",
                        "time_in_force": "GFD", "price_tick": 0.2}}
    store = BtApiStore(config={"gateway_strategy": config, "contracts": rules},
                       gateway_host=host, gateway_security_profiles=keys)
    row = store.contract_metadata["IF2612"]
    assert row["instrument_key"] == config["instruments_by_ref"]["main"]
    assert row["exchange_name"] == config["exchange_name"]
    assert (row["quantity_unit"], row["time_in_force"]) == ("lots", "GFD")
    assert row["gateway_rule_source"] == "local_configuration"
    rules["IF2612"]["quantity_unit"] = "native"
    assert row["quantity_unit"] == "lots"


def test_missing_gateway_contract_rules_remain_unavailable(setup_gateway):
    store = make_store(setup_gateway)
    assert store.contract_metadata == {}


@pytest.mark.parametrize("field,value", [
    ("quantity_unit", None), ("quantity_unit", []), ("quantity_unit", "unknown"),
    ("time_in_force", None), ("time_in_force", ""), ("time_in_force", "OTHER"),
])
def test_gateway_contracts_require_supported_local_rule_values(setup_gateway, field, value):
    config, host, keys = setup_gateway
    row = {"quantity_unit": "lots", "time_in_force": "GFD"}
    row[field] = value
    with pytest.raises(BtApiStoreError, match="GATEWAY_CONTRACT_RULES_REQUIRED"):
        BtApiStore(config={"gateway_strategy": config, "contracts": {"IF2612": row}},
                   gateway_host=host, gateway_security_profiles=keys)


def test_gateway_contracts_reject_duplicate_native_symbols(setup_gateway):
    import copy
    config, host, keys = setup_gateway
    config["instruments_by_ref"]["other"] = copy.deepcopy(config["instruments_by_ref"]["main"])
    with pytest.raises(BtApiStoreError, match="GATEWAY_CONTRACT_SYMBOL_AMBIGUOUS"):
        BtApiStore(config={"gateway_strategy": config}, gateway_host=host,
                   gateway_security_profiles=keys)


@pytest.mark.parametrize("mutation,error", [
    ("symbol", "GATEWAY_CONTRACT_INSTRUMENT_UNKNOWN"),
    ("venue", "GATEWAY_CONTRACT_INSTRUMENT_CONFLICT"),
    ("route", "GATEWAY_CONTRACT_ROUTE_CONFLICT"),
    ("instrument", "GATEWAY_CONTRACT_INSTRUMENT_CONFLICT"),
    ("rules", "GATEWAY_CONTRACT_RULE_CONFLICT"),
    ("identity", "GATEWAY_CONTRACT_IDENTITY_REQUIRED"),
])
def test_gateway_contract_rule_scope_and_conflicts_are_rejected(setup_gateway, mutation, error):
    import copy
    config, host, keys = setup_gateway
    rules = {"IF2612": {"exchange": "CFFEX", "quantity_unit": "lots", "time_in_force": "GFD"}}
    explicit = {"IF2612": {"instrument_key": copy.deepcopy(config["instruments_by_ref"]["main"]),
                            "exchange_name": config["exchange_name"], "quantity_unit": "lots",
                            "time_in_force": "GFD"}}
    if mutation == "symbol":
        rules["NOT-REGISTERED"] = rules.pop("IF2612")
    elif mutation == "venue":
        rules["IF2612"]["exchange"] = "OTHER"
    elif mutation == "route":
        explicit["IF2612"]["exchange_name"] = "OTHER"
    elif mutation == "instrument":
        explicit["IF2612"]["instrument_key"]["venue"] = "OTHER"
    elif mutation == "rules":
        explicit["IF2612"]["quantity_unit"] = "native"
    elif mutation == "identity":
        del explicit["IF2612"]["instrument_key"]
    with pytest.raises(BtApiStoreError, match=error):
        BtApiStore(config={"gateway_strategy": config, "contracts": rules}, gateway_host=host,
                   gateway_security_profiles=keys, contract_metadata=explicit)


def test_gateway_contract_rules_allow_identical_explicit_metadata(setup_gateway):
    import copy
    config, host, keys = setup_gateway
    rules = {"IF2612": {"exchange": "CFFEX", "quantity_unit": "lots", "time_in_force": "GFD"}}
    explicit = {"IF2612": {"instrument_key": copy.deepcopy(config["instruments_by_ref"]["main"]),
                            "exchange_name": config["exchange_name"], "quantity_unit": "lots",
                            "time_in_force": "GFD"}}
    store = BtApiStore(config={"gateway_strategy": config, "contracts": rules}, gateway_host=host,
                       gateway_security_profiles=keys, contract_metadata=explicit)
    assert store.contract_metadata["IF2612"]["instrument_key"] == explicit["IF2612"]["instrument_key"]


# ---------------------------------------------------------------------------
# D63-03: a lost SDK session is replaced inside the same process
# ---------------------------------------------------------------------------
class ReconnectApi(FakeApi):
    """A session whose start and close outcomes the test controls."""

    def __init__(self, *, start_ok=True, start_raises=False):
        super().__init__()
        self.start_ok, self.start_raises = start_ok, start_raises
        self.cleanup_failures = self.owner_cleanup_uncertainties = self.unregister_uncertainties = 0

    def start(self, *, timeout_seconds):
        self.starts += 1
        if self.start_raises:
            self.state = "failed"
            raise RuntimeError("REGISTRATION_REFUSED")
        self.state = "running" if self.start_ok else "starting"
        return self.status()

    def status(self):
        return SimpleNamespace(state=self.state, healthy=self.state == "running",
                               thread_alive=self.state in ("running", "starting", "stopping"),
                               cleanup_failures=self.cleanup_failures,
                               unregister_uncertainties=self.unregister_uncertainties,
                               owner_cleanup_uncertainties=self.owner_cleanup_uncertainties)

    def close(self, *, timeout_seconds):
        # As the SDK runtime: a failed runtime stays "failed" after its own
        # cleanup; an unfinished close leaves the worker thread alive.
        self.closes += 1
        if not self.close_complete:
            self.state = "stopping"
        elif self.state != "failed":
            self.state = "closed"
        return self.status()


def _reconnect_store(setup_gateway, monkeypatch, sessions):
    created = []

    def create(_self, *, host, cancel_host, security_profiles):
        api = sessions.pop(0)
        created.append((api, host, cancel_host, security_profiles))
        return api

    monkeypatch.setattr(GatewayStrategyConfig, "create_api", create)
    monkeypatch.setattr("backtrader.service.gateway_config._RECONNECT_BACKOFF", (0.0,))
    store = make_store(setup_gateway)
    store.start()
    return store, created


def test_lost_session_is_closed_and_a_new_one_registered_in_the_same_store(setup_gateway, monkeypatch):
    first, second = ReconnectApi(), ReconnectApi()
    store, created = _reconnect_store(setup_gateway, monkeypatch, [first, second])
    lock = store._gateway_run_lock
    assert store.gateway_session_recoverable() and store.gateway_session_generation == 0
    assert store.gateway_reconnect() is True and first.closes == 0  # nothing to do while healthy
    first.state = "running"
    first.status = lambda: SimpleNamespace(state="running", healthy=False, thread_alive=True)
    assert store.gateway_session_state() == "UNAVAILABLE"
    assert store.gateway_reconnect() is False and first.closes == 0  # may still come back by itself
    del first.status
    first.state = "failed"  # the lease ran out or the Gateway has a new service epoch
    # What the old Gateway side could not be told does not hold the strategy back.
    first.unregister_uncertainties = first.cleanup_failures = first.owner_cleanup_uncertainties = 1
    assert store.gateway_session_state() == "LOST" and not store.is_connected
    assert store.gateway_reconnect() is True
    assert first.closes == 1 and second.starts == 1
    assert store.gateway_api is second and store.is_connected
    assert store.gateway_session_state() == "CONNECTED" and store.gateway_session_generation == 1
    # Same host, same keys, same run lock: only the connection was replaced.
    assert created[1][1] is created[1][2] is setup_gateway[1] and created[1][3] == created[0][3]
    assert store._gateway_run_lock is lock and lock.held
    store.stop()
    assert second.closes == 1 and store.gateway_api is None


def test_reconnect_waits_until_the_gateway_accepts_a_registration(setup_gateway, monkeypatch):
    first = ReconnectApi()
    refused, pending, accepted = (ReconnectApi(start_raises=True), ReconnectApi(start_ok=False),
                                  ReconnectApi())
    store, _ = _reconnect_store(setup_gateway, monkeypatch, [first, refused, pending, accepted])
    first.state = "failed"
    assert store.gateway_reconnect() is False
    assert store._gateway_reconnect_reason == "REGISTRATION_FAILED:RuntimeError"
    # The refused session is kept so that it is closed before another is made.
    assert store.gateway_api is refused and store.gateway_session_state() == "LOST"
    assert store.gateway_session_recoverable()
    assert store.gateway_reconnect() is False
    assert refused.closes == 1 and store.gateway_api is pending and pending.starts == 1
    # Still starting: its thread is alive, so no second runtime is created beside it.
    assert store.gateway_session_state() == "UNAVAILABLE"
    assert store.gateway_reconnect() is False and pending.closes == 0
    pending.state = "failed"
    assert store.gateway_reconnect() is True
    assert pending.closes == 1 and store.gateway_api is accepted
    assert store.gateway_session_generation == 1 and store._gateway_reconnect_reason is None


@pytest.mark.parametrize("held", ["thread", "timeout", "cleanup_failed"])
def test_no_second_runtime_while_the_lost_one_is_not_closed(setup_gateway, monkeypatch, held):
    first, second = ReconnectApi(), ReconnectApi()
    store, created = _reconnect_store(setup_gateway, monkeypatch, [first, second])
    first.state = "failed"
    if held == "thread":
        first.close_complete = False  # its worker thread is still alive after close
    else:
        def broken(*, timeout_seconds):
            # The SDK raises while a transport or owner resource is still open.
            error = RuntimeError("close incomplete")
            error.code = "CLOSE_TIMEOUT_WORKER_ALIVE" if held == "timeout" else "CLEANUP_FAILED"
            raise error
        first.close = broken
    assert store.gateway_reconnect(timeout=0.3) is False
    assert store.gateway_api is first and len(created) == 1 and second.starts == 0
    assert store._gateway_reconnect_reason == {
        "thread": "OLD_SESSION_STILL_RUNNING", "timeout": "OLD_SESSION_CLOSE_FAILED:CLOSE_TIMEOUT_WORKER_ALIVE",
        "cleanup_failed": "OLD_SESSION_CLOSE_FAILED:CLEANUP_FAILED"}[held]
    # Once the old runtime has closed, the next attempt proceeds.
    first.close_complete = True
    first.__dict__.pop("close", None)
    first.state = "failed"
    assert store.gateway_reconnect() is True and store.gateway_api is second


def test_reconnect_attempts_are_spaced_by_a_backoff(setup_gateway, monkeypatch):
    import backtrader.service.gateway_config as module

    first = ReconnectApi()
    store, created = _reconnect_store(
        setup_gateway, monkeypatch, [first] + [ReconnectApi(start_raises=True) for _ in range(4)])
    monkeypatch.setattr(module, "_RECONNECT_BACKOFF", (0.0, 60.0))
    clock = [1000.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    first.state = "failed"
    assert store.gateway_reconnect() is False and len(created) == 2
    assert store.gateway_reconnect() is False and len(created) == 3  # first retry is immediate
    assert store.gateway_reconnect() is False and len(created) == 3  # then spaced
    clock[0] += 59.0
    assert store.gateway_reconnect() is False and len(created) == 3
    clock[0] += 2.0
    assert store.gateway_reconnect() is False and len(created) == 4


def test_stopped_store_never_registers_again(setup_gateway, monkeypatch):
    first, second = ReconnectApi(), ReconnectApi()
    store, created = _reconnect_store(setup_gateway, monkeypatch, [first, second])
    first.state = "failed"
    first.close_complete = False
    store.stop(timeout=1)  # stopped; the lost session's close is still unconfirmed
    assert store.gateway_api is first and store._shutdown_state == "INCOMPLETE"
    assert not store.gateway_session_recoverable()
    first.close_complete = True
    assert store.gateway_reconnect() is False and len(created) == 1 and second.starts == 0
    assert first.closes == 1  # the reconnect path did not even touch the retained session
    store.stop(timeout=1)
    assert store.gateway_api is None
    plain = BtApiStore.__new__(BtApiStore)
    plain._gateway_mode = False
    for method in (plain.gateway_reconnect, plain.gateway_session_recoverable):
        with pytest.raises(RuntimeError, match="GATEWAY_MODE_REQUIRED"):
            method()

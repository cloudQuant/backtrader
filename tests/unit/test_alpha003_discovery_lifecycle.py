"""Guarded lifecycle tests for the narrow 028 discovery Store close helper."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest

from backtrader.stores.registered_sim import RegisteredSimStore, RegisteredSimWrapper


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "unified" / "028_alpha003_simnow_minute"
LIFECYCLE_PATH = EXAMPLE / "discovery_lifecycle.py"


def _load_lifecycle():
    example_path = str(EXAMPLE)
    if example_path not in sys.path:
        sys.path.insert(0, example_path)
    spec = importlib.util.spec_from_file_location(
        "alpha003_simnow_discovery_lifecycle_under_test", LIFECYCLE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


LIFECYCLE = _load_lifecycle()


@pytest.fixture(autouse=True)
def _unit_only_canonical_receipt_module_seam(monkeypatch):
    """Use unit fakes; the runtime helper still requires canonical module identity."""
    module = ModuleType("bt_api_ctp.ctp.client")
    module.CtpNativeStopReceipt = CtpNativeStopReceipt
    module.CtpNativeStartupStopReceipt = CtpNativeStartupStopReceipt
    monkeypatch.setitem(sys.modules, "bt_api_ctp.ctp.client", module)


class CtpNativeStopReceipt:
    __module__ = "bt_api_ctp.ctp.client"

    def __init__(
        self,
        *,
        generation=1,
        native_released=True,
        join_required=False,
        join_completed=True,
        thread_alive=False,
        timed_out=False,
    ):
        self.connection_generation = generation
        self.native_released = native_released
        self.join_required = join_required
        self.join_completed = join_completed
        self.thread_alive = thread_alive
        self.timed_out = timed_out

    @property
    def complete(self):
        return (
            self.native_released is True
            and (self.join_required is False or self.join_completed is True)
            and self.thread_alive is False
            and self.timed_out is False
        )


class CtpNativeStartupStopReceipt:
    __module__ = "bt_api_ctp.ctp.client"

    def __init__(self, outcome="preflight_no_owner"):
        self.api_attempt_id = None
        self.outcome = outcome
        self.connection_generation = 0
        self.native_released = None
        self.join_required = False
        self.join_completed = outcome == "preflight_no_owner"
        self.thread_alive = False if outcome == "preflight_no_owner" else None
        self.timed_out = False
        self._client_binding = object()

    @property
    def complete(self):
        return (
            type(self.connection_generation) is int
            and self.connection_generation == 0
            and self.api_attempt_id is None
            and self.outcome == "preflight_no_owner"
            and self.native_released is None
            and self.join_required is False
            and self.join_completed is True
            and self.thread_alive is False
            and self.timed_out is False
            and type(self._client_binding) is object
        )


class _Client:
    def __init__(self, *, secret="SYNTHETIC_SECRET_SENTINEL", startup_outcome=None):
        self._secret = secret
        self._stopped = False
        self.stop_calls = 0
        self.stop_and_wait_calls = 0
        self.stop_startup_and_wait_calls = 0
        self.receipt_generation = 1
        self.startup_outcome = startup_outcome
        self.receipt_complete = True

    def stop(self):
        self.stop_calls += 1
        self._stopped = True

    def stop_and_wait(self, *, timeout):
        self.stop_and_wait_calls += 1
        if not self._stopped:
            self.stop()
        generation = self.receipt_generation
        return CtpNativeStopReceipt(
            generation=generation,
            native_released=self.receipt_complete,
            join_required=False,
            join_completed=True,
            thread_alive=False if self.receipt_complete else True,
            timed_out=False,
        )

    def stop_startup_and_wait(self, *, timeout):
        self.stop_startup_and_wait_calls += 1
        if self.startup_outcome is not None:
            return CtpNativeStartupStopReceipt(self.startup_outcome)
        return self.stop_and_wait(timeout=timeout)


class _WrapperBase:
    def __init__(self, *, md_client=None, trader_client=None, connected=False):
        self.md_client = md_client
        self.trader_client = trader_client
        self._connected = connected
        self.disconnect_calls = 0
        self.raise_after_md_stop = False


class _DiscoveryWrapper(RegisteredSimWrapper, _WrapperBase):
    def __init__(self, *, md_client=None, trader_client=None, connected=False):
        super().__init__(
            md_client=md_client,
            trader_client=trader_client,
            connected=connected,
        )

    def disconnect(self):
        self.disconnect_calls += 1
        if self.md_client is not None:
            self.md_client.stop()
        if self.raise_after_md_stop:
            raise RuntimeError("SYNTHETIC_SECRET_SENTINEL")
        if self.trader_client is not None:
            self.trader_client.stop()
        self._connected = False


def _store(wrapper):
    return RegisteredSimStore(api=wrapper)


def _connected_pair():
    md = _Client()
    trader = _Client()
    wrapper = _DiscoveryWrapper(md_client=md, trader_client=trader, connected=True)
    store = _store(wrapper)
    store._connected = True
    return store, wrapper, md, trader


def _startup_pair(*, outcome="preflight_no_owner"):
    md = _Client()
    md.receipt_generation = 1
    trader = _Client(startup_outcome=outcome)
    wrapper = _DiscoveryWrapper(md_client=md, trader_client=trader)
    return _store(wrapper), wrapper, md, trader


def test_connected_store_uses_one_store_stop_then_typed_receipts_and_repeat_guard(
    monkeypatch,
):
    monkeypatch.delenv("BT_STORE_PROVIDER", raising=False)
    store, wrapper, md, trader = _connected_pair()

    result = LIFECYCLE.close_discovery_store(store, timeout=0.25)

    assert result.status == "CLOSED"
    assert result.complete is True
    assert result.store_stop_attempted is True
    assert result.store_stop_returned is True
    assert result.store_workers_quiescent is True
    assert result.md_client.complete is True
    assert result.trader_client.complete is True
    assert wrapper.disconnect_calls == 1
    assert md.stop_calls == 1
    assert trader.stop_calls == 1
    assert md.stop_and_wait_calls == trader.stop_and_wait_calls == 1
    assert md.stop_startup_and_wait_calls == trader.stop_startup_and_wait_calls == 0
    assert "SYNTHETIC_SECRET_SENTINEL" not in repr(result)

    with pytest.raises(LIFECYCLE.DiscoveryStoreCloseError) as repeated:
        LIFECYCLE.close_discovery_store(store, timeout=0.25)
    assert repeated.value.result.status == "ALREADY_ATTEMPTED"
    assert repeated.value.result.complete is False
    assert repeated.value.result.already_attempted is True
    assert repeated.value.custody.store is store
    assert wrapper.disconnect_calls == 1
    assert md.stop_calls == trader.stop_calls == 1
    assert md.stop_and_wait_calls == trader.stop_and_wait_calls == 1


def test_partial_disconnect_retains_exact_refs_and_never_repeats_store_stop(
    monkeypatch,
):
    monkeypatch.delenv("BT_STORE_PROVIDER", raising=False)
    store, wrapper, md, trader = _connected_pair()
    wrapper.raise_after_md_stop = True

    with pytest.raises(LIFECYCLE.DiscoveryStoreCloseError) as first:
        LIFECYCLE.close_discovery_store(store, timeout=0.25)

    error = first.value
    assert error.result.complete is False
    assert error.result.reason_code == "store_stop_raised"
    assert error.custody.store is store
    assert error.custody.wrapper is wrapper
    assert error.custody.md_client is md
    assert error.custody.trader_client is trader
    assert error.__context__ is None
    assert error.__cause__ is None
    assert wrapper.disconnect_calls == 1
    assert md.stop_calls == 1
    assert trader.stop_calls == 1
    assert md.stop_and_wait_calls == trader.stop_and_wait_calls == 1
    assert "SYNTHETIC_SECRET_SENTINEL" not in str(error)
    assert "SYNTHETIC_SECRET_SENTINEL" not in repr(error.custody)

    with pytest.raises(LIFECYCLE.DiscoveryStoreCloseError) as repeated:
        LIFECYCLE.close_discovery_store(store, timeout=0.25)
    assert repeated.value.result.already_attempted is True
    assert repeated.value.result.reason_code == "close_already_attempted"
    assert repeated.value.custody.store is store
    assert wrapper.disconnect_calls == 1
    assert md.stop_calls == trader.stop_calls == 1
    assert md.stop_and_wait_calls == trader.stop_and_wait_calls == 1


def test_startup_failure_uses_typed_client_stops_without_store_early_return(
    monkeypatch,
):
    monkeypatch.delenv("BT_STORE_PROVIDER", raising=False)
    store, wrapper, md, trader = _startup_pair()

    result = LIFECYCLE.close_discovery_store(store, timeout=0.25)

    assert result.status == "CLOSED"
    assert result.complete is True
    assert result.store_stop_attempted is False
    assert result.store_stop_returned is None
    assert result.shutdown_state == "NOT_STARTED"
    assert result.md_client.receipt_present is True
    assert result.trader_client.receipt_present is True
    assert result.trader_client.startup_outcome == "preflight_no_owner"
    assert wrapper.disconnect_calls == 0
    assert md.stop_and_wait_calls == 1
    assert trader.stop_and_wait_calls == 0
    assert trader.stop_startup_and_wait_calls == 1


def test_zero_generation_md_receipt_does_not_prove_startup_disposition(
    monkeypatch,
):
    monkeypatch.delenv("BT_STORE_PROVIDER", raising=False)
    store, wrapper, md, trader = _startup_pair()
    # A complete-looking generation-zero receipt cannot distinguish an API
    # created before MD publication from a true no-owner startup.
    md.receipt_generation = 0

    with pytest.raises(LIFECYCLE.DiscoveryStoreCloseError) as caught:
        LIFECYCLE.close_discovery_store(store, timeout=0.25)

    result = caught.value.result
    assert result.status == "INCOMPLETE"
    assert result.reason_code == "md_startup_disposition_unproven"
    assert result.complete is False
    assert result.store_stop_attempted is False
    assert result.md_client.receipt_present is True
    assert result.md_client.complete is True
    assert result.md_client.connection_generation == 0
    assert result.trader_client.complete is True
    assert result.trader_client.startup_outcome == "preflight_no_owner"
    assert caught.value.custody.store is store
    assert caught.value.custody.wrapper is wrapper
    assert caught.value.custody.md_client is md
    assert caught.value.custody.trader_client is trader
    assert wrapper.disconnect_calls == 0
    assert md.stop_and_wait_calls == 1
    assert trader.stop_startup_and_wait_calls == 1


def test_incomplete_startup_receipt_is_retained_and_not_retried(monkeypatch):
    monkeypatch.delenv("BT_STORE_PROVIDER", raising=False)
    store, wrapper, md, trader = _startup_pair(outcome="factory_uncertain")

    with pytest.raises(LIFECYCLE.DiscoveryStoreCloseError) as first:
        LIFECYCLE.close_discovery_store(store, timeout=0.25)

    assert first.value.result.complete is False
    assert first.value.result.trader_client.complete is False
    assert first.value.result.trader_client.startup_outcome == "factory_uncertain"
    assert first.value.custody.store is store
    assert first.value.custody.wrapper is wrapper
    assert first.value.custody.md_client is md
    assert first.value.custody.trader_client is trader

    with pytest.raises(LIFECYCLE.DiscoveryStoreCloseError) as repeated:
        LIFECYCLE.close_discovery_store(store, timeout=0.25)
    assert repeated.value.result.already_attempted is True
    assert trader.stop_startup_and_wait_calls == 1
    assert md.stop_and_wait_calls == 1


class _LiveWorker:
    def __init__(self):
        self.join_calls = 0

    def is_alive(self):
        return True

    def join(self, timeout=None):
        self.join_calls += 1


def test_nonquiescent_store_worker_blocks_client_cleanup(monkeypatch):
    monkeypatch.delenv("BT_STORE_PROVIDER", raising=False)
    store, wrapper, md, trader = _connected_pair()
    worker = _LiveWorker()
    store._command_worker_thread = worker

    with pytest.raises(LIFECYCLE.DiscoveryStoreCloseError) as caught:
        LIFECYCLE.close_discovery_store(store, timeout=0)

    assert caught.value.result.reason_code == "store_workers_not_quiescent"
    assert caught.value.result.store_workers_quiescent is False
    assert caught.value.result.worker_alive is True
    assert worker.join_calls == 1
    assert wrapper.disconnect_calls == 0
    assert md.stop_calls == trader.stop_calls == 0
    assert md.stop_and_wait_calls == trader.stop_and_wait_calls == 0
    assert caught.value.custody.store is store
    assert caught.value.custody.wrapper is wrapper


def test_missing_clients_do_not_create_or_claim_typed_receipts(monkeypatch):
    monkeypatch.delenv("BT_STORE_PROVIDER", raising=False)
    wrapper = _DiscoveryWrapper()
    store = _store(wrapper)

    with pytest.raises(LIFECYCLE.DiscoveryStoreCloseError) as caught:
        LIFECYCLE.close_discovery_store(store, timeout=0.25)

    result = caught.value.result
    assert result.reason_code == "client_reference_missing"
    assert result.complete is False
    assert result.store_stop_attempted is False
    assert result.md_client.present is False
    assert result.md_client.receipt_present is False
    assert result.md_client.complete is None
    assert result.trader_client.present is False
    assert result.trader_client.receipt_present is False
    assert result.trader_client.complete is None
    assert wrapper.disconnect_calls == 0
    assert caught.value.custody.store is store
    assert caught.value.custody.wrapper is wrapper


def test_receipt_type_name_without_canonical_module_identity_is_rejected(
    monkeypatch,
):
    monkeypatch.delenv("BT_STORE_PROVIDER", raising=False)
    store, wrapper, md, trader = _connected_pair()

    class CtpNativeStopReceipt:
        __module__ = "bt_api_ctp.ctp.client"

        connection_generation = 1
        native_released = True
        join_required = False
        join_completed = True
        thread_alive = False
        timed_out = False
        complete = True

    def impostor_stop_and_wait(*, timeout):
        md.stop_and_wait_calls += 1
        return CtpNativeStopReceipt()

    md.stop_and_wait = impostor_stop_and_wait

    with pytest.raises(LIFECYCLE.DiscoveryStoreCloseError) as caught:
        LIFECYCLE.close_discovery_store(store, timeout=0.25)

    assert caught.value.result.reason_code == "typed_stop_receipt_invalid"
    assert caught.value.result.md_client.receipt_present is False
    assert md.stop_and_wait_calls == 1
    assert trader.stop_and_wait_calls == 1
    assert wrapper.disconnect_calls == 1


def test_unregistered_wrapper_is_rejected_before_any_stop(monkeypatch):
    monkeypatch.delenv("BT_STORE_PROVIDER", raising=False)
    client = _Client()

    class _PlainWrapper:
        _connected = False
        md_client = client
        trader_client = client

    store = RegisteredSimStore(api=None)
    store._api = _PlainWrapper()

    with pytest.raises(LIFECYCLE.DiscoveryStoreCloseError) as caught:
        LIFECYCLE.close_discovery_store(store, timeout=0.25)

    assert caught.value.result.reason_code == "registered_wrapper_unavailable"
    assert client.stop_calls == 0
    assert client.stop_and_wait_calls == 0


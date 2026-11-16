"""Gateway Execution journal ownership; all facades are local test doubles."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from backtrader.live_state.atomic import read_json
from backtrader.service import gateway_config
from bt_api_py.gateway_strategy_config import GatewayStrategyConfig
from tests.unit.stores.test_iter63_gateway_store_config import (
    FakeApi, ReconnectApi, make_store, setup_gateway, state, strategy_dir,
)


@pytest.fixture
def selected(monkeypatch):
    monkeypatch.setattr(GatewayStrategyConfig, "execution_selection", property(lambda _: object()))


def test_selected_opens_under_lock_upgrades_and_reconnect_reuses_db(setup_gateway, selected, monkeypatch):
    store = make_store(setup_gateway)
    sessions = [ReconnectApi(), ReconnectApi()]
    observed = []
    def create(_self, *, host, cancel_host, security_profiles, execution_db):
        assert store._gateway_run_lock.held
        observed.append((host, execution_db))
        return sessions.pop(0)
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", create)
    monkeypatch.setattr(gateway_config, "_RECONNECT_BACKOFF", (0.0,))
    store.start()
    path = Path(store._gateway_state.paths.state_dir) / gateway_config._EXECUTION_DB_FILENAME
    assert path.is_file()
    assert read_json(store._gateway_state.pending.path)["version"] == 8
    store.start()
    original = observed[0][1]
    store._api.state = "failed"
    assert store.gateway_reconnect()
    assert len(observed) == 2 and observed[1] == (setup_gateway[1], original)
    store.stop()
    assert store._gateway_execution_db is None
    store._gateway_state.acquire_run_lock().release()
    reopened = make_store(setup_gateway)
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: FakeApi())
    reopened.start()
    assert read_json(reopened._gateway_state.pending.path)["version"] == 8
    reopened.stop()


def test_unselected_does_not_create_db_and_cannot_reopen_v8(setup_gateway, selected, monkeypatch):
    store = make_store(setup_gateway)
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: FakeApi())
    store.start()
    store.stop()
    monkeypatch.setattr(GatewayStrategyConfig, "execution_selection", property(lambda _: None))
    store = make_store(setup_gateway)
    with pytest.raises(Exception, match="GATEWAY_EXECUTION_SELECTION_REQUIRED"):
        store.start()
    store._gateway_state.acquire_run_lock().release()


def test_unselected_does_not_open_execution_db(setup_gateway, monkeypatch):
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: FakeApi())
    store = make_store(setup_gateway)
    store.start()
    assert not (Path(store._gateway_state.paths.state_dir) / gateway_config._EXECUTION_DB_FILENAME).exists()
    store.stop()


def test_unconfirmed_facade_close_and_db_close_failure_keep_lock(setup_gateway, selected, monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: api)
    store = make_store(setup_gateway)
    store.start()
    lock, db = store._gateway_run_lock, store._gateway_execution_db
    api.close_complete = False
    store.stop(timeout=0)
    assert store._gateway_execution_db is db and lock.held and store._shutdown_state == "INCOMPLETE"
    api.close_complete = True
    original_close = gateway_config._close_gateway_execution_db
    def failed_close(_store):
        assert lock.held
        raise OSError("db close failed")
    monkeypatch.setattr(gateway_config, "_close_gateway_execution_db", failed_close)
    with pytest.raises(OSError, match="db close failed"):
        store.stop()
    assert store._gateway_execution_db is db and lock.held
    monkeypatch.setattr(gateway_config, "_close_gateway_execution_db", original_close)
    store.stop()
    assert store._gateway_execution_db is None and not lock.held


def test_selected_rejects_symlink_db(setup_gateway, selected, monkeypatch, tmp_path):
    target = tmp_path / "target"
    target.write_bytes(b"")
    store = make_store(setup_gateway)
    path = Path(store._gateway_state.paths.state_dir) / gateway_config._EXECUTION_DB_FILENAME
    path.symlink_to(target)
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: pytest.fail("created"))
    with pytest.raises(OSError):
        store.start()
    store.stop()
    store._gateway_state.acquire_run_lock().release()


def test_selected_rejects_shared_writable_state_dir(setup_gateway, selected, monkeypatch):
    store = make_store(setup_gateway)
    directory = Path(store._gateway_state.paths.state_dir)
    original_mode = directory.stat().st_mode & 0o777
    directory.chmod(original_mode | 0o020)
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: pytest.fail("created"))
    try:
        with pytest.raises(ValueError, match="GATEWAY_EXECUTION_STATE_PATH_INVALID"):
            store.start()
        assert not (directory / gateway_config._EXECUTION_DB_FILENAME).exists()
        store.stop()
    finally:
        directory.chmod(original_mode)


def test_selected_rejects_hardlinked_db(setup_gateway, selected, monkeypatch, tmp_path):
    import os

    target = tmp_path / "target"
    target.write_bytes(b"")
    store = make_store(setup_gateway)
    path = Path(store._gateway_state.paths.state_dir) / gateway_config._EXECUTION_DB_FILENAME
    os.link(target, path)
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: pytest.fail("created"))
    with pytest.raises(ValueError, match="GATEWAY_EXECUTION_STATE_PATH_INVALID"):
        store.start()
    store.stop()


def test_wrong_thread_db_close_retains_connection_and_lock(setup_gateway, selected, monkeypatch):
    import threading

    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: FakeApi())
    store = make_store(setup_gateway)
    store.start()
    lock, db = store._gateway_run_lock, store._gateway_execution_db
    errors = []
    def stop_on_other_thread():
        try:
            store.stop()
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=stop_on_other_thread)
    thread.start()
    thread.join()
    assert len(errors) == 1 and store._shutdown_state == "INCOMPLETE"
    assert store._gateway_execution_db is db and lock.held
    store.stop()
    assert store._gateway_execution_db is None and not lock.held


def test_failed_composition_retries_exact_cleanup_before_unlock(setup_gateway, selected, monkeypatch):
    class Owner:
        cleanup_confirmed = False
        calls = 0
        def close(self, *, timeout_seconds):
            self.calls += 1

    owner = Owner()
    def create(*_args, **_kwargs):
        error = RuntimeError("composition failed")
        error.cleanup_owner = owner
        raise error
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", create)
    store = make_store(setup_gateway)
    with pytest.raises(RuntimeError, match="composition failed"):
        store.start()
    lock, db = store._gateway_run_lock, store._gateway_execution_db
    store.stop()
    assert owner.calls == 1 and lock.held and store._gateway_execution_db is db
    owner.cleanup_confirmed = True
    store.stop()
    assert owner.calls == 1 and not lock.held and store._gateway_execution_db is None


@pytest.mark.parametrize("confirmed_initially", [True, False])
def test_reconnect_retries_failed_composition_cleanup(setup_gateway, selected, monkeypatch, confirmed_initially):
    class Owner:
        cleanup_confirmed = confirmed_initially
        calls = 0
        def close(self, *, timeout_seconds):
            self.calls += 1

    owner = Owner()
    first, replacement = ReconnectApi(), ReconnectApi()
    calls = []
    def create(*_args, **kwargs):
        calls.append(kwargs["execution_db"])
        if len(calls) == 1:
            return first
        if len(calls) == 2:
            error = RuntimeError("composition failed")
            error.cleanup_owner = owner
            raise error
        return replacement
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", create)
    monkeypatch.setattr(gateway_config, "_RECONNECT_BACKOFF", (0.0,))
    store = make_store(setup_gateway)
    store.start()
    lock, db = store._gateway_run_lock, store._gateway_execution_db
    first.state = "failed"
    assert not store.gateway_reconnect()
    assert store.gateway_session_recoverable() and store._api is first
    assert lock.held and store._gateway_execution_db is db
    if not confirmed_initially:
        assert not store.gateway_reconnect()
        assert owner.calls == 1 and len(calls) == 2 and lock.held
        owner.cleanup_confirmed = True
    assert store.gateway_reconnect()
    assert calls == [db, db, db] and store._api is replacement and lock.held
    store.stop()


@pytest.mark.parametrize("drift", ["owner", "nonliteral", "api", "db", "lock"])
def test_reconnect_cleanup_rejects_missing_owner_or_binding_drift(setup_gateway, selected, monkeypatch, drift):
    first = ReconnectApi()
    owner = SimpleNamespace(cleanup_confirmed=True)
    calls = []
    def create(*_args, **kwargs):
        calls.append(kwargs["execution_db"])
        if len(calls) == 1:
            return first
        error = RuntimeError("composition failed")
        error.cleanup_owner = owner
        raise error
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", create)
    monkeypatch.setattr(gateway_config, "_RECONNECT_BACKOFF", (0.0,))
    store = make_store(setup_gateway)
    store.start()
    first.state = "failed"
    assert not store.gateway_reconnect()
    lock, db = store._gateway_run_lock, store._gateway_execution_db
    fields = {"owner": "_gateway_composition_cleanup_owner", "nonliteral": "_gateway_composition_cleanup_owner", "api": "_api",
              "db": "_gateway_execution_db", "lock": "_gateway_run_lock"}
    field = fields[drift]
    original = getattr(store, field)
    replacement = {"api": ReconnectApi(), "owner": SimpleNamespace(cleanup_confirmed=True),
                   "nonliteral": SimpleNamespace(cleanup_confirmed=1)}
    setattr(store, field, replacement.get(drift))
    try:
        assert not store.gateway_reconnect()
        store.stop()
        assert lock.held and len(calls) == 2
    finally:
        setattr(store, field, original)
    store.stop()


def test_v8_checks_saved_route_identity_and_notification_high_water(state, monkeypatch):
    from backtrader.live_state import atomic, pending
    from backtrader.stores.btapistore import BtApiStoreError

    state.sequence.allocate(ref=1)
    route = dict(configuration_id="cfg", account="acct", strategy="strat", execution_domain_ref="domain")
    raw = {"version": 8, "gateway": {"execution_routes": {"a": route},
                                       "intents": {"a": {"bt_ref": 1, "local_seq": 1}}}}
    monkeypatch.setattr(atomic, "read_json", lambda _path: raw)
    monkeypatch.setattr(pending, "validate_pending_state", lambda value, _path, _uuid: value)
    host = SimpleNamespace(list_intents=lambda: (SimpleNamespace(request_key="a"),),
                           iter_order_snapshots=lambda: {"a": {"bt_ref": 1, "local_seq": 1}},
                           local_order_notifications=lambda: {"cancel:a": {"bt_ref": 2}})
    config = SimpleNamespace(routing=SimpleNamespace(configuration_id="other", account_ref="acct",
                             strategy_ref="strat", execution_domain_ref="domain"))
    with pytest.raises(BtApiStoreError, match="GATEWAY_EXECUTION_CONFIGURATION_MISMATCH"):
        gateway_config._check_gateway_sequence_consistency(host, state, BtApiStoreError,
                                                          execution_selection=config)
    config.routing.configuration_id = "cfg"
    with pytest.raises(BtApiStoreError, match="GATEWAY_SEQUENCE_BEHIND_PENDING"):
        gateway_config._check_gateway_sequence_consistency(host, state, BtApiStoreError,
                                                          execution_selection=config)


def _parent_route():
    intent = SimpleNamespace(request_key="req")
    route = SimpleNamespace(kind="EXECUTION_PARENT", account="acct", strategy="strat", request_key="req",
                            intent_digest="a" * 64, request_id="request", request_sha256="b" * 64,
                            configuration_id="cfg", execution_domain_ref="domain", parent_ref="parent")
    return [(intent, route)]


def test_parent_route_missing_db_never_creates_empty_db(setup_gateway, selected, monkeypatch):
    store = make_store(setup_gateway)
    path = Path(store._gateway_state.paths.state_dir) / gateway_config._EXECUTION_DB_FILENAME
    monkeypatch.setattr(gateway_config, "_gateway_execution_parent_routes", lambda _: _parent_route())
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: pytest.fail("created"))
    with pytest.raises(FileNotFoundError):
        store.start()
    assert not path.exists() and store._gateway_run_lock.held
    store.stop()


def test_parent_journal_mismatch_fences_facade_before_start(setup_gateway, selected, monkeypatch):
    first = make_store(setup_gateway)
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: FakeApi())
    first.start()
    first.stop()
    store = make_store(setup_gateway)
    api = FakeApi()
    api.verify_execution_parent_route = lambda _intent, _prepared: False
    monkeypatch.setattr(gateway_config, "_gateway_execution_parent_routes", lambda _: _parent_route())
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: api)
    with pytest.raises(ValueError, match="GATEWAY_EXECUTION_JOURNAL_MISMATCH"):
        store.start()
    assert api.starts == 0 and store._api is api and store._gateway_run_lock.held
    store.stop()


def test_reconnect_journal_mismatch_never_starts_new_facade(setup_gateway, selected, monkeypatch):
    first, replacement = ReconnectApi(), ReconnectApi()
    replacement.verify_execution_parent_route = lambda _intent, _prepared: False
    sessions = [first, replacement]
    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_kw: sessions.pop(0))
    monkeypatch.setattr(gateway_config, "_RECONNECT_BACKOFF", (0.0,))
    store = make_store(setup_gateway)
    store.start()
    lock, db = store._gateway_run_lock, store._gateway_execution_db
    monkeypatch.setattr(gateway_config, "_gateway_execution_parent_routes", lambda _: _parent_route())
    first.state = "failed"
    assert not store.gateway_reconnect()
    assert store._api is replacement and replacement.starts == 0
    assert lock.held and store._gateway_execution_db is db
    store.stop()

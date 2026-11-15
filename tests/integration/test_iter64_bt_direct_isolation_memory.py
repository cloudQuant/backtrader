"""BT direct Broker and SDK facade isolation with in-memory endpoints.

The child hooks are defensive observations, not an OS sandbox: native code,
inherited file descriptors, and unsupported system calls can bypass them. This
exercises Broker start, order, returns and stop through the actual BtApi facade
and DirectWriteCoordinator. Plugin discovery, account facts, market feed,
provider, strategy state, run lock and the facts poller are synthetic. No
provider service, background thread, filesystem journal or account is used.
"""

import json
import os
from pathlib import Path
import subprocess
import sys

if __name__ != "__main__":
    import pytest

    pytestmark = pytest.mark.skipif(os.name != "posix", reason="requires POSIX fcntl guards")


def _child(mode):
    # Install all observers before importing any product package. The parent
    # supplies -B/PYTHONDONTWRITEBYTECODE to prevent bytecode writes as well.
    import fcntl
    import socket
    import threading
    import _thread

    attempts = {"risk": 0, "network": 0, "bind": 0, "private_read": 0, "write": 0,
                "lock": 0, "thread": 0, "process": 0}

    bind_origins = []

    class RiskObserver:
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "bt_api_risk" or fullname.startswith("bt_api_risk."):
                attempts["risk"] += 1
                raise ImportError("Risk import blocked")
            return None

    sys.meta_path.insert(0, RiskObserver())
    assert not any(n == "bt_api_risk" or n.startswith("bt_api_risk.") for n in sys.modules)

    def audit(event, args):
        if event == "socket.bind":
            attempts["bind"] += 1
            bind_origins.append(sys._getframe(1).f_globals.get("__name__"))
            raise PermissionError("socket bind blocked")
        if event in {"socket.connect", "socket.sendto", "socket.sendmsg", "socket.getaddrinfo"}:
            attempts["network"] += 1
            raise PermissionError("network blocked")
        if event == "open":
            path, mode_arg, flags = args
            if isinstance(path, (str, bytes, os.PathLike)):
                name = os.fsdecode(path).lower()
                base = os.path.basename(name)
                if (base.startswith(".env")
                    or base in {"credentials", "secrets", "secret"}
                    or (base.startswith(("credentials.", "secrets.", "secret."))
                        and base.rsplit(".", 1)[-1] in {"json", "yaml", "yml", "ini", "toml", "txt"})
                    or base in {"config.yaml", "config.yml"}
                    or name.endswith((".pem", ".key", ".sqlite", ".sqlite3", ".db",
                                      ".sqlite-wal", ".db-wal"))):
                    attempts["private_read"] += 1
                    raise PermissionError("private config and database reads blocked")
            write_mode = isinstance(mode_arg, str) and any(c in mode_arg for c in "wax+")
            write_flags = isinstance(flags, int) and flags & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
            )
            if write_mode or write_flags:
                attempts["write"] += 1
                raise PermissionError("file writes blocked")
        if event in {"os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.link",
                     "os.symlink", "os.chmod", "os.chown", "os.truncate"}:
            attempts["write"] += 1
            raise PermissionError("file mutations blocked")
        if event in {"subprocess.Popen", "os.system", "os.fork", "os.posix_spawn"}:
            attempts["process"] += 1
            raise PermissionError("process creation blocked")

    sys.addaudithook(audit)

    def deny_lock(*args, **kwargs):
        attempts["lock"] += 1
        raise PermissionError("file locks blocked")

    def deny_thread(*args, **kwargs):
        attempts["thread"] += 1
        raise RuntimeError("thread start blocked")

    fcntl.flock = deny_lock
    fcntl.lockf = deny_lock
    original_fcntl = fcntl.fcntl
    lock_commands = {getattr(fcntl, name) for name in (
        "F_SETLK", "F_SETLKW", "F_OFD_SETLK", "F_OFD_SETLKW"
    ) if hasattr(fcntl, name)}

    def guarded_fcntl(fd, command, *args):
        if command in lock_commands:
            return deny_lock(fd, command, *args)
        return original_fcntl(fd, command, *args)

    fcntl.fcntl = guarded_fcntl
    if hasattr(os, "lockf"):
        os.lockf = deny_lock
    threading.Thread.start = deny_thread
    threading._start_new_thread = deny_thread
    _thread.start_new_thread = deny_thread

    def deny_network(*args, **kwargs):
        attempts["network"] += 1
        raise PermissionError("network blocked")

    for method in ("connect", "connect_ex", "send", "sendall", "sendto", "sendmsg"):
        if hasattr(socket.socket, method):
            setattr(socket.socket, method, deny_network)
    socket.getaddrinfo = deny_network

    for method in ("write", "pwrite", "writev"):
        if hasattr(os, method):
            original = getattr(os, method)
            def guarded_write(fd, *args, _original=original):
                if fd not in (1, 2):
                    attempts["write"] += 1
                    raise PermissionError("file writes blocked")
                return _original(fd, *args)
            setattr(os, method, guarded_write)

    if mode == "guards":
        try:
            with socket.socket() as sock:
                sock.connect(("127.0.0.1", 1))
        except PermissionError:
            pass
        else:
            raise AssertionError("connect guard failed")
        try:
            with socket.socket() as sock:
                sock.connect_ex(("127.0.0.1", 1))
        except PermissionError:
            pass
        else:
            raise AssertionError("connect_ex guard failed")
        try:
            with socket.socket(type=socket.SOCK_DGRAM) as sock:
                sock.sendto(b"synthetic", ("127.0.0.1", 1))
        except PermissionError:
            pass
        else:
            raise AssertionError("sendto guard failed")
        for method in ("send", "sendall", "sendmsg"):
            if hasattr(socket.socket, method):
                try:
                    with socket.socket() as sock:
                        getattr(sock, method)(b"synthetic")
                except PermissionError:
                    pass
                else:
                    raise AssertionError(method + " guard failed")
        try:
            socket.getaddrinfo("synthetic.invalid", 1)
        except PermissionError:
            pass
        else:
            raise AssertionError("DNS guard failed")
        try:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
        except PermissionError:
            pass
        else:
            raise AssertionError("bind guard failed")
        for name in ("/__iter64__/.env", "/__iter64__/config.yaml", "/__iter64__/facts.sqlite",
                     "/__iter64__/secrets.json", "/__iter64__/client.key"):
            try:
                open(name, "r")
            except PermissionError:
                pass
            else:
                raise AssertionError("private read guard failed")
        try:
            open("/__iter64_write_blocked__", "w")
        except PermissionError:
            pass
        else:
            raise AssertionError("write guard failed")
        try:
            os.write(-1, b"synthetic")
        except PermissionError:
            pass
        else:
            raise AssertionError("fd write guard failed")
        try:
            fcntl.flock(-1, fcntl.LOCK_EX)
        except PermissionError:
            pass
        else:
            raise AssertionError("lock guard failed")
        try:
            fcntl.fcntl(-1, fcntl.F_SETLK, b"")
        except PermissionError:
            pass
        else:
            raise AssertionError("fcntl lock guard failed")
        try:
            threading.Thread(target=lambda: None).start()
        except RuntimeError:
            pass
        else:
            raise AssertionError("thread guard failed")
        try:
            sys.audit("subprocess.Popen", "synthetic", (), None, None)
        except PermissionError:
            pass
        else:
            raise AssertionError("process creation audit guard failed")
        assert attempts == {"risk": 0, "network": 6 + int(hasattr(socket.socket, "sendmsg")),
                            "bind": 1, "private_read": 5, "write": 2,
                            "lock": 2, "thread": 1, "process": 1}
    elif mode == "risk_control":
        from importlib.machinery import PathFinder
        assert PathFinder.find_spec("bt_api_risk") is not None
        try:
            import bt_api_risk  # noqa: F401 -- positive observer control
        except ImportError as exc:
            assert str(exc) == "Risk import blocked"
        else:
            raise AssertionError("Risk import guard failed")
        assert attempts["risk"] > 0 and "bt_api_risk" not in sys.modules
        assert all(attempts[key] == 0 for key in ("network", "bind", "private_read", "write", "lock", "thread", "process"))
    elif mode in {"direct", "direct_denied"}:
        from importlib.machinery import PathFinder
        assert PathFinder.find_spec("bt_api_risk") is not None
        import logging
        from types import SimpleNamespace
        import bt_api_base.logging_factory as logging_factory

        logger = logging.getLogger("iter64-bt-direct-isolation")
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        logging_factory.get_logger = lambda *args, **kwargs: logger

        import backtrader as bt
        import backtrader.live_state as live_state
        from bt_api_base.direct_write_protocol import (
            DirectOrderReservation, DirectSubmitResult, DirectWriteErrorPolicy,
            SettlementStatus, WriteOperation,
        )
        from bt_api_py.bt_api import BtApi
        import bt_api_py.bt_api as facade_module
        import bt_api_py.provider_entrypoints as entrypoints
        from tests.unit.brokers.direct._fakes import (
            EXCHANGE, SYMBOL, FakeApi, FakeSchedule, FakeStore, make_feed,
            native_identity, order_event, trade_event,
        )

        calls = []
        facts = FakeApi()
        identity = native_identity("000000000001")

        class MemorySnapshot:
            def __init__(self):
                self.value = None
            def read(self):
                return self.value
            def read_for_live(self, *_args, **_kwargs):
                return self.value
            def write(self, value):
                self.value = value

        class MemorySequence:
            local_seq = 0
            def restore_ref_basis(self):
                pass
            def allocate(self, _ref):
                self.local_seq += 1
                return self.local_seq

        class MemoryPending:
            def __init__(self):
                self.records = {}
            def active(self):
                return []
            def history(self):
                return []
            def get(self, key):
                return self.records.get(key)
            def bind(self, **kwargs):
                owner = self
                class Port:
                    store = owner
                    def commit(self, record):
                        calls.append("commit")
                        owner.records["marker"] = {"record": record, "status": "PREPARED", **kwargs}
                        return "marker"
                return Port()
            def mark(self, marker, status, **kwargs):
                self.records[marker].update(status=status, **kwargs)
                return True

        class MemoryWaiting:
            def active(self):
                return []
            def history(self):
                return []
            def waiting(self):
                return []

        class MemoryState:
            strategy_uuid = "00000000-0000-0000-0000-000000000001"
            strategy_dir = "memory-only"
            identity = SimpleNamespace(account_binding={"synthetic": True})
            def __init__(self):
                self.snapshot = MemorySnapshot()
                self.sequence = MemorySequence()
                self.pending = MemoryPending()
                self.waiting = MemoryWaiting()
            def acquire_run_lock(self):
                calls.append("memory_lock")
                return SimpleNamespace(release=lambda: calls.append("memory_unlock"))

        state = MemoryState()
        live_state.StrategyStateDir = lambda *_args, **_kwargs: state
        live_state.bind_account = lambda *_args, **_kwargs: None
        bt.brokers.BtApiBroker._direct_start_facts_poller = lambda _self: calls.append("poller_stub")

        class Feed:
            def disconnect(self):
                calls.append("feed_disconnect")
        feed = Feed()

        class Provider:
            direct_write_error_policy = DirectWriteErrorPolicy(frozenset(), frozenset())
            settlement_required = False
            def __init__(self):
                self.events = []
            def account_reference(self):
                return "synthetic-account"
            def account_facts(self, **sections):
                calls.append("account_facts")
                return facts.direct_account_facts(EXCHANGE, **sections)
            def trading_day(self):
                return facts.trading_day
            def session_generation(self):
                return facts.session_generation
            def settlement_status(self):
                return SettlementStatus.CONFIRMED
            def reserve_order(self, request):
                calls.append("reserve")
                return DirectOrderReservation(identity=identity, symbol=request.symbol, reservation_id="r1")
            def release_reservation(self, reservation):
                calls.append("release")
            def submit_order(self, reservation, request, grant, verifier):
                assert state.pending.get("marker") is not None
                calls.append("submit")
                verifier.consume(grant, exchange_name=EXCHANGE, operation=WriteOperation.PLACE,
                                 session_generation=1)
                return DirectSubmitResult(sent=True, identity=reservation.identity)
            def drain_execution_events(self, limit):
                calls.append("poll")
                out, self.events = self.events[:limit], self.events[limit:]
                return tuple(out)
            def close(self):
                calls.append("provider_close")

        provider = Provider()
        def create_feed(name, queue, **settings):
            assert name == EXCHANGE and settings.get("synthetic") is True, (name, settings)
            calls.append("feed_create")
            return feed
        def load_entrypoint(group, name, *, optional=False):
            assert name == EXCHANGE
            if group == "bt_api.trading_session_providers":
                return lambda selected: FakeSchedule()
            assert group == "bt_api.direct_write_providers" and optional
            calls.append("discovery")
            def factory(selected):
                assert selected is feed
                calls.append("provider_create")
                return provider
            return factory

        facade_module._ensure_plugins_loaded = lambda: calls.append("plugin_discovery_fake")
        facade_module.ExchangeRegistry.create_feed = create_feed
        entrypoints.load_route_entrypoint = load_entrypoint
        enabled = mode == "direct"
        api = BtApi({EXCHANGE: {"synthetic": True}}, debug=False, write_admission={EXCHANGE: enabled})
        assert api.write_admission.is_enabled(EXCHANGE) is enabled
        bt_feed = make_feed(SYMBOL)
        store = FakeStore(api, [bt_feed])
        broker = bt.brokers.BtApiBroker(store=store, strategy_dir="memory-only", first_init=True,
                                        stop_cancel_timeout=0)
        broker.start()
        assert broker._direct_active() and store.start_calls == [broker]
        order = broker.buy(SimpleNamespace(name="strategy"), bt_feed, 1, price=3500.0,
                           exectype=bt.Order.Limit, offset="open")
        if enabled:
            assert order.status == bt.Order.Submitted, (order.status, dict(order.info), calls)
            assert calls.index("reserve") < calls.index("commit") < calls.index("submit")
            provider.events.append(order_event(identity, "accepted", sys_id="1001"))
            broker.next()
            assert order.status == bt.Order.Accepted
            provider.events.append(trade_event("T1", sys_id="1001", qty=1))
            broker.next()
            assert order.status == bt.Order.Completed
            assert broker.getposition(bt_feed).size == 1
        else:
            assert order.status == bt.Order.Rejected
            assert order.info.error_code == "write_admission_disabled"
            assert order.executed.size == 0
            assert not any(call in calls for call in ("reserve", "commit", "submit"))
            assert state.pending.records == {}
            assert broker.getposition(bt_feed).size == 0
        assert broker.stop()["status"] == "STOPPED"
        assert store.stop_calls == 1 and "memory_unlock" in calls
        api.close()
        assert "feed_disconnect" in calls and "provider_close" in calls
        assert bind_origins in ([], ["urllib3.util.connection"]), bind_origins
        assert all(attempts[key] == 0 for key in
                   ("risk", "network", "private_read", "write", "lock", "thread", "process")), attempts
        assert not any(n == "bt_api_risk" or n.startswith("bt_api_risk.") for n in sys.modules)
    else:
        raise AssertionError("unknown child mode")
    print(json.dumps({"mode": mode, "attempts": attempts}))


def _run_child(mode):
    root = Path(__file__).resolve().parents[2]
    sdk = root.parent / "bt_api_py"
    paths = [root, sdk, sdk / "bt_api/bt_api_base/src", sdk / "bt_api/bt_api_risk/src"]
    env = {"PYTHONPATH": os.pathsep.join(map(str, paths)), "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONNOUSERSITE": "1"}
    result = subprocess.run([sys.executable, "-B", __file__, mode], cwd=root, env=env,
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_bt_direct_lifecycle_never_imports_risk_or_performs_external_io():
    attempts = _run_child("direct")["attempts"]
    assert attempts["bind"] in (0, 1)
    assert all(attempts[key] == 0 for key in
               ("risk", "network", "private_read", "write", "lock", "thread", "process"))


def test_bt_direct_disabled_admission_refuses_without_provider_write():
    attempts = _run_child("direct_denied")["attempts"]
    assert attempts["bind"] in (0, 1)
    assert all(attempts[key] == 0 for key in
               ("risk", "network", "private_read", "write", "lock", "thread", "process"))


def test_observers_detect_risk_and_block_side_effects():
    assert _run_child("risk_control")["attempts"]["risk"] > 0
    attempts = _run_child("guards")["attempts"]
    assert attempts["network"] in (6, 7)
    assert {key: value for key, value in attempts.items() if key != "network"} == {
        "risk": 0, "bind": 1, "private_read": 5, "write": 2, "lock": 2,
        "thread": 1, "process": 1,
    }


if __name__ == "__main__":
    _child(sys.argv[1])

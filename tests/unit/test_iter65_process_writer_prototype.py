"""Local process probe of the CTP family owner and parent writer lease.

Only a new temporary SQLite file and synthetic identities/admission are used.
This does not establish Gateway generation fencing, a caller-owned flow lock,
cross-host exclusion, native CTP behavior, or real account authorization.
"""

from hashlib import sha256
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time


WORKSPACE = Path(__file__).resolve().parents[3]
DAY = "20261109"
ACCOUNT = "ctp-account-ref.v1:" + sha256(b"iter65-process-writer-fixture").hexdigest()
TIMEOUT = 30
LEGACY_TABLES = (
    "execution_outbox", "cancellation_outbox", "ctp_order_identity_reservations",
    "ctp_order_ref_watermarks", "ctp_order_ref_account_watermarks", "ctp_dispatch_commands",
)


def _environment():
    return {
        "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
        "PYTHONPATH": os.pathsep.join(str(path) for path in (
            WORKSPACE / "tools", WORKSPACE / "backtrader",
            WORKSPACE / "bt_api_py" / "bt_api" / "bt_api_base" / "src",
            WORKSPACE / "bt_api_py" / "bt_api" / "bt_api_execution" / "src",
        )),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }


def _spec(scope, name):
    from bt_api_base.market_protocol import MarketInstrumentKey

    instrument = MarketInstrumentKey("ctp", "SHFE", "synthetic", "future", "rb", "rb")
    return {
        "parent_ref": name, "registration_operation_id": "register-" + name,
        "risk_operation_id": "risk-" + name, "account_scope": scope.account_ref,
        "strategy_scope": scope.strategy_id, "execution_domain_ref": "synthetic-domain",
        "instrument": instrument.to_dict(), "quantity": "5", "quantity_unit": "lots",
        "side": "buy", "offset": "open", "limit_price": "10",
        "creation_trading_day": DAY, "allowed_trading_days": [DAY],
        "expires_at_ns": time.time_ns() + 300_000_000_000, "grant_revision": "synthetic-grant",
        "plan_digest": "a" * 64, "plan_version": "v1", "target_position_ref": None,
        "risk_selected": False, "time_in_force": "DAY",
    }


def _worker(role, path):
    # Any attempted CTP provider import or socket creation is an immediate failure.
    import importlib.abc
    import socket

    class NoCtpProvider(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "_ctp" or fullname == "bt_api_ctp" or fullname.startswith("bt_api_ctp."):
                raise AssertionError("CTP provider imports are forbidden in this probe")
            return None

    def forbidden(*_args, **_kwargs):
        raise AssertionError("native CTP identity or network access is forbidden")

    sys.meta_path.insert(0, NoCtpProvider())
    socket.socket = forbidden
    import bt_api_base
    import bt_api_execution
    from bt_api_execution.contracts import ExecutionScope
    from bt_api_execution.errors import InvalidStateTransition, WriterLeaseUnavailableError
    from bt_api_execution.parent_authority import ParentAuthority
    from bt_api_execution.store import SqliteExecutionStore

    SqliteExecutionStore.reserve_ctp_order_identity = forbidden
    for module in (bt_api_base, bt_api_execution, sys.modules[ParentAuthority.__module__],
                   sys.modules[SqliteExecutionStore.__module__]):
        assert Path(module.__file__).resolve().is_relative_to(WORKSPACE), module.__file__
    for name, module in tuple(sys.modules.items()):
        if name.startswith(("bt_api_base.", "bt_api_execution.")) and getattr(module, "__file__", None):
            assert Path(module.__file__).resolve().is_relative_to(WORKSPACE), module.__file__
    assert not any(name in {"_ctp", "bt_api_ctp"} or name.startswith("bt_api_ctp.")
                   for name in sys.modules)
    scope = ExecutionScope("ctp", "simulation", ACCOUNT, "synthetic-strategy", DAY)
    store = SqliteExecutionStore.open_ctp_account_store(path, scope)

    def send(**message):
        print(json.dumps(message), flush=True)

    def counts():
        return {table: store._connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                for table in LEGACY_TABLES}

    def conflict():
        try:
            store.acquire_ctp_account_family_owner(scope)
        except InvalidStateTransition as error:
            assert "already has a persistent owner" in str(error)
            return "persistent-owner-conflict"
        raise AssertionError("a second store unexpectedly acquired the family")

    try:
        if role == "A":
            family = store.acquire_ctp_account_family_owner(scope)
            lease = store.acquire_or_renew_lease(
                scope, "synthetic-writer", ttl_ns=300_000_000_000, ctp_account_family_owner=family)
            authority = ParentAuthority(store, scope, lease, admission=lambda action, value: True)
            before = counts()
            assert all(value == 0 for value in before.values())
            assert authority.accept(_spec(scope, "original"))["gateway_state"] == "PENDING"
            send(event="ready", pid=os.getpid(), token=lease.fencing_token, counts=before)
            assert sys.stdin.readline().strip() == "renew"
            assert store.release_lease(scope, lease.owner_id, fencing_token=lease.fencing_token)
            renewed = store.acquire_or_renew_lease(
                scope, "synthetic-writer", ttl_ns=300_000_000_000, ctp_account_family_owner=family)
            assert renewed.fencing_token > lease.fencing_token
            try:
                authority.accept(_spec(scope, "stale"))
            except WriterLeaseUnavailableError:
                pass
            else:
                raise AssertionError("stale lease unexpectedly wrote a parent")
            new_authority = ParentAuthority(store, scope, renewed, admission=lambda action, value: True)
            assert new_authority.accept(_spec(scope, "renewed"))["gateway_state"] == "PENDING"
            assert counts() == before
            send(event="renewed", token=renewed.fencing_token, stale_rejected=True)
            assert sys.stdin.readline().strip() == "exit"
        else:
            send(event="ready", pid=os.getpid(), result=conflict())
            assert sys.stdin.readline().strip() == "retry"
            send(event="retry", result=conflict())
            assert sys.stdin.readline().strip() == "reopen"
            store.close()
            store = SqliteExecutionStore.open_ctp_account_store(path, scope)
            result = conflict()
            rows = store._connection.execute(
                "SELECT parent_id, gateway_state, request_json FROM execution_parent_records ORDER BY parent_id"
            ).fetchall()
            parents = {row["parent_id"]: row["gateway_state"] for row in rows}
            assert all(json.loads(row["request_json"])["account_scope"] == ACCOUNT for row in rows)
            send(event="reopened", result=result, parents=parents, counts=counts())
        assert not any(name in {"_ctp", "bt_api_ctp"} or name.startswith("bt_api_ctp.")
                       for name in sys.modules)
    finally:
        store.close()


def _receive(process):
    ready, _, _ = select.select([process.stdout], [], [], TIMEOUT)
    assert ready, "worker did not respond within the bounded timeout"
    line = process.stdout.readline()
    assert line, "worker exited without a response"
    return json.loads(line)


def _send(process, command):
    process.stdin.write(command + "\n")
    process.stdin.flush()


def test_ctp_family_conflict_and_writer_fence_across_independent_processes(tmp_path):
    path = tmp_path / "synthetic-process-writer.sqlite"
    processes = []
    try:
        def start(role):
            process = subprocess.Popen(
                [sys.executable, "-u", str(Path(__file__).resolve()), role, str(path)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=_environment(), cwd=str(WORKSPACE / "backtrader"),
                start_new_session=True,
            )
            processes.append(process)
            return process

        a = start("A")
        first = _receive(a)
        assert first["event"] == "ready"
        b = start("B")
        second = _receive(b)
        assert second["event"] == "ready" and second["result"] == "persistent-owner-conflict"
        assert len({os.getpid(), first["pid"], second["pid"]}) == 3
        _send(a, "renew")
        renewed = _receive(a)
        assert renewed["event"] == "renewed" and renewed["stale_rejected"]
        assert renewed["token"] > first["token"]
        _send(b, "retry")
        assert _receive(b) == {"event": "retry", "result": "persistent-owner-conflict"}
        _send(a, "exit")
        a.wait(timeout=TIMEOUT)
        assert a.returncode == 0, a.stderr.read()
        _send(b, "reopen")
        reopened = _receive(b)
        assert reopened == {
            "event": "reopened", "result": "persistent-owner-conflict",
            "parents": {"original": "PENDING", "renewed": "PENDING"}, "counts": first["counts"],
        }
        b.wait(timeout=TIMEOUT)
        assert b.returncode == 0, b.stderr.read()
    finally:
        for process in processes:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=TIMEOUT)
                except subprocess.TimeoutExpired:
                    if process.poll() is None:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    process.wait(timeout=TIMEOUT)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()


if __name__ == "__main__":
    _worker(sys.argv[1], sys.argv[2])

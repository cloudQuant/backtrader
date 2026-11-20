"""Identity-safe retention of uncertain service observation owners."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
from types import MappingProxyType

import pytest

pytest.importorskip("bt_api_py.service_observation_assembly")

import backtrader.service.service_observation as observation  # noqa: E402
from bt_api_py.service_observation_assembly import ServiceObservationError  # noqa: E402


@pytest.fixture
def isolated_keepalive(monkeypatch):
    keepalive = []
    monkeypatch.setattr(observation, "_KEEPALIVE", keepalive)
    monkeypatch.setattr(observation, "_KEEPALIVE_LOCK", threading.Lock())
    return keepalive


class _IdentityOnly:
    __hash__ = None

    def __eq__(self, _other):
        raise AssertionError("keepalive deduplication must use identity")


class _FakeStore:
    def stop(self, *, timeout):
        assert timeout == 1.0
        return {"shutdown_state": "PASS"}


class _FakeClients:
    def __init__(self, outcomes):
        self.runtime = object()
        self.account_client = object()
        self.metadata = {}
        self.market_clients = {}
        self.close_report = None
        self._outcomes = list(outcomes)
        self.close_calls = 0

    def assert_owner(self):
        return None

    def close(self, **_kwargs):
        self.close_calls += 1
        outcome = self._outcomes.pop(0)
        if outcome == "raise_before_report":
            raise RuntimeError("synthetic close interruption")
        self.close_report = MappingProxyType({"status": "PASS"})
        return self.close_report


def _session(clients):
    proxy = _IdentityOnly()
    store = _FakeStore()
    session = observation.ServiceObservationSession(
        clients,
        proxy=proxy,
        store=store,
        bindings={"feed": _IdentityOnly()},
        timeout_seconds=1.0,
    )
    return session, proxy, store


def test_repeated_pre_report_close_failure_keeps_one_exact_tuple(isolated_keepalive):
    clients = _FakeClients(("raise_before_report", "raise_before_report", "pass"))
    session, proxy, store = _session(clients)

    for expected_calls in (1, 2):
        with pytest.raises(ServiceObservationError, match="SERVICE_CLEANUP_UNCONFIRMED"):
            session.close()
        assert clients.close_calls == expected_calls
        assert len(isolated_keepalive) == 1
        retained = isolated_keepalive[0]
        assert retained[0] is clients
        assert retained[1] is proxy
        assert retained[2] is store
        assert retained[3] is session.bindings

    report = session.close()
    assert report["status"] == "PASS"
    assert clients.close_calls == 3
    # No retained entry is removed, even after a later successful retry.
    assert len(isolated_keepalive) == 1
    assert isolated_keepalive[0][0] is clients


def test_distinct_uncertain_resource_groups_are_never_coalesced(isolated_keepalive):
    sessions = []
    for _ in range(2):
        session, proxy, store = _session(_FakeClients(("raise_before_report",)))
        sessions.append((session, proxy, store))

    for session, _proxy, _store in sessions:
        with pytest.raises(ServiceObservationError, match="SERVICE_CLEANUP_UNCONFIRMED"):
            session.close()

    assert len(isolated_keepalive) == 2
    for retained, (session, proxy, store) in zip(isolated_keepalive, sessions):
        assert retained[0] is session._clients
        assert retained[1] is proxy
        assert retained[2] is store
        assert retained[3] is session.bindings


def test_concurrent_exact_identity_retention_is_atomic(isolated_keepalive):
    same = (_IdentityOnly(), _IdentityOnly(), _IdentityOnly(), _IdentityOnly())
    distinct = [
        (_IdentityOnly(), _IdentityOnly(), _IdentityOnly(), _IdentityOnly())
        for _ in range(4)
    ]
    groups = [same] * 12 + distinct
    barrier = threading.Barrier(len(groups) + 1)

    def retain(group):
        barrier.wait(timeout=10)
        observation._retain_uncertain_resources(*group)

    with ThreadPoolExecutor(max_workers=len(groups)) as pool:
        futures = [pool.submit(retain, group) for group in groups]
        barrier.wait(timeout=10)
        for future in futures:
            future.result(timeout=10)

    assert len(isolated_keepalive) == 1 + len(distinct)
    same_entries = [
        entry for entry in isolated_keepalive
        if all(held is current for held, current in zip(entry, same))
    ]
    assert len(same_entries) == 1
    for group in distinct:
        assert sum(
            all(held is current for held, current in zip(entry, group))
            for entry in isolated_keepalive
        ) == 1

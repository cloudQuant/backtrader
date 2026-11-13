"""Explicit Store simulation queries over real temporary SDK calendar stores."""

import hashlib
import json
import threading
from dataclasses import replace
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from bt_api_ctp.calendar_snapshot import CalendarSnapshot
from bt_api_py.trading_calendar_binding import SIMULATION_ONLY
from bt_api_py.trading_calendar_composite import compose_simulated
from bt_api_py.trading_calendar_store import (
    CurrentPrecondition,
    PolicyPublication,
    TradingCalendarStore,
    calendar_snapshot_digest,
)
from bt_api_py.trading_calendar_update_simulation import VenueContent

from backtrader.stores import btapistore as module
from tests.unit.stores.test_iter67_calendar_config_wiring import local_store
from tests.unit.stores.test_iter67_trading_calendar_status import ROUTE, OTHER, make_store

MONDAY = date(2026, 10, 12)


def publish(root, start="09:00", mock=True):
    root.mkdir(parents=True)
    ids = ["MOCK.simulation_only" if mock else "synthetic"]
    days = ["2026-10-12"]

    def row(kind, contract, night):
        return {
            "venue": "XSH",
            "kind": kind,
            "product": "cu",
            "contracts": [contract],
            "valid_from": days[0],
            "valid_to": days[0],
            "day_windows": [
                {
                    "id": "day",
                    "phase": "continuous",
                    "start": start,
                    "end": "11:00",
                    "end_day_offset": 0,
                }
            ],
            "night_windows": (
                [
                    {
                        "id": "night",
                        "phase": "continuous",
                        "start": "21:00",
                        "end": "01:00",
                        "end_day_offset": 1,
                    }
                ]
                if night
                else []
            ),
            "night_mappings": [
                {
                    "trading_day": days[0],
                    "start_date": "2026-10-09" if night else None,
                    "source_ids": ids,
                }
            ],
            "windows_complete": True,
            "exceptions_complete": True,
            "source_ids": ids,
        }

    data = {
        "sources": [{"id": ids[0], "description": "fictional"}],
        "trading_days": [{"venue": "XSH", "day": days[0], "status": "open", "source_ids": ids}],
        "trading_hours": [row("future", "cu2601", True), row("option", "cu2601-C-100", False)],
        "exceptions": [],
    }
    bundle = compose_simulated(
        mode=SIMULATION_ONLY,
        venues=(VenueContent.from_layers("XSH", MONDAY, MONDAY, data),),
        snapshot_factory=CalendarSnapshot,
    )
    assert bundle.status == "READY_SIMULATED"
    content = json.loads(bundle.snapshot_bytes)
    artifacts = {
        "coverage_manifest_bytes": bundle.manifest_bytes,
        "coverage_manifest_sha256": bundle.manifest_sha256,
        "binding_bytes": bundle.binding_bytes,
        "binding_sha256": bundle.binding_sha256,
    }
    store = TradingCalendarStore(root)
    policy = store.initialize_review_policy(config_read_succeeded=True)
    difference = {}
    diff_sha = hashlib.sha256(
        json.dumps(difference, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    claim = PolicyPublication(
        policy.directory_id,
        policy.revision,
        policy.mode,
        calendar_snapshot_digest(content, **artifacts),
        difference,
        diff_sha,
    )
    assert (
        store.publish(
            content,
            publication_id="p1",
            version_id="v1",
            expected_current=CurrentPrecondition.absent(),
            policy_publication=claim,
            **artifacts,
        ).visibility
        == "COMMITTED"
    )


def query(store, route=ROUTE, **changes):
    fields = {
        "venue": "XSH",
        "kind": "future",
        "product": "cu",
        "contract": "cu2601",
        "trading_day": MONDAY,
        "mode": SIMULATION_ONLY,
    }
    fields.update(changes)
    return store.trading_calendar_query(route, **fields)


def test_real_local_and_facade_queries_and_isolation(monkeypatch, tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    publish(first / "calendars/ctp")
    publish(second / "calendars/ctp", start="10:00", mock=False)
    store, api = local_store(monkeypatch, first)
    other, _ = local_store(monkeypatch, second, api=api)
    result = query(store)
    assert result.status == "COMPLETE" and result.source_ids == ("MOCK.simulation_only",)
    assert (
        result.source_classification,
        result.account_use,
        result.bound,
        result.provider_selection,
        result.observation,
    ) == (
        "DECLARED_MOCK",
        "NOT_AUTHORIZED",
        "NOT_BOUND",
        "EXPLICIT_CTP_ONLY_ROUTE_UNVERIFIED",
        "CURRENT_NOT_PINNED",
    )
    night, day = result.windows
    assert night.trading_day == MONDAY and night.start_utc == datetime(
        2026, 10, 9, 13, tzinfo=timezone.utc
    )
    assert night.end_utc == datetime(2026, 10, 9, 17, tzinfo=timezone.utc)
    assert night.interval_semantics == "START_INCLUSIVE_END_EXCLUSIVE"
    assert day.start_local.hour == 9 and query(other).windows[-1].start_local.hour == 10
    assert query(other).source_classification == "UNVERIFIED"
    option = query(store, kind="option", contract="cu2601-C-100")
    assert option.status == "COMPLETE" and [w.window_id for w in option.windows] == ["day"]
    assert query(store, kind="option", contract="absent").status == "UNKNOWN"
    assert str(first) not in repr(result)
    api.configure_trading_calendar_status(route_roots={ROUTE: str(first / "calendars/ctp")})
    facade, _ = make_store(monkeypatch)
    facade._api.configure_trading_calendar_status(route_roots={ROUTE: str(first / "calendars/ctp")})
    assert query(facade) == result
    assert api.trading_calendar_status(ROUTE).version_id == "v1"


def test_mode_routes_and_faults_are_fail_closed(monkeypatch, tmp_path):
    publish(tmp_path / "calendars/ctp")
    store, api = local_store(monkeypatch, tmp_path)
    assert query(store, mode=None).reason == "SIMULATION_MODE_REQUIRED"
    assert query(store, mode="LIVE").reason == "SIMULATION_MODE_REQUIRED"
    assert query(store, route="MISSING").reason == "ROUTE_UNCONFIGURED"
    assert query(store, trading_day=None).reason == "INVALID_QUERY_SCOPE"
    assert query(store, venue="/private/secret").reason == "INVALID_QUERY_SCOPE"
    good = query(store)
    for bad in (
        replace(good, calendar_ref="/private/secret"),
        replace(good, source_ids=("/private/secret",)),
        replace(good, reason="/private/secret"),
        replace(good, account_use="AUTHORIZED"),
        replace(good, status="UNKNOWN"),
        replace(good, windows=(replace(good.windows[0], window_id="/private/secret"),)),
        {"path": "/private/secret"},
    ):
        monkeypatch.setattr(store._calendar_local_reader, "query", lambda *a, _bad=bad, **kw: _bad)
        result = query(store)
        assert (result.status, result.reason) == ("UNKNOWN", "READ_UNAVAILABLE")
        assert "/private/secret" not in repr(result)

    def broken(*args, **kwargs):
        raise RuntimeError("/private/secret")

    monkeypatch.setattr(store._calendar_local_reader, "query", broken)
    assert query(store).reason == "READ_UNAVAILABLE"
    monkeypatch.setattr(api, "list_exchanges", broken)
    assert query(store).reason == "ROUTE_UNAVAILABLE"


def test_unknown_reader_or_facade_generation_is_rejected(monkeypatch, tmp_path):
    publish(tmp_path / "calendars/ctp")
    store, _ = local_store(monkeypatch, tmp_path)
    good = query(store)
    assert good.status == "COMPLETE"
    calls = []

    def fake(*args, **kwargs):
        calls.append(None)
        return good

    store._calendar_local_reader = SimpleNamespace(query=fake)
    result = query(store)
    assert (result.status, result.reason) == ("UNKNOWN", "CAPABILITY_UNAVAILABLE")
    assert not calls

    facade, api = make_store(monkeypatch)
    monkeypatch.setattr(api, "trading_calendar_query", fake)
    api._trading_calendar_status_reader = object()
    result = query(facade)
    assert (result.status, result.reason) == ("UNKNOWN", "CAPABILITY_UNAVAILABLE")
    assert not calls


@pytest.mark.parametrize("change", ["stop", "restart", "stream", "route", "reader", "reconfigure"])
def test_concurrent_store_and_reader_changes_discard_result(monkeypatch, tmp_path, change):
    publish(tmp_path / "calendars/ctp")
    store, api = local_store(monkeypatch, tmp_path)
    original = store._calendar_local_reader.query
    entered, release = threading.Event(), threading.Event()

    def delayed(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(store._calendar_local_reader, "query", delayed)
    results = []
    thread = threading.Thread(target=lambda: results.append(query(store)))
    thread.start()
    try:
        assert entered.wait(5)
        if change == "stop":
            monkeypatch.setattr(module, "_stop_store", lambda *a, **kw: None)
            store.stop()
        elif change == "restart":
            store.start()
        elif change == "stream":
            store._stream_generation += 1
        elif change == "route":
            api.exchange_feeds[OTHER] = object()
        elif change == "reader":
            store._calendar_local_reader = object()
        else:
            store._calendar_local_reader.configure({ROUTE: str(tmp_path / "calendars/ctp")})
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    expected = (
        "ROUTE_SET_CHANGED"
        if change == "route"
        else "CONFIGURATION_CHANGED"
        if change == "reconfigure"
        else "STORE_CHANGED"
    )
    assert (results[0].status, results[0].reason) == ("UNKNOWN", expected)

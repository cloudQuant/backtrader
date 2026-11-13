"""Offline Store queries against a real SDK mixed simulation publication."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
import hashlib
import json
import socket

import pytest
from bt_api_ctp.calendar_akshare_fetch import collect_akshare_contract
from bt_api_py import trading_calendar_akshare_observation as observation
from bt_api_py import trading_calendar_mixed_simulation_version as mixed
from bt_api_py import trading_calendar_mock as mock
from bt_api_py import trading_calendar_review_bundle as review
from bt_api_py import trading_calendar_store as calendar_store

from tests.unit.stores.test_iter67_trading_calendar_status import OTHER, ROUTE, make_store
from tests.unit.stores.test_iter67_calendar_config_wiring import local_store

SCOPE = {
    "venue": "SHFE", "kind": "future", "product": "pfuture",
    "contract": "mock_shfe_future_contract", "trading_day": date(2027, 1, 4),
    "mode": "SIMULATION_ONLY",
}


def publish(root, *, mixed_version):
    """Build and publish an offline mixed CURRENT from a fake collector response."""
    dates = ["2026-12-31", "2027-01-01", "2027-01-02", "2027-01-03", "2027-01-04"]
    source_ids = ["MOCK.simulation_only"]
    shards = []
    for venue in ("SHFE", "INE", "DCE", "CZCE", "CFFEX", "GFEX"):
        hours, requirements = [], []
        for kind in ("future", "option"):
            product, contract = "p" + kind, f"mock_{venue.lower()}_{kind}_contract"
            hours.append({
                "venue": venue, "kind": kind, "product": product, "contracts": [contract],
                "valid_from": dates[0], "valid_to": dates[-1],
                "day_windows": [{"id": "day", "phase": "continuous", "start": "09:00",
                                 "end": "10:00", "end_day_offset": 0}],
                "night_windows": [{"id": "night", "phase": "continuous", "start": "21:00",
                                   "end": "23:00", "end_day_offset": 0}],
                "night_mappings": [
                    {"trading_day": dates[1], "start_date": None, "source_ids": source_ids},
                    {"trading_day": dates[4], "start_date": dates[1], "source_ids": source_ids},
                ],
                "windows_complete": True, "exceptions_complete": True, "source_ids": source_ids,
            })
            requirements.append({"kind": kind, "product": product, "contract": contract,
                                 "start_day": dates[0], "end_day": dates[-1]})
        shards.append({
            "venue": venue, "coverage_start": dates[0], "coverage_end": dates[-1],
            "layers": {"sources": [deepcopy(mock.SOURCE)],
                       "trading_days": [{"venue": venue, "day": day,
                                         "status": "open" if i in (1, 4) else "closed",
                                         "source_ids": source_ids} for i, day in enumerate(dates)],
                       "trading_hours": hours, "exceptions": []},
            "requirements": requirements, "unresolved": [],
        })
    value = {"metadata": deepcopy(mock.LABEL), "shards": shards,
             "source_texts": {source_ids[0]: "MOCK fictional simulation data"}}
    fs = "TRUSTED_LOCAL_POSIX"

    def save(candidate_id, data):
        result = review.build_once(root=str(root), candidate_id=candidate_id, input_data=data,
                                   filesystem=fs, emit=lambda _: None)
        assert (result["status"], result["review_status"]) == (
            "COMMITTED", "STRUCTURALLY_READY_UNVERIFIED"), result
        return review.show(root=str(root), candidate_id=candidate_id, filesystem=fs)

    shown = save("1" * 32, value)
    provenance = None
    if mixed_version:
        def collector(**kwargs):
            return collect_akshare_contract(
                **kwargs, _runner=lambda *_: ("CHILD_OK", {
                    "status": "OK", "rows": [["交易时间", "日盘 09:00-10:00"]]})
            )
        observed = observation.observe(
            root=str(root), observation_id="a" * 32, run_id="b" * 32,
            venue="SHFE", contract="RB2701", requested_date=date(2026, 11, 13),
            timeout=1, filesystem=fs, _collector=collector,
        )
        assert observed["record_state"] == "COMMITTED"
        record = mixed.build_template(
            root=str(root), candidate_root=str(root), candidate_id="1" * 32,
            observation_id="a" * 32, run_id="b" * 32, filesystem=fs,
            target={"venue": "SHFE", "kind": "future", "product": "pfuture",
                    "mock_contract": "mock_shfe_future_contract", "valid_from": dates[0],
                    "valid_to": dates[-1]},
            assumptions={scope: {"phase": "continuous", "timezone": "Asia/Shanghai"}
                         for scope in ("DAY", "NIGHT")},
        )
        digest = mixed.template_digest(record, root=str(root), candidate_root=str(root),
                                       filesystem=fs, include_trace=True)
        generated = mixed.materialize_template(
            record, root=str(root), candidate_root=str(root), filesystem=fs,
            alignment="REPEAT_OVER_MOCK_OWNER_DAY_MAPPING", expected_evidence_sha256=digest,
            candidate_id="2" * 32,
        )
        provenance = generated["provenance"]
        shown = save("2" * 32, generated["input"])
    composite = shown["bundle"]["report"]["composite"]
    canonical = lambda obj: json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=False).encode("utf-8")
    artifacts = {"coverage_manifest_bytes": canonical(composite["manifest"]),
                 "coverage_manifest_sha256": composite["manifest_sha256"],
                 "binding_bytes": canonical(composite["binding"]),
                 "binding_sha256": composite["binding_sha256"],
                 "simulation_provenance": provenance}
    content = composite["snapshot"]
    store = calendar_store.TradingCalendarStore(str(root))
    policy = store.initialize_review_policy(config_read_succeeded=True)
    difference = {}
    claim = calendar_store.PolicyPublication(
        policy.directory_id, policy.revision, policy.mode,
        calendar_store.calendar_snapshot_digest(content, **artifacts), difference,
        hashlib.sha256(canonical(difference)).hexdigest(),
    )
    result = store.publish(content, publication_id="MOCK_pub", version_id="MOCK_ver",
                           **artifacts, expected_current=calendar_store.CurrentPrecondition.absent(),
                           policy_publication=claim)
    assert result.visibility == "COMMITTED", result


@pytest.fixture
def ready(monkeypatch, tmp_path):
    def blocked(*args, **kwargs):
        raise AssertionError("network access is disabled")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    root = tmp_path / "calendars" / "ctp"
    root.mkdir(parents=True)
    publish(root, mixed_version=True)
    store, api = make_store(monkeypatch)
    api.configure_trading_calendar_status(route_roots={ROUTE: str(root)})
    return store, api, root


def query(store, **scope):
    return store.trading_calendar_query(ROUTE, **(SCOPE | scope))


def test_real_mixed_facade_and_non_target(ready, monkeypatch):
    store, api, root = ready
    sdk = api.trading_calendar_query(ROUTE, **SCOPE)
    actual = query(store)
    assert actual == sdk
    assert (actual.status, actual.source_classification, actual.data_origin) == (
        "COMPLETE", "AKSHARE_MOCK", "AKSHARE_MOCK")
    assert (actual.bound, actual.observation, actual.account_use) == (
        "NOT_BOUND", "CURRENT_NOT_PINNED", "NOT_AUTHORIZED")
    assert {row["source_type"] for row in actual.simulation_provenance["windows"]} == {
        "AKSHARE", "MOCK"}
    assert all(w.interval_semantics == "START_INCLUSIVE_END_EXCLUSIVE" for w in actual.windows)
    for window in actual.windows:
        contains = lambda moment, w=window: w.start_utc <= moment < w.end_utc
        assert contains(window.start_utc)
        assert contains(window.end_utc - timedelta(microseconds=1))
        assert not contains(window.start_utc - timedelta(microseconds=1))
        assert not contains(window.end_utc)
    local, _ = local_store(monkeypatch, root.parent.parent, api=api)
    assert query(local) == actual
    day_only = query(store, trading_day=date(2027, 1, 1))
    assert day_only.status == "COMPLETE" and len(day_only.windows) == 1
    option = query(store, kind="option", product="poption", contract="mock_shfe_option_contract")
    assert (option.status, option.source_classification, option.data_origin,
            option.simulation_provenance) == ("COMPLETE", "DECLARED_MOCK", "AKSHARE_MOCK", None)


def test_pure_mock_legacy_publication(monkeypatch, tmp_path):
    root = tmp_path / "calendar"
    root.mkdir()
    publish(root, mixed_version=False)
    store, api = make_store(monkeypatch)
    api.configure_trading_calendar_status(route_roots={ROUTE: str(root)})
    result = query(store)
    assert (result.status, result.source_classification, result.data_origin,
            result.simulation_provenance) == ("COMPLETE", "DECLARED_MOCK", "UNSPECIFIED", None)


@pytest.mark.parametrize("change", [
    "missing", "legacy_downgrade", "legacy_unverified", "origin", "schema", "scope", "date",
    "window_missing", "window_duplicate",
    "window_id", "scope_swap", "source_type", "source_ids", "basis", "start", "transition", "phase",
    "observation", "simulation", "locator", "digest", "window_time", "half_open", "unknown",
])
def test_tampered_mixed_result_is_rejected(ready, monkeypatch, change):
    store, api, _ = ready
    good = api.trading_calendar_query(ROUTE, **SCOPE)
    p = deepcopy(good.simulation_provenance)
    rows = p["windows"]
    changes = {"simulation_provenance": p}
    if change == "missing":
        changes.update(simulation_provenance=None, source_classification="UNVERIFIED")
    elif change in {"legacy_downgrade", "legacy_unverified"}:
        changes.update(data_origin="UNSPECIFIED", simulation_provenance=None,
                       source_classification=("DECLARED_MOCK" if change == "legacy_downgrade"
                                              else "UNVERIFIED"))
    elif change == "origin":
        changes["data_origin"] = "UNSPECIFIED"
    elif change == "schema":
        p["schema"] = "bt_api.calendar-mixed-window-provenance/1"
    elif change == "scope":
        p["target"]["mock_contract"] = "mock_other"
    elif change == "date":
        p["target"]["valid_to"] = "2027-01-01"
    elif change == "window_missing":
        rows.pop()
    elif change == "window_duplicate":
        rows[0] = deepcopy(rows[1])
    elif change == "window_id":
        rows[0]["window_id"] = "wrong"
    elif change == "scope_swap":
        rows[0]["scope"] = "DAY" if rows[0]["scope"] == "NIGHT" else "NIGHT"
        rows[0]["fields"]["scope"]["value"] = rows[0]["scope"]
    elif change == "source_type":
        rows[0]["source_type"] = "MOCK" if rows[0]["source_type"] == "AKSHARE" else "AKSHARE"
    elif change == "source_ids":
        changes["source_ids"] = ("MOCK.simulation_only",)
    elif change == "basis":
        rows[0]["fields"]["start"]["basis"] = "PROVEN"
    elif change == "start":
        rows[0]["fields"]["start"]["value"] = "10:00"
    elif change == "transition":
        rows[0]["fields"]["day_transition"]["value"] = True
    elif change == "phase":
        rows[0]["simulation"]["phase"]["value"] = "auction"
    elif change == "observation":
        rows[0]["observation"]["identity"] = "PROVEN"
    elif change == "simulation":
        rows[0]["simulation"]["local_date"]["value"] = "2027-01-04"
    elif change == "locator":
        p["evidence_locator"]["capture_id"] = "/private/path"
    elif change == "digest":
        p["evidence_sha256"] = "a" * 63
    elif change == "window_time":
        window = good.windows[0]
        changes["windows"] = (replace(window, start_utc=window.start_utc + timedelta(minutes=1),
                                      start_local=window.start_local + timedelta(minutes=1)),
                              *good.windows[1:])
    elif change == "half_open":
        changes["windows"] = (replace(good.windows[0], interval_semantics="INCLUSIVE"),
                              *good.windows[1:])
    else:
        changes.update(status="UNKNOWN", reason="CURRENT_UNAVAILABLE", windows=(), source_ids=(),
                       source_classification="UNVERIFIED", coverage_status="UNKNOWN", calendar_ref=None,
                       publication_id=None, content_sha256=None, version_sha256=None)
    monkeypatch.setattr(api, "trading_calendar_query", lambda *args, **kwargs: replace(good, **changes))
    result = query(store)
    assert (result.status, result.reason) == ("UNKNOWN", "READ_UNAVAILABLE")
    assert "/private/path" not in repr(result)


def test_mixed_result_cannot_be_reused_for_another_query_scope(ready, monkeypatch):
    store, api, _ = ready
    mixed_result = api.trading_calendar_query(ROUTE, **SCOPE)
    monkeypatch.setattr(api, "trading_calendar_query", lambda *args, **kwargs: mixed_result)
    result = query(store, kind="option", product="poption", contract="mock_shfe_option_contract")
    assert (result.status, result.reason) == ("UNKNOWN", "READ_UNAVAILABLE")


def test_mixed_result_discarded_after_configuration_or_route_change(ready, monkeypatch):
    store, api, root = ready
    original = api.trading_calendar_query
    def reconfigure(*args, **kwargs):
        result = original(*args, **kwargs)
        api.configure_trading_calendar_status(route_roots={ROUTE: str(root)})
        return result
    monkeypatch.setattr(api, "trading_calendar_query", reconfigure)
    assert query(store).reason == "CONFIGURATION_CHANGED"

    def change_route(*args, **kwargs):
        result = original(*args, **kwargs)
        api.exchange_feeds[OTHER] = object()
        return result
    monkeypatch.setattr(api, "trading_calendar_query", change_route)
    assert query(store).reason == "ROUTE_SET_CHANGED"

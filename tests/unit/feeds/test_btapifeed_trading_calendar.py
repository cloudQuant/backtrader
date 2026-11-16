"""BtApiFeed read-only calendar queries, day rollover and restart recovery.

Iteration 67, D67-11: a strategy reads its feed's session/window projection.
These cases use a real temporary SDK calendar directory and the Store's
read-only query; no network, account, updater or private configuration is used.
"""

import datetime as _dt
import hashlib
import json

import pytest

pytest.importorskip("bt_api_py", reason="needs the bt_api_py SDK")
pytest.importorskip("bt_api_ctp", reason="needs the CTP calendar provider")

from bt_api_ctp.calendar_snapshot import CalendarSnapshot  # noqa: E402
from bt_api_py.bt_api import BtApi  # noqa: E402
from bt_api_py.trading_calendar_binding import SIMULATION_ONLY  # noqa: E402
from bt_api_py.trading_calendar_composite import compose_simulated  # noqa: E402
from bt_api_py.trading_calendar_store import (  # noqa: E402
    CalendarStoreError,
    CurrentPrecondition,
    PolicyPublication,
    TradingCalendarStore,
    calendar_snapshot_digest,
)
from bt_api_py.trading_calendar_update_simulation import VenueContent  # noqa: E402

from backtrader.feeds.btapifeed import BtApiFeed  # noqa: E402
from tests.unit.stores.test_iter67_calendar_config_wiring import local_store  # noqa: E402
from tests.unit.stores.test_iter67_trading_calendar_status import ROUTE  # noqa: E402

MONDAY = _dt.date(2026, 10, 12)
TUESDAY = _dt.date(2026, 10, 13)
SHANGHAI = _dt.timezone(_dt.timedelta(hours=8), "Asia/Shanghai")
UTC = _dt.timezone.utc


def publish(root, *, publication_id="p1", version_id="v1", days=(MONDAY,), start="09:00",
            mock=True, night=True, day_status="open", exceptions=()):
    """Publish one simulated CTP snapshot; this is fixture data, not an exchange fact."""
    root.mkdir(parents=True, exist_ok=True)
    ids = ["MOCK.simulation_only" if mock else "synthetic"]
    first, last = days[0], days[-1]

    def hours_row(kind, contract, has_night):
        return {
            "venue": "XSH",
            "kind": kind,
            "product": "cu",
            "contracts": [contract],
            "valid_from": first.isoformat(),
            "valid_to": last.isoformat(),
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
                if has_night
                else []
            ),
            "night_mappings": [
                {
                    "trading_day": day.isoformat(),
                    "start_date": (
                        (day - _dt.timedelta(days=3)).isoformat() if has_night else None
                    ),
                    "source_ids": ids,
                }
                for day in days
                if day_status == "open"
            ],
            "windows_complete": True,
            "exceptions_complete": True,
            "source_ids": ids,
        }

    layers = {
        "sources": [{"id": ids[0], "description": "fictional"}],
        "trading_days": [
            {"venue": "XSH", "day": day.isoformat(), "status": day_status, "source_ids": ids}
            for day in days
        ],
        "trading_hours": [
            hours_row("future", "cu2601", night),
            hours_row("option", "cu2601-C-100", False),
        ],
        "exceptions": list(exceptions),
    }
    bundle = compose_simulated(
        mode=SIMULATION_ONLY,
        venues=(VenueContent.from_layers("XSH", first, last, layers),),
        snapshot_factory=CalendarSnapshot,
    )
    assert bundle.status == "READY_SIMULATED", bundle
    content = json.loads(bundle.snapshot_bytes)
    artifacts = {
        "coverage_manifest_bytes": bundle.manifest_bytes,
        "coverage_manifest_sha256": bundle.manifest_sha256,
        "binding_bytes": bundle.binding_bytes,
        "binding_sha256": bundle.binding_sha256,
    }
    store = TradingCalendarStore(root)
    try:
        policy = store.read_review_policy()
    except CalendarStoreError:
        policy = store.initialize_review_policy(config_read_succeeded=True)
    difference = {}
    difference_sha256 = hashlib.sha256(
        json.dumps(difference, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    claim = PolicyPublication(
        policy.directory_id,
        policy.revision,
        policy.mode,
        calendar_snapshot_digest(content, **artifacts),
        difference,
        difference_sha256,
    )
    if (root / "CURRENT.json").exists():
        current = store.read_current()
        expected = CurrentPrecondition.matching(
            current.publication_id, current.publication_sha256
        )
    else:
        expected = CurrentPrecondition.absent()
    result = store.publish(
        content,
        publication_id=publication_id,
        version_id=version_id,
        expected_current=expected,
        policy_publication=claim,
        **artifacts,
    )
    assert result.visibility == "COMMITTED"


def make_feed(store, **kwargs):
    options = {
        "dataname": "cu2601",
        "store": store,
        "provider": "btapi",
        "calendar_route": ROUTE,
        "calendar_venue": "XSH",
        "calendar_kind": "future",
        "calendar_product": "cu",
        "calendar_contract": "cu2601",
    }
    options.update(kwargs)
    return BtApiFeed(**options)


def test_trading_session_reads_calendar_and_reports_neutral_scope(monkeypatch, tmp_path):
    publish(tmp_path / "calendars/ctp")
    store, _ = local_store(monkeypatch, tmp_path)
    feed = make_feed(store)

    result = feed.trading_session(trading_day=MONDAY)
    assert result.status == "COMPLETE"
    assert result.reason == "EXPLICIT_DATA"
    assert result.trading_day == MONDAY
    assert result.windows and [window.window_id for window in result.windows] == ["night", "day"]
    assert all(window.trading_day == MONDAY for window in result.windows)
    assert (result.phase, result.active, result.active_window) == ("unknown", None, None)
    assert (result.calendar_ref, result.publication_id) == ("v1", "p1")
    assert result.source_ids == ("MOCK.simulation_only",)
    assert result.source_classification == "DECLARED_MOCK"
    assert (result.environment, result.bound, result.account_use) == (
        "SIMULATION_ONLY",
        "NOT_BOUND",
        "NOT_AUTHORIZED",
    )
    assert result.trading_day_transition == "NOT_PROVEN"
    assert result.stale is False
    assert str(tmp_path) not in repr(result)

    # Only a matching window establishes an active phase.
    inside = feed.trading_session(at=_dt.datetime(2026, 10, 12, 9, 30, tzinfo=SHANGHAI))
    assert (inside.status, inside.phase, inside.active) == ("COMPLETE", "continuous", True)
    assert inside.active_window.window_id == "day"
    outside = feed.trading_session(at=_dt.datetime(2026, 10, 12, 12, 0, tzinfo=SHANGHAI))
    assert (outside.status, outside.reason, outside.phase, outside.active) == (
        "COMPLETE", "INSTANT_OUTSIDE_WINDOWS", "unknown", None
    )
    assert outside.active_window is None
    # The fixture owns a Friday-evening night window as trading day Monday. The
    # instant's calendar date is never used to infer the trading day.
    overnight = feed.trading_session(at=_dt.datetime(2026, 10, 9, 22, 0, tzinfo=SHANGHAI))
    assert (overnight.trading_day, overnight.phase, overnight.active) == (
        MONDAY,
        "continuous",
        True,
    )
    assert overnight.active_window.window_id == "night"
    # Keyword-compatible calls are equivalent to the positional date form.
    assert feed.trading_session(at=MONDAY) == result


@pytest.mark.parametrize("empty_cause", ["closed_day", "contract_close", "cancel_all"])
def test_complete_empty_windows_do_not_prove_closed(monkeypatch, tmp_path, empty_cause):
    ids = ["MOCK.simulation_only"]
    exception = {
        "venue": "XSH", "kind": "future", "product": "cu", "contract": "cu2601",
        "trading_day": MONDAY.isoformat(), "source_ids": ids,
    }
    exceptions = (
        [{**exception, "action": "close_day", "window_id": None}]
        if empty_cause == "contract_close"
        else [
            {**exception, "action": "cancel_window", "window_id": window_id}
            for window_id in ("night", "day")
        ] if empty_cause == "cancel_all" else []
    )
    publish(
        tmp_path / "calendars/ctp",
        day_status="closed" if empty_cause == "closed_day" else "open",
        night=empty_cause != "closed_day",
        exceptions=exceptions,
    )
    store, _ = local_store(monkeypatch, tmp_path)
    feed = make_feed(store)

    for instant in (None, _dt.datetime(2026, 10, 12, 9, 30, tzinfo=SHANGHAI)):
        result = feed.trading_session(at=instant, trading_day=MONDAY)
        assert (result.status, result.reason, result.phase, result.active) == (
            "COMPLETE", "NO_WINDOWS_RETURNED", "unknown", None
        )
        assert result.windows == () and result.active_window is None
        assert (result.calendar_ref, result.publication_id) == ("v1", "p1")
        assert result.content_sha256 and result.version_sha256
        assert result.source_ids == ("MOCK.simulation_only",)
    windows = feed.trading_windows(
        _dt.datetime(2026, 10, 12, 9, tzinfo=SHANGHAI),
        _dt.datetime(2026, 10, 12, 10, tzinfo=SHANGHAI),
    )
    assert (windows.status, windows.reason, windows.windows, windows.incomplete) == (
        "COMPLETE", "EXPLICIT_DATA", (), False
    )
    assert (windows.calendar_ref, windows.publication_id) == ("v1", "p1")


def test_instant_boundaries_and_other_days_never_infer_closed(monkeypatch, tmp_path):
    publish(tmp_path / "calendars/ctp")
    store, _ = local_store(monkeypatch, tmp_path)
    feed = make_feed(store)
    initial = feed.trading_session(trading_day=MONDAY)
    night, day = initial.windows
    epsilon = _dt.timedelta(microseconds=1)
    for window in (night, day):
        for instant in (window.start_utc, window.end_utc - epsilon):
            hit = feed.trading_session(at=instant)
            assert (hit.reason, hit.phase, hit.active, hit.active_window) == (
                "EXPLICIT_DATA", "continuous", True, window
            )
        for instant in (window.start_utc - epsilon, window.end_utc):
            missed = feed.trading_session(at=instant)
            assert (missed.status, missed.reason, missed.phase, missed.active) == (
                "COMPLETE", "INSTANT_OUTSIDE_WINDOWS", "unknown", None
            )
            assert missed.windows == initial.windows and missed.calendar_ref == "v1"
    far_future = feed.trading_session(at=_dt.datetime(2040, 1, 1, tzinfo=UTC))
    assert (far_future.trading_day, far_future.reason, far_future.phase, far_future.active) == (
        MONDAY, "INSTANT_OUTSIDE_WINDOWS", "unknown", None
    )


def test_unavailable_calendar_never_fabricates_a_session(monkeypatch, tmp_path):
    # The configured root exists only as a path; its CURRENT is absent.
    store, _ = local_store(monkeypatch, tmp_path)
    feed = make_feed(store)
    missing = feed.trading_session(trading_day=MONDAY)
    assert missing.status == "UNKNOWN"
    assert missing.reason == "CURRENT_UNAVAILABLE"
    assert missing.windows == ()
    assert (missing.phase, missing.active, missing.active_window) == ("unknown", None, None)
    assert (missing.calendar_ref, missing.publication_id) == (None, None)
    assert missing.stale is False
    assert str(tmp_path) not in repr(missing)
    missing_at = feed.trading_session(
        at=_dt.datetime(2026, 10, 12, 9, 30, tzinfo=SHANGHAI), trading_day=MONDAY
    )
    assert (missing_at.status, missing_at.reason, missing_at.phase, missing_at.active) == (
        "UNKNOWN", "CURRENT_UNAVAILABLE", "unknown", None
    )

    publish(tmp_path / "calendars/ctp")
    store, _ = local_store(monkeypatch, tmp_path)
    feed = make_feed(store)
    calls = []
    original = store.trading_calendar_query

    def counted(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "trading_calendar_query", counted)
    no_scope = make_feed(store, calendar_venue=None)
    unavailable = no_scope.trading_session(trading_day=MONDAY)
    assert (unavailable.status, unavailable.reason) == ("UNKNOWN", "CALENDAR_SCOPE_UNAVAILABLE")
    assert unavailable.windows == () and not calls

    no_day = feed.trading_session()
    assert (no_day.status, no_day.reason) == ("UNKNOWN", "TRADING_DAY_REQUIRED")
    assert not calls


def test_day_rollover_rereads_only_after_the_qualified_day_advances(monkeypatch, tmp_path):
    root = tmp_path / "calendars/ctp"
    publish(root)
    store, _ = local_store(monkeypatch, tmp_path)
    feed = make_feed(store)
    first = feed.refresh_trading_calendar(trading_day=MONDAY)
    assert (first.status, first.reason) == ("BOUND", "CALENDAR_BOUND")
    assert (first.trading_day, first.calendar_ref) == (MONDAY, "v1")

    calls = []
    original = store.trading_calendar_query

    def counted(route, **kwargs):
        calls.append((route, kwargs["trading_day"]))
        return original(route, **kwargs)

    monkeypatch.setattr(store, "trading_calendar_query", counted)
    # A newer publication inside the same binding day is not effective.
    publish(root, publication_id="p2", version_id="v2", days=(TUESDAY,))
    same = feed.refresh_trading_calendar(trading_day=MONDAY)
    assert (same.status, same.reason, same.calendar_ref) == ("BOUND", "SAME_DAY", "v1")
    assert not calls
    assert feed.trading_session(trading_day=MONDAY).calendar_ref == "v1"

    advanced = feed.refresh_trading_calendar(trading_day=TUESDAY)
    assert calls and calls[-1][1] == TUESDAY
    assert (advanced.status, advanced.reason) == ("BOUND", "CALENDAR_ADVANCED")
    assert (advanced.trading_day, advanced.calendar_ref) == (TUESDAY, "v2")
    session = feed.trading_session()
    assert (session.status, session.trading_day, session.calendar_ref) == (
        "COMPLETE",
        TUESDAY,
        "v2",
    )
    assert [window.trading_day for window in session.windows] == [TUESDAY, TUESDAY]

    # The qualified trading day never rewinds silently.
    regressed = feed.refresh_trading_calendar(trading_day=MONDAY)
    assert (regressed.status, regressed.reason) == ("STALE", "TRADING_DAY_REGRESSION")
    assert (regressed.trading_day, regressed.calendar_ref) == (TUESDAY, "v2")
    assert regressed.stale is True


def test_failed_reread_keeps_the_previous_version_and_reports_stale(monkeypatch, tmp_path):
    root = tmp_path / "calendars/ctp"
    publish(root)
    store, _ = local_store(monkeypatch, tmp_path)
    feed = make_feed(store)
    assert feed.refresh_trading_calendar(trading_day=MONDAY).calendar_ref == "v1"
    bound = feed.trading_session(trading_day=MONDAY)

    current = (root / "CURRENT.json").read_bytes()
    (root / "CURRENT.json").unlink()
    stale = feed.refresh_trading_calendar(trading_day=TUESDAY)
    assert (stale.status, stale.reason, stale.stale) == (
        "STALE",
        "CURRENT_UNAVAILABLE",
        True,
    )
    assert (stale.trading_day, stale.calendar_ref) == (MONDAY, "v1")
    # The retained version is still the last readable view; no new-day windows exist.
    assert feed.trading_calendar_binding() == stale
    unknown_day = feed.trading_session(trading_day=TUESDAY)
    assert (unknown_day.status, unknown_day.reason) == ("UNKNOWN", "CURRENT_UNAVAILABLE")
    assert unknown_day.windows == () and unknown_day.stale is True
    retained = feed.trading_session(trading_day=MONDAY)
    assert (retained.status, retained.stale) == ("COMPLETE", True)
    assert (retained.calendar_ref, retained.windows) == (bound.calendar_ref, bound.windows)

    # A read-only accessor performs no store I/O.
    def forbidden(*_args, **_kwargs):
        raise AssertionError("binding accessor must not re-read the calendar")

    original_query = store.trading_calendar_query
    monkeypatch.setattr(store, "trading_calendar_query", forbidden)
    assert feed.trading_calendar_binding() == stale
    monkeypatch.setattr(store, "trading_calendar_query", original_query)

    (root / "CURRENT.json").write_bytes(current)
    publish(root, publication_id="p2", version_id="v2", days=(TUESDAY,))
    recovered = feed.refresh_trading_calendar(trading_day=TUESDAY)
    assert (recovered.status, recovered.reason, recovered.stale) == (
        "BOUND",
        "CALENDAR_ADVANCED",
        False,
    )
    assert (recovered.trading_day, recovered.calendar_ref) == (TUESDAY, "v2")


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_restart_recovery_reads_current_and_never_reuses_feed_state(
    monkeypatch, tmp_path, damage
):
    root = tmp_path / "calendars/ctp"
    publish(root, publication_id="p1", version_id="v1", days=(MONDAY,))
    store, api = local_store(monkeypatch, tmp_path)
    first = make_feed(store)
    assert first.trading_session(trading_day=MONDAY).calendar_ref == "v1"

    # "Restart": a newer CURRENT was published by another process.
    publish(root, publication_id="p2", version_id="v2", days=(TUESDAY,))
    restarted_store, _ = local_store(monkeypatch, tmp_path, api=api)
    restarted = make_feed(restarted_store)
    reopened = restarted.trading_session(trading_day=TUESDAY)
    assert (reopened.status, reopened.calendar_ref) == ("COMPLETE", "v2")
    assert reopened.windows and all(window.trading_day == TUESDAY for window in reopened.windows)
    # The old feed keeps its own same-day binding; no process-global cache leaks.
    assert first.trading_calendar_binding().calendar_ref == "v1"

    # Another restart with no publication reports the same version, never older.
    second_store, _ = local_store(monkeypatch, tmp_path, api=api)
    assert make_feed(second_store).trading_session(trading_day=TUESDAY).calendar_ref == "v2"

    if damage == "missing":
        (root / "CURRENT.json").unlink()
    else:
        (root / "CURRENT.json").write_bytes(b"{not-json")
    damaged_store, _ = local_store(monkeypatch, tmp_path, api=api)
    damaged = make_feed(damaged_store)
    unavailable = damaged.trading_session(trading_day=TUESDAY)
    assert (unavailable.status, unavailable.reason) == ("UNKNOWN", "CURRENT_UNAVAILABLE")
    assert (unavailable.calendar_ref, unavailable.publication_id) == (None, None)
    assert unavailable.windows == () and unavailable.stale is False


def test_trading_windows_are_utc_half_open_with_explicit_gaps(monkeypatch, tmp_path):
    publish(tmp_path / "calendars/ctp")
    store, _ = local_store(monkeypatch, tmp_path)
    feed = make_feed(store)
    assert feed.refresh_trading_calendar(trading_day=MONDAY).calendar_ref == "v1"

    start = _dt.datetime(2026, 10, 12, 9, 30, tzinfo=SHANGHAI).astimezone(UTC)
    end = _dt.datetime(2026, 10, 12, 10, 30, tzinfo=SHANGHAI).astimezone(UTC)
    whole = feed.trading_windows(start=start, end=end)
    assert (whole.status, whole.reason, whole.incomplete) == ("COMPLETE", "EXPLICIT_DATA", False)
    assert [window.window_id for window in whole.windows] == ["day"]
    assert (whole.start_utc, whole.end_utc) == (start, end)
    assert whole.windows[0].start_utc < start and whole.windows[0].end_utc > end
    assert whole.calendar_ref == "v1" and whole.stale is False
    assert str(tmp_path) not in repr(whole)

    later = _dt.datetime(2026, 10, 13, 10, 0, tzinfo=SHANGHAI).astimezone(UTC)
    partial = feed.trading_windows(start, later)
    assert (partial.status, partial.incomplete) == ("PARTIAL", True)
    assert [gap.trading_day for gap in partial.gaps] == [TUESDAY]
    assert partial.gaps[0].reason in {"SCOPE_OR_DATA_UNAVAILABLE", "COVERAGE_UNAVAILABLE"}
    assert all(window.trading_day == MONDAY for window in partial.windows)

    invalid = feed.trading_windows(end, start)
    assert (invalid.status, invalid.reason) == ("UNKNOWN", "INVALID_QUERY_RANGE")
    naive = feed.trading_windows(_dt.datetime(2026, 10, 12, 9), end)
    assert (naive.status, naive.reason) == ("UNKNOWN", "INVALID_QUERY_RANGE")
    assert naive.windows == () and naive.gaps == ()


def test_shared_facade_stores_keep_calendar_query_isolation(monkeypatch, tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    publish(
        first / "calendars/ctp", publication_id="p1", version_id="v1", start="09:00"
    )
    publish(
        second / "calendars/ctp",
        publication_id="p9",
        version_id="v9",
        start="10:00",
        mock=False,
    )
    api = BtApi(debug=False)
    api.exchange_feeds[ROUTE] = object()
    reconfigurations = []
    original_configure = api.configure_trading_calendar_status

    def configure(*, route_roots):
        reconfigurations.append(dict(route_roots))
        return original_configure(route_roots=route_roots)

    monkeypatch.setattr(api, "configure_trading_calendar_status", configure)
    store_a, _ = local_store(monkeypatch, first, api=api)
    store_b, _ = local_store(monkeypatch, second, api=api)
    # Constructing either Store must not rewrite the borrowed facade's calendar.
    assert reconfigurations == []
    assert api.trading_calendar_status(ROUTE).reason == "ROUTE_UNCONFIGURED"

    feed_a = make_feed(store_a)
    feed_b = make_feed(store_b)
    value_a = feed_a.trading_session(trading_day=MONDAY)
    value_b = feed_b.trading_session(trading_day=MONDAY)
    assert (value_a.calendar_ref, value_a.windows[-1].start_local.hour) == ("v1", 9)
    assert (value_b.calendar_ref, value_b.windows[-1].start_local.hour) == ("v9", 10)
    assert (value_a.source_classification, value_b.source_classification) == (
        "DECLARED_MOCK",
        "UNVERIFIED",
    )

    # An external facade reconfiguration affects only facade-backed routes; the
    # local Store keeps its own directory on a forced re-read.
    api.configure_trading_calendar_status(route_roots={ROUTE: str(second / "calendars/ctp")})
    reread = feed_a.refresh_trading_calendar(trading_day=MONDAY, force=True)
    assert (reread.calendar_ref, reread.status) == ("v1", "BOUND")
    assert feed_a.trading_session(trading_day=MONDAY).windows[-1].start_local.hour == 9
    assert feed_b.trading_calendar_binding().calendar_ref == "v9"

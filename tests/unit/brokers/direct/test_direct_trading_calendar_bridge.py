"""Day-switch Feed calendar re-read and the aggregated reconcile report (67.07).

G1: when a verified trading-day switch reaches ``completed`` the Broker asks
every attached Feed that holds a calendar binding to re-read CURRENT for the
qualified day; the outcome of each Feed is surfaced in the reconcile report.
G2: the report carries an aggregated ``trading_calendar`` section projected
only from each Feed's ``trading_calendar_binding()``; absent bindings are
explicit unknown/unavailable rows, never omitted or guessed.

Evidence: UNIT/FAKE for the Broker facade (``_fakes.Env``), but the calendar
side is a real temporary published CTP snapshot read through a real
``BtApiStore`` and a real ``BtApiFeed``. No network, account or updater runs.
The fixture data is simulated, not an exchange fact or trading authority.
"""

import datetime as _dt

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")
pytest.importorskip("bt_api_ctp", reason="needs the CTP calendar provider")

from tests.unit.feeds.test_btapifeed_trading_calendar import (  # noqa: E402
    MONDAY,
    TUESDAY,
    make_feed as make_calendar_feed,
    publish,
)
from tests.unit.stores.test_iter67_calendar_config_wiring import local_store  # noqa: E402

from ._fakes import (  # noqa: E402
    EXCHANGE,
    calendar_binding,
    drop_calendar,
    quiet,
    run_day_switch,
    set_calendar,
)

FROM_DAY = "20261012"
TO_DAY = "20261013"
_CALENDAR_SYMBOL = "cu2601"


def _start(env):
    env.api.trading_day = FROM_DAY
    broker = env.start(first_init=True)
    quiet(broker)
    env.api.schedule.trading_day = MONDAY
    return broker


def _move_to_new_day(env, broker, day=TO_DAY, date=TUESDAY):
    env.api.trading_day = day
    env.api.schedule.trading_day = date
    facts = env.api.direct_account_facts(EXCHANGE, positions=False, active_orders=False)
    broker._direct_facts_results.append(("funds", facts))
    broker.next()


def _calendar_feed(env, tmp_path, monkeypatch, *, bind=MONDAY):
    """Attach a real BtApiFeed bound to ``bind`` from a published snapshot."""
    base = tmp_path / "caldata"
    base.mkdir()
    root = base / "calendars/ctp"
    publish(root, days=(bind,))
    store, _ = local_store(monkeypatch, base)
    feed = make_calendar_feed(store)
    assert feed.refresh_trading_calendar(bind).status == "BOUND"
    env.store._data_feeds.append(feed)
    calls = []
    original = feed.refresh_trading_calendar

    def counted(day, **kwargs):
        calls.append(day)
        return original(day, **kwargs)

    feed.refresh_trading_calendar = counted
    return feed, root, calls


def _row(section, symbol=_CALENDAR_SYMBOL):
    return next(row for row in section["feeds"] if row["feed"] == symbol)


def _reload_row(reload_result, symbol=_CALENDAR_SYMBOL):
    return next(row for row in reload_result["feeds"] if row["feed"] == symbol)


# ---------------------------------------------------------------------------
# G1: the completed switch requests one re-read at the qualified day
# ---------------------------------------------------------------------------
def test_completed_switch_rereads_the_feed_at_the_qualified_day(env, tmp_path, monkeypatch):
    feed, root, calls = _calendar_feed(env, tmp_path, monkeypatch)
    broker = _start(env)
    # The next day's publication exists before the switch; the Feed keeps v1
    # until the qualified day actually advances.
    publish(root, publication_id="p2", version_id="v2", days=(TUESDAY,))
    assert feed.trading_calendar_binding().calendar_ref == "v1"

    _move_to_new_day(env, broker)
    report = run_day_switch(broker)
    assert report["status"] == "completed"
    assert calls and calls[-1] == TUESDAY  # the exact qualified trading day

    binding = feed.trading_calendar_binding()
    assert (binding.status, binding.trading_day, binding.calendar_ref) == (
        "BOUND",
        TUESDAY,
        "v2",
    )
    reload_result = report["calendar_reload"]
    row = _reload_row(reload_result)
    assert (row["status"], row["reason"]) == ("BOUND", "CALENDAR_ADVANCED")
    assert (row["previous_version"], row["version"]) == ("v1", "v2")
    assert row["publication_id"] == "p2" and row["stale"] is False

    section = broker.get_direct_reconcile_report()["trading_calendar"]
    row = _row(section)
    assert row["status"] == "BOUND" and row["stale"] is False
    assert (row["version"], row["publication_id"]) == ("v2", "p2")
    assert row["trading_day"] == TUESDAY.isoformat()
    assert row["source_ids"] == ["MOCK.simulation_only"]
    assert row["source_classification"] == "DECLARED_MOCK"
    assert row["last_reread"] == "CALENDAR_ADVANCED"
    assert row["coverage_end_utc"] is not None
    assert str(tmp_path) not in repr(section)


@pytest.mark.parametrize("damage", ["missing_current", "uncovered_day"])
def test_failed_reread_keeps_the_previous_version_and_reports_stale(
    env, tmp_path, monkeypatch, damage
):
    feed, root, calls = _calendar_feed(env, tmp_path, monkeypatch)
    broker = _start(env)
    if damage == "missing_current":
        (root / "CURRENT.json").unlink()
    else:
        # A same-day publication is not effective: CURRENT has no answer for
        # the new qualified day, so the retained version stays in use.
        publish(root, publication_id="p2", version_id="v2", days=(MONDAY,), start="09:30")

    _move_to_new_day(env, broker)
    report = run_day_switch(broker)
    # A failed Feed re-read never fails the verified Broker switch itself.
    assert report["status"] == "completed"
    assert calls == [TUESDAY]
    reload_row = _reload_row(report["calendar_reload"])
    assert reload_row["status"] == "STALE" and reload_row["stale"] is True
    assert reload_row["reason"] in {"CURRENT_UNAVAILABLE", "COVERAGE_UNAVAILABLE"}
    # The bridge never turns the UNKNOWN re-read into the "current" publication.
    assert (reload_row["version"], reload_row["publication_id"]) == ("v1", "p1")
    section = broker.get_direct_reconcile_report()["trading_calendar"]
    row = _row(section)
    assert (row["status"], row["stale"]) == ("STALE", True)
    assert (row["version"], row["publication_id"]) == ("v1", "p1")
    assert row["trading_day"] == MONDAY.isoformat()  # the retained binding day
    assert section["status"] in {"STALE", "PARTIAL"}


def test_a_regressed_day_is_refused_by_the_feed_and_surfaced(env, tmp_path, monkeypatch):
    feed, root, calls = _calendar_feed(env, tmp_path, monkeypatch, bind=TUESDAY)
    broker = _start(env)
    # Direct call: the Broker itself blocks a regressed provider day before a
    # switch can complete, so this checks the bridge does not bypass the Feed's
    # own regression refusal and reports it as-is.
    result = broker._direct_refresh_feed_calendars(FROM_DAY)
    row = _reload_row(result)
    assert (row["status"], row["reason"]) == ("STALE", "TRADING_DAY_REGRESSION")
    assert (row["version"], row["trading_day"]) == ("v1", TUESDAY.isoformat())
    assert calls == [MONDAY]


def test_a_feed_without_a_binding_is_not_queried_and_is_still_reported(env):
    class UnboundFeed:
        _name = _CALENDAR_SYMBOL

        def trading_calendar_binding(self):
            return calendar_binding(
                status="UNBOUND",
                reason="NOT_BOUND",
                calendar_ref=None,
                publication_id=None,
                trading_day=None,
            )

        def refresh_trading_calendar(self, day):
            raise AssertionError("an unbound feed must not be queried")

    env.store._data_feeds = [env.feed, UnboundFeed()]
    broker = _start(env)
    _move_to_new_day(env, broker)
    report = run_day_switch(broker)
    assert report["status"] == "completed"
    row = _reload_row(report["calendar_reload"])
    assert (row["status"], row["reason"]) == ("UNBOUND", "NOT_BOUND")
    assert row["version"] is None and row["publication_id"] is None


# ---------------------------------------------------------------------------
# G2: the aggregated calendar section
# ---------------------------------------------------------------------------
def test_aggregated_section_uses_only_the_feed_binding(env):
    broker = env.broker()
    _dt_end = _dt.datetime(2026, 11, 6, 3, 0, tzinfo=_dt.timezone.utc)
    set_calendar(
        env.feed,
        calendar_ref="cal-v9",
        publication_id="pub-9",
        reason="CALENDAR_REFRESHED",
        trading_day=_dt.date(2026, 11, 6),
        coverage_end_utc=_dt_end,
        source_ids=("AKSHARE.simulation_unverified",),
        source_classification="UNVERIFIED",
    )
    section = broker.get_direct_reconcile_report()["trading_calendar"]
    row = _row(section, "rb2701")
    assert row["status"] == "BOUND" and row["stale"] is False
    assert (row["version"], row["publication_id"]) == ("cal-v9", "pub-9")
    assert row["trading_day"] == "2026-11-06"
    assert row["source_ids"] == ["AKSHARE.simulation_unverified"]
    assert row["source_classification"] == "UNVERIFIED"
    assert row["coverage_status"] == "DECLARED_UNVERIFIED"
    assert row["coverage_end_utc"].startswith("2026-11-06T03:00:00")
    assert row["last_reread"] == "CALENDAR_REFRESHED"
    assert row["environment"] == "SIMULATION_ONLY"
    assert row["bound"] == "NOT_BOUND" and row["account_use"] == "NOT_AUTHORIZED"


def test_absent_bindings_are_explicit_unknown_rows_with_finite_codes(env):
    broker = env.broker()
    drop_calendar(env.feed)
    drop_calendar(env.other_feed)
    section = broker.get_direct_reconcile_report()["trading_calendar"]
    assert section["status"] == "UNKNOWN"
    assert section["reason"] == "CALENDAR_UNAVAILABLE"
    assert [row["feed"] for row in section["feeds"]] == ["rb2701", "hc2701"]
    for row in section["feeds"]:
        assert (row["status"], row["reason"]) == (
            "UNAVAILABLE",
            "CALENDAR_CONTRACT_UNAVAILABLE",
        )
        assert row["version"] is None and row["publication_id"] is None
        assert row["source_ids"] == []

    # A binding that cannot be read is also an explicit row, never a match.
    class Unreadable:
        def trading_calendar_binding(self):
            raise RuntimeError("binding unavailable")

    env.store._data_feeds = [Unreadable()]
    section = broker.get_direct_reconcile_report()["trading_calendar"]
    (row,) = section["feeds"]
    assert (row["status"], row["reason"]) == ("UNAVAILABLE", "CALENDAR_BINDING_UNAVAILABLE")

    # No attached Feed at all is stated, not omitted.
    env.store._data_feeds = []
    section = broker.get_direct_reconcile_report()["trading_calendar"]
    assert section == {
        "status": "UNKNOWN",
        "reason": "CALENDAR_BINDING_UNAVAILABLE",
        "feeds": [],
        "reload": None,
    }

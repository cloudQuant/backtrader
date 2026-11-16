"""Explicit Feed calendar scope for the 007 direct examples (iteration 67, D67-11).

The E2E case uses a real temporary published calendar, a real ``BtApiStore`` and
the real ``BtApiFeed`` created by the example's ``add_feeds``.  No network,
account, updater or private configuration is involved.
"""

import runpy
from pathlib import Path

import pytest
import yaml

import backtrader as bt

from tests.unit.feeds.test_btapifeed_trading_calendar import MONDAY, publish
from tests.unit.stores.test_iter67_calendar_config_wiring import local_store
from tests.unit.stores.test_iter67_trading_calendar_status import ROUTE

EXAMPLE_DIR = Path(__file__).resolve().parents[3] / "examples/live/007_ctp"
_direct = sorted(EXAMPLE_DIR.glob("*_direct/run.py"))
_configs = sorted(EXAMPLE_DIR.glob("*_direct/config.yaml"))
_helper = runpy.run_path(str(EXAMPLE_DIR / "calendar_feed_scope.py"))
check_direct_feed_scope = _helper["check_direct_feed_scope"]
CalendarFeedScopeRefusal = _helper["CalendarFeedScopeRefusal"]
store_calendar_section = _helper["store_calendar_section"]


def scope_config():
    return {
        "symbols": ["cu2601"],
        "contracts": {"cu2601": {"exchange": "XSH", "price_tick": 0.1}},
        "calendars": {
            "root": "calendars",
            "feed_scope": {
                "cu2601": {
                    "route": ROUTE,
                    "venue": "XSH",
                    "kind": "future",
                    "product": "cu",
                    "contract": "cu2601",
                }
            },
        },
        "feed": {
            "timeframe": "ticks",
            "compression": 1,
            "backfill_start": False,
            "event_time_max_age": 2.0,
            "receive_time_max_age": 2.0,
            "incomplete_volume_bars": "lines",
        },
    }


def test_valid_scope_becomes_explicit_feed_keywords():
    result = check_direct_feed_scope(scope_config(), symbols=["cu2601"], route=ROUTE)
    assert result.code is None
    assert result.scopes == {
        "cu2601": {
            "calendar_route": ROUTE,
            "calendar_venue": "XSH",
            "calendar_kind": "future",
            "calendar_product": "cu",
            "calendar_contract": "cu2601",
        }
    }


def test_absent_calendars_section_is_left_to_the_root_gate():
    config = scope_config()
    config.pop("calendars")
    result = check_direct_feed_scope(config, symbols=["cu2601"], route=ROUTE)
    assert result.scopes == {} and result.code is None


def test_missing_or_partial_feed_scope_is_unconfigured():
    for declared in (None, {}):
        config = scope_config()
        if declared is None:
            config["calendars"].pop("feed_scope")
        else:
            config["calendars"]["feed_scope"] = declared
        result = check_direct_feed_scope(config, symbols=["cu2601"], route=ROUTE)
        assert result.scopes == {}
        assert result.code == "calendar_feed_scope_unconfigured"
    config = scope_config()
    config["symbols"] = ["cu2601", "cu2602"]
    config["contracts"]["cu2602"] = {"exchange": "XSH", "price_tick": 0.1}
    result = check_direct_feed_scope(config, symbols=["cu2601", "cu2602"], route=ROUTE)
    assert result.scopes == {}
    assert result.code == "calendar_feed_scope_unconfigured"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda scope: scope.update(kind="spot"),
        lambda scope: scope.pop("product"),
        lambda scope: scope.update(venue="bad value"),
        lambda scope: scope.update(unknown="x"),
        lambda scope: scope.update(contract=""),
    ],
)
def test_malformed_scope_is_invalid(mutate):
    config = scope_config()
    mutate(config["calendars"]["feed_scope"]["cu2601"])
    with pytest.raises(CalendarFeedScopeRefusal, match="calendar_feed_scope_invalid"):
        check_direct_feed_scope(config, symbols=["cu2601"], route=ROUTE)


def test_non_mapping_feed_scope_is_invalid():
    config = scope_config()
    config["calendars"]["feed_scope"] = ["cu2601"]
    with pytest.raises(CalendarFeedScopeRefusal, match="calendar_feed_scope_invalid"):
        check_direct_feed_scope(config, symbols=["cu2601"], route=ROUTE)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda config: config["calendars"]["feed_scope"]["cu2601"].update(contract="cu2602"),
        lambda config: config["calendars"]["feed_scope"]["cu2601"].update(venue="SHFE"),
        lambda config: config["calendars"]["feed_scope"]["cu2601"].update(route="OTHER___FUTURE"),
        lambda config: config["calendars"]["feed_scope"].update(extra={}),
        lambda config: config["feed"].update(calendar_venue="XSH"),
        lambda config: config["contracts"]["cu2601"].update(calendar_product="cu"),
    ],
)
def test_conflicting_scope_fails_closed_without_guessing(mutate):
    config = scope_config()
    mutate(config)
    with pytest.raises(CalendarFeedScopeRefusal, match="calendar_feed_scope_conflict"):
        check_direct_feed_scope(config, symbols=["cu2601"], route=ROUTE)


def test_store_calendar_section_strips_the_consumer_declaration():
    config = scope_config()
    config["calendars"]["review_mode"] = "manual"
    assert store_calendar_section(config) == {"root": "calendars", "review_mode": "manual"}
    assert store_calendar_section({"calendars": {"feed_scope": {}}}) == {}
    assert store_calendar_section({}) is None
    assert store_calendar_section({"calendars": ["not", "a", "mapping"]}) == [
        "not",
        "a",
        "mapping",
    ]


@pytest.mark.parametrize("path", _configs, ids=lambda path: path.parent.name)
def test_every_direct_config_declares_one_explicit_scope_per_symbol(path):
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    result = check_direct_feed_scope(config, symbols=config["symbols"], route="CTP___FUTURE")
    assert result.code is None
    assert set(result.scopes) == set(config["symbols"])
    for symbol, scope in result.scopes.items():
        assert scope["calendar_contract"] == symbol
        # The venue must agree with the already explicit CTP ExchangeID.
        assert scope["calendar_venue"] == config["contracts"][symbol]["exchange"]
        assert scope["calendar_kind"] == "future"


def test_example_runner_wires_the_declared_scope_into_a_real_feed(monkeypatch, tmp_path):
    root = tmp_path / "calendars/ctp"
    root.mkdir(parents=True)
    publish(root)
    store, _ = local_store(monkeypatch, tmp_path)
    config = scope_config()
    result = check_direct_feed_scope(config, symbols=config["symbols"], route=ROUTE)

    script = _direct[0]
    monkeypatch.syspath_prepend(str(script.parent))
    namespace = runpy.run_path(str(script), run_name="feed_scope_runner_test")
    cerebro = bt.Cerebro(stdstats=False)
    feeds = namespace["add_feeds"](cerebro, store, config, result.scopes)
    assert len(feeds) == 1
    feed = feeds[0]
    assert (
        feed.p.calendar_route,
        feed.p.calendar_venue,
        feed.p.calendar_kind,
        feed.p.calendar_product,
        feed.p.calendar_contract,
    ) == (ROUTE, "XSH", "future", "cu", "cu2601")

    session = feed.trading_session(trading_day=MONDAY)
    assert (session.status, session.reason, session.calendar_ref) == (
        "COMPLETE",
        "EXPLICIT_DATA",
        "v1",
    )
    assert session.windows and all(window.trading_day == MONDAY for window in session.windows)


def test_all_direct_runners_pass_the_scope_to_add_feeds():
    assert len(_direct) == 11
    for script in _direct:
        text = script.read_text(encoding="utf-8")
        assert "check_direct_feed_scope(config, symbols=symbols, route=ROUTE)" in text
        assert "add_feeds(cerebro, store, config, feed_calendar.scopes)" in text
        assert "store_calendar_section(config)" in text

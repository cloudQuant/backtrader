"""Unknown tick eligibility is not treated as eligible (iteration 60, INV-04).

A tick that does not state ``bar_eligible`` must not build a Backtrader bar;
only an explicit ``True`` does. SDK typed ticks always set the field (see
``test_market_tick_adapter_baseline``); this pins the untyped/dict path.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

# The live tick path of BtApiFeed requires the SDK.
pytest.importorskip("bt_api_py")

import backtrader as bt  # noqa: E402
from backtrader.feeds.btapifeed import BtApiFeed  # noqa: E402

_WHEN = dt.datetime(2026, 11, 2, 2, 0, tzinfo=dt.timezone.utc)


@pytest.fixture
def feed():
    item = BtApiFeed(dataname="SA609", store=None, timeframe=bt.TimeFrame.Ticks)
    item.events = []
    item._enqueue_bar_event = lambda event, when: item.events.append(event)
    return item


def _tick(**extra):
    return SimpleNamespace(
        price=1500.0, volume=3.0, timestamp=_WHEN.timestamp(), datetime=_WHEN, **extra
    )


def test_tick_without_bar_eligibility_builds_no_bar(feed):
    feed._ingest_tick(_tick())
    assert feed.events == []


def test_explicitly_ineligible_tick_builds_no_bar(feed):
    feed._ingest_tick(_tick(bar_eligible=False))
    assert feed.events == []


def test_explicitly_eligible_tick_builds_a_bar(feed):
    feed._ingest_tick(_tick(bar_eligible=True))
    assert len(feed.events) == 1
    assert feed.events[0].close == 1500.0

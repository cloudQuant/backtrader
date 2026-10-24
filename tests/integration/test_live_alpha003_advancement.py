"""Observe the real Cerebro/cohort advancement barrier for live Alpha003.

Only bounded source rows and the replay clock are synthetic. BtApiFeed,
LiveBarCohort, LiveFactorSet, the Alpha003 graph, Cerebro's runnext loop, and
all line advancement remain the production implementations.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
import backtrader as bt
import pytest

from backtrader.research.live_cohort import LiveBarCohort
from tests.integration import test_live_alpha003_cohort_scenarios as scenarios
from tests.integration import test_live_alpha003_parity as parity


_BARS = 40
_TARGET_COUNTS = (3, 5, 20)
_MODES = ("native", "build")
_OHLCV_FIELDS = parity._OHLCV_FIELDS


def _progress(strategy):
    """Read feed, output-line, and scheduled-node cursors without advancing them."""
    factor = strategy.live_factor_set.factor_instances["alpha003"]["default"]
    feed_lengths = {data._name: len(data) for data in strategy.datas}
    node_line_lengths = {}

    for name, node in factor._nodes.items():
        if isinstance(getattr(node, "outputs", None), Mapping):
            for data in strategy.datas:
                output = node.outputs[data]
                node_line_lengths["%s/%s/value" % (name, data._name)] = len(output.value)
                node_line_lengths["%s/%s/reason" % (name, data._name)] = len(output.reason)
            continue

        lines = node.lines
        node_line_lengths["%s/value" % name] = len(lines.value)
        node_line_lengths["%s/reason" % name] = len(lines.reason)

    for data in strategy.datas:
        node_line_lengths["alpha003/%s/factor" % data._name] = len(factor.outputs[data].factor)

    scheduled = {id(factor): ("alpha003", factor)}
    stack = [factor]
    visited = set()
    while stack:
        owner = stack.pop()
        if owner is None or id(owner) in visited:
            continue
        visited.add(id(owner))
        diagnostics = getattr(owner, "lifecycle_diagnostics", None)
        if isinstance(diagnostics, Mapping) and type(diagnostics.get("call_count")) is int:
            name = type(owner).__name__
            scheduled.setdefault(id(owner), (name, owner))
        for children in getattr(owner, "_lineiterators", {}).values():
            stack.extend(children)

    # Native Alpha003 keeps logical per-asset views over two physical panel
    # Indicators. Build mode may instead expose one scheduled node per asset.
    # Include every graph reference and deduplicate only the scheduled object.
    for name, node in factor._nodes.items():
        physical = getattr(node, "_physical_panel", node)
        diagnostics = getattr(physical, "lifecycle_diagnostics", None)
        if isinstance(diagnostics, Mapping) and type(diagnostics.get("call_count")) is int:
            scheduled.setdefault(id(physical), (name, physical))

    node_call_counts = {}
    for index, (name, node) in enumerate(scheduled.values()):
        node_call_counts["%s#%d" % (name, index)] = node.lifecycle_diagnostics["call_count"]

    return {
        "feed_lengths": feed_lengths,
        "node_line_lengths": node_line_lengths,
        "node_call_counts": node_call_counts,
        "factor_call_count": factor._factor_call_count,
    }


def _assert_progress(progress, expected):
    assert set(progress["feed_lengths"].values()) == {expected}
    assert set(progress["node_line_lengths"].values()) == {expected}
    assert set(progress["node_call_counts"].values()) == {expected}
    assert progress["factor_call_count"] == expected


def _assert_batch_written_progress(progress, *, feed_count, graph_count):
    assert set(progress["feed_lengths"].values()) == {feed_count}
    assert set(progress["node_line_lengths"].values()) == {graph_count}
    assert set(progress["node_call_counts"].values()) == {graph_count}
    assert progress["factor_call_count"] == graph_count


def _source_cursor(feed):
    def remaining(name):
        iterator = getattr(feed, name)
        length_hint = getattr(iterator, "__length_hint__", None)
        return length_hint() if callable(length_hint) else None

    return {
        "history_remaining": remaining("_cohort_history_iter"),
        "live_remaining": remaining("_cohort_live_iter"),
        "history_exhausted": feed._cohort_history_exhausted,
        "live_exhausted": feed._cohort_live_exhausted,
        "history_lookahead": id(feed._cohort_history_lookahead),
        "live_lookahead": id(feed._cohort_live_lookahead),
        "store_lookahead": id(feed._cohort_store_lookahead),
        "completed_lookahead": id(feed._cohort_completed_lookahead),
    }


def _bounded_frames(member_count):
    source = scenarios._scenario_frames(member_count)
    return {name: frame.iloc[:_BARS].copy(deep=True) for name, frame in source.items()}


def _run_observed(frames, *, mode, feed_order, registration_order, availability_order):
    targets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)
    calendar, member_ids = parity._calendar(targets, grid)
    clock = parity._ReplayClock(grid[0].to_pydatetime())
    cohort = LiveBarCohort(
        "alpha003-advancement-%d-%s" % (len(targets), mode),
        calendar,
        max_pending_slots=1,
        max_window_bars=len(grid),
        wait_timeout_ns=5_000_000_000,
    )
    arrival_rank = {asset: index + 1 for index, asset in enumerate(availability_order)}
    events = {
        asset: parity._bar_events(
            frames,
            asset,
            arrival_delay=lambda current, row: arrival_rank[current] * 0.01,
        )
        for asset in targets
    }

    cerebro = bt.Cerebro(
        stdstats=False,
        exactbars=0,
        preload=False,
        runonce=False,
    )
    feeds = {}
    for asset in feed_order:
        feed = bt.feeds.BtApiFeed(
            dataname=asset,
            historical_bars=(),
            live_bars=events[asset],
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            bar_watermark_ms=0,
            clock=clock,
        )
        feeds[asset] = feed
        cerebro.adddata(feed, name=asset)

    for asset in registration_order:
        cohort.register_member(
            member_ids[asset],
            feeds[asset],
            instrument=asset,
            source_ref="feed-%s" % asset,
            line_fields=_OHLCV_FIELDS,
            raw_fields=_OHLCV_FIELDS,
            numeric_fields=_OHLCV_FIELDS,
        )

    plan = parity._live_alpha003_plan(
        targets,
        calendar=calendar,
        mode=mode,
        max_pending_slots=cohort.max_pending_slots,
        max_window_bars=len(grid),
        wait_timeout_ns=cohort.wait_timeout_ns,
        max_future_skew_seconds=1.0,
    )
    cerebro.add_live_bar_cohort(cohort, clock=clock)

    trace = {
        "strategy": None,
        "captures": [],
        "prepare_statuses": [],
        "batch_commits": [],
        "load_calls": [],
        "next_calls": Counter(),
        "next_retries": Counter(),
        "check_calls": [],
        "bar_notifications": [],
        "strategy_progress": [],
        "stop_calls": 0,
    }

    class _AdvancementCapture(parity._LiveAlpha003Capture):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            trace["strategy"] = self

        def _capture(self):
            super()._capture()
            trace["strategy_progress"].append(_progress(self))

        def notify_bar(self, bar):
            instrument = bar.get("instrument") if isinstance(bar, Mapping) else None
            sequence = bar.get("bar_sequence") if isinstance(bar, Mapping) else None
            trace["bar_notifications"].append(
                {
                    "instrument": instrument,
                    "sequence": sequence,
                    "progress": _progress(self),
                    "batch": self.p.cohort.current_batch(),
                }
            )
            return super().notify_bar(bar)

        def stop(self):
            trace["stop_calls"] += 1
            return super().stop()

    cerebro.addstrategy(
        _AdvancementCapture,
        cohort=cohort,
        plan=plan,
        target_order=targets,
    )

    original_capture = cohort.capture_bar

    def capture_spy(feed_ref, event, *, source_role, received_monotonic_ns=None):
        before = _progress(trace["strategy"])
        captured = original_capture(
            feed_ref,
            event,
            source_role=source_role,
            received_monotonic_ns=received_monotonic_ns,
        )
        after = _progress(trace["strategy"])
        if not captured.duplicate:
            trace["captures"].append(
                {
                    "slot_index": captured.slot_index,
                    "instrument": event["instrument"],
                    "source_role": source_role,
                    "available_at": event["available_at"],
                    "before": before,
                    "after": after,
                }
            )
        return captured

    cohort.capture_bar = capture_spy
    original_prepare = cohort.prepare_round

    def prepare_spy(now_monotonic_ns, *, source_time_utc):
        before = _progress(trace["strategy"])
        result = original_prepare(now_monotonic_ns, source_time_utc=source_time_utc)
        after = _progress(trace["strategy"])
        trace["prepare_statuses"].append(
            {"status": result.status, "before": before, "after": after}
        )
        return result

    cohort.prepare_round = prepare_spy
    original_batch_commit = cohort.record_delivery_batch

    def batch_commit_spy(deliveries):
        before = _progress(trace["strategy"])
        batch = original_batch_commit(deliveries)
        after = _progress(trace["strategy"])
        trace["batch_commits"].append(
            {"slot_index": batch.slot_index, "before": before, "after": after}
        )
        return batch

    cohort.record_delivery_batch = batch_commit_spy

    for asset, feed in feeds.items():
        original_load = feed._load

        def load_spy(_feed=feed, _original=original_load):
            envelope = _feed._cohort_armed_envelope
            result = _original()
            trace["load_calls"].append(
                {
                    "instrument": _feed._dataname,
                    "slot_index": None if envelope is None else envelope.slot_index,
                    "result": result,
                    "line_count": len(_feed),
                    "graph": _progress(trace["strategy"]),
                }
            )
            return result

        feed._load = load_spy
        original_next = feed.next

        def next_spy(datamaster=None, ticks=True, _feed=feed, _original=original_next):
            trace["next_calls"][_feed._dataname] += 1
            if datamaster is not None:
                trace["next_retries"][_feed._dataname] += 1
            return _original(datamaster=datamaster, ticks=ticks)

        feed.next = next_spy
        original_check = feed._check

        def check_spy(forcedata=None, _feed=feed, _original=original_check):
            before = {
                "cursor": _source_cursor(_feed),
                "progress": _progress(trace["strategy"]),
                "capture_count": len(trace["captures"]),
            }
            result = _original(forcedata=forcedata)
            after = {
                "cursor": _source_cursor(_feed),
                "progress": _progress(trace["strategy"]),
                "capture_count": len(trace["captures"]),
            }
            trace["check_calls"].append(
                {"instrument": _feed._dataname, "before": before, "after": after}
            )
            return result

        feed._check = check_spy

    strategies = cerebro.run()
    assert len(strategies) == 1
    strategy = strategies[0]
    trace["strategy"] = strategy
    return strategy, cohort, feeds, events, clock, trace


@pytest.mark.integration
@pytest.mark.parametrize("member_count", _TARGET_COUNTS)
@pytest.mark.parametrize("mode", _MODES)
def test_alpha003_live_feed_and_graph_advance_once_after_whole_batch(member_count, mode):
    """Observe source arrival, all-None wait/retry, sealing, and one graph step."""
    frames = _bounded_frames(member_count)
    targets = tuple(frames)
    if mode == "native":
        feed_order = targets[1:] + targets[:1]
        availability_order = tuple(reversed(targets))
    else:
        feed_order = tuple(reversed(targets))
        availability_order = targets[1:] + targets[:1]
    registration_order = tuple(reversed(feed_order))

    strategy, cohort, feeds, events, clock, trace = _run_observed(
        frames,
        mode=mode,
        feed_order=feed_order,
        registration_order=registration_order,
        availability_order=availability_order,
    )
    trace["strategy"] = strategy

    assert len(strategy.snapshots) == _BARS
    assert len(trace["strategy_progress"]) == _BARS
    assert len(trace["captures"]) == _BARS * member_count
    assert len(trace["batch_commits"]) == _BARS
    assert len(trace["bar_notifications"]) == _BARS * member_count
    assert trace["stop_calls"] == 1
    assert not cohort.frozen
    assert len(clock.waits) >= _BARS
    assert all(timeout > 0.0 for timeout in clock.waits)
    assert any(row["status"] == "WAITING_AVAILABILITY" for row in trace["prepare_statuses"])
    assert all(row["before"] == row["after"] for row in trace["prepare_statuses"])

    for slot_index in range(_BARS):
        captures = [row for row in trace["captures"] if row["slot_index"] == slot_index]
        assert tuple(row["instrument"] for row in captures) == feed_order
        assert all(row["source_role"] == "live" for row in captures)
        # Every feed's raw row is captured before the next-slot engine phase;
        # even the last source arrival cannot advance a line or indicator.
        for row in captures:
            _assert_progress(row["before"], slot_index)
            _assert_progress(row["after"], slot_index)
        available_order = tuple(
            sorted(targets, key=lambda asset: events[asset][slot_index]["available_at"])
        )
        assert available_order == availability_order

        commit = trace["batch_commits"][slot_index]
        assert commit["slot_index"] == slot_index
        _assert_batch_written_progress(
            commit["before"], feed_count=slot_index + 1, graph_count=slot_index
        )
        _assert_batch_written_progress(
            commit["after"], feed_count=slot_index + 1, graph_count=slot_index
        )

        progress = trace["strategy_progress"][slot_index]
        _assert_progress(progress, slot_index + 1)
        batch = strategy.snapshots[slot_index]
        assert batch.batch_complete
        assert batch.close_time == tuple(events[targets[0]])[slot_index]["bucket_end"]
        latest_available = max(events[asset][slot_index]["available_at"] for asset in targets)
        assert batch.available_at == latest_available

        notifications = [
            row for row in trace["bar_notifications"] if row["sequence"] == slot_index + 1
        ]
        assert Counter(row["instrument"] for row in notifications) == Counter(targets)
        for notification in notifications:
            current_batch = notification["batch"]
            assert current_batch is not None and current_batch.status == "COMPLETE"
            assert current_batch.close_time == batch.close_time
            # Channel notifications happen after every feed line is written,
            # but before Cerebro advances any factor child for this slot.
            _assert_batch_written_progress(
                notification["progress"],
                feed_count=slot_index + 1,
                graph_count=slot_index,
            )

    assert Counter(row["instrument"] for row in trace["load_calls"]) == Counter(
        dict.fromkeys(targets, _BARS)
    )
    assert all(row["result"] is True for row in trace["load_calls"])
    assert all(row["slot_index"] is not None for row in trace["load_calls"])
    assert Counter(trace["next_calls"]) == Counter(dict.fromkeys(targets, _BARS))
    assert not any(trace["next_retries"].values())
    assert trace["check_calls"]
    for call in trace["check_calls"]:
        assert call["before"] == call["after"]

    factor = strategy.live_factor_set.factor_instances["alpha003"]["default"]
    assert factor._factor_call_count == _BARS
    assert all(
        factor.lifecycle_diagnostics["call_times"][index] == point.to_pydatetime()
        for index, point in enumerate(tuple(next(iter(frames.values())).index))
    )
    finite_outputs = sum(
        math.isfinite(float(output.value))
        for snapshot in strategy.snapshots
        for output in snapshot.factors["alpha003"].values.values()
    )
    assert finite_outputs > 0


@pytest.mark.integration
def test_alpha003_live_incomplete_finite_source_reaches_eof_without_half_batch():
    """Finite EOF rejects a half batch and stops without Feed or factor advance."""
    frames = _bounded_frames(3)
    targets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index[:_BARS])
    short_frames = {asset: frame.iloc[:_BARS].copy(deep=True) for asset, frame in frames.items()}
    calendar, member_ids = parity._calendar(targets, grid)
    clock = parity._ReplayClock(grid[0].to_pydatetime())
    events = {asset: parity._bar_events(short_frames, asset) for asset in targets}
    events[targets[-1]] = events[targets[-1]][:-1]
    cohort = LiveBarCohort(
        "alpha003-advancement-eof",
        calendar,
        max_pending_slots=1,
        max_window_bars=len(grid),
        wait_timeout_ns=5_000_000_000,
    )
    cerebro = bt.Cerebro(stdstats=False, exactbars=0, preload=False, runonce=False)
    feeds = {}
    for asset in targets:
        feed = bt.feeds.BtApiFeed(
            dataname=asset,
            historical_bars=(),
            live_bars=events[asset],
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            bar_watermark_ms=0,
            clock=clock,
        )
        feeds[asset] = feed
        cerebro.adddata(feed, name=asset)
    for asset in targets:
        cohort.register_member(
            member_ids[asset],
            feeds[asset],
            instrument=asset,
            source_ref="feed-%s" % asset,
            line_fields=_OHLCV_FIELDS,
            raw_fields=_OHLCV_FIELDS,
            numeric_fields=_OHLCV_FIELDS,
        )
    plan = parity._live_alpha003_plan(
        targets,
        calendar=calendar,
        mode="native",
        max_pending_slots=cohort.max_pending_slots,
        max_window_bars=len(grid),
        wait_timeout_ns=cohort.wait_timeout_ns,
        max_future_skew_seconds=1.0,
    )
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    trace = {"strategy": None, "stop_calls": 0, "bar_notifications": []}

    class _EofCapture(parity._LiveAlpha003Capture):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            trace["strategy"] = self

        def notify_bar(self, bar):
            trace["bar_notifications"].append(
                {
                    "instrument": bar.get("instrument"),
                    "sequence": bar.get("bar_sequence"),
                    "progress": _progress(self),
                    "batch": self.p.cohort.current_batch(),
                }
            )
            return super().notify_bar(bar)

        def stop(self):
            trace["stop_calls"] += 1
            return super().stop()

    cerebro.addstrategy(_EofCapture, cohort=cohort, plan=plan, target_order=targets)
    load_counts = Counter()
    check_states = []
    for asset, feed in feeds.items():
        original_load = feed._load

        def load_spy(_feed=feed, _original=original_load):
            load_counts[_feed._dataname] += 1
            return _original()

        feed._load = load_spy
        original_check = feed._check

        def check_spy(forcedata=None, _feed=feed, _original=original_check):
            before = _source_cursor(_feed)
            result = _original(forcedata=forcedata)
            after = _source_cursor(_feed)
            check_states.append((_feed._dataname, before, after))
            return result

        feed._check = check_spy

    strategies = cerebro.run()
    assert len(strategies) == 1
    strategy = strategies[0]
    trace["strategy"] = strategy
    assert trace["stop_calls"] == 1
    assert len(trace["bar_notifications"]) == (_BARS - 1) * len(targets)
    assert Counter(row["sequence"] for row in trace["bar_notifications"]) == Counter(
        {sequence: len(targets) for sequence in range(1, _BARS)}
    )
    for notification in trace["bar_notifications"]:
        assert notification["batch"].status == "COMPLETE"
        slot_index = notification["sequence"] - 1
        _assert_batch_written_progress(
            notification["progress"],
            feed_count=slot_index + 1,
            graph_count=slot_index,
        )
    assert len(strategy.snapshots) == _BARS - 1
    assert Counter(load_counts) == Counter(dict.fromkeys(targets, _BARS - 1))
    assert all(len(feed) == _BARS - 1 for feed in feeds.values())
    assert cohort.frozen
    assert cohort.frozen_reason == "finite_source_exhausted_before_complete_batch"
    assert cohort.current_batch() is not None
    assert cohort.current_batch().slot_index == _BARS - 2
    assert cohort.current_batch().status == "COMPLETE"
    assert check_states
    assert all(before == after for _asset, before, after in check_states)
    factor = strategy.live_factor_set.factor_instances["alpha003"]["default"]
    assert factor._factor_call_count == _BARS - 1
    assert factor.lifecycle_diagnostics["call_count"] == _BARS - 1

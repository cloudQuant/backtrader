"""Alpha003 live cohort proof for qbuffer parity and readiness notifications.

The feed, cohort, LiveFactorSet, FactorIndicator graph and Cerebro lifecycle
are production objects. Only the source bars and replay clock are deterministic
test inputs. Expected factor values are checked by the existing independent
Alpha003 trace validator.
"""

from __future__ import annotations

import math
import struct

import backtrader as bt
import pytest

from backtrader.linebuffer import LineBuffer
from backtrader.research import operators
from backtrader.research.live import LiveFactorReadiness
from backtrader.research.live_cohort import LiveBarCohort
from tests.integration import test_live_alpha003_parity as parity


_ROWS = 1280
_SHORT_ROWS = 24
_TARGET_COUNT = 3
_FIELDS = parity._OHLCV_FIELDS
_WARMUP_BARS = parity._WARMUP_BARS


class _BufferAndReadinessCapture(parity._LiveAlpha003Capture):
    """Observe actual graph outputs from ordinary Strategy callbacks."""

    params = (("submit_on_live_ready", False),)

    def __init__(self):
        super().__init__()
        self.node_rows = []
        self.feed_lengths = []
        self.qbuffer_observation = None
        self.data_notifications = []
        self.buy_entries = []
        self.order_updates = []
        self.order = None

    def prenext(self):
        self._capture()

    def nextstart(self):
        self._capture()

    def next(self):
        self._capture()

    def _capture(self):
        super()._capture()
        factor = self.live_factor_set.factor_instances["alpha003"]["default"]
        row_index = len(self.snapshots) - 1
        self.feed_lengths.append(tuple(len(data) for data in self.datas))
        self.node_rows.append(_read_current_nodes(factor, self.target_order))

        if self.datas and self.datas[0].close.mode == LineBuffer.QBuffer:
            self.qbuffer_observation = _sample_qbuffers(
                self, factor, row_index=row_index, previous=self.qbuffer_observation
            )

        snapshot = self.snapshots[-1]
        if self.p.submit_on_live_ready and snapshot.readiness is LiveFactorReadiness.LIVE_READY:
            if self.order is None:
                self.order = self.buy(data=self.datas[0], size=1)

    def buy(self, *args, **kwargs):
        self.buy_entries.append(self.snapshots[-1])
        return super().buy(*args, **kwargs)

    def notify_data(self, data, status, *args, **kwargs):
        self.data_notifications.append(
            (data._name, data._getstatusname(status), len(self.snapshots))
        )
        return super().notify_data(data, status, *args, **kwargs)

    def notify_order(self, order):
        self.order_updates.append(order.getstatusname())


def _live_run(frames, *, mode, exactbars, submit_on_live_ready=False):
    targets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)
    calendar, member_ids = parity._calendar(targets, grid)
    window_bars = max(_WARMUP_BARS, len(grid))
    cohort = LiveBarCohort(
        "alpha003-live-buffer-%s-%d-%d" % (mode, exactbars, len(grid)),
        calendar,
        max_pending_slots=2,
        max_window_bars=window_bars,
        wait_timeout_ns=5_000_000_000,
    )
    clock = parity._ReplayClock(grid[0].to_pydatetime())
    cerebro = bt.Cerebro(
        stdstats=False,
        exactbars=exactbars,
        preload=False,
        runonce=False,
    )

    feeds = {}
    for target in targets:
        feed = bt.feeds.BtApiFeed(
            dataname=target,
            historical_bars=(),
            live_bars=parity._bar_events(frames, target),
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            bar_watermark_ms=0,
            clock=clock,
        )
        feeds[target] = feed
        cerebro.adddata(feed, name=target)

    for target in targets:
        cohort.register_member(
            member_ids[target],
            feeds[target],
            instrument=target,
            source_ref="alpha003-live-buffer-fixture:%s" % target,
            line_fields=_FIELDS,
            raw_fields=_FIELDS,
            numeric_fields=_FIELDS,
        )

    plan = parity._live_alpha003_plan(
        targets,
        calendar=calendar,
        mode=mode,
        max_pending_slots=cohort.max_pending_slots,
        max_window_bars=window_bars,
        wait_timeout_ns=cohort.wait_timeout_ns,
        max_future_skew_seconds=5.0,
    )
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(
        _BufferAndReadinessCapture,
        cohort=cohort,
        plan=plan,
        target_order=targets,
        submit_on_live_ready=submit_on_live_ready,
    )
    strategy = cerebro.run()[0]
    return strategy, cohort, feeds, cerebro, plan


def _value_reason(series):
    return float(series.value[0]), float(series.reason[0])


def _read_current_nodes(factor, targets):
    row = {}
    data_by_name = {data._name: data for data in factor.target_datas}
    for name, node in factor._nodes.items():
        if isinstance(node, operators._PanelOperator):
            row[name] = {
                target: _value_reason(node.outputs[data_by_name[target]]) for target in targets
            }
        else:
            row[name] = _value_reason(node.lines)
    return row


def _tracked_lines(strategy, factor):
    lines = {}

    def add(label, line):
        if line is None:
            return
        previous = lines.get(id(line))
        if previous is not None:
            if previous[0] is not line:
                raise AssertionError("line identity was reused during one live run")
            return
        lines[id(line)] = (line, label)

    def add_series(label, series):
        line_map = getattr(series, "_lines", None)
        if callable(getattr(line_map, "items", None)):
            for alias, line in line_map.items():
                add("%s.%s" % (label, alias), line)
            return

        aliases = series.getlinealiases()
        for alias, line in zip(aliases, series.lines):
            add("%s.%s" % (label, alias), line)

    for data in strategy.datas:
        for alias, line in zip(data.getlinealiases(), data.lines.lines):
            add("feed:%s:%s" % (data._name, alias), line)

    for alias, source_lines in factor._field_line_cache.items():
        for index, line in enumerate(source_lines):
            add("input:%s:%d" % (alias, index), line)

    for name, node in factor._nodes.items():
        if isinstance(node, operators._PanelOperator):
            for target, output in node.outputs.items():
                add_series("node:%s:%s" % (name, target._name), output)
        else:
            add_series("node:%s" % name, node.lines)

    for index, node in enumerate(getattr(factor, "_physical_nodes", ())):
        if isinstance(node, operators._PanelOperator):
            for target, output in node.outputs.items():
                add_series("physical:%d:%s" % (index, target._name), output)
        else:
            add_series("physical:%d" % index, node.lines)

    for target, output in factor.outputs.items():
        add_series("factor:%s" % target._name, output)

    return lines


def _sample_qbuffers(strategy, factor, *, row_index, previous):
    if previous is None:
        lines = _tracked_lines(strategy, factor)
        if not lines:
            raise AssertionError("the live Alpha003 graph exposed no lines to sample")
        states = {}
        for identity, (line, label) in lines.items():
            if line.mode != LineBuffer.QBuffer:
                raise AssertionError("exactbars=1 did not qbuffer %s" % label)
            configured = int(line.maxlen)
            if configured < 1:
                raise AssertionError("QBuffer has invalid configured maxlen: %s" % label)
            states[identity] = {
                "line": line,
                "label": label,
                "configured": configured,
                "retained_highwater": 0,
                "samples": 0,
            }
        previous = {"lines": states, "callbacks": 0}

    assert previous["lines"]
    for state in previous["lines"].values():
        line = state["line"]
        if line.mode != LineBuffer.QBuffer or int(line.maxlen) != state["configured"]:
            raise AssertionError("QBuffer mode or maxlen changed for %s" % state["label"])
        logical = int(len(line))
        retained = int(line.buflen())
        expected_retained = min(row_index + 1, state["configured"])
        if logical != row_index + 1:
            raise AssertionError(
                "%s advanced %d logical rows at callback %d"
                % (state["label"], logical, row_index + 1)
            )
        if retained != expected_retained:
            raise AssertionError(
                "%s retained %d rows, expected %d at callback %d"
                % (state["label"], retained, expected_retained, row_index + 1)
            )
        state["retained_highwater"] = max(state["retained_highwater"], retained)
        state["samples"] += 1
    previous["callbacks"] += 1
    return previous


def _float_equal(left, right):
    left, right = float(left), float(right)
    if math.isnan(left):
        return math.isnan(right)
    return struct.pack("=d", left) == struct.pack("=d", right)


def _full_node_trace(factor, targets, rows):
    result = {}
    for name, node in factor._nodes.items():
        if isinstance(node, operators._PanelOperator):
            result[name] = {}
            for target in targets:
                feed = next(data for data in factor.target_datas if data._name == target)
                values, reasons = parity._actual_node_arrays(node, feed, panel=True)
                if len(values) != rows or len(reasons) != rows:
                    raise AssertionError(
                        "full node trace has the wrong length: %s/%s" % (name, target)
                    )
                result[name][target] = tuple(zip(values, reasons))
        else:
            values, reasons = parity._actual_node_arrays(node, None, panel=False)
            if len(values) != rows or len(reasons) != rows:
                raise AssertionError("full node trace has the wrong length: %s" % name)
            result[name] = tuple(zip(values, reasons))
    return result


def _captured_node_trace(strategy, targets):
    result = {}
    keys = set(strategy.node_rows[0]) if strategy.node_rows else set()
    for key in keys:
        first = strategy.node_rows[0][key]
        if isinstance(first, dict):
            result[key] = {
                target: tuple(row[key][target] for row in strategy.node_rows) for target in targets
            }
        else:
            result[key] = tuple(row[key] for row in strategy.node_rows)
    return result


def _first_finite_ready(trace):
    ready = float(operators.OperatorReason.READY)
    return next(
        (
            index
            for index, (value, reason) in enumerate(trace)
            if math.isfinite(float(value)) and float(reason) == ready
        ),
        None,
    )


def _compare_node_traces(full_factor, queued, targets, rows, *, mode):
    full = _full_node_trace(full_factor, targets, rows)
    captured = _captured_node_trace(queued, targets)
    assert set(full) == set(captured), (mode, sorted(set(full) ^ set(captured)))

    for name, full_outputs in full.items():
        if isinstance(full_outputs, dict):
            assert isinstance(captured[name], dict), (mode, name)
            assert set(full_outputs) == set(captured[name]), (mode, name)
            output_series = tuple((target, full_outputs[target]) for target in targets)
        else:
            assert not isinstance(captured[name], dict), (mode, name)
            output_series = ((name, full_outputs),)

        for output_name, expected in output_series:
            actual = (
                captured[name][output_name] if isinstance(full_outputs, dict) else captured[name]
            )
            assert len(actual) == len(expected) == rows, (mode, name, output_name)
            for index, (left, right) in enumerate(zip(expected, actual)):
                assert _float_equal(left[0], right[0]), (
                    mode,
                    name,
                    output_name,
                    index,
                    left[0],
                    right[0],
                )
                assert _float_equal(left[1], right[1]), (
                    mode,
                    name,
                    output_name,
                    index,
                    "reason",
                    left[1],
                    right[1],
                )

            first_full = _first_finite_ready(expected)
            first_queued = _first_finite_ready(actual)
            assert first_full is not None, (mode, name, output_name, "no finite full witness")
            assert first_queued == first_full, (mode, name, output_name, first_full, first_queued)
            distinct = {
                float(value).hex() for value, _reason in expected if math.isfinite(float(value))
            }
            assert len(distinct) > 1, (mode, name, output_name, "finite values do not vary")


def _compare_snapshots(full, queued, targets):
    assert len(full.snapshots) == len(queued.snapshots)
    for row_index, (left, right) in enumerate(zip(full.snapshots, queued.snapshots)):
        assert (
            left.close_time,
            left.available_at,
            left.batch_complete,
            left.readiness,
            left.readiness_reasons,
        ) == (
            right.close_time,
            right.available_at,
            right.batch_complete,
            right.readiness,
            right.readiness_reasons,
        ), row_index
        left_values = left.factors["alpha003"].values
        right_values = right.factors["alpha003"].values
        assert set(left_values) == set(right_values) == set(targets)
        for target in targets:
            before, after = left_values[target], right_values[target]
            assert (
                before.status,
                before.reason,
                before.present,
                before.complete,
                before.quality,
                before.source_role,
                before.member_id,
                before.sequence,
            ) == (
                after.status,
                after.reason,
                after.present,
                after.complete,
                after.quality,
                after.source_role,
                after.member_id,
                after.sequence,
            ), (
                row_index,
                target,
            )
            assert _float_equal(before.value, after.value), (row_index, target)


@pytest.mark.integration
@pytest.mark.parametrize("mode", ("native", "build"))
def test_live_alpha003_full_and_exactbars_qbuffer_match_after_ten_wraps(mode):
    """Compare every live Alpha003 node across full and real Cerebro QBuffers."""
    all_frames = parity._minute_frames(_ROWS)
    targets = tuple(all_frames)[:_TARGET_COUNT]
    frames = {target: all_frames[target] for target in targets}

    full, full_cohort, full_feeds, _full_cerebro, _full_plan = _live_run(
        frames,
        mode=mode,
        exactbars=0,
    )
    expected, full_factor = parity._validate_live(
        full,
        frames,
        label="Alpha003 live full buffer %s T%d" % (mode, _ROWS),
    )

    queued, queued_cohort, queued_feeds, _queued_cerebro, _queued_plan = _live_run(
        frames,
        mode=mode,
        exactbars=1,
    )
    assert len(full.snapshots) == len(queued.snapshots) == _ROWS
    assert full.factor_callback_times == queued.factor_callback_times
    assert tuple(full.factor_callback_times) == tuple(
        point.to_pydatetime() for point in next(iter(frames.values())).index
    )
    expected_lengths = [tuple([index + 1] * len(targets)) for index in range(_ROWS)]
    assert full.feed_lengths == queued.feed_lengths == expected_lengths
    assert len(full_cohort.gaps) == len(queued_cohort.gaps) == 0
    assert all(not cohort.frozen for cohort in (full_cohort, queued_cohort))
    assert all(
        len(feed) == _ROWS for feed in tuple(full_feeds.values()) + tuple(queued_feeds.values())
    )

    _compare_snapshots(full, queued, targets)
    _compare_node_traces(full_factor, queued, targets, _ROWS, mode=mode)
    queued_factor = queued.live_factor_set.factor_instances["alpha003"]["default"]
    assert tuple(queued_factor._nodes) == tuple(full_factor._nodes)

    capacity = queued.qbuffer_observation
    assert capacity is not None and capacity["callbacks"] == _ROWS
    actual_max = max(state["retained_highwater"] for state in capacity["lines"].values())
    assert actual_max >= 10
    assert max(1280, 10 * actual_max) <= _ROWS, (
        mode,
        _ROWS,
        actual_max,
    )
    assert all(state["samples"] == _ROWS for state in capacity["lines"].values())

    finite = [
        float(output.value)
        for snapshot in queued.snapshots
        for output in snapshot.factors["alpha003"].values.values()
        if math.isfinite(float(output.value))
    ]
    assert finite and len({value.hex() for value in finite}) > 1
    assert sum(math.isfinite(float(value)) for row in expected for value in row) >= 100
    first_available = next(
        index
        for index, snapshot in enumerate(queued.snapshots)
        if all(
            output.status.value == "OUTPUT_AVAILABLE"
            for output in snapshot.factors["alpha003"].values.values()
        )
    )
    assert first_available == 9
    assert all(
        snapshot.readiness is LiveFactorReadiness.LIVE_READY
        for snapshot in queued.snapshots[_WARMUP_BARS - 1 :]
    )


@pytest.mark.integration
@pytest.mark.parametrize("mode", ("native", "build"))
def test_early_live_notifications_do_not_unlock_short_finite_alpha003_source(mode):
    """A LIVE feed status cannot replace the thirty-grid warmup requirement."""
    all_frames = parity._minute_frames(320)
    targets = tuple(all_frames)[:_TARGET_COUNT]
    frames = {target: all_frames[target].iloc[:_SHORT_ROWS].copy(deep=True) for target in targets}
    strategy, cohort, feeds, cerebro, plan = _live_run(
        frames,
        mode=mode,
        exactbars=0,
        submit_on_live_ready=True,
    )

    assert plan.warmup_min_bars == _WARMUP_BARS == 30
    assert len(strategy.snapshots) == _SHORT_ROWS
    assert all(len(feed) == _SHORT_ROWS for feed in feeds.values())
    assert all(snapshot.batch_complete for snapshot in strategy.snapshots)
    assert [snapshot.close_time for snapshot in strategy.snapshots] == [
        point.to_pydatetime() for point in next(iter(frames.values())).index
    ]
    assert all(snapshot.epoch_id == 1 for snapshot in strategy.snapshots)
    batch_ids = [snapshot.batch_id for snapshot in strategy.snapshots]
    assert all(batch_id is not None for batch_id in batch_ids)
    assert len(set(batch_ids)) == _SHORT_ROWS
    assert not cohort.frozen and len(cohort.gaps) == 0

    live_notifications = [
        (feed_name, rows_seen)
        for feed_name, status_name, rows_seen in strategy.data_notifications
        if status_name == "LIVE"
    ]
    assert {feed_name for feed_name, _rows_seen in live_notifications} == set(targets)
    assert all(rows_seen < 9 for _feed_name, rows_seen in live_notifications), live_notifications

    assert all(snapshot.readiness is LiveFactorReadiness.WARMUP for snapshot in strategy.snapshots)
    assert all(
        "input_window_incomplete_or_warmup_short" in snapshot.readiness_reasons
        for snapshot in strategy.snapshots
    )
    final = strategy.snapshots[-1]
    assert final.batch_complete
    assert final.close_time == next(iter(frames.values())).index[-1].to_pydatetime()
    assert all(
        output.status.value == "OUTPUT_AVAILABLE" and math.isfinite(float(output.value))
        for output in final.factors["alpha003"].values.values()
    ), "the graph may have values, but cohort readiness is still below its declared warmup"

    assert strategy.buy_entries == []
    assert strategy.order is None
    assert strategy.order_updates == []
    assert cerebro.broker.orders == []

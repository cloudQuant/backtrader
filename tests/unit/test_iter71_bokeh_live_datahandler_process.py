"""Semantic and performance-path regressions for live Bokeh data processing."""

from datetime import datetime, timedelta
from threading import Barrier, Event, Lock, Thread, get_ident

import numpy as np
import pandas as pd
import pytest

from backtrader.bokeh.live.datahandler import LiveDataHandler, UpdateType


def _frame(indexes, datetimes, closes):
    return pd.DataFrame(
        {
            "index": indexes,
            "datetime": datetimes,
            "close": closes,
            "volume": [100 + value for value in closes],
        },
        index=pd.Index(indexes),
    )


class _BarrierFrame(pd.DataFrame):
    _metadata = ["_entered_rows", "_resume_rows", "_pause_before_first_row"]

    @property
    def _constructor(self):
        return _BarrierFrame

    def iterrows(self):
        if self._pause_before_first_row:
            self._pause_before_first_row = False
            self._entered_rows.wait(timeout=5)
            if not self._resume_rows.wait(timeout=5):
                raise TimeoutError("test did not release the row iterator")
        yield from super().iterrows()


def _barrier_frame(frame, entered_rows, resume_rows):
    rows = _BarrierFrame(frame)
    rows._entered_rows = entered_rows
    rows._resume_rows = resume_rows
    rows._pause_before_first_row = True
    return rows


def _make_handler(datastore, lookback):
    handler = LiveDataHandler.__new__(LiveDataHandler)
    handler._datastore = datastore.copy()
    handler._lookback = lookback
    handler._lock = Lock()
    handler._patches = []
    handler.push_events = []
    handler._push_adds = lambda: handler.push_events.append("add")
    handler._push_patches = lambda: handler.push_events.append("patch")
    return handler


def _legacy_process(handler, rows):
    """Reference the pre-optimization per-row membership/loc behavior."""
    for idx, row in rows.iterrows():
        if (
            handler._datastore is not None
            and handler._datastore.shape[0] > 0
            and "index" in handler._datastore.columns
            and idx in handler._datastore["index"].values
        ):
            update_type = UpdateType.UPDATE
        else:
            update_type = UpdateType.ADD

        if update_type == UpdateType.UPDATE:
            ds_idx = handler._datastore.loc[
                handler._datastore["index"] == idx
            ].index[0]
            handler._set_data(row, ds_idx)
            handler._patches.append(row)
            handler._push_patches()
        else:
            handler._set_data(row)
            handler._push_adds()


def _assert_same_result(actual, expected):
    pd.testing.assert_frame_equal(actual._datastore, expected._datastore)
    assert actual.push_events == expected.push_events
    assert len(actual._patches) == len(expected._patches)
    for actual_patch, expected_patch in zip(actual._patches, expected._patches):
        pd.testing.assert_series_equal(actual_patch, expected_patch)


def test_process_preserves_update_add_order_timestamps_and_tail_eviction():
    day0 = datetime(2024, 1, 1)
    day1 = day0 + timedelta(days=1)
    day2 = day0 + timedelta(days=2)
    initial = _frame(
        [8, 9, 10, 11],
        [day0, day0, day1, day2],
        [80.0, 90.0, 100.0, 110.0],
    )
    rows = _frame(
        [10, 12, 13, 11, 9],
        [day1, day2, day2, day2, day0],
        [1000.0, 120.0, 130.0, 1100.0, 90.0],
    )

    actual = _make_handler(initial, lookback=4)
    expected = _make_handler(initial, lookback=4)

    actual._process(rows)
    _legacy_process(expected, rows)

    _assert_same_result(actual, expected)
    assert actual.push_events == ["patch", "add", "add", "patch", "add"]
    assert actual._datastore["index"].tolist() == [11, 12, 13, 9]
    assert actual._datastore["datetime"].tolist() == [day2, day2, day2, day0]
    assert actual._datastore["close"].tolist() == [1100.0, 120.0, 130.0, 90.0]


def test_process_monotonic_new_batch_keeps_one_add_push_per_row():
    timestamp = datetime(2024, 1, 1)
    initial = _frame([0, 1, 2], [timestamp] * 3, [10.0, 20.0, 30.0])
    rows = _frame([3, 4, 5], [timestamp] * 3, [40.0, 50.0, 60.0])

    actual = _make_handler(initial, lookback=3)
    expected = _make_handler(initial, lookback=3)

    actual._process(rows)
    _legacy_process(expected, rows)

    _assert_same_result(actual, expected)
    assert actual.push_events == ["add", "add", "add"]
    assert actual._datastore["index"].tolist() == [3, 4, 5]
    assert actual._datastore["datetime"].tolist() == [timestamp] * 3


def test_process_rechecks_same_size_replacement_after_lookup_preparation():
    timestamp = datetime(2024, 1, 1)
    initial = _frame([0, 1, 2], [timestamp] * 3, [10.0, 20.0, 30.0])
    replacement = _frame([10, 11, 12], [timestamp] * 3, [100.0, 110.0, 120.0])
    entered_rows = Barrier(2)
    resume_rows = Event()

    rows = _BarrierFrame(
        {
            "index": [1],
            "datetime": [timestamp],
            "close": [999.0],
            "volume": [1099.0],
        },
        index=pd.Index([1]),
    )
    rows._entered_rows = entered_rows
    rows._resume_rows = resume_rows
    rows._pause_before_first_row = True

    actual = _make_handler(initial, lookback=3)
    expected = _make_handler(initial, lookback=3)
    errors = []

    def process_actual():
        try:
            actual._process(rows)
        except BaseException as exc:  # surface worker failures in the test thread
            errors.append(exc)

    worker = Thread(target=process_actual)
    worker.start()
    try:
        entered_rows.wait(timeout=5)
        actual.set(replacement.copy())
        expected.set(replacement.copy())
    finally:
        resume_rows.set()
        worker.join(timeout=5)

    assert not worker.is_alive(), "data processing worker did not finish"
    assert errors == []
    _legacy_process(expected, rows)

    _assert_same_result(actual, expected)
    assert actual.push_events == ["add", "add"]
    assert actual._datastore["index"].tolist() == [11, 12, 1]


@pytest.mark.parametrize("replace_after_first_add", [False, True])
def test_process_all_add_batch_rechecks_replacement_around_first_row(
    replace_after_first_add,
):
    timestamp = datetime(2024, 1, 1)
    initial = _frame([0, 1, 2], [timestamp] * 3, [10.0, 20.0, 30.0])
    rows = _frame([3, 4], [timestamp] * 2, [40.0, 50.0])
    if not replace_after_first_add:
        rows = _barrier_frame(rows, Barrier(2), Event())
    replacement_ids = [10, 4, 12] if replace_after_first_add else [10, 3, 12]
    replacement = _frame(
        replacement_ids,
        [timestamp] * 3,
        [100.0, 110.0, 120.0],
    )
    entered_rows = rows._entered_rows if not replace_after_first_add else Barrier(2)
    resume_rows = rows._resume_rows if not replace_after_first_add else Event()

    actual = _make_handler(initial, lookback=3)
    expected = _make_handler(initial, lookback=3)
    worker_ident = []
    paused_after_add = []

    def push_adds():
        actual.push_events.append("add")
        if (
            replace_after_first_add
            and worker_ident
            and get_ident() == worker_ident[0]
            and not paused_after_add
        ):
            paused_after_add.append(True)
            entered_rows.wait(timeout=5)
            if not resume_rows.wait(timeout=5):
                raise TimeoutError("test did not release the add callback")

    actual._push_adds = push_adds
    errors = []

    def process_actual():
        worker_ident.append(get_ident())
        try:
            actual._process(rows)
        except BaseException as exc:  # surface worker failures in the test thread
            errors.append(exc)

    worker = Thread(target=process_actual)
    worker.start()
    try:
        entered_rows.wait(timeout=5)
        if replace_after_first_add:
            _legacy_process(expected, rows.iloc[:1])
            expected.set(replacement.copy())
        else:
            expected.set(replacement.copy())
        actual.set(replacement.copy())
    finally:
        resume_rows.set()
        worker.join(timeout=5)

    assert not worker.is_alive(), "data processing worker did not finish"
    assert errors == []
    if replace_after_first_add:
        _legacy_process(expected, rows.iloc[1:])
        assert actual.push_events == ["add", "add", "patch"]
    else:
        _legacy_process(expected, rows)
        assert actual.push_events == ["add", "patch", "add"]

    _assert_same_result(actual, expected)


def test_process_falls_back_when_caller_mutates_set_dataframe_alias():
    timestamp = datetime(2024, 1, 1)
    source = _frame([0, 1, 2], [timestamp] * 3, [10.0, 20.0, 30.0])
    expected_source = source.copy()
    entered_rows = Barrier(2)
    resume_rows = Event()
    rows = _barrier_frame(
        _frame([1], [timestamp], [999.0]), entered_rows, resume_rows
    )

    actual = _make_handler(_frame([], [], []), lookback=3)
    expected = _make_handler(_frame([], [], []), lookback=3)
    actual.set(source)
    expected.set(expected_source)
    assert np.shares_memory(
        actual._datastore["index"].to_numpy(copy=False),
        source["index"].to_numpy(copy=False),
    )
    errors = []

    def process_actual():
        try:
            actual._process(rows)
        except BaseException as exc:  # surface worker failures in the test thread
            errors.append(exc)

    worker = Thread(target=process_actual)
    worker.start()
    try:
        entered_rows.wait(timeout=5)
        source.loc[1, "index"] = 10
        expected_source.loc[1, "index"] = 10
        assert actual._datastore["index"].iloc[1] == 10
    finally:
        resume_rows.set()
        worker.join(timeout=5)

    assert not worker.is_alive(), "data processing worker did not finish"
    assert errors == []
    _legacy_process(expected, rows)

    _assert_same_result(actual, expected)
    assert actual.push_events == ["add", "add"]
    assert actual._datastore["index"].tolist() == [10, 2, 1]
    assert actual._datastore_may_be_aliased is False
    source.loc[2, "index"] = 20
    assert actual._datastore["index"].tolist() == [10, 2, 1]


def test_process_takes_alias_flag_and_store_snapshot_atomically():
    timestamp = datetime(2024, 1, 1)
    source = _frame([0, 1, 2], [timestamp] * 3, [10.0, 20.0, 30.0])
    expected_source = source.copy()
    taint_snapshot_barrier = Barrier(2)
    resume_snapshot = Event()
    row_barrier = Barrier(2)
    resume_rows = Event()
    rows = _barrier_frame(
        _frame([1], [timestamp], [999.0]), row_barrier, resume_rows
    )

    actual = _make_handler(_frame([5, 6, 7], [timestamp] * 3, [5.0, 6.0, 7.0]), 3)
    expected = _make_handler(
        _frame([5, 6, 7], [timestamp] * 3, [5.0, 6.0, 7.0]), 3
    )
    key_calls = []
    original_key = actual._integer_index_key

    def pause_after_alias_check(value):
        if not key_calls:
            key_calls.append(True)
            taint_snapshot_barrier.wait(timeout=5)
            if not resume_snapshot.wait(timeout=5):
                raise TimeoutError("test did not release the initial snapshot")
        return original_key(value)

    # The first key conversion follows the alias check and precedes the old
    # implementation's datastore snapshot, making the false -> set -> snapshot
    # race deterministic.
    actual._integer_index_key = pause_after_alias_check
    errors = []

    def process_actual():
        try:
            actual._process(rows)
        except BaseException as exc:  # surface worker failures in the test thread
            errors.append(exc)

    worker = Thread(target=process_actual)
    worker.start()
    try:
        taint_snapshot_barrier.wait(timeout=5)
        actual.set(source)
        expected.set(expected_source)
        assert np.shares_memory(
            actual._datastore["index"].to_numpy(copy=False),
            source["index"].to_numpy(copy=False),
        )
        resume_snapshot.set()

        row_barrier.wait(timeout=5)
        source.loc[1, "index"] = 10
        expected_source.loc[1, "index"] = 10
    finally:
        resume_snapshot.set()
        resume_rows.set()
        worker.join(timeout=5)

    assert not worker.is_alive(), "data processing worker did not finish"
    assert errors == []
    _legacy_process(expected, rows)

    _assert_same_result(actual, expected)
    assert actual.push_events == ["add", "add"]
    assert actual._datastore["index"].tolist() == [10, 2, 1]


def test_process_does_not_coerce_identity_only_index_objects_to_integer_keys():
    timestamp = datetime(2024, 1, 1)

    class _IndexLike:
        def __index__(self):
            return 1

    old_id = _IndexLike()
    incoming_id = _IndexLike()
    assert old_id is not incoming_id
    assert old_id != incoming_id

    initial = _frame([old_id], [timestamp], [10.0])
    rows = _frame([incoming_id], [timestamp], [20.0])
    assert initial["index"].dtype == object
    assert rows.index.dtype == object

    actual = _make_handler(initial, lookback=3)
    expected = _make_handler(initial, lookback=3)

    actual._process(rows)
    _legacy_process(expected, rows)

    _assert_same_result(actual, expected)
    assert actual.push_events == ["add"]
    assert len(actual._datastore) == 2
    assert actual._datastore["index"].iloc[0] is old_id
    assert actual._datastore["index"].iloc[1] is incoming_id


def test_process_duplicate_input_labels_use_legacy_update_semantics():
    day0 = datetime(2024, 1, 1)
    initial = _frame([0, 1, 2], [day0, day0, day0], [10.0, 20.0, 30.0])
    rows = pd.DataFrame(
        {
            "index": [3, 3],
            "datetime": [day0, day0],
            "close": [40.0, 41.0],
            "volume": [140.0, 141.0],
        },
        index=pd.Index([3, 3]),
    )

    actual = _make_handler(initial, lookback=5)
    expected = _make_handler(initial, lookback=5)

    actual._process(rows)
    _legacy_process(expected, rows)

    _assert_same_result(actual, expected)
    assert actual.push_events == ["add", "patch"]
    assert actual._datastore["close"].tolist() == [10.0, 20.0, 30.0, 41.0]


def test_process_duplicate_store_labels_keep_legacy_pandas_error():
    day0 = datetime(2024, 1, 1)
    initial = pd.DataFrame(
        {
            "index": [0, 0, 1],
            "datetime": [day0, day0, day0],
            "close": [10.0, 11.0, 12.0],
            "volume": [100.0, 110.0, 120.0],
        },
        index=pd.Index([0, 0, 1]),
    )
    rows = _frame([0], [day0], [99.0])

    actual = _make_handler(initial, lookback=5)
    expected = _make_handler(initial, lookback=5)

    with pytest.raises(ValueError) as actual_error:
        actual._process(rows)
    with pytest.raises(ValueError) as expected_error:
        _legacy_process(expected, rows)

    assert str(actual_error.value) == str(expected_error.value)
    _assert_same_result(actual, expected)
    assert actual.push_events == []


def test_process_oversized_initial_store_keeps_per_update_tail_semantics():
    day0 = datetime(2024, 1, 1)
    initial = _frame([0, 1, 2, 3], [day0] * 4, [0.0, 1.0, 2.0, 3.0])
    rows = _frame([0, 3], [day0, day0], [10.0, 30.0])

    actual = _make_handler(initial, lookback=2)
    expected = _make_handler(initial, lookback=2)

    actual._process(rows)
    _legacy_process(expected, rows)

    _assert_same_result(actual, expected)
    assert actual.push_events == ["patch", "patch"]
    assert actual._datastore["index"].tolist() == [2, 3]
    assert actual._datastore["close"].tolist() == [2.0, 30.0]

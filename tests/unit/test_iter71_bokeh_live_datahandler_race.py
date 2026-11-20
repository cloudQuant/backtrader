"""Deterministic worker/IOLoop race regressions for LiveDataHandler."""

from datetime import datetime
from threading import Event, Lock, Thread, get_ident

import pandas as pd

from backtrader.bokeh.live.datahandler import LiveDataHandler


class _ObservedLock:
    """Record whether the worker meets the handler lock during a callback read."""

    def __init__(self):
        self._lock = Lock()
        self.writer_thread_id = None
        self.writer_attempted = Event()
        self.writer_was_blocked = None

    def __enter__(self):
        if get_ident() == self.writer_thread_id:
            acquired = self._lock.acquire(blocking=False)
            self.writer_was_blocked = not acquired
            self.writer_attempted.set()
            if not acquired:
                self._lock.acquire()
        else:
            self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._lock.release()


class _BlockingSelectionFrame(pd.DataFrame):
    _metadata = ["selection_entered", "resume_selection", "block_selection"]

    @property
    def _constructor(self):
        return _BlockingSelectionFrame

    def __getitem__(self, key):
        if (
            self.block_selection
            and isinstance(key, pd.Series)
            and pd.api.types.is_bool_dtype(key.dtype)
        ):
            self.block_selection = False
            self.selection_entered.set()
            if not self.resume_selection.wait(5):
                raise TimeoutError("test did not release the IOLoop data snapshot")
        return super().__getitem__(key)


class _RecordingColumnDataSource:
    def __init__(self):
        self.streamed = []

    def stream(self, data, rollover):
        self.streamed.append((data, rollover))


class _RecordingFigurePage:
    def __init__(self):
        self.cds = _RecordingColumnDataSource()
        self.figures = []

    @staticmethod
    def get_cds_streamdata_from_df(frame):
        return {column: frame[column].tolist() for column in frame.columns}


def _make_handler(frame):
    handler = LiveDataHandler.__new__(LiveDataHandler)
    handler._datastore = frame
    handler._lookback = 5
    handler._last_idx = 0
    handler._lock = _ObservedLock()
    handler._figurepage = _RecordingFigurePage()
    return handler


def test_add_callback_snapshots_under_lock_before_worker_mutates_datastore():
    """The IOLoop must not read a row while the worker replaces its values."""
    entered = Event()
    resume = Event()
    frame = _BlockingSelectionFrame(
        {
            "index": [2],
            "datetime": [datetime(2024, 1, 1)],
            "close": [10.0],
        },
        index=pd.Index([2]),
    )
    frame.selection_entered = entered
    frame.resume_selection = resume
    frame.block_selection = True
    handler = _make_handler(frame)
    callback_errors = []
    writer_errors = []
    writer_done = Event()

    def run_callback():
        try:
            handler._cb_push_adds()
        except BaseException as exc:  # surface thread failures in the test thread
            callback_errors.append(exc)

    def update_row():
        handler._lock.writer_thread_id = get_ident()
        try:
            handler._set_data(
                pd.Series(
                    {
                        "index": 2,
                        "datetime": datetime(2024, 1, 1),
                        "close": 99.0,
                    },
                    name=2,
                ),
                idx=2,
            )
        except BaseException as exc:  # surface thread failures in the test thread
            writer_errors.append(exc)
        finally:
            writer_done.set()

    callback = Thread(target=run_callback, daemon=True)
    callback.start()
    writer = None
    try:
        assert entered.wait(1), "callback did not reach its DataFrame selection"
        writer = Thread(target=update_row, daemon=True)
        writer.start()
        assert handler._lock.writer_attempted.wait(1), "worker did not attempt the handler lock"
        assert handler._lock.writer_was_blocked is True
        assert not writer_done.is_set()
    finally:
        resume.set()
        callback.join(2)
        if writer is not None:
            writer.join(2)

    assert not callback.is_alive()
    assert writer is not None and not writer.is_alive()
    assert callback_errors == []
    assert writer_errors == []
    assert writer_done.is_set()
    assert handler._datastore.loc[2, "close"] == 99.0
    assert len(handler._figurepage.cds.streamed) == 1
    streamed, rollover = handler._figurepage.cds.streamed[0]
    assert streamed["index"] == [2]
    assert streamed["close"] == [10.0]
    assert rollover == 1

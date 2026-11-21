#!/usr/bin/env python
"""
Live data handler.

Handles real-time data updates and pushes.
"""

import importlib.util
import numbers
import operator
import time
from collections import deque
from enum import Enum
from itertools import chain
from threading import Lock, Thread
from typing import Deque

from backtrader.utils.log_message import get_logger

TORNADO_AVAILABLE = importlib.util.find_spec("tornado") is not None

try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

_logger = get_logger(__name__)


class UpdateType(Enum):
    """Data update type."""

    ADD = 1  # Add new data
    UPDATE = 2  # Update existing data


class LiveDataHandler:
    """Live data handler.

    Responsible for receiving, storing and pushing real-time data.

    Attributes:
        _doc: Bokeh document
        _app: BacktraderBokeh application
        _figid: Figure page ID
        _lookback: Historical data retention
        _fill_gaps: Whether to fill data gaps
    """

    def __init__(self, doc, app, figid, lookback, fill_gaps=True, timeout=1):
        """Initialize data handler.

        Args:
            doc: Bokeh document
            app: BacktraderBokeh application
            figid: Figure page ID
            lookback: Historical data retention
            fill_gaps: Whether to fill data gaps
            timeout: Thread timeout
        """
        self._doc = doc
        self._app = app
        self._figid = figid
        self._lookback = lookback
        self._fill_gaps = fill_gaps
        self._timeout = timeout

        # Get figurepage
        self._figurepage = app.get_figurepage(figid)

        # Thread related
        self._thread = Thread(target=self._t_thread, daemon=True)
        self._lock = Lock()
        self._running = True
        self._new_data = False

        # Data storage
        self._datastore = None
        self._datastore_may_be_aliased = False
        self._last_idx = -1
        self._patches = []

        # Callbacks
        self._cb_patch = None
        self._cb_add = None

        # Initial data fill
        self._fill()

        # Start thread
        self._thread.start()

    def _fill(self):
        """Fill initial data."""
        if not PANDAS_AVAILABLE:
            return

        df = self._app.generate_data(
            figid=self._figid, back=self._lookback, preserveidx=True, fill_gaps=self._fill_gaps
        )

        self._set_data(df)
        # generate_data returns a fresh private frame that is not retained by
        # the caller after _fill returns, so this initial store has no external
        # mutable alias.
        self._datastore_may_be_aliased = False

        # Initialize CDS columns
        if self._figurepage is not None and hasattr(self._figurepage, "set_cds_columns_from_df"):
            self._figurepage.set_cds_columns_from_df(self._datastore)

    def _set_data(self, data, idx=None):
        """Set or append data.

        Args:
            data: DataFrame or Series
            idx: Index (for updating specific row)
        """
        if not PANDAS_AVAILABLE:
            return

        with self._lock:
            self._set_data_locked(data, idx)

    def _set_data_locked(self, data, idx=None):
        """Set data when the caller already holds ``_lock``."""
        if not PANDAS_AVAILABLE:
            return

        if isinstance(data, pd.DataFrame):
            self._datastore = data
            # DataFrame.tail may return a view. The public set(df) caller can
            # therefore mutate the index column without changing this object's
            # identity, so _process must keep legacy per-row classification.
            self._datastore_may_be_aliased = True
            self._last_idx = -1
        elif isinstance(data, pd.Series):
            if idx is None:
                self._datastore = pd.concat([self._datastore, data.to_frame().T])
                # concat creates a new frame and severs any alias introduced by
                # set(DataFrame), matching pandas' observable behavior.
                self._datastore_may_be_aliased = False
            else:
                self._datastore.loc[idx] = data
        else:
            _logger.warning(f"Unsupported data type: {type(data)}")
            return

        # Keep data length within lookback range
        if self._datastore is not None:
            self._datastore = self._datastore.tail(self._get_data_stream_length_locked())

    def _cb_push_adds(self):
        """Push new data to ColumnDataSources."""
        # The worker may append or patch rows while this IOLoop callback runs.
        # Select the pending rows and advance the high-water mark together;
        # boolean selection copies only the rows being pushed, so the lock is
        # released before any Bokeh model or user callback is invoked.
        with self._lock:
            datastore = self._datastore
            if datastore is None or "index" not in datastore.columns:
                return

            update_df = datastore[datastore["index"] > self._last_idx]
            if update_df.shape[0] == 0:
                return

            self._last_idx = update_df["index"].iloc[-1]
            stream_length = self._get_data_stream_length_locked()

        fp = self._figurepage
        if fp is None:
            return

        # Push to figurepage
        if hasattr(fp, "get_cds_streamdata_from_df") and hasattr(fp, "cds"):
            data = fp.get_cds_streamdata_from_df(update_df)
            if data:
                _logger.debug("Streaming data to figurepage: %s columns", len(data))
                fp.cds.stream(data, stream_length)

        # Push to each figure
        if hasattr(fp, "figures"):
            for f in fp.figures:
                if hasattr(f, "get_cds_streamdata_from_df") and hasattr(f, "cds"):
                    data = f.get_cds_streamdata_from_df(update_df)
                    if data:
                        f.cds.stream(data, stream_length)

    def _cb_push_patches(self):
        """Push patch data to ColumnDataSources."""
        patches = []
        while len(self._patches) > 0:
            patches.append(self._patches.pop(0))

        if len(patches) == 0:
            return

        fp = self._figurepage
        if fp is None:
            return

        for patch in patches:
            # Patch figurepage
            if hasattr(fp, "get_cds_patchdata_from_series") and hasattr(fp, "cds"):
                p_data, s_data = fp.get_cds_patchdata_from_series(patch)
                if len(p_data) > 0:
                    _logger.debug("Patching figurepage: %s fields", len(p_data))
                    fp.cds.patch(p_data)
                if len(s_data) > 0:
                    fp.cds.stream(s_data, self._get_data_stream_length())

            # Patch all figures
            if hasattr(fp, "figures"):
                for f in fp.figures:
                    if not hasattr(f, "get_cds_patchdata_from_series") or not hasattr(f, "cds"):
                        continue

                    # Determine whether to fill NaN
                    c_fill_nan = []
                    if not self._fill_gaps and hasattr(f, "fill_nan"):
                        c_fill_nan = f.fill_nan()

                    p_data, s_data = f.get_cds_patchdata_from_series(patch, c_fill_nan)
                    if len(p_data) > 0:
                        f.cds.patch(p_data)
                    if len(s_data) > 0:
                        f.cds.stream(s_data, self._get_data_stream_length())

    def _push_adds(self):
        """Trigger new data push."""
        if self._doc is None:
            return

        try:
            if self._cb_add is not None:
                self._doc.remove_next_tick_callback(self._cb_add)
        except ValueError:
            # Callback was already consumed/removed by Bokeh; nothing to undo.
            _logger.debug("datahandler:214 ignored ValueError")

        self._cb_add = self._doc.add_next_tick_callback(self._cb_push_adds)

    def _push_patches(self):
        """Trigger patch data push."""
        if self._doc is None:
            return

        try:
            if self._cb_patch is not None:
                self._doc.remove_next_tick_callback(self._cb_patch)
        except ValueError:
            # Callback was already consumed/removed by Bokeh; nothing to undo.
            _logger.debug("datahandler:228 ignored ValueError")

        self._cb_patch = self._doc.add_next_tick_callback(self._cb_push_patches)

    def _process(self, rows):
        """Process new data rows.

        Args:
            rows: DataFrame containing new data
        """
        if not PANDAS_AVAILABLE or rows is None:
            return

        if rows.empty:
            return

        # Read both fields under the same lock: set(DataFrame) replaces the
        # datastore and marks it externally aliased in one critical section.
        with self._lock:
            datastore = self._datastore
            datastore_may_be_aliased = getattr(
                self, "_datastore_may_be_aliased", False
            )

        if datastore_may_be_aliased:
            self._process_rows_slow(rows.iterrows())
            return

        # The Bokeh app emits an integer bar id both as the DataFrame index and
        # in its ``index`` column. Build the lookup once for that common shape;
        # unusual labels retain the original pandas membership/selection path
        # below so its equality and duplicate-label behavior remains intact.
        lookback = self._integer_index_key(self._lookback)
        if self._can_process_as_adds(rows, datastore, lookback):
            # Generated live batches are commonly a monotonic run of new bars.
            # Their ids are beyond the current high-water mark, so skip both
            # membership lookup and map construction while keeping one append
            # and one stream notification per row.
            expected_datastore = datastore
            row_iterator = iter(rows.iterrows())
            for idx, row in row_iterator:
                with self._lock:
                    if (
                        self._datastore is not expected_datastore
                        or getattr(self, "_datastore_may_be_aliased", False)
                    ):
                        store_changed = True
                    else:
                        self._set_data_locked(row)
                        expected_datastore = self._datastore
                        store_changed = False

                if store_changed:
                    self._process_rows_slow(chain(((idx, row),), row_iterator))
                    return

                self._push_adds()
            return

        if (
            lookback is None
            or lookback <= 0
            or datastore is None
            or "index" not in datastore.columns
            or "index" not in rows.columns
            or datastore.shape[0] > lookback
            or not pd.api.types.is_integer_dtype(datastore["index"].dtype)
            or not pd.api.types.is_integer_dtype(rows["index"].dtype)
            or not pd.api.types.is_integer_dtype(datastore.index.dtype)
            or not pd.api.types.is_integer_dtype(rows.index.dtype)
            or not datastore.index.is_unique
            or not rows.index.is_unique
        ):
            self._process_rows_slow(rows.iterrows())
            return

        index_to_label = {}
        row_ids: Deque[int] = deque()
        for label, value in zip(datastore.index, datastore["index"].array):
            label_key = self._integer_index_key(label)
            value_key = self._integer_index_key(value)
            if label_key is None or value_key is None or label_key != value_key:
                self._process_rows_slow(rows.iterrows())
                return
            if value_key in index_to_label:
                self._process_rows_slow(rows.iterrows())
                return
            index_to_label[value_key] = label
            row_ids.append(value_key)

        # A fast-path row must preserve the same bar-id/index-label identity as
        # generated Bokeh frames. This also rejects exotic equality/hash cases
        # before any row is applied, allowing the exact legacy path to handle
        # them without partial processing.
        for label, value in zip(rows.index, rows["index"].array):
            label_key = self._integer_index_key(label)
            value_key = self._integer_index_key(value)
            if label_key is None or value_key is None or label_key != value_key:
                self._process_rows_slow(rows.iterrows())
                return

        expected_datastore = datastore
        row_iterator = iter(rows.iterrows())
        for idx, row in row_iterator:
            with self._lock:
                if (
                    self._datastore is not expected_datastore
                    or getattr(self, "_datastore_may_be_aliased", False)
                ):
                    store_changed = True
                    size_mismatch = False
                    update_type = None
                else:
                    store_changed = False
                    idx_key = self._integer_index_key(idx)
                    if idx_key in index_to_label:
                        ds_idx = index_to_label[idx_key]
                        self._set_data_locked(row, ds_idx)
                        expected_datastore = self._datastore
                        update_type = UpdateType.UPDATE
                        size_mismatch = False
                    else:
                        old_size = len(self._datastore)
                        self._set_data_locked(row)
                        expected_datastore = self._datastore
                        new_size = len(self._datastore)
                        expected_size = min(lookback, old_size + 1)
                        size_mismatch = new_size != expected_size
                        update_type = UpdateType.ADD

                        if not size_mismatch:
                            # _set_data tails after each append. Mirror that
                            # window so an evicted id becomes an ADD again.
                            drop_count = old_size + 1 - new_size
                            for _ in range(drop_count):
                                dropped_id = row_ids.popleft()
                                index_to_label.pop(dropped_id, None)

                            if new_size:
                                row_ids.append(idx_key)
                                index_to_label[idx_key] = idx

            if store_changed:
                self._process_rows_slow(chain(((idx, row),), row_iterator))
                return

            if update_type == UpdateType.UPDATE:
                self._patches.append(row)
                self._push_patches()
            else:
                self._push_adds()
                if size_mismatch:
                    # Preserve the original behavior if an unexpected store
                    # shape prevents this lookup map from tracking tail().
                    self._process_rows_slow(row_iterator)
                    return

    def _can_process_as_adds(self, rows, datastore, lookback):
        """Check the narrow, monotonic all-new batch shape without scanning rows repeatedly."""
        if (
            lookback is None
            or lookback <= 0
            or datastore is None
            or "index" not in datastore.columns
            or "index" not in rows.columns
            or not pd.api.types.is_integer_dtype(datastore["index"].dtype)
            or not pd.api.types.is_integer_dtype(datastore.index.dtype)
            or not pd.api.types.is_integer_dtype(rows["index"].dtype)
            or not pd.api.types.is_integer_dtype(rows.index.dtype)
            or not datastore["index"].is_unique
            or not datastore["index"].is_monotonic_increasing
            or not rows["index"].is_unique
            or not rows["index"].is_monotonic_increasing
            or not rows.index.is_unique
            or not rows.index.is_monotonic_increasing
        ):
            return False

        try:
            for label, value in zip(rows.index, rows["index"].array):
                if self._integer_index_key(label) != self._integer_index_key(value):
                    return False

            if len(datastore["index"]) == 0:
                return True
            if len(rows) == 0:
                return False
            first_new = self._integer_index_key(rows["index"].iloc[0])
            last_existing = self._integer_index_key(datastore["index"].iloc[-1])
            return first_new is not None and last_existing is not None and first_new > last_existing
        except (TypeError, ValueError, OverflowError):
            return False

    @staticmethod
    def _integer_index_key(value):
        """Return an exact integer key, or ``None`` for the slow path."""
        if not isinstance(value, numbers.Integral):
            return None
        try:
            return operator.index(value)
        except TypeError:
            return None

    def _process_rows_slow(self, row_iterator):
        """Process unusual index shapes with the original pandas semantics."""
        for idx, row in row_iterator:
            if (
                self._datastore is not None
                and self._datastore.shape[0] > 0
                and "index" in self._datastore.columns
                and idx in self._datastore["index"].values
            ):
                update_type = UpdateType.UPDATE
            else:
                update_type = UpdateType.ADD

            if update_type == UpdateType.UPDATE:
                ds_idx = self._datastore.loc[self._datastore["index"] == idx].index[0]
                self._set_data(row, ds_idx)
                self._patches.append(row)
                self._push_patches()
            else:
                self._set_data(row)
                self._push_adds()

    def _t_thread(self):
        """Data processing thread."""
        while self._running:
            if self._new_data:
                last_idx = self.get_last_idx()
                last_avail_idx = self._app.get_last_idx(self._figid)

                if last_avail_idx - last_idx > (2 * self._lookback):
                    # If new data exceeds lookback length, load from end
                    data = self._app.generate_data(
                        figid=self._figid,
                        back=self._lookback,
                        preserveidx=True,
                        fill_gaps=self._fill_gaps,
                    )
                else:
                    # Otherwise load from last index
                    data = self._app.generate_data(
                        figid=self._figid,
                        start=last_idx,
                        preserveidx=True,
                        fill_gaps=self._fill_gaps,
                    )

                self._new_data = False
                self._process(data)

            time.sleep(self._timeout)

    def _get_data_stream_length_locked(self):
        """Get data stream length when the handler lock is already held."""
        if self._datastore is None:
            return self._lookback
        return min(self._lookback, self._datastore.shape[0])

    def _get_data_stream_length(self):
        """Get the current data stream length under the handler lock.

        Returns:
            int: Data stream length
        """
        with self._lock:
            return self._get_data_stream_length_locked()

    def get_last_idx(self):
        """Get last data index.

        Returns:
            int: Last index, returns -1 if no data
        """
        with self._lock:
            if self._datastore is not None and self._datastore.shape[0] > 0:
                if "index" in self._datastore.columns:
                    return self._datastore["index"].iloc[-1]
            return -1

    def set(self, df):
        """Set new DataFrame and push.

        Args:
            df: New DataFrame
        """
        self._set_data(df)
        self._push_adds()

    def update(self):
        """Notify that new data is available."""
        if self._running:
            self._new_data = True

    def stop(self):
        """Stop data handler."""
        self._running = False

        # Remove pending callbacks
        try:
            if self._cb_patch is not None:
                self._doc.remove_next_tick_callback(self._cb_patch)
        except (ValueError, AttributeError):
            # Callback already gone or doc detached during shutdown; ignore.
            _logger.debug("datahandler:335 ignored ValueError,AttributeError")

        try:
            if self._cb_add is not None:
                self._doc.remove_next_tick_callback(self._cb_add)
        except (ValueError, AttributeError):
            # Callback already gone or doc detached during shutdown; ignore.
            _logger.debug("datahandler:342 ignored ValueError,AttributeError")

        # Wait for thread to finish
        if self._thread.is_alive():
            self._thread.join(timeout=0.5)
            if self._thread.is_alive():
                # Keep the handler/thread reachable so a caller can retry
                # stop; returning here would falsely report a closed client.
                raise RuntimeError("LiveDataHandler worker did not stop before timeout")

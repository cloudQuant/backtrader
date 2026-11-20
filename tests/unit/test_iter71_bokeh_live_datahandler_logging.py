"""Lazy debug logging regressions for the live Bokeh data handler."""

from threading import Lock
from types import SimpleNamespace

import pandas as pd

import backtrader.bokeh.live.datahandler as datahandler


class _RecordingColumnDataSource:
    def stream(self, data, rollover):
        self.streamed = (data, rollover)

    def patch(self, data):
        self.patched = data


def test_stream_and_patch_debug_logs_use_lazy_arguments(monkeypatch):
    log_calls = []
    monkeypatch.setattr(
        datahandler,
        "_logger",
        SimpleNamespace(debug=lambda message, *args: log_calls.append((message, args))),
    )

    source = _RecordingColumnDataSource()
    figurepage = SimpleNamespace(
        cds=source,
        figures=[],
        get_cds_streamdata_from_df=lambda frame: {
            column: frame[column].tolist() for column in frame.columns
        },
        get_cds_patchdata_from_series=lambda _series: ({"close": [(0, 12.0)]}, {}),
    )
    handler = datahandler.LiveDataHandler.__new__(datahandler.LiveDataHandler)
    handler._lock = Lock()
    handler._datastore = pd.DataFrame({"index": [1], "close": [12.0]}, index=[1])
    handler._last_idx = 0
    handler._lookback = 5
    handler._figurepage = figurepage

    handler._cb_push_adds()
    handler._patches = [pd.Series({"close": 12.0}, name=1)]
    handler._cb_push_patches()

    assert log_calls == [
        ("Streaming data to figurepage: %s columns", (2,)),
        ("Patching figurepage: %s fields", (1,)),
    ]
    assert [message % args for message, args in log_calls] == [
        "Streaming data to figurepage: 2 columns",
        "Patching figurepage: 1 fields",
    ]
    assert source.streamed[0] == {"index": [1], "close": [12.0]}
    assert source.patched == {"close": [(0, 12.0)]}
